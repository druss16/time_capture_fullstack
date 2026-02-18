# tracker/tasks.py
"""
Celery background tasks for TimeTracker:
1. Auto-compact recent events every 5 minutes
2. Run AI classification on uncategorized blocks
3. Clean up old raw events
4. Daily timesheet review reminders (Mon-Fri 9am)
5. Weekly summary emails (Monday 9:30am)
6. Timesheet reminders (Monday 9am)
7. Timesheet auto-submit (Tuesday 9am)
8. Weekly timesheet creation (Monday 1am)
9. Manager approval notifications (Tuesday 10am)
"""

from celery import shared_task
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# DAILY NOTIFICATION TASKS (NEW)
# ============================================================================

@shared_task(name='tracker.tasks.send_daily_timesheet_reminders_task', bind=True, max_retries=3)
def send_daily_timesheet_reminders_task(self):
    """
    Mon-Fri 9am: Send email reminders to users who have unreviewed hours from yesterday.
    
    This is DIFFERENT from the weekly submission reminder - this is for DAILY review
    of time tracked to ensure accurate categorization before it gets too stale.
    
    Schedule: crontab(hour=9, minute=0, day_of_week='1-5')  # Mon-Fri 9am
    """
    try:
        from tracker.models import Block, TimesheetSubmission, UserPreference
        from django.core.mail import send_mail
        from django.conf import settings
        from django.contrib.auth import get_user_model
        
        User = get_user_model()
        yesterday = timezone.localdate() - timedelta(days=1)
        
        # Get all users with time tracked yesterday
        users_with_time = User.objects.filter(
            blocks__day=yesterday
        ).distinct()
        
        sent_count = 0
        skipped_count = 0
        errors = []
        
        for user in users_with_time:
            try:
                # Skip if no email
                if not user.email:
                    skipped_count += 1
                    continue
                
                # Check user preference for email notifications
                try:
                    pref = UserPreference.objects.get(user=user)
                    if not getattr(pref, 'email_timesheet_reminders', True):
                        skipped_count += 1
                        continue
                except UserPreference.DoesNotExist:
                    pass  # Default to sending
                
                # Get their blocks from yesterday
                blocks = Block.objects.filter(user=user, day=yesterday)
                total_minutes = sum(b.minutes or 0 for b in blocks)
                total_hours = total_minutes / 60
                
                if total_hours < 0.5:
                    skipped_count += 1
                    continue  # Skip if minimal time
                
                unassigned_count = blocks.filter(client__isnull=True).count()
                
                # Get client breakdown
                client_hours = {}
                for block in blocks.filter(client__isnull=False):
                    client_name = block.client.name
                    hrs = (block.minutes or 0) / 60
                    client_hours[client_name] = client_hours.get(client_name, 0) + hrs
                
                client_breakdown = sorted(
                    client_hours.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5]
                
                # Build email
                user_name = user.first_name or user.username
                date_str = yesterday.strftime('%A, %b %d')
                
                # Client lines for email
                client_lines = '\n'.join([f'  • {name}: {hrs:.1f}h' for name, hrs in client_breakdown])
                if not client_lines:
                    client_lines = '  • No clients assigned yet'
                
                unassigned_warning = f'\n⚠️ {unassigned_count} blocks need client assignment.\n' if unassigned_count else ''
                
                frontend_url = getattr(settings, 'FRONTEND_URL', 'https://app.timetracker.com')
                
                plain_message = f"""
Hi {user_name},

You tracked {total_hours:.1f} hours on {date_str} that need review:

{client_lines}
{unassigned_warning}
Review your timesheet: {frontend_url}/timesheet

—
TimeTracker

Manage notification preferences: {frontend_url}/settings
                """.strip()
                
                # HTML version
                client_rows = ''.join([
                    f'<tr><td style="padding: 8px 0; border-bottom: 1px solid #e2e8f0;">{name}</td>'
                    f'<td style="padding: 8px 0; border-bottom: 1px solid #e2e8f0; text-align: right; font-weight: bold;">{hrs:.1f}h</td></tr>'
                    for name, hrs in client_breakdown
                ])
                if not client_rows:
                    client_rows = '<tr><td colspan="2" style="padding: 8px 0; color: #94a3b8;">No clients assigned yet</td></tr>'
                
                unassigned_html = f'''
                <div style="background: #fef3c7; border: 1px solid #fcd34d; padding: 12px 16px; border-radius: 8px; margin: 16px 0;">
                    <p style="margin: 0; color: #92400e; font-size: 14px;">
                        ⚠️ <strong>{unassigned_count} block{"s" if unassigned_count != 1 else ""}</strong> need client assignment
                    </p>
                </div>
                ''' if unassigned_count else ''
                
                html_message = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <div style="max-width: 500px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%); padding: 24px; border-radius: 16px 16px 0 0; text-align: center;">
            <h1 style="margin: 0; color: white; font-size: 24px;">⏰ Review Your Time</h1>
        </div>
        <div style="background: white; padding: 24px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
            <p style="color: #475569; font-size: 16px; line-height: 1.5; margin-top: 0;">
                Hi {user_name},
            </p>
            <p style="color: #475569; font-size: 16px; line-height: 1.5;">
                You tracked <strong style="color: #ea580c;">{total_hours:.1f} hours</strong> on {date_str}:
            </p>
            <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                {client_rows}
            </table>
            {unassigned_html}
            <div style="text-align: center; margin: 24px 0;">
                <a href="{frontend_url}/timesheet" 
                   style="display: inline-block; background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%); color: white; padding: 14px 28px; border-radius: 10px; text-decoration: none; font-weight: bold; font-size: 16px;">
                    Review Timesheet →
                </a>
            </div>
            <p style="color: #94a3b8; font-size: 12px; margin-bottom: 0; text-align: center;">
                <a href="{frontend_url}/settings" style="color: #94a3b8;">Manage notification preferences</a>
            </p>
        </div>
    </div>
