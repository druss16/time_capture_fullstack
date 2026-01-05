# tracker/auth.py
from typing import Optional
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
from .models import AgentDevice
from tracker.models import AuthToken  # ✅ Add this import


from django.utils import timezone
from datetime import timedelta


User = get_user_model()


# tracker/auth.py
class AgentKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        key = (request.headers.get("X-Agent-Key") or "").strip()
        if not key:
            auth = (request.headers.get("Authorization") or "").strip()
            if auth.startswith("DeviceKey "):
                key = auth[len("DeviceKey "):].strip()
            # ✅ REMOVED: Bearer fallback (conflicts with BearerTokenAuthentication)

        if not key:
            return None  # allow other authenticators to try

        try:
            dev: AgentDevice = (
                AgentDevice.objects.select_related("user")
                .get(api_key=key, is_active=True)
            )
        except AgentDevice.DoesNotExist:
            return None  # ✅ CHANGED: Return None instead of raising (let other auth try)

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


# Add this class to tracker/auth.py

class BearerTokenAuthentication(BaseAuthentication):
    """
    Custom auth that accepts: Authorization: Bearer <token>
    Looks up tokens in tracker_authtoken table.
    """
    keyword = 'Bearer'
    
    def authenticate(self, request):
        from .models import AuthToken  # Import here to avoid circular imports
        
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if not auth_header.startswith(f'{self.keyword} '):
            return None  # Let other auth backends try
        
        token = auth_header[len(self.keyword) + 1:].strip()
        
        if not token:
            return None
        
        try:
            auth_token = AuthToken.objects.select_related('user').get(token=token)
            
            # Check if valid (not expired)
            if not auth_token.is_valid():
                raise AuthenticationFailed('Token expired')
            
            return (auth_token.user, auth_token)
            
        except AuthToken.DoesNotExist:
            # Don't raise - let other auth backends try
            return None
    
    def authenticate_header(self, request):
        return self.keyword


__all__ = ["AgentKeyAuthentication", "AgentKeyPermission", "NoAuth", "BearerTokenAuthentication"]