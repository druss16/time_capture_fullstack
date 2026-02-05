# ============================================================================
# tracker/views_notifications.py
# Timesheet Review Notification Endpoints + Email Service
# ============================================================================

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.db.models.functions import Coalesce
from datetime import timedelta, date, datetime
from decimal import Decimal


# ============================================================================
# HELPER: Check if a date falls within a submitted/approved timesheet week
# ============================================================================

def _get_week_start(d):
    """Get Monday of the week containing date d."""
    return d - timedelta(days=d.weekday())


def _is_date_submitted(user, check_date, Timesheet):
    """Check if a date falls in a submitted/approved timesheet week."""
    week_start = _get_week_start(check_date)
    return Timesheet.objects.filter(
        user=user,
        week_start=week_start,
        status__in=['submitted', 'approved']
    ).exists()


def _get_submitted_weeks(user, Timesheet):
    """Get set of week_start dates that are submitted/approved."""
    return set(
        Timesheet.objects.filter(
            user=user,
            status__in=['submitted', 'approved']
        ).values_list('week_start', flat=True)
    )


# ============================================================================
# API ENDPOINTS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def timesheet_needs_review(request):
    """
    Check if user has unreviewed hours from recent days.
    Returns up to 5 days of unreviewed time.
    
    Returns:
    - needs_review: bool
    - days: list of days needing review
    - total_unreviewed_hours: total across all days
    - total_unassigned: total unassigned blocks
    """
    from .models import Block, Timesheet, UserPreference
    
    user = request.user
    today = timezone.localdate()
    
    # Check last 5 work days (excluding today)
    days_to_check = []
    check_date = today - timedelta(days=1)
    
    for _ in range(7):  # Go back up to 7 days to find 5 work days
        if len(days_to_check) >= 5:
            break
        days_to_check.append(check_date)
        check_date -= timedelta(days=1)
    
    # Get all submitted/approved week_start dates for this user
    submitted_weeks = _get_submitted_weeks(user, Timesheet)
    
    def is_submitted(d):
        week_start = _get_week_start(d)
        return week_start in submitted_weeks
    
    # Check each day
    unreviewed_days = []
    total_hours = 0
    total_unassigned = 0
    
    for check_date in days_to_check:
        if is_submitted(check_date):
            continue
        
        blocks = Block.objects.filter(user=user, day=check_date)
        
        if not blocks.exists():
            continue
        
        # Calculate stats
        day_minutes = sum(b.minutes or 0 for b in blocks)
        day_hours = day_minutes / 60
        
        if day_hours < 0.25:  # Skip if less than 15 min
            continue
        
        unassigned_blocks = blocks.filter(client__isnull=True)
        unassigned_count = unassigned_blocks.count()
        
        # Get top clients
        client_hours = {}
        for block in blocks.filter(client__isnull=False):
            client_name = block.client.name
            hrs = (block.minutes or 0) / 60
            client_hours[client_name] = client_hours.get(client_name, 0) + hrs
        
        top_clients = sorted(
            [{'name': k, 'hours': v} for k, v in client_hours.items()],
            key=lambda x: x['hours'],
            reverse=True
        )[:3]
        
        # Day name formatting
        if check_date == today - timedelta(days=1):
            day_name = 'Yesterday'
        elif check_date == today - timedelta(days=2):
            day_name = '2 days ago'
        else:
            day_name = check_date.strftime('%A, %b %d')
        
        unreviewed_days.append({
            'date': check_date.isoformat(),
            'day_name': day_name,
            'total_hours': round(day_hours, 2),
            'block_count': blocks.count(),
            'has_unassigned': unassigned_count > 0,
            'unassigned_count': unassigned_count,
            'top_clients': top_clients,
        })
        
        total_hours += day_hours
        total_unassigned += unassigned_count
    
    return Response({
        'needs_review': len(unreviewed_days) > 0,
        'days': unreviewed_days,
        'total_unreviewed_hours': round(total_hours, 2),
        'total_unassigned': total_unassigned,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def dismiss_timesheet_reminder(request):
    """
    Mark that user has dismissed the reminder for today.
    """
    from .models import UserPreference
    
    dismissed_date = request.data.get('date')
    if not dismissed_date:
        dismissed_date = timezone.localdate().isoformat()
    
    # Store in user preferences
    pref, _ = UserPreference.objects.get_or_create(user=request.user)
    pref.last_timesheet_reminder_dismissed = dismissed_date
    pref.save(update_fields=['last_timesheet_reminder_dismissed'])
    
    return Response({'success': True, 'dismissed_date': dismissed_date})


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def notification_preferences(request):
    """
    GET/PUT user notification preferences
    """
    from .models import UserPreference
    
    pref, _ = UserPreference.objects.get_or_create(user=request.user)
    
    if request.method == 'GET':
        return Response({
            'email_timesheet_reminders': getattr(pref, 'email_timesheet_reminders', True),
            'email_weekly_summary': getattr(pref, 'email_weekly_summary', True),
            'email_approval_notifications': getattr(pref, 'email_approval_notifications', True),
            'desktop_notifications': getattr(pref, 'desktop_notifications', True),
            'reminder_time': getattr(pref, 'reminder_time', '09:00'),
        })
    
    elif request.method == 'PUT':
        if 'email_timesheet_reminders' in request.data:
            pref.email_timesheet_reminders = request.data['email_timesheet_reminders']
        if 'email_weekly_summary' in request.data:
            pref.email_weekly_summary = request.data['email_weekly_summary']
        if 'email_approval_notifications' in request.data:
            pref.email_approval_notifications = request.data['email_approval_notifications']
        if 'desktop_notifications' in request.data:
            pref.desktop_notifications = request.data['desktop_notifications']
        if 'reminder_time' in request.data:
            pref.reminder_time = request.data['reminder_time']
        
        pref.save()
        
        return Response({'success': True})


# ============================================================================
# DESKTOP AGENT NOTIFICATION ENDPOINT
# Called by the desktop agent on startup
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_startup_notification(request):
    """
    Called by desktop agent on startup to check if there are
    pending timesheet reviews. Returns notification data if needed.
    """
    from .models import Block, Timesheet, UserPreference
    
    user = request.user
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    
    # Check user preference
    try:
        pref = UserPreference.objects.get(user=user)
        if not getattr(pref, 'desktop_notifications', True):
            return Response({'show_notification': False})
    except UserPreference.DoesNotExist:
        pass
    
    # Check yesterday's blocks
    blocks = Block.objects.filter(user=user, day=yesterday)
    
    if not blocks.exists():
        return Response({'show_notification': False})
    
    # Check if yesterday's week is already submitted
    if _is_date_submitted(user, yesterday, Timesheet):
        return Response({'show_notification': False})
    
    # Calculate stats
    total_minutes = sum(b.minutes or 0 for b in blocks)
    total_hours = total_minutes / 60
    
    if total_hours < 0.5:
        return Response({'show_notification': False})
    
    unassigned_count = blocks.filter(client__isnull=True).count()
    
    return Response({
        'show_notification': True,
        'title': '⏰ Review Your Timesheet',
        'message': f'You have {total_hours:.1f} hours from yesterday to review.',
        'subtitle': f'{unassigned_count} blocks need client assignment' if unassigned_count else None,
        'url': f'/daily?date={yesterday.isoformat()}',
        'date': yesterday.isoformat(),
        'hours': round(total_hours, 1),
        'unassigned': unassigned_count,
    })


# ============================================================================
# EMAIL SERVICE - Daily Digest
# ============================================================================

def send_daily_timesheet_reminders():
    """
    Send email reminders to users who have unreviewed time from yesterday.
    Call this from a scheduled task (Celery beat, cron, etc.) at 9am.
    
    Returns: dict with 'sent' count and 'errors' list
    """
    from django.core.mail import send_mail
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from .models import Block, Timesheet, UserPreference
    
    User = get_user_model()
    yesterday = timezone.localdate() - timedelta(days=1)
    
    # Get all users with time tracked yesterday
    users_with_time = User.objects.filter(
        blocks__day=yesterday
    ).distinct()
    
    sent_count = 0
    errors = []
    
    for user in users_with_time:
        try:
            # Skip if no email
            if not user.email:
                continue
            
            # Check user preference
            try:
                pref = UserPreference.objects.get(user=user)
                if not getattr(pref, 'email_timesheet_reminders', True):
                    continue
            except UserPreference.DoesNotExist:
                pass  # Default to sending
            
            # Skip if yesterday's week is already submitted
            if _is_date_submitted(user, yesterday, Timesheet):
                continue
            
            # Get their blocks
            blocks = Block.objects.filter(user=user, day=yesterday)
            total_minutes = sum(b.minutes or 0 for b in blocks)
            total_hours = total_minutes / 60
            
            if total_hours < 0.5:
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
            frontend_url = getattr(settings, 'FRONTEND_URL', 'https://app.timetracker.com')
            review_url = f'{frontend_url}/timesheet?date={yesterday.isoformat()}'
            
            # Plain text version
            client_lines = '\n'.join([f'  • {name}: {hrs:.1f}h' for name, hrs in client_breakdown])
            if not client_lines:
                client_lines = '  • No clients assigned yet'
            
            unassigned_warning = f'\n⚠️ {unassigned_count} blocks need client assignment.\n' if unassigned_count else ''
            
            plain_message = f"""Hi {user_name},

You tracked {total_hours:.1f} hours on {date_str} that need review:

{client_lines}
{unassigned_warning}
Review your timesheet: {review_url}

—
TimeTracker

Manage notification preferences: {frontend_url}/settings"""
            
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
            
            html_message = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <div style="max-width: 500px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%); padding: 24px; border-radius: 16px 16px 0 0; text-align: center;">
            <h1 style="margin: 0; color: white; font-size: 24px;">⏰ Timesheet Reminder</h1>
        </div>
        <div style="background: white; padding: 24px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
            <p style="color: #475569; font-size: 16px; line-height: 1.5; margin-top: 0;">
                Hi {user_name},
            </p>
            <p style="color: #475569; font-size: 16px; line-height: 1.5;">
                You tracked <strong style="color: #ea580c;">{total_hours:.1f} hours</strong> on {date_str} that need review:
            </p>
            <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                {client_rows}
            </table>
            {unassigned_html}
            <div style="text-align: center; margin: 24px 0;">
                <a href="{review_url}" 
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
</html>'''
            
            send_mail(
                subject=f'⏰ Review your timesheet for {date_str}',
                message=plain_message,
                from_email=f'TimeTracker <{settings.DEFAULT_FROM_EMAIL}>',
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            sent_count += 1
            
        except Exception as e:
            errors.append(f'{user.email}: {str(e)}')
    
    return {
        'sent': sent_count,
        'errors': errors,
    }


def send_weekly_summary():
    """
    Send weekly summary email every Monday morning.
    Shows last week's time breakdown by client.
    """
    from django.core.mail import send_mail
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from .models import Block, UserPreference
    
    User = get_user_model()
    today = timezone.localdate()
    
    # Last week = Monday to Sunday
    days_since_monday = today.weekday()  # Monday = 0
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)
    
    # Get all active users
    users = User.objects.filter(is_active=True)
    
    sent_count = 0
    
    for user in users:
        try:
            if not user.email:
                continue
            
            # Check preference
            try:
                pref = UserPreference.objects.get(user=user)
                if not getattr(pref, 'email_weekly_summary', True):
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
                continue
            
            # Calculate totals
            total_minutes = sum(b.minutes or 0 for b in blocks)
            total_hours = total_minutes / 60
            
            if total_hours < 1:
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
            
            user_name = user.first_name or user.username
            week_str = f"{last_monday.strftime('%b %d')} - {last_sunday.strftime('%b %d')}"
            frontend_url = getattr(settings, 'FRONTEND_URL', 'https://app.timetracker.com')
            
            # Build email
            client_lines = '\n'.join([f'  • {name}: {hrs:.1f}h' for name, hrs in client_breakdown[:10]])
            
            plain_message = f"""Hi {user_name},

Here's your weekly time summary for {week_str}:

Total: {total_hours:.1f} hours

By Client:
{client_lines}

View detailed report: {frontend_url}/reports

—
TimeTracker"""
            
            send_mail(
                subject=f'📊 Your weekly summary: {total_hours:.1f} hours tracked',
                message=plain_message,
                from_email=f'TimeTracker <{settings.DEFAULT_FROM_EMAIL}>',
                recipient_list=[user.email],
                fail_silently=False,
            )
            
            sent_count += 1
            
        except Exception as e:
            print(f'Failed to send weekly summary to {user.email}: {e}')
    
    return sent_count