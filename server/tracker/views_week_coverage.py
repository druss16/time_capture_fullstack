"""
tracker/views_week_coverage.py

Is this person's week actually whole?

Daily Review answers "is this time on the right client?" — a question about
*attribution*, and one the product has always been able to answer, because a
mis-attributed block is visible: it is sitting there on the wrong client.

Nothing answered the other question. Time that was never captured is invisible
by definition. It does not appear on a wrong client, it does not sit in a queue,
it simply is not there — and under a fee-setting model that is the expensive
failure. A partner who bills from 47 hours when the real number was 62 has
underbilled permanently, and no screen would have told them.

The signal is RawEvent. Blocks are compacted from raw events, so the two can be
compared: raw events are what the agent saw, blocks are what survived into
reviewable time. A day where the agent watched six active hours and produced
two hours of blocks is a day with a hole in it.

Caveats the endpoint is honest about rather than hiding:

  · Raw events are pruned after 30 days, so older weeks genuinely cannot be
    checked. Those days report `checkable: false` instead of a fake clean bill.
  · Idle intervals (app_name == "idle") are excluded from the active total —
    counting them would flag lunch as missing work.
  · A gap is not automatically an error. Short gaps are compaction rounding and
    suppressed sub-minute activity. Only a material shortfall is worth raising.
"""

from datetime import date, timedelta
from collections import defaultdict

from django.db import models
from django.db.models import Sum, Min, Max
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import Block, RawEvent, OrganizationMembership, Timesheet

# Raw events are pruned on a 30-day cycle; past that there is nothing to
# compare against and saying "looks complete" would be a guess.
RAW_RETENTION_DAYS = 28

# Below this, a shortfall is compaction rounding rather than lost work.
MATERIAL_GAP_MINUTES = 45

# A day the agent barely saw at all is a different problem from a day with a
# hole in it — usually the machine was off, or the agent was not running.
QUIET_DAY_ACTIVE_MINUTES = 30


# Tools whose push is wired to a timesheet transition, and what to call them
# in front of a person. Adding another billing integration means adding it here
# rather than teaching the UI a second special case.
PUSH_DESTINATIONS = [('clio', 'Clio')]


