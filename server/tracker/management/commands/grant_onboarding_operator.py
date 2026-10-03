"""
Give (or take away) access to the Onboarding Console.

    python manage.py grant_onboarding_operator dan@mavops.ai
    python manage.py grant_onboarding_operator new.hire@mavops.ai
    python manage.py grant_onboarding_operator new.hire@mavops.ai --revoke
    python manage.py grant_onboarding_operator --list

The console has its own role on purpose: being staff does not let you in, and
being an operator does not get you into MavOps admin.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from tracker.models_onboarding_console import OPERATOR_GROUP


class Command(BaseCommand):
    help = 'Grant or revoke the Onboarding Operator role'

    def add_arguments(self, parser):
        parser.add_argument('email', nargs='?')
        parser.add_argument('--revoke', action='store_true')
        parser.add_argument('--list', action='store_true')

    def handle(self, *args, **opts):
        group, _ = Group.objects.get_or_create(name=OPERATOR_GROUP)
        if opts['list']:
            for u in group.user_set.order_by('email'):
                self.stdout.write(f'  {u.email}')
            self.stdout.write(f'{group.user_set.count()} operator(s); superusers also have access.')
            return
        if not opts['email']:
            raise CommandError('Give an email, or --list.')
        user = get_user_model().objects.filter(email__iexact=opts['email']).first()
        if not user:
            raise CommandError(f'No user with email {opts["email"]}.')
        if opts['revoke']:
            user.groups.remove(group)
            self.stdout.write(self.style.SUCCESS(f'Revoked: {user.email}'))
        else:
            user.groups.add(group)
            self.stdout.write(self.style.SUCCESS(f'Granted: {user.email} can open /onboard'))
