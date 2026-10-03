"""
Send Timesheet Review Reminder Emails

Django management command that sends morning email digests to users
who have unreviewed/unsubmitted time from the last workday.

Features:
  - Monday mornings review Friday's timesheet
  - Respects per-user email_timesheet_reminders preference
  - Skips users with already-approved timesheets
  - HTML email in the shared TimeTracker shell, with client breakdown
  - Plain text fallback
  - Dry run mode for testing

Usage:
    python manage.py send_timesheet_reminders
    python manage.py send_timesheet_reminders --dry-run
    python manage.py send_timesheet_reminders --force
    python manage.py send_timesheet_reminders --user-id 1

Schedule (Render Cron Job):
    0 13 * * 1-5   (1 PM UTC = 8 AM EST, Mon-Fri)

Place at:
    tracker/management/commands/send_timesheet_reminders.py
"""

from datetime import date, timedelta, datetime, time as dt_time

from django.core.management.base import BaseCommand
from tracker.email_service import (
    send_email, _wrap_html, _btn, _p, _panel, _rows, _e, _prefs_note,
)
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


# ============================================================
# Configuration
# ============================================================
REMINDER_FROM_EMAIL = getattr(settings, 'TIMESHEET_REMINDER_FROM_EMAIL',
                              settings.DEFAULT_FROM_EMAIL or 'noreply@timetracker.mavops.ai')
WEB_APP_URL = getattr(settings, 'TIMETRACKER_WEB_URL', 'https://timetracker.mavops.ai')
MIN_HOURS_TO_SKIP = getattr(settings, 'TIMESHEET_REMINDER_MIN_HOURS_TO_SKIP', None)


