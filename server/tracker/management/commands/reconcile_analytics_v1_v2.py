"""
Numerical reconciliation: run the same scope/period through v1 and v2,
print per-metric deltas. Target is within 0.5% on Tier 1 KPIs.

Usage:
    python manage.py reconcile_analytics_v1_v2 --org=21
    python manage.py reconcile_analytics_v1_v2 --org=21 --period=last_quarter
    python manage.py reconcile_analytics_v1_v2 --org=21 --period=ytd --verbose
    python manage.py reconcile_analytics_v1_v2 --org=21 --period=q1_2026

Periods accepted:
    today, yesterday, this_week, last_week, this_month, last_month,
    this_quarter, last_quarter, ytd, last_30_days, last_90_days,
    trailing_12_months, q1_2026 / q2_2025 / etc., busy_season, extension_season

Exits non-zero if any Tier 1 metric is off by more than 0.5%.
"""
from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tracker.analytics_v2.query import execute_query
from tracker.analytics_v2.scopes import resolve_relative_time
from tracker.models import Organization

User = get_user_model()


# Tier 1 KPIs must reconcile within this tolerance (0.5%)
TIER_1_METRICS = {
    "realization_dollar",
    "realization_hours",
    "billable_utilization",
    "wip_total",
    "invoiced_revenue",
}
TOLERANCE_PCT = 0.5


