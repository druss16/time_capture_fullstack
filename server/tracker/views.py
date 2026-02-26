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
from django.contrib.auth import authenticate, login, get_user_model, logout as django_logout
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Sum, Q
from django.db.models.functions import TruncHour
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.timezone import localtime
from django.views.decorators.csrf import csrf_exempt  # only if used
from django.views.decorators.http import require_http_methods



# --- DRF ---
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated, BasePermission
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle
from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView  # ← ADD THIS LINE

# In your views file
from tracker.services.compaction import compact_rawevents_into_blocks


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

from django.contrib.auth.models import User
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
import secrets

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
    AgentRegistration, 
    OrgInstallToken,
    OrgProfile,
    Organization,

)
from tracker.permissions import AgentKeyPermission, NoAuth, PermUI
from tracker.rules import apply_rules
from tracker.serializers import RawEventSerializer
from tracker.auth import AgentKeyAuthentication
from tracker.utils import (
    _client_ip,
    infer_task_for_block,
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
from .models import RawEvent, CurrentClient, Client, BillingRate, Timesheet, Block, BlockAuditLog, Client, TaskType, Organization, OrganizationMembership

# If you need a User class reference:
User = get_user_model()

import logging
logger = logging.getLogger(__name__)

def log(msg: str):
    """Simple logging helper"""
    logger.info(msg)
    print(msg)  # Also print for immediate visibility


from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.db import transaction
from datetime import timedelta, date

from tracker.models import Block, Client, UserWorkPattern
from tracker.services.pattern_learning import PatternLearningService

from rest_framework import viewsets, status
from django.db.models import Sum, F, Q, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal


from .serializers_billing import (
    BillingRateSerializer, TimesheetSummarySerializer, TimesheetDetailSerializer,
    ApprovalQueueItemSerializer, ClientSummarySerializer, BlockAuditLogSerializer,
    InvoiceExportSerializer
)

# ADD THESE IMPORTS AT TOP OF views.py:
from tracker.industry_categories import (
    INDUSTRY_CHOICES,
    INDUSTRY_TYPES,
    get_categories_for_industry,
    get_combined_tool_detection,
    get_task_types_for_industry,
    get_seasonal_context_for_industry,
    build_ai_prompt_for_industry,
)

from tracker.utils.display_formatter import (
    format_block_for_display,
    format_blocks_grouped,
    format_duration,
    clean_window_title,
)

def match_client_in_text(text: str, clients: list, known_entities: list = None) -> list:
    """
    Smart client matching that handles various naming patterns.
    
    Returns: [(client, score, reason), ...] sorted by score descending
    """
    if not text:
        return []
    
    text_lower = text.lower()
    matches = []
    
    for client in clients:
        score = 0.0
        reasons = []
        client_name = client.name or ""
        client_name_lower = client_name.lower()
        
        # 1. Exact full name match (highest confidence)
        if client_name_lower and client_name_lower in text_lower:
            score += 0.50
            reasons.append(f"Exact match '{client_name}'")
        
        # 2. First word match (e.g., "Aurelia" from "Aurelia LLC")
        #    Only if first word is 3+ chars and not generic
        first_word = client_name.split()[0].lower() if client_name else ""
        generic_words = {'the', 'and', 'inc', 'llc', 'corp', 'ltd', 'company', 'co', 'group'}
        
        if (first_word 
            and len(first_word) >= 3 
            and first_word not in generic_words
            and first_word in text_lower
            and client_name_lower not in text_lower):  # Don't double-count
            score += 0.40
            reasons.append(f"First word '{first_word}'")
        
        # 3. Client code match (e.g., "ACME" in filename)
        client_code = (getattr(client, 'code', '') or '').lower()
        if client_code and len(client_code) >= 2 and client_code in text_lower:
            # Make sure it's a word boundary match to avoid false positives
            import re
            if re.search(rf'\b{re.escape(client_code)}\b', text_lower):
                score += 0.35
                reasons.append(f"Code match '{client_code}'")
        
        # 4. Each significant word in client name (for multi-word names)
        #    e.g., "Smith & Associates" - look for "smith" and "associates"
        words = [w.lower() for w in client_name.split() if len(w) >= 4 and w.lower() not in generic_words]
        word_matches = sum(1 for w in words if w in text_lower)
        if word_matches > 0 and len(words) > 0:
            word_score = 0.25 * (word_matches / len(words))
            if word_score > 0 and score < 0.50:  # Don't add if already matched fully
                score += word_score
                matched_words = [w for w in words if w in text_lower]
                reasons.append(f"Words: {', '.join(matched_words)}")
        
        # 5. Check aliases from KnownEntity
        if known_entities:
            for entity in known_entities:
                if entity.name == client.name and entity.aliases:
                    for alias in entity.aliases:
                        alias_lower = (alias or '').lower()
                        if alias_lower and len(alias_lower) >= 2 and alias_lower in text_lower:
                            score += 0.45
                            reasons.append(f"Alias '{alias}'")
                            break
        
        if score > 0:
            matches.append((client, score, '; '.join(reasons)))
    
    # Sort by score descending
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches


def extract_domain_from_url(url: str) -> str:
    """Extract clean domain from URL."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = (parsed.netloc or '').lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except:
        return ""

# ============================================================================
# CONFIGURATION: Available Categories
# ============================================================================

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

# Add this class right after imports, before your view functions
# Replace IsOrgAdmin in tracker/views.py
# This uses your existing OrganizationMembership model

from tracker.models import OrganizationMembership

class IsOrgAdmin(BasePermission):
    """
    Check if user is owner/admin/manager of their organization.
    Uses OrganizationMembership for per-org role control.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        # Superusers can access everything
        if request.user.is_superuser:
            return True
        
        # Get user's organization (Organization model, not Group)
        user_org = get_user_org(request.user)
        if not user_org:
            return False
        
        # Check OrganizationMembership role
        try:
            membership = OrganizationMembership.objects.get(
                user=request.user,
                organization=user_org  # ✅ Now passing Organization instance
            )
            # Owner, admin, or manager can access settings
            return membership.role in ['owner', 'admin', 'manager']
        except OrganizationMembership.DoesNotExist:
            # Fallback for users without membership yet
            return request.user.is_staff


# Update helper functions:
# Helper to get user's org
def get_user_org(user):
    """Get the user's Organization from OrganizationMembership."""
    try:
        membership = OrganizationMembership.objects.filter(user=user).first()
        if membership:
            return membership.organization
        return None
    except Exception as e:
        print(f"Error in get_user_org: {e}")
        return None

def get_monday(d):
    """Get Monday of the week containing date d"""
    return d - timedelta(days=d.weekday())

def get_user_role(user, organization):
    """Get user's role in an organization"""
    if user.is_superuser:
        return 'owner'
    
    try:
        membership = OrganizationMembership.objects.get(
            user=user,
            organization=organization
        )
        return membership.role
    except OrganizationMembership.DoesNotExist:
        if user.is_staff:
            return 'admin'
        return 'member'


def is_org_owner(user, organization):
    """Check if user is owner of the organization"""
    if user.is_superuser:
        return True
    
    try:
        membership = OrganizationMembership.objects.get(
            user=user,
            organization=organization
        )
        return membership.role == 'owner'
    except OrganizationMembership.DoesNotExist:
        return False

def is_org_admin_or_owner(user, organization):
    """Check if user is owner or admin"""
    if user.is_superuser:
        return True
    
    try:
        membership = OrganizationMembership.objects.get(
            user=user,
            organization=organization
        )
        return membership.role in ['owner', 'admin']
    except OrganizationMembership.DoesNotExist:
        return False


######
# AFTER ORG ADMIN
######

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
        org = get_user_org(request.user)
    else:
        org = None
    if not org:
        org, _ = Organization.objects.get_or_create(
            name="default-org",
            defaults={"slug": "default-org"}
        )
    return org



@api_view(["GET"])
@permission_classes([AllowAny])
def get_csrf(request):
    """
    Return CSRF token in response body (for browsers that block cookies).
    """
    from django.middleware.csrf import get_token
    
    # Generate token
    csrf_token = get_token(request)
    
    resp = Response({
        "ok": True,
        "csrfToken": csrf_token  # ← Return in body
    })
    
    # Still try to set cookie (for browsers that allow it)
    resp.set_cookie(
        key='csrftoken',
        value=csrf_token,
        max_age=31449600,
        secure=True,
        httponly=False,
        samesite='None',
        path='/',
    )
    
    return resp

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


def build_classification_prompt(text_blocks, org_context):
    from tracker.industry_categories import build_classification_user_prompt
    return build_classification_user_prompt(text_blocks, org_context)



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
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import json

# NEW: paired hello (device-key)
# NEW: paired hello (device-key)
@api_view(["POST"])
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

# tracker/views_raw_events.py
"""
UPDATED raw_events endpoint that triggers compaction immediately.

Replace your existing raw_events view with this version.
"""

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from tracker.auth import AgentKeyAuthentication
from tracker.models import RawEvent, CurrentClient, Client

import logging
logger = logging.getLogger(__name__)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def raw_events(request):
    """
    Ingest events from a paired agent.
    NOW: Auto-tags events with current client AND triggers compaction immediately.
    
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
                device_id=device.id if device else None,
                current_client_id=item.get("current_client_id") or current_client_id,  # ← Prefer agent payload

            )
            
            created += 1
        except Exception as e:
            errors.append({"item": item, "error": str(e)})
    
    # ✅ NEW: Trigger compaction immediately after ingesting events
    if created > 0:
        try:
            from tracker.services.compaction import compact_recent_events
            
            # Run quick compaction for recent events (last 15 minutes)
            blocks_created = compact_recent_events(
                user=agent_user,
                hostname=hostname,
                minutes_back=15
            )
            
            logger.info(
                f"[INGEST] Created {created} events → {blocks_created} blocks "
                f"for {agent_user.username}@{hostname}"
            )
            
        except Exception as e:
            logger.error(f"[INGEST] Compaction failed: {e}", exc_info=True)
            # Don't fail the request if compaction fails
    
    status_code = (
        status.HTTP_201_CREATED if created and not errors
        else status.HTTP_207_MULTI_STATUS if created and errors
        else status.HTTP_400_BAD_REQUEST
    )
    
    response = {
        "created": created,
        "errors": errors,
        "current_client": current_client_name
    }
    
    # Add blocks_created to response if compaction ran
    if created > 0:
        try:
            response["blocks_created"] = blocks_created
        except NameError:
            pass
    
    return Response(response, status=status_code)


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


# tracker/utils.py (or wherever your compact function lives)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def blocks_today(request):
    date_str  = request.GET.get("date") or None
    username  = request.GET.get("user") or None
    hostname  = request.GET.get("hostname") or None
    limit_str = request.GET.get("limit") or None
    
    org = get_org_or_default(request)
    
    compact_rawevents_into_blocks(user=username, hostname=hostname, org=org)
    
    start_utc, end_utc = _start_end_of_local_day_utc(date_str)
    qs = Block.objects.filter(start__gte=start_utc, start__lt=end_utc).order_by("start")
    
    if username:
        qs = qs.filter(user__username=username)
    if hostname:
        qs = qs.filter(hostname=hostname)
    
    # Match your dev/prod org scoping
    if USE_AUTH and org:
        if settings.DEBUG:
            qs = qs.filter(Q(org=org) | Q(org__isnull=True))
        else:
            qs = qs.filter(org=org)
    
    if limit_str:
        try: 
            qs = qs[:max(1, min(int(limit_str), 1000))]
        except Exception: 
            pass
    
    def _minutes(b: Block) -> int:
        m = getattr(b, "minutes", None)
        if isinstance(m, (int, float)):
            try: 
                return int(m)
            except Exception: 
                pass
        try:
            if not b.end or not b.start: 
                return 0
            return max(0, int((b.end - b.start).total_seconds() // 60))
        except Exception:
            return 0
    
    data = []
    for b in qs.select_related("client", "project", "task", "user"):
        idle = _is_idle_block(b)
        win_title = getattr(b, "window_title", "") or ""
        if idle:
            win_title = "Uncategorized - Idle"
        
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
            "app_name": getattr(b, "app_name", "") or "",
            "bundle_id": getattr(b, "bundle_id", "") or "",
            "is_idle": _is_idle_block(b),
            
            # ✅ ADD: Include categorization status (useful for UI)
            "is_categorized": getattr(b, "is_categorized", False),
            "categorized_by": getattr(b, "categorized_by", None),
            "category_hours": getattr(b, "category_hours", {}),
        })
    
    return Response(data)

from django.db.models import Q


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
# UPDATED: AI-Enhanced Suggestions (context-aware)
# Prioritizes Development/Consulting patterns over CPA patterns
# -------------------------------------------------------------------
def pre_classify_obvious_categories(block, industry_type='general') -> dict:
    """
    Pre-classify obvious patterns before AI runs.
    NOW USES INDUSTRY-SPECIFIC TOOL DETECTION!
    """
    from tracker.industry_categories import get_combined_tool_detection
    
    title = (getattr(block, "window_title", "") or getattr(block, "title", "") or "").lower()
    url = (block.url or "").lower()
    app_name = (getattr(block, "app_name", "") or "").lower()
    file_path = (block.file_path or "").lower()
    
    # Calculate block duration in hours
    if block.end and block.start:
        hours = round((block.end - block.start).total_seconds() / 3600, 2)
    elif hasattr(block, 'minutes') and block.minutes:
        hours = round(block.minutes / 60.0, 2)
    else:
        hours = 0.1
    
    combined_text = f"{title} {url} {app_name} {file_path}"
    
    # MEETINGS (universal - all industries)
    meeting_apps = ['zoom', 'teams', 'meet', 'slack', 'webex', 'discord', 'skype']
    meeting_domains = ['zoom.us', 'meet.google.com', 'teams.microsoft.com']
    
    if any(app in app_name for app in meeting_apps):
        return {'categories': {'Meetings': hours}, 'confidence': 0.90, 'reasoning': f'Meeting app: {app_name}'}
    
    if any(domain in url for domain in meeting_domains):
        return {'categories': {'Meetings': hours}, 'confidence': 0.85, 'reasoning': 'Meeting URL detected'}
    
    # INDUSTRY-SPECIFIC TOOL DETECTION
    tool_detection = get_combined_tool_detection(industry_type)
    
    for tool_key, tool_config in tool_detection.items():
        keywords = tool_config.get('keywords', [])
        domains = tool_config.get('domains', [])
        category = tool_config.get('category', 'Administration')
        confidence = tool_config.get('confidence', 0.80)
        
        if any(keyword in combined_text for keyword in keywords):
            return {'categories': {category: hours}, 'confidence': confidence, 'reasoning': f'{category} via {tool_key}'}
        
        if any(domain in url for domain in domains):
            return {'categories': {category: hours}, 'confidence': confidence, 'reasoning': f'{category} from URL'}
    
    # EMAIL (universal)
    email_indicators = ["mail.google.com", "outlook.office.com", "inbox", "compose"]
    if any(indicator in combined_text for indicator in email_indicators):
        return {'categories': {'Email/Communication': hours}, 'confidence': 0.90, 'reasoning': 'Email activity'}
    
    return {}


from tracker.services.pattern_learning import PatternLearningService

# tracker/views.py - COMPLETE ai_suggestions_today function
# ============================================================
# REPLACE your existing ai_suggestions_today function with this entire block
# ============================================================

from tracker.services.pattern_learning import PatternLearningService

@api_view(["GET"])
@permission_classes([PermUI])
@throttle_classes([AIGenerateThrottle])
def ai_suggestions_today(request):
    """
    Generate AI-powered suggestions for today's blocks.
    
    GUARANTEES:
    ✅ Categorized blocks NEVER change (is_categorized=True is permanent)
    ✅ Only uncategorized blocks get AI suggestions
    ✅ Auto-saves high-confidence results (>= 0.70)
    ✅ No duplicates (event-centric compaction)
    ✅ No flip-flopping (once saved, never touched again)
    ✅ Clean display formatting (App - Context format)
    """
    # Import display formatter
    from tracker.utils.display_names import format_block_for_display, format_duration
    
    # Toggles
    username = request.GET.get("user") or None
    hostname = request.GET.get("hostname") or None
    limit = int(request.GET.get("limit") or 120)
    limit = max(1, min(limit, 200))
    timeout_ms = int(request.GET.get("timeout_ms") or 15000)
    noai = request.GET.get("noai") in ("1", "true", "yes")
    fallback_mode = request.GET.get("fallback") or ""
    debug = request.GET.get("debug") in ("1", "true", "yes")

    org = get_org_or_default(request)

    # =========================================================
    # STEP 1: Compact any new unlinked events into blocks
    # This only processes events where block__isnull=True
    # Existing blocks are NEVER touched
    # =========================================================
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

    # =========================================================
    # STEP 2: Split blocks into categorized vs uncategorized
    # Categorized blocks are NEVER sent to AI
    # =========================================================
    blocks_needing_ai = []
    already_categorized = []

    for b in all_blocks:
        if b.is_categorized:
            # This block is DONE - never touch it again
            already_categorized.append(b)
        else:
            blocks_needing_ai.append(b)

    log(f"[AI] {len(already_categorized)} blocks already categorized (LOCKED), {len(blocks_needing_ai)} need AI")

    # =========================================================
    # STEP 3: If everything is categorized, return immediately
    # No AI call needed - these blocks are permanent
    # =========================================================
    if not blocks_needing_ai:
        out = []
        for b in already_categorized:
            # Get category for display
            cat_name = list((b.category_hours or {}).keys())[0] if b.category_hours else None
            client_name = getattr(b.client, "name", None)
            
            # ✅ Clean display formatting
            formatted = format_block_for_display({
                'app_name': getattr(b, 'app_name', '') or '',
                'window_title': getattr(b, 'window_title', '') or '',
                'url': getattr(b, 'url', '') or '',
                'minutes': b.minutes or 0,
                'category': cat_name,
            }, client_name=client_name)
            
            out.append({
                "block_id": b.id,
                "start": b.start,
                "end": b.end,
                "title": b.title,
                "ai_suggestion": {
                    "client": client_name,
                    "project": getattr(b.project, "name", None),
                    "categories": b.category_hours or {},
                    "confidence": 1.0,
                    "needs_review": False,
                    "reasoning": "Already categorized (locked)",
                    "source": "existing",
                    "auto_saved": False,
                },
                # ✅ Clean display data for UI
                "display": {
                    "title": formatted['title'],
                    "app": formatted['app'],
                    "duration": formatted['duration'],
                    "category_icon": formatted['category_icon'],
                },
                "current_client": client_name,
                "current_project": getattr(b.project, "name", None),
            })
        return Response(out)

    # Only process uncategorized blocks
    blocks = blocks_needing_ai

    # Get user object for pattern learning
    user_obj = None
    if username:
        try:
            user_obj = User.objects.get(username=username)
        except User.DoesNotExist:
            pass

    # Trim payload for AI
    def _shorten(s: str, n: int = 180) -> str:
        s = (s or "").strip()
        return s[:n] + ("…" if len(s) > n else "")

    MAX_BLOCKS = limit
    trimmed = []
    for b in blocks[:MAX_BLOCKS]:
        minutes = int((b.end - b.start).total_seconds() / 60) if b.end else 0
        hints = getattr(b, "hints", {}) or {}
        
        # Add learned pattern hints to each block
        pattern_hints = []
        if user_obj:
            learned_patterns = PatternLearningService.get_patterns_for_block(b, user_obj)
            for client_name, category, confidence in learned_patterns:
                if client_name or category:
                    pattern_hints.append({
                        "client": client_name,
                        "category": category,
                        "confidence": round(confidence, 2)
                    })
        
        trimmed.append({
            "id": str(b.id),
            "title": _shorten(b.title, 160),
            "window_title": _shorten(getattr(b, 'window_title', ''), 160),
            "url": _shorten(b.url, 140),
            "file_path": _shorten(b.file_path, 140),
            "app_name": _shorten(getattr(b, 'app_name', ''), 80),
            "bundle_id": _shorten(getattr(b, 'bundle_id', ''), 100),
            "minutes": minutes,
            "attendees": getattr(b, 'attendees', []) or [],
            "description": _shorten(getattr(b, 'description', ''), 220),
            "hints": hints,
            "learned_patterns": pattern_hints,
            "assigned_client": getattr(b.client, "name", None),  # ← what the agent set

        })

    # Build comprehensive context for AI
    org_context = build_ai_context(org) or ""
    #seasonal_context = get_seasonal_context()
    
    # Add learned user patterns
    pattern_context = ""
    if user_obj:
        pattern_context = PatternLearningService.build_pattern_context(user_obj, org)

    if debug:
        return Response({
            "debug": True,
            "count": len(trimmed),
            "sample": trimmed[:3],
            "org_context": org_context[:1200] if org_context else "",
            "seasonal_context": get_seasonal_context_for_industry(industry_type)[:500],
            "pattern_context": pattern_context[:500],
            "already_categorized": len(already_categorized),
            "needs_ai": len(blocks_needing_ai),
        })

    # =========================================================
    # NOAI MODE: Return blocks without calling AI
    # =========================================================
    if noai:
        out = []
        for b in blocks[:len(trimmed)]:
            client_name = getattr(b.client, "name", None)
            
            # ✅ Clean display formatting
            formatted = format_block_for_display({
                'app_name': getattr(b, 'app_name', '') or '',
                'window_title': getattr(b, 'window_title', '') or '',
                'url': getattr(b, 'url', '') or '',
                'minutes': b.minutes or 0,
                'category': None,
            }, client_name=client_name)
            
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
                # ✅ Clean display data
                "display": {
                    "title": formatted['title'],
                    "app": formatted['app'],
                    "duration": formatted['duration'],
                    "category_icon": formatted['category_icon'],
                },
                "current_client": client_name,
                "current_project": getattr(b.project, "name", None),
            })
        return Response(out)

    # =========================================================
    # OpenAI API Call
    # =========================================================
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

    # =========================================================
    # Build AI prompts — single source of truth
    # =========================================================
    from tracker.industry_categories import (
        build_ai_prompt_for_industry,
        build_classification_user_prompt,
    )

    industry_type = getattr(org, 'industry_type', 'general') or 'general'

    # System prompt: categories + rules + seasonal (all from industry_categories.py)
    system_msg = build_ai_prompt_for_industry(industry_type)

    # Append org-specific context (clients, aliases, training examples)
    if org_context:
        system_msg += "\n\n=== ORGANIZATION CONTEXT ===\n" + org_context

    # Append learned user patterns (from PatternLearningService)
    if pattern_context:
        system_msg += "\n\n=== LEARNED PATTERNS ===\n" + pattern_context

    last_text = None
    ai_suggestions = []

    # Scale model params to batch size
    if len(trimmed) <= 3:
        model = "gpt-4o-mini"
        max_tokens = 1000
    else:
        model = "gpt-4o-mini"
        max_tokens = 4000

    try:
        resp = client.chat.completions.create(
            model=model,              # ← was hardcoded "gpt-4o-mini"
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens,    # ← was hardcoded 4000
        )
        last_text = (resp.choices[0].message.content or "").strip()
        raw_json = _extract_json(last_text)
        ai_suggestions = _json_loads_loose(raw_json)
        if not isinstance(ai_suggestions, list):
            raise ValueError("Model did not return a JSON array.")

        # ✅ Fix AI category name mistakes before saving
        from tracker.industry_categories import validate_and_fix_ai_response
        ai_suggestions = validate_and_fix_ai_response(ai_suggestions, industry_type)
    except Exception as e:
        log(f"[AI] OpenAI error: {e}")
        if fallback_mode == "rule":
            return suggestions_today(request)
        
        # =========================================================
        # FALLBACK: Return blocks with error info
        # =========================================================
        out = []
        for b in blocks[:len(trimmed)]:
            client_name = getattr(b.client, "name", None)
            
            # ✅ Clean display formatting
            formatted = format_block_for_display({
                'app_name': getattr(b, 'app_name', '') or '',
                'window_title': getattr(b, 'window_title', '') or '',
                'url': getattr(b, 'url', '') or '',
                'minutes': b.minutes or 0,
                'category': None,
            }, client_name=client_name)
            
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
                # ✅ Clean display data
                "display": {
                    "title": formatted['title'],
                    "app": formatted['app'],
                    "duration": formatted['duration'],
                    "category_icon": formatted['category_icon'],
                },
                "current_client": client_name,
                "current_project": getattr(b.project, "name", None),
            })
        return Response(out, status=200)

    # =========================================================
    # STEP 4: Process AI suggestions and auto-save
    # CRITICAL: Only save if is_categorized=False
    # Once saved, the block is LOCKED forever
    # =========================================================
    out = []
    N = min(len(blocks), len(ai_suggestions))
    saved_count = 0

    with transaction.atomic():
        for i in range(N):
            b = blocks[i]
            sug = ai_suggestions[i] if isinstance(ai_suggestions[i], dict) else {}
            
            
            confidence = float(sug.get("confidence", 0.0))
            needs_review = sug.get("needs_review", True)
            client_name = (sug.get("client") or "").strip()
            categories = sug.get("categories", {})
            
            # =========================================================
            # AUTO-SAVE: Only if confidence >= 0.70 AND not categorized
            # =========================================================
            auto_saved = False
            if confidence >= 0.70 and categories:
                try:
                    # SAFETY CHECK: Re-fetch block to ensure it's still uncategorized
                    fresh_block = Block.objects.select_for_update().get(id=b.id)
                    
                    if not fresh_block.is_categorized:
                        # Client CORRECTION only — never create new clients
                        suggested_client = (sug.get("client") or "").strip()
                        current_client_name = getattr(fresh_block.client, "name", None)

                        if suggested_client and suggested_client != current_client_name:
                            # AI thinks agent's client is wrong — only accept known clients
                            try:
                                correct_client = Client.objects.get(
                                    org=org,
                                    name__iexact=suggested_client,
                                    is_active=True,
                                )
                                fresh_block.client = correct_client
                                sug["needs_review"] = True  # Always flag corrections for user review
                                log(f"[AI] 🔄 Client correction: {current_client_name} → {suggested_client} (block {b.id})")
                            except Client.MultipleObjectsReturned:
                                # Multiple clients with same name — don't guess
                                log(f"[AI] ⚠️ Multiple clients match '{suggested_client}' — skipping correction")
                                sug["client"] = current_client_name
                            except Client.DoesNotExist:
                                # AI hallucinated a client name — ignore silently
                                log(f"[AI] ⚠️ Ignoring unknown client suggestion: '{suggested_client}'")
                                sug["client"] = current_client_name  # Reset to agent's client
                        
                        # Save categories
                        if categories and isinstance(categories, dict):
                            clean_cats = {}
                            for k, v in categories.items():
                                try:
                                    clean_cats[str(k)] = float(v)
                                except (ValueError, TypeError):
                                    pass
                            
                            if clean_cats:
                                fresh_block.category_hours = clean_cats
                                fresh_block.ai_category = list(clean_cats.keys())[0]
                                fresh_block.is_categorized = True  # ← LOCK IT
                                fresh_block.categorized_at = timezone.now()
                                fresh_block.categorized_by = 'ai'
                                fresh_block.ai_processed_at = timezone.now()
                                fresh_block.ai_confidence = confidence
                                
                                fresh_block.save()
                                auto_saved = True
                                saved_count += 1
                                
                                # Update local reference
                                b.client = fresh_block.client
                                b.is_categorized = True
                                
                                log(f"[AI] ✅ LOCKED block {b.id} → {client_name or 'none'} | {list(clean_cats.keys())} ({confidence:.2f})")
                    else:
                        log(f"[AI] ⚠️ Block {b.id} already categorized - skipping")
                
                except Exception as e:
                    log(f"[AI] ❌ Failed to save block {b.id}: {e}")
                    import traceback
                    traceback.print_exc()
            
            # ✅ Clean display formatting
            display_client = client_name or getattr(b.client, "name", None)
            formatted = format_block_for_display({
                'app_name': getattr(b, 'app_name', '') or '',
                'window_title': getattr(b, 'window_title', '') or '',
                'url': getattr(b, 'url', '') or '',
                'minutes': b.minutes or 0,
                'category': list(categories.keys())[0] if categories else None,
            }, client_name=display_client)
            
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
                # ✅ Clean display data for UI
                "display": {
                    "title": formatted['title'],
                    "app": formatted['app'],
                    "duration": formatted['duration'],
                    "category_icon": formatted['category_icon'],
                },
                "current_client": getattr(b.client, "name", None),
                "current_project": getattr(b.project, "name", None),
            })

    # =========================================================
    # STEP 5: Add already-categorized blocks to response
    # These are READ-ONLY - just returned for display
    # =========================================================
    for b in already_categorized:
        cat_name = list((b.category_hours or {}).keys())[0] if b.category_hours else None
        client_name = getattr(b.client, "name", None)
        
        # ✅ Clean display formatting
        formatted = format_block_for_display({
            'app_name': getattr(b, 'app_name', '') or '',
            'window_title': getattr(b, 'window_title', '') or '',
            'url': getattr(b, 'url', '') or '',
            'minutes': b.minutes or 0,
            'category': cat_name,
        }, client_name=client_name)
        
        out.append({
            "block_id": b.id,
            "start": b.start,
            "end": b.end,
            "title": b.title,
            "ai_suggestion": {
                "client": client_name,
                "project": getattr(b.project, "name", None),
                "categories": b.category_hours or {},
                "confidence": 1.0,
                "needs_review": False,
                "reasoning": "Already categorized (locked)",
                "source": "existing",
                "auto_saved": False,
            },
            # ✅ Clean display data for UI
            "display": {
                "title": formatted['title'],
                "app": formatted['app'],
                "duration": formatted['duration'],
                "category_icon": formatted['category_icon'],
            },
            "current_client": client_name,
            "current_project": getattr(b.project, "name", None),
        })

    if saved_count > 0:
        log(f"[AI] Auto-saved and LOCKED {saved_count}/{N} blocks")

    return Response(out)


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

        # NEW (use actual event-based minutes):
        block_minutes = b.minutes
        if not block_minutes or block_minutes <= 0:
            # Fallback to span only if minutes not set
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
        "date": (parse_date(date_str) if date_str else localtime(timezone.now()).date()).isoformat(),
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

# tracker/views.py - UPDATED save_block_classification

from tracker.services.pattern_learning import PatternLearningService


@api_view(["POST"])
@permission_classes([PermUI])
@transaction.atomic
def save_block_classification(request, block_id: int):
    """
    Manual block classification by user.
    
    POST: { 
        client?: str, 
        project?: str, 
        task?: str, 
        categories?: {name: hours(float)} 
    }
    
    ✅ Learns patterns from manual classifications to improve future accuracy
    ✅ Creates Client/Project if needed (within org)
    ✅ Coerces category values to floats (hours)
    ✅ Tracks immutability with is_categorized flag
    """
    b = get_object_or_404(Block, id=block_id)
    
    # Ensure org exists on the block
    org = getattr(b, "org", None)
    if org is None:
        org = get_org_or_default(request)
        try:
            # Only set if Block has org FK field
            if any(f.name == "org" for f in Block._meta.fields):
                b.org = org
        except Exception:
            pass  # If no org field, ignore
    
    payload = request.data or {}
    client_name  = (payload.get("client")  or "").strip() or None
    project_name = (payload.get("project") or "").strip() or None
    categories   = payload.get("categories", {})
    
    # Track what changed for learning
    original_client = b.client
    original_categories = getattr(b, "category_hours", None)
    was_categorized = b.is_categorized  # ✅ Track if already categorized
    original_source = b.categorized_by   # ✅ Track original source
    
    # Attach/create Client
    client_obj = None
    if client_name:
        client_obj, created = Client.objects.get_or_create(
            org=org, 
            name=client_name,
            defaults={"is_active": True}
        )
        b.client = client_obj
        
        if created:
            log(f"[CLASSIFY] Created new client: {client_name}")
    
    # Attach/create Project (requires client)
    if project_name:
        if client_obj is None:
            client_obj, _ = Client.objects.get_or_create(
                org=org, 
                name="(General)",
                defaults={"is_active": True}
            )
            b.client = client_obj
        
        proj_obj, created = Project.objects.get_or_create(
            org=org, 
            client=client_obj, 
            name=project_name,
            defaults={"is_active": True}
        )
        b.project = proj_obj
        
        if created:
            log(f"[CLASSIFY] Created new project: {project_name} for {client_name}")
    
    # Coerce categories (hours)
    clean_categories = {}
    if categories is None or categories == {}:
        clean_categories = {}
    elif isinstance(categories, dict):
        for k, v in categories.items():
            f = _to_float_or_none(v)
            if f is None or f < 0:
                # Don't blow up; just skip bad entries
                continue
            clean_categories[str(k)] = f
    else:
        raise ValidationError({
            "categories": "Must be an object mapping {category: hours}."
        })
    
    # ✅ UPDATED: Set categories and immutability tracking
    if clean_categories:
        if hasattr(b, "category_hours"):
            b.category_hours = clean_categories
            b.is_categorized = True
            b.categorized_at = b.categorized_at or timezone.now()  # Keep original if exists
            
            # ✅ Track if this is a correction vs manual entry
            if was_categorized and original_source == 'ai':
                b.categorized_by = 'correction'  # User corrected AI
                log(f"[CLASSIFY] User corrected AI classification for block {b.id}")
            elif was_categorized and original_source in ('pattern', 'import'):
                b.categorized_by = 'correction'  # User corrected other auto-classification
                log(f"[CLASSIFY] User corrected {original_source} classification for block {b.id}")
            elif not was_categorized:
                b.categorized_by = 'manual'  # First-time manual entry
                log(f"[CLASSIFY] User manually classified block {b.id}")
            # else: keep existing categorized_by (already 'manual' or 'correction')
    
    # Optional task
    task_name = (payload.get("task") or "").strip() or None
    if task_name:
        try:
            task_obj, created = Task.objects.get_or_create(
                org=org, 
                project=b.project, 
                name=task_name,
                defaults={"is_active": True}
            )
            b.task = task_obj
            
            if created:
                log(f"[CLASSIFY] Created new task: {task_name}")
        except Exception as e:
            log(f"[CLASSIFY] Could not create task: {e}")
            pass
    
    # ✅ Mark as manually reviewed (if fields exist)
    if hasattr(b, "manually_reviewed"):
        b.manually_reviewed = True
    if hasattr(b, "reviewed_at"):
        b.reviewed_at = timezone.now()
    if hasattr(b, "reviewed_by"):
        b.reviewed_by = request.user
    
    # ✅ Save with force_update to bypass protection check
    # (User is intentionally editing, so we allow it)
    b.save(force_update=True)
    
    # ✅ Learn patterns from this manual classification
    user = request.user if request.user.is_authenticated else None
    
    if user and clean_categories:
        try:
            # Learn from this confirmed classification
            PatternLearningService.learn_from_block(b, user)
            
            # Log what we learned
            learned_details = []
            
            # File path pattern
            if getattr(b, 'file_path', None):
                file_path_short = b.file_path[:50] + "..." if len(b.file_path) > 50 else b.file_path
                learned_details.append(f"file '{file_path_short}'")
            
            # Time pattern
            if b.start:
                hour = b.start.hour
                weekday = b.start.strftime('%A')
                learned_details.append(f"{weekday} at {hour}:00")
            
            if learned_details:
                category_names = list(clean_categories.keys())
                log(f"[PATTERN] Learned: {' + '.join(learned_details)} → {client_name or 'no client'} / {category_names}")
            
            # ✅ Track AI corrections for accuracy metrics
            if original_client != b.client and original_client and was_categorized:
                log(f"[PATTERN] User corrected client: {original_client.name} → {client_name}")
                # Future: Implement negative feedback loop to downgrade bad patterns
            
            if original_categories != clean_categories and was_categorized:
                log(f"[PATTERN] User corrected categories: {original_categories} → {clean_categories}")
            
        except Exception as e:
            # Don't fail the request if pattern learning fails
            log(f"[PATTERN] Failed to learn from block {b.id}: {e}")
    
    # Build response with helpful context
    response_data = {
        "ok": True,
        "block_id": b.id,
        "client": getattr(b.client, "name", None),
        "project": getattr(b.project, "name", None),
        "task": getattr(b.task, "name", None) if hasattr(b, "task") else None,
        "categories": getattr(b, "category_hours", {}),
        "manually_reviewed": getattr(b, "manually_reviewed", None),
        "is_categorized": b.is_categorized,
        "categorized_by": b.categorized_by,
    }
    
    # ✅ Add feedback about pattern learning (optional)
    if user and clean_categories:
        try:
            learned_patterns = PatternLearningService.get_patterns_for_block(b, user)
            if learned_patterns:
                # Return the top learned pattern for feedback
                top_client, top_category, top_confidence = learned_patterns[0]
                response_data["learned_pattern"] = {
                    "client": top_client,
                    "category": top_category,
                    "confidence": round(top_confidence, 2),
                    "message": f"Future similar work will default to {top_client or top_category} ({int(top_confidence*100)}% confidence)"
                }
        except Exception:
            pass
    
    return Response(response_data)

# -------------------------------------------------------------------
# Bulk import (clients/projects) for onboarding
# -------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([PermUI])
def clients_list(request):
    org = get_org_or_default(request)
    qs = Client.objects.filter(org=org).order_by("name")
    return Response([{"id": c.id, "name": c.name} for c in qs])


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

# Replace your whoami view in tracker/views.py with this:

@api_view(["GET"])
@permission_classes([AllowAny])
def whoami(request):
    """Check authentication via token in database."""
    from tracker.models import AuthToken, OrganizationMembership
    
    # Helper to get org info AND role
    def get_user_info(user):
        org = get_user_org(user)
        
        # Get the user's role from OrganizationMembership
        role = None
        if org:
            membership = OrganizationMembership.objects.filter(
                user=user, 
                organization=org
            ).first()
            if membership:
                role = membership.role
        
        return {
            "is_authenticated": True,
            "username": user.username,
            "user_id": user.id,
            "email": user.email or "",
            "first_name": user.first_name or "",   # ✅ NEW
            "last_name": user.last_name or "",     # ✅ NEW
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "role": role,  # ← 'owner', 'admin', 'manager', or 'member'
            "org_id": org.id if org else None,
            "org_name": org.name if org else None,
        }
    
    # 1) Check Authorization header (Bearer token)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "", 1).strip()
        
        try:
            auth_token = AuthToken.objects.select_related('user').get(token=token)
            if auth_token.is_valid():
                user_data = get_user_info(auth_token.user)
                user_data["auth_source"] = "token"
                user_data["host"] = None
                user_data["device_id"] = None
                return Response(user_data)
        except AuthToken.DoesNotExist:
            pass
    
    # 2) Agent API key
    agent_key = (
        request.headers.get("X-Agent-Key")
        or request.headers.get("Agent-Key")
        or request.META.get("HTTP_X_AGENT_KEY")
        or request.META.get("HTTP_AGENT_KEY")
    )
    if agent_key:
        try:
            device = AgentDevice.objects.filter(api_key=agent_key, is_active=True).select_related("user").first()
            if device and device.user_id:
                user_data = get_user_info(device.user)
                user_data["auth_source"] = "agent"
                user_data["host"] = device.hostname or None
                user_data["device_id"] = device.device_id
                return Response(user_data)
        except Exception:
            pass
    
    # 3) Django session
    if getattr(request.user, "is_authenticated", False):
        user_data = get_user_info(request.user)
        user_data["auth_source"] = "session"
        user_data["host"] = None
        user_data["device_id"] = None
        return Response(user_data)
    
    # 4) Unknown/not authenticated
    return Response({
        "is_authenticated": False,
        "auth_source": "unknown",
        "username": "",
        "user_id": None,
        "email": "",
        "first_name": "",   # ✅ NEW
        "last_name": "",    # ✅ NEW
        "is_staff": False,
        "is_superuser": False,
        "role": None,
        "org_id": None,
        "org_name": None,
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
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect

from .models import AgentSession  # if you have it; safe to remove if not present


# tracker/views.py
from django.core import signing
from django.utils import timezone

from django.views.decorators.csrf import csrf_exempt

from django.views.decorators.csrf import csrf_exempt

import secrets

import secrets
from datetime import timedelta

@api_view(["POST"])
@permission_classes([AllowAny])
def auth_login(request):
    """JSON login endpoint - accepts username OR email."""
    data = request.data or {}
    username_or_email = (data.get("username") or data.get("email") or "").strip()
    password = data.get("password") or ""
    
    if not username_or_email or not password:
        return Response(
            {"ok": False, "error": "Username/email and password required."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Try to find user by email or username
    user = None
    if '@' in username_or_email:
        # Looks like an email - try email first
        user = User.objects.filter(email__iexact=username_or_email).first()
    
    if not user:
        # Try username (case-insensitive)
        user = User.objects.filter(username__iexact=username_or_email).first()
    
    if not user:
        return Response(
            {"ok": False, "error": "Invalid credentials."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify password
    if not user.check_password(password):
        return Response(
            {"ok": False, "error": "Invalid credentials."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not user.is_active:
        return Response(
            {"ok": False, "error": "Account is disabled."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Log them in (creates session)
    login(request, user)
    
    # Generate token and store in database
    from tracker.models import AuthToken, OrganizationMembership
    
    token_value = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(days=14)
    
    AuthToken.objects.create(
        user=user,
        token=token_value,
        expires_at=expires_at
    )
    
    # Get org/role info
    membership = OrganizationMembership.objects.filter(user=user).select_related('organization').first()
    
    return Response({
        "ok": True,
        "token": token_value,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email or "",
            "name": f"{user.first_name} {user.last_name}".strip(),
        },
        "organization": {
            "id": membership.organization.id,
            "name": membership.organization.name,
            "slug": membership.organization.slug,
        } if membership else None,
        "role": membership.role if membership else None,
    })


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

# views.py
from django.contrib.auth import logout as django_logout
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["POST", "GET"])
@authentication_classes([])  # ← Add this - NO authentication required
@permission_classes([AllowAny])
def auth_logout(request):
    """Logout - always succeeds"""
    try:
        django_logout(request)
    except:
        pass
    
    if hasattr(request, 'auth') and request.auth:
        try:
            request.auth.delete()
        except:
            pass
    
    resp = Response({"ok": True})
    resp.delete_cookie("sessionid", path="/")
    resp.delete_cookie("mavops_username", path="/")
    resp.delete_cookie("mavops_host", path="/")
    resp.delete_cookie("mavops_ident", path="/")
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

    default_org, _ = Organization.objects.get_or_create(
        name="default-org",
        defaults={"slug": "default-org"}
    )

    # Create membership instead of adding to groups
    OrganizationMembership.objects.get_or_create(
        user=user,
        organization=default_org,
        defaults={"role": "member"}
    )

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
        "device_id": dev.id,  # <-- Add this line
        "username": pc.user.username,
        "hostname": dev.hostname,
    }, status=200)


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

from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication


@api_view(["POST"])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])  # Only these, no Session
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
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(
            name="default-org",
            defaults={"slug": "default-org"}
        )
    
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


# views.py - Replace the existing list_clients function

from django.db.models import Q, Exists, OuterRef

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_clients(request):
    """
    List clients visible to the current user.
    
    Visibility rules:
    - Owners/Admins: See all clients (except 'confidential' without assignment)
    - Managers: See 'all' visibility clients + their assigned clients
    - Members: See 'all' visibility clients + their assigned clients
    
    Returns: [
      {"id": 1, "name": "Acme Corp", "code": "ACME", "is_active": true, "visibility": "all"},
      ...
    ]
    """
    user = request.user
    
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(
            name="default-org",
            defaults={"slug": "default-org"}
        )
    
    # Get user's role in the organization
    membership = OrganizationMembership.objects.filter(
        user=user, organization=org
    ).first()
    
    role = membership.role if membership else 'member'
    
    # Base queryset - active clients in org
    base_qs = Client.objects.filter(org=org, is_active=True)
    
    # Check if ClientAssignment model exists and has data
    # This allows backward compatibility if no assignments exist yet
    try:
        from .models import ClientAssignment
        has_assignment_system = True
    except ImportError:
        has_assignment_system = False
    
    if not has_assignment_system:
        # No assignment system - return all clients (legacy behavior)
        clients = base_qs.order_by('name')
    else:
        # Check if user has any assignments (subquery for efficiency)
        user_assignments = ClientAssignment.objects.filter(
            user=user,
            client=OuterRef('pk')
        )
        
        if role in ('owner', 'admin'):
            # Admins see everything EXCEPT 'confidential' clients they're not assigned to
            clients = base_qs.filter(
                Q(visibility__in=['all', 'assigned']) |
                Q(visibility='confidential', pk__in=ClientAssignment.objects.filter(user=user).values('client_id')) |
                # Also include if visibility field doesn't exist (legacy clients)
                Q(visibility__isnull=True)
            ).order_by('name')
        
        elif role == 'manager':
            # Managers see 'all' visibility + their direct assignments
            clients = base_qs.filter(
                Q(visibility='all') |
                Q(visibility__isnull=True) |  # Legacy clients without visibility field
                Exists(user_assignments)
            ).order_by('name')
        
        else:
            # Members see 'all' visibility + their direct assignments
            clients = base_qs.filter(
                Q(visibility='all') |
                Q(visibility__isnull=True) |  # Legacy clients without visibility field
                Exists(user_assignments)
            ).order_by('name')
    
    return Response([{
        "id": c.id,
        "name": c.name,
        "code": getattr(c, 'code', '') or c.name[:4].upper(),
        "is_active": c.is_active,
        "visibility": getattr(c, 'visibility', 'all') or 'all',
    } for c in clients])


@api_view(["GET"])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def context_guess(request):
    """
    AI-powered client suggestion based on recent activity.
    
    Uses smart matching to find client names in:
    - Window titles (e.g., "MavOps_Aurelia_Website_Proposal.pdf")
    - URLs (e.g., "acmecorp.quickbooks.com")
    - File paths (e.g., "/Users/dan/Clients/Aurelia/")
    
    Query params:
      - host: hostname (optional, from agent)
      - device_id: device UUID (optional)
    
    Returns: { client_id, client_name, confidence, reason }
    """
    user = request.user
    device = getattr(request, "agent_device", None)
    
    # Get recent blocks (last 15 minutes for better coverage)
    cutoff = timezone.now() - timedelta(minutes=15)
    
    recent_blocks = Block.objects.filter(
        user=user,
        start__gte=cutoff
    ).order_by("-start")[:30]
    
    if not recent_blocks:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": 0.0,
            "reason": "No recent activity"
        })
    
    # Get user's org and clients
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(
            name="default-org",
            defaults={"slug": "default-org"}
        )
    
    clients = list(Client.objects.filter(org=org, is_active=True))
    if not clients:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": 0.0,
            "reason": "No clients defined"
        })
    
    # Get known entities for alias matching
    known_entities = list(KnownEntity.objects.filter(
        org=org,
        entity_type="client"
    ))
    
    # Score each client across all recent blocks
    client_scores = {}  # client_id -> {'score': float, 'reasons': [], 'blocks': int}
    
    for block in recent_blocks:
        # Skip idle blocks
        if _is_idle_block(block):
            continue
        
        # Collect all text to search
        window_title = (getattr(block, "window_title", "") or "").strip()
        url = (block.url or "").strip()
        file_path = (block.file_path or "").strip()
        app_name = (getattr(block, "app_name", "") or "").strip()
        
        # Combine for matching (with separators to avoid false joins)
        combined_text = f"{window_title} | {url} | {file_path} | {app_name}"
        
        # Run smart matching
        matches = match_client_in_text(combined_text, clients, known_entities)
        
        for client, score, reason in matches:
            if client.id not in client_scores:
                client_scores[client.id] = {
                    'client': client,
                    'score': 0.0,
                    'reasons': set(),
                    'blocks': 0
                }
            
            client_scores[client.id]['score'] += score
            client_scores[client.id]['reasons'].add(reason)
            client_scores[client.id]['blocks'] += 1
        
        # Additional: Check URL domain against client name/code
        domain = extract_domain_from_url(url)
        if domain:
            for client in clients:
                client_name_lower = client.name.lower().replace(' ', '')
                client_code_lower = (getattr(client, 'code', '') or '').lower()
                
                # Domain contains client name (e.g., "acmecorp.quickbooks.com")
                if client_name_lower and client_name_lower in domain.replace('.', ''):
                    if client.id not in client_scores:
                        client_scores[client.id] = {
                            'client': client,
                            'score': 0.0,
                            'reasons': set(),
                            'blocks': 0
                        }
                    client_scores[client.id]['score'] += 0.35
                    client_scores[client.id]['reasons'].add(f"Domain contains '{client.name}'")
                    client_scores[client.id]['blocks'] += 1
    
    # Find best match
    if not client_scores:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": 0.0,
            "reason": "No matches found in recent activity"
        })
    
    # Get top match
    best_match = max(client_scores.values(), key=lambda x: x['score'])
    best_client = best_match['client']
    raw_score = best_match['score']
    block_count = best_match['blocks']
    reasons = list(best_match['reasons'])[:3]  # Top 3 reasons
    
    # Normalize confidence (cap at 0.95)
    # More blocks = more confidence, but diminishing returns
    block_bonus = min(0.15, block_count * 0.03)
    confidence = min(0.95, (raw_score / 2.0) + block_bonus)
    
    # Minimum threshold to suggest
    if confidence < 0.35:
        return Response({
            "client_id": None,
            "client_name": None,
            "confidence": confidence,
            "reason": f"Low confidence ({confidence:.2f}): {'; '.join(reasons)}"
        })
    
    return Response({
        "client_id": best_client.id,
        "client_name": best_client.name,
        "confidence": round(confidence, 2),
        "reason": '; '.join(reasons),
        "blocks_matched": block_count
    })


@api_view(["POST"])
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
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(
            name="default-org",
            defaults={"slug": "default-org"}
        )
    
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
@permission_classes([PermUI])
def import_clients_csv(request):
    """
    Import clients from CSV file.
    
    Supported columns:
      - name/client/client_name (required): Client name
      - code (optional): Short code (e.g., "ACME")
      - project (optional): Default project name
      - active (optional): true/false (default: true)
    """
    import csv
    import io
    
    user = request.user
    
    if 'file' not in request.FILES:
        return Response({"error": "No file provided"}, status=400)
    
    csv_file = request.FILES['file']
    
    # Decode file - use utf-8-sig to automatically strip BOM
    try:
        text = csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            csv_file.seek(0)
            text = csv_file.read().decode('latin-1')
        except Exception:
            return Response(
                {"error": "Invalid file encoding. Please use UTF-8."},
                status=400
            )
    
    # Also strip BOM manually just in case (belt and suspenders)
    text = text.lstrip('\ufeff')
    
    # Get org
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(
            name="default-org",
            defaults={"slug": "default-org"}
        )
    
    # Parse CSV
    reader = csv.DictReader(io.StringIO(text))
    
    # Check if first row looks like valid headers - if not, might have a title row
    fieldnames = reader.fieldnames or []
    valid_header_names = ['name', 'client', 'client_name', 'code', 'project', 'active', 'email', 'contact']
    has_valid_header = any(
        col.lower().strip() in valid_header_names 
        for col in fieldnames
    )
    
    if not has_valid_header:
        # Skip first row (title row) and re-parse
        lines = text.strip().split('\n')
        if len(lines) > 1:
            text = '\n'.join(lines[1:])
            reader = csv.DictReader(io.StringIO(text))
    
    clients_created = 0
    projects_created = 0
    clients_skipped = 0
    errors = []
    
    for row_num, row in enumerate(reader, start=2):
        try:
            # Flexible column name matching for client name
            client_name = None
            for col in ['name', 'client', 'client_name', 'Name', 'Client', 'Client Name', 'CLIENT', 'NAME']:
                if col in row and row[col]:
                    client_name = row[col].strip()
                    break
            
            if not client_name:
                errors.append(f"Row {row_num}: Missing client name")
                clients_skipped += 1
                continue
            
            # Check if client already exists
            if Client.objects.filter(org=org, name=client_name).exists():
                clients_skipped += 1
                continue
            
            # Get optional code field (flexible matching)
            code = None
            for col in ['code', 'Code', 'CODE']:
                if col in row and row[col]:
                    code = row[col].strip()
                    break
            
            # Generate code if not provided
            if not code:
                code = client_name[:10].upper().replace(" ", "")
            
            # Parse active field
            active_str = str(row.get('active', row.get('Active', 'true'))).lower().strip()
            is_active = active_str in ('1', 'true', 'yes', 'y', '')
            
            # Create client
            client = Client.objects.create(
                org=org,
                name=client_name,
                code=code,
                is_active=is_active
            )
            clients_created += 1
            
            # Optional: Create default project
            project_name = None
            for col in ['project', 'Project', 'PROJECT', 'default_project']:
                if col in row and row[col]:
                    project_name = row[col].strip()
                    break
            
            if project_name:
                Project.objects.create(
                    org=org,
                    client=client,
                    name=project_name,
                    is_active=True
                )
                projects_created += 1
            
        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")
            clients_skipped += 1
    
    return Response({
        "ok": True,
        "clients": clients_created,
        "projects": projects_created,
        "skipped": clients_skipped,
        "errors": errors if errors else None,
        "message": f"Successfully imported {clients_created} clients ({clients_skipped} skipped)"
    })

# ============================================================================
# BACKEND FIX: tracker/views.py (around line 4390)
# ============================================================================
# This fix handles anonymous users gracefully in the user_profile endpoint
# 
# INSTRUCTIONS:
# 1. Open tracker/views.py in your Django backend
# 2. Find the user_profile function (around line 4390)
# 3. Replace the entire function with the code below
# ============================================================================

from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    """
    GET: Return user profile information
    PATCH: Update user profile
    """
    user = request.user
    
    if request.method == 'GET':
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        })
    
    elif request.method == 'PATCH':
        # Update allowed fields
        if 'first_name' in request.data:
            user.first_name = request.data['first_name']
        if 'last_name' in request.data:
            user.last_name = request.data['last_name']
        if 'email' in request.data:
            user.email = request.data['email']
        
        user.save()
        
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        })

@api_view(["POST"])
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


"""
COMPLETE today_time() REPLACEMENT
=================================
Copy this entire function and replace your existing today_time() in tracker/views.py

FIX: Uses UNION of time spans instead of SUM to handle overlapping blocks correctly.
Before: 47 + 12 + 11 = 70 min (wrong - counts overlap twice)
After:  Union of spans = 42 min (correct - actual clock time)
"""

# =============================================================================
# EVENT-BASED today_time() - Correct time attribution
# =============================================================================
#
# KEY INSIGHT: At any given moment, only ONE app is active.
# The app with the most recent event "owns" that time.
#
# OLD (wrong): Block spans → Chrome 16:15-18:03 = 1.81h, Sublime 16:40-17:38 = 0.97h
#              Total billed: 2.78h (but you only worked 1.81h!)
#
# NEW (correct): Event-by-event → Each minute belongs to ONE client only
#                Chrome gets time when YOU were using Chrome
#                Sublime gets time when YOU were using Sublime
#                No double-counting!
# =============================================================================

# tracker/views_today_time.py
"""
Updated today_time endpoint with clean display formatting.

REPLACE your existing today_time function in views.py with this version.
Also add the _today_time_from_blocks helper function.

ALSO: Copy display_names.py to tracker/utils/display_names.py
"""

# ============================================================================
# UPDATED today_time() - With Clean Display Formatting
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def today_time(request):
    """
    Get tracked time organized by client → category.
    
    Uses EVENT-BASED attribution: each minute belongs to the app
    that had the most recent activity, not block spans.
    
    NOW WITH CLEAN DISPLAY FORMATTING:
    - "Chrome - Aurelia Dashboard (15m)" instead of "Google Chrome (15m)"
    - "VS Code - views.py (timetracker) (45m)" instead of messy raw titles
    """
    from datetime import datetime, timedelta
    from datetime import timezone as dt_timezone
    from collections import defaultdict
    from django.utils.dateparse import parse_date
    
    # Import the display formatter
    from tracker.utils.display_names import format_block_for_display, format_duration
    
    user = request.user
    
    if not user.is_authenticated:
        return Response(
            {"error": "Authentication required"},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    date_str = request.GET.get('date')
    if date_str:
        target_date = parse_date(date_str)
    else:
        target_date = timezone.localdate()
    
    tz = timezone.get_current_timezone()
    start_local = timezone.make_aware(
        datetime.combine(target_date, datetime.min.time()), 
        tz
    )
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(dt_timezone.utc)
    end_utc = end_local.astimezone(dt_timezone.utc)
    
    # =========================================================================
    # STEP 1: Get ALL events for the day, ordered by time
    # =========================================================================
    events = list(RawEvent.objects.filter(
        user=user,
        ts_utc__gte=start_utc,
        ts_utc__lt=end_utc,
    ).select_related('block', 'block__client').order_by('ts_utc'))
    
    if not events:
        # Fallback to blocks if no events (e.g., manual entries)
        return _today_time_from_blocks(request, user, target_date, start_utc, end_utc)
    
    # =========================================================================
    # STEP 2: Calculate duration for each event
    # Duration = time until next event (capped at 3 min)
    # =========================================================================
    IDLE_CAP_SECONDS = 180  # 3 minutes - matches agent's MOUSE_IDLE_PAUSE_S
    
    event_durations = []
    for i, event in enumerate(events):
        if i + 1 < len(events):
            next_ts = events[i + 1].ts_utc
            duration_sec = (next_ts - event.ts_utc).total_seconds()
            duration_sec = min(duration_sec, IDLE_CAP_SECONDS)
        else:
            duration_sec = 180  # 3 min for last event
        
        # Get client and category from linked block
        block = event.block
        if block:
            client_id = block.client_id
            client_name = block.client.name if block.client else 'Unassigned'
            
            # Get category from block
            if block.category_hours and isinstance(block.category_hours, dict):
                categories = list(block.category_hours.keys())
                category = categories[0] if categories else 'Uncategorized'
            else:
                category = 'Uncategorized'
            
            # Check if idle
            is_idle = category.lower() == 'idle'
        else:
            client_id = None
            client_name = 'Unassigned'
            category = 'Uncategorized'
            is_idle = False
        
        event_durations.append({
            'ts': event.ts_utc,
            'duration_minutes': duration_sec / 60.0,
            'client_id': client_id,
            'client_name': client_name,
            'category': category,
            'is_idle': is_idle,
            'app_name': event.app_name or 'Unknown',
            'window_title': event.window_title or '',
            'url': event.url or '',  # ✅ NEW: Include URL for better formatting
            'block_id': block.id if block else None,
        })
    
    # =========================================================================
    # STEP 3: Aggregate by client → category
    # Each event's duration goes to exactly ONE client
    # =========================================================================
    data = defaultdict(lambda: {
        'client_id': None,
        'categories': defaultdict(lambda: {
            'minutes': 0.0,
            'block_count': 0,
            'blocks_seen': set(),
            'by_activity': {},  # ✅ RENAMED: by_title → by_activity (keyed by clean title)
        })
    })
    
    total_minutes = 0.0
    billable_minutes = 0.0
    
    for ev in event_durations:
        client_name = ev['client_name']
        category = ev['category']
        minutes = ev['duration_minutes']
        
        data[client_name]['client_id'] = ev['client_id']
        cat_data = data[client_name]['categories'][category]
        cat_data['minutes'] += minutes
        
        # Track unique blocks for count
        if ev['block_id'] and ev['block_id'] not in cat_data['blocks_seen']:
            cat_data['blocks_seen'].add(ev['block_id'])
            cat_data['block_count'] += 1
        
        # ✅ NEW: Use display formatter for clean title
        formatted = format_block_for_display({
            'app_name': ev['app_name'],
            'window_title': ev['window_title'],
            'url': ev['url'],
            'minutes': minutes,
        }, client_name=client_name)
        
        clean_title = formatted['title']
        
        # Aggregate by CLEAN title (merges similar activities)
        if clean_title in cat_data['by_activity']:
            cat_data['by_activity'][clean_title]['minutes'] += minutes
        else:
            cat_data['by_activity'][clean_title] = {
                'id': ev['block_id'],
                'title': clean_title,
                'minutes': minutes,
            }
        
        # Track totals
        total_minutes += minutes
        if ev['client_id'] and not ev['is_idle']:
            billable_minutes += minutes
    
    # =========================================================================
    # STEP 4: Build response with clean formatting
    # =========================================================================
    result = []
    for client_name, client_data in sorted(data.items()):
        categories = []
        client_total_minutes = 0.0
        
        for cat_name, cat_data in sorted(client_data['categories'].items()):
            minutes = cat_data['minutes']
            client_total_minutes += minutes
            
            # Build sample activities (top 10 by time) with CLEAN titles
            aggregated_samples = []
            sorted_activities = sorted(
                cat_data['by_activity'].items(), 
                key=lambda x: -x[1]['minutes']
            )[:10]

            for clean_title, info in sorted_activities:
                mins = info['minutes']
                time_str = format_duration(mins)
                
                # ✅ Clean format with block ID for editing
                if info['id']:
                    aggregated_samples.append(f"[id:{info['id']}] {clean_title} ({time_str})")
                else:
                    aggregated_samples.append(f"{clean_title} ({time_str})")
            
            categories.append({
                'name': cat_name,
                'hours': round(minutes / 60, 2),
                'block_count': cat_data['block_count'],
                'unique_activities': len(cat_data['by_activity']),
                'sample_activities': aggregated_samples,
            })
        
        result.append({
            'client_id': client_data['client_id'],
            'client': client_name,
            'total_hours': round(client_total_minutes / 60, 2),
            'categories': categories,
        })
    
    return Response({
        'clients': result,
        'global_hours': round(total_minutes / 60, 2),
        'billable_hours': round(billable_minutes / 60, 2),
        'date': target_date.isoformat(),
    })


def _today_time_from_blocks(request, user, target_date, start_utc, end_utc):
    """
    Fallback for manual entries or when no events exist.
    Uses block-level data (less accurate but necessary for manual time).
    
    NOW WITH CLEAN DISPLAY FORMATTING.
    """
    from collections import defaultdict
    from tracker.utils.display_names import format_block_for_display, format_duration
    
    blocks = Block.objects.filter(
        user=user,
        start__gte=start_utc,
        start__lt=end_utc,
        deleted_at__isnull=True
    ).select_related('client').order_by('start')
    
    data = defaultdict(lambda: {
        'client_id': None,
        'categories': defaultdict(lambda: {
            'minutes': 0.0,
            'block_count': 0,
            'by_activity': {},
        })
    })
    
    total_minutes = 0.0
    billable_minutes = 0.0
    
    for block in blocks:
        client_name = block.client.name if block.client else 'Unassigned'
        client_id = block.client_id
        minutes = block.minutes or 0
        
        if block.category_hours and isinstance(block.category_hours, dict):
            categories = list(block.category_hours.keys())
            category = categories[0] if categories else 'Uncategorized'
        else:
            category = 'Uncategorized'
        
        is_idle = category.lower() == 'idle'
        
        data[client_name]['client_id'] = client_id
        cat_data = data[client_name]['categories'][category]
        cat_data['minutes'] += minutes
        cat_data['block_count'] += 1
        
        # ✅ Use display formatter for clean title
        formatted = format_block_for_display({
            'app_name': block.app_name or '',
            'window_title': block.window_title or '',
            'url': block.url or '',
            'minutes': minutes,
        }, client_name=client_name)
        
        clean_title = formatted['title']
        
        if clean_title in cat_data['by_activity']:
            cat_data['by_activity'][clean_title]['minutes'] += minutes
        else:
            cat_data['by_activity'][clean_title] = {
                'id': block.id,
                'title': clean_title,
                'minutes': minutes,
            }
        
        total_minutes += minutes
        if client_id and not is_idle:
            billable_minutes += minutes
    
    result = []
    for client_name, client_data in sorted(data.items()):
        categories = []
        client_total = 0.0
        
        for cat_name, cat_data in sorted(client_data['categories'].items()):
            minutes = cat_data['minutes']
            client_total += minutes
            
            samples = []
            for clean_title, info in sorted(cat_data['by_activity'].items(), key=lambda x: -x[1]['minutes'])[:10]:
                time_str = format_duration(info['minutes'])
                if info['id']:
                    samples.append(f"[id:{info['id']}] {clean_title} ({time_str})")
                else:
                    samples.append(f"{clean_title} ({time_str})")
            
            categories.append({
                'name': cat_name,
                'hours': round(minutes / 60, 2),
                'block_count': cat_data['block_count'],
                'unique_activities': len(cat_data['by_activity']),
                'sample_activities': samples,
            })
        
        result.append({
            'client_id': client_data['client_id'],
            'client': client_name,
            'total_hours': round(client_total / 60, 2),
            'categories': categories,
        })
    
    return Response({
        'clients': result,
        'global_hours': round(total_minutes / 60, 2),
        'billable_hours': round(billable_minutes / 60, 2),
        'date': target_date.isoformat(),
    })

# ============================================================================
# VIEW 1: Get Uncategorized Blocks + Dropdown Options
# ============================================================================
# backend/api/views/categorization.py

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.db import transaction
from collections import defaultdict
from urllib.parse import urlparse
from datetime import timedelta
from .models import Block, Client



def normalize_url(url):
    """Normalize URL to base (remove query params, anchors)"""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')
    except:
        return url


def get_activity_signature(block):
    """Get unique signature for an activity"""
    # Priority 1: URL (for browser activity)
    if block.url:
        normalized = normalize_url(block.url)
        if normalized:
            return ('url', normalized)
    
    # Priority 2: App + window title
    app = (block.app_name or "").strip().lower()
    title = (block.window_title or "").strip().lower()
    
    # Special handling for idle
    if app == "idle" or "idle" in title or "uncategorized" in title:
        return ('idle', 'idle')
    
    # Use app + significant part of title
    title_key = title[:80] if title else ""
    return ('app', f"{app}:{title_key}")


def group_into_sessions(blocks, max_gap_minutes=15, min_idle_minutes=5):
    """
    Group blocks into work sessions.
    
    Strategy:
    1. Group all blocks by their "activity signature" (URL/app/title)
    2. Within each activity, merge blocks that are within max_gap (even with idle between)
    3. Only break sessions if there's a real context switch or long idle
    
    Args:
        blocks: List of Block objects
        max_gap_minutes: Max gap between blocks of same activity to still merge (default 15 min)
        min_idle_minutes: Min idle duration to show separately (default 5 min)
    
    Returns:
        List of sessions (each session is a list of blocks)
    """
    if not blocks:
        return []
    
    # Step 1: Group blocks by activity signature
    activity_groups = defaultdict(list)
    for block in blocks:
        sig = get_activity_signature(block)
        activity_groups[sig].append(block)
    
    # Step 2: Within each activity, create sessions
    sessions = []
    
    for signature, activity_blocks in activity_groups.items():
        # Skip pure idle blocks (only include long idle periods)
        if signature == ('idle', 'idle'):
            for block in activity_blocks:
                if block.minutes >= min_idle_minutes:
                    sessions.append([block])
            continue
        
        # Sort blocks by time
        activity_blocks.sort(key=lambda b: b.start)
        
        # Merge blocks within max_gap
        current_session = [activity_blocks[0]]
        
        for i in range(1, len(activity_blocks)):
            prev_block = current_session[-1]
            curr_block = activity_blocks[i]
            
            gap_minutes = (curr_block.start - prev_block.end).total_seconds() / 60.0
            
            # Merge if gap is small enough
            if gap_minutes <= max_gap_minutes:
                current_session.append(curr_block)
            else:
                # Gap too large, start new session
                sessions.append(current_session)
                current_session = [curr_block]
        
        # Don't forget last session
        if current_session:
            sessions.append(current_session)
    
    # Step 3: Sort sessions by start time
    sessions.sort(key=lambda s: s[0].start)
    
    return sessions


# tracker/views_categorization.py
"""
Updated get_categorization_data endpoint with clean display formatting.

REPLACE your existing get_categorization_data function in views.py with this version.
"""

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_categorization_data(request):
    """Get uncategorized blocks for manual categorization with CLEAN formatting."""
    from datetime import datetime, timedelta
    from django.utils.dateparse import parse_date
    from tracker.utils.display_names import format_block_for_display, format_duration
    
    user = request.user
    date_str = request.GET.get('date')
    limit = int(request.GET.get('limit', 500))
    
    # Get org
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(name="default-org", defaults={"slug": "default-org"})
    
    # ✅ Get industry-specific categories
    industry_type = getattr(org, 'industry_type', 'general') or 'general'
    categories = get_categories_for_industry(industry_type)
    
    # Parse target date
    if date_str:
        target_date = parse_date(date_str)
    else:
        target_date = timezone.localdate()
    
    # Build datetime range for the day
    tz = timezone.get_current_timezone()
    start_local = timezone.make_aware(
        datetime.combine(target_date, datetime.min.time()), 
        tz
    )
    end_local = start_local + timedelta(days=1)
    
    # Convert to UTC
    start_utc = start_local.astimezone(dt_timezone.utc)
    end_utc = end_local.astimezone(dt_timezone.utc)
    
    # Only show blocks older than 10 minutes
    cutoff_time = timezone.now() - timedelta(minutes=10)
    effective_end = min(end_utc, cutoff_time)
    
    # Get uncategorized blocks
    blocks = Block.objects.filter(
        user=user,
        start__gte=start_utc,
        start__lt=effective_end,
        is_categorized=False
    ).select_related('client').order_by('start')[:limit]
    
    original_count = len(blocks)
    
    # Group into sessions
    sessions = group_into_sessions(list(blocks), max_gap_minutes=15, min_idle_minutes=5)
    
    blocks_data = []
    for session in sessions:
        first_block = session[0]
        last_block = session[-1]
        total_minutes = sum(b.minutes for b in session)
        block_ids = [b.id for b in session]
        
        span_minutes = (last_block.end - first_block.start).total_seconds() / 60.0
        
        # ✅ NEW: Use display formatter for clean title
        client_name = first_block.client.name if first_block.client else None
        formatted = format_block_for_display({
            'app_name': first_block.app_name or '',
            'window_title': first_block.window_title or '',
            'url': first_block.url or '',
            'minutes': total_minutes,
        }, client_name=client_name)
        
        blocks_data.append({
            'id': first_block.id,
            'block_ids': block_ids,
            'block_count': len(session),
            'start': first_block.start.isoformat(),
            'end': last_block.end.isoformat(),
            'duration_minutes': total_minutes,
            'span_minutes': round(span_minutes, 1),
            
            # ✅ Raw data (for debugging/advanced use)
            'app_name': first_block.app_name or '',
            'window_title': first_block.window_title or '',
            'url': first_block.url or '',
            'file_path': first_block.file_path or '',
            
            # ✅ NEW: Clean display data
            'display': {
                'title': formatted['title'],
                'app': formatted['app'],
                'duration': formatted['duration'],
            },
            
            'current_client': client_name,
            'current_client_id': first_block.client.id if first_block.client else None,
            'suggestions': [],
        })
    
    # Get clients
    clients = Client.objects.filter(
        org=org,
        is_active=True
    ).order_by('name').values('id', 'name', 'code')
    
    clients_list = [
        {
            'id': c['id'],
            'name': c['name'],
            'code': c['code'] or c['name'][:4].upper(),
        }
        for c in clients
    ]
    
    return Response({
        'date': target_date.isoformat(),
        'blocks': blocks_data,
        'clients': clients_list,
        'categories': categories,
        'industry_type': industry_type,
        'stats': {
            'uncategorized_count': len(blocks_data),
            'total_minutes': sum(b['duration_minutes'] for b in blocks_data),
            'original_block_count': original_count,
        }
    })

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def save_categorization(request):
    """
    Save manual categorization for a block or group of blocks.
    Learns patterns from manual categorization to improve future AI suggestions.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    user = request.user
    data = request.data
    
    # Get block ID(s)
    block_id = data.get('block_id')
    block_ids = data.get('block_ids', [block_id] if block_id else [])
    
    if not block_ids:
        return Response(
            {'error': 'block_id or block_ids is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get org
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(name="default-org", defaults={"slug": "default-org"})
    
    # Get client (if provided)
    client = None
    client_id = data.get('client_id')
    if client_id:
        try:
            client = Client.objects.get(id=client_id, org=org)
        except Client.DoesNotExist:
            return Response(
                {'error': f'Client {client_id} not found'},
                status=status.HTTP_400_BAD_REQUEST
            )

    # Validate category using industry-specific list
    # Validate category using industry-specific list
    category = data.get('category', '').strip()
    if not category:
        return Response(
            {'error': 'category is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    client_code = client.code if client else None
    industry_type = getattr(org, 'industry_type', 'general') or 'general'
    valid_categories = get_categories_for_industry(industry_type, client_code=client_code)
    
    if category not in valid_categories:
        return Response(
            {'error': f'Invalid category: {category}', 'valid_categories': valid_categories},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get notes
    notes = data.get('notes', '').strip()
    
    # Apply categorization to all blocks in the group
    updated_blocks = []
    skipped_blocks = []
    
    for bid in block_ids:
        try:
            block = Block.objects.select_for_update().get(id=bid, user=user)
            
            if block.is_categorized:
                skipped_blocks.append(bid)
                continue  # Skip already categorized
            
            # Calculate hours
            hours = round(block.minutes / 60.0, 2)
            
            # Update block
            block.client = client
            block.category_hours = {category: hours}
            block.is_categorized = True
            block.categorized_at = timezone.now()
            block.categorized_by = 'manual'
            
            if notes:
                block.notes = notes
            
            # Save with force_update to bypass protection
            block.save(force_update=True)
            updated_blocks.append(block)
            
            # ✅ Learn from this manual categorization
            try:
                from tracker.services.pattern_learning import PatternLearningService
                PatternLearningService.learn_from_block(block, user)
                logger.info(f"[LEARNING] Learned patterns from block {block.id}")
            except Exception as e:
                # Don't fail the save if learning fails
                logger.warning(f"[LEARNING] Failed to learn from block {block.id}: {e}")
                    
        except Block.DoesNotExist:
            skipped_blocks.append(bid)
    
    # Better response handling
    if not updated_blocks and skipped_blocks:
        return Response({
            'success': True,
            'message': f'All {len(skipped_blocks)} block(s) already categorized',
            'updated_count': 0,
            'skipped_count': len(skipped_blocks),
            'already_categorized': True
        })
    
    if not updated_blocks:
        return Response(
            {'error': 'No blocks found or updated'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    return Response({
        'success': True,
        'message': f'Categorized {len(updated_blocks)} block(s) successfully',
        'updated_count': len(updated_blocks),
        'skipped_count': len(skipped_blocks),
        'block': {
            'client': client.name if client else None,
            'category': category,
            'total_hours': round(sum(b.minutes for b in updated_blocks) / 60.0, 2),
        }
    })

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def bulk_categorize(request):
    """
    Categorize multiple blocks at once.
    
    Body:
    {
        "blocks": [
            {"block_id": 123, "client_id": 456, "category": "Tax Preparation"},
            {"block_id": 124, "client_id": 456, "category": "Email/Communication"}
        ]
    }
    """
    user = request.user
    blocks_data = request.data.get('blocks', [])
    
    if not blocks_data or not isinstance(blocks_data, list):
        return Response(
            {'error': 'blocks array is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Get org
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(name="default-org", defaults={"slug": "default-org"})


    industry_type = getattr(org, 'industry_type', 'general') or 'general'
    
    results = {
        'success_count': 0,
        'error_count': 0,
        'errors': []
    }
    
    for item in blocks_data:
        try:
            block_id = item.get('block_id')
            if not block_id:
                results['errors'].append({'block_id': None, 'error': 'block_id missing'})
                results['error_count'] += 1
                continue
            
            # Get block
            block = Block.objects.select_for_update().get(
                id=block_id,
                user=user,
                is_categorized=False
            )
            
            # Set client
            client = None
            client_id = item.get('client_id')
            if client_id:
                client = Client.objects.get(id=client_id, org=org)
                block.client = client
            
            # Set category (validate against client-aware category list)
            category = item.get('category', '').strip()
            if not category:
                results['errors'].append({'block_id': block_id, 'error': 'category missing'})
                results['error_count'] += 1
                continue

            client_code = client.code if client else None
            valid_categories = get_categories_for_industry(industry_type, client_code=client_code)
            if category not in valid_categories:
                results['errors'].append({'block_id': block_id, 'error': f'invalid category: {category}'})
                results['error_count'] += 1
                continue
            
            # Calculate hours
            hours = round(block.minutes / 60.0, 2)
            
            # Save
            block.category_hours = {category: hours}
            block.is_categorized = True
            block.categorized_at = timezone.now()
            block.categorized_by = 'manual'
            block.save()
            
            results['success_count'] += 1
            
        except Block.DoesNotExist:
            results['errors'].append({'block_id': block_id, 'error': 'block not found or already categorized'})
            results['error_count'] += 1
        except Client.DoesNotExist:
            results['errors'].append({'block_id': block_id, 'error': f'client {client_id} not found'})
            results['error_count'] += 1
        except Exception as e:
            results['errors'].append({'block_id': block_id, 'error': str(e)})
            results['error_count'] += 1
    
    return Response({
        'success': results['success_count'] > 0,
        'message': f"Categorized {results['success_count']} blocks, {results['error_count']} errors",
        'results': results
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def category_stats(request):
    """
    Get category usage statistics for the user.
    Shows which categories are used most often.
    
    Query params:
    - days: lookback period (default 30)
    """
    user = request.user
    days = int(request.GET.get('days', 30))
    
    cutoff = timezone.now() - timedelta(days=days)
    
    # Get categorized blocks
    blocks = Block.objects.filter(
        user=user,
        start__gte=cutoff,
        is_categorized=True
    ).select_related('client')
    
    # Calculate stats
    by_category = defaultdict(lambda: {'count': 0, 'hours': 0.0, 'clients': set()})
    
    for block in blocks:
        if block.category_hours:
            for category, hours in block.category_hours.items():
                by_category[category]['count'] += 1
                by_category[category]['hours'] += float(hours)
                if block.client:
                    by_category[category]['clients'].add(block.client.name)
    
    # Format results
    stats = []
    for category, data in sorted(by_category.items(), key=lambda x: x[1]['hours'], reverse=True):
        stats.append({
            'category': category,
            'block_count': data['count'],
            'total_hours': round(data['hours'], 2),
            'avg_hours_per_block': round(data['hours'] / data['count'], 2) if data['count'] > 0 else 0,
            'clients_using': list(data['clients']),
        })
    
    return Response({
        'period_days': days,
        'total_categories': len(stats),
        'stats': stats
    })

# tracker/views.py - ADD these new view functions

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta

from .models import TaskType, Block, Client, Project
from .serializers import (
    TaskTypeSerializer, TaskTypeListSerializer,
    ClientListSerializer, ProjectListSerializer,
    BlockSerializer, BlockCategorizationSerializer, BulkCategorizationSerializer,
    GroupedBlocksSerializer,
)


# ========================================
# ========== DROPDOWN OPTIONS ============
# ========================================
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_options(request):
    """Get clients for dropdown"""
    org = get_user_org(request.user)
    clients = Client.objects.filter(org=org, is_active=True).order_by('name')
    return Response(ClientListSerializer(clients, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def project_options(request):
    """Get all projects for dropdown"""
    org = get_user_org(request.user)
    projects = Project.objects.filter(org=org, is_active=True).select_related('client').order_by('client__name', 'name')
    return Response(ProjectListSerializer(projects, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def project_options_by_client(request, client_id):
    """Get projects filtered by client (for cascading dropdown)"""
    org = get_user_org(request.user)
    projects = Project.objects.filter(
        org=org, 
        client_id=client_id, 
        is_active=True
    ).order_by('name')
    return Response(ProjectListSerializer(projects, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def task_type_options(request):
    """Get task types for dropdown"""
    org = get_user_org(request.user)
    task_types = TaskType.objects.filter(org=org, is_active=True).order_by('sort_order', 'name')
    return Response(TaskTypeListSerializer(task_types, many=True).data)


# ========================================
# ========== GROUPED BLOCKS VIEW =========
# ========================================
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def blocks_grouped(request):
    """
    Get blocks grouped by Client → Project → TaskType
    For the hybrid categorization UI
    
    Query params:
        days: Number of days to look back (default 7)
        include_uncategorized: Include uncategorized blocks (default true)
    """
    org = get_user_org(request.user)
    days = int(request.query_params.get('days', 7))
    include_uncategorized = request.query_params.get('include_uncategorized', 'true').lower() == 'true'
    
    start_date = timezone.now() - timedelta(days=days)
    
    queryset = Block.objects.filter(
        org=org,
        user=request.user,
        start__gte=start_date,
    ).select_related('client', 'project', 'task_type').order_by('-start')
    
    if not include_uncategorized:
        queryset = queryset.filter(is_categorized=True)
    
    serializer = GroupedBlocksSerializer()
    grouped_data = serializer.to_representation(queryset)
    
    # Add summary stats
    total_minutes = sum(c['total_minutes'] for c in grouped_data)
    categorized_count = queryset.filter(is_categorized=True).count()
    uncategorized_count = queryset.filter(is_categorized=False).count()
    
    return Response({
        'summary': {
            'total_hours': round(total_minutes / 60, 1),
            'total_blocks': queryset.count(),
            'categorized': categorized_count,
            'uncategorized': uncategorized_count,
            'date_range': {
                'start': start_date.date().isoformat(),
                'end': timezone.now().date().isoformat(),
            }
        },
        'clients': grouped_data,
    })


# ========================================
# ========== TASK TYPE VIEWSET ===========
# ========================================
class TaskTypeViewSet(viewsets.ModelViewSet):
    """CRUD for firm-wide task types"""
    serializer_class = TaskTypeSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        org = get_user_org(self.request.user)
        return TaskType.objects.filter(org=org).order_by('sort_order', 'name')
    
    def perform_create(self, serializer):
        org = get_user_org(self.request.user)
        serializer.save(org=org)


# ========================================
# ========== BLOCK CATEGORIZATION ========
# ========================================
class BlockCategorizationViewSet(viewsets.ViewSet):
    """Endpoints for categorizing time blocks"""
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def uncategorized(self, request):
        """Get blocks that need categorization"""
        org = get_user_org(request.user)
        
        blocks = Block.objects.filter(
            org=org,
            user=request.user,
            is_categorized=False,
        ).select_related('client', 'project', 'task_type').order_by('-start')[:100]
        
        return Response(BlockSerializer(blocks, many=True).data)
    
    @action(detail=True, methods=['patch'], url_path='categorize')
    def categorize(self, request, pk=None):
        """Categorize a single block"""
        try:
            block = Block.objects.get(pk=pk, user=request.user)
        except Block.DoesNotExist:
            return Response({'error': 'Block not found'}, status=404)
        
        serializer = BlockCategorizationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        
        data = serializer.validated_data
        
        if 'client_id' in data and data['client_id']:
            block.client_id = data['client_id']
        if 'project_id' in data and data['project_id']:
            block.project_id = data['project_id']
        if 'task_type_id' in data and data['task_type_id']:
            block.task_type_id = data['task_type_id']
        if data.get('notes'):
            block.notes = data['notes']
        
        # Mark as categorized
        if not block.is_categorized:
            block.is_categorized = True
            block.categorized_by = 'manual'
            block.categorized_at = timezone.now()
        else:
            block.categorized_by = 'correction'
        
        block.save(force_update=True)
        
        return Response(BlockSerializer(block).data)
    
    @action(detail=False, methods=['post'], url_path='bulk')
    def bulk_categorize(self, request):
        """Categorize multiple blocks at once"""
        serializer = BulkCategorizationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        
        data = serializer.validated_data
        block_ids = data['block_ids']
        
        update_fields = {
            'is_categorized': True,
            'categorized_by': 'manual',
            'categorized_at': timezone.now(),
        }
        
        if data.get('client_id'):
            update_fields['client_id'] = data['client_id']
        if data.get('project_id'):
            update_fields['project_id'] = data['project_id']
        if data.get('task_type_id'):
            update_fields['task_type_id'] = data['task_type_id']
        
        updated = Block.objects.filter(
            id__in=block_ids,
            user=request.user,
            is_categorized=False,
        ).update(**update_fields)
        
        return Response({
            'updated': updated,
            'requested': len(block_ids),
        })


# tracker/views.py

from django.utils.text import slugify
import uuid

@api_view(['POST'])
@permission_classes([AllowAny])
def firm_signup(request):
    """
    New CPA firm signs up - creates org + owner user
    """
    # Validate input
    firm_name = request.data.get('firm_name')  # "Smith & Associates CPA"
    email = request.data.get('email')
    password = request.data.get('password')
    owner_name = request.data.get('name')  # "John Smith"
    
    if not all([firm_name, email, password]):
        return Response({'error': 'Missing required fields'}, status=400)
    
    # Check email not taken
    if User.objects.filter(email=email).exists():
        return Response({'error': 'Email already registered'}, status=400)
    
    # Create everything in a transaction
    from django.db import transaction
    
    with transaction.atomic():
        # 1. Create the organization
        base_slug = slugify(firm_name)[:40]
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        org = Organization.objects.create(
            name=firm_name,
            slug=slug,
            plan='trial',
            trial_ends_at=timezone.now() + timedelta(days=14),
        )
        

        # 3. Create the owner user
        username = email.split('@')[0][:30]
        if User.objects.filter(username=username).exists():
            username = f"{username}-{uuid.uuid4().hex[:6]}"
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=owner_name.split()[0] if owner_name else '',
            last_name=' '.join(owner_name.split()[1:]) if owner_name else '',
        )
                
        # 5. Create membership with owner role
        OrganizationMembership.objects.create(
            user=user,
            organization=org,
            role='owner',
        )
        
        # 6. Seed default TaskTypes for this org
        from tracker.models import TaskType, DEFAULT_CPA_TASK_TYPES
        for idx, tt_data in enumerate(DEFAULT_CPA_TASK_TYPES):
            TaskType.objects.create(
                org=org,
                name=tt_data['name'],
                code=tt_data['code'],
                color=tt_data['color'],
                is_billable=tt_data['is_billable'],
                sort_order=idx,
            )
    
    # Log them in
    from django.contrib.auth import login
    login(request, user)
    
    return Response({
        'success': True,
        'user': {
            'id': user.id,
            'email': user.email,
            'username': user.username,
        },
        'organization': {
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
            'plan': org.plan,
        }
    })

# tracker/views.py

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invite_team_member(request):
    """Owner/Admin invites a team member - enforces seat limits"""
    email = request.data.get('email')
    role = request.data.get('role', 'member')
    
    # Get user's org
    membership = request.user.memberships.first()
    if not membership or membership.role not in ['owner', 'admin']:
        return Response({'error': 'Not authorized to invite'}, status=403)
    
    org = membership.organization
    
    # ✅ CHECK SEAT AVAILABILITY
    current_member_count = OrganizationMembership.objects.filter(
        organization=org
    ).count()
    
    # Also count pending invitations (optional but recommended)
    pending_invites = Invitation.objects.filter(
        organization=org,
        accepted_at__isnull=True,  # ✅ Correct - invitation not yet accepted
        expires_at__gt=timezone.now()
    ).count()
    
    total_allocated = current_member_count + pending_invites
    
    if total_allocated >= org.seat_count:
        return Response({
            'error': 'No seats available',
            'message': f'Your plan has {org.seat_count} seat(s). Currently {current_member_count} member(s) and {pending_invites} pending invite(s).',
            'current_members': current_member_count,
            'pending_invites': pending_invites,
            'seat_count': org.seat_count,
            'seats_available': max(0, org.seat_count - total_allocated),
            'upgrade_required': True,
        }, status=403)
    
    # Check if email already has pending invite
    existing_invite = Invitation.objects.filter(
        organization=org,
        email=email,
        accepted=False,
        expires_at__gt=timezone.now()
    ).first()
    
    if existing_invite:
        return Response({
            'error': 'Invitation already sent',
            'message': f'An invitation was already sent to {email}',
        }, status=400)
    
    # Check if user is already a member
    from django.contrib.auth import get_user_model
    User = get_user_model()
    existing_user = User.objects.filter(email=email).first()
    if existing_user:
        existing_membership = OrganizationMembership.objects.filter(
            user=existing_user,
            organization=org
        ).exists()
        if existing_membership:
            return Response({
                'error': 'Already a member',
                'message': f'{email} is already a member of this organization',
            }, status=400)
    
    # Create invitation
    invite = Invitation.create_invite(org, email, role, request.user)
    
    # Send email (implement with your email service)
    invite_url = f"{settings.FRONTEND_URL}/invite/{invite.token}"
    # send_invite_email(email, invite_url, org.name, request.user.get_full_name())
    
    return Response({
        'success': True,
        'message': f'Invitation sent to {email}',
        'invite_url': invite_url,  # For testing - remove in production
        'seats_remaining': org.seat_count - total_allocated - 1,
    })



@api_view(['POST'])
@permission_classes([AllowAny])
def accept_invitation(request, token):
    """New user accepts invitation and creates account"""
    try:
        invite = Invitation.objects.get(
            token=token,
            accepted_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
    except Invitation.DoesNotExist:
        return Response({'error': 'Invalid or expired invitation'}, status=400)
    
    password = request.data.get('password')
    name = request.data.get('name', '')
    
    with transaction.atomic():
        # Create user
        username = invite.email.split('@')[0][:30]
        if User.objects.filter(username=username).exists():
            username = f"{username}-{uuid.uuid4().hex[:6]}"
        
        user = User.objects.create_user(
            username=username,
            email=invite.email,
            password=password,
            first_name=name.split()[0] if name else '',
        )
        
        # Create membership
        OrganizationMembership.objects.create(
            user=user,
            organization=invite.organization,
            role=invite.role,
            invited_by=invite.invited_by,
        )
        
        # Mark invitation as used
        invite.accepted_at = timezone.now()
        invite.save()
    
    login(request, user)
    
    return Response({
        'success': True,
        'organization': invite.organization.name,
    })


# tracker/views.py

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_client(request, client_id):
    """
    Delete (or deactivate) a client.
    Only owners/admins can delete clients.
    """
    user = request.user
    org = get_user_org(user)
    
    if not org:
        return Response({'error': 'No organization found'}, status=400)
    
    # Check permissions (optional - implement role check)
    membership = getattr(user, 'memberships', None)
    if membership:
        membership = membership.first()
        if membership and membership.role not in ['owner', 'admin']:
            return Response({'error': 'Not authorized to delete clients'}, status=403)
    
    try:
        client = Client.objects.get(id=client_id, org=org)
    except Client.DoesNotExist:
        return Response({'error': 'Client not found'}, status=404)
    
    # Check if client has blocks (soft delete if so)
    has_blocks = Block.objects.filter(client=client).exists()
    
    if has_blocks:
        # Soft delete - just deactivate
        client.is_active = False
        client.save()
        return Response({
            'ok': True,
            'action': 'deactivated',
            'message': f"Client '{client.name}' deactivated (has associated time blocks)"
        })
    else:
        # Hard delete - no associated data
        client_name = client.name
        client.delete()
        return Response({
            'ok': True,
            'action': 'deleted',
            'message': f"Client '{client_name}' permanently deleted"
        })


#############
#
# PROJECT MANAGEMENT UI
#
#############

# tracker/views.py

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_projects(request):
    """List all projects, optionally filtered by client"""
    org = get_user_org(request.user)
    client_id = request.GET.get('client_id')
    
    qs = Project.objects.filter(org=org, is_active=True).select_related('client')
    
    if client_id:
        qs = qs.filter(client_id=client_id)
    
    return Response([{
        'id': p.id,
        'name': p.name,
        'client_id': p.client_id,
        'client_name': p.client.name,
        'is_active': p.is_active,
    } for p in qs.order_by('client__name', 'name')])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_project(request):
    """Create a new project/engagement for a client"""
    org = get_user_org(request.user)
    data = request.data
    
    client_id = data.get('client_id')
    name = data.get('name', '').strip()
    
    if not client_id:
        return Response({'error': 'client_id is required'}, status=400)
    if not name:
        return Response({'error': 'name is required'}, status=400)
    
    # Verify client belongs to this org
    try:
        client = Client.objects.get(id=client_id, org=org)
    except Client.DoesNotExist:
        return Response({'error': 'Client not found'}, status=404)
    
    # Check for duplicate
    if Project.objects.filter(org=org, client=client, name=name).exists():
        return Response({'error': f"Project '{name}' already exists for this client"}, status=400)
    
    project = Project.objects.create(
        org=org,
        client=client,
        name=name,
        is_active=True,
    )
    
    return Response({
        'ok': True,
        'project': {
            'id': project.id,
            'name': project.name,
            'client_id': client.id,
            'client_name': client.name,
        }
    }, status=201)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_project(request, project_id):
    """Update a project"""
    org = get_user_org(request.user)
    
    try:
        project = Project.objects.get(id=project_id, org=org)
    except Project.DoesNotExist:
        return Response({'error': 'Project not found'}, status=404)
    
    data = request.data
    
    if 'name' in data:
        project.name = data['name'].strip()
    if 'is_active' in data:
        project.is_active = data['is_active']
    
    project.save()
    
    return Response({
        'ok': True,
        'project': {
            'id': project.id,
            'name': project.name,
            'client_id': project.client_id,
            'is_active': project.is_active,
        }
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_project(request, project_id):
    """Delete or deactivate a project"""
    org = get_user_org(request.user)
    
    try:
        project = Project.objects.get(id=project_id, org=org)
    except Project.DoesNotExist:
        return Response({'error': 'Project not found'}, status=404)
    
    # Check if project has blocks
    has_blocks = Block.objects.filter(project=project).exists()
    
    if has_blocks:
        project.is_active = False
        project.save()
        return Response({
            'ok': True,
            'action': 'deactivated',
            'message': f"Project '{project.name}' deactivated (has time entries)"
        })
    else:
        project_name = project.name
        project.delete()
        return Response({
            'ok': True,
            'action': 'deleted',
            'message': f"Project '{project_name}' permanently deleted"
        })



# Add this view to your tracker/views.py file
# This enables drag-and-drop recategorization in DailyReview

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def recategorize_block(request, block_id):
    """Move a block to a different category."""
    try:
        block = Block.objects.get(id=block_id, user=request.user)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)
    
    new_category = request.data.get('category')
    new_client_id = request.data.get('client_id')
    
    if not new_category:
        return Response({"error": "category required"}, status=400)
    
    # Track old category
    old_category = None
    if block.category_hours:
        old_category = list(block.category_hours.keys())[0] if block.category_hours else None
    
    # Calculate duration
    duration = (block.end - block.start).total_seconds() / 3600 if block.end and block.start else 0
    block.category_hours = {new_category: round(duration, 2)}
    
    # Mark as user correction
    block.categorized_by = 'correction'
    block.categorized_at = timezone.now()
    
    # Optionally update client
    if new_client_id:
        try:
            block.client = Client.objects.get(id=new_client_id)
        except Client.DoesNotExist:
            pass
    
    # ✅ CRITICAL: force_update=True bypasses immutability protection
    block.save(force_update=True)
    
    return Response({
        "success": True,
        "block_id": block.id,
        "old_category": old_category,
        "new_category": new_category
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_manual_time_entry(request):
    """
    Create a manual time entry.
    
    Body: {
        "client_id": int (required),
        "category": str (required),
        "date": "YYYY-MM-DD" (required),
        "hours": float (required) - e.g., 1.5 for 1 hour 30 min,
        "start_time": "HH:MM" (optional) - defaults to 09:00,
        "notes": str (optional)
    }
    """
    user = request.user
    data = request.data
    
    # Validate required fields
    client_id = data.get('client_id')
    category = data.get('category', '').strip()
    date_str = data.get('date')
    hours = data.get('hours')
    
    if not client_id:
        return Response({"error": "client_id is required"}, status=400)
    if not category:
        return Response({"error": "category is required"}, status=400)
    if not date_str:
        return Response({"error": "date is required"}, status=400)
    if not hours:
        return Response({"error": "hours is required"}, status=400)
    
    try:
        hours = float(hours)
        if hours <= 0 or hours > 24:
            return Response({"error": "hours must be between 0 and 24"}, status=400)
    except (ValueError, TypeError):
        return Response({"error": "hours must be a number"}, status=400)
    
    # Get org
    org = get_user_org(user)
    if not org:
        org, _ = Organization.objects.get_or_create(name="default-org", defaults={"slug": "default-org"})
    
    # Get client
    try:
        client = Client.objects.get(id=client_id, org=org)
    except Client.DoesNotExist:
        return Response({"error": "Client not found"}, status=404)
    
    # Parse date and time
    try:
        entry_date = parse_date(date_str)
        if not entry_date:
            raise ValueError("Invalid date")
    except Exception:
        return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
    
    # Parse start time or default to 9am
    start_time_str = data.get('start_time', '09:00')
    try:
        hour, minute = map(int, start_time_str.split(':'))
        start_time = dt_time(hour, minute)
    except Exception:
        start_time = dt_time(9, 0)
    
    # Calculate start and end datetime
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(dt.combine(entry_date, start_time), tz)
    
    # Calculate end time based on hours
    minutes = int(hours * 60)
    end_dt = start_dt + timedelta(minutes=minutes)
    
    # Get notes
    notes = data.get('notes', '').strip()
    
    # Create the block
    block = Block.objects.create(
        user=user,
        org=org,
        client=client,
        start=start_dt,
        end=end_dt,
        minutes=minutes,
        title=f"Manual: {category}",
        window_title=f"Manual entry - {client.name}",
        category_hours={category: round(hours, 2)},
        is_categorized=True,
        categorized_at=timezone.now(),
        categorized_by='manual',
        notes=notes,
        app_name='manual_entry',
    )
    
    return Response({
        "success": True,
        "block_id": block.id,
        "client": client.name,
        "category": category,
        "hours": round(hours, 2),
        "date": entry_date.isoformat(),
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }, status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_block(request, block_id):
    """
    Delete a time block.
    
    Only allows deleting blocks that belong to the user.
    """
    user = request.user
    
    try:
        block = Block.objects.get(id=block_id, user=user)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)
    
    # Store info for response
    block_info = {
        "block_id": block.id,
        "title": block.title,
        "minutes": block.minutes,
        "client": block.client.name if block.client else "Unassigned",
    }
    
    # Delete the block
    block.deleted_at = timezone.now()
    block.save(force_update=True)  # force_update bypasses your protection check
    
    return Response({
        "success": True,
        "message": "Block deleted successfully",
        **block_info
    })



@api_view(["POST"])
@permission_classes([AllowAny])  # No auth - uses org token
def register_agent(request):
    """
    Register a new agent installation using org token.
    Called by desktop agent on first launch.
    
    Body: {
        "org_token": "tt_org_abc123...",
        "machine_name": "LAPTOP-ABC",
        "os": "windows" | "macos",
        "os_version": "Windows 11" | "macOS 14.0",
        "username": "jsmith"  # System username
    }
    
    Returns:
        - agent_key: For future API auth
        - user_id: Created or matched user
    """
    data = request.data
    org_token = data.get('org_token', '').strip()
    machine_name = data.get('machine_name', '').strip()
    os_type = data.get('os', '').strip()
    os_version = data.get('os_version', '').strip()
    username = data.get('username', '').strip().lower()
    
    if not org_token:
        return Response({"error": "org_token is required"}, status=400)
    if not username:
        return Response({"error": "username is required"}, status=400)
    
    # Validate org token
    try:
        install_token = OrgInstallToken.objects.select_related('org').get(
            token=org_token,
            is_active=True
        )
    except OrgInstallToken.DoesNotExist:
        return Response({"error": "Invalid or expired org token"}, status=401)
    
    org = install_token.org
    
    # Find or create user
    user, user_created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': f'{username}@{org.name.lower().replace(" ", "")}.local',
            'first_name': username.title(),
        }
    )
    
    # Add user to org if not already
    if org not in user.groups.all():
        user.groups.add(org)
    
    # Create or update agent registration
    agent, agent_created = AgentRegistration.objects.update_or_create(
        user=user,
        machine_name=machine_name,
        defaults={
            'org': org,
            'os': os_type,
            'os_version': os_version,
            'last_seen': timezone.now(),
            'is_active': True,
        }
    )
    
    # Generate agent key if new
    if agent_created or not agent.agent_key:
        agent.agent_key = f"tt_agent_{secrets.token_urlsafe(32)}"
        agent.save()
    
    return Response({
        "success": True,
        "agent_key": agent.agent_key,
        "user_id": user.id,
        "username": user.username,
        "org_name": org.name,
        "is_new_user": user_created,
        "is_new_agent": agent_created,
    }, status=201 if agent_created else 200)



from django.contrib.auth.models import User, Group
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
import secrets


# ============================================================================
# Organization Info
# ============================================================================

# UPDATED settings_org() function for tracker/views.py
# This version doesn't assume billing_email/billing_contact fields exist

# Replace your settings_org function in tracker/views.py with this:

# Add this updated settings_org function to your views.py
# Replace the existing settings_org function with this one
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def settings_org(request):
    """GET/PATCH organization settings including industry_type."""
    from decimal import Decimal
    from tracker.industry_categories import INDUSTRY_CHOICES

    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()

    if not membership:
        return Response({"error": "No organization found"}, status=404)

    org = membership.organization
    is_admin_or_owner = membership.role in ["owner", "admin"]
    profile, _ = OrgProfile.objects.get_or_create(org=org)

    if request.method == "GET":
        return Response({
            "id": org.id,
            "name": org.name,
            "slug": getattr(org, "slug", "") or "",
            "industry_type": getattr(org, 'industry_type', 'general') or 'general',  # ✅ ADD
            "industry_name": dict(INDUSTRY_CHOICES).get(
                getattr(org, 'industry_type', 'general'), 
                'General Professional Services'
            ),  # ✅ Human-readable
            "plan": getattr(org, "plan", "none"),
            "seat_count": getattr(org, "seat_count", 1),
            "trial_ends_at": org.trial_ends_at.isoformat() if getattr(org, "trial_ends_at", None) else None,
            "billing_email": profile.billing_email or "",
            "billing_contact": profile.billing_contact or "",
            "billing_rate_default": str(getattr(org, "billing_rate_default", None) or "150.00"),
            "cost_rate_default": str(getattr(org, "cost_rate_default", None) or "75.00") if is_admin_or_owner else "0.00",
            "created_at": org.created_at.isoformat() if getattr(org, "created_at", None) else None,
            "can_edit_org": is_admin_or_owner,
            "role": membership.role,
        })

    # PATCH
    if not is_admin_or_owner:
        return Response({"error": "Only owner/admin can update"}, status=403)

    if "name" in request.data:
        org.name = request.data["name"]

    # ✅ Allow updating industry_type
    if "industry_type" in request.data:
        new_industry = request.data["industry_type"]
        valid_industries = [choice[0] for choice in INDUSTRY_CHOICES]
        if new_industry in valid_industries:
            org.industry_type = new_industry

    if "billing_rate_default" in request.data:
        org.billing_rate_default = Decimal(str(request.data["billing_rate_default"]))

    if "cost_rate_default" in request.data:
        org.cost_rate_default = Decimal(str(request.data["cost_rate_default"]))

    org.save()

    if "billing_email" in request.data:
        profile.billing_email = (request.data.get("billing_email") or "").strip() or None
    if "billing_contact" in request.data:
        profile.billing_contact = (request.data.get("billing_contact") or "").strip()
    profile.save()

    return Response({
        "id": org.id,
        "name": org.name,
        "industry_type": getattr(org, 'industry_type', 'general'),
        "industry_name": dict(INDUSTRY_CHOICES).get(getattr(org, 'industry_type', 'general'), 'General'),
        "plan": org.plan,
        "message": "Settings updated"
    })


# ============================================================================
# Team Members
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_list(request):
    """List all team members in the organization"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    memberships = OrganizationMembership.objects.filter(
        organization=org
    ).select_related('user')
    
    result = []
    for membership in memberships:  # ✅ Fixed: was 'members'
        user = membership.user       # ✅ Get user from membership
        result.append({
            "id": user.id,
            "username": user.username,
            "email": user.email or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "is_active": user.is_active,
            "role": membership.role,  # ✅ Add role from membership
            "is_admin": membership.role in ['owner', 'admin'],  # ✅ Use membership role
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        })
    
    return Response(result)


# Update settings_team_invite in tracker/views.py
# This uses your existing OrganizationMembership model

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_invite(request):
    """
    Invite a new team member by email.
    Creates user, OrganizationMembership, and sends invitation email.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    org = get_user_org(request.user)  # This should return Organization object
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    email = (request.data.get("email") or "").strip().lower()
    if not email:
        return Response({"error": "Email is required"}, status=400)
    
    logger.info(f"[INVITE] Processing invite for: {email}")
    
    # Check if user already exists
    existing = User.objects.filter(email=email).first()
    if existing:
        # Check if already in this org
        if OrganizationMembership.objects.filter(user=existing, organization=org).exists():
            return Response({"error": "User is already a team member"}, status=400)
        
        # Add to org with member role
        OrganizationMembership.objects.create(
            user=existing,
            organization=org,
            role='member',
            invited_by=request.user
        )
        
        return Response({
            "success": True,
            "message": "Existing user added to team",
            "user_id": existing.id,
        })
    
    # Create new user
    username = email.split("@")[0].lower()
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    
    # Generate temporary password
    temp_password = secrets.token_urlsafe(12)
    
    user = User.objects.create_user(
        username=username,
        email=email,
        password=temp_password,
        is_active=True,
    )
    logger.info(f"[INVITE] Created user: {username}")
    
    # Create OrganizationMembership with member role
    OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role='member',
        invited_by=request.user
    )
    logger.info(f"[INVITE] Created membership with member role")
    
    # Send invitation email
    logger.info(f"[INVITE] Attempting to send email to: {email}")
    logger.info(f"[INVITE] From: {settings.DEFAULT_FROM_EMAIL}")
    logger.info(f"[INVITE] SMTP: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
    
    email_sent = False
    error_message = None
    
    try:
        from tracker.email_service import send_team_invitation
        email_sent = send_team_invitation(
            to_email=email,
            org_name=org.name,
            username=username,
            temp_password=temp_password,
            invited_by=request.user.get_full_name() or request.user.username,
        )
        logger.info(f"[INVITE] ✅ Email sent successfully! Result: {email_sent}")
        email_sent = True
    except Exception as e:
        error_message = str(e)
        logger.error(f"[INVITE] ❌ Failed to send email: {e}")
        logger.exception("Full email error traceback:")
    
    return Response({
        "success": True,
        "message": "User invited" if email_sent else f"User created (email failed: {error_message})",
        "user_id": user.id,
        "username": username,
        "temp_password": temp_password,
        "email_sent": email_sent,
    }, status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_remove(request, user_id):
    """Remove a team member from the organization"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    # Can't remove yourself
    if user_id == request.user.id:
        return Response({"error": "Cannot remove yourself"}, status=400)
    
    try:
        member = User.objects.get(id=user_id, groups=org)
    except User.DoesNotExist:
        return Response({"error": "User not found"}, status=404)
    
    # Remove from org
    member.groups.remove(org)
    
    return Response({
        "success": True,
        "message": f"Removed {member.username} from team",
    })


# ============================================================================
# Clients
# ============================================================================

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_clients(request):
    """
    GET: List all clients for the organization
    POST: Create a new client
    """
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    if request.method == "GET":
        clients = Client.objects.filter(org=org).order_by("name")
        result = []
        for client in clients:
            result.append({
                "id": client.id,
                "name": client.name,
                "code": client.code or "",
                "is_active": client.is_active if hasattr(client, 'is_active') else True,
                "created_at": client.created_at.isoformat() if hasattr(client, 'created_at') and client.created_at else "",
            })
        return Response(result)
    
    elif request.method == "POST":
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip().upper()
        
        if not name:
            return Response({"error": "Name is required"}, status=400)
        
        # Check for duplicate name in org
        if Client.objects.filter(org=org, name__iexact=name).exists():
            return Response({"error": "Client with this name already exists"}, status=400)
        
        client = Client.objects.create(
            org=org,
            name=name,
            code=code or None,
        )
        
        return Response({
            "success": True,
            "id": client.id,
            "name": client.name,
            "code": client.code or "",
        }, status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_client_detail(request, client_id):
    """
    PATCH: Update a client
    DELETE: Delete a client
    """
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    try:
        client = Client.objects.get(id=client_id, org=org)
    except Client.DoesNotExist:
        return Response({"error": "Client not found"}, status=404)
    
    if request.method == "PATCH":
        if "name" in request.data:
            client.name = request.data["name"].strip()
        if "code" in request.data:
            client.code = request.data["code"].strip().upper() or None
        if "is_active" in request.data:
            client.is_active = bool(request.data["is_active"])
        client.save()
        
        return Response({
            "success": True,
            "id": client.id,
            "name": client.name,
            "code": client.code or "",
        })
    
    elif request.method == "DELETE":
        client_name = client.name
        client.delete()
        return Response({
            "success": True,
            "message": f"Deleted client: {client_name}",
        })


# ============================================================================
# Devices (Agent Registrations)
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_devices(request):
    """List all registered devices/agents for the organization"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    devices = AgentRegistration.objects.filter(org=org).select_related("user").order_by("-last_seen")
    
    result = []
    for device in devices:
        result.append({
            "id": device.id,
            "user": device.user.username,
            "user_id": device.user.id,
            "machine_name": device.machine_name,
            "os": device.os,
            "os_version": device.os_version or "",
            "agent_version": device.agent_version or "",
            "first_seen": device.first_seen.isoformat() if device.first_seen else "",
            "last_seen": device.last_seen.isoformat() if device.last_seen else "",
            "is_active": device.is_active,
        })
    
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_device_deactivate(request, device_id):
    """Deactivate a device (revoke its agent key)"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    try:
        device = AgentRegistration.objects.get(id=device_id, org=org)
    except AgentRegistration.DoesNotExist:
        return Response({"error": "Device not found"}, status=404)
    
    device.is_active = False
    device.agent_key = f"revoked_{device.agent_key}"  # Invalidate the key
    device.save()
    
    return Response({
        "success": True,
        "message": f"Deactivated device: {device.machine_name}",
    })


# ============================================================================
# Install Token
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_install_token(request):
    """Get the organization's install token"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    try:
        token = OrgInstallToken.objects.get(org=org, is_active=True)
        return Response({
            "token": token.token,
            "created_at": token.created_at.isoformat(),
            "is_active": token.is_active,
        })
    except OrgInstallToken.DoesNotExist:
        return Response({
            "token": None,
            "created_at": None,
            "is_active": False,
        })


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_install_token_regenerate(request):
    """Regenerate the organization's install token"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    # Deactivate existing token
    OrgInstallToken.objects.filter(org=org).update(is_active=False)
    
    # Create new token
    token = OrgInstallToken.objects.create(
        org=org,
        created_by=request.user,
        is_active=True,
    )
    
    return Response({
        "success": True,
        "token": token.token,
        "created_at": token.created_at.isoformat(),
        "is_active": token.is_active,
    })

# Add these NEW endpoints to tracker/views.py
# These use your existing OrganizationMembership model

@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_promote(request, user_id):
    """
    Promote a member to admin or manager to admin (owners only).
    """
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    # Check requester is owner
    if not is_org_owner(request.user, org):
        return Response({"error": "Only owners can promote users"}, status=403)
    
    # Get target user membership
    try:
        membership = OrganizationMembership.objects.get(
            user_id=user_id,
            organization=org
        )
    except OrganizationMembership.DoesNotExist:
        return Response({"error": "User not found in this organization"}, status=404)
    
    if membership.role == 'owner':
        return Response({"error": "User is already owner"}, status=400)
    
    if membership.role == 'admin':
        return Response({"error": "User is already admin"}, status=400)
    
    # Promote to admin (from member or manager)
    old_role = membership.role
    membership.role = 'admin'
    membership.save()
    
    return Response({
        "success": True,
        "message": f"Promoted from {old_role} to admin",
        "user_id": membership.user.id,
        "username": membership.user.username,
        "old_role": old_role,
        "new_role": "admin",
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_demote(request, user_id):
    """
    Demote admin to member or manager (owners only).
    Optionally specify target_role in request body.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    # Check requester is owner
    if not is_org_owner(request.user, org):
        return Response({"error": "Only owners can demote users"}, status=403)
    
    # Can't demote yourself
    if user_id == request.user.id:
        return Response({"error": "Cannot demote yourself"}, status=400)
    
    # Get target user membership
    try:
        membership = OrganizationMembership.objects.get(
            user_id=user_id,
            organization=org
        )
    except OrganizationMembership.DoesNotExist:
        return Response({"error": "User not found in this organization"}, status=404)
    
    if membership.role == 'owner':
        return Response({"error": "Cannot demote owner. Transfer ownership first."}, status=400)
    
    if membership.role == 'member':
        return Response({"error": "User is already a member"}, status=400)
    
    # Get target role from request (default to member)
    target_role = request.data.get('target_role', 'member')
    if target_role not in ['member', 'manager']:
        return Response({"error": "Invalid target role. Must be 'member' or 'manager'"}, status=400)
    
    # Demote
    old_role = membership.role
    membership.role = target_role
    membership.save()
    
    return Response({
        "success": True,
        "message": f"Demoted from {old_role} to {target_role}",
        "user_id": membership.user.id,
        "username": membership.user.username,
        "old_role": old_role,
        "new_role": target_role,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_set_manager(request, user_id):
    """
    Promote a member to manager (owners and admins can do this).
    Managers can approve timecards but can't access full settings.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    # Check requester is owner or admin
    if not is_org_admin_or_owner(request.user, org):
        return Response({"error": "Only owners and admins can promote to manager"}, status=403)
    
    # Get target user membership
    try:
        membership = OrganizationMembership.objects.get(
            user_id=user_id,
            organization=org
        )
    except OrganizationMembership.DoesNotExist:
        return Response({"error": "User not found in this organization"}, status=404)
    
    if membership.role in ['owner', 'admin']:
        return Response({"error": "Cannot change owner/admin role to manager"}, status=400)
    
    if membership.role == 'manager':
        return Response({"error": "User is already a manager"}, status=400)
    
    # Promote to manager
    membership.role = 'manager'
    membership.save()
    
    return Response({
        "success": True,
        "message": f"Promoted to manager",
        "user_id": membership.user.id,
        "username": membership.user.username,
        "new_role": "manager",
    })


@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_remove(request, user_id):
    """Remove a team member from the organization"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    # Can't remove yourself
    if user_id == request.user.id:
        return Response({"error": "Cannot remove yourself"}, status=400)
    
    try:
        membership = OrganizationMembership.objects.get(
            user_id=user_id,
            organization=org
        )
        
        # Cannot remove owner
        if membership.role == 'owner':
            return Response({"error": "Cannot remove owner. Transfer ownership first."}, status=400)
        
        username = membership.user.username
        membership.delete()
        
        return Response({
            "success": True,
            "message": f"Removed {username} from team",
        })
        
    except OrganizationMembership.DoesNotExist:
        return Response({"error": "User not found in this organization"}, status=404)

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

@receiver(user_logged_in)
def update_last_login(sender, user, **kwargs):
    """Update last_login timestamp when user logs in"""
    logger.info(f"[LOGIN] Signal fired for user: {user.username}")
    user.last_login = timezone.now()
    user.save(update_fields=['last_login'])



class CurrentMembershipView(APIView):
    """
    GET: Return current user's organization membership including role
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        membership = OrganizationMembership.objects.filter(
            user=request.user,
        ).select_related('organization').first()
        
        if not membership:
            return Response({'error': 'No organization membership'}, status=404)
        
        return Response({
            'id': membership.id,
            'role': membership.role,
            'is_active': membership.is_active,
            'organization': {
                'id': membership.organization.id,
                'name': membership.organization.name,
            },
            'user': {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
            }
        })

# Add this to tracker/views.py

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def auth_change_password(request):
    """
    Change the authenticated user's password.
    
    POST body:
    {
        "current_password": "oldpassword",
        "new_password": "newpassword"
    }
    """
    user = request.user
    
    current_password = request.data.get('current_password', '')
    new_password = request.data.get('new_password', '')
    
    if not current_password:
        return Response({'error': 'Current password is required'}, status=400)
    
    if not new_password:
        return Response({'error': 'New password is required'}, status=400)
    
    if len(new_password) < 8:
        return Response({'error': 'New password must be at least 8 characters'}, status=400)
    
    # Verify current password
    if not user.check_password(current_password):
        return Response({'error': 'Current password is incorrect'}, status=400)
    
    # Don't allow same password
    if current_password == new_password:
        return Response({'error': 'New password must be different from current password'}, status=400)
    
    # Set new password
    user.set_password(new_password)
    user.save()
    
    return Response({
        'success': True,
        'message': 'Password changed successfully'
    })


# views.py - Add sync check endpoint
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sync_check(request):
    membership = OrganizationMembership.objects.get(user=request.user)
    org = membership.organization
    
    # Get latest update timestamps
    latest_client = Client.objects.filter(organization=org).order_by('-updated_at').first()
    
    return Response({
        'clients_updated': latest_client.updated_at if latest_client else None,
        'server_time': timezone.now(),
    })



from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Count
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@api_view(['POST'])
def agent_error_report(request):
    """
    Receive error reports from desktop agents.
    POST /api/agent/errors/
    
    No auth required - uses device_id to find user.
    """
    from tracker.models import AgentError, Device
    
    data = request.data
    device_id = data.get('device_id')
    
    # Find user from device
    user = None
    org = None
    if device_id:
        try:
            device = Device.objects.select_related('user', 'org').get(device_id=device_id)
            user = device.user
            org = device.org
        except Device.DoesNotExist:
            pass
    
    # Parse client timestamp
    client_ts = None
    if data.get('timestamp'):
        try:
            from dateutil.parser import parse
            client_ts = parse(data['timestamp'])
        except:
            pass
    
    # Create error record
    error = AgentError.objects.create(
        user=user,
        org=org,
        error_type=data.get('error_type', 'unknown')[:50],
        error_message=data.get('error_message', '')[:5000],
        traceback=data.get('traceback', '')[:10000],
        device_id=device_id or 'unknown',
        hostname=data.get('hostname', '')[:100],
        app_version=data.get('app_version', '')[:20],
        platform=data.get('platform', '')[:100],
        python_version=data.get('python_version', '')[:20],
        os_username=data.get('os_username', '')[:100],
        context=data.get('context', {}),
        client_timestamp=client_ts,
    )
    
    # Log for immediate visibility
    logger.warning(
        f"[AGENT-ERROR] id={error.id} | {error.error_type} | "
        f"user={user.username if user else '?'} | "
        f"host={error.hostname} | v={error.app_version}"
    )

    maybe_send_alert(error)
    
    return Response({"ok": True, "error_id": error.id})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_errors_list(request):
    """
    List agent errors with filtering.
    GET /api/agent/errors/list/
    
    Query params:
    - user_id: Filter by user
    - device_id: Filter by device
    - hostname: Filter by hostname (partial match)
    - error_type: Filter by error type
    - app_version: Filter by version
    - resolved: true/false
    - days: Last N days (default 7)
    - limit: Max results (default 100)
    """
    from tracker.models import AgentError
    
    # Check if user is admin/manager
    if not request.user.is_staff:
        # Regular users can only see their own errors
        qs = AgentError.objects.filter(user=request.user)
    else:
        qs = AgentError.objects.all()
    
    # Filters
    if request.GET.get('user_id'):
        qs = qs.filter(user_id=request.GET['user_id'])
    
    if request.GET.get('device_id'):
        qs = qs.filter(device_id=request.GET['device_id'])
    
    if request.GET.get('hostname'):
        qs = qs.filter(hostname__icontains=request.GET['hostname'])
    
    if request.GET.get('error_type'):
        qs = qs.filter(error_type=request.GET['error_type'])
    
    if request.GET.get('app_version'):
        qs = qs.filter(app_version=request.GET['app_version'])
    
    if request.GET.get('resolved'):
        qs = qs.filter(resolved=request.GET['resolved'].lower() == 'true')
    
    # Time filter
    days = int(request.GET.get('days', 7))
    cutoff = timezone.now() - timedelta(days=days)
    qs = qs.filter(created_at__gte=cutoff)
    
    # Limit
    limit = min(int(request.GET.get('limit', 100)), 500)
    
    errors = qs.select_related('user')[:limit]
    
    return Response({
        "count": qs.count(),
        "errors": [
            {
                "id": e.id,
                "error_type": e.error_type,
                "error_message": e.error_message[:200],
                "user": e.user.username if e.user else None,
                "hostname": e.hostname,
                "device_id": e.device_id[:12],
                "app_version": e.app_version,
                "created_at": e.created_at.isoformat(),
                "resolved": e.resolved,
            }
            for e in errors
        ]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_errors_summary(request):
    """
    Summary dashboard of agent errors.
    GET /api/agent/errors/summary/
    """
    from tracker.models import AgentError
    
    if not request.user.is_staff:
        return Response({"error": "Admin only"}, status=403)
    
    days = int(request.GET.get('days', 7))
    cutoff = timezone.now() - timedelta(days=days)
    
    qs = AgentError.objects.filter(created_at__gte=cutoff)
    
    # Summary stats
    total = qs.count()
    unresolved = qs.filter(resolved=False).count()
    
    # By error type
    by_type = list(
        qs.values('error_type')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )
    
    # By app version
    by_version = list(
        qs.values('app_version')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )
    
    # Most affected users
    by_user = list(
        qs.filter(user__isnull=False)
        .values('user__username', 'hostname')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )
    
    # Recent unique errors (deduped by type + message)
    recent = list(
        qs.order_by('-created_at')
        .values('error_type', 'error_message', 'hostname', 'app_version', 'created_at')[:20]
    )
    
    return Response({
        "period_days": days,
        "total_errors": total,
        "unresolved": unresolved,
        "by_error_type": by_type,
        "by_app_version": by_version,
        "most_affected_users": by_user,
        "recent_errors": recent,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_error_detail(request, error_id):
    """
    Get full error details including traceback.
    GET /api/agent/errors/<id>/
    """
    from tracker.models import AgentError
    
    try:
        error = AgentError.objects.select_related('user', 'resolved_by').get(id=error_id)
    except AgentError.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    
    # Check permissions
    if not request.user.is_staff and error.user != request.user:
        return Response({"error": "Forbidden"}, status=403)
    
    return Response({
        "id": error.id,
        "error_type": error.error_type,
        "error_message": error.error_message,
        "traceback": error.traceback,
        "user": error.user.username if error.user else None,
        "hostname": error.hostname,
        "device_id": error.device_id,
        "app_version": error.app_version,
        "platform": error.platform,
        "python_version": error.python_version,
        "os_username": error.os_username,
        "context": error.context,
        "created_at": error.created_at.isoformat(),
        "client_timestamp": error.client_timestamp.isoformat() if error.client_timestamp else None,
        "resolved": error.resolved,
        "resolved_at": error.resolved_at.isoformat() if error.resolved_at else None,
        "resolved_by": error.resolved_by.username if error.resolved_by else None,
        "notes": error.notes,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def agent_error_resolve(request, error_id):
    """
    Mark an error as resolved.
    POST /api/agent/errors/<id>/resolve/
    """
    from tracker.models import AgentError
    
    if not request.user.is_staff:
        return Response({"error": "Admin only"}, status=403)
    
    try:
        error = AgentError.objects.get(id=error_id)
    except AgentError.DoesNotExist:
        return Response({"error": "Not found"}, status=404)
    
    error.resolved = True
    error.resolved_at = timezone.now()
    error.resolved_by = request.user
    error.notes = request.data.get('notes', '')
    error.save()
    
    return Response({"ok": True})


from django.conf import settings
from django.utils import timezone
from datetime import timedelta

def maybe_send_alert(error):
    '''Send email for critical errors.'''
    CRITICAL_TYPES = ['tracking_fatal', 'tracking_loop_critical']
    
    if error.error_type not in CRITICAL_TYPES:
        return
    
    # Only alert once per device per hour
    recent = AgentError.objects.filter(
        device_id=error.device_id,
        error_type=error.error_type,
        created_at__gte=timezone.now() - timedelta(hours=1)
    ).count()
    
    if recent > 1:
        return  # Already alerted
    
    from tracker.email_service import send_critical_error_alert
    send_critical_error_alert(
        error_type=error.error_type,
        username=error.user.username if error.user else 'Unknown',
        hostname=error.hostname,
        device_id=error.device_id,
        app_version=error.app_version,
        error_message=error.error_message,
        error_id=error.id,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_org_categories(request):
    """Get the category list for the current user's organization."""
    from tracker.industry_categories import get_categories_for_industry, INDUSTRY_CHOICES, GENERAL_CATEGORIES
    
    org = get_user_org(request.user)
    if not org:
        return Response({
            'industry_type': 'general',
            'industry_name': 'General Professional Services',
            'categories': GENERAL_CATEGORIES
        })
    
    industry_type = getattr(org, 'industry_type', 'general') or 'general'
    categories = get_categories_for_industry(industry_type)
    industry_name = dict(INDUSTRY_CHOICES).get(industry_type, 'General Professional Services')
    
    return Response({
        'industry_type': industry_type,
        'industry_name': industry_name,
        'categories': categories
    })
    

@api_view(['GET'])
@permission_classes([AllowAny])
def get_industry_options(request):
    """Get available industry types for signup form."""
    from tracker.industry_categories import INDUSTRY_TYPES
    
    return Response({
        'industries': [
            {'value': k, 'label': v}
            for k, v in INDUSTRY_TYPES
        ]
    })


from datetime import date, timedelta, datetime, time as dt_time
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, F, ExpressionWrapper, DurationField
from django.db.models.functions import Coalesce

# Adjust these imports to match your actual model locations
# from .models import TimeBlock, Timesheet


def yesterday_summary(request):
    """
    GET /api/timesheet/yesterday-summary/
    
    Auth: DeviceKey header (device token) or session auth
    
    Returns:
    {
        "date": "2026-02-06",
        "total_hours": 7.5,
        "status": "draft",  // draft | submitted | approved
        "entries": [
            {"client_name": "Acme Corp", "client_id": 1, "hours": 3.5},
            {"client_name": "Beta Industries", "client_id": 2, "hours": 2.0},
            {"client_name": "Uncategorized", "client_id": null, "hours": 2.0}
        ],
        "entry_count": 12,
        "has_unassigned": true
    }
    """
    user = request.user
    if not user or not user.is_authenticated:
        return JsonResponse({"error": "unauthorized"}, status=401)

    yesterday = date.today() - timedelta(days=1)

    # ── Adjust the query below to match YOUR actual models ──
    # This assumes you have something like:
    #   TimeBlock(user, client, start_time, end_time, ...)
    #   Timesheet(user, date, status, ...)
    
    try:
        from timeblocks.models import TimeBlock  # adjust import path
    except ImportError:
        # Fallback - adjust to your actual model location
        from .models import TimeBlock

    # Get yesterday's time blocks for this user
    yesterday_start = timezone.make_aware(datetime.combine(yesterday, dt_time.min))
    yesterday_end = timezone.make_aware(datetime.combine(yesterday, dt_time.max))

    blocks = TimeBlock.objects.filter(
        user=user,
        start_time__gte=yesterday_start,
        start_time__lte=yesterday_end,
    )

    # Group by client
    client_hours = {}
    total_seconds = 0
    has_unassigned = False

    for block in blocks:
        # Calculate duration
        if block.end_time and block.start_time:
            duration = (block.end_time - block.start_time).total_seconds()
        elif hasattr(block, 'duration_seconds') and block.duration_seconds:
            duration = block.duration_seconds
        else:
            duration = 0

        total_seconds += duration

        # Get client info
        client_id = getattr(block, 'client_id', None)
        client_name = "Uncategorized"

        if client_id and hasattr(block, 'client') and block.client:
            client_name = getattr(block.client, 'name', str(client_id))
        elif not client_id:
            has_unassigned = True

        key = client_id or "unassigned"
        if key not in client_hours:
            client_hours[key] = {
                "client_name": client_name,
                "client_id": client_id,
                "seconds": 0,
            }
        client_hours[key]["seconds"] += duration

    # Convert to hours and sort by hours desc
    entries = []
    for data in client_hours.values():
        entries.append({
            "client_name": data["client_name"],
            "client_id": data["client_id"],
            "hours": round(data["seconds"] / 3600, 2),
        })
    entries.sort(key=lambda e: e["hours"], reverse=True)

    total_hours = round(total_seconds / 3600, 2)

    # ── Get timesheet status ──
    status = "draft"
    try:
        from timesheets.models import Timesheet  # adjust import path
        ts = Timesheet.objects.filter(user=user, date=yesterday).first()
        if ts:
            status = getattr(ts, 'status', 'draft')
    except (ImportError, Exception):
        # If no Timesheet model, infer from blocks
        # If all blocks have been submitted/approved, mark accordingly
        pass

    return JsonResponse({
        "date": yesterday.isoformat(),
        "total_hours": total_hours,
        "status": status,
        "entries": entries,
        "entry_count": blocks.count(),
        "has_unassigned": has_unassigned,
    })


import time
import json
import urllib.request
from django.http import JsonResponse
from django.views.decorators.http import require_GET

# ── Config ──
GITHUB_REPO = "druss16/timetracker-releases"
CACHE_TTL = 300  # 5 minutes — don't hammer GitHub API

# ── Cache ──
_cache = {"version": None, "fetched_at": 0}


def _fetch_latest_version() -> str:
    """Get latest release tag from GitHub. Returns version string like '1.5.0'."""
    now = time.time()

    # Return cached if fresh
    if _cache["version"] and (now - _cache["fetched_at"]) < CACHE_TTL:
        return _cache["version"]

    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            tag = data.get("tag_name", "").lstrip("v")
            if tag:
                _cache["version"] = tag
                _cache["fetched_at"] = now
                return tag
    except Exception as e:
        print(f"[VERSION] GitHub API error: {e}")

    # Fallback to cached even if stale
    return _cache["version"] or "0.0.0"


def _is_newer(latest: str, current: str) -> bool:
    try:
        def p(v): return tuple(int(x) for x in v.strip().lstrip('v').split('.'))
        return p(latest) > p(current)
    except Exception:
        return latest != current


@require_GET
def agent_version_check(request):
    current = request.GET.get('version', '')
    plat = request.GET.get('platform', '').lower()

    latest = _fetch_latest_version()
    update_needed = _is_newer(latest, current)

    base = f"https://github.com/{GITHUB_REPO}/releases/latest/download"
    if 'mac' in plat or 'darwin' in plat:
        download_url = f"{base}/TimeTracker.pkg"
    else:
        download_url = f"{base}/TimeTracker-Windows-Setup.exe"

    return JsonResponse({
        "update_available": update_needed,
        "force": update_needed,
        "latest_version": latest,
        "download_url": download_url,
    })


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_preferences(request):
    from .models import UserPreference
    
    prefs, created = UserPreference.objects.get_or_create(user=request.user)
    
    if request.method == 'GET':
        return Response({
            'email_timesheet_reminders': prefs.email_timesheet_reminders,
            'email_weekly_summary': prefs.email_weekly_summary,
            'email_approval_notifications': prefs.email_approval_notifications,
            'desktop_notifications': prefs.desktop_notifications,
        })
    
    elif request.method == 'PATCH':
        for field in ['email_timesheet_reminders', 'email_weekly_summary', 
                       'email_approval_notifications', 'desktop_notifications']:
            if field in request.data:
                setattr(prefs, field, request.data[field])
        prefs.save()
        return Response({'ok': True})