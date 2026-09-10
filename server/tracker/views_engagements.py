"""
Engagement API — budget vs progress on open jobs.

    GET  /api/engagements/                    list open jobs with burn/progress
    POST /api/engagements/<id>/phase/         set the phase (the progress signal)
    POST /api/engagements/<id>/budget/        override the derived budget
    GET  /api/engagements/phase-agreement/    how well inference matches people

Setting a phase is the one piece of data entry in this whole feature, and it's
deliberately one click: everything else (which job, how many hours, what it
should have cost) is derived from what the agent already captured.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import Engagement, OrganizationMembership
from tracker.models_engagements import ladder_for
from tracker.services.engagements import engagement_stats, open_engagement_stats
from tracker.views_billing import get_user_org

logger = logging.getLogger(__name__)


def _can_manage(user, org) -> bool:
    """Owner/admin/manager set budgets. Any member can set a phase on work they
    can see — the preparer is the person who knows where the job is."""
    if user.is_staff or user.is_superuser:
        return True
    membership = OrganizationMembership.objects.filter(
        user=user, organization=org
    ).first()
    return bool(membership and membership.role in ("owner", "admin", "manager"))


def _phase_options(engagement: Engagement) -> list[dict]:
    return [
        {"value": key, "label": label, "progress": round(weight * 100)}
        for key, label, weight in ladder_for(engagement.engagement_type)
    ]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_engagements(request):
    """Open jobs, worst overrun first."""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)

    client_ids = None
    raw = request.query_params.get("client_id")
    if raw:
        try:
            client_ids = [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            return Response({"error": "client_id must be integer(s)"}, status=400)

    limit = request.query_params.get("limit")
    try:
        limit = int(limit) if limit else 100
    except ValueError:
        return Response({"error": "limit must be an integer"}, status=400)

    stats = open_engagement_stats(org, client_ids=client_ids, limit=limit)
    rows = []
    for s in stats:
        row = s.to_row()
        row["phase_options"] = _phase_options(s.engagement)
        row["budget_basis"] = s.engagement.budget_basis
        rows.append(row)

    return Response({
        "count": len(rows),
        "engagements": rows,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_engagement_phase(request, engagement_id: int):
    """Set where a job actually is. This is the progress half of burn-vs-progress."""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)

    engagement = get_object_or_404(Engagement, id=engagement_id, org=org)
    phase = (request.data.get("phase") or "").strip()
    valid = {key for key, _l, _w in ladder_for(engagement.engagement_type)}
    if phase and phase not in valid:
        return Response(
            {"error": f"Unknown phase {phase!r}. Valid: {sorted(valid)}"},
            status=400,
        )

    engagement.phase = phase
    engagement.phase_source = "user" if phase else ""
    engagement.phase_set_at = timezone.now() if phase else None
    engagement.phase_set_by = request.user if phase else None
    # Reaching the last rung closes the job — that's what makes it stop showing
    # up in the open-jobs worklist and become a comparable for next year.
    ladder = ladder_for(engagement.engagement_type)
    if phase and phase == ladder[-1][0]:
        engagement.status = "done"
    elif engagement.status == "done" and phase != ladder[-1][0]:
        engagement.status = "open"
    engagement.save(update_fields=[
        "phase", "phase_source", "phase_set_at", "phase_set_by", "status",
        "updated_at",
    ])

    stats = engagement_stats(
        engagement, rate=float(getattr(org, "billing_rate_default", 0) or 0)
    )
    return Response({"engagement": stats.to_row()})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_engagement_budget(request, engagement_id: int):
    """Override the derived budget. Marks the budget manual so the nightly
    derivation stops touching it."""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)
    if not _can_manage(request.user, org):
        return Response({"error": "Not permitted"}, status=403)

    engagement = get_object_or_404(Engagement, id=engagement_id, org=org)
    raw = request.data.get("budget_hours")

    if raw in (None, ""):
        # Clearing a manual budget hands the job back to auto-derivation.
        engagement.budget_hours = None
        engagement.budget_amount = None
        engagement.budget_source = "none"
        engagement.budget_basis = ""
    else:
        try:
            hours = Decimal(str(raw))
        except (InvalidOperation, TypeError):
            return Response({"error": "budget_hours must be a number"}, status=400)
        if hours <= 0:
            return Response({"error": "budget_hours must be positive"}, status=400)
        rate = Decimal(str(getattr(org, "billing_rate_default", 0) or 0))
        engagement.budget_hours = hours
        engagement.budget_amount = (hours * rate) if rate else None
        engagement.budget_source = "manual"
        engagement.budget_basis = f"set by {request.user.get_username()}"

    engagement.budget_set_at = timezone.now()
    engagement.save(update_fields=[
        "budget_hours", "budget_amount", "budget_source", "budget_basis",
        "budget_set_at", "updated_at",
    ])

    stats = engagement_stats(
        engagement, rate=float(getattr(org, "billing_rate_default", 0) or 0)
    )
    return Response({"engagement": stats.to_row()})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def phase_agreement(request):
    """How often the inferred phase matches what preparers actually said.

    The gate on ever trusting inference over asking. Admin-only because it's a
    calibration tool, not a firm metric.
    """
    from tracker.services.phase_inference import agreement_report

    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)
    if not _can_manage(request.user, org):
        return Response({"error": "Not permitted"}, status=403)

    return Response(agreement_report(org))


# ---------------------------------------------------------------------------
# Budget setup, at client x job-type grain
# ---------------------------------------------------------------------------
# A firm doesn't think "engagement 467 needs 6.15 hours". It thinks "Assumption
# Church bookkeeping is a $450 job". The fee is a property of the arrangement,
# not of one month of it — so the editing surface is client x engagement_type
# (166 rows for org 21), and setting one writes every open period at once. That
# is the same grain as set_engagement_budgets' CSV, deliberately: the page and
# the importer must not disagree about what a budget belongs to.


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def engagement_budget_setup(request):
    """Every client x job type with an open engagement, and its current budget."""
    from collections import defaultdict

    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)

    rate = float(getattr(org, "billing_rate_default", 0) or 0)
    from django.db.models import Sum
    from tracker.models import Block

    qs = (Engagement.objects.filter(org=org, status="open")
          .exclude(client=None).select_related("client"))

    # One aggregate for every engagement's hours, not services.actual_hours per
    # row. That helper runs a query each call, and this page has 383 of them —
    # 383 round trips to a remote database, which took the endpoint from
    # instant to unusable.
    hours_by_eng = {
        r["engagement"]: (r["m"] or 0) / 60.0
        for r in (Block.objects
                  .filter(engagement__in=qs)
                  .values("engagement")
                  .annotate(m=Sum("minutes")))
    }

    groups: dict[tuple, dict] = defaultdict(
        lambda: {"periods": 0, "budgets": set(), "sources": set(), "actuals": []}
    )
    for e in qs:
        g = groups[(e.client_id, e.client.name, e.engagement_type)]
        g["periods"] += 1
        g["budgets"].add(float(e.budget_hours) if e.budget_hours else None)
        g["sources"].add(e.budget_source or "")
        # What the firm actually works on this job. Not a proposed fee — capture
        # is incomplete, so this is a floor — but it's the number that makes a
        # blank box answerable: "we see about 8h a month on this, what do you
        # charge?" beats an empty field 166 times over.
        g["actuals"].append(hours_by_eng.get(e.id, 0.0))

    rows = []
    for (cid, cname, etype), g in groups.items():
        vals = {b for b in g["budgets"] if b is not None}
        # One number only when every open period agrees; otherwise the field
        # shows blank rather than picking a winner and hiding the disagreement.
        budget = round(next(iter(vals)), 2) if len(vals) == 1 else None
        # Median, so one catch-up month doesn't set the expectation.
        worked = sorted(x for x in g["actuals"] if x > 0)
        typical = (worked[len(worked) // 2] if worked else 0.0)
        rows.append({
            "client_id": cid,
            "client_name": cname,
            "engagement_type": etype,
            "open_periods": g["periods"],
            "typical_hours": round(typical, 2),
            "typical_value": round(typical * rate, 2) if (typical and rate) else None,
            "budget_hours": budget,
            "budget_mixed": len(vals) > 1,
            "budget_fee": round(budget * rate, 2) if (budget and rate) else None,
            "budget_source": (next(iter(g["sources"])) if len(g["sources"]) == 1
                              else "mixed"),
        })
    # Biggest first. Alphabetical buries the jobs worth pricing behind a hundred
    # one-period tax returns nobody needs to budget.
    rows.sort(key=lambda r: (-(r["typical_hours"] * r["open_periods"]),
                             r["client_name"].lower()))

    unset = sum(1 for r in rows if r["budget_hours"] is None)
    derived = sum(1 for r in rows
                  if r["budget_source"] in ("prior_year", "comparable"))
    return Response({
        "bill_rate": rate,
        "rows": rows,
        "summary": {
            "total": len(rows),
            "unset": unset,
            "derived": derived,
            "manual": sum(1 for r in rows if r["budget_source"] == "manual"),
        },
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def set_engagement_budget_group(request):
    """Write one budget across every open period of a client x job type.

    Accepts hours or a fee; a fee is divided by the firm's default bill rate,
    the same conversion the CSV importer uses. Writes budget_source='manual',
    which derive_budget refuses to overwrite — so the nightly derivation pass
    never undoes what a person typed.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)
    if not _can_edit(request.user, org):
        return Response({"error": "Not permitted"}, status=403)

    client_id = request.data.get("client_id")
    etype = (request.data.get("engagement_type") or "").strip()
    if not client_id or not etype:
        return Response({"error": "client_id and engagement_type are required"},
                        status=400)

    rate = float(getattr(org, "billing_rate_default", 0) or 0)
    hours = request.data.get("budget_hours")
    fee = request.data.get("monthly_fee")
    try:
        if hours not in (None, ""):
            hours = float(hours)
        elif fee not in (None, ""):
            if rate <= 0:
                return Response(
                    {"error": "Set a firm bill rate before budgeting by fee "
                              "(Settings -> Economics -> Firm defaults)"}, status=400)
            hours = float(fee) / rate
        else:
            return Response({"error": "Give budget_hours or monthly_fee"}, status=400)
    except (TypeError, ValueError):
        return Response({"error": "budget_hours / monthly_fee must be numbers"},
                        status=400)
    if hours <= 0:
        return Response({"error": "Budget must be greater than zero"}, status=400)

    engagements = list(Engagement.objects.filter(
        org=org, client_id=client_id, engagement_type=etype, status="open"))
    if not engagements:
        return Response({"error": "No open engagements for that client and type"},
                        status=404)

    for e in engagements:
        e.budget_hours = Decimal(str(round(hours, 2)))
        e.budget_amount = Decimal(str(round(hours * rate, 2))) if rate else None
        e.budget_source = "manual"
        e.budget_basis = f"set in Settings by {request.user.username}"
        e.budget_set_at = timezone.now()
        e.save(update_fields=["budget_hours", "budget_amount", "budget_source",
                              "budget_basis", "budget_set_at", "updated_at"])

    return Response({
        "client_id": client_id,
        "engagement_type": etype,
        "budget_hours": round(hours, 2),
        "periods_updated": len(engagements),
    })


