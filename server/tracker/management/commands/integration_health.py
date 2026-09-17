"""
Management command: what is the TRUE state of every mail/calendar integration?

Read-only. Exists because the Connections page shows one bit — is_connected —
and that bit lies in both directions:

  * A row is created at OAuth *start* to hold the state token. Abandon the
    Microsoft consent screen and the row persists forever with no tokens,
    looking like an integration that exists. Five TL Wall mailboxes sat in
    exactly this state from 2026-06-16 with nobody aware mail was never on.

  * Sync dispatch filters `sync_failure_count__lt=5` (tasks_mail.py,
    tasks_calendar.py). At 5 consecutive failures the row is skipped
    permanently — while is_connected stays True and the UI keeps saying
    "Connected". Three TL Wall calendars were in this state for 17 days.

Neither case raises anything. This command is how you find them.

Usage:
  python manage.py integration_health
  python manage.py integration_health --org 21
  python manage.py integration_health --problems        # only what needs a human
"""
from django.core.management.base import BaseCommand

from tracker.models import UserIntegration
from tracker.services.integration_health import (
    NEEDS_ACTION,
    OK,
    PRESENTATION,
    assess,
)

# The states this command paints red — not syncing, and a person must act.
LOUD = NEEDS_ACTION


class Command(BaseCommand):
    help = "Report the true state of every mail/calendar integration."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None)
        parser.add_argument('--problems', action='store_true',
                            help='Only rows that need a human')

    def handle(self, *args, **opts):
        qs = UserIntegration.objects.select_related('user', 'org').order_by(
            'org_id', 'provider', 'user__username',
        )
        if opts['org']:
            qs = qs.filter(org_id=opts['org'])

        rows = []
        for i in qs:
            state, detail = assess(i)
            if opts['problems'] and state == OK:
                continue
            rows.append((i, state, detail))

        if not rows:
            self.stdout.write("Nothing to report.")
            return

        self.stdout.write(
            f"\n  {'org':>4s}  {'provider':20s} {'user':12s} {'shows as':10s} {'true state':22s} detail"
        )
        for i, state, detail in rows:
            shows_as = 'Connected' if i.is_connected else 'Not conn.'
            line = (f"  {i.org_id:>4d}  {i.provider:20s} {i.user.username:12s} "
                    f"{shows_as:10s} {PRESENTATION[state][0]:22s} {detail}")
            if state in LOUD:
                self.stdout.write(self.style.ERROR(line))
            elif state == OK:
                self.stdout.write(line)
            else:
                self.stdout.write(self.style.WARNING(line))

        needing = [r for r in rows if r[1] in NEEDS_ACTION]
        self.stdout.write("")
        if needing:
            self.stdout.write(self.style.WARNING(
                f"{len(needing)} integration(s) need a person to reconnect from "
                f"Settings → Connections. Nobody can do this for them — the "
                f"Microsoft consent screen has to be completed by the account holder."
            ))
        self.stdout.write("")
