# tracker/views_settings.py - Add these

from .models import ClientAssignment
from django.db import IntegrityError
from rest_framework.views import APIView  # ← ADD THIS LINE
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView  # ← ADD THIS LINE
from django.db.models import Sum, F, Q, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import timedelta, date
from decimal import Decimal
from .models import (
    BillingRate, Timesheet, Block, BlockAuditLog, 
    Client, TaskType, Organization, OrganizationMembership,
    EmployeeCostRate, Invitation  # ← ADD THIS
)
from .serializers_billing import (
    BillingRateSerializer, TimesheetSummarySerializer, TimesheetDetailSerializer,
    ApprovalQueueItemSerializer, ClientSummarySerializer, BlockAuditLogSerializer,
    InvoiceExportSerializer,
    EmployeeCostRateSerializer,  # ← ADD THIS
)

from rest_framework.response import Response
from functools import wraps  # Add this import

from django.conf import settings
import stripe

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_clients(request):
    """Get clients visible to the current user (for dropdowns)."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    clients = get_visible_clients(request.user, org).values(
        'id', 'name', 'code', 'visibility'
    ).order_by('name')
    
    return Response(list(clients))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def client_assignments_list(request):
    """
    GET: List all client assignments (admin only)
    POST: Create new assignment (admin only)
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    
    if not membership or membership.role not in ('owner', 'admin', 'manager'):
        return Response({'error': 'Permission denied'}, status=403)
    
    if request.method == 'GET':
        # Optional filters
        client_id = request.query_params.get('client_id')
        user_id = request.query_params.get('user_id')
        
        assignments = ClientAssignment.objects.filter(
            organization=org
        ).select_related('client', 'user', 'assigned_by')
        
        if client_id:
            assignments = assignments.filter(client_id=client_id)
        if user_id:
            assignments = assignments.filter(user_id=user_id)
        
        result = []
        for a in assignments:
            result.append({
                'id': a.id,
                'client_id': a.client_id,
                'client_name': a.client.name,
                'client_code': a.client.code,
                'user_id': a.user_id,
                'user_name': f"{a.user.first_name} {a.user.last_name}".strip() or a.user.username,
                'user_email': a.user.email,
                'role': a.role,
                'assigned_at': a.assigned_at.isoformat(),
                'assigned_by': a.assigned_by.username if a.assigned_by else None,
            })
        
        return Response(result)
    
    elif request.method == 'POST':
        client_id = request.data.get('client_id')
        user_id = request.data.get('user_id')
        role = request.data.get('role', 'staff')
        
        if not client_id or not user_id:
            return Response({'error': 'client_id and user_id required'}, status=400)
        
        # Verify client belongs to org
        try:
            client = Client.objects.get(id=client_id, org=org)
        except Client.DoesNotExist:
            return Response({'error': 'Client not found'}, status=404)
        
        try:
            assignment = ClientAssignment.objects.create(
                organization=org,
                client_id=client_id,
                user_id=user_id,
                role=role,
                assigned_by=request.user,
            )
            
            return Response({
                'id': assignment.id,
                'client_id': assignment.client_id,
                'user_id': assignment.user_id,
                'role': assignment.role,
                'message': 'Assignment created',
            }, status=201)
            
        except IntegrityError:
            return Response({
                'error': 'duplicate',
                'message': 'User is already assigned to this client',
            }, status=409)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def client_assignment_delete(request, assignment_id):
    """Delete a client assignment."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    
    if not membership or membership.role not in ('owner', 'admin', 'manager'):
        return Response({'error': 'Permission denied'}, status=403)
    
    try:
        assignment = ClientAssignment.objects.get(id=assignment_id, organization=org)
        assignment.delete()
        return Response({'success': True, 'message': 'Assignment removed'})
    except ClientAssignment.DoesNotExist:
        return Response({'error': 'Assignment not found'}, status=404)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_assign_clients(request):
    """
    Bulk assign multiple clients to multiple users.
    
    Body:
    {
        "client_ids": [1, 2, 3],
        "user_ids": [10, 11, 12],
        "role": "staff"
    }
    
    OR copy from another user:
    {
        "copy_from_user_id": 5,
        "to_user_ids": [10, 11, 12]
    }
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
    
    # Option 1: Direct assignment
    client_ids = request.data.get('client_ids', [])
    user_ids = request.data.get('user_ids', [])
    role = request.data.get('role', 'staff')
    
    # Option 2: Copy from user
    copy_from_user_id = request.data.get('copy_from_user_id')
    to_user_ids = request.data.get('to_user_ids', [])
    
    created = 0
    skipped = 0
    
    if copy_from_user_id and to_user_ids:
        # Copy assignments from one user to others
        source_assignments = ClientAssignment.objects.filter(
            organization=org,
            user_id=copy_from_user_id
        )
        
        for assignment in source_assignments:
            for user_id in to_user_ids:
                if user_id == copy_from_user_id:
                    continue
                try:
                    ClientAssignment.objects.create(
                        organization=org,
                        client_id=assignment.client_id,
                        user_id=user_id,
                        role=assignment.role,
                        assigned_by=request.user,
                    )
                    created += 1
                except IntegrityError:
                    skipped += 1
    
    elif client_ids and user_ids:
        # Direct bulk assignment
        for client_id in client_ids:
            # Verify client belongs to org
            if not Client.objects.filter(id=client_id, org=org).exists():
                continue
            
            for user_id in user_ids:
                try:
                    ClientAssignment.objects.create(
                        organization=org,
                        client_id=client_id,
                        user_id=user_id,
                        role=role,
                        assigned_by=request.user,
                    )
                    created += 1
                except IntegrityError:
                    skipped += 1
    
    else:
        return Response({
            'error': 'Provide either (client_ids + user_ids) or (copy_from_user_id + to_user_ids)'
        }, status=400)
    
    return Response({
        'success': True,
        'created': created,
        'skipped_duplicates': skipped,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_client_assignments_csv(request):
    """
    Import client assignments from CSV.
    
    Expected CSV format:
    user_email,client_code,role
    john@firm.com,ACME,staff
    jane@firm.com,ACME,lead
    jane@firm.com,BIGCO,manager
    """
    import csv
    from io import StringIO
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
    
    csv_content = request.data.get('csv_content', '')
    if not csv_content:
        return Response({'error': 'csv_content required'}, status=400)
    
    # Parse CSV
    reader = csv.DictReader(StringIO(csv_content))
    
    # Build lookup caches
    users_by_email = {
        m.user.email.lower(): m.user 
        for m in OrganizationMembership.objects.filter(organization=org).select_related('user')
        if m.user.email
    }
    
    clients_by_code = {
        c.code.upper(): c 
        for c in Client.objects.filter(org=org)
        if c.code
    }
    
    created = 0
    skipped = 0
    errors = []
    
    for i, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
        email = (row.get('user_email') or '').strip().lower()
        code = (row.get('client_code') or '').strip().upper()
        role = (row.get('role') or 'staff').strip().lower()
        
        if not email or not code:
            errors.append(f"Row {i}: Missing email or client_code")
            continue
        
        user = users_by_email.get(email)
        if not user:
            errors.append(f"Row {i}: User not found: {email}")
            continue
        
        client = clients_by_code.get(code)
        if not client:
            errors.append(f"Row {i}: Client not found: {code}")
            continue
        
        if role not in ('lead', 'manager', 'staff', 'reviewer'):
            role = 'staff'
        
        try:
            ClientAssignment.objects.create(
                organization=org,
                client=client,
                user=user,
                role=role,
                assigned_by=request.user,
            )
            created += 1
        except IntegrityError:
            skipped += 1
    
    return Response({
        'success': True,
        'created': created,
        'skipped_duplicates': skipped,
        'errors': errors[:20],  # Limit error messages
        'total_errors': len(errors),
    })