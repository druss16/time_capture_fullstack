# tracker/utils/org.py
from django.contrib.auth.models import Group

DEFAULT_ORG_NAME = "Time Agents"

def get_org_or_default(request) -> Group | None:
    """
    Pick an org (Group) for this request.
    Priority:
      1) If request.user is authenticated and in any groups → first one.
      2) Cookie 'mavops_org' → ensure group exists.
      3) Fallback to DEFAULT_ORG_NAME (ensure exists).
    """
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        g = user.groups.first()
        if g:
            return g

    # Optional cookie-based org
    org_name = (request.COOKIES or {}).get("mavops_org")
    if org_name:
        g, _ = Group.objects.get_or_create(name=org_name)
        return g

    g, _ = Group.objects.get_or_create(name=DEFAULT_ORG_NAME)
    return g