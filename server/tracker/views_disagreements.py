"""
API endpoints for AI vs Agent disagreement flagged blocks.

Used by the daily review UI to surface blocks where Stage 10 AI proposed
a different client than the agent assigned. The agent's deterministic
client choice is sacred; AI's role is to flag possible disagreements for
user review, never to silently override.

Endpoints:
  GET  /api/disagreements/                          — list flagged blocks
  GET  /api/disagreements/stats/                    — aggregate stats
  POST /api/disagreements/<block_id>/resolve/       — accept/dismiss/change

All endpoints respect the staff override pattern from get_request_user_override.
"""

import json
import logging
from datetime import timedelta

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
from django.db import transaction

from tracker.models import Block, Client
from tracker.views import get_request_user_override
from tracker.utils.user_reasoning import humanize_for_api

logger = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================

def _serialize_disagreement(b: Block) -> dict:
    """Build the JSON payload for a single flagged block."""
    return {
        'block_id': b.id,
        'day': b.day.isoformat() if b.day else None,
        'start': b.start.isoformat() if b.start else None,
        'end': b.end.isoformat() if b.end else None,
        'minutes': b.minutes,
        'window_title': b.window_title or '',
        'app_name': b.app_name or '',
        'file_path': b.file_path or '',
        'agent_client': {
            'id': b.client_id,
            'name': b.client.name if b.client else None,
        },
        'ai_proposed_client': {
            'id': b.ai_proposed_client_id,
            'name': b.ai_proposed_client.name if b.ai_proposed_client else None,
        },
        'ai_confidence': b.ai_proposed_confidence,
        'ai_reasoning': humanize_for_api(b),
        'resolved_at': (
            b.ai_disagreement_resolved_at.isoformat()
            if b.ai_disagreement_resolved_at else None
        ),
        'resolution': b.ai_disagreement_resolution,
    }


# =============================================================================
# Views
# =============================================================================

@require_GET
def list_disagreements(request):
    """
    GET /api/disagreements/?days=7&unresolved_only=true&limit=100

    Returns blocks where AI disagreed with agent's client choice.

    Query params:
      days            (int, default 7)     — look-back window
      unresolved_only (bool, default true) — show only unresolved disagreements
      limit           (int, default 100)   — max results
    """
    user = get_request_user_override(request)
    if not user or not user.is_authenticated:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        days = max(1, min(90, int(request.GET.get('days', 7))))
        limit = max(1, min(500, int(request.GET.get('limit', 100))))
    except ValueError:
        return JsonResponse({'error': 'invalid_params'}, status=400)

    unresolved_only = request.GET.get('unresolved_only', 'true').lower() == 'true'

    cutoff = timezone.now().date() - timedelta(days=days)

    qs = (
        Block.objects.filter(
            user=user,
            day__gte=cutoff,
            ai_disagrees_with_agent=True,
        )
        .select_related('client', 'ai_proposed_client')
        .order_by('-day', '-start')
    )

    if unresolved_only:
        qs = qs.filter(ai_disagreement_resolved_at__isnull=True)

    total = qs.count()
    blocks = list(qs[:limit])

    return JsonResponse({
        'count': len(blocks),
        'total': total,  # how many match before limit
        'days': days,
        'unresolved_only': unresolved_only,
        'disagreements': [_serialize_disagreement(b) for b in blocks],
    })


