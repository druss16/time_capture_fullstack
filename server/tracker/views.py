# tracker/views.py
from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.parse
import asyncio
from datetime import timedelta, date as date_type, timezone as dt_timezone, datetime, time as dt_time
from typing import Optional, List, Dict, Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
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

from openai import OpenAI

from .models import (
    RawEvent, Block, Rule, Suggestion, Client, Project, Task,
    OrganizationSettings, KnownEntity, AITrainingExample, TimecardEntry,
    AgentControl, AgentSession
)
# tracker/views.py
from .permissions import PermUI, AgentKeyPermission, NoAuth
from .rules import apply_rules
from .serializers import RawEventSerializer

from .utils import resolve_agent_user  # <— add this import

# views.py
from datetime import datetime, time as dt_time, timedelta, date as date_type
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from .permissions import PermUI
from .models import Block
from .utils import get_org_or_default, resolve_client_from_known, infer_task_for_block, compact_rawevents_into_blocks
from django.contrib.auth import get_user_model

from datetime import datetime, timedelta, time as dt_time, timezone as dt_timezone
from django.utils import timezone
from datetime import date, datetime, timedelta, time as dt_time, timezone as dt_timezone
from django.utils import timezone
from django.db.models.functions import TruncHour

from .utils import (
    get_org_or_default,
    resolve_client_from_known,
    infer_task_for_block,
    compact_rawevents_into_blocks,
)

# tracker/views.py
import datetime
from datetime import timedelta, time as dt_time
from django.utils import timezone
from django.db.models import Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Block
from .services.classify_block import classify_block

# --- helper: resolve which user to show in the day summary ---
from django.contrib.auth import get_user_model
User = get_user_model()



# -------------------------------------------------------------------
# Config / constants
# -------------------------------------------------------------------
BLOCK_PAD_MINUTES = 10
MIN_BLOCK_DURATION = 6          # minutes
BLOCK_GRANULARITY = 6           # round to 6-min increments

USE_AUTH = bool(getattr(settings, "USE_AUTH", False))
PermUI = IsAuthenticated if USE_AUTH else AllowAny

IDLE_STICKY_MINUTES = int(getattr(settings, "IDLE_STICKY_MINUTES", 4))
FUZZY_HOST_MATCH = True
FUZZY_TITLE_THRESHOLD = float(getattr(settings, "FUZZY_TITLE_THRESHOLD", 0.72))

MAX_NAME_LEN = 120


# -------------------------------------------------------------------
# Utility helpers
# -------------------------------------------------------------------
def get_org_or_default(request):
    """Get org from user or a default dev org."""
    if USE_AUTH and getattr(request, "user", None) and request.user.is_authenticated:
        org = request.user.groups.first()
    else:
        org = None
    if not org:
        org, _ = Group.objects.get_or_create(name="default-org")
    return org


def _get_user_obj(username: Optional[str]):
    if not username:
        return None
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        return None


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


def _client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else "") or request.META.get("REMOTE_ADDR", "")


def _round_up_minutes(n: int, granularity: int) -> int:
    return n if n % granularity == 0 else n + (granularity - (n % granularity))


