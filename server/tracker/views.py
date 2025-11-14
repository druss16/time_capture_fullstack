# tracker/views.py
from __future__ import annotations

# --- Standard library ---
import asyncio
import csv
import io
import json
import os
import platform
import re
import urllib.parse
from collections import defaultdict
from datetime import datetime as dt, time as dt_time, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional


# --- Django ---
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, logout as django_logout
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Sum, Q
from django.db.models.functions import TruncHour
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.timezone import localtime
from django.views.decorators.csrf import csrf_exempt  # only if used



# --- DRF ---
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle
from rest_framework.authentication import SessionAuthentication


# --- Third-party ---
from allauth.account import app_settings as allauth_settings
from allauth.account.utils import perform_login
from openai import OpenAI

import datetime

# --- day window helpers (Django 5 safe) ---
import datetime as _dt
from django.utils import timezone
from django.utils.timezone import get_current_timezone, localtime
from django.utils.dateparse import parse_date

# --- imports (make sure these exist at top of views.py) ---
from collections import defaultdict
from datetime import datetime as dt, time as dt_time, timedelta
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


# imports you should have near top of views.py
import datetime as _dt
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.timezone import get_current_timezone, localtime

# imports
import datetime as _dt
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.timezone import get_current_timezone, localtime

from django.contrib.auth.decorators import login_required

# tracker/views.py
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie

from django.db import transaction

# --- Local apps ---
from tracker.models import (
    AgentControl,
    AgentSession,
    AgentPairCode,
    AgentDevice,
    AITrainingExample,
    Block,
    Client,
    KnownEntity,
    OrganizationSettings,
    Project,
    RawEvent,
    Rule,
    Suggestion,
    Task,
    TimecardEntry,
)
from tracker.permissions import AgentKeyPermission, NoAuth, PermUI
from tracker.rules import apply_rules
from tracker.serializers import RawEventSerializer
from tracker.services.classify_block import classify_block
from tracker.auth import AgentKeyAuthentication
from tracker.utils import (
    _client_ip,
    compact_rawevents_into_blocks,
    get_org_or_default,
    infer_task_for_block,
    resolve_agent_user,
    resolve_client_from_known,
)
from tracker.throttles import (
    AgentIngestThrottle,
    UIReadThrottle,
    UIWriteThrottle,
    AIGenerateThrottle,
    PublicHelloThrottle,
    PairIssueRate,
    PairClaimRate,
)

from tracker.utils.blocks import (
    get_current_client_for_user,
    apply_current_client_to_recent_blocks
)

# REPLACE your existing raw_events() function with this version

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from .auth import AgentKeyAuthentication
from .models import RawEvent, CurrentClient, Client

# If you need a User class reference:
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


User = get_user_model()

COOKIE_USER_KEY = "mavops_username"
COOKIE_HOST_KEY = "mavops_host"
COOKIE_BUNDLE = "mavops_ident"  # signed bundle (preferred)


# tracker/views.py
import os, threading, logging
logger = logging.getLogger(__name__)

NON_BLOCKING_COMPACT = os.getenv("NON_BLOCKING_COMPACT", "1") == "1"

# --- helpers at top of file (keep your _to_epoch_ms and _union_minutes) ---

# --- Idle detection (shared) ---
IDLE_TITLES = {
    "uncategorized - idle", "idle/uncategorized", "idle",
    "uncategorized", "newtab", "new tab", "screen saver",
    "loginwindow", "lock screen"
}
IDLE_APPS = {
    "idle", "loginwindow", "screensaverengine", "screensaver",
    "lockscreen", "notificationcenter", "controlcenter", "dock"
}

def _iso(dt):
    return dt.isoformat() if dt else None

def _is_idle_block(b):
    # keep consistent with your agent semantics
    try:
        if getattr(b, "bundle_id", None) == "__idle__": return True
        if (getattr(b, "app_name", "") or "").lower() == "idle": return True
        if (getattr(b, "window_title", "") or "").strip() == "Uncategorized - Idle": return True
    except Exception:
        pass
    return False


def _is_idle_activity(app_name=None, bundle_id=None, window_title=None):
    """Detect if activity is idle/AFK - idle blocks should NOT get client assigned."""
    if bundle_id == "__idle__":
        return True
    if app_name and app_name.lower() in ("idle", "loginwindow", "screensaver"):
        return True
    if window_title:
        title_lower = window_title.strip().lower()
        if title_lower in ("uncategorized - idle", "idle", "lock screen"):
            return True
    return False


