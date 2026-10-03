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
from django.utils.text import slugify

from tracker.models import Block, Organization, OrganizationMembership, OrgProfile
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
    Auto-classify new blocks on creation via ClassificationService.
 
    Immutability guarantee: this signal only enqueues classification for
    blocks in 'captured' state (or NULL/legacy). Once a block enters any
    other state (committed/proposed/suppressed), automated re-classification
    never touches it again. Only user manual edits can change it.
    """
    if _running_management_command():
        return
    if _guarded():
        return
 
    # Only classify new blocks
    if not created:
        return
 
    # Skip if legacy is_categorized flag is set (already classified by some path)
    if instance.is_categorized:
        return
 
    # Immutability check: skip blocks already in a non-captured state.
    # This protects against re-classification of blocks that have been
    # explicitly handled by ClassificationService.
    state = getattr(instance, 'classification_state', None)
    if state and state != 'captured':
        return
 
    def _do():
        try:
            blk = Block.objects.get(pk=instance.pk)
            from tracker.tasks import classify_block_task
            classify_block_task.delay(blk.pk)
        except Block.DoesNotExist:
            return
        except Exception:
            # Don't let Redis/Celery errors break block creation
            pass
 
    transaction.on_commit(_do)


# ────────────────────────────────────────────────────────────────────────────────
# Auto-create "Internal" client for new organizations
# ────────────────────────────────────────────────────────────────────────────────

def ensure_internal_tax_client(org):
    from tracker.models import Client
    client, _ = Client.objects.get_or_create(
        org=org,
        code='INTERNAL_TAX',
        defaults={
            'name': 'Internal - Tax',
            'is_active': True,
            'visibility': 'all',
        }
    )
    return client


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
        # 'Internal - Tax' is a CPA firm's own-tax bucket (UltraTax routing,
        # the tax-returns lens). An agency or law firm has no use for it, so
        # only CPA firms get one; ensure_internal_tax_client adds it if a firm
        # is switched to CPA later.
        if instance.industry_type == 'cpa':
            ensure_internal_tax_client(instance)

        logger.info(f"[ORG] Created internal client(s) for org: {instance.name}")
    except Exception as e:
        logger.warning(f"[ORG] Failed to create Internal client for {instance.name}: {e}")



def backfill_internal_clients():
    """
    One-time helper to create 'Internal' + 'Internal - Tax' clients for all existing orgs.
    
    Run from Django shell:
        from tracker.signals import backfill_internal_clients
        backfill_internal_clients()
    """
    from tracker.models import Client
    
    internal_created = 0
    internal_tax_created = 0
    skipped = 0
    
    for org in Organization.objects.all():
        # Internal
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
            internal_created += 1
            logger.info(f"[BACKFILL] Created 'Internal' for: {org.name}")
        else:
            skipped += 1
        
        # Internal - Tax
        _, was_created = Client.objects.get_or_create(
            org=org,
            code='INTERNAL_TAX',
            defaults={
                'name': 'Internal - Tax',
                'is_active': True,
                'visibility': 'all',
            }
        )
        if was_created:
            internal_tax_created += 1
            logger.info(f"[BACKFILL] Created 'Internal - Tax' for: {org.name}")
    
    logger.info(
        f"[BACKFILL] Done. Internal created: {internal_created}, "
        f"Internal-Tax created: {internal_tax_created}, Internal already existed: {skipped}"
    )
    return {
        'internal_created': internal_created,
        'internal_tax_created': internal_tax_created,
        'internal_skipped': skipped,
    }


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
    
    from tracker.models_onboarding_console import ROLE_GROUPS

    for group_id in pk_set:
        try:
            group = Group.objects.get(id=group_id)
            # Some groups are roles, not firms. Granting the Onboarding
            # Operator role made an organization called "Onboarding Operator"
            # and put the operator in it — where get_user_org's unordered
            # .first() could land them.
            if group.name in ROLE_GROUPS:
                continue
            
            # Find or create Organization with same name as Group. The billing
            # fields live on OrgProfile, not Organization: passing them as
            # Organization defaults raised FieldError on every create, so
            # this signal never made an org or a membership.
            org = Organization.objects.filter(name=group.name).order_by('id').first()
            if org is None:
                base_slug = slugify(group.name)[:40] or 'org'
                slug, counter = base_slug, 1
                while Organization.objects.filter(slug=slug).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1
                org = Organization.objects.create(name=group.name, slug=slug)
                logger.info(f"[ORG] Created Organization: {org.name}")

            OrgProfile.objects.get_or_create(org=org)
            
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