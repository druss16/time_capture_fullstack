# tracker/views_reports.py
"""
Simple high-level reporting for customer firms + MavOps admin.

ONE endpoint, TWO consumers:
  - Customer web account: role-gated (manager/owner/admin see all employees in
    their org; members see only themselves).
  - MavOps admin dashboard: staff/superuser pass ?org_id= to impersonate any org
    (reuses get_request_org_override, same as the rest of views.py).

Design goals:
  - Read from committed Blocks only (mirrors today_time's block-based source,
    avoids the IDLE_CAP vs event-total mismatch).
  - Bucket by day/week/month/quarter using TruncDay/Week/Month/Quarter.
  - Stays deliberately flat — no drilldowns. This is the layer BELOW the
    C-level ExecutiveDashboard v2, meant to give the 12 TL Wall users quick wins.

Wire into urls.py:
    path("api/reports/summary/", views_reports.reports_summary, name="reports_summary"),
    path("api/reports/summary/export/", views_reports.reports_summary_export, name="reports_summary_export"),
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db.models import Sum, Count, Q, F, Case, When, DecimalField, IntegerField
from django.db.models.functions import (
    TruncDay, TruncWeek, TruncMonth, TruncQuarter,
)
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import Block, OrganizationMembership

# Reuse the helpers already defined in views.py — single source of truth for
# org resolution + impersonation. (These are module-level functions in views.py.)
from tracker.views import (
    get_request_org_override,
    get_user_role,
)


# ──────────────────────────────────────────────────────────────────────────
# Period handling
# ──────────────────────────────────────────────────────────────────────────
_TRUNC = {
    "day": TruncDay,
    "week": TruncWeek,
    "month": TruncMonth,
    "quarter": TruncQuarter,
}

# Categories that should never count toward billable/total (mirrors today_time).
_EXCLUDE_CATEGORIES = {"idle", "uncategorized"}


def _resolve_period_window(period: str, anchor_date):
    """
    Given a period type and an anchor date, return (start_date, end_date)
    inclusive of the full natural period containing the anchor.

    day     → that single day
    week    → Monday..Sunday containing anchor
    month   → 1st..last of anchor's month
    quarter → first day..last day of anchor's quarter
    """
    d = anchor_date

    if period == "day":
        return d, d

    if period == "week":
        monday = d - timedelta(days=d.weekday())
        return monday, monday + timedelta(days=6)

    if period == "month":
        first = d.replace(day=1)
        # next month's first minus a day
        if first.month == 12:
            nxt = first.replace(year=first.year + 1, month=1)
        else:
            nxt = first.replace(month=first.month + 1)
        return first, nxt - timedelta(days=1)

    if period == "quarter":
        q_start_month = ((d.month - 1) // 3) * 3 + 1
        first = d.replace(month=q_start_month, day=1)
        end_month = q_start_month + 2
        if end_month == 12:
            nxt = first.replace(year=first.year + 1, month=1)
        else:
            nxt = first.replace(month=end_month + 1, day=1)
        return first, nxt - timedelta(days=1)

    # default: treat as day
    return d, d


def _day_bounds_utc(start_date, end_date):
    """Convert local [start_date, end_date] (inclusive) to UTC datetime bounds."""
    tz = timezone.get_current_timezone()
    start_local = timezone.make_aware(
        datetime.combine(start_date, datetime.min.time()), tz
    )
    end_local = timezone.make_aware(
        datetime.combine(end_date + timedelta(days=1), datetime.min.time()), tz
    )
    return (
        start_local.astimezone(dt_timezone.utc),
        end_local.astimezone(dt_timezone.utc),
    )


# ──────────────────────────────────────────────────────────────────────────
# Scope resolution — the security-critical part
# ──────────────────────────────────────────────────────────────────────────
def _resolve_scope(request, org):
    """
    Decide which users this requester may see, ENFORCED SERVER-SIDE.

    Returns: (can_see_all: bool, forced_user_id: int | None)

    - Staff/superuser (MavOps admin via ?org_id=) → see all in target org.
    - owner/admin/manager → see all employees in their org.
    - member → forced to their own user_id, regardless of any param sent.
    """
    if request.user.is_staff or request.user.is_superuser:
        return True, None

    role = get_user_role(request.user, org)
    if role in ("owner", "admin", "manager"):
        return True, None

    # member (or anything unexpected) — locked to self.
    return False, request.user.id


# ──────────────────────────────────────────────────────────────────────────
# Core aggregation
# ──────────────────────────────────────────────────────────────────────────
def _block_queryset(org, start_utc, end_utc, can_see_all, forced_user_id,
                    committed_only=True):
    """
    Non-deleted blocks for the org in the window.

    committed_only=True (default): only confirmed time (state machine
    'committed', with is_categorized fallback for legacy rows). This is what
    the totals/rows/timeseries read — reports reflect confirmed time, not
    in-flight proposals. Mobile manual entries are committed too.

    committed_only=False: the inverse — captured/proposed blocks the agent
    tracked but nobody has confirmed yet. Used to tally the "uncategorized"
    (still-needs-review) column, kept separate from Total.
    """
    qs = Block.objects.filter(
        org=org,
        deleted_at__isnull=True,
        start__gte=start_utc,
        start__lt=end_utc,
    )

    if committed_only:
        qs = qs.filter(
            Q(classification_state="committed") | Q(is_categorized=True)
        )
    else:
        # The review pile — match get_categorization_data() EXACTLY so the
        # report's Uncategorized number agrees with the Categorize tab badge.
        # That endpoint uses is_categorized=False (not a state-machine check),
        # excluding only suppressed blocks. Proposed/captured blocks the AI
        # hasn't had confirmed are is_categorized=False, so they count here.
        qs = qs.filter(is_categorized=False).exclude(
            classification_state="suppressed"
        )

    if not can_see_all and forced_user_id:
        qs = qs.filter(user_id=forced_user_id)

    return qs.select_related("client", "user")


def _uncategorized_by_group(blocks, group_by: str):
    """
    Tally uncommitted minutes per group key + the overall total. These are
    blocks the agent captured but nobody has confirmed (is_categorized=False).

    We skip only genuine *idle* blocks (the agent's idle/AFK sentinels) — NOT
    blocks that merely lack a category. A block with no category yet IS the
    thing we're counting, so excluding it (as the committed aggregation does
    via _EXCLUDE_CATEGORIES) would zero out the very number we want.

    Returns: (total_uncat_min: int, {group_key: minutes})
    """
    per_group: dict = defaultdict(int)
    total = 0
    for b in blocks:
        minutes = b.minutes or 0
        if minutes <= 0:
            continue
        # Skip only true idle — match _is_idle semantics, not category text.
        cat = _dominant_category(b).lower()
        if cat == "idle":
            continue
        if (b.bundle_id or "").lower() == "__idle__":
            continue
        key = (b.user_id if group_by == "employee" else (b.client_id or "unassigned"))
        per_group[key] += minutes
        total += minutes
    return total, per_group


def _is_billable_block(block) -> bool:
    """A block bills if it's marked billable AND tied to a client."""
    return bool(block.is_billable and block.client_id)


