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

from tracker.models import Block, OrganizationMembership, OrgRoutingRule, Client

# Reuse the helpers already defined in views.py — single source of truth for
# org resolution + impersonation. (These are module-level functions in views.py.)
from tracker.views import (
    get_request_org_override,
    get_user_role,
)


# ──────────────────────────────────────────────────────────────────────────
# Period handling
# ──────────────────────────────────────────────────────────────────────────
from django.db.models.functions import TruncYear  # add to the existing functions import

_TRUNC = {
    "day": TruncDay,
    "week": TruncWeek,
    "month": TruncMonth,
    "quarter": TruncQuarter,
    "year": TruncYear,
}

# Categories that should never count toward billable/total (mirrors today_time).
_EXCLUDE_CATEGORIES = {"idle", "uncategorized"}

# ── Standard workday model (utilization denominator) ──────────────────────
# Utilization has two honest denominators and they tell different stories:
#   (a) ÷ captured time — "of what we tracked, how much billed." The denominator
#       drifts with how long the agent happened to run, so a laptop left on
#       overnight depresses the ratio unfairly.
#   (b) ÷ STANDARD AVAILABLE hours — "of the time we PAY for, how much billed."
#       This is the number partners actually care about and consultants quote.
# We compute BOTH and let the frontend lead with (b). _STANDARD_WORKDAY_HOURS is
# the per-person available-hours baseline for a single working day; weekends are
# excluded from the count. Override per-org later via an OrgSetting if needed.
_STANDARD_WORKDAY_HOURS = 8.0

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

    NOTE: this is the LEDGER value — used for Total Captured, which counts all
    real time. Materiality (the utilization/uncategorized threshold) is applied
    separately via _is_material(), so Total Captured stays honest while the
    quality metrics ignore sub-threshold noise.
    """
    if _is_anomalous_block(b):
        return 0
    m = b.minutes or 0
    return m if m > 0 else 0



# ── Materiality threshold ─────────────────────────────────────────────────
# Blocks shorter than this are immaterial noise — 30-second context switches,
# alt-tabs, momentary glances at Outlook/Calculator/a PDF. They still count in
# Total Captured (the ledger), but are EXCLUDED from the utilization ratio and
# the "needs review" uncategorized pile, because forcing nobody-will-ever-
# categorize-these slivers into the denominator drags utilization down and
# misrepresents a productive day. Mirrors the Categorize tab's own
# SHORT_BLOCK_THRESHOLD_MINUTES=2 so the two views agree.
#
# Utilization is a QUALITY metric (how much real working time was billable),
# not an accounting ledger — Total Captured is the ledger. Keeping those two
# numbers serving different jobs is why this threshold applies here and not to
# _block_minutes above.
_MATERIAL_MIN_MINUTES = 2


def _is_material(b) -> bool:
    """True if the block is long enough to count toward utilization / review."""
    return _block_minutes(b) >= _MATERIAL_MIN_MINUTES


def _count_working_days(start_date, end_date) -> int:
    """
    Inclusive Mon–Fri count between two dates. Used as the per-person multiplier
    for standard-available-hours utilization. Saturdays/Sundays are excluded so
    a normal week reads as 5 working days, not 7 — otherwise the standard-hours
    denominator would understate utilization on every weekend-spanning range.
    """
    if end_date < start_date:
        return 0
    days = 0
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:  # 0=Mon … 4=Fri
            days += 1
        d += timedelta(days=1)
    return days


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

    if period == "year":
        first = d.replace(month=1, day=1)
        last = d.replace(month=12, day=31)
        return first, last

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


def _headcount_for_scope(org, can_see_all, forced_user_id) -> int:
    """
    Number of people the utilization denominator should account for.
      - self scope → 1 (the requesting member).
      - team scope → active memberships in the org.
    Used to size the standard-available-hours denominator
    (headcount × working_days × _STANDARD_WORKDAY_HOURS).
    """
    if not can_see_all:
        return 1
    qs = OrganizationMembership.objects.filter(organization=org)
    # Honor an is_active flag if the model has one; otherwise count all members.
    try:
        qs = qs.filter(is_active=True)
    except Exception:
        pass
    n = qs.values("user_id").distinct().count()
    return max(n, 1)


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
    ).exclude(
        classification_state="suppressed",
    )

    if committed_only:
        # Match Daily Review (today_time), which is the source of truth: it
        # counts proposed AND committed time, not committed-only. Without this
        # the dashboard under-reports billable hours vs the day view.
        qs = qs.filter(
            Q(classification_state__in=["committed", "proposed"]) | Q(is_categorized=True)
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
        # Skip immaterial sub-threshold slivers — they're noise, not a real
        # "needs review" item, and (since uncategorized folds into the
        # utilization total) counting them here would drag utilization down.
        if not _is_material(b):
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
    total_min = 0          # material only — drives utilization denominator
    billable_min = 0
    non_billable_min = 0
    immaterial_min = 0     # sub-threshold noise — added to displayed Total, NOT utilization

    # group_key -> rollup
    groups: dict = defaultdict(lambda: {
        "label": "",
        "id": None,
        "total_min": 0,          # material only (utilization denominator)
        "billable_min": 0,
        "non_billable_min": 0,
        "immaterial_min": 0,     # sub-threshold, shown in Total but not utilization
        "top_client": defaultdict(int),   # client name -> minutes (employee view)
        "block_count": 0,
        # Cross-breakdown for the drill-downs (employee card / client modal):
        #   employee mode → keyed by client_id, one entry per client worked
        #   client mode   → keyed by user_id,   one entry per person who worked it
        # Built from committed blocks only, so items sum to committed minutes.
        "breakdown": defaultdict(lambda: {
            "id": None,
            "name": "",
            "total_min": 0,
            "billable_min": 0,
            "non_billable_min": 0,
        }),
    })

    distinct_clients = set()

    for b in blocks:
        minutes = _block_minutes(b)
        if minutes <= 0:
            continue

        cat = _dominant_category(b).lower()
        # Only drop genuine non-billable idle/uncategorized noise. A block that
        # is billable WITH a client but has empty category_hours reads as
        # "uncategorized" here — it's real billable time and must be counted,
        # matching today_time (which counts by client+billable, not category
        # label). Without this, AI-proposed billable blocks vanish from the
        # dashboard's billable total.
        if cat in _EXCLUDE_CATEGORIES and not (b.is_billable and b.client_id):
            continue
        client_name = b.client.name if b.client_id else "Unassigned"
        if b.client_id:
            distinct_clients.add(b.client_id)

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
        g["block_count"] += 1

        # Immaterial (sub-2min) blocks: the materiality filter exists to keep
        # noise out of the utilization ratio — BUT a sub-2min block that is
        # billable with a real client is genuine billable work (the agent often
        # captures client work in <2min slices), not noise. Dropping it here is
        # what made the dashboard show 1h14m when the real billable is 3h51m.
        # So: only treat NON-billable sub-2min blocks as immaterial. Billable-
        # with-client time always counts, matching today_time.
        billable = _is_billable_block(b)
        if not _is_material(b) and not billable:
            immaterial_min += minutes
            g["immaterial_min"] += minutes
            continue

        total_min += minutes
        if billable:
            billable_min += minutes
        else:
            non_billable_min += minutes

        g["total_min"] += minutes
        if billable:
            g["billable_min"] += minutes
        else:
            g["non_billable_min"] += minutes

        if group_by == "employee" and b.client_id:
            g["top_client"][client_name] += minutes

        # Cross-breakdown accumulation. In employee mode we split this person's
        # time by client; in client mode we split this client's time by person.
        # Unassigned client / unknown user fall into an explicit bucket so the
        # split still sums to the row total instead of silently dropping time.
        if group_by == "employee":
            bkey = b.client_id or "unassigned"
            bname = client_name                      # "Unassigned" when no client
            bid = b.client_id
        else:
            bkey = b.user_id or "unknown"
            bname = (
                (b.user.get_full_name().strip() or b.user.username)
                if b.user_id else "Unknown"
            )
            bid = b.user_id
        bd = g["breakdown"][bkey]
        bd["id"] = bid
        bd["name"] = bname
        bd["total_min"] += minutes
        if billable:
            bd["billable_min"] += minutes
        else:
            bd["non_billable_min"] += minutes

    # build rows
    rows = []
    for key, g in groups.items():
        top_client = None
        if g["top_client"]:
            top_client = max(g["top_client"].items(), key=lambda kv: kv[1])[0]

        # Utilization denominator is MATERIAL time only (g["total_min"]).
        util = (
            round(100 * g["billable_min"] / g["total_min"], 1)
            if g["total_min"] else 0.0
        )
        # Displayed Total = material + immaterial (the honest ledger).
        display_total_min = g["total_min"] + g["immaterial_min"]
        # B: fold sub-threshold slivers into displayed non-billable so the row
        # reads Total = Billable + Non-Bill. util above used material-only
        # total (g["total_min"]), so the ratio is untouched.
        display_non_billable_min = g["non_billable_min"] + g["immaterial_min"]

        # Serialize the cross-breakdown (drill-down source). Committed minutes
        # only; drop empty buckets; biggest first so the UI shows the top
        # client/person at the top of the list.
        breakdown = []
        for _bk, bd in g["breakdown"].items():
            if bd["total_min"] <= 0:
                continue
            breakdown.append({
                "id": bd["id"],
                "name": bd["name"],
                "total_hours": round(bd["total_min"] / 60, 2),
                "billable_hours": round(bd["billable_min"] / 60, 2),
                "non_billable_hours": round(bd["non_billable_min"] / 60, 2),
            })
        breakdown.sort(key=lambda x: x["total_hours"], reverse=True)

        rows.append({
            "id": g["id"],
            "label": g["label"],
            "total_hours": round(display_total_min / 60, 2),
            "billable_hours": round(g["billable_min"] / 60, 2),
            "non_billable_hours": round(display_non_billable_min / 60, 2),
            "utilization_pct": util,
            "top_client": top_client,
            "block_count": g["block_count"],
            "breakdown": breakdown,
        })

    rows.sort(key=lambda r: r["total_hours"], reverse=True)

    # Overall utilization: billable ÷ MATERIAL total (immaterial excluded so it
    # can't drag the ratio). Displayed Total still includes immaterial below.
    util_overall = (
        round(100 * billable_min / total_min, 1) if total_min else 0.0
    )

    return {
        "totals": {
            # Total Captured = material + immaterial (full ledger, honest sum).
            "total_hours": round((total_min + immaterial_min) / 60, 2),
            "billable_hours": round(billable_min / 60, 2),
            "non_billable_hours": round((non_billable_min + immaterial_min) / 60, 2),
            "immaterial_hours": round(immaterial_min / 60, 2),
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
        # Only drop genuine non-billable idle/uncategorized noise. A block that
        # is billable WITH a client but has empty category_hours reads as
        # "uncategorized" here — it's real billable time and must be counted,
        # matching today_time (which counts by client+billable, not category
        # label). Without this, AI-proposed billable blocks vanish from the
        # dashboard's billable total.
        if cat in _EXCLUDE_CATEGORIES and not (b.is_billable and b.client_id):
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

    # Custom range: if explicit start & end are passed, use them directly and
    # ignore period/anchor. Powers the calendar start–end picker on the
    # dashboard. Falls back to the named-period window otherwise.
    custom_start = parse_date(request.GET.get("start") or "")
    custom_end = parse_date(request.GET.get("end") or "")
    if custom_start and custom_end and custom_start <= custom_end:
        start_date, end_date = custom_start, custom_end
    else:
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
    # Capture-based utilization (billable ÷ total captured). Kept for the
    # "of what we tracked" framing and backwards-compat with existing callers.
    summary["totals"]["utilization_pct"] = (
        round(100 * summary["totals"]["billable_hours"] / summary["totals"]["total_hours"], 1)
        if summary["totals"]["total_hours"] else 0.0
    )

    # ── Standard-hours utilization (the number partners actually quote) ─────
    # billable ÷ (headcount × working_days × 8h). This is the headline util the
    # frontend leads with; capture-based stays available as a secondary read.
    headcount = _headcount_for_scope(org, can_see_all, forced_user_id)
    working_days = _count_working_days(start_date, end_date)
    available_hours = round(headcount * working_days * _STANDARD_WORKDAY_HOURS, 2)
    summary["totals"]["available_hours"] = available_hours
    summary["totals"]["headcount"] = headcount
    summary["totals"]["working_days"] = working_days
    summary["totals"]["utilization_standard_pct"] = (
        round(100 * summary["totals"]["billable_hours"] / available_hours, 1)
        if available_hours else 0.0
    )
    # Keep the capture-based number under an explicit name too, so the frontend
    # can label each one unambiguously instead of guessing.
    summary["totals"]["utilization_captured_pct"] = summary["totals"]["utilization_pct"]

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
    # Custom range: if explicit start & end are passed, use them directly and
    # ignore period/anchor. Powers the calendar start–end picker on the
    # dashboard. Falls back to the named-period window otherwise.
    custom_start = parse_date(request.GET.get("start") or "")
    custom_end = parse_date(request.GET.get("end") or "")
    if custom_start and custom_end and custom_start <= custom_end:
        start_date, end_date = custom_start, custom_end
    else:
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
        "Non-Billable Hours", "Needs Review Hours", "Utilization %",
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

    # Custom range: if explicit start & end are passed, use them directly and
    # ignore period/anchor. Powers the calendar start–end picker on the
    # dashboard. Falls back to the named-period window otherwise.
    custom_start = parse_date(request.GET.get("start") or "")
    custom_end = parse_date(request.GET.get("end") or "")
    if custom_start and custom_end and custom_start <= custom_end:
        start_date, end_date = custom_start, custom_end
    else:
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
        "user_ids": set(),   # distinct employees hitting this theme (blind-spots)
    })
    total_min = 0

    # Immaterial (sub-2min) slivers are rolled into ONE summary line instead of
    # cluttering the themed list — visible and accounted for, but not treated
    # as individual "needs review" items.
    immaterial_min = 0
    immaterial_count = 0

    for b in uncat_blocks:
        minutes = _block_minutes(b)
        if minutes <= 0:
            continue
        cat = _dominant_category(b).lower()
        if cat == "idle":
            continue
        if (b.bundle_id or "").lower() == "__idle__":
            continue

        # Roll up immaterial blocks rather than listing each tiny sliver.
        if not _is_material(b):
            immaterial_min += minutes
            immaterial_count += 1
            continue

        label, key = _normalize_signature(b.app_name, b.window_title, b.url)
        g = themes[key]
        g["label"] = label
        g["minutes"] += minutes
        g["block_count"] += 1
        g["apps"].add((b.app_name or "").strip())
        if b.user_id:
            g["user_ids"].add(b.user_id)
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
            "user_count": len(g["user_ids"]),   # how many employees hit this theme
            "sample_block_ids": g["sample_block_ids"],
            "pct_of_uncategorized": (
                round(100 * g["minutes"] / total_min, 1) if total_min else 0.0
            ),
        })

    groups.sort(key=lambda x: x["minutes"], reverse=True)

    # A one-line "headline theme" the frontend can show as the wow stat.
    # (Based on material groups only — the headline should be a real chunk.)
    headline = None
    if groups:
        top = groups[0]
        headline = {
            "label": top["label"],
            "hours": top["hours"],
            "pct": top["pct_of_uncategorized"],
        }

    # Append the rolled-up immaterial line LAST so it sits at the bottom of the
    # list. Flagged with is_immaterial so the frontend can render it muted /
    # non-actionable (it's not a "go categorize this" item). Its minutes are
    # NOT in total_min, so it doesn't affect pct_of_uncategorized of real groups.
    if immaterial_min > 0:
        groups.append({
            "label": f"{immaterial_count} small activities (under {_MATERIAL_MIN_MINUTES}m each)",
            "hours": round(immaterial_min / 60, 2),
            "minutes": immaterial_min,
            "block_count": immaterial_count,
            "sample_block_ids": [],
            "pct_of_uncategorized": 0.0,
            "is_immaterial": True,
        })

    return Response({
        "org_id": org.id,
        "period": period,
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        # total_uncategorized_hours = MATERIAL uncategorized only (matches the
        # KPI tile / utilization). Immaterial is surfaced separately below.
        "total_uncategorized_hours": round(total_min / 60, 2),
        "immaterial_hours": round(immaterial_min / 60, 2),
        "immaterial_count": immaterial_count,
        "group_count": len(groups),
        "headline": headline,
        "groups": groups,
    })


# ──────────────────────────────────────────────────────────────────────────
# AI performance — "is the tool working?" metrics
# ──────────────────────────────────────────────────────────────────────────
# What counts as the AI/automation classifying on its own (real-time flow):
_AUTOMATED_SOURCES = {
    "ai", "pattern", "learned", "deterministic", "meeting_detector", "tax_software",
}
# Excluded from the rate entirely — these are admin/backfill operations, NOT
# the classifier working in the normal flow. Counting them would credit the AI
# for migration scripts. ('system' + any reclassify_* bulk tag.)
_NON_CLASSIFICATION_SOURCES = {"system", "import"}


def _ai_perf_for_window(org, start_utc, end_utc, can_see_all, forced_user_id):
    """
    Compute the AI-performance numbers for ONE time window. Pulled out of the
    endpoint so the trend series can call it once per historical period without
    duplicating the counting logic. Returns a plain dict (not a Response).
    """
    qs = Block.objects.filter(
        org=org,
        deleted_at__isnull=True,
        start__gte=start_utc,
        start__lt=end_utc,
    )
    if not can_see_all and forced_user_id:
        qs = qs.filter(user_id=forced_user_id)
    qs = qs.select_related("client")

    automated_blocks = 0
    automated_min = 0
    manual_blocks = 0           # human categorized from scratch
    correction_blocks = 0       # human overrode an AI guess
    ai_blocks = 0               # specifically categorized_by='ai'
    auto_captured_min = 0       # all agent-captured material time

    # Confidence accounting — independent of who/what categorized. A block is
    # "uncertain" if it carries a low-confidence flag (the red clock). We probe
    # a few likely attribute names so this keeps working regardless of which
    # field the classifier stamps; absence of all of them = treat as confident.
    confident_blocks = 0
    uncertain_blocks = 0
    confidence_observed = 0     # blocks where we could actually read a signal

    def _is_uncertain(b) -> bool:
        # needs_review / low_confidence boolean flags, if present.
        for attr in ("needs_review", "is_uncertain", "low_confidence"):
            v = getattr(b, attr, None)
            if isinstance(v, bool):
                return v
        # numeric confidence score, if present (0..1 or 0..100).
        score = getattr(b, "confidence", None)
        if score is None:
            score = getattr(b, "ai_confidence", None)
        if isinstance(score, (int, float)):
            thresh = 0.6 if score <= 1 else 60
            return score < thresh
        return False  # no signal → assume confident

    for b in qs:
        minutes = _block_minutes(b)  # respects anomaly exclusion
        cb = (b.categorized_by or "").lower()

        # Hours auto-captured: any real (material, non-anomalous) time the
        # agent recorded. This is the "time you didn't have to write down."
        if minutes > 0 and _is_material(b):
            auto_captured_min += minutes

        # Confidence: only meaningful for material blocks the agent classified.
        if minutes > 0 and _is_material(b) and cb not in _NON_CLASSIFICATION_SOURCES:
            has_signal = any(
                getattr(b, a, None) is not None
                for a in ("needs_review", "is_uncertain", "low_confidence",
                          "confidence", "ai_confidence")
            )
            if has_signal:
                confidence_observed += 1
                if _is_uncertain(b):
                    uncertain_blocks += 1
                else:
                    confident_blocks += 1

        # Classification-source accounting — only for blocks that were actually
        # classified by something we count (exclude admin/bulk + uncategorized).
        if cb in _NON_CLASSIFICATION_SOURCES:
            continue
        if cb in _AUTOMATED_SOURCES:
            automated_blocks += 1
            automated_min += minutes
            if cb == "ai":
                ai_blocks += 1
        elif cb == "manual":
            manual_blocks += 1
        elif cb == "correction":
            # A correction is BOTH a human touch AND evidence the AI was
            # overridden. Counted in the denominator for override rate.
            correction_blocks += 1

    classified_total = automated_blocks + manual_blocks + correction_blocks
    auto_cat_rate = (
        round(100 * automated_blocks / classified_total, 1)
        if classified_total else 0.0
    )

    ai_decisions = ai_blocks + correction_blocks
    override_rate = (
        round(100 * correction_blocks / ai_decisions, 1)
        if ai_decisions else 0.0
    )
    confirmation_rate = round(100 - override_rate, 1) if ai_decisions else 0.0

    confidence_rate = (
        round(100 * confident_blocks / confidence_observed, 1)
        if confidence_observed else None
    )

    return {
        "auto_categorization_rate": auto_cat_rate,
        "ai_override_rate": override_rate,
        "ai_confirmation_rate": confirmation_rate,
        "ai_confidence_rate": confidence_rate,
        "hours_auto_captured": round(auto_captured_min / 60, 2),
        "ai_decisions": ai_decisions,        # denominator size — lets the frontend
                                             # hide trend points with no data.
        "counts": {
            "automated_blocks": automated_blocks,
            "manual_blocks": manual_blocks,
            "correction_blocks": correction_blocks,
            "ai_blocks": ai_blocks,
            "classified_total": classified_total,
            "confident_blocks": confident_blocks,
            "uncertain_blocks": uncertain_blocks,
            "confidence_observed": confidence_observed,
        },
    }


def _prev_period_anchor(period: str, anchor):
    """Step one whole period backwards from `anchor` (a date in the period)."""
    if period == "day":
        return anchor - timedelta(days=1)
    if period == "week":
        return anchor - timedelta(days=7)
    if period == "month":
        # go to the 1st, step back a day → previous month, keep day=1
        first = anchor.replace(day=1)
        return (first - timedelta(days=1)).replace(day=1)
    if period == "quarter":
        first = anchor.replace(day=1)
        # back up 3 months by stepping to prior-month firsts
        for _ in range(3):
            first = (first - timedelta(days=1)).replace(day=1)
        return first
    if period == "year":
        return anchor.replace(year=anchor.year - 1)
    return anchor - timedelta(days=7)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_ai_performance(request):
    """
    GET /api/reports/ai-performance/
      ?period=...&date=...&org_id=...   (same window params as summary)
      &trend=N                          (optional: also return the last N periods
                                         as a time series, oldest → newest)

    The "is the tool earning its keep" story. We report THREE distinct things
    that customers conflate if you let them:

      1. AUTOMATED — how much work the tool did for you.
      2. ACCURATE  — how often you trust its guess (override / confirmation).
      3. CONFIDENT — how sure the tool was up front (confidence rate).

    When ?trend=N is passed we ALSO walk N periods back and return a `trend`
    array of {bucket, ai_override_rate, ai_confirmation_rate, ai_decisions} so
    the frontend can draw a real falling-override-rate line — using actual data,
    not a fabricated slope. Points with ai_decisions=0 carry null rates so the
    chart can skip empty periods honestly.
    """
    period = (request.GET.get("period") or "week").lower()
    if period not in _TRUNC:
        period = "week"

    date_str = request.GET.get("date")
    anchor = parse_date(date_str) if date_str else timezone.localdate()
    if not anchor:
        anchor = timezone.localdate()

    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    can_see_all, forced_user_id = _resolve_scope(request, org)

    # Custom range: if explicit start & end are passed, use them directly and
    # ignore period/anchor. (Trend is disabled for custom ranges — a custom
    # window has no natural "previous period" to step back through.)
    custom_start = parse_date(request.GET.get("start") or "")
    custom_end = parse_date(request.GET.get("end") or "")
    is_custom = bool(custom_start and custom_end and custom_start <= custom_end)
    if is_custom:
        start_date, end_date = custom_start, custom_end
    else:
        start_date, end_date = _resolve_period_window(period, anchor)
    start_utc, end_utc = _day_bounds_utc(start_date, end_date)

    current = _ai_perf_for_window(org, start_utc, end_utc, can_see_all, forced_user_id)

    # ── Optional trend series ───────────────────────────────────────────
    trend = None
    trend_n = request.GET.get("trend")
    if trend_n and not is_custom:
        try:
            n = max(2, min(int(trend_n), 26))  # clamp 2..26 to bound the work
        except (ValueError, TypeError):
            n = 8
        series = []
        a = anchor
        for _ in range(n):
            ws, we = _resolve_period_window(period, a)
            wsu, weu = _day_bounds_utc(ws, we)
            pt = _ai_perf_for_window(org, wsu, weu, can_see_all, forced_user_id)
            has_data = pt["ai_decisions"] > 0
            series.append({
                "bucket": ws.isoformat(),
                "ai_override_rate": pt["ai_override_rate"] if has_data else None,
                "ai_confirmation_rate": pt["ai_confirmation_rate"] if has_data else None,
                "ai_decisions": pt["ai_decisions"],
                # Volume metric — immune to the review-ramp distortion that makes
                # the accuracy %s misleading during onboarding. This is the clean
                # "work nobody had to type" line; cumulative is filled in below.
                "hours_auto_captured": pt["hours_auto_captured"],
                "cumulative_hours": 0.0,   # set in the running pass after reverse
            })
            a = _prev_period_anchor(period, a)
        series.reverse()  # oldest → newest for left-to-right charting
        # Running total, oldest → newest, so the frontend gets a monotonic line.
        _run = 0.0
        for _p in series:
            _run = round(_run + (_p["hours_auto_captured"] or 0), 2)
            _p["cumulative_hours"] = _run
        trend = series

    return Response({
        "org_id": org.id,
        "period": period,
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "auto_categorization_rate": current["auto_categorization_rate"],
        "ai_override_rate": current["ai_override_rate"],
        "ai_confirmation_rate": current["ai_confirmation_rate"],
        "ai_confidence_rate": current["ai_confidence_rate"],
        "hours_auto_captured": current["hours_auto_captured"],
        "counts": current["counts"],
        "trend": trend,   # null unless ?trend=N was passed
    })


# ──────────────────────────────────────────────────────────────────────────
# Billing leakage — "what did we capture but never invoice?" (Phase 3 seed)
# ──────────────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_leakage(request):
    """
    GET /api/reports/leakage/
      ?period=...&date=...&group_by=client|employee&org_id=...

    The recurring revenue-recovery story: billable time the agent CAPTURED that
    never made it onto an invoice. No manual-timesheet firm can see this number
    because the time was never written down in the first place — that's the moat.

        captured_billable_hours  — billable+client time we recorded
        invoiced_hours           — hours actually marked billed/invoiced
        leakage_hours            — captured_billable − invoiced (floored at 0)

    A dollar figure needs a bill rate. If the Block (or a related rate table)
    exposes one we use it; otherwise leakage is returned in HOURS only and the
    frontend can multiply by a firm-entered blended rate. We deliberately do NOT
    invent a rate server-side — a made-up dollar number is worse than none.

    NOTE: this reads whatever "invoiced" signal the Block model exposes
    (is_invoiced / invoiced_at / invoice_id). If none exist yet, invoiced_hours
    is 0 and leakage == captured_billable, which is still directionally useful
    and flags that invoice-linkage is the next thing to wire up.
    """
    period = (request.GET.get("period") or "week").lower()
    if period not in _TRUNC:
        period = "week"
    group_by = (request.GET.get("group_by") or "client").lower()
    if group_by not in ("employee", "client"):
        group_by = "client"

    date_str = request.GET.get("date")
    anchor = parse_date(date_str) if date_str else timezone.localdate()
    if not anchor:
        anchor = timezone.localdate()

    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    can_see_all, forced_user_id = _resolve_scope(request, org)

    custom_start = parse_date(request.GET.get("start") or "")
    custom_end = parse_date(request.GET.get("end") or "")
    if custom_start and custom_end and custom_start <= custom_end:
        start_date, end_date = custom_start, custom_end
    else:
        start_date, end_date = _resolve_period_window(period, anchor)
    start_utc, end_utc = _day_bounds_utc(start_date, end_date)

    blocks = list(
        _block_queryset(org, start_utc, end_utc, can_see_all, forced_user_id)
    )

    def _is_invoiced(b) -> bool:
        for attr in ("is_invoiced", "invoiced", "billed"):
            v = getattr(b, attr, None)
            if isinstance(v, bool):
                return v
        for attr in ("invoiced_at", "invoice_id", "invoice_line_id"):
            if getattr(b, attr, None):
                return True
        return False

    def _rate_for(b):
        # Best-effort per-block bill rate, if the schema exposes one.
        for attr in ("bill_rate", "billing_rate", "rate"):
            v = getattr(b, attr, None)
            if isinstance(v, (int, float, Decimal)) and v:
                return float(v)
        return None

    per_group = defaultdict(lambda: {
        "label": "",
        "id": None,
        "captured_billable_min": 0,
        "invoiced_min": 0,
        "leakage_dollars": 0.0,
        "has_rate": False,
    })
    tot_capt = tot_inv = 0
    tot_leak_dollars = 0.0
    any_rate = False

    for b in blocks:
        if not _is_billable_block(b):
            continue
        minutes = _block_minutes(b)
        if minutes <= 0 or not _is_material(b):
            continue

        if group_by == "client":
            key = b.client_id or "unassigned"
            label = b.client.name if b.client_id else "Unassigned"
        else:
            key = b.user_id
            label = (b.user.get_full_name().strip() or b.user.username) if b.user_id else "Unknown"

        g = per_group[key]
        g["label"] = label
        g["id"] = (b.client_id if group_by == "client" else b.user_id)
        g["captured_billable_min"] += minutes
        tot_capt += minutes

        invoiced = _is_invoiced(b)
        if invoiced:
            g["invoiced_min"] += minutes
            tot_inv += minutes
        else:
            rate = _rate_for(b)
            if rate is not None:
                any_rate = True
                g["has_rate"] = True
                dollars = (minutes / 60.0) * rate
                g["leakage_dollars"] += dollars
                tot_leak_dollars += dollars

    rows = []
    for key, g in per_group.items():
        leak_min = max(g["captured_billable_min"] - g["invoiced_min"], 0)
        rows.append({
            "id": g["id"],
            "label": g["label"],
            "captured_billable_hours": round(g["captured_billable_min"] / 60, 2),
            "invoiced_hours": round(g["invoiced_min"] / 60, 2),
            "leakage_hours": round(leak_min / 60, 2),
            "leakage_dollars": round(g["leakage_dollars"], 2) if g["has_rate"] else None,
        })
    rows.sort(key=lambda r: r["leakage_hours"], reverse=True)

    total_leak_min = max(tot_capt - tot_inv, 0)
    return Response({
        "org_id": org.id,
        "period": period,
        "group_by": group_by,
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "totals": {
            "captured_billable_hours": round(tot_capt / 60, 2),
            "invoiced_hours": round(tot_inv / 60, 2),
            "leakage_hours": round(total_leak_min / 60, 2),
            # Only present a dollar figure if at least one block carried a real
            # rate. Otherwise null → frontend asks for a blended rate instead of
            # showing a fabricated number.
            "leakage_dollars": round(tot_leak_dollars, 2) if any_rate else None,
            "rate_available": any_rate,
        },
        "rows": rows,
    })


# ──────────────────────────────────────────────────────────────────────────
# Create an OrgRoutingRule from a blind-spot signature (safe-by-default)
# ──────────────────────────────────────────────────────────────────────────
# Browser exes: rules matching on these by exe are almost always wrong (the
# same browser hosts client work, personal news, and login screens). We steer
# browser rules to title matching and refuse exe-match for them.
_BROWSER_EXES = {
    "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe",
    "msedge", "chrome", "firefox", "brave", "opera",
}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reports_create_rule(request):
    """
    POST /api/reports/create-rule/
    Body (JSON):
      {
        "match_type": "title_contains" | "exe",
        "match_value": "Inbox" | "outlook.exe",
        "action": "route_to_client" | "assign_category" | "propose_only"
                  | "mark_non_billable" | "suppress",
        "target_client_id": <int|null>,     # for route_to_client
        "target_category": "<str>",          # for assign_category
        "suggest_only": true|false,          # default true → runs_at=classifier
        "org_id": <int>                      # staff impersonation (optional)
      }

    SAFETY (deliberate, to avoid the Rule-17 terminal-rule mistake):
      - Only org owners/admins/managers or staff may create rules.
      - priority is forced to 100 (lowest — user soft rule, never overrides
        org hard rules at 300/500).
      - runs_at defaults to 'classifier' (server-side propose path) so a wrong
        rule surfaces as a REVIEWABLE proposal, not a silent live commit.
      - Browser exes cannot be matched by exe (too broad); forced to title.
      - never creates a terminal/short-circuiting configuration by default.
    """
    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    # Permission: firm-wide rules affect EVERYONE at the firm and route time
    # onto client invoices, so creation is restricted to MavOps staff for now.
    # (Interim gate — the planned propose+approval queue will let firm users
    # propose rules that MavOps/owners approve before they fire. Until that
    # ships, only staff may create, so a manager can't mis-route the whole
    # firm's time.)
    if not request.user.is_staff:
        return Response(
            {"error": "Firm-wide rules can only be created by MavOps staff. "
                      "Please flag this activity to your MavOps contact."},
            status=403,
        )

    data = request.data or {}
    match_type = (data.get("match_type") or "title_contains").strip()
    match_value = (data.get("match_value") or "").strip()
    action = (data.get("action") or "propose_only").strip()
    target_client_id = data.get("target_client_id")
    target_category = (data.get("target_category") or "").strip()
    suggest_only = data.get("suggest_only", True)

    # ── Validation ──────────────────────────────────────────────────────
    valid_match_types = {
        "exe", "exe_family", "title_contains", "title_regex", "file_path_contains",
    }
    if match_type not in valid_match_types:
        return Response({"error": f"Invalid match_type: {match_type}"}, status=400)
    if not match_value:
        return Response({"error": "match_value is required."}, status=400)

    valid_actions = {
        "route_to_client", "assign_category", "propose_only",
        "mark_non_billable", "suppress",
    }
    if action not in valid_actions:
        return Response({"error": f"Invalid action: {action}"}, status=400)

    # Browser guard: refuse exe-match on a browser (too broad → mis-routes).
    if match_type == "exe" and match_value.lower() in _BROWSER_EXES:
        return Response({
            "error": (
                "Matching a browser by app name would mis-categorize unrelated "
                "tabs (client work, news, logins all share the browser). "
                "Use a title keyword instead."
            ),
        }, status=400)

    # Resolve / validate target depending on action.
    target_client = None
    rule_category = "routing"
    if action == "route_to_client":
        if not target_client_id:
            return Response(
                {"error": "target_client_id is required for route_to_client."},
                status=400,
            )
        try:
            target_client = Client.objects.get(id=target_client_id, org=org)
        except Client.DoesNotExist:
            return Response(
                {"error": "Client not found in this org."}, status=400
            )
        rule_category = "routing"
    elif action == "assign_category":
        if not target_category:
            return Response(
                {"error": "target_category is required for assign_category."},
                status=400,
            )
        rule_category = "categorization"
    elif action == "mark_non_billable":
        rule_category = "billing"
    elif action == "suppress":
        rule_category = "routing"
    elif action == "propose_only":
        rule_category = "routing"

    # ── Safe defaults ──────────────────────────────────────────────────
    # suggest_only → runs_at='classifier' (server propose path, reviewable).
    # Even when not suggest_only, we keep priority low and avoid terminal modes.
    runs_at = "classifier" if suggest_only else "both"

    # Human-readable description for the admin UI.
    if action == "route_to_client":
        target_desc = f"→ {target_client.name}"
    elif action == "assign_category":
        target_desc = f"→ category '{target_category}'"
    elif action == "mark_non_billable":
        target_desc = "→ non-billable"
    elif action == "suppress":
        target_desc = "→ ignore"
    else:
        target_desc = "→ propose for review"
    description = f"[from blind-spots] {match_type}='{match_value}' {target_desc}"[:255]

    # Guard against creating an exact duplicate.
    existing = OrgRoutingRule.objects.filter(
        org=org, match_type=match_type, match_value=match_value, action=action,
    ).first()
    if existing:
        return Response({
            "created": False,
            "duplicate": True,
            "rule_id": existing.id,
            "message": "An identical rule already exists.",
        })

    rule = OrgRoutingRule.objects.create(
        org=org,
        match_type=match_type,
        match_value=match_value,
        action=action,
        target_client=target_client,
        target_category=target_category if action == "assign_category" else "",
        category=rule_category,
        runs_at=runs_at,
        priority=100,                 # lowest — never overrides hard rules
        enabled=True,
        is_default=False,
        source="manual",
        description=description,
        created_by=request.user if request.user.is_authenticated else None,
    )

    return Response({
        "created": True,
        "rule_id": rule.id,
        "match_type": rule.match_type,
        "match_value": rule.match_value,
        "action": rule.action,
        "runs_at": rule.runs_at,
        "suggest_only": suggest_only,
        "description": rule.description,
        "message": (
            "Rule created in suggest-only mode — future matching blocks will be "
            "proposed for review, not auto-committed."
            if suggest_only else
            "Rule created and active."
        ),
    })


# ──────────────────────────────────────────────────────────────────────────
# Rule suggestions — firm users flag a blind spot; MavOps reviews & creates
# ──────────────────────────────────────────────────────────────────────────
# NOTE: requires the RuleSuggestion model (migration 0118). Import is done
# lazily inside the functions so this module still imports cleanly before the
# migration is applied (avoids a hard ImportError on deploy ordering).


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reports_submit_suggestion(request):
    """
    POST /api/reports/suggest-rule/
    Body: { label, app_hint, title_hint, minutes, block_count, user_count, note?, org_id? }

    Any authenticated firm user may submit (it's a problem report, not a rule).
    Stores a RuleSuggestion and best-effort emails MavOps. The email failing
    never blocks the record from saving.
    """
    from tracker.models import RuleSuggestion  # lazy (post-migration)

    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    data = request.data or {}
    label = (data.get("label") or "").strip()
    if not label:
        return Response({"error": "label is required."}, status=400)

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    suggestion = RuleSuggestion.objects.create(
        org=org,
        suggested_by=request.user if request.user.is_authenticated else None,
        label=label[:255],
        app_hint=(data.get("app_hint") or "")[:255],
        title_hint=(data.get("title_hint") or "")[:255],
        minutes=_int(data.get("minutes")),
        block_count=_int(data.get("block_count")),
        user_count=_int(data.get("user_count")),
        note=(data.get("note") or "").strip(),
        status="pending",
    )

    # Best-effort email notification — never block on it.
    try:
        from tracker.email_service import send_rule_suggestion_notification
        send_rule_suggestion_notification(
            org_name=org.name,
            submitted_by=(request.user.get_full_name() or request.user.username) if request.user.is_authenticated else "Unknown",
            label=suggestion.label,
            minutes=suggestion.minutes,
            block_count=suggestion.block_count,
            user_count=suggestion.user_count,
            note=suggestion.note,
            suggestion_id=suggestion.id,
        )
    except Exception:
        # Swallow — the suggestion is saved; the notification is a convenience.
        pass

    return Response({
        "created": True,
        "suggestion_id": suggestion.id,
        "message": "Sent to MavOps — thanks! We'll review this and set up a rule.",
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_list_suggestions(request):
    """
    GET /api/reports/suggestions/?status=pending&org_id=
    Staff-only. Lists rule suggestions for review in MavOps Admin.
    """
    from tracker.models import RuleSuggestion  # lazy

    if not request.user.is_staff:
        return Response({"error": "Staff only."}, status=403)

    qs = RuleSuggestion.objects.select_related("org", "suggested_by", "resulting_rule")

    status_filter = (request.GET.get("status") or "").strip()
    if status_filter:
        qs = qs.filter(status=status_filter)

    org_id = request.GET.get("org_id")
    if org_id:
        try:
            qs = qs.filter(org_id=int(org_id))
        except (ValueError, TypeError):
            pass

    out = []
    for s in qs[:200]:
        out.append({
            "id": s.id,
            "org_id": s.org_id,
            "org_name": s.org.name if s.org_id else None,
            "label": s.label,
            "app_hint": s.app_hint,
            "title_hint": s.title_hint,
            "minutes": s.minutes,
            "hours": round((s.minutes or 0) / 60, 2),
            "block_count": s.block_count,
            "user_count": s.user_count,
            "note": s.note,
            "status": s.status,
            "suggested_by": (
                (s.suggested_by.get_full_name() or s.suggested_by.username)
                if s.suggested_by_id else None
            ),
            "resulting_rule_id": s.resulting_rule_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })

    return Response({"suggestions": out, "count": len(out)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reports_suggestion_set_status(request, suggestion_id):
    """
    POST /api/reports/suggestions/<id>/status/
    Body: { status: 'actioned' | 'dismissed' }
    Staff-only. Marks a suggestion reviewed (and records who/when).
    """
    from tracker.models import RuleSuggestion  # lazy

    if not request.user.is_staff:
        return Response({"error": "Staff only."}, status=403)

    new_status = (request.data or {}).get("status", "").strip()
    if new_status not in ("actioned", "dismissed", "pending"):
        return Response({"error": "Invalid status."}, status=400)

    try:
        s = RuleSuggestion.objects.get(id=suggestion_id)
    except RuleSuggestion.DoesNotExist:
        return Response({"error": "Not found."}, status=404)

    s.status = new_status
    s.reviewed_at = timezone.now()
    s.reviewed_by = request.user if request.user.is_authenticated else None
    s.save(update_fields=["status", "reviewed_at", "reviewed_by"])

    return Response({"updated": True, "id": s.id, "status": s.status})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reports_activity(request):
    """
    GET /api/reports/activity/
      ?period=day|week|month|quarter|year   (default: week)
      &date=YYYY-MM-DD                       (anchor; default: today)
      &start=YYYY-MM-DD&end=YYYY-MM-DD       (custom range; overrides period)
      &user_id=<int>                         (REQUIRED — the employee)
      &client_id=<int>                       (REQUIRED — the client; 0/blank = Unassigned)
      &org_id=<id>                           (staff-only impersonation)
 
    Returns that person's activity on that client for the window, collapsed to
    an "App — Document" list (newest activity first), each with minutes, block
    count, billable/review flags, and first/last seen. Totals reconcile with the
    breakdown row that opened this view:
      billable   = committed billable minutes on this client
      non_billable = committed non-billable minutes on this client
      needs_review = uncommitted (is_categorized=False) minutes on this client
 
    Role-gating: members can only ever pull their own user_id; managers/staff
    may pull any user in the org (same pattern as reports_uncategorized_detail).
    """
    period = (request.GET.get("period") or "week").lower()
    if period not in _TRUNC:
        period = "week"
 
    date_str = request.GET.get("date")
    anchor = parse_date(date_str) if date_str else timezone.localdate()
    if not anchor:
        anchor = timezone.localdate()
 
    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)
 
    # ── user_id is required and drives the scope narrowing ──────────────────
    user_id_raw = request.GET.get("user_id")
    if not user_id_raw:
        return Response({"error": "user_id is required."}, status=400)
    try:
        req_user_id = int(user_id_raw)
    except (ValueError, TypeError):
        return Response({"error": "user_id must be an integer."}, status=400)
 
    can_see_all, forced_user_id = _resolve_scope(request, org)
    # Managers/staff may target any user; narrow the queryset to that person.
    # Members are already locked to their own forced_user_id — if they ask for
    # someone else, we ignore it and keep them scoped to themselves.
    if can_see_all:
        forced_user_id = req_user_id
        can_see_all = False
    elif forced_user_id and forced_user_id != req_user_id:
        # A member requesting another user's activity — deny rather than
        # silently return their own (avoids a confusing mismatch in the UI).
        return Response({"error": "Not permitted to view this user."}, status=403)
 
    # ── client_id (required; 0/blank means the Unassigned bucket) ───────────
    client_id_raw = request.GET.get("client_id")
    if client_id_raw is None or client_id_raw == "":
        client_id = None          # Unassigned
        client_is_unassigned = True
    else:
        try:
            cid = int(client_id_raw)
        except (ValueError, TypeError):
            return Response({"error": "client_id must be an integer."}, status=400)
        if cid <= 0:
            client_id = None
            client_is_unassigned = True
        else:
            client_id = cid
            client_is_unassigned = False
 
    # ── window (custom range overrides named period), same as summary ───────
    custom_start = parse_date(request.GET.get("start") or "")
    custom_end = parse_date(request.GET.get("end") or "")
    if custom_start and custom_end and custom_start <= custom_end:
        start_date, end_date = custom_start, custom_end
    else:
        start_date, end_date = _resolve_period_window(period, anchor)
    start_utc, end_utc = _day_bounds_utc(start_date, end_date)
 
    def _client_filter(qs):
        return qs.filter(client_id__isnull=True) if client_is_unassigned \
            else qs.filter(client_id=client_id)
 
    # Committed (billable / non-billable) + uncommitted (needs review), both
    # narrowed to this one user (via forced_user_id) and this one client.
    committed = _client_filter(_block_queryset(
        org, start_utc, end_utc, can_see_all, forced_user_id, committed_only=True
    ))
    uncommitted = _client_filter(_block_queryset(
        org, start_utc, end_utc, can_see_all, forced_user_id, committed_only=False
    ))
 
    # Resolve a display label for the client (best-effort; the row already knows
    # it, but returning it keeps the endpoint self-describing).
    client_label = "Unassigned"
    if not client_is_unassigned:
        c = Client.objects.filter(id=client_id, org=org).first()
        client_label = c.name if c else f"Client {client_id}"
 
    # Resolve the user label from the first block we see (avoids an extra query).
    user_label = None
 
    # ── collapse to activities keyed by normalized signature ────────────────
    activities: dict = defaultdict(lambda: {
        "app": "",
        "title": "",
        "minutes": 0,
        "block_count": 0,
        "billable": False,
        "needs_review": False,
        "first_seen": None,
        "last_seen": None,
    })
 
    billable_min = 0
    non_billable_min = 0
    review_min = 0
    immaterial_min = 0
 
    def _touch_times(entry, b):
        # Track first/last activity timestamps for the group.
        if b.start:
            if entry["first_seen"] is None or b.start < entry["first_seen"]:
                entry["first_seen"] = b.start
            end_ts = b.end or b.start
            if entry["last_seen"] is None or end_ts > entry["last_seen"]:
                entry["last_seen"] = end_ts
 
    # Committed blocks → billable / non-billable buckets.
    for b in committed:
        minutes = _block_minutes(b)
        if minutes <= 0:
            continue
        if user_label is None and b.user_id:
            user_label = (b.user.get_full_name().strip() or b.user.username)
 
        billable = _is_billable_block(b)
        # Mirror _aggregate's immaterial handling: non-billable sub-2min slivers
        # are noise; billable-with-client sub-2min still counts.
        if not _is_material(b) and not billable:
            immaterial_min += minutes
            continue
 
        label, key = _normalize_signature(b.app_name, b.window_title, b.url)
        e = activities[key]
        e["app"] = (b.app_name or "Unknown").strip()
        e["title"] = label
        e["minutes"] += minutes
        e["block_count"] += 1
        if billable:
            e["billable"] = True
            billable_min += minutes
        else:
            non_billable_min += minutes
        _touch_times(e, b)
 
    # Uncommitted blocks → needs-review bucket (skip idle + immaterial, same as
    # the uncategorized endpoint).
    for b in uncommitted:
        minutes = _block_minutes(b)
        if minutes <= 0:
            continue
        cat = _dominant_category(b).lower()
        if cat == "idle":
            continue
        if (b.bundle_id or "").lower() == "__idle__":
            continue
        if not _is_material(b):
            immaterial_min += minutes
            continue
        if user_label is None and b.user_id:
            user_label = (b.user.get_full_name().strip() or b.user.username)
 
        label, key = _normalize_signature(b.app_name, b.window_title, b.url)
        e = activities[key]
        e["app"] = (b.app_name or "Unknown").strip()
        e["title"] = label
        e["minutes"] += minutes
        e["block_count"] += 1
        e["needs_review"] = True
        review_min += minutes
        _touch_times(e, b)
 
    # Serialize, newest activity first (by last_seen, then minutes).
    out = []
    for key, e in activities.items():
        out.append({
            "app": e["app"],
            "title": e["title"],
            "minutes": e["minutes"],
            "hours": round(e["minutes"] / 60, 2),
            "block_count": e["block_count"],
            "billable": e["billable"],
            "needs_review": e["needs_review"],
            "first_seen": e["first_seen"].isoformat() if e["first_seen"] else None,
            "last_seen": e["last_seen"].isoformat() if e["last_seen"] else None,
        })
    out.sort(
        key=lambda a: (a["last_seen"] or "", a["minutes"]),
        reverse=True,
    )
 
    return Response({
        "org_id": org.id,
        "user_id": forced_user_id,
        "user_label": user_label or "Unknown",
        "client_id": None if client_is_unassigned else client_id,
        "client_label": client_label,
        "period": period,
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "totals": {
            "billable_hours": round(billable_min / 60, 2),
            "non_billable_hours": round((non_billable_min + immaterial_min) / 60, 2),
            "needs_review_hours": round(review_min / 60, 2),
            "total_hours": round((billable_min + non_billable_min + immaterial_min + review_min) / 60, 2),
        },
        "activities": out,
    })
 