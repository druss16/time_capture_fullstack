# ============================================================================
# tracker/views_mavops.py
# MavOps Internal — cross-org endpoints for the ops dashboard
# Only accessible to is_staff users
# ============================================================================

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Count, Max
from datetime import timedelta

from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication
from tracker.models import (
    AgentDevice, AgentLog, Organization, OrganizationMembership,
)


class IsStaff(BasePermission):
    """Only Django staff/superusers can access MavOps internal endpoints."""
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        )


# ── Org overview ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_orgs(request):
    """
    All organizations with seat counts, device counts, plan info.
    GET /api/mavops/orgs/
    """
    orgs = Organization.objects.all().order_by('name')

    result = []
    for org in orgs:
        member_count = OrganizationMembership.objects.filter(organization=org).count()
        device_count = AgentDevice.objects.filter(
            user__memberships__organization=org,
            is_active=True
        ).values('user_id', 'hostname').distinct().count()

        # Last activity — most recent device seen
        last_device = AgentDevice.objects.filter(
            user__memberships__organization=org
        ).order_by('-last_seen_at').first()

        result.append({
            'id': org.id,
            'name': org.name,
            'slug': getattr(org, 'slug', '') or '',
            'plan': getattr(org, 'plan', 'unknown') or 'unknown',
            'seat_count': getattr(org, 'seat_count', 0) or 0,
            'member_count': member_count,
            'active_devices': device_count,
            'last_activity': last_device.last_seen_at.isoformat() if last_device and last_device.last_seen_at else None,
            'trial_ends_at': org.trial_ends_at.isoformat() if getattr(org, 'trial_ends_at', None) else None,
            'created_at': org.created_at.isoformat() if getattr(org, 'created_at', None) else None,
        })

    return Response({
        'orgs': result,
        'total': len(result),
    })


# ── All devices ───────────────────────────────────────────────────────────────

@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_devices(request):
    org_id = request.GET.get('org_id')
    active = request.GET.get('active')

    qs = AgentDevice.objects.select_related('user').order_by('-last_seen_at')

    if org_id:
        qs = qs.filter(user__memberships__organization_id=org_id)

    if active == 'true':
        qs = qs.filter(is_active=True)
    elif active == 'false':
        qs = qs.filter(is_active=False)

    # Dedup: one entry per user+hostname, keep most recent
    seen = {}
    for device in qs:
        key = (device.user_id, device.hostname)
        if key not in seen:
            seen[key] = device  # first = most recent (ordered by -last_seen_at)

    result = []
    for device in seen.values():
        membership = OrganizationMembership.objects.filter(
            user=device.user
        ).select_related('organization').first()

        result.append({
            'id': device.id,
            'device_id': device.device_id,
            'user': device.user.username if device.user else 'unknown',
            'user_id': device.user_id,
            'machine_name': device.hostname or device.device_id,
            'os': device.platform or '',
            'agent_version': device.app_version or '',
            'first_seen': device.created_at.isoformat() if device.created_at else '',
            'last_seen': device.last_seen_at.isoformat() if device.last_seen_at else '',
            'is_active': device.is_active,
            'org_id': membership.organization.id if membership else None,
            'org_name': membership.organization.name if membership else 'Unknown',
        })

    # Sort by last_seen descending
    result.sort(key=lambda d: d['last_seen'], reverse=True)

    return Response({
        'devices': result,
        'total': len(result),
    })


# ── All logs ──────────────────────────────────────────────────────────────────

@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_logs(request):
    """
    All agent logs across all orgs.
    GET /api/mavops/logs/
    Query params:
      - hostname: filter by hostname (partial)
      - device_id: filter by device_id
      - org_id: filter by org
      - trigger: scheduled/on_demand/error
    """
    qs = AgentLog.objects.select_related('user').order_by('-created_at')

    hostname = request.GET.get('hostname')
    device_id = request.GET.get('device_id')
    trigger = request.GET.get('trigger')
    org_id = request.GET.get('org_id')

    if hostname:
        qs = qs.filter(hostname__icontains=hostname)
    if device_id:
        qs = qs.filter(agent_device_id=device_id)  # ← renamed
    if trigger:
        qs = qs.filter(trigger=trigger)
    if org_id:
        qs = qs.filter(user__memberships__organization_id=org_id)

    logs = qs[:50]

    # Get org for each log
    def get_org(user_id):
        m = OrganizationMembership.objects.filter(
            user_id=user_id
        ).select_related('organization').first()
        return m.organization.name if m else 'Unknown'

    return Response({
        'logs': [{
            'id': l.id,
            'user': l.user.username if l.user else 'unknown',
            'device_id': l.device_id,
            'hostname': l.hostname,
            'platform': l.platform,
            'app_version': l.app_version,
            'trigger': l.trigger,
            'line_count': l.line_count,
            'created_at': l.created_at.isoformat(),
            'log_text': l.log_text,
            'org_name': get_org(l.user_id) if l.user_id else 'Unknown',
        } for l in logs],
        'total': qs.count(),
    })


