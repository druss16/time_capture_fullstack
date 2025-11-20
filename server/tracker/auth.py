# tracker/auth.py
from typing import Optional
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
from .models import AgentDevice
from tracker.models import AuthToken  # ✅ Add this import


User = get_user_model()


# tracker/auth.py
class AgentKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        key = (request.headers.get("X-Agent-Key") or "").strip()
        if not key:
            auth = (request.headers.get("Authorization") or "").strip()
            if auth.startswith("DeviceKey "):
                key = auth[len("DeviceKey "):].strip()
            elif auth.startswith("Bearer "):  # legacy fallback
                key = auth[len("Bearer "):].strip()

        if not key:
            return None  # allow other authenticators to try

        try:
            dev: AgentDevice = (
                AgentDevice.objects.select_related("user")
                .get(api_key=key, is_active=True)
            )
        except AgentDevice.DoesNotExist:
            raise AuthenticationFailed("Invalid agent key")

        if not dev.user_id:
            raise AuthenticationFailed("Unlinked device")

        # (optional) touch last_seen_at
        from django.utils import timezone
        AgentDevice.objects.filter(pk=dev.pk).update(last_seen_at=timezone.now())

        request.agent_device = dev
        return (dev.user, None)


class AgentKeyPermission(BasePermission):
    """
    Requires that AgentKeyAuthentication succeeded and attached request.agent_device.
    """
    message = "Agent device is not authenticated."

    def has_permission(self, request, view):
        return bool(getattr(request, "agent_device", None))


class NoAuth(BaseAuthentication):
    """
    Explicitly opts this endpoint out of SessionAuthentication/CSRF by not authenticating.
    Returning None tells DRF to continue to other authenticators (if any).
    """
    def authenticate(self, request):
        return None

# Add to tracker/auth.py
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from tracker.models import AuthToken

class BearerTokenAuthentication(BaseAuthentication):
    """
    Token authentication for browsers that block cookies.
    """
    def authenticate(self, request):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return None  # Not a bearer token, try next auth method
        
        token = auth_header.replace('Bearer ', '', 1).strip()
        
        try:
            auth_token = AuthToken.objects.select_related('user').get(token=token)
            if auth_token.is_valid():
                return (auth_token.user, None)
        except AuthToken.DoesNotExist:
            pass
        
        return None  # Invalid token, try next auth method


__all__ = ["AgentKeyAuthentication", "AgentKeyPermission", "NoAuth", "BearerTokenAuthentication"]