@csrf_exempt
@require_POST
def resolve_disagreement(request, block_id):
    """
    POST /api/disagreements/<block_id>/resolve/
    Body: {"action": "accept" | "dismiss" | "change", "client_id": <int|null>}

    accept  — switch block to AI's proposed client
    dismiss — keep agent's client, just mark resolved
    change  — switch to a third client (specified via client_id in body)

    Writes a ClassificationAudit row tracking the user's choice. The block's
    is_categorized stays True; only the client field changes (when applicable).
    """
    user = get_request_user_override(request)
    if not user or not user.is_authenticated:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        body = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'invalid_json'}, status=400)

    action = body.get('action')
    if action not in ('accept', 'dismiss', 'change'):
        return JsonResponse({'error': 'invalid_action',
                             'valid_actions': ['accept', 'dismiss', 'change']},
                            status=400)

    try:
        block = (
            Block.objects
            .select_related('client', 'ai_proposed_client', 'org')
            .get(id=block_id, user=user, ai_disagrees_with_agent=True)
        )
    except Block.DoesNotExist:
        return JsonResponse({'error': 'block_not_found_or_not_flagged'}, status=404)

    if block.ai_disagreement_resolved_at:
        return JsonResponse({
            'error': 'already_resolved',
            'resolved_at': block.ai_disagreement_resolved_at.isoformat(),
            'resolution': block.ai_disagreement_resolution,
        }, status=409)

    with transaction.atomic():
        old_client_id = block.client_id

        if action == 'accept':
            if not block.ai_proposed_client_id:
                return JsonResponse({'error': 'no_ai_proposal_to_accept'}, status=400)
            block.client_id = block.ai_proposed_client_id
            resolution = 'accepted'

        elif action == 'change':
            new_client_id = body.get('client_id')
            if not new_client_id:
                return JsonResponse({'error': 'client_id_required_for_change'}, status=400)
            try:
                new_client = Client.objects.get(id=new_client_id, org=block.org)
            except Client.DoesNotExist:
                return JsonResponse({'error': 'client_not_found_in_org'}, status=404)
            block.client_id = new_client.id
            resolution = 'changed_to_other'

        else:  # dismiss
            resolution = 'dismissed'
            # Block client unchanged

        block.ai_disagreement_resolved_at = timezone.now()
        block.ai_disagreement_resolution = resolution

        # Use force_classifier=True to bypass the immutability check on
        # already-categorized blocks (this is a deliberate user correction)
        block.save(force_classifier=True)

        # Audit log — track the resolution for analytics + later AI tuning
        try:
            from tracker.models import ClassificationAudit
            ClassificationAudit.objects.create(
                block=block,
                source='manual',
                client_before_id=old_client_id,
                client_after_id=block.client_id,
                category_before='',
                category_after='',
                confidence_client=1.0,
                confidence_category=0.0,
                overall_confidence=1.0,
                matched_signals=[{
                    'type': 'ai_disagreement_resolution',
                    'strength': 1.0,
                    'evidence': (
                        f"User {user.username} resolved AI disagreement "
                        f"with action='{action}'"
                    ),
                    'detail': {
                        'action': action,
                        'agent_proposed_client_id': old_client_id,
                        'ai_proposed_client_id': block.ai_proposed_client_id,
                        'final_client_id': block.client_id,
                        'ai_confidence': block.ai_proposed_confidence,
                    },
                }],
                corrected_by_user=True,
            )
        except Exception as e:
            # Audit is nice-to-have — don't fail the resolution if it errors
            logger.warning(
                f'Failed to write ClassificationAudit for disagreement '
                f'resolution on block {block.id}: {e}'
            )

        logger.info(
            f"[DISAGREEMENT-RESOLVE] block={block.id} user={user.username} "
            f"action={action} old_client={old_client_id} → "
            f"new_client={block.client_id}"
        )

    return JsonResponse({
        'block_id': block.id,
        'resolution': resolution,
        'final_client_id': block.client_id,
        'final_client_name': block.client.name if block.client else None,
    })


@require_GET
def disagreement_stats(request):
    """
    GET /api/disagreements/stats/?days=30

    Returns aggregate stats for the user's disagreements over N days.
    Used by the daily review banner ("AI suggested changes 12 times,
    you accepted 8") and for self-tuning the system over time.
    """
    user = get_request_user_override(request)
    if not user or not user.is_authenticated:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        days = max(1, min(365, int(request.GET.get('days', 30))))
    except ValueError:
        return JsonResponse({'error': 'invalid_params'}, status=400)

    cutoff = timezone.now().date() - timedelta(days=days)

    qs = Block.objects.filter(
        user=user,
        day__gte=cutoff,
        ai_disagrees_with_agent=True,
    )

    total = qs.count()
    unresolved = qs.filter(ai_disagreement_resolved_at__isnull=True).count()
    accepted = qs.filter(ai_disagreement_resolution='accepted').count()
    dismissed = qs.filter(ai_disagreement_resolution='dismissed').count()
    changed = qs.filter(ai_disagreement_resolution='changed_to_other').count()

    resolved = accepted + dismissed + changed

    # AI accuracy when user resolved: accepted = AI right; others = AI wrong
    # (changed_to_other is "AI was wrong AND agent was wrong" — most damning)
    ai_accuracy_pct = round(100 * accepted / resolved, 1) if resolved else 0.0

    return JsonResponse({
        'days': days,
        'total_disagreements': total,
        'unresolved': unresolved,
        'resolved': resolved,
        'breakdown': {
            'accepted_ai': accepted,
            'kept_agent': dismissed,
            'picked_other': changed,
        },
        'ai_accuracy_pct': ai_accuracy_pct,
    })