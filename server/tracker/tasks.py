# tracker/tasks.py
from tracker.utils.monitoring import capture_exception

# tracker/tasks.py
from celery import shared_task
from tracker.views import compact_rawevents_into_blocks
from django.utils import timezone


def _run(pk: int):
    from tracker.models import Block
    from tracker.services.classify_block import classify_block
    blk = Block.objects.get(pk=pk)
    classify_block(blk)

class _ShimTask:
    """Provides .delay(pk) even when Celery is not installed/running."""
    @staticmethod
    def delay(pk: int):
        try:
            _run(pk)
        except Exception as e:
            capture_exception(e)

# Public alias used by signals
classify_block_task = _ShimTask()


@shared_task
def auto_compact_recent_events():
    """Compact raw events from the last hour for all active users"""
    from django.contrib.auth import get_user_model
    from datetime import datetime, timedelta
    
    User = get_user_model()
    recent_threshold = timezone.now() - timedelta(hours=1)
    
    # Find users with recent raw events
    from tracker.models import RawEvent
    active_users = RawEvent.objects.filter(
        ts_utc__gte=recent_threshold
    ).values_list('user', flat=True).distinct()
    
    for user_id in active_users:
        try:
            user = User.objects.get(id=user_id)
            compact_rawevents_into_blocks(user=user)
        except Exception as e:
            print(f"Compaction failed for user {user_id}: {e}")