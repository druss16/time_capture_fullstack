# tracker/auth.py
import os, secrets
from django.conf import settings
from rest_framework import authentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import AnonymousUser

class NoAuth(authentication.BaseAuthentication):
    def authenticate(self, request):
        return (AnonymousUser(), None)

class AgentKeyPermission(BasePermission):
    message = "Missing or invalid X-Agent-Key."

    def has_permission(self, request, view):
        expected = (
            getattr(settings, "AGENT_KEY", "")
            or os.getenv("AGENT_KEY", "")
            or os.getenv("AGENT_API_KEY", "")
        ).strip()

        provided = (
            request.headers.get("X-Agent-Key")
            or request.META.get("HTTP_X_AGENT_KEY")
            or ""
        ).strip()

        if not expected:
            raise AuthenticationFailed("Server agent key is not configured.")
        if not provided:
            raise AuthenticationFailed("Missing X-Agent-Key.")
        if not secrets.compare_digest(provided, expected):
            raise AuthenticationFailed("Invalid X-Agent-Key.")

        return True