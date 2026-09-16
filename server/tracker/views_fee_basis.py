"""
tracker/views_fee_basis.py

The number a partner prices from, and how much of it we actually saw.

This firm sets each client's fee monthly off the hours. QuickBooks is open,
they look up what went into the account, they arrive at a fair figure, and they
invoice from their own system. Nothing is decided here and nothing is recorded
here — earlier versions of this endpoint asked the partner to mark clients
billed or priced, which was data entry that made the product feel complete and
made him slower, and it has been taken back out.

What is left is the one thing he cannot get from QuickBooks, his memory, or the
Reports client table: our hours, with the honesty about them that makes a
reference worth respecting.

Because the number is a FLOOR, not a total. org 21 captures about 45% of
scheduled hours; "Basilica: 28.1h" reads like a fact and is a minimum. A
partner pricing off a silent under-count either loses money or applies a
private gut multiplier — and if he is doing the second, the barometer is his
instinct and we are decoration. So every figure here travels with how much of
that client's team we actually saw.

Firms do not bill straight out of TimeTracker — the numbers are a reference
they weigh against their own judgement. That changes what this endpoint owes
them compared with the invoice-prep view:

  · Completeness beats precision. Time hidden from this screen is money quietly
    left on the table, so it counts every committed block and reports what has
    not been reviewed as a caveat rather than filtering it away. The older
    client-summary view defaulted to only_approved=True, which is right when the
    output is an invoice and wrong when the output is a judgement call — that
    view has since been removed along with the Client Billing tab it served.

  · A number alone settles nothing. "Acme: 47 hours" is not a decision; it
    becomes one next to what you charged last year, what the engagement was
    budgeted at, and what the standing arrangement says. Those three anchors
    live in three different tables and nothing had ever put them side by side.

  · Confidence belongs to the CLIENT, not the firm. A firm-wide 45% says
    nothing about whether to trust this row: Basilica had five people on it,
    and what matters is how completely those five were captured, weighted by
    how much of the work each of them did. One partner who never runs the agent
    makes his clients' numbers soft and nobody else's.

  · An anchor has to be measured the same way as the number beside it. A budget
    derived from a month when the agent saw 42% of the week, compared against a
    month when it saw more, reads as an overrun the firm never had — that is why
    set_engagement_budgets exists and why only a `manual` budget (the firm's own
    fee schedule, which the automatic ladder refuses to overwrite) is shown as a
    budget here. Everything else gets a SAME-BASIS anchor instead: this client's
    own typical period, carried across as a share of the firm's month rather
    than as raw hours, because coverage itself keeps moving (org 21 went from
    171.7h captured in May to 888.1h in August). A share cancels that drift —
    it lands on the numerator and the denominator alike — and answers what the
    partner is actually asking: is this month unusual for them?

  · Most of the list is not the work. 44 of org 21's 103 clients had under an
    hour in August; the top twenty are 72% of the month. A partner pricing his
    month should not wade through sub-hour rows to reach the eight that need
    thinking about, so the tail is split off here rather than left for the page
    to scroll past. `partition_material` is the same rule the rest of the
    product uses for "worth showing, never worth ranking".

  · The mix is the argument. A fee conversation turns on what the work *was* —
    a return versus a month of cleanup nobody scoped — so the breakdown by work
    type travels with the total instead of hiding behind a drill-down.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.analytics_v2.stats import partition_material
from tracker.models import Block, Client, Invoice, OrganizationMembership

ZERO = Decimal("0")
TOP_WORK_TYPES = 4


def _hours(minutes) -> float:
    return round(float(minutes or 0) / 60.0, 2)


def _prior_windows(start_d: date, end_d: date, n: int = 3):
    """The n windows immediately before this one, most recent first.

    Whole calendar months step by month so February is compared with January
    rather than with 28 days ending mid-January; anything else steps by its own
    length.
    """
    windows = []
    is_whole_month = (
        start_d.day == 1
        and end_d == (start_d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    )
    if is_whole_month:
        month_end = start_d - timedelta(days=1)
        for _ in range(n):
            windows.append((month_end.replace(day=1), month_end))
            month_end = month_end.replace(day=1) - timedelta(days=1)
        return windows
    span = (end_d - start_d).days + 1
    w_end = start_d - timedelta(days=1)
    for _ in range(n):
        windows.append((w_end - timedelta(days=span - 1), w_end))
        w_end = w_end - timedelta(days=span)
    return windows


def _capture_by_user(org, user_ids, start_d, end_d) -> dict[int, float]:
    """How much of each person's scheduled time we actually captured, 0..1.

    Same basis as the readiness checklist and the Review tab — tracked working
    hours over calendar capacity — so the firm is never told two different
    coverage numbers by two different screens.

    Non-chargeable staff are left out entirely, the same population filter firm
    utilization uses. This page shipped without it and the first thing it did
    was accuse someone: org 21's admin read 21% captured, which looked like a
    dead agent and was nothing of the sort — her agent reported today, she works
    about 3.8h a day across 14 days a month, and the firm has already declared
    her tier non-chargeable. Measuring an admin against a fee-earner's eight-hour
    day produces a number that is wrong about her and drags the firm's average
    down with it.
    """
    from tracker.analytics_v2.blocks import working_qs
    from tracker.analytics_v2.capacity import capacity_hours_map
    from tracker.analytics_v2.cost_rates import non_utilization_user_ids

    excluded = non_utilization_user_ids(org)
    user_ids = [u for u in user_ids if u and u not in excluded]
    if not user_ids:
        return {}

    tracked = {
        r["user_id"]: (r["m"] or 0) / 60.0
        for r in (
            working_qs(
                Block.objects.filter(
                    org=org, user_id__in=user_ids,
                    day__gte=start_d, day__lte=end_d,
                ), org,
            )
            .values("user_id")
            .annotate(m=Sum("minutes"))
        )
    }
    capacity = capacity_hours_map(org, user_ids, start_d, end_d)
    out = {}
    for uid in user_ids:
        cap = capacity.get(uid) or 0
        if cap > 0:
            out[uid] = min(1.0, tracked.get(uid, 0.0) / cap)
    return out


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return round((ordered[mid - 1] + ordered[mid]) / 2, 2)


def _period_defaults(request):
    """Default to last completed month — the period a fee is usually set for."""
    start = request.query_params.get("start")
    end = request.query_params.get("end")
    if start and end:
        return date.fromisoformat(start), date.fromisoformat(end)
    today = date.today()
    this_month = today.replace(day=1)
    end_d = this_month - timedelta(days=1)
    return end_d.replace(day=1), end_d


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fee_basis(request):
    """GET /api/billing/fee-basis/?start=&end=

    One row per client that had time in the period, each carrying the evidence
    and the anchors needed to land on a number.
    """
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related("organization").first()
    if not membership:
        return Response({"error": "No organization"}, status=403)
    if membership.role not in ("owner", "admin", "manager"):
        return Response({"error": "Permission denied"}, status=403)

    org = membership.organization
    start_d, end_d = _period_defaults(request)

    # Everything captured in the window. Deliberately not filtered to approved:
    # see the module docstring — unreviewed time is reported, never hidden.
    blocks = Block.objects.filter(org=org, day__gte=start_d, day__lte=end_d)

    rows = (
        blocks.values("client_id", "client__name", "client__code")
        .annotate(
            total_minutes=Sum("minutes"),
            billable_minutes=Coalesce(Sum("minutes", filter=Q(is_billable=True)), 0),
            unapproved_minutes=Coalesce(Sum("minutes", filter=Q(approved=False)), 0),
            value=Coalesce(Sum("billing_amount", filter=Q(is_billable=True)), ZERO),
            people=Count("user_id", distinct=True),
        )
        .order_by("-value", "-total_minutes")
    )
    rows = [r for r in rows if r["client_id"]]
    client_ids = [r["client_id"] for r in rows]
    if not client_ids:
        return Response({
            "period": {"start": start_d.isoformat(), "end": end_d.isoformat()},
            "totals": {"clients": 0, "hours": 0, "value": 0, "unapproved_hours": 0},
            "clients": [],
        })

    # ── Anchors, gathered per table rather than per client ────────────────
    work_by_client = {}
    for w in (
        blocks.filter(client_id__in=client_ids)
        .values("client_id", "task_type__name")
        .annotate(minutes=Sum("minutes"))
        .order_by("client_id", "-minutes")
    ):
        work_by_client.setdefault(w["client_id"], []).append({
            "name": w["task_type__name"] or "Unclassified",
            "hours": _hours(w["minutes"]),
        })

    profiles = {
        c.id: getattr(c, "billing_profile", None)
        for c in Client.objects.filter(id__in=client_ids).select_related("billing_profile")
    }

    # Same window, previous year: the number a partner actually reaches for.
    try:
        ly_start = start_d.replace(year=start_d.year - 1)
        ly_end = end_d.replace(year=end_d.year - 1)
    except ValueError:                      # 29 Feb
        ly_start = start_d - timedelta(days=365)
        ly_end = end_d - timedelta(days=365)

    prior_year = dict(
        Invoice.objects.filter(
            org=org, client_id__in=client_ids,
            invoice_date__gte=ly_start, invoice_date__lte=ly_end,
        )
        .values_list("client_id")
        .annotate(total=Sum("amount"))
        .values_list("client_id", "total")
    )

    # ── How much of each client's month we actually saw ───────────────────
    # Weighted by who did the work: a client whose hours came mostly from
    # someone with patchy capture is a softer number than one worked by people
    # the agent sees all day, and a firm-wide average would hide both.
    minutes_by_client_user = {}
    for r in (
        blocks.filter(client_id__in=client_ids)
        .values("client_id", "user_id")
        .annotate(minutes=Sum("minutes"))
    ):
        minutes_by_client_user.setdefault(r["client_id"], []).append(
            (r["user_id"], r["minutes"] or 0)
        )
    all_user_ids = {u for rows_ in minutes_by_client_user.values() for u, _ in rows_}
    capture_by_user = _capture_by_user(org, all_user_ids, start_d, end_d)

    capture_by_client = {}
    for cid, pairs in minutes_by_client_user.items():
        weighted = [(capture_by_user[u], m) for u, m in pairs if u in capture_by_user]
        total_m = sum(m for _, m in weighted)
        if total_m > 0:
            capture_by_client[cid] = round(
                sum(cap * m for cap, m in weighted) / total_m, 3
            )

    last_invoice = {}
    for inv in Invoice.objects.filter(
        org=org, client_id__in=client_ids
    ).order_by("client_id", "-invoice_date"):
        last_invoice.setdefault(inv.client_id, {
            "date": inv.invoice_date.isoformat(),
            "amount": float(inv.amount or 0),
        })

    budgets = {}
    try:
        from tracker.models_engagements import Engagement
        for e in Engagement.objects.filter(
            org=org, client_id__in=client_ids,
            period_start__lte=end_d, period_end__gte=start_d,
        ):
            slot = budgets.setdefault(
                e.client_id, {"hours": ZERO, "amount": ZERO, "sources": set()}
            )
            slot["hours"] += e.budget_hours or ZERO
            slot["amount"] += e.budget_amount or ZERO
            if e.budget_hours:
                slot["sources"].add(e.budget_source or "none")
    except Exception:
        # Engagements are optional; their absence must not blank the screen.
        budgets = {}

    # ── The same-basis anchor: what this client's own recent periods looked
    # like, as a SHARE of the firm's month rather than as raw hours.
    #
    # Raw hours would repeat the mistake the budgets make. org 21 captured
    # 171.7h in May, 604.8h in June (three agents became nine), 888.1h in
    # August — so every client "grew" against their own history and the anchor
    # would cry overrun on all of them. A share cancels that: coverage moves
    # the numerator and the denominator together. Measured against the firm's
    # month, the median client now lands at 1.01x their own typical, and the
    # ones that are genuinely unusual still stand out.
    #
    # Two prior periods minimum — one month is an anecdote, and a client whose
    # only other month was their onboarding is worse than no anchor at all.
    firm_now_minutes = sum(r["total_minutes"] or 0 for r in rows)
    shares_by_client = {}
    for w_start, w_end in _prior_windows(start_d, end_d):
        window = Block.objects.filter(
            org=org, client_id__isnull=False, day__gte=w_start, day__lte=w_end
        )
        firm_minutes = window.aggregate(m=Sum("minutes"))["m"] or 0
        if firm_minutes <= 0:
            continue
        for r in (
            window.filter(client_id__in=client_ids)
            .values("client_id")
            .annotate(minutes=Sum("minutes"))
        ):
            if r["minutes"]:
                shares_by_client.setdefault(r["client_id"], []).append(
                    float(r["minutes"]) / float(firm_minutes)
                )

    # ── Compose ───────────────────────────────────────────────────────────
    out = []
    for r in rows:
        cid = r["client_id"]
        work = sorted(work_by_client.get(cid, []), key=lambda w: -w["hours"])
        shown, rest = work[:TOP_WORK_TYPES], work[TOP_WORK_TYPES:]
        if rest:
            shown.append({
                "name": f"{len(rest)} other",
                "hours": round(sum(w["hours"] for w in rest), 2),
            })

        prof = profiles.get(cid)
        arrangement = {"type": "hourly", "amount": None, "period": None}
        if prof:
            arrangement = {
                "type": prof.billing_type or "hourly",
                "amount": float(prof.flat_amount) if prof.flat_amount else None,
                "period": prof.flat_period or None,
            }

        budget = budgets.get(cid)
        # Only the firm's own fee schedule is quoted as a budget. The derived
        # ladder (prior_year off an under-captured month, or the median of
        # equally under-captured peers) is measured differently from the hours
        # it would be compared against, so it is carried for diagnostics and
        # never rendered as an overrun.
        budget_sources = sorted(budget["sources"]) if budget else []
        shares = shares_by_client.get(cid, [])
        typical = (
            round(_median(shares) * _hours(firm_now_minutes), 2)
            if len(shares) >= 2
            else None
        )
        # A share this small carries across as 0.0h, and "typical month 0.0h ·
        # +3.3h" is noise wearing the clothes of an anchor. 16 of org 21's 103
        # August clients landed here — a minute or two of time in each of two
        # prior months. No anchor says the same thing honestly.
        if typical is not None and typical < 0.1:
            typical = None
        out.append({
            "client_id": cid,
            "name": r["client__name"] or "Unassigned",
            "code": r["client__code"] or "",
            "hours": _hours(r["total_minutes"]),
            "billable_hours": _hours(r["billable_minutes"]),
            "unapproved_hours": _hours(r["unapproved_minutes"]),
            "value_at_rates": float(r["value"] or 0),
            "people": r["people"],
            "capture": capture_by_client.get(cid),
            "work": shown,
            "arrangement": arrangement,
            "budget_hours": float(budget["hours"]) if budget and budget["hours"] else None,
            "budget_amount": float(budget["amount"]) if budget and budget["amount"] else None,
            "budget_is_fee": budget_sources == ["manual"],
            "budget_sources": budget_sources,
            "typical_hours": typical,
            "typical_periods": len(shares),
            "prior_year_billed": float(prior_year[cid]) if cid in prior_year else None,
            "last_invoice": last_invoice.get(cid),
        })

    # An hour is the line. Below it a client is a rounding error on the month
    # — min_share is off deliberately, because a 1%-of-the-firm floor would be
    # 5.1h here and bury clients this firm genuinely charges for.
    material, tail = partition_material(
        out, "hours", min_weight=1.0, min_share=0.0,
        revenue_key="value_at_rates", min_revenue=250.0,
    )
    tail_ids = {c["client_id"] for c in tail}
    for c in out:
        c["material"] = c["client_id"] not in tail_ids

    # The firm's own capture over this period, and the time we did see but
    # could not put against a client — which on this page is money sitting one
    # decision away from being billable.
    firm_users = list(blocks.order_by().values_list("user_id", flat=True).distinct())
    firm_capture_map = _capture_by_user(org, firm_users, start_d, end_d)
    firm_capture = (round(sum(firm_capture_map.values()) / len(firm_capture_map), 3)
                    if firm_capture_map else None)
    # BILLABLE and client-less. The raw figure is 378h at org 21 in August and
    # would have been a lie on this page: 331h of it is already marked
    # non-billable — someone's lunch, admin, 204h the classifier never gave a
    # task type. What is actually one decision away from a client's row is
    # 47.1h, and a reference that overstates by eight times is not one.
    unassigned_minutes = (
        blocks.filter(client_id__isnull=True, is_billable=True)
        .aggregate(m=Sum("minutes"))["m"] or 0
    )

    total_hours = round(sum(c["hours"] for c in out), 2)
    unapproved = round(sum(c["unapproved_hours"] for c in out), 2)
    # A firm that has never approved anything is not "behind on review" — it
    # simply does not use the workflow. Only call it out where it discriminates.
    uses_approval = 0 < unapproved < total_hours

    return Response({
        "period": {"start": start_d.isoformat(), "end": end_d.isoformat()},
        "totals": {
            "clients": len(out),
            "hours": total_hours,
            "value": round(sum(c["value_at_rates"] for c in out), 2),
            "unapproved_hours": unapproved,
        },
        "uses_approval": uses_approval,
        "tail": {
            "clients": len(tail),
            "hours": round(sum(c["hours"] for c in tail), 2),
            "value": round(sum(c["value_at_rates"] for c in tail), 2),
        },
        # What the whole page is standing on. Said once, at the top, because a
        # firm pricing off a silent under-count either loses money or applies a
        # private gut multiplier — and in the second case the barometer is the
        # partner's instinct and these numbers are decoration.
        "completeness": {
            "capture": firm_capture,
            "unassigned_billable_hours": _hours(unassigned_minutes),
        },
        "clients": out,
    })
