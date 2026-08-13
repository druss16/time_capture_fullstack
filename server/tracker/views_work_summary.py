"""
Client work-summary generation — turns a client's committed activity over a
period into a concise, professional, client-readable narrative (the kind a CPA
firm puts on an invoice or a status email).

Design guardrails:
  - READ-ONLY. Touches no attribution, no billing, no block state.
  - PRIVACY: the model only ever sees activity *titles / categories / minutes*
    (the same metadata the existing AI client-guess uses) — never document
    contents.
  - PROPOSE, don't assert: the output is a draft for a human to review/edit
    before it reaches a client.
  - Deterministic gathering; the LLM only writes prose over data we hand it and
    is instructed to invent nothing.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import Block, Client
from tracker.views_block_evidence import _clean_label

_MODEL = "gpt-4o-mini"
_MAX_ACTIVITIES_PER_CATEGORY = 12


def _resolve_range(request):
    """Date window for a summary. Prefers explicit start/end (billing/monthly);
    otherwise falls back to date + days (staff/weekly). Returns (start, end) dates."""
    start_s, end_s = request.GET.get("start"), request.GET.get("end")
    if start_s and end_s:
        sd, ed = parse_date(start_s), parse_date(end_s)
        if sd and ed and sd <= ed:
            return sd, ed
    date_s = request.GET.get("date")
    target = parse_date(date_s) if date_s else timezone.localdate()
    if not target:
        return None, None
    try:
        days = max(1, min(45, int(request.GET.get("days", "1"))))
    except (TypeError, ValueError):
        days = 1
    return target - timedelta(days=days - 1), target


def _range_utc(start_date, end_date):
    tz = timezone.get_current_timezone()
    s = timezone.make_aware(datetime.combine(start_date, datetime.min.time()), tz).astimezone(dt_timezone.utc)
    e = timezone.make_aware(datetime.combine(end_date, datetime.max.time()), tz).astimezone(dt_timezone.utc)
    return s, e


def _firm_authorized(user, org):
    """Firm-wide (all-staff) summaries are management-only — the invoice-narrative
    audience: owners, admins, managers."""
    try:
        from tracker.views import get_user_role
        return get_user_role(user, org) in ("owner", "admin", "manager")
    except Exception:
        return False


def _fmt_period(start_date, end_date) -> str:
    if start_date == end_date:
        return start_date.strftime("%b %-d, %Y")
    if start_date.year == end_date.year:
        return f"{start_date.strftime('%b %-d')} – {end_date.strftime('%b %-d, %Y')}"
    return f"{start_date.strftime('%b %-d, %Y')} – {end_date.strftime('%b %-d, %Y')}"


def _build_digest(client, blocks, start_date, end_date):
    """Group committed blocks into a compact, LLM-ready activity digest —
    per category: total hours + the distinct things worked on."""
    per_cat_minutes = defaultdict(float)
    per_cat_labels = defaultdict(list)
    seen = defaultdict(set)
    total_minutes = 0.0

    for b in blocks:
        mins = float(b.minutes or 0)
        if mins <= 0:
            continue
        ch = b.category_hours or {}
        category = max(ch, key=ch.get) if ch else "General Client Work"
        raw = (b.window_title or b.app_name or "").strip()
        label = _clean_label(raw) or "Client work"
        total_minutes += mins
        per_cat_minutes[category] += mins
        key = label.lower()
        if key not in seen[category]:
            seen[category].add(key)
            if len(per_cat_labels[category]) < _MAX_ACTIVITIES_PER_CATEGORY:
                per_cat_labels[category].append(label)

    categories = []
    for cat, mins in sorted(per_cat_minutes.items(), key=lambda kv: -kv[1]):
        categories.append({
            "category": cat,
            "hours": round(mins / 60.0, 2),
            "activities": per_cat_labels[cat],
        })

    return {
        "client": client.name,
        "period": _fmt_period(start_date, end_date),
        "total_hours": round(total_minutes / 60.0, 2),
        "categories": categories,
    }


_SYSTEM_PROMPT = (
    "You are an assistant to a CPA firm, drafting a concise, professional, "
    "client-facing summary of work performed — the kind that goes on an invoice "
    "narrative or a client status note.\n"
    "Rules:\n"
    "- Use ONLY the activities, categories, and hours provided. Invent nothing — "
    "no amounts, findings, outcomes, dates, or specifics that aren't in the data.\n"
    "- Write in past tense, third person, professional but plain English.\n"
    "- Group related work; lead with the largest categories.\n"
    "- Prefer 2–5 short bullet points. No greeting, no sign-off, no filler, no "
    "mention of software or file names — describe the WORK, not the tools.\n"
    "- If the data is thin, keep it brief and general rather than padding."
)


def _call_openai(
    digest: dict,
    system_prompt: str = _SYSTEM_PROMPT,
    user_intro: str = "Draft a work summary for this client from the activity below.",
    temperature: float = 0.2,
    max_tokens: int = 400,
):
    """Returns (summary_text, tokens_used). Raises on failure."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    user_prompt = user_intro + "\n\n" + json.dumps(digest, ensure_ascii=False)
    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())

    text = (data["choices"][0]["message"]["content"] or "").strip()
    tokens = int((data.get("usage") or {}).get("total_tokens", 0))
    return text, tokens


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def client_work_summary(request, client_id):
    """GET /api/clients/<id>/work-summary/?date=YYYY-MM-DD&days=N

    Generates a professional, client-readable summary of the CURRENT user's
    committed work for this client over the window (default: the single `date`,
    or today). Read-only; logs the call to AIProcessingLog for cost visibility.
    """
    user = request.user

    try:
        client = Client.objects.select_related("org").get(id=client_id)
    except Client.DoesNotExist:
        return Response({"error": "Client not found"}, status=404)

    org = client.org
    if not user.memberships.filter(organization_id=org.id).exists() \
            and not (getattr(user, "is_mavops_admin", False) or user.is_superuser):
        return Response({"error": "forbidden"}, status=403)

    # Date window. Prefer explicit start/end (billing/monthly); else date+days.
    start_date, end_date = _resolve_range(request)
    if not start_date or not end_date:
        return Response({"error": "bad date range"}, status=400)
    start_utc, end_utc = _range_utc(start_date, end_date)

    # Scope: "mine" (default — the requester's own time) or "firm" (all staff's
    # work on this client, for an invoice narrative). Firm scope is management-only.
    scope = (request.GET.get("scope") or "mine").lower()
    firm = scope == "firm"
    if firm and not _firm_authorized(user, org):
        return Response({"error": "forbidden"}, status=403)

    block_filter = dict(
        org=org, client_id=client_id,
        classification_state="committed", deleted_at__isnull=True,
        start__gte=start_utc, start__lte=end_utc,
    )
    if not firm:
        block_filter["user"] = user
    blocks = list(
        Block.objects.filter(**block_filter)
        .only("minutes", "category_hours", "window_title", "app_name", "day")
    )

    if not blocks:
        return Response({
            "client_id": client_id, "client_name": client.name,
            "summary": "", "empty": True,
            "message": "No committed work for this client in the selected period.",
        })

    digest = _build_digest(client, blocks, start_date, end_date)

    t0 = time.monotonic()
    try:
        summary, tokens = _call_openai(digest)
        ok, err = True, ""
    except Exception as e:  # noqa: BLE001 — surface a clean message, log the detail
        summary, tokens, ok, err = "", 0, False, str(e)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    try:
        from tracker.models import AIProcessingLog
        AIProcessingLog.objects.create(
            org=org, user=user, operation_type="work_summary",
            input_data=digest, output_data={"summary": summary},
            model_used=_MODEL, tokens_used=tokens,
            processing_time_ms=elapsed_ms, success=ok, error_message=err[:500],
        )
    except Exception:
        pass

    if not ok:
        return Response({"error": "Couldn’t generate a summary right now."}, status=502)

    return Response({
        "client_id": client_id,
        "client_name": client.name,
        "period": digest["period"],
        "total_hours": digest["total_hours"],
        "summary": summary,
        "categories": digest["categories"],
    })


