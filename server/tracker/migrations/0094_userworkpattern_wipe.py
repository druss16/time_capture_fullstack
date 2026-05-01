"""
Migration 0094 - UserWorkPattern low-quality cleanup.

Removes patterns matching ANY of:
  1. confidence_score < 0.7 AND total_predictions >= 5  (demonstrably-wrong)
  2. total_predictions < 5 AND last_seen older than 90 days  (stale)
  3. pattern_key matches generic email/dialog patterns (likely poisoned)

PRESERVED:
  - confidence_score >= 0.7 with total_predictions >= 5
  - Recently confirmed (last_confirmed within 90 days)
  - High occurrence count (>= 50) regardless of confidence

Dry-run: TT_WIPE_DRY_RUN=1 python manage.py migrate tracker 0094

Reverse migration is a no-op with warning - cannot restore deleted rows.
"""

import os
import logging
from datetime import timedelta
from django.db import migrations
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


POISONED_KEY_SUBSTRINGS = [
    'inbox',
    'outlook.com',
    'sent items',
    'drafts',
    'untitled',
    'document1',
    'book1',
    'save as',
    'open',
    'print',
    'preferences',
    'settings',
]


def wipe_low_quality_patterns(apps, schema_editor):
    UserWorkPattern = apps.get_model('tracker', 'UserWorkPattern')

    dry_run = os.environ.get('TT_WIPE_DRY_RUN', '').lower() in ('1', 'true', 'yes')

    now = timezone.now()
    ninety_days_ago = now - timedelta(days=90)

    demonstrably_wrong = Q(
        confidence_score__lt=0.7,
        total_predictions__gte=5,
    )
    stale_unconfirmed = Q(
        total_predictions__lt=5,
        last_seen__lt=ninety_days_ago,
    )
    poisoned_q = Q()
    for substring in POISONED_KEY_SUBSTRINGS:
        poisoned_q |= Q(pattern_key__icontains=substring)

    high_occurrence_protected = Q(occurrence_count__gte=50)
    recently_confirmed_protected = Q(last_confirmed__gte=ninety_days_ago)

    delete_qs = (
        UserWorkPattern.objects
        .filter(demonstrably_wrong | stale_unconfirmed | poisoned_q)
        .exclude(high_occurrence_protected)
        .exclude(recently_confirmed_protected)
    )

    total_patterns = UserWorkPattern.objects.count()
    delete_count = delete_qs.count()

    dw_count = (UserWorkPattern.objects.filter(demonstrably_wrong)
                .exclude(high_occurrence_protected)
                .exclude(recently_confirmed_protected).count())
    su_count = (UserWorkPattern.objects.filter(stale_unconfirmed)
                .exclude(high_occurrence_protected)
                .exclude(recently_confirmed_protected).count())
    pk_count = (UserWorkPattern.objects.filter(poisoned_q)
                .exclude(high_occurrence_protected)
                .exclude(recently_confirmed_protected).count())

    print("")
    print("[0094 WIPE] Pre-flight summary:")
    print(f"  Total UserWorkPattern rows: {total_patterns}")
    print(f"  Will be DELETED:            {delete_count}")
    print("")
    print(f"  Breakdown by criterion (overlapping):")
    print(f"    Demonstrably wrong:    {dw_count}")
    print(f"    Stale unconfirmed:     {su_count}")
    print(f"    Poisoned key substr:   {pk_count}")
    print("")
    print(f"  PRESERVED: {total_patterns - delete_count}")
    print(f"  Dry run mode: {dry_run}")
    print("")

    if dry_run:
        print("[0094 WIPE] DRY RUN - no patterns deleted. Exiting.")
        return

    deleted, _ = delete_qs.delete()
    print(f"[0094 WIPE] Deleted {deleted} patterns.")
    logger.info(f"[0094 WIPE] Deleted {deleted} patterns.")


def reverse_wipe(apps, schema_editor):
    print("")
    print("=" * 60)
    print("[0094 WIPE REVERSE] WARNING: cannot reverse - rows are gone.")
    print("Restore from a backup taken before migration 0094 was applied.")
    print("=" * 60)
    print("")


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0093_backfill_classification_state'),
    ]

    operations = [
        migrations.RunPython(
            wipe_low_quality_patterns,
            reverse_code=reverse_wipe,
        ),
    ]
