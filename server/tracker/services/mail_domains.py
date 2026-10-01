"""
Email domain → client mappings: the one place that reads and writes them.

Mail and calendar attribution both have a 0.95 strategy that reads
OrgCalendarRule(match_type='attendee_domain'):

  * tracker/mail_matching.match_by_domain_rule   — MailSignal.other_party_domain
  * tracker/calendar_matching.match_by_direct_rule — CalendarEvent attendee domains

Until a settings screen existed that table had no API, no admin and no UI, so in
production it held zero rows and mail only matched when a client's name was
spelled out in the subject line. This module is shared by the Settings →
Email domains API (views_mail_domains.py) and the `mail_domains` management
command, so the two cannot drift.

Decisions worth knowing before changing anything here:

SUBDOMAINS ARE NOT COVERED. A mapping is an EXACT domain match — `acme.com`
does not match `mail.acme.com`. That is what both matchers do today (string
equality after lower-casing), and this module keeps it rather than widening
the matchers: a parent mapping would silently swallow every subdomain under a
shared parent (`state.pa.us`, a university, a hosting provider), and the
observed list already shows each subdomain on its own row, so an admin can map
the ones they mean. Changing this means changing BOTH matchers and the rematch
filter below together.

PUBLIC DOMAINS CANNOT BE MAPPED. The matcher refuses its own small list at
match time; validation here refuses that list plus the wider free-mail list
alias derivation uses (comcast.net, protonmail.com…). A rule on either would be
dead or wrong: everyone shares the domain, it identifies nobody.

THE FIRM'S OWN DOMAIN CANNOT BE MAPPED. Internal mail is dropped at sync, but
the firm's domain still shows up in calendar attendee lists; mapping it to a
client would stamp that client on every internal meeting.

SUGGESTIONS ARE NEVER APPLIED. `suggest_client` returns one confident client or
nothing. A tier that finds two candidates returns nothing — it does not fall
through to a weaker tier, because a weaker tier that "breaks the tie" is
exactly how a same-name client family gets the wrong one.

REMATCH IS A CELERY TASK. Mail sync is a delta query: a stored message is never
resent, so a new rule only reaches past mail if the stored rows are re-matched.
`rematch_mail_domain` walks with keyset_chunks, not .iterator() — the loop
writes, and Neon's pooler kills a named cursor on the first write.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, Optional

from celery import shared_task
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from tracker.models import (
    CalendarEvent, Client, IgnoredEmailDomain, MailSignal, OrgCalendarRule,
    Organization, OrganizationMembership, UserIntegration,
)
from tracker.services.alias_derivation import (
    FREE_EMAIL_DOMAINS, STOP_TOKENS, UNSAFE_SINGLE_TOKENS,
    _strip_corp_suffix, _strip_possessives,
)
from tracker.services import mail_domain_noise as noise
from tracker.tasks_mail import PUBLIC_EMAIL_DOMAINS as _MATCHER_PUBLIC_DOMAINS

logger = logging.getLogger(__name__)

MATCH_TYPE = 'attendee_domain'
DEFAULT_WINDOW_DAYS = 90
MATCH_FLOOR = 0.70  # same floor both sync paths apply before storing a client

# The matcher's list plus alias derivation's wider free-mail list.
PUBLIC_DOMAINS = frozenset(_MATCHER_PUBLIC_DOMAINS) | frozenset(FREE_EMAIL_DOMAINS)

# Two-level public suffixes common enough in a US/UK/AU client book to matter
# for picking the registrable label. Not a full PSL — a miss only means a
# suggestion is not offered.
_TWO_LEVEL_SUFFIXES = frozenset({
    'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'ltd.uk', 'plc.uk', 'me.uk',
    'com.au', 'net.au', 'org.au', 'co.nz', 'org.nz', 'co.za', 'com.br',
    'co.in', 'co.jp', 'com.mx', 'com.sg', 'com.hk',
})

# Labels that can never identify ONE client by themselves.
_GENERIC_LABELS = (
    frozenset(UNSAFE_SINGLE_TOKENS) | frozenset(STOP_TOKENS) | frozenset({
        'mail', 'email', 'info', 'office', 'online', 'web', 'site', 'home',
        'law', 'legal', 'cpa', 'cpas', 'tax', 'taxes', 'audit', 'accounting',
        'consulting', 'partners', 'holdings', 'capital', 'bank', 'insurance',
        'health', 'care', 'realty', 'properties', 'property', 'management',
        'tech', 'design', 'media', 'marketing', 'church', 'parish', 'school',
        'cemetery', 'catholic', 'diocese', 'center', 'centre', 'company',
        'corp', 'inc', 'llc', 'family', 'trust', 'foundation', 'associates',
        'construction', 'services', 'service', 'global', 'international',
        'state', 'county', 'city', 'town', 'township', 'borough', 'gov',
    })
)
MIN_LABEL_LEN = 4
MIN_TOKEN_LEN = 5  # the single-distinctive-token tier wants a longer word

_DOMAIN_RE = re.compile(
    r'^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$'
)


class DomainError(ValueError):
    """A domain or mapping request that cannot be honoured. str() is user-facing."""

    def __init__(self, message: str, code: str = 'invalid'):
        super().__init__(message)
        self.code = code


# ─── Normalization + validation ─────────────────────────────────────────────

def normalize_domain(raw: str) -> str:
    """'https://www.Acme.com/about', '@acme.com', 'jo@acme.com' → 'acme.com'.

    Returns '' for anything that does not leave a plausible domain behind.
    """
    s = (raw or '').strip().lower()
    s = re.sub(r'^[a-z][a-z0-9+.-]*://', '', s)   # scheme
    s = re.split(r'[/?#]', s, maxsplit=1)[0]       # path / query / fragment
    if '@' in s:
        s = s.rsplit('@', 1)[1]                    # an address, or '@acme.com'
    s = s.split(':', 1)[0]                         # port
    s = s.strip().strip('.')
    if s.startswith('www.'):
        s = s[4:]
    return s if _DOMAIN_RE.match(s) else ''


def org_own_domains(org) -> set[str]:
    """The firm's own (non-public) domains: its members' and mailboxes' addresses."""
    emails = list(
        OrganizationMembership.objects.filter(organization=org)
        .values_list('user__email', flat=True)
    ) + list(
        UserIntegration.objects.filter(org=org)
        .exclude(provider_email='')
        .values_list('provider_email', flat=True)
    )
    out = set()
    for e in emails:
        d = normalize_domain(e or '')
        if d and d not in PUBLIC_DOMAINS:
            out.add(d)
    return out


