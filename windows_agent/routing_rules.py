"""
Org admin routing rules — HARD rules from org admins that force certain
windows/files to specific clients.

v1.4.0: Extracted from ai_client_switcher.py into its own module so the
inference engine's routing_rule_match collector can use it without
depending on the AIClientSwitcher class.

Example rules:
  - exe=UltraTax.exe                  → route_to_client(Internal-Tax)
  - title_contains "Slack"            → suppress
  - exe_family="quickbooks"           → route_to_client(QB-Bookkeeping)

Both the legacy AIClientSwitcher (for backwards compat) and the inference
engine's routing_rule_match collector read from the process-wide singleton
get_routing_engine(). Rule updates from sync flow to both paths via that
singleton.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import urllib.request
from typing import List, Optional

logger = logging.getLogger(__name__)


def _exe_family_matches(family: str, exe_l: str) -> bool:
    """Lazy import to avoid circular dependency at module load.
    Returns True if exe_l is in the given exe family per EXE_FAMILY_MAP
    defined in ai_client_switcher.py."""
    try:
        from windows_agent.ai_client_switcher import _exe_family_matches as _impl
    except ImportError:
        try:
            from ai_client_switcher import _exe_family_matches as _impl
        except ImportError:
            logger.warning(
                "_exe_family_matches not importable; exe_family rules will always miss"
            )
            return False
    return _impl(family, exe_l)


class OrgRoutingRuleEngine:
    """
    Evaluates per-org routing rules fetched from the backend.

    Rules are fetched via sync and passed in via update_rules().
    Call match() on every classification decision (now in the inference
    engine's routing_rule_match collector).
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
        self._rules = sorted(
            rules or [],
            key=lambda r: r.get('priority', 0),
            reverse=True,
        )
        logger.info(f"[ROUTING] OrgRoutingRuleEngine: {len(self._rules)} rules loaded")
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
                    f"[ROUTING] OrgRule fire: id={rule.get('id')} "
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
                logger.debug(f"[ROUTING] OrgRule fire telemetry failed: {e}")

        threading.Thread(target=_send, daemon=True).start()


# Process-wide singleton — inference collector and AIClientSwitcher share this.
_singleton: Optional[OrgRoutingRuleEngine] = None


def get_routing_engine() -> OrgRoutingRuleEngine:
    """Return the process-wide OrgRoutingRuleEngine singleton.

    Both the inference engine's routing_rule_match collector and the
    legacy AIClientSwitcher reference this same instance so rule updates
    from sync flow to both paths."""
    global _singleton
    if _singleton is None:
        _singleton = OrgRoutingRuleEngine()
    return _singleton