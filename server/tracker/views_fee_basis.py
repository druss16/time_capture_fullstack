"""
tracker/views_fee_basis.py

What a partner needs in front of them to set a fair fee for a period.

Firms do not bill straight out of TimeTracker — the numbers are a reference
they weigh against their own judgement. That changes what this endpoint owes
them compared with the invoice-prep view:

  · Completeness beats precision. Time hidden from this screen is money quietly
    left on the table, so it counts every committed block and reports what has
    not been reviewed as a caveat rather than filtering it away. The older
    client-summary view defaults to only_approved=True, which is right when the
    output is an invoice and wrong when the output is a judgement call.

  · A number alone settles nothing. "Acme: 47 hours" is not a decision; it
    becomes one next to what you charged last year, what the engagement was
    budgeted at, and what the standing arrangement says. Those three anchors
    live in three different tables and nothing had ever put them side by side.

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

from tracker.models import Block, Client, Invoice, OrganizationMembership

ZERO = Decimal("0")
TOP_WORK_TYPES = 4


def _hours(minutes) -> float:
    return round(float(minutes or 0) / 60.0, 2)


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
            slot = budgets.setdefault(e.client_id, {"hours": ZERO, "amount": ZERO})
            slot["hours"] += e.budget_hours or ZERO
            slot["amount"] += e.budget_amount or ZERO
    except Exception:
        # Engagements are optional; their absence must not blank the screen.
        budgets = {}

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
            "prior_year_billed": float(prior_year[cid]) if cid in prior_year else None,
            "last_invoice": last_invoice.get(cid),
        })

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
        "clients": out,
    })
