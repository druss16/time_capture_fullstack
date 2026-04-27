"""
tracker/services/rules/matcher.py

Pure rule-matching logic. No Django imports — just rule dicts in, bool out.

WHY THIS EXISTS
---------------
Today the same matching logic is duplicated in 3 places:
  1. windows_agent/ai_client_switcher.py  (OrgRoutingRuleEngine._rule_matches)
  2. server/tracker/views_routing_rules.py (_rule_matches)
  3. server/tracker/views_mavops.py        (_mavops_rule_matches)

This module is the single source of truth. The other 3 should call it
(via subprocess for the agent, or import for the backend) — eventually.

For now: this module is the canonical implementation. The other 3 must
mirror its behavior exactly. When you change matching logic, change it
here AND verify the other 3 match.

USAGE
-----
    from tracker.services.rules.matcher import rule_matches, build_context

    ctx = build_context(
        title="UltraTax CS - 1040 [SMITH, JOHN]",
        exe="utw25.exe",
        file_path="Z:\\Clients\\Smith\\1040.pdf",
        duration_minutes=180,
    )
    if rule_matches(rule_dict, ctx):
        # apply the rule
        ...
"""

import re
from typing import Optional


# -----------------------------------------------------------------------------
# Exe family registry — must match windows_agent/ai_client_switcher.py
# -----------------------------------------------------------------------------

EXE_FAMILIES = {
    'taxwise':     ['utw', 'taxwise', 'tww'],
    'ultratax':    ['uts', 'ultratax', 'utw'],
    'lacerte':     ['lacerte', 'lacertepro'],
    'proseries':   ['proseries', 'ps'],
    'drake':       ['drake'],
    'quickbooks':  ['qbw', 'qb', 'quickbooks'],
    'excel':       ['excel'],
    'word':        ['winword'],
    'powerpoint':  ['powerpnt'],
    'outlook':     ['outlook', 'olk'],
    'chrome':      ['chrome'],
    'edge':        ['msedge'],
    'firefox':     ['firefox'],
    'teams':       ['teams', 'ms-teams'],
    'slack':       ['slack'],
    'zoom':        ['zoom'],
}


def exe_family_matches(family_key: str, exe_name: str) -> bool:
    """Given 'taxwise' and 'utw25.exe', return True."""
    if not exe_name:
        return False
    prefixes = EXE_FAMILIES.get((family_key or '').lower(), [(family_key or '').lower()])
    exe_low = exe_name.lower().replace('.exe', '').strip()
    return any(exe_low.startswith(p) for p in prefixes if p)


# -----------------------------------------------------------------------------
# Context builder
# -----------------------------------------------------------------------------

def build_context(
    title: str = '',
    exe: str = '',
    file_path: str = '',
    app_name: str = '',
    duration_minutes: Optional[int] = None,
    is_inside_meeting: bool = False,
    has_attributed_client: bool = False,
    is_idle: bool = False,
    **extra,
) -> dict:
    """
    Build a context dict for matching.

    Extra kwargs are stored in the context for future match types
    we haven't built yet — keeps the API extensible.
    """
    return {
        'title':                 title or '',
        'exe':                   exe or '',
        'file_path':             file_path or '',
        'app_name':              app_name or '',
        'duration_minutes':      duration_minutes,
        'is_inside_meeting':     bool(is_inside_meeting),
        'has_attributed_client': bool(has_attributed_client),
        'is_idle':               bool(is_idle),
        **extra,
    }


# -----------------------------------------------------------------------------
# Rule matchers — one function per match_type
# -----------------------------------------------------------------------------

def _match_exe(rule: dict, ctx: dict) -> bool:
    mv = (rule.get('match_value') or '').lower()
    exe_l = ctx['exe'].lower()
    return exe_l == mv or exe_l == f"{mv}.exe"


def _match_exe_family(rule: dict, ctx: dict) -> bool:
    return exe_family_matches(rule.get('match_value', ''), ctx['exe'])


def _match_title_contains(rule: dict, ctx: dict) -> bool:
    mv = (rule.get('match_value') or '').lower()
    return bool(mv) and mv in ctx['title'].lower()


def _match_title_regex(rule: dict, ctx: dict) -> bool:
    pattern = rule.get('match_value', '')
    if not pattern:
        return False
    try:
        return bool(re.search(pattern, ctx['title'] or '', re.IGNORECASE))
    except re.error:
        return False


def _match_file_path_contains(rule: dict, ctx: dict) -> bool:
    mv = (rule.get('match_value') or '').lower()
    return bool(mv) and mv in ctx['file_path'].lower()


def _match_duration_gt(rule: dict, ctx: dict) -> bool:
    """Block duration exceeds threshold_minutes."""
    threshold = rule.get('threshold_minutes')
    duration = ctx.get('duration_minutes')
    if threshold is None or duration is None:
        return False
    return duration > int(threshold)


def _match_inside_meeting(rule: dict, ctx: dict) -> bool:
    """Block is inside a meeting window with an attributed client."""
    return ctx.get('is_inside_meeting', False) and ctx.get('has_attributed_client', False)


def _match_idle_gt(rule: dict, ctx: dict) -> bool:
    """Idle duration exceeds threshold."""
    threshold = rule.get('threshold_minutes')
    duration = ctx.get('duration_minutes')
    if threshold is None or duration is None:
        return False
    return ctx.get('is_idle', False) and duration > int(threshold)


# Match-type → handler. Keep in sync with OrgRule.MATCH_TYPE_CHOICES
# and rule_templates.py templates' fixed.match_type values.
_MATCHERS = {
    'exe':                _match_exe,
    'exe_family':         _match_exe_family,
    'title_contains':     _match_title_contains,
    'title_regex':        _match_title_regex,
    'file_path_contains': _match_file_path_contains,
    'duration_gt':        _match_duration_gt,
    'inside_meeting':     _match_inside_meeting,
    'idle_gt':            _match_idle_gt,
}


def rule_matches(rule: dict, ctx: dict) -> bool:
    """
    Top-level entry point. Given a rule (as a dict, not a Django model)
    and a context dict, return True if the rule matches.

    Rule must have keys: match_type, match_value (and optional
    threshold_minutes for duration-based rules).
    """
    handler = _MATCHERS.get(rule.get('match_type'))
    if handler is None:
        return False
    try:
        return handler(rule, ctx)
    except Exception:
        # Defensive: a malformed rule should never crash the engine
        return False


# -----------------------------------------------------------------------------
# Rule serialization — convert ORM to matcher-compatible dict
# -----------------------------------------------------------------------------

def rule_to_dict(rule_obj) -> dict:
    """
    Convert an OrgRoutingRule ORM instance to the dict shape this matcher
    expects. Engines call this once per rule before matching.
    """
    return {
        'id':                rule_obj.id,
        'match_type':        rule_obj.match_type,
        'match_value':       rule_obj.match_value,
        'action':            rule_obj.action,
        'target_client_id':  rule_obj.target_client_id,
        'target_category':   getattr(rule_obj, 'target_category', None),
        'threshold_minutes': getattr(rule_obj, 'threshold_minutes', None),
        'flag_reason':       getattr(rule_obj, 'flag_reason', None),
        'priority':          rule_obj.priority,
        'category':          getattr(rule_obj, 'category', 'routing'),
        'runs_at':           getattr(rule_obj, 'runs_at', 'agent'),
    }