def _dominant_category(block) -> str:
    ch = block.category_hours
    if isinstance(ch, dict) and ch:
        return next(iter(ch.keys()))
    return "Uncategorized"


def _aggregate(blocks, group_by: str):
    """
    Walk blocks once, building:
      - top-line totals (total / billable / non-billable minutes, client count)
      - per-group rows (by employee or by client)

    Returns a dict ready to serialize.
    """
    total_min = 0
    billable_min = 0
    non_billable_min = 0

    # group_key -> rollup
    groups: dict = defaultdict(lambda: {
        "label": "",
        "id": None,
        "total_min": 0,
        "billable_min": 0,
        "non_billable_min": 0,
        "top_client": defaultdict(int),   # client name -> minutes (employee view)
        "block_count": 0,
    })

    distinct_clients = set()

    for b in blocks:
        minutes = b.minutes or 0
        if minutes <= 0:
            continue

        cat = _dominant_category(b).lower()
        if cat in _EXCLUDE_CATEGORIES:
            continue

        billable = _is_billable_block(b)
        client_name = b.client.name if b.client_id else "Unassigned"
        if b.client_id:
            distinct_clients.add(b.client_id)

        total_min += minutes
        if billable:
            billable_min += minutes
        else:
            non_billable_min += minutes

        # group key
        if group_by == "client":
            key = b.client_id or "unassigned"
            label = client_name
        else:  # employee
            key = b.user_id
            label = (
                b.user.get_full_name().strip()
                or b.user.username
            ) if b.user_id else "Unknown"

        g = groups[key]
        g["label"] = label
        g["id"] = (b.user_id if group_by == "employee" else b.client_id)
        g["total_min"] += minutes
        g["block_count"] += 1
        if billable:
            g["billable_min"] += minutes
        else:
            g["non_billable_min"] += minutes

        if group_by == "employee" and b.client_id:
            g["top_client"][client_name] += minutes

    # build rows
    rows = []
    for key, g in groups.items():
        top_client = None
        if g["top_client"]:
            top_client = max(g["top_client"].items(), key=lambda kv: kv[1])[0]

        util = (
            round(100 * g["billable_min"] / g["total_min"], 1)
            if g["total_min"] else 0.0
        )
        rows.append({
            "id": g["id"],
            "label": g["label"],
            "total_hours": round(g["total_min"] / 60, 2),
            "billable_hours": round(g["billable_min"] / 60, 2),
            "non_billable_hours": round(g["non_billable_min"] / 60, 2),
            "utilization_pct": util,
            "top_client": top_client,
            "block_count": g["block_count"],
        })

    rows.sort(key=lambda r: r["total_hours"], reverse=True)

    util_overall = (
        round(100 * billable_min / total_min, 1) if total_min else 0.0
    )

    return {
        "totals": {
            "total_hours": round(total_min / 60, 2),
            "billable_hours": round(billable_min / 60, 2),
            "non_billable_hours": round(non_billable_min / 60, 2),
            "utilization_pct": util_overall,
            "active_clients": len(distinct_clients),
        },
        "rows": rows,
    }


