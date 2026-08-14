"""
Insight engine — generates "Needs attention" cards for the Pulse lens.

Three tiers (per Phase 4 design):
  Tier 1: Rule-driven   — OrgRoutingRule with category='flagging'
  Tier 2: Threshold-driven — built-in metric threshold breaches (configurable per firm)
  Tier 3: AI-driven     — Executive plan only, GPT-4o on recent deltas (stubbed)

All three return InsightCardPayload objects rendered by the same frontend
component. A `source` field on the card distinguishes them.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from django.utils import timezone

from tracker.models import Block, Organization

from ..metrics import get_metric
from ..metrics.wip import compute_wip_aging_bands
from ..types import InsightCardPayload, MetricState, Scope, TimeRange, to_float

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def generate_pulse_insights(
    org: Organization,
    scope: Scope,
    time: TimeRange,
    invoiceless: bool = False,
) -> list[InsightCardPayload]:
    """
    Return up to 5 ranked insight cards for the Pulse view.
    
    The actual InsightCardPayload objects come from three sub-generators,
    are dedup'd by signature, ranked by severity, and capped.
    """
    insights: list[InsightCardPayload] = []
    
    try:
        insights.extend(_generate_threshold_insights(org, scope, time, invoiceless=invoiceless))
    except Exception as exc:
        logger.exception("[ANALYTICS_V2] Threshold insights failed: %s", exc)
    
    try:
        insights.extend(_generate_rule_insights(org, scope, time))
    except Exception as exc:
        logger.exception("[ANALYTICS_V2] Rule insights failed: %s", exc)
    
    if _is_executive_plan(org):
        try:
            insights.extend(_generate_ai_insights(org, scope, time))
        except Exception as exc:
            logger.exception("[ANALYTICS_V2] AI insights failed: %s", exc)
    
    # Dedup by id (multiple sources may detect the same thing)
    seen: set[str] = set()
    unique: list[InsightCardPayload] = []
    for ins in insights:
        if ins.id in seen:
            continue
        seen.add(ins.id)
        unique.append(ins)
    
    # Rank: bad > watch > good > info, then by source priority (rule > threshold > ai)
    severity_rank = {"bad": 0, "watch": 1, "good": 2, "info": 3}
    source_rank = {"rule": 0, "threshold": 1, "ai": 2}
    unique.sort(key=lambda i: (severity_rank.get(i.severity, 4), source_rank.get(i.source, 3)))
    
    return unique[:5]


def _is_executive_plan(org: Organization) -> bool:
    plan = (getattr(org, "plan", "none") or "none").lower()
    return plan.startswith(("executive", "trial"))


# ---------------------------------------------------------------------------
# Tier 2: Threshold-driven (the bulk of useful insights)
# ---------------------------------------------------------------------------

def _generate_threshold_insights(
    org: Organization, scope: Scope, time: TimeRange, invoiceless: bool = False,
) -> list[InsightCardPayload]:
    """
    Built-in threshold rules. These fire when configured metrics breach.
    Designed to be the same kind of thing a firm would write a custom rule for,
    but shipped sensibly out of the box.
    """
    cards: list[InsightCardPayload] = []
    
    # ── WIP aged 60+ over $25K ──
    try:
        from ..metrics.base import Metric as _M
        # Use a throwaway Metric() just for its scope-application helper
        class _Helper:
            def _apply_scope(self, qs, s):
                return _M()._apply_scope(qs, s)
        bands = compute_wip_aging_bands(org, scope, _Helper())
        aged_total = bands["61_90"] + bands["90_plus"]
        if aged_total > 25000:
            cards.append(_wip_aging_card(org, scope, aged_total, bands))
    except Exception as exc:
        logger.warning("[insights] WIP aging check failed: %s", exc)
    
    # ── Dollar realization below 85% ──
    # Skip entirely for invoice-less firms (their realization is structurally 0%,
    # not a problem to surface)
    if not invoiceless:
        try:
            rd = get_metric("realization_dollar").safe_compute(org, scope, time)
            if rd.state == MetricState.READY and rd.value is not None and rd.value < 85:
                cards.append(_low_realization_card(rd.value))
        except Exception as exc:
            logger.warning("[insights] Realization check failed: %s", exc)
    
    # ── Utilization vs the firm's OWN normal (WHOOP-style baseline) ──
    if scope.type in ("firm", "staff"):
        try:
            ut = get_metric("billable_mix").safe_compute(org, scope, time)
            if ut.state == MetricState.READY and ut.value is not None:
                from ..baselines import weekly_mix_series, band
                vals = [v for _, v in weekly_mix_series(org, scope, time.end)]
                b = band(vals)
                if b:
                    # Judge against the firm's own history, not a textbook target.
                    if ut.value < b["p25"]:
                        cards.append(_low_utilization_card(ut.value, b))
                    elif ut.value > b["max"]:
                        cards.append(_high_utilization_card(ut.value, b))
                    # Slow drift the weekly band can't see (frog-boil guard).
                    drift = _utilization_drift(vals)
                    if drift:
                        cards.append(_utilization_drift_card(*drift))
                else:
                    # Not enough history to learn a baseline — generic fallback.
                    if ut.value < 60:
                        cards.append(_low_utilization_card(ut.value, None))
                    elif ut.value > 90:
                        cards.append(_high_utilization_card(ut.value, None))
        except Exception as exc:
            logger.warning("[insights] Utilization check failed: %s", exc)
    
    # ── Open AI/mail/calendar disagreements (a TimeTracker-native signal) ──
    try:
        disagreement_count = _count_open_disagreements(org, scope, time)
        if disagreement_count >= 3:
            cards.append(_disagreement_card(disagreement_count))
    except Exception as exc:
        logger.warning("[insights] Disagreement check failed: %s", exc)
    
    return cards


def _count_open_disagreements(org, scope, time) -> int:
    """Count Blocks with open AI/mail/calendar disagreements in the scope."""
    qs = Block.objects.filter(
        org=org,
        day__gte=time.start,
        day__lte=time.end,
    )
    # Apply scope
    if scope.type == "client":
        qs = qs.filter(client_id__in=scope.ids)
    elif scope.type == "staff":
        qs = qs.filter(user_id__in=scope.ids)
    # Open = at least one type of disagreement is set and unresolved
    from django.db.models import Q
    qs = qs.filter(
        (Q(ai_disagrees_with_agent=True) & Q(ai_disagreement_resolved_at__isnull=True))
        | (Q(mail_disagrees_with_agent=True) & Q(mail_disagreement_resolved_at__isnull=True))
        | (Q(calendar_disagrees_with_agent=True) & Q(calendar_disagreement_resolved_at__isnull=True))
    )
    return qs.count()


# --- card builders ---

def _wip_aging_card(org, scope, aged_total, bands) -> InsightCardPayload:
    return InsightCardPayload(
        id="threshold_wip_aged",
        severity="bad",
        headline=f"WIP aged 60+ days: ${aged_total:,.0f}",
        body=(
            f"${bands['61_90']:,.0f} in 61-90 day band, "
            f"${bands['90_plus']:,.0f} in 90+ band. "
            f"Risk of write-off — prioritize billing these clients."
        ),
        evidence=[
            {"label": "61-90 days", "value": f"${bands['61_90']:,.0f}"},
            {"label": "90+ days", "value": f"${bands['90_plus']:,.0f}"},
        ],
        source="threshold",
        drilldown={"scope": scope.to_dict(), "lens": "wip"},
    )


def _low_realization_card(value: float) -> InsightCardPayload:
    return InsightCardPayload(
        id="threshold_low_realization",
        severity="bad",
        headline=f"Realization dropped to {value:.1f}%",
        body=(
            "Dollar realization below 85% indicates a combination of unbilled time "
            "and rate discounting. Check the Realization lens for client-by-client breakdown."
        ),
        evidence=[{"label": "Dollar realization", "value": f"{value:.1f}%"}],
        source="threshold",
        drilldown={"scope": {"type": "firm", "ids": []}, "lens": "realization"},
    )


def _utilization_drift(vals: list) -> tuple | None:
    """Return (recent_avg, earlier_avg) when the last ~4 weeks are meaningfully
    below the prior 4 — a slow decline each weekly band reads as 'normal'."""
    complete = vals[:-1]  # drop current partial week
    if len(complete) < 8:
        return None
    import statistics as st
    recent = st.mean(complete[-4:])
    earlier = st.mean(complete[-8:-4])
    if earlier - recent >= 6.0:
        return round(recent, 1), round(earlier, 1)
    return None


def _utilization_drift_card(recent: float, earlier: float) -> InsightCardPayload:
    return InsightCardPayload(
        id="baseline_utilization_drift",
        severity="watch",
        headline=f"Utilization trending down ({earlier:.0f}% → {recent:.0f}%)",
        body=(
            f"Your last ~4 weeks averaged {recent:.0f}%, down from ~{earlier:.0f}% the "
            f"month before. Each week still looks 'normal,' but the trend is slipping — "
            f"worth a look before it becomes the new normal."
        ),
        evidence=[
            {"label": "Last 4 wks", "value": f"{recent:.0f}%"},
            {"label": "Prior 4 wks", "value": f"{earlier:.0f}%"},
        ],
        source="threshold",
        drilldown={"scope": {"type": "firm", "ids": []}, "lens": "utilization"},
    )


def _low_utilization_card(value: float, band: dict | None = None) -> InsightCardPayload:
    if band:
        body = (
            f"Below your firm's usual {band['p25']:.0f}–{band['p75']:.0f}% range "
            f"(≈{band['baseline']:.0f}% over the last {band['n']} weeks) — a real dip, "
            f"not just a low textbook number. Check the Utilization lens for the "
            f"per-staff and Mix × Coverage breakdown."
        )
        evidence = [
            {"label": "This period", "value": f"{value:.1f}%"},
            {"label": "Your normal", "value": f"{band['p25']:.0f}–{band['p75']:.0f}%"},
        ]
    else:
        body = (
            "Billable share of tracked (active) working time is on the low side. "
            "May reflect non-billable/internal work or client work not yet attributed "
            "to a client. (Still calibrating your firm's normal range.)"
        )
        evidence = [{"label": "Utilization", "value": f"{value:.1f}%"}]
    return InsightCardPayload(
        id="threshold_low_utilization",
        severity="watch",
        headline=f"Utilization at {value:.1f}%",
        body=body,
        evidence=evidence,
        source="threshold",
        drilldown={"scope": {"type": "firm", "ids": []}, "lens": "utilization"},
    )


def _high_utilization_card(value: float, band: dict | None = None) -> InsightCardPayload:
    if band:
        body = (
            f"Above your firm's usual range (best recent week was {band['max']:.0f}%). "
            f"Great throughput — but if it's sustained, watch for burnout and consider "
            f"capacity/hiring."
        )
        evidence = [
            {"label": "This period", "value": f"{value:.1f}%"},
            {"label": "Your normal", "value": f"{band['p25']:.0f}–{band['p75']:.0f}%"},
        ]
    else:
        body = (
            "Sustained very high utilization is hard to maintain. Watch for burnout "
            "signals and consider hiring or workload rebalancing."
        )
        evidence = [{"label": "Utilization", "value": f"{value:.1f}%"}]
    return InsightCardPayload(
        id="threshold_high_utilization",
        severity="watch",
        headline=f"Utilization at {value:.1f}%",
        body=body,
        evidence=evidence,
        source="threshold",
        drilldown={"scope": {"type": "firm", "ids": []}, "lens": "utilization"},
    )


def _disagreement_card(count: int) -> InsightCardPayload:
    return InsightCardPayload(
        id="threshold_disagreements",
        severity="watch",
        headline=f"{count} unresolved attribution disagreements",
        body=(
            "TimeTracker's classifier flagged blocks where AI, mail, or calendar "
            "signals disagree with the original attribution. Review in Daily Review."
        ),
        evidence=[{"label": "Open disagreements", "value": str(count)}],
        source="threshold",
        drilldown={"scope": {"type": "firm", "ids": []}, "lens": "pulse"},
    )


# ---------------------------------------------------------------------------
# Tier 1: Rule-driven (your moat — OrgRoutingRule with category='flagging')
# ---------------------------------------------------------------------------

def _generate_rule_insights(
    org: Organization, scope: Scope, time: TimeRange
) -> list[InsightCardPayload]:
    """
    Read OrgRoutingRule rows where category='flagging' and synthesize cards
    from their fire telemetry. Stubbed for v2 launch — RuleFireLog gives us
    the data, we just need a meaningful aggregation. Concrete implementation
    lands in v2.1 when we know which rule patterns customers actually configure.
    """
    return []


# ---------------------------------------------------------------------------
# Tier 3: AI-driven (Executive only)
# ---------------------------------------------------------------------------

def _generate_ai_insights(
    org: Organization, scope: Scope, time: TimeRange
) -> list[InsightCardPayload]:
    """
    Calls GPT-4o with the period's deltas and asks for one or two findings
    in our schema. Stubbed for v2 launch — wire up after threshold/rule
    insights have been validated in production.
    """
    # Pseudocode for the real implementation:
    #   context = {
    #       "revenue_delta": ..., "wip_delta": ..., "client_changes": ...,
    #   }
    #   prompt = AI_INSIGHTS_PROMPT.format(**context)
    #   response = openai.chat.completions.create(model="gpt-4o", messages=...)
    #   findings = json.loads(response.choices[0].message.content)["findings"]
    #   return [InsightCardPayload(...) for f in findings]
    return []
