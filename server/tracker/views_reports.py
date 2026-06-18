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

# ── Anomalous-block guardrail (report-side) ───────────────────────────────
# A block whose wall-clock span (end - start) exceeds this is almost certainly
# the sleep/wake artifact: the agent left a block open while the machine slept
# and closed it on wake, so an idle overnight stretch got recorded as one giant
# "active" block (classic: Explorer/desktop left open → 10h block).
#
# Blocks store NO interaction signal (no idle/active seconds), so we can't tell
# active-from-idle after the fact. The honest move is to EXCLUDE these from
# report math entirely rather than cap them to a smaller wrong number — a 10h
# overnight block capped to 8h is still a lie; dropped, it stops distorting
# totals. The real fix is upstream (agent closes block at sleep); this is the
# backstop so existing/legacy bad blocks don't make the dashboard wrong.
#
# 6h is deliberately generous: no single uninterrupted app session in a CPA
# workday legitimately runs 6h without the agent breaking it into pieces, so
# anything longer is an artifact, not work. Tune via this one constant.
_MAX_PLAUSIBLE_BLOCK_MINUTES = 6 * 60


def _is_anomalous_block(b) -> bool:
    """
    True if this block looks like a sleep/wake idle artifact and should be
    excluded from report totals. Uses wall-clock span; falls back to .minutes
    if start/end are missing.
    """
    span_min = None
    if b.start and b.end:
        span_min = (b.end - b.start).total_seconds() / 60.0
    if span_min is None:
        span_min = b.minutes or 0
    return span_min > _MAX_PLAUSIBLE_BLOCK_MINUTES


def _block_minutes(b) -> int:
    """
    Report-counting minutes for a block: 0 if anomalous (excluded), else the
    block's own minutes floored at 0. Single chokepoint so every aggregation
    path treats anomalies identically.
    """
    if _is_anomalous_block(b):
        return 0
    m = b.minutes or 0
    return m if m > 0 else 0


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
        minutes = _block_minutes(b)
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
        minutes = _block_minutes(b)
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


