"""
views_ai_analysis.py
POST /api/analytics/ai-analysis/

Accepts the full KPI payload already returned by /analytics/executive/
and returns a structured AI analysis: headline, health score, wins, warnings, actions.

Requires OPENAI_API_KEY in environment (same key used by ai-classify).
"""

import json
import logging
import os
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


def _get_org_for_request(request):
    """
    Resolve org from the Bearer token in the Authorization header.
    This view is a plain Django view (not DRF APIView), so request.user is
    AnonymousUser even after BearerAuth runs — we must parse the token ourselves.
    Returns (org, error_response) — error_response is None on success.
    """
    from tracker.models import AuthToken, OrganizationMembership
    from django.utils import timezone

    # --- 1. Extract raw token string ---
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    token_str = None
    if auth_header.startswith("Bearer "):
        token_str = auth_header[7:].strip()
    elif auth_header.startswith("Token "):
        token_str = auth_header[6:].strip()

    if not token_str:
        logger.warning("[AI-ANALYSIS] No Bearer token in request")
        return None, JsonResponse({"error": "Authentication required."}, status=401)

    # --- 2. Look up AuthToken ---
    try:
        auth_token = AuthToken.objects.select_related("user").get(token=token_str)
    except AuthToken.DoesNotExist:
        logger.warning("[AI-ANALYSIS] Token not found")
        return None, JsonResponse({"error": "Invalid token."}, status=401)

    if auth_token.expires_at and auth_token.expires_at < timezone.now():
        logger.warning("[AI-ANALYSIS] Token expired")
        return None, JsonResponse({"error": "Token expired."}, status=401)

    user = auth_token.user

    # --- 3. Resolve org (owner-preference) ---
    qs = OrganizationMembership.objects.filter(user=user).select_related("organization").order_by("-id")
    membership = qs.filter(role="owner").first() or qs.first()
    if not membership:
        return None, JsonResponse({"error": "No organization found for this user."}, status=404)

    return membership.organization, None


