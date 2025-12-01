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

    # Don't hammer the LLM if we just ran
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
# COMMENTED OUT: classify_block_task doesn't exist yet (needs Celery setup)
# Using ai_suggestions_today() endpoint for batch classification instead
# Uncomment when Celery is properly configured

@receiver(post_save, sender=Block, dispatch_uid="tracker.block.auto_classify")
def _auto_classify_block(sender, instance: Block, created: bool, **kwargs):
    """
    Auto-classify new blocks using simple pattern matching.
    Runs synchronously on save (fast, no LLM).
    """
    if _running_management_command():
        return
    if _guarded():
        return
    
    # Only classify new, uncategorized blocks
    if not created or instance.is_categorized:
        return
    
    def _do():
        try:
            blk = Block.objects.get(pk=instance.pk)
            from tracker.tasks import classify_block_task  # ✅ ADD THIS LINE IF MISSING
            classify_block_task.delay(blk.pk)  # ✅ Calls Celery task
        except Block.DoesNotExist:
            return
    
    transaction.on_commit(_do)


from django.apps import AppConfig

class TrackerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tracker'
    
    def ready(self):
        import tracker.signals  # ← Import signals