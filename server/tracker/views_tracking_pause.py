# tracker/views_tracking_pause.py
"""
Menu-bar "Pause Tracking" — the agent reports each pause here, and Reports
reads paused hours per employee from paused_minutes_by_user().

    POST /api/agent/pauses/   device key   {"pauses": [{started_at, ended_at, planned_until}, ...]}

See models_tracking_pause.py for why this is its own table.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Dict, Iterable, Optional

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from tracker.auth import AgentKeyAuthentication, AgentKeyPermission
from tracker.views_billing import get_user_org

logger = logging.getLogger(__name__)

MAX_PAUSES_PER_POST = 50
# A pause the agent never closed (machine died mid-pause, agent removed) is
# not counted for ever: at most this long past its start.
OPEN_PAUSE_CAP = timedelta(hours=24)


def _aware(value) -> Optional[datetime]:
    dt = parse_datetime(value) if isinstance(value, str) else None
    if dt is not None and timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication])
@permission_classes([AgentKeyPermission])
def agent_pauses_report(request):
    """Idempotent per (device, started_at): a re-sent pause replaces itself,
    so the agent can retry until it gets a 200."""
    from tracker.models import TrackingPause

    device = request.agent_device
    org = get_user_org(device.user) if device.user else None
    if not org:
        return Response({'error': 'Device is not paired to a firm member.'}, status=400)

    pauses = request.data.get('pauses') if isinstance(request.data, dict) else None
    if not isinstance(pauses, list):
        return Response({'error': 'pauses must be a list'}, status=400)

    now = timezone.now()
    saved = 0
    try:
        with transaction.atomic():
            for p in pauses[:MAX_PAUSES_PER_POST]:
                if not isinstance(p, dict):
                    continue
                started = _aware(p.get('started_at'))
                if not started or started > now + timedelta(minutes=5):
                    continue
                ended = _aware(p.get('ended_at'))
                if ended is not None and ended < started:
                    ended = started
                planned = _aware(p.get('planned_until'))
                TrackingPause.objects.update_or_create(
                    device=device, started_at=started,
                    defaults=dict(org=org, user=device.user,
                                  ended_at=ended, planned_until=planned),
                )
                saved += 1
    except DatabaseError as e:
        # Code ships on merge, the migration is applied by hand: until it is,
        # tell the agent to keep the pause and try again later.
        logger.warning("[PAUSES] not stored (migration pending?): %s", e)
        return Response({'error': 'pauses not available yet'}, status=503)
    return Response({'saved': saved})


def paused_minutes_by_user(org, start_utc: datetime, end_utc: datetime,
                           user_ids: Optional[Iterable[int]] = None) -> Dict[int, float]:
    """{user_id: minutes paused inside [start_utc, end_utc)}.

    Only the part of each pause inside the window counts. An open pause runs
    to its planned end, or now, whichever is first (and never more than
    OPEN_PAUSE_CAP past its start). Overlapping pauses from two devices of
    the same person are merged, so a person is never paused twice over.
    Returns {} if the table is not there yet (migration pending).
    """
    from tracker.models import TrackingPause

    now = timezone.now()
    try:
        # Savepoint: a missing table must not poison an enclosing transaction.
        with transaction.atomic():
            qs = TrackingPause.objects.filter(org=org, started_at__lt=end_utc).filter(
                Q(ended_at__isnull=True) | Q(ended_at__gt=start_utc))
            if user_ids is not None:
                qs = qs.filter(user_id__in=list(user_ids))
            rows = list(qs.values_list('user_id', 'started_at', 'ended_at', 'planned_until'))
    except DatabaseError as e:
        logger.warning("[PAUSES] paused minutes unavailable (migration pending?): %s", e)
        return {}

    return paused_minutes_from_rows(rows, start_utc, end_utc, now)


def paused_minutes_from_rows(rows, start_utc: datetime, end_utc: datetime,
                             now: datetime) -> Dict[int, float]:
    """The arithmetic of paused_minutes_by_user, on (user_id, started_at,
    ended_at, planned_until) tuples — no database, so it is unit-tested."""
    spans: Dict[int, list] = {}
    for uid, started, ended, planned in rows:
        if ended is None:
            ended = min(x for x in (planned, now, started + OPEN_PAUSE_CAP) if x is not None)
        s, e = max(started, start_utc), min(ended, end_utc)
        if e > s:
            spans.setdefault(uid, []).append((s, e))

    out: Dict[int, float] = {}
    for uid, ivs in spans.items():
        ivs.sort()
        total = 0.0
        cur_s, cur_e = ivs[0]
        for s, e in ivs[1:]:
            if s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                total += (cur_e - cur_s).total_seconds()
                cur_s, cur_e = s, e
        total += (cur_e - cur_s).total_seconds()
        out[uid] = total / 60.0
    return out
