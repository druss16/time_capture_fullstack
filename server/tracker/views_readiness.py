# tracker/views_readiness.py
"""
What the firm has given us, and what is still missing.

Every number in Analytics rests on data somebody has to supply — wages, a
burden factor, fees, invoices — and until now nothing in the product said which
of those had actually arrived. A firm could look at a revenue figure for weeks
without knowing it was an estimate because no invoice had ever been imported,
or read a burn percentage derived from a budget the system invented. The gap
wasn't that the data was missing; it was that its absence was invisible.

Each check answers three questions in the firm's own terms: is this done, what
does it unlock, and where do I go. Checks that pass say so briefly and get out
of the way — this is a to-do list, not a dashboard.
"""
from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.views_billing import get_user_org

OK, PARTIAL, MISSING = "ok", "partial", "missing"


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def setup_readiness(request):
    """Ordered checks, most blocking first."""
    from decimal import Decimal

    from tracker.models import (
        Client, CostTier, EmployeeCostRate, Engagement, Invoice,
        OrganizationMembership,
    )
    from tracker.cost_visibility import can_view_cost_data

    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)

    can_cost = can_view_cost_data(request.user, org)
    checks: list[dict] = []

    # ── 1. invoices: the single biggest unlock ─────────────────────────────
    n_inv = Invoice.objects.filter(org=org).count()
    checks.append({
        "id": "invoices",
        "title": "Import your invoices",
        "status": OK if n_inv else MISSING,
        "detail": (f"{n_inv:,} invoices imported."
                   if n_inv else
                   "None imported. Revenue is an estimate of what your time was "
                   "worth, WIP only grows because nothing ever marks work as "
                   "billed, and two tabs stay empty."),
        "unlocks": "Actual revenue instead of estimated · WIP that drains · "
                   "Realization and Trends · real leakage",
        "where": "Billing → Invoices → Import CSV",
        "link": "/billing?tab=invoices",
    })

    # ── 2. per-person cost, and whether it's loaded ────────────────────────
    if can_cost:
        members = OrganizationMembership.objects.filter(organization=org)
        n_members = members.count()
        rated = set(EmployeeCostRate.objects.filter(organization=org)
                    .values_list("user_id", flat=True))
        tiered = set(members.exclude(cost_tier=None).values_list("user_id", flat=True))
        covered = rated | tiered
        missing = n_members - len(covered)
        checks.append({
            "id": "cost_rates",
            "title": "Set what each person costs",
            "status": OK if not missing else (PARTIAL if covered else MISSING),
            "detail": (f"{len(rated)} of {n_members} have their own rate; "
                       f"{len(tiered - rated)} fall back to a tier."
                       + (f" {missing} have neither and use the firm default."
                          if missing else "")),
            "unlocks": "Margin per client and per person",
            "where": "Settings → Economics → Tiers & assignments",
            "link": "/settings?tab=economics",
        })

        burden = Decimal(str(getattr(org, "payroll_burden_multiplier", 1) or 1))
        checks.append({
            "id": "burden",
            "title": "Say what payroll really costs",
            "status": OK if burden > 1 else MISSING,
            "detail": (f"Wages are multiplied by {burden:g} to cover taxes, "
                       f"benefits and PTO."
                       if burden > 1 else
                       "Set to 1.00, so the rates you entered are treated as "
                       "fully loaded. If they're raw wages, every margin on the "
                       "site is too high."),
            "unlocks": "Margin that reflects what an hour actually costs",
            "where": "Settings → Economics → Firm defaults",
            "link": "/settings?tab=economics",
        })

    # ── 3. engagement budgets ──────────────────────────────────────────────
    open_eng = Engagement.objects.filter(org=org, status="open").exclude(client=None)
    pairs = set(open_eng.values_list("client_id", "engagement_type"))
    manual_pairs = set(open_eng.filter(budget_source="manual")
                       .values_list("client_id", "engagement_type"))
    if pairs:
        checks.append({
            "id": "engagement_budgets",
            "title": "Enter what each job is worth",
            "status": (OK if len(manual_pairs) == len(pairs)
                       else PARTIAL if manual_pairs else MISSING),
            "detail": (f"{len(manual_pairs)} of {len(pairs)} jobs have a fee you set. "
                       f"The rest use a budget guessed from previously recorded "
                       f"hours, which is only as good as what the agent captured."),
            "unlocks": "Burn-vs-pace you can act on, and which fixed fees are "
                       "quietly unprofitable",
            "where": "Settings → Economics → Engagement budgets",
            "link": "/settings?tab=economics",
        })

    # ── 4. does billed work drain WIP ──────────────────────────────────────
    checks.append({
        "id": "wip_relief",
        "title": "Let invoices drain WIP",
        "status": OK if getattr(org, "wip_auto_relief", False) else MISSING,
        "detail": ("Invoices are matched against uninvoiced time each night."
                   if getattr(org, "wip_auto_relief", False) else
                   "Off — so WIP will keep climbing even after you import "
                   "invoices."),
        "unlocks": "WIP that falls when you bill",
        "where": "Settings → Economics → Firm defaults",
        "link": "/settings?tab=economics",
    })

    # ── 5. coverage: not config, but it caps everything above ──────────────
    cov = _coverage_pct(org)
    if cov is not None:
        checks.append({
            "id": "coverage",
            "title": "Get the agent running everywhere",
            "status": OK if cov >= 80 else (PARTIAL if cov >= 50 else MISSING),
            "detail": (f"About {cov:.0f}% of scheduled hours are reaching the "
                       f"system. Everything else here is a floor, not a total — "
                       f"we can only report what we see."),
            "unlocks": "Numbers that stand up next to a P&L",
            "where": "Settings → Devices",
            "link": "/settings?tab=devices",
        })

    # ── 6. clients with nowhere to bill to ─────────────────────────────────
    n_clients = Client.objects.filter(org=org, is_active=True).count()
    checks.append({
        "id": "clients",
        "title": "Have your client list in",
        "status": OK if n_clients else MISSING,
        "detail": f"{n_clients:,} active clients.",
        "unlocks": "Time attributed to the right client",
        "where": "Settings → Clients",
        "link": "/settings?tab=clients",
    })

    done = sum(1 for c in checks if c["status"] == OK)
    return Response({
        "checks": checks,
        "summary": {
            "total": len(checks),
            "done": done,
            "blocking": sum(1 for c in checks if c["status"] == MISSING),
        },
    })


def _coverage_pct(org) -> float | None:
    """Tracked hours against scheduled capacity over the last 30 days.

    Deliberately the same basis the Review tab shows, so the checklist and the
    dashboard can't quote different coverage numbers at each other.
    """
    from datetime import timedelta

    from django.db.models import Sum
    from django.utils import timezone

    from tracker.analytics_v2.blocks import working_qs
    from tracker.analytics_v2.capacity import capacity_hours_map
    from tracker.models import Block

    end = timezone.localdate()
    start = end - timedelta(days=30)
    qs = working_qs(Block.objects.filter(org=org, day__gte=start, day__lte=end), org)
    tracked = (qs.aggregate(s=Sum("minutes"))["s"] or 0) / 60.0
    uids = list(qs.order_by().values_list("user_id", flat=True).distinct())
    if not uids:
        return None
    capacity = sum(capacity_hours_map(org, uids, start, end).values())
    if capacity <= 0:
        return None
    return min(100.0, tracked / capacity * 100)
