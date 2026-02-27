"""
Deployment views for MDM/Intune support.
PATCHED: deploy_claim now checks DeviceProvisioningMap before falling back to manual picker.
"""
import json
import uuid
import secrets
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.db.models import Q
from django.db import transaction
from django.contrib.auth import get_user_model

from .models import (
    Organization,
    OrganizationMembership,
    AgentDevice,
    OrgDeploymentToken,
    DeviceProvisioningMap,
    BillingRate,
    EmployeeCostRate,
)

User = get_user_model()
logger = logging.getLogger(__name__)


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

@csrf_exempt
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


@csrf_exempt
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


@csrf_exempt
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
    return secrets.token_hex(16)


def _match_user_by_email(org, os_username):
    """
    Try to match os_username to an org member.
    On AAD-joined machines, os_username is the UPN (e.g., jsmith@cpafirm.com).
    """
    email = os_username.strip().lower()

    # Direct email match
    membership = OrganizationMembership.objects.filter(
        organization=org,
        user__email__iexact=email
    ).select_related('user').first()

    if membership:
        return membership

    # Try matching just the username part
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

    return membership


def _match_via_provisioning_map(org, hostname, os_username):
    """
    Check DeviceProvisioningMap for a pre-provisioned hostname or windows_username match.
    
    Returns (DeviceProvisioningMap, match_method) or (None, None).
    """
    # Priority 1: Hostname match (most reliable from Intune/AD exports)
    if hostname:
        prov = DeviceProvisioningMap.objects.filter(
            organization=org,
            machine_hostname__iexact=hostname.strip(),
            status='pending',
        ).first()
        if prov:
            return prov, 'hostname'

    # Priority 2: Windows username match
    if os_username:
        # Try exact match first
        prov = DeviceProvisioningMap.objects.filter(
            organization=org,
            windows_username__iexact=os_username.strip(),
            status='pending',
        ).first()
        if prov:
            return prov, 'windows_username'

        # Try matching just the username part (strip DOMAIN\ prefix)
        clean_username = os_username.strip()
        if '\\' in clean_username:
            clean_username = clean_username.split('\\')[-1]
        
        prov = DeviceProvisioningMap.objects.filter(
            organization=org,
            status='pending',
        ).filter(
            Q(windows_username__iexact=clean_username) |
            Q(email__istartswith=clean_username + '@')
        ).first()
        if prov:
            return prov, 'windows_username'

    return None, None


def _pair_from_provisioning_map(org, prov, match_method, hostname, os_username,
                                 platform_str, version, token):
    """
    Given a matched DeviceProvisioningMap entry, create or find the user,
    create the AgentDevice, and update the provisioning map.
    
    Returns (device, user) tuple.
    """
    email = prov.email.lower().strip()
    display_name = prov.display_name or ''

    # Get or create user
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            'username': email.split('@')[0],
            'first_name': display_name.split(' ')[0] if display_name else '',
            'last_name': ' '.join(display_name.split(' ')[1:]) if display_name else '',
            'is_active': True,
        }
    )
    if created:
        user.set_unusable_password()
        user.save()
        logger.info(f"Created user {email} for org {org.slug} via provisioning map")

    # Ensure membership
    membership, _ = OrganizationMembership.objects.get_or_create(
        user=user,
        organization=org,
        defaults={'role': prov.role or 'member'}
    )

    # Set billing rate if provided
    if prov.billing_rate:
        BillingRate.objects.get_or_create(
            org=org, user=user, client=None, task_type=None,
            effective_date=timezone.now().date(),
            defaults={'rate': prov.billing_rate}
        )

    # Set cost rate if provided
    if prov.cost_rate:
        EmployeeCostRate.objects.get_or_create(
            organization=org, user=user,
            effective_date=timezone.now().date(),
            defaults={'cost_rate': prov.cost_rate}
        )

    # Create device
    device_key = _generate_device_key()
    device = AgentDevice.objects.create(
        user=user,
        device_id=str(uuid.uuid4()),
        hostname=hostname,
        platform=platform_str,
        app_version=version,
        api_key=device_key,
        os_username=os_username,
        is_active=True,
        last_seen_at=timezone.now(),
        claimed_via_token=token,
        auto_matched=True,
    )

    # Update provisioning map
    prov.mark_paired(device, user, method=match_method)

    return device, user


