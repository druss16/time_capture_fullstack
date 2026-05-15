"""
tracker/management/commands/provision_firm.py

White-glove bulk provisioning command.
Imports team roster + client list + task types from CSV files and sets up everything.

Usage:
    # Import team & devices
    python manage.py provision_firm --org smith-associates --team team.csv

    # Import clients
    python manage.py provision_firm --org smith-associates --clients clients.csv

    # Import task types (service codes)
    python manage.py provision_firm --org smith-associates --task-types task_types.csv

    # Import everything at once
    python manage.py provision_firm --org smith-associates --team team.csv --clients clients.csv --task-types task_types.csv

    # Dry run (preview without making changes)
    python manage.py provision_firm --org smith-associates --team team.csv --dry-run

    # Re-run with updated CSVs (updates existing records)
    python manage.py provision_firm --org smith-associates --team team.csv --update

CSV Formats:
    team.csv:       email, display_name, role, billing_rate, cost_rate, machine_hostname, windows_username
    clients.csv:    client_name, billing_rate, assigned_team (comma-separated emails)
    task_types.csv: name, code, is_billable, default_rate
"""

import csv
import sys
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from tracker.models import (
    Organization, OrganizationMembership, Client, ClientAssignment,
    BillingRate, EmployeeCostRate, OrgDeploymentToken, Invitation,
    OnboardingBatch, DeviceProvisioningMap,
    TaskType, TaskTypeSet, TaskTypeSetMember, 
)

from tracker.models_task_type_sets import CategoryTaskTypeMapping

User = get_user_model()


