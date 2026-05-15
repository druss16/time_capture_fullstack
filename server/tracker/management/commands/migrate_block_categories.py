"""
tracker/management/commands/migrate_block_categories.py

Plan B Step 5/6 — migrate existing Blocks to the canonical category
vocabulary AND backfill Block.task_type.

For a given org, this command:
  1. Remaps each Block.ai_category from the org's old/messy vocabulary to
     the canonical Layer 1 category list (per-org REMAP_TABLES below).
  2. Rebuilds Block.category_hours keyed on canonical names (faithful —
     every key remapped; hours merged if two old categories collapse to
     one canonical category).
  3. Backfills Block.task_type by resolving the canonical category through
     the org's CategoryTaskTypeMapping table (the Layer 1 -> Layer 2 bridge).

Strings not present in an org's remap table are LEFT ALONE and counted as
'unmapped' (reported, never guessed). Blank ai_category stays blank /
task_type stays null — those blocks were never classified.

Usage:
    # Preview — no changes
    python manage.py migrate_block_categories --org anderson-associates --dry-run

    # Preview just the first 50 blocks
    python manage.py migrate_block_categories --org anderson-associates --dry-run --limit 50

    # Live run
    python manage.py migrate_block_categories --org anderson-associates
"""

from django.core.management.base import BaseCommand, CommandError

from tracker.models import Organization, Block
from tracker.services.task_type_resolver import resolve_task_type_for_category


# =============================================================================
# PER-ORG REMAP TABLES  (Plan B design doc, Part 3)
# Keyed by org_id. Maps the org's CURRENT ai_category strings -> canonical.
# A current string deliberately ABSENT from a table is left alone (unmapped).
# =============================================================================

REMAP_TABLES = {
    # ORG 19 — Anderson & Associates CPAs (internally consistent)
    19: {
        'Tax Preparation': 'Tax Preparation',
        'Bookkeeping': 'Accounting/Bookkeeping',
        'Document Review': 'Document Management',
        'Research': 'Research',
        'Email/Communication': 'Email/Communication',
        'Meetings': 'Meetings',
        'Admin/Internal': 'Administration',
    },
    # ORG 23 — Pinnacle Advisory CPAs (internally consistent)
    23: {
        'Tax Preparation': 'Tax Preparation',
        'Tax Planning': 'Tax Planning',
        'Audit & Assurance': 'Audit/Assurance',
        'Bookkeeping': 'Accounting/Bookkeeping',
        'Advisory/Consulting': 'Advisory',
        'Client Communication': 'Email/Communication',
        'Research': 'Research',
        'Document Review': 'Document Management',
        'Admin/Internal': 'Administration',
        'Training': 'Training',
    },
    # ORG 21 — TL Wall Accounting (was on the wrong industry list)
    21: {
        'Tax Preparation': 'Tax Preparation',
        'Bookkeeping': 'Accounting/Bookkeeping',
        'Administration': 'Administration',
        'Email/Communication': 'Email/Communication',
        'Documentation': 'Document Management',
        'Document Management': 'Document Management',
        'Research': 'Research',
        'Meetings': 'Meetings',
        'Client Meeting': 'Meetings',
        'Billing / Admin': 'Billing/Admin',
        'Personal/Non-Billable': 'Personal/Non-Billable',
        'Idle': 'Idle',
        'Client Work': 'General Client Work',
        'Project Work': 'General Client Work',
        'Calls': 'General Client Work',
        # '(empty)' deliberately absent — blank ai_category stays blank.
    },
}


