# tracker/utils.py
from __future__ import annotations

from datetime import datetime, timedelta, time as dt_time
from typing import Optional

from django.db.models import Q
from django.utils import timezone

from .models import (
    OrganizationSettings,
    KnownEntity,
    RawEvent,
    Block,
    Client,
    Task,
)

# --- add to tracker/utils.py ---
from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from django.db.models.functions import TruncHour



from django.db.models.functions import TruncHour




User = get_user_model()

def resolve_agent_user(request):
    """
    Resolve the Django user for agent calls using headers.
    Priority:
      1) X-Agent-User-Id (numeric)
      2) X-Agent-User (username)
    If not found and settings.AGENT_AUTO_PROVISION=True, create a user with that username.
    Otherwise raise AuthenticationFailed.
    """
    from django.conf import settings  # local import to avoid circulars

    # 1) numeric user id
    uid = (request.headers.get("X-Agent-User-Id") or "").strip()
    if uid.isdigit():
        try:
            return User.objects.get(id=int(uid))
        except User.DoesNotExist:
            raise AuthenticationFailed("X-Agent-User-Id not found")

    # 2) username
    uname = (request.headers.get("X-Agent-User") or "").strip()
    if not uname:
        raise AuthenticationFailed("Missing X-Agent-User")

    try:
        return User.objects.get(username=uname)
    except User.DoesNotExist:
        # Optional auto-provision (off by default)
        if getattr(settings, "AGENT_AUTO_PROVISION", False):
            u = User.objects.create_user(username=uname)
            u.set_unusable_password()
            u.save()
            return u
        raise AuthenticationFailed(f"User '{uname}' not found")


def get_org_or_default(request) -> Optional[OrganizationSettings]:
    """
    Return an OrganizationSettings to scope queries.
    Current simple strategy:
      1) If request.user is authenticated and their org can be inferred later, plug it here.
      2) Otherwise return the first OrganizationSettings row if it exists.
      3) Else None (unscoped).
    """
    try:
        return OrganizationSettings.objects.first()
    except Exception:
        return None


def resolve_client_from_known(org: Optional[OrganizationSettings], block: Block) -> Optional[str]:
    """
    Try to infer a client name for a Block using KnownEntity hints.
    Very lightweight: checks app_name, window_title, and url-like tokens.
    Returns a *client name* string if we can infer it, else None.
    """
    title = (block.window_title or "").lower()
    app = (block.app_name or "").lower()
    url = (block.url or "").lower()

    qs = KnownEntity.objects.all()
    if org:
        qs = qs.filter(Q(org=org) | Q(org__isnull=True))

    candidates = []
    for ke in qs:
        tokens = []
        # we treat name + aliases as tokens to look for
        if ke.name:
            tokens.append(ke.name.lower())
        for a in (ke.aliases or []):
            try:
                tokens.append(str(a).lower())
            except Exception:
                continue

        hit = False
        for t in tokens:
            if not t:
                continue
            if t in title or t in app or t in url:
                hit = True
                break

        if hit:
            # If this KnownEntity is linked to a Client, prefer that
            if ke.parent_client_id:
                try:
                    c = Client.objects.get(id=ke.parent_client_id)
                    candidates.append(c.name)
                    continue
                except Client.DoesNotExist:
                    pass
            candidates.append(ke.name)

    # Return the most specific (arbitrary: longest string)
    if candidates:
        return sorted(set(filter(None, candidates)), key=len, reverse=True)[0]

    return None


def infer_task_for_block(block: Block) -> str:
    """
    Lightweight task inference from window title / app name.
    """
    title = (block.window_title or "").lower()
    app = (block.app_name or "").lower()

    if "mail" in app or "gmail" in title or "outlook" in title:
        return "Email/Communication"
    if "calendar" in app or "zoom.us" in title or "meet.google" in (block.url or "").lower():
        return "Meetings"
    if "chrome" in app or "safari" in app or "firefox" in app:
        return "Research/Browsing"
    if "code" in app or "pycharm" in title or "vscode" in title or "github" in (block.url or ""):
        return "Development"
    if "sheets" in title or "excel" in title or "numbers" in title:
        return "Spreadsheets"
    if "docs" in title or "word" in title or "notion" in title:
        return "Docs/Writing"
    return "Uncategorized"

def compact_rawevents_into_blocks(
    user: Optional[str] = None,
    hostname: Optional[str] = None,
    org: Optional[OrganizationSettings] = None,
    *,
    since_minutes: int = 24 * 60,
) -> int:
    """
    Best-effort compactor that groups recent RawEvent rows into coarse hourly Blocks.
    One Block per (user_id, hostname, app_name, hour_bucket) if it doesn't already exist.
    Safe to call frequently; skips existing buckets.
    """
    now = timezone.now()
    since = now - timedelta(minutes=since_minutes)

    q = RawEvent.objects.filter(ts_utc__gte=since)
    if user:
        q = q.filter(user__username=user)
    if hostname:
        q = q.filter(hostname=hostname)
    if org:
        # Only apply if RawEvent has an org column in your schema
        try:
            q = q.filter(org=org)
        except Exception:
            pass

    created = 0

    # Bucket by hour/app; TruncHour keeps this DB-portable and clean
    rows = (
        q.annotate(hour_bucket=TruncHour("ts_utc"))
         .values("user_id", "hostname", "app_name", "hour_bucket")
         .distinct()
    )

    for r in rows:
        user_id = r["user_id"]
        host = r["hostname"] or "unknown"
        app_name = r["app_name"] or ""
        hour = r["hour_bucket"]
        if not hour:
            continue

        start = hour
        end = start + timedelta(hours=1)

        # Skip if a block already exists covering this bucket
        exists = Block.objects.filter(
            user_id=user_id,
            hostname=host,
            app_name=app_name,
            start__lte=start,
            end__gte=end,
        ).exists()
        if exists:
            continue

        try:
            Block.objects.create(
                user_id=user_id,
                hostname=host,
                app_name=app_name,
                window_title=app_name,
                url=None,
                start=start,
                end=end,
                category_hours={"Uncategorized": 1.0},  # placeholder
                client=None,
                task=None,
                # Pass org only if the field exists on your Block model
                **({"org": org} if hasattr(Block, "org") else {}),
            )
            created += 1
        except Exception:
            # Best-effort: ignore individual failures
            continue

    return created