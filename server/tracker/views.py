# tracker/views.py
from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
import asyncio
from datetime import timedelta, date as date_type, timezone as dt_timezone
from typing import Optional, List, Dict, Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.timezone import localtime

from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes, throttle_classes
)
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from .models import (
    RawEvent, Block, Rule, Suggestion, Client, Project, Task,
    OrganizationSettings, KnownEntity, AITrainingExample, TimecardEntry
)
from .permissions import AgentKeyPermission
from .rules import apply_rules
from .serializers import RawEventSerializer
from .ai_timecard_service_adapted import TimecardGenerator

# -------------------------------------------------------------------
# Config / constants
# -------------------------------------------------------------------
BLOCK_PAD_MINUTES = 10
MIN_BLOCK_DURATION = 6          # minutes
BLOCK_GRANULARITY = 6           # round to 6-min increments

DEFAULT_USER = "unknown-user"
DEFAULT_HOST = "unknown-host"

USE_AUTH = bool(getattr(settings, "USE_AUTH", False))
PermUI = IsAuthenticated if USE_AUTH else AllowAny

IDLE_STICKY_MINUTES = int(getattr(settings, "IDLE_STICKY_MINUTES", 4))   # configurable
FUZZY_HOST_MATCH = True
FUZZY_TITLE_THRESHOLD = float(getattr(settings, "FUZZY_TITLE_THRESHOLD", 0.72))

def _host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url or "").hostname or ""
    except Exception:
        return ""

def _similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    return SequenceMatcher(None, a, b).ratio()


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def get_org_or_default(request):
    """Get org from user or a default dev org."""
    if USE_AUTH and getattr(request, "user", None) and request.user.is_authenticated:
        org = request.user.groups.first()
    else:
        org = None
    if not org:
        from django.contrib.auth.models import Group
        org, _ = Group.objects.get_or_create(name="default-org")
    return org


def _start_of_local_day_utc(dt: Optional[timezone.datetime] = None) -> timezone.datetime:
    dt = dt or timezone.now()
    local = localtime(dt)
    sod_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return sod_local.astimezone(dt_timezone.utc)


def _label_from_event(e: RawEvent) -> str:
    # url host -> file basename -> window title -> app name
    if e.url:
        try:
            host = urllib.parse.urlparse(e.url).hostname or ""
            if host:
                return host
        except Exception:
            pass
    if e.file_path:
        return e.file_path.rstrip("/").split("/")[-1]
    if e.window_title:
        return e.window_title[:80]
    return e.app_name or "Unknown"


def _round_up_minutes(n: int, granularity: int) -> int:
    return n if n % granularity == 0 else n + (granularity - (n % granularity))


def build_classification_prompt(text_blocks: list, org_context: str) -> str:
    """Context-aware AI prompt for block classification."""
    prompt = f"""You are a time-tracking AI assistant. Your job is to classify computer activity blocks into client work, projects, and time categories.

{org_context if org_context else ""}

CLASSIFICATION RULES:
1) Client identification: match against KNOWN CLIENTS (including aliases). Mark internal work appropriately.
2) Project identification: infer from context; link to parent client if relevant.
3) Categories (hours in decimal): Meeting, Development, Research, Planning, Administration. Non-billable breaks should be 0 billable.
4) Time allocation: split multi-topic blocks; round to nearest 0.25h; include confidence (0.0–1.0).
5) Special cases: multiple clients -> pick dominant; unclear -> needs_review true with low confidence.

Return a JSON array with objects shaped like:
{{
  "client": "Acme Corp" | null,
  "project": "Q4 Strategy" | null,
  "categories": {{"Meeting": 1.0}},
  "confidence": 0.92,
  "needs_review": false,
  "reasoning": "why"
}}

NOW CLASSIFY THESE BLOCKS:
{text_blocks}

Return ONLY a JSON array. No markdown.
"""
    return prompt


