"""
Push captured time into Clio as TimeEntry activities.

THE DOUBLE-BILLING PROBLEM
--------------------------
An attorney who already ran Clio's own timer has logged some of the same work
we captured. Pushing our version on top of theirs bills the client twice — the
failure that gets an integration uninstalled, and the same shape as the old
QuickBooks-chrome double count.

Clio activities carry a DATE and a DURATION but no start time, so overlap can
never be determined precisely: there is no way to know whether our 2–3pm block
is the hour they logged by hand. The only honest comparison is a total, per
(user, matter, day).

So push is a DELTA, not an append:

    delta = (everything we captured for that user/matter/day)
          - (everything already in Clio for that user/matter/day)

pushed as one entry, and skipped entirely when delta <= 0. That converges to
the right total no matter how many times it runs, and it never double-bills:

    run 1:  captured 3.5h, Clio has 2.0h (theirs)   -> push 1.5h, Clio = 3.5h
    run 2:  a new 1.0h block lands, Clio has 3.5h   -> push 1.0h, Clio = 4.5h
    run 3:  they log 1.0h by hand, Clio has 5.5h    -> push 0,    no change

Note that `captured` is the FULL day total, not just un-pushed blocks. Netting
un-pushed blocks against a Clio total that already contains our earlier push
would subtract our own work twice and silently under-bill. `clio_activity_id`
is therefore an audit trail, never an input to the arithmetic.

WHAT IS DELIBERATELY NOT PUSHED
-------------------------------
- Matters requiring UTBMS/LEDES codes. We have no codes to supply and Clio
  would 422. Surfaced as a skip reason rather than silently dropped.
- Flat-fee and contingency matters. Pushing hours there risks creating billable
  lines on a fixed-price engagement. Conservative until a firm asks for it.
- Closed matters, which reject new time.
- Blocks with no matter: Clio rejects a TimeEntry without one.

REQUEST BUDGET
--------------
Existing activities are fetched with ONE paginated scan of the window, then
bucketed in memory. Asking Clio per (user, matter, day) would cost hundreds of
requests against a 50/min ceiling and starve the writes that follow.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from tracker.integrations.clio.client import (
    ClioClient, ClioError, ClioValidationError,
)
from tracker.models import Block, Integration
from tracker.models_task_type_sets import ExternalMatterMapping, ExternalStaffMapping

logger = logging.getLogger(__name__)

# One level of nesting is Clio's limit; user{id}/matter{id} are what we bucket on.
ACTIVITY_FIELDS = 'id,date,quantity,type,note,user{id},matter{id}'
CREATED_FIELDS = 'id,date,quantity,type'

# Below this the delta is rounding noise, not work worth a line on a bill.
MIN_PUSH_MINUTES = 1

# Matter billing methods we refuse to push hours into. See module docstring.
UNPUSHABLE_BILLING_METHODS = {'flat', 'contingency'}
OPEN_MATTER_STATUSES = {'open', 'pending', ''}

SKIP_DETAIL = {
    'requires_utbms': 'Matter mandates UTBMS/LEDES codes, which TimeTracker does not yet supply.',
    'not_hourly': 'Matter bills as "{billing_method}" — pushing hours could create a '
                  'billable line on a fixed-price engagement.',
    'matter_closed': 'Matter is {status} and will not accept new time.',
    'already_in_clio': 'Clio already holds {already}m for this matter and day; we captured '
                       '{captured}m. Nothing to add.',
}


def _day_bounds(day, tz):
    """UTC window covering one local calendar day."""
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    return start, start + timedelta(days=1)


# Bare application chrome. On its own none of these describes work, and a bill
# line reading "Explorer" or "Word" tells a client nothing they would pay for.
_APP_CHROME = {
    'explorer', 'file explorer', 'windows explorer', 'finder',
    'word', 'microsoft word', 'excel', 'microsoft excel', 'outlook',
    'microsoft outlook', 'powerpoint', 'acrobat', 'adobe acrobat',
    'chrome', 'google chrome', 'edge', 'microsoft edge', 'firefox', 'safari',
    'new tab', 'untitled', 'document1', 'book1', '(no title)',
}


def _describe(block) -> str:
    """
    The best available description of one block's work, for a client's bill.

    Order matters. A human note beats anything captured. Failing that the
    window title carries the subject — "Marta Vance - File Explorer" — where
    `title` is often reduced to the application alone. Preferring `title`, as
    this did, put the word "Explorer" on a real invoice line.
    """
    for candidate in (block.notes, block.window_title, block.title):
        text = (candidate or '').strip()
        if text and text.lower() not in _APP_CHROME:
            return text
    return ''


def _note_for(blocks):
    """A human-readable note built from what was actually worked on."""
    seen, titles = set(), []
    for b in blocks:
        text = _describe(b)
        if text and text.lower() not in seen:
            seen.add(text.lower())
            titles.append(text)
    note = '; '.join(titles)
    return note[:500] if note else 'Captured by TimeTracker'


def decide_entry(captured_minutes, already_minutes, *, requires_utbms=False,
                 billing_method='', matter_status=''):
    """
    Decide what to do with one (user, matter, day) bucket. Pure — no I/O.

    Returns (action, minutes, reason) where action is 'push' or 'skip'.
    The guard order is deliberate: a matter that cannot legally take our time
    is rejected before we bother reasoning about how much time that is.

    Extracted so the arithmetic that prevents double-billing can be tested
    without a database or a Clio account.
    """
    if requires_utbms:
        return 'skip', captured_minutes, 'requires_utbms'
    if (billing_method or '').lower() in UNPUSHABLE_BILLING_METHODS:
        return 'skip', captured_minutes, 'not_hourly'
    if (matter_status or '').lower() not in OPEN_MATTER_STATUSES:
        return 'skip', captured_minutes, 'matter_closed'

    delta = captured_minutes - already_minutes
    if delta < MIN_PUSH_MINUTES:
        return 'skip', captured_minutes, 'already_in_clio'
    return 'push', delta, ''


def build_push_plan(integration: Integration, start_date, end_date, user_ids=None,
                    force_conflicts=None) -> dict:
    """
    Work out what WOULD be pushed. Reads Clio, writes nothing.

    This is the dry run the UI previews, and `execute_push` consumes the exact
    same plan — so what a firm confirms is what gets written.
    """
    from tracker.services.billing_totals import committed_block_qs
    from tracker.views_reports import _is_billable_block

    org = integration.organization
    tz = timezone.get_current_timezone()
    window_start, _ = _day_bounds(start_date, tz)
    _, window_end = _day_bounds(end_date, tz)

    api = ClioClient(integration)

    matter_by_project = {
        m.project_id: m for m in ExternalMatterMapping.objects.filter(integration=integration)
    }
    clio_user_by_user = {
        s.user_id: s.external_id for s in ExternalStaffMapping.objects.filter(integration=integration)
    }

    blocks = (
        committed_block_qs(org, window_start, window_end)
        .select_related('client', 'project', 'user')
    )
    if user_ids:
        blocks = blocks.filter(user_id__in=user_ids)

    # ── Bucket our own captured time ────────────────────────────────────
    groups = defaultdict(list)
    skipped = []

    for b in blocks:
        if not _is_billable_block(b):
            continue
        if not b.project_id:
            skipped.append({
                'block_id': b.id, 'minutes': b.minutes or 0,
                'reason': 'no_matter',
                'detail': 'Block has no matter — Clio rejects time without one.',
            })
            continue

        mapping = matter_by_project.get(b.project_id)
        if mapping is None:
            skipped.append({
                'block_id': b.id, 'minutes': b.minutes or 0,
                'reason': 'matter_not_synced',
                'detail': f'Project "{b.project}" is not linked to a Clio matter. Run a sync.',
            })
            continue

        clio_user_id = clio_user_by_user.get(b.user_id)
        if not clio_user_id:
            skipped.append({
                'block_id': b.id, 'minutes': b.minutes or 0,
                'reason': 'user_not_mapped',
                'detail': f'{b.user.username} has no Clio user with a matching email.',
            })
            continue

        day = b.day or timezone.localtime(b.start, tz).date()
        groups[(clio_user_id, mapping.external_id, day)].append((b, mapping))

    if not groups:
        return {
            'window': {'start': str(start_date), 'end': str(end_date)},
            'entries': [], 'skipped': skipped,
            'totals': {'entries': 0, 'minutes': 0, 'hours': 0.0},
        }

    # ── One scan of what Clio already holds ─────────────────────────────
    existing_seconds = defaultdict(int)
    # What Clio already holds, kept rather than just counted. A person can tell
    # "Call with client re: estate" from "Estate Planning.docx — Word" instantly;
    # a total cannot. Nothing in the data distinguishes duplicate work from
    # additional work — Clio entries carry a date and a duration but no start
    # time — so the only honest resolution is to show it and let someone say.
    existing_entries = defaultdict(list)
    for act in api.paginated_get(
        '/activities', fields=ACTIVITY_FIELDS,
        params={
            'type': 'TimeEntry',
            'start_date': str(start_date),
            'end_date': str(end_date),
        },
    ):
        if act.get('type') != 'TimeEntry':
            continue
        user = act.get('user') or {}
        matter = act.get('matter') or {}
        raw_date = str(act.get('date') or '')[:10]
        if not (user.get('id') and matter.get('id') and raw_date):
            continue
        try:
            day = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            continue
        key = (str(user['id']), str(matter['id']), day)
        mins = int(act.get('quantity') or 0) // 60
        existing_seconds[key] += int(act.get('quantity') or 0)
        existing_entries[key].append({
            'clio_activity_id': str(act.get('id') or ''),
            'minutes': mins,
            'note': (act.get('note') or '').strip(),
            # Ours or theirs. Our own previous pushes are never a conflict —
            # re-running a week must not re-ask about time we sent ourselves.
            'ours': str(act.get('id') or '') in our_activity_ids,
        })

    # Activities we pushed before, so a re-run never treats our own work as a
    # conflict needing a human decision.
    our_activity_ids = set(
        Block.objects
        .filter(org=org, clio_activity_id__gt='')
        .values_list('clio_activity_id', flat=True)
    )

    # ── Net our totals against theirs ───────────────────────────────────
    entries = []
    for (clio_user_id, matter_id, day), pairs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        block_objs = [b for b, _ in pairs]
        mapping = pairs[0][1]

        captured_minutes = sum(b.minutes or 0 for b in block_objs)
        already_minutes = existing_seconds.get((clio_user_id, matter_id, day), 0) // 60

        conflict_key = f'{clio_user_id}:{matter_id}:{day}'
        theirs = [e for e in existing_entries.get((clio_user_id, matter_id, day), [])
                  if not e['ours']]

        # A person said this is additional work, not the same work logged twice.
        # Send the full captured amount: netting it against entries they have
        # just told us are unrelated would be the under-billing this exists to
        # prevent.
        if force_conflicts and conflict_key in force_conflicts and captured_minutes > 0:
            entries.append({
                'clio_user_id': clio_user_id, 'matter_id': matter_id,
                'matter': mapping.display_number or matter_id, 'day': str(day),
                'captured_minutes': captured_minutes,
                'already_in_clio_minutes': already_minutes,
                'push_minutes': captured_minutes,
                'push_hours': round(captured_minutes / 60.0, 2),
                'note': _note_for(block_objs),
                'block_ids': [b.id for b in block_objs],
                'forced_additional': True,
            })
            continue

        action, delta_minutes, reason = decide_entry(
            captured_minutes, already_minutes,
            requires_utbms=mapping.requires_utbms,
            billing_method=mapping.billing_method,
            matter_status=mapping.external_status,
        )

        if action == 'skip':
            skipped.append({
                'matter': mapping.display_number or matter_id, 'day': str(day),
                'minutes': captured_minutes,
                'reason': reason,
                # Only an already_in_clio skip is resolvable by a person, and
                # only that one carries what they need to judge it.
                'conflict_key': conflict_key if reason == 'already_in_clio' else None,
                'existing': theirs if reason == 'already_in_clio' else [],
                'detail': SKIP_DETAIL[reason].format(
                    billing_method=mapping.billing_method,
                    status=mapping.external_status,
                    already=already_minutes,
                    captured=captured_minutes,
                ),
            })
            continue

        entries.append({
            'clio_user_id': clio_user_id,
            'matter_id': matter_id,
            'matter': mapping.display_number or matter_id,
            'day': str(day),
            'captured_minutes': captured_minutes,
            'already_in_clio_minutes': already_minutes,
            'push_minutes': delta_minutes,
            'push_hours': round(delta_minutes / 60.0, 2),
            'note': _note_for(block_objs),
            'block_ids': [b.id for b in block_objs],
        })

    total_minutes = sum(e['push_minutes'] for e in entries)
    return {
        'window': {'start': str(start_date), 'end': str(end_date)},
        'entries': entries,
        'skipped': skipped,
        'totals': {
            'entries': len(entries),
            'minutes': total_minutes,
            'hours': round(total_minutes / 60.0, 2),
        },
    }


def execute_push(integration: Integration, plan: dict) -> dict:
    """
    Write the plan's entries to Clio. Consumes exactly what `build_push_plan`
    produced, so a confirmed preview is what lands.
    """
    api = ClioClient(integration)
    pushed, errors = [], []

    for entry in plan.get('entries', []):
        payload = {
            'type': 'TimeEntry',
            'date': entry['day'],
            # Clio counts time in SECONDS.
            'quantity': entry['push_minutes'] * 60,
            'matter': {'id': entry['matter_id']},
            'user': {'id': entry['clio_user_id']},
            'note': entry['note'],
        }

        try:
            created = api.post('/activities', payload, fields=CREATED_FIELDS)
        except ClioValidationError as e:
            errors.append({
                'matter': entry['matter'], 'day': entry['day'],
                'error': 'rejected_by_clio', 'detail': str(e)[:300],
            })
            continue
        except ClioError as e:
            errors.append({
                'matter': entry['matter'], 'day': entry['day'],
                'error': 'api_error', 'detail': str(e)[:300],
            })
            continue

        activity_id = str((created.get('data') or created).get('id') or '')

        # Stamp only blocks with no id yet — an earlier partial push keeps its
        # own provenance rather than being rewritten.
        if activity_id:
            with transaction.atomic():
                Block.objects.filter(
                    id__in=entry['block_ids'], clio_activity_id='',
                ).update(clio_activity_id=activity_id)

        pushed.append({
            'matter': entry['matter'], 'day': entry['day'],
            'minutes': entry['push_minutes'], 'hours': entry['push_hours'],
            'clio_activity_id': activity_id,
            'blocks': len(entry['block_ids']),
        })

    total_minutes = sum(p['minutes'] for p in pushed)
    if pushed:
        integration.last_synced_at = timezone.now()
        integration.save(update_fields=['last_synced_at', 'updated_at'])

    logger.info(
        'Clio push for org %s: %s entries, %s minutes, %s errors',
        integration.organization_id, len(pushed), total_minutes, len(errors),
    )

    return {
        'pushed': pushed,
        'errors': errors,
        'skipped': plan.get('skipped', []),
        'totals': {
            'entries': len(pushed),
            'minutes': total_minutes,
            'hours': round(total_minutes / 60.0, 2),
            'errors': len(errors),
        },
    }
