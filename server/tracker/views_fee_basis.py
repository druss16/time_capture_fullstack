"""
tracker/views_fee_basis.py

What a partner needs in front of them to set a fair fee for a period — and
somewhere for the answer to go.

The second half was missing for a long time and it was the more important half.
The page showed a partner everything about a client's month and then ended:
they raised the invoice in their own system and came back to a list that looked
exactly as it had before, with no way to tell the eleven clients they had
settled from the seventy they had not. `decision` and `decided_totals` below
are what make eighty-two rows finite — and, because the firm records what it
charged as it goes, they become the anchor that invoice imports were never
going to supply.

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
from tracker.models import (
    BillingDecision, Block, Client, Invoice, OrganizationMembership,
)

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

    # ── What has already been settled for this period ─────────────────────
    decisions = {
        d.client_id: d
        for d in BillingDecision.objects.filter(
            org=org, client_id__in=client_ids,
            period_start=start_d, period_end=end_d,
        ).select_related("decided_by")
    }

    # And what they charged the period before — the firm's own record, which
    # needs no invoice to have been imported from anywhere.
    prev_windows = _prior_windows(start_d, end_d, n=1)
    last_decision = {}
    if prev_windows:
        p_start, p_end = prev_windows[0]
        last_decision = {
            d.client_id: {"amount": float(d.amount),
                          "period": p_start.isoformat()}
            for d in BillingDecision.objects.filter(
                org=org, client_id__in=client_ids,
                period_start=p_start, period_end=p_end,
            )
        }

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

        decision = decisions.get(cid)
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
            "last_charged": last_decision.get(cid),
            "decision": ({
                "amount": float(decision.amount),
                "note": decision.note,
                "decided_at": decision.decided_at.isoformat(),
                "decided_by": (decision.decided_by.username
                               if decision.decided_by else ""),
            } if decision else None),
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

    decided = [c for c in out if c["decision"]]
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
        # The two numbers that turn a list into a piece of work: how much of it
        # is done, and what has been charged so far.
        "decided": {
            "clients": len(decided),
            "amount": round(sum(c["decision"]["amount"] for c in decided), 2),
        },
        "clients": out,
    })


@api_view(["POST", "DELETE"])
@permission_classes([IsAuthenticated])
def fee_decision(request):
    """Record — or undo — what the firm charged one client for one period.

    POST {client_id, start, end, amount, note?}    DELETE {client_id, start, end}

    Deliberately forgiving about being called twice: a decision is upserted, so
    correcting a number is the same gesture as making it. And deliberately
    undoable — the row this settles disappears from the list, which is exactly
    the kind of action a person needs to be able to take back without asking
    anyone.
    """
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related("organization").first()
    if not membership:
        return Response({"error": "No organization"}, status=403)
    if membership.role not in ("owner", "admin", "manager"):
        return Response({"error": "Permission denied"}, status=403)

    org = membership.organization
    data = request.data or {}
    client_id = data.get("client_id")
    try:
        start_d = date.fromisoformat(data.get("start"))
        end_d = date.fromisoformat(data.get("end"))
    except (TypeError, ValueError):
        return Response({"error": "start and end must be YYYY-MM-DD"}, status=400)
    if not client_id or not Client.objects.filter(org=org, id=client_id).exists():
        return Response({"error": "Unknown client"}, status=404)

    if request.method == "DELETE":
        BillingDecision.objects.filter(
            org=org, client_id=client_id,
            period_start=start_d, period_end=end_d,
        ).delete()
        return Response({"client_id": client_id, "decision": None})

    try:
        amount = Decimal(str(data.get("amount")).replace("$", "").replace(",", ""))
    except (TypeError, ValueError, ArithmeticError):
        return Response({"error": "amount must be a number"}, status=400)
    if amount < 0:
        return Response({"error": "amount cannot be negative"}, status=400)

    # Snapshot what the page was showing. The hours keep moving after the call
    # is made, and the interesting question later is what the fee was charged
    # AGAINST, not what the client eventually accumulated.
    agg = Block.objects.filter(
        org=org, client_id=client_id, day__gte=start_d, day__lte=end_d,
    ).aggregate(
        minutes=Sum("minutes"),
        value=Coalesce(Sum("billing_amount", filter=Q(is_billable=True)), ZERO),
    )

    decision, _ = BillingDecision.objects.update_or_create(
        org=org, client_id=client_id, period_start=start_d, period_end=end_d,
        defaults={
            "amount": amount,
            "hours_at_decision": Decimal(str(_hours(agg["minutes"]))),
            "value_at_decision": agg["value"] or ZERO,
            "note": (data.get("note") or "")[:200],
            "decided_by": request.user,
        },
    )
    return Response({
        "client_id": client_id,
        "decision": {
            "amount": float(decision.amount),
            "note": decision.note,
            "decided_at": decision.decided_at.isoformat(),
            "decided_by": request.user.username,
        },
    })