# ── All errors ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_errors(request):
    """
    All agent errors across all orgs.
    GET /api/mavops/errors/
    Query params:
      - days: lookback (default 7)
      - org_id: filter by org
      - resolved: true/false
      - limit: max results (default 100)
    """
    from tracker.models import AgentError

    days = int(request.GET.get('days', 7))
    cutoff = timezone.now() - timedelta(days=days)
    qs = AgentError.objects.filter(created_at__gte=cutoff).select_related('user').order_by('-created_at')

    org_id = request.GET.get('org_id')
    resolved = request.GET.get('resolved')
    limit = min(int(request.GET.get('limit', 100)), 500)

    if org_id:
        qs = qs.filter(user__memberships__organization_id=org_id)
    if resolved == 'true':
        qs = qs.filter(resolved=True)
    elif resolved == 'false':
        qs = qs.filter(resolved=False)

    # Summary stats
    total = qs.count()
    unresolved = qs.filter(resolved=False).count()

    by_type = list(
        qs.values('error_type')
        .annotate(count=Count('id'))
        .order_by('-count')[:10]
    )

    by_org = []
    for m in OrganizationMembership.objects.select_related('organization').all():
        count = qs.filter(user=m.user).count()
        if count > 0:
            by_org.append({'org': m.organization.name, 'count': count})

    def get_org(user_id):
        m = OrganizationMembership.objects.filter(
            user_id=user_id
        ).select_related('organization').first()
        return m.organization.name if m else 'Unknown'

    errors = qs[:limit]

    return Response({
        'summary': {
            'total': total,
            'unresolved': unresolved,
            'by_type': by_type,
            'by_org': sorted(by_org, key=lambda x: -x['count'])[:10],
        },
        'errors': [{
            'id': e.id,
            'error_type': e.error_type,
            'error_message': e.error_message[:300],
            'traceback': e.traceback,
            'user': e.user.username if e.user else None,
            'hostname': e.hostname,
            'device_id': e.device_id,
            'app_version': e.app_version,
            'platform': e.platform,
            'created_at': e.created_at.isoformat(),
            'resolved': e.resolved,
            'org_name': get_org(e.user_id) if e.user_id else 'Unknown',
        } for e in errors],
    })


# ── Request logs from any device ─────────────────────────────────────────────

@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_request_logs(request):
    """
    Request on-demand log ship from any device.
    POST /api/mavops/request-logs/
    Body: { "device_id": "uuid" }
    """
    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': 'device_id required'}, status=400)

    updated = AgentDevice.objects.filter(device_id=device_id).update(
        log_requested=True
    )

    if not updated:
        return Response({'error': 'Device not found'}, status=404)

    return Response({
        'ok': True,
        'message': f'Log request sent to {device_id} — agent will ship within 10s'
    })


# ── Resolve error ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_resolve_error(request, error_id):
    """
    Resolve an error from any org.
    POST /api/mavops/errors/<id>/resolve/
    """
    from tracker.models import AgentError

    try:
        error = AgentError.objects.get(id=error_id)
    except AgentError.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)

    error.resolved = True
    error.resolved_at = timezone.now()
    error.resolved_by = request.user
    error.notes = request.data.get('notes', '')
    error.save()

    return Response({'ok': True})


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_restart_device(request):
    """
    Queue a restart command for a specific device.
    POST /api/mavops/restart-device/
    Body: { "device_id": "TLW101032" }  ← hostname
    """
    from tracker.models import AgentControl

    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': 'device_id required'}, status=400)

    updated = AgentDevice.objects.filter(hostname=device_id).update(
        restart_requested=True
    )

    if not updated:
        return Response({'error': f'Device {device_id} not found'}, status=404)

    return Response({
        'ok': True,
        'message': f'Restart queued for {device_id} — agent will restart within 10s'
    })