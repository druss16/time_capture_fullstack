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
    
    # Calculate BILLABLE hours only (exclude idle/uncategorized)
    total_minutes = 0
    billable_minutes = 0
    for b in blocks:
        minutes = b.minutes or 0
        total_minutes += minutes
        
        category = (b.ai_category or '').lower()        # Skip non-billable categories
        if 'idle' in category or 'uncategorized' in category:
            continue
        billable_minutes += minutes
    
    billable_hours = billable_minutes / 60
    
    # Only notify if meaningful billable hours
    if billable_hours < 0.5:
        return Response({'show_notification': False})
    
    unassigned_count = blocks.filter(client__isnull=True).exclude(
        ai_category__icontains='idle'
    ).exclude(
        ai_category__icontains='uncategorized'
    ).count()
    
    return Response({
        'show_notification': True,
        'title': '⏰ Review Your Timesheet',
        'message': f'You have {billable_hours:.1f} billable hours from yesterday to review.',
        'subtitle': f'{unassigned_count} blocks need client assignment' if unassigned_count else None,
        'url': f'/daily?date={yesterday.isoformat()}',
        'date': yesterday.isoformat(),
        'hours': round(billable_hours, 1),
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
            
            from tracker.email_service import send_timesheet_reminder
            send_timesheet_reminder(
                to_email=user.email,
                user_name=user_name,
                date_str=date_str,
                total_hours=total_hours,
                client_breakdown=client_breakdown,
                unassigned_count=unassigned_count,
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
            
            
            from tracker.email_service import send_weekly_summary_email
            send_weekly_summary_email(
                to_email=user.email,
                user_name=user_name,
                week_str=week_str,
                total_hours=total_hours,
                client_breakdown=client_breakdown,
            )
            
            sent_count += 1
            
        except Exception as e:
            print(f'Failed to send weekly summary to {user.email}: {e}')
    
    return sent_count