def _rules(org):
    return OrgCalendarRule.objects.filter(org=org, match_type=MATCH_TYPE)


def _rule_domain(rule) -> str:
    return (rule.match_value or '').strip().lower().lstrip('@')


def validate_new_domain(org, raw: str, *, allow_existing: bool = False) -> str:
    """Normalize `raw` and refuse what can never be a working mapping."""
    domain = normalize_domain(raw)
    if not domain:
        raise DomainError(f"{(raw or '').strip()!r} doesn't look like an email domain "
                          f"(expected something like acme.com).")
    if domain in PUBLIC_DOMAINS:
        raise DomainError(
            f"{domain} is a public email provider. Everyone shares it, so it can't "
            f"identify a client.", code='public')
    if domain in org_own_domains(org):
        raise DomainError(
            f"{domain} is your firm's own domain. Mapping it would put a client on "
            f"every internal email and meeting.", code='own_domain')
    if not allow_existing:
        existing = next((r for r in _rules(org).filter(is_active=True)
                         .select_related('target_client')
                         if _rule_domain(r) == domain), None)
        if existing:
            raise DomainError(
                f"{domain} is already mapped to {existing.target_client.name}. "
                f"Remove that mapping first, or change its client.", code='duplicate')
    return domain


def _client_in_org(org, client_id) -> Client:
    try:
        return Client.objects.get(id=int(client_id), org=org)
    except (Client.DoesNotExist, TypeError, ValueError):
        raise DomainError(f"No client {client_id} in this organization.", code='client')


# ─── Mappings CRUD ──────────────────────────────────────────────────────────

@dataclass
class MappingChange:
    rule: Optional[OrgCalendarRule]
    domain: str
    created: bool = False
    previous_client_id: Optional[int] = None


def list_mappings(org, *, include_inactive: bool = False):
    qs = _rules(org).select_related('target_client').order_by('match_value')
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return list(qs)


