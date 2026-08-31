# tracker/views_outstanding_weeks.py
"""
"You still owe last week" — the outstanding-weeks reminder on My Week.

Nobody at a firm like this submits a timesheet by hand; the Tuesday task does
it. That works right up until a week has no Timesheet ROW at all, because
`auto_submit_timesheets` only ever looks at `status='draft'` records. A week
that was never created is invisible to it forever, and the time in it can never
be submitted, approved, or billed.

That is not hypothetical. Org 21 today: 92 person-weeks holding 1,246.9 hours
(565.4 billable, ~$84.8k) with committed time and no timesheet row, going back
months, because the weekly draft-creation task spent a long stretch crashing
and its backfill never ran.

The person is the only one who can see their own missing weeks, and until now
nothing told them. This does.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication
from tracker.models import Block, OrganizationMembership, Timesheet
from tracker.services.billing_totals import committed_block_qs
from tracker.views_reports import _day_bounds_utc

# How far back to look. Deep enough to surface a real backlog, bounded so the
# reminder can't become a wall of every week the person has ever worked.
LOOKBACK_WEEKS = 12

# Statuses that mean the week has left the person's hands. Anything else is
# still theirs to send.
SETTLED = ('submitted', 'approved', 'locked')


def _monday(d):
    return d - timedelta(days=d.weekday())


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def outstanding_weeks(request):
    """
    GET /api/timesheets/outstanding/

    The requester's own COMPLETED weeks that still hold committed time nobody
    has sent. Two shapes, and the difference matters:

      state "draft"   — a timesheet exists. Tuesday's task will pick it up if
                        it is last week; older drafts it will never touch,
                        because that task only ever reads last week.
      state "missing" — no timesheet row at all. Nothing will ever pick it up.
                        `timesheet_id` is null and one has to be created before
                        the week can be submitted.

    The current week is deliberately excluded: it is not late, it is in progress.
    """
    membership = (OrganizationMembership.objects
                  .filter(user=request.user).select_related('organization').first())
    if not membership:
        return Response({'weeks': [], 'total_minutes': 0, 'total_billable_minutes': 0})

    org = membership.organization
    this_monday = _monday(timezone.localdate())
    last_monday = this_monday - timedelta(days=7)

    existing = {
        t.week_start: t
        for t in Timesheet.objects.filter(org=org, user=request.user,
                                          week_start__gte=this_monday - timedelta(weeks=LOOKBACK_WEEKS))
    }

    weeks = []
    total = billable_total = 0
    for i in range(1, LOOKBACK_WEEKS + 1):
        wk = this_monday - timedelta(weeks=i)
        ts = existing.get(wk)
        if ts and ts.status in SETTLED:
            continue

        start_utc, end_utc = _day_bounds_utc(wk, wk + timedelta(days=6))
        minutes = billable = 0
        for b in committed_block_qs(org, start_utc, end_utc,
                                    user_id=request.user.id, can_see_all=False):
            minutes += b.minutes or 0
            if b.is_billable:
                billable += b.minutes or 0
        if not minutes:
            continue                      # an empty week is not an outstanding one

        total += minutes
        billable_total += billable
        weeks.append({
            'week_start': wk.isoformat(),
            'week_end': (wk + timedelta(days=6)).isoformat(),
            'timesheet_id': ts.id if ts else None,
            'state': 'draft' if ts else 'missing',
            'minutes': minutes,
            'billable_minutes': billable,
            # Only last week's drafts are on the Tuesday task's list. Saying so
            # is the difference between "it's handled" and "nobody is coming".
            'auto_submits': bool(ts) and wk == last_monday,
        })

    weeks.sort(key=lambda w: w['week_start'])
    return Response({
        'weeks': weeks,
        'count': len(weeks),
        'total_minutes': total,
        'total_billable_minutes': billable_total,
        # Nothing is coming for these on its own.
        'stranded_count': sum(1 for w in weeks if not w['auto_submits']),
    })


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def ensure_week_timesheet(request):
    """
    POST /api/timesheets/ensure-week/   {"week_start": "2026-08-17"}

    Create the requester's draft timesheet for a past week if it does not exist,
    and return its id so the normal submit flow can take over.

    Needed because submission is addressed by timesheet id, so a week that was
    never created has literally nothing to submit — the reminder could point at
    it but not let anyone act. Creating a draft is the smallest thing that
    unblocks that, and it is the same row the weekly task would have made.

    Only ever creates for the requester, only for a past week, and only when the
    week actually holds committed time.
    """
    membership = (OrganizationMembership.objects
                  .filter(user=request.user).select_related('organization').first())
    if not membership:
        return Response({'error': 'No organization membership'}, status=403)
    org = membership.organization

    raw = (request.data.get('week_start') or '').strip()
    try:
        wk = timezone.datetime.fromisoformat(raw).date()
    except (TypeError, ValueError):
        return Response({'error': 'week_start must be an ISO date (YYYY-MM-DD).'}, status=400)

    wk = _monday(wk)
    if wk >= _monday(timezone.localdate()):
        return Response({'error': 'That week is still in progress.'}, status=400)

    existing = Timesheet.objects.filter(org=org, user=request.user, week_start=wk).first()
    if existing:
        return Response({'timesheet_id': existing.id, 'status': existing.status, 'created': False})

    start_utc, end_utc = _day_bounds_utc(wk, wk + timedelta(days=6))
    has_time = Block.objects.filter(
        org=org, user=request.user, deleted_at__isnull=True,
        start__gte=start_utc, start__lt=end_utc,
    ).exists()
    if not has_time:
        return Response({'error': 'That week has no tracked time.'}, status=400)

    ts = Timesheet.objects.create(org=org, user=request.user, week_start=wk, status='draft')
    return Response({'timesheet_id': ts.id, 'status': ts.status, 'created': True}, status=201)


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def week_misfiles(request):
    """
    GET /api/timesheets/week-misfiles/?week_start=YYYY-MM-DD

    How much of the requester's own confirmed time for that week is booked to a
    client its title contradicts.

    This exists for the moment of SENDING, not as ambient furniture. Daily
    Review already shows a person their own mismatches and can span a week, so a
    standing banner on My Week would be the third surface repeating one finding.
    What My Week has that Daily Review does not is the button that commits the
    week — and that is the last moment fixing one of these is cheap.

    CLIENT bucket only, the same standard the owner auto-approve gate uses.
    Internal/admin disagreements and same-family ties are real but are not
    reasons to interrupt someone sending a week; a warning that fires often is
    one people click past.
    """
    membership = (OrganizationMembership.objects
                  .filter(user=request.user).select_related('organization').first())
    if not membership:
        return Response({'count': 0, 'minutes': 0, 'examples': []})
    org = membership.organization

    raw = (request.GET.get('week_start') or '').strip()
    try:
        wk = _monday(timezone.datetime.fromisoformat(raw).date())
    except (TypeError, ValueError):
        return Response({'error': 'week_start must be an ISO date (YYYY-MM-DD).'}, status=400)

    from tracker.services.mismatch_scan import (
        build_indexes, confirmed_correct_block_ids, scan_buckets,
    )

    start_utc, end_utc = _day_bounds_utc(wk, wk + timedelta(days=6))
    blocks = (
        committed_block_qs(org, start_utc, end_utc, user_id=request.user.id, can_see_all=False)
        .filter(client_id__isnull=False)
        .exclude(window_title__isnull=True)
        .exclude(window_title='')
        .select_related('client', 'user', 'org')
    )
    names_by_org, index_by_org, firm_by_org = build_indexes([org.id])
    result = scan_buckets(
        blocks, names_by_org, index_by_org, firm_by_org,
        limit=5,                                   # a warning, not a work queue
        skip_block_ids=confirmed_correct_block_ids([org.id]),
    )
    rows = result['flagged']['client']
    return Response({
        'week_start': wk.isoformat(),
        'count': result['counts']['client'],
        'minutes': sum(r.get('minutes') or 0 for r in rows),
        'examples': [{
            'block_id': r['block_id'],
            'date': r['date'],
            'minutes': r['minutes'],
            'window_title': r['window_title'],
            'booked_client_name': r['booked_client_name'],
            'looks_like_client_name': r.get('looks_like_client_name'),
        } for r in rows],
    })
