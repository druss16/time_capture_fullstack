# tracker/management/commands/seed_test_data.py
"""
Seeds test data for the TimeTracker hybrid categorization feature.

Usage:
    python manage.py seed_test_data --org 1
    python manage.py seed_test_data --org 1 --blocks 50
    python manage.py seed_test_data --org 1 --clear  # Clear and reseed
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import random

User = get_user_model()


# Default CPA task types
DEFAULT_CPA_TASK_TYPES = [
    {'name': 'Tax Preparation', 'code': 'TAX', 'color': '#10B981', 'is_billable': True},
    {'name': 'Tax Planning', 'code': 'TAXPL', 'color': '#059669', 'is_billable': True},
    {'name': 'Audit & Assurance', 'code': 'AUDIT', 'color': '#6366F1', 'is_billable': True},
    {'name': 'Bookkeeping', 'code': 'BOOK', 'color': '#8B5CF6', 'is_billable': True},
    {'name': 'Payroll', 'code': 'PAY', 'color': '#A855F7', 'is_billable': True},
    {'name': 'Advisory/Consulting', 'code': 'ADV', 'color': '#EC4899', 'is_billable': True},
    {'name': 'Client Communication', 'code': 'COMM', 'color': '#F59E0B', 'is_billable': True},
    {'name': 'Research', 'code': 'RES', 'color': '#3B82F6', 'is_billable': True},
    {'name': 'Document Review', 'code': 'DOC', 'color': '#06B6D4', 'is_billable': True},
    {'name': 'Admin/Internal', 'code': 'ADMIN', 'color': '#6B7280', 'is_billable': False},
    {'name': 'Training', 'code': 'TRAIN', 'color': '#F97316', 'is_billable': False},
]

# Sample clients
SAMPLE_CLIENTS = [
    {'name': 'ABC Manufacturing', 'code': 'ABCMFG'},
    {'name': 'Johnson Family Trust', 'code': 'JOHNFT'},
    {'name': 'Smith & Associates LLC', 'code': 'SMITHLLC'},
    {'name': 'Downtown Restaurant Group', 'code': 'DRG'},
    {'name': 'Tech Startup Inc', 'code': 'TECHSTART'},
]

# Sample projects per client
SAMPLE_PROJECTS = [
    '2024 Tax Return',
    'Q4 Bookkeeping',
    'Year-End Audit',
    'Payroll Setup',
    'Tax Planning Meeting',
    'Entity Restructuring',
]

# Sample apps and window titles for generating blocks
SAMPLE_ACTIVITIES = [
    {'app': 'Drake Tax', 'titles': ['1040 - Johnson', 'Schedule C - Smith', '1120S - Tech Startup']},
    {'app': 'QuickBooks Desktop', 'titles': ['ABC Manufacturing - General Ledger', 'Reconciliation', 'Payroll Entry']},
    {'app': 'Microsoft Excel', 'titles': ['Tax Worksheet.xlsx', 'Client Analysis.xlsx', 'Budget Projections.xlsx']},
    {'app': 'Microsoft Outlook', 'titles': ['RE: Tax Documents Needed', 'Meeting: Year-End Review', 'FW: Q4 Financials']},
    {'app': 'Google Chrome', 'titles': ['IRS.gov - Form Instructions', 'State Tax Portal', 'Research - Section 179']},
    {'app': 'Adobe Acrobat', 'titles': ['Engagement Letter.pdf', 'Prior Year Return.pdf', 'W-2 Forms.pdf']},
    {'app': 'Zoom', 'titles': ['Client Meeting - Johnson Family', 'Team Standup', 'Advisory Call']},
    {'app': 'Slack', 'titles': ['#tax-team', '#general', 'DM: Partner Review']},
]


class Command(BaseCommand):
    help = 'Seed test data for TimeTracker hybrid categorization'

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True, help='Organization (Group) ID')
        parser.add_argument('--user', type=int, help='User ID (optional, uses first org user)')
        parser.add_argument('--blocks', type=int, default=30, help='Number of blocks to create')
        parser.add_argument('--days', type=int, default=7, help='Spread blocks over N days')
        parser.add_argument('--clear', action='store_true', help='Clear existing test data first')

    def handle(self, *args, **options):
        from tracker.models import TaskType, Client, Project, Block

        org_id = options['org']
        try:
            org = Group.objects.get(id=org_id)
        except Group.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Organization {org_id} not found'))
            return

        # Get user
        if options['user']:
            user = User.objects.get(id=options['user'])
        else:
            user = User.objects.filter(groups=org).first()
            if not user:
                self.stdout.write(self.style.ERROR('No users found in this org'))
                return

        self.stdout.write(f'Seeding data for org: {org.name}, user: {user.username}')

        # Clear existing if requested
        if options['clear']:
            self.stdout.write('Clearing existing data...')
            Block.objects.filter(org=org, user=user).delete()
            Project.objects.filter(org=org).delete()
            Client.objects.filter(org=org).delete()
            TaskType.objects.filter(org=org).delete()

        # 1. Create TaskTypes
        self.stdout.write('Creating task types...')
        task_types = []
        for idx, tt_data in enumerate(DEFAULT_CPA_TASK_TYPES):
            tt, created = TaskType.objects.get_or_create(
                org=org,
                name=tt_data['name'],
                defaults={
                    'code': tt_data['code'],
                    'color': tt_data['color'],
                    'is_billable': tt_data['is_billable'],
                    'sort_order': idx,
                }
            )
            task_types.append(tt)
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  {status}: {tt.name}')

        # 2. Create Clients
        self.stdout.write('Creating clients...')
        clients = []
        for c_data in SAMPLE_CLIENTS:
            client, created = Client.objects.get_or_create(
                org=org,
                name=c_data['name'],
                defaults={'code': c_data['code']}
            )
            clients.append(client)
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  {status}: {client.name}')

        # 3. Create Projects for each client
        self.stdout.write('Creating projects...')
        all_projects = []
        for client in clients:
            # Each client gets 2-4 projects
            num_projects = random.randint(2, 4)
            for proj_name in random.sample(SAMPLE_PROJECTS, num_projects):
                project, created = Project.objects.get_or_create(
                    org=org,
                    client=client,
                    name=proj_name,
                )
                all_projects.append(project)
                if created:
                    self.stdout.write(f'  Created: {client.name} → {proj_name}')

        # 4. Create Blocks
        self.stdout.write(f'Creating {options["blocks"]} time blocks...')
        now = timezone.now()
        blocks_created = 0

        for _ in range(options['blocks']):
            # Random day in the past N days
            day_offset = random.randint(0, options['days'] - 1)
            block_date = now - timedelta(days=day_offset)
            
            # Random hour (8am - 6pm)
            hour = random.randint(8, 17)
            minute = random.choice([0, 15, 30, 45])
            
            start = block_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            duration = random.choice([15, 30, 45, 60, 90, 120])  # minutes
            end = start + timedelta(minutes=duration)
            
            # Random activity
            activity = random.choice(SAMPLE_ACTIVITIES)
            
            # Decide if this block should be categorized or not
            is_categorized = random.random() > 0.4  # 60% categorized
            
            block_data = {
                'org': org,
                'user': user,
                'device_id': 'test-device',
                'hostname': 'test-mac',
                'start': start,
                'end': end,
                'app_name': activity['app'],
                'window_title': random.choice(activity['titles']),
            }
            
            if is_categorized:
                # Assign categorization
                client = random.choice(clients)
                client_projects = [p for p in all_projects if p.client == client]
                project = random.choice(client_projects) if client_projects else None
                task_type = random.choice(task_types)
                
                block_data.update({
                    'client': client,
                    'project': project,
                    'task_type': task_type,
                    'is_categorized': True,
                    'categorized_by': random.choice(['ai', 'manual']),
                    'categorized_at': now,
                    'ai_confidence': random.uniform(0.7, 0.99),
                })
            else:
                # AI suggested but not confirmed
                block_data.update({
                    'is_categorized': False,
                    'ai_extracted_client': random.choice(SAMPLE_CLIENTS)['name'],
                    'ai_category': random.choice(DEFAULT_CPA_TASK_TYPES)['name'],
                    'ai_confidence': random.uniform(0.5, 0.85),
                })
            
            Block.objects.create(**block_data)
            blocks_created += 1

        self.stdout.write(self.style.SUCCESS(f'\n✅ Done! Created:'))
        self.stdout.write(f'  - {len(task_types)} task types')
        self.stdout.write(f'  - {len(clients)} clients')
        self.stdout.write(f'  - {len(all_projects)} projects')
        self.stdout.write(f'  - {blocks_created} time blocks')
        
        # Stats
        categorized = Block.objects.filter(org=org, user=user, is_categorized=True).count()
        uncategorized = Block.objects.filter(org=org, user=user, is_categorized=False).count()
        self.stdout.write(f'\n📊 Block stats:')
        self.stdout.write(f'  - Categorized: {categorized}')
        self.stdout.write(f'  - Needs review: {uncategorized}')