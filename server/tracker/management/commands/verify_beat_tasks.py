"""Fail if anything scheduled cannot actually run.

Runs in CI, where it would have caught the four months of discarded mail
syncs on the day the task module was added.
"""
from django.core.management.base import BaseCommand

from tracker.celery_health import unregistered_scheduled_tasks


class Command(BaseCommand):
    help = "Check that every scheduled Celery task is registered on the worker."

    def handle(self, *args, **options):
        from celery_app import app

        missing = unregistered_scheduled_tasks(app)

        if not missing:
            self.stdout.write(self.style.SUCCESS(
                "Every scheduled task is registered."
            ))
            return

        self.stderr.write(self.style.ERROR(
            f"{len(missing)} scheduled task(s) are not registered on the worker. "
            f"Beat will send them and the worker will discard each one:\n"
        ))
        for name, sources in missing.items():
            self.stderr.write(f"  {name}  (scheduled in: {', '.join(sources)})")
        self.stderr.write(
            "\nA task defined outside tracker/tasks.py is not autodiscovered. "
            "Re-export it there, as tasks.py already does for the calendar and "
            "mail task modules."
        )
        raise SystemExit(1)
