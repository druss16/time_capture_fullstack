"""
Send Timesheet Review Reminder Emails

Django management command that sends morning email digests to users
who have unreviewed/unsubmitted time from the last workday.

Features:
  - Monday mornings review Friday's timesheet
  - Respects per-user email_timesheet_reminders preference
  - Skips users with already-approved timesheets
  - Beautiful dark-themed HTML email with client breakdown
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
    yourapp/management/commands/send_timesheet_reminders.py
"""

from datetime import date, timedelta, datetime, time as dt_time

from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
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
        # ── Adjust these imports to your actual models ──
        try:
            from timeblocks.models import TimeBlock
        except ImportError:
            from tracker.models import TimeBlock  # adjust!

        try:
            from timesheets.models import Timesheet
            HAS_TIMESHEET_MODEL = True
        except ImportError:
            HAS_TIMESHEET_MODEL = False

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

        review_start = timezone.make_aware(datetime.combine(review_date, dt_time.min))
        review_end = timezone.make_aware(datetime.combine(review_date, dt_time.max))

        results = []

        for user in qs:
            # Skip if already approved
            if HAS_TIMESHEET_MODEL and not force:
                ts = Timesheet.objects.filter(user=user, date=review_date).first()
                if ts and getattr(ts, 'status', '') == 'approved':
                    continue

            # Get time blocks for review date
            blocks = TimeBlock.objects.filter(
                user=user,
                start_time__gte=review_start,
                start_time__lte=review_end,
            )

            # Build summary
            client_hours = {}
            total_seconds = 0
            has_unassigned = False

            for block in blocks:
                if block.end_time and block.start_time:
                    duration = (block.end_time - block.start_time).total_seconds()
                elif hasattr(block, 'duration_seconds') and block.duration_seconds:
                    duration = block.duration_seconds
                else:
                    duration = 0

                total_seconds += duration

                client_id = getattr(block, 'client_id', None)
                client_name = "Uncategorized"
                if client_id and hasattr(block, 'client') and block.client:
                    client_name = getattr(block.client, 'name', str(client_id))
                elif not client_id:
                    has_unassigned = True

                key = client_id or "unassigned"
                if key not in client_hours:
                    client_hours[key] = {"client_name": client_name, "seconds": 0}
                client_hours[key]["seconds"] += duration

            total_hours = round(total_seconds / 3600, 2)

            if MIN_HOURS_TO_SKIP is not None and total_hours <= 0:
                continue

            entries = [
                {"client_name": d["client_name"], "hours": round(d["seconds"] / 3600, 2)}
                for d in sorted(client_hours.values(), key=lambda x: x["seconds"], reverse=True)
            ]

            status = "draft"
            if HAS_TIMESHEET_MODEL:
                ts = Timesheet.objects.filter(user=user, date=review_date).first()
                if ts:
                    status = getattr(ts, 'status', 'draft')

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
        """Send the reminder email with HTML template."""
        display_name = getattr(user, 'first_name', '') or user.username
        date_str = review_date.strftime('%A, %B %d')
        review_url = f"{WEB_APP_URL}/daily?date={review_date.isoformat()}"

        status = summary.get('status', 'draft')
        if status == 'submitted':
            status_text = "Submitted — pending approval"
            status_color = "#14B8A6"
        elif status == 'approved':
            status_text = "Approved ✓"
            status_color = "#10B981"
        else:
            status_text = "Draft — not yet submitted"
            status_color = "#F59E0B"

        subject = f"⏱ Review your timesheet for {date_str}"

        html_content = self._build_html_email(
            display_name=display_name,
            date_str=date_str,
            summary=summary,
            review_url=review_url,
            status_text=status_text,
            status_color=status_color,
        )

        text_content = self._build_text_email(
            display_name=display_name,
            date_str=date_str,
            summary=summary,
            review_url=review_url,
            status_text=status_text,
        )

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=REMINDER_FROM_EMAIL,
            to=[user.email],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)

    def _build_html_email(self, display_name, date_str, summary,
                          review_url, status_text, status_color):
        """Build the HTML email content."""
        entries = summary.get('entries', [])
        total_hours = summary.get('total_hours', 0)

        client_rows = ""
        if entries:
            for entry in entries:
                client_rows += f"""
                <tr>
                    <td style="padding: 10px 16px; border-bottom: 1px solid #333; color: #fff; font-size: 14px;">
                        {entry['client_name']}
                    </td>
                    <td style="padding: 10px 16px; border-bottom: 1px solid #333; color: #14B8A6; font-weight: bold; text-align: right; font-size: 14px;">
                        {entry['hours']:.1f} hrs
                    </td>
                </tr>"""
        else:
            client_rows = """
                <tr>
                    <td colspan="2" style="padding: 20px 16px; color: #F59E0B; text-align: center; font-size: 14px;">
                        ⚠️ No time was tracked
                    </td>
                </tr>"""

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #111; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #111;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table width="500" cellpadding="0" cellspacing="0" style="background-color: #1A1A1A; border-radius: 12px; overflow: hidden;">
                    
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #14B8A6, #0D9488); padding: 24px 30px;">
                            <h1 style="margin: 0; color: #fff; font-size: 20px; font-weight: 700;">
                                📋 Review Your Timesheet
                            </h1>
                            <p style="margin: 6px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">
                                {date_str}
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Greeting -->
                    <tr>
                        <td style="padding: 24px 30px 8px;">
                            <p style="margin: 0; color: #ccc; font-size: 15px; line-height: 1.5;">
                                Hi {display_name},<br>
                                Here's your time summary. Please review and submit your timesheet.
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Time Summary Table -->
                    <tr>
                        <td style="padding: 16px 30px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #252525; border-radius: 8px; overflow: hidden;">
                                <thead>
                                    <tr>
                                        <th style="padding: 12px 16px; text-align: left; color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #333;">
                                            Client
                                        </th>
                                        <th style="padding: 12px 16px; text-align: right; color: #888; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #333;">
                                            Hours
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {client_rows}
                                </tbody>
                                <tfoot>
                                    <tr>
                                        <td style="padding: 12px 16px; color: #fff; font-weight: bold; font-size: 15px; border-top: 2px solid #3A3A3A;">
                                            Total
                                        </td>
                                        <td style="padding: 12px 16px; color: #14B8A6; font-weight: bold; font-size: 15px; text-align: right; border-top: 2px solid #3A3A3A;">
                                            {total_hours:.1f} hrs
                                        </td>
                                    </tr>
                                </tfoot>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Status -->
                    <tr>
                        <td style="padding: 0 30px 16px;">
                            <p style="margin: 0; font-size: 13px;">
                                <span style="color: {status_color};">●</span>
                                <span style="color: #999; margin-left: 6px;">{status_text}</span>
                            </p>
                        </td>
                    </tr>
                    
                    <!-- CTA Button -->
                    <tr>
                        <td style="padding: 8px 30px 28px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center">
                                        <a href="{review_url}" 
                                           style="display: inline-block; background-color: #14B8A6; color: #fff; 
                                                  text-decoration: none; padding: 14px 40px; border-radius: 8px; 
                                                  font-size: 16px; font-weight: 600; letter-spacing: 0.3px;">
                                            📝 Review &amp; Submit Timesheet
                                        </a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 16px 30px; background-color: #151515; border-top: 1px solid #252525;">
                            <p style="margin: 0; color: #555; font-size: 12px; text-align: center; line-height: 1.4;">
                                This is an automated reminder from TimeTracker.<br>
                                You can adjust notification preferences in your 
                                <a href="{WEB_APP_URL}/settings" style="color: #14B8A6; text-decoration: none;">account settings</a>.
                            </p>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

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