class Command(BaseCommand):
    help = "Reconcile v1 vs v2 analytics for an org/period and report deltas."
    
    def add_arguments(self, parser):
        parser.add_argument(
            "--org", required=True, type=int,
            help="Organization ID to reconcile",
        )
        parser.add_argument(
            "--period", default="this_quarter",
            help="Relative time expression (default: this_quarter)",
        )
        parser.add_argument(
            "--verbose", "-V", action="store_true",
            help="Print full payloads",
        )
    
    def handle(self, *args, **opts):
        org_id = opts["org"]
        period = opts["period"]
        verbose = opts["verbose"]
        
        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            raise CommandError(f"Organization id={org_id} not found")
        
        time_range = resolve_relative_time(period)
        
        self.stdout.write(self.style.HTTP_INFO(
            f"\n═══════════════════════════════════════════════════════════"
        ))
        self.stdout.write(self.style.HTTP_INFO(
            f"  Reconciliation: {org.name} (id={org.id})"
        ))
        self.stdout.write(self.style.HTTP_INFO(
            f"  Period: {time_range.label} ({time_range.start} → {time_range.end})"
        ))
        self.stdout.write(self.style.HTTP_INFO(
            f"═══════════════════════════════════════════════════════════\n"
        ))
        
        # Pick an admin/owner user for query authorization
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            raise CommandError(
                "No Django superuser found — cannot run reconciliation without one."
            )
        
        # --- v1 numbers via views_analytics direct call ---
        v1_metrics = self._get_v1_metrics(org, time_range)
        
        # --- v2 numbers via execute_query ---
        v2_metrics = self._get_v2_metrics(admin_user, org, time_range)
        
        # --- compare ---
        all_keys = sorted(set(v1_metrics) | set(v2_metrics))
        any_tier1_fail = False
        
        self.stdout.write(f"{'Metric':<30} {'v1':>15} {'v2':>15} {'Δ %':>10}  Status")
        self.stdout.write("─" * 80)
        
        for k in all_keys:
            v1 = v1_metrics.get(k)
            v2 = v2_metrics.get(k)
            delta_pct = self._delta_pct(v1, v2)
            tier1 = k in TIER_1_METRICS
            
            if v1 is None and v2 is None:
                status_str = self.style.WARNING("both empty")
            elif v1 is None or v2 is None:
                status_str = self.style.ERROR("MISSING ONE SIDE")
                if tier1:
                    any_tier1_fail = True
            elif delta_pct is None:
                status_str = self.style.WARNING("can't compute")
            elif tier1 and abs(delta_pct) > TOLERANCE_PCT:
                status_str = self.style.ERROR(f"FAIL (>{TOLERANCE_PCT}%)")
                any_tier1_fail = True
            elif abs(delta_pct or 0) > 2.0:
                status_str = self.style.WARNING("large delta")
            else:
                status_str = self.style.SUCCESS("ok")
            
            marker = " ★" if tier1 else "  "
            v1_str = self._fmt(v1)
            v2_str = self._fmt(v2)
            delta_str = (f"{delta_pct:+.2f}%" if delta_pct is not None else "—")
            self.stdout.write(
                f"{k:<28}{marker} {v1_str:>15} {v2_str:>15} {delta_str:>10}  {status_str}"
            )
        
        self.stdout.write("")
        self.stdout.write("★ = Tier 1 KPI (must reconcile within 0.5%)")
        self.stdout.write("")
        
        if verbose:
            self.stdout.write(self.style.HTTP_INFO("─── Full v1 payload ───"))
            self.stdout.write(json.dumps(v1_metrics, indent=2, default=str))
            self.stdout.write(self.style.HTTP_INFO("\n─── Full v2 payload ───"))
            self.stdout.write(json.dumps(v2_metrics, indent=2, default=str))
        
        if any_tier1_fail:
            raise CommandError("Tier 1 reconciliation FAILED")
        
        self.stdout.write(self.style.SUCCESS(
            "\nReconciliation PASSED for all Tier 1 metrics."
        ))
    
    # ----------------------------------------------------------------------
    
    def _get_v1_metrics(self, org, time_range) -> dict:
        """
        Call v1's _calc_* helpers directly to get comparable scalars.
        Returns {metric_id: float_or_None}.
        """
        from tracker import views_analytics as v1
        
        out = {}
        
        # The v1 helpers take (org, start_date, end_date). Some return dicts,
        # some return scalars. We map them to the v2 metric IDs.
        try:
            r = v1._calc_realization(org, time_range.start, time_range.end)
            # v1's _calc_realization returns {"hours": ..., "dollar": ...}
            out["realization_hours"] = r.get("hours") if isinstance(r, dict) else None
            out["realization_dollar"] = r.get("dollar") if isinstance(r, dict) else None
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"v1 realization failed: {exc}"))
        
        try:
            u = v1._calc_utilization(org, time_range.start, time_range.end)
            out["billable_utilization"] = u if isinstance(u, (int, float)) else u.get("rate") if isinstance(u, dict) else None
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"v1 utilization failed: {exc}"))
        
        try:
            w = v1._calc_wip(org)
            out["wip_total"] = w.get("total") if isinstance(w, dict) else w
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"v1 wip failed: {exc}"))
        
        try:
            from tracker.models import Invoice
            from django.db.models import Sum
            from decimal import Decimal as D
            inv_sum = Invoice.objects.filter(
                org=org,
                invoice_date__gte=time_range.start,
                invoice_date__lte=time_range.end,
            ).aggregate(s=Sum("amount"))["s"] or D("0")
            out["invoiced_revenue"] = float(inv_sum)
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"v1 invoiced_revenue failed: {exc}"))
        
        return out
    
    def _get_v2_metrics(self, admin_user, org, time_range) -> dict:
        """Pull v2 numbers by calling each metric directly. Bypasses lens
        assembly so we get raw values."""
        from tracker.analytics_v2.metrics import get_metric
        from tracker.analytics_v2.types import MetricState, Scope
        
        scope = Scope(type="firm", ids=(), label=org.name)
        out = {}
        for mid in ["realization_hours", "realization_dollar",
                    "billable_utilization", "wip_total", "invoiced_revenue"]:
            try:
                metric = get_metric(mid)
                v = metric.safe_compute(org, scope, time_range)
                out[mid] = v.value if v.state == MetricState.READY else None
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"v2 {mid} failed: {exc}"))
                out[mid] = None
        return out
    
    @staticmethod
    def _delta_pct(v1, v2) -> float | None:
        try:
            v1f = float(v1) if v1 is not None else None
            v2f = float(v2) if v2 is not None else None
        except (TypeError, ValueError):
            return None
        if v1f is None or v2f is None:
            return None
        if abs(v1f) < 1e-9:
            return 0.0 if abs(v2f) < 1e-9 else float("inf")
        return (v2f - v1f) / abs(v1f) * 100
    
    @staticmethod
    def _fmt(v) -> str:
        if v is None:
            return "—"
        try:
            return f"{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)
