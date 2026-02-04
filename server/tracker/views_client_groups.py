# ============================================================================
# ADD TO tracker/views_settings.py OR create new views_client_groups.py
# Client Groups API Endpoints
# ============================================================================

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import Count, Prefetch

# Import your models - adjust path as needed
# from .models import ClientGroup, Client, ClientAssignment, Organization, OrganizationMembership


def get_user_org(user):
    """Get the user's Organization from OrganizationMembership."""
    try:
        from .models import OrganizationMembership
        membership = OrganizationMembership.objects.filter(user=user).first()
        if membership:
            return membership.organization
        return None
    except Exception:
        return None


# ============================================================================
# CLIENT GROUPS CRUD
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def client_groups_list(request):
    """
    GET: List all client groups with client counts
    POST: Create a new client group
    """
    from .models import ClientGroup, Client
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    if request.method == 'GET':
        groups = ClientGroup.objects.filter(org=org).annotate(
            num_clients=Count('clients')  # ← Changed name
        ).prefetch_related('clients', 'default_assignees').order_by('name')

        data = []
        for group in groups:
            data.append({
                'id': group.id,
                'name': group.name,
                'description': group.description,
                'color': group.color,
                'icon': group.icon,
                'client_count': group.num_clients,  # ← Use the new name here
                'client_ids': list(group.clients.values_list('id', flat=True)),
                'default_assignee_ids': list(group.default_assignees.values_list('id', flat=True)),
                'created_at': group.created_at.isoformat(),
            })
        
        return Response({
            'groups': data,
            'total': len(data),
        })
    
    elif request.method == 'POST':
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'error': 'Name is required'}, status=400)
        
        # Check for duplicate
        if ClientGroup.objects.filter(org=org, name__iexact=name).exists():
            return Response({'error': f'Group "{name}" already exists'}, status=409)
        
        group = ClientGroup.objects.create(
            org=org,
            name=name,
            description=request.data.get('description', ''),
            color=request.data.get('color', 'slate'),
            icon=request.data.get('icon', 'folder'),
            created_by=request.user,
        )
        
        # Add clients if provided
        client_ids = request.data.get('client_ids', [])
        if client_ids:
            clients = Client.objects.filter(org=org, id__in=client_ids)
            group.clients.set(clients)
        
        # Add default assignees if provided
        assignee_ids = request.data.get('default_assignee_ids', [])
        if assignee_ids:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            users = User.objects.filter(id__in=assignee_ids)
            group.default_assignees.set(users)
        
        return Response({
            'id': group.id,
            'name': group.name,
            'description': group.description,
            'color': group.color,
            'icon': group.icon,
            'client_count': group.clients.count(),
            'client_ids': list(group.clients.values_list('id', flat=True)),
            'default_assignee_ids': list(group.default_assignees.values_list('id', flat=True)),
        }, status=201)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def client_groups_detail(request, group_id):
    """
    GET: Get group details with all clients
    PUT/PATCH: Update group
    DELETE: Delete group (doesn't delete clients)
    """
    from .models import ClientGroup, Client
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    try:
        group = ClientGroup.objects.prefetch_related('clients', 'default_assignees').get(
            id=group_id, org=org
        )
    except ClientGroup.DoesNotExist:
        return Response({'error': 'Group not found'}, status=404)
    
    if request.method == 'GET':
        clients_data = [{
            'id': c.id,
            'name': c.name,
            'code': c.code,
            'is_active': c.is_active,
        } for c in group.clients.all()]
        
        return Response({
            'id': group.id,
            'name': group.name,
            'description': group.description,
            'color': group.color,
            'icon': group.icon,
            'client_count': len(clients_data),
            'clients': clients_data,
            'client_ids': [c['id'] for c in clients_data],
            'default_assignee_ids': list(group.default_assignees.values_list('id', flat=True)),
            'created_at': group.created_at.isoformat(),
        })
    
    elif request.method in ['PUT', 'PATCH']:
        if 'name' in request.data:
            new_name = request.data['name'].strip()
            # Check for duplicate (excluding self)
            if ClientGroup.objects.filter(org=org, name__iexact=new_name).exclude(id=group.id).exists():
                return Response({'error': f'Group "{new_name}" already exists'}, status=409)
            group.name = new_name
        
        if 'description' in request.data:
            group.description = request.data['description']
        if 'color' in request.data:
            group.color = request.data['color']
        if 'icon' in request.data:
            group.icon = request.data['icon']
        
        group.save()
        
        # Update clients if provided
        if 'client_ids' in request.data:
            clients = Client.objects.filter(org=org, id__in=request.data['client_ids'])
            group.clients.set(clients)
        
        # Update default assignees if provided
        if 'default_assignee_ids' in request.data:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            users = User.objects.filter(id__in=request.data['default_assignee_ids'])
            group.default_assignees.set(users)
        
        return Response({
            'id': group.id,
            'name': group.name,
            'description': group.description,
            'color': group.color,
            'icon': group.icon,
            'client_count': group.clients.count(),
            'client_ids': list(group.clients.values_list('id', flat=True)),
            'default_assignee_ids': list(group.default_assignees.values_list('id', flat=True)),
        })
    
    elif request.method == 'DELETE':
        group_name = group.name
        group.delete()
        return Response({
            'success': True,
            'message': f'Group "{group_name}" deleted',
        })


