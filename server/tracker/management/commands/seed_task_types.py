# tracker/management/commands/seed_task_types.py

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from tracker.models import TaskType, DEFAULT_CPA_TASK_TYPES


class Command(BaseCommand):
    help = 'Seed default CPA task types for an organization'

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, help='Organization (Group) ID')
        parser.add_argument('--all', action='store_true', help='Seed for all orgs')

    def handle(self, *args, **options):
        if options['all']:
            orgs = Group.objects.all()
        elif options['org']:
            orgs = Group.objects.filter(id=options['org'])
        else:
            self.stdout.write(self.style.ERROR('Specify --org ID or --all'))
            return

        for org in orgs:
            created_count = 0
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
                if created:
                    created_count += 1
            
            self.stdout.write(
                self.style.SUCCESS(f'✅ {org.name}: Created {created_count} task types')
            )