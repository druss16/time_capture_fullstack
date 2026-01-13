# tracker/utils.py
from tracker.models import OrganizationMembership
# tracker/utils.py or in views

from django.db.models import Q, Exists, OuterRef
from .models import Client, ClientAssignment, OrganizationMembership

def get_user_org(user):
    """Get the user's Organization from OrganizationMembership."""
    try:
        membership = OrganizationMembership.objects.filter(user=user).first()
        if membership:
            return membership.organization
        return None
    except Exception as e:
        print(f"Error in get_user_org: {e}")
        return None

def get_user_membership(user):
    """Get user's membership with role info"""
    return OrganizationMembership.objects.select_related('organization').filter(user=user).first()

def require_role(roles):
    """Decorator to require specific roles"""
    from rest_framework.response import Response
    def decorator(view_func):
        def wrapped(request, *args, **kwargs):
            membership = get_user_membership(request.user)
            if not membership or membership.role not in roles:
                return Response({'error': 'Insufficient permissions'}, status=403)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator



def get_visible_clients(user, org):
    """
    Returns queryset of clients visible to this user.
    
    Rules:
    - Owners/Admins: See all clients (except 'confidential' without assignment)
    - Managers: See 'all' clients + their assignments
    - Members: See 'all' clients + their assignments
    
    For 'confidential' clients, even admins need explicit assignment.
    """
    membership = OrganizationMembership.objects.filter(
        user=user, organization=org
    ).first()
    
    if not membership:
        return Client.objects.none()
    
    role = membership.role
    
    # Base: all clients in org
    base_qs = Client.objects.filter(org=org, is_active=True)
    
    # Check if user is assigned to each client
    user_assignments = ClientAssignment.objects.filter(
        user=user,
        client=OuterRef('pk')
    )
    
    if role in ('owner', 'admin'):
        # Admins see everything EXCEPT confidential without assignment
        return base_qs.filter(
            Q(visibility__in=['all', 'assigned']) |
            Q(visibility='confidential', pk__in=ClientAssignment.objects.filter(user=user).values('client_id'))
        )
    
    elif role == 'manager':
        # Managers see 'all' visibility + their assignments
        return base_qs.filter(
            Q(visibility='all') |
            Exists(user_assignments)
        )
    
    else:
        # Members see 'all' visibility + their assignments
        return base_qs.filter(
            Q(visibility='all') |
            Exists(user_assignments)
        )

def get_visible_clients_for_dropdown(user, org, include_unassigned=False):
    """
    Optimized version for dropdowns - returns list of dicts.
    """
    clients = get_visible_clients(user, org).values(
        'id', 'name', 'code', 'visibility'
    ).order_by('name')
    
    result = list(clients)
    
    if include_unassigned:
        result.insert(0, {'id': None, 'name': '— Unassigned —', 'code': ''})
    
    return result