def mapping_counts(org, domains: Iterable[str]) -> dict[str, dict]:
    """Per mapped domain: how many stored messages/events currently carry its client.

    Read live, so it shows a background rematch landing without any status row.
    """
    domains = [d for d in domains if d]
    if not domains:
        return {}
    out = {d: {'messages': 0, 'messages_attributed': 0} for d in domains}
    rows = (MailSignal.objects.filter(org=org, other_party_domain__in=domains)
            .values('other_party_domain')
            .annotate(n=Count('id'), attributed=Count('extracted_client')))
    for r in rows:
        d = (r['other_party_domain'] or '').lower()
        if d in out:
            out[d]['messages'] += r['n']
            out[d]['messages_attributed'] += r['attributed']
    return out


def create_mapping(org, raw_domain: str, client_id) -> MappingChange:
    """New domain → client rule. Refuses public/own/duplicate domains.

    An INACTIVE rule for the same domain (nothing in the product writes those,
    but the column exists) is reactivated rather than duplicated.
    """
    domain = validate_new_domain(org, raw_domain)
    client = _client_in_org(org, client_id)
    inactive = next((r for r in _rules(org).filter(is_active=False)
                     if _rule_domain(r) == domain), None)
    if inactive:
        prev = inactive.target_client_id
        inactive.target_client = client
        inactive.is_active = True
        inactive.match_value = domain
        inactive.save(update_fields=['target_client', 'is_active', 'match_value', 'updated_at'])
        return MappingChange(inactive, domain, created=True, previous_client_id=prev)
    rule = OrgCalendarRule.objects.create(
        org=org, match_type=MATCH_TYPE, match_value=domain,
        target_client=client, is_active=True,
    )
    return MappingChange(rule, domain, created=True)


def get_mapping(org, rule_id) -> OrgCalendarRule:
    try:
        return _rules(org).select_related('target_client').get(id=int(rule_id))
    except (OrgCalendarRule.DoesNotExist, TypeError, ValueError):
        raise DomainError("No such domain mapping.", code='not_found')


def update_mapping(org, rule_id, client_id) -> MappingChange:
    rule = get_mapping(org, rule_id)
    client = _client_in_org(org, client_id)
    prev = rule.target_client_id
    rule.target_client = client
    rule.is_active = True
    rule.save(update_fields=['target_client', 'is_active', 'updated_at'])
    return MappingChange(rule, _rule_domain(rule), previous_client_id=prev)


def map_domain(org, raw_domain: str, client_id) -> MappingChange:
    """Create, or re-point an existing mapping (the management command's --map)."""
    domain = validate_new_domain(org, raw_domain, allow_existing=True)
    existing = next((r for r in _rules(org) if _rule_domain(r) == domain), None)
    if existing:
        return update_mapping(org, existing.id, client_id)
    return create_mapping(org, domain, client_id)


def delete_mapping(org, rule_id) -> MappingChange:
    rule = get_mapping(org, rule_id)
    change = MappingChange(None, _rule_domain(rule), previous_client_id=rule.target_client_id)
    rule.delete()
    return change


def unmap_domain(org, raw_domain: str) -> Optional[MappingChange]:
    """Remove every rule for a domain (command --unmap). None if there was none."""
    domain = normalize_domain(raw_domain) or (raw_domain or '').strip().lower().lstrip('@')
    rules = [r for r in _rules(org) if _rule_domain(r) == domain]
    if not rules:
        return None
    prev = rules[0].target_client_id
    OrgCalendarRule.objects.filter(id__in=[r.id for r in rules]).delete()
    return MappingChange(None, domain, previous_client_id=prev)


# ─── Ignore list ────────────────────────────────────────────────────────────

def ignored_domains(org) -> list:
    """Ignored domains, or [] if the table does not exist yet.

    The migration that creates the table is applied by hand, and may land
    AFTER the code deploys. A missing table must cost the ignore list, not the
    whole screen — so the read runs in a savepoint and degrades to empty.
    """
    try:
        with transaction.atomic():
            return list(IgnoredEmailDomain.objects.filter(org=org).order_by('domain'))
    except Exception as e:  # ProgrammingError: relation does not exist
        logger.warning(f"[MAIL-DOMAINS] ignored-domain table unavailable: {e}")
        return []


def ignore_domain(org, raw_domain: str, user=None) -> IgnoredEmailDomain:
    domain = normalize_domain(raw_domain)
    if not domain:
        raise DomainError(f"{(raw_domain or '').strip()!r} doesn't look like an email domain.")
    try:
        with transaction.atomic():
            obj, _ = IgnoredEmailDomain.objects.get_or_create(
                org=org, domain=domain, defaults={'created_by': user},
            )
        return obj
    except IntegrityError:
        return IgnoredEmailDomain.objects.get(org=org, domain=domain)


