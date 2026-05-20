"""
AI Client Auto-Switcher for TimeTracker Windows Agent

v1.2.95:
  * NEW: Tier -1 Org Routing Rules — hard rules from the backend that
         take priority over all other matchers. Per-firm configurable
         via admin UI. Used for "UltraTax always → Internal - Tax" etc.
  * NEW: Learned-rules auto-cleanup on version upgrade — the Maconi-style
         false-positive rules built from pre-v1.2.94 buggy data are wiped
         when the version bumps past 1.2.94.

v1.2.94: Three-layer bulletproof guard against false switches from
noise titles (QB redraws, Office splashes, browser tab flickers, etc.)
  Layer 1: Known app-chrome title patterns
  Layer 2: Signal-strength check (strip chrome tokens, require real content)
  Layer 3: Stability gate — title must persist >= 2s before detection fires

Full tier order (highest priority first):
  Tier -1: OrgRoutingRule (backend, per-firm)                    ← v1.2.95
  Tier  0: ClientPattern (title substring → client)
  Tier  1: Local matching (regex, cache, learned, CPA file conv)
  Tier  1e: Removed v1.2.97 — see comment in _detect()
  Tier  2: Backend AI classify

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
)

def _version_lt(a: str, b: str) -> bool:
    """Numeric semver compare. Returns True if a < b. Returns False
    for non-numeric strings (dev, unknown, custom) — caller must
    handle those explicitly."""
    try:
        a_parts = [int(x) for x in a.split(".")]
        b_parts = [int(x) for x in b.split(".")]
        return a_parts < b_parts
    except (ValueError, AttributeError):
        return False

# =====================================================================
# Three-Layer Guard Against False Switches From Noise Titles
# =====================================================================
# Problem this solves:
#   Apps sometimes briefly redraw their title bar with no document
#   context (e.g. " QuickBooks Accountant Desktop Plus 2024" with
#   leading space where client name used to be). Feeding these to
#   learned_partial causes non-deterministic false switches.

# Layer 1: Pure-chrome titles we've seen in the wild ------------------
_CHROME_ONLY_PATTERNS = [
    # QuickBooks Desktop — company file not loaded yet
    re.compile(r'^\s*QuickBooks(\s+Accountant)?\s+Desktop(\s+Plus)?(\s+\d{4})?\s*$', re.IGNORECASE),
    re.compile(r'^\s*QuickBooks\s+Desktop\s+Login\s*$', re.IGNORECASE),
    re.compile(r'^\s*QuickBooks\s*$', re.IGNORECASE),

    # Tax software — no return open
    re.compile(r'^\s*UltraTax\s+CS\s*$', re.IGNORECASE),
    re.compile(r'^\s*TaxWise(\s+\d{4})?\s*$', re.IGNORECASE),
    re.compile(r'^\s*Lacerte(\s+\d{4})?\s*$', re.IGNORECASE),
    re.compile(r'^\s*CCH\s+Axcess(\s+Tax)?\s*$', re.IGNORECASE),
    re.compile(r'^\s*ProSeries(\s+\d{4})?\s*$', re.IGNORECASE),
    re.compile(r'^\s*Drake\s+Tax(\s+\d{4})?\s*$', re.IGNORECASE),

    # Office — no document
    re.compile(r'^\s*Microsoft\s+(Excel|Word|PowerPoint|Outlook|Access|Project|Publisher|OneNote|Visio)\s*$', re.IGNORECASE),
    re.compile(r'^\s*(Excel|Word|PowerPoint|Outlook|OneNote)\s*$', re.IGNORECASE),

    # Browsers — no page / between tabs
    re.compile(r'^\s*(Google\s+Chrome|Microsoft\s+Edge|Brave(\s+Browser)?|Firefox|Opera|Safari)\s*$', re.IGNORECASE),
    re.compile(r'^\s*New\s+Tab\s*$', re.IGNORECASE),

    # Collaboration / comms
    re.compile(r'^\s*Microsoft\s+Teams\s*$', re.IGNORECASE),
    re.compile(r'^\s*Slack\s*$', re.IGNORECASE),
    re.compile(r'^\s*Zoom(\s+Meetings?)?\s*$', re.IGNORECASE),
    re.compile(r'^\s*Webex\s*$', re.IGNORECASE),
    re.compile(r'^\s*Discord\s*$', re.IGNORECASE),

    # Misc productivity
    re.compile(r'^\s*Adobe\s+Acrobat(\s+(DC|Pro|Reader))?\s*$', re.IGNORECASE),
    re.compile(r'^\s*File\s+Explorer\s*$', re.IGNORECASE),
    re.compile(r'^\s*Windows\s+Explorer\s*$', re.IGNORECASE),
    re.compile(r'^\s*Notepad(\+\+)?\s*$', re.IGNORECASE),
    re.compile(r'^\s*Visual\s+Studio(\s+Code)?\s*$', re.IGNORECASE),
]


def _is_chrome_only_title(title: str) -> bool:
    """Layer 1: title is empty or matches a known app-chrome pattern."""
    if not title or not title.strip():
        return True
    for pat in _CHROME_ONLY_PATTERNS:
        if pat.match(title):
            return True
    return False

_ACRONYM_BLOCKLIST = {
    # English stopwords / prepositions
    "of", "in", "on", "at", "to", "by", "or", "an", "as", "is", "it", "no",
    "so", "if", "do", "go", "us", "we", "be", "he", "my", "up", "am",
    # File-extension-ish / tech
    "pdf", "doc", "txt", "csv", "xls", "ppt",  # caught by len>=2 rule but fine
    "df", "tc", "id", "ip", "os", "pc", "ui", "ux", "qa", "qc",
    "db", "io", "ai", "ml", "vm",
    # Common biz fragments
    "co", "hr", "pr", "it", "rd", "qb",  # qb = QuickBooks
    "tx", "fl", "ny", "ca",  # state codes (will collide w/ TX clients etc)
}

# 2-letter acronyms are blocked by default because they collide with common
# fragments ("tc", "df", "co", "in"). Add an entry here when a firm has a
# 2-word client whose initials are unambiguous in their domain. Long-term
# this should move to a per-org sync field; for now it's hardcoded.
_ACRONYM_2CHAR_ALLOWLIST = {
    "df",  # TL Wall — Dauphin & Fantacone
}

# Layer 2: Signal-strength check --------------------------------------
_CHROME_TOKENS = {
    "microsoft", "google", "adobe", "intuit", "mozilla",
    "quickbooks", "qb", "excel", "word", "powerpoint", "outlook",
    "onenote", "access", "project", "publisher", "visio",
    "chrome", "edge", "brave", "firefox", "opera", "safari",
    "teams", "slack", "zoom", "webex", "discord",
    "acrobat", "reader", "notepad", "explorer", "code",
    "ultratax", "taxwise", "lacerte", "proseries", "drake",
    "cch", "axcess", "atx", "prosystem", "fx",
    "desktop", "professional", "enterprise", "premier", "accountant",
    "plus", "pro", "standard", "edition", "version", "home", "business",
    "student", "personal", "family", "suite", "online", "cloud",
    "login", "sign", "in", "signin", "new", "tab", "untitled", "document",
    "workbook", "presentation", "file", "window", "blank", "loading",
    "20", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026",
    "v1", "v2", "v3",
    "the", "and", "for", "of", "a", "an",
}

_MIN_SIGNAL_CHARS = 3
_ACRONYM_LENGTH_BLOCKLIST = 2  # block acronyms shorter than this+1 unless allowlisted
_ACRONYM_GLOBAL_ALLOWLIST = set()

def _has_client_signal(title: str, file_path: str = None) -> bool:
    """Layer 2: title has real content beyond app branding?"""
    if file_path:
        return True
    if not title:
        return False

    tokens = re.split(r'[\s\-\u2013\u2014|:/\\.,()\[\]{}*<>"\']+', title.lower())
    signal_tokens = [
        t for t in tokens
        if t and t not in _CHROME_TOKENS and not t.isdigit() and len(t) >= 2
    ]

    if not signal_tokens:
        return False

    total_alpha = sum(len(t) for t in signal_tokens if any(c.isalpha() for c in t))
    return total_alpha >= _MIN_SIGNAL_CHARS


# Layer 3: Stability gate ---------------------------------------------
_STABILITY_SECONDS = 2.0


_PATH_NOISE_FOLDERS = {
    "users", "user", "home",
    "onedrive", "dropbox", "icloud", "icloud drive", "box", "google drive",
    "desktop", "documents", "downloads", "pictures", "music", "videos",
    "appdata", "local", "roaming", "library",
    "c:", "d:", "e:",
}
 

# =====================================================================
# Tier -1: Org Routing Rules (v1.2.95)
# =====================================================================
# Hard rules that take priority over every other matcher.
# Fetched from backend via sync.routing_rules.
#
# The matching logic MUST stay in sync with backend
# views_routing_rules._rule_matches() so the admin's "Test this title"
# simulator matches what the agent actually does.

# Shared exe family → process name prefixes. Keep in sync with
# views_routing_rules.EXE_FAMILIES on the backend.
_EXE_FAMILIES = {
    'taxwise':     ['tww', 'taxwise'],   # tww24.exe / tww25.exe / TaxWise.exe
    'ultratax':    ['uts', 'ultratax', 'utw'],   # utw24.exe / utw25.exe
    'lacerte':     ['lacerte', 'lacertepro'],
    'proseries':   ['proseries', 'ps'],
    'drake':       ['drake'],
    'quickbooks':  ['qbw', 'qb', 'quickbooks'],
    'excel':       ['excel'],
    'word':        ['winword'],
    'powerpoint':  ['powerpnt'],
    'outlook':     ['outlook'],
    'chrome':      ['chrome'],
    'edge':        ['msedge'],
    'firefox':     ['firefox'],
    'teams':       ['teams', 'ms-teams'],
    'slack':       ['slack'],
    'zoom':        ['zoom'],
}


def _exe_family_matches(family_key: str, exe_name: str) -> bool:
    """Given 'taxwise' and 'utw25.exe', return True."""
    if not exe_name:
        return False
    prefixes = _EXE_FAMILIES.get(family_key.lower(), [family_key.lower()])
    exe_low = exe_name.lower().replace('.exe', '').strip()
    return any(exe_low.startswith(p) for p in prefixes)


class OrgRoutingRuleEngine:
    """
    Evaluates per-org routing rules fetched from the backend.

    Rules are fetched via sync and passed in via update_rules().
    Call match() on every window change before running other tiers.
    """

    def __init__(self, rules: Optional[List[dict]] = None):
        self._rules: List[dict] = []
        self._api_base: str = ""
        self._api_key: str = ""
        self.update_rules(rules or [])

    def set_api(self, api_base: str, api_key: str):
        """Set API credentials for telemetry (fire_count reporting)."""
        self._api_base = api_base
        self._api_key = api_key

    def update_rules(self, rules: List[dict]):
        """Replace the rule set; called from sync."""
        # Sort by priority descending so the first match wins
        self._rules = sorted(
            rules or [],
            key=lambda r: r.get('priority', 0),
            reverse=True,
        )
        logger.info(f"[AI-SWITCH] OrgRoutingRuleEngine: {len(self._rules)} rules loaded")
        for r in self._rules:
            logger.info(
                f"  · [{r.get('priority', 0)}] {r.get('match_type')}={r.get('match_value')!r} "
                f"→ {r.get('action')} (client={r.get('target_client_name') or 'n/a'})"
            )

    def match(self, title: str, exe: str, file_path: str) -> Optional[dict]:
        """
        Return the first matching rule (highest priority wins), or None.
        Returns the raw rule dict so caller can inspect action/target/etc.
        """
        if not self._rules:
            return None

        for rule in self._rules:
            if self._rule_matches(rule, title, exe, file_path):
                logger.info(
                    f"[AI-SWITCH] OrgRule fire: id={rule.get('id')} "
                    f"{rule.get('match_type')}={rule.get('match_value')!r} "
                    f"→ {rule.get('action')} "
                    f"({rule.get('target_client_name') or 'n/a'})"
                )
                self._report_fire(rule.get('id'))
                return rule
        return None

    @staticmethod
    def _rule_matches(rule: dict, title: str, exe: str, file_path: str) -> bool:
        mv = (rule.get('match_value') or '').lower()
        mt = rule.get('match_type')
        title_l = (title or '').lower()
        exe_l = (exe or '').lower()
        path_l = (file_path or '').lower()

        if mt == 'exe':
            return exe_l == mv or exe_l == f"{mv}.exe"

        if mt == 'exe_family':
            return _exe_family_matches(mv, exe_l)

        if mt == 'title_contains':
            return mv in title_l

        if mt == 'title_regex':
            try:
                return bool(re.search(rule['match_value'], title or '', re.IGNORECASE))
            except re.error:
                return False

        if mt == 'file_path_contains':
            return mv in path_l

        return False

    def _report_fire(self, rule_id: Optional[int]):
        """Fire-and-forget telemetry to the backend (non-blocking)."""
        if not rule_id or not self._api_base or not self._api_key:
            return

        def _send():
            try:
                url = f"{self._api_base.rstrip('/')}/routing-rules/fire/"
                req = urllib.request.Request(
                    url,
                    data=json.dumps({'rule_id': rule_id}).encode('utf-8'),
                    method='POST',
                )
                req.add_header('Authorization', f'DeviceKey {self._api_key}')
                req.add_header('Content-Type', 'application/json')
                urllib.request.urlopen(req, timeout=3).read()
            except Exception as e:
                logger.debug(f"[AI-SWITCH] OrgRule fire telemetry failed: {e}")

        threading.Thread(target=_send, daemon=True).start()


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

    "local_confidence_threshold": 0.80,
    "openai_confidence_threshold": 0.75,
    "suggest_threshold": 0.55,
    "partial_name_matching": False,
    "partial_name_min_word_len": 5,

    "dwell_seconds_before_switch": 0,
    "cooldown_seconds": 0,
    "manual_override_snooze_minutes": 0,

    "ai_timeout": 10,
    "max_ai_calls_per_hour": 60,
    "ai_debounce_seconds": 2.0,
    "ai_max_batch": 5,

    "learn_from_confirms": True,
    "notify_on_switch": False,   # v1.2.96: win10toast steals focus on Win10/11,
                                 # causes "black box flash" + interrupted keyboard
                                 # input. Switches happen silently until we build
                                 # a non-focus-stealing notification mechanism.
    "undo_window_seconds": 120,
    "max_switch_history": 50,
    "debug": False,

    "pattern_cache_file": os.path.expanduser("~/.timetracker/ai_pattern_cache.json"),
    "max_cache_entries": 2000,
    "cache_ttl_days": 30,

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
    # Original
    "professional", "services", "accounting", "management",
    "associates", "solutions", "group", "local", "national",
    "international", "community", "united", "general", "advanced",
    # Added 2026-05-18: "-service" matched Self-Service Portal against
    # Mike's Painting Service, locking Wayne onto the wrong client for
    # ~30 minutes. Singular was missing; plural already present.
    "service",
    # Generic legal-entity / business-noun tokens — these are never
    # discriminating partial-word matches. If a client name literally
    # IS one of these, they need a real alias, not partial-word fallback.
    "company", "co", "corp", "inc", "llc", "ltd",
    "holdings", "enterprises", "systems", "partners",
    "consulting", "properties", "investments",
    "the", "and", "of",
    # Tax-domain tokens — partial-word on these would false-positive
    # against every UltraTax title and tax-related email in an
    # accounting firm.
    "tax", "taxes", "law",
}


# =====================================================================
# Sensitivity → Threshold Mapping
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
# Pattern Cache
# =====================================================================

class PatternCache:
    def __init__(self, path, max_entries=2000, ttl_days=3):
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

    def invalidate(self, title: str) -> bool:
        """Remove a single cache entry by title. Returns True if removed.

        Used by _detect and _fire_ai_batch to drop cache entries that
        contradict the title evidence (e.g. cache says client A but the
        title clearly contains client B's name).
        """
        sig = self._signature(title)
        with self._lock:
            if sig in self._data:
                del self._data[sig]
                self._save()
                return True
        return False

    def remove_client(self, client_id: int):
        with self._lock:
            to_del = [k for k, v in self._data.items() if v.get("client_id") == client_id]
            for k in to_del:
                del self._data[k]
            if to_del:
                self._save()


# =====================================================================
# Pre-compiled Regex Matchers
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


        # Acronym match: build "DF" from "Dauphin & Fantacone" so filenames
        # like DF_Client_Invoice.pdf auto-switch without manual aliases.
        # Acronym must be 2+ letters; built from significant words only.
        words_for_acronym = re.split(r'[\s&,./\\]+', name)
        sig_words = [
            w.strip(" .,&") for w in words_for_acronym
            if w.strip(" .,&") and w.strip(" .,&").lower() not in _STOP_WORDS
            and len(w.strip(" .,&")) >= 2
        ]
        if len(sig_words) >= 2:
            acronym = "".join(w[0] for w in sig_words).lower()
            if len(acronym) >= 2:
                # 2-letter acronyms are collision-prone (e.g. "tc" matches
                # TimeCard, TaxCalc, etc.) and only enabled via the per-org
                # allowlist. 3+ letter acronyms ("lnp", "df_co" wouldn't,
                # but "lnp" for Little Nero's Pizza) are safe by default.
                allowed = (
                    len(acronym) >= 3
                    or acronym in _ACRONYM_2CHAR_ALLOWLIST
                )
                if not allowed:
                    logger.info(
                        f"[AI-SWITCH] Skipping 2-letter acronym {acronym!r} "
                        f"for {name!r} (not in allowlist — high collision risk)"
                    )
                else:
                    # Don't add if acronym is already a needle (some clients DO use
                    # their initials as the official name — avoid double pattern)
                    already_covered = any(acronym == n.lower() for n in needles_raw)
                    if not already_covered:
                        escaped = re.escape(acronym)
                        pat = re.compile(
                            r'(?:^|' + _BOUNDARY + r')' + escaped + r'(?:$|' + _BOUNDARY + r'|[0-9])',
                            re.IGNORECASE,
                        )
                        patterns.append((pat, acronym, "acronym"))

        if patterns:
            matchers.append({
                "client_id": c["id"],
                "client_name": name,
                "patterns": patterns,
                "needles_raw": needles_raw,
            })
    return matchers


def _path_depth_boost(needle: str, file_path: str) -> float:
    """
    Return a confidence adjustment based on WHERE in the path `needle`
    appears. Deeper = more relevant. Filename matches win over folder
    matches. Very-early matches (likely user/sync folders) get penalized.
 
    Returns a delta to add to confidence (can be negative).
    """
    if not file_path or not needle:
        return 0.0
 
    # Normalize separators so we handle / \ and mixed
    path_norm = file_path.replace("\\", "/").lower()
    needle_low = needle.lower()
 
    # Split into segments — drop empty ones (handles leading / and double //)
    segments = [s for s in path_norm.split("/") if s]
    if not segments:
        return 0.0
 
    # Find which segment(s) contain the needle, prefer the deepest hit
    deepest_hit_idx = -1
    for i, seg in enumerate(segments):
        if needle_low in seg:
            deepest_hit_idx = i
 
    if deepest_hit_idx < 0:
        return 0.0  # not in path at all (matched on title only)
 
    last_idx = len(segments) - 1
    distance_from_end = last_idx - deepest_hit_idx
 
    # Filename match (last segment) — strongest boost
    if distance_from_end == 0:
        boost = 0.10
    # Folder containing the file (2nd-to-last)
    elif distance_from_end == 1:
        boost = 0.07
    # One level up
    elif distance_from_end == 2:
        boost = 0.03
    else:
        boost = 0.0


    # Penalty for matches in user/sync/desktop folders. These are NEVER the
    # actual client context for the file. We need a heavy penalty to overcome
    # the +0.05 path-mention boost AND the +0.03 primary-name boost AND drop
    # below the 0.80 switch threshold.
    #
    # Specifically: the user folder ALWAYS contains the OS username (here,
    # "mavops") which is also a real client name in this org. Without a heavy
    # penalty, every Excel/Word/PDF on the user's machine triggers a switch
    # to the company that owns the machine.
    NOISE_FOLDER_NAMES = {
        "users", "user", "home",
        "onedrive", "dropbox", "icloud", "icloud drive", "box", "google drive",
        "desktop", "documents", "downloads", "pictures", "music", "videos",
        "appdata", "local", "roaming", "library",
    }
    # If the match is ONLY in the noise-folder region of the path
    # (first 3 segments) AND no deeper segment also contains it, kill it.
    only_in_noise = deepest_hit_idx < 3
    if only_in_noise:
        # Heavy penalty: -0.30 drops a 0.96 confidence to 0.66 (below 0.80
        # switch threshold AND below 0.65 learned threshold). Effectively
        # disqualifies user-folder name matches.
        boost -= 0.30

    return boost

def _regex_match(title: str, file_path: str, matchers: list,
                 sensitivity: int = 50) -> Optional[ClientMatch]:
    search_text = _normalize(f"{title or ''} {file_path or ''}")
    if not search_text.strip():
        return None

    best = None
    for m in matchers:
        for i, (pattern, needle, kind) in enumerate(m["patterns"]):
            hit = pattern.search(search_text)
            if not hit:
                continue

            needle_len = len(needle)

            # kind is False (exact/alias), True (partial_word), or "acronym"
            if kind == "acronym":
                # Acronyms are deterministic — built from the client's
                # actual significant words, not fuzzy. A 2-char acronym
                # from a 2-word client name is a strong signal.
                conf = 0.85
                method = "acronym"
            elif kind is True:  # partial_word
                if needle.lower() in _GENERIC_WORD_BLOCKLIST:
                    continue
                conf = _partial_word_confidence(needle_len, sensitivity)
                method = "partial_word"
            else:  # exact / alias
                if needle_len >= 8:   conf = 0.95
                elif needle_len >= 5: conf = 0.88
                elif needle_len >= 3: conf = 0.70
                else:                 conf = 0.50
                is_primary = (needle == m["needles_raw"][0])
                if is_primary:
                    conf = min(1.0, conf + 0.03)
                method = "exact" if is_primary else "alias"

            # Existing flat boost for any path mention
            if file_path and needle.lower() in (file_path or "").lower():
                conf = min(1.0, conf + 0.05)

            # Depth-aware boost
            depth_delta = _path_depth_boost(needle, file_path)
            conf = max(0.0, min(1.0, conf + depth_delta))

            this_depth = 0
            if file_path:
                segs = [s for s in file_path.replace("\\", "/").lower().split("/") if s]
                for seg_idx, seg in enumerate(segs):
                    if needle.lower() in seg:
                        this_depth = seg_idx

            is_better = False
            if best is None:
                is_better = True
            elif conf > best.confidence:
                is_better = True
            elif conf == best.confidence:
                best_depth = getattr(best, "_path_depth", -1)
                if this_depth > best_depth:
                    is_better = True

            if is_better:
                best = ClientMatch(
                    client_id=m["client_id"],
                    client_name=m["client_name"],
                    confidence=conf,
                    match_method=method,
                    matched_token=hit.group(0).strip(),
                    reasoning=(
                        f"Acronym '{needle}' matched in title"
                        if kind == "acronym"
                        else f"Partial word '{needle}' matched in title"
                        if kind is True
                        else f"Found '{needle}' in window title/path"
                    ),
                )
                best._path_depth = this_depth

    return best


# =====================================================================
# Learned Rules
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

    @staticmethod
    def _title_contains_client(title: str, client_name: str) -> bool:
        """
        v1.2.96: Returns True if the title contains the client's name in a
        recognizable form. Used to gate learning from email titles — only
        learn when the client is actually named in the title.

        Handles common fuzziness at CPA firms:
          - "St." vs "Saint"          (prefix substitution)
          - Apostrophes                ("Mary's" vs "Marys")
          - Abbreviated suffixes       ("Cemetery" vs "Cem")
          - Legal suffixes             ("Inc", "LLC", "Corp", "Ltd")
          - Case / whitespace / punct

        Strategy: normalize both sides, then check if at least 2 of the
        client's "distinctive" words appear in the title (or, for short
        client names, require the whole name to match).
        """
        if not title or not client_name:
            return False

        def _normalize(s: str) -> str:
            s = s.lower()
            # Common abbreviation expansions
            s = re.sub(r'\bst\.?\s', 'saint ', s)
            s = re.sub(r'\bmt\.?\s', 'mount ', s)
            s = re.sub(r'\bft\.?\s', 'fort ', s)
            # Strip apostrophes — "Mary's" == "Marys"
            s = s.replace("'", "").replace("\u2019", "")
            # Strip punctuation (keep word boundaries)
            s = re.sub(r'[.,()&/\\|:;!?"*\u2013\u2014]+', ' ', s)
            # Collapse whitespace
            s = re.sub(r'\s+', ' ', s).strip()
            return s

        title_n  = _normalize(title)
        client_n = _normalize(client_name)

        # Direct substring hit — easiest case
        if client_n and client_n in title_n:
            return True

        # Token-based fallback: at least 2 of the client's distinctive
        # tokens must appear in the title. Distinctive = 4+ chars AND
        # not in stop-words / generic business suffixes.
        _GENERIC_SUFFIXES = {
            'inc', 'llc', 'ltd', 'corp', 'co', 'company', 'group',
            'associates', 'partners', 'services', 'holdings', 'trust',
            'llp', 'pllc', 'pc',
        }
        client_tokens = [
            t for t in client_n.split()
            if len(t) >= 4
            and t not in _STOP_WORDS
            and t not in _GENERIC_SUFFIXES
        ]

        # If the client name has no distinctive tokens (e.g. "TL Inc"),
        # fall back to requiring a full substring match — which we
        # already checked above. Be conservative: reject.
        if not client_tokens:
            return False

        # Handle abbreviated variants: also check if a distinctive token
        # appears as a prefix of any title word (e.g. "Cemetery" matches
        # "Cem" in title, OR "Cem" matches "Cemetery"). We pick a 4-char
        # floor so trivial prefixes don't slip through.
        title_tokens = title_n.split()
        matches = 0
        for ct in client_tokens:
            # Direct token match
            if ct in title_tokens:
                matches += 1
                continue
            # Fuzzy prefix (4+ chars of client token OR title token must
            # share a prefix of 4+ chars)
            for tt in title_tokens:
                if len(tt) < 4:
                    continue
                # One is a prefix of the other, shared prefix >= 4 chars
                common_prefix = 0
                for a, b in zip(ct, tt):
                    if a != b:
                        break
                    common_prefix += 1
                if common_prefix >= 4:
                    matches += 1
                    break

        # Require at least 2 matching distinctive tokens for multi-word
        # client names. For single-word distinctive names, 1 token is
        # enough since the direct substring check above already failed.
        if len(client_tokens) == 1:
            return matches >= 1
        return matches >= 2

    def learn(self, title: str, client_id: int, client_name: str, source: str = "ai"):
        # v1.2.96: Only learn from email titles when the client name is
        # actually present in the title. Otherwise the agent picks up junk
        # like "Tax - Inbox - Outlook" and associates it with whatever
        # client happened to be active when the user read that email.
        #
        # GOOD — learns:
        #   "St. Mary's Cemetery - Q3 Financials - Outlook" → St. Mary's Cemetery
        #   "Benjamin Essig - 1040 Draft - Message (Plain Text)" → Benjamin Essig
        # BAD — skips:
        #   "Tax - Inbox - Tax - Outlook" → no client signal
        #   "Inbox - wayne@tlwallaccounting.com - Outlook" → no client signal
        #   "Rejected electronic file - Message (Plain Text)" → no client signal
        title_low = (title or '').lower()
        email_markers = [
            'inbox', 'outlook', '- mail', 'deleted items', 'sent items',
            'drafts', 'junk email', 'message (plain text)', 'message (html)',
        ]
        is_email = any(m in title_low for m in email_markers)

        # v1.2.97: Don't learn from IDE/editor source-file titles. They're
        # almost always a developer's environment, not a client signal.
        # Example: "main.py (windows_agent) - Sublime Text" gets learned as
        # whatever client the developer was on, then auto-switches them
        # every time they open the file again.
        ide_markers = [
            '- sublime text', '- visual studio code', 'visual studio code -',
            '- pycharm', '- intellij', '- webstorm', '- vim', '- neovim',
            '- notepad++', '- atom', '- emacs',
        ]
        source_extensions = ['.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs',
                             '.java', '.cpp', '.c', '.h', '.rb', '.php', '.html',
                             '.css', '.json', '.yaml', '.yml', '.md', '.sql']
        is_ide_source = (
            any(m in title_low for m in ide_markers)
            or any(ext in title_low for ext in source_extensions)
        )

        if is_ide_source:
            logger.debug(
                f"[AI-SWITCH] Not learning from IDE/source title: "
                f"{title[:60]!r} → {client_name!r}"
            )
            return

        if is_email:
            if not self._title_contains_client(title, client_name):
                logger.debug(
                    f"[AI-SWITCH] Not learning from email (no strong client match): "
                    f"{title[:60]!r} → {client_name!r}"
                )
                return
            # else: email IS about this client by name — safe to learn

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

            # v1.2.96: Skip matches that are purely stop-words or too short.
            # At a tax firm, titles like "Tax - Inbox - Tax - Outlook" contain
            # only stop-words, and caused constant false-positive switches
            # between random clients whose historical titles happened to
            # contain "tax." See Wayne@TL Wall outbreak 2026-04-22.
            key_tokens = set(re.split(r'[\s_\-.,|:/\\&()]+', key))
            key_tokens.discard('')
            if not key_tokens:
                continue
            if all(t in _STOP_WORDS or len(t) < 3 for t in key_tokens):
                continue

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

                # v1.2.96: Require at least one 5+ char non-stop-word shared
                # token before considering a fuzzy learned_partial match.
                # Short tokens ("tax", "and", "inc") create constant cross-
                # client noise at a CPA firm where every client has one.
                rk_tokens = set(re.split(r'[\s_\-.,|:/\\&()]+', rk.lower()))
                shared_strong = [
                    t for t in (rk_tokens & key_tokens)
                    if len(t) >= 5 and t not in _STOP_WORDS
                ]
                if not shared_strong:
                    continue

                if key in rk or rk in key:
                    # v1.2.97: A short title key matching as substring of a much
                    # longer rule key is almost always a false positive. Example:
                    # window title "timetracker" matches stored rule
                    # "timetracker by mavops — ai time intelligence for cpa firms"
                    # but the title is just an app name, not the actual brand.
                    shorter, longer = (key, rk) if len(key) <= len(rk) else (rk, key)
                    if len(longer) > len(shorter) * 2.5 and len(shorter) < 25:
                        # Title is ≥2.5x shorter than rule and under 25 chars —
                        # too generic to trust as a fuzzy match.
                        continue

                    adj = rule["confidence"] * 0.70
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
# CPA File Convention Matcher
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
# Backend AI Classifier
# =====================================================================

def _call_backend_classify(titles: list, api_base: str, api_key: str,
                           timeout: int = 10) -> List[Optional[ClientMatch]]:
    if not api_base or not api_key or not titles:
        return [None] * len(titles)

    url = f"{api_base.rstrip('/')}/ai/classify-batch/"
    payload = {
        "titles": [
            {
                "title":               t.get("title", ""),
                "app_name":            t.get("app", ""),
                "file_path":           t.get("file_path", ""),
                "url":                 t.get("url", ""),
                "current_client_name": t.get("current_client_name", ""),
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

        # v1.2.95: Tier -1 routing engine
        self._routing_engine = OrgRoutingRuleEngine()
        self._routing_engine.set_api(api_base, api_key)

        self._learned     = LearnedRules()
        self._cache       = PatternCache(
            self.config["pattern_cache_file"],
            self.config["max_cache_entries"],
            self.config["cache_ttl_days"],
        )

        # ── Auto-clear stale pattern cache + learned rules on version upgrade ─
        try:
            from version import APP_VERSION
        except Exception:
            APP_VERSION = "unknown"

        logger.info(f"[AI-SWITCH] Version: {APP_VERSION}")

        try:
            cache_version_file = os.path.expanduser("~/.timetracker/ai_cache_version.txt")
            cached_version = ""
            if os.path.exists(cache_version_file):
                with open(cache_version_file) as f:
                    cached_version = f.read().strip()

            logger.info(f"[AI-SWITCH] Cache version: {cached_version} → {APP_VERSION}")

            if cached_version != APP_VERSION:
                cache_path = self.config["pattern_cache_file"]
                if os.path.exists(cache_path):
                    os.remove(cache_path)
                    self._cache._data = {}
                    logger.info(f"[AI-SWITCH] Pattern cache cleared on upgrade {cached_version or 'unknown'} → {APP_VERSION}")

                # v1.2.96: Wipe learned rules on upgrade from pre-1.2.96.
                # v1.2.95's wipe (pre-1.2.94 guard) evidently didn't catch all
                # contaminated rule sets — Wayne@TL Wall still saw learned_partial
                # false positives on Outlook "Tax" folder. Widened the wipe guard
                # so ANY upgrade into 1.2.96+ from an older version clears the
                # contaminated learned rules, regardless of prior version.
                needs_wipe = (
                    cached_version == "" or
                    cached_version == "unknown" or
                    cached_version == "dev" or
                    APP_VERSION == "dev" or
                    _version_lt(cached_version, "1.2.96")
                )
                if needs_wipe:
                    learned_path = self._learned.path
                    if os.path.exists(learned_path):
                        backup_path = learned_path + f".pre_{APP_VERSION}.bak"
                        try:
                            os.rename(learned_path, backup_path)
                            logger.info(
                                f"[AI-SWITCH] Wiped learned rules (backed up to {backup_path}) "
                                f"— upgrade {cached_version or 'unknown'} → {APP_VERSION} "
                                f"crossed the learned-partial hardening threshold (v1.2.96)"
                            )
                        except Exception as e:
                            logger.warning(f"[AI-SWITCH] Learned rules wipe failed: {e}")
                    self._learned.rules = {}

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

        # Layer 3: Stability gate state
        self._pending_title: Optional[str] = None
        self._pending_title_first_seen: float = 0.0
        self._pending_title_context: Optional[tuple] = None
        self._stability_timer: Optional[threading.Timer] = None

        self._cooldowns:           Dict[int, float] = {}
        self._manual_override_until: float = 0.0
        self._switch_history: List[SwitchEvent] = []
        self._lock      = threading.Lock()
        self._last_title = ""

        self._skip_exes = set(self.config.get("skip_exes", set()))

        self._skip_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in self.config.get("skip_title_patterns", [])
        ]

        self.stats = {
            "regex": 0, "cache": 0, "learned": 0, "file_conv": 0,
            "backend_ai": 0, "partial_word": 0, "acronym": 0,  # ← add this
            "switches": 0, "suppressed": 0, "org_rule": 0,
        }

        self._backend_ai_available = bool(api_base and api_key)

        logger.info(
            f"[AI-SWITCH] Ready: {len(clients)} clients, "
            f"sensitivity={sensitivity}, "
            f"local_thresh={self.config['local_confidence_threshold']}, "
            f"partial={'on' if self.config['partial_name_matching'] else 'off'}, "
            f"dwell={self.config['dwell_seconds_before_switch']}s, "
            f"stability={_STABILITY_SECONDS}s, "
            f"backend_ai={'yes' if self._backend_ai_available else 'no'}"
        )

    # =================================================================
    # Sensitivity Management
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
    # Public API
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

    def update_routing_rules(self, rules: list):
        """
        v1.2.95: Update the Tier -1 org routing rules from backend sync payload.
        Called by sync when rules change server-side.
        """
        self._routing_engine.update_rules(rules or [])

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
        self._cancel_stability_timer()

    def on_window_change(self, app_name: str, exe_name: str, title: str,
                         url: str = None, file_path: str = None, in_meeting: bool = False,
                         bundle_id: str = None):
        """
        Called on every foreground-window change.

        Applies guards BEFORE running detection:
          - Tier -1 exe match peek: if an org rule matches on exe/path alone,
            bypass chrome guards so empty titles like "UltraTax CS" still route
          - Layer 1: chrome-only titles → drop
          - Layer 2: no signal content → drop
          - Layer 3: stability gate → wait _STABILITY_SECONDS, then detect
        """
        if not self.config["enabled"] or not title:
            return

        logger.info(f"[AI-SWITCH] on_window_change fired: {title[:60]!r} cur={self._current_client_id}")
        self._last_title = title

        if in_meeting or time.time() < self._manual_override_until:
            logger.info(
                f"[AI-SWITCH] on_window_change: skipped (meeting/override) "
                f"override_until={self._manual_override_until:.0f} now={time.time():.0f}"
            )
            return


        # ── Tier -2: Org routing rules run FIRST, before any skip ──────
        # Org admin hard rules must not be filterable by heuristics. If
        # a rule matches and routes to a client, switch immediately and
        # bypass everything else. This is what makes UltraTax → Internal-Tax
        # actually work — _should_skip used to block it.
        rule_hit = self._routing_engine.match(title or "", exe_name or "", file_path or "")
        if rule_hit:
            action = rule_hit.get('action')
            if action == 'route_to_client':
                target_id = rule_hit.get('target_client_id')
                target_name = rule_hit.get('target_client_name')
                if target_id and target_id != self._current_client_id:
                    match = ClientMatch(
                        client_id=int(target_id),
                        client_name=target_name or "",
                        confidence=1.0,
                        match_method="org_routing_rule",
                        matched_token=rule_hit.get('match_value', '')[:80],
                        reasoning=(
                            f"Org rule: {rule_hit.get('match_type')}="
                            f"{rule_hit.get('match_value')!r} → {target_name}"
                        ),
                    )
                    self.stats["org_rule"] += 1
                    self._queue_switch(match)
                # On target client or about to switch — done either way
                return
            elif action == 'suppress':
                logger.info(f"[AI-SWITCH] on_window_change: suppressed by rule {rule_hit.get('id')}")
                self.stats["suppressed"] += 1
                return
            elif action == 'never_switch_away':
                logger.info(f"[AI-SWITCH] on_window_change: never_switch_away rule {rule_hit.get('id')}")
                return

        # explorer_watcher dispatches folder paths even when the window title
        # is just a folder name (e.g. "Dauphin & Fantacone"), and we want
        # those to flow through to regex matching against the client list.
        if not file_path and self._should_skip(title, exe_name):
            logger.info(f"[AI-SWITCH] on_window_change: skipped by _should_skip")
            self._clear_pending()
            self._cancel_stability_timer()
            return

        # ── LAYER 1: Chrome-only titles ────────────────────────────────
        if _is_chrome_only_title(title):
            logger.info(
                f"[AI-SWITCH] Layer 1 drop: chrome-only title {title[:60]!r} "
                f"— holding cur={self._current_client_id}"
            )
            self.stats["suppressed"] += 1
            self._cancel_stability_timer()
            return

        # ── LAYER 2: Signal-strength check ─────────────────────────────
        if not _has_client_signal(title, file_path):
            logger.info(
                f"[AI-SWITCH] Layer 2 drop: no client signal in {title[:60]!r} "
                f"— holding cur={self._current_client_id}"
            )
            self.stats["suppressed"] += 1
            self._cancel_stability_timer()
            return

        # ── LAYER 3: Stability gate ────────────────────────────────────
        self._arm_stability_timer(app_name, exe_name, title, url, file_path)

    def _arm_stability_timer(self, app_name, exe_name, title, url, file_path):
        """
        Schedule _detect() to run in _STABILITY_SECONDS, unless another
        title arrives first and cancels this timer.
        """
        self._cancel_stability_timer()

        self._pending_title = title
        self._pending_title_first_seen = time.time()
        self._pending_title_context = (app_name, exe_name, url, file_path)

        def _fire():
            if self._pending_title != title:
                logger.info(
                    f"[AI-SWITCH] Layer 3: stability timer fired but title changed; skipping"
                )
                return

            age = time.time() - self._pending_title_first_seen
            logger.info(
                f"[AI-SWITCH] Layer 3 pass: {title[:60]!r} stable for {age:.1f}s → running _detect"
            )
            threading.Thread(
                target=self._detect,
                args=(app_name, exe_name, title, url, file_path),
                daemon=True,
            ).start()

        self._stability_timer = threading.Timer(_STABILITY_SECONDS, _fire)
        self._stability_timer.daemon = True
        self._stability_timer.start()

    def _cancel_stability_timer(self):
        if self._stability_timer is not None:
            try:
                self._stability_timer.cancel()
            except Exception:
                pass
            self._stability_timer = None
        self._pending_title = None
        self._pending_title_first_seen = 0.0
        self._pending_title_context = None

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
    # Tier 0 — Org admin patterns
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
    # =================================================================

    def _title_strongly_matches_other_client(
        self, title: str, exclude_client_id: int
    ) -> Optional[int]:
        """
        Returns the client_id of an active client (other than
        exclude_client_id) whose name or any alias is clearly present in
        the title. Returns None if no other client matches.

        Used to validate cache hits and backend AI verdicts: if the title
        evidence clearly points to a different client than the proposed
        attribution, reject it (don't trust, don't cache, don't learn).

        Uses LearnedRules._title_contains_client for CPA-friendly fuzzy
        matching (St. <-> Saint, apostrophes, suffixes, etc.).
        """
        if not title:
            return None
        for client in self._clients:
            cid = client.get("id")
            if not cid or cid == exclude_client_id:
                continue
            name = client.get("name") or ""
            if name and LearnedRules._title_contains_client(title, name):
                return cid
            for alias in client.get("aliases", []) or []:
                if alias and LearnedRules._title_contains_client(title, alias):
                    return cid
        return None

    def _detect(self, app_name: str, exe_name: str, title: str,
                url: str, file_path: str):
        try:
            logger.info(f"[AI-SWITCH] _detect entered: {title[:60]!r}")

            cur_id = self._current_client_id

            # Org routing rules now run in on_window_change (Tier -2),
            # before _should_skip. See on_window_change top.

            # Defense in depth: on_window_change already applies these
            # guards (chrome-only, no-signal), but catch any direct callers
            # that bypass it. Note: org rules ran in on_window_change before
            # we got here, so this block won't override them.
            if _is_chrome_only_title(title):
                logger.info(f"[AI-SWITCH] _detect safety-net: chrome-only — holding")
                self.stats["suppressed"] += 1
                return
            if not _has_client_signal(title, file_path):
                logger.info(f"[AI-SWITCH] _detect safety-net: no signal — holding")
                self.stats["suppressed"] += 1
                return

            search      = f"{title} {file_path}" if file_path else title
            sensitivity = self.config["ai_sensitivity"]

            # Tier 1b: Pre-compiled regex + partial-word
            regex_hit = _regex_match(title, file_path, self._matchers, sensitivity)
            logger.info(f"[AI-SWITCH] _detect: regex_hit={regex_hit} cur_id={cur_id}")
            if regex_hit and regex_hit.client_id != cur_id:
                if regex_hit.confidence >= self.config["local_confidence_threshold"]:
                    if regex_hit.match_method == "acronym":
                        stat_key = "acronym"
                    elif regex_hit.match_method == "partial_word":
                        stat_key = "partial_word"
                    else:
                        stat_key = "regex"
                    self.stats[stat_key] += 1
                    self._queue_switch(regex_hit)
                    return

            # Tier 1a: Pattern cache
            cached = self._cache.get(title)
            if cached and cached.get("client_id"):
                cached_id = cached["client_id"]
                # v1.3.20: Validate cache against title content. If the
                # title contains a DIFFERENT active client's name or
                # alias, the cache is stale or was poisoned (e.g. by a
                # prior backend AI call that fell back to current_client
                # per Rule 5 of the OpenAI prompt). Invalidate and fall
                # through to fresh detection.
                contradicted_by = self._title_strongly_matches_other_client(
                    title, exclude_client_id=cached_id
                )
                if contradicted_by is not None:
                    logger.warning(
                        f"[AI-SWITCH] cache INVALIDATED for {title[:60]!r}: "
                        f"cached client_id={cached_id} "
                        f"({cached.get('client_name')!r}) but title evidence "
                        f"points to client_id={contradicted_by}. Dropping entry."
                    )
                    self._cache.invalidate(title)
                    self.stats["cache_invalidated"] = (
                        self.stats.get("cache_invalidated", 0) + 1
                    )
                elif cached_id != cur_id:
                    match = ClientMatch(
                        client_id=cached_id,
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

            # NOTE: LLM-based real-time client classification was removed
            # in v1.2.98 (architecture decision: client classification is
            # deterministic-only; LLM runs at backend compaction with full
            # block context, not on individual window-change events).
            # See compaction.py for the LLM-driven client/category logic.
            #
            # Heuristic tiers below remain as the agent's deterministic
            # ladder. If nothing fires, the block stays Uncategorized
            # and compaction's LLM gets a second look.

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

            # Tier 0 fallback: Org-admin patterns
            if self._client_patterns:
                tier0_hit = self._tier0_pattern_match(app_name, title)
                if tier0_hit and tier0_hit.client_id != cur_id:
                    self.stats["regex"] += 1
                    self._queue_switch(tier0_hit)
                    return

            # Tier 1e removed (v1.2.97) — replaced by org routing rules in Tier -1.
            # TL Wall's TaxWise/UltraTax/Lacerte/ProSeries/Drake → Internal-Tax routing
            # is now handled by their 5 OrgRoutingRule entries (priority 300, all enabled).
            # Other firms get whatever rules they configure via the admin dashboard.
            # Migration audit (2026-04-27): 218 fires on TaxWise rule confirmed the engine
            # had taken over in production before this fallback was deleted.
            # If you're adding tax-software defaults for new firms, do it via OrgRoutingRule,
            # not here. See views_routing_rules.py for the API.

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

            # All deterministic tiers exhausted with no confident match.
            # Block accumulates as Uncategorized — backend compaction's
            # LLM will re-evaluate with full block context (5+ minutes
            # of titles/paths/URLs) and either assign a client at high
            # confidence (>=0.90) or leave Uncategorized for the user
            # to fix at timesheet review time.
            with self._lock:
                self._pending_switch = None

        except Exception as e:
            logger.exception(f"[AI-SWITCH] _detect crashed: {e}")


    def _queue_switch(self, match: ClientMatch):
        with self._lock:
            if match.client_id == self._current_client_id:
                return
            if time.time() < self._cooldowns.get(match.client_id, 0):
                self.stats["suppressed"] += 1
                return
        logger.info(f"[AI-SWITCH] _queue_switch: cid={match.client_id} cur={self._current_client_id} cooldown={self._cooldowns.get(match.client_id, 0):.0f} now={time.time():.0f}")
        self._execute_switch({
            "client_id": match.client_id,
            "client_name": match.client_name,
            "confidence": match.confidence,
            "method": match.match_method,
            "reasoning": match.reasoning,
            "match": match,
        })

    # =================================================================
    # Backend AI Batch Queue
    # =================================================================

    def _enqueue_for_ai(self, title: str, file_path: str, app_name: str,
                       url: str = "", current_client_name: str = ""):
        if not self._backend_ai_available:
            return
        now = time.time()
        if now - self._ai_window_start > 3600:
            self._ai_call_count  = 0
            self._ai_window_start = now
        if self._ai_call_count >= self.config["max_ai_calls_per_hour"]:
            return
        item = {
            "id":                  hashlib.md5(f"{title}:{now}".encode()).hexdigest()[:12],
            "title":               title,
            "file_path":           file_path,
            "app":                 app_name,
            "url":                 url,
            "current_client_name": current_client_name,
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
                    if not match:
                        logger.info(f"[AI-SWITCH] LLM: no match for {item['title'][:60]!r}")
                        continue
                    if match.client_id not in self._client_map:
                        logger.warning(
                            f"[AI-SWITCH] LLM returned unknown client_id={match.client_id} "
                            f"for {item['title'][:60]!r} — ignoring"
                        )
                        continue
                    # Log the verdict regardless of whether we switch
                    if match.client_id == cur_id:
                        logger.info(
                            f"[AI-SWITCH] LLM confirmed current client "
                            f"{match.client_name!r} (conf={match.confidence:.2f}) "
                            f"for {item['title'][:60]!r}"
                        )
                    else:
                        logger.info(
                            f"[AI-SWITCH] LLM verdict: {match.client_name!r} "
                            f"(conf={match.confidence:.2f}) for {item['title'][:60]!r}"
                        )
                    
                    # v1.3.20: Validate backend AI verdict before
                    # persisting. If the title clearly contains a
                    # different active client's name or alias, the
                    # backend AI guessed wrong (likely fell back to
                    # "current_client" per Rule 5 of the OpenAI prompt
                    # in views_ai_classify.py). Don't cache, don't
                    # learn, don't switch. Prevents cache poisoning of
                    # all subsequent events with this title.
                    contradicted_by = self._title_strongly_matches_other_client(
                        item["title"], exclude_client_id=match.client_id
                    )
                    if contradicted_by is not None:
                        logger.warning(
                            f"[AI-SWITCH] backend AI REJECTED for "
                            f"{item['title'][:60]!r}: returned client_id="
                            f"{match.client_id} ({match.client_name!r}) but "
                            f"title evidence points to client_id={contradicted_by}."
                        )
                        self.stats["backend_ai_rejected"] = (
                            self.stats.get("backend_ai_rejected", 0) + 1
                        )
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
    # Switch Execution
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
    # Notifications
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
    # =================================================================


    def _should_skip(self, title: str, exe_name: str) -> bool:
        title_lower = title.lower().strip()
        # Exact match only — startswith() was overreaching. Every loaded
        # UltraTax return title starts with "2025 ultratax cs" so the old
        # logic was hiding every real return from the rule engine.
        if title_lower in GENERIC_TAX_DIALOGS:
            return True
     
        if exe_name and exe_name.lower() in self._skip_exes:
            # Explorer exception: the explorer_watcher dispatches full filesystem
            # paths (e.g. "C:\Clients\Varacchi\2024 1040"). When the title looks
            # like a path, treat it as legitimate signal — same as the Mac agent
            # does via NSWorkspace. Random Explorer chrome ("Documents", "This PC",
            # "Quick access") doesn't look like a path so it still gets skipped.
            if exe_name.lower() == "explorer.exe" and self._looks_like_path(title):
                pass  # don't skip — fall through to the rest of the checks
            else:
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


    @staticmethod
    def _looks_like_path(s: str) -> bool:
        """Heuristic: does this string look like a Windows filesystem path?"""
        if not s or len(s) < 2:
            return False
        s = s.strip()
        # Drive letter (C:, D:, etc.)
        if len(s) >= 2 and s[1] == ":":
            return True
        # UNC path (\\server\share)
        if s.startswith("\\\\"):
            return True
        return False

    def _clear_pending(self):
        with self._lock:
            self._pending_switch = None

if __name__ == "__main__":
    test_clients = [
        {"id": 20, "name": "MAVOPS"},
        {"id": 141, "name": "Little Nero's Pizza"},
        {"id": 453, "name": "PureADK"},
    ]
    matchers = _build_client_matchers(test_clients, sensitivity=70)

    cases = [
        ("Little_Neros_Daily_Sales_March_2026  -  Protected View - Excel",
         r"C:\Users\mavops\OneDrive\Desktop\Little Nero's Pizza\Little_Neros_Daily_Sales_March_2026.xlsx"),
        ("PureADK_Client_Invoice_Lake_Placid_Outfitters.pdf - Edge",
         r"C:\Users\mavops\Downloads\PureADK_Client_Invoice_Lake_Placid_Outfitters.pdf"),
    ]
    for title, path in cases:
        result = _regex_match(title, path, matchers, sensitivity=70)
        if result:
            print(f"{title[:50]:50s}  →  {result.client_name:25s} conf={result.confidence:.2f}")
        else:
            print(f"{title[:50]:50s}  →  NO MATCH")