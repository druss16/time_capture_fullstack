# tracker/views_agent_work.py
"""
AI agent work — the report-in endpoint agents call, and the read endpoint that
totals it. See models_agent_work.py for why this never touches Block.

    POST /api/agent-work/report/   device key (the paired desktop agent's)
    GET  /api/agent-work/          web login; members see their own sessions,
                                   owners/admins/managers see the whole firm
"""
from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.db.models import Count, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.auth import AgentKeyAuthentication, AgentKeyPermission, BearerTokenAuthentication
from tracker.models import AgentWorkSession, Client, OrganizationMembership
from tracker.views_billing import get_user_org

AGENT_KINDS = {k for k, _ in AgentWorkSession.AGENT_KINDS}
FIRM_WIDE_ROLES = ('owner', 'admin', 'manager')
MAX_SESSIONS_RETURNED = 500


def _int(value):
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _aware(value):
    dt = parse_datetime(value) if isinstance(value, str) else None
    if dt is not None and timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def resolve_client(org, hint):
    """The org's active client the project NAMED, or None.

    Exact name or code, case-insensitive, and only when exactly one client
    answers to it. No fuzzy matching on purpose: the hint is something a
    person wrote into the project, so a near-miss is a typo to fix, not a
    guess to make — the title matcher's history is a list of near-misses.
    """
    hint = (hint or '').strip()
    if not hint:
        return None
    hits = list(
        Client.objects.filter(org=org, is_active=True, name__iexact=hint)[:2]
    ) or list(
        Client.objects.filter(org=org, is_active=True, code__iexact=hint)[:2]
    )
    return hits[0] if len(hits) == 1 else None


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication])
@permission_classes([AgentKeyPermission])
def agent_work_report(request):
    """
    One snapshot of an agent session. Totals are the session's running totals,
    not a delta, so the same snapshot posted twice changes nothing.

    {
      "agent_kind": "claude_code",
      "session_id": "71b942e5-...",
      "model": "claude-opus-5-5",
      "started_at": "2026-10-02T18:16:03Z",
      "last_activity_at": "2026-10-02T18:40:11Z",
      "ended": false,
      "active_seconds": 912,
      "turns": 4,
      "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
      "project_path": "/Users/x/clients/acme",
      "client": "Acme Widgets"          // optional: name or code
    }
    """
    device = request.agent_device
    user = device.user
    org = get_user_org(user) if user else None
    if not org:
        return Response({'error': 'Device is not paired to a firm member.'}, status=400)

    data = request.data if isinstance(request.data, dict) else {}
    session_id = str(data.get('session_id') or '').strip()[:128]
    started_at = _aware(data.get('started_at'))
    last_activity_at = _aware(data.get('last_activity_at'))
    if not session_id or not started_at or not last_activity_at:
        return Response(
            {'error': 'session_id, started_at and last_activity_at are required.'},
            status=400)
    if last_activity_at < started_at:
        return Response({'error': 'last_activity_at is before started_at.'}, status=400)

    agent_kind = data.get('agent_kind') if data.get('agent_kind') in AGENT_KINDS else 'other'
    existing = AgentWorkSession.objects.filter(
        org=org, agent_kind=agent_kind, external_session_id=session_id).first()

    # Snapshots can arrive out of order (a slow post overtaken by the next
    # turn's). An older snapshot must not roll the totals back.
    if existing and last_activity_at < existing.last_activity_at:
        return Response({'id': existing.id, 'status': 'stale_snapshot_ignored'})

    # Active time can never exceed the session's wall-clock span — a reporter
    # bug must not be able to claim more agent time than elapsed.
    span = int((last_activity_at - started_at).total_seconds())
    active_seconds = min(_int(data.get('active_seconds')), span)

    tokens = data.get('tokens') if isinstance(data.get('tokens'), dict) else {}
    hint = str(data.get('client') or '').strip()[:255]
    client = resolve_client(org, hint)

    fields = dict(
        user=user,
        device=device,
        model_name=str(data.get('model') or '')[:64],
        started_at=started_at,
        last_activity_at=last_activity_at,
        ended_at=last_activity_at if data.get('ended') else None,
        active_seconds=active_seconds,
        turns=_int(data.get('turns')),
        input_tokens=_int(tokens.get('input')),
        output_tokens=_int(tokens.get('output')),
        cache_read_tokens=_int(tokens.get('cache_read')),
        cache_write_tokens=_int(tokens.get('cache_write')),
        project_path=str(data.get('project_path') or '')[:512],
        client=client,
        client_hint=hint,
        client_source='explicit' if client else 'none',
    )
    session, created = AgentWorkSession.objects.update_or_create(
        org=org, agent_kind=agent_kind, external_session_id=session_id,
        defaults=fields)
    return Response(
        {'id': session.id, 'status': 'created' if created else 'updated',
         'client_id': client.id if client else None},
        status=201 if created else 200)


def _day_window(request):
    """[start, end) in the server's timezone from ?start=&end= dates; default last 7 days."""
    today = timezone.localdate()
    start = parse_date(request.GET.get('start') or '') or today - timedelta(days=6)
    end = parse_date(request.GET.get('end') or '') or today
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), tz),
            timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz),
            start, end)


def _totals(qs):
    t = qs.aggregate(
        sessions=Count('id'), active_seconds=Sum('active_seconds'), turns=Sum('turns'),
        input_tokens=Sum('input_tokens'), output_tokens=Sum('output_tokens'),
        cache_read_tokens=Sum('cache_read_tokens'), cache_write_tokens=Sum('cache_write_tokens'))
    return {k: v or 0 for k, v in t.items()}


