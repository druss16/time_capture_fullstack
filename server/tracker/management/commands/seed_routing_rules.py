"""
Seed default OrgRoutingRule records for orgs.

Usage:
    # Seed defaults for all orgs
    docker compose exec api python manage.py seed_routing_rules

    # Seed defaults for a specific org
    docker compose exec api python manage.py seed_routing_rules --org-id 21

    # Dry run (show what would be created, no writes)
    docker compose exec api python manage.py seed_routing_rules --org-id 21 --dry-run

    # Add TL Wall-specific customizations (currently none needed)
    docker compose exec api python manage.py seed_routing_rules --org-id 21 --tl-wall

Idempotent: running it multiple times won't create duplicates.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import Organization, Client, OrgRoutingRule


# Inline default rules — no JSON fixture needed
DEFAULT_RULES = [
    {
        'match_type': 'exe_family',
        'match_value': 'taxwise',
        'action': 'route_to_client',
        'target_client_name': 'Internal - Tax',
        'priority': 300,
        'description': 'TaxWise is always internal tax work',
    },
    {
        'match_type': 'exe_family',
        'match_value': 'ultratax',
        'action': 'route_to_client',
        'target_client_name': 'Internal - Tax',
        'priority': 300,
        'description': 'UltraTax is always internal tax work',
    },
    {
        'match_type': 'exe_family',
        'match_value': 'lacerte',
        'action': 'route_to_client',
        'target_client_name': 'Internal - Tax',
        'priority': 300,
        'description': 'Lacerte is always internal tax work',
    },
    {
        'match_type': 'exe_family',
        'match_value': 'proseries',
        'action': 'route_to_client',
        'target_client_name': 'Internal - Tax',
        'priority': 300,
        'description': 'ProSeries is always internal tax work',
    },
    {
        'match_type': 'exe_family',
        'match_value': 'drake',
        'action': 'route_to_client',
        'target_client_name': 'Internal - Tax',
        'priority': 300,
        'description': 'Drake Tax is always internal tax work',
    },
]


class Command(BaseCommand):
    help = 'Seed default routing rules for one or all orgs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-id',
            type=int,
            default=None,
            help='Seed rules for only this org (otherwise all orgs)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without writing',
        )
        parser.add_argument(
            '--tl-wall',
            action='store_true',
            help='Also apply TL Wall-specific rules (currently no-op)',
        )

    def handle(self, *args, **opts):
        org_id = opts['org_id']
        dry = opts['dry_run']
        tl_wall = opts['tl_wall']

        if org_id:
            orgs = Organization.objects.filter(id=org_id)
            if not orgs.exists():
                self.stdout.write(self.style.ERROR(
                    f"No org found with id={org_id}"
                ))
                return
        else:
            orgs = Organization.objects.all()

        total_created = 0
        total_skipped = 0
        total_warned = 0

        for org in orgs:
            self.stdout.write(f'\n─── {org.name} (id={org.id}) ───')
            created, skipped, warned = self._seed_org(org, DEFAULT_RULES, dry)
            total_created += created
            total_skipped += skipped
            total_warned += warned

            if tl_wall and org.id == 21:
                self.stdout.write(self.style.WARNING('  → TL Wall custom rules:'))
                self._seed_tl_wall_specific(org, dry)

        self.stdout.write('')
        verb = 'Would create' if dry else 'Created'
        self.stdout.write(self.style.SUCCESS(
            f'✅ {verb} {total_created} rule(s), skipped {total_skipped} '
            f'(already existed), warned {total_warned} (missing client).'
        ))

    def _seed_org(self, org, rules_data, dry):
        created = 0
        skipped = 0
        warned = 0

        for rule_data in rules_data:
            target_name = rule_data.get('target_client_name')
            target_client = None

            if target_name:
                target_client = Client.objects.filter(
                    org=org, name__iexact=target_name
                ).first()
                if not target_client:
                    self.stdout.write(self.style.WARNING(
                        f"  ⚠ Client '{target_name}' not found — "
                        f"skipping rule '{rule_data['match_value']}'. "
                        f"Create the client first, then re-run this command."
                    ))
                    warned += 1
                    continue

            # Idempotent: skip if already seeded
            exists = OrgRoutingRule.objects.filter(
                org=org,
                match_type=rule_data['match_type'],
                match_value=rule_data['match_value'],
                is_default=True,
            ).exists()
            if exists:
                self.stdout.write(
                    f"  · already seeded: {rule_data['match_value']} → {target_name}"
                )
                skipped += 1
                continue

            if dry:
                self.stdout.write(
                    f"  + WOULD CREATE: {rule_data['match_value']} → {target_name}"
                )
            else:
                with transaction.atomic():
                    OrgRoutingRule.objects.create(
                        org=org,
                        match_type=rule_data['match_type'],
                        match_value=rule_data['match_value'],
                        action=rule_data['action'],
                        target_client=target_client,
                        priority=rule_data.get('priority', 300),
                        description=rule_data.get('description', ''),
                        is_default=True,
                        enabled=True,
                    )
                self.stdout.write(self.style.SUCCESS(
                    f"  + created: {rule_data['match_value']} → {target_name}"
                ))
            created += 1

        return created, skipped, warned

    def _seed_tl_wall_specific(self, org, dry):
        """TL Wall-specific overrides (priority 500 — beats defaults)."""
        # The default rules above already cover TL Wall's request:
        # "TaxWise or UltraTax open → route to Internal - Tax"
        #
        # Add custom TL Wall-only rules here if they ever diverge
        # from the defaults.
        self.stdout.write(
            '    (no TL Wall custom rules needed — defaults cover it)'
        )