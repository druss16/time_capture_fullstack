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
    """Days whose review still covers everything on them.

    Reviewedness is a MOMENT, not a flag. Somebody who presses "Looks right" at
    two in the afternoon and then works until six has vouched for half a day —
    and an earlier version of this counted that as the whole of it, which would
    have sent four unreviewed hours to a billing system on the strength of a
    button pressed before the work existed.

    The derived half was worse: editing one block at nine in the morning marked
    the entire day reviewed, without anyone intending to vouch for anything.

    So a day counts only while the last human touch is at least as recent as
    the last thing that happened to its time. New work after a review quietly
    un-reviews the day, which is the honest outcome — there is now something on
    it nobody has seen.
    """
    from django.db.models import Max

    blocks = Block.objects.filter(
        org=org, user=user, day__gte=start, day__lte=end,
    )

    # Last thing that happened to a day's time, whoever or whatever did it. A
    # re-classification counts: the content changed after it was looked at.
    last_activity = {
        r['day']: max(filter(None, (r['created'], r['changed'])), default=None)
        for r in blocks.values('day').annotate(
            created=Max('created_at'), changed=Max('state_changed_at'),
        )
    }

    last_human = {}
    for r in blocks.filter(state_changed_by__in=HUMAN_STATES).values('day').annotate(
        touched=Max('state_changed_at'),
    ):
        if r['touched']:
            last_human[r['day']] = r['touched']

    for day, at in DayReview.objects.filter(
        org=org, user=user, day__gte=start, day__lte=end,
    ).values_list('day', 'reviewed_at'):
        prev = last_human.get(day)
        if prev is None or at > prev:
            last_human[day] = at

    reviewed = set()
    for day, human_at in last_human.items():
        activity_at = last_activity.get(day)
        # No activity recorded at all — nothing to have missed.
        if activity_at is None or human_at >= activity_at:
            reviewed.add(day)
    return reviewed


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

    # Same rule as reviewed_days, or the button would claim a day is covered
    # after work landed on it that nobody has seen.
    still_covered = d in reviewed_days(org, request.user, d, d)
    explicit = DayReview.objects.filter(org=org, user=request.user, day=d).exists()
    touched = Block.objects.filter(
        org=org, user=request.user, day=d, state_changed_by__in=HUMAN_STATES,
    ).exists()

    return Response({
        'day': d.isoformat(),
        'reviewed': still_covered,
        # Told apart so the UI can offer "looks right" on a day with no edits,
        # and stay quiet on one the person has already worked through.
        'explicit': explicit and still_covered,
        'derived_from_edits': touched and still_covered,
        # A marker exists but time landed after it. The day needs looking at
        # again, and saying so beats silently showing an un-pressed button.
        'stale': (explicit or touched) and not still_covered,
    })
