# tracker/signals.py
from __future__ import annotations

import os
import sys
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from django.utils import timezone

from tracker.models import Block, Organization, OrganizationMembership
from tracker.utils.monitoring import capture_exception

from django.contrib.auth.models import User, Group

logger = logging.getLogger(__name__)


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
# Block auto-classification on save
# ────────────────────────────────────────────────────────────────────────────────

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
            from tracker.tasks import classify_block_task
            classify_block_task.delay(blk.pk)
        except Block.DoesNotExist:
            return
        except Exception as e:
            # Don't let Redis/Celery errors break block creation
            pass
    
    transaction.on_commit(_do)


# ────────────────────────────────────────────────────────────────────────────────
# Auto-create "Internal" client for new organizations
# ────────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender=Organization, dispatch_uid="tracker.org.create_internal_client")
def create_internal_client(sender, instance, created, **kwargs):
    """
    Auto-create an 'Internal' client for every new organization.
    
    Used for non-client work: team meetings, admin, training, PTO,
    internal projects, R&D, business development, etc.
    """
    if _running_management_command():
        return
    
    if not created:
        return
    
    from tracker.models import Client
    
    try:
        Client.objects.get_or_create(
            org=instance,
            code='INTERNAL',
            defaults={
                'name': 'Internal',
                'is_active': True,
                'visibility': 'all',
            }
        )
        # After the existing 'Internal' client creation
        Client.objects.get_or_create(
            org=instance,
            code='INTERNAL_TAX',
            defaults={
                'name': 'Internal - Tax',
                'is_active': True,
                'is_billable': False,
                'visibility': 'all',
            }
        )

        logger.info(f"[ORG] Created 'Internal' + 'Internal - Tax' clients for org: {instance.name}")
    except Exception as e:
        logger.warning(f"[ORG] Failed to create Internal client for {instance.name}: {e}")



def backfill_internal_clients():
    """
    One-time helper to create 'Internal' client for all existing orgs.
    
    Run from Django shell:
        from tracker.signals import backfill_internal_clients
        backfill_internal_clients()
    """
    from tracker.models import Client
    
    created_count = 0
    skipped_count = 0
    
    for org in Organization.objects.all():
        _, was_created = Client.objects.get_or_create(
            org=org,
            code='INTERNAL',
            defaults={
                'name': 'Internal',
                'is_active': True,
                'visibility': 'all',
            }
        )
        if was_created:
            created_count += 1
            logger.info(f"[BACKFILL] Created 'Internal' client for: {org.name}")
        else:
            skipped_count += 1
    
    logger.info(f"[BACKFILL] Done. Created: {created_count}, Already existed: {skipped_count}")
    return {'created': created_count, 'skipped': skipped_count}


# ────────────────────────────────────────────────────────────────────────────────
# Auto-create OrganizationMembership when users are added to Groups via admin
# ────────────────────────────────────────────────────────────────────────────────

@receiver(m2m_changed, sender=User.groups.through)
def auto_create_org_membership(sender, instance, action, pk_set, **kwargs):
    """
    When a user is added to a Group via Django admin,
    automatically create the corresponding OrganizationMembership.
    """
    if action != "post_add":
        return
    
    user = instance
    
    for group_id in pk_set:
        try:
            group = Group.objects.get(id=group_id)
            
            # Find or create Organization with same name as Group
            org, org_created = Organization.objects.get_or_create(
                name=group.name,
                defaults={
                    'billing_email': '',
                    'billing_contact': '',
                }
            )
            
            if org_created:
                logger.info(f"[ORG] Created Organization: {org.name}")
            
            # Create OrganizationMembership if it doesn't exist
            membership, mem_created = OrganizationMembership.objects.get_or_create(
                user=user,
                organization=org,
                defaults={
                    'role': 'member',
                    'invited_by': None,
                }
            )
            
            if mem_created:
                logger.info(f"[ORG] Auto-created membership: {user.username} → {org.name} (member)")
                    
        except Exception as e:
            logger.warning(f"[ORG] Error in auto_create_org_membership: {e}")