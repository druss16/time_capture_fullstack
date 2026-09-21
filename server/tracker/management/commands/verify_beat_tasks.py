"""Fail if any Celery task cannot actually run on the worker.

Two checks, because there are two ways to get this wrong and they fail
differently:

  SCHEDULED BUT UNREGISTERED — beat sends the message, the worker discards it.
  tasks_mail.py spent four months here: sync_all_mail went out every five
  minutes and nothing ran. Nothing in the app surfaced it.

  DECLARED BUT UNREGISTERED — nothing sends it yet, so nothing is visibly
  broken. It is a loaded gun: the day someone adds a beat entry or calls
  .delay(), it fails silently, because .delay() from the web process returns
  cleanly (the web process imported the module itself) while the worker
  discards the message. sync_clio_full sat here for a month carrying a
  docstring that claimed it ran on a schedule that did not exist.

Both have the same cause — @shared_task in a module autodiscover_tasks() does
not walk, since it only walks each app's `tasks` module — and the same fix: a
re-export in tracker/tasks.py.

Runs in CI.
"""
from django.core.management.base import BaseCommand

from tracker.celery_health import (
    unregistered_declared_tasks,
    unregistered_scheduled_tasks,
)

FIX = (
    "A task defined outside tracker/tasks.py is not autodiscovered. "
    "Re-export it there, as tasks.py already does for the calendar, mail, "
    "analytics rollup and Clio task modules."
)


class Command(BaseCommand):
    help = "Check that every Celery task is registered on the worker."

    def add_arguments(self, parser):
        parser.add_argument(
            '--scheduled-only', action='store_true',
            help='Only check tasks that are scheduled. Skips the audit of '
                 'tasks that are declared but unrunnable.',
        )

    def handle(self, *args, **options):
        from celery_app import app

        failed = False

        missing = unregistered_scheduled_tasks(app)
        if missing:
            failed = True
            self.stderr.write(self.style.ERROR(
                f"{len(missing)} SCHEDULED task(s) are not registered on the "
                f"worker. Beat will send them and the worker will discard "
                f"each one:\n"
            ))
            for name, sources in missing.items():
                self.stderr.write(f"  {name}  (scheduled in: {', '.join(sources)})")
            self.stderr.write('')
        else:
            self.stdout.write(self.style.SUCCESS(
                "Every scheduled task is registered."
            ))

        if not options['scheduled_only']:
            orphans = unregistered_declared_tasks(app)
            if orphans:
                failed = True
                self.stderr.write(self.style.ERROR(
                    f"{len(orphans)} task(s) are declared but NOT registered "
                    f"on the worker. Nothing sends them today, so nothing "
                    f"looks broken — but .delay() will succeed from the web "
                    f"process and the worker will discard the message:\n"
                ))
                for name, where in orphans.items():
                    self.stderr.write(f"  {name}\n      {where}")
                self.stderr.write('')
            else:
                self.stdout.write(self.style.SUCCESS(
                    "Every declared task is registered."
                ))

        if failed:
            self.stderr.write(FIX)
            raise SystemExit(1)
