# tracker/auth.py
from typing import Optional
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
from .models import AgentDevice
from tracker.models import AuthToken
from django.utils import timezone
from datetime import timedelta

User = get_user_model()


class AgentKeyAuthentication(BaseAuthentication):
    """
    Authenticates requests from desktop agents using device API keys.
    
    Accepts:
    - X-Agent-Key header
    - Authorization: DeviceKey <key>
    - Authorization: Bearer <key> (also checks AgentDevice first)
    """
    def authenticate(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        key = None
        auth_source = None
        
        # Priority 1: X-Agent-Key header
        key = (request.headers.get("X-Agent-Key") or "").strip()
        if key:
            auth_source = "X-Agent-Key"
        
        # Priority 2: Authorization header
        if not key:
            auth = (request.headers.get("Authorization") or "").strip()
            
            if auth.startswith("DeviceKey "):
                key = auth[len("DeviceKey "):].strip()
                auth_source = "DeviceKey"
            elif auth.startswith("Bearer "):
                # Check if this Bearer token is actually a device key
                key = auth[len("Bearer "):].strip()
                auth_source = "Bearer-as-DeviceKey"
        
        if not key:
            return None  # Let other authenticators try
        
        # Look up in AgentDevice table
        try:
            dev: AgentDevice = (
                AgentDevice.objects.select_related("user")
                .get(api_key=key, is_active=True)
            )
            logger.info(f"[AgentKeyAuth] Found device via {auth_source}: {dev.hostname}")
        except AgentDevice.DoesNotExist:
            # If it was Bearer prefix and not found in AgentDevice,
            # return None so BearerTokenAuthentication can try AuthToken table
            if auth_source == "Bearer-as-DeviceKey":
                logger.debug(f"[AgentKeyAuth] Bearer token not in AgentDevice, letting BearerTokenAuth try")
                return None
            # For DeviceKey/X-Agent-Key, also return None to let other auth try
            return None
        
        if not dev.user_id:
            raise AuthenticationFailed("Unlinked device")
        
        # Touch last_seen_at
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


class BearerTokenAuthentication(BaseAuthentication):
    """
    Authenticates using Bearer tokens stored in AuthToken table.
    Used for web app authentication (login tokens).
    
    Note: AgentKeyAuthentication checks Bearer tokens against AgentDevice FIRST,
    so this only handles tokens that are actual AuthTokens (from web login).
    """
    keyword = 'Bearer'
    
    def authenticate(self, request):
        import logging
        logger = logging.getLogger(__name__)
        
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        
        if not auth_header.startswith(f'{self.keyword} '):
            return None
        
        token = auth_header[len(self.keyword) + 1:].strip()
        
        if not token:
            return None
        
        try:
            auth_token = AuthToken.objects.select_related('user').get(token=token)
            logger.info(f"[BearerAuth] Found AuthToken for user: {auth_token.user.username}")
            
            if not auth_token.is_valid():
                logger.info("[BearerAuth] Token expired!")
                raise AuthenticationFailed('Token expired')
            
            return (auth_token.user, auth_token)
            
        except AuthToken.DoesNotExist:
            # Token not found in AuthToken table
            # (AgentKeyAuth should have already checked AgentDevice)
            logger.debug(f"[BearerAuth] Token not found in AuthToken table")
            return None
    
    def authenticate_header(self, request):
        return self.keyword


__all__ = ["AgentKeyAuthentication", "AgentKeyPermission", "NoAuth", "BearerTokenAuthentication"]