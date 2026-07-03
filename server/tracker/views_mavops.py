# ============================================================================
# tracker/views_mavops.py
# MavOps Internal — cross-org endpoints for the ops dashboard
# Only accessible to is_staff users
# ============================================================================

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, BasePermission, AllowAny
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Count, Max, Sum, Q
from collections import defaultdict
from datetime import timedelta

from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication
from tracker.models import (
    AgentDevice, AgentLog, Organization, OrganizationMembership, OrgRoutingRule, Client
)

from django.db import transaction
 
from tracker.utils.client_name_match import build_token_index, detect_mismatch, detect_title_client

# The category that reassigned tax work should carry so it lands billable under
# the client. SET THIS to your system's actual value (e.g. "Tax Prep" / "Tax" /
# "Taxes"). If left None, the block's existing category is preserved and only
# the client is changed (safe fallback — never sets a stale/blank category).
RECONCILE_TAX_CATEGORY = None    # <-- set to your tax category string, or leave None
 

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
    from django.db.models import Q
    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': 'device_id required'}, status=400)

    updated = AgentDevice.objects.filter(
        Q(device_id=device_id) | Q(hostname=device_id)
    ).update(log_requested=True)

    if not updated:
        return Response({'error': 'Device not found'}, status=404)

    return Response({'ok': True, 'message': f'Log request sent — agent will ship within 10s'})


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
    from django.db.models import Q
    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': 'device_id required'}, status=400)

    updated = AgentDevice.objects.filter(
        Q(device_id=device_id) | Q(hostname=device_id)
    ).update(restart_requested=True)

    if not updated:
        return Response({'error': f'Device not found'}, status=404)

    return Response({'ok': True, 'message': f'Restart queued — agent will restart within 10s'})


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_kill_agent(request):
    """Force-kill agent via watchdog — works even when loop is frozen."""
    from django.db.models import Q
    device_id = request.data.get('device_id')
    if not device_id:
        return Response({'error': 'device_id required'}, status=400)

    updated = AgentDevice.objects.filter(
        Q(hostname=device_id) | Q(device_id=device_id)
    ).update(kill_requested=True)

    if not updated:
        return Response({'error': 'Device not found'}, status=404)

    return Response({
        'ok': True,
        'message': f'Kill queued — watchdog will fire within 60s'
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def watchdog_command(request):
    """Polled by tt_watchdog.exe every 60s."""
    from django.db.models import Q
    device_id = request.GET.get('device_id')
    if not device_id:
        return Response({'kill': False})

    device = AgentDevice.objects.filter(
        Q(device_id=device_id)
    ).first()

    if not device:
        return Response({'kill': False})

    kill = getattr(device, 'kill_requested', False)
    if kill:
        device.kill_requested = False
        device.save(update_fields=['kill_requested'])

    return Response({'kill': kill})



# ── Org Impersonation ─────────────────────────────────────────────────────────

import os
import json

MAVOPS_ADMIN_SECRET = os.environ.get("MAVOPS_ADMIN_SECRET", "")

def _is_mavops_admin(request):
    auth = request.headers.get("X-Admin-Secret", "")
    return bool(MAVOPS_ADMIN_SECRET) and auth == MAVOPS_ADMIN_SECRET

@api_view(['POST'])
@permission_classes([AllowAny])
def impersonate_org(request):
    if not _is_mavops_admin(request):
        return Response({"error": "Unauthorized"}, status=403)

    org_id = request.data.get("org_id")
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({"error": "Org not found"}, status=404)

    request.session["admin_impersonating_org_id"] = org.id
    request.session["admin_impersonating_org_name"] = org.name
    request.session.modified = True

    return Response({"ok": True, "org_id": org.id, "org_name": org.name})


@api_view(['POST'])
@permission_classes([AllowAny])
def clear_impersonation(request):
    if not _is_mavops_admin(request):
        return Response({"error": "Unauthorized"}, status=403)

    request.session.pop("admin_impersonating_org_id", None)
    request.session.pop("admin_impersonating_org_name", None)
    request.session.modified = True

    return Response({"ok": True})


@api_view(['GET'])
@permission_classes([AllowAny])
def impersonation_status(request):
    org_id = request.session.get("admin_impersonating_org_id")
    if org_id:
        return Response({
            "is_impersonating": True,
            "org_id": org_id,
            "org_name": request.session.get("admin_impersonating_org_name"),
        })
    return Response({"is_impersonating": False})


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_org_members(request, org_id):
    """
    GET /api/mavops/orgs/<org_id>/members/
    Returns all members of an org for the user picker.
    """
    memberships = OrganizationMembership.objects.filter(
        organization_id=org_id
    ).select_related('user').order_by('user__username')

    return Response({
        'members': [{
            'user_id': m.user.id,
            'username': m.user.username,
            'email': m.user.email or '',
            'first_name': m.user.first_name or '',
            'last_name': m.user.last_name or '',
            'role': m.role,
        } for m in memberships]
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_routing_rules_orgs(request):
    """
    GET /api/mavops/routing-rules/orgs/
    Returns all orgs with rule counts + fire stats for the overview page.
    """
    orgs = Organization.objects.all().order_by('name')
 
    result = []
    for org in orgs:
        rules_qs = OrgRoutingRule.objects.filter(org=org)
        stats = rules_qs.aggregate(
            rule_count=Count('id'),
            enabled_count=Count('id', filter=Q(enabled=True)),
            custom_count=Count('id', filter=Q(is_default=False)),
            default_count=Count('id', filter=Q(is_default=True)),
            total_fires=Sum('fire_count'),
            last_fire_at=Max('last_fired_at'),
        )
        result.append({
            'id': org.id,
            'name': org.name,
            'rule_count': stats['rule_count'] or 0,
            'enabled_count': stats['enabled_count'] or 0,
            'custom_count': stats['custom_count'] or 0,
            'default_count': stats['default_count'] or 0,
            'total_fires': stats['total_fires'] or 0,
            'last_fire_at': (
                stats['last_fire_at'].isoformat() if stats['last_fire_at'] else None
            ),
        })
 
    return Response({'orgs': result, 'total': len(result)})
 
 
# ── List rules for a single org (with target client info) ──────────────────
 
@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_routing_rules_for_org(request, org_id):
    """
    GET /api/mavops/routing-rules/orgs/<org_id>/
    Returns all rules for one org + the org's client list (for target dropdowns).
    """
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Org not found'}, status=404)
 
    rules = (
        OrgRoutingRule.objects
        .filter(org=org)
        .select_related('target_client', 'created_by')
        .order_by('-priority', 'id')
    )
 
    clients = Client.objects.filter(org=org, is_active=True).order_by('name')
 
    return Response({
        'org': {'id': org.id, 'name': org.name},
        'rules': [
            {
                'id': r.id,
                'match_type': r.match_type,
                'match_value': r.match_value,
                'action': r.action,
                'target_client_id': r.target_client_id,
                'target_client_name': r.target_client.name if r.target_client else None,
                'priority': r.priority,
                'enabled': r.enabled,
                'description': r.description,
                'is_default': r.is_default,
                'fire_count': r.fire_count,
                'last_fired_at': (
                    r.last_fired_at.isoformat() if r.last_fired_at else None
                ),
                'created_by': r.created_by.username if r.created_by else None,
                'created_at': r.created_at.isoformat() if r.created_at else None,
            }
            for r in rules
        ],
        'clients': [{'id': c.id, 'name': c.name} for c in clients],
    })
 
 
# ── Create rule ────────────────────────────────────────────────────────────
 
@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_create_routing_rule(request, org_id):
    """POST /api/mavops/routing-rules/orgs/<org_id>/create/"""
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Org not found'}, status=404)
 
    data = request.data
    target_client = None
    if data.get('target_client_id'):
        try:
            target_client = Client.objects.get(id=data['target_client_id'], org=org)
        except Client.DoesNotExist:
            return Response({'error': 'Target client not found in this org'}, status=400)
 
    try:
        rule = OrgRoutingRule(
            org=org,
            match_type=data['match_type'],
            match_value=data['match_value'],
            action=data.get('action', 'route_to_client'),
            target_client=target_client,
            priority=int(data.get('priority', 100)),
            enabled=bool(data.get('enabled', True)),
            description=data.get('description', ''),
            is_default=False,
            created_by=request.user,
        )
        rule.full_clean()
        rule.save()
        return Response({'ok': True, 'rule_id': rule.id})
    except Exception as e:
        return Response({'ok': False, 'error': str(e)}, status=400)
 
 
# ── Update / delete rule ───────────────────────────────────────────────────
 
@api_view(['PATCH', 'DELETE'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_update_delete_routing_rule(request, org_id, rule_id):
    """
    PATCH  /api/mavops/routing-rules/orgs/<org_id>/<rule_id>/
    DELETE /api/mavops/routing-rules/orgs/<org_id>/<rule_id>/
    """
    try:
        org = Organization.objects.get(id=org_id)
        rule = OrgRoutingRule.objects.get(id=rule_id, org=org)
    except (Organization.DoesNotExist, OrgRoutingRule.DoesNotExist):
        return Response({'error': 'Not found'}, status=404)
 
    if request.method == 'DELETE':
        if rule.is_default:
            return Response(
                {'error': 'Default rules cannot be deleted. Disable instead.'},
                status=400,
            )
        rule.delete()
        return Response({'ok': True})
 
    # PATCH
    data = request.data
    try:
        if 'match_type' in data and not rule.is_default:
            rule.match_type = data['match_type']
        if 'match_value' in data and not rule.is_default:
            rule.match_value = data['match_value']
        if 'action' in data:
            rule.action = data['action']
        if 'target_client_id' in data:
            if data['target_client_id']:
                rule.target_client = Client.objects.get(
                    id=data['target_client_id'], org=org
                )
            else:
                rule.target_client = None
        if 'priority' in data:
            rule.priority = int(data['priority'])
        if 'enabled' in data:
            rule.enabled = bool(data['enabled'])
        if 'description' in data:
            rule.description = data['description']
 
        rule.full_clean()
        rule.save()
        return Response({'ok': True})
    except Exception as e:
        return Response({'ok': False, 'error': str(e)}, status=400)
 
 
# ── Test simulator ─────────────────────────────────────────────────────────
# Mirrors agent's OrgRoutingRuleEngine._rule_matches() — keep in sync!
 
_MAVOPS_EXE_FAMILIES = {
    'taxwise':    ['tww', 'taxwise'],
    'ultratax':   ['uts', 'ultratax', 'utw'],
    'lacerte':    ['lacerte', 'lacertepro'],
    'proseries':  ['proseries', 'ps'],
    'drake':      ['drake'],
    'quickbooks': ['qbw', 'qb', 'quickbooks'],
    'excel':      ['excel'],
    'word':       ['winword'],
    'powerpoint': ['powerpnt'],
    'outlook':    ['outlook'],
    'chrome':     ['chrome'],
    'edge':       ['msedge'],
    'firefox':    ['firefox'],
    'teams':      ['teams', 'ms-teams'],
    'slack':      ['slack'],
    'zoom':       ['zoom'],
}
 
 
def _mavops_rule_matches(rule, title, exe, file_path):
    import re as _re
    mv = (rule.match_value or '').lower()
    title_l = (title or '').lower()
    exe_l = (exe or '').lower()
    path_l = (file_path or '').lower()
 
    if rule.match_type == 'exe':
        return exe_l == mv or exe_l == f"{mv}.exe"
 
    if rule.match_type == 'exe_family':
        prefixes = _MAVOPS_EXE_FAMILIES.get(mv, [mv])
        exe_stripped = exe_l.replace('.exe', '').strip()
        return any(exe_stripped.startswith(p) for p in prefixes) if exe_stripped else False
 
    if rule.match_type == 'title_contains':
        return mv in title_l
 
    if rule.match_type == 'title_regex':
        try:
            return bool(_re.search(rule.match_value, title or '', _re.IGNORECASE))
        except _re.error:
            return False
 
    if rule.match_type == 'file_path_contains':
        return mv in path_l
 
    return False
 
 
@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_test_routing_rules(request, org_id):
    """POST /api/mavops/routing-rules/orgs/<org_id>/test/
    Body: {title, exe, file_path}
    Returns which rules match + winning outcome.
    """
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Org not found'}, status=404)
 
    title = request.data.get('title', '')
    exe = request.data.get('exe', '')
    file_path = request.data.get('file_path', '')
 
    rules = (
        OrgRoutingRule.objects
        .filter(org=org, enabled=True)
        .select_related('target_client')
        .order_by('-priority', 'id')
    )
 
    matches = []
    winning = None
    for r in rules:
        if _mavops_rule_matches(r, title, exe, file_path):
            matches.append({
                'rule_id': r.id,
                'match_type': r.match_type,
                'match_value': r.match_value,
                'action': r.action,
                'target_client_name': r.target_client.name if r.target_client else None,
                'priority': r.priority,
                'description': r.description,
            })
            if winning is None:
                winning = r
 
    if winning is None:
        outcome = {
            'action': 'fall_through',
            'message': 'No org rule matched. Agent falls through to regex/learned/AI tiers.',
        }
    elif winning.action == 'route_to_client':
        name = winning.target_client.name if winning.target_client else 'MISSING'
        outcome = {
            'action': 'route_to_client',
            'target_client_name': name,
            'message': f'Would switch active client to "{name}".',
        }
    elif winning.action == 'never_switch_away':
        outcome = {
            'action': 'never_switch_away',
            'message': 'Would hold current client — no switch allowed.',
        }
    elif winning.action == 'suppress':
        outcome = {
            'action': 'suppress',
            'message': 'Would ignore this window entirely.',
        }
    else:
        outcome = {'action': 'unknown', 'message': 'Unknown action.'}
 
    return Response({
        'input': {'title': title, 'exe': exe, 'file_path': file_path},
        'matches': matches,
        'winning_rule_id': winning.id if winning else None,
        'outcome': outcome,
    })
 
 
# ── Top firing rules (cross-org telemetry) ─────────────────────────────────
 
@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_top_firing_rules(request):
    """
    GET /api/mavops/routing-rules/top-firing/
    Top 10 rules by fire_count across ALL orgs.
    """
    rules = (
        OrgRoutingRule.objects
        .filter(fire_count__gt=0)
        .select_related('org', 'target_client')
        .order_by('-fire_count')[:10]
    )
 
    return Response({
        'rules': [
            {
                'org_id': r.org_id,
                'org_name': r.org.name,
                'rule_id': r.id,
                'match_type': r.match_type,
                'match_value': r.match_value,
                'target_client_name': r.target_client.name if r.target_client else None,
                'fire_count': r.fire_count,
                'last_fired_at': r.last_fired_at.isoformat() if r.last_fired_at else None,
            }
            for r in rules
        ]
    })
 
 
# ── Copy rules from source org → destination org ───────────────────────────
 
@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_copy_routing_rules(request, org_id):
    """
    POST /api/mavops/routing-rules/orgs/<org_id>/copy-from/
    Body: {source_org_id: N}
    Returns: {copied, skipped_duplicates, skipped_missing_client}
    """
    from django.db import transaction as _tx
 
    try:
        dest_org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Destination org not found'}, status=404)
 
    source_id = request.data.get('source_org_id')
    if not source_id:
        return Response({'error': 'source_org_id required'}, status=400)
    if int(source_id) == int(org_id):
        return Response({'error': 'Source and destination are the same org'}, status=400)
 
    try:
        source_org = Organization.objects.get(id=source_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Source org not found'}, status=404)
 
    source_rules = OrgRoutingRule.objects.filter(
        org=source_org, enabled=True,
    ).select_related('target_client')
 
    existing_keys = set(
        OrgRoutingRule.objects.filter(org=dest_org).values_list(
            'match_type', 'match_value',
        )
    )
 
    dest_client_by_name = {
        c.name.lower(): c
        for c in Client.objects.filter(org=dest_org, is_active=True)
    }
 
    copied = 0
    skipped_duplicates = 0
    skipped_missing_client = 0
 
    with _tx.atomic():
        for src in source_rules:
            if (src.match_type, src.match_value) in existing_keys:
                skipped_duplicates += 1
                continue
 
            new_target = None
            if src.target_client:
                new_target = dest_client_by_name.get(src.target_client.name.lower())
                if not new_target:
                    skipped_missing_client += 1
                    continue
 
            OrgRoutingRule.objects.create(
                org=dest_org,
                match_type=src.match_type,
                match_value=src.match_value,
                action=src.action,
                target_client=new_target,
                priority=src.priority,
                enabled=src.enabled,
                description=src.description or f'Copied from {source_org.name}',
                is_default=False,
                created_by=request.user,
            )
            copied += 1
 
    return Response({
        'ok': True,
        'copied': copied,
        'skipped_duplicates': skipped_duplicates,
        'skipped_missing_client': skipped_missing_client,
        'source_org_name': source_org.name,
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_client_mismatches(request):
    """
    GET /api/mavops/mismatches/
      ?org_id=<id>       (optional — scope to one org; default: all orgs)
      &days=<int>        (lookback window; default 60, max 365)
      &limit=<int>       (max flagged rows returned; default 500, max 2000)

    Returns high-confidence client-name mismatches, each with the offending
    block's title, the booked client, and the client the title actually looks
    like — plus a per-day histogram so you can see if the problem is historical
    or ongoing.
    """
    from tracker.models import Block, Client

    org_id = request.GET.get('org_id')
    try:
        days = min(int(request.GET.get('days', 60)), 365)
    except (ValueError, TypeError):
        days = 60
    try:
        limit = min(int(request.GET.get('limit', 500)), 2000)
    except (ValueError, TypeError):
        limit = 500

    cutoff = timezone.now() - timedelta(days=days)

    # Build a per-org client-name index once, so tokens' distinctiveness is
    # computed within each org's own roster (cross-org names shouldn't dilute
    # each other's df).
    client_qs = Client.objects.all()
    if org_id:
        client_qs = client_qs.filter(org_id=org_id)
    names_by_org = defaultdict(dict)
    for c in client_qs.only('id', 'name', 'org_id'):
        names_by_org[c.org_id][c.id] = c.name
    index_by_org = {oid: build_token_index(names) for oid, names in names_by_org.items()}

    # Firm name per org — lets the matcher recognize the firm's own name showing
    # up as a pseudo-client (e.g. the CS Connect window) and bucket it internal.
    from tracker.models import Organization
    firm_by_org = {}
    org_qs = Organization.objects.all()
    if org_id:
        org_qs = org_qs.filter(id=org_id)
    for o in org_qs.only('id', 'name'):
        firm_by_org[o.id] = o.name

    # Committed blocks with a client assigned + a usable window title.
    blocks = (
        Block.objects
        .filter(
            deleted_at__isnull=True,
            client_id__isnull=False,
            start__gte=cutoff,
        )
        .exclude(window_title__isnull=True)
        .exclude(window_title='')
        .select_related('client', 'user', 'org')
        .order_by('-start')
    )
    if org_id:
        blocks = blocks.filter(org_id=org_id)

    # Split everything by bucket: "client" = real billing-impacting mismatches,
    # "internal" = firm/admin bucket noise (real but not a client billing error).
    flagged = {"client": [], "internal": []}
    by_day = {"client": defaultdict(int), "internal": defaultdict(int)}
    by_pair = {"client": defaultdict(int), "internal": defaultdict(int)}
    counts = {"client": 0, "internal": 0}
    scanned = 0

    for b in blocks.iterator(chunk_size=1000):
        scanned += 1
        oid = b.org_id
        index = index_by_org.get(oid)
        names = names_by_org.get(oid)
        if not index or not names or b.client_id not in names:
            continue

        m = detect_mismatch(
            b.window_title, b.client_id, index, names,
            firm_name=firm_by_org.get(oid),
        )
        if not m:
            continue

        bucket = m.get("bucket", "client")
        day = timezone.localtime(b.start).date().isoformat()
        by_day[bucket][day] += 1
        by_pair[bucket][f'{names[b.client_id]} → {m["looks_like_client_name"]}'] += 1
        counts[bucket] += 1

        if len(flagged[bucket]) < limit:
            flagged[bucket].append({
                'block_id': b.id,
                'org_id': oid,
                'org_name': b.org.name if b.org_id else None,
                'user': (b.user.get_full_name().strip() or b.user.username) if b.user_id else None,
                'date': day,
                'window_title': b.window_title[:200],
                'app_name': getattr(b, 'app_name', '') or '',
                'booked_client_id': b.client_id,
                'booked_client_name': names[b.client_id],
                'looks_like_client_id': m['looks_like_client_id'],
                'looks_like_client_name': m['looks_like_client_name'],
                'bucket': bucket,
                'confidence': {
                    'looks_like_coverage': m['looks_like_coverage'],
                    'abs_hit': m['looks_like_abs_hit'],
                    'booked_coverage': m['booked_coverage'],
                    'top_token_weight': m['top_token_weight'],
                },
            })

    def _histogram(bucket):
        d = by_day[bucket]
        return [{'date': k, 'count': d[k]} for k in sorted(d.keys())]

    def _pairs(bucket):
        return sorted(
            ({'pair': k, 'count': v} for k, v in by_pair[bucket].items()),
            key=lambda x: -x['count'],
        )[:25]

    return Response({
        'params': {'org_id': int(org_id) if org_id else None, 'days': days},
        'scanned_blocks': scanned,
        # The money bucket — real client<->client mismatches (e.g. UltraTax
        # forward-fill). The verdict/histogram the UI leads with is THIS one.
        'client': {
            'total': counts['client'],
            'returned': len(flagged['client']),
            'histogram': _histogram('client'),
            'top_pairs': _pairs('client'),
            'mismatches': flagged['client'],
        },
        # Firm/admin bucket noise — surfaced separately so it's visible and
        # accurate, but never inflates the client count or the verdict.
        'internal': {
            'total': counts['internal'],
            'returned': len(flagged['internal']),
            'histogram': _histogram('internal'),
            'top_pairs': _pairs('internal'),
            'mismatches': flagged['internal'],
        },
    })


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def mavops_reconcile_mismatches(request):
    """
    POST /api/mavops/mismatches/reconcile/
      body: {
        "org_id": 21,                 (required)
        "block_ids": [123, 456, ...], (required — the blocks to reconcile)
        "confirm": false              (default false = dry-run)
      }
 
    For each block: re-derive the client from its title. If the title
    distinctively names ONE business client, reassign the block there (and set
    the tax category if RECONCILE_TAX_CATEGORY is configured). Dry-run by
    default — returns the plan and changes nothing unless confirm=true.
    """
    from tracker.models import Block, Client, Organization, ClassificationAudit
 
    org_id = request.data.get('org_id')
    block_ids = request.data.get('block_ids') or []
    confirm = bool(request.data.get('confirm', False))
 
    if not org_id:
        return Response({"error": "org_id is required."}, status=400)
    if not isinstance(block_ids, list) or not block_ids:
        return Response({"error": "block_ids (non-empty list) is required."}, status=400)
    # Guardrail: cap batch size so a runaway request can't rewrite everything.
    if len(block_ids) > 1000:
        return Response({"error": "Too many block_ids (max 1000 per call)."}, status=400)
 
    # Build the org's client index once.
    names = {}
    for c in Client.objects.filter(org_id=org_id).only('id', 'name'):
        names[c.id] = c.name
    if not names:
        return Response({"error": "No clients for this org."}, status=404)
    index = build_token_index(names)
 
    firm = None
    o = Organization.objects.filter(id=org_id).only('name').first()
    if o:
        firm = o.name
 
    blocks = (
        Block.objects
        .filter(id__in=block_ids, org_id=org_id, deleted_at__isnull=True)
        .select_related('client')
    )
 
    planned = []
    skipped = []
    for b in blocks:
        det = detect_title_client(b.window_title or '', index, names, firm_name=firm)
        if not det:
            skipped.append({
                'block_id': b.id,
                'reason': 'title no longer distinctively names a client',
                'window_title': (b.window_title or '')[:160],
            })
            continue
        target_cid = det['client_id']
        if b.client_id == target_cid:
            skipped.append({
                'block_id': b.id,
                'reason': 'already booked to the detected client',
                'client_name': names.get(target_cid),
            })
            continue
        planned.append({
            'block_id': b.id,
            'from_client_id': b.client_id,
            'from_client_name': names.get(b.client_id) or (b.client.name if b.client_id else None),
            'to_client_id': target_cid,
            'to_client_name': det['client_name'],
            'window_title': (b.window_title or '')[:160],
            'confidence': {'coverage': det['coverage'], 'abs_hit': det['abs_hit']},
        })
 
    if not confirm:
        return Response({
            'dry_run': True,
            'org_id': int(org_id),
            'would_reassign': len(planned),
            'skipped': len(skipped),
            'category_will_be_set': RECONCILE_TAX_CATEGORY,
            'plan': planned,
            'skips': skipped[:100],
        })
 
    # ── commit ──────────────────────────────────────────────────────────────
    from django.db import transaction
    from tracker.services.classification_service import ClassificationService
    changed = 0
    with transaction.atomic():
        # Re-fetch for update to avoid races on the committed rows.
        by_id = {p['block_id']: p for p in planned}
        for b in Block.objects.select_for_update().filter(id__in=list(by_id.keys())):
            p = by_id.get(b.id)
            if not p:
                continue
            old_client = b.client_id
            cat_before = ClassificationService._extract_dominant_category(b)
 
            b.client_id = p['to_client_id']
            update_fields = ['client_id']
            if RECONCILE_TAX_CATEGORY:
                b.category = RECONCILE_TAX_CATEGORY
                update_fields.append('category')
            if hasattr(b, 'is_billable'):
                b.is_billable = True
                update_fields.append('is_billable')
            b.save(update_fields=update_fields, force_classifier=True)
 
            cat_after = ClassificationService._extract_dominant_category(b)
 
            ClassificationAudit.objects.create(
                block=b,
                source='manual',
                client_before_id=old_client,
                client_after_id=p['to_client_id'],
                category_before=cat_before,
                category_after=cat_after,
                confidence_client=1.0,
                confidence_category=1.0,
                overall_confidence=1.0,
                matched_signals=[{
                    'type': 'mismatch_reconcile',
                    'strength': p['confidence']['coverage'],
                    'evidence': (
                        f"Title distinctively names {p['to_client_name']!r} "
                        f"(coverage {p['confidence']['coverage']}, "
                        f"mass {p['confidence']['abs_hit']}); reassigned from "
                        f"{p['from_client_name']!r}."
                    ),
                    'detail': (b.window_title or '')[:200],
                }],
                corrected_by_user=True,   # the client actually changed
            )
            changed += 1
 
    return Response({
        'dry_run': False,
        'org_id': int(org_id),
        'reassigned': changed,
        'skipped': len(skipped),
        'category_set': RECONCILE_TAX_CATEGORY,
    })
 