# ============================================================================
# BULK OPERATIONS
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_groups_add_clients(request, group_id):
    """
    Add clients to a group (without removing existing ones)
    POST body: { "client_ids": [1, 2, 3] }
    """
    from .models import ClientGroup, Client
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    try:
        group = ClientGroup.objects.get(id=group_id, org=org)
    except ClientGroup.DoesNotExist:
        return Response({'error': 'Group not found'}, status=404)
    
    client_ids = request.data.get('client_ids', [])
    if not client_ids:
        return Response({'error': 'client_ids required'}, status=400)
    
    clients = Client.objects.filter(org=org, id__in=client_ids)
    
    # Add to group (won't duplicate)
    existing_count = group.clients.count()
    group.clients.add(*clients)
    new_count = group.clients.count()
    added = new_count - existing_count
    
    return Response({
        'success': True,
        'added': added,
        'total_clients': new_count,
        'message': f'Added {added} client(s) to "{group.name}"',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_groups_remove_clients(request, group_id):
    """
    Remove clients from a group
    POST body: { "client_ids": [1, 2, 3] }
    """
    from .models import ClientGroup, Client
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    try:
        group = ClientGroup.objects.get(id=group_id, org=org)
    except ClientGroup.DoesNotExist:
        return Response({'error': 'Group not found'}, status=404)
    
    client_ids = request.data.get('client_ids', [])
    if not client_ids:
        return Response({'error': 'client_ids required'}, status=400)
    
    clients = Client.objects.filter(org=org, id__in=client_ids)
    
    before_count = group.clients.count()
    group.clients.remove(*clients)
    after_count = group.clients.count()
    removed = before_count - after_count
    
    return Response({
        'success': True,
        'removed': removed,
        'total_clients': after_count,
        'message': f'Removed {removed} client(s) from "{group.name}"',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_groups_assign_team(request, group_id):
    """
    Assign team members to ALL clients in a group.
    This is the key feature for bulk assignment!
    
    POST body: { 
        "user_ids": [1, 2, 3],
        "mode": "add" | "replace"  // optional, default "add"
    }
    """
    from .models import ClientGroup, ClientAssignment
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    try:
        group = ClientGroup.objects.prefetch_related('clients').get(id=group_id, org=org)
    except ClientGroup.DoesNotExist:
        return Response({'error': 'Group not found'}, status=404)
    
    user_ids = request.data.get('user_ids', [])
    if not user_ids:
        return Response({'error': 'user_ids required'}, status=400)
    
    mode = request.data.get('mode', 'add')  # 'add' or 'replace'
    
    clients = list(group.clients.all())
    if not clients:
        return Response({
            'error': 'No clients in this group',
            'client_count': 0,
        }, status=400)
    
    created = 0
    updated = 0
    deleted = 0
    
    with transaction.atomic():
        for client in clients:
            if mode == 'replace':
                # Remove existing assignments for this client
                deleted_count, _ = ClientAssignment.objects.filter(
                    org=org, client=client
                ).exclude(user_id__in=user_ids).delete()
                deleted += deleted_count
            
            # Add new assignments
            for user_id in user_ids:
                assignment, was_created = ClientAssignment.objects.get_or_create(
                    org=org,
                    client=client,
                    user_id=user_id,
                    defaults={'assigned_by': request.user}
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
    
    return Response({
        'success': True,
        'group_name': group.name,
        'clients_affected': len(clients),
        'users_assigned': len(user_ids),
        'assignments_created': created,
        'assignments_updated': updated,
        'assignments_removed': deleted if mode == 'replace' else 0,
        'mode': mode,
        'message': f'Assigned {len(user_ids)} user(s) to {len(clients)} client(s) in "{group.name}"',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_groups_remove_team(request, group_id):
    """
    Remove team members from ALL clients in a group.
    
    POST body: { "user_ids": [1, 2, 3] }
    If user_ids is empty, removes ALL assignments.
    """
    from .models import ClientGroup, ClientAssignment
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    try:
        group = ClientGroup.objects.prefetch_related('clients').get(id=group_id, org=org)
    except ClientGroup.DoesNotExist:
        return Response({'error': 'Group not found'}, status=404)
    
    user_ids = request.data.get('user_ids', [])
    
    client_ids = list(group.clients.values_list('id', flat=True))
    if not client_ids:
        return Response({'error': 'No clients in this group'}, status=400)
    
    query = ClientAssignment.objects.filter(org=org, client_id__in=client_ids)
    
    if user_ids:
        # Remove specific users
        query = query.filter(user_id__in=user_ids)
    
    deleted_count, _ = query.delete()
    
    return Response({
        'success': True,
        'group_name': group.name,
        'assignments_removed': deleted_count,
        'message': f'Removed {deleted_count} assignment(s) from clients in "{group.name}"',
    })


# ============================================================================
# IMPORT CSV WITH GROUPS
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def client_groups_import_csv(request):
    """
    Import client-to-group mappings from CSV.
    
    Expected CSV format:
    client_code,group_name
    ACME,Partner: Smith
    BIGCO,Partner: Smith
    NEWCORP,Tax Clients
    
    Creates groups if they don't exist.
    """
    from .models import ClientGroup, Client
    import csv
    import io
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    csv_content = request.data.get('csv_content', '')
    if not csv_content:
        return Response({'error': 'csv_content required'}, status=400)
    
    try:
        reader = csv.DictReader(io.StringIO(csv_content))
        
        # Normalize headers
        if reader.fieldnames:
            reader.fieldnames = [h.lower().strip().replace(' ', '_') for h in reader.fieldnames]
        
        # Build lookups
        clients_by_code = {
            c.code.upper(): c 
            for c in Client.objects.filter(org=org, code__isnull=False) 
            if c.code
        }
        
        groups_cache = {}  # name -> ClientGroup
        
        created_groups = 0
        assignments_made = 0
        errors = []
        
        with transaction.atomic():
            for row_num, row in enumerate(reader, start=2):
                client_code = (row.get('client_code') or row.get('code') or '').strip().upper()
                group_name = (row.get('group_name') or row.get('group') or '').strip()
                
                if not client_code or not group_name:
                    errors.append(f'Row {row_num}: Missing client_code or group_name')
                    continue
                
                # Find client
                client = clients_by_code.get(client_code)
                if not client:
                    errors.append(f'Row {row_num}: Client code "{client_code}" not found')
                    continue
                
                # Get or create group
                if group_name not in groups_cache:
                    group, was_created = ClientGroup.objects.get_or_create(
                        org=org,
                        name=group_name,
                        defaults={'created_by': request.user}
                    )
                    groups_cache[group_name] = group
                    if was_created:
                        created_groups += 1
                else:
                    group = groups_cache[group_name]
                
                # Add client to group
                if not group.clients.filter(id=client.id).exists():
                    group.clients.add(client)
                    assignments_made += 1
        
        return Response({
            'success': True,
            'groups_created': created_groups,
            'assignments_made': assignments_made,
            'errors': errors[:20],
            'total_errors': len(errors),
        })
    
    except Exception as e:
        return Response({'error': f'Failed to parse CSV: {str(e)}'}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def client_groups_template(request):
    """Download CSV template for group import"""
    from .models import Client
    from django.http import HttpResponse
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    # Generate template with existing clients
    clients = Client.objects.filter(org=org, code__isnull=False).order_by('name')[:50]
    
    lines = ['client_code,group_name']
    for client in clients:
        if client.code:
            lines.append(f'{client.code},')  # Empty group for them to fill in
    
    # Add example
    if not clients:
        lines.append('ACME,Partner: Smith')
        lines.append('BIGCO,Tax Clients')
    
    content = '\n'.join(lines)
    
    response = HttpResponse(content, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="client_groups_template.csv"'
    return response


# ============================================================================
# UNGROUPED CLIENTS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ungrouped_clients(request):
    """
    Get all clients that aren't in any group.
    Useful for finding clients that need to be organized.
    """
    from .models import Client, ClientGroup
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    # Get all client IDs that ARE in groups
    grouped_client_ids = set()
    for group in ClientGroup.objects.filter(org=org).prefetch_related('clients'):
        grouped_client_ids.update(group.clients.values_list('id', flat=True))
    
    # Get clients NOT in that set
    ungrouped = Client.objects.filter(org=org).exclude(id__in=grouped_client_ids)
    
    data = [{
        'id': c.id,
        'name': c.name,
        'code': c.code,
        'is_active': c.is_active,
    } for c in ungrouped.order_by('name')]
    
    return Response({
        'clients': data,
        'count': len(data),
    })