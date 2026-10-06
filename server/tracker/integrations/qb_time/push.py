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

ONE ROW, WHOLE INCREMENTS
------------------------
Each (user, jobcode, day) total is rounded to the nearest ROUND_MINUTES before
netting, so what lands in QuickBooks Time reads like a timesheet a person
would keep — 0:06, 0:12 — not 0:01 and 0:02. Nearest rather than up: these
hours feed payroll, and always rounding up would inflate every day.

And a day stays ONE row of ours per jobcode. When more time arrives after a
push, our existing timesheet grows to the new total rather than a second row
appearing beside it; any extra rows of ours left over (from before this rule)
are folded into the one kept. Time a person entered is still never touched.

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
from contextlib import contextmanager
from datetime import datetime, timedelta

from celery import shared_task
from django.db import connection
from django.utils import timezone

from tracker.integrations.qb_time.client import (
    QBTimeClient, QBTimeError, row_error, row_ok, row_results,
)
from tracker.models import Integration
from tracker.models_task_type_sets import (
    ExternalClientMapping, ExternalMatterMapping, ExternalStaffMapping, QbtPushedTimesheet,
    QbtPushSettings, QbtTimesheetPush,
)

logger = logging.getLogger(__name__)

# Below this the delta is rounding noise, not a timesheet worth writing.
MIN_PUSH_MINUTES = 1
# Day totals per jobcode are rounded to the nearest of this (6 min = 0.1 h).
ROUND_MINUTES = 6
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
    'under_increment': '{raw}m on "{jobcode}" rounds to nothing at {step}-minute increments.',
}


