"""
Utilization lens — billable share of *capacity*.

The headline KPI, the by-staff table, and the by-tier table all use the SAME
definition — billable hours ÷ available capacity — so the numbers reconcile.
(Capacity = each person's weekly hours from their cost tier × weeks in window,
falling back to the org default.) A separate "Mix" column keeps the older
billable-÷-tracked ratio, clearly labelled so the two aren't confused.
"""
from __future__ import annotations

from collections import defaultdict
from django.contrib.auth import get_user_model

from tracker.models import Block

from ..types import (
    DataTablePayload, MetricState, Section,
    to_float,
)
from .base import Lens, register_lens
from .helpers import column, headline_row

User = get_user_model()


@register_lens("utilization")
class UtilizationLens(Lens):
    label = "Utilization"

    def assemble(self, org, scope, time, compare=None):
        sections: list[Section] = []
        # ONE utilization number: Mix (billable ÷ tracked active time) — the
        # honest efficiency figure for an activity tracker, and the one directly
        # comparable to the "~75% of working time should be billable" benchmark.
        # Capacity Utilization is not in the hero (it reads artificially low
        # because tracked time excludes idle); it lives in the By-Staff table as
        # the "Cap. Util" column for anyone who wants it.
        sections.append(headline_row(
            ["billable_mix", "billable_hours", "total_hours"],
            org, scope, time, compare,
            section_id="headline",
        ))

        # By tier (cohort targets) — only meaningful firm-wide.
        if scope.type in ("firm", "composite"):
            tier_section = self._by_tier_section(org, scope, time)
            if tier_section:
                sections.append(tier_section)

        # Always show per-staff breakdown unless scoped to a single staff
        if scope.type != "staff" or len(scope.ids) > 1:
            sections.append(self._by_staff_section(org, scope, time))

        return sections

    # ── shared per-user aggregation ─────────────────────────────────────────
    def _scoped_qs(self, org, scope, time):
        qs = Block.objects.filter(org=org, day__gte=time.start, day__lte=time.end)
        if scope.type == "client":
            qs = qs.filter(client_id__in=scope.ids)
        elif scope.type == "service":
            qs = qs.filter(task_type_id__in=scope.ids)
        elif scope.type == "composite":
            for dim, ids in scope.filters.items():
                if not ids:
                    continue
                if dim == "client":
                    qs = qs.filter(client_id__in=ids)
                elif dim == "service":
                    qs = qs.filter(task_type_id__in=ids)
        elif scope.type == "staff":
            qs = qs.filter(user_id__in=scope.ids)
        from ..blocks import exclude_idle
        return exclude_idle(qs)

    def _per_user(self, org, scope, time):
        """{uid: {billable_h, total_h, cap_h, name}} for users active in scope,
        plus (excluded_ids, tier_of). Capacity mirrors the headline metric."""
        from ..cost_rates import non_utilization_user_ids
        from ..capacity import capacity_hours_map
        from tracker.models import OrganizationMembership

        qs = self._scoped_qs(org, scope, time)
        agg: dict[int, dict] = defaultdict(lambda: {"billable": 0.0, "total": 0.0})
        for b in qs.only("user_id", "minutes", "is_billable"):
            mins = to_float(b.minutes)
            agg[b.user_id]["total"] += mins
            if b.is_billable:
                agg[b.user_id]["billable"] += mins

        # Calendar-aware capacity (net of holidays / summer Fridays / time off),
        # with the legacy per-tier × weeks fallback. Same source as the metric.
        cap_map = capacity_hours_map(org, list(agg.keys()), time.start, time.end)

        names = {u.id: (f"{u.first_name} {u.last_name}".strip() or u.username)
                 for u in User.objects.filter(id__in=agg.keys())
                 .only("id", "first_name", "last_name", "username")}
        tier_of = dict(
            OrganizationMembership.objects
            .filter(organization=org, user_id__in=agg.keys())
            .values_list("user_id", "cost_tier_id")
        )

        out: dict[int, dict] = {}
        for uid, d in agg.items():
            out[uid] = {
                "name": names.get(uid, f"User {uid}"),
                "billable_h": d["billable"] / 60.0,
                "total_h": d["total"] / 60.0,
                "cap_h": cap_map.get(uid, 0.0),
            }
        return out, non_utilization_user_ids(org), tier_of

    # ── by staff ────────────────────────────────────────────────────────────
    def _by_staff_section(self, org, scope, time) -> Section:
        per_user, excluded_ids, _ = self._per_user(org, scope, time)

        # Capacity is a whole-person concept (available hours), so it's only
        # meaningful when the rows ARE the whole person — firm or staff scope.
        # At client/service scope the billable/tracked numbers are just this
        # client's slice, so dividing by full capacity is nonsense — drop the
        # capacity columns entirely there.
        cap_meaningful = scope.type in ("firm", "staff")

        def _row(uid, d):
            bh, th, cap = d["billable_h"], d["total_h"], d["cap_h"]
            util = (bh / th * 100) if th > 0 else 0.0       # billable ÷ tracked
            cap_util = (bh / cap * 100) if cap > 0 else 0.0  # billable ÷ capacity
            return {
                "user_id": uid,
                "name": d["name"],
                "billable_hours": round(bh, 2),
                "tracked_hours": round(th, 2),
                "utilization": round(util, 1),
                "cap_util": round(cap_util, 1),
            }

        cols = [
            column("name", "Name", "text"),
            column("billable_hours", "Billable", "hours_1dp",
                   tooltip="Hours marked billable (active-at-computer time; idle excluded)."),
            column("tracked_hours", "Tracked", "hours_1dp",
                   tooltip="Total active-at-computer time (billable + non-billable). Idle/away time is excluded."),
            column("utilization", "Utilization", "percent_1dp",
                   tooltip="Billable ÷ Tracked. Of the time actually spent working at the computer, how much was billable. The one utilization number — comparable to the ~75% 'billable share of working time' benchmark."),
        ]
        if cap_meaningful:
            cols.append(column("cap_util", "Cap. Util", "percent_1dp",
                   tooltip="Billable ÷ Capacity (available wall-clock hours). The traditional utilization definition; reads lower here because tracked time excludes idle/away time. Not shown at client scope, where capacity isn't per-client."))

        main_rows = sorted(
            (_row(uid, d) for uid, d in per_user.items() if uid not in excluded_ids),
            key=lambda r: -r["utilization"],
        )
        excluded_rows = sorted(
            (_row(uid, d) for uid, d in per_user.items() if uid in excluded_ids),
            key=lambda r: -r["billable_hours"],
        )

        children = [DataTablePayload(
            id="staff_utilization",
            title="Utilization by staff",
            subtitle=f"{time.label} · Utilization = billable ÷ tracked (active) time",
            columns=cols,
            rows=main_rows,
            default_sort={"key": "utilization", "direction": "desc"},
            state=MetricState.READY if main_rows else MetricState.EMPTY,
        )]

        if excluded_rows:
            children.append(DataTablePayload(
                id="staff_utilization_excluded",
                title="Non-billable staff",
                subtitle="Excluded from firm utilization",
                columns=cols,
                rows=excluded_rows,
                default_sort={"key": "billable_hours", "direction": "desc"},
                state=MetricState.READY,
            ))

        return Section(
            id="by_staff",
            type="section",
            title="By Staff",
            collapsible=True,
            children=children,
        )

    # ── by tier (cohort targets) ────────────────────────────────────────────
    def _by_tier_section(self, org, scope, time):
        """Per-tier utilization vs the tier's target — so a partner tier at 30%
        reads as on-target instead of underperforming. Chargeable tiers only."""
        from tracker.models import CostTier

        per_user, excluded_ids, tier_of = self._per_user(org, scope, time)
        if not per_user:
            return None

        tiers = {t.id: t for t in CostTier.objects.filter(organization=org)}
        org_target = to_float(getattr(org, "target_utilization", 0)) or 75.0

        # Aggregate active users into their tier (skip non-chargeable tiers —
        # they're the overhead population, not measured against a target).
        buckets: dict[int, dict] = defaultdict(lambda: {"billable": 0.0, "tracked": 0.0, "cap": 0.0, "n": 0})
        for uid, d in per_user.items():
            if uid in excluded_ids:
                continue
            tid = tier_of.get(uid)
            buckets[tid]["billable"] += d["billable_h"]
            buckets[tid]["tracked"] += d["total_h"]
            buckets[tid]["cap"] += d["cap_h"]
            buckets[tid]["n"] += 1

        rows = []
        for tid, b in buckets.items():
            if b["tracked"] <= 0:
                continue
            tier = tiers.get(tid)
            label = tier.label if tier else "No tier"
            target = (to_float(tier.target_utilization)
                      if tier and tier.target_utilization is not None else org_target)
            # Headline utilization = billable ÷ tracked (active) time, matched
            # to the tier's target. Coverage stays capacity-based (secondary).
            util = b["billable"] / b["tracked"] * 100
            coverage = b["tracked"] / b["cap"] * 100 if b["cap"] > 0 else 0.0
            rows.append({
                "tier": label,
                "members": b["n"],
                "billable_hours": round(b["billable"], 2),
                "utilization": round(util, 1),
                "coverage": round(coverage, 1),
                "target": round(target, 1),
                "vs_target": round(util - target, 1),
            })
        if not rows:
            return None
        rows.sort(key=lambda r: -r["utilization"])

        table = DataTablePayload(
            id="tier_utilization",
            title="Utilization by tier vs target",
            subtitle=f"{time.label} · variance to each tier's cohort target",
            columns=[
                column("tier", "Tier", "text"),
                column("members", "People", "integer",
                       tooltip="Active chargeable people in this tier during the period."),
                column("billable_hours", "Billable", "hours_1dp",
                       tooltip="Billable hours across the tier."),
                column("utilization", "Utilization", "percent_1dp",
                       tooltip="Billable ÷ Tracked (active) time for this tier — the headline efficiency number, matched to the tier's target."),
                column("coverage", "Coverage", "percent_1dp",
                       tooltip="Tracked ÷ Capacity for this tier — how much of available (wall-clock) time is captured as active-computer time."),
                column("target", "Target", "percent_1dp",
                       tooltip="This tier's expected utilization target (Settings → Cost Tiers), or the firm target if unset. Now a billable-share-of-active-time target."),
                column("vs_target", "vs Target", "percent_1dp",
                       tooltip="Utilization minus target, in points. Positive = above target."),
            ],
            rows=rows,
            default_sort={"key": "vs_target", "direction": "desc"},
            state=MetricState.READY,
        )
        return Section(
            id="by_tier",
            type="section",
            title="By Tier",
            collapsible=True,
            children=[table],
        )
