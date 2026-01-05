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
    keyword = 'Bearer'
    
    def authenticate(self, request):
        from .models import AuthToken
        import logging
        logger = logging.getLogger(__name__)
        
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        logger.info(f"[BearerAuth] Header: {auth_header[:50] if auth_header else 'NONE'}")
        
        if not auth_header.startswith(f'{self.keyword} '):
            logger.info("[BearerAuth] No Bearer prefix, skipping")
            return None
        
        token = auth_header[len(self.keyword) + 1:].strip()
        logger.info(f"[BearerAuth] Token: {token[:20]}...")
        
        if not token:
            return None
        
        try:
            auth_token = AuthToken.objects.select_related('user').get(token=token)
            logger.info(f"[BearerAuth] Found token for user: {auth_token.user.username}")
            
            if not auth_token.is_valid():
                logger.info("[BearerAuth] Token expired!")
                raise AuthenticationFailed('Token expired')
            
            logger.info(f"[BearerAuth] SUCCESS - authenticated {auth_token.user.username}")
            return (auth_token.user, auth_token)
            
        except AuthToken.DoesNotExist:
            logger.info(f"[BearerAuth] Token not found in DB")
            return None
    
    def authenticate_header(self, request):
        return self.keyword

__all__ = ["AgentKeyAuthentication", "AgentKeyPermission", "NoAuth", "BearerTokenAuthentication"]