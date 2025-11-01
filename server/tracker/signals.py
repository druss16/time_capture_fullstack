# tracker/signals.py
from __future__ import annotations
import os, sys, threading
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

from tracker.models import Block
from tracker.utils.monitoring import capture_exception

_tls = threading.local()

# --- helper: detect recursion
def _guarded() -> bool:
    return getattr(_tls, "skip_block_classify_signal", False)

class _SkipSignal:
    def __enter__(self):
        _tls.skip_block_classify_signal = True
    def __exit__(self, exc_type, exc, tb):
        _tls.skip_block_classify_signal = False

# --- skip during management commands
def _running_management_command() -> bool:
    argv = " ".join(os.environ.get("DJANGO_CMDLINE", "") or " ".join(sys.argv)).lower()
    return any(k in argv for k in (" makemigrations", " migrate", " collectstatic", " loaddata "))

# --- logic to decide if AI should run again
def _needs_classification(b: Block, created: bool) -> bool:
    if getattr(b, "locked", False):
        return False
    if created:
        return True
    if hasattr(b, "has_ai_inputs_changed") and b.has_ai_inputs_changed():
        return True
    ai_client = getattr(b, "ai_extracted_client", None)
    ai_cat = getattr(b, "ai_category", None)
    ai_conf = float(getattr(b, "ai_confidence", 0.0) or 0.0)
    return (not ai_client) or (not ai_cat) or (ai_conf < 0.5)

@receiver(post_save, sender=Block, dispatch_uid="tracker.block.auto_classify")
def _auto_classify_block(sender, instance: Block, created: bool, **kwargs):
    """
    Automatically classify Blocks after save.
    Runs *after commit* to avoid partial writes.
    Safe: will not loop recursively or crash migrations.
    """
    if _running_management_command():
        return
    if _guarded():
        return
    if not _needs_classification(instance, created):
        return

    def _do():
        try:
            blk = Block.objects.get(pk=instance.pk)
            from tracker.tasks import classify_block_task
            classify_block_task.delay(blk.pk)  # works with or without Celery
        except Block.DoesNotExist:
            pass
        except Exception as e:
            capture_exception(e)
            if getattr(settings, "DEBUG", False):
                print(f"[signals] classify_block error on Block {instance.pk}: {e}")

    transaction.on_commit(_do)