@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def agent_work_list(request):
    """
    GET /api/agent-work/?start=YYYY-MM-DD&end=YYYY-MM-DD

    Agent work in the window, its own totals, and the same totals split by
    client and by the person who ran the agent. These numbers are separate
    from — and never added to — human time.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)

    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org).first()
    firm_wide = request.user.is_staff or (membership and membership.role in FIRM_WIDE_ROLES)

    start_dt, end_dt, start, end = _day_window(request)
    qs = AgentWorkSession.objects.filter(org=org, started_at__gte=start_dt, started_at__lt=end_dt)
    if not firm_wide:
        qs = qs.filter(user=request.user)

    by_client = [
        {'client_id': r['client_id'], 'client_name': r['client__name'] or 'Unassigned',
         'sessions': r['sessions'], 'active_seconds': r['active_seconds'] or 0,
         'output_tokens': r['output_tokens'] or 0}
        for r in qs.values('client_id', 'client__name').annotate(
            sessions=Count('id'), active_seconds=Sum('active_seconds'),
            output_tokens=Sum('output_tokens')).order_by('-active_seconds')
    ]
    by_user = [
        {'user_id': r['user_id'], 'email': r['user__email'] or '',
         'sessions': r['sessions'], 'active_seconds': r['active_seconds'] or 0}
        for r in qs.values('user_id', 'user__email').annotate(
            sessions=Count('id'), active_seconds=Sum('active_seconds')).order_by('-active_seconds')
    ]
    sessions = [
        {'id': s.id, 'agent_kind': s.agent_kind, 'model': s.model_name,
         'user_email': s.user.email if s.user else '',
         'client_id': s.client_id, 'client_name': s.client.name if s.client else None,
         'client_hint': s.client_hint, 'project_path': s.project_path,
         'started_at': s.started_at, 'last_activity_at': s.last_activity_at,
         'ended_at': s.ended_at, 'active_seconds': s.active_seconds, 'turns': s.turns,
         'input_tokens': s.input_tokens, 'output_tokens': s.output_tokens,
         'cache_read_tokens': s.cache_read_tokens, 'cache_write_tokens': s.cache_write_tokens}
        for s in qs.select_related('user', 'client')[:MAX_SESSIONS_RETURNED]
    ]
    return Response({
        'start': start.isoformat(), 'end': end.isoformat(),
        'scope': 'firm' if firm_wide else 'self',
        'totals': _totals(qs),
        'by_client': by_client,
        'by_user': by_user,
        'sessions': sessions,
    })


# ──────────────────────────────────────────────
# Agent presence — measurement from the desktop agent (agent_presence.py)
# ──────────────────────────────────────────────

MAX_BUCKETS_PER_POST = 100
MAX_MAP_KEYS = 50


def _count_map(value):
    """{name: non-negative int}, capped — the agent caps too; never trust it."""
    if not isinstance(value, dict):
        return {}
    out = {}
    for k, v in list(value.items())[:MAX_MAP_KEYS]:
        out[str(k)[:64]] = _int(v)
    return out


def _process_map(value):
    if not isinstance(value, dict):
        return {}
    out = {}
    for label, p in list(value.items())[:MAX_MAP_KEYS]:
        if isinstance(p, dict):
            try:
                cpu = round(max(float(p.get('cpu_s') or 0), 0.0), 1)
            except (TypeError, ValueError):
                cpu = 0.0
            out[str(label)[:64]] = {'seen_min': _int(p.get('seen_min')),
                                    'busy_min': _int(p.get('busy_min')), 'cpu_s': cpu}
    return out


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication])
@permission_classes([AgentKeyPermission])
def agent_presence_report(request):
    """
    POST /api/agent-presence/   {"buckets": [<one device-hour of counts>, ...]}

    Idempotent per (device, hour): a re-sent hour replaces itself. Stored for
    measurement only; nothing that computes time reads it.
    """
    from tracker.models import AgentPresenceSample

    device = request.agent_device
    org = get_user_org(device.user) if device.user else None
    if not org:
        return Response({'error': 'Device is not paired to a firm member.'}, status=400)

    buckets = request.data.get('buckets') if isinstance(request.data, dict) else None
    if not isinstance(buckets, list):
        return Response({'error': 'buckets must be a list'}, status=400)

    saved = 0
    for b in buckets[:MAX_BUCKETS_PER_POST]:
        if not isinstance(b, dict):
            continue
        start = _aware(b.get('bucket_start'))
        if not start:
            continue
        AgentPresenceSample.objects.update_or_create(
            device=device, bucket_start=start,
            defaults=dict(
                org=org, user=device.user,
                app_version=(request.headers.get('X-Agent-Version') or device.app_version or '')[:32],
                seconds_observed=min(_int(b.get('seconds_observed')), 3600),
                idle_seconds=min(_int(b.get('idle_seconds')), 3600),
                remote_session=bool(b.get('remote_session')),
                input_monitor=str(b.get('input_monitor') or '')[:16],
                clicks_real=_int(b.get('clicks_real')),
                clicks_synthetic=_int(b.get('clicks_synthetic')),
                synthetic_by=_count_map(b.get('synthetic_by')),
                idle_changes=_int(b.get('idle_changes')),
                idle_changes_by_app=_count_map(b.get('idle_changes_by_app')),
                processes=_process_map(b.get('processes')),
                local_sessions=_count_map(b.get('local_sessions')),
            ))
        saved += 1
    return Response({'saved': saved})
