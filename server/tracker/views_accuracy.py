# ============================================================================
# tracker/views_accuracy.py
# MavOps Accuracy — the sampled audit loop behind the accuracy number.
# Staff-only, same auth posture as the rest of MavOps.
# ============================================================================
from datetime import date, timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication
from tracker.services import accuracy as acc
from tracker.views_mavops import IsStaff


def _period(request):
    """Resolve the audit window. Defaults to the last 30 days ending today."""
    today = timezone.localdate()
    try:
        days = min(max(int(request.GET.get('days', 30)), 1), 365)
    except (TypeError, ValueError):
        days = 30
    start_raw = request.GET.get('start')
    end_raw = request.GET.get('end')
    if start_raw and end_raw:
        try:
            return date.fromisoformat(start_raw), date.fromisoformat(end_raw)
        except ValueError:
            pass
    return today - timedelta(days=days), today


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def accuracy_summary(request):
    """GET /api/mavops/accuracy/?org_id=<id>&days=<int>

    Coverage, the sampled precision with its interval, and both lower-bound
    estimators — never a single blended number, because the two halves are
    gamed in opposite directions.
    """
    org_id = request.GET.get('org_id')
    if not org_id:
        return Response({'detail': 'org_id is required.'}, status=400)
    start, end = _period(request)
    return Response(acc.summary(int(org_id), start, end))


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def accuracy_draw(request):
    """POST /api/mavops/accuracy/draw/  {org_id, days|start+end, n}

    Draws the random sample. Idempotent per period: blocks already drawn are
    skipped, so pressing the button twice tops the sample up rather than
    stacking duplicates that would weight the same block twice.
    """
    org_id = request.data.get('org_id')
    if not org_id:
        return Response({'detail': 'org_id is required.'}, status=400)
    try:
        n = min(max(int(request.data.get('n', acc.DEFAULT_SAMPLE_SIZE)), 1), 200)
    except (TypeError, ValueError):
        n = acc.DEFAULT_SAMPLE_SIZE

    start, end = _period(request)
    if request.data.get('start') and request.data.get('end'):
        try:
            start = date.fromisoformat(request.data['start'])
            end = date.fromisoformat(request.data['end'])
        except ValueError:
            pass

    drawn = acc.draw_sample(int(org_id), start, end, n)
    return Response({
        'drawn': len(drawn),
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'population': acc.auditable_blocks(int(org_id), start, end).count(),
    })


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def accuracy_queue(request):
    """GET /api/mavops/accuracy/queue/?org_id=&days=&state=pending

    The adjudication queue: each row carries the evidence a human needs to
    judge it — the title, the app, the file path, and what it was filed as.
    """
    from tracker.models import AccuracySample

    org_id = request.GET.get('org_id')
    if not org_id:
        return Response({'detail': 'org_id is required.'}, status=400)
    start, end = _period(request)
    state = request.GET.get('state', 'pending')

    qs = (AccuracySample.objects
          .filter(org_id=org_id, period_start=start, period_end=end)
          .select_related('block', 'booked_client', 'correct_client', 'block__user'))
    if state != 'all':
        qs = qs.filter(verdict=state)

    rows = []
    for s in qs[:200]:
        b = s.block
        rows.append({
            'sample_id': s.id,
            'block_id': b.id,
            'date': b.day.isoformat() if b.day else None,
            'user': (b.user.get_full_name().strip() or b.user.username) if b.user_id else None,
            'minutes': s.minutes,
            'app_name': getattr(b, 'app_name', '') or '',
            'window_title': (b.window_title or '')[:220],
            'file_path': (getattr(b, 'file_path', '') or '')[:220],
            'booked_client_id': s.booked_client_id,
            'booked_client_name': s.booked_client.name if s.booked_client_id else None,
            'verdict': s.verdict,
            'correct_client_name': s.correct_client.name if s.correct_client_id else None,
            'note': s.note,
        })
    return Response({'period': {'start': start.isoformat(), 'end': end.isoformat()},
                     'rows': rows})


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def accuracy_adjudicate(request):
    """POST /api/mavops/accuracy/adjudicate/  {sample_id, verdict, correct_client_id?, note?}

    Records a verdict. Deliberately does NOT re-file the block: an audit that
    edits the thing it measures stops being a measurement. Fixing the block is
    a separate, visible action.
    """
    from tracker.models import AccuracySample

    sample_id = request.data.get('sample_id')
    verdict = request.data.get('verdict')
    if verdict not in ('correct', 'wrong', 'unverifiable', 'pending'):
        return Response({'detail': 'verdict must be correct, wrong, unverifiable or pending.'},
                        status=400)
    try:
        s = AccuracySample.objects.get(id=sample_id)
    except AccuracySample.DoesNotExist:
        return Response({'detail': 'sample not found.'}, status=404)

    s.verdict = verdict
    s.correct_client_id = request.data.get('correct_client_id') if verdict == 'wrong' else None
    s.note = (request.data.get('note') or '')[:2000]
    s.adjudicated_by = request.user if request.user.is_authenticated else None
    s.adjudicated_at = timezone.now() if verdict != 'pending' else None
    s.save(update_fields=['verdict', 'correct_client', 'note',
                          'adjudicated_by', 'adjudicated_at'])

    return Response({'ok': True, 'sample_id': s.id, 'verdict': s.verdict,
                     'summary': acc.sampled_precision(s.org_id, s.period_start, s.period_end)})