def ignore_domains(org, raw_domains, user=None) -> tuple[list, list]:
    """Ignore several domains. ([IgnoredEmailDomain], [{domain, error}])."""
    done, failed = [], []
    for raw in raw_domains or []:
        try:
            done.append(ignore_domain(org, raw if isinstance(raw, str) else '', user=user))
        except DomainError as e:
            failed.append({'domain': raw, 'error': str(e)})
    return done, failed


def unignore_domain(org, ignore_id) -> bool:
    try:
        deleted, _ = IgnoredEmailDomain.objects.filter(org=org, id=int(ignore_id)).delete()
    except (TypeError, ValueError):
        return False
    return bool(deleted)


# ─── Observed domains ───────────────────────────────────────────────────────

def domain_activity(org, days: int = DEFAULT_WINDOW_DAYS) -> dict[str, dict]:
    """Every counterparty domain seen in the window, unfiltered.

    domain → {messages, inbound, outbound, events, users:set, last_seen,
    senders_known, senders_automated}. Mail from MailSignal.other_party_domain
    (all providers); calendar from each CalendarEvent's attendee domains (one
    event counts once per domain). `senders_*` count inbound rows that store a
    from_address (Gmail only) and how many of those are noreply@-style.
    """
    since = timezone.now() - timedelta(days=days)
    acc: dict[str, dict] = defaultdict(
        lambda: {'messages': 0, 'inbound': 0, 'outbound': 0, 'events': 0, 'users': set(),
                 'last_seen': None, 'senders_known': 0, 'senders_automated': 0})

    def touch(d, when):
        cur = acc[d]['last_seen']
        if when and (cur is None or when > cur):
            acc[d]['last_seen'] = when

    def norm(raw):
        return (raw or '').strip().lower().lstrip('@')

    mail = MailSignal.objects.filter(org=org, occurred_at__gte=since)
    mail_rows = (mail.values('other_party_domain', 'user_id', 'direction')
                 .annotate(n=Count('id'), last=Max('occurred_at')))
    for r in mail_rows:
        d = norm(r['other_party_domain'])
        if not d:
            continue
        acc[d]['messages'] += r['n']
        acc[d]['outbound' if r['direction'] == 'out' else 'inbound'] += r['n']
        acc[d]['users'].add(r['user_id'])
        touch(d, r['last'])

    sender_rows = (mail.filter(direction='in', from_address__isnull=False)
                   .exclude(from_address='')
                   .values('other_party_domain')
                   .annotate(known=Count('id'),
                             automated=Count('id', filter=Q(
                                 from_address__iregex=noise.AUTOMATED_LOCAL_PART_REGEX))))
    for r in sender_rows:
        d = norm(r['other_party_domain'])
        if d in acc:
            acc[d]['senders_known'] += r['known']
            acc[d]['senders_automated'] += r['automated']

    # Read-only walk; keyset paging anyway so it never holds a named cursor.
    from tracker.utils.db_iter import keyset_iter
    events = (CalendarEvent.objects.filter(org=org, start__gte=since)
              .only('id', 'user_id', 'start', 'attendees'))
    for ev in keyset_iter(events):
        seen = set()
        for a in ev.attendees or []:
            d = (a.get('domain') or '').strip().lower() if isinstance(a, dict) else ''
            if d and d not in seen:
                seen.add(d)
                acc[d]['events'] += 1
                acc[d]['users'].add(ev.user_id)
                touch(d, ev.start)
    return dict(acc)


# ─── Signal ranking + automated classification ──────────────────────────────
# What lives in which list is in mail_domain_noise.py; this is only the logic.

def classify_automated(domain: str, *, events: int = 0, outbound: int = 0,
                       senders_known: int = 0, senders_automated: int = 0
                       ) -> tuple[bool, str]:
    """(automated, reason). Never automated with a meeting or outbound mail."""
    if events > 0 or outbound > 0:
        return False, ''
    labels = [x for x in (domain or '').lower().split('.') if x]
    _label, registrable = split_domain(domain)
    if registrable and len(labels) > len(registrable.split('.')):
        if noise.is_automated_host_label(labels[0]):
            return True, f'Sent from a bulk-mail host ({labels[0]}.)'
    if registrable in noise.VENDOR_DOMAINS:
        return True, f'{registrable} is a known software or platform vendor'
    if (senders_known and senders_automated / senders_known > noise.AUTOMATED_LOCAL_PART_SHARE):
        return True, 'Mostly sent from no-reply or notification addresses'
    return False, ''