def _idle_minutes_from_gaps(spans_ms, start_ms, end_ms) -> int:
    """
    Given merged-eligible spans (ms) for ACTIVE work within [start_ms, end_ms),
    return minutes of 'idle/away' gaps between them.
    """
    if not spans_ms:
        return int((end_ms - start_ms) // 60_000)

    spans_ms = sorted(spans_ms, key=lambda p: p[0])
    idle_ms = 0
    cur = start_ms
    for s, e in spans_ms:
        if s > cur:
            idle_ms += (s - cur)
        cur = max(cur, e)
    if cur < end_ms:
        idle_ms += (end_ms - cur)
    return int(idle_ms // 60_000)


def _block_minutes_fallback(b) -> int:
    m = getattr(b, "minutes", None)
    try: m = int(m) if m is not None else None
    except Exception: m = None
    if m is None:
        if not getattr(b, "end", None) and getattr(b, "start", None):
            return 5
        return 0
    return max(0, min(m, 180))  # cap to 3h

def _to_epoch_ms(d):
    if not d: return None
    if timezone.is_naive(d):
        d = d.replace(tzinfo=dt_timezone.utc)
    return int(d.timestamp() * 1000)

def _union_minutes(spans):
    if not spans: return 0
    norm = []
    for s, e in spans:
        if isinstance(s, (int, float)) and isinstance(e, (int, float)):
            s = dt.fromtimestamp(s / 1000.0, tz=dt_timezone.utc)
            e = dt.fromtimestamp(e / 1000.0, tz=dt_timezone.utc)
        if not s or not e or e <= s: continue
        if timezone.is_naive(s): s = s.replace(tzinfo=dt_timezone.utc)
        if timezone.is_naive(e): e = e.replace(tzinfo=dt_timezone.utc)
        norm.append((s, e))
    if not norm: return 0
    norm.sort(key=lambda x: x[0])
    merged = []
    cur_s, cur_e = norm[0]
    for s, e in norm[1:]:
        if s <= cur_e: cur_e = max(cur_e, e)
        else: merged.append((cur_s, cur_e)); cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return int(sum((e - s).total_seconds() for s, e in merged) // 60)

def _make_aware_local(dt_naive, tz):
    try:
        return tz.localize(dt_naive)  # pytz
    except Exception:
        return timezone.make_aware(dt_naive, tz)  # zoneinfo

def _start_end_of_local_day_utc(date_str: Optional[str] = None):
    tz = get_current_timezone()
    d = parse_date(date_str) if date_str else None
    if not d:
        d = localtime(timezone.now()).date()
    start_local = _make_aware_local(dt.combine(d, dt_time.min), tz)
    next_local  = _make_aware_local(dt.combine(d + timedelta(days=1), dt_time.min), tz)
    return (start_local.astimezone(dt_timezone.utc), next_local.astimezone(dt_timezone.utc))

def _compact_fire_and_forget(username, hostname, org, date_str):
    try:
        # IMPORTANT: add fast/llm flags inside _compact_safe (or wrap your classify) to skip LLM here
        _compact_safe(username, hostname, org, date_str, fast=True, llm=False, max_seconds=3)
    except Exception as e:
        logger.warning("non-blocking compact skipped: %s", e)


def _make_aware_local(dt_naive: _dt.datetime, tz) -> _dt.datetime:
    """
    Make a naive local datetime aware. Works for both pytz and zoneinfo.
    """
    try:
        # pytz style
        return tz.localize(dt_naive)  # type: ignore[attr-defined]
    except Exception:
        # zoneinfo (Django 4/5)
        return timezone.make_aware(dt_naive, tz)



# from tracker.models import Block   # <-- already in your file

# --- helpers: MILLIS-BASED path (used by your current view) ---

# ---- HELPER FUNCTIONS ----

from datetime import datetime as dt, timezone as dt_timezone, timedelta
from django.utils import timezone



def _span_for_block(b, day_start, day_end):
    """Return clamped (start, end) tuple inside [day_start, day_end) in UTC."""
    s = getattr(b, "start", None)
    e = getattr(b, "end", None)
    if not s:
        return None
    if timezone.is_naive(s):
        s = s.replace(tzinfo=dt_timezone.utc)
    else:
        s = s.astimezone(dt_timezone.utc)
    if e:
        if timezone.is_naive(e):
            e = e.replace(tzinfo=dt_timezone.utc)
        else:
            e = e.astimezone(dt_timezone.utc)
    else:
        mins = getattr(b, "minutes", None)
        e = s + (timedelta(minutes=float(mins)) if isinstance(mins, (int, float)) and mins > 0 else timedelta(seconds=1))
    if e <= day_start or s >= day_end:
        return None
    if s < day_start: s = day_start
    if e > day_end: e = day_end
    if e <= s:
        return None
    return (s, e)

def _start_of_local_day_utc(dt: _dt.datetime | None = None) -> _dt.datetime:
    # if a datetime is passed, convert that instant to local midnight; else today
    if dt is None:
        return _start_end_of_local_day_utc(None)[0]
    local = timezone.localtime(dt)
    sod_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return sod_local.astimezone(_dt.timezone.utc)   # <-- key change

def _compact_safe(username, hostname, org, date_str):
    try:
        # If your function supports day / start_utc / end_utc, pass them:
        start_utc, end_utc = _start_end_of_local_day_utc(date_str)
        return compact_rawevents_into_blocks(
            user=username,
            hostname=hostname,
            org=org,
            day=date_str,                 # ok if supported
            start_utc=start_utc,          # ok if supported
            end_utc=end_utc,              # ok if supported
        )
    except TypeError:
        # Old signature — just call the legacy form
        return compact_rawevents_into_blocks(user=username, hostname=hostname, org=org)

def _signed_cookie_get(request, name: str, default=None):
    raw = request.COOKIES.get(name)
    if not raw:
        return default
    try:
        return signing.loads(raw, max_age=60 * 60 * 24 * 14)  # 14 days
    except signing.BadSignature:
        return default

# -------------------------------------------------------------------
# Utility helpers
# -------------------------------------------------------------------
# --- utility: org helper (safe default group) ---
def get_org_or_default(request):
    """
    Get org from user or a default dev org ('default-org').
    Ensures there's always a Group so queries don't crash.
    """
    if USE_AUTH and getattr(request, "user", None) and request.user.is_authenticated:
        org = request.user.groups.first()
    else:
        org = None
    if not org:
        org, _ = Group.objects.get_or_create(name="default-org")
    return org



@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def get_csrf(request):
    return Response({"ok": True})

def _get_user_obj(username: Optional[str]):
    if not username:
        return None
    try:
        return User.objects.get(username=username)
    except User.DoesNotExist:
        return None

def _get_agent_device(request):
    """Return the AgentDevice for the given API key, or None."""
    api_key = request.META.get(AGENT_HEADER)
    if not api_key:
        return None
    try:
        return AgentDevice.objects.select_related("user").get(api_key=api_key, is_active=True)
    except AgentDevice.DoesNotExist:
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
# ---------- Agent-authenticated endpoints ----------
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

@login_required
@api_view(["POST"])
def pair_start(request):
    """Signed-in user clicks 'Pair this Mac' → get code"""
    pc = AgentPairCode.issue(request.user, ttl_seconds=600)
    return Response({"code": pc.code, "expires_at": pc.expires_at})


# Optional: list & manage devices
@login_required
@api_view(["GET"])
def my_devices(request):
    q = AgentDevice.objects.filter(user=request.user).order_by("-last_seen_at", "-created_at")
    return Response([{
        "id": d.id, "hostname": d.hostname, "device_id": d.device_id,
        "is_active": d.is_active, "last_seen_at": d.last_seen_at, "created_at": d.created_at,
    } for d in q])


@login_required
@api_view(["POST"])
def revoke_device(request, pk=None):
    try:
        d = AgentDevice.objects.get(id=pk, user=request.user)
    except AgentDevice.DoesNotExist:
        return Response({"detail": "Not found."}, status=404)
    d.is_active = False
    d.save(update_fields=["is_active"])
    return Response({"ok": True})

@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def pair_complete(request):
    """
    Complete device pairing using a short code.

    Expected JSON:
    {
      "code": "ABC123",
      "device_id": "uuid-or-random",
      "hostname": "Dans-MacBook",
      "platform": "macOS 15.1",
      "app_version": "1.0.0"
    }

    Returns:
    {
      "ok": true,
      "paired": true,
      "api_key": "...",
      "user_id": 123,
      "username": "danrussell",
      "device_id": "..."
    }
    """
    data = request.data or {}
    code = (data.get("code") or "").strip().upper()
    device_id = (data.get("device_id") or "").strip()
    hostname = (data.get("hostname") or "").strip()
    platform_str = (data.get("platform") or "").strip()
    app_version = (data.get("app_version") or "").strip()

    if not code or not device_id:
        return Response(
            {"ok": False, "error": "code and device_id are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Look up valid, unconsumed, unexpired code
    now = timezone.now()
    try:
        pair = AgentPairCode.objects.select_related("user").get(
            code=code, consumed_at__isnull=True, expires_at__gte=now
        )
    except AgentPairCode.DoesNotExist:
        return Response(
            {"ok": False, "error": "Invalid or expired code"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Create/update device + generate API key
    with transaction.atomic():
        device, _ = AgentDevice.objects.select_for_update().get_or_create(
            user=pair.user,
            device_id=device_id,
            defaults={"is_active": True},
        )
        # (Re)generate key on every successful pair to rotate secrets
        device.api_key = secrets.token_hex(16)
        if hostname:
            device.hostname = hostname
        if platform_str:
            device.platform = platform_str
        if app_version:
            device.app_version = app_version
        device.last_seen_at = now
        device.is_active = True
        device.save()

        # consume the code
        pair.consume()

    return Response(
        {
            "ok": True,
            "paired": True,
            "api_key": device.api_key,
            "user_id": pair.user.id,
            "username": getattr(pair.user, "username", str(pair.user)),
            "device_id": device.device_id,
        },
        status=status.HTTP_200_OK,
    )

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import AgentDevice  # adjust import

# views.py (DRF)
from django.utils import timezone
from django.contrib.auth.models import User, Group
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import json

# NEW: paired hello (device-key)
# NEW: paired hello (device-key)
@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def agents_hello2(request):
    """
    DeviceKey-authenticated heartbeat.
    - Updates AgentDevice metadata
    - Upserts AgentSession
    - Returns a minimal payload (user_id optional for convenience)
    """
    user = request.user
    dev = getattr(request, "agent_device", None)  # set by AgentKeyAuthentication

    # host: prefer payload, else header, else device hostname, else 'unknown'
    payload_host = (request.data.get("hostname") or "").strip()
    header_host  = (request.headers.get("X-Agent-Host") or "").strip()
    dev_host     = (getattr(dev, "hostname", "") or "").strip()
    host = (payload_host or header_host or dev_host or "unknown")[:128]

    # keep device metadata fresh
    if dev:
        dev.hostname    = host or dev.hostname
        dev.app_version = (request.data.get("app_version") or dev.app_version or "")[:32]
        dev.is_active   = True
        dev.last_seen_at = timezone.now()
        # optional: record platform from header for quick visibility
        plat_hdr = (request.headers.get("X-Agent-Platform") or "").strip()
        if hasattr(dev, "platform") and plat_hdr:
            dev.platform = plat_hdr[:128]
        dev.save(update_fields=["hostname", "app_version", "is_active", "last_seen_at", "platform"] if plat_hdr else ["hostname", "app_version", "is_active", "last_seen_at"])

    # upsert AgentSession for dashboards/fallbacks
    AgentSession.objects.update_or_create(
        user=user,
        hostname=host,
        defaults={
            "last_seen": timezone.now(),
            "last_app": request.data.get("last_app", "")[:120],
            "last_window_title": request.data.get("last_window_title", "")[:512],
            "platform": (request.headers.get("X-Agent-Platform") or "")[:80],
            "version": (request.headers.get("X-Agent-Version") or "")[:40],
            "last_ip": (request.META.get("REMOTE_ADDR") or _client_ip(request) or "")[:45],
        },
    )

    # keep response minimal; user_id is optional – agent shouldn't depend on it
    return Response({
        "ok": True,
        "user_id": user.id,
        "username": user.username,
        "host": host,
    })

@api_view(["POST"])
@permission_classes([AllowAny])
def agents_hello(request):
    """
    Legacy browser hello: sets a signed *hint* cookie for the SPA.
    - Does NOT create users
    - Does NOT upsert sessions
    - Keeps the flow clean (pair via AgentPairCode + DeviceKey)
    """
    # Gather inputs (headers preferred, JSON fallback)
    try:
        body = request.data if isinstance(request.data, dict) else json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        body = {}

    username = ((request.headers.get("X-Agent-User") or body.get("user") or body.get("os_username") or "").strip())[:150]
    host     = ((request.headers.get("X-Agent-Host") or body.get("hostname") or body.get("machine") or "").strip() or "browser")[:128]

    if not username:
        # nothing useful to hint; respond ok without cookies
        return Response({"ok": True, "hint": False})

    # Build signed bundle cookie (HINT ONLY — not auth)
    bundle = {"username": username, "host": host, "ts": timezone.now().isoformat()}
    signed = signing.dumps(bundle)

    resp = Response({
        "ok": True,
        "hint": True,
        "username": username,
        "host": host,
    })

    secure = request.is_secure()  # make sure True in prod behind HTTPS
    # Preferred: single signed cookie the SPA can read
    resp.set_cookie(
        COOKIE_BUNDLE,
        signed,
        max_age=60 * 60 * 24 * 14,  # 14 days
        samesite="Lax",
        secure=secure,
        httponly=False,  # readable by SPA; only a display hint
        path="/",
    )

    # Optional legacy cookies for transition (safe to remove later)
    resp.set_cookie(COOKIE_USER_KEY, username, samesite="Lax", secure=secure, httponly=False, path="/")
    resp.set_cookie(COOKIE_HOST_KEY, host,     samesite="Lax", secure=secure, httponly=False, path="/")

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



# views.py (raw_events)
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model

User = get_user_model()

# use your existing auth class that sets request.user and request.agent_device
from .auth import AgentKeyAuthentication   # ← adjust import to your project
from .models import RawEvent

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from .models import RawEvent

# tracker/views.py
@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def raw_events(request):
    """
    Ingest events from a paired agent.
    NOW: Auto-tags events with current client if set.
    
    - Requires Authorization: DeviceKey <api_key>
    - request.user = linked user from AgentDevice
    - request.agent_device = the AgentDevice instance
    """
    agent_user = request.user
    device = getattr(request, "agent_device", None)
    if not getattr(agent_user, "is_authenticated", False):
        return Response({"error": "Not authenticated"}, status=403)
    
    payload = request.data
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return Response({"error": "Must be object or array"}, status=400)
    
    # Get current client for this user/device
    current_client_id = None
    current_client_name = None
    try:
        current = CurrentClient.objects.select_related('client').get(
            user=agent_user,
            device_id=device.id if device else 0
        )
        current_client_id = current.client.id if current.client else None
        current_client_name = current.client.name if current.client else None
    except CurrentClient.DoesNotExist:
        pass  # No current client set
    
    header_host = (request.headers.get("X-Agent-Host") or "").strip()
    device_host = getattr(device, "hostname", "") if device else ""
    default_host = header_host or device_host or "unknown"
    created, errors = 0, []
    
    for item in payload:
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
        
        hostname = (default_host or item.get("hostname") or "unknown").strip() or "unknown"
        
        try:
            # Create RawEvent with current_client_id
            event = RawEvent.objects.create(
                ts_utc=item["ts_utc"],
                app_name=item.get("app_name"),
                bundle_id=item.get("bundle_id"),
                window_title=item.get("window_title") or "",
                url=item.get("url"),
                file_path=item.get("file_path"),
                user=agent_user,
                hostname=hostname,
                ctx=item.get("ctx", {}) or {},
                device_id=getattr(device, "device_id", "unknown") if device else "unknown",
                current_client_id=current_client_id,  # ← NEW: Store current client
            )
            
            created += 1
        except Exception as e:
            errors.append({"item": item, "error": str(e)})
    
    status_code = (
        status.HTTP_201_CREATED if created and not errors
        else status.HTTP_207_MULTI_STATUS if created and errors
        else status.HTTP_400_BAD_REQUEST
    )
    
    return Response({
        "created": created,
        "errors": errors,
        "current_client": current_client_name  # Return client name for logging
    }, status=status_code)


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
    
    ✅ NEW: PRESERVES blocks that have user data (categories, manual client assignments)
    ✅ Only recreates blocks that are "raw" (no user edits)
    """
    start_utc = _start_of_local_day_utc()

    user_obj = user if isinstance(user, User) else _get_user_obj(user)

    ev_qs = RawEvent.objects.filter(ts_utc__gte=start_utc).order_by("ts_utc")
    if user_obj:
        ev_qs = ev_qs.filter(user=user_obj)
    if hostname:
        ev_qs = ev_qs.filter(hostname=hostname)
    events: List[RawEvent] = list(ev_qs)

    # ✅ CRITICAL FIX: Only delete blocks WITHOUT user data
    blk_qs = Block.objects.filter(start__gte=start_utc)
    if user_obj:
        blk_qs = blk_qs.filter(user=user_obj)
    if hostname:
        blk_qs = blk_qs.filter(hostname=hostname)
    
    # ✅ NEW: Preserve blocks with user data (categories or manually set clients)
    # Only delete "raw" blocks that can be safely recreated
    blocks_to_preserve = blk_qs.filter(
        Q(category_hours__isnull=False) |  # Has categories
        Q(client__isnull=False)  # Has manually assigned client
    ).exclude(
        category_hours={}  # Exclude empty category dicts
    )
    
    preserved_blocks = list(blocks_to_preserve.values_list('id', 'start', 'end'))
    preserved_count = len(preserved_blocks)
    
    # Only delete raw/uncategorized blocks
    blk_qs.exclude(id__in=[b[0] for b in preserved_blocks]).delete()
    
    log(f"[COMPACT] Preserved {preserved_count} user-categorized blocks")

    created = 0
    pad = timedelta(minutes=BLOCK_PAD_MINUTES)
    sticky_delta = timedelta(minutes=IDLE_STICKY_MINUTES)

    current: Optional[Dict[str, Any]] = None

    def _duration_minutes(cur: Dict[str, Any]) -> int:
        return int((cur["end"] - cur["start"]).total_seconds() // 60)

    def _is_time_covered_by_preserved_blocks(start_time, end_time) -> bool:
        """Check if this time range overlaps with preserved blocks"""
        for block_id, block_start, block_end in preserved_blocks:
            # Check for overlap
            if start_time < block_end and end_time > block_start:
                return True
        return False

    def _finalize_and_create(cur: Dict[str, Any], org_val, user_obj) -> int:
        """
        Finalize and create a block.
        ✅ NEW: Skip creating if time range already covered by preserved block
        """
        actual = _duration_minutes(cur)
        target = max(MIN_BLOCK_DURATION, _round_up_minutes(actual, BLOCK_GRANULARITY))
        if actual < target:
            cur["end"] = cur["start"] + timedelta(minutes=target)

        # ✅ NEW: Don't create if already covered by a preserved block
        if _is_time_covered_by_preserved_blocks(cur["start"], cur["end"]):
            log(f"[COMPACT] Skipping block creation - time range already covered by user data")
            return 0

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

        # Check if this is IDLE activity before assigning client
        is_idle = _is_idle_activity(
            app_name=cur.get("app_name"),
            bundle_id=cur.get("bundle_id"),
            window_title=cur.get("window_title")
        )
        
        if is_idle:
            kwargs["client"] = None
            if hasattr(Block, "app_name"):
                kwargs["app_name"] = cur.get("app_name") or "idle"
            if hasattr(Block, "bundle_id"):
                kwargs["bundle_id"] = cur.get("bundle_id") or "__idle__"
        else:
            # Get client from stored current_client_id
            current_client = None
            stored_client_id = cur.get("current_client_id")
            if stored_client_id:
                try:
                    from tracker.models import Client
                    current_client = Client.objects.get(id=stored_client_id)
                except Client.DoesNotExist:
                    pass
                                    
            if current_client and hasattr(Block, "client"):
                kwargs["client"] = current_client
            
            if hasattr(Block, "app_name"):
                kwargs["app_name"] = cur.get("app_name") or ""
            if hasattr(Block, "bundle_id"):
                kwargs["bundle_id"] = cur.get("bundle_id") or ""

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
        u_fk = e.user
        h = hostname or getattr(e, "hostname", None) or ""
        et = e.ts_utc
        url = e.url or ""
        fpath = e.file_path or ""
        wtitle = getattr(e, "window_title", "") or ""
        app_name = getattr(e, "app_name", "") or ""
        bundle_id = getattr(e, "bundle_id", "") or ""

        if current is None:
            current = dict(
                start=et, end=et, title=lbl, window_title=wtitle,
                url=url, file_path=fpath, user=u_fk, hostname=h,
                app_name=app_name, bundle_id=bundle_id,
                current_client_id=getattr(e, "current_client_id", None),
            )
            _merge_ctx(current, e)
            continue

        gap = et - current["end"]

        if gap <= pad and _same_activity(current, lbl, url):
            if timedelta(0) < gap <= sticky_delta:
                current["end"] += gap
            current["end"] = et
            _merge_ctx(current, e)
        else:
            created += _finalize_and_create(current, org, user_obj)
            current = dict(
                start=et, end=et, title=lbl, window_title=wtitle,
                url=url, file_path=fpath, user=u_fk, hostname=h,
                app_name=app_name, bundle_id=bundle_id,
                current_client_id=getattr(e, "current_client_id", None),
            )
            _merge_ctx(current, e)

    if current:
        created += _finalize_and_create(current, org, user_obj)

    log(f"[COMPACT] Created {created} new blocks, preserved {preserved_count} existing blocks")
    return created


# -------------------------------------------------------------------
# UI endpoints (compaction-on-read)
# -------------------------------------------------------------------
from rest_framework.response import Response

# tracker/views.py (snippets)
import datetime as _dt
from django.utils import timezone

from django.db.models import Q

from django.db.models import Q

@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UIReadThrottle])
def blocks_today(request):
    date_str  = request.GET.get("date") or None
    username  = request.GET.get("user") or None
    hostname  = request.GET.get("hostname") or None
    limit_str = request.GET.get("limit") or None
    org       = get_org_or_default(request)

    # background compaction as you had...

    start_utc, end_utc = _start_end_of_local_day_utc(date_str)
    qs = Block.objects.filter(start__gte=start_utc, start__lt=end_utc).order_by("start")
    if username:
        qs = qs.filter(user__username=username)
    if hostname:
        qs = qs.filter(hostname=hostname)

    # match your dev/prod org scoping used elsewhere
    if USE_AUTH and org:
        if settings.DEBUG:
            qs = qs.filter(Q(org=org) | Q(org__isnull=True))
        else:
            qs = qs.filter(org=org)

    if limit_str:
        try: qs = qs[: max(1, min(int(limit_str), 1000))]
        except Exception: pass

    def _minutes(b: Block) -> int:
        m = getattr(b, "minutes", None)
        if isinstance(m, (int, float)):
            try: return int(m)
            except Exception: pass
        try:
            if not b.end or not b.start: return 0
            return max(0, int((b.end - b.start).total_seconds() // 60))
        except Exception:
            return 0

    data = []
    for b in qs.select_related("client", "project", "task", "user"):
        idle = _is_idle_block(b)
        win_title = getattr(b, "window_title", "") or ""
        if idle:
            win_title = "Uncategorized - Idle"  # normalize for UI

        data.append({
            "id": b.id,
            "start": _iso(b.start),
            "end": _iso(b.end),
            "minutes": _minutes(b),
            "title": b.title,
            "window_title": win_title,
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
            # expose app/bundle if you have them (optional but useful)
            "app_name": getattr(b, "app_name", "") or "",
            "bundle_id": getattr(b, "bundle_id", "") or "",
            "is_idle": _is_idle_block(b),   # <--- reuse your server idle logic

        })

    return Response(data)

from django.db.models import Q

@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UserRateThrottle])
def suggestions_today(request):
    date_str = request.GET.get("date") or None
    username = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    org      = get_org_or_default(request)

    # quick compact to improve block edges
    try:
        _compact_safe(username, hostname, org, date_str)
    except Exception:
        pass

    start_utc, end_utc = _start_end_of_local_day_utc(date_str)
    qs = Block.objects.filter(start__gte=start_utc, start__lt=end_utc).order_by("start")
    if username:
        qs = qs.filter(user__username=username)
    if hostname:
        qs = qs.filter(hostname=hostname)

    # mirror /summary org filtering
    if USE_AUTH and org:
        if settings.DEBUG:
            qs = qs.filter(Q(org=org) | Q(org__isnull=True))
        else:
            qs = qs.filter(org=org)

    # scope rules to org if available
    rule_qs = Rule.objects.filter(active=True)
    try:
        if org and "org" in {f.name for f in Rule._meta.get_fields()}:
            rule_qs = rule_qs.filter(org=org)
    except Exception:
        pass
    rules = list(rule_qs)

    out = []
    with transaction.atomic():
        for b in qs.select_related("client", "project", "task"):
            # Clean slate (optional)
            Suggestion.objects.filter(block=b).delete()

            mins = int(getattr(b, "minutes", 0) or 0)
            if mins <= 0 and b.start and b.end:
                mins = max(0, int((b.end - b.start).total_seconds() // 60))
            hours = round(mins / 60.0, 2)

            # 🔒 IDLE short-circuit
            if _is_idle_block(b):
                # store a Suggestion row (optional) for audit trail
                Suggestion.objects.create(
                    block=b, label_type="category",
                    value_text="Uncategorized - Idle",
                    confidence=1.0, source="idle"
                )
                out.append({
                    "block_id": b.id,
                    "ai_suggestion": {
                        "client": None,
                        "project": None,
                        "categories": {"Uncategorized - Idle": hours},
                        "confidence": 1.0,
                        "needs_review": False,
                        "reasoning": "Detected system/user idle; not billable.",
                    }
                })
                continue

            # Apply your existing rules (top 3) → we still persist them if you want
            for field, value_text, conf in list(apply_rules(b, rules))[:3]:
                Suggestion.objects.create(
                    block=b, label_type=field, value_text=value_text,
                    confidence=conf, source="rule"
                )

            # Heuristic fallback for non-idle
            host = ""
            try:
                if b.url:
                    host = urllib.parse.urlparse(b.url).hostname or ""
                    host = host.replace("www.", "")
            except Exception:
                pass

            client_guess  = getattr(b.client, "name", None) or (host or None)
            project_guess = getattr(b.project, "name", None)
            cats = {"General": hours} if hours > 0 else {}

            out.append({
                "block_id": b.id,
                "ai_suggestion": {
                    "client": client_guess,
                    "project": project_guess,
                    "categories": cats,
                    "confidence": 0.55,
                    "needs_review": True,
                    "reasoning": "Rule/URL heuristic.",
                }
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
def pre_classify_obvious_categories(block) -> dict:
    """
    Pre-classify obvious patterns before AI runs.
    Enhanced with CPA-specific tool detection.
    Returns: {"categories": {...}, "confidence": float, "reasoning": str} or empty dict
    """
    title = (getattr(block, "window_title", "") or block.title or "").lower()
    url = (block.url or "").lower()
    app_name = (getattr(block, "app_name", "") or "").lower()
    file_path = (block.file_path or "").lower()
    
    # Calculate block duration in hours
    if block.end and block.start:
        hours = round((block.end - block.start).total_seconds() / 3600, 2)
    else:
        hours = 0.1  # fallback
    
    combined_text = f"{title} {url} {app_name} {file_path}"
    
    # === EMAIL DETECTION ===
    email_indicators = [
        "@gmail.com", "@outlook.com", "@yahoo.com", "@hotmail.com",
        "mail.google.com", "outlook.office.com", "inbox",
        "compose", "draft", "sent mail", "email", "message"
    ]
    if any(indicator in combined_text for indicator in email_indicators):
        return {
            "categories": {"Email/Communication": hours},
            "confidence": 0.90,
            "reasoning": "Email activity detected"
        }
    
    # === MEETING DETECTION ===
    meeting_indicators = [
        "zoom.us", "zoom meeting", "meet.google.com", "teams.microsoft.com",
        "webex", "gotomeeting", "join meeting", "video call", "conference"
    ]
    if any(indicator in combined_text for indicator in meeting_indicators):
        return {
            "categories": {"Meetings": hours},
            "confidence": 0.95,
            "reasoning": "Virtual meeting detected"
        }
    
    # === CPA TOOL DETECTION ===
    for tool_key, tool_config in CPA_TOOL_DETECTION.items():
        # Check keywords
        if any(keyword in combined_text for keyword in tool_config["keywords"]):
            return {
                "categories": {tool_config["category"]: hours},
                "confidence": tool_config["confidence"],
                "reasoning": f"{tool_config['category']} software detected"
            }
        
        # Check domains
        if any(domain in url for domain in tool_config["domains"]):
            return {
                "categories": {tool_config["category"]: hours},
                "confidence": tool_config["confidence"],
                "reasoning": f"{tool_config['category']} platform detected from URL"
            }
        
        # Check URL patterns
        if any(pattern in combined_text for pattern in tool_config.get("urls", [])):
            return {
                "categories": {tool_config["category"]: hours},
                "confidence": tool_config["confidence"] - 0.05,
                "reasoning": f"{tool_config['category']} content detected"
            }
    
    # === IRS.GOV SPECIAL CASE ===
    if "irs.gov" in url:
        return {
            "categories": {"Tax Research": hours},
            "confidence": 0.93,
            "reasoning": "IRS website research"
        }
    
    return {}


@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([AIGenerateThrottle])
def ai_suggestions_today(request):
    """
    Generate AI-powered suggestions for today's blocks.
    ✅ NEW: Skips already-categorized blocks (no wasted AI credits)
    ✅ NEW: Auto-saves high-confidence results (>= 0.70 confidence)
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

    all_blocks = list(qs)
    if not all_blocks:
        return Response([])

    # ✅ NEW: Filter out blocks that already have categories
    # Don't waste AI credits re-processing work that's already categorized
    blocks_needing_ai = []
    already_categorized = []

    for b in all_blocks:
        has_categories = (
            getattr(b, "category_hours", None) 
            and b.category_hours 
            and isinstance(b.category_hours, dict) 
            and len(b.category_hours) > 0
        )
        
        if has_categories:
            already_categorized.append(b)
        else:
            blocks_needing_ai.append(b)

    log(f"[AI] {len(already_categorized)} blocks already categorized, {len(blocks_needing_ai)} need AI")

    # If everything is already categorized, return early with existing data
    if not blocks_needing_ai:
        out = []
        for b in already_categorized:
            out.append({
                "block_id": b.id,
                "start": b.start,
                "end": b.end,
                "title": b.title,
                "ai_suggestion": {
                    "client": getattr(b.client, "name", None),
                    "project": getattr(b.project, "name", None),
                    "categories": b.category_hours or {},
                    "confidence": 1.0,
                    "needs_review": False,
                    "reasoning": "Already categorized",
                    "source": "existing",
                    "auto_saved": False,
                },
                "current_client": getattr(b.client, "name", None),
                "current_project": getattr(b.project, "name", None),
            })
        return Response(out)

    # ✅ Only process uncategorized blocks from here on
    blocks = blocks_needing_ai

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
            "already_categorized": len(already_categorized),
            "needs_ai": len(blocks_needing_ai),
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
        "You are a time-tracking classifier for a CPA firm. "
        "Use the organization context and each block's hints to classify time blocks. "
        "\n\n"
        "AVAILABLE CATEGORIES (use these exact names):\n"
        "- Tax Preparation: Tax returns, forms, calculations\n"
        "- Accounting/Bookkeeping: General ledger, reconciliations, journal entries\n"
        "- Audit/Assurance: Audit procedures, testing, working papers\n"
        "- Tax Research: IRS codes, regulations, research\n"
        "- Payroll Services: Payroll processing, filings\n"
        "- Financial Planning: Retirement, investment planning\n"
        "- Regulatory/Compliance: SEC filings, compliance work\n"
        "- Document Management: File organization, signatures\n"
        "- Email/Communication: Client emails, correspondence\n"
        "- Meetings: Video calls, client meetings\n"
        "- Administration: Practice management, billing, workflows\n"
        "- Review: Reviewing work, quality control\n"
        "\n"
        "CRITICAL RULES:\n"
        "1. Use exact category names from the list above\n"
        "2. Email apps/domains → 'Email/Communication'\n"
        "3. Zoom/Teams/Meet → 'Meetings'\n"
        "4. QuickBooks/Xero/Sage → 'Accounting/Bookkeeping'\n"
        "5. UltraTax/Drake/Lacerte → 'Tax Preparation'\n"
        "6. Set confidence >= 0.85 for obvious professional tools\n"
        "\n"
        "Return ONLY a JSON array. Include: client, project, categories, confidence, needs_review, reasoning."
        "\n\n--- ORG CONTEXT ---\n" + org_context
    )

    last_text = None
    ai_suggestions = []
    
    # ✅ FIXED: Move the try/except so the processing code is reachable
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
        log(f"[AI] OpenAI error: {e}")
        if fallback_mode == "rule":
            return suggestions_today(request)
        # Return fallback response
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

    # ✅ Process AI suggestions and auto-save high-confidence results
    out = []
    N = min(len(blocks), len(ai_suggestions))
    saved_count = 0

    with transaction.atomic():
        for i in range(N):
            b = blocks[i]
            sug = ai_suggestions[i] if isinstance(ai_suggestions[i], dict) else {}
            
            # ✅ Try pre-classification first (CPA tools, emails, meetings)
            pre_class = pre_classify_obvious_categories(b)
            if pre_class:
                # Override AI suggestion with obvious classification
                sug["categories"] = pre_class.get("categories", sug.get("categories", {}))
                # Boost confidence if pre-classified
                sug["confidence"] = max(float(sug.get("confidence", 0)), pre_class.get("confidence", 0))
                if pre_class.get("reasoning"):
                    sug["reasoning"] = pre_class["reasoning"]
            
            confidence = float(sug.get("confidence", 0.0))
            needs_review = sug.get("needs_review", True)
            client_name = (sug.get("client") or "").strip()
            categories = sug.get("categories", {})
            
            # ✅ Auto-save if high confidence (>= 0.70)
            auto_saved = False
            if confidence >= 0.70 and categories:
                try:
                    # Double-check block doesn't already have categories (shouldn't happen due to filtering)
                    if not getattr(b, "category_hours", None) or not b.category_hours:
                        
                        # Create/get client if provided AND block doesn't have one
                        if client_name and not b.client:
                            client_obj, _ = Client.objects.get_or_create(
                                org=org,
                                name=client_name,
                                defaults={"is_active": True}
                            )
                            b.client = client_obj
                        
                        # Save categories
                        if categories and isinstance(categories, dict):
                            # Clean categories (ensure hours are floats)
                            clean_cats = {}
                            for k, v in categories.items():
                                try:
                                    clean_cats[str(k)] = float(v)
                                except (ValueError, TypeError):
                                    pass
                            
                            if clean_cats:
                                b.category_hours = clean_cats
                                
                                # Mark as AI-processed (if fields exist)
                                if hasattr(b, "ai_processed_at"):
                                    b.ai_processed_at = timezone.now()
                                if hasattr(b, "ai_confidence"):
                                    b.ai_confidence = confidence
                                
                                b.save()
                                auto_saved = True
                                saved_count += 1
                                
                                # Better logging
                                existing_client = getattr(b.client, "name", None)
                                log(f"[AI] Auto-saved block {b.id} → Client: {existing_client or client_name or 'none'} | Categories: {list(clean_cats.keys())} ({confidence:.2f})")
                
                except Exception as e:
                    log(f"[AI] Failed to auto-save block {b.id}: {e}")
            
            out.append({
                "block_id": b.id,
                "start": b.start,
                "end": b.end,
                "title": b.title,
                "ai_suggestion": {
                    "client": client_name or None,
                    "project": sug.get("project"),
                    "categories": categories,
                    "confidence": confidence,
                    "needs_review": needs_review,
                    "reasoning": sug.get("reasoning", ""),
                    "source": "ai_with_context",
                    "auto_saved": auto_saved,
                },
                "current_client": getattr(b.client, "name", None),
                "current_project": getattr(b.project, "name", None),
            })

    # ✅ Add already-categorized blocks to the response
    for b in already_categorized:
        out.append({
            "block_id": b.id,
            "start": b.start,
            "end": b.end,
            "title": b.title,
            "ai_suggestion": {
                "client": getattr(b.client, "name", None),
                "project": getattr(b.project, "name", None),
                "categories": b.category_hours or {},
                "confidence": 1.0,
                "needs_review": False,
                "reasoning": "Already categorized",
                "source": "existing",
                "auto_saved": False,
            },
            "current_client": getattr(b.client, "name", None),
            "current_project": getattr(b.project, "name", None),
        })

    if saved_count > 0:
        log(f"[AI] Auto-saved {saved_count}/{N} high-confidence classifications")

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
# @throttle_classes([UserRateThrottle])
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
    Summary rollup for managers / end-of-day review.

    Query:
      ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&user=<username>

    Response:
    {
      total_hours: float,
      by_client: [
        {
          client: "Client A",
          total_hours: 4.0,
          categories: { "Tax Prep": 1.0, "Email/Communication": 0.5, "Research": 1.0, "1040": 1.5 },
          entries: [<optional lightweight refs>]
        },
        ...
      ],
      by_status: { approved: x, pending: y, draft: z, rejected: w },
      entries_count: N,
      needs_review_count: M
    }
    """
    from django.db.models import Sum

    org = get_org_or_default(request)
    qs = TimecardEntry.objects.filter(org=org)

    if start_str := request.GET.get('start_date'):
        qs = qs.filter(date__gte=date_type.fromisoformat(start_str))
    if end_str := request.GET.get('end_date'):
        qs = qs.filter(date__lte=date_type.fromisoformat(end_str))
    if user_filter := request.GET.get('user'):
        qs = qs.filter(user=user_filter)

    total_hours = float(qs.aggregate(total=Sum('total_hours'))['total'] or 0.0)

    # status buckets
    def _sum(q, st):
        return float(q.filter(status=st).aggregate(total=Sum('total_hours'))['total'] or 0.0)

    by_status = {
        'approved': _sum(qs, 'approved'),
        'pending': _sum(qs, 'pending'),
        'draft': _sum(qs, 'draft'),
        'rejected': _sum(qs, 'rejected'),
    }

    # merge categories per client
    rollups = {}  # client_name -> { total_hours, categories{str->float}, entries[] }
    for e in qs.select_related('client'):
        cname = e.client.name if e.client else "Unknown"
        r = rollups.setdefault(cname, {"total_hours": 0.0, "categories": {}, "entries": []})
        r["total_hours"] += float(e.total_hours or 0.0)
        # merge JSON category_breakdown {name: hours}
        if isinstance(e.category_breakdown, dict):
            for k, v in e.category_breakdown.items():
                if not k:
                    continue
                r["categories"][k] = float(r["categories"].get(k, 0.0)) + float(v or 0.0)
        # (optional) keep a tiny reference for drill-downs
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
            "entries": v["entries"],  # keep or remove if you don't want it
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


date_type = dt.date


# tracker/views.py
from collections import defaultdict
from datetime import datetime as dt, time as dt_time, timedelta, timezone as dt_timezone
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import Block


@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([UIReadThrottle])
def timecards_summary_day(request):
    date_str   = request.GET.get("date") or None
    user_param = (request.GET.get("user") or "").strip()
    hostname   = request.GET.get("hostname") or None
    org        = get_org_or_default(request)

    # Optional compact (no LLM); best-effort
    try:
        compact_rawevents_into_blocks(
            user=user_param, hostname=hostname, org=org,
            start_utc=None, end_utc=None, day=date_str
        )
    except Exception:
        pass

    # Day window in UTC
    start_utc, end_utc = _start_end_of_local_day_utc(date_str)
    start_ms = _to_epoch_ms(start_utc)
    end_ms   = _to_epoch_ms(end_utc)

    # Base queryset
    qs = Block.objects.filter(start__gte=start_utc, start__lt=end_utc)
    if user_param:
        qs = qs.filter(user__username=user_param)
    if hostname:
        qs = qs.filter(hostname=hostname)

    # ✅ Keep legacy NULL-org rows in dev; be strict in prod
    if USE_AUTH and org:
        if settings.DEBUG:
            qs = qs.filter(Q(org=org) | Q(org__isnull=True))
        else:
            qs = qs.filter(org=org)

    blocks = list(qs.select_related("client", "project"))

    # ---------- aggregate ----------
    from collections import defaultdict

    def BucketAgg():
        return {
            "spans": [],                # list[(s_ms, e_ms)] — for per-bucket union
            "sum_minutes": 0,           # raw (pre-union) minutes; for category rescale
            "categories_hours": defaultdict(float),
        }

    buckets = defaultdict(BucketAgg)
    all_active_spans = []  # for header union + idle envelope

    for b in blocks:
        # Skip idle/AFK blocks completely
        if _is_idle_block(b):
            continue

        s_dt = getattr(b, "start", None)
        e_dt = getattr(b, "end", None)

        s_ms = _to_epoch_ms(s_dt)
        if e_dt:
            e_ms = _to_epoch_ms(e_dt)
        else:
            # conservative fallback when end missing
            e_ms = s_ms + _block_minutes_fallback(b) * 60_000 if s_ms else None

        if s_ms is None or e_ms is None:
            continue

        # clamp to day window
        if e_ms <= start_ms or s_ms >= end_ms:
            continue
        s_ms = max(s_ms, start_ms)
        e_ms = min(e_ms, end_ms)
        if e_ms <= s_ms:
            continue

        # header/envelope
        all_active_spans.append((s_ms, e_ms))

        client  = (getattr(b, "client_name", None) or getattr(getattr(b, "client", None), "name", "") or "").strip() or "Unassigned"
        project = (getattr(b, "project_name", None) or getattr(getattr(b, "project", None), "name", None))
        key = (client, project or "-")

        block_minutes = int((e_ms - s_ms) // 60_000)
        if block_minutes <= 0:
            continue

        # categories are HOURS — allocate proportionally for this block
        cats = getattr(b, "category_hours", {}) or {}
        if not isinstance(cats, dict) or not cats:
            cats = {"General": round(block_minutes / 60.0, 2)}
        else:
            numeric_cats = {str(k)[:120]: max(0.0, float(v or 0)) for k, v in cats.items()}
            tot = sum(numeric_cats.values())
            if tot <= 0:
                cats = {"General": round(block_minutes / 60.0, 2)}
            else:
                cats = {k: round((block_minutes * (v / tot)) / 60.0, 2) for k, v in numeric_cats.items()}

        agg = buckets[key]
        agg["spans"].append((s_ms, e_ms))
        agg["sum_minutes"] += block_minutes
        for kcat, h in cats.items():
            agg["categories_hours"][kcat] += float(h)

    # Header: active union across ALL included non-idle spans
    active_union_minutes = _union_minutes(all_active_spans)

    # Idle: envelope between first and last active span (NOT full 24h)
    if all_active_spans:
        first_ms = min(s for s, _ in all_active_spans)
        last_ms  = max(e for _, e in all_active_spans)
        envelope_minutes = int(max(0, (last_ms - first_ms) // 60_000))
        idle_minutes = max(0, envelope_minutes - active_union_minutes)
    else:
        idle_minutes = 0

    # Build rows: per-bucket UNION + rescale categories to union minutes
    out_rows = []
    for (client, project_key), agg in buckets.items():
        union_mins = _union_minutes(agg["spans"])
        sum_mins   = max(1, int(agg["sum_minutes"]))      # guard div-by-zero
        scale      = union_mins / float(sum_mins)
        cats_rescaled = {k: round(v * scale, 2) for k, v in agg["categories_hours"].items()}
        cats_rescaled = dict(sorted(cats_rescaled.items(), key=lambda kv: kv[0].lower()))

        out_rows.append({
            "client":  client,
            "project": (None if project_key == "-" else project_key),
            "minutes": union_mins,
            "hours":   round(union_mins / 60.0, 2),
            "categories": cats_rescaled,
        })

    out_rows.sort(key=lambda r: (r["client"].lower(), (r["project"] or "~zzz").lower()))

    return Response({
        "date": (parse_date(date_str) or localtime(timezone.now()).date()).isoformat(),
        "user": user_param or "",
        "total_hours": round(active_union_minutes / 60.0, 2),  # ACTIVE only
        "buckets": out_rows,                                   # per-bucket union
        "meta": {
            "count_blocks": len(blocks),
            "active_minutes": active_union_minutes,
            "idle_minutes": idle_minutes,   # envelope idle
            "stable": True,
        },
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


from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

def _to_float_or_none(v):
    # Accept numbers, numeric strings, and strings with trailing 'h' or 'hrs'
    if v is None:
        return None
    try:
        if isinstance(v, str):
            s = v.strip().lower().rstrip("h").rstrip("hrs").strip()
            if s == "":
                return None
            return float(s)
        return float(v)
    except Exception:
        return None

@api_view(["POST"])
@permission_classes([PermUI])   # or AllowAny while testing
@transaction.atomic
def save_block_classification(request, block_id: int):
    """
    POST: { client?: str, project?: str, task?: str, categories?: {name: hours(float)} }
    - Creates Client/Project if needed (within org)
    - Coerces category values to floats (hours)
    """
    b = get_object_or_404(Block, id=block_id)

    # Ensure org exists on the block
    org = getattr(b, "org", None)
    if org is None:
        org = get_org_or_default(request)
        try:
            # only set if Block has org FK field
            if any(f.name == "org" for f in Block._meta.fields):
                b.org = org
        except Exception:
            pass  # if no org field, ignore

    payload = request.data or {}
    client_name  = (payload.get("client")  or "").strip() or None
    project_name = (payload.get("project") or "").strip() or None
    categories   = payload.get("categories", {})

    # Attach/create Client
    client_obj = None
    if client_name:
        client_obj, _ = Client.objects.get_or_create(org=org, name=client_name)
        b.client = client_obj

    # Attach/create Project (requires client)
    if project_name:
        if client_obj is None:
            client_obj, _ = Client.objects.get_or_create(org=org, name="(General)")
            b.client = client_obj
        proj_obj, _ = Project.objects.get_or_create(org=org, client=client_obj, name=project_name)
        b.project = proj_obj

    # Coerce categories (hours)
    clean_categories = {}
    if categories is None or categories == {}:
        clean_categories = {}
    elif isinstance(categories, dict):
        for k, v in categories.items():
            f = _to_float_or_none(v)
            if f is None or f < 0:
                # don’t blow up; just skip bad entries
                continue
            clean_categories[str(k)] = f
    else:
        raise ValidationError({"categories": "Must be an object mapping {category: hours}."})

    if clean_categories:
        # Make sure Block has JSONField 'category_hours'
        if hasattr(b, "category_hours"):
            b.category_hours = clean_categories

    # Optional task
    task_name = (payload.get("task") or "").strip() or None
    if task_name:
        # Only if you use tasks per project; otherwise skip
        try:
            task_obj, _ = Task.objects.get_or_create(org=org, project=b.project, name=task_name)
            b.task = task_obj
        except Exception:
            # If your Task model requires project and it's missing, skip silently
            pass

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


# tracker/views.py - Enhanced version

@api_view(["POST"])
@permission_classes([PermUI])
def import_clients_csv(request):
    """
    Enhanced CSV import with validation.
    
    Supported columns:
      - client (required): Client name
      - code (optional): Short code (e.g., "ACME")
      - contact (optional): Contact person
      - email (optional): Email address
      - phone (optional): Phone number
      - project (optional): Default project name
      - active (optional): true/false (default: true)
      - billable (optional): true/false (default: true)
    """
    org = get_org_or_default(request)
    
    if 'file' not in request.FILES:
        raise ValidationError({"file": "Upload a CSV file."})

    f = request.FILES['file']
    try:
        text = f.read().decode('utf-8', errors='ignore')
    except Exception:
        text = f.read().decode('latin-1', errors='ignore')

    reader = csv.DictReader(io.StringIO(text))
    
    created = {"clients": 0, "projects": 0, "skipped": 0}
    errors = []
    
    for row_num, row in enumerate(reader, start=2):
        client_name = (row.get('client') or '').strip()
        
        if not client_name:
            errors.append(f"Row {row_num}: Missing client name")
            continue
        
        # Check if already exists
        existing = Client.objects.filter(org=org, name=client_name).first()
        if existing:
            created['skipped'] += 1
            continue
        
        # Parse active field
        active_str = str(row.get('active', 'true')).lower()
        is_active = active_str in ('1', 'true', 'yes', 'y')
        
        # Create client
        client = Client.objects.create(
            org=org,
            name=client_name,
            is_active=is_active
        )
        created['clients'] += 1
        
        # Optional: Create default project
        project_name = (row.get('project') or '').strip()
        if project_name:
            Project.objects.create(
                org=org,
                client=client,
                name=project_name,
                is_active=True
            )
            created['projects'] += 1

    return Response({
        "message": "Import complete",
        "clients": created['clients'],
        "projects": created['projects'],
        "skipped": created['skipped'],
        "errors": errors if errors else None
    })


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

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.conf import settings

from .models import AgentSession  # adjust import if needed

from django.conf import settings


from django.views.decorators.cache import cache_control
from django.views.decorators.vary import vary_on_headers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

# views.py
from django.views.decorators.cache import cache_control
from django.views.decorators.vary import vary_on_headers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

@api_view(["GET"])
@permission_classes([AllowAny])
@cache_control(private=True, max_age=300)
@vary_on_headers("Cookie")
def whoami(request):
    # 1) Agent header
    agent_key = (
        request.headers.get("X-Agent-Key")
        or request.headers.get("Agent-Key")
        or request.META.get("HTTP_X_AGENT_KEY")
        or request.META.get("HTTP_AGENT_KEY")
    )
    if agent_key:
        device = AgentDevice.objects.filter(api_key=agent_key, is_active=True).select_related("user").first()
        if device and device.user_id:
            u = device.user
            return Response({
                "is_authenticated": True,
                "auth_source": "agent",
                "username": (u.username or "").strip(),
                "user_id": u.pk,
                "host": (device.hostname or None),
                "device_id": device.device_id,
            })

    # 2) Django session
    if getattr(request.user, "is_authenticated", False):
        u = request.user
        return Response({
            "is_authenticated": True,
            "auth_source": "session",
            "username": (u.username or "").strip(),
            "user_id": u.pk,
            "host": None,
            "device_id": None,
        })

    # 3) Signed cookie (NOT a login)
    bundle = _signed_cookie_get(request, COOKIE_BUNDLE)
    if bundle and isinstance(bundle, dict):
        username = (bundle.get("username") or "").strip()
        host = (bundle.get("host") or "").strip() or None
        if username:
            return Response({
                "is_authenticated": False,        # <- important
                "auth_source": "cookie",
                "username": username,
                "user_id": None,
                "host": host,
                "device_id": None,
            })
    else:
        u = (request.COOKIES.get(COOKIE_USER_KEY) or "").strip()
        h = (request.COOKIES.get(COOKIE_HOST_KEY) or "").strip()
        if u:
            return Response({
                "is_authenticated": False,        # <- important
                "auth_source": "cookie_legacy",
                "username": u,
                "user_id": None,
                "host": (h or None),
                "device_id": None,
            })

    # 4) AgentSession by IP (NOT a login)
    ip = _client_ip(request)
    if ip:
        sess = (
            AgentSession.objects
            .filter(last_ip=ip)
            .select_related("user")
            .order_by("-last_seen")
            .only("hostname", "user__username", "user__id")
            .first()
        )
        if sess and getattr(sess, "user", None):
            return Response({
                "is_authenticated": False,        # <- important
                "auth_source": "ip",
                "username": (sess.user.username or "").strip(),
                "user_id": sess.user_id,
                "host": (getattr(sess, "hostname", None) or None),
                "device_id": None,
            })

    # 5) Unknown
    return Response({
        "is_authenticated": False,
        "auth_source": "unknown",
        "username": "",
        "user_id": None,
        "host": None,
        "device_id": None,
    })

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q
from .models import Block
from .serializers import BlockLiteSerializer

@api_view(["GET"])
@permission_classes([AllowAny])  # swap to IsAuthenticated once you wire auth
def recent_classified_blocks(request):
    """
    Returns latest classified Blocks (has ai_processed_at) for the last 48h,
    newest first. Optional ?limit=50 (default 25).
    Optional filter: ?me=1 to restrict to request.user.
    """
    limit = int(request.GET.get("limit", 25))
    qs = Block.objects.filter(
        ai_processed_at__isnull=False,
        ai_category__isnull=False,
    ).order_by("-ai_processed_at")

    # Example scoping by user (enable when auth is on)
    if request.GET.get("me") == "1" and request.user.is_authenticated:
        qs = qs.filter(user=request.user)

    # Optional: last 48h window
    since = timezone.now() - timezone.timedelta(hours=48)
    qs = qs.filter(ai_processed_at__gte=since)[:max(1, min(limit, 200))]

    return Response(BlockLiteSerializer(qs, many=True).data)


# tracker/views_public.py
import json
from django.utils import timezone
from django.contrib.auth.models import User, Group
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import AgentSession  # if you have it; safe to remove if not present

@api_view(["POST", "OPTIONS"])
@permission_classes([AllowAny])
def agents_hello(request):
    """
    Auto-provision user and upsert AgentSession.
    Tolerates partial schemas and sets cookies for SPA identity.
    """
    # headers first, JSON fallback
    username = (request.headers.get("X-Agent-User") or "").strip()
    host     = (request.headers.get("X-Agent-Host") or "").strip()
    plat     = (request.headers.get("X-Agent-Platform") or "").strip()
    ver      = (request.headers.get("X-Agent-Version") or "").strip()

    if not (username and host):
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

    grp, _ = Group.objects.get_or_create(name="Time Agents")
    user, created = User.objects.get_or_create(username=username, defaults={"is_active": True, "email": ""})
    if created:
        user.set_unusable_password()
        user.save()
    if not user.groups.filter(id=grp.id).exists():
        user.groups.add(grp)

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
    if "hostname" in sess_fields and "hostname" not in filter_kwargs:
        defaults["hostname"] = host

    AgentSession.objects.update_or_create(**filter_kwargs, defaults=defaults)

    try:
        AgentControl.objects.get_or_create(user=user, host=host)
    except Exception:
        pass

    resp = Response({
        "ok": True,
        "user_id": user.id,
        "username": user.username,
        "host": host,
        "stop": False,
        "stop_until": None,
    })
    secure = request.is_secure()
    resp.set_cookie("mavops_username", user.username, samesite="Lax", secure=secure, httponly=False)
    resp.set_cookie("mavops_host", host, samesite="Lax", secure=secure, httponly=False)
    return resp

@api_view(["POST", "OPTIONS"])
@permission_classes([AllowAny])
def browser_hello(request):
    """
    Lightweight browser-only handshake to set a signed identity hint cookie for /whoami.
    Body: { "username": "dan", "host": "MacBook-Pro" (optional) }

    NOTE: This NO LONGER creates shadow users. It's strictly a client hint.
    """
    if request.method == "OPTIONS":
        return Response(status=200)

    # Parse body safely
    try:
        body = request.data if isinstance(request.data, dict) else json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        body = {}

    username = (body.get("username") or "").strip()
    host = (body.get("host") or "").strip() or "browser"

    if not username:
        return Response({"ok": False, "error": "missing-username"}, status=400)

    # Build signed bundle cookie (HINT ONLY — not auth)
    bundle = {"username": username, "host": host, "ts": timezone.now().isoformat()}
    signed = signing.dumps(bundle)

    resp = Response({"ok": True, "username": username, "host": host, "source": "browser"})
    secure = request.is_secure()  # ensure True in prod behind HTTPS

    # Preferred: single signed cookie
    resp.set_cookie(
        COOKIE_BUNDLE,
        signed,
        max_age=60 * 60 * 24 * 14,  # 14 days
        samesite="Lax",
        secure=secure,
        httponly=False,  # SPA can read; it's only a hint
        path="/",
    )

    # (Optional) legacy plain cookies — safe to delete later
    resp.set_cookie(COOKIE_USER_KEY, username, samesite="Lax", secure=secure, httponly=False, path="/")
    resp.set_cookie(COOKIE_HOST_KEY, host,     samesite="Lax", secure=secure, httponly=False, path="/")

    return resp

# tracker/views.py
from django.core import signing
from django.utils import timezone

@api_view(["POST"])
@permission_classes([AllowAny])
def auth_login(request):
    """
    JSON login endpoint for SPA frontend.
    """
    data = request.data or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return Response({"ok": False, "error": "Username and password required."},
                        status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(request, username=username, password=password)
    if not user:
        return Response({"ok": False, "error": "Invalid credentials."},
                        status=status.HTTP_400_BAD_REQUEST)

    perform_login(request, user, email_verification=allauth_settings.EMAIL_VERIFICATION)

    # Build the same signed “hint” bundle cookie here (no need for /browser/hello/)
    host = request.get_host() or "browser"
    bundle = {"username": user.username, "host": host, "ts": timezone.now().isoformat()}
    signed = signing.dumps(bundle, salt="browser-ident-v1")

    resp = Response({"ok": True, "user": {"id": user.id, "username": user.username, "email": user.email or ""}})
    resp.set_cookie(COOKIE_USER_KEY, user.username, samesite="Lax", path="/")
    resp.set_cookie(COOKIE_HOST_KEY, host, samesite="Lax", path="/")
    resp.set_cookie(COOKIE_BUNDLE, signed, samesite="Lax", httponly=False, path="/")
    return resp


from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import logout as django_logout
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

# tracker/views.py
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.contrib.auth import logout as django_logout
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([SessionAuthentication])  # use session + CSRF
@ensure_csrf_cookie                                # set csrftoken if missing
@csrf_protect                                      # require + validate CSRF
def auth_logout(request):
    """
    Logs out the current session (if any). Requires CSRF.
    """
    django_logout(request)
    resp = Response({"ok": True})
    # Don’t delete the CSRF cookie; it’s useful for the next POST.
    resp.delete_cookie("sessionid", path="/")
    # If you previously set custom identity cookies, clear them:
    for cookie_name in ("mavops_username", "mavops_host", "mavops_ident"):
        resp.delete_cookie(cookie_name, path="/")
    return resp


@api_view(["POST"])
@permission_classes([AllowAny])
def auth_signup(request):
    """
    JSON signup endpoint (no email verification required).
    """
    data = request.data or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    email = (data.get("email") or "").strip()

    errors = {}
    if not username:
        errors["username"] = "Username is required."
    if not password or len(password) < 6:
        errors["password"] = "Password must be at least 6 characters."

    if errors:
        return Response({"ok": False, "errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username__iexact=username).exists():
        return Response(
            {"ok": False, "errors": {"username": "Username already taken."}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.create_user(username=username, email=email or None, password=password)
    perform_login(request, user, email_verification=allauth_settings.EMAIL_VERIFICATION)

    resp = Response(
        {
            "ok": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email or "",
            },
        }
    )
    resp.set_cookie("mavops_username", user.username, samesite="Lax")
    return resp

# views.py
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone

from .models import AgentDevice, AgentPairCode

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([PairIssueRate])
def agents_pair_issue(request):
    ttl = int(request.data.get("ttl_seconds") or 600)
    ttl = max(60, min(ttl, 3600))  # 1–60 min
    code_obj = AgentPairCode.issue(request.user, ttl_seconds=ttl)
    return Response({
        "ok": True,
        "code": code_obj.code,
        "expires_at": code_obj.expires_at.isoformat(),
        "ttl_seconds": ttl,
    }, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([PairClaimRate])
@transaction.atomic
def agents_pair_claim(request):
    data = request.data or {}
    code = (data.get("code") or "").strip().upper()
    device_id = (data.get("device_id") or "").strip()
    hostname = (data.get("hostname") or "unknown")[:128]
    platform_s = (data.get("platform") or "")[:128]
    version = (data.get("version") or "")[:32]

    if not code or not device_id:
        return Response({"ok": False, "error": "missing code or device_id"}, status=400)

    now = timezone.now()
    pc = (AgentPairCode.objects
          .select_for_update()
          .filter(code=code, consumed_at__isnull=True, expires_at__gt=now)
          .first())
    if not pc:
        return Response({"ok": False, "error": "invalid_or_expired_code"}, status=400)

    dev, _created = AgentDevice.objects.select_for_update().get_or_create(
        device_id=device_id,
        defaults={
            "user": pc.user,
            "hostname": hostname,
            "platform": platform_s,
            "app_version": version,
            "is_active": False,
        },
    )
    # If device belongs to another user, block
    if dev.user_id and dev.user_id != pc.user_id:
        return Response({"ok": False, "error": "device_belongs_to_another_user"}, status=409)

    # Link/refresh and rotate key
    if not dev.user_id:
        dev.user = pc.user
    if hostname:
        dev.hostname = hostname
    if platform_s:
        dev.platform = platform_s
    if version:
        dev.app_version = version

    dev.rotate_key()  # sets api_key, last_seen_at, is_active=True
    pc.consume()

    return Response({
        "ok": True,
        "api_key": dev.api_key,
        "username": pc.user.username,
        "hostname": dev.hostname,
    }, status=200)

# views.py (TEMP ONLY FOR DEV!)
@api_view(["POST"])
@permission_classes([AllowAny])
def agents_pair_issue_dev_open(request):
    code = AgentPairCode.issue(User.objects.first(), ttl_seconds=600)  # pick a test user
    return Response({"ok": True, "code": code.code, "expires_at": code.expires_at.isoformat(), "ttl_seconds": 600})



# tracker/views.py
# Add these 2 endpoints for current client management

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from .auth import AgentKeyAuthentication
from .models import Client, CurrentClient, Block

# ==============================================================================
# CURRENT CLIENT MANAGEMENT (Add these to your views.py)
# ==============================================================================

@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def set_current_client(request):
    """
    Set the current client for this device/user.
    NOW: Also retroactively assigns recent unassigned blocks.
    
    Body: {
      "client_id": int | null,
      "client_name": str | null
    }
    
    Pass null/empty to clear current client.
    """
    user = request.user
    device = getattr(request, "agent_device", None)
    data = request.data or {}
    
    client_id = data.get("client_id")
    client_name = data.get("client_name")
    
    # Get org
    org = user.groups.first()
    if not org:
        from django.contrib.auth.models import Group
        org, _ = Group.objects.get_or_create(name="default-org")
    
    # Handle clearing current client
    if not client_id and not client_name:
        CurrentClient.objects.filter(
            user=user,
            device_id=device.id if device else 0
        ).delete()
        
        return Response({
            "ok": True,
            "client_id": None,
            "client_name": None,
            "message": "Current client cleared"
        })
    
    # Resolve client
    client = None
    if client_id:
        try:
            client = Client.objects.get(id=client_id, org=org)
        except Client.DoesNotExist:
            return Response({"error": "Client not found"}, status=404)
    elif client_name:
        # Create client if it doesn't exist
        client, created = Client.objects.get_or_create(
            org=org,
            name=client_name,
            defaults={'is_active': True}
        )
    
    if not client:
        return Response({"error": "Must provide client_id or client_name"}, status=400)
    
    # Update or create CurrentClient
    CurrentClient.objects.update_or_create(
        user=user,
        device_id=device.id if device else 0,
        defaults={
            'client': client,
            'started_at': timezone.now(),
            'updated_at': timezone.now(),
        }
    )
    
    # ✅ NEW: Retroactively assign recent unassigned blocks using helper
    count = apply_current_client_to_recent_blocks(
        user=user,
        client=client,
        minutes_back=15,
        device_id=getattr(device, 'device_id', None) if device else None
    )
    
    return Response({
        "ok": True,
        "client_id": client.id,
        "client_name": client.name,
        "message": f"Set current client to {client.name}",
        "retroactive_blocks": count
    })


@api_view(["GET"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def get_current_client(request):
    """
    Get the current client for this device/user.
    Called by GUI on startup to restore state.
    
    Returns: {
      "client_id": int | null,
      "client_name": str | null,
      "started_at": timestamp | null
    }
    """
    user = request.user
    device = getattr(request, "agent_device", None)
    
    try:
        current = CurrentClient.objects.select_related('client').get(
            user=user,
            device_id=device.id if device else 0
        )
        
        return Response({
            "client_id": current.client_id,
            "client_name": current.client.name if current.client else None,
            "started_at": current.started_at.isoformat() if current.started_at else None,
            "updated_at": current.updated_at.isoformat() if current.updated_at else None,
        })
    except CurrentClient.DoesNotExist:
        return Response({
            "client_id": None,
            "client_name": None,
            "started_at": None,
            "updated_at": None,
        })


@api_view(["GET"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def list_clients(request):
    """
    List all clients for this user's org.
    Called by GUI to populate "Switch Client" menu.
    
    Returns: [
      {"id": 1, "name": "Acme Corp", "code": "ACME", "is_active": true},
      ...
    ]
    """
    user = request.user
    org = user.groups.first()
    
    if not org:
        from django.contrib.auth.models import Group
        org, _ = Group.objects.get_or_create(name="default-org")
    
    clients = Client.objects.filter(org=org, is_active=True).order_by('name')
    
    return Response([{
        "id": c.id,
        "name": c.name,
        "code": getattr(c, 'code', '') or c.name[:4].upper(),
        "is_active": c.is_active,
    } for c in clients])


@api_view(["GET"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def context_guess(request):
    """
    AI-powered client suggestion based on recent activity.
    
    Query params:
      - host: hostname (optional, from agent)
      - device_id: device UUID (optional)
    
    Returns: { client_id, client_name, confidence, reason }
    """
    user = request.user
    device = getattr(request, "agent_device", None)
    host = request.GET.get("host", "")
    device_id_param = request.GET.get("device_id", "")
    
    # Get recent blocks (last 10 minutes)
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(minutes=10)
    
    recent_blocks = Block.objects.filter(
        user=user,
        start__gte=cutoff
    ).order_by("-start")[:20]
    
    if not recent_blocks:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": 0.0,
            "reason": "No recent activity"
        })
    
    # Get user's clients
    org = user.groups.first()
    if not org:
        from django.contrib.auth.models import Group
        org, _ = Group.objects.get_or_create(name="default-org")
    
    clients = list(Client.objects.filter(org=org, is_active=True))
    if not clients:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": 0.0,
            "reason": "No clients defined"
        })
    
    # Simple matching logic
    scores = {}
    reasons = {}
    
    for client in clients:
        score = 0.0
        reason_parts = []
        
        # Check window titles for client name
        for block in recent_blocks:
            window_title = (getattr(block, "window_title", "") or "").lower()
            if client.name.lower() in window_title:
                score += 0.3
                reason_parts.append(f"Window title matches '{client.name}'")
                break
        
        # Check URLs for client name/domain
        for block in recent_blocks:
            url = (block.url or "").lower()
            if client.name.lower() in url:
                score += 0.4
                reason_parts.append(f"URL contains '{client.name}'")
                break
        
        # Check file paths
        for block in recent_blocks:
            file_path = (block.file_path or "").lower()
            if client.name.lower() in file_path:
                score += 0.2
                reason_parts.append(f"File path contains '{client.name}'")
                break
        
        # Check against KnownEntity aliases
        try:
            known = KnownEntity.objects.filter(
                org=org,
                entity_type="client",
                name=client.name
            ).first()
            
            if known and known.aliases:
                for alias in known.aliases:
                    for block in recent_blocks:
                        if alias.lower() in (getattr(block, "window_title", "") or "").lower():
                            score += 0.3
                            reason_parts.append(f"Alias '{alias}' matched")
                            break
        except:
            pass
        
        if score > 0:
            scores[client.id] = score
            reasons[client.id] = "; ".join(reason_parts[:2])
    
    # Find best match
    if not scores:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": 0.0,
            "reason": "No matches found"
        })
    
    best_client_id = max(scores, key=scores.get)
    best_score = scores[best_client_id]
    
    # Only suggest if confidence is reasonable
    if best_score < 0.45:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": best_score,
            "reason": "Confidence too low"
        })
    
    best_client = Client.objects.get(id=best_client_id)
    
    return Response({
        "client_id": best_client.id,
        "client_name": best_client.name,
        "confidence": min(best_score, 0.95),
        "reason": reasons.get(best_client_id, "Pattern match")
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def context_confirm(request):
    """
    User confirmed the AI suggestion.
    
    Body: {
      client_id: int,
      confidence: float,
      hostname: str,
      device_id: str,
      os_username: str,
      prompt_id: str (optional)
    }
    """
    user = request.user
    device = getattr(request, "agent_device", None)
    data = request.data or {}
    
    client_id = data.get("client_id")
    confidence = float(data.get("confidence", 0.0))
    
    if not client_id:
        return Response({"error": "client_id required"}, status=400)
    
    try:
        client = Client.objects.get(id=client_id)
    except Client.DoesNotExist:
        return Response({"error": "Client not found"}, status=404)
    
    # Get recent unassigned blocks (last 15 minutes)
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(minutes=15)
    
    recent_blocks = Block.objects.filter(
        user=user,
        start__gte=cutoff,
        client__isnull=True
    )
    
    # Assign them to this client
    count = recent_blocks.update(client=client)
    
    # Optional: Store feedback for ML training
    try:
        sample_block = recent_blocks.first()
        if sample_block:
            text_content = f"{sample_block.window_title or ''} | {sample_block.url or ''}"
            
            AITrainingExample.objects.create(
                org=client.org,
                text_content=text_content[:500],
                correct_client=client,
                correct_categories={"feedback_type": "confirm"},
                original_prediction={"confidence": confidence}
            )
    except:
        pass
    
    return Response({
        "ok": True,
        "client_id": client_id,
        "client_name": client.name,
        "blocks_updated": count,
        "message": f"Assigned {count} recent blocks to {client.name}"
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([IsAuthenticated])
def context_reject(request):
    """
    User rejected the AI suggestion.
    
    Body: {
      client_id: int,
      confidence: float,
      hostname: str,
      device_id: str,
      os_username: str,
      prompt_id: str (optional)
    }
    """
    user = request.user
    data = request.data or {}
    
    client_id = data.get("client_id")
    confidence = float(data.get("confidence", 0.0))
    
    # Store negative feedback for ML training
    try:
        client = Client.objects.get(id=client_id)
        
        # Get recent block context
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(minutes=5)
        
        recent_block = Block.objects.filter(
            user=user,
            start__gte=cutoff
        ).order_by("-start").first()
        
        if recent_block:
            text_content = f"{recent_block.window_title or ''} | {recent_block.url or ''}"
            
            AITrainingExample.objects.create(
                org=client.org,
                text_content=text_content[:500],
                correct_client=None,
                correct_categories={"feedback_type": "reject", "rejected_client": client.name},
                original_prediction={"confidence": confidence, "client_id": client_id}
            )
    except:
        pass
    
    return Response({
        "ok": True,
        "message": "Feedback recorded"
    })


# ============================================================================== 
# ADD THESE NEW VIEWS TO YOUR views.py
# ==============================================================================

@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([PermUI])  # ← Use this instead
def create_client(request):
    """
    Create a new client.
    
    Body: {
      "name": str,
      "code": str,
      "email": str (optional),
      "billable_rate": float (optional)
    }
    """
    user = request.user
    data = request.data or {}
    
    name = data.get("name", "").strip()
    code = data.get("code", "").strip()
    
    if not name:
        return Response({"error": "Client name is required"}, status=400)
    
    if not code:
        # Auto-generate code from name
        code = name[:10].upper().replace(" ", "")
    
    # Get org
    org = user.groups.first()
    if not org:
        from django.contrib.auth.models import Group
        org, _ = Group.objects.get_or_create(name="default-org")
    
    # Check if client already exists
    if Client.objects.filter(org=org, code=code).exists():
        return Response(
            {"error": f"Client with code '{code}' already exists"},
            status=400
        )
    
    # Create client
    client = Client.objects.create(
        org=org,
        name=name,
        code=code,
        is_active=True
    )
    
    return Response({
        "ok": True,
        "client": {
            "id": client.id,
            "name": client.name,
            "code": client.code,
            "is_active": client.is_active,
        },
        "message": f"Client '{name}' created successfully"
    }, status=201)


@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([PermUI])  # ← Use this instead
def import_clients_csv(request):
    """
    Import clients from CSV file.
    
    Expected CSV format:
    name,code,email,billable_rate
    Acme Corp,ACME,contact@acme.com,250
    Smith LLC,SMITH,info@smith.com,200
    """
    user = request.user
    
    if 'file' not in request.FILES:
        return Response({"error": "No file provided"}, status=400)
    
    csv_file = request.FILES['file']
    
    # Decode file
    try:
        decoded_file = csv_file.read().decode('utf-8')
    except UnicodeDecodeError:
        return Response(
            {"error": "Invalid file encoding. Please use UTF-8."},
            status=400
        )
    
    # Get org
    org = user.groups.first()
    if not org:
        from django.contrib.auth.models import Group
        org, _ = Group.objects.get_or_create(name="default-org")
    
    # Parse CSV
    import csv
    import io
    
    io_string = io.StringIO(decoded_file)
    reader = csv.DictReader(io_string)
    
    clients_created = 0
    clients_skipped = 0
    errors = []
    
    for row_num, row in enumerate(reader, start=2):
        try:
            name = row.get('name', '').strip()
            if not name:
                errors.append(f"Row {row_num}: Missing client name")
                clients_skipped += 1
                continue
            
            code = row.get('code', '').strip() or name[:10].upper().replace(" ", "")
            
            # Check if exists
            if Client.objects.filter(org=org, code=code).exists():
                clients_skipped += 1
                continue
            
            # Create client
            Client.objects.create(
                org=org,
                name=name,
                code=code,
                is_active=True
            )
            
            clients_created += 1
            
        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")
            clients_skipped += 1
    
    return Response({
        "ok": True,
        "clients": clients_created,
        "skipped": clients_skipped,
        "errors": errors,
        "message": f"Successfully imported {clients_created} clients ({clients_skipped} skipped)"
    })


@api_view(["GET"])  # ← Change from POST to GET
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([PermUI])
def user_profile(request):
    """
    Get current user profile with onboarding status.
    
    Returns: {
      "id": int,
      "email": str,
      "username": str,
      "onboarding_completed": bool,
      "organization": {...}
    }
    """
    user = request.user
    
    # Get org
    org = user.groups.first()
    
    return Response({
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        # Check if user has onboarding_completed field, default to True for existing users
        "onboarding_completed": getattr(user, 'onboarding_completed', True),
        "organization": {
            "id": org.id if org else None,
            "name": org.name if org else None,
        }
    })


@api_view(["POST"])
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([PermUI])  # ← Use this instead
def complete_onboarding(request):
    """
    Mark user's onboarding as complete.
    Called when user finishes onboarding wizard.
    """
    user = request.user
    
    # Set onboarding_completed flag
    if hasattr(user, 'onboarding_completed'):
        user.onboarding_completed = True
        user.save()
    
    return Response({
        "ok": True,
        "message": "Onboarding completed"
    })


@api_view(["GET"])  # ← Change from POST to GET
@authentication_classes([SessionAuthentication, AgentKeyAuthentication])
@permission_classes([PermUI])
def today_time(request):
    """
    Get today's tracked time organized by client → category.
    Uses union-of-spans to avoid double-counting overlapping blocks.
    """
    from datetime import date
    from collections import defaultdict
    
    user = request.user
    today = date.today()
    
    # Get ALL blocks for today
    blocks = Block.objects.filter(
        user=user,
        day=today
    ).select_related('client').order_by('start')
    
    # Helper: union of time spans (avoid overlaps)
    def union_minutes(spans):
        if not spans:
            return 0
        ranges = []
        for s in spans:
            if s['start'] and s['end']:
                start_ms = int(s['start'].timestamp() * 1000)
                end_ms = int(s['end'].timestamp() * 1000)
                if start_ms < end_ms:
                    ranges.append((start_ms, end_ms))
        
        ranges.sort()
        total_ms = 0
        cur_start, cur_end = -1, -1
        
        for start, end in ranges:
            if cur_start < 0:
                cur_start, cur_end = start, end
                continue
            if start <= cur_end:
                if end > cur_end:
                    cur_end = end
            else:
                total_ms += cur_end - cur_start
                cur_start, cur_end = start, end
        
        if cur_start >= 0:
            total_ms += cur_end - cur_start
        
        return total_ms / 60000  # Convert to minutes
    
    # Group by client → category
    data = defaultdict(lambda: {
        'client_id': None,
        'client_name': None,
        'categories': defaultdict(lambda: {'spans': [], 'count': 0, 'samples': []})
    })
    
    for block in blocks:
        client_name = block.client.name if block.client else 'Unassigned'
        client_id = block.client.id if block.client else None
        category = block.ai_category or 'Uncategorized'
        
        data[client_name]['client_id'] = client_id
        data[client_name]['client_name'] = client_name
        
        cat_data = data[client_name]['categories'][category]
        cat_data['spans'].append({'start': block.start, 'end': block.end})
        cat_data['count'] += 1
        
        # Sample activities (max 3)
        if len(cat_data['samples']) < 3:
            title = block.window_title or block.url or block.app_name or 'Unknown'
            if len(title) > 60:
                title = title[:57] + '...'
            cat_data['samples'].append(title)
    
    # Calculate union minutes for each category
    result = []
    for client_name, client_data in sorted(data.items()):
        categories = []
        total_client_minutes = 0
        
        for cat_name, cat_data in sorted(client_data['categories'].items()):
            minutes = union_minutes(cat_data['spans'])
            total_client_minutes += minutes
            
            categories.append({
                'name': cat_name,
                'hours': round(minutes / 60, 2),
                'block_count': cat_data['count'],
                'sample_activities': cat_data['samples']
            })
        
        result.append({
            'client_id': client_data['client_id'],
            'client': client_name,
            'total_hours': round(total_client_minutes / 60, 2),
            'categories': categories
        })
    
    return Response(result)