def _is_internal_name(name: str) -> bool:
    n = (name or "").strip().lower()
    return n == "internal" or n.startswith("internal -")


_WEEK_SYSTEM_PROMPT = (
    "You are writing a crisp, personable end-of-week work recap for the person who did the work "
    "— a clear note they'd drop to their manager or keep for themselves. Warm and human, but "
    "tight and scannable.\n"
    "HARD RULES:\n"
    "- Use ONLY the data provided. Invent nothing — no amounts, findings, outcomes, or specifics "
    "that aren't in the data.\n"
    "- NEVER name software, apps, or files (QuickBooks, Excel, Outlook, Microsoft, .xlsx, etc.). "
    "If an activity is just a tool or file name, describe the underlying task instead — "
    "bookkeeping, reconciliations, check runs, payroll, worksheets, email. Describe the WORK, "
    "never the tool.\n"
    "- Never write precise decimal hours. Use each client's hours_label verbatim (\"~2h\", "
    "\"about an hour\").\n"
    "FORMAT:\n"
    "- Open with ONE short, qualitative lead-in line (where the week's focus went). No numbers, "
    "no \"busy week\" filler, no exclamation points.\n"
    "- Then one bullet per main client, in order, each on its own line starting with '- '. "
    "Each bullet: \"Client Name — <concrete work>, <hours_label>.\" Draw the concrete work from "
    "that client's activities/categories; be specific (\"ran payroll and printed checks\", "
    "\"reconciled accounts and sent weekly invoices\", \"prepped the July reports\"). Avoid vague "
    "\"general client work\" / \"various tasks\" when a real activity exists.\n"
    "- If other_clients is given, end with ONE bullet: \"A few shorter items — <name up to 3 of "
    "its sample clients> and <count minus those named> others — <work from their categories>, "
    "<other_clients.hours_label> in total.\"\n"
    "- No greeting, no sign-off. No exclamation points anywhere."
)

