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

class AgentKeyPermission(BasePermission):
    """
    Accept key from many places:
      - X-Agent-Key
      - Agent-Key
      - X-Api-Key
      - X-AgentToken
      - X-Auth-Token
      - Authorization: Bearer <key>
      - ?key=<key>  (last resort for debugging)
    And compare after stripping whitespace.
    """
    message = "Missing or invalid agent key."

    def has_permission(self, request, view):
        expected = (getattr(settings, "AGENT_KEY", None) 
                    or os.getenv("AGENT_API_KEY", "")).strip()
        if not expected:
            return False

        # Try multiple header names
        cand = (
            request.headers.get("X-Agent-Key")
            or request.headers.get("Agent-Key")
            or request.headers.get("X-Api-Key")
            or request.headers.get("X-AgentToken")
            or request.headers.get("X-Auth-Token")
            or ""
        ).strip()

        if cand and cand == expected:
            return True

        # Authorization: Bearer <key>
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.startswith("Bearer "):
            if auth[7:].strip() == expected:
                return True

        # Query param fallback (?key=...) — useful for quick diagnostics
        qp = (request.query_params.get("key") or "").strip()
        if qp and qp == expected:
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