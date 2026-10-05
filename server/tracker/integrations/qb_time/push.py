"""
Push captured time into QuickBooks Time as manual timesheets.

WHO THIS IS FOR
---------------
A firm that runs its hours through QuickBooks Time — approvals, payroll,
job costing all happen there. TimeTracker's captured time has to land as
QuickBooks Time timesheets on the firm's jobcodes, or to them it does not
exist. Writing to QuickBooks Online instead would bypass their workflow and
double-count once QuickBooks Time syncs its own hours across.

THE DOUBLE-COUNT PROBLEM
------------------------
Same shape as Clio (integrations/clio/push.py — read its docstring): someone
may already have clocked some of the same work in QuickBooks Time. So push is
a DELTA per (QuickBooks Time user, jobcode, day), not an append:

    delta = (everything we captured for that user/jobcode/day)
          - (everything QuickBooks Time already holds for it)

pushed as one manual timesheet, and skipped when delta <= 0. That converges
however many times it runs. `captured` is always the full day total, and
QbtPushedTimesheet is only "which ones are ours", never an input to the sum.

When captured falls BELOW what we ourselves pushed (a block was recategorised
to another client after we sent it), our own timesheets are cut back by the
overshoot. Time a person entered is never touched.

WHERE TIME GOES
---------------
A block's project, if that project came from QuickBooks Time, else its
client's customer jobcode. Anything else is skipped with a reason the firm
can act on, never silently dropped.

REQUEST BUDGET
--------------
200 requests per 5 minutes per token. Existing timesheets are read with one
paginated scan of the window, jobcodes with one lookup by id, and writes go
out in batches of 50 — a firm's whole week is a handful of requests.

⚠️ Built against the published API reference
(https://tsheetsteam.github.io/api_docs/), not yet run against a live account.
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from django.utils import timezone

from tracker.integrations.qb_time.client import (
    QBTimeClient, QBTimeError, row_error, row_ok, row_results,
)
from tracker.models import Integration
from tracker.models_task_type_sets import (
    ExternalClientMapping, ExternalMatterMapping, ExternalStaffMapping, QbtPushedTimesheet,
)

logger = logging.getLogger(__name__)

# Below this the delta is rounding noise, not a timesheet worth writing.
MIN_PUSH_MINUTES = 1
# QuickBooks Time accepts up to 50 rows per write.
WRITE_BATCH = 50
NOTE_MAX = 500

SKIP_DETAIL = {
    'no_client': 'Block has no client, so there is no jobcode to put it on.',
    'jobcode_not_synced': '"{name}" is not linked to a QuickBooks Time jobcode. '
                          'Run a QuickBooks Time sync, or file the time to a synced project.',
    'user_not_mapped': '{user} has no QuickBooks Time user with a matching email.',
    'jobcode_inactive': 'Jobcode "{jobcode}" is archived in QuickBooks Time and takes no new time.',
    'already_in_qbt': 'QuickBooks Time already holds {already}m on "{jobcode}" for this day; '
                      'we captured {captured}m. Nothing to add.',
}


def _day_bounds(day, tz):
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    return start, start + timedelta(days=1)


def decide_entry(captured_minutes, already_minutes, ours_minutes=0):
    """
    What to do with one (user, jobcode, day) bucket. Pure — no I/O.

    Returns (action, minutes, reason): 'push' the shortfall, 'reduce' our own
    timesheets by the overshoot, or 'skip'. See clio.push.decide_entry for why
    the overshoot is measured against OUR contribution and never the total:
    hand-entered extra time must not make us delete a correct push.
    """
    delta = captured_minutes - already_minutes
    if delta >= MIN_PUSH_MINUTES:
        return 'push', delta, ''
    overshoot = ours_minutes - captured_minutes
    if overshoot >= MIN_PUSH_MINUTES:
        return 'reduce', overshoot, 'attribution_moved'
    return 'skip', captured_minutes, 'already_in_qbt'


def _note_for(blocks):
    # Same wording rules as the Clio push: a human note, else the window title,
    # never bare application chrome.
    from tracker.integrations.clio.push import _note_for as clio_note
    return clio_note(blocks)[:NOTE_MAX]


def _parse_day(raw):
    try:
        return datetime.strptime(str(raw or '')[:10], '%Y-%m-%d').date()
    except ValueError:
        return None


def _jobcodes_by_id(api, ids):
    """id -> jobcode record, for just the jobcodes we are about to write to."""
    out = {}
    ids = sorted(ids)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        for jc in api.paginated('jobcodes', ids=','.join(chunk), active='both'):
            out[str(jc.get('id'))] = jc
    return out


def build_push_plan(integration: Integration, start_date, end_date, user_ids=None, *, api=None) -> dict:
    """
    Work out what WOULD be pushed. Reads QuickBooks Time, writes nothing.

    The preview the UI shows, and exactly what `execute_push` consumes.
    """
    from tracker.services.billing_totals import committed_block_qs

    org = integration.organization
    tz = timezone.get_current_timezone()
    window_start, _ = _day_bounds(start_date, tz)
    _, window_end = _day_bounds(end_date, tz)

    jobcode_by_project = {
        m.project_id: m.external_id
        for m in ExternalMatterMapping.objects.filter(integration=integration)
    }
    jobcode_by_client = {
        m.client_id: m.external_id
        for m in ExternalClientMapping.objects.filter(integration=integration)
    }
    qbt_user_by_user = {
        s.user_id: s.external_id
        for s in ExternalStaffMapping.objects.filter(integration=integration)
    }

    blocks = committed_block_qs(org, window_start, window_end).select_related('client', 'project', 'user')
    if user_ids:
        blocks = blocks.filter(user_id__in=user_ids)

    # ── Bucket our own captured time ────────────────────────────────────
    groups = defaultdict(list)
    skipped = []
    for b in blocks:
        minutes = b.minutes or 0
        if minutes <= 0:
            continue
        if not b.client_id:
            skipped.append({'block_id': b.id, 'minutes': minutes, 'reason': 'no_client',
                            'detail': SKIP_DETAIL['no_client']})
            continue
        jobcode_id = jobcode_by_project.get(b.project_id) or jobcode_by_client.get(b.client_id)
        if not jobcode_id:
            name = f'{b.client} / {b.project}' if b.project_id else str(b.client)
            skipped.append({'block_id': b.id, 'minutes': minutes, 'reason': 'jobcode_not_synced',
                            'detail': SKIP_DETAIL['jobcode_not_synced'].format(name=name)})
            continue
        qbt_user_id = qbt_user_by_user.get(b.user_id)
        if not qbt_user_id:
            skipped.append({'block_id': b.id, 'minutes': minutes, 'reason': 'user_not_mapped',
                            'detail': SKIP_DETAIL['user_not_mapped'].format(
                                user=b.user.get_full_name() or b.user.email or b.user.username)})
            continue
        day = b.day or timezone.localtime(b.start, tz).date()
        groups[(str(qbt_user_id), str(jobcode_id), day)].append(b)

    # Days where our earlier push sits on a jobcode that no longer has any
    # captured time — the block was recategorised or removed outright. With
    # no block left in that bucket it would never be looked at, and our old
    # timesheet would keep the hour on the wrong jobcode forever.
    qbt_users_in_scope = (
        {qbt_user_by_user[u] for u in user_ids if u in qbt_user_by_user}
        if user_ids else None
    )
    pushed_rows = QbtPushedTimesheet.objects.filter(
        integration=integration, deleted_at__isnull=True,
        day__gte=start_date, day__lte=end_date,
    )
    ours_ids = set(
        QbtPushedTimesheet.objects
        .filter(integration=integration, deleted_at__isnull=True)
        .values_list('timesheet_id', flat=True)
    )
    for row in pushed_rows:
        if qbt_users_in_scope is not None and row.qbt_user_id not in qbt_users_in_scope:
            continue
        groups.setdefault((row.qbt_user_id, row.jobcode_id, row.day), [])

    if not groups:
        return {
            'window': {'start': str(start_date), 'end': str(end_date)},
            'entries': [], 'skipped': skipped,
            'totals': {'entries': 0, 'minutes': 0, 'hours': 0.0},
        }

    api = api or QBTimeClient(integration)
    jobcodes = _jobcodes_by_id(api, {jid for _u, jid, _d in groups})
    name_by_qbt_user = {
        s.external_id: (s.user.get_full_name() or s.user.email or s.external_name)
        for s in ExternalStaffMapping.objects.filter(integration=integration).select_related('user')
    }

    # ── One scan of what QuickBooks Time already holds ──────────────────
    # Scoped to the people we are pushing for; a timesheet-sized push is then
    # one or two requests regardless of firm size.
    existing = defaultdict(list)
    scan_users = sorted({u for u, _j, _d in groups})
    for i in range(0, len(scan_users), 50):
        for ts in api.paginated('timesheets', start_date=str(start_date), end_date=str(end_date),
                                user_ids=','.join(scan_users[i:i + 50])):
            day = _parse_day(ts.get('date'))
            if day is None:
                continue
            key = (str(ts.get('user_id')), str(ts.get('jobcode_id')), day)
            tid = str(ts.get('id') or '')
            existing[key].append({
                'timesheet_id': tid,
                'minutes': int(ts.get('duration') or 0) // 60,
                'type': ts.get('type') or '',
                'note': (ts.get('notes') or '').strip(),
                'ours': tid in ours_ids,
            })

    # ── Net our totals against theirs ───────────────────────────────────
    entries = []
    for (qbt_user_id, jobcode_id, day), blocks_in in sorted(groups.items(), key=lambda kv: str(kv[0])):
        jc = jobcodes.get(jobcode_id) or {}
        jobcode_name = jc.get('name') or jobcode_id
        captured = sum(b.minutes or 0 for b in blocks_in)
        held = existing.get((qbt_user_id, jobcode_id, day), [])
        already = sum(e['minutes'] for e in held)
        ours = [e for e in held if e['ours'] and e['timesheet_id']]
        if not blocks_in and not ours:
            continue  # our row was already removed in QuickBooks Time by hand
        base = {
            'qbt_user_id': qbt_user_id,
            'user': name_by_qbt_user.get(qbt_user_id, qbt_user_id),
            'jobcode_id': jobcode_id,
            'jobcode': jobcode_name,
            'day': str(day),
            'captured_minutes': captured,
            'already_in_qbt_minutes': already,
            'block_ids': [b.id for b in blocks_in],
        }

        if blocks_in and jc and jc.get('active') is False:
            skipped.append({**base, 'minutes': captured, 'reason': 'jobcode_inactive',
                            'detail': SKIP_DETAIL['jobcode_inactive'].format(jobcode=jobcode_name)})
            continue

        action, minutes, reason = decide_entry(captured, already, sum(e['minutes'] for e in ours))

        if action == 'reduce':
            remaining, reductions = minutes, []
            for e in sorted(ours, key=lambda x: -x['minutes']):
                if remaining <= 0:
                    break
                take = min(remaining, e['minutes'])
                reductions.append({'timesheet_id': e['timesheet_id'],
                                   'from_minutes': e['minutes'], 'to_minutes': e['minutes'] - take})
                remaining -= take
            entries.append({**base, 'action': 'reduce', 'push_minutes': 0, 'push_hours': 0,
                            'reduce_minutes': minutes, 'reductions': reductions, 'note': ''})
            continue

        if action == 'skip':
            skipped.append({**base, 'minutes': captured, 'reason': reason,
                            'existing': [e for e in held if not e['ours']],
                            'detail': SKIP_DETAIL[reason].format(
                                already=already, captured=captured, jobcode=jobcode_name)})
            continue

        entries.append({**base, 'action': 'push', 'push_minutes': minutes,
                        'push_hours': round(minutes / 60.0, 2),
                        # QuickBooks Time only takes time on a jobcode with no
                        # sub-jobcodes in its own UI. Not refused here — the
                        # API is the judge — but named so a rejection is
                        # explicable from the preview.
                        'parent_jobcode': bool(jc.get('has_children')),
                        'note': _note_for(blocks_in)})

    total = sum(e['push_minutes'] for e in entries)
    return {
        'window': {'start': str(start_date), 'end': str(end_date)},
        'entries': entries,
        'skipped': skipped,
        'totals': {'entries': len(entries), 'minutes': total, 'hours': round(total / 60.0, 2)},
    }


def execute_push(integration: Integration, plan: dict, *, api=None) -> dict:
    """Write the plan to QuickBooks Time. Consumes exactly what build_push_plan made."""
    api = api or QBTimeClient(integration)
    pushed, reduced, errors = [], [], []

    def _err(entry, code, detail):
        errors.append({'user': entry.get('user'), 'jobcode': entry['jobcode'], 'day': entry['day'],
                       'error': code, 'detail': str(detail)[:300]})

    # ── Retractions first, so a moved hour is never briefly on two jobcodes ──
    for entry in (e for e in plan.get('entries', []) if e.get('action') == 'reduce'):
        for r in entry.get('reductions', []):
            try:
                if r['to_minutes'] <= 0:
                    res = api.delete('timesheets', [r['timesheet_id']])
                else:
                    res = api.put('timesheets', [{'id': int(r['timesheet_id']),
                                                  'duration': r['to_minutes'] * 60}])
            except QBTimeError as e:
                _err(entry, 'reduce_failed', e)
                continue
            rows = row_results(res, 'timesheets')
            if rows and not row_ok(rows[0]):
                _err(entry, 'reduce_failed', row_error(rows[0]))
                continue
            row = QbtPushedTimesheet.objects.filter(integration=integration, timesheet_id=r['timesheet_id'])
            if r['to_minutes'] <= 0:
                row.update(minutes=0, deleted_at=timezone.now())
            else:
                row.update(minutes=r['to_minutes'])
            reduced.append({'user': entry.get('user'), 'jobcode': entry['jobcode'], 'day': entry['day'],
                            'timesheet_id': r['timesheet_id'],
                            'from_minutes': r['from_minutes'], 'to_minutes': r['to_minutes']})

    # ── New time, in batches ────────────────────────────────────────────
    to_push = [e for e in plan.get('entries', []) if e.get('action') == 'push']
    for i in range(0, len(to_push), WRITE_BATCH):
        batch = to_push[i:i + WRITE_BATCH]
        rows_out = [{
            'user_id': int(e['qbt_user_id']),
            'jobcode_id': int(e['jobcode_id']),
            'type': 'manual',
            'date': e['day'],
            # QuickBooks Time counts duration in SECONDS.
            'duration': e['push_minutes'] * 60,
            'notes': e['note'],
        } for e in batch]
        try:
            res = api.post('timesheets', rows_out)
        except QBTimeError as e:
            for entry in batch:
                _err(entry, 'api_error', e)
            continue

        rows = row_results(res, 'timesheets')
        for n, entry in enumerate(batch):
            row = rows[n] if n < len(rows) else None
            if row is None:
                _err(entry, 'no_result', 'QuickBooks Time returned no result for this row.')
                continue
            if not row_ok(row):
                _err(entry, 'rejected_by_qbt', row_error(row))
                continue
            tid = str(row.get('id') or '')
            if tid:
                QbtPushedTimesheet.objects.update_or_create(
                    integration=integration, timesheet_id=tid,
                    defaults={'qbt_user_id': entry['qbt_user_id'], 'jobcode_id': entry['jobcode_id'],
                              'day': _parse_day(entry['day']), 'minutes': entry['push_minutes'],
                              'block_ids': entry['block_ids'], 'deleted_at': None},
                )
            pushed.append({'user': entry.get('user'), 'jobcode': entry['jobcode'], 'day': entry['day'],
                           'minutes': entry['push_minutes'], 'hours': entry['push_hours'],
                           'timesheet_id': tid, 'blocks': len(entry['block_ids'])})

    total = sum(p['minutes'] for p in pushed)
    logger.info('QB Time push for org %s: %s timesheets, %s minutes, %s reduced, %s errors',
                integration.organization_id, len(pushed), total, len(reduced), len(errors))
    return {
        'pushed': pushed,
        'reduced': reduced,
        'errors': errors,
        'skipped': plan.get('skipped', []),
        'totals': {'entries': len(pushed), 'minutes': total,
                   'hours': round(total / 60.0, 2), 'errors': len(errors)},
    }
