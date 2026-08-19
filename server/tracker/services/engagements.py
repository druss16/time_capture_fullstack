"""
Engagement derivation, budgets, and burn-vs-progress math.

Three jobs:

  1. ASSIGN    Group captured blocks into engagements (client + service +
               period) using signals the agent already collects — no data entry.
  2. BUDGET    Give each engagement a budget from what the same job took last
               year, or the median of comparable jobs. Again, no data entry.
  3. MEASURE   burn% vs progress% and the spread between them, which is the
               "65% of the budget but only 35% done" number.

The spread is the whole point. Burn alone can't tell you whether a job is in
trouble: 65% burned is fine at 70% done and a fire at 35% done.
"""
from __future__ import annotations

import calendar
import logging
import statistics
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from tracker.models import Block, Engagement, Organization
from tracker.models_engagements import phase_progress
from tracker.utils.db_iter import keyset_iter

logger = logging.getLogger(__name__)

# Only these engagement types are derived automatically. Advisory and one-off
# work have no natural recurring period, so inventing one would produce noise
# rather than budgets — those stay manual.
AUTO_DERIVED_TYPES = ("tax_return", "bookkeeping", "payroll")

# Task-type name fragments → engagement type, for non-tax work.
TASK_TYPE_HINTS = (
    ("bookkeep", "bookkeeping"),
    ("close", "bookkeeping"),
    ("payroll", "payroll"),
)

# Work on a 1040 done Jan–Oct 2026 is the TY2025 return. Work in Nov/Dec is
# next season. Fiscal-year filers break this; they're a minority and the
# budget only needs to group like with like, not be tax-law correct.
TAX_YEAR_ROLLOVER_MONTH = 10

# A budget derived from a single sub-hour prior job is noise, not a baseline.
MIN_CREDIBLE_BUDGET_HOURS = 0.5
# Need this many comparable engagements before a median means anything.
MIN_COMPARABLES = 3


# ---------------------------------------------------------------------------
# 1. Assignment
# ---------------------------------------------------------------------------

def tax_year_for(day: date) -> int:
    return day.year - 1 if day.month <= TAX_YEAR_ROLLOVER_MONTH else day.year


def _month_bounds(day: date) -> tuple[date, date]:
    last = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, 1), date(day.year, day.month, last)


def _engagement_type_for(block: Block) -> str | None:
    if block.tax_return_type:
        return "tax_return"
    name = (block.task_type.name if block.task_type_id else "") or ""
    lowered = name.lower()
    for fragment, etype in TASK_TYPE_HINTS:
        if fragment in lowered:
            return etype
    return None


@dataclass(frozen=True)
class EngagementKey:
    engagement_type: str
    return_type: str
    period_label: str
    period_start: date
    period_end: date


def engagement_key_for_block(block: Block) -> EngagementKey | None:
    """Which engagement does this block belong to? None = not auto-derivable."""
    if not block.client_id or not block.day:
        return None
    etype = _engagement_type_for(block)
    if etype not in AUTO_DERIVED_TYPES:
        return None

    if etype == "tax_return":
        ty = tax_year_for(block.day)
        return EngagementKey(
            engagement_type=etype,
            return_type=(block.tax_return_type or "").strip(),
            period_label=f"TY{ty}",
            # Tax-year engagements span the filing window, not the tax year:
            # that's the period the WORK happens in, which is what budgets and
            # aging care about.
            period_start=date(ty + 1, 1, 1),
            period_end=date(ty + 1, 12, 31),
        )

    start, end = _month_bounds(block.day)
    return EngagementKey(
        engagement_type=etype,
        return_type="",
        period_label=start.strftime("%Y-%m"),
        period_start=start,
        period_end=end,
    )


def get_or_create_engagement(org: Organization, block: Block,
                             key: EngagementKey) -> tuple[Engagement, bool]:
    return Engagement.objects.get_or_create(
        org=org,
        client_id=block.client_id,
        taxpayer_bucket_id=block.taxpayer_bucket_id,
        engagement_type=key.engagement_type,
        return_type=key.return_type,
        period_label=key.period_label,
        defaults={
            "period_start": key.period_start,
            "period_end": key.period_end,
        },
    )