def signal_score(*, events: int = 0, outbound: int = 0, inbound: int = 0, users: int = 0) -> float:
    """How much a domain looks like a person or business the firm works with.

    Meetings and mail the firm SENT are strong; more firm members in touch
    with it is strong; inbound-only volume is weak and capped, so a newsletter
    that arrives daily (capped at 4) cannot outrank one meeting (10) or one
    message the firm sent (5).
    """
    return round(10.0 * events + 5.0 * outbound + 3.0 * max(users - 1, 0)
                 + 0.2 * min(inbound, 20), 2)


def observed_domains(org, days: int = DEFAULT_WINDOW_DAYS, limit: int = 200) -> list[dict]:
    """Domains seen but not mapped: excludes public, own, mapped and ignored.

    Each row carries `score` / `automated` / `automated_reason` and a
    `suggestion` ({client_id, client_name, reason, tier}) or None. Ordered
    non-automated first, then by score — strongest relationship at the top.
    """
    activity = domain_activity(org, days)
    own = org_own_domains(org)
    mapped = {_rule_domain(r) for r in list_mappings(org)}
    ignored = {i.domain for i in ignored_domains(org)}
    ctx = SuggestionContext.for_org(org)

    rows = []
    for d, a in activity.items():
        if (d in PUBLIC_DOMAINS or d in own or d in mapped or d in ignored
                or not _DOMAIN_RE.match(d)):
            continue
        automated, why = classify_automated(
            d, events=a['events'], outbound=a['outbound'],
            senders_known=a['senders_known'], senders_automated=a['senders_automated'])
        rows.append({
            'domain': d,
            'messages': a['messages'],
            'inbound': a['inbound'],
            'outbound': a['outbound'],
            'events': a['events'],
            'users': len(a['users']),
            'last_seen': a['last_seen'].isoformat() if a['last_seen'] else None,
            'score': signal_score(events=a['events'], outbound=a['outbound'],
                                  inbound=a['inbound'], users=len(a['users'])),
            'automated': automated,
            'automated_reason': why,
        })
    rows.sort(key=lambda r: (r['automated'], -r['score'],
                             -(r['messages'] + r['events']), r['domain']))
    rows = rows[:limit]
    for r in rows:
        r['suggestion'] = suggest_client(r['domain'], ctx)
    return rows


# ─── Suggestions ────────────────────────────────────────────────────────────

def split_domain(domain: str) -> tuple[str, str]:
    """'mail.acme-corp.co.uk' → ('acme-corp', 'acme-corp.co.uk').

    (registrable label, registrable domain). ('', '') if there is no label.
    """
    labels = [x for x in (domain or '').split('.') if x]
    if len(labels) < 2:
        return '', ''
    n = 3 if '.'.join(labels[-2:]) in _TWO_LEVEL_SUFFIXES and len(labels) >= 3 else 2
    reg = labels[-n:]
    return reg[0], '.'.join(reg)


def _compact(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _name_forms(name: str) -> set[str]:
    """Compact spellings a domain label could take for a client name/alias."""
    out = set()
    if not name:
        return out
    base = _strip_possessives(name)
    for v in {base, _strip_corp_suffix(base)}:
        v = re.sub(r'^\s*the\s+', '', v, flags=re.I)
        for w in {v.replace('&', ' '), v.replace('&', ' and ')}:
            c = _compact(w)
            if len(c) >= MIN_LABEL_LEN:
                out.add(c)
    return out


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r'[^a-z0-9]+', _strip_possessives(name or '').lower()) if t]


# ── Initials ──
# Generic words a firm puts next to its initials in a domain: df-cpas.com,
# dfcpas.com, cpa-df.com. Also left out of a client's own initials.
FIRM_SUFFIXES = ('accounting', 'partners', 'group', 'cpas', 'cpa', 'law', 'llp',
                 'llc', 'inc', 'pc', 'co')
# Legal-form words never contribute a letter ("Alpha Beta LLC" → ab).
_LEGAL_FORMS = frozenset({'llc', 'inc', 'ltd', 'llp', 'pllc', 'lp', 'pc', 'pa', 'plc',
                          'dds', 'incorporated', 'limited'})