# Window-title chrome that describes the tool, not the work — dropped from the digest
# so the recap has real activity signal to describe.
_CHROME_LABELS = {
    "go to", "open a company", "information", "home", "reminders", "untitled",
    "save print output as", "select checks to print", "print register", "print checks",
    "quickbooks desktop information", "print checks - confirmation",
    "quickbooks accountant desktop", "(secondary) quickbooks accountant desktop",
}


def _keep_activity(label: str) -> bool:
    ll = label.strip().lower()
    if ll in _CHROME_LABELS:
        return False
    if "(secondary)" in ll or "confirmation" in ll or "save print output" in ll:
        return False
    if re.sub(r"[^a-z]", "", ll) in ("quickbooks", "quickbooksaccountantdesktop"):
        return False
    return len(ll) >= 3


def _hours_phrase(h: float) -> str:
    """Human, rounded duration — never a robotic decimal."""
    if h < 0.5:
        return "under an hour"
    if h < 1.0:
        return "about an hour"
    r = round(h * 2) / 2  # nearest half hour
    return f"~{int(r)}h" if r == int(r) else f"~{r:.1f}h"


_WEEK_MAIN_CLIENTS = 6  # top clients get their own bullet; the rest are grouped


def _build_week_digest(blocks, start_date, end_date) -> dict:
    """One person's whole week across clients, shaped for a clean recap: the top
    clients (by hours) each with a friendly duration + top categories + a few
    real activities; the long tail collapsed into one grouped summary. Internal /
    no-client blocks are filtered by the caller."""
    per_client = {}

    for b in blocks:
        mins = float(b.minutes or 0)
        if mins <= 0:
            continue
        name = (b.client.name if b.client else "") or "Client"
        pc = per_client.setdefault(
            name, {"minutes": 0.0, "cat_minutes": defaultdict(float), "labels": [], "seen": set()}
        )
        ch = b.category_hours or {}
        category = max(ch, key=ch.get) if ch else "General Client Work"
        raw = (b.window_title or b.app_name or "").strip()
        label = _clean_label(raw) or "Client work"

        pc["minutes"] += mins
        pc["cat_minutes"][category] += mins
        key = label.lower()
        if key not in pc["seen"] and _keep_activity(label):
            pc["seen"].add(key)
            if len(pc["labels"]) < 8:
                pc["labels"].append(label)

    ordered = sorted(per_client.items(), key=lambda kv: -kv[1]["minutes"])

    main = []
    for name, pc in ordered[:_WEEK_MAIN_CLIENTS]:
        top_cats = [c for c, _ in sorted(pc["cat_minutes"].items(), key=lambda kv: -kv[1])[:4]]
        main.append({
            "client": name,
            "hours_label": _hours_phrase(pc["minutes"] / 60.0),
            "categories": top_cats,
            "activities": pc["labels"],
        })

    rest = ordered[_WEEK_MAIN_CLIENTS:]
    other = None
    if rest:
        rest_minutes = 0.0
        rest_cats = defaultdict(float)
        for _name, pc in rest:
            rest_minutes += pc["minutes"]
            for c, m in pc["cat_minutes"].items():
                rest_cats[c] += m
        other = {
            "count": len(rest),
            "hours_label": _hours_phrase(rest_minutes / 60.0),
            "sample": [n for n, _ in rest[:3]],
            "categories": [c for c, _ in sorted(rest_cats.items(), key=lambda kv: -kv[1])[:3]],
        }

    return {
        "period": _fmt_period(start_date, end_date),
        "main_clients": main,
        "other_clients": other,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_week_summary(request):
    """GET /api/work-summary/week/?date=YYYY-MM-DD&days=7

    A single personable, bulleted recap of the CURRENT user's committed client
    work across the window (their whole week) — one summary, not one narrative
    per client. Read-only; logs the call to AIProcessingLog for cost visibility.
    """
    from tracker.views import get_user_org

    user = request.user
    org = get_user_org(user)
    if not org:
        return Response({"error": "no org"}, status=400)

    start_date, end_date = _resolve_range(request)
    if not start_date or not end_date:
        return Response({"error": "bad date range"}, status=400)
    start_utc, end_utc = _range_utc(start_date, end_date)

    blocks = list(
        Block.objects.filter(
            org=org, user=user,
            classification_state="committed", deleted_at__isnull=True,
            client_id__isnull=False,
            start__gte=start_utc, start__lte=end_utc,
        )
        .select_related("client")
        .only("minutes", "category_hours", "window_title", "app_name", "client__name")
    )
    # Drop internal (never client-billable) buckets — this is a client-work recap.
    blocks = [b for b in blocks if b.client and not _is_internal_name(b.client.name)]

    if not blocks:
        return Response({
            "summary": "", "empty": True,
            "period": _fmt_period(start_date, end_date),
            "message": "No committed client work in this period yet.",
        })

    digest = _build_week_digest(blocks, start_date, end_date)

    t0 = time.monotonic()
    try:
        summary, tokens = _call_openai(
            digest,
            system_prompt=_WEEK_SYSTEM_PROMPT,
            user_intro="Write the recap from the data below.",
            temperature=0.4,
            max_tokens=500,
        )
        ok, err = True, ""
    except Exception as e:  # noqa: BLE001 — surface a clean message, log the detail
        summary, tokens, ok, err = "", 0, False, str(e)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    try:
        from tracker.models import AIProcessingLog
        AIProcessingLog.objects.create(
            org=org, user=user, operation_type="work_summary_week",
            input_data=digest, output_data={"summary": summary},
            model_used=_MODEL, tokens_used=tokens,
            processing_time_ms=elapsed_ms, success=ok, error_message=err[:500],
        )
    except Exception:
        pass

    if not ok:
        return Response({"error": "Couldn’t generate a summary right now."}, status=502)

    return Response({
        "period": digest["period"],
        "summary": summary,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def firm_period_clients(request):
    """GET /api/work-summaries/clients/?start=&end=  (management only)

    Lists clients with committed work across the WHOLE firm in the range, with
    hours — drives the invoice-narrative picker for owners / admins / managers.
    Read-only; no LLM call (that happens per client on demand via
    client_work_summary?scope=firm).
    """
    from django.db.models import Sum
    from tracker.views import get_user_org

    user = request.user
    org = get_user_org(user)
    if not org:
        return Response({"error": "no org"}, status=400)
    if not _firm_authorized(user, org):
        return Response({"error": "forbidden"}, status=403)

    start_date, end_date = _resolve_range(request)
    if not start_date or not end_date:
        return Response({"error": "bad date range"}, status=400)
    start_utc, end_utc = _range_utc(start_date, end_date)

    rows = (
        Block.objects.filter(
            org=org, classification_state="committed", deleted_at__isnull=True,
            client_id__isnull=False,
            start__gte=start_utc, start__lte=end_utc,
        )
        .values("client_id", "client__name")
        .annotate(minutes=Sum("minutes"))
        .order_by("-minutes")
    )
    clients = [
        {
            "client_id": r["client_id"],
            "name": r["client__name"] or "Client",
            "hours": round((r["minutes"] or 0) / 60.0, 2),
        }
        for r in rows if (r["minutes"] or 0) > 0
    ]
    return Response({
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "period": _fmt_period(start_date, end_date),
        "clients": clients,
    })
