"""
Remove the "Internal - Tax" client from firms that are not CPA firms.

Every org used to be created with it, including marketing agencies and law
firms, where a tax bucket means nothing. New orgs only get it when they are
CPA firms; this cleans up the ones made before that.

    python manage.py remove_internal_tax_non_cpa           # show what would go
    python manage.py remove_internal_tax_non_cpa --apply   # delete it

Never touches a client that has time on it, rules pointing at it, or is
referenced anywhere else — those are listed and left for a person to decide.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import ProtectedError

from tracker.models import Block, Client


class Command(BaseCommand):
    help = 'Delete unused "Internal - Tax" clients from non-CPA firms'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        qs = (Client.objects.filter(code='INTERNAL_TAX')
              .exclude(org__industry_type='cpa').select_related('org'))
        if not qs.exists():
            self.stdout.write('Nothing to do: no non-CPA firm has an "Internal - Tax" client.')
            return
        removed = kept = 0
        for c in qs:
            label = f'{c.org.name} (#{c.org_id}, {c.org.industry_type})'
            if Block.objects.filter(client=c).exists():
                kept += 1
                self.stdout.write(self.style.WARNING(f'  KEEP  {label}: it has time on it'))
                continue
            if not opts['apply']:
                self.stdout.write(f'  would delete  {label}')
                continue
            try:
                with transaction.atomic():
                    c.delete()
                removed += 1
                self.stdout.write(self.style.SUCCESS(f'  deleted  {label}'))
            except ProtectedError:
                kept += 1
                self.stdout.write(self.style.WARNING(f'  KEEP  {label}: still referenced'))
        if not opts['apply']:
            self.stdout.write('Dry run. Re-run with --apply to delete.')
        else:
            self.stdout.write(f'{removed} deleted, {kept} kept.')
