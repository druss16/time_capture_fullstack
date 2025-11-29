# tracker/utils.py

def get_user_org(user):
    """Get user's organization (Group) - used in all views"""
    return user.groups.first()

def get_user_membership(user):
    """Get user's membership with role info"""
    return user.memberships.select_related('organization').first()

def require_role(roles):
    """Decorator to require specific roles"""
    def decorator(view_func):
        def wrapped(request, *args, **kwargs):
            membership = get_user_membership(request.user)
            if not membership or membership.role not in roles:
                return Response({'error': 'Insufficient permissions'}, status=403)
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator