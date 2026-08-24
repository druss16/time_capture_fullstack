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
from django.middleware.csrf import get_token



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

from tracker.utils.user_reasoning import humanize_for_api


# REPLACE your existing raw_events() function with this version

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from .auth import AgentKeyAuthentication
from .models import RawEvent, CurrentClient, Client, BillingRate, Timesheet, Block, BlockAuditLog, Client, TaskType, Organization, OrganizationMembership, Invitation

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

def get_request_org_override(request):
    """
    For staff/superuser, allow ?org_id= to override the org context.
    Used by MavOps admin impersonation. Falls back to normal org resolution.
    """
    override_id = request.GET.get("org_id") or request.data.get("org_id")
    if override_id and (request.user.is_staff or request.user.is_superuser):
        try:
            return Organization.objects.get(id=int(override_id))
        except (Organization.DoesNotExist, ValueError, TypeError):
            pass
    return get_org_or_default(request)

def get_request_user_override(request):
    override_uid = request.GET.get("user_id")
    if override_uid and (request.user.is_staff or request.user.is_superuser):
        try:
            return User.objects.get(id=int(override_uid))
        except (User.DoesNotExist, ValueError, TypeError):
            pass
    return request.user

def _get_meeting_category_for_org(org):
    """Return the canonical meeting category for this org's industry."""
    try:
        from tracker.industry_categories import get_categories_for_industry
        industry = getattr(org, 'industry_type', None) or 'general'
        cats = get_categories_for_industry(industry)
        # Prefer plural 'Meetings', fall back to other reasonable names
        for candidate in ('Meetings', 'Client Meeting', 'Meeting', 'Calls'):
            if candidate in cats:
                return candidate
    except Exception:
        pass
    return 'Meetings'

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
    if getattr(request, "user", None) and request.user.is_authenticated:
        org = get_user_org(request.user)
        if org:
            return org
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
    """Return the AgentDevice for the given API key, or None.
    Raises PermissionError('subscription_inactive') if device exists but is deactivated.
    """
    api_key = request.META.get(AGENT_HEADER)
    if not api_key:
        return None
    try:
        return AgentDevice.objects.select_related("user").get(api_key=api_key, is_active=True)
    except AgentDevice.DoesNotExist:
        # Check if device exists but was deactivated (subscription cancelled/expired)
        if AgentDevice.objects.filter(api_key=api_key, is_active=False).exists():
            raise PermissionError("subscription_inactive")
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
    username = (request.GET.get("user") or "").strip()
    host = (request.GET.get("host") or "").strip()
    stop, reason, stop_until = False, "", None
    ship_logs = False
    restart = False

    if host:
        from django.db.models import Q
        device = AgentDevice.objects.filter(
            Q(hostname=host) | Q(device_id=host)
        ).order_by('-last_seen_at').first()  # ← ADD order_by
        
        if device and device.log_requested:
            ship_logs = True
            device.log_requested = False
            device.save(update_fields=['log_requested'])
        
        if device and device.restart_requested:
            restart = True
            device.restart_requested = False
            device.save(update_fields=['restart_requested'])

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
        "stop_until": stop_until.isoformat() if stop_until else None,
        "ship_logs": ship_logs,
        "restart": restart,
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
    Ingest agent events. v1.3.38 hard cutover to dual timestamps.

    EXPECTED PAYLOAD (per event)
    ============================
      {
        "start_ts":  "2026-05-11T15:00:00Z",   # required, ISO-8601
        "end_ts":    "2026-05-11T15:01:00Z",   # required, ISO-8601, > start_ts
        "app_name":  "Outlook",
        "bundle_id": "outlook.exe",
        "window_title": "Inbox - wayne@tlwall.com",
        "url":       None,
        "file_path": None,
        "hostname":  "WAYNE-PC",
        "current_client_id": 42,
        "ctx":       {...}
      }

    STRICT VALIDATION
    =================
    Missing start_ts/end_ts → 400. End ≤ start → 400. Old-format events
    (ts_utc only) → 400. TL Wall is beta — no compat path.

    DOWNSTREAM
    ==========
    On success, kicks compact_recent_events for the user/hostname. Block
    creation now uses real event durations instead of IDLE_CAP-guessed.
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

    # Look up the user/device current client once for the whole batch.
    current_client_id = None
    current_client_name = None
    try:
        current = CurrentClient.objects.select_related("client").get(
            user=agent_user,
            device_id=device.id if device else 0,
        )
        current_client_id = current.client.id if current.client else None
        current_client_name = current.client.name if current.client else None
    except CurrentClient.DoesNotExist:
        pass

    header_host = (request.headers.get("X-Agent-Host") or "").strip()
    device_host = getattr(device, "hostname", "") if device else ""
    default_host = header_host or device_host or "unknown"

    created, errors = 0, []

    for item in payload:
        # ── Strict dual-timestamp validation ──
        start_raw = item.get("start_ts")
        end_raw = item.get("end_ts")

        if not start_raw or not end_raw:
            errors.append({
                "item": item,
                "error": "Missing start_ts or end_ts (v1.3.38 requires both)",
            })
            continue

        start_dt = parse_datetime(start_raw) if isinstance(start_raw, str) else start_raw
        end_dt = parse_datetime(end_raw) if isinstance(end_raw, str) else end_raw

        if start_dt is None or end_dt is None:
            errors.append({"item": item, "error": "Invalid start_ts/end_ts format"})
            continue

        if end_dt <= start_dt:
            errors.append({"item": item, "error": "end_ts must be > start_ts"})
            continue

        hostname = (default_host or item.get("hostname") or "unknown").strip() or "unknown"

        try:
            RawEvent.objects.create(
                start_ts=start_dt,
                end_ts=end_dt,
                app_name=item.get("app_name"),
                bundle_id=item.get("bundle_id"),
                window_title=item.get("window_title") or "",
                url=item.get("url"),
                file_path=item.get("file_path"),
                user=agent_user,
                hostname=hostname,
                ctx=item.get("ctx", {}) or {},
                device_id=str(device.id) if device else "unknown",
                # Prefer the agent's payload (captured at dwell_start) over the
                # server-side lookup (captured at write time). The agent knows
                # which client was active when the dwell began — that's what
                # the AI switcher race fix relies on.
                current_client_id=item.get("current_client_id") or current_client_id,
                # v1.3.49: Agent version for fleet visibility. NULL when
                # older agents (pre-v1.3.24) send events without this field.
                agent_version=item.get("agent_version"),
                # v1.4.0: Confidence-graded inference result. Empty dict for
                # events from pre-v1.4.0 agents — backwards compatible.
                inference=item.get("inference", {}) or {},
            )
            created += 1
        except Exception as e:
            errors.append({"item": item, "error": str(e)})

    # Kick compaction for this user/host so blocks appear immediately.
    blocks_created = 0
    if created > 0:
        try:
            from tracker.services.compaction import compact_recent_events
            blocks_created = compact_recent_events(
                user=agent_user,
                hostname=hostname,
                minutes_back=15,
            ) or 0
            logger.info(
                f"[INGEST] {created} events → {blocks_created} blocks "
                f"for {agent_user.username}@{hostname}"
            )
        except Exception as e:
            logger.error(f"[INGEST] Compaction failed: {e}", exc_info=True)
            # Don't fail the request — events are already persisted.

    status_code = (
        status.HTTP_201_CREATED if created and not errors
        else status.HTTP_207_MULTI_STATUS if created and errors
        else status.HTTP_400_BAD_REQUEST
    )

    return Response(
        {
            "created": created,
            "errors": errors,
            "blocks_created": blocks_created,
            "current_client": current_client_name,
        },
        status=status_code,
    )


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
    
    org = get_request_org_override(request)
    
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


# Replace your ENTIRE existing _ai_suggestions_via_classification_service
# function with this version. Changes from your original are marked with # ✨ CHANGED

def _ai_suggestions_via_classification_service(
    request,
    org,
    all_blocks,
    blocks_needing_ai,
    already_categorized,
    do_processing=True,   # ✨ CHANGED: new param — False means another request holds the lock
    lock_key=None,        # ✨ CHANGED: new param — lock to release when processing finishes
):
    """
    ClassificationService-based path with ASYNC Stage 10.

    Two-phase approach:
      Phase 1 (SYNC): Classify all blocks via Stages 0-9 (~1-2s)
               → Runs in request thread, returns immediately
      Phase 2 (ASYNC): Queue Stage 10 (OpenAI) to Celery background worker
               → Runs in background, doesn't block response

    ✨ CHANGED: Phases 1+2 only run when do_processing=True (the request that
    won the cache lock). Concurrent requests skip straight to formatting and
    return current state instantly — no more lock convoy on page load.
    """
    from rest_framework.response import Response
    from tracker.services.classification_service import ClassificationService
    from tracker.utils.display_names import format_block_for_display
    import logging

    logger = logging.getLogger('timetracker.classification')

    user = request.user if request.user.is_authenticated else None
    if hasattr(request, 'GET') and request.GET.get('user'):
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            user = User.objects.get(username=request.GET['user'])
        except User.DoesNotExist:
            pass

    def _format_locked(b):
        """Format an already-categorized block for response."""
        cat_name    = list((b.category_hours or {}).keys())[0] if b.category_hours else None
        client_name = getattr(b.client, "name", None)
        formatted   = format_block_for_display({
            'app_name':     getattr(b, 'app_name', '') or '',
            'window_title': getattr(b, 'window_title', '') or '',
            'url':          getattr(b, 'url', '') or '',
            'minutes':      b.minutes or 0,
            'category':     cat_name,
        }, client_name=client_name)
        return {
            "block_id": b.id,
            "start":    b.start,
            "end":      b.end,
            "title":    b.title,
            "ai_suggestion": {
                "client":          client_name,
                "project":         getattr(b.project, "name", None),
                "categories":      b.category_hours or {},
                "confidence":      1.0,
                "needs_review":    False,
                "reasoning":       "Already categorized (locked)",
                "source":          "existing",
                "auto_saved":      False,
                "taxpayer_name":   getattr(b, 'taxpayer_name', None),
                "tax_return_type": getattr(b, 'tax_return_type', None),
            },
            "display": {
                "title":         formatted['title'],
                "app":           formatted['app'],
                "duration":      formatted['duration'],
                "category_icon": formatted['category_icon'],
            },
            "current_client":  client_name,
            "current_project": getattr(b.project, "name", None),
        }

    service = ClassificationService(org=org, user=user)
    pipeline_out = []

    # ✨ CHANGED: Phases 1+2 wrapped in try/finally and gated on do_processing.
    # The finally block guarantees the lock is released even if a phase crashes.
    try:
        if do_processing:
            # ──────────────────────────────────────────────────────────────
            # PHASE 1 (SYNC): Classify via Stages 0-9 (NO OpenAI)
            # ──────────────────────────────────────────────────────────────
            logger.info(f"[PHASE1] Starting synchronous classification (Stages 0-9) for {len(blocks_needing_ai)} blocks")

            for b in blocks_needing_ai:
                current_state = getattr(b, 'classification_state', None)
                needs_classify = current_state in (None, '', 'captured')

                if needs_classify:
                    try:
                        # skip_ai=True → Stages 0-9 only, Stage 10 deferred to async task
                        decision = service.classify(b, skip_ai=True)
                        service.apply(b, decision)
                        b.refresh_from_db()
                    except Exception as e:
                        logger.error(f"[PHASE1] Failed on block {b.id}: {e}", exc_info=True)
                        continue

            logger.info(f"[PHASE1] ✅ Synchronous classification complete")

            # ──────────────────────────────────────────────────────────────
            # PHASE 2 (ASYNC): Queue Stage 10 (OpenAI) to Celery
            # ──────────────────────────────────────────────────────────────
            blocks_for_ai = [
                b for b in blocks_needing_ai
                if b.classification_state == 'captured'
                and not getattr(b, 'proposed_client_id', None)
            ]

            if blocks_for_ai:
                try:
                    from tracker.tasks import batch_ai_classify_async

                    block_ids = [b.id for b in blocks_for_ai]
                    logger.info(f"[PHASE2-QUEUE] Queueing {len(block_ids)} blocks for async AI classification")

                    task = batch_ai_classify_async.delay(
                        block_ids=block_ids,
                        org_id=org.id,
                        user_id=user.id if user else None,
                    )

                    logger.info(f"[PHASE2-QUEUE] ✅ Queued task {task.id} to Celery (will run in background)")

                except Exception as e:
                    logger.warning(f"[PHASE2-QUEUE] Failed to queue async task: {e} (Stage 10 will be skipped)")
            else:
                logger.info("[PHASE2-QUEUE] No blocks need AI (all covered by Stages 0-9)")
        else:
            # ✨ CHANGED: another concurrent request is doing the heavy work
            logger.info("[PHASE1/2] Skipped — another request holds the processing lock")
    finally:
        # ✨ CHANGED: always release the lock if we hold it
        if lock_key:
            from django.core.cache import cache
            cache.delete(lock_key)

    # ──────────────────────────────────────────────────────────────────────
    # FORMAT RESPONSE — runs for EVERY request, lock or not
    # ──────────────────────────────────────────────────────────────────────
    for b in blocks_needing_ai:
        # Q1: Filter out suppressed blocks entirely
        if b.classification_state == 'suppressed':
            continue

        # Build response entry matching old shape
        if b.classification_state == 'committed':
            client_obj  = getattr(b, 'client', None)
            client_name = client_obj.name if client_obj else None
            categories  = b.category_hours or {}
            confidence  = float(getattr(b, 'proposed_confidence', 0.0) or 0.0)
            needs_review = False
            reasoning   = "Auto-classified (committed)"
            auto_saved  = True
        elif b.classification_state == 'proposed':
            from tracker.models import Client
            proposed_id   = getattr(b, 'proposed_client_id', None)
            client_name   = None
            if proposed_id:
                try:
                    client_name = Client.objects.get(id=proposed_id).name
                except Client.DoesNotExist:
                    pass
            proposed_cat  = getattr(b, 'proposed_category', '') or ''
            categories    = {proposed_cat: round((b.minutes or 0) / 60.0, 2)} if proposed_cat else {}
            confidence    = float(getattr(b, 'proposed_confidence', 0.0) or 0.0)
            needs_review  = True
            reasoning     = getattr(b, 'proposed_reasoning', '') or 'Proposed — needs review'
            auto_saved    = False
        else:
            # captured (no strong signals from Stages 0-9, AI pending)
            client_name  = getattr(getattr(b, 'client', None), 'name', None)
            categories   = {}
            confidence   = 0.0
            needs_review = True
            reasoning    = "Awaiting AI classification (Stage 10 in progress)"
            auto_saved   = False

        formatted = format_block_for_display({
            'app_name':     getattr(b, 'app_name', '') or '',
            'window_title': getattr(b, 'window_title', '') or '',
            'url':          getattr(b, 'url', '') or '',
            'minutes':      b.minutes or 0,
            'category':     list(categories.keys())[0] if categories else None,
        }, client_name=client_name)

        pipeline_out.append({
            "block_id": b.id,
            "start":    b.start,
            "end":      b.end,
            "title":    b.title,
            "ai_suggestion": {
                "client":          client_name,
                "project":         None,
                "categories":      categories,
                "confidence":      confidence,
                "needs_review":    needs_review,
                "reasoning":       reasoning,
                "source":          "classification_service",
                "auto_saved":      auto_saved,
                "taxpayer_name":   getattr(b, 'taxpayer_name', None),
                "tax_return_type": getattr(b, 'tax_return_type', None),
            },
            "display": {
                "title":         formatted['title'],
                "app":           formatted['app'],
                "duration":      formatted['duration'],
                "category_icon": formatted['category_icon'],
            },
            "current_client":  getattr(getattr(b, 'client', None), 'name', None),
            "current_project": getattr(getattr(b, 'project', None), 'name', None),
        })

    # Merge pipeline output with already-categorized blocks
    out = pipeline_out + [_format_locked(b) for b in already_categorized]

    logger.info(
        f"[RESPONSE] org={org.id} returning {len(pipeline_out)} pipeline + "
        f"{len(already_categorized)} locked = {len(out)} total blocks "
        f"(processing={'ran' if do_processing else 'skipped'})"
    )

    return Response(out)

