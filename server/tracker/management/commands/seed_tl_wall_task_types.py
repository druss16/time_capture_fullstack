"""
Seed TaskTypes for TL Wall (org_id=21) based on their actual category usage.

Generated from a survey of 5000 recent Block.category_hours keys.

Run:
    python manage.py seed_tl_wall_task_types --dry-run
    python manage.py seed_tl_wall_task_types --commit

Safe to re-run — uses get_or_create.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import Organization, TaskType
from tracker.models_task_type_sets import TaskTypeSet, TaskTypeSetMember


# (code, name, billable, default_rate, color, sort_order, matches_category_strings)
# `matches_category_strings` records the category names from production usage
# that this TaskType represents. Kept here for documentation; the resolver in
# tracker/services/view_integration_helpers.py uses name+code matching at
# runtime, not this list.
TASK_TYPES = [
    # ─── Billable client work ───
    ('TAX',     'Tax Preparation',      True,  None, '#1F3D34', 10,
        ['Tax Preparation']),
    ('TAXRES',  'Tax Research',         True,  None, '#3D5F4E', 20,
        ['Tax Research']),
    ('BOOK',    'Bookkeeping',          True,  None, '#5E8A6F', 30,
        ['Bookkeeping']),
    ('RECON',   'Reconciliation',       True,  None, '#7DA98E', 40,
        ['Reconciliation']),
    ('DOC',     'Documentation',        True,  None, '#A4B89C', 50,
        ['Documentation', 'Document Management']),
    ('RES',     'Research',             True,  None, '#B8C9AB', 60,
        ['Research']),
    ('PROJ',    'Project Work',         True,  None, '#8A4F2D', 70,
        ['Project Work', 'Client Work']),

    # ─── Communication ───
    ('EMAIL',   'Email / Communication', True, None, '#C28940', 80,
        ['Email/Communication', 'Client Email / Communication']),
    ('MEET',    'Meetings',              True, None, '#D9A86C', 90,
        ['Meetings', 'Client Meeting']),
    ('CALL',    'Calls',                 True, None, '#E5BC8E', 100,
        ['Calls']),

    # ─── Overhead / Admin (billability is firm-policy; default to non-billable) ───
    ('ADMIN',   'Administration',       False, None, '#6B7280', 110,
        ['Administration', 'General']),
    # Canonical name has no spaces (see industry_categories); the spaced form
    # stays as an ALIAS so historical blocks and titles still resolve to it.
    ('BILL',    'Billing/Admin',        False, None, '#9CA3AF', 120,
        ['Billing / Admin', 'Billing/Admin']),
    ('IT',      'IT / Setup',           False, None, '#B5BAC1', 130,
        ['IT / Setup']),

    # ─── Non-billable ───
    ('IDLE',    'Idle',                 False, None, '#D1D5DB', 200,
        ['Idle']),
    ('PERSONAL', 'Personal / Non-Billable', False, None, '#E5E7EB', 210,
        ['Personal/Non-Billable']),
]


class Command(BaseCommand):
    help = 'Seed TaskTypes and a default Standard set for TL Wall (org 21).'

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=21,
                            help='Org ID (default: 21 / TL Wall)')
        parser.add_argument('--commit', action='store_true',
                            help='Actually save. Without this, runs in dry-run mode.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Explicit dry-run (default behavior).')

    def handle(self, *args, **options):
        commit = options['commit'] and not options['dry_run']
        org_id = options['org']

        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'Org {org_id} not found.'))
            return

        self.stdout.write(self.style.NOTICE(
            f'Seeding TaskTypes for org {org_id} ({org.name})'
        ))
        self.stdout.write(self.style.NOTICE(
            f'Mode: {"COMMIT" if commit else "DRY-RUN"}\n'
        ))

        created_count = 0
        existing_count = 0
        created_task_types = []

        with transaction.atomic():
            for code, name, billable, rate, color, sort_order, _matches in TASK_TYPES:
                existing = TaskType.objects.filter(org=org, code=code).first()
                if existing:
                    existing_count += 1
                    created_task_types.append(existing)
                    self.stdout.write(f'  · {code:<10} {name:<35} [exists]')
                    continue

                if commit:
                    tt = TaskType.objects.create(
                        org=org,
                        name=name,
                        code=code,
                        is_billable=billable,
                        default_rate=rate,
                        color=color,
                        sort_order=sort_order,
                        is_active=True,
                    )
                    created_task_types.append(tt)
                created_count += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ {code:<10} {name:<35} billable={billable}'
                ))

            # Create the Standard set if it doesn't exist
            if commit:
                ts, created = TaskTypeSet.objects.get_or_create(
                    org=org,
                    name='Standard',
                    defaults={
                        'description': 'Default firm-wide TaskType list for TL Wall (seeded from actual usage).',
                        'is_default': True,
                        'source': 'seed',
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(
                        '\n  ✓ Created TaskTypeSet "Standard" (is_default=True)'
                    ))
                else:
                    self.stdout.write(f'\n  · TaskTypeSet "Standard" already exists')

                # Add all task types as members (idempotent)
                for idx, tt in enumerate(created_task_types):
                    TaskTypeSetMember.objects.update_or_create(
                        set=ts, task_type=tt,
                        defaults={'sort_order': idx * 10},
                    )
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ Added {len(created_task_types)} members to Standard set'
                ))

            if not commit:
                # Rollback the atomic block
                transaction.set_rollback(True)

        self.stdout.write(self.style.NOTICE('─' * 60))
        self.stdout.write(f'  Would create: {created_count} TaskTypes')
        self.stdout.write(f'  Already exist: {existing_count}')

        if commit:
            self.stdout.write(self.style.SUCCESS('\nSeed complete.'))
        else:
            self.stdout.write(self.style.WARNING(
                '\nDRY-RUN — no changes saved. Re-run with --commit to apply.'
            ))