"""
Migration 0093 — Backfill classification_state from existing is_categorized data.

This is a DATA migration. It reads every existing block and sets the new
classification_state field appropriately:
  - is_categorized=True  -> classification_state='committed'
  - is_categorized=False -> classification_state='captured'
  - approved=True        -> classification_state='committed' (already locked)

Also backfills state_changed_at and state_changed_by where possible:
  - If categorized_at is set, use it for state_changed_at
  - state_changed_by is mapped from categorized_by ('ai' -> 'classifier', etc.)

PRE-RUN VALIDATION:
  - This migration prints a summary BEFORE applying changes.
  - Dry-run: TT_BACKFILL_DRY_RUN=1 python manage.py migrate tracker 0093

Estimated runtime:
  - TL Wall: ~50,000 blocks -> 5-15 seconds
  - At scale (1M blocks): 5-10 minutes

Reverse migration:
  - Sets all classification_state values back to default ('captured').
  - Clears state_changed_at and state_changed_by.
  - DOES NOT touch is_categorized or categorized_by.
"""

import os
import logging
from django.db import migrations

logger = logging.getLogger(__name__)


CATEGORIZED_BY_MAP = {
    'ai':         'classifier',
    'manual':     'user',
    'correction': 'correction',
    'import':     'admin_bulk',
    'pattern':    'classifier',
}


def backfill_classification_state(apps, schema_editor):
    Block = apps.get_model('tracker', 'Block')

    dry_run = os.environ.get('TT_BACKFILL_DRY_RUN', '').lower() in ('1', 'true', 'yes')

    total = Block.all_objects.count() if hasattr(Block, 'all_objects') else Block.objects.count()
    categorized_count = Block.objects.filter(is_categorized=True).count()
    uncategorized_count = Block.objects.filter(is_categorized=False).count()
    approved_count = Block.objects.filter(approved=True).count()

    summary = (
        f"\n[0093 BACKFILL] Pre-flight summary:\n"
        f"  Total blocks:           {total:>10}\n"
        f"  Will become COMMITTED:  {categorized_count:>10}  (currently is_categorized=True)\n"
        f"  Will become CAPTURED:   {uncategorized_count:>10}  (currently is_categorized=False)\n"
        f"  Of these, approved:     {approved_count:>10}  (will also be COMMITTED)\n"
        f"  Dry run mode:           {dry_run}\n"
    )
    print(summary)
    logger.info(summary)

    if dry_run:
        print("[0093 BACKFILL] DRY RUN - no changes applied. Exiting.")
        return

    BATCH_SIZE = 5000
    updated_committed = 0

    qs = Block.objects.filter(is_categorized=True)
    while True:
        ids = list(qs.values_list('id', flat=True)[:BATCH_SIZE])
        if not ids:
            break
        for block in Block.objects.filter(id__in=ids).only('id', 'categorized_at', 'categorized_by'):
            new_state_by = CATEGORIZED_BY_MAP.get(block.categorized_by, 'classifier')
            Block.objects.filter(id=block.id).update(
                classification_state='committed',
                state_changed_at=block.categorized_at,
                state_changed_by=new_state_by,
            )
            updated_committed += 1
        qs = Block.objects.filter(is_categorized=True, classification_state='captured')

        if updated_committed % 10000 == 0 and updated_committed > 0:
            print(f"[0093 BACKFILL] Committed: {updated_committed:,} blocks updated...")

    final_summary = (
        f"\n[0093 BACKFILL] Complete:\n"
        f"  Committed: {updated_committed:>10}\n"
        f"  Captured:  {uncategorized_count:>10}  (default, no update needed)\n"
    )
    print(final_summary)
    logger.info(final_summary)


def reverse_backfill(apps, schema_editor):
    Block = apps.get_model('tracker', 'Block')

    print("\n[0093 BACKFILL REVERSE] Clearing all classification_state values...")

    Block.objects.exclude(classification_state='captured').update(
        classification_state='captured',
        state_changed_at=None,
        state_changed_by=None,
    )

    print("[0093 BACKFILL REVERSE] Complete.\n")


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0092_calendarevent_mailsignal_userintegration_and_more'),
    ]

    operations = [
        migrations.RunPython(
            backfill_classification_state,
            reverse_code=reverse_backfill,
        ),
    ]