@csrf_exempt
@require_POST
def deploy_claim(request):
    """
    Agent calls this on first boot with an org_token.
    
    Match priority:
    1. Existing device (already registered) → return existing credentials
    2. Email match via os_username → OrganizationMembership lookup
    3. Provisioning map match via hostname → DeviceProvisioningMap lookup
    4. Provisioning map match via windows_username → DeviceProvisioningMap lookup
    5. No match → return member list for manual picker
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

    # ─── Validate token ───
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

    # ─── Step 1: Check if this hostname is already registered ───
    existing_device = AgentDevice.objects.filter(
        hostname=hostname,
        user__memberships__organization=org
    ).select_related('user').first()

    if existing_device and existing_device.api_key:
        return JsonResponse({
            "status": "matched",
            "api_key": existing_device.api_key,
            "device_id": str(existing_device.id),
            "user_id": existing_device.user_id,
            "user_name": existing_device.user.get_full_name() if existing_device.user else None,
            "already_registered": True,
        })

    # ─── Step 2: Try email match via os_username (existing logic) ───
    membership = _match_user_by_email(org, os_username)

    if membership:
        device_key = _generate_device_key()
        device = AgentDevice.objects.create(
            user=membership.user,
            device_id=str(uuid.uuid4()),
            hostname=hostname,
            platform=platform_str,
            app_version=version,
            api_key=device_key,
            os_username=os_username,
            is_active=True,
            last_seen_at=timezone.now(),
            claimed_via_token=token,
            auto_matched=True,
        )
        token.claim()

        # Also update provisioning map if one exists for this hostname
        prov = DeviceProvisioningMap.objects.filter(
            organization=org,
            machine_hostname__iexact=hostname,
            status='pending',
        ).first()
        if prov:
            prov.mark_paired(device, membership.user, method='email_match')

        logger.info(
            f"deploy_claim: email match {os_username} → {membership.user.email} "
            f"(org={org.slug})"
        )

        return JsonResponse({
            "status": "matched",
            "api_key": device_key,
            "device_id": str(device.id),
            "user_id": membership.user.id,
            "user_name": membership.user.get_full_name(),
        })

    # ─── Step 3: Try provisioning map (hostname then windows_username) ───
    prov, match_method = _match_via_provisioning_map(org, hostname, os_username)

    if prov:
        try:
            with transaction.atomic():
                device, user = _pair_from_provisioning_map(
                    org, prov, match_method, hostname, os_username,
                    platform_str, version, token
                )
                token.claim()

            logger.info(
                f"deploy_claim: provisioning map match {hostname} → {user.email} "
                f"(method={match_method}, org={org.slug})"
            )

            return JsonResponse({
                "status": "matched",
                "api_key": device.api_key,
                "device_id": str(device.id),
                "user_id": user.id,
                "user_name": user.get_full_name(),
                "match_method": match_method,
            })
        except Exception as e:
            logger.exception(
                f"deploy_claim: provisioning map pair failed for {hostname}, "
                f"org={org.slug}: {e}"
            )
            prov.mark_failed(str(e))
            # Fall through to manual picker

    # ─── Step 4: No match — return member list for manual picker ───
    logger.info(
        f"deploy_claim: no match for hostname={hostname}, os_user={os_username}, "
        f"org={org.slug} — returning picker"
    )

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

    # Check for existing device by hostname in this org
    existing_device = AgentDevice.objects.filter(
        hostname=hostname,
        user__memberships__organization=org
    ).select_related('user').first()

    if existing_device:
        existing_device.user = membership.user
        existing_device.os_username = os_username
        existing_device.auto_matched = False
        existing_device.claimed_via_token = token
        existing_device.last_seen_at = timezone.now()
        existing_device.save()
        device_key = existing_device.api_key
        device = existing_device
    else:
        device_key = _generate_device_key()
        device = AgentDevice.objects.create(
            user=membership.user,
            device_id=str(uuid.uuid4()),
            hostname=hostname,
            platform=platform_str,
            app_version=version,
            api_key=device_key,
            os_username=os_username,
            is_active=True,
            last_seen_at=timezone.now(),
            claimed_via_token=token,
            auto_matched=False,
        )
        token.claim()

    # Update provisioning map if one exists (manual pick = fallback)
    prov = DeviceProvisioningMap.objects.filter(
        organization=org,
        machine_hostname__iexact=hostname,
        status='pending',
    ).first()
    if prov:
        prov.mark_paired(device, membership.user, method='manual')

    return JsonResponse({
        "status": "matched",
        "api_key": device_key,
        "device_id": str(device.id),
        "user_id": membership.user.id,
        "user_name": membership.user.get_full_name(),
    })


# ─────────────────────────────────────────────
# Admin: Provisioning status monitoring
# ─────────────────────────────────────────────

from .models import OnboardingBatch

@csrf_exempt
@require_GET
def provisioning_status(request, org_slug):
    """
    GET /api/deploy/provisioning/<org_slug>/status/
    Returns current provisioning progress for an org.
    """
    org, error = _get_admin_org(request)
    if error:
        return error

    if org.slug != org_slug:
        return JsonResponse({"error": "Org mismatch"}, status=403)

    batch = OnboardingBatch.objects.filter(organization=org).order_by('-created_at').first()
    maps = DeviceProvisioningMap.objects.filter(organization=org)

    total = maps.count()
    paired = maps.filter(status='paired').count()
    pending = maps.filter(status='pending').count()
    failed = maps.filter(status='failed').count()

    devices = []
    for m in maps.order_by('machine_hostname'):
        devices.append({
            'hostname': m.machine_hostname,
            'email': m.email,
            'display_name': m.display_name,
            'status': m.status,
            'match_method': m.match_method,
            'paired_at': m.paired_at.isoformat() if m.paired_at else None,
            'error': m.error_message,
        })

    return JsonResponse({
        'org': org.name,
        'batch_id': batch.id if batch else None,
        'batch_status': batch.status if batch else None,
        'summary': {
            'total_devices': total,
            'paired': paired,
            'pending': pending,
            'failed': failed,
            'percent_complete': round((paired / total) * 100, 1) if total > 0 else 0,
        },
        'devices': devices,
    })