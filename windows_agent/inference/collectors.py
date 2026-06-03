"""
Evidence collectors — one function per evidence source.

Each collector takes a WindowContext and returns a list of Evidence objects.
Collectors are pure: no state, no side effects. They wrap existing detection
logic from the agent (ai_client_switcher.py, widget_state_tracker.py,
tax_software_constants.py) so we don't duplicate matching logic.

Collectors that fail return [] rather than raising — the engine should never
crash because one detector hit an edge case.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Any
from urllib.parse import urlparse

from .evidence import Evidence, WindowContext

logger = logging.getLogger("timetracker.inference.collectors")


# =============================================================================
# Lazy imports — avoid circular import of ai_client_switcher
# =============================================================================

def _strip_qb(title: str) -> str:
    """Lazy import to avoid circular dependency at module load.
    v1.4.1: try bundle path first, fall back to dev path."""
    try:
        try:
            from ai_client_switcher import _strip_qb_screen_bracket
        except ImportError:
            from windows_agent.ai_client_switcher import _strip_qb_screen_bracket
        return _strip_qb_screen_bracket(title)
    except Exception:
        return title


def _cpa_file_match_safe(title: str, clients: list,
                         current_client_id: Optional[int] = None) -> Any:
    """Lazy import wrapper for _cpa_file_match.
    v1.4.1: try bundle path first, fall back to dev path."""
    try:
        try:
            from ai_client_switcher import _cpa_file_match
        except ImportError:
            from windows_agent.ai_client_switcher import _cpa_file_match
        return _cpa_file_match(title, clients, current_client_id)
    except Exception as e:
        logger.debug(f"_cpa_file_match failed: {e}")
        return None


def _widget_title_matches(title, file_path, url, client_name, aliases) -> bool:
    """Lazy import wrapper for WidgetStateTracker._title_matches_client.
    v1.4.1: try bundle path first, fall back to dev path."""
    try:
        try:
            from widget_state_tracker import WidgetStateTracker
        except ImportError:
            from windows_agent.widget_state_tracker import WidgetStateTracker
        return WidgetStateTracker._title_matches_client(
            title, file_path, url, client_name, aliases
        )
    except Exception as e:
        logger.debug(f"widget title match failed: {e}")
        return False

# v1.4.2: System path segments that must never match client names.
# Without this filter, file paths like C:\Users\<windows-username>\...
# falsely match when the Windows username happens to equal a client name.
_SYSTEM_PATH_SEGMENTS_BLOCKLIST = {
    'appdata', 'localappdata', 'local', 'roaming',
    'temp', 'tmp', 'cache', 'packages',
    'programfiles', 'programfilesx86', 'programdata',
    'program files', 'program files (x86)',
    'windows', 'system32', 'syswow64',
    'public', 'default',
    'ac', 'oice_16',  # Office Protected View internals
    'recycle.bin', '$recycle.bin', 'system volume information',
}


def _filter_path_segments(file_path: str) -> List[str]:
    """
    v1.4.2: Return path segments suitable for client matching.
    Strips drive letters, the user's home directory (immediate child of
    \\Users\\), and common system folders. This prevents false positives
    where a Windows username (e.g. 'mavops') collides with a client name.
    """
    if not file_path:
        return []
    normalized = file_path.replace('\\', '/')
    raw_segments = [s.strip() for s in normalized.split('/') if s.strip()]

    filtered = []
    skip_next = False
    for seg in raw_segments:
        seg_lower = seg.lower()

        # Skip drive letters (c:, d:, etc.)
        if re.match(r'^[a-z]:$', seg_lower):
            continue

        # If previous was "Users", skip this one (it's the Windows username)
        if skip_next:
            skip_next = False
            continue

        # If this is "Users", mark next segment to skip
        if seg_lower == 'users':
            skip_next = True
            continue

        # Skip common system folders + Office Protected View internals
        seg_compact = re.sub(r'[\s\-_,.&]+', '', seg_lower)
        if seg_compact in _SYSTEM_PATH_SEGMENTS_BLOCKLIST or seg_lower in _SYSTEM_PATH_SEGMENTS_BLOCKLIST:
            continue

        # Skip random hex/GUID-like segments (Office Protected View
        # generates folders like 'oice_16_974fa576_32c1d314_15fb')
        if re.match(r'^[0-9a-f]{8}[-_]', seg_lower):
            continue
        if re.search(r'\{[0-9a-f-]{20,}\}', seg_lower):
            continue

        filtered.append(seg_lower)

    return filtered

def _learned_rules_match(learned_rules, title, current_client_id=None):
    """Lazy wrapper for LearnedRules.match."""
    if learned_rules is None:
        return None
    try:
        return learned_rules.match(title, current_client_id)
    except Exception as e:
        logger.debug(f"learned rules match failed: {e}")
        return None


# =============================================================================
# Tier 1 — Hard direct evidence (0.85-0.95)
# =============================================================================

def collect_routing_rule_evidence(ctx: WindowContext) -> List[Evidence]:
    """
    Tier 1 (strength 0.95): org admin routing rules. HARD rules configured
    by org admins that force certain windows/files to specific clients.

    Example: UltraTax.exe → Internal-Tax client; Slack title → suppress.

    Reads from the process-wide OrgRoutingRuleEngine singleton in
    windows_agent.routing_rules. Updates from sync flow to both this
    collector and the legacy AIClientSwitcher path via that singleton.

    Only 'route_to_client' actions become evidence. 'suppress' and
    'never_switch_away' are state-machine actions that don't translate
    to confidence-graded evidence; they return no evidence so other
    collectors decide naturally.
    """
    try:
        from routing_rules import get_routing_engine
    except ImportError:
        try:
            from windows_agent.routing_rules import get_routing_engine
        except ImportError:
            return []

    try:
        engine = get_routing_engine()
        hit = engine.match(
            ctx.title or "",
            ctx.exe_name or "",
            ctx.file_path or "",
        )
    except Exception as e:
        logger.debug(f"routing rule match failed: {e}")
        return []

    if not hit:
        return []

    action = hit.get('action')
    if action != 'route_to_client':
        return []

    target_id = hit.get('target_client_id')
    if not target_id:
        return []

    return [Evidence(
        source='routing_rule_match',
        strength=0.95,
        client_id=int(target_id),
        detail={
            'rule_id': hit.get('id'),
            'match_type': hit.get('match_type'),
            'match_value': (hit.get('match_value') or '')[:80],
            'target_client_name': hit.get('target_client_name'),
            'action': action,
            'priority': hit.get('priority', 0),
        },
        detected_at=ctx.timestamp,
        freshness_window_seconds=900,
    )]

def collect_tax_software_evidence(
    ctx: WindowContext,
    clients: List[dict],
) -> List[Evidence]:
    """
    Tier 1 (0.95): Extract taxpayer name from UltraTax / TaxWise return title.

    Window titles like "1040 [SMITH JOHN A]" or "TaxWise 2024: 1040 In SMITH J"
    contain the taxpayer name directly. If we can match the extracted name
    against a client, that's nearly direct evidence.

    For returns that don't match a specific client (firm internal tax work),
    we don't emit evidence here — the firm-name detector handles routing
    to Internal-Tax.
    """
    if not ctx.title:
        return []

    try:
        try:
            from tax_software_constants import (
                TAX_SOFTWARE_RETURN_PATTERN,
                TAX_SOFTWARE_TAXWISE_PATTERN,
                GENERIC_TAX_DIALOGS,
            )
        except ImportError:
            from windows_agent.tax_software_constants import (
                TAX_SOFTWARE_RETURN_PATTERN,
                TAX_SOFTWARE_TAXWISE_PATTERN,
                GENERIC_TAX_DIALOGS,
            )
    except Exception as e:
        logger.debug(f"tax_software_constants not available: {e}")
        return []

    title_lower = ctx.title.lower().strip()
    if title_lower in GENERIC_TAX_DIALOGS:
        return []  # generic dialog, no client signal

    # Try UltraTax-style pattern first
    match = TAX_SOFTWARE_RETURN_PATTERN.search(ctx.title)
    if not match:
        match = TAX_SOFTWARE_TAXWISE_PATTERN.search(ctx.title)
    if not match:
        return []

    # We matched a return-open pattern. Now figure out which taxpayer.
    # The bracketed/colon-separated part contains the taxpayer name.
    # Example: "1040 [SMITH JOHN A]" → extract "SMITH JOHN A"
    bracket_match = re.search(r'\[([^\]]+)\]', ctx.title)
    if bracket_match:
        taxpayer_text = bracket_match.group(1).strip()
    else:
        # TaxWise: "1040 In SMITH J"
        in_match = re.search(r'(?:In|Individual)\s*:?\s*([A-Z][A-Z\s,]+)', ctx.title)
        taxpayer_text = in_match.group(1).strip() if in_match else None

    if not taxpayer_text:
        return []

    # Match taxpayer text against the client list (case-insensitive, both directions)
    taxpayer_lower = taxpayer_text.lower()
    for client in clients:
        client_name = (client.get("name") or "").strip()
        client_id = client.get("id")
        if not client_name or not client_id:
            continue
        cn_lower = client_name.lower()
        if cn_lower in taxpayer_lower or taxpayer_lower in cn_lower:
            return [Evidence(
                source="tax_software_taxpayer",
                client_id=client_id,
                strength=0.95,
                detected_at=ctx.timestamp,
                detail={
                    "taxpayer_text": taxpayer_text,
                    "matched_client_name": client_name,
                    "title_excerpt": ctx.title[:80],
                },
            )]

    return []


def collect_qb_company_file_evidence(
    ctx: WindowContext,
    clients: List[dict],
) -> List[Evidence]:
    """
    Tier 1 (0.95): Match QuickBooks company file against client list.

    QB Desktop titles look like:
      'Holly Corbett, Inc - QuickBooks Accountant Desktop Plus 2024 - [Home]'

    We strip the screen bracket to get just the company file, then match it
    against clients. Unambiguous when it matches.
    """
    if not ctx.title:
        return []

    # Only fire on QB-named processes
    exe_lower = (ctx.exe_name or "").lower()
    if "qbw" not in exe_lower and "quickbooks" not in (ctx.app_name or "").lower():
        return []

    stripped = _strip_qb(ctx.title)
    if not stripped:
        return []

    # Extract the company-file portion: everything before "- QuickBooks"
    company_file = stripped
    qb_idx = stripped.lower().find(" - quickbooks")
    if qb_idx > 0:
        company_file = stripped[:qb_idx].strip()
    # Strip trailing "(Primary)" or similar marker
    company_file = re.sub(r'\s*\([^)]+\)\s*$', '', company_file).strip()

    if not company_file:
        return []

    cf_lower = company_file.lower()
    for client in clients:
        client_name = (client.get("name") or "").strip()
        client_id = client.get("id")
        if not client_name or not client_id:
            continue
        cn_lower = client_name.lower()
        # Match company file ↔ client name in either direction. QB company
        # files often include "Inc" / "LLC" suffixes; tolerate that.
        if cn_lower == cf_lower or cn_lower in cf_lower or cf_lower in cn_lower:
            return [Evidence(
                source="qb_company_file",
                client_id=client_id,
                strength=0.95,
                detected_at=ctx.timestamp,
                detail={
                    "company_file": company_file,
                    "matched_client_name": client_name,
                },
            )]

    return []


def collect_file_path_evidence(
    ctx: WindowContext,
    clients: List[dict],
) -> List[Evidence]:
    """
    Tier 1 (0.90): Match active file path against client folder structures
    or CPA file convention.

    Two mechanisms:
      1. _cpa_file_match — matches "Smith Tax Return.pdf" style filenames
         against client names (existing helper, conf=0.82, we bump to 0.90
         since this is Tier 1)
      2. Folder-segment match — if the file path contains a folder named
         after a client (e.g., /Clients/HollyCorbett/2025-Q3/...), that
         folder is essentially declarative.
    """
    if not ctx.file_path:
        return []

    evidence_list = []

    # Mechanism 1: CPA file convention match (uses existing helper)
    cpa_match = _cpa_file_match_safe(ctx.file_path, clients)
    if cpa_match:
        evidence_list.append(Evidence(
            source="file_path_client_folder",
            client_id=cpa_match.client_id,
            strength=0.90,
            detected_at=ctx.timestamp,
            detail={
                "matched_token": getattr(cpa_match, "matched_token", ""),
                "match_method": getattr(cpa_match, "match_method", "file_convention"),
                "reasoning": getattr(cpa_match, "reasoning", ""),
            },
        ))

    # Mechanism 2: Folder-segment match
    # Walk path segments looking for one that matches a client name.
    # Folder structure is curated by the firm, so this is high signal.
    # v1.4.2: Filter system path segments (Users\<username>, AppData,
    # Temp, Packages, etc.) to prevent false matches where a Windows
    # username collides with a client name.
    segments = _filter_path_segments(ctx.file_path)
    if not segments:
        return evidence_list
    for client in clients:
        client_name = (client.get("name") or "").strip()
        client_id = client.get("id")
        if not client_name or not client_id:
            continue
        if any(e.client_id == client_id for e in evidence_list):
            continue  # already matched via mechanism 1

        cn_lower = client_name.lower()
        # v1.4.2: Compress whitespace/punctuation INCLUDING apostrophes
        # (both straight and curly) so "Lola's Pet Shop" matches the folder
        # name "lolas pet shop" / "Lolas_Pet_Shop".
        cn_compact = re.sub(r"[\s\-_,.&'\"\u2018\u2019]+", '', cn_lower)

        for seg in segments:
            seg_compact = re.sub(r"[\s\-_,.&'\"\u2018\u2019]+", '', seg)
            if not seg_compact or len(seg_compact) < 4:
                continue
            if cn_compact == seg_compact or cn_compact in seg_compact or seg_compact in cn_compact:
                evidence_list.append(Evidence(
                    source="file_path_client_folder",
                    client_id=client_id,
                    strength=0.90,
                    detected_at=ctx.timestamp,
                    detail={
                        "folder_segment": seg,
                        "matched_client_name": client_name,
                        "path_excerpt": ctx.file_path[-100:],
                    },
                ))
                break

    return evidence_list


def collect_title_alias_evidence(
    ctx: WindowContext,
    clients: List[dict],
) -> List[Evidence]:
    """
    Tier 1 (0.85): Match window title against client name + aliases.

    Uses the existing WidgetStateTracker._title_matches_client logic which
    has four matching modes (flexible full-name, apostrophe-tolerant,
    partial-word on distinctive tokens, and acronym match). That logic is
    already battle-tested in production for widget state tracking, so we
    reuse it directly here.
    """
    if not ctx.title and not ctx.file_path and not ctx.url:
        return []

    matches = []
    for client in clients:
        client_name = (client.get("name") or "").strip()
        client_id = client.get("id")
        if not client_name or not client_id:
            continue
        aliases = client.get("aliases") or []

        # v1.4.2: title_alias collector only checks the window title.
        # file_path has its own dedicated collector (file_path_client_folder);
        # url has its own (url_domain_match). Including them here caused
        # double-attribution when path segments like Windows usernames
        # collided with client names.
        if _widget_title_matches(
            ctx.title, None, None, client_name, aliases
        ):
            matches.append(Evidence(
                source="title_alias_match",
                client_id=client_id,
                strength=0.85,
                detected_at=ctx.timestamp,
                detail={
                    "matched_client_name": client_name,
                    "title_excerpt": (ctx.title or "")[:80],
                },
            ))

    return matches


def collect_manual_override_evidence(
    ctx: WindowContext,
) -> List[Evidence]:
    """
    Tier 1 (0.85): Active user manual override.

    The manual override is set in WindowContext.manual_override when the
    user explicitly picked a client in the tray. Strength is 0.85 (same as
    other Tier 1) and decays via the standard 15-min linear decay using
    the override's set_at timestamp.
    """
    if not ctx.manual_override:
        return []

    override = ctx.manual_override
    client_id = override.get("client_id")
    set_at = override.get("set_at")
    if not client_id or not set_at:
        return []

    # If set_at is a string, parse it
    if isinstance(set_at, str):
        try:
            set_at = datetime.fromisoformat(set_at)
        except Exception:
            return []

    return [Evidence(
        source="manual_user_override",
        client_id=client_id,
        strength=0.85,
        detected_at=set_at,
        detail={
            "set_by": override.get("set_by", "user"),
            "previous_client_id": override.get("previous_client_id"),
        },
    )]


# =============================================================================
# Tier 2 — Contextual evidence (0.40-0.75)
# =============================================================================

def collect_calendar_evidence(
    ctx: WindowContext,
    clients: List[dict],
) -> List[Evidence]:
    """
    Tier 2 (0.75): Active calendar event tagged for a client.

    Reads from ctx.active_calendar_event (shape:
    {client_id, event_title, started_at, ...}). The agent's meeting
    detector or a calendar integration would populate this.
    """
    if not ctx.active_calendar_event:
        return []

    event = ctx.active_calendar_event
    client_id = event.get("client_id")
    if not client_id:
        return []

    started_at = event.get("started_at")
    if isinstance(started_at, str):
        try:
            started_at = datetime.fromisoformat(started_at)
        except Exception:
            started_at = ctx.timestamp
    elif not started_at:
        started_at = ctx.timestamp

    return [Evidence(
        source="calendar_event_tag",
        client_id=client_id,
        strength=0.75,
        detected_at=started_at,
        freshness_window_seconds=3600,  # calendar events are valid for full duration
        detail={
            "event_title": event.get("event_title", ""),
            "event_id": event.get("event_id"),
        },
    )]


def collect_url_domain_evidence(
    ctx: WindowContext,
    clients: List[dict],
) -> List[Evidence]:
    """
    Tier 2 (0.65): Active browser URL on a client-associated domain.

    For now, checks if the URL hostname (sans www.) appears in any client's
    associated_domains list. Most clients won't have this populated — it's
    opt-in. Stubbed but functional.
    """
    if not ctx.url:
        return []

    try:
        parsed = urlparse(ctx.url)
        host = (parsed.hostname or "").lower().lstrip("www.")
        if not host:
            return []
    except Exception:
        return []

    matches = []
    for client in clients:
        client_id = client.get("id")
        domains = client.get("associated_domains") or []
        if not client_id or not domains:
            continue
        for domain in domains:
            domain_lower = (domain or "").lower().lstrip("www.")
            if not domain_lower:
                continue
            if host == domain_lower or host.endswith("." + domain_lower):
                matches.append(Evidence(
                    source="url_domain_match",
                    client_id=client_id,
                    strength=0.65,
                    detected_at=ctx.timestamp,
                    detail={
                        "matched_domain": domain,
                        "active_host": host,
                    },
                ))
                break
    return matches


def collect_email_thread_evidence(
    ctx: WindowContext,
    clients: List[dict],
) -> List[Evidence]:
    """
    Tier 2 (0.60): Active email thread linked to a client.

    Reads from ctx.active_email_thread (shape:
    {client_id, subject, sender, ...}). Requires Outlook integration to
    populate. Stubbed but functional.
    """
    if not ctx.active_email_thread:
        return []
    thread = ctx.active_email_thread
    client_id = thread.get("client_id")
    if not client_id:
        return []
    return [Evidence(
        source="email_thread_match",
        client_id=client_id,
        strength=0.60,
        detected_at=ctx.timestamp,
        detail={
            "subject": thread.get("subject", ""),
            "sender": thread.get("sender", ""),
        },
    )]


def collect_continuity_evidence(
    ctx: WindowContext,
) -> List[Evidence]:
    """
    Tier 2 (0.40): Recent window history showed the same client.

    If the last 2-3 windows had Tier 1 evidence for the same client, that
    client gets a continuity signal here. Helps with brief excursions
    (Outlook check, file browser, etc.) that interrupt focused work.

    ctx.recent_windows shape: [{client_id, confidence, timestamp}, ...]
    most recent first.
    """
    if not ctx.recent_windows or len(ctx.recent_windows) < 2:
        return []

    # Count occurrences of each client_id in last 3 windows
    last_n = ctx.recent_windows[:3]
    client_votes: dict = {}
    most_recent_at = None
    for w in last_n:
        cid = w.get("client_id")
        if not cid:
            continue
        client_votes[cid] = client_votes.get(cid, 0) + 1
        wts = w.get("timestamp")
        if wts and (most_recent_at is None or wts > most_recent_at):
            most_recent_at = wts

    if not client_votes:
        return []

    # At least 2 of the last 3 windows must point to the same client
    best_client_id, votes = max(client_votes.items(), key=lambda kv: kv[1])
    if votes < 2:
        return []

    detected_at = most_recent_at or ctx.timestamp
    if isinstance(detected_at, str):
        try:
            detected_at = datetime.fromisoformat(detected_at)
        except Exception:
            detected_at = ctx.timestamp

    return [Evidence(
        source="recent_window_continuity",
        client_id=best_client_id,
        strength=0.40,
        detected_at=detected_at,
        detail={
            "votes": votes,
            "windows_considered": len(last_n),
        },
    )]


# =============================================================================
# Tier 3 — Soft evidence (0.20-0.40)
# =============================================================================

def collect_learned_pattern_evidence(
    ctx: WindowContext,
    learned_rules,  # LearnedRules instance or None
) -> List[Evidence]:
    """
    Tier 3 (0.30): Learned pattern match.

    IMPORTANT: The LearnedRules store should only contain patterns confirmed
    by user actions, never auto-attributions. That constraint is enforced
    when patterns are written (separate concern). Here we just read.

    Strength is capped at 0.30 regardless of the underlying rule's stored
    confidence — learned patterns alone never commit; they only corroborate.
    """
    if not ctx.title or learned_rules is None:
        return []

    match = _learned_rules_match(learned_rules, ctx.title)
    if not match:
        return []

    return [Evidence(
        source="learned_pattern",
        client_id=match.client_id,
        strength=0.30,
        detected_at=ctx.timestamp,
        detail={
            "matched_token": getattr(match, "matched_token", ""),
            "match_method": getattr(match, "match_method", "learned_rule"),
            "stored_confidence": getattr(match, "confidence", 0.0),
        },
    )]


# =============================================================================
# Tier 4 — Anti-evidence (reduce/cap confidence)
# =============================================================================

def collect_idle_evidence(ctx: WindowContext, is_idle: bool) -> List[Evidence]:
    """
    Anti-evidence: OS reports user-idle. Forces confidence to 0.0.

    is_idle is sourced from the agent's existing idle detection. Caller
    passes it in rather than collector re-querying.
    """
    if not is_idle:
        return []
    return [Evidence(
        source="os_idle",
        client_id=None,
        strength=1.0,  # full anti-evidence effect
        detected_at=ctx.timestamp,
        detail={"reason": "os_idle_detected"},
    )]


def collect_generic_browser_evidence(ctx: WindowContext) -> List[Evidence]:
    """
    Anti-evidence: Generic browser tab (news, search, social, new tab). Caps
    inference confidence at 0.5 — strong evidence can still attribute, but
    weak/contextual evidence alone cannot.
    """
    if not ctx.title:
        return []
    exe = (ctx.exe_name or "").lower()
    is_browser = any(b in exe for b in ("chrome", "msedge", "firefox", "brave", "safari"))
    if not is_browser:
        return []

    title_lower = ctx.title.lower()
    generic_markers = (
        "new tab", "google search", "search - ", "- youtube", "- twitter",
        "- facebook", "- reddit", "- linkedin", "- instagram",
        "google news", "yahoo news", "bing - search",
    )
    if any(m in title_lower for m in generic_markers):
        return [Evidence(
            source="generic_browser_tab",
            client_id=None,
            strength=1.0,
            detected_at=ctx.timestamp,
            detail={"title_excerpt": ctx.title[:80]},
        )]

    # Also fire for blank or near-blank titles
    if len(title_lower.strip()) < 5:
        return [Evidence(
            source="generic_browser_tab",
            client_id=None,
            strength=1.0,
            detected_at=ctx.timestamp,
            detail={"reason": "blank_browser_title"},
        )]

    return []


def collect_personal_app_evidence(ctx: WindowContext) -> List[Evidence]:
    """
    Anti-evidence: Foreground app is a personal/non-work app. Caps
    confidence at 0.3.
    """
    exe = (ctx.exe_name or "").lower()
    personal_exes = {
        "spotify.exe", "spotify", "applemusic", "vlc.exe", "vlc",
        "steam.exe", "steam", "epicgameslauncher.exe", "battle.net.exe",
        "discord.exe", "discord",  # could be work, but usually personal
        "netflix.exe", "primevideo.exe",
    }
    if any(p in exe for p in personal_exes):
        return [Evidence(
            source="personal_app_foreground",
            client_id=None,
            strength=1.0,
            detected_at=ctx.timestamp,
            detail={"exe": exe},
        )]
    return []


def collect_firm_name_evidence(
    ctx: WindowContext,
    firm_name_patterns: List[str],
    internal_client_id: Optional[int] = None,
) -> List[Evidence]:
    """
    Anti-evidence + Internal routing: If the window title contains the firm's
    own name (e.g., 'T.L. Wall Accounting'), this is INTERNAL work and
    should never attribute to a client.

    If internal_client_id is provided (the agent knows the org's Internal
    client_id), we emit positive evidence for Internal AND anti-evidence
    blocking any client attribution. Otherwise emit anti-evidence only.

    firm_name_patterns: list of strings to match against the title
        (case-insensitive substring). Should include the firm name and any
        common variants (e.g., ['T.L. Wall Accounting', 'TL Wall',
        'TLWall']).
    """
    if not ctx.title or not firm_name_patterns:
        return []

    title_lower = ctx.title.lower()
    matched_pattern = None
    for pattern in firm_name_patterns:
        if not pattern:
            continue
        if pattern.lower() in title_lower:
            matched_pattern = pattern
            break

    if not matched_pattern:
        return []

    out: List[Evidence] = [
        Evidence(
            source="firm_name_in_title",
            client_id=None,
            strength=1.0,
            detected_at=ctx.timestamp,
            detail={
                "matched_pattern": matched_pattern,
                "title_excerpt": ctx.title[:80],
            },
        )
    ]
    if internal_client_id:
        # Also vote positively for Internal — strong evidence
        out.append(Evidence(
            source="firm_name_in_title",
            client_id=internal_client_id,
            strength=0.90,
            detected_at=ctx.timestamp,
            detail={
                "matched_pattern": matched_pattern,
                "routes_to": "Internal",
            },
        ))
    return out


# =============================================================================
# Orchestrator — run all collectors and return combined evidence
# =============================================================================

def collect_all_evidence(
    ctx: WindowContext,
    clients: List[dict],
    learned_rules=None,
    is_idle: bool = False,
    firm_name_patterns: Optional[List[str]] = None,
    internal_client_id: Optional[int] = None,
) -> List[Evidence]:
    """
    Run every collector against the window context and return the combined
    evidence list. Order does not matter — the engine groups and ranks.

    Args:
        ctx: WindowContext snapshot of the current window
        clients: list of {id, name, aliases, associated_domains?} dicts
        learned_rules: LearnedRules instance (or None to skip Tier 3)
        is_idle: True if the OS reports the user as idle
        firm_name_patterns: list of firm name strings to detect for
            anti-evidence routing
        internal_client_id: client_id of the "Internal - Tax" client (if
            known) so firm_name detection can route there positively

    Returns:
        List of Evidence objects (positive + anti-evidence mixed). The
        inference engine separates and applies them.
    """
    all_evidence: List[Evidence] = []

    # Tier 1
    try:
        all_evidence.extend(collect_routing_rule_evidence(ctx))
    except Exception as e:
        logger.warning(f"routing_rule collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_tax_software_evidence(ctx, clients))
    except Exception as e:
        logger.warning(f"tax_software collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_qb_company_file_evidence(ctx, clients))
    except Exception as e:
        logger.warning(f"qb_company_file collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_file_path_evidence(ctx, clients))
    except Exception as e:
        logger.warning(f"file_path collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_title_alias_evidence(ctx, clients))
    except Exception as e:
        logger.warning(f"title_alias collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_manual_override_evidence(ctx))
    except Exception as e:
        logger.warning(f"manual_override collector failed: {e}", exc_info=True)

    # Tier 2
    try:
        all_evidence.extend(collect_calendar_evidence(ctx, clients))
    except Exception as e:
        logger.warning(f"calendar collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_url_domain_evidence(ctx, clients))
    except Exception as e:
        logger.warning(f"url_domain collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_email_thread_evidence(ctx, clients))
    except Exception as e:
        logger.warning(f"email_thread collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_continuity_evidence(ctx))
    except Exception as e:
        logger.warning(f"continuity collector failed: {e}", exc_info=True)

    # Tier 3
    try:
        all_evidence.extend(collect_learned_pattern_evidence(ctx, learned_rules))
    except Exception as e:
        logger.warning(f"learned_pattern collector failed: {e}", exc_info=True)

    # Tier 4 — anti-evidence
    try:
        all_evidence.extend(collect_idle_evidence(ctx, is_idle))
    except Exception as e:
        logger.warning(f"idle collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_generic_browser_evidence(ctx))
    except Exception as e:
        logger.warning(f"generic_browser collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_personal_app_evidence(ctx))
    except Exception as e:
        logger.warning(f"personal_app collector failed: {e}", exc_info=True)
    try:
        all_evidence.extend(collect_firm_name_evidence(
            ctx, firm_name_patterns or [], internal_client_id
        ))
    except Exception as e:
        logger.warning(f"firm_name collector failed: {e}", exc_info=True)

    return all_evidence