def _bucket_key(dt_value, period: str):
    """Local-date bucket label for a datetime, matching the period granularity."""
    local = timezone.localtime(dt_value)
    if period == "day":
        return local.date().isoformat()
    if period == "week":
        monday = local.date() - timedelta(days=local.date().weekday())
        return monday.isoformat()
    if period == "month":
        return local.date().replace(day=1).isoformat()
    if period == "quarter":
        q_start_month = ((local.month - 1) // 3) * 3 + 1
        return local.date().replace(month=q_start_month, day=1).isoformat()
    return local.date().isoformat()


def _daily_shape(committed_blocks, uncat_blocks, period: str):
    """
    Build a per-bucket stacked-bar series with three bands:
      billable / non_billable (from committed) + uncategorized (from uncommitted).

    Walks the in-memory block lists (already fetched) rather than hitting the
    DB again — keeps it one pass and lets us reuse the same idle/category
    skipping rules as the rest of the report.
    """
    buckets: dict = defaultdict(lambda: {
        "billable_min": 0, "non_billable_min": 0, "uncategorized_min": 0,
    })

    for b in committed_blocks:
        minutes = _block_minutes(b)
        if minutes <= 0:
            continue
        cat = _dominant_category(b).lower()
        if cat in _EXCLUDE_CATEGORIES:
            continue
        key = _bucket_key(b.start, period)
        if _is_billable_block(b):
            buckets[key]["billable_min"] += minutes
        else:
            buckets[key]["non_billable_min"] += minutes

    for b in uncat_blocks:
        minutes = _block_minutes(b)
        if minutes <= 0:
            continue
        cat = _dominant_category(b).lower()
        if cat == "idle":
            continue
        if (b.bundle_id or "").lower() == "__idle__":
            continue
        key = _bucket_key(b.start, period)
        buckets[key]["uncategorized_min"] += minutes

    out = []
    for key in sorted(buckets.keys()):
        v = buckets[key]
        billable_h = round(v["billable_min"] / 60, 2)
        non_billable_h = round(v["non_billable_min"] / 60, 2)
        uncategorized_h = round(v["uncategorized_min"] / 60, 2)
        out.append({
            "bucket": key,
            "billable_hours": billable_h,
            "non_billable_hours": non_billable_h,
            "uncategorized_hours": uncategorized_h,
            "total_hours": round(billable_h + non_billable_h + uncategorized_h, 2),
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

    # Daily shape — 3-band stacked series (billable / non-billable / uncategorized)
    # built from the block lists already in memory. No extra DB round-trip.
    series = _daily_shape(blocks, uncat_blocks, period)

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


# ──────────────────────────────────────────────────────────────────────────
# Uncategorized drill-through — the "what's in the pile + common theme" view
# ──────────────────────────────────────────────────────────────────────────
def _normalize_signature(app_name: str, window_title: str, url: str) -> tuple:
    """
    Collapse an activity into a stable (theme_label, group_key) so blocks that
    are really 'the same thing' bucket together. Mirrors the spirit of
    get_categorization_data's signature logic but tuned for theme display.

    Examples:
      Outlook / "Inbox - wayne@..."     → "Outlook — Inbox"
      Chrome  / "Acme 1040 - Google..." → "Chrome — Acme 1040"
      Acrobat / "SOE26 - 247 TL WALL"   → "Acrobat — SOE26 - 247 TL WALL"
    """
    app = (app_name or "Unknown").strip()
    # Strip common app suffixes/extensions for a cleaner label
    app_clean = app.replace(".exe", "").replace(".EXE", "").strip().title()

    title = (window_title or "").strip()
    # Drop everything after a " - <app>" tail and trailing email/account noise
    # Keep the first meaningful segment.
    if title:
        # Take the part before the last " - " if it looks like an app/account tail
        segs = [s.strip() for s in title.split(" - ") if s.strip()]
        head = segs[0] if segs else title
        # Truncate very long heads
        head = head[:60]
        label = f"{app_clean} — {head}"
    elif url:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").replace("www.", "")
        label = f"{app_clean} — {host}" if host else app_clean
    else:
        label = app_clean

    return (label, label.lower())


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_uncategorized_detail(request):
    """
    GET /api/reports/uncategorized/
      ?period=...&date=...&group_by=...&org_id=...   (same params as summary)
      &user_id=<id>   (optional — narrow to one employee, e.g. clicking a row)

    Returns the uncommitted (needs-review) blocks for the window, grouped by a
    normalized app+title signature so a 'common theme' surfaces. Each theme
    group carries total minutes, block count, and a few sample block ids the
    frontend can deep-link into the Categorize tab.
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

    # Optional narrowing to a single employee (row click in the table).
    # Only honored if the requester is allowed to see others.
    row_user_id = request.GET.get("user_id")
    if row_user_id and can_see_all:
        try:
            forced_user_id = int(row_user_id)
            can_see_all = False  # narrow the queryset to just this user
        except (ValueError, TypeError):
            pass

    start_date, end_date = _resolve_period_window(period, anchor)
    start_utc, end_utc = _day_bounds_utc(start_date, end_date)

    uncat_blocks = list(
        _block_queryset(
            org, start_utc, end_utc, can_see_all, forced_user_id,
            committed_only=False,
        )
    )

    # Group by normalized signature
    themes: dict = defaultdict(lambda: {
        "label": "",
        "minutes": 0,
        "block_count": 0,
        "sample_block_ids": [],
        "apps": set(),
    })
    total_min = 0

    for b in uncat_blocks:
        minutes = _block_minutes(b)
        if minutes <= 0:
            continue
        cat = _dominant_category(b).lower()
        if cat == "idle":
            continue
        if (b.bundle_id or "").lower() == "__idle__":
            continue

        label, key = _normalize_signature(b.app_name, b.window_title, b.url)
        g = themes[key]
        g["label"] = label
        g["minutes"] += minutes
        g["block_count"] += 1
        g["apps"].add((b.app_name or "").strip())
        if len(g["sample_block_ids"]) < 10:
            g["sample_block_ids"].append(b.id)
        total_min += minutes

    groups = []
    for key, g in themes.items():
        groups.append({
            "label": g["label"],
            "hours": round(g["minutes"] / 60, 2),
            "minutes": g["minutes"],
            "block_count": g["block_count"],
            "sample_block_ids": g["sample_block_ids"],
            "pct_of_uncategorized": (
                round(100 * g["minutes"] / total_min, 1) if total_min else 0.0
            ),
        })

    groups.sort(key=lambda x: x["minutes"], reverse=True)

    # A one-line "headline theme" the frontend can show as the wow stat.
    headline = None
    if groups:
        top = groups[0]
        headline = {
            "label": top["label"],
            "hours": top["hours"],
            "pct": top["pct_of_uncategorized"],
        }

    return Response({
        "org_id": org.id,
        "period": period,
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "total_uncategorized_hours": round(total_min / 60, 2),
        "group_count": len(groups),
        "headline": headline,
        "groups": groups,
    })