def _batch_ai_classify(blocks_for_ai, service, org, user):
    """
    Batch OpenAI classification for multiple blocks in chunks.
    
    Instead of one huge request (42 blocks), split into smaller batches (10 per request).
    This keeps OpenAI response time fast (5-8s per batch) instead of slow (20s+ for 42).
    """
    import logging
    from tracker.services.classification_service import ClassificationDecision, Signal
    
    logger = logging.getLogger('timetracker.classification')
    
    try:
        from tracker.views_ai_classify import _call_openai
    except ImportError:
        logger.warning('views_ai_classify not available — skipping batch AI')
        return

    def _sanitize_for_openai(text):
        """Escape quotes and special chars so OpenAI JSON doesn't break."""
        if not text:
            return text
        text = text.replace('\\', '\\\\')
        text = text.replace('"', '\\"')
        text = text.replace('\n', ' ')
        text = text.replace('\r', ' ')
        return text[:500]

    # Get clients list for OpenAI context (reuse for all batches)
    try:
        service._ensure_context_loaded()   # async path: fresh service hasn't lazy-loaded yet
        clients_payload = [
            {'id': c.id, 'name': c.name, 'aliases': c.aliases or []}
            for c in service._clients
        ]
    except Exception as e:
        logger.warning(f"Failed to build clients payload for batch AI: {e}", exc_info=True)
        return

    # Split blocks into smaller chunks for faster OpenAI responses
    BATCH_SIZE = 10
    chunks = [blocks_for_ai[i:i+BATCH_SIZE] for i in range(0, len(blocks_for_ai), BATCH_SIZE)]
    logger.info(f"[BATCH-AI] Processing {len(blocks_for_ai)} blocks in {len(chunks)} batches of ~{BATCH_SIZE}")

    total_applied = 0
    
    for chunk_idx, chunk in enumerate(chunks):
        logger.info(f"[BATCH-AI] Batch {chunk_idx+1}/{len(chunks)}: {len(chunk)} blocks")

        # Build titles_batch for this chunk (with sanitization)
        titles_batch = []
        for b in chunk:
            titles_batch.append({
                'title':     _sanitize_for_openai(b.window_title or b.title or ''),
                'app_name':  _sanitize_for_openai(getattr(b, 'app_name', '') or ''),
                'file_path': _sanitize_for_openai(getattr(b, 'file_path', '') or ''),
                'url':       _sanitize_for_openai(getattr(b, 'url', '') or ''),
            })

        # Call OpenAI for this batch
        try:
            import time
            t_start = time.monotonic()
            results = _call_openai(titles_batch, clients_payload)
            processing_ms = int((time.monotonic() - t_start) * 1000)
            logger.info(f"[BATCH-AI] Batch {chunk_idx+1}: OpenAI returned {len(results) if results else 0} results in {processing_ms}ms")
        except Exception as e:
            logger.error(f"[BATCH-AI] Batch {chunk_idx+1} failed: {e}", exc_info=True)
            continue

        if not results or len(results) != len(chunk):
            logger.warning(f"[BATCH-AI] Batch {chunk_idx+1}: Result count mismatch (got {len(results) if results else 0}, expected {len(chunk)})")
            continue

        # Map results back to blocks in this chunk and apply
        for block, result in zip(chunk, results):
            if not result:
                # Stamp the attempt so the dispatcher doesn't re-send this
                # block to OpenAI every 90s forever.
                from tracker.models import Block as BlockModel
                BlockModel.objects.filter(id=block.id).update(
                    proposed_reasoning='AI: no client evidence found'
                )
                continue

            try:
                # Build a synthetic decision from OpenAI result
                client_id = result.get('client_id')
                category = result.get('category', '')
                confidence = float(result.get('confidence', 0.0))
                is_billable = result.get('is_billable', True)

                decision = ClassificationDecision(
                    client_id=client_id,
                    category=category,
                    confidence=confidence,
                    is_billable=is_billable,
                    source='ai_batch',
                    reasoning=result.get('reasoning', ''),
                )

                # Add signals for traceability
                if client_id:
                    client_obj = next(
                        (c for c in service._clients if c.id == client_id), None
                    )
                    if client_obj:
                        decision.matched_signals.append(Signal(
                            type='ai_client_batch',
                            strength=min(0.95, confidence),
                            evidence=f"AI batch: {client_obj.name} ({confidence:.2f})",
                            detail={
                                'client_id': client_id,
                                'client_name': client_obj.name,
                                'ai_confidence': confidence,
                                'batch_classified': True,
                            },
                        ))
                
                if category:
                    decision.matched_signals.append(Signal(
                        type='ai_category_batch',
                        strength=min(0.85, confidence),
                        evidence=f"AI category: {category}",
                        detail={
                            'category': category,
                            'is_billable': is_billable,
                            'batch_classified': True,
                        },
                    ))

                # Finalize and apply
                decision = service._finalize_decision(decision, block)
                service.apply(block, decision, source='ai_batch')
                block.refresh_from_db()
                total_applied += 1

                logger.debug(
                    f"[BATCH-AI] Block {block.id}: client={client_id} → {block.classification_state}"
                )

            except Exception as e:
                logger.error(f"[BATCH-AI] Failed to apply block {block.id}: {e}", exc_info=True)
                continue

    logger.info(f"[BATCH-AI] Completed: {total_applied}/{len(blocks_for_ai)} blocks classified")
 

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
    ✅ 5-stage pipeline runs BEFORE OpenAI:
         Stage 0a — Suppress generic dialogs / internal timesheets (no save, no response)
         Stage 0b — Internal firm work shortcut (Billing/Admin, no client)
         Stage 1  — Tax software extraction (UltraTax/TaxWise SSN hashed, taxpayer bucket)
         Stage 2  — Deterministic alias/domain/path rules
         Stage 3  — Learned patterns (UserWorkPattern)
         Stage 4  — AI client identification
         Stage 5  — AI category classification
    ✅ Auto-saves high-confidence results (>= 0.88)
    ✅ OpenAI batch only called for genuinely unresolved blocks
    ✅ No duplicates (event-centric compaction)
    ✅ No flip-flopping (once saved, never touched again)
    ✅ Clean display formatting (App - Context format)
    ✅ Individual tax returns returned with taxpayer_name for frontend bucketing
    ✅ Suppressed blocks silently dropped (no frontend entry)
    """
    from tracker.utils.display_names import format_block_for_display, format_duration

    # ── Query params ──────────────────────────────────────────────────────────
    username      = request.GET.get("user") or None
    hostname      = request.GET.get("hostname") or None
    limit         = int(request.GET.get("limit") or 120)
    limit         = max(1, min(limit, 200))
    timeout_ms    = int(request.GET.get("timeout_ms") or 15000)
    noai          = request.GET.get("noai") in ("1", "true", "yes")
    fallback_mode = request.GET.get("fallback") or ""
    debug         = request.GET.get("debug") in ("1", "true", "yes")

    org = get_request_org_override(request)

    import logging
    from django.core.cache import cache

    # =========================================================
    # STEP 1: Compact any new unlinked events into blocks —
    # but only ONE request at a time does the heavy work.
    # Concurrent requests skip it and just read current state.
    # =========================================================
    start_utc = _start_of_local_day_utc()
    qs = Block.objects.filter(start__gte=start_utc).order_by("start")
    if username:
        qs = qs.filter(user__username=username)
    if hostname:
        qs = qs.filter(hostname=hostname)
    if org:
        qs = qs.filter(org=org)

    qs = qs[:limit]
    all_blocks = list(qs)
    log(f"[suggestions] Blocks: {len(all_blocks)}, Limit: {limit}")

    if not all_blocks:
        return Response([])

    # =========================================================
    # STEP 2: Split blocks into categorized vs uncategorized
    # Categorized blocks are NEVER sent to AI
    # =========================================================
    blocks_needing_ai   = []
    already_categorized = []

    for b in all_blocks:
        if b.is_categorized:
            already_categorized.append(b)
        else:
            blocks_needing_ai.append(b)

    log(f"[AI] {len(already_categorized)} categorized (LOCKED), {len(blocks_needing_ai)} need classification")

    # Before calling OpenAI:
    log(f"[OpenAI-Usage] Blocks needing AI: {len(blocks_needing_ai)}")
    log(f"[OpenAI-Usage] Already categorized: {len(already_categorized)}")

    return _ai_suggestions_via_classification_service(
        request, org, all_blocks, blocks_needing_ai, already_categorized,
        do_processing=False,   # view is read-only; Celery owns all processing
        lock_key=None,
    )

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
            # State machine: explicitly set classification_state for user actions.
            # Maps state_changed_by to match the categorized_by we just set above.
            b.classification_state = 'committed'
            b.state_changed_at = timezone.now()
            b.state_changed_by = 'correction' if b.categorized_by == 'correction' else 'user'
    
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

    # Mark the most recent audit row as user-corrected
    try:
        from tracker.models import ClassificationAudit
        audit = ClassificationAudit.objects.filter(
            block=b
        ).order_by('-created_at').first()
        if audit:
            audit.corrected_by_user = True
            audit.client_before = original_client
            audit.category_before = list(original_categories.keys())[0] if isinstance(original_categories, dict) and original_categories else ''
            audit.save(update_fields=['corrected_by_user', 'client_before', 'category_before'])
    except Exception as e:
        log(f"[AUDIT] Failed to mark correction (non-fatal): {e}")
    
    # ✅ Learn patterns from this manual classification
    user = request.user if request.user.is_authenticated else None
    
    if user and clean_categories:
        try:
            # Learn from this confirmed classification
            _learn_src = 'correction' if getattr(b, 'categorized_by', '') == 'correction' else 'manual'
            PatternLearningService.learn_from_block(b, user, source=_learn_src)
            
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
# Bulk confirm — accept all proposed blocks for a user/date in one click
# -------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([PermUI])
@transaction.atomic
def confirm_all_blocks(request):
    """
    Bulk-confirm every needs-review block the requesting user has for a date.

    Commits the SAME set the report's "Needs Review" tile counts — i.e. every
    uncommitted, material, non-idle block (both `proposed` AND `captured`), via
    ClassificationService.commit() (canonical path, writes a ClassificationAudit
    row identical to the per-block Confirm button):
      - proposed client -> committed, billable to that client
      - no client       -> committed as No Client (non-billable)

    Historically this only touched `proposed` blocks, so `captured` no-client
    slivers (generic browsing/doc time the classifier couldn't attribute)
    survived and the tile never dropped to zero even after the user confirmed
    everything. We now reuse the report's own predicate helpers so the count
    and the action can't drift apart.

    User-scoped (only the caller's own blocks), date-scoped (default today),
    never touches committed/suppressed. Per-block try/except so a single race
    doesn't abort the batch. Returns counts.
    """
    from tracker.services.classification_service import ClassificationService
    # Reuse the report's exact "needs review" predicate so Confirm All clears
    # precisely what the Reports tile counts (see _uncategorized_by_group).
    from tracker.views_reports import (
        _block_minutes, _dominant_category, _is_material,
    )

    user = request.user
    org = get_org_or_default(request)

    # Range-aware (Day / Week / Month views). When `start` & `end` are given,
    # confirm every pending block across [start, end] inclusive; otherwise fall
    # back to the single `date` (or today).
    start_str = request.data.get("start") or request.query_params.get("start")
    end_str   = request.data.get("end")   or request.query_params.get("end")
    date_str  = request.data.get("date")  or request.query_params.get("date")
    if start_str and end_str:
        start_date = parse_date(start_str)
        end_date   = parse_date(end_str)
    else:
        start_date = parse_date(date_str) if date_str else timezone.localdate()
        end_date   = start_date
    day_start = timezone.make_aware(dt.combine(start_date, dt_time.min))
    day_end = timezone.make_aware(dt.combine(end_date, dt_time.min)) + timedelta(days=1)

    # Uncommitted, non-suppressed blocks for the day — mirrors the report's
    # committed_only=False queryset (is_categorized=False, excludes suppressed).
    candidates = Block.objects.filter(
        org=org, user=user,
        start__gte=day_start, start__lt=day_end,
        is_categorized=False,
        deleted_at__isnull=True,
    ).exclude(classification_state="suppressed")

    # Commit every proposed block (accepting the AI suggestion, as before),
    # plus captured blocks that are material — i.e. exactly the captured slivers
    # the tile counts. Sub-2min captured noise and idle sentinels (which the
    # tile does NOT count) are left untouched so we don't bulk-commit micro-noise.
    pending = [
        b for b in candidates
        if _block_minutes(b) > 0
        and _dominant_category(b).lower() != "idle"
        and (b.bundle_id or "").lower() != "__idle__"
        and (b.classification_state == "proposed" or _is_material(b))
    ]

    # Match the per-row green "✓ [client]" button: when the classifier proposed
    # NO client, fall back to the same context suggestion the /why/ panel shows
    # (co-open file / temporal "sandwich" / day-dominant). This keeps "Confirm
    # all" == "accept every green button", so bulk-confirming never silently
    # files a context-attributable block as No Client (non-billable).
    from tracker.views_block_evidence import suggested_client_for

    svc = ClassificationService(org=org, user=user)
    with_client = no_client = skipped = 0
    for b in pending:
        try:
            override = None
            if b.proposed_client_id is None and b.client_id is None:
                sid = suggested_client_for(b, org)
                if sid:
                    override = {"client_id": sid, "category": (b.proposed_category or "General Client Work")}
            svc.commit(b, user=user, override=override)
            if b.client_id:
                with_client += 1
            else:
                no_client += 1
        except ValueError:
            skipped += 1  # already committed/suppressed (race) — skip

    return Response({
        "ok": True,
        "confirmed_with_client": with_client,
        "confirmed_no_client": no_client,
        "skipped": skipped,
        "total": with_client + no_client,
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
        from tracker.models import OrgDeploymentToken
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
        
        # Check if org uses MDM deployment
        mdm_managed = False
        if org:
            mdm_managed = OrgDeploymentToken.objects.filter(
                organization=org,
                is_active=True
            ).exists()

        # Vertical labelling. Resolved here because whoami is the one payload
        # every page already loads, so no screen needs its own fetch to know
        # whether to say "Matter" or "Engagement".
        from tracker.industry_categories import get_terminology, get_primary_integrations
        industry_type = (getattr(org, 'industry_type', None) or 'general') if org else 'general'
        
        return {
            "is_authenticated": True,
            "username": user.username,
            "user_id": user.id,
            "email": user.email or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
            "role": role,
            "org_id": org.id if org else None,
            "org_name": org.name if org else None,
            "mdm_managed": mdm_managed,
            "industry_type": industry_type,
            "terminology": get_terminology(industry_type),
            "primary_integrations": get_primary_integrations(industry_type),
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
        "first_name": "",
        "last_name": "",
        "is_staff": False,
        "is_superuser": False,
        "role": None,
        "org_id": None,
        "org_name": None,
        "host": None,
        "device_id": None,
        "mdm_managed": False,
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

import secrets
from datetime import timedelta
from django.middleware.csrf import get_token

@api_view(["GET", "POST"])  # Add GET method
@permission_classes([AllowAny])
def auth_login(request):
    """
    GET: Returns CSRF token for login form (prevents 403 on first login attempt)
    POST: JSON login endpoint - accepts username OR email.
    """
    
    # Handle GET - return CSRF token
    if request.method == 'GET':
        csrf_token = get_token(request)
        return Response({
            "ok": True,
            "csrfToken": csrf_token,
        }, status=status.HTTP_200_OK)
    
    # Handle POST - login
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

    v1.3.63: Added staleness guard. If the CurrentClient row hasn't been
    affirmed by the agent within STALE_CURRENT_CLIENT_MINUTES, treat as
    stale and return None. Prevents the feedback loop where an old
    CurrentClient row (e.g. set by AI-SWITCH hours ago, never cleared
    because widget_tracker's demote didn't fire) keeps re-poisoning the
    agent on startup. See TL Wall block 39995 (Wayne, 2026-06-01).

    Returns: {
      "client_id": int | null,
      "client_name": str | null,
      "started_at": timestamp | null,
      "updated_at": timestamp | null
    }
    """
    from django.utils import timezone
    from datetime import timedelta

    STALE_CURRENT_CLIENT_MINUTES = 30

    user = request.user
    device = getattr(request, "agent_device", None)

    try:
        current = CurrentClient.objects.select_related('client').get(
            user=user,
            device_id=device.id if device else 0
        )

        # Staleness guard
        if current.updated_at and (
            timezone.now() - current.updated_at
            > timedelta(minutes=STALE_CURRENT_CLIENT_MINUTES)
        ):
            return Response({
                "client_id": None,
                "client_name": None,
                "started_at": None,
                "updated_at": None,
            })

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
    
    org = get_request_org_override(request)

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

    # Best-effort append-only alias derivation for the new client (never
    # removes existing aliases). Async so it can't fail the create.
    try:
        from tracker.tasks import derive_client_aliases_for_org
        derive_client_aliases_for_org.delay(org.id)
    except Exception:
        logger.warning("Alias derivation dispatch failed for org %s", org.id, exc_info=True)

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

    # Best-effort append-only alias derivation for the whole batch. One
    # re-derive covers every client just imported; never removes aliases.
    if clients_created:
        try:
            from tracker.tasks import derive_client_aliases_for_org
            derive_client_aliases_for_org.delay(org.id)
        except Exception:
            logger.warning("Alias derivation dispatch failed for org %s", org.id, exc_info=True)

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


def _humanize_mixed_content(review_reason):
    """
    Convert {'unknown': 18} → human-readable message
    """
    if not review_reason or 'Mixed content:' not in review_reason:
        return review_reason or 'Needs review'
    
    # Extract the dict part: "Mixed content: {'work': 37, 'unknown': 8}"
    try:
        dict_str = review_reason.split('Mixed content:')[1].strip()
        content_dict = eval(dict_str)  # Safe here since we generated it
        
        has_work = 'work' in content_dict
        has_unknown = 'unknown' in content_dict
        has_personal = 'personal' in content_dict
        
        if has_work and has_unknown:
            return "Mixed work and unclear activity"
        elif has_personal and has_work:
            return "Mixed work and personal activity"
        elif has_unknown:
            return "Contains unclear activity that needs categorization"
        elif has_personal:
            return "Contains personal activity mixed with work"
        else:
            return "Mixed activity types detected"
    except:
        return "Block contains mixed activity types"

# ============================================================================
# UPDATED today_time() - With Clean Display Formatting
# ============================================================================x


# tracker/views.py — today_time()
#
# Header totals + per-client cards are computed from ONE source of truth,
# tracker.services.billing_totals (committed blocks, flag-based billable), so
# Daily Review and Reports agree. Captured/proposed time surfaces only as
# proposed_inline (Needs Review), never as billable.


# --- block activity context (tab/document names within a block) -----------
_TABCTX_STOP = {
    'this pc', 'program manager', '1 file conflict', 'file conflict', 'desktop',
    'downloads', 'documents', 'quick access', 'home', 'control panel', 'settings',
    'task manager', 'recycle bin', 'quickbooks desktop information',
    'cs connect background services', 'untitled',
}
_TABCTX_STOP_PREFIX = ('company data (', 'local disk (', 'windows (', 'os (', 'skmbt_')
_TABCTX_NOISE_SUB = ('background services', 'quickbooks desktop login', 'desktop information')


def _tabctx_lead_name(t: str) -> str:
    t = t or ''
    m = re.search(r'-\s*\[([^\]]+)\]\s*$', t)
    screen = m.group(1).strip() if m else None
    t = re.sub(r'\s*-\s*QuickBooks Accountant Desktop.*$', '', t, flags=re.I)
    t = re.sub(
        r'\s*-\s*(File Explorer|Excel|Word|Google Chrome|Microsoft.*|Adobe.*|'
        r'Outlook|Work|Compatibility Mode)\s*$', '', t, flags=re.I)
    t = re.sub(r'\s+and\s+\d+\s+more\s+(tabs?|pages?)\s*$', '', t, flags=re.I)
    t = t.strip(' -')
    if screen and screen.lower() not in ('home',):
        return screen
    return t.strip()


def _tabctx_is_noise(n: str) -> bool:
    nl = n.lower()
    if nl in _TABCTX_STOP:
        return True
    if any(nl.startswith(p) for p in _TABCTX_STOP_PREFIX):
        return True
    if any(sub in nl for sub in _TABCTX_NOISE_SUB):
        return True
    if re.match(r'^[a-z]:\\?$', nl):
        return True
    if re.match(r'^(skmbt_|0056_)', nl):
        return True
    return False


def block_tab_context(block_id, primary_title='', max_dominant=5,
                      dominant_min=2, max_brief=5):
    """
    Weighted activity context for a block: distinct tab/document names that
    appeared across its RawEvents, split into 'dominant' (seen >= dominant_min
    times) and 'brief' (seen once). Chrome / OS / scanner noise stripped.
    Returns None when nothing is additive beyond the primary (single-app).

    Makes NO claim about which CLIENT a name belongs to — naive token matching
    produced false matches. We show honest names; the user judges the client.
    """
    from collections import Counter
    titles = list(
        RawEvent.objects.filter(block_id=block_id)
        .exclude(window_title__exact='').exclude(window_title__isnull=True)
        .values_list('window_title', flat=True)
    )
    names = Counter()
    canon = {}  # lower -> first-seen display form, for case-insensitive merge
    for t in titles:
        n = _tabctx_lead_name(t)
        if n and len(n) >= 2 and not _tabctx_is_noise(n):
            key = n.lower()
            display = canon.setdefault(key, n)
            names[display] += 1
    dominant = [n for n, c in names.most_common() if c >= dominant_min][:max_dominant]
    brief = [n for n, c in names.most_common() if c < dominant_min][:max_brief]
    if len(dominant) + len(brief) <= 1:
        return None
    return {'dominant': dominant, 'brief': brief}


@api_view(["GET"])
@permission_classes([PermUI])
def block_tab_context_view(request, block_id: int):
    """Lazy-loaded activity context for one block (called on row expand)."""
    org = get_org_or_default(request)
    b = get_object_or_404(Block, id=block_id, org=org)
    ctx = block_tab_context(b.id, getattr(b, 'window_title', '') or '')
    return Response(ctx or {'dominant': [], 'brief': []})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def today_time(request):
    """
    Get tracked time organized by client → category.

    v1.3.38: events have (start_ts, end_ts) intervals — no IDLE_CAP guessing.
    Each event contributes its real interval duration to the totals.

    DISPLAY FORMATTING:
    - "Chrome - Aurelia Dashboard (15m)" instead of "Google Chrome (15m)"
    - "VS Code - views.py (timetracker) (45m)" instead of raw titles

    INDIVIDUAL RETURNS:
    - Tax software open return events are excluded from client aggregation (Step 3)
    - Instead bucketed by taxpayer in Step 6 (individual_returns)
    - IR billable minutes are added to totals so header reflects full day
    """
    from datetime import datetime, timedelta
    from datetime import timezone as dt_timezone
    from collections import defaultdict
    from django.utils.dateparse import parse_date

    from tracker.utils.display_names import format_block_for_display, format_duration

    # ── Impersonation override ──
    user = get_request_user_override(request)

    if not user.is_authenticated:
        return Response(
            {"error": "Authentication required"},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # ── Date range (Day / Week / Month views) ──────────────────────────────
    # When `start` & `end` are both provided, the summary aggregates every day
    # in [start, end] inclusive (Week / Month views). Otherwise it falls back to
    # the single `date` (or today) — the classic one-day view. All the billing
    # helpers already accept a UTC window, and the per-day block lists below use
    # `day__gte`/`day__lte` so a range widens them without any other change.
    date_str  = request.GET.get('date')
    start_str = request.GET.get('start')
    end_str   = request.GET.get('end')
    if start_str and end_str:
        start_date = parse_date(start_str)
        end_date   = parse_date(end_str)
    else:
        start_date = parse_date(date_str) if date_str else timezone.localdate()
        end_date   = start_date
    # `target_date` names the range start — used for the response `date` label.
    target_date = start_date

    # Plan B: get the user's org once for TaskType code lookups in category loop.
    user_org = None
    try:
        membership = OrganizationMembership.objects.filter(user=user).first()
        if membership:
            user_org = membership.organization
    except Exception:
        pass

    tz = timezone.get_current_timezone()
    start_local = timezone.make_aware(
        datetime.combine(start_date, datetime.min.time()),
        tz
    )
    # end_local is the exclusive upper bound = midnight AFTER the last day.
    end_local = timezone.make_aware(
        datetime.combine(end_date, datetime.min.time()),
        tz
    ) + timedelta(days=1)
    start_utc = start_local.astimezone(dt_timezone.utc)
    end_utc = end_local.astimezone(dt_timezone.utc)

    # =========================================================================
    # Totals + per-client cards — ONE source of truth.
    # Header totals AND per-client cards both come from the SAME committed-block
    # set and the SAME billable rule Reports uses (tracker.services.billing_totals),
    # so Daily Review and Reports agree for any user/day. CONFIRMED (committed)
    # time only — captured/proposed time is never billable here; it surfaces below
    # as proposed_inline (Needs Review).
    # =========================================================================
    from tracker.services.billing_totals import compute_totals, compute_client_cards

    org = get_request_org_override(request)
    _totals = compute_totals(org, start_utc, end_utc, user_id=user.id, can_see_all=False)
    result = compute_client_cards(org, start_utc, end_utc, user_id=user.id, can_see_all=False)

    billable_hours     = _totals['billable_hours']
    non_billable_hours = _totals['non_billable_hours']
    needs_review_hours = _totals['needs_review_hours']
    # Total = ALL time captured that day, including not-yet-confirmed review time,
    # so it matches Reports' total exactly. Needs-review is also surfaced as its
    # own number (below) so the header total stays self-explanatory.
    global_hours       = round(_totals['total_hours'] + needs_review_hours, 2)

    # =========================================================================
    # Mobile blocks that need review -> flagged banners. Their TIME is already
    # counted above by compute_client_cards (committed mobile blocks are in the
    # same block set), so we do NOT re-add their minutes here.
    # =========================================================================
    flagged_blocks = []

    mobile_blocks = Block.objects.filter(
        user=user,
        org=get_request_org_override(request),
        hostname='mobile',
        start__gte=start_utc,
        start__lt=end_utc,
        is_categorized=True,
        client__isnull=False,
        deleted_at__isnull=True,
    ).select_related('client')

    for block in mobile_blocks:
        b_client_name = block.client.name
        b_minutes     = block.minutes or 0
        b_hours       = round(b_minutes / 60, 2)
        b_cat         = (
            list(block.category_hours.keys())[0]
            if isinstance(block.category_hours, dict) and block.category_hours
            else 'Manual Entry'
        )
        b_title = f"Mobile - {block.notes or b_cat} ({b_minutes}m)"

        if getattr(block, 'needs_review', False):
            flagged_blocks.append({
                'block_id':      block.id,
                'client_name':   b_client_name,
                'review_reason': getattr(block, 'review_reason', ''),
                'minutes':       b_minutes,
                'start':         block.start.isoformat(),
            })


    # =========================================================================
    # STEP 6: AI disagreement blocks → flagged_blocks
    # =========================================================================
    ai_disagreement_blocks = Block.objects.filter(
        user=user,
        day__gte=start_date,
        day__lte=end_date,
        ai_disagrees_with_agent=True,
        ai_disagreement_resolved_at__isnull=True,
        deleted_at__isnull=True,
    ).select_related('client', 'ai_proposed_client')

    for block in ai_disagreement_blocks:
        flagged_blocks.append({
            'block_id':                block.id,
            'client_name':             block.client.name if block.client else 'Uncategorized',
            'review_reason':           f"AI suggests {block.ai_proposed_client.name if block.ai_proposed_client else 'a different client'}",
            'minutes':                 block.minutes or 0,
            'start':                   block.start.isoformat() if block.start else '',
            'type':                    'ai_disagreement',
            'ai_proposed_client_id':   block.ai_proposed_client_id,
            'ai_proposed_client_name': block.ai_proposed_client.name if block.ai_proposed_client else None,
            'ai_confidence':           block.ai_proposed_confidence or 0.0,
            'ai_reasoning':            humanize_for_api(block),
        })

    # =========================================================================
    # STEP 6.5: MAIL disagreement blocks → flagged_blocks
    # =========================================================================
    mail_disagreement_blocks = Block.objects.filter(
        user=user,
        day__gte=start_date,
        day__lte=end_date,
        mail_disagrees_with_agent=True,
        mail_disagreement_resolved_at__isnull=True,
        deleted_at__isnull=True,
    ).select_related('client', 'mail_proposed_client')

    for block in mail_disagreement_blocks:
        proposed_name = (
            block.mail_proposed_client.name
            if block.mail_proposed_client else 'a different client'
        )
        flagged_blocks.append({
            'block_id':                  block.id,
            'client_name':               block.client.name if block.client else 'Uncategorized',
            'review_reason':             f"Email metadata suggests {proposed_name}",
            'minutes':                   block.minutes or 0,
            'start':                     block.start.isoformat() if block.start else '',
            'type':                      'mail_disagreement',
            'mail_proposed_client_id':   block.mail_proposed_client_id,
            'mail_proposed_client_name': block.mail_proposed_client.name if block.mail_proposed_client else None,
            'mail_confidence':           block.mail_proposed_confidence or 0.0,
            'mail_reasoning':            block.mail_disagreement_reasoning or '',
        })

    # =========================================================================
    # STEP 6.6: CALENDAR disagreement blocks → flagged_blocks (v1.3.42)
    # =========================================================================
    # Mirrors STEP 6.5 (mail disagreements) for the new Stage 6 calendar
    # disagreement signal. The frontend reads `type` and renders different
    # banner copy for 'classifier' vs 'manual' disagreement sources.
    calendar_disagreement_blocks = Block.objects.filter(
        user=user,
        day__gte=start_date,
        day__lte=end_date,
        calendar_disagrees_with_agent=True,
        calendar_disagreement_resolved_at__isnull=True,
        deleted_at__isnull=True,
    ).select_related('client', 'calendar_proposed_client')

    for block in calendar_disagreement_blocks:
        proposed_name = (
            block.calendar_proposed_client.name
            if block.calendar_proposed_client else 'a different client'
        )

        # Source-aware banner copy. Mirrors apply()'s FIX D logic.
        if block.calendar_disagreement_source == 'manual':
            review_reason = (
                f"You picked a different client, but this block overlaps "
                f"a calendar event associated with {proposed_name}"
            )
        else:
            review_reason = f"Calendar event suggests {proposed_name}"

        flagged_blocks.append({
            'block_id':                      block.id,
            'client_name':                   block.client.name if block.client else 'Uncategorized',
            'review_reason':                 review_reason,
            'minutes':                       block.minutes or 0,
            'start':                         block.start.isoformat() if block.start else '',
            'type':                          'calendar_disagreement',
            'calendar_proposed_client_id':   block.calendar_proposed_client_id,
            'calendar_proposed_client_name': block.calendar_proposed_client.name if block.calendar_proposed_client else None,
            'calendar_confidence':           block.calendar_proposed_confidence or 0.0,
            'calendar_reasoning':            block.calendar_disagreement_reasoning or '',
            'calendar_disagreement_source':  block.calendar_disagreement_source or 'classifier',
        })

    # =========================================================================
    # STEP 6.7: NEEDS_REVIEW blocks → flagged_blocks (mixed content)
    # =========================================================================
    needs_review_blocks = Block.objects.filter(
        user=user,
        day__gte=start_date,
        day__lte=end_date,
        needs_review=True,
        deleted_at__isnull=True,
    ).select_related('client')
    
    for block in needs_review_blocks:
        flagged_blocks.append({
            'block_id':      block.id,
            'client_name':   block.client.name if block.client else 'Uncategorized',
            'review_reason': block.review_reason or 'Needs review',
            'minutes':       block.minutes or 0,
            'start':         block.start.isoformat() if block.start else '',
            'type':          'needs_review',
        })

    # =========================================================================
    # STEP 6.8: Second-pass proposals → flagged_blocks (type='second_pass')
    # =========================================================================
    second_pass_blocks = Block.objects.filter(
        user=user,
        day__gte=start_date,
        day__lte=end_date,
        classification_state='proposed',
        deleted_at__isnull=True,
    ).exclude(
        categorized_by__in=['manual', 'correction'],
    ).select_related('client', 'proposed_client')

    for block in second_pass_blocks:
        reason = getattr(block, 'proposed_reasoning', '') or ''
        if 'second-pass' not in reason and not block.proposed_client_id:
            continue
        flagged_blocks.append({
            'block_id':              block.id,
            'type':                  'second_pass',
            'window_title':          getattr(block, 'window_title', '') or '',
            'client_name':           block.client.name if block.client else 'Uncategorized',
            'review_reason':         'Auto-categorized — confirm',
            'minutes':               block.minutes or 0,
            'start':                 block.start.isoformat() if block.start else '',
            'proposed_client_id':    block.proposed_client_id,
            'proposed_client_name':  block.proposed_client.name if block.proposed_client_id else None,
            'proposed_confidence':   float(getattr(block, 'proposed_confidence', 0.0) or 0.0),
            'proposed_category':     getattr(block, 'proposed_category', '') or '',
            'proposed_reasoning':    reason,
        })

    # Tag mobile-review-flagged blocks with their type for the frontend
    for fb in flagged_blocks:
        if 'type' not in fb:
            fb['type'] = 'mobile_review'

    # ── Pending review rows (red-clock rows, NOT in totals) ─────────────────
    # The "Pending — confirm to count as billable" list. Gated on the SHARED
    # is_pending_review_block predicate so this list and the report's REVIEW
    # column are identical by construction (same blocks, same minutes) for any
    # date range. Covers both proposed blocks (client guess / second-pass) and
    # captured-but-unattributed material blocks (rendered as no-guess "Assign
    # client" / "No Client" rows).
    from tracker.views_reports import is_pending_review_block
    from tracker.views_block_evidence import why_summary
    proposed_inline = []
    _pending = Block.objects.filter(
        user=user, day__gte=start_date, day__lte=end_date,
        is_categorized=False, deleted_at__isnull=True,
    ).exclude(classification_state='suppressed').select_related('proposed_client')
    for _b in _pending:
        if not is_pending_review_block(_b):
            continue
        # Embed the /why/ suggestion + reason up front so the pending row's green
        # client + explanation paint with the page (no per-row /why/ fetch → no lag).
        try:
            _why_reason, _why_sid, _why_sname = why_summary(_b, org)
        except Exception:
            _why_reason, _why_sid, _why_sname = ('', None, None)
        # Learning progress for the suggested client — powers the "Learning… ~N
        # more to auto-file" hint so a repeated suggestion visibly graduates.
        _learning = None
        try:
            from tracker.services.pattern_learning import PatternLearningService
            _sid = _why_sid or _b.proposed_client_id
            if _sid:
                _learning = PatternLearningService.progress_for_block(_b, user, _sid)
        except Exception:
            _learning = None
        proposed_inline.append({
            'block_id':             _b.id,
            'window_title':         getattr(_b, 'window_title', '') or '',
            'app_name':             getattr(_b, 'app_name', '') or '',
            'minutes':              _b.minutes or 0,
            'proposed_client_id':   _b.proposed_client_id,
            'proposed_client_name': _b.proposed_client.name if _b.proposed_client_id else None,
            'proposed_confidence':  float(getattr(_b, 'proposed_confidence', 0.0) or 0.0),
            'proposed_category':    getattr(_b, 'proposed_category', '') or '',
            'proposed_reasoning':   getattr(_b, 'proposed_reasoning', '') or '',
            'why_explanation':          _why_reason,
            'why_suggested_client_id':  _why_sid,
            'why_suggested_client_name': _why_sname,
            'learning':                 _learning,
        })

    # ── Mismatch flags: title clearly names a DIFFERENT client than booked ──
    # Same distinctive-token detector behind the MavOps Mismatches tab / admin
    # Daily Review. Scoped to THIS user's committed blocks for the day so the
    # Compact view can badge suspect rows. Keyed separately from the disagreement
    # `flagged_blocks` list above. Wrapped defensively — a detector hiccup must
    # never take down the Daily Review page.
    # `mismatch_flags` (legacy) = {block_id: looks_like_name} for the old Compact
    # view's inline chips. `mismatch_blocks` (redesign) carries the full row the
    # Daily Review "Needs you" lane renders: minutes (every triage row leads with
    # its minutes), the booked client, and the target so "Move to X" is one click.
    # `split_candidates` (redesign) = committed blocks whose per-activity
    # breakdown resolves to 2+ DISTINCT clients (one Edge/Excel window that
    # touched several clients' files, e.g. St John / St Paul / St Peter bills).
    # detect_mismatch only sees the block's single representative title, and the
    # STRICT matcher abstains on same-family churches — so those never surface.
    # Here we reuse the block breakdown + the same lenient per-slice matcher the
    # Split pre-fill uses, so a genuinely-mixed block gets flagged for a split in
    # "Needs you" instead of sitting silently under one client.
    mismatch_flags = {}
    mismatch_blocks = []
    split_candidates = []
    try:
        from tracker.utils.client_name_match import build_token_index, detect_mismatch
        from tracker.services.billing_totals import committed_block_qs
        from tracker.services.classification_service import (
            FALLBACK_CATEGORIES, FALLBACK_CATEGORIES_DEFAULT,
        )
        from tracker.views_block_evidence import _block_breakdown, _slice_suggestions
        _names = {c.id: c.name for c in Client.objects.filter(org=org).only('id', 'name')} if org else {}
        if _names:
            _index = build_token_index(_names)
            # The category a NO-CLIENT row should carry once it moves to a real
            # client. Those blocks sit in the non-billable catch-all the "no
            # client identified" fallback gave them, and the one-click fix reuses
            # the row's category verbatim — so handing back Personal/Non-Billable
            # would file the block under a client AND leave it non-billable.
            _billable_fb = FALLBACK_CATEGORIES.get(
                getattr(org, 'industry_type', None) or 'general', FALLBACK_CATEGORIES_DEFAULT
            )[0]
            # Scan committed blocks WITH a client (title names someone else ->
            # mismatch) and committed blocks with NO client (title/activities name
            # someone -> it should be under that client, or split between several).
            # No-client blocks used to be filtered out here, so a 13-minute Outlook
            # thread whose activities plainly name two parishes sat silently in the
            # "No client" browse instead of asking for a decision.
            # A no-client block only qualifies if a MACHINE parked it there.
            # "No client" is a legitimate answer a person can give (personal
            # browsing, firm admin, their own timesheet), and re-asking a
            # question they already answered is exactly the nagging this lane
            # is supposed to avoid.
            _human = {'manual', 'correction'}
            _scan = [
                _b for _b in committed_block_qs(
                    org, start_utc, end_utc, user_id=user.id, can_see_all=False
                )[:200]
                if _b.window_title and _b.bundle_id != '__idle__' and (
                    _b.client_id in _names if _b.client_id
                    else _b.categorized_by not in _human
                )
            ]
            # Bulk-load every scanned block's sub-events in ONE query and group by
            # block. The per-block fetch this replaces made the scan cost a DB
            # round trip per block — the single largest chunk of this endpoint's
            # latency, and it was paid again on every reload after a confirm.
            _events_by_block = defaultdict(list)
            if _scan:
                for _ev in RawEvent.objects.filter(
                    block_id__in=[b.id for b in _scan]
                ).only('block_id', 'window_title', 'start_ts', 'end_ts'):
                    _events_by_block[_ev.block_id].append(_ev)
            for _b in _scan:
                _unassigned = _b.client_id is None
                _cat = list((_b.category_hours or {}).keys())[0] if _b.category_hours else 'General Client Work'
                # The category the one-click fix will apply. A no-client block is
                # parked in the non-billable catch-all; once it moves to a client
                # it is client work, so hand back the billable fallback instead.
                _row_cat = _billable_fb if _unassigned else _cat

                # SPLIT: does the activity breakdown point at 2+ distinct clients?
                _is_split = False
                _lone_cid = None
                try:
                    _bd = _block_breakdown(_b, events=_events_by_block.get(_b.id, []))
                    # Single-slice blocks skip the per-slice matcher (their one
                    # label IS the title) — except when nobody is booked, where
                    # that matcher is the only thing that can name a client.
                    _sug = (
                        _slice_suggestions(_b, org, breakdown=_bd, names=_names, index=_index)
                        if _bd and (len(_bd) > 1 or _unassigned) else {}
                    )
                    _cids = {s['client_id'] for s in _sug.values() if s.get('client_id') is not None}
                    # Minutes whose activity names nobody. On a no-client block a
                    # material unnamed remainder is a party in its own right: the
                    # block genuinely is mixed, and moving the whole thing to the
                    # one client it does name would bill that client for the rest.
                    _bd_min = sum(it.get('minutes', 0) for it in (_bd or [])) or 1
                    _none_min = sum(
                        it.get('minutes', 0) for it in (_bd or [])
                        if (_sug.get(it['label']) or {}).get('client_id') is None
                    )
                    # A fifth of the block, not a fixed minute count: on a 2-minute
                    # block (own timesheet + a parish file) one minute IS half the
                    # block, and a minutes floor turned that into a one-click
                    # "move it all to the parish" — billing them for the timesheet.
                    _remainder_is_party = (
                        _unassigned and _none_min >= 1 and _none_min >= 0.2 * _bd_min
                    )
                    if len(_cids) >= 2 or (len(_cids) == 1 and _remainder_is_party):
                        _is_split = True
                        split_candidates.append({
                            'block_id':           _b.id,
                            'window_title':       _b.window_title or '',
                            'minutes':            _b.minutes or 0,
                            'category':           _row_cat,
                            'booked_client_id':   _b.client_id,
                            'booked_client_name': _names.get(_b.client_id, '') if not _unassigned else 'No client',
                            'slices': [
                                {
                                    'label':                 it['label'],
                                    'minutes':               it.get('minutes', 0),
                                    'suggested_client_id':   (_sug.get(it['label']) or {}).get('client_id'),
                                    'suggested_client_name': (_sug.get(it['label']) or {}).get('client_name'),
                                    # Slices that land on nobody stay non-billable;
                                    # only the ones that name a client become work.
                                    'suggested_category': (
                                        _row_cat if (_sug.get(it['label']) or {}).get('client_id') is not None
                                        else _cat
                                    ),
                                }
                                for it in _bd
                            ],
                        })
                    elif _unassigned and len(_cids) == 1:
                        _lone_cid = next(iter(_cids))
                except Exception:
                    pass
                if _is_split:
                    continue  # a multi-client split isn't also a single-client mismatch

                if _unassigned:
                    # Nothing is booked, so detect_mismatch has no disagreement to
                    # find — the per-slice matcher above is what named this block's
                    # client, and it is the ONLY thing we trust here. Running the
                    # title matcher over the raw window title instead skips that
                    # path's timesheet/noise guards and mis-reads incidental words
                    # ("...on-demand webinar" -> "On Demand Delivery Inc", "E DILLON
                    # TIMESHEET" -> a parish), which is a worse failure than staying
                    # quiet: it invites a one-click move to the wrong client.
                    if _lone_cid and _b.id is not None:
                        mismatch_flags[_b.id] = _names.get(_lone_cid, '')
                        mismatch_blocks.append({
                            'block_id':               _b.id,
                            'window_title':           _b.window_title or '',
                            'minutes':                _b.minutes or 0,
                            'category':               _row_cat,
                            'booked_client_id':       None,
                            'booked_client_name':     'No client',
                            'looks_like_client_id':   _lone_cid,
                            'looks_like_client_name': _names.get(_lone_cid, ''),
                        })
                    continue

                # MISMATCH: title clearly names ONE different client than booked.
                _m = detect_mismatch(_b.window_title, _b.client_id, _index, _names, firm_name=org.name)
                if _m and _m.get('bucket') == 'client' and _b.id is not None:
                    mismatch_flags[_b.id] = _m['looks_like_client_name']
                    mismatch_blocks.append({
                        'block_id':               _b.id,
                        'window_title':           _b.window_title or '',
                        'minutes':                _b.minutes or 0,
                        'category':               _cat,
                        'booked_client_id':       _b.client_id,
                        'booked_client_name':     _names.get(_b.client_id, ''),
                        'looks_like_client_id':   _m.get('looks_like_client_id'),
                        'looks_like_client_name': _m['looks_like_client_name'],
                    })
    except Exception:
        mismatch_flags = {}
        mismatch_blocks = []
        split_candidates = []

    return Response({
        'clients':            result,
        'global_hours':       global_hours,
        'billable_hours':     billable_hours,
        'non_billable_hours': non_billable_hours,
        'needs_review_hours': needs_review_hours,
        'date':               target_date.isoformat(),
        'flagged_blocks':     flagged_blocks,
        'proposed_inline':    proposed_inline,
        'mismatch_flags':     mismatch_flags,
        'mismatch_blocks':    mismatch_blocks,
        'split_candidates':   split_candidates,

    })


# ── Add this new view to views.py ─────────────────────────────────────────────
 
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def dismiss_block_review(request, block_id):
    """
    POST /api/blocks/<block_id>/dismiss-review/
    Clears needs_review + review_reason on a Block.
    """
    try:
        block = Block.objects.get(id=block_id, user=request.user)
    except Block.DoesNotExist:
        return Response({'error': 'Block not found'}, status=404)
 
    block.needs_review  = False
    block.review_reason = ''
    block.save(update_fields=['needs_review', 'review_reason'])
 
    return Response({'ok': True, 'block_id': block_id})

# Add somewhere in views.py near the other dismiss-review code
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
import json

@csrf_exempt
@require_POST
def resolve_ai_disagreement(request, block_id):
    """
    POST /api/blocks/<block_id>/resolve-disagreement/
    Body: {"action": "accept" | "dismiss" | "change", "client_id": <int|null>}

    Despite the legacy "ai" in the name, this endpoint resolves THREE kinds of
    disagreements. It dispatches based on which flag is set on the block:

      - block.ai_disagrees_with_agent        → AI disagreement flow (Stage 10)
      - block.mail_disagrees_with_agent      → mail disagreement flow (Stage 7)
      - block.calendar_disagrees_with_agent  → calendar disagreement flow (Stage 6, v1.3.42)

    Priority when multiple flags are set: AI > mail > calendar. (Highest-
    confidence-source first. Rare in practice — most blocks have at most one
    flag set since each comes from a different stage and the signal that
    matched first typically resolves the attribution.)

    accept  — switch block to the proposed client (whichever flow)
    dismiss — keep current client, mark resolved
    change  — switch to a third client (specified via client_id in body)

    v1.3.61: All client mutations route through ClassificationService.recommit
    so a manual ClassificationAudit row is written. The audit row's detail
    records {flow, resolution} — this is the highest-value ground-truth label
    in the system (the classifier flagged a likely error; this is the user's
    verdict on it), and the precision report reads it to score each detector.
    """
    user = get_request_user_override(request)
    if not user or not user.is_authenticated:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        body = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'invalid_json'}, status=400)

    action = body.get('action')
    if action not in ('accept', 'dismiss', 'change'):
        return JsonResponse({'error': 'invalid_action'}, status=400)

    from tracker.models import Block, Client
    from tracker.services.classification_service import ClassificationService

    # Look up by all three flags — frontend doesn't tell us which type
    try:
        block = Block.objects.select_related(
            'client',
            'ai_proposed_client',
            'mail_proposed_client',
            'calendar_proposed_client',
            'org',
        ).get(id=block_id, user=user)
    except Block.DoesNotExist:
        return JsonResponse({'error': 'block_not_found'}, status=404)

    is_ai = bool(getattr(block, 'ai_disagrees_with_agent', False))
    is_mail = bool(getattr(block, 'mail_disagrees_with_agent', False))
    is_calendar = bool(getattr(block, 'calendar_disagrees_with_agent', False))

    if not (is_ai or is_mail or is_calendar):
        return JsonResponse({'error': 'block_not_flagged'}, status=404)

    ai_open       = is_ai       and not block.ai_disagreement_resolved_at
    mail_open     = is_mail     and not block.mail_disagreement_resolved_at
    calendar_open = is_calendar and not block.calendar_disagreement_resolved_at

    if ai_open:
        flow = 'ai'
        proposed_client_id = block.ai_proposed_client_id
        no_proposal_error = 'no_ai_proposal'
    elif mail_open:
        flow = 'mail'
        proposed_client_id = block.mail_proposed_client_id
        no_proposal_error = 'no_mail_proposal'
    elif calendar_open:
        flow = 'calendar'
        proposed_client_id = block.calendar_proposed_client_id
        no_proposal_error = 'no_calendar_proposal'
    else:
        return JsonResponse({'error': 'already_resolved'}, status=409)

    old_client_id = block.client_id

    # Build the recommit override based on action. override stays None for
    # 'dismiss' (no client change), in which case we still write an audit row
    # below to record that the user rejected the flag.
    override = None

    if action == 'accept':
        if not proposed_client_id:
            return JsonResponse({'error': no_proposal_error}, status=400)
        resolution = 'accepted'
        override = {'client_id': proposed_client_id}
        # v1.3.47: For calendar accept, also reclassify as meeting time.
        # The user is confirming "this block represents meeting time," not
        # "this foreground app is owned by the meeting's client." So bill
        # under the meeting category, not the original foreground category.
        if flow == 'calendar':
            block.is_meeting = True
            minutes = block.minutes or 0
            hours = round(minutes / 60.0, 2) if minutes else 0.0
            meeting_category = _get_meeting_category_for_org(block.org)
            override['category'] = meeting_category
            override['category_hours'] = {meeting_category: hours}
            logger.info(
                f"[CAL-ACCEPT] Block {block.pk}: reclassified to "
                f"'{meeting_category}' ({hours}h) for "
                f"{block.client.name if block.client else '?'}"
            )

    elif action == 'change':
        new_client_id = body.get('client_id')
        if not new_client_id:
            return JsonResponse({'error': 'client_id_required'}, status=400)
        try:
            new_client = Client.objects.get(id=new_client_id, org=block.org)
        except Client.DoesNotExist:
            return JsonResponse({'error': 'client_not_found'}, status=404)
        resolution = 'changed_to_other'
        override = {'client_id': new_client.id}

    else:  # dismiss — keep current client, just mark resolved
        resolution = 'dismissed'

    # Stamp resolution on the appropriate set of fields. Done on the in-memory
    # instance BEFORE the service save so it persists in the same write.
    now = timezone.now()
    if flow == 'ai':
        block.ai_disagreement_resolved_at = now
        block.ai_disagreement_resolution = resolution
    elif flow == 'mail':
        block.mail_disagreement_resolved_at = now
        block.mail_disagreement_resolution = resolution
    else:  # calendar
        block.calendar_disagreement_resolved_at = now
        block.calendar_disagreement_resolution = resolution

    # Audit detail — the structured ground-truth label for this resolution.
    audit_detail = {
        'flow':          flow,
        'resolution':    resolution,
        'proposed_client_id': proposed_client_id,
        'old_client_id': old_client_id,
    }

    service = ClassificationService(org=block.org, user=user)

    if override is not None:
        # accept / change — writes the manual ClassificationAudit row.
        service.recommit(
            block, user=user, override=override, audit_detail=audit_detail
        )
    else:
        # dismiss — no client change, but still record the verdict so the
        # report can see "user said the flag was a false alarm."
        block.save(force_classifier=True)
        try:
            from tracker.models import ClassificationAudit
            ClassificationAudit.objects.create(
                block=block,
                source='manual',
                client_before_id=old_client_id,
                client_after_id=old_client_id,   # unchanged
                category_before=ClassificationService._extract_dominant_category(block),
                category_after=ClassificationService._extract_dominant_category(block),
                confidence_client=1.0,
                confidence_category=1.0,
                overall_confidence=1.0,
                matched_signals=[{
                    'type': 'user_dismiss_disagreement',
                    'strength': 1.0,
                    'evidence': f'User {getattr(user, "username", "?")} dismissed {flow} disagreement',
                    'detail': audit_detail,
                }],
                corrected_by_user=False,   # dismiss = original stood = NOT a correction
            )
        except Exception as e:
            logger.warning(f"[RESOLVE-DISAGREE] dismiss audit write failed for block {block.pk}: {e}")

    block.refresh_from_db()

    return JsonResponse({
        'block_id': block.id,
        'flow': flow,
        'resolution': resolution,
        'final_client_id': block.client_id,
        'final_client_name': block.client.name if block.client else None,
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


def _heuristic_suggestion(block, user, org, clients_by_name_lower):
    """
    v1.3.60: Pattern-match common cases where the classifier didn't propose
    anything useful but the right answer is obvious from the title/app.

    Returns a dict matching the suggestions[] item shape, or None.

    Patterns matched (in priority order):
      1. Outlook + user's own email address     → Internal + Email/Communication
      2. Browser/Acrobat + org name in title    → Internal + Billing/Admin
      3. Browser news/sports/personal patterns  → no client + Personal/Non-Billable

    The classifier's proposal (if any) takes precedence — this only fires when
    suggestions[] is otherwise empty.
    """
    title = (block.window_title or '').lower()
    app = (block.app_name or '').lower()
    org_name_lower = (org.name or '').lower() if org else ''

    # Strip "& Tax Corp", "Inc", "LLC" etc. for fuzzy org-name matching
    org_tokens = [
        t for t in re.findall(r'\b[a-z]{4,}\b', org_name_lower)
        if t not in {'corp', 'inc', 'llc', 'and', 'the', 'tax', 'firm'}
    ]

    # Find an "Internal" client for this org (handles "Internal", "Internal - Tax", etc.)
    internal_client_name = None
    for name_lower, name_original in clients_by_name_lower.items():
        if name_lower == 'internal' or name_lower.startswith('internal'):
            internal_client_name = name_original
            break

    # Pattern 1: Wayne's own Outlook inbox
    # Title format: "Inbox - <username>@<orgdomain> - Outlook"
    user_email = (user.email or '').lower()
    user_handle = user_email.split('@')[0] if '@' in user_email else None
    username = user.username.lower()
    is_outlook_app = 'outlook' in app or app == 'olk'

    if is_outlook_app and 'inbox' in title:
        # Check for user's email or username in title
        if (user_email and user_email in title) or \
           (user_handle and len(user_handle) >= 3 and user_handle in title) or \
           (username and len(username) >= 3 and f'{username}@' in title):
            if internal_client_name:
                return {
                    'client': internal_client_name,
                    'category': 'Email/Communication',
                    'confidence': 0.75,
                    'reasoning': "User's own Outlook inbox — internal email triage",
                }

    # Pattern 2: Org name in window title (TL Wall quote, WordPress site, etc.)
    # Match if any 4+ char distinctive org token appears in title
    if org_tokens and internal_client_name:
        for token in org_tokens:
            if token in title:
                return {
                    'client': internal_client_name,
                    'category': 'Billing/Admin',
                    'confidence': 0.70,
                    'reasoning': f"Title references '{token}' — internal firm admin",
                }

    # Pattern 3: Browser personal/news patterns
    BROWSER_APPS = {'msedge', 'chrome', 'firefox', 'brave', 'safari', 'opera', 'iexplore'}
    if app in BROWSER_APPS:
        PERSONAL_PATTERNS = [
            'fox news', 'cnn ', 'cnn.com', 'nbc news', 'cbs news', 'abc news',
            'msnbc', 'bloomberg', 'reuters', 'yahoo finance', 'yahoo news',
            'espn', 'sports', 'twitter.com', 'x.com/', 'facebook.com',
            'instagram', 'reddit.com', 'tiktok', 'youtube.com',
            'shopping', 'amazon.com', 'ebay.com',
            'breaking news', 'latest news', 'news headlines',
        ]
        if any(p in title for p in PERSONAL_PATTERNS):
            return {
                'client': '',  # no client for personal
                'category': 'Personal/Non-Billable',
                'confidence': 0.75,
                'reasoning': 'Title matches personal browsing pattern',
            }

    return None


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
    
    # Get industry-specific categories
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
    
    start_utc = start_local.astimezone(dt_timezone.utc)
    end_utc = end_local.astimezone(dt_timezone.utc)
    
    # Only show blocks older than 10 minutes
    cutoff_time = timezone.now() - timedelta(minutes=10)
    effective_end = min(end_utc, cutoff_time)
    
    # Get uncategorized blocks
    # v1.3.60: Exclude suppressed blocks. The classifier already decided these
    # are meaningless (Windows shell, blank Excel, transient dialogs, etc.) —
    # they should never appear in the user's review pile.
    blocks = Block.objects.filter(
        user=user,
        start__gte=start_utc,
        start__lt=effective_end,
        is_categorized=False,
    ).exclude(
        classification_state='suppressed',
    ).select_related('client').order_by('start')[:limit]

    # Batch-fetch proposed client names so we don't N+1 inside the session loop
    proposed_client_ids = {
        b.proposed_client_id for b in blocks
        if getattr(b, 'proposed_client_id', None)
    }
    proposed_clients_map = (
        dict(
            Client.objects
            .filter(id__in=proposed_client_ids)
            .values_list('id', 'name')
        )
        if proposed_client_ids else {}
    )
    # Build name-keyed lookup for heuristic suggestions
    clients_by_name_lower = {
        c.name.lower(): c.name
        for c in Client.objects.filter(org=org, is_active=True)
    }
    
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
        
        client_name = first_block.client.name if first_block.client else None
        formatted = format_block_for_display({
            'app_name': first_block.app_name or '',
            'window_title': first_block.window_title or '',
            'url': first_block.url or '',
            'minutes': total_minutes,
        }, client_name=client_name)

        # ← NEW: Pull classifier proposal set by ClassificationService.apply()
        proposed_client_id   = getattr(first_block, 'proposed_client_id', None)
        proposed_category    = (getattr(first_block, 'proposed_category', '') or '').strip()
        proposed_confidence  = float(getattr(first_block, 'proposed_confidence', 0.0) or 0.0)
        proposed_reasoning   = getattr(first_block, 'proposed_reasoning', '') or ''
        classification_state = getattr(first_block, 'classification_state', '') or 'captured'

        # ← NEW: Build a suggestion if the classifier proposed anything
        suggestions = []
        if proposed_client_id or proposed_category:
            suggestions.append({
                'client':     proposed_clients_map.get(proposed_client_id, '') if proposed_client_id else '',
                'category':   proposed_category,
                'confidence': proposed_confidence,
                'reasoning':  proposed_reasoning[:200],
            })
        # v1.3.60: heuristic fallback for patterns the classifier doesn't propose
        if not suggestions:
            heuristic = _heuristic_suggestion(first_block, user, org, clients_by_name_lower)
            if heuristic:
                suggestions.append(heuristic)

        blocks_data.append({
            'id': first_block.id,
            'block_ids': block_ids,
            'block_count': len(session),
            'start': first_block.start.isoformat(),
            'end': last_block.end.isoformat(),
            'duration_minutes': total_minutes,
            'span_minutes': round(span_minutes, 1),
            
            'app_name': first_block.app_name or '',
            'window_title': first_block.window_title or '',
            'url': first_block.url or '',
            'file_path': first_block.file_path or '',
            
            'display': {
                'title': formatted['title'],
                'app': formatted['app'],
                'duration': formatted['duration'],
            },
            
            'current_client': client_name,
            'current_client_id': first_block.client.id if first_block.client else None,
            'suggestions': suggestions,                                          # ← NEW (was [])
            'classification_state': classification_state,                        # ← NEW
            'is_billable_suggested': getattr(first_block, 'is_billable', True),  # ← NEW
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
            
            # State machine
            block.classification_state = 'committed'
            block.state_changed_at = timezone.now()
            block.state_changed_by = 'user'
            
            if notes:
                block.notes = notes
            
            # Save with force_update to bypass protection
            block.save(force_update=True)
            updated_blocks.append(block)
            
            # ✅ Learn from this manual categorization
            try:
                from tracker.services.pattern_learning import PatternLearningService
                # Bulk group-assign — one client stamped across many varied
                # blocks. Rubber-stamp risk, so do NOT teach patterns from it.
                PatternLearningService.learn_from_block(block, user, source='bulk_move')
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
            block.classification_state = 'committed'
            block.state_changed_at = timezone.now()
            block.state_changed_by = 'user'
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
    org = get_request_org_override(request)
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
    org = get_request_org_override(request)
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
        
        from tracker.services.classification_service import ClassificationService

        # Fields the service doesn't own — set these directly, then save
        # via the service so the manual ClassificationAudit row gets written.
        if 'project_id' in data and data['project_id']:
            block.project_id = data['project_id']
        if 'task_type_id' in data and data['task_type_id']:
            block.task_type_id = data['task_type_id']
        if data.get('notes'):
            block.notes = data['notes']

        override = {}
        if 'client_id' in data and data['client_id']:
            override['client_id'] = data['client_id']
        if 'category' in data and data.get('category'):
            override['category'] = data['category']

        service = ClassificationService(org=block.org, user=request.user)
        service.recommit(block, user=request.user, override=override)
        block.refresh_from_db()
        
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
            plan='professional',
            trial_ends_at=timezone.now() + timedelta(days=30),
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
        accepted_at__isnull=True,
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
def password_reset_request(request):
    """POST /api/auth/password-reset/ — start a reset.

    Always answers the same way, whether or not the address is known. A
    different response for a real account turns this endpoint into a way to
    test which of a firm's addresses exist.

    Accounts provisioned for MSI auto-pair have no usable password at all;
    those get their setup invite resent instead of a reset, because a reset
    link would land them on a page for changing something they never had.
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_encode
    from django.utils.encoding import force_bytes

    same_answer = Response({
        'ok': True,
        'detail': 'If that address has an account, a reset link is on its way.',
    })

    email = (request.data.get('email') or '').strip()
    if not email:
        return Response({'error': 'Email is required.'}, status=400)

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        return same_answer

    membership = OrganizationMembership.objects.filter(
        user=user
    ).select_related('organization').first()
    org_name = membership.organization.name if membership else 'TimeTracker'

    # Never signed in and no password: this is an unfinished setup, not a
    # forgotten password. Send the invite that was missing.
    if not user.has_usable_password() and membership:
        try:
            from tracker.views_onboarding import _issue_invite
            _issue_invite(
                membership.organization, user, membership.role,
                membership.invited_by or user,
            )
        except Exception as e:
            logger.error(f'[RESET] Could not re-issue invite for {email}: {e}')
        return same_answer

    base = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai').rstrip('/')
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = f'{base}/reset-password/{uid}/{token}'

    try:
        from tracker.email_service import send_password_reset
        send_password_reset(
            to_email=user.email,
            user_name=user.first_name or user.username,
            reset_url=reset_url,
            org_name=org_name,
        )
    except Exception as e:
        logger.error(f'[RESET] Could not send reset email to {email}: {e}')

    return same_answer


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    """POST /api/auth/password-reset/confirm/ — finish a reset.

    Django's token generator hashes the user's current password and last_login
    into the token, so using a link invalidates it and a stale link cannot be
    replayed. No model or migration needed for any of that.
    """
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.http import urlsafe_base64_decode
    from django.utils.encoding import force_str
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    uid = request.data.get('uid') or ''
    token = request.data.get('token') or ''
    password = request.data.get('password') or ''

    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return Response({'error': 'This reset link is no longer valid.'}, status=400)

    if not default_token_generator.check_token(user, token):
        return Response({'error': 'This reset link has expired or was already used.'}, status=400)

    try:
        validate_password(password, user=user)
    except DjangoValidationError as e:
        return Response({'error': ' '.join(e.messages)}, status=400)

    user.set_password(password)
    user.save(update_fields=['password'])
    logger.info(f'[RESET] Password reset completed for {user.email}')

    return Response({'ok': True, 'detail': 'Your password has been changed. You can sign in now.'})


def _lookup_invite(token):
    """Resolve a live invite token, or return None."""
    return Invitation.objects.select_related('organization', 'invited_by').filter(
        token=token,
        accepted_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()


@api_view(['GET'])
@permission_classes([AllowAny])
def invite_details(request, token):
    """GET /api/invite/<token>/ — what the accept page needs before it renders.

    Told apart from a bad token deliberately: an expired invite gets a "ask for
    a new one" path, while a garbage token gets nothing, so a guessed token
    never confirms an address exists.
    """
    invite = _lookup_invite(token)
    if not invite:
        stale = Invitation.objects.filter(token=token).first()
        if stale:
            return Response({
                'valid': False,
                'reason': 'accepted' if stale.accepted_at else 'expired',
            }, status=410)
        return Response({'valid': False, 'reason': 'invalid'}, status=404)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = User.objects.filter(email__iexact=invite.email).first()

    # Already has a password — the link has nothing left to do for them.
    if user and user.has_usable_password():
        return Response({'valid': False, 'reason': 'already_active'}, status=409)

    inviter = None
    if invite.invited_by:
        inviter = invite.invited_by.get_full_name().strip() or invite.invited_by.email

    return Response({
        'valid': True,
        'email': invite.email,
        'name': f"{user.first_name} {user.last_name}".strip() if user else '',
        'org_name': invite.organization.name,
        'invited_by': inviter,
        'role': invite.role,
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def accept_invitation(request, token):
    """POST /api/invite/<token>/accept/ — member chooses their password.

    The account was already created when the invite was sent (so the seat is
    held and they appear in the team list), so this fills in the password
    rather than creating anything. Falls back to creating the user for tokens
    minted before that was true.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    User = get_user_model()

    invite = _lookup_invite(token)
    if not invite:
        return Response({'error': 'This invitation is no longer valid.'}, status=400)

    password = request.data.get('password') or ''
    name = (request.data.get('name') or '').strip()

    user = User.objects.filter(email__iexact=invite.email).first()

    # Never let a stale invite overwrite the password of a live account.
    if user and user.has_usable_password():
        return Response(
            {'error': 'This account is already active. Please sign in instead.'},
            status=409,
        )

    try:
        validate_password(password, user=user)
    except DjangoValidationError as e:
        return Response({'error': ' '.join(e.messages)}, status=400)

    with transaction.atomic():
        if not user:
            username = invite.email.split('@')[0][:30]
            if User.objects.filter(username=username).exists():
                username = f"{username}-{uuid.uuid4().hex[:6]}"
            user = User.objects.create_user(
                username=username,
                email=invite.email,
                password=password,
            )
        else:
            user.set_password(password)

        if name:
            parts = name.split()
            user.first_name = parts[0]
            user.last_name = ' '.join(parts[1:])
        user.is_active = True
        user.save()

        OrganizationMembership.objects.get_or_create(
            user=user,
            organization=invite.organization,
            defaults={'role': invite.role, 'invited_by': invite.invited_by},
        )

        invite.accepted_at = timezone.now()
        invite.save(update_fields=['accepted_at'])

    login(request, user)

    from tracker.models import AuthToken
    token_value = secrets.token_urlsafe(32)
    AuthToken.objects.create(
        user=user,
        token=token_value,
        expires_at=timezone.now() + timedelta(days=14),
    )

    membership = OrganizationMembership.objects.filter(
        user=user
    ).select_related('organization').first()

    return Response({
        'success': True,
        'ok': True,
        'token': token_value,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email or '',
            'name': f"{user.first_name} {user.last_name}".strip(),
        },
        'organization': {
            'id': membership.organization.id,
            'name': membership.organization.name,
            'slug': membership.organization.slug,
        } if membership else None,
        'role': membership.role if membership else None,
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
        classification_state='committed',
        state_changed_at=timezone.now(),
        state_changed_by='user',
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
    Soft-delete a time block and unlink all its RawEvents.
    Unlinking events means they won't appear in today_time at all
    (no block reference → treated as unlinked background noise).
    """
    user = request.user

    try:
        block = Block.objects.get(id=block_id, user=user)
    except Block.DoesNotExist:
        return Response({"success": True, "message": "Block already deleted"})

    block_info = {
        "block_id": block.id,
        "title": block.title,
        "minutes": block.minutes,
        "client": block.client.name if block.client else "Unassigned",
    }

    # Soft-delete the block (bypasses model save() override)
    Block.objects.filter(id=block_id, user=user).update(deleted_at=timezone.now())

    # Unlink RawEvents — once block=None, today_time skips them entirely
    RawEvent.objects.filter(block_id=block_id, user=user).update(block=None)

    return Response({
        "success": True,
        "message": "Block deleted successfully",
        **block_info
    })


def _is_nonbillable_category(category):
    return (category or '').strip().lower() in {'personal/non-billable', 'idle', 'uncategorized'}


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def recategorize_block(request, block_id):
    """Move a block to a different category and/or client. Handles No Client."""
    try:
        block = Block.objects.get(id=block_id, user=request.user, deleted_at__isnull=True)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)

    new_category = request.data.get('category')
    client_provided = 'client_id' in request.data
    new_client_id = request.data.get('client_id')

    # No-Client moves allowed with empty category → default to non-billable.
    if not new_category:
        if client_provided and new_client_id is None:
            new_category = 'Personal/Non-Billable'
        else:
            return Response({"error": "category required"}, status=400)

    old_category = list(block.category_hours.keys())[0] if block.category_hours else None

    # PRESERVE the block's real recorded duration. Do NOT recompute from
    # end-start (idle-capped / merged blocks have category_hours != span).
    existing_total = sum((block.category_hours or {}).values())
    if existing_total <= 0:
        # Proposed/second-pass blocks have empty category_hours AND may have
        # null start/end. Fall back to block.minutes (the real recorded
        # duration) before giving up — otherwise we'd write a ZERO-hour
        # category, which commits but contributes 0 to billable and never
        # renders in today_time (which sums category_hours hours).
        if block.end and block.start:
            existing_total = (block.end - block.start).total_seconds() / 3600
        elif getattr(block, 'minutes', None):
            existing_total = block.minutes / 60.0
        else:
            existing_total = 0
    block.category_hours = {new_category: round(existing_total, 4)}

    # Client: distinguish "absent" (leave as-is) from "present & null" (No Client).
    if client_provided:
        if new_client_id is None:
            block.client = None
            block.is_billable = False
        else:
            try:
                block.client = Client.objects.get(id=new_client_id)
                block.is_billable = not _is_nonbillable_category(new_category)
            except Client.DoesNotExist:
                pass

    # Protect the manual decision from re-classification.
    block.categorized_by = 'correction'
    block.categorized_at = timezone.now()
    block.is_categorized = True
    block.classification_state = 'committed'

    block.save(force_update=True)

    # Gated pattern learning. This endpoint handles single per-row confirms AND
    # multi-select bulk-moves/drags identically (one recategorize call per
    # block), so we teach ONLY when the frontend explicitly tags the action as a
    # deliberate single confirm. PatternLearningService.learn_from_block further
    # gates on LEARNING_SOURCES = {'correction','single_confirm','manual'}, so any
    # other source (bulk_move, drag, or absent → default) is a safe no-op. This
    # is what prevents the bulk rubber-stamp poisoning we guarded against before.
    # Auto-confirmed blocks never reach this path (committed by the classifier),
    # so a machine guess can never reinforce itself.
    _learn_source = (request.data.get('source') or 'bulk_move')
    if _learn_source in {'single_confirm', 'correction', 'manual'} and block.client_id:
        try:
            PatternLearningService.learn_from_block(
                block, request.user, source=_learn_source
            )
            log(f"[PATTERN] Learned from {_learn_source} on block {block.id} "
                f"→ client {block.client_id}")
        except Exception as e:
            log(f"[PATTERN] Failed to learn from block {block.id}: {e}")

    return Response({
        "success": True,
        "block_id": block.id,
        "old_category": old_category,
        "new_category": new_category,
        "client_id": block.client_id,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def blocks_needing_matter(request):
    """
    GET /api/blocks/needs-matter/?date=YYYY-MM-DD

    Blocks that a person can actually resolve: committed time, no matter yet,
    whose client HAS matters to choose between.

    Deliberately excludes clients with no matters. Nobody can act on those from
    here, and listing them would turn a short actionable queue into a long one
    people learn to skip.

    Same day by default, because a matter chosen on Tuesday is remembered and a
    matter chosen on Friday is reconstructed — and a reconstruction bills a
    client.
    """
    from datetime import datetime as _dt
    from tracker.models_task_type_sets import ExternalMatterMapping

    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)

    raw = request.GET.get('date')
    try:
        day = _dt.strptime(raw, '%Y-%m-%d').date() if raw else timezone.localdate()
    except ValueError:
        return Response({'error': 'date must be YYYY-MM-DD'}, status=400)

    counts = {}
    for m in ExternalMatterMapping.objects.filter(
        integration__organization=org
    ).select_related('project'):
        if (m.external_status or '').lower() in ('open', 'pending', ''):
            counts[m.project.client_id] = counts.get(m.project.client_id, 0) + 1

    if not counts:
        return Response({'date': str(day), 'blocks': [], 'total_minutes': 0})

    blocks = (
        Block.objects
        .filter(org=org, user=request.user, day=day,
                project__isnull=True, client_id__in=counts.keys(),
                deleted_at__isnull=True)
        .exclude(classification_state='suppressed')
        .select_related('client')
        .order_by('start')
    )

    rows = [{
        'id': b.id,
        'minutes': b.minutes or 0,
        'started_at': b.start.isoformat() if b.start else None,
        'client_id': b.client_id,
        'client_name': b.client.name if b.client else None,
        # window_title carries the subject; title is often just the app.
        'label': (b.window_title or b.title or '').strip() or '(no title)',
        'matter_options': counts.get(b.client_id, 0),
    } for b in blocks]

    return Response({
        'date': str(day),
        'blocks': rows,
        'total_minutes': sum(r['minutes'] for r in rows),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def block_matter_options(request, block_id):
    """
    GET /api/blocks/<id>/matter-options/

    Matters this block could belong to — its client's open matters, plus
    whichever one is already set. Scoped to the client rather than the whole
    firm: picking from three matters is a decision, picking from four hundred
    is a search.
    """
    from tracker.models_task_type_sets import ExternalMatterMapping

    try:
        block = Block.objects.get(id=block_id, user=request.user, deleted_at__isnull=True)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)

    mappings = (
        ExternalMatterMapping.objects
        .filter(integration__organization=block.org, project__client_id=block.client_id)
        .select_related('project')
    )
    candidates = [
        m for m in mappings
        if (m.external_status or '').lower() in ('open', 'pending', '')
        or m.project_id == block.project_id
    ]

    # When did THIS user last work each of these matters. Lawyers live in a
    # handful of active matters, so putting those first turns most picks into
    # hitting the top row instead of reading a list.
    from django.db.models import Max
    last_worked = dict(
        Block.objects
        .filter(user=request.user, org=block.org,
                project_id__in=[m.project_id for m in candidates])
        .values_list('project_id')
        .annotate(last=Max('start'))
    )

    def sort_key(m):
        # Recently worked first, then newest matter — a matter opened last week
        # is likelier to be the one in hand than one opened three years ago.
        return (
            last_worked.get(m.project_id) is None,
            -(last_worked[m.project_id].timestamp() if last_worked.get(m.project_id) else 0),
            -(m.open_date.toordinal() if m.open_date else 0),
            m.display_number or '',
        )

    options = [
        {
            'project_id': m.project_id,
            'display_number': m.display_number,
            'description': m.external_name,
            'status': m.external_status,
            'billing_method': m.billing_method,
            'requires_utbms': m.requires_utbms,
            # The fields that make two same-named matters distinguishable.
            'open_date': m.open_date.isoformat() if m.open_date else None,
            'responsible_attorney': m.responsible_attorney,
            'practice_area': m.practice_area,
            'last_worked': (last_worked[m.project_id].isoformat()
                            if last_worked.get(m.project_id) else None),
        }
        for m in sorted(candidates, key=sort_key)
    ]

    return Response({
        'block_id': block.id,
        'client_id': block.client_id,
        'client_name': block.client.name if block.client else None,
        'current_project_id': block.project_id,
        'options': options,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_block_matter(request, block_id):
    """
    POST /api/blocks/<id>/set-matter/   body: {"project_id": 63}

    Assign a block to a matter by hand, for work the resolver abstained on.

    Worth more than fixing one row. Matter attribution learns from blocks that
    already carry a project, so a correction here teaches every future document
    in the same folder — the person trains the system by doing the thing they
    wanted to do anyway. `learns_folder` says whether that will happen, so the
    UI can tell them.

    project_id=null clears it, for a pick made in error.
    """
    from tracker.services.matter_attribution import folder_key

    try:
        block = Block.objects.get(id=block_id, user=request.user, deleted_at__isnull=True)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)

    project_id = request.data.get("project_id")

    # `project` is one of Block.save's protected fields, so a categorized block
    # rejects the write with ValueError — which surfaced as a 500 and a picker
    # that silently did nothing. force_classifier is the sanctioned bypass for a
    # user-accepted correction, the same one move_block_task_type uses.
    if project_id in (None, '', 0):
        block.project = None
        block.save(update_fields=['project'], force_classifier=True)
        return Response({'ok': True, 'block_id': block.id, 'project_id': None})

    try:
        project = Project.objects.get(id=project_id, org=block.org)
    except Project.DoesNotExist:
        return Response({"error": "Matter not found for this organization"}, status=404)

    # A matter belongs to one client. A block pointing at another client's
    # matter would push its time onto the wrong client's bill.
    if block.client_id and project.client_id != block.client_id:
        return Response(
            {"error": "That matter belongs to a different client."}, status=400,
        )

    block.project = project
    block.save(update_fields=['project'], force_classifier=True)

    return Response({
        'ok': True,
        'block_id': block.id,
        'project_id': project.id,
        'project_name': project.name,
        'learns_folder': bool(folder_key(block.file_path or '')),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def move_block_task_type(request, block_id):
    """Move a block to a different TaskType (category) from the weekly timesheet.

    The weekly timesheet groups by Block.task_type, while Daily Review and billing
    read Block.category_hours / Block.is_billable. A category move must keep ALL
    THREE consistent, or the change would show in one view but not the others.
    So this endpoint, given a target task_type_id:

      - sets block.task_type            (weekly timesheet regroups)
      - sets category_hours={name: hrs} (Daily Review relabels)
      - sets is_billable from the TaskType (billing $ follows; No-Client stays
        non-billable, and Block.save still enforces internal-client non-billable)

    It preserves the block's real recorded duration and routes through the audited
    ClassificationService.recommit() path (writes a manual ClassificationAudit and
    commits the block), same as every other user correction.
    """
    try:
        block = Block.objects.get(id=block_id, user=request.user, deleted_at__isnull=True)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)

    task_type_id = request.data.get("task_type_id")
    if not task_type_id:
        return Response({"error": "task_type_id required"}, status=400)

    try:
        tt = TaskType.objects.get(id=task_type_id, org=block.org, is_active=True)
    except TaskType.DoesNotExist:
        return Response({"error": "TaskType not found for this organization"}, status=404)

    # Preserve the real recorded duration (category_hours != end-start for
    # idle-capped / merged blocks), mirroring recategorize_block's fallback chain.
    hours = sum((block.category_hours or {}).values())
    if hours <= 0:
        if block.end and block.start:
            hours = (block.end - block.start).total_seconds() / 3600
        elif getattr(block, "minutes", None):
            hours = block.minutes / 60.0
        else:
            hours = 0.0

    # A No-Client block is never billable regardless of the category picked;
    # otherwise inherit the TaskType's billable flag. Block.save independently
    # enforces internal-client → non-billable, so we don't duplicate that here.
    is_billable = bool(tt.is_billable) and block.client_id is not None

    from tracker.services.classification_service import ClassificationService

    block.task_type = tt
    service = ClassificationService(org=block.org, user=request.user)
    service.recommit(
        block,
        user=request.user,
        override={
            "category": tt.name,
            "category_hours": {tt.name: round(hours, 4)},
            "is_billable": is_billable,
        },
        audit_detail={"action": "timesheet_move_task_type", "task_type_id": tt.id},
    )

    return Response({
        "success": True,
        "block_id": block.id,
        "task_type": {"id": tt.id, "name": tt.name},
        "is_billable": block.is_billable,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def split_block(request, block_id):
    """POST /api/blocks/<id>/split/ — carve ONE block into pieces per client.

    A genuinely-mixed block (e.g. 5m in a No-Client timesheet + 2m in a client's
    workbook) can be split so each slice books to its own client, instead of the
    whole block landing on one attribution.

    Body: {"assignments": {"<slice label>": {"client_id": int|null, "category": str}}}
    where the labels are the breakdown slices the user saw (from /blocks/<id>/why/).
    Any slice not named keeps the block's current client.

    Mechanics (migration-free, all-or-nothing):
      - regroup the block's sub-events by those same slice labels,
      - group the events by their assigned (client, category),
      - the largest group stays as THIS block (re-attributed in place),
      - each other group becomes a NEW committed block built from its events,
      - minutes are the real interval-union of each group's events, so the pieces
        sum to (at most) the original — no invented or double-counted time.

    Refuses to split time that's already been invoiced or synced to QB/Xero.
    """
    from django.db import transaction
    from tracker.models import RawEvent
    from tracker.services.classification_service import ClassificationService
    from tracker.services.compaction import _calculate_minutes_from_events
    from tracker.views_block_evidence import block_slices
    from collections import defaultdict

    user = request.user
    try:
        block = Block.objects.get(id=block_id, user=user, deleted_at__isnull=True)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)

    if block.invoiced or getattr(block, "qb_time_activity_id", None) or getattr(block, "xero_invoice_id", None):
        return Response(
            {"error": "This entry is already invoiced or synced to your billing system, so it can't be split."},
            status=400,
        )

    assignments = (request.data or {}).get("assignments") or {}
    if not isinstance(assignments, dict) or not assignments:
        return Response({"error": "assignments required"}, status=400)

    slices = block_slices(block)  # {label: [event_id, ...]}
    if not slices:
        return Response({"error": "This entry has no sub-activity to split."}, status=400)

    # Defaults for any slice the user didn't reassign: keep the block's current attribution.
    default_client_id = block.client_id
    ch = block.category_hours or {}
    default_category = (
        max(ch, key=ch.get) if ch
        else (getattr(block, "proposed_category", None) or "General Client Work")
    )

    # Validate assigned client ids belong to this org.
    org = block.org
    assigned_ids = {
        a.get("client_id") for a in assignments.values()
        if isinstance(a, dict) and a.get("client_id") is not None
    }
    if assigned_ids:
        valid = set(
            Client.objects.filter(org=org, id__in=assigned_ids).values_list("id", flat=True)
        )
        bad = assigned_ids - valid
        if bad:
            return Response({"error": f"Unknown client(s): {sorted(bad)}"}, status=400)

    # Map each slice's events to its assigned (client, category); merge slices that
    # land on the same client+category into one group.
    groups = defaultdict(list)  # (client_id, category) -> [event_id, ...]
    for label, ev_ids in slices.items():
        a = assignments.get(label)
        if isinstance(a, dict):
            cid = a.get("client_id")
            cat = (a.get("category") or default_category)
        else:
            cid, cat = default_client_id, default_category
        groups[(cid, cat)].extend(ev_ids)

    if len(groups) <= 1:
        return Response(
            {"error": "Every slice goes to the same client — nothing to split. Use “Change client” instead."},
            status=400,
        )

    # Largest group (by real minutes) keeps the original block; the rest split off.
    def _group_minutes(ev_ids):
        return _calculate_minutes_from_events(
            RawEvent.objects.filter(id__in=ev_ids, start_ts__isnull=False, end_ts__isnull=False)
        )

    ordered = sorted(groups.items(), key=lambda kv: -_group_minutes(kv[1]))
    (keep_key, keep_ev_ids), *carve = ordered

    svc = ClassificationService(org=org, user=user)
    created = []
    try:
        with transaction.atomic():
            for (cid, cat), ev_ids in carve:
                evs = list(
                    RawEvent.objects.filter(id__in=ev_ids)
                    .order_by("start_ts")
                    .only("id", "start_ts", "end_ts", "window_title", "app_name", "file_path", "url")
                )
                if not evs:
                    continue
                rep = max(
                    evs,
                    key=lambda e: ((e.end_ts - e.start_ts).total_seconds()
                                   if e.end_ts and e.start_ts else 0),
                )
                nb = Block.objects.create(
                    org=org, user=user,
                    device_id=block.device_id, hostname=block.hostname,
                    day=block.day, start=evs[0].start_ts, end=evs[-1].end_ts,
                    window_title=(rep.window_title or block.window_title or ""),
                    app_name=(rep.app_name or block.app_name or ""),
                    file_path=(rep.file_path or ""), url=(rep.url or ""),
                    category_hours={}, is_categorized=False, is_billable=True,
                )
                RawEvent.objects.filter(id__in=ev_ids).update(block=nb)
                nb.minutes = max(1, _calculate_minutes_from_events(
                    RawEvent.objects.filter(block=nb, start_ts__isnull=False, end_ts__isnull=False)
                ))
                svc.commit(nb, user=user, override={
                    "client_id": cid, "category": cat, "is_billable": cid is not None,
                })
                created.append({"id": nb.id, "client_id": cid, "minutes": nb.minutes})

            # Re-attribute the retained block to its group's client, on its remaining events.
            keep_cid, keep_cat = keep_key
            remaining = list(
                RawEvent.objects.filter(id__in=keep_ev_ids)
                .only("id", "start_ts", "end_ts", "window_title", "app_name", "file_path", "url")
            )
            block.minutes = max(1, _calculate_minutes_from_events(
                RawEvent.objects.filter(block=block, start_ts__isnull=False, end_ts__isnull=False)
            ))
            # Refresh the representative title from what's LEFT — otherwise the kept
            # block keeps the pre-split dominant title and displays a carved-off
            # slice's filename (e.g. it retains St Peter's events but still reads
            # "St. Paul's Church bills"). Mirrors how carved blocks pick a rep event.
            rep = max(
                (e for e in remaining if e.window_title),
                key=lambda e: ((e.end_ts - e.start_ts).total_seconds()
                               if e.end_ts and e.start_ts else 0),
                default=None,
            )
            if rep:
                block.window_title = rep.window_title
                block.app_name = rep.app_name or block.app_name
                block.file_path = rep.file_path or ""
                block.url = rep.url or ""
            svc.recommit(block, user=user, override={
                "client_id": keep_cid, "category": keep_cat, "is_billable": keep_cid is not None,
            })
    except Exception as e:
        log(f"[SPLIT] block {block_id} failed: {e}")
        return Response({"error": f"Split failed: {e}"}, status=500)

    return Response({
        "success": True,
        "kept_block": {"id": block.id, "client_id": block.client_id, "minutes": block.minutes},
        "new_blocks": created,
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
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def settings_org(request):
    """GET/PATCH organization settings including industry_type."""
    from decimal import Decimal, InvalidOperation
    from tracker.industry_categories import INDUSTRY_CHOICES
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
    if not membership:
        return Response({"error": "No organization found"}, status=404)

    # ── Admin impersonation override ──
    override_id = request.GET.get("org_id")
    if override_id and (request.user.is_staff or request.user.is_superuser):
        try:
            org = Organization.objects.get(id=int(override_id))
        except (Organization.DoesNotExist, ValueError, TypeError):
            org = membership.organization
    else:
        org = membership.organization
    is_admin_or_owner = membership.role in ["owner", "admin"]
    profile, _ = OrgProfile.objects.get_or_create(org=org)
    if request.method == "GET":
        return Response({
            "id": org.id,
            "name": org.name,
            "slug": getattr(org, "slug", "") or "",
            "industry_type": getattr(org, 'industry_type', 'general') or 'general',
            "industry_name": dict(INDUSTRY_CHOICES).get(
                getattr(org, 'industry_type', 'general'), 
                'General Professional Services'
            ),
            "plan": getattr(org, "plan", "none"),
            "seat_count": getattr(org, "seat_count", 1),
            "auto_submit_timesheets": getattr(org, "auto_submit_timesheets", False),
            "trial_ends_at": org.trial_ends_at.isoformat() if getattr(org, "trial_ends_at", None) else None,
            "billing_email": profile.billing_email or "",
            "billing_contact": profile.billing_contact or "",
            "billing_rate_default": str(getattr(org, "billing_rate_default", None) or "150.00"),
            "cost_rate_default": str(getattr(org, "cost_rate_default", None) or "75.00") if is_admin_or_owner else "0.00",
            "target_utilization": str(getattr(org, "target_utilization", None) or "75.00"),
            "capacity_hours_per_week": str(getattr(org, "capacity_hours_per_week", None) or "40.00"),
            "created_at": org.created_at.isoformat() if getattr(org, "created_at", None) else None,
            "can_edit_org": is_admin_or_owner,
            "role": membership.role,
            "ai_sensitivity":   org.ai_sensitivity,   # <-- NEW
            "sensitivity_label": _sensitivity_label(org.ai_sensitivity),  # add this

        })
    # PATCH
    if not is_admin_or_owner:
        return Response({"error": "Only owner/admin can update"}, status=403)
    if "name" in request.data:
        org.name = request.data["name"]
    if "industry_type" in request.data:
        new_industry = request.data["industry_type"]
        valid_industries = [choice[0] for choice in INDUSTRY_CHOICES]
        if new_industry in valid_industries:
            org.industry_type = new_industry
    if "billing_rate_default" in request.data:
        org.billing_rate_default = Decimal(str(request.data["billing_rate_default"]))
    if "cost_rate_default" in request.data:
        org.cost_rate_default = Decimal(str(request.data["cost_rate_default"]))
    if "target_utilization" in request.data:
        try:
            v = Decimal(str(request.data["target_utilization"]))
            org.target_utilization = max(Decimal("0"), min(Decimal("100"), v))
        except (TypeError, ValueError, InvalidOperation):
            pass
    if "capacity_hours_per_week" in request.data:
        try:
            v = Decimal(str(request.data["capacity_hours_per_week"]))
            org.capacity_hours_per_week = max(Decimal("0"), min(Decimal("168"), v))
        except (TypeError, ValueError, InvalidOperation):
            pass
    if "auto_submit_timesheets" in request.data:
        org.auto_submit_timesheets = bool(request.data["auto_submit_timesheets"])
    if "ai_sensitivity" in request.data:
        try:
            v = int(request.data["ai_sensitivity"])
            if 0 <= v <= 100:
                org.ai_sensitivity = v
        except (TypeError, ValueError):
            pass
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
        "auto_submit_timesheets": getattr(org, "auto_submit_timesheets", False),
        "billing_email": profile.billing_email or "",
        "billing_contact": profile.billing_contact or "",
        "billing_rate_default": str(getattr(org, "billing_rate_default", None) or "150.00"),
        "cost_rate_default": str(getattr(org, "cost_rate_default", None) or "75.00") if is_admin_or_owner else "0.00",
        "target_utilization": str(getattr(org, "target_utilization", None) or "75.00"),
        "capacity_hours_per_week": str(getattr(org, "capacity_hours_per_week", None) or "40.00"),
        "message": "Settings updated"
    })


from django.core.exceptions import ValidationError
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import json

# @api_view(["GET", "PATCH"])
# @authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
# @permission_classes([IsAuthenticated])
# def org_ai_settings(request):
#     print(f"[AI_DEBUG] user={request.user.username} id={request.user.id}")
    
#     membership = OrganizationMembership.objects.select_related("organization").filter(
#         user=request.user
#     ).first()
    
#     print(f"[AI_DEBUG] membership={membership} role={getattr(membership, 'role', None)}")
    
#     if not membership:
#         return Response({"error": "No organization found"}, status=404)

#     org = membership.organization

#     print(f"[AI_DEBUG] role check: {membership.role not in ('admin', 'owner')}")
    
#     if membership.role not in ("admin", "owner"):
#         return Response({"error": "Admin access required"}, status=403)

#     if request.method == "GET":
#         return Response({
#             "ai_sensitivity": org.ai_sensitivity,
#             "sensitivity_label": _sensitivity_label(org.ai_sensitivity),
#         })

#     # PATCH
#     sensitivity = request.data.get("ai_sensitivity")
#     if sensitivity is None:
#         return Response({"error": "ai_sensitivity is required"}, status=400)

#     try:
#         sensitivity = int(sensitivity)
#         if not (0 <= sensitivity <= 100):
#             raise ValueError
#     except (TypeError, ValueError):
#         return Response({"error": "ai_sensitivity must be an integer 0–100"}, status=400)

#     org.ai_sensitivity = sensitivity
#     org.save(update_fields=["ai_sensitivity"])

#     return Response({
#         "ai_sensitivity": org.ai_sensitivity,
#         "sensitivity_label": _sensitivity_label(org.ai_sensitivity),
#         "updated": True,
#     })


def _sensitivity_label(value: int) -> str:
    if value <= 20:   return "Conservative"
    elif value <= 40: return "Cautious"
    elif value <= 60: return "Balanced"
    elif value <= 80: return "Aggressive"
    else:             return "Very Aggressive"

# ============================================================================
# Team Members
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_list(request):
    """List all team members in the organization"""
    org = get_request_org_override(request)
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


# ============================================================================
# Labor Cost Tiers (firm-defined cost bands + member assignment)
# ============================================================================
# The analytics engine resolves each user's cost as: per-person EmployeeCostRate
# override > their CostTier rate > org.cost_rate_default (see
# tracker/analytics_v2/cost_rates.py). This endpoint manages the tiers and the
# member->tier assignment (plus optional per-person overrides). Scales to large
# firms: set a handful of tier rates instead of a rate per employee.

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_cost_rates(request):
    """Cost tiers + member assignment. Admin/owner only."""
    from tracker.models import CostTier, EmployeeCostRate

    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    if request.method == "GET":
        memberships = list(
            OrganizationMembership.objects.filter(organization=org).select_related("user")
        )
        # Per-person overrides (latest per user).
        override = {}
        for cr in (EmployeeCostRate.objects
                   .filter(organization=org)
                   .order_by("user_id", "-effective_date")):
            if cr.user_id not in override:
                override[cr.user_id] = cr.cost_rate

        counts = {}
        for m in memberships:
            if m.cost_tier_id:
                counts[m.cost_tier_id] = counts.get(m.cost_tier_id, 0) + 1

        tiers = [{
            "id": t.id,
            "label": t.label,
            "cost_rate": str(t.cost_rate),
            "bill_rate": str(t.bill_rate) if t.bill_rate is not None else "",
            "hours_per_week": str(t.hours_per_week) if t.hours_per_week is not None else "",
            "counts_toward_utilization": t.counts_toward_utilization,
            "target_utilization": str(t.target_utilization) if t.target_utilization is not None else "",
            "sort_order": t.sort_order,
            "member_count": counts.get(t.id, 0),
        } for t in CostTier.objects.filter(organization=org)]

        members = [{
            "id": m.user_id,
            "name": (f"{m.user.first_name} {m.user.last_name}".strip() or m.user.username),
            "role": m.role,
            "cost_tier_id": m.cost_tier_id,
            "override_rate": str(override[m.user_id]) if m.user_id in override else None,
        } for m in memberships]

        return Response({
            "default_cost": str(getattr(org, "cost_rate_default", None) or "75.00"),
            "default_bill": str(getattr(org, "billing_rate_default", None) or "150.00"),
            "default_capacity": str(getattr(org, "capacity_hours_per_week", None) or "40.00"),
            "tiers": tiers,
            "members": members,
        })

    # POST — any combination of: tier upserts/deletes, assignments, overrides.
    tiers_in = request.data.get("tiers") or []
    assignments = request.data.get("assignments") or []
    overrides = request.data.get("overrides") or []
    today = timezone.now().date()

    def _dec(v):
        try:
            d = Decimal(str(v))
            return d if d > 0 else None
        except (TypeError, ValueError, InvalidOperation):
            return None

    # 1) Tier upserts / deletes.
    for row in tiers_in:
        tid = row.get("id")
        if row.get("_delete") and tid:
            CostTier.objects.filter(organization=org, id=tid).delete()
            continue
        label = (row.get("label") or "").strip()
        rate = _dec(row.get("cost_rate"))
        if not label or rate is None:
            continue
        # bill_rate / hours_per_week optional: blank/invalid -> None (org default)
        bill = _dec(row.get("bill_rate")) if row.get("bill_rate") not in (None, "") else None
        hours = _dec(row.get("hours_per_week")) if row.get("hours_per_week") not in (None, "") else None
        # Chargeable flag: default True; only False when explicitly sent false.
        counts_util = row.get("counts_toward_utilization")
        counts_util = True if counts_util is None else bool(counts_util)
        # Cohort target %: blank/invalid → None (falls back to org target).
        target = _dec(row.get("target_utilization")) if row.get("target_utilization") not in (None, "") else None
        if tid:
            CostTier.objects.filter(organization=org, id=tid).update(
                label=label, cost_rate=rate, bill_rate=bill, hours_per_week=hours,
                counts_toward_utilization=counts_util, target_utilization=target,
                sort_order=row.get("sort_order", 0),
            )
        else:
            CostTier.objects.get_or_create(
                organization=org, label=label,
                defaults={"cost_rate": rate, "bill_rate": bill, "hours_per_week": hours,
                          "counts_toward_utilization": counts_util,
                          "target_utilization": target,
                          "sort_order": row.get("sort_order", 0)},
            )

    valid_tier_ids = set(
        CostTier.objects.filter(organization=org).values_list("id", flat=True)
    )
    member_ids = set(
        OrganizationMembership.objects.filter(organization=org).values_list("user_id", flat=True)
    )

    # 2) Member -> tier assignment (null clears).
    assigned = 0
    for row in assignments:
        uid = row.get("user_id")
        if uid not in member_ids:
            continue
        tid = row.get("cost_tier_id")
        if tid is not None and tid not in valid_tier_ids:
            continue
        OrganizationMembership.objects.filter(
            organization=org, user_id=uid
        ).update(cost_tier_id=tid)
        assigned += 1

    # 3) Per-person overrides (null/blank clears all overrides for that user).
    for row in overrides:
        uid = row.get("user_id")
        if uid not in member_ids:
            continue
        raw = row.get("cost_rate")
        if raw in (None, ""):
            EmployeeCostRate.objects.filter(organization=org, user_id=uid).delete()
            continue
        rate = _dec(raw)
        if rate is None:
            continue
        existing = (EmployeeCostRate.objects
                    .filter(organization=org, user_id=uid)
                    .order_by("-effective_date").first())
        if existing:
            existing.cost_rate = rate
            existing.save(update_fields=["cost_rate", "updated_at"])
        else:
            EmployeeCostRate.objects.create(
                organization=org, user_id=uid, cost_rate=rate, effective_date=today,
            )

    return Response({"success": True, "assigned": assigned, "message": "Cost tiers updated"})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_work_calendar(request):
    """Org work calendar — the utilization capacity denominator. Admin/owner only.

    Drives available capacity (scheduled hours − holidays − summer Fridays −
    PTO). When absent, capacity falls back to per-tier hours × weeks.
    """
    from tracker.models import WorkCalendar

    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)

    cal = WorkCalendar.objects.filter(org=org).first()

    if request.method == "GET":
        default_cap = str(getattr(org, "capacity_hours_per_week", None) or "40.00")
        if not cal:
            return Response({
                "configured": False,
                "hours_per_day": "8.00",
                "working_weekdays": [0, 1, 2, 3, 4],
                "summer_fridays_off": False,
                "summer_start_month": 6,
                "summer_end_month": 8,
                "avg_pto_days_per_year": "0.0",
                "holidays": [],
                "org_capacity_default": default_cap,
            })
        return Response({
            "configured": True,
            "hours_per_day": str(cal.hours_per_day),
            "working_weekdays": cal.working_weekdays or [0, 1, 2, 3, 4],
            "summer_fridays_off": cal.summer_fridays_off,
            "summer_start_month": cal.summer_start_month,
            "summer_end_month": cal.summer_end_month,
            "avg_pto_days_per_year": str(cal.avg_pto_days_per_year),
            "holidays": cal.holidays or [],
            "org_capacity_default": default_cap,
        })

    # POST — upsert the calendar.
    data = request.data or {}

    def _dec(v, default):
        try:
            return Decimal(str(v))
        except (TypeError, ValueError, InvalidOperation):
            return Decimal(str(default))

    def _month(v, default):
        try:
            m = int(v)
            return m if 1 <= m <= 12 else default
        except (TypeError, ValueError):
            return default

    weekdays = data.get("working_weekdays")
    if not isinstance(weekdays, list) or not all(isinstance(x, int) and 0 <= x <= 6 for x in weekdays):
        weekdays = [0, 1, 2, 3, 4]

    holidays = data.get("holidays")
    if not isinstance(holidays, list):
        holidays = []
    # Keep only well-formed ISO dates, de-duped and sorted.
    clean_holidays = []
    for h in holidays:
        try:
            d = dt.strptime(str(h), "%Y-%m-%d").date()
            clean_holidays.append(d.isoformat())
        except (TypeError, ValueError):
            continue
    clean_holidays = sorted(set(clean_holidays))

    WorkCalendar.objects.update_or_create(
        org=org,
        defaults={
            "hours_per_day": _dec(data.get("hours_per_day"), 8),
            "working_weekdays": sorted(set(weekdays)),
            "summer_fridays_off": bool(data.get("summer_fridays_off")),
            "summer_start_month": _month(data.get("summer_start_month"), 6),
            "summer_end_month": _month(data.get("summer_end_month"), 8),
            "avg_pto_days_per_year": _dec(data.get("avg_pto_days_per_year"), 0),
            "holidays": clean_holidays,
        },
    )
    return Response({"success": True, "message": "Work calendar saved"})


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
    
    # Brand new user. Delegated rather than duplicated: this used to mint its
    # own token_urlsafe(12) password and email it in the clear, which is the
    # thing the link-based invite flow exists to stop. One path, one behaviour.
    from tracker.views_onboarding import _create_and_invite_user

    result = _create_and_invite_user(
        org=org,
        email=email,
        role='member',
        name='',
        invited_by=request.user,
    )
    logger.info(f"[INVITE] Created {result['username']} and sent setup link to {email}")

    return Response({
        "success": True,
        "message": "User invited" if result['email_sent'] else "User created (invite email failed \u2014 send the link manually)",
        "user_id": result['user_id'],
        "username": result['username'],
        "invite_url": result['invite_url'],
        "email_sent": result['email_sent'],
    }, status=201)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_team_remove(request, user_id):
    """Remove a team member from the organization"""
    org = get_user_org(request.user)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    if user_id == request.user.id:
        return Response({"error": "Cannot remove yourself"}, status=400)
    
    try:
        membership = OrganizationMembership.objects.get(
            user_id=user_id,
            organization=org
        )
        
        if membership.role == 'owner':
            return Response({"error": "Cannot remove owner. Transfer ownership first."}, status=400)
        
        username = membership.user.username
        
        # Deactivate the user account so they can't log in
        membership.user.is_active = False
        membership.user.save(update_fields=['is_active'])
        
        membership.delete()
        
        return Response({
            "success": True,
            "message": f"Removed {username} from team",
        })
        
    except OrganizationMembership.DoesNotExist:
        return Response({"error": "User not found in this organization"}, status=404)


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
    org = get_request_org_override(request)
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
                "visibility": getattr(client, 'visibility', 'all') or 'all',
                "aliases": client.aliases or [],   # ADD THIS
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
        
        manual_aliases = request.data.get("aliases", []) or []
        client = Client.objects.create(
            org=org,
            name=name,
            code=code or None,
            visibility=request.data.get("visibility", "all"),
            aliases=manual_aliases,  # ADD THIS
            # Mark hand-entered aliases 'manual' so the self-heal never removes
            # them (only auto-derived aliases are ever auto-pruned).
            alias_sources={
                a.lower(): "manual" for a in manual_aliases if isinstance(a, str)
            },
        )

        # Best-effort: auto-derive name aliases for the new client (append-only,
        # never removes the manual aliases just entered above). Dispatched async
        # so a broker/derivation hiccup can never fail the create request.
        try:
            from tracker.tasks import derive_client_aliases_for_org
            derive_client_aliases_for_org.delay(org.id)
        except Exception:
            logger.warning("Alias derivation dispatch failed for org %s", org.id, exc_info=True)

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
    org = get_request_org_override(request)
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
        if "visibility" in request.data:
            client.visibility = request.data["visibility"]
        if "aliases" in request.data:                          # ADD THIS
            aliases = request.data["aliases"]
            aliases = aliases if isinstance(aliases, list) else []
            client.aliases = aliases
            # Re-sync provenance: preserve a known source (a kept 'derived'
            # alias stays self-heal-eligible), default any newly-typed alias to
            # 'manual', and drop entries for aliases the user removed.
            prior = client.alias_sources or {}
            client.alias_sources = {
                a.lower(): prior.get(a.lower(), "manual")
                for a in aliases if isinstance(a, str)
            }
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_client_alias(request, client_id):
    """Append ONE alias to a client — the inline "teach me this name" flow.

    Kept separate from the settings PATCH (which admins use to edit the whole
    alias list) so a reviewer doing corrections can teach a single name without
    org-admin rights. Marks the alias 'manual' so the nightly self-heal never
    removes it, and re-runs the sibling-collision gate server-side — the client
    is never trusted to have checked.
    """
    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    try:
        client = Client.objects.get(id=client_id, org=org)
    except Client.DoesNotExist:
        return Response({"error": "Client not found"}, status=404)

    alias = (request.data.get("alias") or "").strip()
    if not alias:
        return Response({"error": "alias required"}, status=400)

    existing = list(client.aliases or [])
    if any(isinstance(a, str) and a.lower() == alias.lower() for a in existing):
        return Response({"success": True, "aliases": existing, "already": True})

    from tracker.services.alias_suggestion import alias_is_safe_to_add
    siblings = list(Client.objects.filter(org=org).only("id", "name"))
    if not alias_is_safe_to_add(alias, client, siblings):
        return Response(
            {"error": "That alias is too close to another client and could "
                      "cause mix-ups. Edit it to something more specific."},
            status=409,
        )

    existing.append(alias)
    client.aliases = existing
    sources = dict(client.alias_sources or {})
    sources.setdefault(alias.lower(), "manual")
    client.alias_sources = sources
    client.save(update_fields=["aliases", "alias_sources"])
    return Response({"success": True, "aliases": existing})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def always_file_block(request, block_id):
    """One-click "always file titles like this under this client".

    Turns a single confirmation into a HARD, firm-wide rule: derives the
    distinctive client-name phrase already present in the block's title (e.g.
    "CNY Coin" from "CNY Coin Client Information — Excel") and adds it as a
    client alias, so future titles carrying that phrase auto-attribute to this
    client on the very next capture — no waiting for pattern-learning confidence
    to build. Reuses add_client_alias's sibling-collision safety gate.

    Aliases are org-scoped, so this applies FIRM-WIDE (everyone's captures).
    """
    try:
        block = Block.objects.get(id=block_id, user=request.user, deleted_at__isnull=True)
    except Block.DoesNotExist:
        return Response({"error": "Block not found"}, status=404)

    cid = request.data.get("client_id")
    if not cid:
        return Response({"error": "client_id required"}, status=400)

    org = block.org
    try:
        client = Client.objects.get(id=cid, org=org)
    except Client.DoesNotExist:
        return Response({"error": "Client not found"}, status=404)

    # Derive the alias = the longest contiguous run of the CLIENT's name tokens
    # that appears in the title (possessives folded, generic 1-char tokens gone).
    from tracker.views_block_evidence import _norm_name_toks
    ltoks = _norm_name_toks(block.window_title or "")
    ctoks = _norm_name_toks(client.name)
    label_join = " " + " ".join(ltoks) + " "
    alias = ""
    for i in range(len(ctoks)):
        for j in range(i + 1, len(ctoks) + 1):
            phrase = " ".join(ctoks[i:j])
            if (" " + phrase + " ") in label_join and len(phrase) > len(alias):
                alias = phrase
    if len(alias) < 5:
        return Response(
            {"error": "This title doesn’t clearly contain the client’s name, so a "
                      "safe rule can’t be auto-made. Use “Change → Remember a name”."},
            status=422,
        )

    existing = list(client.aliases or [])
    if any(isinstance(a, str) and a.lower() == alias.lower() for a in existing):
        return Response({"success": True, "alias": alias, "client_name": client.name, "already": True})

    from tracker.services.alias_suggestion import alias_is_safe_to_add
    siblings = list(Client.objects.filter(org=org).only("id", "name"))
    if not alias_is_safe_to_add(alias, client, siblings):
        return Response(
            {"error": f"“{alias}” is too close to another client to make a safe rule."},
            status=409,
        )

    existing.append(alias)
    client.aliases = existing
    sources = dict(client.alias_sources or {})
    sources.setdefault(alias.lower(), "manual")
    client.alias_sources = sources
    client.save(update_fields=["aliases", "alias_sources"])
    return Response({"success": True, "alias": alias, "client_name": client.name})


# ============================================================================
# Devices (Agent Registrations)
# ============================================================================

@api_view(["GET"])
@permission_classes([IsAuthenticated, IsOrgAdmin])
def settings_devices(request):
    """List all registered devices/agents for the organization"""
    from tracker.models import AgentDevice, OrganizationMembership
    
    org = get_request_org_override(request)
    if not org:
        return Response({"error": "No organization found"}, status=404)
    
    # Get all user IDs in this org
    org_user_ids = OrganizationMembership.objects.filter(
        organization=org
    ).values_list('user_id', flat=True)
    
    devices = AgentDevice.objects.filter(
        user_id__in=org_user_ids
    ).select_related("user").order_by("-last_seen_at")
    
    # Deduplicate: keep only the most recent per user+hostname
    seen = set()
    result = []
    for device in devices:
        key = (device.user_id, device.hostname)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "id": device.id,
            "user": device.user.username if device.user else "Unassigned",
            "user_id": device.user.id if device.user else None,
            "machine_name": device.hostname or device.device_id,
            "os": device.platform or "",
            "os_version": "",
            "agent_version": device.app_version or "",
            "first_seen": device.created_at.isoformat() if device.created_at else "",
            "last_seen": device.last_seen_at.isoformat() if device.last_seen_at else "",
            "is_active": device.is_active,
            "device_id": device.device_id,  # ← make sure this line exists

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
    latest_client = Client.objects.filter(org=org).order_by('-updated_at').first()
    
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
@authentication_classes([])
@permission_classes([AllowAny])
def agent_error_report(request):
    """
    Receive error reports from desktop agents.
    POST /api/agent/errors/

    Intentionally unauthenticated - uses device_id to find user/org.

    This MUST bypass the default AgentKeyAuthentication: a device whose
    org subscription is inactive (or whose device row was deactivated)
    gets a 403 `subscription_inactive` from that authenticator, which would
    otherwise reject the very error reports that tell us the agent is stuck.
    Those blocked devices are exactly the ones we most need to hear from,
    so error ingest is keyed by device_id, not by a valid DeviceKey.
    """
    from tracker.models import AgentError, AgentDevice
    
    data = request.data
    device_id = data.get('device_id')
    
    # Find user from device
    user = None
    org = None
    if device_id:
        try:
            device = AgentDevice.objects.select_related('user', 'org').get(device_id=device_id)
            user = device.user
            org = device.org
        except AgentDevice.DoesNotExist:
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


"""
Agent Log Storage + Retrieval
"""
 
from django.db import models as db_models
 
 
@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def receive_agent_logs(request):
    """
    Receive log lines shipped from agent.
    POST /api/agent/logs/
    """
    from .models import AgentDevice, AgentLog  # adjust import path
 
    device_id  = request.data.get("device_id")
    hostname   = request.data.get("hostname", "")
    platform_s = request.data.get("platform", "unknown")
    version    = request.data.get("app_version", "")
    trigger    = request.data.get("trigger", "scheduled")
    log_lines  = request.data.get("log_lines", [])
 
    if not log_lines:
        return Response({"error": "No log lines"}, status=400)
 
    log_text = "".join(log_lines)
 
    # Store in AgentLog model (see Part 3 for model)
    try:
        device = AgentDevice.objects.filter(
            user=request.user,
            device_id=device_id
        ).first()
 
        AgentLog.objects.create(
            user=request.user,
            device=device,
            agent_device_id=device_id or "",  # ← renamed
            hostname=hostname,
            platform=platform_s,
            app_version=version,
            trigger=trigger,
            log_text=log_text,
            line_count=len(log_lines),
        )

        # And the cleanup query:
        old_ids = list(
            AgentLog.objects.filter(user=request.user, agent_device_id=device_id or "")
            .order_by('-created_at')
            .values_list('id', flat=True)[10:]
        )
        AgentLog.objects.filter(id__in=old_ids).delete()
 
    except Exception as e:
        return Response({"error": str(e)}, status=500)
 
    return Response({"ok": True, "lines_received": len(log_lines)})
 
 
@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def get_agent_logs(request):
    """
    Get recent agent logs for a device.
    GET /api/agent/logs/?device_id=xxx
    Admin/owner only.
    """
    from .models import AgentLog
    from tracker.models import OrganizationMembership
 
    # Must be owner/admin
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
 
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
 
    org = membership.organization
 
    device_id = request.GET.get('device_id')
    hostname  = request.GET.get('hostname')
 
    # Get all devices in this org
    from django.contrib.auth import get_user_model
    User = get_user_model()
    org_user_ids = OrganizationMembership.objects.filter(
        organization=org
    ).values_list('user_id', flat=True)
 
    logs_qs = AgentLog.objects.filter(
        user_id__in=org_user_ids
    ).select_related('user').order_by('-created_at')
 
    if device_id:
        logs_qs = logs_qs.filter(device_id=device_id)
    if hostname:
        logs_qs = logs_qs.filter(hostname__icontains=hostname)
 
    logs = logs_qs[:20]  # last 20 log shipments
 
    return Response({
        'logs': [{
            'id': l.id,
            'user': l.user.username,
            'device_id': l.device_id,
            'hostname': l.hostname,
            'platform': l.platform,
            'app_version': l.app_version,
            'trigger': l.trigger,
            'line_count': l.line_count,
            'created_at': l.created_at.isoformat(),
            'log_text': l.log_text,
        } for l in logs],
        'total': logs_qs.count(),
    })
 
 
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_agent_logs(request):
    """
    Request an on-demand log ship from a specific device.
    Sets a flag on the control endpoint that the agent polls.
    POST /api/agent/request-logs/
    Body: { "device_id": "xxx" }
    """
    from .models import AgentDevice
    from tracker.models import OrganizationMembership
 
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
 
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
 
    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': 'device_id required'}, status=400)
 
    # Set flag on device — agent will pick this up on next control poll
    updated = AgentDevice.objects.filter(device_id=device_id).update(
        log_requested=True
    )
 
    if not updated:
        return Response({'error': 'Device not found'}, status=404)
 
    return Response({'ok': True, 'message': 'Log request sent — agent will ship within 10s'})

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
    """
    Available verticals, with what each one changes.

    Shared by the signup form and MavOps admin so there is one source of truth
    for what picking a vertical does. `terminology` and `primary_integrations`
    let a caller preview the effect before committing to it.
    """
    from tracker.industry_categories import (
        INDUSTRY_TYPES, get_terminology, get_primary_integrations,
        get_task_types_for_industry,
    )

    return Response({
        'industries': [
            {
                'value': k,
                'label': v,
                'terminology': get_terminology(k),
                'primary_integrations': get_primary_integrations(k),
                'task_type_count': len(get_task_types_for_industry(k) or []),
            }
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
        zip_url = None
    else:
        download_url = f"{base}/TimeTracker-Windows-Setup.exe"
        zip_url = f"{base}/TimeTrackerAgent-{latest}.zip"

    return JsonResponse({
        "update_available": update_needed,
        "force": False,
        "latest_version": latest,
        "download_url": download_url,
        "zip_url": zip_url,
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