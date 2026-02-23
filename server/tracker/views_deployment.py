"""
Deployment views for MDM/Intune support.

Add to server/tracker/views_deployment.py
Wire up in urls.py:
    path('api/deploy/', include('tracker.urls_deployment')),
"""
import json
import secrets
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.utils import timezone
from django.db.models import Q

from .models import (
    Organization,
    OrganizationMembership,
    AgentDevice,
    OrgDeploymentToken,
)


# ─────────────────────────────────────────────
# Admin endpoints (require org admin auth)
# ─────────────────────────────────────────────

def _get_admin_org(request):
    """Get the organization for the authenticated admin user."""
    if not request.user.is_authenticated:
        return None, JsonResponse({"error": "Authentication required"}, status=401)

    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role__in=['owner', 'admin', 'manager']
    ).select_related('organization').first()

    if not membership:
        return None, JsonResponse({"error": "Admin access required"}, status=403)

    return membership.organization, None


@require_POST
def create_deployment_token(request):
    """Create a new org deployment token for MDM distribution."""
    org, error = _get_admin_org(request)
    if error:
        return error

    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        body = {}

    token = OrgDeploymentToken.objects.create(
        organization=org,
        created_by=request.user,
        notes=body.get('notes', ''),
        max_devices=body.get('max_devices'),
        expires_at=body.get('expires_at'),
    )

    return JsonResponse({
        "id": token.id,
        "token": token.token,
        "organization": org.name,
        "created_at": token.created_at.isoformat(),
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "max_devices": token.max_devices,
        "notes": token.notes,
    }, status=201)


@require_GET
def list_deployment_tokens(request):
    """List all deployment tokens for the admin's org."""
    org, error = _get_admin_org(request)
    if error:
        return error

    tokens = OrgDeploymentToken.objects.filter(organization=org)
    data = []
    for t in tokens:
        data.append({
            "id": t.id,
            "token": t.token,
            "is_active": t.is_active,
            "is_valid": t.is_valid,
            "created_at": t.created_at.isoformat(),
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "max_devices": t.max_devices,
            "devices_claimed": t.devices_claimed,
            "notes": t.notes,
            "created_by": t.created_by.get_full_name() if t.created_by else None,
        })

    return JsonResponse({"tokens": data})


@require_POST
def revoke_deployment_token(request, token_id):
    """Revoke a deployment token. Existing devices keep working."""
    org, error = _get_admin_org(request)
    if error:
        return error

    try:
        token = OrgDeploymentToken.objects.get(id=token_id, organization=org)
    except OrgDeploymentToken.DoesNotExist:
        return JsonResponse({"error": "Token not found"}, status=404)

    token.is_active = False
    token.save(update_fields=['is_active'])

    return JsonResponse({"ok": True, "token": token.token, "status": "revoked"})


# ─────────────────────────────────────────────
# Agent endpoints (no auth — token IS the auth)
# ─────────────────────────────────────────────

def _generate_device_key():
    """Generate a secure per-device API key."""
    return secrets.token_urlsafe(48)


def _match_user_by_email(org, os_username):
    """
    Try to match os_username to an org member.

    On AAD-joined machines, os_username is the UPN (e.g., jsmith@cpafirm.com).
    We also try common variations:
      - Exact email match
      - Username part before @ (in case stored differently)
      - Case-insensitive match
    """
    email = os_username.strip().lower()

    # Direct email match
    membership = OrganizationMembership.objects.filter(
        organization=org,
        user__email__iexact=email
    ).select_related('user').first()

    if membership:
        return membership

    # Try matching just the username part (e.g., "jsmith" from "jsmith@cpafirm.com")
    if '@' in email:
        username_part = email.split('@')[0]
        membership = OrganizationMembership.objects.filter(
            organization=org
        ).filter(
            Q(user__email__istartswith=username_part + '@') |
            Q(user__username__iexact=username_part) |
            Q(user__username__iexact=email)
        ).select_related('user').first()

        if membership:
            return membership

    # Try matching by username field directly
    membership = OrganizationMembership.objects.filter(
        organization=org,
        user__username__iexact=email
    ).select_related('user').first()

    return membership  # May be None