def assign_engagements(org: Organization, *, since: date | None = None,
                       dry_run: bool = True, limit: int | None = None) -> dict:
    """Attach unassigned blocks to engagements, creating engagements as needed."""
    qs = (
        Block.objects.filter(org=org, engagement__isnull=True, client__isnull=False)
        .select_related("task_type")
        .only("id", "client_id", "taxpayer_bucket_id", "day", "tax_return_type",
              "task_type_id", "task_type__name")
    )
    if since:
        qs = qs.filter(day__gte=since)
    if limit:
        qs = qs[:limit]

    created = 0
    assigned = 0
    skipped = 0
    # Cache within the run — a tax season is thousands of blocks over a few
    # hundred engagements, so this saves most of the queries.
    cache: dict[tuple, Engagement] = {}
    seen_keys: set[tuple] = set()

    for block in keyset_iter(qs, 1000):
        key = engagement_key_for_block(block)
        if key is None:
            skipped += 1
            continue

        cache_key = (block.client_id, block.taxpayer_bucket_id,
                     key.engagement_type, key.return_type, key.period_label)
        if dry_run:
            if cache_key not in seen_keys:
                seen_keys.add(cache_key)
                if not Engagement.objects.filter(
                    org=org, client_id=block.client_id,
                    taxpayer_bucket_id=block.taxpayer_bucket_id,
                    engagement_type=key.engagement_type,
                    return_type=key.return_type,
                    period_label=key.period_label,
                ).exists():
                    created += 1
            assigned += 1
            continue

        eng = cache.get(cache_key)
        if eng is None:
            eng, was_created = get_or_create_engagement(org, block, key)
            created += int(was_created)
            cache[cache_key] = eng

        Block.objects.filter(id=block.id).update(engagement=eng)
        assigned += 1

    return {
        "org_id": org.id,
        "dry_run": dry_run,
        "engagements_created": created,
        "blocks_assigned": assigned,
        "blocks_skipped": skipped,
    }


# ---------------------------------------------------------------------------
# 2. Budgets
# ---------------------------------------------------------------------------

def actual_hours(engagement: Engagement) -> float:
    minutes = (
        Block.objects.filter(engagement=engagement)
        .aggregate(m=Sum("minutes"))["m"] or 0
    )
    return round(minutes / 60.0, 2)


def _prior_period_label(engagement: Engagement) -> str | None:
    """The label of the same job one period earlier."""
    if engagement.engagement_type == "tax_return":
        if not engagement.period_label.startswith("TY"):
            return None
        try:
            return f"TY{int(engagement.period_label[2:]) - 1}"
        except ValueError:
            return None
    # Monthly work: last month.
    start = engagement.period_start
    prev_year, prev_month = (start.year, start.month - 1) if start.month > 1 else (start.year - 1, 12)
    return f"{prev_year:04d}-{prev_month:02d}"


def _prior_year_budget(engagement: Engagement) -> tuple[float, str] | None:
    """Same client, same job, one period back. The best budget a firm can have."""
    label = _prior_period_label(engagement)
    if not label:
        return None
    prior = Engagement.objects.filter(
        org_id=engagement.org_id,
        client_id=engagement.client_id,
        taxpayer_bucket_id=engagement.taxpayer_bucket_id,
        engagement_type=engagement.engagement_type,
        return_type=engagement.return_type,
        period_label=label,
    ).first()
    if not prior:
        return None
    hours = actual_hours(prior)
    if hours < MIN_CREDIBLE_BUDGET_HOURS:
        return None
    return hours, f"{label} actual: {hours:.1f}h"


def _comparable_budget(engagement: Engagement) -> tuple[float, str] | None:
    """Median of finished comparable jobs — for clients with no history."""
    today = timezone.localdate()
    peers = Engagement.objects.filter(
        org_id=engagement.org_id,
        engagement_type=engagement.engagement_type,
        return_type=engagement.return_type,
        period_end__lt=today,
    ).exclude(id=engagement.id)[:200]

    samples = [h for h in (actual_hours(p) for p in peers) if h >= MIN_CREDIBLE_BUDGET_HOURS]
    if len(samples) < MIN_COMPARABLES:
        return None
    median = round(statistics.median(samples), 2)
    what = engagement.return_type or engagement.get_engagement_type_display()
    return median, f"median of {len(samples)} comparable {what} jobs: {median:.1f}h"


def derive_budget(engagement: Engagement, *, dry_run: bool = True) -> dict:
    """Give this engagement a budget. Never overwrites a manual one."""
    if engagement.budget_source == "manual":
        return {"engagement_id": engagement.id, "action": "kept_manual"}

    found = _prior_year_budget(engagement)
    source = "prior_year"
    if not found:
        found = _comparable_budget(engagement)
        source = "comparable"
    if not found:
        return {"engagement_id": engagement.id, "action": "no_basis"}

    hours, basis = found
    unchanged = (
        engagement.budget_source == source
        and engagement.budget_hours is not None
        and abs(float(engagement.budget_hours) - hours) < 0.01
    )
    if unchanged:
        return {"engagement_id": engagement.id, "action": "unchanged"}

    if not dry_run:
        rate = float(getattr(engagement.org, "billing_rate_default", 0) or 0)
        engagement.budget_hours = Decimal(str(hours))
        engagement.budget_amount = Decimal(str(round(hours * rate, 2))) if rate else None
        engagement.budget_source = source
        engagement.budget_basis = basis
        engagement.budget_set_at = timezone.now()
        engagement.save(update_fields=[
            "budget_hours", "budget_amount", "budget_source", "budget_basis",
            "budget_set_at", "updated_at",
        ])

    return {
        "engagement_id": engagement.id,
        "action": "set",
        "source": source,
        "hours": hours,
        "basis": basis,
    }


