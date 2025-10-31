# tracker/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Block
from .services.classify_block import classify_block

@receiver(post_save, sender=Block)
def _auto_classify_block(sender, instance: Block, created, **kwargs):
    # avoid recursion / unnecessary calls
    if created and not instance.ai_processed_at:
        try:
            classify_block(instance)
        except Exception:
            pass