</body>
</html>
                '''
                
                send_mail(
                    subject=f'⏰ Review your time for {date_str}',
                    message=plain_message,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@timetracker.local'),
                    recipient_list=[user.email],
                    html_message=html_message,
                    fail_silently=False,
                )
                
                sent_count += 1
                logger.info(f"[DAILY-REMINDER] Sent to {user.email}: {total_hours:.1f}h")
                
            except Exception as e:
                errors.append(f'{user.email}: {str(e)}')
                logger.error(f"[DAILY-REMINDER] Failed for {user.email}: {e}")
        
        logger.info(
            f"[DAILY-REMINDER] Complete: {sent_count} sent, "
            f"{skipped_count} skipped, {len(errors)} errors"
        )
        
        return {
            'date': yesterday.isoformat(),
            'sent': sent_count,
            'skipped': skipped_count,
            'errors': errors[:10],  # Limit errors in return
        }
        
    except Exception as exc:
        logger.error(f"[DAILY-REMINDER] Task failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * 5)


@shared_task(name='tracker.tasks.send_weekly_summary_task', bind=True, max_retries=3)
def send_weekly_summary_task(self):
    """
    Monday 9:30am: Send weekly summary email showing last week's time breakdown by client.
    
    Schedule: crontab(hour=9, minute=30, day_of_week=1)  # Monday 9:30am
    """
    try:
        from tracker.models import Block, UserPreference
        from django.core.mail import send_mail
        from django.conf import settings
        from django.contrib.auth import get_user_model
        
        User = get_user_model()
        today = timezone.localdate()
        
        # Last week = Monday to Sunday
        days_since_monday = today.weekday()  # Monday = 0
        last_monday = today - timedelta(days=days_since_monday + 7)
        last_sunday = last_monday + timedelta(days=6)
        
        # Get all active users
        users = User.objects.filter(is_active=True)
        
        sent_count = 0
        skipped_count = 0
        
        for user in users:
            try:
                if not user.email:
                    skipped_count += 1
                    continue
                
                # Check preference
                try:
                    pref = UserPreference.objects.get(user=user)
                    if not getattr(pref, 'email_weekly_summary', True):
                        skipped_count += 1
                        continue
                except UserPreference.DoesNotExist:
                    pass
                
                # Get week's blocks
                blocks = Block.objects.filter(
                    user=user,
                    day__gte=last_monday,
                    day__lte=last_sunday,
                )
                
                if not blocks.exists():
                    skipped_count += 1
                    continue
                
                # Calculate totals
                total_minutes = sum(b.minutes or 0 for b in blocks)
                total_hours = total_minutes / 60
                
                if total_hours < 1:
                    skipped_count += 1
                    continue
                
                # Client breakdown
                client_hours = {}
                for block in blocks.filter(client__isnull=False):
                    client_name = block.client.name
                    hrs = (block.minutes or 0) / 60
                    client_hours[client_name] = client_hours.get(client_name, 0) + hrs
                
                client_breakdown = sorted(
                    client_hours.items(),
                    key=lambda x: x[1],
                    reverse=True
                )
                
                # Daily breakdown
                daily_hours = {}
                day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                for block in blocks:
                    day_idx = block.day.weekday()
                    day_name = day_names[day_idx]
                    hrs = (block.minutes or 0) / 60
                    daily_hours[day_name] = daily_hours.get(day_name, 0) + hrs
                
                user_name = user.first_name or user.username
                week_str = f"{last_monday.strftime('%b %d')} - {last_sunday.strftime('%b %d')}"
                
                # Build email
                client_lines = '\n'.join([f'  • {name}: {hrs:.1f}h' for name, hrs in client_breakdown[:10]])
                daily_lines = ' | '.join([f'{day}: {daily_hours.get(day, 0):.1f}h' for day in day_names[:5]])
                
                frontend_url = getattr(settings, 'FRONTEND_URL', 'https://app.timetracker.com')
                
                plain_message = f"""
Hi {user_name},

Here's your weekly time summary for {week_str}:

📊 Total: {total_hours:.1f} hours

By Day:
  {daily_lines}

By Client:
{client_lines}

View detailed report: {frontend_url}/reports

—
TimeTracker
                """.strip()
                
                send_mail(
                    subject=f'📊 Weekly Summary: {total_hours:.1f} hours ({week_str})',
                    message=plain_message,
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@timetracker.local'),
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                
                sent_count += 1
                logger.info(f"[WEEKLY-SUMMARY] Sent to {user.email}: {total_hours:.1f}h")
                
            except Exception as e:
                logger.error(f"[WEEKLY-SUMMARY] Failed for {user.email}: {e}")
        
        logger.info(
            f"[WEEKLY-SUMMARY] Complete: {sent_count} sent, {skipped_count} skipped"
        )
        
        return {
            'week': f"{last_monday.isoformat()} to {last_sunday.isoformat()}",
            'sent': sent_count,
            'skipped': skipped_count,
        }
        
    except Exception as exc:
        logger.error(f"[WEEKLY-SUMMARY] Task failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * 5)


@shared_task(name='tracker.tasks.cleanup_old_notification_dismissals')
def cleanup_old_notification_dismissals():
    """
    Sunday midnight: Clean up old notification dismissal records.
    
    Schedule: crontab(hour=0, minute=0, day_of_week=0)  # Sunday midnight
    """
    try:
        from tracker.models import UserPreference
        
        # Clear dismissals older than 7 days
        week_ago = (timezone.localdate() - timedelta(days=7)).isoformat()
        
        updated = UserPreference.objects.filter(
            last_timesheet_reminder_dismissed__lt=week_ago
        ).update(last_timesheet_reminder_dismissed=None)
        
        logger.info(f"[CLEANUP] Cleared {updated} old notification dismissals")
        
        return {'cleaned': updated}
        
    except Exception as e:
        logger.error(f"[CLEANUP] Notification dismissal cleanup failed: {e}")
        return {'error': str(e)}


@shared_task(name='tracker.tasks.send_approval_notification_task')
def send_approval_notification_task(user_id: int, timesheet_id: int, status: str):
    """
    Send notification when a timesheet is approved/rejected.
    Called from the approval endpoint (not scheduled).
    
    Args:
        user_id: ID of user who owns the timesheet
        timesheet_id: ID of the timesheet
        status: 'approved' or 'rejected'
    """
    from django.contrib.auth import get_user_model
    from django.core.mail import send_mail
    from django.conf import settings
    from tracker.models import TimesheetSubmission, UserPreference
    
    User = get_user_model()
    
    try:
        user = User.objects.get(id=user_id)
        timesheet = TimesheetSubmission.objects.get(id=timesheet_id)
        
        # Check user preference
        try:
            pref = UserPreference.objects.get(user=user)
            if not getattr(pref, 'email_approval_notifications', True):
                return {'skipped': 'user preference'}
        except UserPreference.DoesNotExist:
            pass
        
        if not user.email:
            return {'skipped': 'no email'}
        
        period = f"{timesheet.period_start.strftime('%b %d')} - {timesheet.period_end.strftime('%b %d')}"
        frontend_url = getattr(settings, 'FRONTEND_URL', 'https://app.timetracker.com')
        
        if status == 'approved':
            subject = f"✅ Timesheet Approved: {period}"
            message = f"""
Hi {user.first_name or user.username},

Great news! Your timesheet for {period} has been approved.

Total hours: {timesheet.total_hours:.1f}

View details: {frontend_url}/timesheet

—
TimeTracker
            """.strip()
            
        elif status == 'rejected':
            notes = getattr(timesheet, 'reviewer_notes', '') or ''
            feedback = f"\nFeedback: {notes}" if notes else "\nPlease review and resubmit."
            
            subject = f"❌ Timesheet Needs Revision: {period}"
            message = f"""
Hi {user.first_name or user.username},

Your timesheet for {period} needs revision.
{feedback}

Edit timesheet: {frontend_url}/timesheet

—
TimeTracker
            """.strip()
        else:
            return {'skipped': 'invalid status'}
        
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@timetracker.local'),
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        logger.info(f"[APPROVAL] Sent {status} notification to {user.email}")
        return {'sent': True, 'status': status}
        
    except Exception as e:
        logger.error(f"[APPROVAL] Failed to send notification: {e}")
        return {'error': str(e)}


# ============================================================================
# TIMESHEET WORKFLOW TASKS (EXISTING)
# ============================================================================

@shared_task(name='tracker.send_timesheet_reminders')
def send_timesheet_reminders():
    """
    Monday 9am: Send reminder emails for unsubmitted timesheets from last week.
    
    This gives users Monday to review their time before auto-submit on Tuesday.
    
    Schedule: crontab(hour=9, minute=0, day_of_week=1)  # Monday 9am
    """
    from tracker.models import Timesheet, Block
    from django.core.mail import send_mail
    from django.conf import settings
    
    today = timezone.now().date()
    
    # Get last week's Monday (the week that just ended)
    # If today is Monday Dec 9, last week was Dec 2-8
    days_since_monday = today.weekday()  # Monday = 0
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    
    # Find all DRAFT timesheets for last week
    draft_timesheets = Timesheet.objects.filter(
        week_start=last_monday,
        status='draft'
    ).select_related('user', 'org')
    
    reminders_sent = 0
    skipped = 0
    
    for timesheet in draft_timesheets:
        user = timesheet.user
        
        # Count their blocks for that week
        blocks = Block.objects.filter(
            user=user,
            org=timesheet.org,
            start__date__gte=last_monday,
            start__date__lte=last_sunday,
        )
        
        block_count = blocks.count()
        
        if block_count == 0:
            # No time tracked, skip reminder
            skipped += 1
            continue
        
        # Calculate total hours
        total_minutes = blocks.aggregate(total=Sum('minutes'))['total'] or 0
        total_hours = round(total_minutes / 60, 1)
        
        # Send reminder email
        if user.email:
            try:
                send_mail(
                    subject=f'⏰ Timesheet Reminder: Week of {last_monday.strftime("%b %d")}',
                    message=f"""Hi {user.first_name or user.username},

Your timesheet for the week of {last_monday.strftime('%B %d')} - {last_sunday.strftime('%B %d, %Y')} has not been submitted yet.

📊 Summary:
• {total_hours} hours tracked
• {block_count} time blocks

Please review and submit your timesheet by end of day today. 

⚠️ If not submitted, it will be automatically submitted tomorrow morning (Tuesday 9am).

To submit:
1. Go to Timecards
2. Select the week of {last_monday.strftime('%b %d')}
3. Review your time entries
4. Click "Submit for Approval"

Thanks,
TimeTracker
""",
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@timetracker.local'),
                    recipient_list=[user.email],
                    fail_silently=True,
                )
                reminders_sent += 1
                logger.info(f"[TIMESHEET] Reminder sent to {user.email} for week {last_monday}")
            except Exception as e:
                logger.error(f"[TIMESHEET] Failed to send reminder to {user.email}: {e}")
        else:
            logger.warning(f"[TIMESHEET] User {user.username} has no email address")
    
    logger.info(
        f"[TIMESHEET] Reminders complete: {reminders_sent} sent, "
        f"{skipped} skipped (no time), {draft_timesheets.count()} total draft"
    )
    
    return {
        'week': last_monday.isoformat(),
        'draft_timesheets_found': draft_timesheets.count(),
        'reminders_sent': reminders_sent,
        'skipped_empty': skipped,
    }


@shared_task(name='tracker.auto_submit_timesheets')
def auto_submit_timesheets():
    """
    Tuesday 9am: Auto-submit any DRAFT timesheets from last week.
    
    This ensures all timesheets get submitted even if users forget.
    Marks them with auto_submitted=True for audit purposes.
    
    Schedule: crontab(hour=9, minute=0, day_of_week=2)  # Tuesday 9am
    """
    from tracker.models import Timesheet, Block
    from django.core.mail import send_mail
    from django.conf import settings
    
    today = timezone.now().date()
    
    # Get last week's Monday
    days_since_monday = today.weekday()  # Tuesday = 1
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    
    # Find all DRAFT timesheets for last week
    draft_timesheets = Timesheet.objects.filter(
        week_start=last_monday,
        status='draft'
    ).select_related('user', 'org')
    
    auto_submitted = 0
    skipped_empty = 0
    errors = 0
    
    for timesheet in draft_timesheets:
        try:
            user = timesheet.user
            org = timesheet.org
            
            # Link blocks to this timesheet
            blocks_updated = Block.objects.filter(
                user=user,
                org=org,
                start__date__gte=last_monday,
                start__date__lte=last_sunday,
                timesheet__isnull=True,  # Not already linked
            ).update(timesheet=timesheet)
            
            # Recalculate totals
            blocks = Block.objects.filter(timesheet=timesheet)
            total_minutes = sum(b.minutes or 0 for b in blocks)
            
            if total_minutes == 0:
                # No time tracked, skip auto-submit
                skipped_empty += 1
                logger.debug(f"[TIMESHEET] Skipping auto-submit for {user.username} - no time tracked")
                continue
            
            # Use the model's submit method with auto=True
            timesheet.submit(notes='[Auto-submitted by system - Tuesday deadline]', auto=True)
            
            auto_submitted += 1
            logger.info(
                f"[TIMESHEET] Auto-submitted timesheet for {user.username}, "
                f"week {last_monday}, {timesheet.total_hours}h"
            )
            
            # Notify the user
            if user.email:
                try:
                    send_mail(
                        subject=f'✅ Timesheet Auto-Submitted: Week of {last_monday.strftime("%b %d")}',
                        message=f"""Hi {user.first_name or user.username},

Your timesheet for the week of {last_monday.strftime('%B %d')} - {last_sunday.strftime('%B %d, %Y')} was automatically submitted.

📊 Summary:
• Total hours: {timesheet.total_hours}
• Billable hours: {timesheet.billable_hours}
• Amount: ${timesheet.total_amount}

Your manager will review and approve it shortly. 

Need to make changes? Contact your manager to reject the timesheet so you can edit and resubmit.

Thanks,
TimeTracker
""",
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@timetracker.local'),
                        recipient_list=[user.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    logger.warning(f"[TIMESHEET] Failed to notify {user.email}: {e}")
                    
        except Exception as e:
            errors += 1
            logger.error(f"[TIMESHEET] Error auto-submitting timesheet {timesheet.id}: {e}", exc_info=True)
    
    logger.info(
        f"[TIMESHEET] Auto-submit complete: {auto_submitted} submitted, "
        f"{skipped_empty} skipped (empty), {errors} errors"
    )
    
    return {
        'week': last_monday.isoformat(),
        'draft_timesheets_found': draft_timesheets.count(),
        'auto_submitted': auto_submitted,
        'skipped_empty': skipped_empty,
        'errors': errors,
    }


@shared_task(name='tracker.create_weekly_timesheets')
def create_weekly_timesheets():
    """
    Monday 1am: Pre-create DRAFT timesheets for all active users for the new week.
    
    This ensures everyone has a timesheet ready when they start tracking time.
    Also helps with the approval queue visibility.
    
    Schedule: crontab(hour=1, minute=0, day_of_week=1)  # Monday 1am
    """
    from tracker.models import Timesheet, Organization, OrganizationMembership
    
    today = timezone.now().date()
    
    # Get this week's Monday
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)
    
    created_count = 0
    existing_count = 0
    
    # For each active organization
    for org in Organization.objects.filter(is_active=True):
        # Get all active members
        members = OrganizationMembership.objects.filter(
            organization=org,
            is_active=True
        ).select_related('user')
        
        for membership in members:
            user = membership.user
            
            # Check if timesheet already exists
            existing = Timesheet.objects.filter(
                org=org,
                user=user,
                week_start=this_monday
            ).exists()
            
            if existing:
                existing_count += 1
            else:
                Timesheet.objects.create(
                    org=org,
                    user=user,
                    week_start=this_monday,
                    status='draft',
                )
                created_count += 1
                logger.debug(f"[TIMESHEET] Created timesheet for {user.username}, week {this_monday}")
    
    logger.info(
        f"[TIMESHEET] Weekly creation complete: {created_count} created, "
        f"{existing_count} already existed"
    )
    
    return {
        'week': this_monday.isoformat(),
        'timesheets_created': created_count,
        'already_existed': existing_count,
    }


@shared_task(name='tracker.notify_managers_pending_approvals')
def notify_managers_pending_approvals():
    """
    Tuesday 10am (1 hour after auto-submit): Notify managers of pending approvals.
    
    Schedule: crontab(hour=10, minute=0, day_of_week=2)  # Tuesday 10am
    """
    from tracker.models import Timesheet, OrganizationMembership
    from django.core.mail import send_mail
    from django.conf import settings
    from collections import defaultdict
    
    today = timezone.now().date()
    
    # Get last week
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7)
    
    # Find all SUBMITTED timesheets
    pending = Timesheet.objects.filter(
        week_start=last_monday,
        status='submitted'
    ).select_related('user', 'org')
    
    if not pending.exists():
        logger.info("[TIMESHEET] No pending approvals to notify about")
        return {'notifications_sent': 0}
    
    # Group by org
    by_org = defaultdict(list)
    for ts in pending:
        by_org[ts.org_id].append(ts)
    
    notifications_sent = 0
    
    for org_id, timesheets in by_org.items():
        # Find managers/admins/owners in this org
        managers = OrganizationMembership.objects.filter(
            organization_id=org_id,
            role__in=['owner', 'admin', 'manager'],
            is_active=True
        ).select_related('user')
        
        for membership in managers:
            manager = membership.user
            if not manager.email:
                continue
            
            # Build summary
            summary_lines = []
            total_hours = 0
            for ts in timesheets:
                name = f"{ts.user.first_name} {ts.user.last_name}".strip() or ts.user.username
                auto_tag = " (auto-submitted)" if ts.auto_submitted else ""
                summary_lines.append(f"  • {name}: {ts.total_hours}h{auto_tag}")
                total_hours += float(ts.total_hours)
            
            try:
                send_mail(
                    subject=f'📋 {len(timesheets)} Timesheets Pending Approval - Week of {last_monday.strftime("%b %d")}',
                    message=f"""Hi {manager.first_name or manager.username},

There are {len(timesheets)} timesheets pending your approval for the week of {last_monday.strftime('%B %d')}.

📊 Summary ({total_hours:.1f} total hours):
{chr(10).join(summary_lines)}

Please review and approve/reject these timesheets at your earliest convenience.

→ Go to Approvals in TimeTracker to review.

Thanks,
TimeTracker
""",
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@timetracker.local'),
                    recipient_list=[manager.email],
                    fail_silently=True,
                )
                notifications_sent += 1
                logger.info(f"[TIMESHEET] Notified manager {manager.email} of {len(timesheets)} pending")
            except Exception as e:
                logger.error(f"[TIMESHEET] Failed to notify manager {manager.email}: {e}")
    
    return {
        'week': last_monday.isoformat(),
        'pending_timesheets': pending.count(),
        'notifications_sent': notifications_sent,
    }


# ============================================================================
# INDIVIDUAL BLOCK CLASSIFICATION (called by signal)
# ============================================================================

@shared_task(name='tracker.classify_block', bind=True, max_retries=3)
def classify_block_task(self, block_id: int):
    """
    Classify a single block using patterns and AI.
    Called automatically by signal when block is created.
    
    This is the fast path - uses pattern matching first,
    only falls back to AI if patterns don't give high confidence.
    
    Args:
        block_id: ID of block to classify
    
    Returns:
        dict with classification result
    """
    try:
        from tracker.models import Block, Client
        from tracker.views import pre_classify_obvious_categories
        from tracker.services.pattern_learning import PatternLearningService
        
        # Get block
        try:
            block = Block.objects.select_related('client', 'user', 'org').get(id=block_id)
        except Block.DoesNotExist:
            logger.warning(f"[CLASSIFY] Block {block_id} not found")
            return {"status": "not_found", "block_id": block_id}
        
        # Skip if already categorized
        if block.is_categorized:
            return {"status": "already_categorized", "block_id": block_id}
        
        # ✅ FIX: Get org and industry_type upfront
        org = getattr(block, 'org', None)
        industry_type = getattr(org, 'industry_type', 'general') or 'general'
        
        # Step 1: Try obvious patterns (CPA tools, meetings, email)
        pre_class = pre_classify_obvious_categories(block, industry_type=industry_type)
        
        if pre_class and pre_class.get('confidence', 0) >= 0.75:
            categories = pre_class.get('categories', {})
            if categories:
                block.category_hours = categories
                block.is_categorized = True
                block.categorized_at = timezone.now()
                block.categorized_by = 'pattern'
                block.ai_confidence = pre_class.get('confidence', 0.0)
                block.save()
                
                logger.info(
                    f"[CLASSIFY] ✅ Block {block_id} auto-categorized: "
                    f"{list(categories.keys())} ({pre_class.get('confidence'):.2f})"
                )
                
                return {
                    "status": "classified",
                    "block_id": block_id,
                    "categories": categories,
                    "confidence": pre_class.get('confidence'),
                    "source": "pattern"
                }
        
        # Step 2: Try learned patterns
        if block.user:
            learned = PatternLearningService.get_patterns_for_block(block, block.user)
            
            if learned:
                client_name, category, confidence = learned[0]
                
                if confidence >= 0.75 and (client_name or category):
                    # ✅ FIX: Client LOOKUP only — never create phantom clients
                    if client_name and not block.client and org:
                        try:
                            client = Client.objects.get(
                                org=org,
                                name__iexact=client_name,
                                is_active=True,
                            )
                            block.client = client
                        except (Client.DoesNotExist, Client.MultipleObjectsReturned):
                            pass  # Don't create phantom clients
                    
                    if category:
                        hours = round(block.minutes / 60.0, 2) if block.minutes else 0.1
                        block.category_hours = {category: hours}
                        block.is_categorized = True
                        block.categorized_at = timezone.now()
                        block.categorized_by = 'learned'
                        block.ai_confidence = confidence
                        block.save()
                        
                        logger.info(
                            f"[CLASSIFY] ✅ Block {block_id} learned pattern: "
                            f"{client_name or 'none'} / {category} ({confidence:.2f})"
                        )
                        
                        return {
                            "status": "classified",
                            "block_id": block_id,
                            "client": client_name,
                            "category": category,
                            "confidence": confidence,
                            "source": "learned"
                        }
        
        # Step 3: Not confident - leave for manual review
        logger.debug(f"[CLASSIFY] Block {block_id} needs manual review")
        
        return {
            "status": "needs_review",
            "block_id": block_id,
            "reason": "Low confidence"
        }
        
    except Exception as exc:
        logger.error(f"[CLASSIFY] Error on block {block_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)


# ============================================================================
# BATCH TASKS (existing)
# ============================================================================

@shared_task(name='tracker.auto_compact_recent_events')
def auto_compact_recent_events():
    """
    Auto-compact recent events for all active users.
    Runs every 5 minutes via Celery beat.
    
    This ensures blocks are created automatically without requiring
    the user to refresh the UI.
    """
    try:
        from tracker.services.compaction import auto_compact_all_active_users
        
        stats = auto_compact_all_active_users(minutes_back=30)
        
        logger.info(
            f"[CELERY] Auto-compact complete: "
            f"{stats['users_processed']} users, "
            f"{stats['blocks_created']} blocks created, "
            f"{stats['errors']} errors"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"[CELERY] Auto-compact failed: {e}", exc_info=True)
        raise


@shared_task(name='tracker.ai_classify_uncategorized_blocks')
def ai_classify_uncategorized_blocks(limit=100):
    """
    Run AI classification on uncategorized blocks.
    Runs every 5 minutes to learn patterns and auto-categorize.
    
    This ensures:
    1. AI learns from recent activity
    2. High-confidence blocks get auto-categorized
    3. Pattern learning happens continuously
    """
    try:
        from tracker.models import Block, Client
        from tracker.services.pattern_learning import PatternLearningService
        from django.contrib.auth import get_user_model
        import os
        
        User = get_user_model()
        
        # Only run if OpenAI key is configured
        if not os.getenv('OPENAI_API_KEY'):
            logger.warning("[CELERY] Skipping AI classification - no OpenAI key")
            return {'skipped': 'no_api_key'}
        
        # Get recent uncategorized blocks (last 24 hours)
        cutoff = timezone.now() - timedelta(hours=24)
        
        blocks = Block.objects.filter(
            is_categorized=False,
            start__gte=cutoff
        ).select_related('user', 'client', 'org').order_by('-start')[:limit]
        
        if not blocks:
            logger.info("[CELERY] No uncategorized blocks to classify")
            return {'blocks_processed': 0}
        
        logger.info(f"[CELERY] Found {len(blocks)} uncategorized blocks")
        
        stats = {
            'blocks_processed': 0,
            'auto_categorized': 0,
            'patterns_learned': 0,
            'errors': 0
        }
        
        # Process blocks by user to leverage patterns
        from collections import defaultdict
        by_user = defaultdict(list)
        
        for block in blocks:
            by_user[block.user_id].append(block)
        
        for user_id, user_blocks in by_user.items():
            try:
                user = User.objects.get(id=user_id)
                
                for block in user_blocks:
                    try:
                        # Check learned patterns first (fast path)
                        learned_patterns = PatternLearningService.get_patterns_for_block(block, user)
                        
                        if learned_patterns:
                            # Use highest confidence pattern
                            client_name, category, confidence = learned_patterns[0]
                            
                            if confidence >= 0.75:
                                # ✅ FIX: Client LOOKUP only — never create phantom clients
                                if client_name and not block.client:
                                    org = getattr(block, 'org', None)
                                    if org:
                                        try:
                                            client = Client.objects.get(
                                                org=org,
                                                name__iexact=client_name,
                                                is_active=True,
                                            )
                                            block.client = client
                                        except (Client.DoesNotExist, Client.MultipleObjectsReturned):
                                            pass  # Don't create phantom clients
                                
                                if category:
                                    block.category_hours = {category: round(block.minutes / 60.0, 2)}
                                    block.is_categorized = True
                                    block.categorized_at = timezone.now()
                                    block.categorized_by = 'pattern'
                                    block.save()
                                    
                                    stats['auto_categorized'] += 1
                                    stats['patterns_learned'] += 1
                                    
                                    logger.debug(
                                        f"[CELERY] Auto-categorized block {block.id} "
                                        f"→ {client_name or 'no client'} / {category} "
                                        f"({confidence:.2f})"
                                    )
                        
                        stats['blocks_processed'] += 1
                        
                    except Exception as e:
                        logger.error(f"[CELERY] Error processing block {block.id}: {e}")
                        stats['errors'] += 1
                        
            except User.DoesNotExist:
                logger.warning(f"[CELERY] User {user_id} not found")
                stats['errors'] += 1
        
        logger.info(
            f"[CELERY] AI classification complete: "
            f"{stats['blocks_processed']} blocks processed, "
            f"{stats['auto_categorized']} auto-categorized, "
            f"{stats['patterns_learned']} patterns applied, "
            f"{stats['errors']} errors"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"[CELERY] AI classification failed: {e}", exc_info=True)
        raise


@shared_task(name='tracker.cleanup_old_raw_events')
def cleanup_old_raw_events(days_to_keep=30):
    """
    Clean up old raw events to prevent database bloat.
    Runs daily at 2 AM.
    
    Raw events are kept for N days, then deleted since blocks
    are the source of truth for billing/reporting.
    """
    try:
        from tracker.models import RawEvent
        
        cutoff = timezone.now() - timedelta(days=days_to_keep)
        
        count = RawEvent.objects.filter(ts_utc__lt=cutoff).delete()[0]
        
        logger.info(f"[CELERY] Cleaned up {count} raw events older than {days_to_keep} days")
        
        return {'deleted': count}
        
    except Exception as e:
        logger.error(f"[CELERY] Cleanup failed: {e}", exc_info=True)
        raise


@shared_task(name='tracker.generate_daily_summary')
def generate_daily_summary(days_back=1):
    """
    Generate daily summary reports for all active users.
    Runs daily at 6 AM for yesterday's data.
    
    This pre-computes summaries for faster dashboard loading.
    """
    try:
        from tracker.models import Block
        from django.contrib.auth import get_user_model
        from collections import defaultdict
        
        User = get_user_model()
        
        target_date = (timezone.now() - timedelta(days=days_back)).date()
        
        # Get all blocks for target date
        blocks = Block.objects.filter(
            day=target_date,
            is_categorized=True
        ).select_related('user', 'client')
        
        # Group by user
        by_user = defaultdict(list)
        for block in blocks:
            by_user[block.user_id].append(block)
        
        summaries = []
        
        for user_id, user_blocks in by_user.items():
            try:
                user = User.objects.get(id=user_id)
                
                # Calculate totals
                total_minutes = sum(b.minutes for b in user_blocks if b.minutes)
                total_hours = round(total_minutes / 60.0, 2)
                
                # Group by client
                by_client = defaultdict(lambda: {'minutes': 0, 'categories': defaultdict(float)})
                
                for block in user_blocks:
                    client_name = block.client.name if block.client else 'Unassigned'
                    by_client[client_name]['minutes'] += block.minutes or 0
                    
                    if block.category_hours:
                        for cat, hours in block.category_hours.items():
                            by_client[client_name]['categories'][cat] += hours
                
                summary = {
                    'user': user.username,
                    'date': str(target_date),
                    'total_hours': total_hours,
                    'clients': [
                        {
                            'name': client_name,
                            'hours': round(data['minutes'] / 60.0, 2),
                            'categories': dict(data['categories'])
                        }
                        for client_name, data in by_client.items()
                    ]
                }
                
                summaries.append(summary)
                
            except User.DoesNotExist:
                pass
        
        logger.info(f"[CELERY] Generated {len(summaries)} daily summaries for {target_date}")
        
        return {
            'date': str(target_date),
            'summaries_generated': len(summaries)
        }
        
    except Exception as e:
        logger.error(f"[CELERY] Daily summary failed: {e}", exc_info=True)
        raise


# ============================================================================
# MANUAL BATCH PROCESSING (callable from shell/admin)
# ============================================================================

@shared_task(name='tracker.batch_classify_all')
def batch_classify_all(user_id=None, limit=500):
    """
    Manually trigger batch classification of ALL uncategorized blocks.
    
    This is useful for:
    - Initial backfill of historical data
    - Manually processing a backlog
    - Testing classification logic
    
    Args:
        user_id: Optional - only classify blocks for this user
        limit: Max blocks to process (default 500)
    
    Usage:
        from tracker.tasks import batch_classify_all
        batch_classify_all.delay(limit=500)
    """
    try:
        from tracker.models import Block
        from django.contrib.auth import get_user_model
        
        User = get_user_model()
        
        # Get uncategorized blocks
        qs = Block.objects.filter(is_categorized=False).order_by('-day', '-start')
        
        if user_id:
            qs = qs.filter(user_id=user_id)
        
        blocks = list(qs[:limit])
        
        if not blocks:
            logger.info("[BATCH] No uncategorized blocks found")
            return {"status": "complete", "processed": 0}
        
        logger.info(f"[BATCH] Processing {len(blocks)} uncategorized blocks")
        
        # Queue each block for individual classification
        for block in blocks:
            classify_block_task.delay(block.id)
        
        return {
            "status": "queued",
            "count": len(blocks),
            "message": f"Queued {len(blocks)} blocks for classification"
        }
        
    except Exception as e:
        logger.error(f"[BATCH] Failed: {e}", exc_info=True)
        raise

# ============================================================================
# ADD THIS TO tracker/tasks.py
# ============================================================================

@shared_task(name='tracker.push_time_to_quickbooks', bind=True)
def push_time_to_quickbooks(self, org_id, user_id, start_date, end_date, client_ids=None):
    """
    Background push of time entries to QuickBooks.
    Called from the push-time endpoint when dry_run=False.
    """
    from tracker.models import Organization, Block, OrganizationMembership, Integration
    from tracker.views_integrations import qb_api_call, get_integration_for_org, refresh_quickbooks_token
    from django.db.models import Q
    from datetime import datetime, timedelta
    from django.utils import timezone
    import logging

    logger = logging.getLogger('tracker.tasks')
    logger.info(f"[QBO-PUSH] Starting push for org={org_id}, dates={start_date} to {end_date}")

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return {'status': 'error', 'error': 'Organization not found'}

    # Get integration
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks', is_connected=True)
    except Integration.DoesNotExist:
        return {'status': 'error', 'error': 'QuickBooks not connected'}

    # Parse dates
    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()

    tz = timezone.get_current_timezone()
    start_aware = timezone.make_aware(datetime.combine(start_dt, datetime.min.time()), tz)
    end_aware = timezone.make_aware(datetime.combine(end_dt + timedelta(days=1), datetime.min.time()), tz)

    # Get blocks
    blocks_qs = Block.objects.filter(
        org=org,
        is_categorized=True,
        start__gte=start_aware,
        start__lt=end_aware,
        client__isnull=False,
        client__quickbooks_id__isnull=False,
    ).exclude(
        client__quickbooks_id=''
    ).filter(
        Q(qb_time_activity_id__isnull=True) | Q(qb_time_activity_id='')
    ).select_related('client', 'user')

    if client_ids:
        blocks_qs = blocks_qs.filter(client_id__in=client_ids)

    blocks = list(blocks_qs.order_by('start'))
    total = len(blocks)

    if not blocks:
        return {
            'status': 'complete',
            'pushed_count': 0,
            'error_count': 0,
            'total_hours': 0,
            'message': 'No entries to push',
        }

    # Pre-cache user → QBO employee mappings
    user_ids = set(b.user_id for b in blocks)
    memberships = {
        m.user_id: m.quickbooks_employee_id
        for m in OrganizationMembership.objects.filter(
            organization=org, user_id__in=user_ids
        )
        if m.quickbooks_employee_id
    }

    # Get default QBO employee
    default_emp_id = None
    try:
        emp_data, emp_err = qb_api_call(
            integration, 'GET', '/query',
            params={'query': 'SELECT Id FROM Employee MAXRESULTS 1', 'minorversion': '65'}
        )
        if emp_data and not emp_err:
            employees = emp_data.get('QueryResponse', {}).get('Employee', [])
            if employees:
                default_emp_id = employees[0].get('Id')
    except Exception:
        pass

    # Push entries one at a time, updating progress
    pushed = []
    errors = []

    for i, block in enumerate(blocks):
        # Update task progress for polling
        self.update_state(state='PROGRESS', meta={
            'current': i + 1,
            'total': total,
            'pushed': len(pushed),
            'errors': len(errors),
        })

        total_minutes = block.minutes or 0
        if total_minutes <= 0 and block.end and block.start:
            total_minutes = int((block.end - block.start).total_seconds() / 60)
        if total_minutes <= 0:
            continue

        hours = total_minutes // 60
        mins = total_minutes % 60

        cats = block.category_hours or {}
        cat_names = ', '.join(cats.keys()) if cats else 'General'
        description = cat_names
        if block.notes:
            description += f" — {block.notes}"

        block_date = timezone.localtime(block.start).strftime('%Y-%m-%d')

        payload = {
            'TxnDate': block_date,
            'NameOf': 'Employee',
            'Hours': hours,
            'Minutes': mins,
            'Description': description[:4000],
            'CustomerRef': {'value': block.client.quickbooks_id},
            'BillableStatus': 'Billable' if block.is_billable else 'NotBillable',
        }

        qb_emp_id = memberships.get(block.user_id) or default_emp_id
        if qb_emp_id:
            payload['EmployeeRef'] = {'value': str(qb_emp_id)}
        else:
            payload['NameOf'] = 'Vendor'

        try:
            data, err = qb_api_call(integration, 'POST', '/timeactivity', json=payload)
            if err:
                errors.append({'block_id': block.id, 'error': str(err)})
                continue

            qb_id = data.get('TimeActivity', {}).get('Id', '')
            if qb_id:
                Block.objects.filter(id=block.id).update(qb_time_activity_id=str(qb_id))

            pushed.append({
                'block_id': block.id,
                'client': block.client.name,
                'hours': round(total_minutes / 60, 2),
                'qb_id': qb_id,
            })
        except Exception as e:
            logger.error(f"[QBO-PUSH] Block {block.id} failed: {e}")
            errors.append({'block_id': block.id, 'error': str(e)})

    logger.info(f"[QBO-PUSH] Complete: {len(pushed)} pushed, {len(errors)} errors")

    return {
        'status': 'complete',
        'pushed_count': len(pushed),
        'error_count': len(errors),
        'total_hours': round(sum(p['hours'] for p in pushed), 2),
        'pushed': pushed,
        'errors': errors,
    }