def _submission_mode(org) -> dict:
    """What pressing submit actually does at this firm.

    The button should name the furthest TRUE consequence of pressing it, not a
    ritual. "Submit for Approval" is right when a human is genuinely waiting;
    it is theatre at a firm where nobody approves anything, and it is simply
    wrong at a firm where pressing it puts time in Clio.

    Returns:
      destination      what receives the time, or None. A NAME, so the label
                       can say "Send to Clio" rather than something generic.
      sends_on_submit  whether SUBMITTING is what sends it. On the 'approve'
                       trigger it is not — approving is — so promising a send
                       would be a lie.
      has_approver     somebody here really approves other people's weeks.
      auto             it also happens on a schedule without anyone acting.
    """
    auto = bool(getattr(org, 'auto_submit_timesheets', False))

    destination, sends_on_submit = None, False
    try:
        from tracker.models import Integration
        connected = set(
            Integration.objects.filter(organization=org).values_list('provider', flat=True)
        )
        for provider, label in PUSH_DESTINATIONS:
            if provider in connected:
                destination = label
                trigger = (getattr(org, 'clio_push_trigger', 'approve') or 'approve')
                sends_on_submit = trigger in ('submit', 'continuous')
                break
    except Exception:
        destination = None

    # Owners auto-approve their own week inside submit(), so self-approval
    # proves nothing about whether a workflow exists.
    has_approver = Timesheet.objects.filter(
        org=org, status__in=('approved', 'locked'), approved_by__isnull=False,
    ).exclude(approved_by=models.F('user')).exists()

    if destination:
        mode = 'push'
        what = (
            f'Submitting sends your time to {destination}.'
            if sends_on_submit
            else f'Your time reaches {destination} once a manager approves it.'
        )
    elif has_approver:
        mode, what = 'review', 'Your firm reviews timesheets before they are final.'
    else:
        mode, what = 'off', ''

    when = 'This week submits itself on Tuesday morning.' if auto else ''

    return {
        'mode': mode,
        'auto': auto,
        'destination': destination,
        'sends_on_submit': sends_on_submit,
        'has_approver': has_approver,
        'reason': ' '.join(p for p in (what, when) if p),
    }


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def week_coverage(request):
    """GET /api/billing/week-coverage/?start=YYYY-MM-DD

    Per day for one person's week: what the agent saw, what became reviewable
    time, and where the difference is big enough to be worth a look.
    """
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related("organization").first()
    if not membership:
        return Response({"error": "No organization"}, status=403)
    org = membership.organization

    start_param = request.query_params.get("start")
    try:
        start = date.fromisoformat(start_param) if start_param else _monday(date.today())
    except ValueError:
        return Response({"error": "start must be YYYY-MM-DD"}, status=400)
    start = _monday(start)
    end = start + timedelta(days=6)

    # Whose week — a manager may inspect a report's, anyone else only their own.
    user = request.user
    target = request.query_params.get("user_id")
    if target and membership.role in ("owner", "admin", "manager"):
        member = OrganizationMembership.objects.filter(
            organization=org, user_id=target
        ).select_related("user").first()
        if not member:
            return Response({"error": "Not a member of this organization"}, status=404)
        user = member.user

    captured = {
        r["day"]: r["minutes"] or 0
        for r in Block.objects.filter(
            org=org, user=user, day__gte=start, day__lte=end
        ).values("day").annotate(minutes=Sum("minutes"))
    }

    # What the agent actually watched. Idle is excluded — flagging lunch as
    # missing work would make the whole screen noise.
    seen = defaultdict(lambda: {"minutes": 0, "first": None, "last": None})
    horizon = date.today() - timedelta(days=RAW_RETENTION_DAYS)
    raw_qs = RawEvent.objects.filter(
        user=user, start_ts__date__gte=start, start_ts__date__lte=end,
    ).exclude(app_name__iexact="idle")

    for r in raw_qs.values("start_ts__date").annotate(
        first=Min("start_ts"), last=Max("end_ts"),
    ):
        d = r["start_ts__date"]
        seen[d]["first"] = r["first"]
        seen[d]["last"] = r["last"]

    # Summing interval durations is correct here: the agent emits sequential
    # non-overlapping intervals (start_ts = last emit, end_ts = now), so
    # heartbeats do not double-count.
    for r in raw_qs.values("start_ts__date", "start_ts", "end_ts"):
        d = r["start_ts__date"]
        delta = (r["end_ts"] - r["start_ts"]).total_seconds() / 60.0
        if 0 < delta < 180:                 # ignore absurd spans from clock skew
            seen[d]["minutes"] += delta

    days, total_gap, flagged = [], 0.0, 0
    for i in range(7):
        d = start + timedelta(days=i)
        cap = float(captured.get(d, 0))
        info = seen.get(d)
        active = round(info["minutes"], 1) if info else 0.0
        checkable = horizon <= d <= date.today()

        gap = max(0.0, active - cap)
        if d > date.today():
            # Hasn't happened yet. Reporting a future Friday as "too old to
            # check" made the current week look broken from Thursday onward.
            state = "future"
        elif not checkable:
            state = "unknown"
        elif active < QUIET_DAY_ACTIVE_MINUTES and cap < QUIET_DAY_ACTIVE_MINUTES:
            state = "quiet"                 # nothing happened; usually a day off
        elif gap >= MATERIAL_GAP_MINUTES:
            state = "gap"
        else:
            state = "ok"

        if state == "gap":
            total_gap += gap
            flagged += 1

        days.append({
            "date": d.isoformat(),
            "weekday": d.strftime("%a"),
            "captured_hours": round(cap / 60, 2),
            "active_hours": round(active / 60, 2),
            "gap_hours": round(gap / 60, 2) if state == "gap" else 0,
            "first_seen": info["first"].isoformat() if info and info["first"] else None,
            "last_seen": info["last"].isoformat() if info and info["last"] else None,
            "state": state,
            "checkable": checkable,
        })

    captured_total = sum(d["captured_hours"] for d in days)
    return Response({
        "submission": _submission_mode(org),
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "user_id": user.id,
        "user_name": f"{user.first_name} {user.last_name}".strip() or user.username,
        "captured_hours": round(captured_total, 2),
        "gap_hours": round(total_gap / 60, 2),
        "days_flagged": flagged,
        # False when the whole week predates raw-event retention, so the UI can
        # say "too old to check" rather than implying the week is clean.
        "checkable": any(d["checkable"] for d in days),
        "days": days,
    })
