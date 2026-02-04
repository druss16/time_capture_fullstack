"""
Django management command to generate demo data for TimeTracker.

INSTALLATION:
    1. Create directory: tracker/management/commands/
    2. Create empty __init__.py files in management/ and commands/
    3. Place this file as: tracker/management/commands/create_demo_data.py

USAGE:
    python manage.py create_demo_data        # Creates demo data
    python manage.py create_demo_data --cleanup   # Removes demo data

DEMO ACCOUNT:
    Username: demo
    Password: demo1234
    Organization: Anderson & Associates CPAs
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from datetime import datetime, timedelta, time as dt_time
from decimal import Decimal
import random

User = get_user_model()


class Command(BaseCommand):
    help = 'Creates demo data for TimeTracker (CPA firm with clients, team, and time blocks)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Remove demo data instead of creating it',
        )

    def handle(self, *args, **options):
        if options['cleanup']:
            self.cleanup()
        else:
            self.create_demo_data()

    def cleanup(self):
        """Remove all demo data."""
        from tracker.models import (
            Organization, OrganizationMembership, Block, Timesheet,
            ClientAssignment, ClientGroup, BillingRate, EmployeeCostRate,
            Project, Client, TaskType
        )
        
        self.stdout.write(self.style.WARNING('🗑️  Cleaning up demo data...'))
        
        try:
            org = Organization.objects.get(slug='anderson-associates')
            
            # Delete in order of dependencies
            Block.objects.filter(org=org).delete()
            self.stdout.write('   Deleted blocks')
            
            Timesheet.objects.filter(org=org).delete()
            self.stdout.write('   Deleted timesheets')
            
            ClientAssignment.objects.filter(organization=org).delete()
            self.stdout.write('   Deleted client assignments')
            
            ClientGroup.objects.filter(org=org).delete()
            self.stdout.write('   Deleted client groups')
            
            BillingRate.objects.filter(org=org).delete()
            self.stdout.write('   Deleted billing rates')
            
            EmployeeCostRate.objects.filter(organization=org).delete()
            self.stdout.write('   Deleted cost rates')
            
            Project.objects.filter(org=org).delete()
            self.stdout.write('   Deleted projects')
            
            Client.objects.filter(org=org).delete()
            self.stdout.write('   Deleted clients')
            
            TaskType.objects.filter(org=org).delete()
            self.stdout.write('   Deleted task types')
            
            # Delete demo users
            demo_usernames = ['demo', 'mike.chen', 'lisa.rodriguez', 'james.wilson']
            User.objects.filter(username__in=demo_usernames).delete()
            self.stdout.write('   Deleted demo users')
            
            OrganizationMembership.objects.filter(organization=org).delete()
            org.delete()
            self.stdout.write('   Deleted organization')
            
            self.stdout.write(self.style.SUCCESS('\n✅ Demo data removed successfully'))
            
        except Organization.DoesNotExist:
            self.stdout.write(self.style.WARNING('⚠️  Demo organization not found - nothing to clean up'))

    def create_demo_data(self):
        """Create complete demo dataset."""
        from tracker.models import (
            Organization, OrganizationMembership, Client, Project, TaskType,
            Block, ClientAssignment, ClientGroup, BillingRate, EmployeeCostRate,
            Timesheet
        )
        
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 60))
        self.stdout.write(self.style.MIGRATE_HEADING('  TimeTracker Demo Data Generator'))
        self.stdout.write(self.style.MIGRATE_HEADING('=' * 60))
        
        with transaction.atomic():
            # 1. Organization
            self.stdout.write('\n📁 Creating organization...')
            org, created = Organization.objects.update_or_create(
                slug='anderson-associates',
                defaults={
                    'name': 'Anderson & Associates CPAs',
                    'industry_type': 'cpa',
                    'plan': 'professional',
                    'billing_rate_default': Decimal('175.00'),
                    'cost_rate_default': Decimal('65.00'),
                    'timezone': 'America/New_York',
                    'trial_ends_at': timezone.now() + timedelta(days=30),
                    'seat_count': 10,
                    'onboarding_completed': True,
                }
            )
            self.stdout.write(f'   {"Created" if created else "Updated"}: {org.name}')
            
            # 2. Users
            self.stdout.write('\n👥 Creating team members...')
            users = self._create_users(org)
            
            # 3. Task Types
            self.stdout.write('\n📊 Creating task types...')
            self._create_task_types(org)
            
            # 4. Clients
            self.stdout.write('\n🏢 Creating clients...')
            clients = self._create_clients(org)
            
            # 5. Client Groups
            self.stdout.write('\n📂 Creating client groups...')
            self._create_client_groups(org, clients)
            
            # 6. Client Assignments
            self.stdout.write('\n🔗 Creating client assignments...')
            self._create_client_assignments(org, users, clients)
            
            # 7. Rates
            self.stdout.write('\n💰 Creating billing rates...')
            self._create_rates(org, users)
            
            # 8. Time Blocks
            self.stdout.write('\n⏱️  Creating time blocks...')
            self._create_time_blocks(org, users, clients)
            
            # 9. Timesheets
            self.stdout.write('\n📋 Creating timesheets...')
            self._create_timesheets(org, users)
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('  ✅ Demo data created successfully!'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        self.stdout.write('  Login credentials:')
        self.stdout.write(self.style.WARNING('    Username: demo'))
        self.stdout.write(self.style.WARNING('    Password: demo1234'))
        self.stdout.write(f'    Organization: {org.name}')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _create_users(self, org):
        from tracker.models import OrganizationMembership
        
        DEMO_USERS = [
            {
                'username': 'demo',
                'email': 'demo@anderson-cpa.com',
                'first_name': 'Sarah',
                'last_name': 'Anderson',
                'password': 'demo1234',
                'role': 'owner',
                'billing_rate': Decimal('250.00'),
                'cost_rate': Decimal('95.00'),
            },
            {
                'username': 'mike.chen',
                'email': 'mike@anderson-cpa.com',
                'first_name': 'Mike',
                'last_name': 'Chen',
                'password': 'demo1234',
                'role': 'manager',
                'billing_rate': Decimal('195.00'),
                'cost_rate': Decimal('75.00'),
            },
            {
                'username': 'lisa.rodriguez',
                'email': 'lisa@anderson-cpa.com',
                'first_name': 'Lisa',
                'last_name': 'Rodriguez',
                'password': 'demo1234',
                'role': 'member',
                'billing_rate': Decimal('150.00'),
                'cost_rate': Decimal('55.00'),
            },
            {
                'username': 'james.wilson',
                'email': 'james@anderson-cpa.com',
                'first_name': 'James',
                'last_name': 'Wilson',
                'password': 'demo1234',
                'role': 'member',
                'billing_rate': Decimal('135.00'),
                'cost_rate': Decimal('50.00'),
            },
        ]
        
        users = {}
        for user_data in DEMO_USERS:
            user, created = User.objects.update_or_create(
                username=user_data['username'],
                defaults={
                    'email': user_data['email'],
                    'first_name': user_data['first_name'],
                    'last_name': user_data['last_name'],
                    'is_active': True,
                }
            )
            
            # Always reset password for demo account
            if created or user_data['username'] == 'demo':
                user.set_password(user_data['password'])
                user.save()
            
            # Create organization membership
            OrganizationMembership.objects.update_or_create(
                user=user,
                organization=org,
                defaults={'role': user_data['role']}
            )
            
            users[user_data['username']] = {'user': user, 'data': user_data}
            
            role_emoji = {'owner': '👑', 'manager': '📋', 'member': '👤'}.get(user_data['role'], '👤')
            self.stdout.write(f"   {role_emoji} {user.get_full_name()} ({user_data['role']})")
        
        return users

    def _create_task_types(self, org):
        from tracker.models import TaskType
        
        CPA_TASK_TYPES = [
            {'name': 'Tax Preparation', 'code': 'TAX', 'color': '#10B981', 'is_billable': True},
            {'name': 'Tax Planning', 'code': 'TAXPL', 'color': '#059669', 'is_billable': True},
            {'name': 'Tax Research', 'code': 'TAXRS', 'color': '#047857', 'is_billable': True},
            {'name': 'Audit & Assurance', 'code': 'AUDIT', 'color': '#6366F1', 'is_billable': True},
            {'name': 'Bookkeeping', 'code': 'BOOK', 'color': '#8B5CF6', 'is_billable': True},
            {'name': 'Payroll Services', 'code': 'PAY', 'color': '#A855F7', 'is_billable': True},
            {'name': 'Advisory/Consulting', 'code': 'ADV', 'color': '#EC4899', 'is_billable': True},
            {'name': 'Email/Communication', 'code': 'COMM', 'color': '#F59E0B', 'is_billable': True},
            {'name': 'Meetings', 'code': 'MTG', 'color': '#EF4444', 'is_billable': True},
            {'name': 'Document Review', 'code': 'DOC', 'color': '#06B6D4', 'is_billable': True},
            {'name': 'Research', 'code': 'RES', 'color': '#3B82F6', 'is_billable': True},
            {'name': 'Admin/Internal', 'code': 'ADMIN', 'color': '#6B7280', 'is_billable': False},
            {'name': 'Training', 'code': 'TRAIN', 'color': '#F97316', 'is_billable': False},
        ]
        
        # Clear existing task types for this org
        TaskType.objects.filter(org=org).delete()
        
        for idx, tt in enumerate(CPA_TASK_TYPES):
            TaskType.objects.create(
                org=org,
                name=tt['name'],
                code=tt['code'],
                color=tt['color'],
                is_billable=tt['is_billable'],
                sort_order=idx,
            )
            emoji = "💵" if tt['is_billable'] else "📝"
            self.stdout.write(f"   {emoji} {tt['name']}")

    def _create_clients(self, org):
        from tracker.models import Client, Project
        
        DEMO_CLIENTS = [
            # High-value clients
            {'name': 'Riverside Medical Group', 'code': 'RMG', 'visibility': 'assigned', 
             'projects': ['2024 Tax Return', 'Monthly Bookkeeping', 'Payroll Services'], 'group': 'Healthcare Clients'},
            {'name': 'Summit Construction LLC', 'code': 'SUMMIT', 'visibility': 'all',
             'projects': ['2024 Corporate Tax', 'Job Costing Review', 'Quarterly Estimates'], 'group': 'Construction Clients'},
            {'name': 'Oakwood Family Trust', 'code': 'OFT', 'visibility': 'confidential',
             'projects': ['Estate Planning', 'Trust Tax Return', 'Gift Tax'], 'group': 'High Net Worth'},
            {'name': 'TechStart Innovations', 'code': 'TECH', 'visibility': 'all',
             'projects': ['R&D Tax Credit', '2024 Corporate Tax', 'Stock Options Advisory'], 'group': 'Tech Clients'},
            {'name': 'Golden Years Senior Care', 'code': 'GYSC', 'visibility': 'assigned',
             'projects': ['2024 Nonprofit Audit', 'Form 990', 'Grant Compliance'], 'group': 'Healthcare Clients'},
            # Medium clients
            {'name': 'Main Street Dental', 'code': 'MSD', 'visibility': 'all',
             'projects': ['2024 Tax Return', 'Retirement Plan Review'], 'group': 'Healthcare Clients'},
            {'name': 'Johnson Family Holdings', 'code': 'JFH', 'visibility': 'confidential',
             'projects': ['2024 Partnership Return', 'K-1 Distribution'], 'group': 'High Net Worth'},
            {'name': 'Precision Manufacturing Inc', 'code': 'PMI', 'visibility': 'all',
             'projects': ['2024 Corporate Tax', 'Cost Accounting'], 'group': 'Manufacturing'},
            {'name': 'Harbor View Restaurant Group', 'code': 'HVRG', 'visibility': 'all',
             'projects': ['2024 Tax Return', 'Tip Reporting Compliance'], 'group': 'Hospitality'},
            {'name': 'Evergreen Landscaping', 'code': 'EVER', 'visibility': 'all',
             'projects': ['2024 Tax Return', 'Quarterly Payroll'], 'group': 'Small Business'},
            # Individual clients
            {'name': 'Dr. Patricia Morrison', 'code': 'MORR', 'visibility': 'all',
             'projects': ['2024 Individual Tax', 'Estimated Payments'], 'group': 'Individual Tax'},
            {'name': 'Robert & Karen Williams', 'code': 'WILL', 'visibility': 'all',
             'projects': ['2024 Individual Tax'], 'group': 'Individual Tax'},
            {'name': 'Thompson Real Estate Ventures', 'code': 'TREV', 'visibility': 'assigned',
             'projects': ['2024 Partnership Return', 'Property Depreciation', '1031 Exchange'], 'group': 'Real Estate'},
        ]
        
        clients = {}
        for c_data in DEMO_CLIENTS:
            client, _ = Client.objects.update_or_create(
                org=org,
                code=c_data['code'],
                defaults={
                    'name': c_data['name'],
                    'visibility': c_data.get('visibility', 'all'),
                    'is_active': True,
                }
            )
            
            # Create projects for this client
            for proj_name in c_data.get('projects', []):
                Project.objects.update_or_create(
                    org=org, client=client, name=proj_name,
                    defaults={'is_active': True}
                )
            
            clients[c_data['code']] = {'client': client, 'data': c_data}
            
            vis_emoji = {'all': '🌐', 'assigned': '🔒', 'confidential': '🔐'}.get(c_data.get('visibility', 'all'), '🌐')
            self.stdout.write(f"   {vis_emoji} {client.name} ({len(c_data.get('projects', []))} projects)")
        
        return clients

    def _create_client_groups(self, org, clients):
        from tracker.models import ClientGroup
        
        # Collect unique groups
        groups = {}
        for code, client_info in clients.items():
            group_name = client_info['data'].get('group')
            if group_name:
                if group_name not in groups:
                    groups[group_name] = []
                groups[group_name].append(client_info['client'])
        
        # Create groups with colors
        colors = ['emerald', 'blue', 'purple', 'amber', 'rose', 'slate', 'cyan', 'pink']
        for idx, (group_name, group_clients) in enumerate(groups.items()):
            group, _ = ClientGroup.objects.update_or_create(
                org=org, name=group_name,
                defaults={'color': colors[idx % len(colors)], 'icon': 'folder'}
            )
            group.clients.set(group_clients)
            self.stdout.write(f"   📁 {group_name} ({len(group_clients)} clients)")

    def _create_client_assignments(self, org, users, clients):
        from tracker.models import ClientAssignment
        
        # Define who works on what
        assignments = {
            'demo': ['RMG', 'OFT', 'TECH', 'JFH', 'TREV'],  # Owner - high-value clients
            'mike.chen': ['SUMMIT', 'PMI', 'GYSC', 'HVRG', 'RMG'],  # Manager
            'lisa.rodriguez': ['MSD', 'EVER', 'MORR', 'WILL', 'TECH'],  # Staff
            'james.wilson': ['HVRG', 'EVER', 'SUMMIT', 'PMI'],  # Staff
        }
        
        for username, client_codes in assignments.items():
            user_info = users.get(username)
            if not user_info:
                continue
            
            user = user_info['user']
            count = 0
            
            for code in client_codes:
                client_info = clients.get(code)
                if not client_info:
                    continue
                
                ClientAssignment.objects.update_or_create(
                    organization=org,
                    client=client_info['client'],
                    user=user,
                    defaults={'assigned_by': users['demo']['user']}
                )
                count += 1
            
            self.stdout.write(f"   👤 {user.get_full_name()}: {count} clients")

    def _create_rates(self, org, users):
        from tracker.models import BillingRate, EmployeeCostRate
        
        today = timezone.now().date()
        
        for username, user_info in users.items():
            user = user_info['user']
            data = user_info['data']
            
            # Billing rate (what we charge clients)
            BillingRate.objects.update_or_create(
                org=org, user=user, client=None, task_type=None,
                effective_date=today - timedelta(days=365),
                defaults={'rate': data['billing_rate']}
            )
            
            # Cost rate (what we pay the employee)
            EmployeeCostRate.objects.update_or_create(
                organization=org, user=user,
                effective_date=today - timedelta(days=365),
                defaults={'cost_rate': data['cost_rate']}
            )
            
            margin = data['billing_rate'] - data['cost_rate']
            margin_pct = (margin / data['billing_rate'] * 100)
            self.stdout.write(f"   💵 {user.get_full_name()}: ${data['billing_rate']}/hr ({margin_pct:.0f}% margin)")

    def _create_time_blocks(self, org, users, clients):
        from tracker.models import Block
        
        # Activity patterns for realistic time tracking
        ACTIVITY_PATTERNS = [
            {'category': 'Tax Preparation', 'activities': [
                ('UltraTax CS - {client}', 'ultratax', None),
                ('Drake Tax - {client} 1040', 'drake', None),
                ('ProSeries - Form 1120S', 'proseries', None),
                ('Schedule C Analysis - {client}', 'excel', None),
                ('K-1 Input - {client}', 'ultratax', None),
                ('Depreciation Schedule - {client}', 'excel', None),
            ], 'duration_range': (15, 90)},
            
            {'category': 'Email/Communication', 'activities': [
                ('Inbox - {client} Documents', 'outlook', 'https://outlook.office.com/mail/inbox'),
                ('Gmail - Client Questions', 'chrome', 'https://mail.google.com'),
                ('Compose: Tax Return Status Update', 'outlook', None),
                ('RE: Missing W-2 for {client}', 'outlook', None),
            ], 'duration_range': (5, 25)},
            
            {'category': 'Meetings', 'activities': [
                ('Zoom - {client} Tax Review', 'zoom', 'https://zoom.us/j/123456789'),
                ('Teams - Staff Meeting', 'teams', 'https://teams.microsoft.com/meeting'),
                ('Client Call - {client}', 'zoom', None),
                ('Partner Review - {client}', 'teams', None),
            ], 'duration_range': (15, 60)},
            
            {'category': 'Document Review', 'activities': [
                ('{client} - Bank Statements.pdf', 'acrobat', None),
                ('Review - {client} Prior Year Return', 'acrobat', None),
                ('W-2 Verification - {client}', 'acrobat', None),
                ('{client} - 1099 Summary', 'excel', None),
            ], 'duration_range': (10, 45)},
            
            {'category': 'Research', 'activities': [
                ('IRS.gov - Section 199A Guidance', 'chrome', 'https://www.irs.gov'),
                ('CCH AnswerConnect - QBI Deduction', 'chrome', 'https://answerconnect.cch.com'),
                ('Thomson Reuters Checkpoint', 'chrome', 'https://checkpoint.riag.com'),
                ('Tax Notes - SALT Update', 'chrome', 'https://www.taxnotes.com'),
            ], 'duration_range': (10, 40)},
            
            {'category': 'Bookkeeping', 'activities': [
                ('QuickBooks Online - {client}', 'chrome', 'https://qbo.intuit.com'),
                ('Bank Reconciliation - {client}', 'qbo', None),
                ('A/R Review - {client}', 'qbo', None),
                ('Journal Entries - {client}', 'excel', None),
            ], 'duration_range': (20, 60)},
            
            {'category': 'Admin/Internal', 'activities': [
                ('TimeTracker - Review Entries', 'chrome', 'https://timetracker.mavops.ai'),
                ('Firm Admin - Staff Schedule', 'excel', None),
                ('Practice Management', 'chrome', None),
            ], 'duration_range': (5, 20)},
        ]
        
        demo_user = users['demo']['user']
        client_list = [c['client'] for c in clients.values()]
        
        today = timezone.now().date()
        total_blocks = 0
        
        # Generate 7 days of data for demo user
        for days_ago in range(7):
            target_date = today - timedelta(days=days_ago)
            
            # Skip weekends
            if target_date.weekday() >= 5:
                continue
            
            blocks_count = self._generate_day_blocks(
                org, demo_user, client_list, target_date, ACTIVITY_PATTERNS
            )
            total_blocks += blocks_count
            
            day_name = "Today" if days_ago == 0 else target_date.strftime("%A")
            self.stdout.write(f"   📅 {day_name} ({target_date}): {blocks_count} blocks")
        
        # Generate data for other team members (less data)
        for username in ['mike.chen', 'lisa.rodriguez', 'james.wilson']:
            user_info = users.get(username)
            if not user_info:
                continue
            for days_ago in range(3):
                target_date = today - timedelta(days=days_ago)
                if target_date.weekday() >= 5:
                    continue
                self._generate_day_blocks(
                    org, user_info['user'], client_list, target_date, ACTIVITY_PATTERNS, density=0.6
                )
        
        self.stdout.write(f"\n   Total blocks for demo user: {total_blocks}")

    def _generate_day_blocks(self, org, user, clients, target_date, patterns, density=1.0):
        from tracker.models import Block
        
        tz = timezone.get_current_timezone()
        day_start = timezone.make_aware(datetime.combine(target_date, dt_time(0, 0)), tz)
        day_end = day_start + timedelta(days=1)
        
        # Clear existing blocks for this user/day
        Block.objects.filter(user=user, org=org, start__gte=day_start, start__lt=day_end).delete()
        
        # Work hours: 8:30 AM to 5:30 PM
        current_time = timezone.make_aware(datetime.combine(target_date, dt_time(8, 30)), tz)
        end_time = timezone.make_aware(datetime.combine(target_date, dt_time(17, 30)), tz)
        
        blocks_created = 0
        
        while current_time < end_time:
            # Random chance to skip (creates gaps/breaks)
            if random.random() > density:
                current_time += timedelta(minutes=random.randint(15, 45))
                continue
            
            # Pick random activity
            pattern = random.choice(patterns)
            activity = random.choice(pattern['activities'])
            client = random.choice(clients)
            
            # Duration
            min_dur, max_dur = pattern['duration_range']
            duration = random.randint(min_dur, max_dur)
            
            # Format window title with client name
            window_title = activity[0].format(client=client.name)
            app_name = activity[1]
            url = activity[2]
            
            hours = round(duration / 60, 2)
            block_end = current_time + timedelta(minutes=duration)
            
            # Create the block
            Block.objects.create(
                org=org,
                user=user,
                device_id='demo-device',
                hostname='demo-workstation',
                start=current_time,
                end=block_end,
                day=target_date,
                minutes=duration,
                title=window_title,
                window_title=window_title,
                app_name=app_name,
                url=url or '',
                client=client,
                category_hours={pattern['category']: hours},
                is_categorized=True,
                categorized_at=timezone.now(),
                categorized_by='ai',
                is_billable=pattern['category'] not in ['Admin/Internal', 'Training'],
                ai_category=pattern['category'],
                ai_confidence=random.uniform(0.75, 0.95),
            )
            
            blocks_created += 1
            
            # Move time forward (with occasional gaps)
            gap = random.randint(0, 15) if random.random() > 0.7 else 0
            current_time = block_end + timedelta(minutes=gap)
        
        return blocks_created

    def _create_timesheets(self, org, users):
        from tracker.models import Timesheet
        
        today = timezone.now().date()
        # Get Monday of current week
        monday = today - timedelta(days=today.weekday())
        
        for username, user_info in users.items():
            user = user_info['user']
            
            timesheet, _ = Timesheet.objects.update_or_create(
                org=org, user=user, week_start=monday,
                defaults={'status': 'draft'}
            )
            
            # Recalculate totals from blocks
            timesheet.recalculate_totals()
            
            emoji = {'draft': '📝', 'submitted': '📤', 'approved': '✅'}.get(timesheet.status, '📝')
            self.stdout.write(f"   {emoji} {user.get_full_name()}: {timesheet.total_hours}h ({timesheet.status})")