# tracker/views_settings.py - Client Assignment endpoints

import csv
from io import StringIO
from django.db import IntegrityError
from django.db.models import Q, Exists, OuterRef
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ClientRequest, Client, Organization, OrganizationMembership, ClientAssignment


def get_request_org_override_settings(request):
    from tracker.models import Organization
    override_id = request.GET.get("org_id")
    if override_id and (request.user.is_staff or request.user.is_superuser):
        try:
            return Organization.objects.get(id=int(override_id))
        except (Organization.DoesNotExist, ValueError, TypeError):
            pass
    return get_user_org(request.user)


def get_user_org(user):
    """Helper to get user's organization."""
    membership = OrganizationMembership.objects.filter(user=user).select_related('organization').first()
    return membership.organization if membership else None


def get_visible_clients(user, org):
    """
    Returns queryset of clients visible to this user.
    """
    membership = OrganizationMembership.objects.filter(user=user, organization=org).first()
    if not membership:
        return Client.objects.none()
    
    role = membership.role
    base_qs = Client.objects.filter(org=org, is_active=True)
    
    user_assignments = ClientAssignment.objects.filter(user=user, client=OuterRef('pk'))
    
    if role in ('owner', 'admin'):
        # Admins see everything except confidential without assignment
        return base_qs.filter(
            Q(visibility__in=['all', 'assigned']) |
            Q(visibility='confidential', pk__in=ClientAssignment.objects.filter(user=user).values('client_id')) |
            Q(visibility__isnull=True)
        )
    else:
        # Managers/Members see 'all' + their assignments
        return base_qs.filter(
            Q(visibility='all') |
            Q(visibility__isnull=True) |
            Exists(user_assignments)
        )


# ============================================================================
# Client Assignment Endpoints
# ============================================================================

# views_settings.py - Add this function

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_clients(request):
    """Get clients visible to the current user (for dropdowns)."""
    org = get_request_org_override_settings(request)
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
    GET: List all client assignments
    POST: Create new assignment(s)
    """
    org = get_request_org_override_settings(request)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    membership = OrganizationMembership.objects.filter(user=request.user, organization=org).first()
    if not membership or membership.role not in ('owner', 'admin', 'manager'):
        return Response({'error': 'Permission denied'}, status=403)
    
    if request.method == 'GET':
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
                'client_code': getattr(a.client, 'code', '') or '',
                'user_id': a.user_id,
                'user_name': f"{a.user.first_name} {a.user.last_name}".strip() or a.user.username,
                'user_email': a.user.email,
                'role': a.role,  # Will be null if not set
                'assigned_at': a.assigned_at.isoformat(),
                'assigned_by': a.assigned_by.username if a.assigned_by else None,
            })
        
        return Response(result)
    
    elif request.method == 'POST':
        client_id = request.data.get('client_id')
        user_id = request.data.get('user_id')
        role = request.data.get('role')  # Optional now
        
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
                role=role if role else None,  # Optional
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
    org = get_request_org_override_settings(request)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    membership = OrganizationMembership.objects.filter(user=request.user, organization=org).first()
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
    Bulk assign clients to users.
    
    Option 1 - Direct assignment:
    {
        "client_ids": [1, 2, 3],
        "user_ids": [10, 11, 12]
    }
    
    Option 2 - Copy from another user:
    {
        "copy_from_user_id": 5,
        "to_user_ids": [10, 11, 12]
    }
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    membership = OrganizationMembership.objects.filter(user=request.user, organization=org).first()
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
    
    # Option 1: Direct assignment
    client_ids = request.data.get('client_ids', [])
    user_ids = request.data.get('user_ids', [])
    
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
            if not Client.objects.filter(id=client_id, org=org).exists():
                continue
            
            for user_id in user_ids:
                try:
                    ClientAssignment.objects.create(
                        organization=org,
                        client_id=client_id,
                        user_id=user_id,
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


# views_settings.py - Update import_client_assignments_csv

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_client_assignments_csv(request):
    """Import client assignments from CSV."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    membership = OrganizationMembership.objects.filter(user=request.user, organization=org).first()
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
    
    csv_content = request.data.get('csv_content', '')
    if not csv_content or not csv_content.strip():
        return Response({
            'error': 'csv_content required',
            'message': 'Please paste CSV content with email and client_code columns'
        }, status=400)
    
    # Clean up the content
    csv_content = csv_content.strip()
    lines = csv_content.split('\n')
    
    if not lines:
        return Response({'error': 'CSV is empty'}, status=400)
    
    # Check if first line looks like a header or data
    first_line = lines[0].strip().lower()
    known_headers = ['email', 'user_email', 'user', 'client', 'client_code', 'code', 'employee']
    has_header = any(h in first_line for h in known_headers)
    
    # If no header detected, add a default header
    if not has_header:
        csv_content = "email,client_code\n" + csv_content
    
    # Parse CSV
    try:
        reader = csv.DictReader(StringIO(csv_content))
        rows = list(reader)
    except Exception as e:
        return Response({
            'error': 'Invalid CSV format',
            'message': str(e)
        }, status=400)
    
    if not rows:
        return Response({
            'error': 'CSV is empty',
            'message': 'No data rows found in CSV.'
        }, status=400)
    
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
    
    clients_by_name = {
        c.name.lower(): c 
        for c in Client.objects.filter(org=org)
    }
    
    created = 0
    skipped = 0
    errors = []
    
    def get_value(row, possible_names, default=''):
        for name in possible_names:
            if name in row and row[name]:
                return row[name].strip()
        return default
    
    for i, row in enumerate(rows, start=2):
        email = get_value(row, ['user_email', 'email', 'Email', 'user', 'User', 'employee', 'Employee']).lower()
        client_ref = get_value(row, ['client_code', 'client', 'Client', 'code', 'Code', 'client_name', 'Client Name'])
        
        if not email or not client_ref:
            errors.append(f"Row {i}: Missing email or client")
            continue
        
        user = users_by_email.get(email)
        if not user:
            errors.append(f"Row {i}: User not found: {email}")
            continue
        
        client = clients_by_code.get(client_ref.upper()) or clients_by_name.get(client_ref.lower())
        if not client:
            errors.append(f"Row {i}: Client not found: {client_ref}")
            continue
        
        try:
            ClientAssignment.objects.create(
                organization=org,
                client=client,
                user=user,
                assigned_by=request.user,
            )
            created += 1
        except IntegrityError:
            skipped += 1
    
    return Response({
        'success': True,
        'created': created,
        'skipped_duplicates': skipped,
        'errors': errors[:20],
        'total_errors': len(errors),
    })