class Command(BaseCommand):
    help = 'Send morning timesheet review reminder emails for the last workday'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show who would receive emails without actually sending',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Send even if timesheet is already approved',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Send only to a specific user (for testing)',
        )

    def _get_review_date(self):
        """
        Get the last workday to review.
        - Monday → Friday
        - Tue-Fri → yesterday
        - Sat/Sun → None (skip)
        """
        today = date.today()
        if today.weekday() == 0:  # Monday
            return today - timedelta(days=3)  # Friday
        elif today.weekday() in (5, 6):  # Sat/Sun
            return None
        else:
            return today - timedelta(days=1)

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        user_id = options.get('user_id')

        review_date = self._get_review_date()
        if review_date is None:
            self.stdout.write(self.style.WARNING('Weekend — no workday to review. Skipping.'))
            return

        day_label = "Friday" if date.today().weekday() == 0 else "yesterday"
        self.stdout.write(f'Checking timesheets for {review_date} ({day_label})...')

        users = self._get_users_to_notify(review_date, user_id, force)

        if not users:
            self.stdout.write(self.style.SUCCESS('No users need reminders today.'))
            return

        self.stdout.write(f'Found {len(users)} user(s) to remind:')

        sent_count = 0
        error_count = 0

        for user_data in users:
            user = user_data['user']
            summary = user_data['summary']

            self.stdout.write(f'  • {user.email or user.username}: '
                            f'{summary["total_hours"]:.1f} hrs, '
                            f'status={summary["status"]}')

            if dry_run:
                continue

            try:
                self._send_reminder_email(user, review_date, summary)
                sent_count += 1
            except Exception as e:
                error_count += 1
                self.stderr.write(self.style.ERROR(
                    f'    ✗ Failed to send to {user.email}: {e}'
                ))

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\nDry run complete. Would have sent {len(users)} email(s).'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nDone: {sent_count} sent, {error_count} failed.'
            ))

    def _get_users_to_notify(self, review_date, user_id=None, force=False):
        """
        Get users who need a timesheet reminder.
        
        Filters:
        - Active users with email addresses
        - email_timesheet_reminders preference is True (or no preference record yet)
        - Timesheet not already approved (unless --force)
        """
        from tracker.models import Block, Timesheet

        # Base queryset
        if user_id:
            qs = User.objects.filter(id=user_id, is_active=True)
        else:
            qs = User.objects.filter(is_active=True)

        # Must have email
        qs = qs.exclude(email='').exclude(email__isnull=True)

        # Respect user preferences:
        # Include users who opted IN, or who have no preferences record yet (default=on)
        qs = qs.filter(
            models.Q(preferences__email_timesheet_reminders=True) |
            models.Q(preferences__isnull=True)
        )

        results = []

        for user in qs:
            # Skip test/demo accounts
            email = (user.email or '').lower()
            if 'test' in email and email.endswith('@gmail.com'):
                continue

            # Check if timesheet for this week is already approved
            if not force:
                # Find the Monday of the review_date's week
                days_since_monday = review_date.weekday()
                week_start = review_date - timedelta(days=days_since_monday)
                
                ts = Timesheet.objects.filter(
                    user=user,
                    week_start=week_start,
                ).first()
                if ts and ts.status == 'approved':
                    continue

            # Get time blocks for review date using the `day` field
            blocks = Block.objects.filter(
                user=user,
                day=review_date,
            )

            # Build summary
            client_hours = {}
            total_minutes = 0
            has_unassigned = False

            for block in blocks:
                # Use the minutes field (already computed), or calculate from start/end
                if block.minutes:
                    duration_mins = block.minutes
                elif block.start and block.end:
                    duration_mins = int((block.end - block.start).total_seconds() / 60)
                else:
                    duration_mins = 0

                total_minutes += duration_mins

                client_id = block.client_id
                client_name = "Uncategorized"
                if client_id and block.client:
                    client_name = block.client.name
                elif not client_id:
                    has_unassigned = True

                key = client_id or "unassigned"
                if key not in client_hours:
                    client_hours[key] = {"client_name": client_name, "minutes": 0}
                client_hours[key]["minutes"] += duration_mins

            total_hours = round(total_minutes / 60, 2)

            if MIN_HOURS_TO_SKIP is not None and total_hours <= 0:
                continue

            entries = [
                {"client_name": d["client_name"], "hours": round(d["minutes"] / 60, 2)}
                for d in sorted(client_hours.values(), key=lambda x: x["minutes"], reverse=True)
            ]

            # Get timesheet status
            status = "draft"
            days_since_monday = review_date.weekday()
            week_start = review_date - timedelta(days=days_since_monday)
            ts = Timesheet.objects.filter(
                user=user,
                week_start=week_start,
            ).first()
            if ts:
                status = ts.status

            results.append({
                'user': user,
                'summary': {
                    'date': review_date.isoformat(),
                    'total_hours': total_hours,
                    'status': status,
                    'entries': entries,
                    'entry_count': blocks.count(),
                    'has_unassigned': has_unassigned,
                },
            })

        return results

    def _send_reminder_email(self, user, review_date, summary):
        """Send the reminder email through the shared SendGrid shell."""
        display_name = getattr(user, 'first_name', '') or user.username
        date_str = review_date.strftime('%A, %B %d')
        review_url = f"{WEB_APP_URL}/daily?date={review_date.isoformat()}"

        status = summary.get('status', 'draft')
        if status == 'submitted':
            status_text, status_tone = "Submitted — pending approval", 'brand'
        elif status == 'approved':
            status_text, status_tone = "Approved", 'brand'
        else:
            status_text, status_tone = "Draft — not yet submitted", 'warn'

        html_content = self._build_html_email(
            display_name=display_name,
            date_str=date_str,
            summary=summary,
            review_url=review_url,
            status_text=status_text,
            status_tone=status_tone,
        )

        text_content = self._build_text_email(
            display_name=display_name,
            date_str=date_str,
            summary=summary,
            review_url=review_url,
            status_text=status_text,
        )

        # Django's mail path has no EMAIL_BACKEND configured; every other
        # email goes through SendGrid, so this one does too.
        sent = send_email(
            to_email=user.email,
            subject=f"Review your timesheet for {date_str}",
            html_content=html_content,
            plain_content=text_content,
            from_email=REMINDER_FROM_EMAIL,
            categories=["timesheet_reminder", "daily"],
        )
        if not sent:
            raise RuntimeError(f"SendGrid did not accept the email to {user.email}")

    def _build_html_email(self, display_name, date_str, summary,
                          review_url, status_text, status_tone):
        """Build the HTML email in the shared TimeTracker shell."""
        entries = summary.get('entries', [])
        total_hours = summary.get('total_hours', 0)

        if entries:
            table = _rows(
                [(_e(e['client_name']), f"{e['hours']:.1f} hrs") for e in entries],
                heading=('Client', 'Hours'),
                total=f"{total_hours:.1f} hrs",
            )
        else:
            table = _panel('<strong>No time was captured.</strong> If you worked '
                           'that day, check that the TimeTracker desktop app is running.',
                           'warn')

        body = (
            _p(f'Hi {_e(display_name)},')
            + _p("Here's your time summary. Please review and submit your timesheet.",
                 last=True)
            + table
            + _panel(f'Status: <strong>{_e(status_text)}</strong>', status_tone)
            + _btn(review_url, 'brand', 'Review &amp; submit')
        )
        return _wrap_html('brand', '', 'Review your timesheet', body,
                          subtitle=_e(date_str),
                          preheader=f'{total_hours:.1f} hrs captured · {_e(status_text)}',
                          footer_note=_prefs_note())

    def _build_text_email(self, display_name, date_str, summary, review_url, status_text):
        """Build plain text fallback."""
        entries = summary.get('entries', [])
        total_hours = summary.get('total_hours', 0)

        lines = [
            f"Review Your Timesheet — {date_str}",
            f"{'=' * 40}",
            "",
            f"Hi {display_name},",
            "",
            "Here's your time summary. Please review and submit your timesheet.",
            "",
        ]

        if entries:
            max_name_len = max(len(e['client_name']) for e in entries)
            for entry in entries:
                name = entry['client_name'].ljust(max_name_len)
                lines.append(f"  {name}  {entry['hours']:.1f} hrs")
            lines.append(f"  {'─' * (max_name_len + 12)}")
            lines.append(f"  {'Total'.ljust(max_name_len)}  {total_hours:.1f} hrs")
        else:
            lines.append("  ⚠️ No time was tracked")

        lines.extend([
            "",
            f"Status: {status_text}",
            "",
            "Review and submit your timesheet:",
            review_url,
            "",
            "—",
            "TimeTracker automated reminder",
        ])

        return "\n".join(lines)