def build_classification_prompt(text_blocks: list, org_context: str) -> str:
    """Context-aware AI prompt for block classification."""
    return f"""You are a time-tracking AI assistant. Your job is to classify computer activity blocks into client work, projects, and time categories.


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


def build_ai_context(org) -> str:
    """Build org-specific context to improve AI accuracy."""
    try:
        settings_obj = OrganizationSettings.objects.get(org=org)
    except OrganizationSettings.DoesNotExist:
        settings_obj = None

    parts = []
    if settings_obj and settings_obj.company_name:
        parts.append(f"COMPANY: {settings_obj.company_name}")
        if settings_obj.description:
            parts.append(f"DESCRIPTION: {settings_obj.description}")

    clients = KnownEntity.objects.filter(org=org, entity_type='client')
    if clients.exists():
        rows = []
        for c in clients:
            aliases = f" (aka: {', '.join(c.aliases)})" if c.aliases else ""
            internal = " [INTERNAL]" if c.is_internal else ""
            rows.append(f"  - {c.name}{aliases}{internal}")
        parts.append("KNOWN CLIENTS:\n" + "\n".join(rows))

    if settings_obj and settings_obj.internal_keywords:
        parts.append(f"INTERNAL WORK INDICATORS: {', '.join(settings_obj.internal_keywords)}")
        if settings_obj.default_internal_project:
            parts.append(f"DEFAULT INTERNAL PROJECT: {settings_obj.default_internal_project}")

    if settings_obj and settings_obj.custom_instructions:
        parts.append(f"SPECIAL INSTRUCTIONS:\n{settings_obj.custom_instructions}")

    recent = AITrainingExample.objects.filter(org=org).order_by('-created_at')[:5]
    if recent.exists():
        rows = []
        for ex in recent:
            cname = ex.correct_client.name if ex.correct_client else "N/A"
            rows.append(f'  - "{ex.text_content[:60]}..." → {cname}')
        parts.append("RECENT CORRECTIONS:\n" + "\n".join(rows))

    return "\n\n".join(parts)


# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([AllowAny])
def ping(_request):
    return Response({"ok": True})


# -------------------------------------------------------------------
# Agent handshake, control, and ingest
# -------------------------------------------------------------------
class NoAuth(BaseAuthentication):
    """Disable session/csrf for token/agent endpoints."""
    def authenticate(self, request):
        return None


# views.py (DRF)
from django.utils import timezone
from django.contrib.auth.models import User, Group
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import json

@api_view(["POST"])
@permission_classes([AllowAny])
def agents_hello(request):
    """
    Auto-provision user and upsert AgentSession.
    Tolerates partial schemas by only touching fields that exist on AgentSession.
    Also sets cookies so the SPA can show the username without login.
    """
    # ---- Gather inputs (headers first, JSON fallback) ----
    username = (request.headers.get("X-Agent-User") or "").strip()
    host     = (request.headers.get("X-Agent-Host") or "").strip()
    plat     = (request.headers.get("X-Agent-Platform") or "").strip()
    ver      = (request.headers.get("X-Agent-Version") or "").strip()

    if not (username and host):
        body = {}
        try:
            body = request.data if isinstance(request.data, dict) else json.loads(request.body.decode("utf-8"))
        except Exception:
            body = {}
        username = username or (body.get("user") or body.get("os_username") or "").strip()
        host     = host or (body.get("hostname") or body.get("machine") or "").strip()
        plat     = plat or (body.get("platform") or "").strip()
        ver      = ver or (body.get("app_version") or body.get("version") or "").strip()

    username = username or "unknown"
    host     = host or "unknown"
    cip      = _client_ip(request)

    # ---- Ensure group & user ----
    grp, _ = Group.objects.get_or_create(name="Time Agents")
    user, created = User.objects.get_or_create(username=username, defaults={"is_active": True, "email": ""})
    if created:
        user.set_unusable_password()
        user.save()
    if not user.groups.filter(id=grp.id).exists():
        user.groups.add(grp)

    # ---- Build safe filter/defaults for AgentSession ----
    sess_fields = {f.name for f in AgentSession._meta.get_fields()}

    filter_kwargs = {"user": user}
    if "hostname" in sess_fields:
        filter_kwargs["hostname"] = host

    defaults = {}
    if "last_seen" in sess_fields:
        defaults["last_seen"] = timezone.now()
    if "platform" in sess_fields and plat:
        defaults["platform"] = plat
    if "version" in sess_fields and ver:
        defaults["version"] = ver
    if "last_ip" in sess_fields and cip:
        defaults["last_ip"] = cip
    # If hostname is a field but not in filter (in case your unique key is just user),
    # add to defaults so we keep it current:
    if "hostname" in sess_fields and "hostname" not in filter_kwargs:
        defaults["hostname"] = host

    AgentSession.objects.update_or_create(**filter_kwargs, defaults=defaults)

    # ---- Ensure AgentControl row (schema tolerant) ----
    try:
        AgentControl.objects.get_or_create(user=user, host=host)
    except Exception:
        # If your AgentControl uses different field names, ignore gently.
        pass

    # ---- Response + cookies for SPA ----
    resp = Response({
        "ok": True,
        "user_id": user.id,
        "username": user.username,
        "host": host,
        # If AgentControl exists with (user, host), return flags if available:
        "stop": False,
        "stop_until": None,
    })
    # Cookies used by /api/whoami/ (so your frontend can show the username)
    resp.set_cookie("mavops_username", user.username, samesite="Lax")
    resp.set_cookie("mavops_host", host, samesite="Lax")
    return resp

@api_view(["GET"])
@permission_classes([AllowAny])
def agent_control(request):
    """
    GET ?user=<username>&host=<host>
    Returns { stop, reason, stop_until }
    """
    username = (request.GET.get("user") or "").strip()
    host = (request.GET.get("host") or "").strip()

    stop, reason, stop_until = False, "", None
    if username and host:
        try:
            u = User.objects.get(username=username)
            ac = AgentControl.objects.filter(user=u, host=host).first()
            if ac:
                if ac.stop_until and ac.stop_until <= timezone.now():
                    stop = False
                else:
                    stop = ac.stop
                reason = ac.reason
                stop_until = ac.stop_until
        except User.DoesNotExist:
            pass

    return Response({
        "stop": stop,
        "reason": reason,
        "stop_until": stop_until.isoformat() if stop_until else None
    })



@api_view(["POST"])
@authentication_classes([NoAuth])          # no cookies/csrf
@permission_classes([AgentKeyPermission])  # require X-Agent-Key
@throttle_classes([AnonRateThrottle])
def raw_events(request):

    # DEBUG: comment out after you confirm
    # if settings.DEBUG:
    #     print("----- /api/raw-events/ DEBUG -----")
    #     print("Headers seen by server:")
    #     for k, v in request.headers.items():
    #         if "agent" in k.lower() or k.lower() == "authorization":
    #             print(f"  {k}: {v!r}")
    #     print("Query key:", request.query_params.get("key"))
    #     print("----------------------------------")
    """
    Ingest one or many RawEvent objects.
    - Accepts dict or list[dict].
    - ts_utc may be ISO string or datetime.
    - user is derived from headers via resolve_agent_user() -> FK.
    - hostname comes from header (X-Agent-Host) or item['hostname'] or 'unknown'.
    """
    # Resolve the authenticated Django user for attribution
    agent_user = resolve_agent_user(request)

    payload = request.data
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValidationError("Payload must be an object or an array of objects.")

    header_host = (request.headers.get("X-Agent-Host") or "").strip() or "unknown"

    created, errors = 0, []
    for item in payload:
        # Parse timestamp
        ts = item.get("ts_utc")
        if isinstance(ts, str):
            dt = parse_datetime(ts)
            if dt is None:
                errors.append({"item": item, "error": "Invalid ts_utc"})
                continue
            item["ts_utc"] = dt
        elif not ts:
            errors.append({"item": item, "error": "Missing ts_utc"})
            continue

        # Hostname preference: header > item > 'unknown'
        hostname = (header_host or item.get("hostname") or "unknown").strip() or "unknown"

        try:
            RawEvent.objects.create(
                ts_utc=item["ts_utc"],
                app_name=item.get("app_name"),
                bundle_id=item.get("bundle_id"),
                window_title=item.get("window_title") or "",
                url=item.get("url"),
                file_path=item.get("file_path"),
                user=agent_user,                 # FK from resolve_agent_user
                hostname=hostname,
                ctx=item.get("ctx", {}) or {},
            )
            created += 1
        except Exception as e:
            errors.append({"item": item, "error": str(e)})

    status_code = status.HTTP_201_CREATED if created and not errors else (
        status.HTTP_207_MULTI_STATUS if created and errors else status.HTTP_400_BAD_REQUEST
    )
    return Response({"created": created, "errors": errors}, status=status_code)


# -------------------------------------------------------------------
# Compactor: RawEvent -> Block (for TODAY only; compaction-on-read)
# -------------------------------------------------------------------
def _merge_ctx(cur: dict, e: RawEvent):
    """Fold RawEvent.ctx into rolling block dict."""
    ctx = getattr(e, "ctx", None) or {}
    if not isinstance(ctx, dict):
        return

    cur.setdefault("hints", {})

    # Browser context
    b = ctx.get("browser") or {}
    if isinstance(b, dict):
        if b.get("origin"):      cur["hints"]["browser_origin"]   = b["origin"]
        if b.get("pathname"):    cur["hints"]["browser_pathname"] = b["pathname"]
        if b.get("jira_key"):    cur["hints"]["jira_key"]         = b["jira_key"]
        if b.get("github_repo"): cur["hints"]["github_repo"]      = b["github_repo"]
        if b.get("github_pr"):   cur["hints"]["github_pr"]        = b["github_pr"]

    # VS Code context
    v = ctx.get("vscode") or {}
    if isinstance(v, dict):
        if v.get("repo_root"):  cur["hints"]["repo_root"]  = v["repo_root"]
        if v.get("workspace"):  cur["hints"]["workspace"]  = v["workspace"]
        if v.get("rel_file"):   cur["hints"]["rel_file"]   = v["rel_file"]
        if v.get("branch"):     cur["hints"]["branch"]     = v["branch"]
        if v.get("remote"):     cur["hints"]["remote"]     = v["remote"]

    # Shell context
    s = ctx.get("shell") or {}
    if isinstance(s, dict):
        if s.get("pwd"):        cur["hints"]["pwd"]        = s["pwd"]
        if s.get("branch"):     cur["hints"]["branch"]     = s["branch"]


@transaction.atomic
def compact_rawevents_into_blocks(user: Optional[str] = None, hostname: Optional[str] = None, org=None) -> int:
    """
    Compacts today's RawEvents into Block rows with merging & rounding.
    `user` may be a username or a User instance; we normalize to FK.
    """
    start_utc = _start_of_local_day_utc()

    user_obj = user if isinstance(user, User) else _get_user_obj(user)

    ev_qs = RawEvent.objects.filter(ts_utc__gte=start_utc).order_by("ts_utc")
    if user_obj:
        ev_qs = ev_qs.filter(user=user_obj)
    if hostname:
        ev_qs = ev_qs.filter(hostname=hostname)
    events: List[RawEvent] = list(ev_qs)

    # wipe today's scope
    blk_qs = Block.objects.filter(start__gte=start_utc)
    if user_obj:
        blk_qs = blk_qs.filter(user=user_obj)
    if hostname:
        blk_qs = blk_qs.filter(hostname=hostname)
    blk_qs.delete()

    created = 0
    pad = timedelta(minutes=BLOCK_PAD_MINUTES)
    sticky_delta = timedelta(minutes=IDLE_STICKY_MINUTES)

    current: Optional[Dict[str, Any]] = None

    def _duration_minutes(cur: Dict[str, Any]) -> int:
        return int((cur["end"] - cur["start"]).total_seconds() // 60)

    def _finalize_and_create(cur: Dict[str, Any], org_val) -> int:
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
            kwargs["user"] = cur.get("user") or user_obj
        if hasattr(Block, "hostname"):
            kwargs["hostname"] = cur.get("hostname") or ""
        if hasattr(Block, "minutes"):
            kwargs["minutes"] = int((kwargs["end"] - kwargs["start"]).total_seconds() // 60)

        if hasattr(Block, "hints") and isinstance(cur.get("hints"), dict):
            kwargs["hints"] = cur.get("hints")

        # org handling
        if any(f.name == "org" for f in Block._meta.fields):
            field = Block._meta.get_field("org")
            if not field.null:
                if org_val is None:
                    org_val, _ = Group.objects.get_or_create(name="default-org")
                kwargs["org"] = org_val
            else:
                kwargs["org"] = org_val

        Block.objects.create(**kwargs)
        return 1

    def _same_activity(prev: Dict[str, Any], new_title: str, new_url: str) -> bool:
        if new_title == prev["title"]:
            return True
        if FUZZY_HOST_MATCH:
            prev_host = _host(prev.get("url", "")) if prev.get("url") else ""
            new_host = _host(new_url or "")
            if prev_host and (prev_host == new_host):
                if _similar(prev["title"], new_title) >= FUZZY_TITLE_THRESHOLD:
                    return True
        return False

    for e in events:
        lbl = _label_from_event(e)
        u_fk = e.user  # FK
        h = hostname or getattr(e, "hostname", None) or ""
        et = e.ts_utc
        url = e.url or ""
        fpath = e.file_path or ""
        wtitle = getattr(e, "window_title", "") or ""

        if current is None:
            current = dict(
                start=et, end=et, title=lbl, window_title=wtitle,
                url=url, file_path=fpath, user=u_fk, hostname=h,
            )
            _merge_ctx(current, e)
            continue

        gap = et - current["end"]

        if gap <= pad and _same_activity(current, lbl, url):
            if timedelta(0) < gap <= sticky_delta:
                current["end"] += gap  # attribute idle to current
            current["end"] = et
            _merge_ctx(current, e)
        else:
            created += _finalize_and_create(current, org)
            current = dict(
                start=et, end=et, title=lbl, window_title=wtitle,
                url=url, file_path=fpath, user=u_fk, hostname=h,
            )
            _merge_ctx(current, e)

    if current:
        created += _finalize_and_create(current, org)

    return created


# -------------------------------------------------------------------
# UI endpoints (compaction-on-read)
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def blocks_today(request):
    """Compact RawEvents -> Blocks for today and return display-ready blocks."""
    username = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org = get_org_or_default(request)

    compact_rawevents_into_blocks(user=username, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if username:
        qs = qs.filter(user__username=username)  # FK filter
    if hostname:
        qs = qs.filter(hostname=hostname)
    if org:
        qs = qs.filter(org=org)

    def minutes(b: Block) -> int:
        if hasattr(b, "minutes") and b.minutes is not None:
            return int(b.minutes)
        return int((b.end - b.start).total_seconds() / 60)

    data = []
    for b in qs.select_related("client", "project", "task", "user"):
        data.append({
            "id": b.id,
            "start": b.start,
            "end": b.end,
            "minutes": minutes(b),
            "title": b.title,
            "window_title": getattr(b, "window_title", "") or "",
            "url": b.url or "",
            "file_path": b.file_path or "",
            "description": getattr(b, "description", "") or "",
            "attendees": getattr(b, "attendees", []) or [],
            "hints": getattr(b, "hints", {}) or {},
            "client_name": getattr(b.client, "name", None),
            "project_name": getattr(b.project, "name", None),
            "task_name": getattr(b.task, "name", None),
            "notes": getattr(b, "notes", "") or "",
            "user": b.user.username if b.user_id else None,
            "hostname": b.hostname,
        })
    return Response(data)


@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def suggestions_today(request):
    """Recompute up to 3 rule-based suggestions per Block for today, after compaction."""
    username = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org = get_org_or_default(request)

    compact_rawevents_into_blocks(user=username, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if username:
        qs = qs.filter(user__username=username)
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
                "url": b.url or "",
                "file_path": b.file_path or "",
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
@transaction.atomic
def label_block(request):
    """
    Save labels directly by block_id (in body).
    """
    body = request.data or {}
    block_id = body.get("block_id")
    if not block_id:
        raise ValidationError({"block_id": "Required."})

    b = get_object_or_404(Block, id=block_id)
    org = getattr(b, "org", None) or get_org_or_default(request)

    client_name  = (body.get("client")  or "").strip() or None
    project_name = (body.get("project") or "").strip() or None
    task_name    = (body.get("task")    or "").strip() or None
    notes        = body.get("notes", None)
    categories   = _sanitize_categories(body.get("categories"))

    # upsert client/project/task
    client_obj = None
    if client_name:
        client_obj, _ = Client.objects.get_or_create(org=org, name=client_name)
        b.client = client_obj

    proj_obj = getattr(b, "project", None)
    if project_name:
        if client_obj is None:
            client_obj, _ = Client.objects.get_or_create(org=org, name="(General)")
            b.client = client_obj
        proj_obj, _ = Project.objects.get_or_create(org=org, client=client_obj, name=project_name)
        b.project = proj_obj

    if task_name:
        if proj_obj is None:
            if client_obj is None:
                client_obj, _ = Client.objects.get_or_create(org=org, name="(General)")
                b.client = client_obj
            proj_obj, _ = Project.objects.get_or_create(org=org, client=client_obj, name="(General)")
            b.project = proj_obj
        task_obj, _ = Task.objects.get_or_create(org=org, project=proj_obj, name=task_name)
        b.task = task_obj

    if categories:
        b.category_hours = categories
    if notes is not None:
        b.notes = str(notes)

    b.save()

    # optional rule creation
    if body.get("create_rule"):
        field = body.get("create_rule_field")
        value_text = body.get("create_rule_value")
        if field not in {"client", "project", "task"}:
            raise ValidationError({"create_rule_field": "Must be 'client'|'project'|'task'."})
        if not value_text:
            raise ValidationError({"create_rule_value": "Required when create_rule is true."})
        pattern = body.get("pattern") or (b.url or b.file_path or (b.title or ""))[:200]
        Rule.objects.create(
            org=org,
            pattern=pattern,
            field=field,
            value_text=value_text,
            kind=body.get("kind") or "contains",
            active=True,
        )

    return Response({
        "ok": True,
        "block_id": b.id,
        "client": getattr(b.client, "name", None),
        "project": getattr(b.project, "name", None),
        "task": getattr(b.task, "name", None),
        "categories": getattr(b, "category_hours", {}),
    })


# -------------------------------------------------------------------
# AI-Enhanced Suggestions (context-aware)
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def ai_suggestions_today(request):
    """
    Generate AI-powered suggestions for today's blocks.
    """
    # toggles
    username = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    limit = int(request.GET.get("limit") or 120)
    limit = max(1, min(limit, 200))
    timeout_ms = int(request.GET.get("timeout_ms") or 12000)
    noai = request.GET.get("noai") in ("1", "true", "yes")
    fallback_mode = request.GET.get("fallback") or ""  # "", "rule"
    debug = request.GET.get("debug") in ("1", "true", "yes")

    org = get_org_or_default(request)

    # Build/refresh today's blocks
    compact_rawevents_into_blocks(user=username, hostname=hostname, org=org)

    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if username:
        qs = qs.filter(user__username=username)
    if hostname:
        qs = qs.filter(hostname=hostname)
    if org:
        qs = qs.filter(org=org)

    blocks = list(qs)
    if not blocks:
        return Response([])

    # trim payload
    def _shorten(s: str, n: int = 180) -> str:
        s = (s or "").strip()
        return s[:n] + ("…" if len(s) > n else "")

    MAX_BLOCKS = limit
    trimmed = []
    for b in blocks[:MAX_BLOCKS]:
        minutes = int((b.end - b.start).total_seconds() / 60) if b.end else 0
        hints = getattr(b, "hints", {}) or {}
        trimmed.append({
            "id": str(b.id),
            "title": _shorten(b.title, 160),
            "window_title": _shorten(getattr(b, 'window_title', ''), 160),
            "url": _shorten(b.url, 140),
            "file_path": _shorten(b.file_path, 140),
            "minutes": minutes,
            "attendees": getattr(b, 'attendees', []) or [],
            "description": _shorten(getattr(b, 'description', ''), 220),
            "hints": hints,
        })

    org_context = build_ai_context(org) or ""

    if debug:
        return Response({
            "debug": True,
            "count": len(trimmed),
            "sample": trimmed[:5],
            "org_context": org_context[:1200] if org_context else "",
        })

    if noai:
        out = []
        for b in blocks[:len(trimmed)]:
            out.append({
                "block_id": b.id,
                "start": b.start,
                "end": b.end,
                "title": b.title,
                "ai_suggestion": {
                    "client": None,
                    "project": None,
                    "categories": {},
                    "confidence": 0.0,
                    "needs_review": True,
                    "reasoning": "NOAI mode",
                    "source": "noai",
                },
                "current_client": getattr(b.client, "name", None),
                "current_project": getattr(b.project, "name", None),
            })
        return Response(out)

    # OpenAI call
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return Response({"error": "OPENAI_API_KEY not configured"}, status=500)

    prompt = build_classification_prompt(trimmed, org_context)

    def _extract_json(s: str) -> str:
        s = s.strip()
        if s.startswith("```"):
            parts = s.split("```")
            if len(parts) >= 3:
                s = parts[1]
                if s.lower().startswith("json"):
                    s = s[4:].lstrip()
        m = re.search(r'\[\s*{', s)
        if m:
            start = m.start()
            depth, i = 0, start
            while i < len(s):
                if s[i] == '[': depth += 1
                elif s[i] == ']':
                    depth -= 1
                    if depth == 0:
                        return s[start:i+1]
                i += 1
        return s

    def _json_loads_loose(raw: str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raw2 = re.sub(r',\s*([}\]])', r'\1', raw)
            return json.loads(raw2)

    client = OpenAI(api_key=api_key, timeout=timeout_ms / 1000.0)

    system_msg = (
        "You are a time-tracking classifier. "
        "Use the organization context and each block's hints "
        "(browser_origin, pathname, repo_root, jira_key, github_repo, etc.) "
        "to map blocks to {client, project, categories(hours)}. "
        "If unsure, set needs_review=true. "
        "Return ONLY a JSON array matching the order of provided blocks. "
        "Include fields: client, project, categories, confidence, needs_review, reasoning."
        "\n\n--- ORG CONTEXT ---\n" + org_context
    )

    last_text = None
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=3500,
        )
        last_text = (resp.choices[0].message.content or "").strip()
        raw_json = _extract_json(last_text)
        ai_suggestions = _json_loads_loose(raw_json)
        if not isinstance(ai_suggestions, list):
            raise ValueError("Model did not return a JSON array.")
    except Exception as e:
        if fallback_mode == "rule":
            return suggestions_today(request)
        out = []
        for b in blocks[:len(trimmed)]:
            out.append({
                "block_id": b.id,
                "start": b.start,
                "end": b.end,
                "title": b.title,
                "ai_suggestion": {
                    "client": None,
                    "project": None,
                    "categories": {},
                    "confidence": 0.0,
                    "needs_review": True,
                    "reasoning": f"AI fallback: {str(e)[:120]}",
                    "source": "fallback",
                },
                "current_client": getattr(b.client, "name", None),
                "current_project": getattr(b.project, "name", None),
            })
        return Response(out, status=200)

    out = []
    N = min(len(blocks), len(ai_suggestions))
    for i in range(N):
        b = blocks[i]
        sug = ai_suggestions[i] if isinstance(ai_suggestions[i], dict) else {}
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


@api_view(["POST"])
@permission_classes([AllowAny])
def reclassify_day(request):
    """
    Manually trigger AI reclassification for all blocks in a given date.
    """
    from tracker.tasks import classify_block_task

    date_str = (request.data.get("date") or "").strip()
    if not date_str:
        return Response({"error": "date is required"}, status=400)
    try:
        day = datetime.date.fromisoformat(date_str)
    except ValueError:
        return Response({"error": "invalid date"}, status=400)

    qs = Block.objects.filter(day=day)
    for b in qs:
        classify_block_task.delay(b.pk)

    return Response({"ok": True, "reclassified": qs.count()})


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

    username = request.data.get('user') or request.GET.get('user') or None
    hostname = request.data.get('hostname') or request.GET.get('hostname') or None
    org = get_org_or_default(request)

    user_obj = _get_user_obj(username)

    target_dt = timezone.make_aware(datetime.combine(target_date, dt_time.min))
    start_utc = _start_of_local_day_utc(target_dt)
    end_utc = start_utc + timedelta(days=1)

    qs = Block.objects.filter(start__gte=start_utc, start__lt=end_utc).order_by("start")
    if user_obj:
        qs = qs.filter(user=user_obj)
    if hostname:
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

    from .ai_timecard_service_adapted import TimecardGenerator
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
        # remove drafts/pending for same day/user
        TimecardEntry.objects.filter(
            org=org, user=user_obj, date=target_date, status__in=['draft', 'pending']
        ).delete()

        for entry in timecard_entries:
            client_obj = None
            if entry.client_name and entry.client_name != 'Unknown':
                client_obj, _ = Client.objects.get_or_create(
                    org=org, name=entry.client_name, defaults={'is_active': True}
                )
            t = TimecardEntry.objects.create(
                org=org,
                user=user_obj,
                date=target_date,
                client=client_obj,
                project=None,  # optional: wire if you later include it in generator
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
    qs = TimecardEntry.objects.filter(org=org).select_related("client", "project", "user")

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
        qs = qs.filter(user__username=user_filter)

    entries = [{
        'id': e.id,
        'date': e.date.isoformat(),
        'user': e.user.username if e.user_id else None,
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
    """
    CPA-style rollup:
    Client → total_hours + merged category_breakdown across entries.
    Query: ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&user=<username>
    """
    org = get_org_or_default(request)
    qs = TimecardEntry.objects.filter(org=org).select_related("client")

    if start_str := request.GET.get('start_date'):
        qs = qs.filter(date__gte=date_type.fromisoformat(start_str))
    if end_str := request.GET.get('end_date'):
        qs = qs.filter(date__lte=date_type.fromisoformat(end_str))
    if user_filter := request.GET.get('user'):
        qs = qs.filter(user__username=user_filter)

    total_hours = float(qs.aggregate(total=Sum('total_hours'))['total'] or 0.0)

    def _sum(q, st):
        return float(q.filter(status=st).aggregate(total=Sum('total_hours'))['total'] or 0.0)

    by_status = {
        'approved': _sum(qs, 'approved'),
        'pending': _sum(qs, 'pending'),
        'draft': _sum(qs, 'draft'),
        'rejected': _sum(qs, 'rejected'),
    }

    rollups: Dict[str, Dict[str, Any]] = {}
    for e in qs.select_related('client'):
        cname = e.client.name if e.client else "Unknown"
        r = rollups.setdefault(cname, {"total_hours": 0.0, "categories": {}, "entries": []})
        r["total_hours"] += float(e.total_hours or 0.0)
        if isinstance(e.category_breakdown, dict):
            for k, v in e.category_breakdown.items():
                if not k:
                    continue
                r["categories"][k] = float(r["categories"].get(k, 0.0)) + float(v or 0.0)
        r["entries"].append({
            "id": e.id,
            "date": e.date.isoformat(),
            "hours": float(e.total_hours or 0.0),
            "status": e.status,
        })

    by_client = [
        {
            "client": cname,
            "total_hours": round(v["total_hours"], 2),
            "categories": { k: round(float(h), 2) for k, h in sorted(v["categories"].items()) },
            "entries": v["entries"],
        }
        for cname, v in rollups.items()
    ]
    by_client.sort(key=lambda x: x["total_hours"], reverse=True)

    return Response({
        "total_hours": round(total_hours, 2),
        "by_client": by_client,
        "by_status": by_status,
        "entries_count": qs.count(),
        "needs_review_count": qs.filter(needs_review=True, status='draft').count(),
    })


# -------------------------------------------------------------------
# Daily roll-up from Blocks
# -------------------------------------------------------------------
def _host_from_url(u: str) -> str:
    try:
        return urllib.parse.urlparse(u or "").hostname or ""
    except Exception:
        return ""


def resolve_client_from_known(org, b) -> str | None:
    """
    Try to infer a client name using KnownEntity(entity_type='client') and block context.
    Checks: hostname, pathname, window_title.
    """
    host = _host_from_url(getattr(b, "url", "") or "")
    try:
        path = urllib.parse.urlparse(getattr(b, "url", "") or "").path or ""
    except Exception:
        path = ""
    title = (getattr(b, "window_title", "") or getattr(b, "title", "") or "").lower()

    known = list(KnownEntity.objects.filter(org=org, entity_type="client"))

    def _match(candidate: KnownEntity) -> bool:
        name = (candidate.name or "").lower()
        aliases = [(a or "").lower() for a in (candidate.aliases or [])]
        needles = [name] + aliases
        for n in needles:
            if not n:
                continue
            if n in (host or "").lower():
                return True
            if n in (path or "").lower():
                return True
            if n in title:
                return True
        return False

    for c in known:
        if _match(c):
            return c.name
    return None


def infer_task_for_block(b) -> str:
    """
    Heuristic task bucketer for CPAs.
    """
    title = (getattr(b, "window_title", "") or getattr(b, "title", "") or "").lower()
    url = getattr(b, "url", "") or ""
    host = _host_from_url(url)
    try:
        path = urllib.parse.urlparse(url).path or ""
    except Exception:
        path = ""

    # Meetings
    if "meet.google.com" in host or "zoom.us" in host or "teams.microsoft.com" in host:
        return "Meeting"

    # Email/Communication
    if "mail.google.com" in host or "outlook.office.com" in host or "gmail" in title or "outlook" in title:
        return "Email/Communication"
    if "slack.com" in host or "slack" in title:
        return "Communication"

    # Tax Prep (common CPA apps/terms)
    tax_terms = ["ultratax", "drake", "proseries", "lacerte", "tax", "1040", "1120", "1065", "w-2", "1099"]
    if any(t in title for t in tax_terms) or any(t in (path or "").lower() for t in tax_terms):
        return "Tax Prep"

    # Research
    if "irs.gov" in host or "taxfoundation.org" in host or "cch" in title or "checkpoint" in title or "research" in title:
        return "Research"

    # Admin / Docs
    if "docs.google.com" in host or "drive.google.com" in host or "onedrive" in host or "sharepoint" in host:
        return "Administration"

    # Default
    return "Uncategorized"


def _resolve_summary_user(request):
    """
    Decide which user to filter by:
      - If ?user=<username> is provided, use that (404 if not found).
      - Else if X-Agent-User header is present, use that (auto-provision if AGENT_AUTO_PROVISION=True).
      - Else return (None, ""), meaning "All Users".

    Returns: (User|None, display_name:str)
    """
    from django.conf import settings

    q_user = (request.GET.get("user") or "").strip()
    if q_user:
        try:
            u = User.objects.get(username=q_user)
            return (u, q_user)
        except User.DoesNotExist:
            # "Hard" fail with 404-ish behavior is okay; or return (None,"") if you prefer.
            from rest_framework.exceptions import NotFound
            raise NotFound(f"user '{q_user}' not found")

    hdr_user = (request.headers.get("X-Agent-User") or "").strip()
    if hdr_user:
        try:
            u = User.objects.get(username=hdr_user)
            return (u, hdr_user)
        except User.DoesNotExist:
            if getattr(settings, "AGENT_AUTO_PROVISION", False):
                u = User.objects.create_user(username=hdr_user)
                u.set_unusable_password()
                u.save()
                return (u, hdr_user)
            # fall through to All Users

    return (None, "")  # All Users


date_type = datetime.date  # if you already have this, keep your version


@api_view(["GET"])
@permission_classes([AllowAny])
def timecards_summary_day(request):
    """
    Summarize Blocks for a single day:
    Groups by client → tasks → category breakdowns.
    """
    date_str = (request.GET.get("date") or "").strip()
    if not date_str:
        return Response({"error": "date is required (YYYY-MM-DD)"}, status=400)

    try:
        day = datetime.date.fromisoformat(date_str)
    except ValueError:
        return Response({"error": "Invalid date format (use YYYY-MM-DD)"}, status=400)

    user_param = (request.GET.get("user") or "").strip()

    # Time window for that day (UTC)
    start_local = timezone.make_aware(datetime.datetime.combine(day, dt_time.min))
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(datetime.timezone.utc)
    end_utc = end_local.astimezone(datetime.timezone.utc)

    qs = Block.objects.filter(start__gte=start_utc, start__lt=end_utc)
    if user_param:
        qs = qs.filter(user__username=user_param)

    blocks = list(qs)

    clients = {}
    total_minutes = 0

    for b in blocks:
        mins = int(b.minutes or ((b.end - b.start).total_seconds() // 60))
        if mins <= 0:
            continue
        total_minutes += mins

        # ✅ Prefer FK client, else AI-inferred
        client_name = (
            getattr(b.client, "name", None)
            or getattr(b, "ai_extracted_client", None)
            or "Unknown"
        )
        task_name = (
            getattr(b.task, "name", None)
            or getattr(b, "ai_category", None)
            or "Uncategorized"
        )

        c_row = clients.setdefault(
            client_name,
            {
                "client_name": client_name,
                "total_hours": 0.0,
                "categories": {},
                "tasks": {},
                "block_ids": [],
            },
        )
        c_row["total_hours"] += mins / 60.0
        c_row["block_ids"].append(b.id)

        t_row = c_row["tasks"].setdefault(
            task_name,
            {"task_name": task_name, "total_hours": 0.0, "categories": {}, "block_ids": []},
        )
        t_row["total_hours"] += mins / 60.0
        t_row["block_ids"].append(b.id)

        cats = getattr(b, "category_hours", {}) or {}
        if isinstance(cats, dict) and cats:
            for k, v in cats.items():
                kk = str(k)[:120]
                hh = max(0.0, float(v))
                t_row["categories"][kk] = t_row["categories"].get(kk, 0.0) + hh
                c_row["categories"][kk] = c_row["categories"].get(kk, 0.0) + hh
        else:
            unc = "Uncategorized"
            hours = mins / 60.0
            t_row["categories"][unc] = t_row["categories"].get(unc, 0.0) + hours
            c_row["categories"][unc] = c_row["categories"].get(unc, 0.0) + hours

    client_rows = []
    for c in clients.values():
        tasks_list = sorted(c["tasks"].values(), key=lambda r: r["total_hours"], reverse=True)
        client_rows.append({
            "client_name": c["client_name"],
            "total_hours": round(c["total_hours"], 2),
            "categories": {k: round(v, 2) for k, v in c["categories"].items()},
            "tasks": [
                {
                    "task_name": t["task_name"],
                    "total_hours": round(t["total_hours"], 2),
                    "categories": {k: round(v, 2) for k, v in (t["categories"] or {}).items()},
                    "block_ids": t["block_ids"],
                }
                for t in tasks_list
            ],
            "block_ids": c["block_ids"],
        })

    client_rows.sort(key=lambda r: r["total_hours"], reverse=True)

    return Response({
        "date": day.isoformat(),
        "user": user_param or "",
        "total_hours": round(total_minutes / 60.0, 2),
        "clients": client_rows,
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
    """List or create known entities (clients, projects, categories, people)."""
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

    # POST
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


# -------------------------------------------------------------------
# Save classification via path param: /api/blocks/<id>/classify/
# -------------------------------------------------------------------
def _clean_name(v):
    if not v:
        return None
    v = str(v).strip()
    if not v:
        return None
    if v.lower() in {"none", "unassigned", "—", "-", "(none)"}:
        return None
    return v[:MAX_NAME_LEN]


def _to_float(v):
    try:
        s = str(v).lower().replace("hrs", "").replace("hr", "").replace("h", "").strip()
        f = float(s)
        if f < 0 or f != f:  # NaN
            return None
        return f
    except Exception:
        return None


def _sanitize_categories(obj):
    clean = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            kk = str(k).strip()[:MAX_NAME_LEN]
            fv = _to_float(v)
            if kk and fv is not None:
                clean[kk] = fv
    return clean


_clean_categories = _sanitize_categories  # alias


def _pick_or_create_client(org, name):
    qs = Client.objects.filter(org=org, name=name).order_by("id")
    obj = qs.first()
    if obj:
        return obj
    return Client.objects.create(org=org, name=name)


def _pick_or_create_project(org, client, name):
    qs = Project.objects.filter(org=org, client=client, name=name).order_by("id")
    obj = qs.first()
    if obj:
        return obj
    return Project.objects.create(org=org, client=client, name=name)


@api_view(["POST"])
@permission_classes([PermUI])
@transaction.atomic
def save_block_classification(request, block_id: int):
    """
    POST /api/blocks/<id>/classify/
    Body: { client?: str, project?: str, categories?: {name: hours} }
    - Ignores 'None' / '—' / 'Unassigned'
    - Picks oldest duplicate Client/Project instead of 400s
    """
    b = get_object_or_404(Block, id=block_id)
    org = getattr(b, "org", None) or get_org_or_default(request)

    data = request.data or {}
    client_name  = _clean_name(data.get("client"))
    project_name = _clean_name(data.get("project"))
    categories   = _sanitize_categories(data.get("categories") or {})

    if not client_name and not project_name and not categories:
        return Response({"ok": True, "block_id": b.id, "noop": True})

    client_obj = getattr(b, "client", None)

    if client_name:
        client_obj = _pick_or_create_client(org, client_name)
        b.client = client_obj

    if project_name:
        if client_obj is None:
            client_obj = _pick_or_create_client(org, "(General)")
            b.client = client_obj
        proj_obj = _pick_or_create_project(org, client_obj, project_name)
        b.project = proj_obj

    if categories:
        b.category_hours = categories

    b.full_clean()
    b.save()

    return Response({
        "ok": True,
        "block_id": b.id,
        "client": getattr(b.client, "name", None),
        "project": getattr(b.project, "name", None),
        "categories": getattr(b, "category_hours", {}),
    })


# -------------------------------------------------------------------
# Bulk import (clients/projects) for onboarding
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([PermUI])
def clients_list(request):
    org = get_org_or_default(request)
    qs = Client.objects.filter(org=org).order_by("name")
    return Response([{"id": c.id, "name": c.name} for c in qs])


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
            _, p_created = Project.objects.get_or_create(org=org, g=client, name=pname, defaults={'is_active': True})
            if p_created:
                created['projects'] += 1

    return Response({"message": "Import complete", **created})


# -------------------------------------------------------------------
# Agent sessions (admin glance)
# -------------------------------------------------------------------
@api_view(['GET'])
@permission_classes([AllowAny])  # tighten as needed
def agent_sessions(request):
    rows = AgentSession.objects.order_by('-last_seen')[:100]
    data = [
        {
            'user': r.user.username if getattr(r, "user_id", None) else None,
            'hostname': r.hostname,
            'last_seen': r.last_seen.isoformat(),
            'last_app': r.last_app,
            'last_window_title': r.last_window_title,
        }
        for r in rows
    ]
    return Response({'sessions': data})

from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

# views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

@api_view(["GET"])
@permission_classes([AllowAny])
def whoami(request):
    # (a) logged-in user
    if getattr(request.user, "is_authenticated", False):
        return Response({"username": request.user.username, "host": None, "source": "session"})

    # (b) cookies from agents_hello
    u = request.COOKIES.get("mavops_username", "").strip()
    h = request.COOKIES.get("mavops_host", "").strip()
    if u:
        return Response({"username": u, "host": h or None, "source": "cookie"})

    client_ip = (request.META.get("HTTP_X_FORWARDED_FOR","").split(",")[0].strip()
                 or request.META.get("REMOTE_ADDR",""))
    sess = AgentSession.objects.filter(last_ip=client_ip).select_related("user").order_by("-last_seen").first()
    if sess:
        return Response({"username": sess.user.username, "host": sess.hostname, "source": "ip"})
    # (c) nothing found
    return Response({"username": "", "host": None, "source": "unknown"})