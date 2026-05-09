"""
Match email metadata to clients using OrgCalendarRule (shared with calendar).

Two strategies:
  1. Direct domain rule: OrgCalendarRule with match_type='attendee_domain'
     where match_value matches MailSignal.other_party_domain. High confidence (0.95).
  2. Subject extract: fuzzy match against client name/aliases in subject text.
     Only populates subject_extract field when confidence >= 0.85 (privacy
     guarantee per MailSignal model docstring). Medium confidence (0.80).

Returns (matched_client, confidence, method, subject_extract).
subject_extract is the trimmed subject if and only if subject extraction
fired with confidence >= 0.85; empty string otherwise.

CRITICAL — pass `clients` argument to avoid the N+1 query bug present in
calendar_matching.py. The mail sync task pre-loads org clients ONCE and
passes the list in for every message.
"""
import re
import logging
from typing import Optional, Tuple, List

from tracker.models import Client, OrgCalendarRule

logger = logging.getLogger(__name__)


# Confidence thresholds
CONF_DIRECT_DOMAIN = 0.95
CONF_SUBJECT_EXTRACT = 0.85   # Threshold for subject_extract storage (privacy gate)
CONF_SUBJECT_FUZZY = 0.80

# Reuse the same stoplists as calendar_matching for consistency
PUBLIC_EMAIL_DOMAINS = {
    'outlook.com', 'gmail.com', 'hotmail.com', 'yahoo.com',
    'icloud.com', 'live.com', 'aol.com', 'me.com', 'msn.com',
}

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'with', 'meeting', 'call', 'check',
    'review', 'discussion', 'sync', 'fwd', 're', 'fw',
    'tax', 'audit', 'consult', 'consulting',
}

MIN_WORD_LEN = 4


def _normalize(s: str) -> str:
    if not s:
        return ''
    return re.sub(r'\s+', ' ', s.lower().strip())


# ─── Strategy 1: Direct domain rule ───────────────────────────────────────────

def match_by_domain_rule(
    other_party_domain: str,
    org,
    rules_cache: Optional[List] = None,
) -> Optional[Tuple[Client, float, str]]:
    """
    Check OrgCalendarRule entries with match_type='attendee_domain'.
    Despite the name (legacy from calendar), these rules represent
    'external party domain → client' mappings and apply to mail too.

    Args:
        other_party_domain: The MailSignal.other_party_domain value.
        org: Organization instance.
        rules_cache: Optional pre-loaded list of OrgCalendarRule rows
                     (avoids N+1 queries during bulk mail sync).

    Returns (client, confidence, method) or None.
    """
    if not other_party_domain:
        return None
    if other_party_domain.lower() in PUBLIC_EMAIL_DOMAINS:
        # Don't match @gmail.com to a client even if a (misconfigured) rule says so
        return None

    if rules_cache is None:
        rules = OrgCalendarRule.objects.filter(
            org=org,
            is_active=True,
            match_type='attendee_domain',
        ).select_related('target_client').order_by('-priority', 'id')
    else:
        rules = rules_cache

    domain_lower = other_party_domain.lower().lstrip('@')

    for rule in rules:
        if rule.match_type != 'attendee_domain':
            continue
        target = _normalize(rule.match_value).lstrip('@')
        if target and target == domain_lower:
            return (rule.target_client, CONF_DIRECT_DOMAIN, 'direct_domain')

    return None


# ─── Strategy 2: Subject fuzzy match ──────────────────────────────────────────

def _client_match_strings(client) -> List[Tuple[str, float]]:
    """Build (search_string, base_confidence) candidates for fuzzy matching."""
    candidates = []
    if client.name:
        name = _normalize(client.name)
        if len(name) >= MIN_WORD_LEN:
            candidates.append((name, CONF_SUBJECT_EXTRACT))
    if client.code and len(client.code) >= 4:
        candidates.append((client.code.lower(), CONF_SUBJECT_EXTRACT))
    for alias in (client.aliases or []):
        alias_str = _normalize(alias)
        if len(alias_str) >= MIN_WORD_LEN:
            candidates.append((alias_str, CONF_SUBJECT_FUZZY))
    return candidates


def match_by_subject(
    subject: str,
    org,
    clients_cache: Optional[List] = None,
) -> Optional[Tuple[Client, float, str]]:
    """
    Match email subject text against client names/codes/aliases.
    Picks longest matching string (specificity wins).

    Args:
        subject: Raw email subject line.
        org: Organization instance.
        clients_cache: Optional pre-loaded list of Client rows.

    Returns (client, confidence, method) or None.
    """
    norm_subject = _normalize(subject)
    if not norm_subject or len(norm_subject) < MIN_WORD_LEN:
        return None

    # Strip common reply/forward prefixes for cleaner matching
    norm_subject = re.sub(r'^(re|fwd?|fw)\s*:\s*', '', norm_subject).strip()
    if not norm_subject:
        return None

    if clients_cache is None:
        clients = Client.objects.filter(org=org, is_active=True)
    else:
        clients = clients_cache

    best_match = None
    best_match_len = 0

    for client in clients:
        for search_str, base_conf in _client_match_strings(client):
            if search_str in STOPWORDS:
                continue

            if len(search_str) <= 6:
                pattern = r'\b' + re.escape(search_str) + r'\b'
                if not re.search(pattern, norm_subject):
                    continue
            else:
                if search_str not in norm_subject:
                    continue

            if len(search_str) > best_match_len:
                best_match = (client, base_conf, 'subject_fuzzy')
                best_match_len = len(search_str)

    return best_match


# ─── Orchestrator ─────────────────────────────────────────────────────────────

def find_mail_match(
    mail_dict,
    org,
    clients_cache: Optional[List] = None,
    rules_cache: Optional[List] = None,
) -> Tuple[Optional[Client], float, str, str]:
    """
    Run mail matching strategies. Returns:
        (client, confidence, method, subject_extract)

    subject_extract is the trimmed subject if confidence >= CONF_SUBJECT_EXTRACT
    (0.85), otherwise empty string. This honors MailSignal's privacy guarantee:
    we only store subject text when we're confident it cleanly identifies a
    known client.

    mail_dict expected keys:
        'other_party_domain' (str), 'subject' (str), 'direction' (str)

    Internal email (sender + recipient both in org's own domains) is NEVER
    matched — this filtering happens upstream in the sync task. By the time
    we reach this function, direction is 'in' or 'out' only.
    """
    domain = mail_dict.get('other_party_domain') or ''
    subject = mail_dict.get('subject') or ''

    # Strategy 1: domain rule (highest confidence)
    domain_match = match_by_domain_rule(domain, org, rules_cache=rules_cache)
    if domain_match:
        client, conf, method = domain_match
        # If we matched on domain AND a subject match would corroborate the
        # same client, populate subject_extract for the classifier signal boost.
        subject_match = match_by_subject(subject, org, clients_cache=clients_cache)
        subj_extract = ''
        if subject_match and subject_match[0].id == client.id:
            # Subject confirms — store the subject (capped at 255 chars per model)
            subj_extract = subject.strip()[:255]
        return (client, conf, method, subj_extract)

    # Strategy 2: subject fuzzy (no domain rule matched)
    subject_match = match_by_subject(subject, org, clients_cache=clients_cache)
    if subject_match:
        client, conf, method = subject_match
        # Only store subject_extract if confidence clears the privacy threshold
        subj_extract = subject.strip()[:255] if conf >= CONF_SUBJECT_EXTRACT else ''
        return (client, conf, method, subj_extract)

    return (None, 0.0, 'unmatched', '')