def _build_prompt(kpis: dict, meta: dict) -> str:
    """Compress KPI data into a tight prompt for GPT."""

    def fmt(v, prefix="", suffix="", decimals=1):
        if v is None:
            return "N/A"
        try:
            return f"{prefix}{float(v):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            return str(v)

    r   = kpis.get("realization_rate",     {})
    u   = kpis.get("billable_utilization", {})
    w   = kpis.get("wip_pipeline",         {})
    e   = kpis.get("effective_rate",       {})
    rev = kpis.get("revenue_trend",        {})
    p   = kpis.get("client_profitability", {})
    inv = kpis.get("invoice_profitability",{})
    c   = kpis.get("timesheet_compliance", {})
    ct  = kpis.get("invoice_cycle_time",   {})

    # Summarize client profitability (top 3 + bottom 1)
    clients = sorted(p.get("clients", []), key=lambda x: x.get("margin_pct", 0), reverse=True)
    top_clients = ", ".join(f"{cl['client_name']} ({cl['margin_pct']:.0f}% margin)" for cl in clients[:3]) or "none"
    low_clients = ", ".join(f"{cl['client_name']} ({cl['margin_pct']:.0f}%)" for cl in clients[-2:] if cl.get("margin_pct", 0) < 20) or "none"

    # Revenue trend direction
    trend = rev.get("trend", [])
    rev_direction = "flat"
    if len(trend) >= 2:
        first_half = sum(t["revenue"] for t in trend[:len(trend)//2]) / max(1, len(trend)//2)
        second_half = sum(t["revenue"] for t in trend[len(trend)//2:]) / max(1, len(trend) - len(trend)//2)
        if second_half > first_half * 1.05:
            rev_direction = "growing"
        elif second_half < first_half * 0.95:
            rev_direction = "declining"

    # Low-utilization staff
    low_staff = [s["name"] for s in u.get("staff", []) if s.get("utilization", 100) < 60]

    lines = [
        f"CPA Firm: {meta.get('org_name', 'Unknown')}",
        f"Period: {meta.get('start_date')} to {meta.get('end_date')}",
        "",
        "=== KEY METRICS ===",
        f"Realization rate: {fmt(r.get('overall'))}% (billed {fmt(r.get('total_billed_hours'))}h / worked {fmt(r.get('total_worked_hours'))}h)",
        f"Billable utilization: {fmt(u.get('overall'))}%",
        f"WIP pipeline: ${w.get('total', 0):,.0f} (uninvoiced approved work)",
        f"Effective rate: ${fmt(e.get('effective_rate'), decimals=0)}/hr (standard: ${fmt(e.get('standard_rate'), decimals=0)}/hr, variance: ${fmt(e.get('variance'), decimals=0)})",
        f"Revenue trend: {rev_direction} | Total: ${rev.get('total_revenue', 0):,.0f} | Avg/mo: ${rev.get('avg_monthly_revenue', 0):,.0f}",
        f"Timesheet compliance: {fmt(c.get('overall'))}% on time ({c.get('compliant', 0)}/{c.get('total_timesheets', 0)} submitted within grace period)",
        f"Invoice cycle time: {fmt(ct.get('avg_days'))} days avg, {fmt(ct.get('median_days'))} days median",
        f"Top margin clients: {top_clients}",
        f"Low margin clients (<20%): {low_clients}",
        f"Staff utilization <60%: {', '.join(low_staff) if low_staff else 'none'}",
    ]

    inv_clients = inv.get("clients", [])
    if inv_clients:
        inv_totals = inv.get("totals", {})
        lines += [
            f"Invoice-based margin: {fmt(inv_totals.get('margin_pct'))}% overall",
            f"Invoice count: {sum(c.get('invoice_count', 0) for c in inv_clients)} invoices across {len(inv_clients)} clients",
        ]

    wip_buckets = w.get("buckets", {})
    aged_wip = (wip_buckets.get("61_90", 0) or 0) + (wip_buckets.get("90_plus", 0) or 0)
    if aged_wip:
        lines.append(f"Aged WIP (61+ days): ${aged_wip:,.0f} — at risk of write-off")

    return "\n".join(lines)


def _call_openai(prompt: str) -> dict:
    import urllib.request

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    system = (
        "You are a blunt, no-BS practice management advisor for CPA firms. "
        "Analyze the metrics provided and return a JSON object with exactly these fields:\n"
        "{\n"
        '  "headline": "One sharp sentence summarizing the firm\'s situation",\n'
        '  "score": <integer 0-100 representing overall firm health>,\n'
        '  "wins": ["bullet 1", "bullet 2", ...],\n'
        '  "warnings": ["bullet 1", "bullet 2", ...],\n'
        '  "actions": ["bullet 1", "bullet 2", ...]\n'
        "}\n\n"
        "Rules:\n"
        "- wins: what is actually working well (2-4 bullets)\n"
        "- warnings: what is hurting profitability or efficiency (2-4 bullets)\n"
        "- actions: specific things to do right now, this week (2-4 bullets)\n"
        "- Each bullet is ONE sentence, max 15 words, direct and actionable\n"
        "- Do NOT hedge. No 'consider' or 'may want to'. Tell them what to do.\n"
        "- Score: 85+ = healthy, 70-84 = solid but improvable, 50-69 = warning signs, <50 = critical\n"
        "- Return ONLY the JSON object. No preamble, no markdown."
    )

    payload = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 600,
        "response_format": {"type": "json_object"},
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    raw = data["choices"][0]["message"]["content"]
    return json.loads(raw)


@csrf_exempt
@require_http_methods(["POST", "OPTIONS"])
def ai_analysis(request):
    if request.method == "OPTIONS":
        resp = JsonResponse({})
        resp["Access-Control-Allow-Origin"]  = "*"
        resp["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        resp["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return resp

    try:
        org, error_response = _get_org_for_request(request)
        if error_response:
            return error_response

        # Plan gate: executive only
        plan = getattr(org, "plan", "")
        if not any(plan.startswith(p) for p in ("executive",)):
            return JsonResponse({"error": "AI analysis requires the Executive plan."}, status=403)

        body = json.loads(request.body or "{}")
        kpis = body.get("kpis", {})
        meta = body.get("meta", {})

        if not kpis:
            return JsonResponse({"error": "No KPI data provided."}, status=400)

        prompt = _build_prompt(kpis, meta)
        logger.info("AI analysis prompt built for org %s (%d chars)", org.id, len(prompt))

        result = _call_openai(prompt)

        # Validate shape
        for key in ("headline", "score", "wins", "warnings", "actions"):
            if key not in result:
                raise ValueError(f"Missing key in AI response: {key}")

        resp = JsonResponse({"analysis": result})
        resp["Access-Control-Allow-Origin"] = "*"
        return resp

    except json.JSONDecodeError as e:
        logger.error("AI analysis JSON error: %s", e)
        return JsonResponse({"error": "Invalid JSON in request body."}, status=400)
    except ValueError as e:
        logger.error("AI analysis value error: %s", e)
        return JsonResponse({"error": str(e)}, status=500)
    except Exception as e:
        logger.exception("AI analysis unexpected error")
        return JsonResponse({"error": f"Analysis failed: {str(e)}"}, status=500)