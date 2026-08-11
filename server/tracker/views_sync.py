"""
views_sync.py - Agent Sync System
Lightweight polling endpoints for desktop agents to stay in sync with the database.
"""

import hashlib
import json
from django.utils import timezone
from django.db.models import Max, Count
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Client, Project, TaskType, ClientAssignment,
    OrganizationMembership, Organization, ClientPattern,
    OrgRoutingRule,
)
from .auth import AgentKeyAuthentication, BearerTokenAuthentication


def _compute_hash(data: str) -> str:
    """Compute a short hash for change detection"""
    return hashlib.md5(data.encode()).hexdigest()[:12]


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_status(request):
    """
    Lightweight endpoint to check if agent needs to sync.
    Agent calls this every 30-60 seconds.
    """
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)

    accessible_clients = _get_accessible_client_ids(request.user, org)
    client_stats = Client.objects.filter(
        id__in=accessible_clients,
        is_active=True
    ).aggregate(latest_id=Max('id'), count=Count('id'))

    project_stats = Project.objects.filter(
        client_id__in=accessible_clients,
        is_active=True
    ).aggregate(latest_id=Max('id'), count=Count('id'))

    try:
        task_stats = TaskType.objects.filter(
            org=org, is_active=True
        ).aggregate(latest_id=Max('id'), count=Count('id'))
    except Exception:
        task_stats = {'latest_id': None, 'count': 0}

    try:
        assignment_stats = ClientAssignment.objects.filter(
            user=request.user, organization=org
        ).aggregate(latest_id=Max('id'), count=Count('id'))
    except Exception:
        assignment_stats = {'latest_id': None, 'count': 0}

    # ── ClientPattern hash ────────────────────────────────────────────────────
    try:
        pattern_stats = ClientPattern.objects.filter(org=org).aggregate(
            latest_id=Max('id'), count=Count('id')
        )
    except Exception:
        pattern_stats = {'latest_id': None, 'count': 0}

    # ── OrgRoutingRule hash (v1.2.95) ─────────────────────────────────────────
    try:
        routing_rule_stats = OrgRoutingRule.objects.filter(org=org, enabled=True).aggregate(
            latest_id=Max('id'), count=Count('id')
        )
    except Exception:
        routing_rule_stats = {'latest_id': None, 'count': 0}

    def make_hash(stats):
        latest_id = stats.get('latest_id') or 0
        count = stats.get('count') or 0
        return _compute_hash(f"{latest_id}:{count}")

    return Response({
        'server_time': timezone.now().isoformat(),
        'organization': {
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
        },
        'entities': {
            'clients': {
                'count': client_stats['count'] or 0,
                'hash': make_hash(client_stats),
            },
            'projects': {
                'count': project_stats['count'] or 0,
                'hash': make_hash(project_stats),
            },
            'task_types': {
                'count': task_stats.get('count') or 0,
                'hash': make_hash(task_stats),
            },
            'assignments': {
                'count': assignment_stats.get('count') or 0,
                'hash': make_hash(assignment_stats),
            },
            'client_patterns': {
                'count': pattern_stats.get('count') or 0,
                'hash': make_hash(pattern_stats),
            },
            'routing_rules': {                           # v1.2.95
                'count': routing_rule_stats.get('count') or 0,
                'hash': make_hash(routing_rule_stats),
            },
        },
        'user': {
            'id': request.user.id,
            'role': membership.role,
        }
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_clients(request):
    """
    Full client list for agent sync.
    Now includes aliases so the agent can match on them.
    """
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)

    accessible_ids = _get_accessible_client_ids(request.user, org)

    clients = Client.objects.filter(
        id__in=accessible_ids,
        is_active=True
    ).order_by('name')

    assignments = {}
    try:
        assignments = {
            a.client_id: a.role
            for a in ClientAssignment.objects.filter(user=request.user, organization=org)
        }
    except Exception:
        pass

    client_list = [{
        'id': c.id,
        'name': c.name,
        'code': c.code or '',
        'visibility': c.visibility or 'all',
        'aliases': c.aliases or [],                       # ← NEW
        'my_role': assignments.get(c.id),
    } for c in clients]

    return Response({
        'clients': client_list,
        'count': len(client_list),
        'synced_at': timezone.now().isoformat(),
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_client_patterns(request):
    """
    NEW: Return org-level ClientPattern rules for the agent.
    Agent uses these as Tier 0 detection — highest priority, explicit org-admin rules.

    GET /api/sync/client-patterns/
    """
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)

    try:
        patterns = list(ClientPattern.objects.filter(org=org).values(
            'id', 'client_name', 'match_type', 'pattern', 'weight'
        ).order_by('-weight'))
    except Exception:
        patterns = []

    return Response({
        'client_patterns': patterns,
        'count': len(patterns),
        'synced_at': timezone.now().isoformat(),
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_projects(request):
    """Full project list for agent sync."""
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)

    accessible_ids = _get_accessible_client_ids(request.user, org)

    projects = Project.objects.filter(
        client_id__in=accessible_ids,
        is_active=True
    ).select_related('client').order_by('client__name', 'name')

    project_list = [{
        'id': p.id,
        'name': p.name,
        'client_id': p.client_id,
        'client_name': p.client.name,
    } for p in projects]

    return Response({
        'projects': project_list,
        'count': len(project_list),
        'synced_at': timezone.now().isoformat(),
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_task_types(request):
    """Full task type list for agent sync."""
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)

    try:
        task_types = list(TaskType.objects.filter(
            org=org, is_active=True
        ).order_by('name').values('id', 'name', 'code', 'is_billable'))
    except Exception:
        try:
            task_types = list(TaskType.objects.filter(
                org=org, is_active=True
            ).order_by('name').values('id', 'name'))
        except Exception:
            task_types = []

    return Response({
        'task_types': task_types,
        'count': len(task_types),
        'synced_at': timezone.now().isoformat(),
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_full(request):
    """
    Full sync - returns everything in one request.
    Now includes aliases on clients and client_patterns for Tier 0 detection.
    """
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)

    accessible_ids = _get_accessible_client_ids(request.user, org)

    assignments = {}
    try:
        assignments = {
            a.client_id: a.role
            for a in ClientAssignment.objects.filter(user=request.user, organization=org)
        }
    except Exception:
        pass

    # Clients — now with aliases
    clients = Client.objects.filter(
        id__in=accessible_ids,
        is_active=True
    ).order_by('name')

    client_list = [{
        'id': c.id,
        'name': c.name,
        'code': getattr(c, 'code', '') or '',
        'visibility': getattr(c, 'visibility', 'all') or 'all',
        'aliases': c.aliases or [],                       # ← NEW
        'my_role': assignments.get(c.id),
    } for c in clients]

    # Projects
    projects = Project.objects.filter(
        client_id__in=accessible_ids,
        is_active=True
    ).select_related('client').order_by('client__name', 'name')

    project_list = [{
        'id': p.id,
        'name': p.name,
        'client_id': p.client_id,
        'client_name': p.client.name,
    } for p in projects]

    # Task types
    try:
        task_types = list(TaskType.objects.filter(
            org=org, is_active=True
        ).order_by('name').values('id', 'name', 'code', 'is_billable'))
    except Exception:
        task_types = []

    # Client patterns (Tier 0 detection rules)         # ← NEW
    try:
        client_patterns = list(ClientPattern.objects.filter(org=org).values(
            'id', 'client_name', 'match_type', 'pattern', 'weight'
        ).order_by('-weight'))
    except Exception:
        client_patterns = []

    # Org routing rules (Tier -1 — highest priority, v1.2.95)
    try:
        routing_rules = [
            r.to_agent_dict() for r in
            OrgRoutingRule.objects
                .filter(org=org, enabled=True)
                .select_related('target_client')
                .order_by('-priority', 'id')
        ]
    except Exception:
        routing_rules = []

    # Org settings relevant to agent
    org_settings = {
        'ai_sensitivity': getattr(org, 'ai_sensitivity', 50) or 50,
        'mouse_idle_pause_seconds': getattr(org, 'mouse_idle_pause_seconds', 90) or 90,  # ← ADD
        # Vendor-controlled: when False (default), the desktop agent hides the
        # floating client ticker AND disables all manual client-switching, so the
        # client experience is fully hands-off. MavOps staff flip it on per-org
        # (e.g. a demo org) to show the file-open→client ticker for sales demos.
        'show_client_widget': bool(getattr(org, 'show_client_widget', False)),
    }

    return Response({
        'organization': {
            'id': org.id,
            'name': org.name,
            'slug': getattr(org, 'slug', '') or '',
        },
        'user': {
            'id': request.user.id,
            'username': request.user.username,
            'email': request.user.email,
            'role': membership.role,
        },
        'clients': client_list,
        'projects': project_list,
        'task_types': task_types,
        'client_patterns': client_patterns,              # ← NEW
        'routing_rules': routing_rules,                  # ← NEW (v1.2.95)
        'org_settings': org_settings,                   # ← NEW
        'synced_at': timezone.now().isoformat(),
    })


def _get_accessible_client_ids(user, org):
    """
    Get list of client IDs the user can access based on visibility rules.
    """
    try:
        membership = OrganizationMembership.objects.get(user=user, organization=org)
        is_admin = membership.role in ['owner', 'admin']
    except OrganizationMembership.DoesNotExist:
        return []

    all_clients = Client.objects.filter(org=org, is_active=True)

    assigned_client_ids = set()
    try:
        assigned_client_ids = set(
            ClientAssignment.objects.filter(
                user=user, organization=org
            ).values_list('client_id', flat=True)
        )
    except Exception:
        pass

    accessible_ids = []
    for client in all_clients:
        visibility = getattr(client, 'visibility', 'all') or 'all'
        if visibility == 'all':
            accessible_ids.append(client.id)
        elif visibility == 'assigned':
            if client.id in assigned_client_ids or is_admin:
                accessible_ids.append(client.id)
        elif visibility == 'confidential':
            if client.id in assigned_client_ids:
                accessible_ids.append(client.id)
        else:
            accessible_ids.append(client.id)

    return accessible_ids