# views.py
from __future__ import annotations

import csv
import io
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Iterable, List, Optional, Tuple

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.timezone import localtime
from rest_framework import status
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from .models import (
    RawEvent,
    Block,
    Rule,
    Suggestion,
    Client,
    Project,
    Task,
)
from .permissions import AgentKeyPermission
from .rules import apply_rules
from .serializers import RawEventSerializer

# -------------------------------------------------------------------
# Constants / Settings
# -------------------------------------------------------------------

BLOCK_PAD_MINUTES = 10          # gap threshold to merge events
MIN_BLOCK_DURATION = 6          # minutes
BLOCK_GRANULARITY = 6           # round up to 6-minute increments

# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------

def _start_of_local_day_utc(dt: timezone.datetime | None = None) -> timezone.datetime:
    """
    Return today's start-of-day in *local* time, converted to UTC (aware).
    This lets us query UTC timestamps correctly for "today" in the user's TZ.
    """
    dt = dt or timezone.now()
    local = localtime(dt)
    sod_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return sod_local.astimezone(timezone.utc)

def _label_from_event(e: RawEvent) -> str:
    """
    Human-ish label preference: URL host → file name → window title → app name
    """
    if e.url:
        try:
            host = urllib.parse.urlparse(e.url).hostname or ""
            if host:
                return host
        except Exception:
            pass
    if e.file_path:
        # use os.path.basename without importing full os as _os
        return e.file_path.rstrip("/").split("/")[-1]
    if e.window_title:
        return e.window_title[:80]
    return e.app_name or "Unknown"

def _round_up_minutes(n: int, granularity: int) -> int:
    return n if n % granularity == 0 else n + (granularity - (n % granularity))

@dataclass
class BlockOut:
    start: timezone.datetime
    end: timezone.datetime
    duration_minutes: int
    label: str
    source_ids: List[int]
    user: Optional[str]
    hostname: Optional[str]

# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([AllowAny])
def ping(_request):
    return Response({"ok": True})

# -------------------------------------------------------------------
# Agent → RawEvent ingestion (two forms)
# 1) /api/raw-events (preferred): AgentKeyPermission, no cookies
# 2) /api/ingest-raw-event (legacy/dev): open POST for quick testing
# -------------------------------------------------------------------

class NoAuth(BaseAuthentication):
    """Explicitly disables session/csrf for this endpoint."""
    def authenticate(self, request):
        return None

@api_view(["POST"])
@authentication_classes([NoAuth])          # don't require cookies
@permission_classes([AgentKeyPermission])  # enforce Agent-Key header
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

    # Let DRF parse datetime strings for us; still normalize ts_utc if needed
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

