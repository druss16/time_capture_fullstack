# tracker/utils/utils_main.py
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db.models.functions import TruncHour
from django.utils import timezone

from ..models import (  # ← note the two dots to reach tracker/models.py
    OrganizationSettings,
    KnownEntity,
    RawEvent,
    Block,
    Client,
    Task,
)

User = get_user_model()

# ---------------- Core helpers ----------------

def resolve_agent_user(request):
    username = (request.headers.get("X-Agent-User") or "").strip()
    if not username:
        username = (request.data.get("user") if isinstance(request.data, dict) else "") or ""
        username = str(username).strip()

    if not username:
        username = "unknown-agent"

    user, created = User.objects.get_or_create(
        username=username,
        defaults={"is_active": True, "email": ""},
    )
    if created:
        user.set_unusable_password()
        user.save()
    return user

def get_org_or_default(request) -> Optional[OrganizationSettings]:
    try:
        return OrganizationSettings.objects.first()
    except Exception:
        return None

def resolve_client_from_known(org: Optional[OrganizationSettings], block: Block) -> Optional[str]:
    title = (block.window_title or "").lower()
    app = (block.app_name or "").lower()
    url = (block.url or "").lower()

    qs = KnownEntity.objects.all()
    if org:
        qs = qs.filter(Q(org=org) | Q(org__isnull=True))

    candidates = []
    for ke in qs:
        tokens = []
        if ke.name:
            tokens.append(ke.name.lower())
        for a in (ke.aliases or []):
            try:
                tokens.append(str(a).lower())
            except Exception:
                continue

        if any(t and (t in title or t in app or t in url) for t in tokens):
            if ke.parent_client_id:
                try:
                    c = Client.objects.get(id=ke.parent_client_id)
                    candidates.append(c.name)
                    continue
                except Client.DoesNotExist:
                    pass
            candidates.append(ke.name)

    if candidates:
        return sorted(set(filter(None, candidates)), key=len, reverse=True)[0]
    return None

def infer_task_for_block(block: Block) -> str:
    title = (block.window_title or "").lower()
    app = (block.app_name or "").lower()
    url = (block.url or "").lower()

    if "mail" in app or "gmail" in title or "outlook" in title:
        return "Email/Communication"
    if "calendar" in app or "zoom.us" in title or "meet.google" in url:
        return "Meetings"
    if any(b in app for b in ("chrome", "safari", "firefox")):
        return "Research/Browsing"
    if "code" in app or "pycharm" in title or "vscode" in title or "github" in url:
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
    now = timezone.now()
    since = now - timedelta(minutes=since_minutes)

    q = RawEvent.objects.filter(ts_utc__gte=since)
    if user:
        q = q.filter(user__username=user)
    if hostname:
        q = q.filter(hostname=hostname)
    if org:
        try:
            q = q.filter(org=org)
        except Exception:
            pass

    created = 0
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
                category_hours={"Uncategorized": 1.0},
                client=None,
                task=None,
                **({"org": org} if hasattr(Block, "org") else {}),
            )
            created += 1
        except Exception:
            continue

    return created

def _client_ip(request) -> str:
    """
    Best-effort client IP resolution. Uses X-Forwarded-For if behind a trusted proxy.
    """
    use_xff = getattr(settings, "SECURE_PROXY_SSL_HEADER", None) or getattr(settings, "USE_X_FORWARDED_HOST", False)
    if use_xff:
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            return xff.split(",")[0].strip()

    ip = request.META.get("REMOTE_ADDR", "")
    if ip:
        return ip.strip()
    return "0.0.0.0"