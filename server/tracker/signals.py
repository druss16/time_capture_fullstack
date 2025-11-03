# tracker/signals.py
from __future__ import annotations

import os
import sys
import threading
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from tracker.models import Block
from tracker.utils.monitoring import capture_exception

# ────────────────────────────────────────────────────────────────────────────────
# Recursion guard (defensive; classify runs out-of-band via task shim anyway)
_tls = threading.local()

def _guarded() -> bool:
    return getattr(_tls, "skip_block_classify_signal", False)

class _SkipSignal:
    def __enter__(self):
        _tls.skip_block_classify_signal = True
    def __exit__(self, exc_type, exc, tb):
        _tls.skip_block_classify_signal = False

# ────────────────────────────────────────────────────────────────────────────────
# Skip during management commands to keep CI/migrations clean
def _running_management_command() -> bool:
    argv = " ".join(os.environ.get("DJANGO_CMDLINE", "") or " ".join(sys.argv)).lower()
    return any(k in argv for k in (" makemigrations", " migrate", " collectstatic", " loaddata "))

# ────────────────────────────────────────────────────────────────────────────────
# Classification policy
COOLDOWN_SECONDS = 60  # prevent rapid re-classifications on quick edits

def _needs_classification(b: Block, created: bool) -> bool:
    """Return True if we should (re)classify this Block."""
    if getattr(b, "locked", False):
        return False

    # Always classify on create
    if created:
        return True

    # Don’t hammer the LLM if we just ran
    if b.ai_processed_at and timezone.now() - b.ai_processed_at < timedelta(seconds=COOLDOWN_SECONDS):
        return False

    # If the inputs that drive AI changed, reclassify
    if hasattr(b, "has_ai_inputs_changed") and b.has_ai_inputs_changed():
        return True

    # If we have low/empty AI fields, try again
    ai_client = getattr(b, "ai_extracted_client", None)
    ai_cat = getattr(b, "ai_category", None)
    ai_conf = float(getattr(b, "ai_confidence", 0.0) or 0.0)
    if not ai_client or not ai_cat or ai_conf < 0.5:
        return True

    return False

# ────────────────────────────────────────────────────────────────────────────────
@receiver(post_save, sender=Block, dispatch_uid="tracker.block.auto_classify")
def _auto_classify_block(sender, instance: Block, created: bool, **kwargs):
    """
    Automatically classify Blocks (client + task/category) after save.

    - Defers work until transaction commit
    - Uses a task shim that works with/without Celery
    - Guarded against recursion and management commands
    """
    if _running_management_command():
        return
    if _guarded():
        return
    if not _needs_classification(instance, created):
        return

    def _do():
        try:
            blk = Block.objects.get(pk=instance.pk)  # re-fetch latest
            # Import inside the function to avoid import cycles at import time
            from tracker.tasks import classify_block_task
            # This .delay works even if Celery is not running (shim falls back to sync)
            classify_block_task.delay(blk.pk)
        except Block.DoesNotExist:
            # Deleted before commit — ignore
            return
        except Exception as e:
            capture_exception(e)
            if getattr(settings, "DEBUG", False):
                print(f"[signals] classify_block error on Block {getattr(instance, 'pk', '?')}: {e}")

    transaction.on_commit(_do)