# tracker/impersonation.py
"""
MavOps "View as" — a real identity swap, not a hint.

Why this lives in the auth layer
--------------------------------
The first version of view-as passed ``?org_id=&user_id=`` on every request and
each view had to *opt in* by calling ``get_request_org_override`` /
``get_request_user_override``.  Only ~49 endpoints ever did; the other several
hundred read ``request.user`` directly, so they quietly served the admin's own
data.  That is why the feature worked on some pages and not others.

Swapping the identity during authentication means ``request.user`` *is* the
target user for the whole request — so every view, permission class, serializer,
role check and org lookup is correct for free, with no per-view opt-in.

Contract
--------
The web client sends ``X-View-As-User: <user id or username>``.  It is honored
only when the *real* authenticated user is staff/superuser.  The header is
advisory input from the browser and is re-validated here on every request; it
never grants access the real user does not already have.
"""

import logging

from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)
User = get_user_model()

#: Header the web client sends. Django exposes it as HTTP_X_VIEW_AS_USER.
VIEW_AS_HEADER = "X-View-As-User"
_VIEW_AS_META = "HTTP_X_VIEW_AS_USER"

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: The admin console itself always runs as the real admin. localStorage is shared
#: across tabs, so without this an admin who starts a view-as in one tab would
#: have the header attached to their MavOps console in the other tab — and lock
#: themselves out of it, since the target user is not staff.
_NEVER_SWAP_PREFIXES = ("/api/mavops/", "/api/support/", "/api/auth/")


def _is_exempt(request):
    path = getattr(request, "path", "") or ""
    return path.startswith(_NEVER_SWAP_PREFIXES)


def _raw_target(request):
    """
    The requested target: header first, then a ``?view_as=`` query param.

    The query param exists only for transports that cannot set headers (server-
    sent events, plain <a> navigations). It goes through the identical staff
    gate below, so it grants nothing the header does not.
    """
    meta = getattr(request, "META", None) or {}
    raw = (meta.get(_VIEW_AS_META) or "").strip()
    if raw:
        return raw
    params = getattr(request, "GET", None)
    if params is not None:
        return (params.get("view_as") or "").strip()
    return ""


def _lookup(raw):
    """Resolve `raw` (numeric id or username) to a User, or None."""
    if raw.isdigit():
        return User.objects.filter(pk=int(raw)).first()
    return User.objects.filter(username=raw).first()


def _mark(request, effective_user, real_user):
    """
    Stamp the request so views/middleware can tell this is a view-as session.

    Set on both the DRF request and the underlying HttpRequest: DRF's Request
    proxies unknown attribute *reads* to the wrapped HttpRequest, but a plain
    ``setattr`` here only lands on whichever object we were handed.
    """
    for target in filter(None, (request, getattr(request, "_request", None))):
        try:
            target.is_view_as = True
            target.impersonator = real_user
            target.view_as_user = effective_user
        except AttributeError:
            pass


def resolve_view_as_user(request, real_user):
    """
    Return the user this request should run as.

    Returns ``real_user`` unchanged when no view-as is requested or when the
    request is not entitled to one.  Raises AuthenticationFailed only when a
    view-as was explicitly asked for and must be refused, so a stale header in
    a forgotten tab fails loudly instead of silently showing the admin's data.
    """
    raw = _raw_target(request)
    if not raw or _is_exempt(request):
        return real_user

    if not (real_user and real_user.is_authenticated):
        raise AuthenticationFailed("view_as_denied: not authenticated.")

    if not (real_user.is_staff or real_user.is_superuser):
        logger.warning(
            "[ViewAs] DENIED non-staff user %r attempted view-as %r",
            real_user.username, raw,
        )
        raise AuthenticationFailed("view_as_denied: staff access required.")

    target = _lookup(raw)
    if target is None:
        raise AuthenticationFailed(f"view_as_denied: no such user '{raw}'.")

    if target.pk == real_user.pk:
        return real_user

    if not target.is_active:
        raise AuthenticationFailed(
            f"view_as_denied: '{target.username}' is deactivated."
        )

    # No lateral escalation: only a superuser may step into a superuser's shoes.
    if target.is_superuser and not real_user.is_superuser:
        logger.warning(
            "[ViewAs] DENIED staff %r attempted view-as superuser %r",
            real_user.username, target.username,
        )
        raise AuthenticationFailed(
            "view_as_denied: cannot view as a superuser."
        )

    _mark(request, target, real_user)
    audit(request, target, real_user)
    return target


def audit(request, effective_user, real_user):
    """
    Log the swap. Reads are logged at debug; anything that can change state is
    logged at warning, because a write made under view-as is a real write to a
    customer's account and needs to be attributable to the admin who made it.
    """
    method = (getattr(request, "method", "") or "").upper()
    path = getattr(request, "path", "?")
    if method in _SAFE_METHODS:
        logger.debug(
            "[ViewAs] %s viewing as %s — %s %s",
            real_user.username, effective_user.username, method, path,
        )
    else:
        logger.warning(
            "[ViewAs] WRITE by %s acting as %s — %s %s",
            real_user.username, effective_user.username, method, path,
        )


def view_as_context(request):
    """Payload describing the active swap, for whoami. Empty dict when off."""
    if not getattr(request, "is_view_as", False):
        return {}
    real = getattr(request, "impersonator", None)
    if not real:
        return {}
    return {
        "active": True,
        "real_user_id": real.id,
        "real_username": real.username,
        "real_name": (f"{real.first_name} {real.last_name}".strip() or real.username),
    }


__all__ = [
    "VIEW_AS_HEADER",
    "resolve_view_as_user",
    "view_as_context",
    "audit",
]