def build_ai_context(org) -> str:
    """Build org-specific context to improve AI accuracy."""
    try:
        settings_obj = OrganizationSettings.objects.get(org=org)
    except OrganizationSettings.DoesNotExist:
        settings_obj = None

    context_parts = []
    if settings_obj and settings_obj.company_name:
        context_parts.append(f"COMPANY: {settings_obj.company_name}")
        if settings_obj.description:
            context_parts.append(f"DESCRIPTION: {settings_obj.description}")

    clients = KnownEntity.objects.filter(org=org, entity_type='client')
    if clients.exists():
        rows = []
        for c in clients:
            aliases = f" (aka: {', '.join(c.aliases)})" if c.aliases else ""
            internal = " [INTERNAL]" if c.is_internal else ""
            rows.append(f"  - {c.name}{aliases}{internal}")
        context_parts.append("KNOWN CLIENTS:\n" + "\n".join(rows))

    if settings_obj and settings_obj.internal_keywords:
        context_parts.append(f"INTERNAL WORK INDICATORS: {', '.join(settings_obj.internal_keywords)}")
        if settings_obj.default_internal_project:
            context_parts.append(f"DEFAULT INTERNAL PROJECT: {settings_obj.default_internal_project}")

    if settings_obj and settings_obj.custom_instructions:
        context_parts.append(f"SPECIAL INSTRUCTIONS:\n{settings_obj.custom_instructions}")

    recent = AITrainingExample.objects.filter(org=org).order_by('-created_at')[:5]
    if recent.exists():
        rows = []
        for ex in recent:
            cname = ex.correct_client.name if ex.correct_client else "N/A"
            rows.append(f'  - "{ex.text_content[:60]}..." → {cname}')
        context_parts.append("RECENT CORRECTIONS:\n" + "\n".join(rows))

    return "\n\n".join(context_parts)


# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([AllowAny])
def ping(_request):
    return Response({"ok": True})


# -------------------------------------------------------------------
# Agent ingestion
# -------------------------------------------------------------------
class NoAuth(BaseAuthentication):
    """Disable session/csrf for token/agent endpoints."""
    def authenticate(self, request):
        return None