@csrf_exempt
@require_POST
def deploy_claim(request):
    """
    Agent calls this on first boot with an org_token.
    Auto-matches the Windows/AD username to a user profile.
    Returns device API key on success, or member list for manual pick.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    org_token_str = body.get('org_token', '').strip()
    hostname = body.get('hostname', '')
    os_username = body.get('os_username', '')
    platform_str = body.get('platform', 'Windows')
    version = body.get('version', '')

    if not org_token_str:
        return JsonResponse({"status": "error", "message": "org_token required"}, status=400)

    # Validate token
    try:
        token = OrgDeploymentToken.objects.select_related('organization').get(
            token=org_token_str
        )
    except OrgDeploymentToken.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Invalid token"}, status=404)

    if not token.is_valid:
        reasons = []
        if not token.is_active:
            reasons.append("Token has been revoked")
        if token.expires_at and timezone.now() > token.expires_at:
            reasons.append("Token has expired")
        if token.max_devices and token.devices_claimed >= token.max_devices:
            reasons.append("Device limit reached")
        return JsonResponse({
            "status": "error",
            "message": "; ".join(reasons) or "Token is no longer valid"
        }, status=403)

    org = token.organization

    # Check if this hostname is already registered for this org
    existing_device = Device.objects.filter(
        organization=org,
        hostname=hostname
    ).first()
    if existing_device and existing_device.api_key:
        # Already claimed — return existing credentials
        return JsonResponse({
            "status": "matched",
            "api_key": existing_device.api_key,
            "device_id": str(existing_device.id),
            "user_id": existing_device.user_id,
            "user_name": existing_device.user.get_full_name() if existing_device.user else None,
            "already_registered": True,
        })

    # Try auto-match by email
    membership = _match_user_by_email(org, os_username)

    if membership:
        # Auto-matched! Create device and return key
        device_key = _generate_device_key()
        device = AgentDevice.objects.create(
            user=membership.user,
            organization=org,
            hostname=hostname,
            platform=platform_str,
            app_version=version,
            api_key=device_key,
            os_username=os_username,
            claimed_via_token=token,
            auto_matched=True,
        )
        token.claim()

        return JsonResponse({
            "status": "matched",
            "api_key": device_key,
            "device_id": str(device.id),
            "user_id": membership.user.id,
            "user_name": membership.user.get_full_name(),
        })

    # No match — return member list for picker
    members = OrganizationMembership.objects.filter(
        organization=org
    ).select_related('user').order_by('user__first_name', 'user__last_name')

    member_list = []
    for m in members:
        member_list.append({
            "id": m.user.id,
            "name": m.user.get_full_name() or m.user.username,
            "email": m.user.email,
        })

    return JsonResponse({
        "status": "pick_user",
        "message": f"Could not auto-match '{os_username}' to a user. Please select your name.",
        "members": member_list,
    })


@csrf_exempt
@require_POST
def deploy_confirm_user(request):
    """
    After the agent shows a picker, the user selects their name.
    This confirms the match and creates the device.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

    org_token_str = body.get('org_token', '').strip()
    hostname = body.get('hostname', '')
    os_username = body.get('os_username', '')
    platform_str = body.get('platform', 'Windows')
    version = body.get('version', '')
    user_id = body.get('user_id')

    if not org_token_str or not user_id:
        return JsonResponse({
            "status": "error",
            "message": "org_token and user_id required"
        }, status=400)

    # Validate token
    try:
        token = OrgDeploymentToken.objects.select_related('organization').get(
            token=org_token_str
        )
    except OrgDeploymentToken.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Invalid token"}, status=404)

    if not token.is_valid:
        return JsonResponse({
            "status": "error",
            "message": "Token is no longer valid"
        }, status=403)

    org = token.organization

    # Verify user is a member of this org
    try:
        membership = OrganizationMembership.objects.select_related('user').get(
            organization=org,
            user_id=user_id
        )
    except OrganizationMembership.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "User is not a member of this organization"
        }, status=404)

    # Check for existing device
    existing_device = AgentDevice.objects.filter(
        organization=org,
        hostname=hostname
    ).first()
    if existing_device:
        # Update existing device with new user
        existing_device.user = membership.user
        existing_device.os_username = os_username
        existing_device.auto_matched = False
        existing_device.claimed_via_token = token
        existing_device.save()
        device_key = existing_device.api_key
        device = existing_device
    else:
        # Create new device
        device_key = _generate_device_key()
        device = AgentDevice.objects.create(
            user=membership.user,
            organization=org,
            hostname=hostname,
            platform=platform_str,
            app_version=version,
            api_key=device_key,
            os_username=os_username,
            claimed_via_token=token,
            auto_matched=False,
        )
        token.claim()

    return JsonResponse({
        "status": "matched",
        "api_key": device_key,
        "device_id": str(device.id),
        "user_id": membership.user.id,
        "user_name": membership.user.get_full_name(),
    })