class Command(BaseCommand):
    help = 'White-glove provisioning: import team roster, clients, and device maps from CSV'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org', required=True,
            help='Organization slug (e.g., smith-associates)'
        )
        parser.add_argument(
            '--team', type=str, default=None,
            help='Path to team CSV (email, display_name, role, billing_rate, cost_rate, machine_hostname, windows_username)'
        )
        parser.add_argument(
            '--clients', type=str, default=None,
            help='Path to clients CSV (client_name, billing_rate, assigned_team)'
        )
        parser.add_argument(
            '--task-types', type=str, default=None,
            help='Path to task types CSV (name, code, is_billable, default_rate)'
        )
        parser.add_argument(
            '--seed-category-mappings', action='store_true',
            help='Auto-seed 1:1 canonical-category -> TaskType mappings (Layer 1 -> Layer 2 bridge)'
        )
        parser.add_argument(
            '--category-mappings', type=str, default=None,
            help='Path to custom category mappings CSV (category, task_type_code)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview what would be created without making changes'
        )
        parser.add_argument(
            '--update', action='store_true',
            help='Update existing records (roles, rates, names) instead of skipping them'
        )
        parser.add_argument(
            '--generate-token', action='store_true',
            help='Also generate (or show existing) OrgDeploymentToken for MSI'
        )
        parser.add_argument(
            '--send-invites', action='store_true',
            help='Send invitation emails to new users (default: skip)'
        )

    def handle(self, *args, **options):
        org_slug = options['org']
        team_csv = options['team']
        clients_csv = options['clients']
        task_types_csv = options['task_types']
        seed_category_mappings = options['seed_category_mappings']
        category_mappings_csv = options['category_mappings']
        dry_run = options['dry_run']
        update = options['update']
        generate_token = options['generate_token']

        if not team_csv and not clients_csv and not task_types_csv \
                and not seed_category_mappings and not category_mappings_csv:
            raise CommandError(
                'Provide at least one of --team, --clients, --task-types, '
                '--seed-category-mappings, or --category-mappings'
            )

        # ─── Resolve org ───
        try:
            org = Organization.objects.get(slug=org_slug)
        except Organization.DoesNotExist:
            raise CommandError(f'Organization with slug "{org_slug}" not found.')

        mode = 'DRY RUN' if dry_run else ('UPDATE' if update else 'LIVE')
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'  PROVISIONING: {org.name}')
        self.stdout.write(f'  MODE: {mode}')
        self.stdout.write(f'{"=" * 60}\n')

        # ─── Create onboarding batch ───
        batch = None
        if not dry_run:
            # Reuse existing batch if updating, create new if first run
            if update:
                batch = OnboardingBatch.objects.filter(
                    organization=org
                ).order_by('-created_at').first()
            
            if not batch:
                batch = OnboardingBatch.objects.create(
                    organization=org,
                    status='draft',
                    notes=f'Provisioned via CLI on {timezone.now().strftime("%Y-%m-%d %H:%M")}'
                )

        # ─── Process team CSV ───
        users_created = {}
        if team_csv:
            users_created = self._import_team(org, team_csv, batch, dry_run, update)

        # ─── Process clients CSV ───
        if clients_csv:
            self._import_clients(org, clients_csv, users_created, dry_run, update)

        # ─── Process task types CSV ───
        if task_types_csv:
            self._import_task_types(org, task_types_csv, dry_run, update)

        # ─── Process category -> TaskType mappings (Layer 1 -> Layer 2 bridge) ───
        if seed_category_mappings or category_mappings_csv:
            self._import_category_mappings(
                org, category_mappings_csv, seed_category_mappings, dry_run, update
            )

        # ─── Generate deployment token ───
        if generate_token and not dry_run:
            self._ensure_deployment_token(org)

        # ─── Update batch status ───
        if batch:
            batch.status = 'imported'
            batch.total_clients = Client.objects.filter(org=org).count()
            batch.refresh_stats()
            self.stdout.write(self.style.SUCCESS(
                f'\nBatch #{batch.id}: '
                f'{batch.total_users} users, '
                f'{batch.total_devices} devices, '
                f'{batch.total_clients} clients'
            ))

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN — no changes were made.'))
        else:
            self.stdout.write(self.style.SUCCESS('\nProvisioning complete.'))

    def _generate_unique_code(self, org, name):
        """Generate a unique client code, appending a number if needed."""
        base = name[:10].upper().replace(' ', '')[:10]
        code = base
        counter = 2
        while Client.objects.filter(org=org, code=code).exists():
            suffix = str(counter)
            code = base[:10 - len(suffix)] + suffix
            counter += 1
        return code

    # ═══════════════════════════════════════════════════════════════
    # TEAM IMPORT
    # ═══════════════════════════════════════════════════════════════
    def _import_team(self, org, csv_path, batch, dry_run, update):
        """
        Import team.csv → creates Users, Memberships, BillingRates, 
        EmployeeCostRates, and DeviceProvisioningMaps.
        
        Returns dict of {email: user} for client assignment linking.
        """
        self.stdout.write(self.style.HTTP_INFO(f'\n── Importing team from: {csv_path}'))
        
        rows = self._read_csv(csv_path)
        required = {'email', 'display_name', 'machine_hostname'}
        self._validate_headers(rows[0].keys(), required, csv_path)

        users_created = {}
        devices_created = 0
        users_updated = 0
        
        role_map = {
            'owner': 'owner',
            'admin': 'admin',
            'manager': 'manager',
            'staff': 'member',
            'member': 'member',
        }

        for i, row in enumerate(rows, 1):
            email = row.get('email', '').strip().lower()
            display_name = row.get('display_name', '').strip()
            role_raw = row.get('role', 'member').strip().lower()
            billing_rate = self._parse_decimal(row.get('billing_rate', ''))
            cost_rate = self._parse_decimal(row.get('cost_rate', ''))
            hostname = row.get('machine_hostname', '').strip()
            win_user = row.get('windows_username', '').strip()

            if not email or not hostname:
                self.stdout.write(self.style.WARNING(
                    f'  Row {i}: Skipping — missing email or hostname'
                ))
                continue

            role = role_map.get(role_raw, 'member')

            # ─── Create or get user ───
            if email not in users_created:
                self.stdout.write(f'  User: {email} ({display_name}) — role: {role}')
                
                if not dry_run:
                    user, created = User.objects.get_or_create(
                        email=email,
                        defaults={
                            'username': email.split('@')[0],
                            'first_name': display_name.split(' ')[0] if display_name else '',
                            'last_name': ' '.join(display_name.split(' ')[1:]) if display_name else '',
                            'is_active': True,
                        }
                    )
                    if created:
                        user.set_unusable_password()
                        user.save()
                        self.stdout.write(self.style.SUCCESS(f'    ✓ User created'))
                    elif update:
                        changed = False
                        first = display_name.split(' ')[0] if display_name else ''
                        last = ' '.join(display_name.split(' ')[1:]) if display_name else ''
                        if first and user.first_name != first:
                            user.first_name = first
                            changed = True
                        if last and user.last_name != last:
                            user.last_name = last
                            changed = True
                        if changed:
                            user.save(update_fields=['first_name', 'last_name'])
                            self.stdout.write(self.style.SUCCESS(f'    ✓ User name updated'))
                        else:
                            self.stdout.write(f'    → User unchanged')
                    else:
                        self.stdout.write(f'    → User already exists (use --update to modify)')

                    # ─── Create or update membership ───
                    membership, mem_created = OrganizationMembership.objects.get_or_create(
                        user=user,
                        organization=org,
                        defaults={'role': role}
                    )
                    if mem_created:
                        self.stdout.write(self.style.SUCCESS(f'    ✓ Membership created ({role})'))
                    elif update and membership.role != role:
                        old_role = membership.role
                        membership.role = role
                        membership.save(update_fields=['role'])
                        users_updated += 1
                        self.stdout.write(self.style.SUCCESS(
                            f'    ✓ Role updated: {old_role} → {role}'
                        ))
                    else:
                        self.stdout.write(f'    → Membership exists ({membership.role})')

                    # ─── Set billing rate ───
                    if billing_rate:
                        rate_obj, rate_created = BillingRate.objects.get_or_create(
                            org=org, user=user, client=None, task_type=None,
                            effective_date=timezone.now().date(),
                            defaults={'rate': billing_rate}
                        )
                        if rate_created:
                            self.stdout.write(f'    ✓ Billing rate: ${billing_rate}/hr')
                        elif update and rate_obj.rate != billing_rate:
                            old_rate = rate_obj.rate
                            rate_obj.rate = billing_rate
                            rate_obj.save(update_fields=['rate'])
                            self.stdout.write(self.style.SUCCESS(
                                f'    ✓ Billing rate updated: ${old_rate} → ${billing_rate}/hr'
                            ))

                    # ─── Set cost rate ───
                    if cost_rate:
                        cost_obj, cost_created = EmployeeCostRate.objects.get_or_create(
                            organization=org, user=user,
                            effective_date=timezone.now().date(),
                            defaults={'cost_rate': cost_rate}
                        )
                        if cost_created:
                            self.stdout.write(f'    ✓ Cost rate: ${cost_rate}/hr')
                        elif update and cost_obj.cost_rate != cost_rate:
                            old_cost = cost_obj.cost_rate
                            cost_obj.cost_rate = cost_rate
                            cost_obj.save(update_fields=['cost_rate'])
                            self.stdout.write(self.style.SUCCESS(
                                f'    ✓ Cost rate updated: ${old_cost} → ${cost_rate}/hr'
                            ))

                    users_created[email] = user
                else:
                    users_created[email] = None  # Placeholder for dry run

            # ─── Create device provisioning map ───
            self.stdout.write(f'    Device: {hostname} ({win_user or "no win_user"})')
            if not dry_run:
                prov, prov_created = DeviceProvisioningMap.objects.get_or_create(
                    organization=org,
                    machine_hostname=hostname.upper(),
                    defaults={
                        'batch': batch,
                        'email': email,
                        'display_name': display_name,
                        'windows_username': win_user.upper() if win_user else '',
                        'role': role,
                        'billing_rate': billing_rate,
                        'cost_rate': cost_rate,
                        'status': 'pending',
                    }
                )
                if prov_created:
                    devices_created += 1
                    self.stdout.write(self.style.SUCCESS(f'      ✓ Provisioning map created'))
                elif update:
                    changed = False
                    if prov.email != email:
                        prov.email = email
                        changed = True
                    if prov.role != role:
                        prov.role = role
                        changed = True
                    if win_user and prov.windows_username != win_user.upper():
                        prov.windows_username = win_user.upper()
                        changed = True
                    if changed:
                        prov.save()
                        self.stdout.write(self.style.SUCCESS(f'      ✓ Provisioning map updated'))
                    else:
                        self.stdout.write(f'      → Already provisioned (unchanged)')
                else:
                    self.stdout.write(f'      → Already provisioned')

        summary = f'\n  Team summary: {len(users_created)} users, {devices_created} device maps'
        if update and users_updated:
            summary += f', {users_updated} roles updated'
        self.stdout.write(summary)
        return users_created

    # ═══════════════════════════════════════════════════════════════
    # CLIENT IMPORT
    # ═══════════════════════════════════════════════════════════════
    def _import_clients(self, org, csv_path, users_created, dry_run, update):
        """
        Import clients.csv → creates Clients and ClientAssignments.
        """
        self.stdout.write(self.style.HTTP_INFO(f'\n── Importing clients from: {csv_path}'))

        rows = self._read_csv(csv_path)
        required = {'client_name'}
        self._validate_headers(rows[0].keys(), required, csv_path)

        clients_created = 0
        clients_updated = 0
        assignments_created = 0

        for i, row in enumerate(rows, 1):
            name = row.get('client_name', '').strip()
            billing_rate = self._parse_decimal(row.get('billing_rate', ''))
            assigned_raw = row.get('assigned_team', '').strip()

            if not name:
                self.stdout.write(self.style.WARNING(f'  Row {i}: Skipping — missing client_name'))
                continue

            code = self._generate_unique_code(org, name)
            self.stdout.write(f'  Client: {name} (code: {code})')

            if not dry_run:
                client, created = Client.objects.get_or_create(
                    org=org,
                    name=name,
                    defaults={
                        'code': code,
                        'is_active': True,
                    }
                )
                if created:
                    clients_created += 1
                    self.stdout.write(self.style.SUCCESS(f'    ✓ Client created'))
                elif update:
                    changed = False
                    if client.code != code:
                        client.code = code
                        changed = True
                    if not client.is_active:
                        client.is_active = True
                        changed = True
                    if changed:
                        client.save()
                        clients_updated += 1
                        self.stdout.write(self.style.SUCCESS(f'    ✓ Client updated'))
                    else:
                        self.stdout.write(f'    → Client exists (unchanged)')
                else:
                    self.stdout.write(f'    → Client already exists')

                # ─── Parse and create assignments ───
                if assigned_raw:
                    emails = [e.strip().lower() for e in assigned_raw.split(';') if e.strip()]
                    for email in emails:
                        user = users_created.get(email)
                        if not user:
                            user = User.objects.filter(email=email).first()
                        
                        if user:
                            assignment, assign_created = ClientAssignment.objects.get_or_create(
                                organization=org,
                                client=client,
                                user=user,
                            )
                            if assign_created:
                                assignments_created += 1
                                self.stdout.write(f'    ✓ Assigned: {email}')
                            else:
                                self.stdout.write(f'    → Already assigned: {email}')
                        else:
                            self.stdout.write(self.style.WARNING(
                                f'    ⚠ User not found: {email} — skipping assignment'
                            ))
            else:
                # Dry run — just report
                if assigned_raw:
                    emails = [e.strip() for e in assigned_raw.split(';')]
                    self.stdout.write(f'    Assignments: {", ".join(emails)}')

        summary = f'\n  Client summary: {clients_created} clients, {assignments_created} assignments'
        if update and clients_updated:
            summary += f', {clients_updated} updated'
        self.stdout.write(summary)


    # ═══════════════════════════════════════════════════════════════
    # TASK TYPE IMPORT
    # ═══════════════════════════════════════════════════════════════
    def _import_task_types(self, org, csv_path, dry_run, update):
        """
        Import task_types.csv → creates TaskTypes and adds them all to
        the org's default TaskTypeSet (creating "Standard" if none exists).
        """
        self.stdout.write(self.style.HTTP_INFO(f'\n── Importing task types from: {csv_path}'))

        rows = self._read_csv(csv_path)
        required = {'name'}
        self._validate_headers(rows[0].keys(), required, csv_path)

        types_created = 0
        types_updated = 0
        imported_task_types = []  # collected for set membership

        for i, row in enumerate(rows, 1):
            name = row.get('name', '').strip()
            code = row.get('code', '').strip().upper()
            billable_raw = row.get('is_billable', 'true').strip().lower()
            is_billable = billable_raw not in ('false', 'no', '0', 'n', '')
            default_rate = self._parse_decimal(row.get('default_rate', ''))

            if not name:
                self.stdout.write(self.style.WARNING(f'  Row {i}: Skipping — missing name'))
                continue

            label = f'{name}' + (f' ({code})' if code else '')
            self.stdout.write(f'  Task Type: {label} — {"billable" if is_billable else "non-billable"}')

            if not dry_run:
                tt, created = TaskType.objects.get_or_create(
                    org=org,
                    name=name,
                    defaults={
                        'code': code,  # blank → TaskType.save() auto-generates
                        'is_billable': is_billable,
                        'default_rate': default_rate,
                        'is_active': True,
                    }
                )
                if created:
                    types_created += 1
                    self.stdout.write(self.style.SUCCESS(f'    ✓ Task type created'))
                elif update:
                    changed = False
                    if code and tt.code != code:
                        tt.code = code
                        changed = True
                    if tt.is_billable != is_billable:
                        tt.is_billable = is_billable
                        changed = True
                    if default_rate is not None and tt.default_rate != default_rate:
                        tt.default_rate = default_rate
                        changed = True
                    if not tt.is_active:
                        tt.is_active = True
                        changed = True
                    if changed:
                        tt.save()
                        types_updated += 1
                        self.stdout.write(self.style.SUCCESS(f'    ✓ Task type updated'))
                    else:
                        self.stdout.write(f'    → Task type exists (unchanged)')
                else:
                    self.stdout.write(f'    → Task type already exists')

                imported_task_types.append(tt)

        # ─── Add all imported task types to the org's default set ───
        if not dry_run and imported_task_types:
            default_set = TaskTypeSet.objects.filter(org=org, is_default=True).first()
            if not default_set:
                default_set = TaskTypeSet.objects.create(
                    org=org,
                    name='Standard',
                    description='Default firm-wide task type set.',
                    is_default=True,
                    source='manual',
                )
                self.stdout.write(self.style.SUCCESS(
                    f'    ✓ Created default set "Standard"'
                ))

            members_added = 0
            for idx, tt in enumerate(imported_task_types):
                _, member_created = TaskTypeSetMember.objects.get_or_create(
                    set=default_set,
                    task_type=tt,
                    defaults={'sort_order': idx},
                )
                if member_created:
                    members_added += 1
            self.stdout.write(self.style.SUCCESS(
                f'    ✓ Added {members_added} task type(s) to set "{default_set.name}"'
            ))

        summary = f'\n  Task type summary: {types_created} created'
        if update and types_updated:
            summary += f', {types_updated} updated'
        if dry_run:
            summary += ' (dry run — no changes made)'
        self.stdout.write(summary)

    def _import_category_mappings(self, org, csv_path, seed_default, dry_run, update):
        """
        Populate CategoryTaskTypeMapping — the Layer 1 -> Layer 2 bridge.

        Two modes:
          seed_default=True  → auto-seed 1:1 mappings. For each canonical
              category in the org's industry vocabulary, find the org's
              TaskType with the matching name, create a mapping with
              source='seed'.
          csv_path given     → import a custom mapping CSV (category,
              task_type_code), create mappings with source='manual'.

        --update: 'seed' rows are regenerated freely; 'manual' rows are
        never clobbered (a human deliberately set those).
        """
        from tracker.industry_categories import get_categories_for_industry

        self.stdout.write(self.style.HTTP_INFO(
            f'\n── Importing category → TaskType mappings'
        ))

        mappings_created = 0
        mappings_updated = 0
        mappings_skipped = 0

        # Build the (category_string, task_type) pairs to map.
        pairs = []  # list of (category_str, task_type_obj_or_None, source)

        if csv_path:
            # ─── Mode 2: custom CSV ───
            rows = self._read_csv(csv_path)
            required = {'category', 'task_type_code'}
            self._validate_headers(rows[0].keys(), required, csv_path)

            for i, row in enumerate(rows, 1):
                category = row.get('category', '').strip()
                tt_code = row.get('task_type_code', '').strip().upper()
                if not category or not tt_code:
                    self.stdout.write(self.style.WARNING(
                        f'  Row {i}: Skipping — missing category or task_type_code'
                    ))
                    continue
                tt = TaskType.objects.filter(org=org, code=tt_code).first()
                if not tt:
                    self.stdout.write(self.style.WARNING(
                        f'  Row {i}: Skipping — no TaskType with code "{tt_code}" '
                        f'for this org'
                    ))
                    continue
                pairs.append((category, tt, 'manual'))
        else:
            # ─── Mode 1: auto-seed 1:1 default ───
            canonical = get_categories_for_industry(org.industry_type)
            for category in canonical:
                tt = TaskType.objects.filter(org=org, name__iexact=category).first()
                if not tt:
                    self.stdout.write(self.style.WARNING(
                        f'  No TaskType named "{category}" for this org — '
                        f'skipping (run --task-types first?)'
                    ))
                    continue
                pairs.append((category, tt, 'seed'))

        # Apply the pairs.
        for category, tt, source in pairs:
            self.stdout.write(f'  Mapping: "{category}" → {tt.code}  [{source}]')

            if dry_run:
                continue

            existing = CategoryTaskTypeMapping.objects.filter(
                org=org, category=category
            ).first()

            if existing is None:
                CategoryTaskTypeMapping.objects.create(
                    org=org, category=category, task_type=tt, source=source,
                )
                mappings_created += 1
                self.stdout.write(self.style.SUCCESS(f'    ✓ Mapping created'))
            elif update:
                # Never clobber a human-set mapping.
                if existing.source == 'manual' and source == 'seed':
                    mappings_skipped += 1
                    self.stdout.write(
                        f'    → Skipped — manual mapping exists (not overwriting)'
                    )
                elif existing.task_type_id != tt.id or existing.source != source:
                    existing.task_type = tt
                    existing.source = source
                    existing.save(update_fields=['task_type', 'source', 'updated_at'])
                    mappings_updated += 1
                    self.stdout.write(self.style.SUCCESS(f'    ✓ Mapping updated'))
                else:
                    self.stdout.write(f'    → Mapping exists (unchanged)')
            else:
                mappings_skipped += 1
                self.stdout.write(f'    → Mapping already exists (use --update to modify)')

        summary = (
            f'\n  Category mapping summary: {mappings_created} created'
        )
        if mappings_updated:
            summary += f', {mappings_updated} updated'
        if mappings_skipped:
            summary += f', {mappings_skipped} skipped'
        if dry_run:
            summary += ' (dry run — no changes made)'
        self.stdout.write(summary)

    # ═══════════════════════════════════════════════════════════════
    # DEPLOYMENT TOKEN
    # ═══════════════════════════════════════════════════════════════
    def _ensure_deployment_token(self, org):
        """Generate or show existing deployment token."""
        self.stdout.write(self.style.HTTP_INFO('\n── Deployment Token'))
        
        token = OrgDeploymentToken.objects.filter(
            organization=org,
            is_active=True
        ).first()

        if token:
            self.stdout.write(f'  Existing token: {token.token}')
        else:
            token = OrgDeploymentToken.objects.create(
                organization=org,
                is_active=True,
                notes='Generated during white-glove provisioning'
            )
            self.stdout.write(self.style.SUCCESS(f'  ✓ New token created: {token.token}'))

        self.stdout.write(f'  Bake into MSI: msiexec /i TimeTracker.msi ORG_TOKEN={token.token}')

    # ═══════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════
    def _read_csv(self, path):
        """Read CSV file, return list of dicts."""
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except FileNotFoundError:
            raise CommandError(f'CSV file not found: {path}')
        except Exception as e:
            raise CommandError(f'Error reading CSV: {e}')

        if not rows:
            raise CommandError(f'CSV is empty: {path}')

        # Strip whitespace from headers
        cleaned = []
        for row in rows:
            cleaned.append({k.strip().lower(): v for k, v in row.items()})
        return cleaned

    def _validate_headers(self, headers, required, path):
        """Check that required columns exist."""
        headers_clean = {h.strip().lower() for h in headers}
        missing = required - headers_clean
        if missing:
            raise CommandError(
                f'CSV {path} missing required columns: {", ".join(missing)}\n'
                f'Found columns: {", ".join(headers_clean)}'
            )

    def _parse_decimal(self, val):
        """Safely parse a decimal value, return None if empty/invalid."""
        if not val or not val.strip():
            return None
        try:
            return Decimal(val.strip().replace('$', '').replace(',', ''))
        except (InvalidOperation, ValueError):
            return None