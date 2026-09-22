"""Fail if the migration graph has forked, or is about to.

WHY THIS EXISTS
---------------
Two PRs were open at once. Each added a migration on top of the same parent,
neither could see the other, and both merged. The result:

    CommandError: Conflicting migrations detected; multiple leaf nodes in the
    migration graph: (0168_client_created_at, 0169_drop_org_install_token)

Django then refuses to run ANY migration — not just the new ones. Every deploy
that migrates is blocked until someone lands a merge migration. It happened
three times in two days on this repo.

Nothing caught it. `manage.py check` does not build the migration graph, and
the app runs fine right up until something tries to migrate. So the first
person to find out is whoever is mid-deploy.

This builds the graph and asserts one leaf per app, which takes about a second
and needs no database.

It also WARNS (without failing) on two migrations sharing a numeric prefix.
That is legal when one depends on the other, and it is exactly the near-miss
that precedes the fatal version — worth seeing in the log while it is still
cheap to renumber.
"""
import collections
import re

from django.core.management.base import BaseCommand
from django.db.migrations.loader import MigrationLoader

NUMBER = re.compile(r'^(\d+)_')


class Command(BaseCommand):
    help = 'Check that each app has exactly one migration leaf node.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--app', default=None,
            help='Only check this app label. Default: every app with migrations.',
        )

    def handle(self, *args, **options):
        # connection=None: read the files, never touch a database. CI has none,
        # and a check that needs one is a check that gets skipped.
        loader = MigrationLoader(None, ignore_no_migrations=True)

        leaves_by_app = collections.defaultdict(list)
        for app_label, name in loader.graph.leaf_nodes():
            leaves_by_app[app_label].append(name)

        only = options['app']
        forked = {
            app: sorted(names)
            for app, names in leaves_by_app.items()
            if len(names) > 1 and (only is None or app == only)
        }

        # Near-miss: same number, different migrations, in one app.
        for app_label, names in sorted(self._numbers_by_app(loader, only).items()):
            for number, migrations in sorted(names.items()):
                if len(migrations) > 1:
                    self.stdout.write(self.style.WARNING(
                        f'  note: {app_label} has {len(migrations)} migrations '
                        f'numbered {number}: {", ".join(sorted(migrations))}'
                    ))

        if not forked:
            checked = only or f'{len(leaves_by_app)} app(s)'
            self.stdout.write(self.style.SUCCESS(
                f'Migration graph is linear ({checked}): one leaf each.'
            ))
            return

        self.stderr.write(self.style.ERROR(
            f'{len(forked)} app(s) have a FORKED migration graph. Django will '
            f'refuse to run any migration at all — including unrelated ones a '
            f'deploy needs — until this is merged:\n'
        ))
        for app_label, names in sorted(forked.items()):
            self.stderr.write(f'  {app_label}: {", ".join(names)}')
        self.stderr.write(
            '\nFix: python manage.py makemigrations --merge\n'
            'Avoid: migration numbers are a shared namespace and concurrent '
            'branches cannot see each other. Rebase on main and check the '
            'number is free before opening a PR.'
        )
        raise SystemExit(1)

    @staticmethod
    def _numbers_by_app(loader, only):
        out = collections.defaultdict(lambda: collections.defaultdict(list))
        for app_label, name in loader.disk_migrations:
            if only is not None and app_label != only:
                continue
            m = NUMBER.match(name)
            if m:
                out[app_label][m.group(1)].append(name)
        return out
