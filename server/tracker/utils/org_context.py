from tracker.models import Organization, OrganizationMembership

def get_effective_org(request):
    """
    Returns (org, is_impersonating).
    If a MavOps admin has set an impersonation session, uses that org.
    Otherwise falls back to the authenticated user's org.
    """
    impersonating_id = request.session.get("admin_impersonating_org_id")
    if impersonating_id:
        try:
            org = Organization.objects.get(id=impersonating_id)
            return org, True
        except Organization.DoesNotExist:
            pass

    # Normal path — get org from membership
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
    
    return (membership.organization if membership else None), False