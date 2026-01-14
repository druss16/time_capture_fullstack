# tracker/views_bulk_assignment.py
"""
Bulk Assignment & CSV Import for Client-Employee Assignments
"""

import csv
import io
import logging
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from .models import Client, ClientAssignment, OrganizationMembership

logger = logging.getLogger(__name__)


def get_user_org(user):
    """Get the user's organization."""
    membership = OrganizationMembership.objects.filter(user=user).select_related('organization').first()
    return membership.organization if membership else None


# ============================================================================
# Bulk Assignment
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_assign_clients(request):
    """
    Bulk assign employees to multiple clients.
    
    Request body:
    {
        "client_ids": [1, 2, 3],
        "user_ids": [10, 11, 12],
        "role": "Staff",  // optional, default "Staff"
        "mode": "add"     // "add" (keep existing) or "replace" (remove existing first)
    }
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    client_ids = request.data.get('client_ids', [])
    user_ids = request.data.get('user_ids', [])
    role = request.data.get('role', 'Staff')
    mode = request.data.get('mode', 'add')  # 'add' or 'replace'
    
    if not client_ids:
        return Response({'error': 'No clients selected'}, status=400)
    if not user_ids:
        return Response({'error': 'No employees selected'}, status=400)
    
    # Validate clients belong to org
    clients = Client.objects.filter(id__in=client_ids, org=org)
    if clients.count() != len(client_ids):
        return Response({'error': 'Some clients not found or not in your organization'}, status=400)
    
    # Validate users belong to org
    valid_user_ids = set(
        OrganizationMembership.objects.filter(
            organization=org, 
            user_id__in=user_ids
        ).values_list('user_id', flat=True)
    )
    
    if len(valid_user_ids) != len(user_ids):
        return Response({'error': 'Some employees not found or not in your organization'}, status=400)
    
    created_count = 0
    skipped_count = 0
    removed_count = 0
    
    with transaction.atomic():
        for client in clients:
            # If replace mode, remove existing assignments first
            if mode == 'replace':
                removed = ClientAssignment.objects.filter(client=client).delete()[0]
                removed_count += removed
            
            for user_id in user_ids:
                # Check if assignment already exists
                existing = ClientAssignment.objects.filter(
                    client=client,
                    user_id=user_id
                ).first()
                
                if existing:
                    # Update role if different
                    if existing.role != role:
                        existing.role = role
                        existing.save(update_fields=['role'])
                    skipped_count += 1
                else:
                    # Create new assignment
                    ClientAssignment.objects.create(
                        organization=org,        # From request.user's membership
                        client=client,
                        user=user,
                        role=role,              # Make sure this matches ROLE_CHOICES
                        assigned_by=request.user,
                    )
                    created_count += 1
    
    return Response({
        'success': True,
        'created': created_count,
        'updated': skipped_count,
        'removed': removed_count if mode == 'replace' else 0,
        'summary': f"Assigned {len(user_ids)} employees to {len(client_ids)} clients"
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_unassign_clients(request):
    """
    Bulk remove employee assignments from multiple clients.
    
    Request body:
    {
        "client_ids": [1, 2, 3],
        "user_ids": [10, 11, 12]  // optional - if not provided, removes ALL assignments
    }
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    client_ids = request.data.get('client_ids', [])
    user_ids = request.data.get('user_ids', [])
    
    if not client_ids:
        return Response({'error': 'No clients selected'}, status=400)
    
    # Validate clients belong to org
    clients = Client.objects.filter(id__in=client_ids, org=org)
    
    with transaction.atomic():
        if user_ids:
            # Remove specific user assignments
            deleted = ClientAssignment.objects.filter(
                client__in=clients,
                user_id__in=user_ids
            ).delete()[0]
        else:
            # Remove ALL assignments for these clients
            deleted = ClientAssignment.objects.filter(client__in=clients).delete()[0]
    
    return Response({
        'success': True,
        'removed': deleted,
        'summary': f"Removed {deleted} assignments from {len(client_ids)} clients"
    })


