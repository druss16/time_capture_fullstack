"""
tracker/views_autopair.py

Auto-pair API endpoint for white-glove MSI deployments.
The agent calls this on first boot with org_token + hostname + windows_username.

Add to your urls.py:
    from tracker.views_autopair import auto_pair_device
    
    urlpatterns = [
        ...
        path('api/devices/auto-pair/', auto_pair_device, name='auto-pair-device'),
    ]
"""

import json
import logging
import secrets
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction

from tracker.models import (
    Organization, OrganizationMembership, OrgDeploymentToken,
    AgentDevice, BillingRate, EmployeeCostRate,
)
from tracker.models import DeviceProvisioningMap, OnboardingBatch

User = get_user_model()
logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def auto_pair_device(request):
    """
    POST /api/devices/auto-pair/
    
    Called by the agent on first boot when an org token is embedded.
    Attempts to match the device to a pre-provisioned user.
    
    Request body:
    {
        "org_token": "ODT-XKCD-9F3A",
        "hostname": "FIRM-PC-101",
        "windows_username": "FIRMNAME\\jsmith",
        "device_id": "uuid-generated-by-agent",
        "platform": "windows",
        "os_version": "Windows 11 Pro 23H2",
        "app_version": "1.2.0"
    }
    
    Success response (200):
    {
        "status": "paired",
        "match_method": "hostname",
        "user_email": "jsmith@firm.com",
        "user_display_name": "John Smith",
        "api_key": "hex-api-key-for-agent",
        "org_name": "Smith & Associates",
        "org_id": 1
    }
    
    Fallback response (202) — no pre-provisioned match, use manual pairing:
    {
        "status": "unprovisioned",
        "message": "No pre-provisioned mapping found. Use manual pairing.",
        "org_name": "Smith & Associates",
        "org_id": 1
    }
    
    Error responses:
    - 400: Missing required fields
    - 401: Invalid or expired org token
    - 409: Device already paired
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # ─── Validate required fields ───
    org_token = body.get('org_token', '').strip()
    hostname = body.get('hostname', '').strip().upper()
    windows_username = body.get('windows_username', '').strip().upper()
    device_id = body.get('device_id', '').strip()
    platform = body.get('platform', '').strip()
    os_version = body.get('os_version', '').strip()
    app_version = body.get('app_version', '').strip()

    if not org_token:
        return JsonResponse({'error': 'org_token is required'}, status=400)
    if not hostname and not windows_username:
        return JsonResponse({'error': 'hostname or windows_username is required'}, status=400)
    if not device_id:
        return JsonResponse({'error': 'device_id is required'}, status=400)

    # ─── Validate org token ───
    try:
        deployment_token = OrgDeploymentToken.objects.select_related('organization').get(
            token=org_token
        )
    except OrgDeploymentToken.DoesNotExist:
        return JsonResponse({'error': 'Invalid org token'}, status=401)

    if not deployment_token.is_valid:
        return JsonResponse({'error': 'Org token expired or deactivated'}, status=401)

    org = deployment_token.organization

    # ─── Check if device already paired ───
    existing_device = AgentDevice.objects.filter(device_id=device_id, is_active=True).first()
    if existing_device and existing_device.user:
        return JsonResponse({
            'status': 'already_paired',
            'user_email': existing_device.user.email,
            'api_key': existing_device.api_key,
            'org_name': org.name,
            'org_id': org.id,
        }, status=200)

    # ─── Try to match against provisioning map ───
    provision_match = None
    match_method = ''

    # Priority 1: Match by hostname (most reliable from Intune)
    if hostname:
        provision_match = DeviceProvisioningMap.objects.filter(
            organization=org,
            machine_hostname=hostname,
            status='pending',
        ).first()
        if provision_match:
            match_method = 'hostname'

    # Priority 2: Match by Windows username (fallback for generic hostnames)
    if not provision_match and windows_username:
        provision_match = DeviceProvisioningMap.objects.filter(
            organization=org,
            windows_username=windows_username,
            status='pending',
        ).first()
        if provision_match:
            match_method = 'windows_username'

    # ─── No match → return unprovisioned (agent falls back to manual pairing) ───
    if not provision_match:
        logger.info(
            f'Auto-pair: No match for hostname={hostname}, '
            f'win_user={windows_username}, org={org.slug}'
        )
        return JsonResponse({
            'status': 'unprovisioned',
            'message': 'No pre-provisioned mapping found. Use manual pairing.',
            'org_name': org.name,
            'org_id': org.id,
        }, status=202)

    # ─── Match found → create user (if needed) and pair device ───
    try:
        with transaction.atomic():
            user = _get_or_create_user(org, provision_match)
            device = _create_or_update_device(
                user, device_id, hostname, platform, os_version, 
                app_version, deployment_token
            )

            # Mark provisioning map as paired
            provision_match.mark_paired(device, user, method=match_method)

            # Increment token claim count
            deployment_token.claim()

            logger.info(
                f'Auto-pair SUCCESS: {hostname} → {user.email} '
                f'(method={match_method}, org={org.slug})'
            )

            return JsonResponse({
                'status': 'paired',
                'match_method': match_method,
                'user_email': user.email,
                'user_display_name': provision_match.display_name,
                'api_key': device.api_key,
                'org_name': org.name,
                'org_id': org.id,
            }, status=200)

    except Exception as e:
        logger.exception(f'Auto-pair FAILED: {hostname}, org={org.slug}')
        provision_match.mark_failed(str(e))
        return JsonResponse({
            'status': 'error',
            'message': f'Pairing failed: {str(e)}',
        }, status=500)


def _get_or_create_user(org, provision_match):
    """
    Get or create the user from the provisioning map entry.
    Also ensures OrganizationMembership exists.
    """
    email = provision_match.email.lower()
    display_name = provision_match.display_name

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

    # Ensure membership exists
    OrganizationMembership.objects.get_or_create(
        user=user,
        organization=org,
        defaults={'role': provision_match.role or 'member'}
    )

    # Set billing rate if provided
    if provision_match.billing_rate:
        BillingRate.objects.get_or_create(
            org=org, user=user, client=None, task_type=None,
            effective_date=timezone.now().date(),
            defaults={'rate': provision_match.billing_rate}
        )

    # Set cost rate if provided
    if provision_match.cost_rate:
        EmployeeCostRate.objects.get_or_create(
            organization=org, user=user,
            effective_date=timezone.now().date(),
            defaults={'cost_rate': provision_match.cost_rate}
        )

    return user


def _create_or_update_device(user, device_id, hostname, platform, os_version, 
                              app_version, deployment_token):
    """
    Create or update the AgentDevice record and activate it.
    """
    device, created = AgentDevice.objects.get_or_create(
        device_id=device_id,
        defaults={
            'user': user,
            'hostname': hostname,
            'platform': platform,
            'app_version': app_version,
            'os_username': '',
            'is_active': False,
            'claimed_via_token': deployment_token,
            'auto_matched': True,
        }
    )

    if not created:
        # Device exists but wasn't paired — link to user now
        device.user = user
        device.hostname = hostname
        device.platform = platform
        device.app_version = app_version
        device.claimed_via_token = deployment_token
        device.auto_matched = True

    # Activate and generate API key
    device.rotate_key()  # Sets api_key, is_active=True, last_seen_at

    return device


# ═══════════════════════════════════════════════════════════════════
# ADMIN API: Check provisioning status for an org
# ═══════════════════════════════════════════════════════════════════

@csrf_exempt
def provisioning_status(request, org_slug):
    """
    GET /api/admin/provisioning/{org_slug}/status/
    
    Returns current provisioning progress for an org.
    Use this to monitor the onboarding dashboard.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)

    try:
        org = Organization.objects.get(slug=org_slug)
    except Organization.DoesNotExist:
        return JsonResponse({'error': 'Org not found'}, status=404)

    # Get latest batch
    batch = OnboardingBatch.objects.filter(organization=org).order_by('-created_at').first()

    maps = DeviceProvisioningMap.objects.filter(organization=org)
    
    total = maps.count()
    paired = maps.filter(status='paired').count()
    pending = maps.filter(status='pending').count()
    failed = maps.filter(status='failed').count()

    # Per-device detail
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