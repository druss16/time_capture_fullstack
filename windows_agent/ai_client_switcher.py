#!/usr/bin/env python3
"""
AI Client Auto-Switcher for TimeTracker Windows Agent

Two-tier client detection from window titles:
  Tier 0: Org-admin ClientPattern rules (highest priority)
  Tier 1: Local pattern matching (instant, free) — covers ~80% of cases
    - Pre-compiled regex matchers for client names + aliases
    - Persistent pattern cache (remembers prior AI decisions)
    - Learned rules that strengthen with repeated confirms
    - CPA file-naming convention detection
    - Partial-word matching (scales with sensitivity)
  Tier 2: Backend AI classification (smart, server-side) — ambiguous cases only

CHANGES FROM PREVIOUS VERSION:
  - GENERIC_TAX_DIALOGS and GENERIC_TAX_EXES imported from tax_software_constants.py
    (agent-local file, no Django dependency — mirrors tracker/utils/tax_software.py)
  - _should_skip() uses the shared set so both agent + backend stay in sync
  - Tax software bare exe names (utw25.exe etc.) added to skip list
  - No logic changes to switching pipeline itself

SYNC NOTE:
  tax_software_constants.py (this folder) mirrors tracker/utils/tax_software.py
  on the backend. Update BOTH when adding new suppress entries.
"""

import json, os, re, time, threading, hashlib, logging, urllib.request, urllib.error
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from datetime import datetime, timezone

logger = logging.getLogger("timetracker")

# ---------------------------------------------------------------------------
# Import suppress lists from agent-local constants file.
# No Django dependency — safe to import in standalone PyInstaller build.
# ---------------------------------------------------------------------------
from tax_software_constants import (
    GENERIC_TAX_DIALOGS,
    GENERIC_TAX_EXES,
    TAX_SOFTWARE_RETURN_PATTERN,
    TAX_SOFTWARE_TAXWISE_PATTERN,
    INTERNAL_TAX_CLIENT_NAME,
)

# =====================================================================
# Data Structures
# =====================================================================

@dataclass
class ClientMatch:
    client_id: int
    client_name: str
    confidence: float
    match_method: str
    matched_token: str = ""
    reasoning: str = ""


@dataclass
class SwitchEvent:
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
    "ai_sensitivity": 50,

    # Computed by _apply_sensitivity() — do not hand-edit
    "local_confidence_threshold": 0.80,
    "openai_confidence_threshold": 0.75,
    "suggest_threshold": 0.55,
    "partial_name_matching": False,
    "partial_name_min_word_len": 5,

    # Timing
    "dwell_seconds_before_switch": 0,
    "cooldown_seconds": 0,
    "manual_override_snooze_minutes": 0,

    # Backend AI
    "ai_timeout": 10,
    "max_ai_calls_per_hour": 60,
    "ai_debounce_seconds": 2.0,
    "ai_max_batch": 5,

    # Behavior
    "learn_from_confirms": True,
    "notify_on_switch": True,
    "undo_window_seconds": 120,
    "max_switch_history": 50,
    "debug": False,

    # Pattern Cache
    "pattern_cache_file": os.path.expanduser("~/.timetracker/ai_pattern_cache.json"),
    "max_cache_entries": 2000,
    "cache_ttl_days": 30,

    # Skip Rules
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

_STOP_WORDS = {
    "and", "the", "for", "inc", "llc", "ltd", "corp", "co", "group",
    "tax", "firm", "cpas", "cpa", "associates", "partners", "services",
}

_GENERIC_WORD_BLOCKLIST = {
    "professional", "services", "accounting", "management",
    "associates", "solutions", "group", "local", "national",
    "international", "community", "united", "general", "advanced",
}


# =====================================================================
# Sensitivity → Threshold Mapping (unchanged)
# =====================================================================