# ============================================================================
# CSV Import for Assignments
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def assignment_csv_template(request):
    """
    Return a CSV template for bulk assignment import.
    """
    template = """client_name,employee_email,role
Acme Corporation,john@yourfirm.com,Partner
Acme Corporation,jane@yourfirm.com,Manager
Acme Corporation,bob@yourfirm.com,Staff
Another Client,john@yourfirm.com,Partner
Another Client,sarah@yourfirm.com,Staff"""
    
    return Response({
        'template': template,
        'instructions': {
            'client_name': 'Exact client name as it appears in TimeTracker (required)',
            'employee_email': 'Employee email address (required)',
            'role': 'Role on engagement: Partner, Manager, Senior, Staff, Admin (optional, defaults to Staff)',
        },
        'valid_roles': ['Partner', 'Manager', 'Senior', 'Staff', 'Admin'],
        'notes': [
            'Client names must match exactly (case-insensitive)',
            'Employees must already exist in your organization',
            'Duplicate assignments will be skipped',
            'Invalid rows will be reported but won\'t stop the import',
        ]
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def import_assignments_csv(request):
    """
    Import client-employee assignments from CSV file.
    
    CSV format:
    client_name,employee_email,role
    Acme Corp,john@firm.com,Partner
    Acme Corp,jane@firm.com,Manager
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    csv_file = request.FILES.get('file')
    if not csv_file:
        return Response({'error': 'No file provided'}, status=400)
    
    # Check file type
    if not csv_file.name.endswith('.csv'):
        return Response({'error': 'File must be a CSV'}, status=400)
    
    # Read and decode file
    try:
        decoded_file = csv_file.read().decode('utf-8-sig')  # utf-8-sig handles BOM
    except UnicodeDecodeError:
        try:
            csv_file.seek(0)
            decoded_file = csv_file.read().decode('latin-1')
        except:
            return Response({'error': 'Unable to read file. Please ensure it\'s a valid CSV.'}, status=400)
    
    # Parse CSV
    reader = csv.DictReader(io.StringIO(decoded_file))
    
    # Validate headers
    required_headers = {'client_name', 'employee_email'}
    if not required_headers.issubset(set(reader.fieldnames or [])):
        return Response({
            'error': f'Missing required columns. Required: {required_headers}. Found: {reader.fieldnames}'
        }, status=400)
    
    # Build lookup caches
    # Client lookup (case-insensitive)
    clients_by_name = {
        c.name.lower(): c 
        for c in Client.objects.filter(org=org)
    }
    
    # User lookup by email
    org_members = OrganizationMembership.objects.filter(
        organization=org
    ).select_related('user')
    
    users_by_email = {
        m.user.email.lower(): m.user 
        for m in org_members if m.user.email
    }
    
    # Also lookup by username in case email isn't set
    users_by_username = {
        m.user.username.lower(): m.user 
        for m in org_members
    }
    
    # Valid roles
    valid_roles = {'partner', 'manager', 'senior', 'staff', 'admin'}
    
    # Process rows
    results = {
        'created': [],
        'updated': [],
        'skipped': [],
        'errors': [],
    }
    
    row_num = 1  # Start at 1 (after header)
    
    with transaction.atomic():
        for row in reader:
            row_num += 1
            
            client_name = (row.get('client_name') or '').strip()
            employee_email = (row.get('employee_email') or '').strip()
            role = (row.get('role') or 'Staff').strip()
            
            # Skip empty rows
            if not client_name and not employee_email:
                continue
            
            # Validate client
            if not client_name:
                results['errors'].append({
                    'row': row_num,
                    'error': 'Missing client_name',
                    'data': row
                })
                continue
            
            client = clients_by_name.get(client_name.lower())
            if not client:
                results['errors'].append({
                    'row': row_num,
                    'error': f'Client "{client_name}" not found',
                    'data': row
                })
                continue
            
            # Validate employee
            if not employee_email:
                results['errors'].append({
                    'row': row_num,
                    'error': 'Missing employee_email',
                    'data': row
                })
                continue
            
            user = users_by_email.get(employee_email.lower())
            if not user:
                # Try username lookup
                user = users_by_username.get(employee_email.lower())
            
            if not user:
                results['errors'].append({
                    'row': row_num,
                    'error': f'Employee "{employee_email}" not found in organization',
                    'data': row
                })
                continue
            
            # Validate role
            normalized_role = role.title()  # "partner" -> "Partner"
            if role.lower() not in valid_roles:
                normalized_role = 'Staff'  # Default to Staff if invalid
            
            # Check for existing assignment
            existing = ClientAssignment.objects.filter(
                client=client,
                user=user
            ).first()
            
            if existing:
                if existing.role != normalized_role:
                    existing.role = normalized_role
                    existing.save(update_fields=['role'])
                    results['updated'].append({
                        'row': row_num,
                        'client': client.name,
                        'employee': user.email or user.username,
                        'role': normalized_role
                    })
                else:
                    results['skipped'].append({
                        'row': row_num,
                        'client': client.name,
                        'employee': user.email or user.username,
                        'reason': 'Assignment already exists'
                    })
            else:
                ClientAssignment.objects.create(
                    client=client,
                    user=user,
                    role=normalized_role
                )
                results['created'].append({
                    'row': row_num,
                    'client': client.name,
                    'employee': user.email or user.username,
                    'role': normalized_role
                })
    
    return Response({
        'success': True,
        'summary': {
            'total_rows': row_num - 1,
            'created': len(results['created']),
            'updated': len(results['updated']),
            'skipped': len(results['skipped']),
            'errors': len(results['errors']),
        },
        'results': results
    })


# ============================================================================
# Copy Assignments Between Clients
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def copy_assignments(request):
    """
    Copy team assignments from one client to other clients.
    
    Request body:
    {
        "source_client_id": 1,
        "target_client_ids": [2, 3, 4],
        "mode": "add"  // "add" (keep existing) or "replace" (remove existing first)
    }
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    source_id = request.data.get('source_client_id')
    target_ids = request.data.get('target_client_ids', [])
    mode = request.data.get('mode', 'add')
    
    if not source_id:
        return Response({'error': 'No source client specified'}, status=400)
    if not target_ids:
        return Response({'error': 'No target clients specified'}, status=400)
    
    # Get source client and its assignments
    try:
        source_client = Client.objects.get(id=source_id, org=org)
    except Client.DoesNotExist:
        return Response({'error': 'Source client not found'}, status=404)
    
    source_assignments = ClientAssignment.objects.filter(client=source_client)
    
    if not source_assignments.exists():
        return Response({'error': 'Source client has no team assignments to copy'}, status=400)
    
    # Get target clients
    target_clients = Client.objects.filter(id__in=target_ids, org=org)
    
    created_count = 0
    skipped_count = 0
    removed_count = 0
    
    with transaction.atomic():
        for target_client in target_clients:
            if target_client.id == source_id:
                continue  # Skip if same as source
            
            if mode == 'replace':
                removed = ClientAssignment.objects.filter(client=target_client).delete()[0]
                removed_count += removed
            
            for assignment in source_assignments:
                existing = ClientAssignment.objects.filter(
                    client=target_client,
                    user=assignment.user
                ).first()
                
                if existing:
                    if existing.role != assignment.role:
                        existing.role = assignment.role
                        existing.save(update_fields=['role'])
                    skipped_count += 1
                else:
                    ClientAssignment.objects.create(
                        client=target_client,
                        user=assignment.user,
                        role=assignment.role
                    )
                    created_count += 1
    
    return Response({
        'success': True,
        'created': created_count,
        'updated': skipped_count,
        'removed': removed_count if mode == 'replace' else 0,
        'summary': f"Copied {source_assignments.count()} team members to {target_clients.count()} clients"
    })