@api_view(["POST"])
@permission_classes([AllowAny])            # dev convenience; lock down in prod
@throttle_classes([AnonRateThrottle])
def ingest_raw_event(request):
    """
    Dev/legacy endpoint mirroring `raw_events` but without AgentKeyPermission.
    Keep enabled only while you’re iterating locally.
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

# -------------------------------------------------------------------
# RawEvent → ad-hoc merged blocks for Today (useful for debugging)
# NOTE: This is *not* the canonical Block model; it's a quick merge view.
# -------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([UserRateThrottle])
def raw_blocks_today(request):
    """
    Merge RawEvents into coarse 'blocks' for today using:
      - same label (url host / file basename / window title / app name)
      - gap <= BLOCK_PAD_MINUTES
    Rounds duration to BLOCK_GRANULARITY with MIN_BLOCK_DURATION floor.
    Filters: ?user=...&hostname=...
    """
    user = request.GET.get("user")
    hostname = request.GET.get("hostname")

    start_utc = _start_of_local_day_utc()
    qs = RawEvent.objects.filter(ts_utc__gte=start_utc).order_by("ts_utc")
    if user:
        qs = qs.filter(user=user)
    if hostname:
        qs = qs.filter(hostname=hostname)

    events: List[RawEvent] = list(qs)
    blocks: List[BlockOut] = []
    current: Optional[BlockOut] = None
    pad = timezone.timedelta(minutes=BLOCK_PAD_MINUTES)

    for e in events:
        lbl = _label_from_event(e)
        if current is None:
            current = BlockOut(
                start=e.ts_utc,
                end=e.ts_utc,
                duration_minutes=0,
                label=lbl,
                source_ids=[e.id],
                user=e.user,
                hostname=e.hostname,
            )
            continue

        gap = e.ts_utc - current.end
        if gap <= pad and lbl == current.label:
            current.end = e.ts_utc
            current.source_ids.append(e.id)
        else:
            # finalize previous
            dur = max(
                MIN_BLOCK_DURATION,
                _round_up_minutes(int((current.end - current.start).total_seconds() // 60), BLOCK_GRANULARITY),
            )
            current.duration_minutes = dur
            blocks.append(current)
            # new current
            current = BlockOut(
                start=e.ts_utc,
                end=e.ts_utc,
                duration_minutes=0,
                label=lbl,
                source_ids=[e.id],
                user=e.user,
                hostname=e.hostname,
            )

    if current:
        dur = max(
            MIN_BLOCK_DURATION,
            _round_up_minutes(int((current.end - current.start).total_seconds() // 60), BLOCK_GRANULARITY),
        )
        current.duration_minutes = dur
        blocks.append(current)

    return Response([asdict(b) for b in blocks])

# -------------------------------------------------------------------
# Canonical Block model views (UI uses these)
# -------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([UserRateThrottle])
def blocks_today(request):
    """
    Return saved Block rows for *today* (already merged by your pipeline).
    """
    today = timezone.localdate()
    qs = Block.objects.filter(start__date=today).order_by("start")
    def _minutes(b: Block) -> int:
        return int((b.end - b.start).total_seconds() / 60)

    data = [
        {
            "id": b.id,
            "start": b.start,
            "end": b.end,
            "minutes": _minutes(b),
            "title": b.title,
            "url": b.url,
            "file_path": b.file_path,
            "client": getattr(b.client, "name", None),
            "project": getattr(b.project, "name", None),
            "task": getattr(b.task, "name", None),
            "notes": b.notes or "",
        }
        for b in qs
    ]
    return Response(data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([UserRateThrottle])
def suggestions_today(request):
    """
    Compute (or refresh) up to 3 rule-based suggestions for each Block today.
    For now this re-computes on each call; you can cron this if needed later.
    """
    org = request.user.groups.first() if request.user.is_authenticated else None
    today = timezone.localdate()
    blocks = list(Block.objects.filter(start__date=today).order_by("start"))

    rules = list(Rule.objects.filter(active=True, org=org)) if org else list(Rule.objects.filter(active=True))
    data = []

    # recompute suggestions in a single transaction per request
    with transaction.atomic():
        for b in blocks:
            Suggestion.objects.filter(block=b).delete()
            computed = list(apply_rules(b, rules))[:3]
            for field, value_text, conf in computed:
                Suggestion.objects.create(
                    block=b,
                    label_type=field,
                    value_text=value_text,
                    confidence=conf,
                    source="rule",
                )
            data.append(
                {
                    "id": b.id,
                    "start": b.start,
                    "end": b.end,
                    "minutes": int((b.end - b.start).total_seconds() / 60),
                    "title": b.title,
                    "url": b.url,
                    "file_path": b.file_path,
                    "client": getattr(b.client, "name", None),
                    "project": getattr(b.project, "name", None),
                    "task": getattr(b.task, "name", None),
                    "suggestions": [
                        {
                            "label_type": s.label_type,
                            "value_text": s.value_text,
                            "confidence": s.confidence,
                        }
                        for s in b.suggestions.all().order_by("-confidence")[:3]
                    ],
                }
            )

    return Response(data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def label_block(request):
    """
    Apply labels to a Block and (optionally) create a rule from the confirmation.
    Body:
      - block_id (required)
      - client/project/task (names; optional)
      - notes (optional)
      - create_rule (bool; optional)
      - create_rule_field ('client'|'project'|'task'; required if create_rule)
      - create_rule_value (str; required if create_rule)
      - pattern (optional; defaults to b.url or b.file_path or b.title[:200])
      - kind (optional; default 'contains')
    """
    block_id = request.data.get("block_id")
    if not block_id:
        raise ValidationError({"block_id": "Required."})

    try:
        b = Block.objects.select_related("org").get(id=block_id)
    except Block.DoesNotExist:
        raise NotFound("Block not found.")

    # Mutations
    name = request.data.get

    if (v := name("client")):
        b.client = Client.objects.get(org=b.org, name=v)
    if (v := name("project")):
        b.project = Project.objects.get(org=b.org, name=v)
    if (v := name("task")):
        b.task = Task.objects.get(org=b.org, name=v)
    if (v := name("notes")) is not None:
        b.notes = v

    b.save()

    if request.data.get("create_rule"):
        field = name("create_rule_field")
        value_text = name("create_rule_value")
        if field not in {"client", "project", "task"}:
            raise ValidationError({"create_rule_field": "Must be 'client'|'project'|'task'."})
        if not value_text:
            raise ValidationError({"create_rule_value": "Required when create_rule is true."})

        Rule.objects.create(
            org=b.org,
            pattern=name("pattern") or (b.url or b.file_path or (b.title or ""))[:200],
            field=field,
            value_text=value_text,
            kind=name("kind") or "contains",
            active=True,
        )

    return Response({"ok": True})

# -------------------------------------------------------------------
# CSV export for today's Blocks (useful for Daily Review / export button)
# -------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_blocks_today_csv(_request):
    """
    CSV export of today's Block rows.
    Columns: start,end,minutes,title,url,file_path,client,project,task,notes
    """
    today = timezone.localdate()
    qs = Block.objects.filter(start__date=today).order_by("start")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["start", "end", "minutes", "title", "url", "file_path", "client", "project", "task", "notes"])

    for b in qs:
        minutes = int((b.end - b.start).total_seconds() / 60)
        writer.writerow(
            [
                b.start.isoformat(),
                b.end.isoformat(),
                minutes,
                (b.title or "").replace("\n", " ").strip(),
                b.url or "",
                b.file_path or "",
                getattr(b.client, "name", "") or "",
                getattr(b.project, "name", "") or "",
                getattr(b.task, "name", "") or "",
                (b.notes or "").replace("\n", " ").strip(),
            ]
        )

    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="blocks_today.csv"'
    return resp
