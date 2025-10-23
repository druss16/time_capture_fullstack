import os
from rest_framework.permissions import BasePermission
from django.conf import settings


class AgentKeyPermission(BasePermission):
    """
    Authorize incoming agent requests using a static API key.

    The key is read from settings.AGENT_KEY (which should come from .env),
    and can be sent using any of these headers:
        Agent-Key: <key>
        X-Agent-Key: <key>
        Authorization: Bearer <key>
    """

    def has_permission(self, request, view):
        expected = getattr(settings, "AGENT_KEY", None) or os.getenv("AGENT_API_KEY", "")
        if not expected:
            return False

        # allow multiple header names
        key = (
            request.headers.get("Agent-Key")
            or request.headers.get("X-Agent-Key")
            or ""
        )

        if key == expected:
            return True

        auth = request.headers.get("Authorization") or ""
        if auth.startswith("Bearer ") and auth[7:] == expected:
            return True

        return False
