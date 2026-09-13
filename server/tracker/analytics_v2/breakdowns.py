"""
One grouped pass over confirmed time, sliced by any dimension.

Client Performance, Team Performance and Where Time Goes are the same question
asked of four different columns — client, person, project, category — so they
are one computation here rather than three that can drift.

Every rule is imported from the shared helpers (`confirmed_qs`, `billable_q`,
`bill_rate_map`, `cost_rate_map`, `apply_scope`); nothing about what counts as
confirmed, billable, or worth what is restated in this file. See `series.py`
for the same argument at more length.

Retainers: like the trend, the per-row `revenue` here is HOURLY billable value.
A flat-fee client's row would otherwise read near-zero revenue against real
cost and look catastrophically unprofitable when it is simply billed another
way. Rows are therefore tagged with `billing_type`, and the client table
carries the retainer share as its own column rather than silently folding a
pro-rated slice into an hourly ranking.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce

from tracker.models import Block

from .types import Scope, TimeRange, to_float

# dimension -> (group-by field, id field)
_DIMENSIONS = {
    "client": ("client_id", "client__name"),
    "user": ("user_id", None),
    "project": ("project_id", "project__name"),
    "category": ("task_type_id", "task_type__name"),
}

# What an unset dimension is called in the table. Not "Unknown": for a CPA firm
# these are two materially different situations, and the label is the whole
# difference between "we owe someone a decision" and "this is overhead".
_UNSET_LABEL = {
    "client": "No client assigned",
    "project": "No project",
    "category": "Uncategorized",
    "user": "Unknown",
}


def _money() -> DecimalField:
    return DecimalField(max_digits=14, decimal_places=2)


def breakdown(org, scope: Scope, time: TimeRange, dimension: str) -> list[dict]:
    """Rows of {id, label, hours, billable_hours, billable_pct, revenue, cost,
    margin, margin_pct, people, share} for one dimension, biggest first.

    `share` is the row's share of the table's total hours, which is what makes
    "where does the time go" answerable without doing arithmetic in your head.
    """
    if dimension not in _DIMENSIONS:
        raise ValueError(f"Unknown breakdown dimension '{dimension}'")

    from tracker.services.billing_totals import billable_block_q, internal_client_ids

    from .blocks import billable_q, confirmed_qs
    from .cost_rates import bill_rate_map, cost_rate_map, default_cost_rate
    from .metrics.base import apply_scope
    from .metrics.revenue_sources import flat_fee_client_ids, non_billable_client_ids

    group_field, name_field = _DIMENSIONS[dimension]

    # TWO billable rules, because the tiles above these tables use two.
    #
    #   billable  (blocks.billable_q)      canonical rule PLUS clients flagged
    #       "counts as billable effort" — work that is productive but not
    #       invoiced through the tool, e.g. UltraTax parked under Internal-Tax.
    #       This is the numerator of the Billable Hours tile and of utilization.
    #
    #   billing   (billable_block_q)       the canonical rule alone: marked
    #       billable AND a real client AND not internal firm work. This is what
    #       the Revenue and Labor Cost tiles charge.
    #
    # Using the first for MONEY is what put $10,489 of "billable value" on an
    # Internal - Tax row that the Billable Value tile above it did not count.
    # Hours columns tie to the hours tile; money columns tie to the money tiles.
    billable = billable_q(org)
    billing = billable_block_q(org)

    qs = confirmed_qs(apply_scope(
        Block.objects.filter(org=org, day__gte=time.start, day__lte=time.end),
        scope,
    ))

    # Grouped by (dimension, user) so each row already carries the person whose
    # bill and cost rates apply to it — the ladders resolve in Python with no
    # further queries.
    values = [group_field, "user_id"] + ([name_field] if name_field else [])

    # Hourly revenue excludes retainer and non-billable clients, as
    # RevenueMetric does, so a retainer is never counted twice. Built
    # conditionally: `~Q(client_id__in=[])` is not the no-op it looks like once
    # NULL client ids are in play, and an empty exclusion list should widen
    # nothing.
    rev_q = billing
    rev_exclude = flat_fee_client_ids(org) | non_billable_client_ids(org)
    if rev_exclude:
        rev_q = rev_q & ~Q(client_id__in=list(rev_exclude))

    rows = list(
        qs.values(*values).annotate(
            total_min=Coalesce(Sum("minutes"), 0),
            billable_min=Coalesce(Sum("minutes", filter=billable), 0),
            billing_min=Coalesce(Sum("minutes", filter=billing), 0),
            rated=Coalesce(
                Sum("billing_amount", filter=rev_q),
                Decimal("0"), output_field=_money()),
            unrated_min=Coalesce(
                Sum("minutes", filter=rev_q & Q(billing_amount__isnull=True)),
                0),
        ).order_by()
    )

    bill_rates = bill_rate_map(org)
    cost_rates = cost_rate_map(org)
    default_bill = to_float(getattr(org, "billing_rate_default", 0))
    default_cost = default_cost_rate(org)

    acc: dict = {}
    for r in rows:
        key = r[group_field]
        slot = acc.get(key)
        if slot is None:
            slot = acc[key] = {
                "id": key,
                "label": (r.get(name_field) if name_field else None),
                "hours": 0.0, "billable_hours": 0.0,
                "revenue": 0.0, "cost": 0.0, "_users": set(),
            }
        billable_h = to_float(r["billable_min"]) / 60.0
        billing_h = to_float(r["billing_min"]) / 60.0
        slot["hours"] += to_float(r["total_min"]) / 60.0
        slot["billable_hours"] += billable_h
        slot["revenue"] += to_float(r["rated"]) + (
            to_float(r["unrated_min"]) / 60.0
            * bill_rates.get(r["user_id"], default_bill))
        # Cost is charged on the hours that earn revenue, as LaborCostMetric
        # does — otherwise an internal row shows cost against no income and
        # reads as a loss.
        slot["cost"] += billing_h * cost_rates.get(r["user_id"], default_cost)
        slot["_users"].add(r["user_id"])

    if dimension == "user":
        _label_users(org, acc)

    internal_ids = internal_client_ids(org) if dimension == "client" else set()

    total_hours = sum(s["hours"] for s in acc.values()) or 0.0
    out: list[dict] = []
    for s in acc.values():
        hours, revenue, cost = s["hours"], s["revenue"], s["cost"]
        margin = revenue - cost
        out.append({
            "id": s["id"],
            "label": s["label"] or _UNSET_LABEL[dimension],
            "hours": round(hours, 2),
            "billable_hours": round(s["billable_hours"], 2),
            "billable_pct": round(s["billable_hours"] / hours * 100, 1) if hours > 0 else 0.0,
            "revenue": round(revenue, 2),
            "cost": round(cost, 2),
            "margin": round(margin, 2),
            # None, not 0 — a row that billed nothing has no margin percentage,
            # and printing 0% would rank it alongside genuine break-even work.
            "margin_pct": round(margin / revenue * 100, 1) if revenue > 0 else None,
            "people": len(s["_users"]),
            "share": round(hours / total_hours * 100, 1) if total_hours > 0 else 0.0,
            # The firm's own work ("Internal", "Internal - Tax", ...). Not a
            # client, and held out of client rankings by `split_client_rows`.
            "is_internal": s["id"] in internal_ids,
        })

    out.sort(key=lambda r: -r["hours"])
    return out


def split_client_rows(
    rows: list[dict],
) -> tuple[list[dict], dict | None, list[dict]]:
    """Split a client breakdown into (clients, unassigned, internal).

    A client table ranks clients, and two kinds of row are not clients:

      unassigned  "No client assigned" — no billable hours, no value, no cost,
          no margin, no drilldown, and at most firms it outranks every real
          client on hours, pushing the actual answer down the page.
      internal    the firm's own work ("Internal", "Internal - Tax", ...).
          Never billable by definition (`is_internal_client_name` is the single
          source of truth), so it earns nothing and cannot be ranked on margin
          against work that does.

    Neither is swept away silently — callers name what was held out in the
    table's subtitle, because a client table whose hours no longer tie to the
    firm's hours is its own kind of wrong.

    Shares are recomputed over the remaining rows so they still sum to 100%.
    """
    unassigned = next((r for r in rows if r.get("id") is None), None)
    internal = [r for r in rows if r.get("is_internal")]
    kept = [r for r in rows
            if r.get("id") is not None and not r.get("is_internal")]

    total = sum(r["hours"] for r in kept)
    for r in kept:
        r["share"] = round(r["hours"] / total * 100, 1) if total > 0 else 0.0
    return kept, unassigned, internal


def held_out_note(unassigned: dict | None, internal: list[dict]) -> str:
    """A subtitle clause naming what was held out, or "" when nothing was."""
    parts = []
    if unassigned and unassigned["hours"] > 0:
        parts.append(f"{unassigned['hours']:,.1f} h with no client")
    internal_hours = sum(r["hours"] for r in internal)
    if internal_hours > 0:
        parts.append(f"{internal_hours:,.1f} h internal")
    if not parts:
        return ""
    return f"{' and '.join(parts)} not shown"


def _label_users(org, acc: dict) -> None:
    """Fill in display names for the user dimension in one query."""
    from tracker.models import OrganizationMembership

    ids = [k for k in acc if k is not None]
    if not ids:
        return
    names: dict[int, str] = {}
    for m in (OrganizationMembership.objects
              .filter(organization=org, user_id__in=ids)
              .select_related("user")):
        u = m.user
        full = (f"{u.first_name} {u.last_name}".strip()
                or getattr(u, "username", "") or u.email or f"User {u.id}")
        names[u.id] = full
    for uid, slot in acc.items():
        slot["label"] = names.get(uid) or slot["label"]
