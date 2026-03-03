#!/usr/bin/env python3
"""
AI Client Auto-Switcher for TimeTracker Mac Agent

Two-tier client detection from window titles:
  Tier 1: Local pattern matching (instant, free) — covers ~80% of cases
    - Pre-compiled regex matchers for client names + aliases
    - Persistent pattern cache (remembers prior AI decisions)
    - Learned rules that strengthen with repeated confirms
    - CPA file-naming convention detection
  Tier 2: OpenAI classification (smart, paid) — ambiguous cases only
    - Debounced + batched to minimize API calls
    - Results cached locally for instant future lookups

Integration points (called from main.py):
  on_window_change()   — every focus change in the tracking loop
  on_dwell_tick()      — every POLL_SECONDS to fire pending switches
  on_manual_switch()   — when user manually picks a client
  update_clients()     — when sync refreshes the client list
  undo_last_switch()   — revert most recent auto-switch
"""

import json, os, re, time, threading, hashlib, logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime, timezone

logger = logging.getLogger("timetracker")


# =====================================================================
# Data Structures
# =====================================================================

@dataclass
class ClientMatch:
    """Result of a client detection attempt."""
    client_id: int
    client_name: str
    confidence: float          # 0.0 - 1.0
    match_method: str          # "exact", "alias", "pattern_cache", "learned_rule",
                               # "learned_partial", "file_convention", "openai"
    matched_token: str = ""
    reasoning: str = ""


@dataclass
class SwitchEvent:
    """Record of an auto-switch for undo support."""
    timestamp: float
    from_client_id: Optional[int]
    from_client_name: Optional[str]
    to_client_id: int
    to_client_name: str
    trigger_title: str
    match: ClientMatch


# =====================================================================
# Configuration
# =====================================================================

DEFAULT_CONFIG = {
    "enabled": True,

    # --- Thresholds ---
    "local_confidence_threshold": 0.80,     # Tier 1 auto-switch minimum
    "openai_confidence_threshold": 0.75,    # Tier 2 auto-switch minimum
    "suggest_threshold": 0.55,              # Below local threshold but worth an AI check

    # --- Timing ---
    "dwell_seconds_before_switch": 8,       # Must dwell N seconds before auto-switch fires
    "cooldown_seconds": 120,                # Don't re-suggest same client within N seconds
    "manual_override_snooze_minutes": 30,   # After manual switch, snooze AI for N minutes

    # --- OpenAI ---
    "openai_model": "gpt-4o-mini",
    "openai_timeout": 8,
    "openai_max_tokens": 600,
    "openai_temperature": 0.1,
    "max_openai_calls_per_hour": 30,
    "ai_debounce_seconds": 5.0,            # Wait N seconds to batch AI calls
    "ai_max_batch": 5,                     # Max titles per OpenAI request

    # --- Behavior ---
    "learn_from_confirms": True,
    "notify_on_switch": True,
    "undo_window_seconds": 120,             # Can undo within N seconds
    "max_switch_history": 50,
    "debug": False,

    # --- Pattern Cache ---
    "pattern_cache_file": os.path.expanduser("~/.timetracker/ai_pattern_cache.json"),
    "max_cache_entries": 2000,
    "cache_ttl_days": 30,

    # --- Skip Rules ---
    "skip_exes": {
        "explorer.exe", "searchapp.exe", "searchui.exe",
        "shellexperiencehost.exe", "startmenuexperiencehost.exe",
        "lockapp.exe", "logonui.exe", "calculator.exe",
        "taskmgr.exe", "snippingtool.exe", "mspaint.exe",
    },
    "skip_title_patterns": [
        r"^$", r"^untitled$", r"^new tab", r"^google$", r"^about:blank$",
    ],
}

LEARNED_RULES_PATH = os.path.expanduser("~/.timetracker/ai_switcher_rules.json")


# =====================================================================
# Pattern Cache — remembers AI decisions to skip repeat calls
# =====================================================================

