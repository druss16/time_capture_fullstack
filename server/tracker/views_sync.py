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
    OrganizationMembership, Organization
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
    
    Returns timestamps and hashes for each entity type.
    Agent compares with local cache and only fetches what changed.
    
    GET /api/sync/status/
    """
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)
    
    # Get latest update times and counts for each entity
    # Using aggregation for efficiency (single query per entity)
    
    # Clients the user can access
    accessible_clients = _get_accessible_client_ids(request.user, org)
    client_stats = Client.objects.filter(
        id__in=accessible_clients,
        is_active=True
    ).aggregate(
        latest=Max('updated_at'),
        count=Count('id')
    )
    
    # Projects
    project_stats = Project.objects.filter(
        client_id__in=accessible_clients,
        is_active=True
    ).aggregate(
        latest=Max('updated_at'),
        count=Count('id')
    )
    
    # Task types (org-wide)
    task_stats = TaskType.objects.filter(
        org=org,
        is_active=True
    ).aggregate(
        latest=Max('updated_at'),
        count=Count('id')
    )
    
    # Client assignments for this user
    assignment_stats = ClientAssignment.objects.filter(
        user=request.user,
        organization=org
    ).aggregate(
        latest=Max('assigned_at'),
        count=Count('id')
    )
    
    # Build response with hashes for quick comparison
    def make_hash(stats):
        """Create hash from stats for change detection"""
        latest = stats['latest'].isoformat() if stats['latest'] else 'none'
        return _compute_hash(f"{latest}:{stats['count']}")
    
    return Response({
        'server_time': timezone.now().isoformat(),
        'organization': {
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
        },
        'entities': {
            'clients': {
                'updated_at': client_stats['latest'],
                'count': client_stats['count'],
                'hash': make_hash(client_stats),
            },
            'projects': {
                'updated_at': project_stats['latest'],
                'count': project_stats['count'],
                'hash': make_hash(project_stats),
            },
            'task_types': {
                'updated_at': task_stats['latest'],
                'count': task_stats['count'],
                'hash': make_hash(task_stats),
            },
            'assignments': {
                'updated_at': assignment_stats['latest'],
                'count': assignment_stats['count'],
                'hash': make_hash(assignment_stats),
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
    Only call when hash changed.
    
    GET /api/sync/clients/
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
    ).order_by('name').values(
        'id', 'name', 'code', 'visibility', 'updated_at'
    )
    
    # Include user's role on each client if assigned
    assignments = {
        a.client_id: a.role 
        for a in ClientAssignment.objects.filter(user=request.user, organization=org)
    }
    
    client_list = []
    for c in clients:
        client_list.append({
            'id': c['id'],
            'name': c['name'],
            'code': c['code'] or '',
            'visibility': c['visibility'],
            'my_role': assignments.get(c['id']),
            'updated_at': c['updated_at'].isoformat() if c['updated_at'] else None,
        })
    
    return Response({
        'clients': client_list,
        'count': len(client_list),
        'synced_at': timezone.now().isoformat(),
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_projects(request):
    """
    Full project list for agent sync.
    
    GET /api/sync/projects/
    """
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
        'code': p.code or '',
        'client_id': p.client_id,
        'client_name': p.client.name,
        'updated_at': p.updated_at.isoformat() if p.updated_at else None,
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
    """
    Full task type list for agent sync.
    
    GET /api/sync/task-types/
    """
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)
    
    task_types = TaskType.objects.filter(
        org=org,
        is_active=True
    ).order_by('name').values(
        'id', 'name', 'code', 'is_billable', 'updated_at'
    )
    
    return Response({
        'task_types': list(task_types),
        'count': len(task_types),
        'synced_at': timezone.now().isoformat(),
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def sync_full(request):
    """
    Full sync - returns everything in one request.
    Use for initial sync or when multiple entities changed.
    
    GET /api/sync/full/
    """
    try:
        membership = OrganizationMembership.objects.select_related('organization').get(
            user=request.user
        )
        org = membership.organization
    except OrganizationMembership.DoesNotExist:
        return Response({'error': 'No organization'}, status=400)
    
    accessible_ids = _get_accessible_client_ids(request.user, org)
    
    # Get user's assignments
    assignments = {
        a.client_id: a.role 
        for a in ClientAssignment.objects.filter(user=request.user, organization=org)
    }
    
    # Clients
    clients = Client.objects.filter(
        id__in=accessible_ids,
        is_active=True
    ).order_by('name')
    
    client_list = [{
        'id': c.id,
        'name': c.name,
        'code': c.code or '',
        'visibility': c.visibility,
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
        'code': p.code or '',
        'client_id': p.client_id,
        'client_name': p.client.name,
    } for p in projects]
    
    # Task types
    task_types = list(TaskType.objects.filter(
        org=org,
        is_active=True
    ).order_by('name').values('id', 'name', 'code', 'is_billable'))
    
    return Response({
        'organization': {
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
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
        'synced_at': timezone.now().isoformat(),
    })


def _get_accessible_client_ids(user, org):
    """
    Get list of client IDs the user can access based on visibility rules.
    
    Rules:
    - 'all' visibility: Everyone can see
    - 'assigned' visibility: Only assigned users + admins
    - 'confidential' visibility: Only explicitly assigned users (even admins need assignment)
    """
    # Get user's role
    try:
        membership = OrganizationMembership.objects.get(user=user, organization=org)
        is_admin = membership.role in ['owner', 'admin']
    except OrganizationMembership.DoesNotExist:
        return []
    
    # Get all org clients
    all_clients = Client.objects.filter(org=org, is_active=True)
    
    # Get user's explicit assignments
    assigned_client_ids = set(
        ClientAssignment.objects.filter(
            user=user, 
            organization=org
        ).values_list('client_id', flat=True)
    )
    
    accessible_ids = []
    
    for client in all_clients:
        visibility = getattr(client, 'visibility', 'all') or 'all'
        
        if visibility == 'all':
            # Everyone can see
            accessible_ids.append(client.id)
        elif visibility == 'assigned':
            # Assigned users + admins
            if client.id in assigned_client_ids or is_admin:
                accessible_ids.append(client.id)
        elif visibility == 'confidential':
            # Only explicitly assigned (even admins need assignment)
            if client.id in assigned_client_ids:
                accessible_ids.append(client.id)
        else:
            # Default: treat as 'all'
            accessible_ids.append(client.id)
    
    return accessible_ids