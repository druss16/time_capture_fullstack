# tracker/views.py
from __future__ import annotations

import csv
import io
import urllib.parse
from datetime import timedelta
from typing import Optional, List, Dict, Any

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
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

from .models import RawEvent, Block, Rule, Suggestion, Client, Project, Task
from .permissions import AgentKeyPermission
from .rules import apply_rules
from .serializers import RawEventSerializer

from datetime import timezone as dt_timezone


# ------------------------------------------------------------------------------------
# Config / constants
# ------------------------------------------------------------------------------------
BLOCK_PAD_MINUTES = 10
MIN_BLOCK_DURATION = 6          # minutes
BLOCK_GRANULARITY = 6           # round to 6-min increments

DEFAULT_USER = "unknown-user"
DEFAULT_HOST = "unknown-host"


# Toggle UI auth with a Django setting (default False for dev)
USE_AUTH = bool(getattr(settings, "USE_AUTH", False))
PermUI = IsAuthenticated if USE_AUTH else AllowAny

# ------------------------------------------------------------------------------------
# Utils
# ------------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------------
# Health
# ------------------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([AllowAny])
def ping(_request):
    return Response({"ok": True})

# ------------------------------------------------------------------------------------
# Agent ingestion
# ------------------------------------------------------------------------------------
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

@api_view(["POST"])
@permission_classes([AllowAny])            # dev/legacy open endpoint (lock down later)
@throttle_classes([AnonRateThrottle])
def ingest_raw_event(request):
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

# ------------------------------------------------------------------------------------
# Compactor: RawEvent -> Block (for TODAY only; compaction-on-read)
# ------------------------------------------------------------------------------------
@transaction.atomic
def compact_rawevents_into_blocks(user: Optional[str] = None, hostname: Optional[str] = None, org=None) -> int:
    start_utc = _start_of_local_day_utc()
    ev_qs = RawEvent.objects.filter(ts_utc__gte=start_utc).order_by("ts_utc")
    if user:
        ev_qs = ev_qs.filter(user=user)
    if hostname:
        ev_qs = ev_qs.filter(hostname=hostname)
    events: List[RawEvent] = list(ev_qs)

    # wipe today's blocks (scoped)
    blk_qs = Block.objects.filter(start__gte=start_utc)
    if hasattr(Block, "user") and user:
        blk_qs = blk_qs.filter(user=user)
    if hasattr(Block, "hostname") and hostname:
        blk_qs = blk_qs.filter(hostname=hostname)
    blk_qs.delete()

    created = 0
    pad = timedelta(minutes=BLOCK_PAD_MINUTES)
    current: Optional[Dict[str, Any]] = None

    def finalize_and_create(cur: Dict[str, Any]) -> int:
        dur = int((cur["end"] - cur["start"]).total_seconds() // 60)
        dur = max(MIN_BLOCK_DURATION, _round_up_minutes(dur, BLOCK_GRANULARITY))

        kwargs: Dict[str, Any] = dict(
            start=cur["start"],
            end=cur["end"],
            title=cur["title"],
            url=cur.get("url") or "",
            file_path=cur.get("file_path") or "",
        )

        # Always provide defaults if your Block has NOT NULL constraints
        if hasattr(Block, "user"):
            kwargs["user"] = (cur.get("user") or DEFAULT_USER)
        if hasattr(Block, "hostname"):
            kwargs["hostname"] = (cur.get("hostname") or DEFAULT_HOST)
        if hasattr(Block, "minutes"):
            kwargs["minutes"] = dur

        # Set org field if it exists on the Block model
        if any(f.name == "org" for f in Block._meta.fields):
            field = Block._meta.get_field("org")
            # If org is required but not provided, we need a default
            if not field.null:
                if org is None:
                    from django.contrib.auth.models import Group
                    # Try to get or create a default org
                    default_org, created = Group.objects.get_or_create(
                        name="default-org",
                        defaults={}
                    )
                    kwargs["org"] = default_org
                else:
                    kwargs["org"] = org
            else:
                # org is nullable, so None is fine
                kwargs["org"] = org

        Block.objects.create(**kwargs)
        return 1


    for e in events:
        lbl = _label_from_event(e)
        if current is None:
            u = user or getattr(e, "user", None) or DEFAULT_USER
            h = hostname or getattr(e, "hostname", None) or DEFAULT_HOST
            current = dict(
                start=e.ts_utc,
                end=e.ts_utc,
                title=lbl,
                url=e.url or "",
                file_path=e.file_path or "",
                user=u,
                hostname=h,
            )


        gap = e.ts_utc - current["end"]
        if gap <= pad and lbl == current["title"]:
            current["end"] = e.ts_utc
        else:
            created += finalize_and_create(current)
            u = user or getattr(e, "user", None) or DEFAULT_USER
            h = hostname or getattr(e, "hostname", None) or DEFAULT_HOST
            current = dict(
                start=e.ts_utc,
                end=e.ts_utc,
                title=lbl,
                url=e.url or "",
                file_path=e.file_path or "",
                user=u,
                hostname=h,
            )

    if current:
        created += finalize_and_create(current)

    return created


# ------------------------------------------------------------------------------------
# UI endpoints (compaction-on-read)
# ------------------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def blocks_today(request):
    """
    Compact RawEvents -> Blocks for today (scoped by ?user=&hostname=) and return Blocks.
    """
    user = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org = request.user.groups.first() if (USE_AUTH and request.user.is_authenticated) else None

    compact_rawevents_into_blocks(user=user, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if hasattr(Block, "user") and user:
        qs = qs.filter(user=user)
    if hasattr(Block, "hostname") and hostname:
        qs = qs.filter(hostname=hostname)

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
    """
    Recompute up to 3 rule-based suggestions per Block for today, after compaction.
    """
    user = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org = request.user.groups.first() if (USE_AUTH and request.user.is_authenticated) else None

    compact_rawevents_into_blocks(user=user, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if hasattr(Block, "user") and user:
        qs = qs.filter(user=user)
    if hasattr(Block, "hostname") and hostname:
        qs = qs.filter(hostname=hostname)

    rules = list(Rule.objects.filter(active=True, org=org)) if org else list(Rule.objects.filter(active=True))

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
    """
    block_id = request.data.get("block_id")
    if not block_id:
        raise ValidationError({"block_id": "Required."})
    try:
        b = Block.objects.select_related("org").get(id=block_id) if hasattr(Block, "org") \
            else Block.objects.get(id=block_id)
    except Block.DoesNotExist:
        raise NotFound("Block not found.")

    # Mutations
    get = request.data.get
    if (v := get("client")):
        b.client = Client.objects.get(org=b.org, name=v) if hasattr(b, "org") else Client.objects.get(name=v)
    if (v := get("project")):
        b.project = Project.objects.get(org=b.org, name=v) if hasattr(b, "org") else Project.objects.get(name=v)
    if (v := get("task")):
        b.task = Task.objects.get(org=b.org, name=v) if hasattr(b, "org") else Task.objects.get(name=v)
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
            org=b.org if hasattr(b, "org") else None,
            pattern=pattern,
            field=field,
            value_text=value_text,
            kind=get("kind") or "contains",
            active=True,
        )
    return Response({"ok": True})