class Command(BaseCommand):
    help = (
        'Plan B: migrate a org\'s Blocks to the canonical category '
        'vocabulary and backfill task_type.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--org', required=True,
            help='Organization slug to migrate.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview changes without writing.',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Only process the first N blocks (for testing).',
        )

    def handle(self, *args, **options):
        org_slug = options['org']
        dry_run = options['dry_run']
        limit = options['limit']

        # ─── Resolve org ───
        try:
            org = Organization.objects.get(slug=org_slug)
        except Organization.DoesNotExist:
            raise CommandError(f'Organization with slug "{org_slug}" not found.')

        remap = REMAP_TABLES.get(org.id)
        if remap is None:
            raise CommandError(
                f'No REMAP_TABLE defined for org {org.id} ({org.name}). '
                f'Add one to migrate_block_categories.py before running.'
            )

        mode = 'DRY RUN' if dry_run else 'LIVE'
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'  MIGRATE BLOCK CATEGORIES: {org.name}')
        self.stdout.write(f'  MODE: {mode}')
        self.stdout.write(f'{"=" * 60}\n')

        blocks_qs = Block.objects.filter(org=org).order_by('id')
        if limit:
            blocks_qs = blocks_qs[:limit]

        # Materialize to a list — NOT .iterator(). A server-side cursor
        # gets invalidated by block.save() calls mid-loop. These orgs are
        # at most a few thousand blocks; a list is fine and safe.
        blocks = list(blocks_qs)
        total = len(blocks)
        self.stdout.write(f'Processing {total} blocks...\n')

        # Counters
        remapped = 0            # ai_category changed to a canonical value
        unchanged = 0           # ai_category already canonical (in remap as identity)
        skipped_blank = 0       # blank ai_category — left alone
        unmapped = 0            # ai_category not in remap table — left alone
        task_type_set = 0       # task_type FK populated
        task_type_null = 0      # canonical category had no mapping — left null
        # before -> after category tally
        transitions = {}

        for block in blocks:
            old_cat = (block.ai_category or '').strip()

            # Blank ai_category — never classified, leave it.
            if not old_cat:
                skipped_blank += 1
                continue

            # Not in the remap table — leave alone, report.
            if old_cat not in remap:
                unmapped += 1
                key = f'{old_cat!r} -> (UNMAPPED, left alone)'
                transitions[key] = transitions.get(key, 0) + 1
                continue

            canonical = remap[old_cat]
            key = f'{old_cat!r} -> {canonical!r}'
            transitions[key] = transitions.get(key, 0) + 1

            if canonical == old_cat:
                unchanged += 1
            else:
                remapped += 1

            # ─── Rebuild category_hours faithfully ───
            # Remap every key; merge hours if two old keys collapse to one.
            new_hours = {}
            old_hours = block.category_hours or {}
            if old_hours:
                for k, v in old_hours.items():
                    mapped_k = remap.get(k.strip(), k)  # unmapped keys kept as-is
                    new_hours[mapped_k] = new_hours.get(mapped_k, 0) + v
            else:
                # No category_hours at all — synthesize one from the block's
                # duration so the canonical category is still represented.
                hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.01
                new_hours = {canonical: hours}

            # ─── Resolve task_type via the mapping table ───
            resolved_tt = resolve_task_type_for_category(org, canonical)

            if not dry_run:
                block.ai_category = canonical
                block.category_hours = new_hours
                if resolved_tt is not None:
                    block.task_type = resolved_tt
                block.save(
                    update_fields=['ai_category', 'category_hours', 'task_type'],
                    force_classifier=True,
                )

            if resolved_tt is not None:
                task_type_set += 1
            else:
                task_type_null += 1

        # ─── Summary ───
        self.stdout.write('\n── Category transitions ──')
        for key in sorted(transitions.keys()):
            self.stdout.write(f'  {transitions[key]:6d}  {key}')

        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write('  SUMMARY')
        self.stdout.write(f'{"=" * 60}')
        self.stdout.write(f'  Total blocks:           {total}')
        self.stdout.write(f'  ai_category remapped:   {remapped}')
        self.stdout.write(f'  ai_category unchanged:  {unchanged} (already canonical)')
        self.stdout.write(f'  Blank — left alone:     {skipped_blank}')
        self.stdout.write(f'  Unmapped — left alone:  {unmapped}')
        self.stdout.write(f'  task_type set:          {task_type_set}')
        self.stdout.write(f'  task_type left null:    {task_type_null} (no mapping for canonical category)')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN — no changes were made.'))
        else:
            self.stdout.write(self.style.SUCCESS('\nMigration complete.'))