class PatternCache:
    """
    Persists title→client mappings learned from AI.
    Normalizes titles so "Smith_Co_1040_2024.pdf" and
    "Smith_Co_1120S_2024.pdf" map to the same cache key.
    """

    def __init__(self, path, max_entries=2000, ttl_days=30):
        self.path = path
        self.max_entries = max_entries
        self.ttl_seconds = ttl_days * 86400
        self._data: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self._data = json.load(f)
                logger.info(f"[AI-SWITCH] Pattern cache loaded: {len(self._data)} entries")
            except Exception:
                self._data = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self._data, f, indent=1)
        except Exception as e:
            logger.warning(f"[AI-SWITCH] Cache save failed: {e}")

    @staticmethod
    def _signature(title: str) -> str:
        """Normalize title into a stable hash for cache lookup.

        Replaces dates, long numbers, and file extensions so that
        'Smith_1040_2024.pdf' and 'Smith_1120_2025.pdf' produce
        the same (or similar) signatures.
        """
        t = title.lower().strip()
        # Normalize dates (YYYY-MM-DD, MM/DD/YYYY, etc.)
        t = re.sub(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b', 'DATE', t)
        t = re.sub(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', 'DATE', t)
        # Normalize long numbers (EINs, tracking numbers, etc.)
        t = re.sub(r'\b\d{5,}\b', 'NNNNN', t)
        # Normalize file extensions
        t = re.sub(r'\.\w{2,5}$', '.EXT', t)
        return hashlib.md5(t.encode()).hexdigest()[:16]

    def get(self, title: str) -> Optional[dict]:
        sig = self._signature(title)
        with self._lock:
            entry = self._data.get(sig)
            if not entry:
                return None
            if time.time() - entry.get("ts", 0) > self.ttl_seconds:
                del self._data[sig]
                return None
            return entry

    def put(self, title: str, client_id: int, client_name: str, confidence: float):
        sig = self._signature(title)
        with self._lock:
            self._data[sig] = {
                "client_id": client_id,
                "client_name": client_name,
                "confidence": confidence,
                "ts": time.time(),
                "example_title": title[:120],
            }
            # Evict oldest if over limit
            if len(self._data) > self.max_entries:
                oldest = min(self._data, key=lambda k: self._data[k].get("ts", 0))
                del self._data[oldest]
            self._save()

    def remove_client(self, client_id: int):
        with self._lock:
            to_del = [k for k, v in self._data.items() if v.get("client_id") == client_id]
            for k in to_del:
                del self._data[k]
            if to_del:
                self._save()


# =====================================================================
# Pre-compiled Regex Matchers (fast local matching)
# =====================================================================

def _normalize(s: str) -> str:
    return re.sub(r'\s+', ' ', s.lower().strip())


def _build_client_matchers(clients: list) -> list:
    """Pre-compile regex patterns for each client name + aliases.

    Patterns allow flexible separators so "SmithCo" matches
    "smith_co", "smith-co", "smith.co", etc.
    """
    matchers = []
    for c in clients:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        needles_raw = [name] + [a.strip() for a in (c.get("aliases") or []) if a and a.strip()]
        patterns = []
        for needle in needles_raw:
            if len(needle) < 3:
                continue
            escaped = re.escape(needle.lower())
            # Allow flexible separators between words
            flex = re.sub(r'\\ ', r'[\\s_\\-.]?', escaped)
            pat = re.compile(
                r'(?:^|[\s_\-./\\|:,()\'"<>])' + flex + r'(?:$|[\s_\-./\\|:,()\'"<>])',
                re.IGNORECASE,
            )
            patterns.append(pat)
        if patterns:
            matchers.append({
                "client_id": c["id"],
                "client_name": name,
                "patterns": patterns,
                "needles_raw": needles_raw,
            })
    return matchers


def _regex_match(title: str, file_path: str, matchers: list) -> Optional[ClientMatch]:
    """Fast pre-compiled regex match of client names/aliases against text."""
    search_text = _normalize(f"{title or ''} {file_path or ''}")
    if not search_text.strip():
        return None

    best = None
    for m in matchers:
        for i, pattern in enumerate(m["patterns"]):
            hit = pattern.search(search_text)
            if not hit:
                continue
            needle = m["needles_raw"][min(i, len(m["needles_raw"]) - 1)]
            needle_len = len(needle)

            # Confidence scales with name length (longer = more specific)
            if needle_len >= 8:
                conf = 0.95
            elif needle_len >= 5:
                conf = 0.88
            elif needle_len >= 3:
                conf = 0.70
            else:
                conf = 0.50

            # Boost for primary name match (not alias)
            if i == 0:
                conf = min(1.0, conf + 0.03)
            # Boost if found in file path (more intentional than browser tab)
            if file_path and needle.lower() in (file_path or "").lower():
                conf = min(1.0, conf + 0.05)

            method = "exact" if i == 0 else "alias"
            if best is None or conf > best.confidence:
                best = ClientMatch(
                    client_id=m["client_id"],
                    client_name=m["client_name"],
                    confidence=conf,
                    match_method=method,
                    matched_token=hit.group(0).strip(),
                    reasoning=f"Found '{needle}' in window title/path",
                )
    return best


# =====================================================================
# Learned Rules — strengthen over time with repeated confirms
# =====================================================================

class LearnedRules:
    """Persistent title-pattern → client mappings that improve with use."""

    def __init__(self, path=LEARNED_RULES_PATH):
        self.path = path
        self.rules: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self.rules = json.load(f)
                logger.info(f"[AI-SWITCH] Loaded {len(self.rules)} learned rules")
            except Exception:
                self.rules = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.rules, f, indent=2)
        except Exception as e:
            logger.warning(f"[AI-SWITCH] Save rules failed: {e}")

    def learn(self, title: str, client_id: int, client_name: str, source: str = "ai"):
        """Record title→client mapping. Strengthens on repeat, weakens on conflict."""
        for pat in self._extract_patterns(title):
            key = pat.lower()
            if key in self.rules:
                existing = self.rules[key]
                if existing["client_id"] == client_id:
                    existing["hits"] = existing.get("hits", 0) + 1
                    existing["confidence"] = min(0.99, existing["confidence"] + 0.05)
                else:
                    # Conflicting client — weaken existing rule
                    existing["confidence"] = max(0.3, existing["confidence"] - 0.15)
            else:
                self.rules[key] = {
                    "client_id": client_id,
                    "client_name": client_name,
                    "confidence": 0.80 if source == "user" else 0.70,
                    "hits": 1,
                    "source": source,
                    "created": datetime.now(timezone.utc).isoformat(),
                }
        self._save()

    def match(self, title: str, current_client_id: int = None) -> Optional[ClientMatch]:
        """Check learned rules for a match."""
        best = None
        best_conf = 0.0

        for pat in self._extract_patterns(title):
            key = pat.lower()

            # Exact rule match
            if key in self.rules:
                rule = self.rules[key]
                if rule["client_id"] != current_client_id and rule["confidence"] > best_conf:
                    best = ClientMatch(
                        client_id=rule["client_id"],
                        client_name=rule["client_name"],
                        confidence=rule["confidence"],
                        match_method="learned_rule",
                        matched_token=key[:80],
                        reasoning=f"Learned from prior {rule.get('source', '?')} match",
                    )
                    best_conf = rule["confidence"]

            # Partial match (substring overlap)
            for rk, rule in self.rules.items():
                if rule["client_id"] == current_client_id:
                    continue
                if key in rk or rk in key:
                    adj = rule["confidence"] * 0.85
                    if adj > best_conf:
                        best = ClientMatch(
                            client_id=rule["client_id"],
                            client_name=rule["client_name"],
                            confidence=adj,
                            match_method="learned_partial",
                            matched_token=rk[:80],
                            reasoning="Partial match against learned pattern",
                        )
                        best_conf = adj
        return best

    @staticmethod
    def _extract_patterns(title: str) -> List[str]:
        """Extract reusable patterns from a window title."""
        patterns = []
        # Strip app suffixes: "Smith_1040.xlsx - Microsoft Excel" → "Smith_1040.xlsx"
        cleaned = re.sub(
            r'\s*[-\u2013\u2014|]\s*(Google Chrome|Chrome|Brave|Firefox|'
            r'Microsoft Edge|Microsoft Excel|Microsoft Word|Microsoft PowerPoint|'
            r'Adobe Acrobat|Notepad\+?\+?|Visual Studio Code|Code|'
            r'Windows PowerShell|Command Prompt|Terminal|File Explorer).*$',
            '', title, flags=re.IGNORECASE
        ).strip()
        if cleaned:
            patterns.append(cleaned.lower())
        for sep in [' - ', ' | ', ' \u2014 ', ' \u2013 ', '_']:
            if sep in cleaned:
                first = cleaned.split(sep)[0].strip()
                if len(first) >= 3:
                    patterns.append(first.lower())
                break
        return patterns


# =====================================================================
# CPA File Convention Matcher
# =====================================================================

def _cpa_file_match(title: str, clients: list, current_client_id: int = None) -> Optional[ClientMatch]:
    """Detect CPA file naming patterns like 'ClientName_1040_2024.pdf'."""
    m = re.match(
        r'^([A-Za-z][A-Za-z0-9\s&.,]+?)[\s_-]+'
        r'(?:1040|1120|1065|990|W-?2|1099|K-?1|tax|return|financials?|'
        r'audit|review|engagement|invoice|proposal|letter)',
        title, re.IGNORECASE
    )
    if not m:
        return None

    candidate = m.group(1).strip()
    if len(candidate) < 3:
        return None

    for client in clients:
        cname = (client.get("name") or "").strip()
        cid = client.get("id")
        if cid == current_client_id:
            continue
        if cname.lower() in candidate.lower() or candidate.lower() in cname.lower():
            return ClientMatch(
                client_id=cid,
                client_name=cname,
                confidence=0.82,
                match_method="file_convention",
                matched_token=candidate,
                reasoning=f"CPA file pattern: '{candidate}' matches client '{cname}'",
            )
    return None


# =====================================================================
# OpenAI Batched Classifier (Tier 2)
# =====================================================================

def _build_ai_prompt(titles: list, clients: list) -> tuple:
    """Build system + user prompt for batched OpenAI classification."""
    client_lines = []
    for c in clients[:50]:
        aliases = c.get("aliases") or []
        alias_str = f" (aliases: {', '.join(aliases[:3])})" if aliases else ""
        client_lines.append(f"  ID {c['id']}: {c.get('name', '')}{alias_str}")

    system = f"""You are a client identification engine for a CPA/accounting firm's time tracker.

TASK: Given window titles / file names, determine which CLIENT the user is working on.

KNOWN CLIENTS:
{chr(10).join(client_lines)}

RULES:
1. CPA firms name files like: "ClientName_FormType_Year", "ClientName - 1040 - 2024"
2. Look for client names, abbreviations, or aliases in the title or path.
3. Clear match → confidence 0.85-0.95. Partial/ambiguous → 0.50-0.75.
4. If NO client can be identified → return null. NEVER guess.
5. Generic windows (Chrome, Finder, Slack with no client info) → null.

Return ONLY a JSON array, one object per input:
[{{"id":"...","client_id":<int|null>,"client_name":"<str|null>","confidence":<float>,"reasoning":"<brief>"}}]"""

    items = []
    for t in titles:
        item = {"id": t["id"], "title": t["title"]}
        if t.get("file_path"):
            item["file_path"] = t["file_path"]
        if t.get("app"):
            item["app"] = t["app"]
        items.append(item)

    user = f"Identify the client for each:\n{json.dumps(items, indent=1)}"
    return system, user


def _call_openai_batch(titles: list, clients: list, api_key: str, cfg: dict) -> List[Optional[ClientMatch]]:
    """Call OpenAI with a batch of titles. Returns list of ClientMatch or None per title."""
    if not api_key or not titles:
        return [None] * len(titles)

    system, user = _build_ai_prompt(titles, clients)
    try:
        import urllib.request
        payload = {
            "model": cfg.get("openai_model", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": cfg.get("openai_temperature", 0.1),
            "max_tokens": cfg.get("openai_max_tokens", 600),
        }
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")

        timeout = cfg.get("openai_timeout", 8)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        raw = (data["choices"][0]["message"]["content"] or "").strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        results = json.loads(raw)
        if not isinstance(results, list):
            raise ValueError("Expected JSON array from OpenAI")

        result_map = {str(r.get("id", "")): r for r in results}
        matches = []
        for t in titles:
            r = result_map.get(t["id"])
            if not r or not r.get("client_id"):
                matches.append(None)
                continue
            matches.append(ClientMatch(
                client_id=int(r["client_id"]),
                client_name=r.get("client_name") or "",
                confidence=float(r.get("confidence", 0.0)),
                match_method="openai",
                matched_token=t["title"][:80],
                reasoning=r.get("reasoning", ""),
            ))
        return matches

    except Exception as e:
        logger.error(f"[AI-SWITCH] OpenAI batch error: {e}")
        return [None] * len(titles)


# =====================================================================
# Orchestrator: AIClientSwitcher
# =====================================================================

class AIClientSwitcher:
    """
    Orchestrates local + AI client detection and auto-switching.

    Constructor accepts the same objects main.py already has:
      gui_menu_bar, notif_manager, sync — used directly, no adapters needed.

    Called from main.py:
      on_window_change()   — every focus change in the tracking loop
      on_dwell_tick()      — every POLL_SECONDS to check pending switches
      on_manual_switch()   — when user manually picks a client
      update_clients()     — when sync refreshes client list
      undo_last_switch()   — revert most recent auto-switch
    """

    def __init__(self, config=None, api_base="", api_key="", openai_api_key="",
                 set_current_client_fn=None, gui_menu_bar=None,
                 notif_manager=None, sync=None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.api_base = api_base
        self.api_key = api_key
        self.openai_api_key = openai_api_key
        self.set_current_client_fn = set_current_client_fn
        self.gui_menu_bar = gui_menu_bar
        self.notif_manager = notif_manager
        self.sync = sync

        # Client data
        clients = (sync.clients if sync else None) or []
        self._clients = clients
        self._client_map = {c["id"]: c for c in clients}

        # Tier 1: Local matchers
        self._matchers = _build_client_matchers(clients)
        self._learned = LearnedRules()
        self._cache = PatternCache(
            self.config["pattern_cache_file"],
            self.config["max_cache_entries"],
            self.config["cache_ttl_days"],
        )

        # Tier 2: OpenAI rate limiter
        self._ai_call_count = 0
        self._ai_window_start = time.time()

        # AI batch queue (debounced)
        self._ai_queue: List[dict] = []
        self._ai_lock = threading.Lock()
        self._ai_timer: Optional[threading.Timer] = None

        # Switch state
        self._current_client_id: Optional[int] = None
        self._current_client_name: Optional[str] = None
        self._pending_switch: Optional[dict] = None    # {client_id, client_name, confidence, first_seen, match}
        self._cooldowns: Dict[int, float] = {}         # client_id → expiry timestamp
        self._manual_override_until: float = 0.0
        self._switch_history: List[SwitchEvent] = []
        self._lock = threading.Lock()
        self._last_title: str = ""

        # Skip rules
        self._skip_exes = set(self.config.get("skip_exes", set()))
        self._skip_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in self.config.get("skip_title_patterns", [])
        ]

        # Stats
        self.stats = {"regex": 0, "cache": 0, "learned": 0, "file_conv": 0,
                      "openai": 0, "switches": 0, "suppressed": 0}

        logger.info(
            f"[AI-SWITCH] Ready: {len(clients)} clients, "
            f"dwell={self.config['dwell_seconds_before_switch']}s, "
            f"openai={'yes' if openai_api_key else 'no'}"
        )

    # =================================================================
    # Public API (called from main.py)
    # =================================================================

    def update_clients(self, clients: list):
        """Called when sync refreshes the client list."""
        self._clients = clients or []
        self._client_map = {c["id"]: c for c in self._clients}
        self._matchers = _build_client_matchers(self._clients)
        self._learned.update_clients_ref(self._clients) if hasattr(self._learned, 'update_clients_ref') else None
        logger.info(f"[AI-SWITCH] Updated: {len(self._clients)} clients")

    def set_current_client(self, client_id: int, client_name: str):
        """Sync current client state (e.g. on startup)."""
        self._current_client_id = client_id
        self._current_client_name = client_name

    def on_manual_switch(self, client_id: int, client_name: str):
        """User manually switched — snooze AI to respect their choice."""
        with self._lock:
            self._current_client_id = client_id
            self._current_client_name = client_name
            snooze_min = self.config["manual_override_snooze_minutes"]
            self._manual_override_until = time.time() + snooze_min * 60
            self._pending_switch = None
            logger.info(f"[AI-SWITCH] Manual override: {client_name} (snoozed {snooze_min}min)")

    def on_window_change(self, app_name: str, exe_name: str, title: str,
                         url: str = None, file_path: str = None, in_meeting: bool = False):
        """Called from tracking loop on every focus change."""
        if not self.config["enabled"] or not title or title == self._last_title:
            return
        self._last_title = title
        if in_meeting or time.time() < self._manual_override_until:
            return
        if self._should_skip(title, exe_name):
            self._clear_pending()
            return
        threading.Thread(
            target=self._detect,
            args=(app_name, exe_name, title, url, file_path),
            daemon=True,
        ).start()

    def on_dwell_tick(self):
        """Called every POLL_SECONDS to check if pending switch met dwell threshold."""
        if not self._pending_switch:
            return
        with self._lock:
            p = self._pending_switch
            if p and (time.time() - p["first_seen"]) >= self.config["dwell_seconds_before_switch"]:
                self._execute_switch(p)
                self._pending_switch = None

    def undo_last_switch(self) -> bool:
        """Revert the most recent auto-switch (within undo window)."""
        if not self._switch_history:
            return False
        last = self._switch_history[-1]
        if last.from_client_id is None:
            return False
        if time.time() - last.timestamp > self.config["undo_window_seconds"]:
            return False

        logger.info(f"[AI-SWITCH] UNDO: {last.to_client_name} → {last.from_client_name}")
        self._do_backend_switch(last.from_client_id, last.from_client_name)
        self._notify_switch(last.from_client_name, last.to_client_name, is_undo=True)
        return True

    def get_last_switch(self) -> Optional[SwitchEvent]:
        return self._switch_history[-1] if self._switch_history else None

    # =================================================================
    # Detection Pipeline
    # =================================================================

    def _detect(self, app_name: str, exe_name: str, title: str,
                url: str, file_path: str):
        """Run the full detection pipeline (background thread)."""
        try:
            search = f"{title} {file_path}" if file_path else title
            cur_id = self._current_client_id

            # --- Tier 1a: Pattern cache (instant, from prior AI decisions) ---
            cached = self._cache.get(title)
            if cached and cached.get("client_id"):
                if cached["client_id"] != cur_id:
                    match = ClientMatch(
                        client_id=cached["client_id"],
                        client_name=cached["client_name"],
                        confidence=cached["confidence"],
                        match_method="pattern_cache",
                        matched_token=title[:80],
                        reasoning="Cached from prior AI decision",
                    )
                    if match.confidence >= self.config["local_confidence_threshold"]:
                        self.stats["cache"] += 1
                        self._queue_switch(match)
                        return

            # --- Tier 1b: Pre-compiled regex match (fast, ~0ms) ---
            regex_hit = _regex_match(title, file_path, self._matchers)
            if regex_hit and regex_hit.client_id != cur_id:
                if regex_hit.confidence >= self.config["local_confidence_threshold"]:
                    self.stats["regex"] += 1
                    self._queue_switch(regex_hit)
                    return

            # --- Tier 1c: Learned rules ---
            learned_hit = self._learned.match(search, cur_id)
            if learned_hit and learned_hit.confidence >= 0.65:
                if learned_hit.client_id != cur_id:
                    self.stats["learned"] += 1
                    self._queue_switch(learned_hit)
                    return

            # --- Tier 1d: CPA file naming conventions ---
            file_hit = _cpa_file_match(title, self._clients, cur_id)
            if file_hit:
                self.stats["file_conv"] += 1
                self._queue_switch(file_hit)
                return

            # --- Tier 2: OpenAI (only if all local methods failed) ---
            if self.openai_api_key and self.config["enabled"]:
                # Check if we got a weak local match worth verifying via AI
                if (regex_hit and regex_hit.confidence >= self.config["suggest_threshold"]) or not regex_hit:
                    self._enqueue_for_ai(title, file_path, app_name)
                    return

            # No match at all — cancel any pending switch
            with self._lock:
                self._pending_switch = None

        except Exception as e:
            logger.error(f"[AI-SWITCH] detect error: {e}")

    def _queue_switch(self, match: ClientMatch):
        """Queue a match for dwell-based switching."""
        cid = match.client_id
        with self._lock:
            if cid == self._current_client_id:
                return
            if time.time() < self._cooldowns.get(cid, 0):
                self.stats["suppressed"] += 1
                return
            if self._pending_switch and self._pending_switch["client_id"] == cid:
                return  # Already pending
            self._pending_switch = {
                "client_id": match.client_id,
                "client_name": match.client_name,
                "confidence": match.confidence,
                "method": match.match_method,
                "reasoning": match.reasoning,
                "first_seen": time.time(),
                "match": match,
            }
            if self.config.get("debug"):
                logger.info(f"[AI-SWITCH] Pending: {match.client_name} "
                            f"(conf={match.confidence:.2f}, via={match.match_method})")

    # =================================================================
    # AI Batch Queue (debounced)
    # =================================================================

    def _enqueue_for_ai(self, title: str, file_path: str, app_name: str):
        """Add title to AI batch queue. Fires after debounce or when batch is full."""
        if not self.openai_api_key:
            return

        # Rate limit check
        now = time.time()
        if now - self._ai_window_start > 3600:
            self._ai_call_count = 0
            self._ai_window_start = now
        if self._ai_call_count >= self.config["max_openai_calls_per_hour"]:
            return

        item = {
            "id": hashlib.md5(f"{title}:{now}".encode()).hexdigest()[:12],
            "title": title,
            "file_path": file_path,
            "app": app_name,
        }

        with self._ai_lock:
            self._ai_queue.append(item)
            if self._ai_timer:
                self._ai_timer.cancel()

            if len(self._ai_queue) >= self.config["ai_max_batch"]:
                self._fire_ai_batch()
            else:
                self._ai_timer = threading.Timer(
                    self.config["ai_debounce_seconds"],
                    self._fire_ai_batch,
                )
                self._ai_timer.daemon = True
                self._ai_timer.start()

    def _fire_ai_batch(self):
        """Send queued titles to OpenAI in one batched call."""
        with self._ai_lock:
            if not self._ai_queue:
                return
            batch = self._ai_queue[:self.config["ai_max_batch"]]
            self._ai_queue = self._ai_queue[self.config["ai_max_batch"]:]
            if self._ai_timer:
                self._ai_timer.cancel()
                self._ai_timer = None

        def _run():
            try:
                logger.info(f"[AI-SWITCH] OpenAI batch: {len(batch)} titles")
                self._ai_call_count += 1
                results = _call_openai_batch(batch, self._clients, self.openai_api_key, self.config)
                cur_id = self._current_client_id

                for item, match in zip(batch, results):
                    if not match or match.client_id not in self._client_map:
                        continue

                    # Cache the AI result for instant future lookups
                    self._cache.put(item["title"], match.client_id, match.client_name, match.confidence)

                    # Learn the pattern for even faster future matching
                    if self.config["learn_from_confirms"]:
                        self._learned.learn(item["title"], match.client_id, match.client_name, "ai")

                    # Queue for switch if above threshold
                    if match.confidence >= self.config["openai_confidence_threshold"]:
                        if match.client_id != cur_id:
                            self.stats["openai"] += 1
                            self._queue_switch(match)
                            cur_id = match.client_id  # Update for next item in batch

            except Exception as e:
                logger.error(f"[AI-SWITCH] batch error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    # =================================================================
    # Switch Execution
    # =================================================================

    def _execute_switch(self, data: dict):
        """Fire the actual client switch after dwell threshold is met."""
        cid = data["client_id"]
        cname = data["client_name"]
        conf = data["confidence"]
        method = data.get("method", "?")
        match = data.get("match")

        try:
            old_id = self._current_client_id
            old_name = self._current_client_name or "None"

            # Backend switch
            # New:
            if self.set_current_client_fn:
                result = self.set_current_client_fn(cid, cname)

            # Update internal state
            self._current_client_id = cid
            self._current_client_name = cname
            self._cooldowns[cid] = time.time() + self.config["cooldown_seconds"]

            # Update GUI
            if self.gui_menu_bar and hasattr(self.gui_menu_bar, "state"):
                self.gui_menu_bar.state.set_client(cid, cname)
                if hasattr(self.gui_menu_bar, "app") and self.gui_menu_bar.app:
                    self.gui_menu_bar.app.title = f"\u23f1 {cname}"

            # Update notification manager
            if self.notif_manager and hasattr(self.notif_manager, "set_current_client"):
                self.notif_manager.set_current_client(cid, cname)

            # Record history for undo
            self._switch_history.append(SwitchEvent(
                timestamp=time.time(),
                from_client_id=old_id,
                from_client_name=old_name,
                to_client_id=cid,
                to_client_name=cname,
                trigger_title=data.get("reasoning", "")[:200],
                match=match or ClientMatch(
                    client_id=cid, client_name=cname,
                    confidence=conf, match_method=method,
                ),
            ))
            max_hist = self.config.get("max_switch_history", 50)
            if len(self._switch_history) > max_hist:
                self._switch_history = self._switch_history[-max_hist:]

            # Notification toast
            self._notify_switch(cname, old_name)

            self.stats["switches"] += 1
            logger.info(f"[AI-SWITCH] \u2705 {old_name} \u2192 {cname} "
                        f"(conf={conf:.0%}, {method})")

        except Exception as e:
            logger.error(f"[AI-SWITCH] switch error: {e}")

    def _do_backend_switch(self, client_id: int, client_name: str):
        """Execute backend + GUI switch (used by both auto-switch and undo)."""
        if self.set_current_client_fn:
            self.set_current_client_fn(client_id)
        self._current_client_id = client_id
        self._current_client_name = client_name
        if self.gui_menu_bar and hasattr(self.gui_menu_bar, "state"):
            self.gui_menu_bar.state.set_client(client_id, client_name)
            if hasattr(self.gui_menu_bar, "app") and self.gui_menu_bar.app:
                self.gui_menu_bar.app.title = f"\u23f1 {client_name}" if client_name else "\u23f1 None"
        if self.notif_manager and hasattr(self.notif_manager, "set_current_client"):
            self.notif_manager.set_current_client(client_id, client_name)

    # =================================================================
    # Notifications
    # =================================================================

    def _notify_switch(self, new_name: str, old_name: str,
                       conf: float = 0, method: str = "", is_undo: bool = False):
        """Show Windows toast notification for auto-switch or undo."""
        if not self.config["notify_on_switch"]:
            return
        if is_undo:
            title = "\u23f1 Client Reverted"
            body = f"Back to {new_name}"
            subtitle = "Undo successful"
        else:
            title = "\u23f1 Client Switched"
            body = f"{old_name} \u2192 {new_name}"
            subtitle = f"Auto-detected ({int(conf * 100)}% confidence)" if conf else "Auto-detected"

        full_body = f"{subtitle}\n{body}" if subtitle else body

        # Method 1: win10toast (pip install win10toast)
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(title, full_body, duration=5, threaded=True)
            return
        except ImportError:
            pass

        # Method 2: PowerShell Windows.UI.Notifications
        try:
            import subprocess
            ps_script = (
                '[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, '
                'ContentType = WindowsRuntime] > $null; '
                '$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(0); '
                '$text = $template.GetElementsByTagName("text"); '
                f'$text[0].AppendChild($template.CreateTextNode("{title}")) > $null; '
                f'$text[1].AppendChild($template.CreateTextNode("{full_body}")) > $null; '
                '$toast = [Windows.UI.Notifications.ToastNotification]::new($template); '
                '[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("TimeTracker").Show($toast)'
            )
            subprocess.run(["powershell", "-Command", ps_script],
                           timeout=5, capture_output=True)
            return
        except Exception:
            pass

        # Method 3: Tkinter popup fallback
        try:
            def _show():
                from tkinter import Tk, Label
                root = Tk()
                root.title(title)
                root.attributes("-topmost", True)
                root.geometry("350x80+{}+{}".format(
                    root.winfo_screenwidth() - 370,
                    root.winfo_screenheight() - 120))
                root.overrideredirect(True)
                root.configure(bg="#2d2d2d")
                Label(root, text=title, fg="white", bg="#2d2d2d",
                      font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
                Label(root, text=full_body, fg="#cccccc", bg="#2d2d2d",
                      font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=10)
                root.after(4000, root.destroy)
                root.mainloop()
            threading.Thread(target=_show, daemon=True).start()
        except Exception:
            pass

    # =================================================================
    # Helpers
    # =================================================================

    def _should_skip(self, title: str, exe_name: str) -> bool:
        """Return True if this window should be ignored entirely."""
        if exe_name and exe_name.lower() in self._skip_exes:
            return True
        t = title.lower().strip()
        for pat in self._skip_patterns:
            if pat.search(t):
                return True
        if t in {"google chrome", "microsoft edge", "brave browser", "firefox",
                 "microsoft outlook", "mail", "slack", "file explorer",
                 "microsoft teams", "zoom", "windows powershell",
                 "command prompt", "terminal", "task manager"}:
            return True
        return False

    def _clear_pending(self):
        with self._lock:
            self._pending_switch = None