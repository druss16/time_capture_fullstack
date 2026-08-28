"""
tracker/views_day_review.py

"Somebody looked at this day and it was right."

Absence of edits means nothing on its own — a day nobody opened and a day
somebody read carefully and agreed with are the same empty set of changes. That
ambiguity is why unattended pushing to a billing system is unsafe today: at a
live org, 87% of committed time was committed by the classifier with no human
in the loop, so "committed" is not a person's opinion.

Reviewedness is therefore two things, and only one of them is stored:

  derived   the day carries blocks a human actually changed (state_changed_by
            of user / user_edit / correction). Nothing to record — the evidence
            is already on the blocks.
  explicit  a DayReview row, for the case with no other trace: opened it,
            agreed with everything, touched nothing.
"""

from datetime import date

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import Block, DayReview, OrganizationMembership

HUMAN_STATES = ('user', 'user_edit', 'correction', 'admin_bulk')


def reviewed_days(org, user, start, end) -> set:
    """Days in [start, end] this person has actually looked at."""
    explicit = set(
        DayReview.objects.filter(
            org=org, user=user, day__gte=start, day__lte=end,
        ).values_list('day', flat=True)
    )
    touched = set(
        Block.objects.filter(
            org=org, user=user, day__gte=start, day__lte=end,
            state_changed_by__in=HUMAN_STATES,
        ).values_list('day', flat=True).distinct()
    )
    return explicit | touched


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def day_review(request, day):
    """GET/POST/DELETE /api/daily/<YYYY-MM-DD>/reviewed/

    POST marks the day reviewed by the caller; DELETE takes it back. Only ever
    your own day — one person cannot vouch for another's time, which is the
    whole point of the signal.
    """
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
    if not membership:
        return Response({'error': 'No organization'}, status=403)
    org = membership.organization

    try:
        d = date.fromisoformat(day)
    except ValueError:
        return Response({'error': 'day must be YYYY-MM-DD'}, status=400)

    if d > date.today():
        return Response({'error': 'That day has not happened yet.'}, status=400)

    if request.method == 'POST':
        DayReview.objects.get_or_create(org=org, user=request.user, day=d)
    elif request.method == 'DELETE':
        DayReview.objects.filter(org=org, user=request.user, day=d).delete()

    explicit = DayReview.objects.filter(org=org, user=request.user, day=d).exists()
    touched = Block.objects.filter(
        org=org, user=request.user, day=d, state_changed_by__in=HUMAN_STATES,
    ).exists()

    return Response({
        'day': d.isoformat(),
        'reviewed': explicit or touched,
        # Told apart so the UI can offer "looks right" on a day with no edits,
        # and stay quiet on one the person has already worked through.
        'explicit': explicit,
        'derived_from_edits': touched,
    })
