import os
from rest_framework.permissions import BasePermission

class AgentKeyPermission(BasePermission):
    """
    Allow only when the correct API key is supplied.
    Checks (in order):
      - 'X-Agent-Key: <key>'
      - 'Authorization: Bearer <key>'
    """
    def has_permission(self, request, view):
        expected = os.getenv("AGENT_API_KEY") or ""
        if not expected:
            return False
        # header variants
        h = request.headers.get("X-Agent-Key") or ""
        if h and h == expected:
            return True
        auth = request.headers.get("Authorization") or ""
        if auth.startswith("Bearer ") and auth[7:] == expected:
            return True
        return False