# tracker/views_settings.py - Add this

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def client_requests(request):
    """
    GET: List pending client requests (admin only)
    POST: Submit a new client request (any user)
    """
    org = get_request_org_override_settings(request)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    if request.method == 'POST':
        # Accept both 'name' and 'client_name' for compatibility
        name = request.data.get('name', '') or request.data.get('client_name', '')
        name = name.strip()
        notes = request.data.get('notes', '').strip()
        
        if not name:
            return Response({'error': 'Client name required'}, status=400)
        
        client_request = ClientRequest.objects.create(
            organization=org,
            requested_by=request.user,
            client_name=name,  # Model field is client_name
            notes=notes,
        )
        
        return Response({
            'success': True,
            'message': 'Request submitted',
            'id': client_request.id,
        }, status=201)
    
    # GET - Admin only
    membership = OrganizationMembership.objects.filter(user=request.user, organization=org).first()
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
    
    requests = ClientRequest.objects.filter(
        organization=org,
        status='pending'
    ).select_related('requested_by').order_by('-created_at')
    
    return Response([{
        'id': r.id,
        'client_name': r.client_name,
        'notes': r.notes,
        'requested_by': r.requested_by.username,
        'requested_by_email': r.requested_by.email,
        'created_at': r.created_at.isoformat(),
    } for r in requests])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_client_request(request, request_id):
    """Approve a client request and create the client."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    membership = OrganizationMembership.objects.filter(user=request.user, organization=org).first()
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)
    
    try:
        client_request = ClientRequest.objects.get(id=request_id, organization=org)
    except ClientRequest.DoesNotExist:
        return Response({'error': 'Request not found'}, status=404)
    
    # Create the client
    code = request.data.get('code', client_request.client_name[:4].upper().replace(' ', ''))
    visibility = request.data.get('visibility', 'all')
    
    client = Client.objects.create(
        org=org,
        name=client_request.client_name,
        code=code,
        visibility=visibility,
    )
    
    # Assign the requester to the client
    ClientAssignment.objects.create(
        organization=org,
        client=client,
        user=client_request.requested_by,
        assigned_by=request.user,
    )
    
    # Update request status
    client_request.status = 'approved'
    client_request.approved_by = request.user
    client_request.save()
    
    return Response({
        'success': True,
        'client_id': client.id,
        'client_name': client.name,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_economics_csv(request):
    """
    Import a team roster CSV to populate cost tiers + member assignments.

    Body: { csv_content: str, dry_run: bool (default True) }.
    Columns (case-insensitive, flexible aliases): email, tier, cost_rate,
    bill_rate, hours_per_week. OWNERS ONLY (the file carries salaries; see
    tracker/cost_visibility.py). When dry_run is true (the
    default) nothing is written — the endpoint returns a preview of the tiers
    to create/update, the people that will be assigned, and any unmatched rows.
    """
    from decimal import Decimal, InvalidOperation
    from django.db import transaction
    from .models import CostTier

    org = get_request_org_override_settings(request)
    if not org:
        return Response({'error': 'No organization found'}, status=404)

    from .cost_visibility import can_view_cost_data, cost_denied_response
    if not can_view_cost_data(request.user, org):
        return cost_denied_response()

    csv_content = (request.data.get('csv_content') or '').strip()
    dry_run = bool(request.data.get('dry_run', True))
    if not csv_content:
        return Response({'error': 'No CSV content provided'}, status=400)

    def _dec(v):
        if v is None:
            return None
        s = str(v).strip().replace('$', '').replace(',', '')
        if s == '':
            return None
        try:
            d = Decimal(s)
            return d if d >= 0 else None
        except (InvalidOperation, ValueError):
            return None

    def get_value(row, keys):
        for actual in row:
            if actual and actual.strip().lower() in keys:
                val = row[actual]
                return val.strip() if isinstance(val, str) else val
        return ''

    try:
        rows = list(csv.DictReader(StringIO(csv_content)))
    except Exception as e:  # noqa: BLE001
        return Response({'error': f'Could not parse CSV: {e}'}, status=400)
    if not rows:
        return Response({'error': 'CSV has no data rows'}, status=400)

    users_by_email = {
        m.user.email.lower(): m.user
        for m in OrganizationMembership.objects.filter(organization=org).select_related('user')
        if m.user.email
    }
    existing_tiers = {t.label.strip().lower(): t for t in CostTier.objects.filter(organization=org)}

    tier_defs = {}      # label_lower -> {label, cost_rate, bill_rate, hours_per_week}
    assignments = []    # {email, name, tier}
    unmatched = []      # {email, tier, reason}
    warnings = []

    for i, row in enumerate(rows, start=2):  # header is row 1
        email = (get_value(row, {'email', 'user_email', 'user', 'employee', 'employee_email'}) or '').strip().lower()
        tier_label = (get_value(row, {'tier', 'cost_tier', 'tier_name', 'level'}) or '').strip()
        cost = _dec(get_value(row, {'cost_rate', 'cost', 'cost $/hr', 'cost_$/hr', 'loaded_cost'}))
        bill = _dec(get_value(row, {'bill_rate', 'bill', 'bill $/hr', 'bill_$/hr', 'billing_rate'}))
        hours = _dec(get_value(row, {'hours_per_week', 'hrs/wk', 'hours', 'capacity'}))

        if not tier_label:
            warnings.append(f'Row {i}: no tier — skipped.')
            continue

        key = tier_label.lower()
        if key not in tier_defs:
            tier_defs[key] = {'label': tier_label, 'cost_rate': cost, 'bill_rate': bill, 'hours_per_week': hours}
        else:
            td = tier_defs[key]
            for field, value in (('cost_rate', cost), ('bill_rate', bill), ('hours_per_week', hours)):
                if value is not None:
                    if td[field] is None:
                        td[field] = value
                    elif td[field] != value:
                        warnings.append(f"Row {i}: {tier_label} {field} {value} differs from earlier {td[field]}; kept {td[field]}.")

        if email:
            user = users_by_email.get(email)
            if user:
                name = f"{user.first_name} {user.last_name}".strip() or user.username
                assignments.append({'email': email, 'name': name, 'tier': tier_label})
            else:
                unmatched.append({'email': email, 'tier': tier_label, 'reason': 'No team member with this email'})

    tiers_preview = []
    for key, td in tier_defs.items():
        if td['cost_rate'] is None and key not in existing_tiers:
            warnings.append(f"Tier '{td['label']}': no cost rate — will use firm default.")
        tiers_preview.append({
            'label': td['label'],
            'cost_rate': str(td['cost_rate']) if td['cost_rate'] is not None else None,
            'bill_rate': str(td['bill_rate']) if td['bill_rate'] is not None else None,
            'hours_per_week': str(td['hours_per_week']) if td['hours_per_week'] is not None else None,
            'action': 'update' if key in existing_tiers else 'create',
        })

    result = {
        'dry_run': dry_run,
        'tiers': tiers_preview,
        'assignments': assignments,
        'unmatched': unmatched,
        'warnings': warnings,
        'summary': {'tiers': len(tiers_preview), 'people': len(assignments), 'unmatched': len(unmatched)},
    }

    if dry_run:
        return Response(result)

    try:
        with transaction.atomic():
            org_default_cost = org.cost_rate_default or Decimal('75.00')
            label_to_tier = {}
            for key, td in tier_defs.items():
                existing = existing_tiers.get(key)
                cost_val = td['cost_rate']
                if cost_val is None:
                    cost_val = existing.cost_rate if existing else org_default_cost
                if existing:
                    existing.cost_rate = cost_val
                    if td['bill_rate'] is not None:
                        existing.bill_rate = td['bill_rate']
                    if td['hours_per_week'] is not None:
                        existing.hours_per_week = td['hours_per_week']
                    existing.save()
                    label_to_tier[key] = existing
                else:
                    label_to_tier[key] = CostTier.objects.create(
                        organization=org, label=td['label'], cost_rate=cost_val,
                        bill_rate=td['bill_rate'], hours_per_week=td['hours_per_week'],
                    )

            assigned = 0
            for a in assignments:
                user = users_by_email.get(a['email'])
                tier = label_to_tier.get(a['tier'].lower())
                if user and tier:
                    OrganizationMembership.objects.filter(organization=org, user=user).update(cost_tier=tier)
                    assigned += 1
    except Exception as e:  # noqa: BLE001
        return Response({'error': f'Import failed: {e}'}, status=400)

    result['applied'] = {'tiers': len(tier_defs), 'assigned': assigned}
    return Response(result)