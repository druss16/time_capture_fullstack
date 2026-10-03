"""
Delete organizations that were created by mistake from a permission-role group.

tracker/signals.py turns any auth Group a user joins into an Organization of
the same name. Before role groups were excluded, granting the Onboarding
Operator role created an org called "Onboarding Operator" with the operator as
a member. This removes such orgs — and only when they hold nothing real.

    python manage.py remove_role_group_orgs           # show what would go
    python manage.py remove_role_group_orgs --apply   # delete it

Refuses an org that has any time blocks, timesheets, devices, a subscription,
or clients beyond the "Internal" ones created automatically with every org.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import (
    Block, Client, Organization, OrganizationMembership, Timesheet,
)
from tracker.models_onboarding_console import ROLE_GROUPS


def _blockers(org):
    out = []
    if Block.objects.filter(org=org).exists():
        out.append('has time blocks')
    if Timesheet.objects.filter(org=org).exists():
        out.append('has timesheets')
    if org.stripe_subscription_id or org.stripe_customer_id:
        out.append('is linked to Stripe')
    real_clients = Client.objects.filter(org=org).exclude(name__istartswith='Internal')
    if real_clients.exists():
        out.append(f'has {real_clients.count()} client(s)')
    return out


class Command(BaseCommand):
    help = 'Delete organizations accidentally created from a permission-role group'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        orgs = list(Organization.objects.filter(name__in=ROLE_GROUPS))
        if not orgs:
            self.stdout.write('No role-group organizations found. Nothing to do.')
            return
        for org in orgs:
            members = list(OrganizationMembership.objects.filter(organization=org)
                           .select_related('user'))
            who = ', '.join(m.user.email or m.user.username for m in members) or 'none'
            blockers = _blockers(org)
            self.stdout.write(f'Org #{org.id} "{org.name}" ({org.slug}) — members: {who}')
            if blockers:
                self.stdout.write(self.style.ERROR(
                    f'  NOT deleting: it {", ".join(blockers)}. Look at it by hand.'))
                continue
            if not opts['apply']:
                self.stdout.write(self.style.WARNING('  Would delete (re-run with --apply).'))
                continue
            with transaction.atomic():
                org.delete()
            self.stdout.write(self.style.SUCCESS(
                '  Deleted. Members keep their real firms; only this membership is gone.'))