# Kept in the WIDE variant only ("Alpha Beta Corp" → ab and abc).
_CORP_WORDS = frozenset({'corp', 'corporation', 'company', 'co'})
MIN_INITIALS = 2


def client_initials(name: str) -> set[str]:
    """Initials a domain might spell for a client name. Each is ≥2 letters.

    Two variants: without legal forms or firm words ("Dauphin & Fantacone
    CPAs" → df), and keeping firm words like Corp/Group/CPA ("Alpha Beta
    Corp" → abc as well as ab). Stop words and '&' never count; a numeric
    word contributes nothing.
    """
    words = [t for t in _tokens(name) if t not in STOP_TOKENS and t[0].isalpha()]
    out = set()
    core = ''.join(t[0] for t in words if t not in _LEGAL_FORMS and t not in FIRM_SUFFIXES
                   and t not in _CORP_WORDS)
    wide = ''.join(t[0] for t in words if t not in _LEGAL_FORMS)
    for ini in (core, wide):
        if len(ini) >= MIN_INITIALS:
            out.add(ini)
    return out


def _initials_candidates(label: str) -> set[str]:
    """Strings in a registrable label that could be a client's initials.

    'df-cpas' → {df}, 'dfcpas' → {dfcpas, df}, 'abc' → {abc}, 'cpa-df' → {df}.
    A preceding firm word is only recognised with a hyphen: stripping a
    joined prefix ('co' + 'as') invents too many accidental matches.
    """
    parts = [_compact(p) for p in (label or '').lower().split('-') if _compact(p)]
    if not parts:
        return set()
    whole = ''.join(parts)
    cands = {whole}
    if len(parts) >= 2 and parts[-1] in FIRM_SUFFIXES:
        cands.add(''.join(parts[:-1]))
    if len(parts) >= 2 and parts[0] in FIRM_SUFFIXES:
        cands.add(''.join(parts[1:]))
    for suf in FIRM_SUFFIXES:
        if whole.endswith(suf) and len(whole) > len(suf):
            cands.add(whole[:-len(suf)])
    return {c for c in cands
            if len(c) >= MIN_INITIALS and c.isalpha()
            and c not in FIRM_SUFFIXES and c not in _GENERIC_LABELS}


@dataclass
class SuggestionContext:
    clients: list            # [(id, name)]
    domain_owners: dict      # exact domain → {client ids}  (Client.email / aliases)
    form_owners: dict        # compact name form → {client ids}
    token_owners: dict       # name token → {client ids}
    names: dict              # id → name
    initials_owners: dict = None  # initials ('df') → {client ids}

    @classmethod
    def for_org(cls, org) -> 'SuggestionContext':
        rows = list(Client.objects.filter(org=org, is_active=True)
                    .values_list('id', 'name', 'email', 'aliases'))
        domain_owners, form_owners, token_owners = defaultdict(set), defaultdict(set), defaultdict(set)
        initials_owners = defaultdict(set)
        names = {}
        for cid, name, email, aliases in rows:
            names[cid] = name or ''
            d = normalize_domain(email or '') if email and '@' in email else ''
            if d and d not in PUBLIC_DOMAINS:
                domain_owners[d].add(cid)
            for alias in aliases or []:
                if not isinstance(alias, str):
                    continue
                ad = normalize_domain(alias) if '.' in alias else ''
                if ad and ad not in PUBLIC_DOMAINS:
                    domain_owners[ad].add(cid)
                else:
                    for f in _name_forms(alias):
                        form_owners[f].add(cid)
            for f in _name_forms(name or ''):
                form_owners[f].add(cid)
            for t in set(_tokens(name or '')):
                token_owners[t].add(cid)
            for ini in client_initials(name or ''):
                initials_owners[ini].add(cid)
        return cls(
            clients=[(cid, names[cid]) for cid, *_ in rows],
            domain_owners=dict(domain_owners), form_owners=dict(form_owners),
            token_owners=dict(token_owners), names=names,
            initials_owners=dict(initials_owners),
        )


def _one(ids, ctx, reason, tier):
    """The single client of a tier, or the string 'ambiguous'/None."""
    ids = set(ids or ())
    if len(ids) == 1:
        cid = next(iter(ids))
        return {'client_id': cid, 'client_name': ctx.names.get(cid, ''),
                'reason': reason, 'tier': tier}
    return 'ambiguous' if ids else None