def _sensitivity_to_thresholds(sensitivity: int) -> dict:
    s = max(0, min(100, int(sensitivity))) / 100.0
    local_thresh   = round(0.90 - (s * 0.40), 3)
    openai_thresh  = round(0.85 - (s * 0.40), 3)
    suggest_thresh = round(0.70 - (s * 0.35), 3)
    partial_matching = s >= 0.40
    if s < 0.40:
        min_word_len = 99
    elif s < 0.70:
        min_word_len = 6
    elif s < 0.90:
        min_word_len = 4
    else:
        min_word_len = 3
    return {
        "local_confidence_threshold":  local_thresh,
        "openai_confidence_threshold": openai_thresh,
        "suggest_threshold":           suggest_thresh,
        "partial_name_matching":       partial_matching,
        "partial_name_min_word_len":   min_word_len,
    }


def _partial_word_confidence(word_len: int, sensitivity: int) -> float:
    s = max(0, min(100, sensitivity)) / 100.0
    if word_len >= 10:   base = 0.72
    elif word_len >= 7:  base = 0.65
    elif word_len >= 5:  base = 0.58
    else:                base = 0.50
    return round(min(0.80, base + s * 0.10), 3)


# =====================================================================
# Pattern Cache (unchanged)
# =====================================================================

class PatternCache:
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
        t = title.lower().strip()
        t = re.sub(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b', 'DATE', t)
        t = re.sub(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', 'DATE', t)
        t = re.sub(r'\b\d{5,}\b', 'NNNNN', t)
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
# Pre-compiled Regex Matchers (unchanged)
# =====================================================================

_BOUNDARY = r'[\s_\-./\\|:,()\'"<>*\u2013\u2014]'


def _normalize(s: str) -> str:
    s = re.sub(r'^\*+', '', s)
    return re.sub(r'\s+', ' ', s.lower().strip())


def _build_client_matchers(clients: list, sensitivity: int = 50) -> list:
    thresholds = _sensitivity_to_thresholds(sensitivity)
    partial_enabled = thresholds["partial_name_matching"]
    min_word_len    = thresholds["partial_name_min_word_len"]

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
            flex = re.sub(r'[\\\s_\-\.&]+', r'[\\s_\\-.&]*', escaped)
            pat = re.compile(
                r'(?:^|' + _BOUNDARY + r')' + flex + r'(?:$|' + _BOUNDARY + r')',
                re.IGNORECASE,
            )
            patterns.append((pat, needle, False))

        if partial_enabled:
            words = re.split(r'[\s&,./\\]+', name)
            for word in words:
                word = word.strip(" .,&")
                if len(word) < min_word_len:
                    continue
                if word.lower() in _STOP_WORDS:
                    continue
                already_covered = any(word.lower() == n.lower() for n in needles_raw)
                if already_covered:
                    continue
                escaped = re.escape(word.lower())
                pat = re.compile(
                    r'(?:^|' + _BOUNDARY + r')' + escaped + r'(?:$|' + _BOUNDARY + r')',
                    re.IGNORECASE,
                )
                patterns.append((pat, word, True))

        if patterns:
            matchers.append({
                "client_id": c["id"],
                "client_name": name,
                "patterns": patterns,
                "needles_raw": needles_raw,
            })
    return matchers


def _regex_match(title: str, file_path: str, matchers: list,
                 sensitivity: int = 50) -> Optional[ClientMatch]:
    search_text = _normalize(f"{title or ''} {file_path or ''}")
    if not search_text.strip():
        return None

    best = None
    for m in matchers:
        for i, (pattern, needle, is_partial) in enumerate(m["patterns"]):
            hit = pattern.search(search_text)
            if not hit:
                continue

            needle_len = len(needle)

            if is_partial:
                if needle.lower() in _GENERIC_WORD_BLOCKLIST:
                    continue
                conf   = _partial_word_confidence(needle_len, sensitivity)
                method = "partial_word"
            else:
                if needle_len >= 8:   conf = 0.95
                elif needle_len >= 5: conf = 0.88
                elif needle_len >= 3: conf = 0.70
                else:                 conf = 0.50
                is_primary = (needle == m["needles_raw"][0])
                if is_primary:
                    conf = min(1.0, conf + 0.03)
                method = "exact" if is_primary else "alias"

            if file_path and needle.lower() in (file_path or "").lower():
                conf = min(1.0, conf + 0.05)

            if best is None or conf > best.confidence:
                best = ClientMatch(
                    client_id=m["client_id"],
                    client_name=m["client_name"],
                    confidence=conf,
                    match_method=method,
                    matched_token=hit.group(0).strip(),
                    reasoning=(
                        f"Partial word '{needle}' matched in title"
                        if is_partial
                        else f"Found '{needle}' in window title/path"
                    ),
                )
    return best


# =====================================================================
# Learned Rules (unchanged)
# =====================================================================

class LearnedRules:

    def __init__(self, path=LEARNED_RULES_PATH):
        self.path  = path
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
        for pat in self._extract_patterns(title):
            key = pat.lower()
            if key in self.rules:
                existing = self.rules[key]
                if existing["client_id"] == client_id:
                    existing["hits"] = existing.get("hits", 0) + 1
                    existing["confidence"] = min(0.99, existing["confidence"] + 0.05)
                else:
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
        best = None
        best_conf = 0.0
        for pat in self._extract_patterns(title):
            key = pat.lower()
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
        patterns = []
        cleaned = re.sub(
            r'\s*[-\u2013\u2014|]\s*(Google Chrome|Chrome|Brave|Firefox|'
            r'Microsoft Edge|Microsoft Excel|Microsoft Word|Microsoft PowerPoint|'
            r'Adobe Acrobat|Notepad\+?\+?|Visual Studio Code|Code|'
            r'Windows PowerShell|Command Prompt|Terminal|File Explorer).*$',
            '', title, flags=re.IGNORECASE,
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
# CPA File Convention Matcher (unchanged)
# =====================================================================

def _cpa_file_match(title: str, clients: list, current_client_id: int = None) -> Optional[ClientMatch]:
    m = re.match(
        r'^([A-Za-z][A-Za-z0-9\s&.,]+?)[\s_-]+'
        r'(?:1040|1120|1065|990|W-?2|1099|K-?1|tax|return|financials?|'
        r'audit|review|engagement|invoice|proposal|letter)',
        title, re.IGNORECASE,
    )
    if not m:
        return None
    candidate = m.group(1).strip()
    if len(candidate) < 3:
        return None
    for client in clients:
        client_name = (client.get("name") or "").strip()
        client_id   = client.get("id")
        if client_id == current_client_id:
            continue
        if client_name.lower() in candidate.lower() or candidate.lower() in client_name.lower():
            return ClientMatch(
                client_id=client_id,
                client_name=client_name,
                confidence=0.82,
                match_method="file_convention",
                matched_token=candidate,
                reasoning=f"CPA file pattern: '{candidate}' matches client '{client_name}'",
            )
    return None


# =====================================================================
# Backend AI Classifier (unchanged)
# =====================================================================

def _call_backend_classify(titles: list, api_base: str, api_key: str,
                           timeout: int = 10) -> List[Optional[ClientMatch]]:
    if not api_base or not api_key or not titles:
        return [None] * len(titles)

    url = f"{api_base.rstrip('/')}/ai/classify-batch/"
    payload = {
        "titles": [
            {
                "title":     t.get("title", ""),
                "app_name":  t.get("app", ""),
                "file_path": t.get("file_path", ""),
            }
            for t in titles
        ]
    }

    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
        )
        req.add_header("Authorization", f"DeviceKey {api_key}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        results_raw = data.get("results") or []
        matches = []
        for i, r in enumerate(results_raw):
            if not r or not r.get("client_id"):
                matches.append(None)
                continue
            matches.append(ClientMatch(
                client_id=int(r["client_id"]),
                client_name=r.get("client_name") or "",
                confidence=float(r.get("confidence", 0.0)),
                match_method="backend_ai",
                matched_token=titles[i]["title"][:80] if i < len(titles) else "",
                reasoning=r.get("reasoning", ""),
            ))
        while len(matches) < len(titles):
            matches.append(None)
        return matches

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")[:200]
        except Exception:
            pass
        if e.code == 403:
            logger.info(f"[AI-SWITCH] Backend AI not available (plan restriction): {body}")
        elif e.code == 429:
            logger.warning(f"[AI-SWITCH] Backend AI rate limited: {body}")
        elif e.code == 404:
            logger.debug(f"[AI-SWITCH] Backend AI endpoint not deployed yet")
        else:
            logger.error(f"[AI-SWITCH] Backend classify HTTP {e.code}: {body}")
        return [None] * len(titles)

    except Exception as e:
        logger.error(f"[AI-SWITCH] Backend classify error: {e}")
        return [None] * len(titles)


# =====================================================================
# Orchestrator: AIClientSwitcher
# =====================================================================

class AIClientSwitcher:

    def __init__(self, config=None, api_base="", api_key="", openai_api_key="",
                 set_current_client_fn=None, gui_menu_bar=None,
                 notif_manager=None, sync=None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.api_base          = api_base
        self.api_key           = api_key
        self.openai_api_key    = openai_api_key
        self.set_current_client_fn = set_current_client_fn
        self.gui_menu_bar      = gui_menu_bar
        self.notif_manager     = notif_manager
        self.sync              = sync

        self._apply_sensitivity()

        clients           = (sync.clients if sync else None) or []
        self._clients     = clients
        self._client_map  = {c["id"]: c for c in clients}

        sensitivity       = self.config["ai_sensitivity"]
        self._matchers    = _build_client_matchers(clients, sensitivity)
        self._client_patterns: List[Dict] = []
        self._learned     = LearnedRules()
        self._cache       = PatternCache(
            self.config["pattern_cache_file"],
            self.config["max_cache_entries"],
            self.config["cache_ttl_days"],
        )

        # ── Auto-clear stale pattern cache on version upgrade ──────────────
        # ── Auto-clear stale pattern cache on version upgrade ──────────────
        try:
            from version import APP_VERSION
        except Exception:
            APP_VERSION = "unknown"
        
        logger.info(f"[AI-SWITCH] Version: {APP_VERSION}")  # ← ADD THIS
        
        try:
            cache_version_file = os.path.expanduser("~/.timetracker/ai_cache_version.txt")
            cached_version = ""
            if os.path.exists(cache_version_file):
                with open(cache_version_file) as f:
                    cached_version = f.read().strip()
            
            logger.info(f"[AI-SWITCH] Cache version: {cached_version} → {APP_VERSION}")  # ← ADD THIS
            
            if cached_version != APP_VERSION:
                cache_path = self.config["pattern_cache_file"]
                if os.path.exists(cache_path):
                    os.remove(cache_path)
                    self._cache._data = {}
                    logger.info(f"[AI-SWITCH] Pattern cache cleared on upgrade {cached_version or 'unknown'} → {APP_VERSION}")
                with open(cache_version_file, "w") as f:
                    f.write(APP_VERSION)
        except Exception as e:
            import traceback
            logger.warning(f"[AI-SWITCH] Cache version check failed: {e}\n{traceback.format_exc()}")

        self._ai_call_count   = 0
        self._ai_window_start = time.time()
        self._ai_queue: List[dict] = []
        self._ai_lock   = threading.Lock()
        self._ai_timer: Optional[threading.Timer] = None

        self._current_client_id:   Optional[int] = None
        self._current_client_name: Optional[str] = None
        self._pending_switch:      Optional[dict] = None
        self._cooldowns:           Dict[int, float] = {}
        self._manual_override_until: float = 0.0
        self._switch_history: List[SwitchEvent] = []
        self._lock      = threading.Lock()
        self._last_title = ""

        self._skip_exes = set(self.config.get("skip_exes", set()))
        # Merge in tax software exe names from shared constant

        self._skip_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in self.config.get("skip_title_patterns", [])
        ]

        self.stats = {
            "regex": 0, "cache": 0, "learned": 0, "file_conv": 0,
            "backend_ai": 0, "partial_word": 0, "switches": 0, "suppressed": 0,
        }

        self._backend_ai_available = bool(api_base and api_key)

        logger.info(
            f"[AI-SWITCH] Ready: {len(clients)} clients, "
            f"sensitivity={sensitivity}, "
            f"local_thresh={self.config['local_confidence_threshold']}, "
            f"partial={'on' if self.config['partial_name_matching'] else 'off'}, "
            f"dwell={self.config['dwell_seconds_before_switch']}s, "
            f"backend_ai={'yes' if self._backend_ai_available else 'no'}"
        )

    # =================================================================
    # Sensitivity Management (unchanged)
    # =================================================================

    def _apply_sensitivity(self):
        sensitivity = int(self.config.get("ai_sensitivity", 50))
        thresholds  = _sensitivity_to_thresholds(sensitivity)
        self.config.update(thresholds)
        logger.info(
            f"[AI-SWITCH] Sensitivity={sensitivity} → "
            f"local={thresholds['local_confidence_threshold']}, "
            f"ai={thresholds['openai_confidence_threshold']}, "
            f"suggest={thresholds['suggest_threshold']}, "
            f"partial={'on (min_len=' + str(thresholds['partial_name_min_word_len']) + ')' if thresholds['partial_name_matching'] else 'off'}"
        )

    def update_sensitivity(self, sensitivity: int):
        self.config["ai_sensitivity"] = max(0, min(100, int(sensitivity)))
        self._apply_sensitivity()
        self._matchers = _build_client_matchers(
            self._clients, self.config["ai_sensitivity"]
        )
        logger.info(f"[AI-SWITCH] Sensitivity updated live → {self.config['ai_sensitivity']}")

    # =================================================================
    # Public API (unchanged)
    # =================================================================

    def update_clients(self, clients: list):
        self._clients    = clients or []
        self._client_map = {c["id"]: c for c in self._clients}
        self._matchers   = _build_client_matchers(
            self._clients, self.config["ai_sensitivity"]
        )
        logger.info(f"[AI-SWITCH] Updated: {len(self._clients)} clients")

    def update_client_patterns(self, patterns: list):
        self._client_patterns = sorted(
            patterns or [],
            key=lambda p: p.get('weight', 0),
            reverse=True,
        )
        logger.info(f"[AI-SWITCH] Updated {len(self._client_patterns)} client patterns (Tier 0)")

    def set_current_client(self, client_id: int, client_name: str):
        self._current_client_id   = client_id
        self._current_client_name = client_name

    def on_manual_switch(self, client_id: int, client_name: str):
        with self._lock:
            self._current_client_id   = client_id
            self._current_client_name = client_name
            snooze_min = self.config["manual_override_snooze_minutes"]
            self._manual_override_until = time.time() + snooze_min * 60
            self._pending_switch = None
            self._last_title = ""
            logger.info(f"[AI-SWITCH] Manual override: {client_name} (snoozed {snooze_min}min)")

    def on_window_change(self, app_name: str, exe_name: str, title: str,
                         url: str = None, file_path: str = None, in_meeting: bool = False,
                         bundle_id: str = None):
        if not self.config["enabled"] or not title:
            return
        logger.info(f"[AI-SWITCH] on_window_change fired: {title[:60]!r} cur={self._current_client_id}")
        self._last_title = title
        if in_meeting or time.time() < self._manual_override_until:
            logger.info(f"[AI-SWITCH] on_window_change: skipped (meeting/override) override_until={self._manual_override_until:.0f} now={time.time():.0f}")
            return
        if self._should_skip(title, exe_name):
            logger.info(f"[AI-SWITCH] on_window_change: skipped by _should_skip")
            self._clear_pending()
            return
        logger.info(f"[AI-SWITCH] on_window_change: launching _detect")
        threading.Thread(
            target=self._detect,
            args=(app_name, exe_name, title, url, file_path),
            daemon=True,
        ).start()

    def on_dwell_tick(self):
        pass  # Switches execute immediately in _queue_switch


    def undo_last_switch(self) -> bool:
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
    # Tier 0 — Org admin patterns (unchanged)
    # =================================================================

    def _tier0_pattern_match(self, app_name: str, title: str) -> Optional[ClientMatch]:
        search_app   = (app_name or '').lower()
        search_title = (title or '').lower()

        for rule in self._client_patterns:
            pattern    = (rule.get('pattern') or '').lower()
            if not pattern:
                continue
            match_type  = rule.get('match_type', 'title')
            client_name = rule.get('client_name', '')

            client = next(
                (c for c in self._clients if c.get('name') == client_name), None
            )
            if not client:
                continue

            hit = False
            if match_type == 'app' and pattern in search_app:
                hit = True
            elif match_type == 'title' and pattern in search_title:
                hit = True

            if hit:
                confidence = min(1.0, rule.get('weight', 100) / 100.0)
                return ClientMatch(
                    client_id=client['id'],
                    client_name=client_name,
                    confidence=confidence,
                    match_method='org_rule',
                    matched_token=pattern,
                    reasoning=f"Org rule: {match_type}='{pattern}' → {client_name}",
                )
        return None

    # =================================================================
    # Detection Pipeline
    # KEY CHANGE: _should_skip now uses shared GENERIC_TAX_DIALOGS
    # =================================================================

    def _detect(self, app_name: str, exe_name: str, title: str,
                url: str, file_path: str):
        try:
            logger.info(f"[AI-SWITCH] _detect entered: {title[:60]!r}")
            search      = f"{title} {file_path}" if file_path else title
            cur_id      = self._current_client_id
            sensitivity = self.config["ai_sensitivity"]

            # Tier 1b: Pre-compiled regex + partial-word — run FIRST, always wins over cache
            regex_hit = _regex_match(title, file_path, self._matchers, sensitivity)
            if regex_hit and regex_hit.client_id != cur_id:
                if regex_hit.confidence >= self.config["local_confidence_threshold"]:
                    stat_key = "partial_word" if regex_hit.match_method == "partial_word" else "regex"
                    self.stats[stat_key] += 1
                    self._queue_switch(regex_hit)
                    return

            # Tier 1a: Pattern cache — only if regex didn't match
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

            # Tier 1c: Learned rules
            learned_hit = self._learned.match(search, cur_id)
            if learned_hit and learned_hit.confidence >= 0.65:
                if learned_hit.client_id != cur_id:
                    self.stats["learned"] += 1
                    self._queue_switch(learned_hit)
                    return

            # Tier 1d: CPA file naming conventions
            file_hit = _cpa_file_match(title, self._clients, cur_id)
            if file_hit:
                self.stats["file_conv"] += 1
                self._queue_switch(file_hit)
                return

            # --- Tier 1e: Tax software open return → Internal - Tax ──────────────
            # When UltraTax/TaxWise has an individual return open and no client
            # matched, switch to the Internal - Tax client so time isn't orphaned.
            logger.info(f"[AI-SWITCH] Tier1e check: regex={regex_hit}, learned={learned_hit}, file={file_hit}, title={title[:60]}")

            if not regex_hit and not learned_hit and not file_hit:
                if (TAX_SOFTWARE_RETURN_PATTERN.search(title or '')
                        or TAX_SOFTWARE_TAXWISE_PATTERN.search(title or '')):
                    # Find the Internal - Tax client in our client list
                    internal_client = next(
                        (c for c in self._clients
                         if c.get('name', '').lower() == INTERNAL_TAX_CLIENT_NAME.lower()),
                        None
                    )
                    if internal_client and internal_client['id'] != cur_id:
                        match = ClientMatch(
                            client_id=internal_client['id'],
                            client_name=internal_client['name'],
                            confidence=0.92,
                            match_method="tax_software_return",
                            matched_token=title[:80],
                            reasoning="Tax software open return — routing to Internal - Tax",
                        )
                        self.stats["regex"] += 1
                        self._queue_switch(match)
                        return

            # Tier 0 fallback: Org-admin rules
            if self._client_patterns:
                tier0_hit = self._tier0_pattern_match(app_name, title)
                if tier0_hit and tier0_hit.client_id != cur_id:
                    self.stats["regex"] += 1
                    self._queue_switch(tier0_hit)
                    return

            # Suggestion only
            best_local = regex_hit or learned_hit or file_hit
            if best_local and best_local.client_id != cur_id:
                if best_local.confidence >= self.config["suggest_threshold"]:
                    if self.notif_manager and hasattr(self.notif_manager, "notify_client_suggestion"):
                        self.notif_manager.notify_client_suggestion(
                            client_id=best_local.client_id,
                            client_name=best_local.client_name,
                            confidence=best_local.confidence,
                            reason=best_local.reasoning,
                        )
                        logger.info(
                            f"[AI-SWITCH] Suggested: {best_local.client_name} "
                            f"(conf={best_local.confidence:.2f})"
                        )
                        return

            # Tier 2: Backend AI
            if self._backend_ai_available and self.config["enabled"]:
                if (regex_hit and regex_hit.confidence >= self.config["suggest_threshold"]) or not regex_hit:
                    self._enqueue_for_ai(title, file_path, app_name)
                    return

            with self._lock:
                self._pending_switch = None

        except Exception as e:
            logger.error(f"[AI-SWITCH] detect error: {e}")


    def _queue_switch(self, match: ClientMatch):
        cid = match.client_id
        with self._lock:
            if cid == self._current_client_id:
                return
            if time.time() < self._cooldowns.get(cid, 0):
                self.stats["suppressed"] += 1
                return
        # Execute immediately — no dwell, no pending
        self._execute_switch({
            "client_id": match.client_id,
            "client_name": match.client_name,
            "confidence": match.confidence,
            "method": match.match_method,
            "reasoning": match.reasoning,
            "match": match,
        })

    # =================================================================
    # Backend AI Batch Queue (unchanged)
    # =================================================================

    def _enqueue_for_ai(self, title: str, file_path: str, app_name: str):
        if not self._backend_ai_available:
            return
        now = time.time()
        if now - self._ai_window_start > 3600:
            self._ai_call_count  = 0
            self._ai_window_start = now
        if self._ai_call_count >= self.config["max_ai_calls_per_hour"]:
            return
        item = {
            "id":        hashlib.md5(f"{title}:{now}".encode()).hexdigest()[:12],
            "title":     title,
            "file_path": file_path,
            "app":       app_name,
        }
        with self._ai_lock:
            self._ai_queue.append(item)
            if self._ai_timer:
                self._ai_timer.cancel()
            if len(self._ai_queue) >= self.config["ai_max_batch"]:
                self._fire_ai_batch()
            else:
                self._ai_timer = threading.Timer(
                    self.config["ai_debounce_seconds"], self._fire_ai_batch,
                )
                self._ai_timer.daemon = True
                self._ai_timer.start()

    def _fire_ai_batch(self):
        with self._ai_lock:
            if not self._ai_queue:
                return
            batch           = self._ai_queue[:self.config["ai_max_batch"]]
            self._ai_queue  = self._ai_queue[self.config["ai_max_batch"]:]
            if self._ai_timer:
                self._ai_timer.cancel()
                self._ai_timer = None

        def _run():
            try:
                logger.info(f"[AI-SWITCH] Backend AI batch: {len(batch)} titles")
                self._ai_call_count += 1
                results = _call_backend_classify(
                    batch,
                    api_base=self.api_base,
                    api_key=self.api_key,
                    timeout=self.config.get("ai_timeout", 10),
                )
                cur_id = self._current_client_id
                for item, match in zip(batch, results):
                    if not match or match.client_id not in self._client_map:
                        continue
                    self._cache.put(item["title"], match.client_id, match.client_name, match.confidence)
                    if self.config["learn_from_confirms"]:
                        self._learned.learn(
                            item["title"], match.client_id, match.client_name, "backend_ai"
                        )
                    if match.confidence >= self.config["openai_confidence_threshold"]:
                        if match.client_id != cur_id:
                            self.stats["backend_ai"] += 1
                            self._queue_switch(match)
                            cur_id = match.client_id
            except Exception as e:
                logger.error(f"[AI-SWITCH] batch error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    # =================================================================
    # Switch Execution (unchanged)
    # =================================================================

    def _execute_switch(self, data: dict):
        cid    = data["client_id"]
        cname  = data["client_name"]
        conf   = data["confidence"]
        method = data.get("method", "?")
        match  = data.get("match")

        if cid == self._current_client_id:
            return

        try:
            old_id   = self._current_client_id
            old_name = self._current_client_name or "None"

            if self.set_current_client_fn:
                self.set_current_client_fn(cid, cname, "ai_switcher")

            self._current_client_id   = cid
            self._current_client_name = cname
            self._last_title = ""
            self._cooldowns[cid] = time.time() + self.config["cooldown_seconds"]

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

            self._notify_switch(cname, old_name, conf=conf, method=method)
            self.stats["switches"] += 1
            logger.info(
                f"[AI-SWITCH] ✅ {old_name} → {cname} "
                f"(conf={conf:.0%}, {method})"
            )

        except Exception as e:
            logger.error(f"[AI-SWITCH] switch error: {e}")

    def _do_backend_switch(self, client_id: int, client_name: str):
        if self.set_current_client_fn:
            self.set_current_client_fn(client_id, client_name, "ai_switcher")
        self._current_client_id   = client_id
        self._current_client_name = client_name
        if self.gui_menu_bar and hasattr(self.gui_menu_bar, "state"):
            self.gui_menu_bar.state.set_client(client_id, client_name)
            if hasattr(self.gui_menu_bar, "app") and self.gui_menu_bar.app:
                self.gui_menu_bar.app.title = (
                    f"⏱ {client_name}" if client_name else "⏱ None"
                )
        if self.notif_manager and hasattr(self.notif_manager, "set_current_client"):
            self.notif_manager.set_current_client(client_id, client_name)

    # =================================================================
    # Notifications (unchanged)
    # =================================================================

    def _notify_switch(self, new_name: str, old_name: str,
                       conf: float = 0, method: str = "", is_undo: bool = False):
        if not self.config["notify_on_switch"]:
            return
        if is_undo:
            title    = "⏱ Client Reverted"
            body     = f"Back to {new_name}"
            subtitle = "Undo successful"
        else:
            title    = "⏱ Client Switched"
            body     = f"{old_name} → {new_name}"
            subtitle = f"Auto-detected ({int(conf * 100)}% confidence)" if conf else "Auto-detected"

        full_body = f"{subtitle}\n{body}" if subtitle else body

        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(title, full_body, duration=5, threaded=True)
            return
        except ImportError:
            pass

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
            subprocess.run(
                ["powershell", "-Command", ps_script],
                timeout=5, capture_output=True,
            )
            return
        except Exception:
            pass

        try:
            def _show():
                from tkinter import Tk, Label
                root = Tk()
                root.title(title)
                root.attributes("-topmost", True)
                root.geometry("350x80+{}+{}".format(
                    root.winfo_screenwidth() - 370,
                    root.winfo_screenheight() - 120,
                ))
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
    # KEY CHANGE: _should_skip uses shared GENERIC_TAX_DIALOGS set
    # =================================================================

    def _should_skip(self, title: str, exe_name: str) -> bool:
        # Use shared suppression list (same set as block_classifier Stage 0)
        title_lower = title.lower().strip()
        if any(title_lower == d or title_lower.startswith(d) for d in GENERIC_TAX_DIALOGS):
            return True

        if exe_name and exe_name.lower() in self._skip_exes:
            return True

        t = title.lower().strip()
        for pat in self._skip_patterns:
            if pat.search(t):
                return True

        if t in {
            "google chrome", "microsoft edge", "brave browser", "firefox",
            "microsoft outlook", "mail", "slack", "file explorer",
            "microsoft teams", "zoom", "windows powershell",
            "command prompt", "terminal", "task manager",
        }:
            return True

        return False

    def _clear_pending(self):
        with self._lock:
            self._pending_switch = None