def _timeseries(blocks, period: str, start_utc, end_utc):
    """
    Bucketed billable vs total hours over the window, for a simple trend strip.
    Uses DB-side Trunc on `start` so granularity matches the requested period.
    """
    trunc = _TRUNC.get(period, TruncDay)

    agg = (
        blocks
        .annotate(bucket=trunc("start"))
        .values("bucket")
        .annotate(
            total_min=Sum("minutes"),
            billable_min=Sum(
                Case(
                    When(is_billable=True, client__isnull=False, then=F("minutes")),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
        )
        .order_by("bucket")
    )

    out = []
    for row in agg:
        bucket = row["bucket"]
        total_min = row["total_min"] or 0
        billable_min = row["billable_min"] or 0
        out.append({
            "bucket": bucket.date().isoformat() if hasattr(bucket, "date") else str(bucket),
            "total_hours": round(total_min / 60, 2),
            "billable_hours": round(billable_min / 60, 2),
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_summary(request):
    """
    GET /api/reports/summary/
      ?period=day|week|month|quarter        (default: week)
      &date=YYYY-MM-DD                       (anchor; default: today)
      &group_by=employee|client             (default: employee)
      &org_id=<id>                           (staff-only impersonation)

    Role-gating is enforced server-side: members see only their own numbers.
    """
    period = (request.GET.get("period") or "week").lower()
    if period not in _TRUNC:
        period = "week"

    group_by = (request.GET.get("group_by") or "employee").lower()
    if group_by not in ("employee", "client"):
        group_by = "employee"

    date_str = request.GET.get("date")
    anchor = parse_date(date_str) if date_str else timezone.localdate()
    if not anchor:
        anchor = timezone.localdate()

    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    can_see_all, forced_user_id = _resolve_scope(request, org)

    start_date, end_date = _resolve_period_window(period, anchor)
    start_utc, end_utc = _day_bounds_utc(start_date, end_date)

    blocks = list(
        _block_queryset(org, start_utc, end_utc, can_see_all, forced_user_id)
    )

    summary = _aggregate(blocks, group_by)

    # Uncategorized (still-needs-review) tally — a separate fetch of the
    # uncommitted blocks, kept OUT of Total so Total stays "confirmed time."
    uncat_blocks = list(
        _block_queryset(
            org, start_utc, end_utc, can_see_all, forced_user_id,
            committed_only=False,
        )
    )
    total_uncat_min, uncat_by_group = _uncategorized_by_group(uncat_blocks, group_by)

    # Merge uncategorized minutes onto each row, and surface rows that have
    # ONLY uncategorized time (no committed time yet) so they don't vanish.
    # Uncategorized is now ADDED INTO total_hours (Total = committed + uncat).
    # Utilization stays billable ÷ total, so adding uncategorized to total
    # correctly drags utilization down until that time is reviewed.
    seen_keys = set()
    for row in summary["rows"]:
        key = (row["id"] if group_by == "employee" else (row["id"] or "unassigned"))
        seen_keys.add(key)
        uncat_h = round(uncat_by_group.get(key, 0) / 60, 2)
        row["uncategorized_hours"] = uncat_h
        row["total_hours"] = round(row["total_hours"] + uncat_h, 2)
        # Recompute utilization against the new (larger) total.
        row["utilization_pct"] = (
            round(100 * row["billable_hours"] / row["total_hours"], 1)
            if row["total_hours"] else 0.0
        )

    for key, mins in uncat_by_group.items():
        if key in seen_keys:
            continue
        # Row exists only in the uncategorized set — build a minimal row.
        label = None
        for b in uncat_blocks:
            bkey = (b.user_id if group_by == "employee" else (b.client_id or "unassigned"))
            if bkey == key:
                if group_by == "employee":
                    label = (b.user.get_full_name().strip() or b.user.username) if b.user_id else "Unknown"
                else:
                    label = b.client.name if b.client_id else "Unassigned"
                break
        uncat_h = round(mins / 60, 2)
        summary["rows"].append({
            "id": None if key == "unassigned" else key,
            "label": label or "Unknown",
            "total_hours": uncat_h,           # all of this row's time is uncategorized
            "billable_hours": 0.0,
            "non_billable_hours": 0.0,
            "utilization_pct": 0.0,
            "top_client": None,
            "block_count": 0,
            "uncategorized_hours": uncat_h,
        })

    # Re-sort: rows may have changed total_hours, and new rows were appended.
    summary["rows"].sort(key=lambda r: r["total_hours"], reverse=True)

    # Totals: fold uncategorized into the headline total + recompute utilization.
    summary["totals"]["uncategorized_hours"] = round(total_uncat_min / 60, 2)
    summary["totals"]["total_hours"] = round(
        summary["totals"]["total_hours"] + (total_uncat_min / 60), 2
    )
    summary["totals"]["utilization_pct"] = (
        round(100 * summary["totals"]["billable_hours"] / summary["totals"]["total_hours"], 1)
        if summary["totals"]["total_hours"] else 0.0
    )

    # timeseries from a fresh queryset (Trunc needs a queryset, not a list)
    ts_qs = _block_queryset(org, start_utc, end_utc, can_see_all, forced_user_id)
    ts_qs = ts_qs.filter(minutes__gt=0)
    series = _timeseries(ts_qs, period, start_utc, end_utc)

    return Response({
        "org_id": org.id,
        "org_name": org.name,
        "period": period,
        "group_by": group_by,
        "range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "scope": "all" if can_see_all else "self",
        "totals": summary["totals"],
        "rows": summary["rows"],
        "timeseries": series,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_summary_export(request):
    """
    GET /api/reports/summary/export/  — same params as reports_summary.
    Returns CSV (CPAs live in Excel; this is itself a quick win).
    """
    period = (request.GET.get("period") or "week").lower()
    if period not in _TRUNC:
        period = "week"
    group_by = (request.GET.get("group_by") or "employee").lower()
    if group_by not in ("employee", "client"):
        group_by = "employee"

    date_str = request.GET.get("date")
    anchor = parse_date(date_str) if date_str else timezone.localdate()
    if not anchor:
        anchor = timezone.localdate()

    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    can_see_all, forced_user_id = _resolve_scope(request, org)
    start_date, end_date = _resolve_period_window(period, anchor)
    start_utc, end_utc = _day_bounds_utc(start_date, end_date)

    blocks = list(
        _block_queryset(org, start_utc, end_utc, can_see_all, forced_user_id)
    )
    summary = _aggregate(blocks, group_by)

    # Uncategorized tally (same logic as the JSON endpoint)
    uncat_blocks = list(
        _block_queryset(
            org, start_utc, end_utc, can_see_all, forced_user_id,
            committed_only=False,
        )
    )
    total_uncat_min, uncat_by_group = _uncategorized_by_group(uncat_blocks, group_by)
    for r in summary["rows"]:
        key = (r["id"] if group_by == "employee" else (r["id"] or "unassigned"))
        uncat_h = round(uncat_by_group.get(key, 0) / 60, 2)
        r["uncategorized_hours"] = uncat_h
        r["total_hours"] = round(r["total_hours"] + uncat_h, 2)
        r["utilization_pct"] = (
            round(100 * r["billable_hours"] / r["total_hours"], 1)
            if r["total_hours"] else 0.0
        )

    buf = io.StringIO()
    writer = csv.writer(buf)

    label_col = "Employee" if group_by == "employee" else "Client"
    writer.writerow([
        f"{org.name} — Time Summary ({period}: {start_date} to {end_date})"
    ])
    writer.writerow([])
    header = [
        label_col, "Total Hours", "Billable Hours",
        "Non-Billable Hours", "Uncategorized Hours", "Utilization %",
    ]
    if group_by == "employee":
        header.append("Top Client")
    writer.writerow(header)

    for r in summary["rows"]:
        row = [
            r["label"], r["total_hours"], r["billable_hours"],
            r["non_billable_hours"], r.get("uncategorized_hours", 0),
            r["utilization_pct"],
        ]
        if group_by == "employee":
            row.append(r["top_client"] or "")
        writer.writerow(row)

    writer.writerow([])
    t = summary["totals"]
    grand_total_h = round(t["total_hours"] + (total_uncat_min / 60), 2)
    grand_util = (
        round(100 * t["billable_hours"] / grand_total_h, 1)
        if grand_total_h else 0.0
    )
    writer.writerow([
        "TOTAL", grand_total_h, t["billable_hours"],
        t["non_billable_hours"], round(total_uncat_min / 60, 2),
        grand_util,
    ])

    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    fname = f"time_summary_{org.slug}_{period}_{start_date}.csv"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp