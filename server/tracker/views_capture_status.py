"""
tracker/views_capture_status.py

Is this person set up, and when did we last hear from them?

Daily Review has to explain an empty day, and the three explanations are very
different: never set up, set up but the agent is not running, or simply a day
off. It was deciding between them from /api/devices/, which is not a signal it
can rely on — that endpoint is guarded by @login_required, a session decorator
that runs before DRF authentication and redirects a token-authenticated caller
to a login page instead of returning anything.

So a partner with four hundred blocks this week was told the desktop app was
not connected and offered a setup wizard, on a day he was simply out of the
office. Capture history answers the question directly and cannot be wrong in
that direction: somebody who has captured time obviously has a working agent,
whatever any other endpoint says.
"""

from datetime import timedelta

from django.db.models import Max
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import (
    AgentDevice, Block, DeviceProvisioningMap, OrgDeploymentToken,
    OrganizationMembership,
)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def capture_status(request):
    """GET /api/capture-status/ — enough to explain an empty day, honestly."""
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
    if not membership:
        return Response({'error': 'No organization'}, status=403)
    org = membership.organization

    last_block = Block.objects.filter(
        org=org, user=request.user,
    ).aggregate(at=Max('start'))['at']

    last_seen = AgentDevice.objects.filter(
        user=request.user,
    ).aggregate(at=Max('last_seen_at'))['at']

    # Whether this firm is rolled out BY IT. A provisioning map or a live
    # deployment token both mean an MSI exists and machines are meant to arrive
    # already paired — so telling one of their staff to generate a pairing code
    # is asking them to work around their own IT department.
    it_deployed = (
        DeviceProvisioningMap.objects.filter(organization=org).exists()
        or OrgDeploymentToken.objects.filter(organization=org, is_active=True).exists()
    )

    now = timezone.now()
    return Response({
        'it_deployed': it_deployed,
        # The load-bearing one. Ever captured anything at all?
        'has_captured': last_block is not None,
        'last_capture_at': last_block.isoformat() if last_block else None,
        'captured_recently': bool(last_block and (now - last_block) < timedelta(days=7)),
        'last_device_seen_at': last_seen.isoformat() if last_seen else None,
        'device_seen_recently': bool(last_seen and (now - last_seen) < timedelta(hours=12)),
    })
