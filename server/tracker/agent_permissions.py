"""Desktop-agent privacy-permission status (macOS Accessibility / Automation).

The Mac agent reports what macOS lets it do in every hello2 check-in
(mac_agent/permissions.py PermissionMonitor.report()):

    {"accessibility": "granted" | "missing",
     "automation": {"com.google.Chrome": "granted" | "denied" | "unknown", ...},
     "capture_mode": "full" | "no_accessibility",
     "extension": "seen" | "not_seen" | "not_running",   (optional)
     "required_missing": ["Google Chrome", ...],
     "stale_entry_reset": true,                          (optional)
     "checked_at": "<iso8601>"}

It is stored on AgentDevice.permission_status as sent (after sanitising) and
turned into human-readable issues here, for the Settings → Devices badges and
the MavOps org health flags. Nothing here trusts the payload's shape: an agent
is a client, so every field is type-checked and size-capped.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_AX = {"granted", "missing"}
_AE = {"granted", "denied", "unknown"}
_MODES = {"full", "no_accessibility"}
_EXT = {"seen", "not_seen", "not_running"}
_MAX_TARGETS = 40
_MAX_STR = 120

# Friendly names for the Automation targets the agent reports by bundle id.
_APP_NAMES = {
    "com.google.Chrome": "Google Chrome",
    "com.microsoft.edgemac": "Microsoft Edge",
    "com.apple.Safari": "Safari",
    "com.brave.Browser": "Brave",
    "company.thebrowser.Browser": "Arc",
    "com.adobe.Photoshop": "Photoshop",
    "com.adobe.illustrator": "Illustrator",
    "com.adobe.InDesign": "InDesign",
    "com.adobe.Acrobat.Pro": "Acrobat",
    "com.microsoft.Excel": "Excel",
    "com.microsoft.Word": "Word",
    "com.microsoft.Powerpoint": "PowerPoint",
    "com.apple.finder": "Finder",
    "com.apple.systemevents": "System Events",
}


def _s(v: Any) -> str:
    return str(v)[:_MAX_STR] if v is not None else ""


def normalize_permission_status(raw: Any) -> Optional[Dict[str, Any]]:
    """The sanitised dict to store, or None if `raw` isn't a status at all."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    ax = raw.get("accessibility")
    if ax in _AX:
        out["accessibility"] = ax
    auto = raw.get("automation")
    if isinstance(auto, dict):
        clean = {}
        for k, v in list(auto.items())[:_MAX_TARGETS]:
            if isinstance(k, str) and k and v in _AE:
                clean[k[:_MAX_STR]] = v
        out["automation"] = clean
    if raw.get("capture_mode") in _MODES:
        out["capture_mode"] = raw["capture_mode"]
    if raw.get("extension") in _EXT:
        out["extension"] = raw["extension"]
    req = raw.get("required_missing")
    if isinstance(req, list):
        out["required_missing"] = [_s(x) for x in req[:_MAX_TARGETS] if isinstance(x, str)]
    if raw.get("stale_entry_reset") is True:
        out["stale_entry_reset"] = True
    if isinstance(raw.get("checked_at"), str):
        out["checked_at"] = raw["checked_at"][:40]
    if not any(k in out for k in ("accessibility", "automation", "capture_mode")):
        return None
    return out


def permission_issues(status: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """[{severity: 'red'|'amber', code, message}] for the Devices page.

    red   — something REQUIRED is off: an Automation target was denied (that
            app's page/file never reaches us) or the browser extension is off.
    amber — limited capture: Accessibility is missing, so window titles of
            apps with no scripting (Slack desktop, Figma, Canva) are empty.
            Browsers and documents still come through.
    """
    if not isinstance(status, dict):
        return []
    issues: List[Dict[str, str]] = []
    denied = [b for b, v in (status.get("automation") or {}).items() if v == "denied"]
    if denied:
        names = ", ".join(_APP_NAMES.get(b, b) for b in sorted(denied))
        issues.append({"severity": "red", "code": "automation_denied",
                       "message": f"Automation off for {names} — page/file names not captured"})
    if status.get("extension") == "not_seen":
        issues.append({"severity": "red", "code": "extension_off",
                       "message": "Browser extension not reporting"})
    if status.get("accessibility") == "missing" or status.get("capture_mode") == "no_accessibility":
        issues.append({"severity": "amber", "code": "accessibility_missing",
                       "message": "Limited capture: Accessibility missing — Slack/desktop app "
                                  "window titles not captured"})
    return issues


def device_needs_attention(status: Optional[Dict[str, Any]]) -> bool:
    return bool(permission_issues(status))