def _strong_tiers(label: str, ctx: SuggestionContext):
    """Tiers 2 and 3: a suggestion dict, 'ambiguous', or None."""
    compact = _compact(label)
    if (len(compact) < MIN_LABEL_LEN or compact in _GENERIC_LABELS
            or label.replace('-', ' ').strip() in _GENERIC_LABELS):
        return None

    hit = _one(ctx.form_owners.get(compact), ctx, 'The domain name matches the client name',
               'name')
    if hit == 'ambiguous':
        return hit
    if hit:
        # Family guard: "Acme Corp" matches acme.com exactly, but if "Acme
        # Payroll LLC" is also a client the domain could be either of them.
        family = set()
        for form, ids in ctx.form_owners.items():
            if form.startswith(compact):
                family |= ids
        family |= ctx.token_owners.get(compact, set())
        return hit if family <= {hit['client_id']} else 'ambiguous'

    if len(compact) >= MIN_TOKEN_LEN and '-' not in label and not compact.isdigit():
        return _one(ctx.token_owners.get(compact), ctx,
                    'The domain name is a word only this client’s name contains', 'token')
    return None


def suggest_client(domain: str, ctx: SuggestionContext) -> Optional[dict]:
    """One confident client for a domain, or None. Never applied automatically.

    Tiers, strongest first. A tier with 2+ candidates ends the search with NO
    suggestion; it never falls through to a weaker tier to break the tie.
      1. The domain (or its registrable domain) is a client's email domain or
         is written in a client's aliases.
      2. The registrable label, compacted, IS a client's name or alias
         ('acme-corp.com' ↔ "Acme Corp, Inc."), and is not a generic word.
      3. The label is a single long name word that only ONE client's name
         contains ('pureadk.com' ↔ "PureADK Holdings"), not a generic word.
      4. Lowest: the label spells ONE client's initials, optionally with a
         firm word ('df-cpas.com' ↔ "Dauphin & Fantacone"). Reached only when
         tiers 1-3 found nothing at all; two clients with those initials →
         nothing.
    `tier` on the result is 'domain' / 'name' / 'token' / 'initials'.
    """
    domain = normalize_domain(domain)
    if not domain:
        return None
    label, registrable = split_domain(domain)

    hit = _one(ctx.domain_owners.get(domain, set()) | ctx.domain_owners.get(registrable, set()),
               ctx, 'This domain is in the client’s email address or aliases', 'domain')
    if hit:
        return None if hit == 'ambiguous' else hit

    hit = _strong_tiers(label, ctx)
    if hit:
        return None if hit == 'ambiguous' else hit

    owners = set()
    for cand in _initials_candidates(label):
        owners |= (ctx.initials_owners or {}).get(cand, set())
    if len(owners) == 1:
        cid = next(iter(owners))
        name = ctx.names.get(cid, '')
        return {'client_id': cid, 'client_name': name,
                'reason': f'The domain matches the initials of {name}', 'tier': 'initials'}
    return None


# ─── Rematch ────────────────────────────────────────────────────────────────