def derive_budgets(org: Organization, *, dry_run: bool = True,
                   only_open: bool = True) -> dict:
    qs = Engagement.objects.filter(org=org).select_related("org")
    if only_open:
        qs = qs.filter(status="open")

    counts: dict[str, int] = {}
    for eng in keyset_iter(qs, 200):
        result = derive_budget(eng, dry_run=dry_run)
        counts[result["action"]] = counts.get(result["action"], 0) + 1

    return {"org_id": org.id, "dry_run": dry_run, "actions": counts}


# ---------------------------------------------------------------------------
# 3. Burn vs progress
# ---------------------------------------------------------------------------

@dataclass
class EngagementStats:
    engagement: Engagement
    actual_hours: float
    budget_hours: float | None
    burn_pct: float | None       # 0..100+ — hours spent / budget
    progress_pct: float | None   # 0..100 — phase-weighted completion
    overrun_pts: float | None    # burn − progress, in points. >0 = trouble
    projected_hours: float | None
    projected_overrun_hours: float | None
    projected_overrun_dollars: float | None

    def to_row(self) -> dict:
        e = self.engagement
        return {
            "engagement_id": e.id,
            "client_id": e.client_id,
            "client_name": e.client.name if e.client_id else "—",
            "engagement": e.display_name(),
            "period": e.period_label,
            "phase": e.phase or "",
            "phase_label": next(
                (lbl for key, lbl, _w in e.ladder if key == e.phase), "Not set"
            ),
            "phase_source": e.phase_source or "",
            "inferred_phase": e.inferred_phase or "",
            "actual_hours": self.actual_hours,
            "budget_hours": self.budget_hours,
            "budget_source": e.budget_source,
            "burn_pct": self.burn_pct,
            "progress_pct": self.progress_pct,
            "overrun_pts": self.overrun_pts,
            "projected_overrun_hours": self.projected_overrun_hours,
            "projected_overrun_dollars": self.projected_overrun_dollars,
        }


def engagement_stats(engagement: Engagement, *, hours: float | None = None,
                     rate: float = 0.0) -> EngagementStats:
    """Burn, progress, and the spread between them for one engagement."""
    actual = actual_hours(engagement) if hours is None else hours
    budget = float(engagement.budget_hours) if engagement.budget_hours else None
    progress = phase_progress(engagement.engagement_type, engagement.phase)

    burn_pct = round(actual / budget * 100, 1) if budget else None
    progress_pct = round(progress * 100, 1) if progress is not None else None

    overrun_pts = None
    if burn_pct is not None and progress_pct is not None:
        overrun_pts = round(burn_pct - progress_pct, 1)

    # Straight-line projection: if this much effort bought this much progress,
    # finishing costs the same per point the rest of the way. Crude, and the
    # right kind of crude — it's an early-warning flag, not a forecast.
    projected = None
    projected_over_hours = None
    projected_over_dollars = None
    if progress and progress > 0 and actual > 0:
        projected = round(actual / progress, 2)
        if budget:
            projected_over_hours = round(projected - budget, 2)
            projected_over_dollars = round(projected_over_hours * rate, 2) if rate else None

    return EngagementStats(
        engagement=engagement,
        actual_hours=actual,
        budget_hours=budget,
        burn_pct=burn_pct,
        progress_pct=progress_pct,
        overrun_pts=overrun_pts,
        projected_hours=projected,
        projected_overrun_hours=projected_over_hours,
        projected_overrun_dollars=projected_over_dollars,
    )


def open_engagement_stats(org: Organization, *, client_ids=None,
                          limit: int | None = None) -> list[EngagementStats]:
    """Stats for every open engagement, cheapest way — one aggregate for hours."""
    qs = Engagement.objects.filter(org=org, status="open").select_related("client")
    if client_ids:
        qs = qs.filter(client_id__in=client_ids)

    engagements = list(qs)
    if not engagements:
        return []

    hours_by_id = {
        r["engagement"]: round((r["m"] or 0) / 60.0, 2)
        for r in Block.objects.filter(engagement__in=engagements)
        .values("engagement").annotate(m=Sum("minutes"))
    }
    rate = float(getattr(org, "billing_rate_default", 0) or 0)

    stats = [
        engagement_stats(e, hours=hours_by_id.get(e.id, 0.0), rate=rate)
        for e in engagements
    ]
    # Worst overrun first — that's the worklist.
    stats.sort(
        key=lambda s: (
            s.projected_overrun_dollars if s.projected_overrun_dollars is not None else -1,
            s.overrun_pts if s.overrun_pts is not None else -1,
        ),
        reverse=True,
    )
    return stats[:limit] if limit else stats
