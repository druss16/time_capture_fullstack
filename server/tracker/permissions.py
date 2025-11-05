# tracker/permissions.py
import os
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, SAFE_METHODS


# tracker/permissions.py
import os
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, SAFE_METHODS

class NoAuth(BaseAuthentication):
    def authenticate(self, request):
        return None

# permissions.py
import os
from django.conf import settings
from rest_framework.permissions import BasePermission

class AgentKeyPermission(BasePermission):
    """
    Accept agent API key from:
      - X-Agent-Key
      - Agent-Key
      - X-Api-Key
      - X-AgentToken
      - X-Auth-Token
      - Authorization: Bearer <key>
      - ?key=<key>    (diagnostic fallback)
    """
    message = "Missing or invalid agent key."

    def has_permission(self, request, view):
        # Single canonical source of truth
        expected = (getattr(settings, "AGENT_API_KEY", None) 
                    or os.getenv("AGENT_API_KEY", "")).strip()
        if not expected:
            return False

        # 1) Direct key headers
        for h in ("X-Agent-Key", "Agent-Key", "X-Api-Key", "X-AgentToken", "X-Auth-Token"):
            cand = (request.headers.get(h) or "").strip()
            if cand == expected:
                return True

        # 2) Authorization: Bearer <key>   (case/space tolerant)
        auth = (request.headers.get("Authorization") or "").strip()
        if auth:
            parts = auth.split()
            if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() == expected:
                return True

        # 3) Query param (last resort)
        qp = (request.query_params.get("key") or "").strip()
        if qp == expected:
            return True

        return False
class PermUI(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)

class PermUI(BasePermission):
    """
    UI/API endpoints:
      - Allow GET/HEAD/OPTIONS for anyone (so the web UI can load).
      - Require authenticated user for mutating methods (POST/PUT/PATCH/DELETE).
    Swap to IsAuthenticated if you want everything locked down.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated)