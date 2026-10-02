"""
Calendar meetings with no captured activity → proposed Daily Review entries.

THE GAP THIS CLOSES
-------------------
The calendar is not a time source. Stage 6 only LABELS blocks the agent already
captured, so a client call taken on the phone, in person, or with the laptop
idle produced no time at all. For a firm whose day is client calls that is the
biggest hole in the record.

WHAT IT DOES
------------
For each user with a connected calendar, in an org with
`calendar_classification_enabled`:

  1. Selection. Finished (end in the past, within LOOKBACK), timed (not
     all-day), not declined, not free/out-of-office events with at least one
     EXTERNAL attendee — someone outside the firm's own domains and not a
     firm member. Cancelled events are already deleted at sync, by both
     providers. Internal meetings are firm overhead and stay out.
  2. Gap check. If the agent's own non-idle blocks cover >= 20% of the event,
     the meeting happened at the computer and Stage 6 labels that time. Below
     that it happened off-computer: fill ONLY the minutes no live block covers
     (idle gaps count as uncovered). Never overlap a non-idle block, never
     overlap another calendar entry.
  3. Create one `proposed` Block per uncovered stretch.

REPRESENTATION (no migration)
-----------------------------
A plain Block, the same row every other surface already reads:

  device_id='calendar', hostname='calendar', bundle_id='__calendar__',
  app_name='Calendar', title/window_title = the event title,
  attendees = the external attendee addresses,
  hints = {source: 'calendar', calendar_provider, calendar_external_id, ...}
  classification_state='proposed', is_categorized=False

`proposed` + is_categorized=False is exactly the state the Reports/Daily
Review single source of truth (services.billing_totals, views_reports.
is_pending_review_block) treats as Needs-Review: shown in Needs You, never in
billable/non-billable totals until a person confirms it. `proposed` also keeps
it away from every automatic classifier (the post_save signal, the 5-minute AI
sweep and compact-and-classify only touch `captured`); second-pass and
compaction exclude it explicitly by device_id.

The event is referenced by (provider, external_id), NOT CalendarEvent.pk: a
Google 410 wipes and re-inserts the user's events with new primary keys.

LIFECYCLE
---------
  * Idempotent: an event's entries are found by that reference and updated in
    place; a re-run with nothing changed writes nothing.
  * The event moves → its still-unconfirmed entries move with it.
  * The event is deleted / declined / turns internal → unconfirmed entries are
    removed (hard delete: a never-confirmed proposal with no raw events).
  * Confirmed (committed) entries are the user's record and are never touched.
  * Dismissed (soft-deleted via the Dismiss button, or suppressed) → that event
    never produces an entry again.

GATE
----
Reuses `Organization.calendar_classification_enabled` rather than a new flag:
the semantics are the same opt-in — "let my calendar shape my time" — and a
second switch would let an org get calendar-born rows in Needs You while Stage
6 ignores the same calendar for captured time, which nobody would expect.
Default stays off; orgs with it off see no change at all.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable, Optional

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

CALENDAR_DEVICE_ID = 'calendar'
CALENDAR_HOSTNAME = 'calendar'
CALENDAR_BUNDLE_ID = '__calendar__'
CALENDAR_APP_NAME = 'Calendar'
CALENDAR_SOURCE = 'calendar'

LOOKBACK = timedelta(days=2)
# Agent-captured non-idle activity covering at least this share of the event
# means the person was (also) at the computer. Below it, every uncovered
# stretch of MIN_SEGMENT_MINUTES+ is proposed; at or above it, only stretches
# of BUSY_GAP_MIN_MINUTES+ are. A hard cut-off here used to drop the whole
# meeting: 10 min of email in an hour proposed 50 min, 13 min proposed none.
COVERAGE_THRESHOLD = 0.20
# Stretches shorter than this are immaterial (the same 2-minute floor the
# billing totals use) and are not proposed.
MIN_SEGMENT_MINUTES = 2
# While the computer was busy during a meeting, a short gap is a pause between
# tasks, not meeting time; only a sustained one is worth asking about.
BUSY_GAP_MIN_MINUTES = 10
# A day-long "meeting" is a calendar placeholder (a conference, a hold), not time.
MAX_EVENT_MINUTES = 6 * 60   # past this the reports' anomaly guard drops it anyway

PROPOSED_CONFIDENCE = 0.60   # below every auto-commit threshold
_RESOURCE_DOMAIN_SUFFIXES = ('resource.calendar.google.com', 'group.calendar.google.com')


# ─── Identity ────────────────────────────────────────────────────────────────

def is_calendar_block(block) -> bool:
    """True for a Block this module created (never for the macOS Calendar app)."""
    if (getattr(block, 'device_id', '') or '') != CALENDAR_DEVICE_ID:
        return False
    hints = getattr(block, 'hints', None) or {}
    return isinstance(hints, dict) and hints.get('source') == CALENDAR_SOURCE


def event_key(ev) -> tuple[str, str]:
    return (ev.provider or '', ev.external_id or '')


def _block_key(b) -> tuple[str, str]:
    h = b.hints or {}
    return (h.get('calendar_provider') or '', h.get('calendar_external_id') or '')


def _is_pending(b) -> bool:
    """Still an unconfirmed proposal — the only state we may move or remove."""
    return (b.deleted_at is None
            and b.classification_state == 'proposed'
            and not b.is_categorized
            and (b.categorized_by or '') not in ('manual', 'correction'))


def _is_dismissed(b) -> bool:
    return b.deleted_at is not None or b.classification_state == 'suppressed'


# ─── Attendees ───────────────────────────────────────────────────────────────

def _attendee_email(a) -> str:
    if isinstance(a, dict):
        return (a.get('email') or '').strip().lower()
    if isinstance(a, str):
        return a.strip().lower()
    return ''


def _attendee_response(a) -> str:
    return (a.get('response') or '').strip() if isinstance(a, dict) else ''


def firm_identity(org) -> tuple[set[str], set[str]]:
    """(own domains, member email addresses) — who counts as 'inside the firm'."""
    from tracker.models import OrganizationMembership, UserIntegration
    from tracker.services.mail_domains import org_own_domains
    emails = {
        (e or '').strip().lower()
        for e in list(OrganizationMembership.objects.filter(organization=org)
                      .values_list('user__email', flat=True))
        + list(UserIntegration.objects.filter(org=org).exclude(provider_email='')
               .values_list('provider_email', flat=True))
        if e
    }
    return org_own_domains(org), emails


def external_attendees(ev, own_domains: set[str], member_emails: set[str]) -> list[str]:
    """Attendee addresses that are outside the firm, in calendar order."""
    out = []
    for a in ev.attendees or []:
        email = _attendee_email(a)
        if '@' not in email or email in member_emails:
            continue
        domain = email.rsplit('@', 1)[1]
        if domain in own_domains or domain.endswith(_RESOURCE_DOMAIN_SUFFIXES):
            continue
        if email not in out:
            out.append(email)
    return out


# A solo appointment ("Derek Baker", a telehealth slot, a client call booked
# on your own calendar) has no outside attendee to go on, but its title names
# the client. calendar_matching scores a client name or code in the title at
# 0.80 and an alias at 0.75; only the name/code tier is strong enough to
# propose time from a calendar entry nobody else is on.
TITLE_CLIENT_MIN_CONFIDENCE = 0.80


def _other_attendees(ev, self_emails: set[str]) -> list[str]:
    """Attendee addresses other than the user (any domain)."""
    out = []
    for a in ev.attendees or []:
        email = _attendee_email(a)
        if email and email not in self_emails and email not in out:
            out.append(email)
    return out


def names_client_alone(ev, self_emails: set[str]) -> bool:
    """True for an event only the user is on whose title names a client."""
    return (bool(getattr(ev, 'extracted_client_id', None))
            and (ev.extraction_confidence or 0.0) >= TITLE_CLIENT_MIN_CONFIDENCE
            and not _other_attendees(ev, self_emails))


def _self_declined(ev, self_emails: set[str]) -> bool:
    for a in ev.attendees or []:
        if _attendee_email(a) in self_emails and _attendee_response(a) == 'declined':
            return True
    return False


# ─── Interval arithmetic ─────────────────────────────────────────────────────

def _merge(intervals: Iterable[tuple]) -> list[tuple]:
    out: list[list] = []
    for s, e in sorted(i for i in intervals if i[0] < i[1]):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _clip(intervals, lo, hi) -> list[tuple]:
    return [(max(s, lo), min(e, hi)) for s, e in intervals if s < hi and e > lo]


def _covered_seconds(intervals, lo, hi) -> float:
    return sum((e - s).total_seconds() for s, e in _merge(_clip(intervals, lo, hi)))


def _subtract(lo, hi, occupied) -> list[tuple]:
    gaps, cur = [], lo
    for s, e in _merge(_clip(occupied, lo, hi)):
        if s > cur:
            gaps.append((cur, s))
        cur = max(cur, e)
    if cur < hi:
        gaps.append((cur, hi))
    return gaps


def _is_idle_block(b) -> bool:
    if (b.bundle_id or '').lower() == '__idle__':
        return True
    if (b.app_name or '').strip().lower() in ('idle', '__idle__'):
        return True
    cats = b.category_hours or {}
    if isinstance(cats, dict) and cats:
        dominant = max(cats.items(), key=lambda kv: kv[1] or 0)[0]
        if (dominant or '').strip().lower() == 'idle':
            return True
    return False


# ─── Selection ───────────────────────────────────────────────────────────────

def _on_time_off(org, user, ev) -> bool:
    from tracker.models import TimeOff
    d = timezone.localtime(ev.start).date()
    return TimeOff.objects.filter(org=org, user=user, start_date__lte=d, end_date__gte=d).exists()


def qualifies(ev, org, user, own_domains, member_emails, self_emails) -> tuple[bool, str]:
    """(ok, reason). Reason is for logs / the status command."""
    from tracker.calendar_timeoff import _looks_like_time_off
    if ev.is_all_day:
        return False, 'all_day'
    minutes = (ev.end - ev.start).total_seconds() / 60
    if minutes < MIN_SEGMENT_MINUTES or minutes > MAX_EVENT_MINUTES:
        return False, 'duration'
    show_as = (ev.show_as or '').lower()
    if show_as in ('free', 'oof'):
        return False, f'show_as_{show_as}'
    if _looks_like_time_off(ev.title, ev.show_as, ev.is_all_day):
        return False, 'time_off'
    if _self_declined(ev, self_emails):
        return False, 'declined'
    if not external_attendees(ev, own_domains, member_emails):
        # Colleagues-only meetings stay out (internal). A solo appointment
        # whose title names a client is client time with no one to invite.
        if not names_client_alone(ev, self_emails):
            return False, 'internal_only'
    if _on_time_off(org, user, ev):
        return False, 'time_off'
    return True, ''


# ─── Copy ────────────────────────────────────────────────────────────────────

def describe_attendees(emails: list[str], limit: int = 3) -> str:
    if not emails:
        return ''
    shown = ', '.join(emails[:limit])
    more = f" and {len(emails) - limit} more" if len(emails) > limit else ''
    return f"{shown}{more}"


def calendar_reasoning(title: str, attendees: list[str]) -> str:
    who = describe_attendees(attendees)
    with_part = f", with {who}" if who else ''
    return (f"From your calendar: “{(title or 'Untitled event')[:80]}”{with_part} "
            f"— no computer activity was captured.")


def calendar_block_facts(block) -> tuple[str, Optional[int], Optional[str]]:
    """(sentence, client_id, client_name) for the why/evidence surfaces."""
    attendees = [a for a in (block.attendees or []) if isinstance(a, str)]
    sentence = calendar_reasoning(block.window_title or block.title, attendees)
    cid = block.proposed_client_id or block.client_id
    name = None
    if cid:
        from tracker.models import Client
        name = Client.objects.filter(id=cid).values_list('name', flat=True).first()
    if not cid:
        domains = (block.hints or {}).get('attendee_domains') or []
        if domains:
            sentence += f" No client matched {', '.join(domains[:3])} — pick one if it was client work."
    return sentence, cid, name


# ─── Reconciliation ──────────────────────────────────────────────────────────

def _billable_category(org) -> str:
    from tracker.services.classification_service import (
        FALLBACK_CATEGORIES, FALLBACK_CATEGORIES_DEFAULT,
    )
    industry = getattr(org, 'industry_type', None) or 'general'
    return FALLBACK_CATEGORIES.get(industry, FALLBACK_CATEGORIES_DEFAULT)[0]


def _event_client(ev):
    return ev.extracted_client if (
        ev.extracted_client_id and (ev.extraction_confidence or 0) >= 0.70) else None


def busy_elsewhere_note(ev, agent_blocks, lo, hi) -> str:
    """When the computer was filed to a DIFFERENT client during the meeting,
    say so, so the person decides which story is true. Never moves that time:
    one stretch is never billed to two clients."""
    event_client_id = getattr(ev, 'extracted_client_id', None) if _event_client(ev) else None
    per_client: dict = {}
    for b in agent_blocks:
        cid = b.client_id or getattr(b, 'proposed_client_id', None)
        if not cid or cid == event_client_id:
            continue
        overlap = (min(b.end, hi) - max(b.start, lo)).total_seconds()
        if overlap > 0:
            per_client[cid] = per_client.get(cid, 0.0) + overlap
    if not per_client:
        return ''
    cid, secs = max(per_client.items(), key=lambda kv: kv[1])
    mins = int(round(secs / 60))
    if mins < 1:
        return ''
    from tracker.models import Client
    name = Client.objects.filter(id=cid).values_list('name', flat=True).first() or 'another client'
    target = ev.extracted_client.name if event_client_id and ev.extracted_client else 'this meeting'
    return (f" Your computer was on {name} for {mins} min during it — "
            f"add the rest to {target}?")


def _segment_fields(org, ev, attendees, start, end, category, note: str = '') -> dict:
    client = _event_client(ev)
    minutes = int(round((end - start).total_seconds() / 60))
    domains = sorted({a.rsplit('@', 1)[1] for a in attendees if '@' in a})
    reasoning = calendar_reasoning(ev.title, attendees)
    if note:
        reasoning = reasoning.replace(' — no computer activity was captured.', '.') + note
    signal = {
        'type': 'calendar_meeting',
        'strength': PROPOSED_CONFIDENCE if client else 0.0,
        'evidence': reasoning[:200],
        'detail': {
            'event_id': ev.id,
            'provider': ev.provider,
            'client_id': client.id if client else None,
            'match_confidence': ev.extraction_confidence or 0.0,
            'attendee_domains': domains,
        },
    }
    return {
        'start': start,
        'end': end,
        'minutes': minutes,
        'title': (ev.title or 'Calendar event')[:1000],
        'window_title': (ev.title or 'Calendar event')[:1000],
        'attendees': attendees[:30],
        'description': '',
        'client_id': client.id if client else None,
        'proposed_client_id': client.id if client else None,
        'proposed_confidence': PROPOSED_CONFIDENCE if client else 0.0,
        'proposed_category': category,
        'proposed_reasoning': reasoning,
        'proposed_signals': [signal],
        'is_billable': bool(client),
        'category_hours': {category: round(minutes / 60.0, 2)} if client else {},
    }


def _apply_fields(b, fields: dict) -> bool:
    changed = False
    for k, v in fields.items():
        if getattr(b, k) != v:
            setattr(b, k, v)
            changed = True
    return changed


def reconcile_event(org, user, ev, attendees, existing, agent_blocks, other_calendar_blocks,
                    category, now) -> dict:
    """Bring one event's calendar entries in line with what it should produce.

    `existing` — every calendar Block (incl. soft-deleted) carrying this event's key.
    `agent_blocks` — the user's live, non-idle, non-calendar blocks near the event.
    `other_calendar_blocks` — live calendar blocks of OTHER events (occupied time).
    """
    from tracker.models import Block

    stats = {'created': 0, 'updated': 0, 'removed': 0}
    pending = sorted([b for b in existing if _is_pending(b)], key=lambda b: b.start)

    if any(_is_dismissed(b) for b in existing):
        # The person said this meeting doesn't belong in their time. Withdraw
        # anything still pending for it and never propose it again.
        for b in pending:
            b.delete()
            stats['removed'] += 1
        return stats

    lo, hi = ev.start, min(ev.end, now)
    event_seconds = (hi - lo).total_seconds()
    agent_iv = [(b.start, b.end) for b in agent_blocks]
    coverage = _covered_seconds(agent_iv, lo, hi) / event_seconds if event_seconds > 0 else 1.0

    # Fill only the minutes nothing else accounts for. When the computer was
    # mostly idle, every stretch of 2+ min; when it was busy, only sustained
    # gaps of 10+ min — and say what the computer was doing meanwhile.
    busy = coverage >= COVERAGE_THRESHOLD
    min_seg = BUSY_GAP_MIN_MINUTES if busy else MIN_SEGMENT_MINUTES
    confirmed_same = [(b.start, b.end) for b in existing
                      if not _is_pending(b) and not _is_dismissed(b)]
    occupied = agent_iv + [(b.start, b.end) for b in other_calendar_blocks] + confirmed_same
    desired: list[tuple] = [(s, e) for s, e in _subtract(lo, hi, occupied)
                            if (e - s).total_seconds() >= min_seg * 60]
    note = busy_elsewhere_note(ev, agent_blocks, lo, hi) if desired else ''

    hints_base = {
        'source': CALENDAR_SOURCE,
        'calendar_provider': ev.provider,
        'calendar_external_id': ev.external_id,
        'calendar_event_id': ev.id,
        'attendee_domains': sorted({a.rsplit('@', 1)[1] for a in attendees if '@' in a}),
    }

    for i, (s, e) in enumerate(desired):
        fields = _segment_fields(org, ev, attendees, s, e, category, note)
        hints = dict(hints_base, segment=i)
        if i < len(pending):
            b = pending[i]
            changed = _apply_fields(b, fields)
            if b.hints != hints:
                b.hints = hints
                changed = True
            if changed:
                b.save(force_classifier=True)
                stats['updated'] += 1
        else:
            Block.objects.create(
                org=org, user=user,
                device_id=CALENDAR_DEVICE_ID, hostname=CALENDAR_HOSTNAME,
                app_name=CALENDAR_APP_NAME, bundle_id=CALENDAR_BUNDLE_ID,
                hints=hints,
                classification_state='proposed',
                state_changed_at=now, state_changed_by='classifier',
                proposed_at=now,
                is_categorized=False,
                **fields,
            )
            stats['created'] += 1

    for b in pending[len(desired):]:
        b.delete()
        stats['removed'] += 1
    return stats


def _calendar_blocks_qs(user):
    from tracker.models import Block
    return Block.all_objects.filter(
        user=user, device_id=CALENDAR_DEVICE_ID, hints__source=CALENDAR_SOURCE,
    )


def propose_for_user(org, user, now=None) -> dict:
    """Run the whole pipeline for one user. Safe to call repeatedly."""
    from tracker.models import Block, CalendarEvent, UserIntegration

    now = now or timezone.now()
    window_start = now - LOOKBACK
    stats = {'events': 0, 'qualified': 0, 'created': 0, 'updated': 0, 'removed': 0,
             'skipped': {}}

    if not getattr(org, 'calendar_classification_enabled', False):
        stats['disabled'] = True
        return stats

    own_domains, member_emails = firm_identity(org)
    self_emails = {(user.email or '').strip().lower()} | {
        (e or '').strip().lower() for e in UserIntegration.objects.filter(
            user=user, provider__in=('google_calendar', 'microsoft_calendar'),
        ).values_list('provider_email', flat=True) if e
    }
    self_emails.discard('')
    category = _billable_category(org)

    events = list(
        CalendarEvent.objects.filter(
            org=org, user=user, end__lte=now, end__gte=window_start,
        ).select_related('extracted_client').order_by('start', 'id')
    )
    stats['events'] = len(events)

    span_lo = min([window_start] + [e.start for e in events]) - timedelta(hours=1)
    cal_blocks = list(_calendar_blocks_qs(user).filter(end__gte=span_lo))
    by_key: dict = {}
    for b in cal_blocks:
        by_key.setdefault(_block_key(b), []).append(b)

    agent_blocks_all = [
        b for b in Block.objects.filter(
            user=user, deleted_at__isnull=True, start__lt=now, end__gt=span_lo,
        ).exclude(device_id=CALENDAR_DEVICE_ID).exclude(classification_state='suppressed')
        .only('id', 'start', 'end', 'bundle_id', 'app_name', 'category_hours')
        if b.start and b.end and not _is_idle_block(b)
    ]

    seen_keys = set()
    with transaction.atomic():
        for ev in events:
            key = event_key(ev)
            ok, why = qualifies(ev, org, user, own_domains, member_emails, self_emails)
            if not ok:
                stats['skipped'][why] = stats['skipped'].get(why, 0) + 1
                continue
            seen_keys.add(key)
            stats['qualified'] += 1
            attendees = external_attendees(ev, own_domains, member_emails)
            agent_near = [b for b in agent_blocks_all if b.start < ev.end and b.end > ev.start]
            others = [
                b for k, bs in by_key.items() if k != key for b in bs
                if b.deleted_at is None and b.classification_state != 'suppressed'
                and b.start < ev.end and b.end > ev.start
            ]
            existing = by_key.get(key, [])
            r = reconcile_event(org, user, ev, attendees, existing, agent_near, others,
                                category, now)
            for k in ('created', 'updated', 'removed'):
                stats[k] += r[k]
            if r['created'] or r['updated'] or r['removed']:
                # Refresh this key so later events see the new occupancy.
                by_key[key] = list(_calendar_blocks_qs(user).filter(
                    hints__calendar_provider=key[0], hints__calendar_external_id=key[1]))

        # Entries whose event no longer qualifies (deleted, declined, moved
        # into the future, turned internal). An event that merely aged out of
        # the lookback window still exists and is left alone.
        for key, bs in by_key.items():
            if key in seen_keys:
                continue
            pending = [b for b in bs if _is_pending(b)]
            if not pending:
                continue
            ev = CalendarEvent.objects.filter(
                user=user, provider=key[0], external_id=key[1]).first()
            if ev is not None and ev.end < window_start:
                continue
            if ev is not None and ev.end <= now:
                ok, _why = qualifies(ev, org, user, own_domains, member_emails, self_emails)
                if ok:
                    continue
            for b in pending:
                b.delete()
                stats['removed'] += 1

    return stats


# ─── Celery ──────────────────────────────────────────────────────────────────

def _eligible_users():
    """(org, user) pairs with a connected calendar in an opted-in org."""
    from tracker.models import UserIntegration
    seen = set()
    for integ in (UserIntegration.objects
                  .filter(provider__in=('google_calendar', 'microsoft_calendar'),
                          is_connected=True, org__calendar_classification_enabled=True)
                  .select_related('org', 'user')):
        k = (integ.org_id, integ.user_id)
        if k in seen:
            continue
        seen.add(k)
        yield integ.org, integ.user


@shared_task(name='tracker.propose_calendar_meetings_all')
def propose_calendar_meetings_all():
    """Beat entry (every 30 min): fan out one task per eligible user."""
    n = 0
    for org, user in _eligible_users():
        propose_calendar_meetings_for_user.delay(org.id, user.id)
        n += 1
    logger.info(f"[CAL-MEET] dispatched {n} user(s)")
    return {'dispatched': n}


@shared_task(name='tracker.propose_calendar_meetings_for_user')
def propose_calendar_meetings_for_user(org_id, user_id):
    from django.contrib.auth import get_user_model
    from tracker.models import Organization
    org = Organization.objects.filter(id=org_id).first()
    user = get_user_model().objects.filter(id=user_id).first()
    if not org or not user:
        return {'status': 'skipped'}
    try:
        stats = propose_for_user(org, user)
    except Exception as e:
        logger.exception(f"[CAL-MEET] failed for user {user_id}: {e}")
        return {'status': 'error', 'error': str(e)[:200]}
    if stats.get('created') or stats.get('updated') or stats.get('removed'):
        logger.info(f"[CAL-MEET] {user.username}: {stats}")
    return {'status': 'ok', **stats}


def after_calendar_sync(org, user):
    """Hook for the sync tasks: queue a run for this user if the org opted in.
    Best-effort — never raises into the sync."""
    try:
        if getattr(org, 'calendar_classification_enabled', False):
            propose_calendar_meetings_for_user.delay(org.id, user.id)
    except Exception as e:
        logger.warning(f"[CAL-MEET] could not queue after sync for {user.id}: {e}")
