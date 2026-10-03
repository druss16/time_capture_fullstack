"""
Remove the "Internal - Tax" client from specific non-CPA firms you name.

Every org used to be created with it, including marketing agencies and law
firms, where a tax bucket means nothing. New orgs only get it when they are
CPA firms.

ONLY the firms you list are touched — never "every non-CPA firm". The first
version swept by industry_type and its dry run listed TL Wall Accounting,
an accounting firm whose vertical happens to be stored as "general".
industry_type is not reliable enough to delete by.

    python manage.py remove_internal_tax_non_cpa --org-id 44            # dry run
    python manage.py remove_internal_tax_non_cpa --org-id 44 --apply

Refused outright: an org whose vertical is cpa or general (general is where
mis-set accounting firms live), and any Internal - Tax client with time on it
or still referenced elsewhere.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from tracker.models import Block, Client, Organization

PROTECTED_VERTICALS = {'cpa', 'general', ''}


class Command(BaseCommand):
    help = 'Delete an unused "Internal - Tax" client from named non-CPA firms'

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, action='append', required=True,
                            help='Firm to clean up; repeat for several')
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        for org_id in opts['org_id']:
            org = Organization.all_objects.filter(id=org_id).first()
            if not org:
                raise CommandError(f'No organization #{org_id}.')
            label = f'{org.name} (#{org.id}, vertical={org.industry_type or "unset"})'
            if (org.industry_type or '') in PROTECTED_VERTICALS:
                self.stdout.write(self.style.ERROR(
                    f'  REFUSED  {label}: only marketing / legal / other named verticals '
                    f'are cleaned up. Fix its vertical first if it is wrong.'))
                continue
            clients = list(Client.objects.filter(org=org, code='INTERNAL_TAX'))
            if not clients:
                self.stdout.write(f'  nothing  {label}: no Internal - Tax client')
                continue
            for c in clients:
                if Block.objects.filter(client=c).exists():
                    self.stdout.write(self.style.WARNING(f'  KEEP  {label}: it has time on it'))
                    continue
                if not opts['apply']:
                    self.stdout.write(f'  would delete  Internal - Tax from {label}')
                    continue
                try:
                    with transaction.atomic():
                        c.delete()
                    self.stdout.write(self.style.SUCCESS(f'  deleted  Internal - Tax from {label}'))
                except ProtectedError:
                    self.stdout.write(self.style.WARNING(f'  KEEP  {label}: still referenced'))
        if not opts['apply']:
            self.stdout.write('Dry run. Re-run with --apply to delete.')
