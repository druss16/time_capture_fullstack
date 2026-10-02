"""
Management command: is the calendar shaping this org's time, and how?

READ-ONLY. Changes nothing — not the flag, not an event, not a block.

Prints:
  * Organization.calendar_classification_enabled — the one switch behind
    Stage 6 (calendar labels captured blocks) AND the off-computer meeting
    proposals (services/calendar_meetings.py). Default off.
  * Every calendar connection: provider, connected, last sync, last error.
  * Recent events per person, by client-match status (matched >= 0.70 /
    matched low / unmatched), and how many would qualify as an off-computer
    client meeting — with the reasons the rest don't.
  * Calendar-born Daily Review entries: pending / confirmed / dismissed.

Usage:
  python manage.py calendar_status --org 21
  python manage.py calendar_status --org 21 --days 14
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.models import Block, CalendarEvent, Organization, UserIntegration


class Command(BaseCommand):
    help = "Read-only: the org's calendar flag, connections, sync and recent event matching."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--days', type=int, default=7)

    def handle(self, *args, **opts):
        from tracker.services.calendar_meetings import (
            CALENDAR_DEVICE_ID, CALENDAR_SOURCE, firm_identity, qualifies,
        )

        org = Organization.objects.filter(id=opts['org']).first()
        if not org:
            raise CommandError(f"No organization {opts['org']}")
        days = max(1, opts['days'])
        now = timezone.now()
        since = now - timedelta(days=days)
        w = self.stdout.write

        flag = bool(getattr(org, 'calendar_classification_enabled', False))
        w(f"Org {org.id} — {org.name}")
        w(f"  calendar_classification_enabled = {flag}"
          + ("" if flag else "   (Stage 6 and calendar meeting proposals are OFF)"))
        w("")

        integrations = list(
            UserIntegration.objects.filter(
                org=org, provider__in=('google_calendar', 'microsoft_calendar'))
            .select_related('user').order_by('user__username', 'provider'))
        if not integrations:
            w("No calendar connections.")
            return

        w("Connections:")
        for i in integrations:
            last = timezone.localtime(i.last_synced_at).strftime('%Y-%m-%d %H:%M') \
                if i.last_synced_at else 'never'
            err = f"  error: {i.last_sync_error[:80]}" if i.last_sync_error else ''
            w(f"  {i.user.username:<24} {i.provider:<19} connected={i.is_connected!s:<5} "
              f"failures={i.sync_failure_count or 0}  last sync {last}{err}")
        w("")

        own_domains, member_emails = firm_identity(org)
        w(f"Firm domains treated as internal: {', '.join(sorted(own_domains)) or '(none)'}")
        w(f"Events in the last {days} day(s), by person:")
        users = {i.user_id: i.user for i in integrations}
        for uid, user in users.items():
            evs = list(CalendarEvent.objects.filter(org=org, user_id=uid, start__gte=since,
                                                    start__lt=now))
            match = Counter()
            reasons = Counter()
            self_emails = {(user.email or '').lower()} | {
                (i.provider_email or '').lower() for i in integrations if i.user_id == uid}
            self_emails.discard('')
            for ev in evs:
                if ev.extracted_client_id and (ev.extraction_confidence or 0) >= 0.70:
                    match['matched'] += 1
                elif ev.extracted_client_id:
                    match['matched_low'] += 1
                else:
                    match['unmatched'] += 1
                ok, why = qualifies(ev, org, user, own_domains, member_emails, self_emails)
                reasons['qualifies' if ok else why] += 1
            w(f"  {user.username}: {len(evs)} events — matched {match['matched']}, "
              f"low-confidence {match['matched_low']}, unmatched {match['unmatched']}")
            if evs:
                w("      off-computer meeting check: "
                  + ', '.join(f"{k} {v}" for k, v in reasons.most_common()))

            cal = Block.all_objects.filter(user_id=uid, device_id=CALENDAR_DEVICE_ID,
                                           hints__source=CALENDAR_SOURCE, start__gte=since)
            pending = cal.filter(deleted_at__isnull=True, classification_state='proposed').count()
            confirmed = cal.filter(deleted_at__isnull=True, classification_state='committed').count()
            dismissed = cal.exclude(deleted_at__isnull=True).count() + \
                cal.filter(deleted_at__isnull=True, classification_state='suppressed').count()
            w(f"      calendar entries in Daily Review: pending {pending}, "
              f"confirmed {confirmed}, dismissed {dismissed}")