def _can_edit(user, org) -> bool:
    m = OrganizationMembership.objects.filter(organization=org, user=user).first()
    return bool(m and m.role in ("owner", "admin", "manager"))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def engagement_budget_csv(request):
    """Upload a fee schedule instead of typing 166 rows.

    Same columns and same rules as `manage.py set_engagement_budgets`, because a
    firm that starts in the terminal and finishes in the page — or the reverse —
    must not get different answers. Previews by default; `apply=true` writes.

        client,engagement_type,budget_hours,monthly_fee

    Rows that can't be applied come back with their line number and the reason
    rather than being dropped, so a typo in row 40 doesn't silently cost a
    budget.
    """
    import csv
    import io

    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization"}, status=400)
    if not _can_edit(request.user, org):
        return Response({"error": "Not permitted"}, status=403)

    upload = request.FILES.get("file")
    if not upload:
        return Response({"error": "No file uploaded"}, status=400)
    if upload.size > 2 * 1024 * 1024:
        return Response({"error": "That file is larger than 2 MB — is it a CSV?"},
                        status=400)

    apply = str(request.data.get("apply", "")).lower() in ("1", "true", "yes")
    rate = float(getattr(org, "billing_rate_default", 0) or 0)

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return Response({"error": "Could not read that file as text. Save it as CSV."},
                        status=400)

    lines = text.splitlines(keepends=True)
    offset = 0
    while offset < len(lines) and (not lines[offset].strip()
                                   or lines[offset].lstrip().startswith("#")):
        offset += 1
    if offset >= len(lines):
        return Response({"error": "That file has no header row"}, status=400)

    planned, problems = [], []
    for i, r in enumerate(csv.DictReader(lines[offset:]), start=offset + 2):
        name = (r.get("client") or "").strip()
        if not name or name.startswith("#"):
            continue
        etype = (r.get("engagement_type") or "").strip().lower()
        if etype not in {"bookkeeping", "payroll", "tax_return"}:
            problems.append({"line": i, "reason":
                             f"engagement_type '{etype}' isn't one of "
                             f"bookkeeping, payroll, tax_return"})
            continue
        client = _resolve_client_by_name(org, name)
        if not client:
            problems.append({"line": i, "reason": f"no client matches '{name}'"})
            continue

        raw_h = (r.get("budget_hours") or "").strip()
        raw_f = (r.get("monthly_fee") or "").strip().replace("$", "").replace(",", "")
        if raw_h and raw_f:
            problems.append({"line": i, "reason": "give budget_hours or monthly_fee, not both"})
            continue
        try:
            if raw_h:
                hours = float(raw_h)
            elif raw_f:
                if rate <= 0:
                    problems.append({"line": i, "reason":
                                     "a fee needs a firm bill rate set first"})
                    continue
                hours = float(raw_f) / rate
            else:
                continue   # blank row: they haven't filled it in yet, not an error
        except ValueError:
            problems.append({"line": i, "reason": f"'{raw_h or raw_f}' isn't a number"})
            continue
        if hours <= 0:
            problems.append({"line": i, "reason": "budget must be more than zero"})
            continue

        engagements = list(Engagement.objects.filter(
            org=org, client=client, engagement_type=etype, status="open"))
        if not engagements:
            problems.append({"line": i, "reason":
                             f"{client.name} has no open {etype} jobs"})
            continue

        planned.append({
            "line": i, "client_id": client.id, "client_name": client.name,
            "engagement_type": etype, "budget_hours": round(hours, 2),
            "periods": len(engagements),
        })
        if apply:
            for e in engagements:
                e.budget_hours = Decimal(str(round(hours, 2)))
                e.budget_amount = Decimal(str(round(hours * rate, 2))) if rate else None
                e.budget_source = "manual"
                e.budget_basis = f"uploaded by {request.user.username}"
                e.budget_set_at = timezone.now()
                e.save(update_fields=["budget_hours", "budget_amount",
                                      "budget_source", "budget_basis",
                                      "budget_set_at", "updated_at"])

    return Response({
        "applied": apply,
        "planned": planned,
        "problems": problems,
        "summary": {
            "rows": len(planned),
            "periods": sum(p["periods"] for p in planned),
            "problems": len(problems),
        },
    })


def _resolve_client_by_name(org, raw: str):
    """Name, then code, then an exact alias — matching the CLI importer."""
    from tracker.models import Client
    name = (raw or "").strip()
    c = (Client.objects.filter(org=org, name__iexact=name).first()
         or Client.objects.filter(org=org, code__iexact=name).first())
    if c:
        return c
    for cand in Client.objects.filter(org=org).only("id", "name", "aliases"):
        for a in (cand.aliases or []):
            if str(a).strip().lower() == name.lower():
                return cand
    return None
