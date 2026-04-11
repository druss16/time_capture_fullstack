# tracker/views_analytics_tax_returns.py
"""
Tax Returns Analytics API
==========================
GET /api/analytics/tax-returns/?period=12m

CPA-specific KPIs broken down by individual taxpayer / return:
  - Total returns worked in period
  - Time per taxpayer (across all staff)
  - Return type breakdown (1040 / 1065 / 1120S / etc.)
  - Staff breakdown per taxpayer
  - Average time per return type (benchmarking)
  - Returns in progress today / this week

Requires: owner / admin / manager role
Plan gate: professional or executive (trial allowed)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import (
    Block,
    OrganizationMembership,
    TaxpayerBucket,
)

logger = logging.getLogger(__name__)
User = get_user_model()


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
        logger.error("[TAX-ANALYTICS] get_user_org error: %s", exc)
        return None


def _safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _parse_period(period: str):
    from datetime import date
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
    from datetime import date as date_type
    return date_type(year, month, 1), today


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tax_returns_dashboard(request):
    """
    GET /api/analytics/tax-returns/?period=12m
    """
    user = request.user

    # ── Admin org override ─────────────────────────────────────────────────
    org_id_override = request.GET.get("org_id")
    if org_id_override and (user.is_staff or user.is_superuser):
        from tracker.models import Organization
        try:
            org = Organization.objects.get(id=org_id_override)
        except Organization.DoesNotExist:
            return Response({"error": "Org not found"}, status=404)
        membership = None
    else:
        org = _get_user_org(user)
        if not org:
            return Response({"error": "No organization found"}, status=404)
        membership = OrganizationMembership.objects.filter(
            user=user, organization=org
        ).first()
        if not membership or membership.role not in ("owner", "admin", "manager"):
            return Response({"error": "Permission denied. Manager role or above required."}, status=403)
        plan = getattr(org, "plan", "none") or "none"
        if not any(plan.startswith(p) for p in ("professional", "executive")):
            return Response({"error": "upgrade_required", "current_plan": plan}, status=403)

    period = (request.GET.get("period") or "12m").strip()
    try:
        start_date, end_date = _parse_period(period)
    except Exception:
        return Response({"error": f"Invalid period '{period}'"}, status=400)

    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())

    # =========================================================================
    # Pull all blocks with taxpayer info in the period
    # =========================================================================
    blocks = list(
        Block.objects.filter(
            org=org,
            day__gte=start_date,
            day__lte=end_date,
            deleted_at__isnull=True,
        )
        .exclude(taxpayer_name__isnull=True)
        .exclude(taxpayer_name="")
        .select_related("user", "taxpayer_bucket")
        .order_by("day")
    )

    # Also pull blocks with Internal - Tax client (no taxpayer bucket yet)
    internal_tax_blocks = list(
        Block.objects.filter(
            org=org,
            day__gte=start_date,
            day__lte=end_date,
            deleted_at__isnull=True,
            client__name="Internal - Tax",
            taxpayer_name__isnull=True,
        )
        .select_related("user")
    )

    # =========================================================================
    # Aggregate by taxpayer
    # =========================================================================
    taxpayer_data = defaultdict(lambda: {
        "taxpayer_name": "",
        "taxpayer_id_hash": "",
        "return_type": "",
        "total_minutes": 0,
        "staff": defaultdict(int),
        "days_worked": set(),
        "last_worked": None,
    })

    for block in blocks:
        key = block.taxpayer_id_hash or block.taxpayer_name
        d = taxpayer_data[key]
        d["taxpayer_name"] = block.taxpayer_name or ""
        d["taxpayer_id_hash"] = block.taxpayer_id_hash or ""
        d["return_type"] = block.tax_return_type or "1040"
        d["total_minutes"] += block.minutes or 0
        name = f"{block.user.first_name} {block.user.last_name}".strip() or block.user.username
        d["staff"][name] += block.minutes or 0
        d["days_worked"].add(block.day)
        if not d["last_worked"] or block.day > d["last_worked"]:
            d["last_worked"] = block.day

    # =========================================================================
    # Return type breakdown
    # =========================================================================
    return_type_totals = defaultdict(lambda: {"count": 0, "total_minutes": 0})
    for d in taxpayer_data.values():
        rt = d["return_type"] or "1040"
        return_type_totals[rt]["count"] += 1
        return_type_totals[rt]["total_minutes"] += d["total_minutes"]

    # =========================================================================
    # Staff leaderboard
    # =========================================================================
    staff_totals = defaultdict(int)
    for d in taxpayer_data.values():
        for name, mins in d["staff"].items():
            staff_totals[name] += mins

    # =========================================================================
    # Today / this week activity
    # =========================================================================
    today_blocks = [b for b in blocks if b.day == today]
    week_blocks = [b for b in blocks if b.day >= week_start]

    today_taxpayers = set(b.taxpayer_name for b in today_blocks if b.taxpayer_name)
    week_taxpayers = set(b.taxpayer_name for b in week_blocks if b.taxpayer_name)

    today_minutes = sum(b.minutes or 0 for b in today_blocks)
    week_minutes = sum(b.minutes or 0 for b in week_blocks)

    # =========================================================================
    # Build sorted taxpayer list
    # =========================================================================
    taxpayer_list = []
    for key, d in taxpayer_data.items():
        hours = round(d["total_minutes"] / 60, 2)
        staff_breakdown = [
            {"name": name, "hours": round(mins / 60, 2)}
            for name, mins in sorted(d["staff"].items(), key=lambda x: -x[1])
        ]
        taxpayer_list.append({
            "taxpayer_name": d["taxpayer_name"],
            "taxpayer_id_hash": d["taxpayer_id_hash"],
            "return_type": d["return_type"] or "1040",
            "total_hours": hours,
            "total_minutes": d["total_minutes"],
            "staff_count": len(d["staff"]),
            "staff": staff_breakdown,
            "days_worked": len(d["days_worked"]),
            "last_worked": d["last_worked"].isoformat() if d["last_worked"] else None,
            "worked_today": d["last_worked"] == today if d["last_worked"] else False,
            "worked_this_week": d["last_worked"] >= week_start if d["last_worked"] else False,
        })

    taxpayer_list.sort(key=lambda x: -x["total_hours"])

    # =========================================================================
    # Return type summary
    # =========================================================================
    return_type_list = [
        {
            "return_type": rt,
            "count": data["count"],
            "total_hours": round(data["total_minutes"] / 60, 2),
            "avg_hours": round(data["total_minutes"] / 60 / data["count"], 2) if data["count"] else 0,
        }
        for rt, data in sorted(return_type_totals.items(), key=lambda x: -x[1]["total_minutes"])
    ]

    # =========================================================================
    # Staff leaderboard
    # =========================================================================
    staff_list = [
        {"name": name, "total_hours": round(mins / 60, 2), "returns_worked": sum(
            1 for d in taxpayer_data.values() if name in d["staff"]
        )}
        for name, mins in sorted(staff_totals.items(), key=lambda x: -x[1])
    ]

    # =========================================================================
    # Summary KPIs
    # =========================================================================
    total_returns = len(taxpayer_list)
    total_tax_hours = round(sum(d["total_minutes"] for d in taxpayer_data.values()) / 60, 2)
    avg_hours_per_return = round(total_tax_hours / total_returns, 2) if total_returns else 0

    # Internal-tax unmatched time
    unmatched_minutes = sum(b.minutes or 0 for b in internal_tax_blocks)

    return Response({
        "meta": {
            "org_id": org.id,
            "org_name": org.name,
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "generated_at": timezone.now().isoformat(),
        },
        "summary": {
            "total_returns": total_returns,
            "total_tax_hours": total_tax_hours,
            "avg_hours_per_return": avg_hours_per_return,
            "returns_worked_today": len(today_taxpayers),
            "returns_worked_this_week": len(week_taxpayers),
            "hours_today": round(today_minutes / 60, 2),
            "hours_this_week": round(week_minutes / 60, 2),
            "unmatched_internal_tax_hours": round(unmatched_minutes / 60, 2),
        },
        "taxpayers": taxpayer_list,
        "return_types": return_type_list,
        "staff": staff_list,
    })