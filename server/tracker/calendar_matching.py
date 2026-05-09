"""
Match calendar events to clients using two strategies:
1. Direct mapping rules (OrgCalendarRule) — highest confidence (0.95)
2. Fuzzy title match against Client.name + code + aliases — medium (0.75-0.80)

Strategy 3 (attendee email domain) is configured via OrgCalendarRule
with match_type='attendee_domain' rather than auto-derived from clients.

Returns (matched_client, confidence, method) or (None, 0.0, 'unmatched').
"""
import re
import logging
from typing import Optional, Tuple, List

from tracker.models import Client, OrgCalendarRule

logger = logging.getLogger(__name__)


# Confidence weights per strategy
CONF_DIRECT = 0.95
CONF_FUZZY_TITLE = 0.80
CONF_FUZZY_ALIAS = 0.75

# Words to ignore in fuzzy matching (too generic)
STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'with', 'meeting', 'call', 'check',
    'review', 'discussion', 'sync', 'standup', 'weekly', 'monthly',
    'tax', 'audit', 'consult', 'consulting',
}

# Public email domains to ignore for direct domain rules
PUBLIC_EMAIL_DOMAINS = {
    'outlook.com', 'gmail.com', 'hotmail.com', 'yahoo.com',
    'icloud.com', 'live.com', 'aol.com', 'me.com', 'msn.com',
}

# Minimum word length for fuzzy matching (avoid matching "us" to "US Tax Corp")
MIN_WORD_LEN = 4


def _normalize(s: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    if not s:
        return ''
    return re.sub(r'\s+', ' ', s.lower().strip())


def _extract_external_domains(attendees: list) -> List[str]:
    """Extract unique external (non-public) email domains from attendees."""
    domains = set()
    for a in attendees or []:
        domain = (a.get('domain') or '').lower().strip()
        if domain and domain not in PUBLIC_EMAIL_DOMAINS:
            domains.add(domain)
    return list(domains)


# ─── Strategy 1: Direct mapping rules ─────────────────────────────────────────

def match_by_direct_rule(event_dict, org) -> Optional[Tuple[Client, float, str]]:
    """
    Check OrgCalendarRule entries in priority order.
    Returns (client, confidence, method) or None.
    """
    title = _normalize(event_dict.get('title') or event_dict.get('subject', ''))
    attendees = event_dict.get('attendees', [])
    domains = _extract_external_domains(attendees)
    categories = [c.lower() for c in (event_dict.get('categories') or [])]
    
    rules = OrgCalendarRule.objects.filter(
        org=org,
        is_active=True,
    ).select_related('target_client').order_by('-priority', 'id')
    
    for rule in rules:
        match_value = _normalize(rule.match_value)
        
        if rule.match_type == 'title_contains':
            if match_value and match_value in title:
                return (rule.target_client, CONF_DIRECT, 'direct_title')
        
        elif rule.match_type == 'title_pattern':
            try:
                if re.search(rule.match_value, title, re.IGNORECASE):
                    return (rule.target_client, CONF_DIRECT, 'direct_pattern')
            except re.error:
                logger.warning(f"[CAL-MATCH] Invalid regex in rule {rule.id}: {rule.match_value}")
                continue
        
        elif rule.match_type == 'attendee_domain':
            target_domain = match_value.lstrip('@').lower()
            if target_domain in domains:
                return (rule.target_client, CONF_DIRECT, 'direct_domain')
        
        elif rule.match_type == 'category_label':
            if match_value in categories:
                return (rule.target_client, CONF_DIRECT, 'direct_category')
    
    return None


# ─── Strategy 2: Fuzzy title match ────────────────────────────────────────────

def _client_match_strings(client) -> List[Tuple[str, float]]:
    """
    Build list of (search_string, confidence) pairs to match against title.
    Includes name, code (if distinctive), and aliases.
    """
    candidates = []
    
    if client.name:
        name = _normalize(client.name)
        if len(name) >= MIN_WORD_LEN:
            candidates.append((name, CONF_FUZZY_TITLE))
    
    if client.code and len(client.code) >= 4:
        candidates.append((client.code.lower(), CONF_FUZZY_TITLE))
    
    for alias in (client.aliases or []):
        alias_str = _normalize(alias)
        if len(alias_str) >= MIN_WORD_LEN:
            candidates.append((alias_str, CONF_FUZZY_ALIAS))
    
    return candidates


def match_by_fuzzy_title(event_dict, org) -> Optional[Tuple[Client, float, str]]:
    """
    Match event title against client names/codes/aliases.
    Picks longest matching string (specificity wins).
    """
    title = _normalize(event_dict.get('title') or event_dict.get('subject', ''))
    if not title or len(title) < MIN_WORD_LEN:
        return None
    
    clients = Client.objects.filter(org=org, is_active=True)
    
    best_match = None
    best_match_len = 0
    
    for client in clients:
        for search_str, base_conf in _client_match_strings(client):
            if search_str in STOPWORDS:
                continue
            
            # For short strings (≤6 chars), require word boundary match
            if len(search_str) <= 6:
                pattern = r'\b' + re.escape(search_str) + r'\b'
                if not re.search(pattern, title):
                    continue
            else:
                if search_str not in title:
                    continue
            
            # Specificity: longer match beats shorter
            if len(search_str) > best_match_len:
                best_match = (client, base_conf, 'fuzzy_title')
                best_match_len = len(search_str)
    
    return best_match


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def find_best_match(event_dict, org) -> Tuple[Optional[Client], float, str]:
    """
    Run all matching strategies in priority order.
    Returns (client, confidence, method).
    
    event_dict expected keys: 'title' (or 'subject'), 'attendees', 'categories'
    """
    direct = match_by_direct_rule(event_dict, org)
    if direct:
        return direct
    
    fuzzy = match_by_fuzzy_title(event_dict, org)
    if fuzzy:
        return fuzzy
    
    return (None, 0.0, 'unmatched')