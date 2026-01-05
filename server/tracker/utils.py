# tracker/utils.py
from tracker.models import OrganizationMembership

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