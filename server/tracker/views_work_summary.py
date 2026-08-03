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


def _call_openai(digest: dict):
    """Returns (summary_text, tokens_used). Raises on failure."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    user_prompt = (
        "Draft a work summary for this client from the activity below.\n\n"
        + json.dumps(digest, ensure_ascii=False)
    )
    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
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

    # Date window (mirror today_time): a single local day, optionally extended
    # back `days-1` days to cover a week/period.
    date_str = request.GET.get("date")
    target_date = parse_date(date_str) if date_str else timezone.localdate()
    if not target_date:
        return Response({"error": "bad date"}, status=400)
    try:
        days = max(1, min(31, int(request.GET.get("days", "1"))))
    except (TypeError, ValueError):
        days = 1
    start_date = target_date - timedelta(days=days - 1)

    tz = timezone.get_current_timezone()
    start_utc = timezone.make_aware(datetime.combine(start_date, datetime.min.time()), tz)\
        .astimezone(dt_timezone.utc)
    end_utc = timezone.make_aware(datetime.combine(target_date, datetime.max.time()), tz)\
        .astimezone(dt_timezone.utc)

    blocks = list(
        Block.objects.filter(
            org=org, user=user, client_id=client_id,
            classification_state="committed",
            deleted_at__isnull=True,
            start__gte=start_utc, start__lte=end_utc,
        ).only("minutes", "category_hours", "window_title", "app_name", "day")
    )

    if not blocks:
        return Response({
            "client_id": client_id, "client_name": client.name,
            "summary": "", "empty": True,
            "message": "No committed work for this client in the selected period.",
        })

    digest = _build_digest(client, blocks, start_date, target_date)

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
