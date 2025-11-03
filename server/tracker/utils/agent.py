# tracker/utils/agent.py
from django.contrib.auth.models import User, Group
from django.utils import timezone
from typing import Tuple
from tracker.models import AgentSession

def resolve_agent_user(request) -> Tuple[User, str]:
    """
    Resolve (or auto-provision) the agent-side user + hostname from:
      1) Cookies set by /api/agents/hello/  (mavops_username, mavops_host)
      2) Identity headers (X-Agent-User, X-Agent-Host)
      3) Auth session (request.user) as a fallback
    Ensures the user is in the 'Time Agents' group and updates AgentSession.
    Returns: (user, hostname)
    """
    cookies = request.COOKIES or {}
    headers = request.headers or {}

    username = (
        (cookies.get("mavops_username") or "").strip()
        or (headers.get("X-Agent-User") or "").strip()
        or (request.user.username if getattr(request, "user", None) and request.user.is_authenticated else "")
        or "unknown"
    )
    host = (
        (cookies.get("mavops_host") or "").strip()
        or (headers.get("X-Agent-Host") or "").strip()
        or (request.get_host().split(":")[0] if hasattr(request, "get_host") else "")
        or "unknown"
    )

    # Ensure group + user
    grp, _ = Group.objects.get_or_create(name="Time Agents")
    user, created = User.objects.get_or_create(username=username, defaults={"is_active": True})
    if created:
        user.set_unusable_password()
        user.save()
    if not user.groups.filter(id=grp.id).exists():
        user.groups.add(grp)

    # Track session / heartbeat
    AgentSession.objects.update_or_create(
        user=user,
        hostname=host,
        defaults={
            "last_seen": timezone.now(),
            "last_ip": request.META.get("REMOTE_ADDR", ""),
        },
    )
    return user, host