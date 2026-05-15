"""
tracker/management/commands/rebase_to_canonical.py

Plan B Step 6.TL.1 — replace an org's TaskTypes with the canonical set
from CPA_TASK_TYPES. Used to bring an org's Layer 2 (TaskTypes) into
alignment with the canonical Layer 1 vocabulary, so that
provision_firm --seed-category-mappings can subsequently seed a clean
1:1 bridge.

WHAT IT DOES (in a single transaction):
  1. Find the org's default TaskTypeSet (creates "Standard" if missing).
  2. Delete all existing TaskTypes for the org. CASCADE clears their
     TaskTypeSetMember rows automatically.
  3. Create the canonical 19 TaskTypes (from CPA_TASK_TYPES).
  4. Add all 19 to the default TaskTypeSet with sort_order matching the
     canonical list.

If any step fails, the transaction rolls back — the org is untouched.

SAFETY:
  - --dry-run shows what WOULD happen; writes nothing.
  - --confirm is REQUIRED for a live run. Without --confirm the command
    refuses and explains.
  - Refuses to run if Block.task_type FKs exist for this org (would
    orphan blocks). Run AFTER blocks have been migrated, or BEFORE
    blocks have any task_type set.

Usage:
    # Preview
    python manage.py rebase_to_canonical --org tl-wall --dry-run

    # Live (requires --confirm)
    python manage.py rebase_to_canonical --org tl-wall --confirm
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tracker.models import Organization, Block, TaskType
from tracker.models_task_type_sets import TaskTypeSet, TaskTypeSetMember
from tracker.industry_categories import CPA_TASK_TYPES


class Command(BaseCommand):
    help = (
        "Replace an org's TaskTypes with the canonical CPA_TASK_TYPES set. "
        "Destructive — requires --confirm for live runs."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--org', required=True,
            help='Organization slug.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview without writing.',
        )
        parser.add_argument(
            '--confirm', action='store_true',
            help='REQUIRED for a live run. Refuses to write without it.',
        )

    def handle(self, *args, **options):
        org_slug = options['org']
        dry_run = options['dry_run']
        confirm = options['confirm']

        # ─── Resolve org ───
        try:
            org = Organization.objects.get(slug=org_slug)
        except Organization.DoesNotExist:
            raise CommandError(f'Organization with slug "{org_slug}" not found.')

        # ─── Safety: refuse live runs without --confirm ───
        if not dry_run and not confirm:
            raise CommandError(
                'This is a destructive operation. Re-run with --confirm '
                '(or use --dry-run to preview).'
            )

        mode = 'DRY RUN' if dry_run else 'LIVE'
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'  REBASE TASKTYPES TO CANONICAL: {org.name}')
        self.stdout.write(f'  MODE: {mode}')
        self.stdout.write(f'{"=" * 60}\n')

        # ─── Safety: refuse if any Block.task_type FK exists for this org ───
        block_task_type_count = Block.objects.filter(
            org=org, task_type__isnull=False,
        ).count()
        if block_task_type_count > 0:
            raise CommandError(
                f'REFUSED: {block_task_type_count} blocks in this org have '
                f'task_type set. Deleting the TaskTypes would set those FKs '
                f'to NULL (per on_delete=SET_NULL). Either:\n'
                f'  (a) Run this BEFORE migrate_block_categories (when '
                f'task_type is still all null), OR\n'
                f'  (b) Re-run migrate_block_categories AFTER this rebase '
                f'to re-populate task_type with the new canonical TaskTypes.\n'
                f'Aborting to avoid silent FK loss.'
            )

        # ─── Inspect current state ───
        existing = TaskType.objects.filter(org=org).order_by('sort_order', 'name')
        self.stdout.write(f'Current TaskTypes ({existing.count()}):')
        for tt in existing:
            self.stdout.write(f'  {tt.code:10s} {tt.name}')

        self.stdout.write(f'\nCanonical TaskTypes to create ({len(CPA_TASK_TYPES)}):')
        for cfg in CPA_TASK_TYPES:
            self.stdout.write(
                f'  {cfg["code"]:10s} {cfg["name"]}  '
                f'(billable={cfg["is_billable"]})'
            )

        if dry_run:
            self.stdout.write(self.style.WARNING(
                '\nDRY RUN — no changes made.'
            ))
            return

        # ─── LIVE RUN: do everything in a single transaction ───
        with transaction.atomic():
            # Step 1: find or create the default TaskTypeSet
            default_set = TaskTypeSet.objects.filter(
                org=org, is_default=True,
            ).first()
            if default_set is None:
                default_set = TaskTypeSet.objects.create(
                    org=org,
                    name='Standard',
                    description='Default firm-wide task type set.',
                    is_default=True,
                    source='manual',
                )
                self.stdout.write(self.style.SUCCESS(
                    f'\n✓ Created default TaskTypeSet "Standard"'
                ))
            else:
                self.stdout.write(
                    f'\n→ Using existing default set "{default_set.name}"'
                )

            # Step 2: delete all existing TaskTypes for this org.
            # CASCADE handles TaskTypeSetMember automatically.
            deleted_count, _ = TaskType.objects.filter(org=org).delete()
            self.stdout.write(self.style.SUCCESS(
                f'✓ Deleted {deleted_count} old TaskType-related rows '
                f'(TaskTypes + TaskTypeSetMembers via CASCADE)'
            ))

            # Step 3: create the canonical 19.
            created_task_types = []
            for cfg in CPA_TASK_TYPES:
                tt = TaskType.objects.create(
                    org=org,
                    code=cfg['code'],
                    name=cfg['name'],
                    is_billable=cfg['is_billable'],
                    is_active=True,
                )
                created_task_types.append(tt)
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created {len(created_task_types)} canonical TaskTypes'
            ))

            # Step 4: add all 19 to the default set, sort_order = list position
            for idx, tt in enumerate(created_task_types):
                TaskTypeSetMember.objects.create(
                    set=default_set,
                    task_type=tt,
                    sort_order=idx,
                )
            self.stdout.write(self.style.SUCCESS(
                f'✓ Added {len(created_task_types)} TaskTypes to '
                f'"{default_set.name}" set'
            ))

        self.stdout.write(self.style.SUCCESS('\nRebase complete.'))
        self.stdout.write(
            '\nNEXT STEPS:\n'
            '  1. provision_firm --org <slug> --seed-category-mappings '
            '(now seeds all 19 1:1)\n'
            '  2. migrate_block_categories --org <slug> --dry-run, then live'
        )