def round_minutes(minutes: int) -> int:
    """Nearest ROUND_MINUTES, halves up: 2 -> 0, 3 -> 6, 8 -> 6, 9 -> 12."""
    step = ROUND_MINUTES
    if step <= 1:
        return int(minutes)
    return int((minutes + step // 2) // step * step)


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
        captured_raw = sum(b.minutes or 0 for b in blocks_in)
        captured = round_minutes(captured_raw)
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
            'captured_raw_minutes': captured_raw,
            'already_in_qbt_minutes': already,
            'block_ids': [b.id for b in blocks_in],
        }

        if blocks_in and jc and jc.get('active') is False:
            skipped.append({**base, 'minutes': captured, 'reason': 'jobcode_inactive',
                            'detail': SKIP_DETAIL['jobcode_inactive'].format(jobcode=jobcode_name)})
            continue

        if captured_raw and not captured and not ours:
            skipped.append({**base, 'minutes': captured_raw, 'reason': 'under_increment',
                            'detail': SKIP_DETAIL['under_increment'].format(
                                raw=captured_raw, jobcode=jobcode_name, step=ROUND_MINUTES)})
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

        # Already have a row of ours here: grow it to the new total and fold
        # any other rows of ours into it, instead of adding another row.
        grow = None
        if ours:
            keep, *rest = sorted(ours, key=lambda x: (-x['minutes'], x['timesheet_id']))
            grow = {
                'timesheet_id': keep['timesheet_id'],
                'from_minutes': keep['minutes'],
                'to_minutes': sum(e['minutes'] for e in ours) + minutes,
                'merge': [{'timesheet_id': e['timesheet_id'], 'minutes': e['minutes']} for e in rest],
            }

        entries.append({**base, 'action': 'push', 'push_minutes': minutes,
                        'push_hours': round(minutes / 60.0, 2),
                        'grow': grow,
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

    # ── More time on a day we already pushed: grow our row ──────────────
    grows = [e for e in plan.get('entries', []) if e.get('action') == 'push' and e.get('grow')]
    for i in range(0, len(grows), WRITE_BATCH):
        batch = grows[i:i + WRITE_BATCH]
        try:
            res = api.put('timesheets', [{
                'id': int(e['grow']['timesheet_id']),
                'duration': e['grow']['to_minutes'] * 60,
                'notes': e['note'],
            } for e in batch])
        except QBTimeError as e:
            for entry in batch:
                _err(entry, 'api_error', e)
            continue
        rows = row_results(res, 'timesheets')
        for n, entry in enumerate(batch):
            row = rows[n] if n < len(rows) else None
            if row is None or not row_ok(row):
                _err(entry, 'rejected_by_qbt',
                     row_error(row) if row else 'QuickBooks Time returned no result for this row.')
                continue
            g = entry['grow']
            QbtPushedTimesheet.objects.filter(integration=integration, timesheet_id=g['timesheet_id']) \
                .update(minutes=g['to_minutes'], block_ids=entry['block_ids'], deleted_at=None)
            pushed.append({'user': entry.get('user'), 'jobcode': entry['jobcode'], 'day': entry['day'],
                           'minutes': entry['push_minutes'], 'hours': entry['push_hours'],
                           'timesheet_id': g['timesheet_id'], 'blocks': len(entry['block_ids']),
                           'grew': True})
            # Only once the kept row holds the whole total do the others go.
            # A failed delete leaves an overshoot the next run reduces.
            extra = [m['timesheet_id'] for m in g.get('merge') or []]
            if not extra:
                continue
            try:
                res = api.delete('timesheets', extra)
            except QBTimeError as e:
                _err(entry, 'merge_failed', e)
                continue
            for tid, r in zip(extra, row_results(res, 'timesheets')):
                if row_ok(r):
                    QbtPushedTimesheet.objects.filter(integration=integration, timesheet_id=tid) \
                        .update(minutes=0, deleted_at=timezone.now())
                else:
                    _err(entry, 'merge_failed', row_error(r))

    # ── New time, in batches ────────────────────────────────────────────
    to_push = [e for e in plan.get('entries', []) if e.get('action') == 'push' and not e.get('grow')]
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


# Namespace for this push's Postgres advisory lock ("QT"), so it cannot collide
# with any other advisory lock taken on the same integration id.
_LOCK_NAMESPACE = 0x5154


@contextmanager
def push_lock(integration: Integration):
    """
    One push per firm at a time.

    The delta is only safe run after run: two pushes planning at once both see
    "QuickBooks Time holds nothing yet" and both write the hour. An approval and
    an admin's manual send can overlap, so every write path takes this lock.

    Blocking, not try-and-skip: a push is a few requests, and the second one
    re-plans after the first has finished, so it nets to nothing instead of
    being lost. Session-level so it holds across the push's autocommit writes;
    the connection closing releases it if a worker dies mid-push.
    """
    if connection.vendor != 'postgresql':
        yield
        return
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_lock(%s, %s)', [_LOCK_NAMESPACE, integration.id])
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute('SELECT pg_advisory_unlock(%s, %s)', [_LOCK_NAMESPACE, integration.id])


def push_trigger_for(integration) -> str:
    """'approve' or 'off'. Never raises — an unmigrated table reads as off."""
    if integration is None:
        return 'off'
    try:
        row = QbtPushSettings.objects.filter(integration=integration).first()
    except Exception as e:
        logger.warning('QB Time push settings unreadable for integration %s: %s', integration.id, e)
        return 'off'
    return row.push_trigger if row else 'off'


def push_timesheet(timesheet, integration: Integration, *, api=None) -> dict:
    """
    Send one person's week to QuickBooks Time. The approval path's entry point.

    Exactly the admin panel's push narrowed to this timesheet's user and week,
    so the two can never disagree about what a week contains.
    """
    week_end = timesheet.week_start + timedelta(days=6)
    with push_lock(integration):
        plan = build_push_plan(integration, timesheet.week_start, week_end,
                               user_ids=[timesheet.user_id], api=api)
        if not plan.get('entries'):
            return {'pushed': [], 'reduced': [], 'errors': [], 'skipped': plan.get('skipped', []),
                    'totals': {'entries': 0, 'minutes': 0, 'hours': 0.0, 'errors': 0}}
        return execute_push(integration, plan, api=api)


def _summary(result: dict) -> dict:
    """What the timesheet screens show — counts plus the reasons, not raw rows."""
    totals = result.get('totals') or {}
    return {
        'entries': totals.get('entries', 0),
        'minutes': totals.get('minutes', 0),
        'hours': totals.get('hours', 0.0),
        'reduced': len(result.get('reduced') or []),
        'errors': result.get('errors') or [],
        'skipped': result.get('skipped') or [],
    }


@shared_task(name='tracker.push_timesheet_to_qb_time')
def push_timesheet_to_qb_time_task(timesheet_id):
    """
    Send an approved timesheet to QuickBooks Time on a worker.

    Safe to re-run: the push is a delta under push_lock, so a retry, a double
    fire or an admin's manual send at the same moment cannot double the hours.
    """
    from tracker.integrations.qb_time.client import QBTimeAuthError
    from tracker.models import Timesheet

    try:
        ts = Timesheet.objects.select_related('org').get(id=timesheet_id)
    except Timesheet.DoesNotExist:
        logger.error('QB Time push: timesheet %s not found', timesheet_id)
        return {'error': 'timesheet_not_found'}

    integration = Integration.objects.filter(
        organization=ts.org, provider='qb_time', is_connected=True,
    ).first()
    if integration is None:
        # Disconnected between approval and now — nothing to do, not a failure.
        QbtTimesheetPush.objects.filter(timesheet_id=ts.id).delete()
        return {'skipped': 'no_qb_time'}

    def _record(status, result):
        QbtTimesheetPush.objects.update_or_create(
            integration=integration, timesheet_id=ts.id,
            defaults={'status': status, 'result': result},
        )

    _record('running', {})
    try:
        result = _summary(push_timesheet(ts, integration))
    except QBTimeAuthError as e:
        _record('failed', {'error': f'QuickBooks Time needs reconnecting: {e}'[:300]})
        return {'error': 'reconnect_required'}
    except Exception as e:
        logger.warning('QB Time push failed for timesheet %s: %s', ts.id, e, exc_info=True)
        _record('failed', {'error': str(e)[:300]})
        return {'error': str(e)[:300]}

    _record('failed' if result['errors'] else 'done', result)
    return result


def queue_timesheet_push(timesheet) -> None:
    """
    Queue the push if this firm sends approved weeks to QuickBooks Time.

    Called from Timesheet.approve() — the transition, not the endpoint, so an
    owner's auto-approved week goes too. Never raises: QuickBooks Time holds a
    copy of the approval, and a problem there must not undo it.
    """
    try:
        integration = Integration.objects.filter(
            organization_id=timesheet.org_id, provider='qb_time', is_connected=True,
        ).first()
        if push_trigger_for(integration) != 'approve':
            return
        QbtTimesheetPush.objects.update_or_create(
            integration=integration, timesheet_id=timesheet.id,
            defaults={'status': 'queued', 'result': {}},
        )
        push_timesheet_to_qb_time_task.delay(timesheet.id)
    except Exception as e:
        logger.warning('Could not queue QB Time push for timesheet %s: %s',
                       timesheet.id, e, exc_info=True)
        try:
            QbtTimesheetPush.objects.filter(timesheet_id=timesheet.id).update(
                status='failed', result={'error': f'Could not queue the push: {e}'[:300]},
            )
        except Exception:
            pass


def timesheet_push_status(timesheet) -> dict | None:
    """The latest QB Time push for this timesheet, for the API response. None if never queued."""
    try:
        row = QbtTimesheetPush.objects.filter(timesheet_id=timesheet.id).order_by('-updated_at').first()
    except Exception:
        return None
    if row is None:
        return None
    return {'status': row.status, 'queued': row.status == 'queued', **(row.result or {})}
