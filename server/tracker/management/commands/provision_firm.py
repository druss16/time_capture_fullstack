"""
tracker/management/commands/provision_firm.py

White-glove bulk provisioning command.
Imports team roster + client list from CSV files and sets up everything.

Usage:
    # Import team & devices
    python manage.py provision_firm --org smith-associates --team team.csv
    
    # Import clients
    python manage.py provision_firm --org smith-associates --clients clients.csv
    
    # Import both at once
    python manage.py provision_firm --org smith-associates --team team.csv --clients clients.csv
    
    # Dry run (preview without making changes)
    python manage.py provision_firm --org smith-associates --team team.csv --clients clients.csv --dry-run

CSV Formats:
    team.csv:    email, display_name, role, billing_rate, cost_rate, machine_hostname, windows_username
    clients.csv: client_name, billing_rate, assigned_team (comma-separated emails)
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
)
from tracker.models import (
    OnboardingBatch, DeviceProvisioningMap,
)

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
            '--dry-run', action='store_true',
            help='Preview what would be created without making changes'
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
        dry_run = options['dry_run']
        generate_token = options['generate_token']

        if not team_csv and not clients_csv:
            raise CommandError('Provide at least one of --team or --clients')

        # ─── Resolve org ───
        try:
            org = Organization.objects.get(slug=org_slug)
        except Organization.DoesNotExist:
            raise CommandError(f'Organization with slug "{org_slug}" not found.')

        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'  PROVISIONING: {org.name}')
        self.stdout.write(f'  {"DRY RUN" if dry_run else "LIVE"}')
        self.stdout.write(f'{"=" * 60}\n')

        # ─── Create onboarding batch ───
        batch = None
        if not dry_run:
            batch = OnboardingBatch.objects.create(
                organization=org,
                status='draft',
                notes=f'Provisioned via CLI on {timezone.now().strftime("%Y-%m-%d %H:%M")}'
            )

        # ─── Process team CSV ───
        users_created = {}
        if team_csv:
            users_created = self._import_team(org, team_csv, batch, dry_run)

        # ─── Process clients CSV ───
        if clients_csv:
            self._import_clients(org, clients_csv, users_created, dry_run)

        # ─── Generate deployment token ───
        if generate_token and not dry_run:
            self._ensure_deployment_token(org)

        # ─── Update batch status ───
        if batch:
            batch.status = 'imported'
            batch.total_clients = Client.objects.filter(org=org).count()
            batch.refresh_stats()
            self.stdout.write(self.style.SUCCESS(
                f'\nBatch #{batch.id} created: '
                f'{batch.total_users} users, '
                f'{batch.total_devices} devices, '
                f'{batch.total_clients} clients'
            ))

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN — no changes were made.'))
        else:
            self.stdout.write(self.style.SUCCESS('\nProvisioning complete.'))

    # ═══════════════════════════════════════════════════════════════
    # TEAM IMPORT
    # ═══════════════════════════════════════════════════════════════
    def _import_team(self, org, csv_path, batch, dry_run):
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
                        # Set unusable password — they'll set one via invite link
                        user.set_unusable_password()
                        user.save()
                        self.stdout.write(self.style.SUCCESS(f'    ✓ User created'))
                    else:
                        self.stdout.write(f'    → User already exists')

                    # ─── Create membership ───
                    membership, mem_created = OrganizationMembership.objects.get_or_create(
                        user=user,
                        organization=org,
                        defaults={'role': role}
                    )
                    if mem_created:
                        self.stdout.write(self.style.SUCCESS(f'    ✓ Membership created ({role})'))
                    else:
                        self.stdout.write(f'    → Membership exists ({membership.role})')

                    # ─── Set billing rate ───
                    if billing_rate:
                        BillingRate.objects.get_or_create(
                            org=org, user=user, client=None, task_type=None,
                            effective_date=timezone.now().date(),
                            defaults={'rate': billing_rate}
                        )
                        self.stdout.write(f'    ✓ Billing rate: ${billing_rate}/hr')

                    # ─── Set cost rate ───
                    if cost_rate:
                        EmployeeCostRate.objects.get_or_create(
                            organization=org, user=user,
                            effective_date=timezone.now().date(),
                            defaults={'cost_rate': cost_rate}
                        )
                        self.stdout.write(f'    ✓ Cost rate: ${cost_rate}/hr')

                    users_created[email] = user
                else:
                    users_created[email] = None  # Placeholder for dry run

            # ─── Create device provisioning map ───
            self.stdout.write(f'    Device: {hostname} ({win_user or "no win_user"})')
            if not dry_run:
                prov, prov_created = DeviceProvisioningMap.objects.get_or_create(
                    organization=org,
                    machine_hostname=hostname.upper(),  # Normalize to uppercase
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
                else:
                    self.stdout.write(f'      → Already provisioned')

        self.stdout.write(f'\n  Team summary: {len(users_created)} users, {devices_created} device maps')
        return users_created

    # ═══════════════════════════════════════════════════════════════
    # CLIENT IMPORT
    # ═══════════════════════════════════════════════════════════════
    def _import_clients(self, org, csv_path, users_created, dry_run):
        """
        Import clients.csv → creates Clients and ClientAssignments.
        """
        self.stdout.write(self.style.HTTP_INFO(f'\n── Importing clients from: {csv_path}'))

        rows = self._read_csv(csv_path)
        required = {'client_name'}
        self._validate_headers(rows[0].keys(), required, csv_path)

        clients_created = 0
        assignments_created = 0

        for i, row in enumerate(rows, 1):
            name = row.get('client_name', '').strip()
            billing_rate = self._parse_decimal(row.get('billing_rate', ''))
            assigned_raw = row.get('assigned_team', '').strip()

            if not name:
                self.stdout.write(self.style.WARNING(f'  Row {i}: Skipping — missing client_name'))
                continue

            code = name[:10].upper().replace(' ', '')[:10]
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
                else:
                    self.stdout.write(f'    → Client already exists')

                # ─── Parse and create assignments ───
                if assigned_raw:
                    emails = [e.strip().lower() for e in assigned_raw.split(',') if e.strip()]
                    for email in emails:
                        # Look up user — first check our import, then DB
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
                    emails = [e.strip() for e in assigned_raw.split(',')]
                    self.stdout.write(f'    Assignments: {", ".join(emails)}')

        self.stdout.write(f'\n  Client summary: {clients_created} clients, {assignments_created} assignments')

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