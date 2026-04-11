# tracker/views_analytics.py
"""
Executive Analytics Dashboard API
===================================
GET /api/analytics/executive/?period=12m

C-level KPIs for CPA firm owners/admins:
  - Realization Rate      (billed ÷ worked hours, per client)
  - Billable Utilization  (billable ÷ total tracked, per staff)
  - WIP Pipeline          (approved & uninvoiced, aged buckets)
  - Effective Billing Rate (actual revenue ÷ billable hours)
  - Revenue Trend         (rolling months from Invoice)
  - Client Profitability  (revenue − labor cost, per client)
  - Timesheet Compliance  (% submitted on time, trend)
  - Invoice Cycle Time    (approval → invoiced avg days)

Period param: 3m | 6m | 12m | ytd | YYYY-MM-DD:YYYY-MM-DD
Requires: owner / admin / manager role
Plan gate: professional or executive (trial allowed)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth, Coalesce
from django.utils import timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import (
    Block,
    Client,
    Invoice,
    Organization,
    OrganizationMembership,
    Timesheet,
    EmployeeCostRate,
)

# BillingRate may not exist in all schema versions — import safely
try:
    from tracker.models import BillingRate
except ImportError:
    BillingRate = None

logger = logging.getLogger(__name__)
User = get_user_model()


# ============================================================================
# Shared helpers
# ============================================================================

def _get_user_org(user):
    try:
        membership = (
            OrganizationMembership.objects
            .filter(user=user, role="owner")
            .select_related("organization")
            .first()
        )
        if not membership:
            membership = (
                OrganizationMembership.objects
                .filter(user=user)
                .select_related("organization")
                .order_by("-id")
                .first()
            )
        return membership.organization if membership else None
    except Exception as exc:
        logger.error("[ANALYTICS] get_user_org error: %s", exc)
        return None


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _parse_period(period: str) -> tuple[date, date]:
    """
    '12m'  → last 12 calendar months (first of start-month → today)
    'ytd'  → Jan 1 this year → today
    'YYYY-MM-DD:YYYY-MM-DD' → explicit range
    """
    today = timezone.now().date()

    if ":" in period:
        parts = period.split(":", 1)
        return date.fromisoformat(parts[0]), date.fromisoformat(parts[1])

    if period == "ytd":
        return today.replace(month=1, day=1), today

    months_map = {"3m": 3, "6m": 6, "12m": 12, "24m": 24}
    n = months_map.get(period, 12)

    year, month = today.year, today.month - n
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1), today


def _months_between(start: date, end: date) -> list[date]:
    """All first-of-month dates from start → end (inclusive)."""
    result, cur = [], start.replace(day=1)
    while cur <= end:
        result.append(cur)
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result


# ============================================================================
# KPI: Realization Rate
# ============================================================================

def _calc_realization(org, start_date: date, end_date: date) -> dict:
    """
    Realization = Billed Hours (Invoice) ÷ Worked Hours (Block) × 100
    Thresholds match views_billing.py: ≥125 excellent, ≥100 good,
    ≥85 warning, <85 critical.
    """
    # --- Invoiced hours by client ---
    invoiced_qs = (
        Invoice.objects
        .filter(org=org, invoice_date__gte=start_date,
                invoice_date__lte=end_date, client__isnull=False)
        .values("client_id", "client__name")
        .annotate(
            billed_hours=Coalesce(Sum("hours_billed"), Decimal("0")),
            billed_amount=Coalesce(Sum("amount"), Decimal("0")),
        )
    )
    invoiced = {
        r["client_id"]: {
            "name": r["client__name"],
            "billed_hours": _safe_float(r["billed_hours"]),
            "billed_amount": _safe_float(r["billed_amount"]),
        }
        for r in invoiced_qs
    }

    # --- Worked (billable) hours by client ---
    worked_qs = (
        Block.objects
        .filter(org=org, day__gte=start_date, day__lte=end_date,
                is_billable=True, client__isnull=False)
        .values("client_id", "client__name")
        .annotate(worked_minutes=Coalesce(Sum("minutes"), 0))
    )
    worked = {
        r["client_id"]: {
            "name": r["client__name"],
            "worked_hours": _safe_float(r["worked_minutes"]) / 60.0,
        }
        for r in worked_qs
    }

    all_ids = set(invoiced) | set(worked)
    clients, total_billed, total_worked = [], 0.0, 0.0

    for cid in all_ids:
        inv = invoiced.get(cid, {})
        wrk = worked.get(cid, {})
        bh = inv.get("billed_hours", 0.0)
        wh = wrk.get("worked_hours", 0.0)
        name = inv.get("name") or wrk.get("name", "Unknown")

        if wh > 0 and bh > 0:
            rate = bh / wh * 100
        elif wh > 0:
            rate = 0.0
        else:
            rate = 100.0  # invoiced with no tracked time

        if rate >= 125:
            status = "excellent"
        elif rate >= 100:
            status = "good"
        elif rate >= 85:
            status = "warning"
        else:
            status = "critical"

        clients.append({
            "client_id": cid,
            "client_name": name,
            "billed_hours": round(bh, 2),
            "worked_hours": round(wh, 2),
            "billed_amount": round(inv.get("billed_amount", 0.0), 2),
            "realization": round(rate, 1),
            "status": status,
        })
        total_billed += bh
        total_worked += wh

    clients.sort(key=lambda x: x["realization"])
    overall = (total_billed / total_worked * 100) if total_worked > 0 else 0.0

    return {
        "overall": round(overall, 1),
        "total_billed_hours": round(total_billed, 2),
        "total_worked_hours": round(total_worked, 2),
        "clients": clients,
    }


# ============================================================================
# KPI: Billable Utilization
# ============================================================================

def _calc_billable_utilization(org, start_date: date, end_date: date) -> dict:
    """
    Utilization = Billable Hours ÷ Total Tracked Hours × 100, per staff.
    """
    qs = (
        Block.objects
        .filter(org=org, day__gte=start_date, day__lte=end_date)
        .values("user_id", "user__username", "user__first_name",
                "user__last_name", "is_billable")
        .annotate(mins=Coalesce(Sum("minutes"), 0))
    )

    staff: dict = defaultdict(lambda: {"name": "", "billable": 0, "total": 0})
    for r in qs:
        uid = r["user_id"]
        fn = (r["user__first_name"] or "").strip()
        ln = (r["user__last_name"] or "").strip()
        staff[uid]["name"] = (f"{fn} {ln}".strip()) or r["user__username"]
        staff[uid]["total"] += r["mins"]
        if r["is_billable"]:
            staff[uid]["billable"] += r["mins"]

    staff_list, org_bill, org_total = [], 0, 0
    for uid, d in staff.items():
        bh = d["billable"] / 60.0
        th = d["total"] / 60.0
        util = (bh / th * 100) if th > 0 else 0.0
        staff_list.append({
            "user_id": uid,
            "name": d["name"],
            "billable_hours": round(bh, 2),
            "total_hours": round(th, 2),
            "utilization": round(util, 1),
        })
        org_bill += d["billable"]
        org_total += d["total"]

    staff_list.sort(key=lambda x: -x["utilization"])
    overall = (org_bill / org_total * 100) if org_total > 0 else 0.0

    return {
        "overall": round(overall, 1),
        "total_billable_hours": round(org_bill / 60.0, 2),
        "total_tracked_hours": round(org_total / 60.0, 2),
        "staff": staff_list,
    }


# ============================================================================
# KPI: WIP Pipeline
# ============================================================================

def _calc_wip(org) -> dict:
    """
    WIP = approved=True AND invoiced=False blocks.
    Aged into 0-30 / 31-60 / 61-90 / 90+ day buckets by approved_at.
    """
    blocks = (
        Block.objects
        .filter(org=org, approved=True, invoiced=False, is_billable=True)
        .select_related("client")
    )
    now = timezone.now()
    buckets = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    client_wip: dict[str, float] = defaultdict(float)
    total = 0.0

    default_rate = _safe_float(getattr(org, "billing_rate_default", 0))

    for b in blocks:
        amount = _safe_float(b.billing_amount)
        if not amount:
            hours = _safe_float(b.minutes) / 60.0
            rate = _safe_float(b.billing_rate) or default_rate
            amount = hours * rate

        ref = b.approved_at or b.start
        if ref:
            if timezone.is_naive(ref):
                ref = timezone.make_aware(ref)
            age = (now - ref).days
        else:
            age = 0

        if age <= 30:
            buckets["0_30"] += amount
        elif age <= 60:
            buckets["31_60"] += amount
        elif age <= 90:
            buckets["61_90"] += amount
        else:
            buckets["90_plus"] += amount

        total += amount
        cname = b.client.name if b.client else "Unassigned"
        client_wip[cname] += amount

    top_clients = sorted(
        [{"client": k, "wip": round(v, 2)} for k, v in client_wip.items()],
        key=lambda x: -x["wip"],
    )[:10]

    return {
        "total": round(total, 2),
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "top_clients": top_clients,
    }


# ============================================================================
# KPI: Effective Billing Rate
# ============================================================================

def _calc_effective_rate(org, start_date: date, end_date: date) -> dict:
    """
    Effective Rate = Total Billing Amount ÷ Total Billable Hours
    """
    agg = Block.objects.filter(
        org=org, day__gte=start_date, day__lte=end_date, is_billable=True,
    ).aggregate(
        total_amount=Coalesce(Sum("billing_amount"), Decimal("0")),
        total_minutes=Coalesce(Sum("minutes"), 0),
    )
    total_hours = _safe_float(agg["total_minutes"]) / 60.0
    total_amount = _safe_float(agg["total_amount"])
    eff = (total_amount / total_hours) if total_hours > 0 else 0.0
    standard = _safe_float(getattr(org, "billing_rate_default", 0))

    return {
        "effective_rate": round(eff, 2),
        "standard_rate": round(standard, 2),
        "variance": round(eff - standard, 2),
        "total_billable_hours": round(total_hours, 2),
        "total_revenue": round(total_amount, 2),
    }


# ============================================================================
# KPI: Revenue Trend
# ============================================================================

def _calc_revenue_trend(org, start_date: date, end_date: date) -> dict:
    """
    Monthly invoice revenue from Invoice model. Every month in the range
    is included (zeros for months with no invoices).
    """
    months = _months_between(start_date, end_date)

    inv_qs = (
        Invoice.objects
        .filter(org=org, invoice_date__gte=start_date, invoice_date__lte=end_date)
        .annotate(month=TruncMonth("invoice_date"))
        .values("month")
        .annotate(
            revenue=Coalesce(Sum("amount"), Decimal("0")),
            hours=Coalesce(Sum("hours_billed"), Decimal("0")),
            invoice_count=Count("id"),
        )
        .order_by("month")
    )

    inv_by_month: dict = {}
    for r in inv_qs:
        m = r["month"]
        key = m.date() if hasattr(m, "date") else m
        inv_by_month[key] = r

    trend = []
    for m in months:
        r = inv_by_month.get(m, {})
        trend.append({
            "month": m.strftime("%Y-%m"),
            "month_label": m.strftime("%b %Y"),
            "revenue": round(_safe_float(r.get("revenue")), 2),
            "hours": round(_safe_float(r.get("hours")), 2),
            "invoice_count": r.get("invoice_count", 0),
        })

    total = sum(t["revenue"] for t in trend)
    avg = total / len(trend) if trend else 0.0

    return {
        "trend": trend,
        "total_revenue": round(total, 2),
        "avg_monthly_revenue": round(avg, 2),
    }


# ============================================================================
# KPI: Client Profitability
# ============================================================================

def _calc_profitability(org, start_date: date, end_date: date) -> dict:
    """
    Profit = Revenue (billing_amount) - Cost (hours × EmployeeCostRate.cost_rate)
    EmployeeCostRate FK is `organization` (not `org`); field is `cost_rate`.
    """
    # Most recent cost rate per user (FK: organization)
    cost_rates: dict[int, float] = {}
    for rate in (
        EmployeeCostRate.objects
        .filter(organization=org)
        .select_related("user")
        .order_by("user_id", "-effective_date")
    ):
        if rate.user_id not in cost_rates:
            cost_rates[rate.user_id] = _safe_float(rate.cost_rate)

    default_cost = _safe_float(getattr(org, "cost_rate_default", 75.0)) or 75.0
    default_bill = _safe_float(getattr(org, "billing_rate_default", 0))

    blocks = (
        Block.objects
        .filter(org=org, day__gte=start_date, day__lte=end_date, is_billable=True)
        .select_related("client", "user")
    )

    data: dict = defaultdict(lambda: {"name": "", "revenue": 0.0, "cost": 0.0, "hours": 0.0})
    for b in blocks:
        cid = b.client_id or 0
        cname = b.client.name if b.client else "Unassigned"
        hours = _safe_float(b.minutes) / 60.0
        revenue = _safe_float(b.billing_amount)
        if not revenue:
            rate = _safe_float(b.billing_rate) or default_bill
            revenue = hours * rate
        cost = hours * cost_rates.get(b.user_id, default_cost)

        data[cid]["name"] = cname
        data[cid]["revenue"] += revenue
        data[cid]["cost"] += cost
        data[cid]["hours"] += hours

    clients = []
    for cid, d in data.items():
        margin = d["revenue"] - d["cost"]
        margin_pct = (margin / d["revenue"] * 100) if d["revenue"] > 0 else 0.0
        clients.append({
            "client_id": cid,
            "client_name": d["name"],
            "revenue": round(d["revenue"], 2),
            "cost": round(d["cost"], 2),
            "margin": round(margin, 2),
            "margin_pct": round(margin_pct, 1),
            "hours": round(d["hours"], 2),
        })

    clients.sort(key=lambda x: -x["revenue"])
    tr = sum(c["revenue"] for c in clients)
    tc = sum(c["cost"] for c in clients)
    tm = tr - tc

    return {
        "clients": clients,
        "totals": {
            "revenue": round(tr, 2),
            "cost": round(tc, 2),
            "margin": round(tm, 2),
            "margin_pct": round(tm / tr * 100, 1) if tr > 0 else 0.0,
        },
    }


# ============================================================================
# KPI: Timesheet Compliance
# ============================================================================

def _calc_timesheet_compliance(org, start_date: date, end_date: date) -> dict:
    """
    Compliance = % of timesheets submitted within GRACE_DAYS after week end.
    Timesheet FK is `org` (confirmed in views_billing.py).
    """
    GRACE_DAYS = 2

    timesheets = Timesheet.objects.filter(
        org=org,
        week_start__gte=start_date,
        week_start__lte=end_date,
    ).exclude(status="draft")

    total = timesheets.count()
    if total == 0:
        return {"overall": None, "total_timesheets": 0,
                "compliant": 0, "late": 0, "trend": []}

    compliant = 0
    late = 0
    monthly: dict = defaultdict(lambda: {"compliant": 0, "total": 0})

    for ts in timesheets:
        week_end = ts.week_start + timedelta(days=6)
        deadline = week_end + timedelta(days=GRACE_DAYS)
        mk = ts.week_start.replace(day=1).strftime("%Y-%m")
        monthly[mk]["total"] += 1

        if ts.submitted_at:
            sub_date = (ts.submitted_at.date()
                        if hasattr(ts.submitted_at, "date")
                        else ts.submitted_at)
            if sub_date <= deadline:
                compliant += 1
                monthly[mk]["compliant"] += 1
            else:
                late += 1
        else:
            late += 1  # never submitted

    overall = (compliant / total * 100) if total > 0 else 0.0

    trend = [
        {
            "month": k,
            "compliance": round(v["compliant"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0,
            "total": v["total"],
            "compliant": v["compliant"],
        }
        for k, v in sorted(monthly.items())
    ]

    return {
        "overall": round(overall, 1),
        "total_timesheets": total,
        "compliant": compliant,
        "late": late,
        "grace_days": GRACE_DAYS,
        "trend": trend,
    }


# ============================================================================
# KPI: Invoice Cycle Time
# ============================================================================

def _calc_invoice_cycle_time(org, start_date: date, end_date: date) -> dict:
    """
    Avg/median days from Timesheet.approved_at → Block.invoiced_at.
    """
    blocks = (
        Block.objects
        .filter(
            org=org,
            day__gte=start_date,
            day__lte=end_date,
            invoiced=True,
            invoiced_at__isnull=False,
        )
        .select_related("timesheet")
    )

    cycle_times = []
    for b in blocks:
        ts = b.timesheet
        if ts and ts.approved_at and b.invoiced_at:
            days = (b.invoiced_at - ts.approved_at).days
            if 0 <= days <= 365:
                cycle_times.append(days)

    if not cycle_times:
        return {"avg_days": None, "median_days": None, "sample_size": 0}

    cycle_times.sort()
    avg = sum(cycle_times) / len(cycle_times)
    n = len(cycle_times)
    mid = n // 2
    median = cycle_times[mid] if n % 2 else (cycle_times[mid - 1] + cycle_times[mid]) / 2.0

    return {
        "avg_days": round(avg, 1),
        "median_days": round(median, 1),
        "sample_size": n,
    }


# ============================================================================
# Helper: Resolve BillingRate for a block
# ============================================================================

def _get_billing_rate(org, user_id: int, client_id: int | None,
                      task_type_id: int | None) -> Decimal:
    """
    Resolve the correct BillingRate using priority hierarchy:
    1. user + client + task_type  (most specific)
    2. user + client
    3. client + task_type
    4. client only
    5. user only
    6. org default
    """
    if BillingRate is None:
        return Decimal(str(_safe_float(getattr(org, "billing_rate_default", 0))))

    qs = BillingRate.objects.filter(org=org).order_by("-effective_date")

    filters = []
    if user_id and client_id and task_type_id:
        filters.append(Q(user_id=user_id, client_id=client_id, task_type_id=task_type_id))
    if user_id and client_id:
        filters.append(Q(user_id=user_id, client_id=client_id, task_type__isnull=True))
    if client_id and task_type_id:
        filters.append(Q(user_id__isnull=True, client_id=client_id, task_type_id=task_type_id))
    if client_id:
        filters.append(Q(user_id__isnull=True, client_id=client_id, task_type__isnull=True))
    if user_id:
        filters.append(Q(user_id=user_id, client__isnull=True, task_type__isnull=True))

    for f in filters:
        match = qs.filter(f).first()
        if match:
            return match.rate

    return Decimal(str(_safe_float(getattr(org, "billing_rate_default", 0))))


# ============================================================================
# KPI: Invoice-based Profitability (Invoice Revenue vs Worked Cost)
# ============================================================================

def _calc_invoice_profitability(org, start_date: date, end_date: date) -> dict:
    """
    True profitability using ACTUAL invoiced revenue (not estimated billing_amount).

    Revenue  = SUM(Invoice.amount) per client in period
    Cost     = SUM(Block.minutes / 60 × EmployeeCostRate.cost_rate) per client
    Margin   = Revenue − Cost

    Also computes per-client breakdown by task_type (service line) using
    BillingRate to show rate mix.
    """
    # --- Cost rates per user ---
    cost_rates: dict[int, float] = {}
    for cr in (
        EmployeeCostRate.objects
        .filter(organization=org)
        .select_related("user")
        .order_by("user_id", "-effective_date")
    ):
        if cr.user_id not in cost_rates:
            cost_rates[cr.user_id] = _safe_float(cr.cost_rate)

    default_cost = _safe_float(getattr(org, "cost_rate_default", 75.0)) or 75.0

    # --- Invoiced revenue per client ---
    inv_qs = (
        Invoice.objects
        .filter(org=org, invoice_date__gte=start_date,
                invoice_date__lte=end_date, client__isnull=False)
        .values("client_id", "client__name")
        .annotate(
            invoiced_amount=Coalesce(Sum("amount"), Decimal("0")),
            invoiced_hours =Coalesce(Sum("hours_billed"), Decimal("0")),
            invoice_count  =Count("id"),
        )
    )
    invoiced: dict[int, dict] = {}
    for r in inv_qs:
        invoiced[r["client_id"]] = {
            "name":           r["client__name"],
            "invoiced_amount": _safe_float(r["invoiced_amount"]),
            "invoiced_hours":  _safe_float(r["invoiced_hours"]),
            "invoice_count":   r["invoice_count"],
        }

    # --- Worked cost + hours per client, broken down by task_type ---
    blocks = (
        Block.objects
        .filter(org=org, day__gte=start_date, day__lte=end_date, is_billable=True)
        .select_related("client", "user", "task_type")
    )

    worked: dict[int, dict] = defaultdict(lambda: {
        "name": "", "cost": 0.0, "hours": 0.0,
        "services": defaultdict(lambda: {"hours": 0.0, "cost": 0.0}),
    })

    for b in blocks:
        cid   = b.client_id or 0
        hours = _safe_float(b.minutes) / 60.0
        cost  = hours * cost_rates.get(b.user_id, default_cost)
        svc   = b.task_type.name if b.task_type else "General"

        if b.client:
            worked[cid]["name"] = b.client.name
        elif cid == 0:
            worked[cid]["name"] = "Unassigned"

        worked[cid]["cost"]  += cost
        worked[cid]["hours"] += hours
        worked[cid]["services"][svc]["hours"] += hours
        worked[cid]["services"][svc]["cost"]  += cost

    # --- Merge invoiced + worked ---
    all_cids = set(invoiced) | {k for k in worked if k != 0}
    clients  = []

    for cid in all_cids:
        inv  = invoiced.get(cid, {})
        wrk  = worked.get(cid, {})
        name = inv.get("name") or wrk.get("name") or f"Client {cid}"

        invoiced_amt  = inv.get("invoiced_amount", 0.0)
        invoiced_hrs  = inv.get("invoiced_hours",  0.0)
        worked_hrs    = wrk.get("hours", 0.0)
        worked_cost   = wrk.get("cost",  0.0)
        invoice_count = inv.get("invoice_count", 0)

        margin     = invoiced_amt - worked_cost
        margin_pct = (margin / invoiced_amt * 100) if invoiced_amt > 0 else 0.0

        # Realization: invoiced hours ÷ worked hours
        realization = (invoiced_hrs / worked_hrs * 100) if worked_hrs > 0 else None

        # Service breakdown
        services = [
            {
                "service":  svc,
                "hours":    round(d["hours"], 2),
                "cost":     round(d["cost"],  2),
            }
            for svc, d in wrk.get("services", {}).items()
        ]
        services.sort(key=lambda x: -x["hours"])

        clients.append({
            "client_id":      cid,
            "client_name":    name,
            "invoiced_amount": round(invoiced_amt,  2),
            "invoiced_hours":  round(invoiced_hrs,  2),
            "worked_hours":    round(worked_hrs,    2),
            "worked_cost":     round(worked_cost,   2),
            "margin":          round(margin,        2),
            "margin_pct":      round(margin_pct,    1),
            "realization":     round(realization, 1) if realization is not None else None,
            "invoice_count":   invoice_count,
            "services":        services,
        })

    clients.sort(key=lambda x: -x["invoiced_amount"])

    # Totals
    total_invoiced = sum(c["invoiced_amount"] for c in clients)
    total_cost     = sum(c["worked_cost"]     for c in clients)
    total_margin   = total_invoiced - total_cost
    total_hours    = sum(c["worked_hours"]    for c in clients)

    return {
        "clients": clients,
        "totals": {
            "invoiced_amount": round(total_invoiced, 2),
            "worked_cost":     round(total_cost,     2),
            "margin":          round(total_margin,   2),
            "margin_pct":      round(total_margin / total_invoiced * 100, 1) if total_invoiced > 0 else 0.0,
            "worked_hours":    round(total_hours, 2),
        },
        "has_invoices": len(invoiced) > 0,
    }


# ============================================================================
# Main View
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def executive_dashboard(request):
    user = request.user

    # ── Admin org override ────────────────────────────────────────────────────
    org_id_override = request.GET.get("org_id")
    if org_id_override and (user.is_staff or user.is_superuser):
        try:
            org = Organization.objects.get(id=org_id_override)
        except Organization.DoesNotExist:
            return Response({"error": "Org not found"}, status=404)
        membership = None  # staff bypass — no membership needed
    else:
        org = _get_user_org(user)
        if not org:
            return Response({"error": "No organization found"}, status=404)
        membership = OrganizationMembership.objects.filter(
            user=user, organization=org
        ).first()
        if not membership or membership.role not in ("owner", "admin", "manager"):
            return Response(
                {"error": "Permission denied. Manager role or above required."},
                status=403,
            )

    # ── Plan gate (skip for staff) ────────────────────────────────────────────
    plan = getattr(org, "plan", "none") or "none"
    if not (user.is_staff or user.is_superuser):
        if not any(plan.startswith(p) for p in ("professional", "executive")):
            return Response(
                {
                    "error": "upgrade_required",
                    "message": "Executive dashboard requires a Professional or Executive plan.",
                    "current_plan": plan,
                    "upgrade_url": "/account/billing",
                },
                status=403,
            )

    # ── Parse period ──────────────────────────────────────────────────────────
    period = (request.GET.get("period") or "12m").strip()
    try:
        start_date, end_date = _parse_period(period)
    except Exception:
        return Response({"error": f"Invalid period '{period}'"}, status=400)

    logger.info(
        "[ANALYTICS] executive_dashboard user=%s org=%s period=%s %s→%s",
        user.username, org.slug, period, start_date, end_date,
    )

    def _safe(fn, *args):
        try:
            return fn(*args)
        except Exception as exc:
            logger.error("[ANALYTICS] %s failed: %s", fn.__name__, exc, exc_info=True)
            return {"error": str(exc)}

    return Response({
        "meta": {
            "org_id": org.id,
            "org_name": org.name,
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": timezone.now().isoformat(),
            "plan": plan,
            "role": membership.role if membership else "staff",
        },
        "kpis": {
            "realization_rate":      _safe(_calc_realization,            org, start_date, end_date),
            "billable_utilization":  _safe(_calc_billable_utilization,   org, start_date, end_date),
            "wip_pipeline":          _safe(_calc_wip,                    org),
            "effective_rate":        _safe(_calc_effective_rate,         org, start_date, end_date),
            "revenue_trend":         _safe(_calc_revenue_trend,          org, start_date, end_date),
            "client_profitability":  _safe(_calc_profitability,          org, start_date, end_date),
            "invoice_profitability": _safe(_calc_invoice_profitability,  org, start_date, end_date),
            "timesheet_compliance":  _safe(_calc_timesheet_compliance,   org, start_date, end_date),
            "invoice_cycle_time":    _safe(_calc_invoice_cycle_time,     org, start_date, end_date),
        },
    })