@api_view(["POST"])
@authentication_classes([NoAuth])          # no cookies/csrf
@permission_classes([AgentKeyPermission])  # require Agent key header
@throttle_classes([AnonRateThrottle])
def raw_events(request):
    """
    Ingest one or many RawEvent objects. Accepts dict or list[dict].
    ts_utc may be ISO string or datetime; other fields per RawEventSerializer.
    """
    payload = request.data
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValidationError("Payload must be an object or an array of objects.")
    for item in payload:
        ts = item.get("ts_utc")
        if isinstance(ts, str):
            dt = parse_datetime(ts)
            if dt is None:
                raise ValidationError({"ts_utc": f"Invalid ts_utc: {ts}"})
            item["ts_utc"] = dt
    ser = RawEventSerializer(data=payload, many=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response({"created": len(payload)}, status=status.HTTP_201_CREATED)


# Optional: keep a dev/legacy open endpoint
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def ingest_raw_event(request):
    return raw_events(request)


# -------------------------------------------------------------------
# Compactor: RawEvent -> Block (for TODAY only; compaction-on-read)
# -------------------------------------------------------------------
@transaction.atomic
def compact_rawevents_into_blocks(user: Optional[str] = None, hostname: Optional[str] = None, org=None) -> int:
    """
    Compacts today's RawEvents into Block rows with:
      - host-aware, fuzzy title merging
      - sticky idle attribution
      - min duration + 6-min rounding
    """
    # 1) Scope to start-of-today (local -> UTC)
    start_utc = _start_of_local_day_utc()
    ev_qs = RawEvent.objects.filter(ts_utc__gte=start_utc).order_by("ts_utc")
    if user:
        ev_qs = ev_qs.filter(user=user)
    if hostname:
        ev_qs = ev_qs.filter(hostname=hostname)
    events: List[RawEvent] = list(ev_qs)

    # 2) Wipe today's blocks for this scope
    blk_qs = Block.objects.filter(start__gte=start_utc)
    if hasattr(Block, "user") and user:
        blk_qs = blk_qs.filter(user=user)
    if hasattr(Block, "hostname") and hostname:
        blk_qs = blk_qs.filter(hostname=hostname)
    blk_qs.delete()

    created = 0
    pad = timedelta(minutes=BLOCK_PAD_MINUTES)
    sticky_delta = timedelta(minutes=IDLE_STICKY_MINUTES)

    current: Optional[Dict[str, Any]] = None  # rolling block

    def _duration_minutes(cur: Dict[str, Any]) -> int:
        return int((cur["end"] - cur["start"]).total_seconds() // 60)

    def _finalize_and_create(cur: Dict[str, Any]) -> int:
        # duration with min + rounding
        actual = _duration_minutes(cur)
        target = max(MIN_BLOCK_DURATION, _round_up_minutes(actual, BLOCK_GRANULARITY))
        if actual < target:
            cur["end"] = cur["start"] + timedelta(minutes=target)

        kwargs: Dict[str, Any] = dict(
            start=cur["start"],
            end=cur["end"],
            title=cur["title"],
            url=cur.get("url") or "",
            file_path=cur.get("file_path") or "",
        )
        if hasattr(Block, "window_title"):
            kwargs["window_title"] = cur.get("window_title") or ""
        if hasattr(Block, "user"):
            kwargs["user"] = cur.get("user") or DEFAULT_USER
        if hasattr(Block, "hostname"):
            kwargs["hostname"] = cur.get("hostname") or DEFAULT_HOST
        if hasattr(Block, "minutes"):
            kwargs["minutes"] = int((kwargs["end"] - kwargs["start"]).total_seconds() // 60)

        # org handling
        if any(f.name == "org" for f in Block._meta.fields):
            field = Block._meta.get_field("org")
            if not field.null:
                if org is None:
                    from django.contrib.auth.models import Group
                    org, _ = Group.objects.get_or_create(name="default-org")
                kwargs["org"] = org
            else:
                kwargs["org"] = org

        Block.objects.create(**kwargs)
        return 1

    def _same_activity(prev: Dict[str, Any], lbl: str, url: str) -> bool:
        """Same block if identical title or (same host & fuzzy-similar title)."""
        if lbl == prev["title"]:
            return True
        if FUZZY_HOST_MATCH:
            prev_host = _host(prev.get("url", "")) if prev.get("url") else ""
            new_host = _host(url or "")
            if prev_host and (prev_host == new_host):
                if _similar(prev["title"], lbl) >= FUZZY_TITLE_THRESHOLD:
                    return True
        return False

    # 3) Stream & merge
    for e in events:
        lbl = _label_from_event(e)  # host -> filename -> window_title -> app_name
        u = user or getattr(e, "user", None) or DEFAULT_USER
        h = hostname or getattr(e, "hostname", None) or DEFAULT_HOST
        et = e.ts_utc
        url = e.url or ""
        fpath = e.file_path or ""
        wtitle = getattr(e, "window_title", "") or ""

        if current is None:
            # start first block
            current = dict(
                start=et,
                end=et,
                title=lbl,
                window_title=wtitle,
                url=url,
                file_path=fpath,
                user=u,
                hostname=h,
            )
            continue

        gap = et - current["end"]

        if gap <= pad and _same_activity(current, lbl, url):
            # Same activity → extend through any tiny idle (sticky) then to event time
            if timedelta(0) < gap <= sticky_delta:
                current["end"] += gap  # attribute idle to current block
            current["end"] = et
        else:
            # Different activity or big gap → finalize current
            created += _finalize_and_create(current)

            # If there is a tiny idle before the new event, we DO NOT create a separate idle block.
            # We start a fresh block at event time.
            current = dict(
                start=et,
                end=et,
                title=lbl,
                window_title=wtitle,
                url=url,
                file_path=fpath,
                user=u,
                hostname=h,
            )

    if current:
        created += _finalize_and_create(current)

    return created



# -------------------------------------------------------------------
# UI endpoints (compaction-on-read)
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def blocks_today(request):
    """Compact RawEvents -> Blocks for today (scoped by ?user=&hostname=) and return Blocks."""
    user = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org = get_org_or_default(request)

    compact_rawevents_into_blocks(user=user, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if user:
        qs = qs.filter(user=user)
    if hostname:
        qs = qs.filter(hostname=hostname)
    if org:
        qs = qs.filter(org=org)

    def minutes(b: Block) -> int:
        if hasattr(b, "minutes") and b.minutes is not None:
            return int(b.minutes)
        return int((b.end - b.start).total_seconds() / 60)

    data = [
        {
            "id": b.id,
            "start": b.start,
            "end": b.end,
            "minutes": minutes(b),
            "title": b.title,
            "window_title": getattr(b, "window_title", "") or "",
            "url": b.url,
            "file_path": b.file_path,
            "client": getattr(b.client, "name", None),
            "project": getattr(b.project, "name", None),
            "task": getattr(b.task, "name", None),
            "notes": getattr(b, "notes", "") or "",
        }
        for b in qs
    ]
    return Response(data)


@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def suggestions_today(request):
    """Recompute up to 3 rule-based suggestions per Block for today, after compaction."""
    user = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org = get_org_or_default(request)

    compact_rawevents_into_blocks(user=user, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if user:
        qs = qs.filter(user=user)
    if hostname:
        qs = qs.filter(hostname=hostname)
    if org:
        qs = qs.filter(org=org)

    rules = list(Rule.objects.filter(active=True, org=org))

    out = []
    with transaction.atomic():
        for b in qs:
            Suggestion.objects.filter(block=b).delete()
            for field, value_text, conf in list(apply_rules(b, rules))[:3]:
                Suggestion.objects.create(
                    block=b, label_type=field, value_text=value_text,
                    confidence=conf, source="rule"
                )
            out.append({
                "id": b.id,
                "start": b.start,
                "end": b.end,
                "minutes": int((b.end - b.start).total_seconds() / 60),
                "title": b.title,
                "window_title": getattr(b, "window_title", "") or "",
                "url": b.url,
                "file_path": b.file_path,
                "client": getattr(b.client, "name", None),
                "project": getattr(b.project, "name", None),
                "task": getattr(b.task, "name", None),
                "suggestions": [
                    {"label_type": s.label_type, "value_text": s.value_text, "confidence": s.confidence}
                    for s in b.suggestions.all().order_by("-confidence")[:3]
                ],
            })
    return Response(out)


@api_view(["POST"])
@permission_classes([PermUI])
def label_block(request):
    """
    Apply labels to a Block; optionally create a rule from this confirmation.
    Body:
      { block_id, client?, project?, task?, notes?, create_rule?, create_rule_field?, create_rule_value?, pattern?, kind? }
    """
    block_id = request.data.get("block_id")
    if not block_id:
        raise ValidationError({"block_id": "Required."})
    try:
        b = Block.objects.get(id=block_id)
    except Block.DoesNotExist:
        raise NotFound("Block not found.")

    # Mutations
    get = request.data.get
    if (v := get("client")):
        b.client = Client.objects.get(org=b.org, name=v)
    if (v := get("project")):
        b.project = Project.objects.get(org=b.org, name=v)
    if (v := get("task")):
        b.task = Task.objects.get(org=b.org, name=v)
    if (v := get("notes")) is not None:
        b.notes = v
    b.save()

    if request.data.get("create_rule"):
        field = get("create_rule_field")
        value_text = get("create_rule_value")
        if field not in {"client", "project", "task"}:
            raise ValidationError({"create_rule_field": "Must be 'client'|'project'|'task'."})
        if not value_text:
            raise ValidationError({"create_rule_value": "Required when create_rule is true."})
        pattern = get("pattern") or (b.url or b.file_path or (b.title or ""))[:200]
        Rule.objects.create(
            org=b.org,
            pattern=pattern,
            field=field,
            value_text=value_text,
            kind=get("kind") or "contains",
            active=True,
        )
    return Response({"ok": True})


# -------------------------------------------------------------------
# AI-Enhanced Suggestions (context-aware)
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def ai_suggestions_today(request):
    """
    Generate AI-powered suggestions for today's blocks.
    Query params: user, hostname
    """
    import re, time
    from difflib import SequenceMatcher

    user = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org = get_org_or_default(request)

    compact_rawevents_into_blocks(user=user, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if user:
        qs = qs.filter(user=user)
    if hostname:
        qs = qs.filter(hostname=hostname)
    if org:
        qs = qs.filter(org=org)

    blocks = list(qs)
    if not blocks:
        return Response([])

    # --------- Trim input size to keep prompts predictable ----------
    MAX_BLOCKS = 120  # plenty for a workday
    def _shorten(s: str, n: int = 180) -> str:
        s = (s or "").strip()
        return s[:n] + ("…" if len(s) > n else "")

    trimmed = []
    for b in blocks[:MAX_BLOCKS]:
        minutes = int((b.end - b.start).total_seconds() / 60) if b.end else 0
        trimmed.append({
            "id": str(b.id),
            "title": _shorten(b.title, 160),
            "window_title": _shorten(getattr(b, 'window_title', ''), 160),
            "url": _shorten(b.url, 140),
            "file_path": _shorten(b.file_path, 140),
            "minutes": minutes,
            "attendees": getattr(b, 'attendees', []) or [],
            "description": _shorten(getattr(b, 'description', ''), 220),
        })

    org_context = build_ai_context(org)
    prompt = build_classification_prompt(trimmed, org_context)

    # --------- OpenAI call with backoff + robust JSON parsing ----------
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return Response({"error": "OPENAI_API_KEY not configured"}, status=500)

    def _extract_json(s: str) -> str:
        """Strip fences and isolate JSON array/object best-effort."""
        s = s.strip()
        # ```json ... ``` or ``` ... ```
        if s.startswith("```"):
            parts = s.split("```")
            # take content between first and second fence if present
            if len(parts) >= 3:
                s = parts[1]
                if s.lower().startswith("json"):
                    s = s[4:].lstrip()
        # grab first JSON array if present
        m = re.search(r'\[\s*{', s)
        if m:
            start = m.start()
            # naive bracket matching to end of array
            depth, i = 0, start
            while i < len(s):
                if s[i] == '[':
                    depth += 1
                elif s[i] == ']':
                    depth -= 1
                    if depth == 0:
                        return s[start:i+1]
                i += 1
        # fallback: attempt to parse whole
        return s

    def _json_loads_loose(raw: str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # remove trailing commas in objects/arrays (loose fix)
            raw2 = re.sub(r',\s*([}\]])', r'\1', raw)
            return json.loads(raw2)

    # Backoff on rate limits/transients
    import openai
    openai.api_key = api_key
    system_msg = (
        "You are a time-tracking classifier. "
        "Use the organization context to map blocks to {client, project, categories(hours)} "
        "and set needs_review when unsure. Respond with ONLY JSON."
        "\n\n--- ORG CONTEXT ---\n" + (org_context or "None")
    )
    last_text = None
    for attempt, delay in [(1, 0.0), (2, 1.0), (3, 3.0)]:
        try:
            if delay:
                time.sleep(delay)
            resp = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=3800,
            )
            last_text = resp.choices[0].message.content.strip()
            raw_json = _extract_json(last_text)
            ai_suggestions = _json_loads_loose(raw_json)
            if not isinstance(ai_suggestions, list):
                raise ValueError("Model did not return a JSON array.")
            break
        except Exception as e:
            err = str(e)
            if attempt == 3:
                return Response({
                    "error": "AI extraction failed",
                    "details": err[:300],
                    "raw_response_head": (last_text or "")[:600],
                }, status=500)
    # --------- Shape output aligned with blocks order ----------
    out = []
    for i, b in enumerate(blocks[:len(ai_suggestions)]):
        sug = ai_suggestions[i] if i < len(ai_suggestions) else {}
        out.append({
            "block_id": b.id,
            "start": b.start,
            "end": b.end,
            "title": b.title,
            "ai_suggestion": {
                "client": sug.get("client"),
                "project": sug.get("project"),
                "categories": sug.get("categories", {}),
                "confidence": sug.get("confidence", 0.0),
                "needs_review": sug.get("needs_review", True),
                "reasoning": sug.get("reasoning", ""),
                "source": "ai_with_context",
            },
            "current_client": getattr(b.client, "name", None),
            "current_project": getattr(b.project, "name", None),
        })
    return Response(out)


# -------------------------------------------------------------------
# Timecard Generation + Management
# -------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def generate_timecard(request):
    """Generate AI-powered timecard for a specific date."""
    target_date_str = request.data.get('date')
    if target_date_str:
        try:
            target_date = date_type.fromisoformat(target_date_str)
        except ValueError:
            raise ValidationError({"date": "Invalid date format. Use YYYY-MM-DD"})
    else:
        target_date = timezone.now().date()

    user = request.data.get('user') or request.GET.get('user') or 'unknown'
    hostname = request.data.get('hostname') or request.GET.get('hostname') or 'unknown'
    org = get_org_or_default(request)

    # Get day window
    import datetime
    target_dt = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time.min))
    start_utc = _start_of_local_day_utc(target_dt)
    end_utc = start_utc + datetime.timedelta(days=1)

    qs = Block.objects.filter(start__gte=start_utc, start__lt=end_utc).order_by("start")
    if user and user != 'unknown':
        qs = qs.filter(user=user)
    if hostname and hostname != 'unknown':
        qs = qs.filter(hostname=hostname)
    if org:
        qs = qs.filter(org=org)

    blocks = list(qs)
    if not blocks:
        return Response({
            'date': target_date_str or str(target_date),
            'entries': [],
            'total_hours': 0,
            'entries_needing_review': 0,
            'message': 'No blocks found for this date'
        })

    # To AI
    blocks_data = []
    existing_assignments = {}
    for b in blocks:
        minutes = int((b.end - b.start).total_seconds() / 60)
        blocks_data.append({
            'id': b.id,
            'start': b.start.isoformat(),
            'end': b.end.isoformat(),
            'minutes': minutes,
            'title': b.title,
            'window_title': getattr(b, 'window_title', ''),
            'url': b.url or '',
            'file_path': b.file_path or '',
        })
        if b.client or b.project or b.task:
            existing_assignments[b.id] = {
                'client': getattr(b.client, 'name', None),
                'project': getattr(b.project, 'name', None),
                'task': getattr(b.task, 'name', None),
            }

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return Response({"error": "OPENAI_API_KEY not configured"}, status=500)

    generator = TimecardGenerator(api_key)
    try:
        timecard_entries = asyncio.run(
            generator.generate_timecard(
                blocks_data,
                date=str(target_date),
                existing_assignments=existing_assignments
            )
        )
    except Exception as e:
        import traceback
        return Response({"error": f"Timecard generation failed: {str(e)}", "traceback": traceback.format_exc()}, status=500)

    saved_entries = []
    needs_review_count = 0
    with transaction.atomic():
        # Remove only draft/pending for this user/date/org
        TimecardEntry.objects.filter(
            org=org, user=user, date=target_date, status__in=['draft', 'pending']
        ).delete()

        for entry in timecard_entries:
            client_obj = None
            if entry.client_name and entry.client_name != 'Unknown':
                client_obj, _ = Client.objects.get_or_create(
                    org=org, name=entry.client_name, defaults={'is_active': True}
                )
            t = TimecardEntry.objects.create(
                org=org,
                user=user,
                date=target_date,
                client=client_obj,
                total_hours=entry.total_hours,
                category_breakdown=entry.category_breakdown,
                activities_summary=entry.activities_summary,
                confidence_score=entry.confidence_score,
                needs_review=entry.needs_review,
                status='pending' if entry.needs_review else 'draft',
                block_ids=entry.block_ids or [],
            )
            if entry.needs_review:
                needs_review_count += 1
            saved_entries.append({
                'id': t.id,
                'client_name': entry.client_name,
                'project_name': entry.project_name,
                'total_hours': float(entry.total_hours),
                'category_breakdown': entry.category_breakdown,
                'activities_summary': entry.activities_summary,
                'confidence_score': entry.confidence_score,
                'needs_review': entry.needs_review,
                'status': t.status,
                'block_ids': entry.block_ids or [],
            })

    return Response({
        'date': str(target_date),
        'entries': saved_entries,
        'total_hours': sum(e['total_hours'] for e in saved_entries),
        'entries_needing_review': needs_review_count
    })


@api_view(["GET"])
@permission_classes([PermUI])
def list_timecards(request):
    """List timecard entries with optional filtering."""
    org = get_org_or_default(request)
    qs = TimecardEntry.objects.filter(org=org)

    if date_str := request.GET.get('date'):
        try:
            qs = qs.filter(date=date_type.fromisoformat(date_str))
        except ValueError:
            raise ValidationError({"date": "Invalid date format"})

    if start_str := request.GET.get('start_date'):
        try:
            qs = qs.filter(date__gte=date_type.fromisoformat(start_str))
        except ValueError:
            raise ValidationError({"start_date": "Invalid date format"})

    if end_str := request.GET.get('end_date'):
        try:
            qs = qs.filter(date__lte=date_type.fromisoformat(end_str))
        except ValueError:
            raise ValidationError({"end_date": "Invalid date format"})

    if status_filter := request.GET.get('status'):
        qs = qs.filter(status=status_filter)

    if user_filter := request.GET.get('user'):
        qs = qs.filter(user=user_filter)

    entries = [{
        'id': e.id,
        'date': e.date.isoformat(),
        'user': e.user,
        'client_name': e.client.name if e.client else 'Unknown',
        'project_name': e.project.name if e.project else None,
        'total_hours': float(e.total_hours),
        'category_breakdown': e.category_breakdown,
        'activities_summary': e.activities_summary,
        'confidence_score': e.confidence_score,
        'needs_review': e.needs_review,
        'status': e.status,
        'reviewed_at': e.reviewed_at.isoformat() if e.reviewed_at else None,
        'notes': e.notes,
        'block_ids': e.block_ids,
    } for e in qs]

    return Response(entries)


@api_view(["POST"])
@permission_classes([PermUI])
def approve_timecard(request, timecard_id: int):
    """Approve a timecard entry."""
    try:
        entry = TimecardEntry.objects.get(id=timecard_id)
    except TimecardEntry.DoesNotExist:
        raise NotFound("Timecard entry not found")
    entry.approve(request.data.get('notes', ''))
    return Response({
        'id': entry.id,
        'status': entry.status,
        'reviewed_at': entry.reviewed_at.isoformat(),
        'message': 'Timecard entry approved successfully'
    })


@api_view(["POST"])
@permission_classes([PermUI])
def reject_timecard(request, timecard_id: int):
    """Reject a timecard entry."""
    try:
        entry = TimecardEntry.objects.get(id=timecard_id)
    except TimecardEntry.DoesNotExist:
        raise NotFound("Timecard entry not found")
    reason = request.data.get('reason', '')
    if not reason:
        raise ValidationError({"reason": "Reason is required when rejecting"})
    entry.reject(reason)
    return Response({
        'id': entry.id,
        'status': entry.status,
        'reviewed_at': entry.reviewed_at.isoformat(),
        'message': 'Timecard entry rejected'
    })


@api_view(["GET"])
@permission_classes([PermUI])
def timecard_summary(request):
    """Summary statistics for timecards."""
    from django.db.models import Sum
    org = get_org_or_default(request)
    qs = TimecardEntry.objects.filter(org=org)

    if start_str := request.GET.get('start_date'):
        qs = qs.filter(date__gte=date_type.fromisoformat(start_str))
    if end_str := request.GET.get('end_date'):
        qs = qs.filter(date__lte=date_type.fromisoformat(end_str))
    if user_filter := request.GET.get('user'):
        qs = qs.filter(user=user_filter)

    by_client = qs.values('client__name').annotate(total=Sum('total_hours')).order_by('-total')
    by_status = {
        'approved': qs.filter(status='approved').aggregate(Sum('total_hours'))['total_hours__sum'] or 0,
        'pending': qs.filter(status='pending').aggregate(Sum('total_hours'))['total_hours__sum'] or 0,
        'draft': qs.filter(status='draft').aggregate(Sum('total_hours'))['total_hours__sum'] or 0,
        'rejected': qs.filter(status='rejected').aggregate(Sum('total_hours'))['total_hours__sum'] or 0,
    }

    return Response({
        'total_hours': qs.aggregate(Sum('total_hours'))['total_hours__sum'] or 0,
        'by_client': list(by_client),
        'by_status': by_status,
        'entries_count': qs.count(),
        'needs_review_count': qs.filter(needs_review=True, status='draft').count(),
    })


# -------------------------------------------------------------------
# Org Settings & Knowledge
# -------------------------------------------------------------------
@api_view(["GET", "PUT"])
@permission_classes([PermUI])
def organization_settings(request):
    """Get or update organization settings."""
    org = get_org_or_default(request)

    if request.method == "GET":
        try:
            s = OrganizationSettings.objects.get(org=org)
            return Response({
                "company_name": s.company_name,
                "industry": s.industry,
                "description": s.description,
                "internal_keywords": s.internal_keywords,
                "default_internal_project": s.default_internal_project,
                "custom_instructions": s.custom_instructions,
            })
        except OrganizationSettings.DoesNotExist:
            return Response({
                "company_name": "",
                "industry": "",
                "description": "",
                "internal_keywords": [],
                "default_internal_project": "",
                "custom_instructions": "",
            })

    s, _created = OrganizationSettings.objects.get_or_create(
        org=org,
        defaults={
            'company_name': '',
            'industry': '',
            'description': '',
            'internal_keywords': [],
            'default_internal_project': '',
            'custom_instructions': '',
        }
    )
    s.company_name = request.data.get('company_name', s.company_name)
    s.industry = request.data.get('industry', s.industry)
    s.description = request.data.get('description', s.description)
    s.internal_keywords = request.data.get('internal_keywords', s.internal_keywords)
    s.default_internal_project = request.data.get('default_internal_project', s.default_internal_project)
    s.custom_instructions = request.data.get('custom_instructions', s.custom_instructions)
    s.save()
    return Response({"message": "Settings updated successfully", "company_name": s.company_name})


@api_view(["GET", "POST"])
@permission_classes([PermUI])
def known_entities(request):
    """List or create known entities (clients, projects, categories)."""
    org = get_org_or_default(request)
    if request.method == "GET":
        entity_type = request.GET.get('entity_type')
        qs = KnownEntity.objects.filter(org=org)
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        return Response([{
            'id': e.id,
            'entity_type': e.entity_type,
            'name': e.name,
            'aliases': e.aliases,
            'description': e.description,
            'is_internal': e.is_internal,
            'confidence_boost': e.confidence_boost,
        } for e in qs])

    entity_type = request.data.get('entity_type')
    name = request.data.get('name')
    if not entity_type or not name:
        raise ValidationError({"error": "entity_type and name are required"})
    e = KnownEntity.objects.create(
        org=org,
        entity_type=entity_type,
        name=name,
        aliases=request.data.get('aliases', []),
        description=request.data.get('description', ''),
        is_internal=request.data.get('is_internal', False),
        confidence_boost=request.data.get('confidence_boost', 0.0),
    )
    return Response({'id': e.id, 'entity_type': e.entity_type, 'name': e.name, 'message': 'Entity created successfully'})


@api_view(["PUT", "DELETE"])
@permission_classes([PermUI])
def known_entity_detail(request, entity_id: int):
    """Update or delete a known entity."""
    org = get_org_or_default(request)
    try:
        e = KnownEntity.objects.get(id=entity_id, org=org)
    except KnownEntity.DoesNotExist:
        raise NotFound("Entity not found")

    if request.method == "PUT":
        e.name = request.data.get('name', e.name)
        e.aliases = request.data.get('aliases', e.aliases)
        e.description = request.data.get('description', e.description)
        e.is_internal = request.data.get('is_internal', e.is_internal)
        e.confidence_boost = request.data.get('confidence_boost', e.confidence_boost)
        e.save()
        return Response({'message': 'Entity updated successfully'})

    e.delete()
    return Response({'message': 'Entity deleted successfully'})


@api_view(["POST"])
@permission_classes([PermUI])
def save_training_example(request):
    """
    Save a training example when user corrects AI classification.
    Body:
      { text_content, correct_client_id?, correct_project_id?, correct_categories{}, original_prediction{} }
    """
    org = get_org_or_default(request)
    ex = AITrainingExample.objects.create(
        org=org,
        text_content=request.data.get('text_content', ''),
        correct_client_id=request.data.get('correct_client_id'),
        correct_project_id=request.data.get('correct_project_id'),
        correct_categories=request.data.get('correct_categories', {}),
        original_prediction=request.data.get('original_prediction', {}),
    )
    return Response({'id': ex.id, 'message': 'Training example saved'})


@api_view(["POST"])
@permission_classes([PermUI])
def save_block_classification(request, block_id: int):
    """
    When user saves/corrects a classification, persist it & learn.
    Body:
      { client_id?, project_id?, category_hours{}, original_prediction{} , notes? }
    """
    org = get_org_or_default(request)
    try:
        block = Block.objects.get(id=block_id, org=org)
    except Block.DoesNotExist:
        raise NotFound("Block not found")

    block.client_id = request.data.get('client_id')
    block.project_id = request.data.get('project_id')
    block.category_hours = request.data.get('category_hours', {})
    if 'notes' in request.data:
        block.notes = request.data['notes']
    block.save()

    AITrainingExample.objects.create(
        org=org,
        text_content=f"{block.title} - {getattr(block, 'description', '') or ''}",
        correct_client_id=block.client_id,
        correct_project_id=block.project_id,
        correct_categories=block.category_hours,
        original_prediction=request.data.get('original_prediction', {}),
    )
    return Response({'message': 'Classification saved and learned!'})


# -------------------------------------------------------------------
# Bulk import (clients/projects) for onboarding
# -------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([PermUI])
def import_clients_csv(request):
    """
    CSV columns supported:
      client (required), project (optional), active (optional true/false)
    """
    org = get_org_or_default(request)
    if 'file' not in request.FILES:
        raise ValidationError({"file": "Upload a CSV file with 'file' field."})

    f = request.FILES['file']
    try:
        text = f.read().decode('utf-8', errors='ignore')
    except Exception:
        text = f.read().decode('latin-1', errors='ignore')

    reader = csv.DictReader(io.StringIO(text))
    created = {"clients": 0, "projects": 0}
    for row in reader:
        cname = (row.get('client') or '').strip()
        if not cname:
            continue
        is_active = str(row.get('active', 'true')).lower() in ('1', 'true', 'yes', 'y')
        client, c_created = Client.objects.get_or_create(org=org, name=cname, defaults={'is_active': is_active})
        if c_created:
            created['clients'] += 1
        pname = (row.get('project') or '').strip()
        if pname:
            _, p_created = Project.objects.get_or_create(org=org, client=client, name=pname, defaults={'is_active': True})
            if p_created:
                created['projects'] += 1

    return Response({"message": "Import complete", **created})
