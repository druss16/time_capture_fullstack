"""
Review lens — the numbers, plus where they came from.

Every other lens answers a question ("how profitable?", "how utilized?") and
assumes you already accept the figures. This one exists because that assumption
kept failing in the room: a partner looks at $46,641 of revenue next to a P&L
that says something else, and the conversation is over before it starts.

So this lens shows the same numbers as Profitability and Utilization, but leads
with the derivation instead of the conclusion:

  1. the headline four
  2. the hours waterfall — every hour captured, and what we removed at each step
  3. how much of the working week we actually see, per person
  4. plain-language notes on what each number is and is NOT

Nothing here is computed differently from the other lenses; it composes the same
metrics and the same block helpers. If a figure disagrees with Profitability,
that's a bug, not a basis difference.
"""
from __future__ import annotations

from django.db.models import Sum

from tracker.models import Block

from ..types import (
    DataTablePayload, InsightCardPayload, MetricState, Section, to_float,
)
from .base import Lens, register_lens
from .helpers import column, headline_row


@register_lens("review")
class ReviewLens(Lens):
    label = "Review"

    def assemble(self, org, scope, time, compare=None):
        sections: list[Section] = [
            headline_row(
                ["revenue", "gross_margin", "billable_mix", "wip_total"],
                org, scope, time, compare, section_id="headline",
            ),
            self._waterfall_section(org, scope, time),
        ]

        coverage = self._coverage_section(org, scope, time)
        if coverage is not None:
            sections.append(coverage)

        sections.append(self._notes_section(org, scope, time))
        return sections

    # ── 1. where the hours went ─────────────────────────────────────────────
    def _waterfall_section(self, org, scope, time) -> Section:
        """Every captured hour, and what each filter removed.

        This is the single most useful thing on the page. Without it the drop
        from "everything the agent saw" to "hours we can bill" looks like lost
        time; with it, it's a list of exclusions someone can agree to one at a
        time.
        """
        from ..blocks import (
            billable_q, confirmed_qs, exclude_idle, working_qs,
        )
        from ..cost_rates import non_utilization_user_ids

        base = Block.objects.filter(
            org=org, day__gte=time.start, day__lte=time.end,
        )
        base = self._apply_scope_qs(base, scope)

        def hrs(qs) -> float:
            return to_float(qs.aggregate(s=Sum("minutes"))["s"]) / 60.0

        captured = hrs(base)
        no_idle = hrs(exclude_idle(base))
        confirmed = hrs(working_qs(base, org))

        chargeable_qs_ = working_qs(base, org)
        excl = non_utilization_user_ids(org) if scope.type in ("firm", "composite") else set()
        if excl:
            chargeable_qs_ = chargeable_qs_.exclude(user_id__in=excl)
        chargeable = hrs(chargeable_qs_)
        billable = hrs(chargeable_qs_.filter(billable_q(org)))

        steps = [
            ("Everything the agent captured", captured, None,
             "Raw tracked time"),
            ("less idle and lock-screen", no_idle, no_idle - captured,
             "Away from the desk"),
            ("less unreviewed, suppressed, and internal or flat-fee clients",
             confirmed, confirmed - no_idle,
             "The same time Daily Review counts"),
            ("less non-chargeable admin and ops staff", chargeable,
             chargeable - confirmed, "Total Hours tile"),
            ("billable only", billable, billable - chargeable,
             "Billable Hours tile"),
        ]

        rows = [{
            "step": label,
            "hours": round(h, 1),
            "removed": (round(d, 1) if d is not None else None),
            "becomes": becomes,
        } for label, h, d, becomes in steps]

        kept = (billable / captured * 100) if captured else 0.0
        table = DataTablePayload(
            id="hours_waterfall",
            title="Where the hours went",
            subtitle=(f"{time.label} · {captured:,.1f} h captured → {billable:,.1f} h "
                      f"billable ({kept:.0f}%). Each line is one exclusion."),
            columns=[
                column("step", "Step", "text"),
                column("hours", "Hours", "hours_1dp"),
                column("removed", "Removed", "hours_1dp",
                       tooltip="How much this step took out."),
                column("becomes", "Which is", "text"),
            ],
            rows=rows,
            state=MetricState.READY if captured else MetricState.EMPTY,
        )
        return Section(
            id="waterfall", type="section", title="How The Hours Add Up",
            collapsible=False, children=[table],
        )

    # ── 2. how much of the week we see ──────────────────────────────────────
    def _coverage_section(self, org, scope, time) -> Section | None:
        """Tracked hours against scheduled capacity, per person.

        The honest ceiling on everything else: if we only see 58% of the week,
        every dollar on this page is a floor rather than a total. Shown per
        person because the gap is never evenly spread, and an individual at 30%
        is usually an agent that isn't running rather than someone not working.
        """
        if scope.type not in ("firm", "composite", "staff"):
            return None

        from .utilization import UtilizationLens
        per_user, excluded_ids, _ = UtilizationLens()._per_user(org, scope, time)
        if not per_user:
            return None

        rows = []
        for uid, d in per_user.items():
            cap = d["cap_h"]
            if cap <= 0:
                continue
            rows.append({
                "user_id": uid,
                "name": d["name"] + (" · non-chargeable" if uid in excluded_ids else ""),
                "tracked_hours": round(d["total_h"], 1),
                "capacity_hours": round(cap, 1),
                "coverage": round(d["total_h"] / cap * 100, 1),
            })
        if not rows:
            return None
        rows.sort(key=lambda r: r["coverage"])

        tracked = sum(r["tracked_hours"] for r in rows)
        capacity = sum(r["capacity_hours"] for r in rows)
        firm_cov = (tracked / capacity * 100) if capacity else 0.0

        table = DataTablePayload(
            id="coverage_by_staff",
            title="How much of the week we see",
            subtitle=(f"{tracked:,.0f} h tracked against {capacity:,.0f} h scheduled — "
                      f"{firm_cov:.0f}% coverage. Lowest first; a low number is "
                      f"usually an agent that isn't running, not someone who isn't working."),
            columns=[
                column("name", "Name", "text"),
                column("tracked_hours", "Tracked", "hours_1dp"),
                column("capacity_hours", "Scheduled", "hours_1dp",
                       tooltip="Available hours from the work calendar, or the tier's weekly hours."),
                column("coverage", "Coverage", "percent_1dp",
                       tooltip="Tracked ÷ Scheduled. How much of the working week reached the system."),
            ],
            rows=rows,
            default_sort={"key": "coverage", "direction": "asc"},
            state=MetricState.READY,
        )
        return Section(
            id="coverage", type="section", title="What We Can And Can't See",
            collapsible=False, children=[table],
        )

    # ── 3. what these numbers are, and are not ──────────────────────────────
    def _notes_section(self, org, scope, time) -> Section:
        """Plain-language notes, driven by the firm's actual configuration.

        Deliberately not static copy: each card only appears when it's true of
        this org right now, so the page stops nagging once a thing is fixed.
        """
        from ..permissions import firm_invoices_here
        from ..cost_rates import cost_rate_map
        from tracker.models import EmployeeCostRate, OrganizationMembership

        cards: list[InsightCardPayload] = []

        if not firm_invoices_here(org):
            cards.append(InsightCardPayload(
                id="note_estimated",
                severity="watch",
                headline="Revenue here is estimated, not invoiced",
                body=("No invoices have been imported, so revenue is the value of "
                      "billable time at your rates — what the work was worth, not "
                      "what was billed or collected. Import invoices and this "
                      "becomes actual revenue, WIP starts draining, and the "
                      "Realization and Trends tabs switch on."),
                source="rule", dismissible=False,
            ))

        burden = to_float(getattr(org, "payroll_burden_multiplier", 1) or 1)
        rates = cost_rate_map(org)
        n_override = EmployeeCostRate.objects.filter(organization=org).values("user_id").distinct().count()
        n_members = OrganizationMembership.objects.filter(organization=org).count()
        if rates:
            avg = sum(rates.values()) / len(rates)
            cards.append(InsightCardPayload(
                id="note_cost_basis",
                severity="info",
                headline=f"Cost is wages × {burden:g} payroll burden",
                body=(f"{n_override} of {n_members} people have an individual rate; the "
                      f"rest fall back to their tier. Blended cost works out to "
                      f"${avg:,.2f} an hour. Margin moves with the burden setting, "
                      f"so if {burden:g}× isn't your real loaded-cost factor, that one "
                      f"field in Settings changes every figure on this page."),
                source="rule", dismissible=False,
            ))

        missing = [
            m.user_id for m in OrganizationMembership.objects.filter(organization=org)
            if m.user_id not in rates
        ]
        if missing:
            cards.append(InsightCardPayload(
                id="note_unrated",
                severity="watch",
                headline=f"{len(missing)} people have no cost rate",
                body=("They fall through to the firm default, which is a placeholder "
                      "rather than what they actually cost. Harmless while they aren't "
                      "tracking time; the moment they do, their work is costed at a "
                      "made-up number."),
                source="rule", dismissible=False,
            ))

        # The pile that is excluded, priced. This is the actionable one: the
        # second-pass classifier moves attributions back to `proposed`
        # overnight, so previously-counted time silently drops out of every
        # figure until someone re-confirms it in Daily Review. Org 21 lost 52 h
        # of committed time that way in a single night. Without this card the
        # only symptom is revenue quietly falling.
        from ..blocks import exclude_idle, utilization_excluded_client_ids
        unreviewed = (exclude_idle(
                Block.objects.filter(org=org, day__gte=time.start, day__lte=time.end))
            .filter(classification_state__in=("proposed", "captured"),
                    deleted_at__isnull=True, client__isnull=False))
        skip = utilization_excluded_client_ids(org)
        if skip:
            unreviewed = unreviewed.exclude(client_id__in=skip)
        unreviewed = self._apply_scope_qs(unreviewed, scope)
        u_hours = to_float(unreviewed.aggregate(s=Sum("minutes"))["s"]) / 60.0
        if u_hours >= 1:
            rate = to_float(getattr(org, "billing_rate_default", 0)) or 0.0
            worth = f" — worth about ${u_hours * rate:,.0f}" if rate else ""
            cards.append(InsightCardPayload(
                id="note_unreviewed",
                severity="watch",
                headline=f"{u_hours:,.0f} hours are waiting on review{worth}",
                body=("Real client time that nobody has confirmed yet, so none of it "
                      "is in the figures above. Note this number moves on its own: "
                      "the classifier re-opens attributions it wants to change, "
                      "which pushes already-counted time back into this queue and "
                      "quietly lowers revenue until someone clears it. Working "
                      "through Daily Review adds it back."),
                source="rule", dismissible=False,
                drilldown=None,
            ))

        cards.append(InsightCardPayload(
            id="note_confirmed",
            severity="info",
            headline="Only reviewed time is counted",
            body=("Every figure here counts the same blocks Daily Review, Reports and "
                  "your timesheets count — confirmed, with a client attached, not "
                  "suppressed. Time nobody has reviewed yet is excluded rather than "
                  "assumed billable, which is why these totals can sit below what "
                  "the agent captured."),
            source="rule", dismissible=False,
        ))

        return Section(
            id="notes", type="section", title="How To Read These Numbers",
            collapsible=True, children=cards,
        )

    # ── helper ──────────────────────────────────────────────────────────────
    def _apply_scope_qs(self, qs, scope):
        """Scope a raw Block queryset without needing a Metric instance."""
        from ..metrics.base import Metric
        return Metric()._apply_scope(qs, scope)