def rematch_mail(org, *, domain: Optional[str] = None, days: int = DEFAULT_WINDOW_DAYS,
                 apply: bool = True) -> dict:
    """Re-run find_mail_match over stored MailSignal rows.

    `domain` scopes to one counterparty domain (what a map/unmap needs);
    None walks every row in the window (the command's org-wide --rematch).
    Returns {'changed': Counter[(domain, client_name|None)], 'examples': [...]}.
    """
    from tracker.mail_matching import find_mail_match
    from tracker.utils.db_iter import keyset_chunks

    since = timezone.now() - timedelta(days=days)
    clients_cache = list(
        Client.objects.filter(org=org, is_active=True).only('id', 'name', 'code', 'aliases'))
    rules_cache = list(
        OrgCalendarRule.objects.filter(org=org, is_active=True, match_type=MATCH_TYPE)
        .select_related('target_client').order_by('-priority', 'id'))

    signals = MailSignal.objects.filter(org=org, occurred_at__gte=since)
    if domain:
        signals = signals.filter(other_party_domain__iexact=domain)

    changed: Counter = Counter()
    examples: list[str] = []
    # keyset_chunks, not .iterator(): this loop writes to the rows it walks,
    # and a named server-side cursor dies on the first write under Neon's
    # transaction pooler (see tracker/utils/db_iter.py).
    for page in keyset_chunks(signals.select_related('extracted_client')):
        for sig in page:
            # Outlook stores a subject only for an already-matched signal, so a
            # previously unmatched Outlook row has no subject to re-read; domain
            # rules are what this pass can newly apply. Gmail rows keep the full
            # subject, so they re-match on both.
            client, conf, _method, _subj = find_mail_match(
                mail_dict={
                    'other_party_domain': sig.other_party_domain,
                    'subject': sig.subject or sig.subject_extract or '',
                    'direction': 'in' if sig.direction == 'in' else 'out',
                },
                org=org, clients_cache=clients_cache, rules_cache=rules_cache,
            )
            new_client = client if (client and conf >= MATCH_FLOOR) else None
            if (new_client.id if new_client else None) == sig.extracted_client_id:
                continue
            changed[(sig.other_party_domain, new_client.name if new_client else None)] += 1
            if len(examples) < 10:
                examples.append(
                    f"  {sig.occurred_at:%Y-%m-%d} {sig.other_party_domain:30s} "
                    f"{(sig.extracted_client.name if sig.extracted_client else 'none')} "
                    f"→ {new_client.name if new_client else 'none'}")
            if apply:
                sig.extracted_client = new_client
                sig.save(update_fields=['extracted_client'])
    return {'changed': changed, 'examples': examples}


def rematch_calendar(org, domain: str, *, previous_client_id: Optional[int] = None,
                     days: int = DEFAULT_WINDOW_DAYS, apply: bool = True) -> int:
    """Re-match CalendarEvents that have an attendee on `domain`. Returns rows changed.

    Narrower than the mail pass on purpose. Calendar categories are not stored,
    so a category_label rule cannot be re-evaluated here; a blanket re-run
    would strip clients that a category rule set. So: a new match is written;
    a client is CLEARED only when no rule matches any more AND the event's
    client is the one the removed/re-pointed mapping used to give it.
    """
    from tracker.calendar_matching import find_best_match
    from tracker.utils.db_iter import keyset_chunks

    since = timezone.now() - timedelta(days=days)
    events = CalendarEvent.objects.filter(
        org=org, start__gte=since, attendees__contains=[{'domain': domain}])
    n = 0
    for page in keyset_chunks(events.only(
            'id', 'title', 'attendees', 'extracted_client', 'extraction_confidence')):
        for ev in page:
            client, conf, _method = find_best_match(
                {'title': ev.title, 'attendees': ev.attendees or [], 'categories': []}, org)
            if client and conf >= MATCH_FLOOR:
                if client.id == ev.extracted_client_id:
                    continue
                ev.extracted_client, ev.extraction_confidence = client, conf
            elif previous_client_id and ev.extracted_client_id == previous_client_id:
                ev.extracted_client, ev.extraction_confidence = None, 0.0
            else:
                continue
            n += 1
            if apply:
                ev.save(update_fields=['extracted_client', 'extraction_confidence'])
    return n


@shared_task(name='tracker.rematch_mail_domain')
def rematch_mail_domain(org_id: int, domain: str, previous_client_id: Optional[int] = None):
    """Background re-match after a mapping for `domain` is added, changed or removed."""
    org = Organization.objects.filter(id=org_id).first()
    if not org or not domain:
        return {'status': 'skipped'}
    mail = rematch_mail(org, domain=domain, apply=True)
    events = rematch_calendar(org, domain, previous_client_id=previous_client_id, apply=True)
    total = sum(mail['changed'].values())
    logger.info(f"[MAIL-DOMAINS] org {org_id} {domain}: {total} message(s), "
                f"{events} event(s) re-matched")
    return {'status': 'ok', 'domain': domain, 'messages': total, 'events': events}


def queue_rematch(org, change: MappingChange) -> bool:
    """Enqueue the rematch once the mapping write commits. True if queued.

    If the broker is unreachable the rematch runs inline instead — it is
    scoped to one domain, so that is bounded — rather than leaving past mail
    silently unmatched.
    """
    org_id, domain, prev = org.id, change.domain, change.previous_client_id

    def _send():
        try:
            rematch_mail_domain.delay(org_id, domain, prev)
        except Exception as e:
            logger.warning(f"[MAIL-DOMAINS] broker unavailable ({e}); rematching {domain} inline")
            rematch_mail_domain(org_id, domain, prev)

    transaction.on_commit(_send)
    return True
