# tracker/tasks.py
from tracker.utils.monitoring import capture_exception

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