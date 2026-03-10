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
    try:
        from tracker.models import Block, UserPreference, OrganizationMembership
        from django.contrib.auth import get_user_model

        User = get_user_model()
        yesterday = timezone.localdate() - timedelta(days=1)

        active_user_ids = OrganizationMembership.objects.values_list('user_id', flat=True)
        users_with_time = User.objects.filter(
            is_active=True,
            id__in=active_user_ids,
        ).exclude(email='').exclude(email__isnull=True).distinct()

        sent_count = 0
        skipped_count = 0
        errors = []

        for user in users_with_time:
            try:
                # Preference check
                try:
                    pref = UserPreference.objects.get(user=user)
                    if not getattr(pref, 'email_timesheet_reminders', True):
                        skipped_count += 1
                        continue
                except UserPreference.DoesNotExist:
                    pass

                blocks = Block.objects.filter(user=user, day=yesterday)
                total_minutes = sum(b.minutes or 0 for b in blocks)
                total_hours = total_minutes / 60

                unassigned_count = blocks.filter(client__isnull=True).count()

                client_hours = {}
                for block in blocks.filter(client__isnull=False):
                    name = block.client.name
                    hrs = (block.minutes or 0) / 60
                    client_hours[name] = client_hours.get(name, 0) + hrs

                client_breakdown = sorted(client_hours.items(), key=lambda x: x[1], reverse=True)[:5]

                user_name = user.first_name or user.username
                date_str = yesterday.strftime('%A, %b %d')

                from tracker.email_service import send_timesheet_reminder
                send_timesheet_reminder(
                    to_email=user.email,
                    user_name=user_name,
                    date_str=date_str,
                    total_hours=round(total_hours, 1),
                    unassigned_count=unassigned_count,
                    client_breakdown=client_breakdown,
                    date_iso=yesterday.isoformat(),  # ✅ add this so the link opens that day

                )

                sent_count += 1
                logger.info(f"[DAILY-REMINDER] Sent to {user.email}: {total_hours:.1f}h")

            except Exception as e:
                errors.append(f"{user.email}: {str(e)}")
                logger.error(f"[DAILY-REMINDER] Failed for {user.email}: {e}")

        logger.info(f"[DAILY-REMINDER] Complete: {sent_count} sent, {skipped_count} skipped, {len(errors)} errors")

        return {
            "date": yesterday.isoformat(),
            "sent": sent_count,
            "skipped": skipped_count,
            "errors": errors[:10],
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
                
                from tracker.email_service import send_weekly_summary_email
                send_weekly_summary_email(
                    to_email=user.email,
                    user_name=user_name,
                    week_str=week_str,
                    total_hours=total_hours,
                    client_breakdown=client_breakdown,
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
        
        from tracker.email_service import send_approval_notification
        send_approval_notification(
            to_email=user.email,
            user_name=user.first_name or user.username,
            period_str=period,
            status=status,
            total_hours=float(timesheet.total_hours),
            reviewer_notes=getattr(timesheet, 'reviewer_notes', '') or '',
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
                from tracker.email_service import send_submission_reminder
                send_submission_reminder(
                    to_email=user.email,
                    user_name=user.first_name or user.username,
                    week_start_str=last_monday.strftime("%b %d"),
                    week_end_str=last_sunday.strftime("%b %d, %Y"),
                    total_hours=total_hours,
                    block_count=block_count,
                    week_start_iso=last_monday.isoformat(),
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

            # Check if org has auto-submit enabled
            if not getattr(org, 'auto_submit_timesheets', False):
                skipped_empty += 1
                continue
            
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
                    from tracker.email_service import send_auto_submit_notification
                    send_auto_submit_notification(
                        to_email=user.email,
                        user_name=user.first_name or user.username,
                        week_start_str=last_monday.strftime("%b %d"),
                        week_end_str=last_sunday.strftime("%b %d, %Y"),
                        total_hours=timesheet.total_hours,
                        billable_hours=timesheet.billable_hours,
                        total_amount=timesheet.total_amount,
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
                from tracker.email_service import send_manager_pending_approvals
                send_manager_pending_approvals(
                    to_email=manager.email,
                    manager_name=manager.first_name or manager.username,
                    week_start_str=last_monday.strftime("%b %d"),
                    timesheet_count=len(timesheets),
                    total_hours=total_hours,
                    summary_lines=summary_lines,
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


"""
FIXED: ai_classify_uncategorized_blocks — NOW ACTUALLY CALLS OPENAI

Replace the existing ai_classify_uncategorized_blocks task in tracker/tasks.py
with this version.

WHAT WAS BROKEN:
- The old task only used PatternLearningService (keyword matching)
- It NEVER called OpenAI despite having the API key configured
- Result: $0 OpenAI bill for 1.5 months, blocks stuck uncategorized

WHAT THIS FIX DOES:
1. First tries pattern matching (fast, free) — same as before
2. Batches remaining uncategorized blocks by user/org
3. Sends batches to OpenAI using the SAME prompt system as ai_suggestions_today()
4. Auto-saves high-confidence results (>= 0.70)
5. Learns patterns from AI results for future fast-path matching

SCHEDULE: Every 5 minutes via Celery beat (already configured)
"""


@shared_task(name='tracker.ai_classify_uncategorized_blocks', bind=True, max_retries=2)
def ai_classify_uncategorized_blocks(self, limit=80):
    """
    Run AI classification on uncategorized blocks.
    Runs every 5 minutes via Celery beat.

    Pipeline:
      1. Pattern matching (free, fast) — handles ~60-70% of blocks
      2. OpenAI batch classification — handles the rest
      3. Learn patterns from AI results for future runs
    """
    import os
    import re
    import json
    from collections import defaultdict
    from datetime import timedelta

    from django.db import transaction

    logger = logging.getLogger(__name__)

    try:
        from tracker.models import Block, Client, OrganizationMembership
        from tracker.services.pattern_learning import PatternLearningService
        from tracker.industry_categories import (
            build_ai_prompt_for_industry,
            build_classification_user_prompt,
            validate_and_fix_ai_response,
        )
        from django.contrib.auth import get_user_model

        User = get_user_model()

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.warning("[AI-TASK] Skipping — OPENAI_API_KEY not set")
            return {'skipped': 'no_api_key'}

        # ==================================================================
        # STEP 1: Gather uncategorized blocks (last 24h)
        # ==================================================================
        cutoff = timezone.now() - timedelta(hours=24)

        blocks = list(
            Block.objects.filter(
                is_categorized=False,
                start__gte=cutoff,
                deleted_at__isnull=True,
            )
            .select_related('user', 'client', 'org')
            .order_by('-start')[:limit]
        )

        if not blocks:
            return {'blocks_found': 0, 'message': 'Nothing to classify'}

        logger.info(f"[AI-TASK] Found {len(blocks)} uncategorized blocks")

        stats = {
            'blocks_found': len(blocks),
            'pattern_classified': 0,
            'ai_classified': 0,
            'ai_failed': 0,
            'errors': 0,
        }

        # ==================================================================
        # STEP 2: Fast path — pattern matching (free)
        # ==================================================================
        still_need_ai = []

        for block in blocks:
            try:
                # Try learned patterns
                if block.user:
                    learned = PatternLearningService.get_patterns_for_block(block, block.user)
                    if learned:
                        client_name, category, confidence = learned[0]
                        if confidence >= 0.75 and category:
                            _apply_pattern_result(block, client_name, category, confidence)
                            stats['pattern_classified'] += 1
                            continue

                # Try compaction's auto_categorize (keyword matching)
                from tracker.services.compaction import auto_categorize_block
                if auto_categorize_block(block):
                    stats['pattern_classified'] += 1
                    continue

                # Not matched — needs AI
                still_need_ai.append(block)

            except Exception as e:
                logger.warning(f"[AI-TASK] Pattern check error on block {block.id}: {e}")
                still_need_ai.append(block)

        logger.info(
            f"[AI-TASK] Pattern pass: {stats['pattern_classified']} classified, "
            f"{len(still_need_ai)} still need AI"
        )

        if not still_need_ai:
            return stats

        # ==================================================================
        # STEP 3: Batch by org for AI classification
        # ==================================================================
        by_org = defaultdict(list)
        for block in still_need_ai:
            org_id = block.org_id or 0
            by_org[org_id].append(block)

        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=30.0)

        for org_id, org_blocks in by_org.items():
            try:
                org = org_blocks[0].org if org_blocks[0].org else None
                industry_type = getattr(org, 'industry_type', 'general') or 'general'

                # Build system prompt (categories, rules, seasonal context)
                system_msg = build_ai_prompt_for_industry(industry_type)

                # Add org context (clients, aliases, training examples)
                if org:
                    from tracker.views import build_ai_context
                    org_context = build_ai_context(org) or ""
                    if org_context:
                        system_msg += "\n\n=== ORGANIZATION CONTEXT ===\n" + org_context
                else:
                    org_context = ""

                # Format blocks for the prompt
                trimmed = []
                for b in org_blocks[:50]:  # Cap at 50 per org per run
                    minutes = b.minutes or 0
                    trimmed.append({
                        "id": str(b.id),
                        "title": _shorten(b.title, 160),
                        "window_title": _shorten(getattr(b, 'window_title', ''), 160),
                        "url": _shorten(b.url, 140),
                        "file_path": _shorten(b.file_path, 140),
                        "app_name": _shorten(getattr(b, 'app_name', ''), 80),
                        "bundle_id": _shorten(getattr(b, 'bundle_id', ''), 100),
                        "minutes": minutes,
                        "hints": getattr(b, 'hints', {}) or {},
                        "assigned_client": getattr(b.client, "name", None),
                    })

                user_prompt = build_classification_user_prompt(trimmed, org_context)

                # Choose model/tokens based on batch size
                max_tokens = 1000 if len(trimmed) <= 3 else 4000

                # ==============================================================
                # THE ACTUAL OPENAI CALL
                # ==============================================================
                logger.info(
                    f"[AI-TASK] Calling OpenAI for org {org_id}: "
                    f"{len(trimmed)} blocks, industry={industry_type}"
                )

                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    max_tokens=max_tokens,
                )

                raw_text = (resp.choices[0].message.content or "").strip()
                raw_json = _extract_json(raw_text)
                ai_results = _json_loads_loose(raw_json)

                if not isinstance(ai_results, list):
                    raise ValueError("OpenAI did not return a JSON array")

                # Validate/fix category names
                ai_results = validate_and_fix_ai_response(ai_results, industry_type)

                logger.info(
                    f"[AI-TASK] OpenAI returned {len(ai_results)} results "
                    f"for {len(trimmed)} blocks"
                )

                # ==============================================================
                # STEP 4: Save results
                # ==============================================================
                n = min(len(org_blocks), len(ai_results))

                with transaction.atomic():
                    for i in range(n):
                        block = org_blocks[i]
                        sug = ai_results[i] if isinstance(ai_results[i], dict) else {}

                        confidence = float(sug.get("confidence", 0.0))
                        categories = sug.get("categories", {})

                        if confidence < 0.70 or not categories:
                            continue  # Leave for manual review

                        try:
                            fresh = Block.objects.select_for_update().get(id=block.id)
                            if fresh.is_categorized:
                                continue  # Race condition — already done

                            # Client correction (lookup only, never create)
                            suggested_client = (sug.get("client") or "").strip()
                            if suggested_client and not fresh.client and org:
                                try:
                                    correct_client = Client.objects.get(
                                        org=org,
                                        name__iexact=suggested_client,
                                        is_active=True,
                                    )
                                    fresh.client = correct_client
                                except (Client.DoesNotExist, Client.MultipleObjectsReturned):
                                    pass

                            # Save categories
                            clean_cats = {}
                            for k, v in categories.items():
                                try:
                                    clean_cats[str(k)] = float(v)
                                except (ValueError, TypeError):
                                    pass

                            if not clean_cats:
                                continue

                            # ✅ Normalize category_hours to actual block duration
                            actual_hours = round((fresh.minutes or 0) / 60.0, 2)
                            cat_total = sum(clean_cats.values())
                            if cat_total > 0 and actual_hours > 0:
                                ratio = actual_hours / cat_total
                                clean_cats = {k: round(v * ratio, 2) for k, v in clean_cats.items()}
                            elif actual_hours > 0 and len(clean_cats) > 0:
                                per_cat = round(actual_hours / len(clean_cats), 2)
                                clean_cats = {k: per_cat for k in clean_cats}

                            fresh.category_hours = clean_cats
                            fresh.ai_category = list(clean_cats.keys())[0]
                            fresh.is_categorized = True
                            fresh.categorized_at = timezone.now()
                            fresh.categorized_by = 'ai'
                            fresh.ai_processed_at = timezone.now()
                            fresh.ai_confidence = confidence
                            fresh.save()

                            stats['ai_classified'] += 1

                            logger.debug(
                                f"[AI-TASK] ✅ Block {block.id} → "
                                f"{suggested_client or 'no client'} / "
                                f"{list(clean_cats.keys())} ({confidence:.2f})"
                            )

                            # Learn from this classification
                            if fresh.user:
                                try:
                                    PatternLearningService.learn_from_block(fresh, fresh.user)
                                except Exception:
                                    pass

                        except Block.DoesNotExist:
                            pass
                        except Exception as e:
                            logger.error(f"[AI-TASK] Save error block {block.id}: {e}")
                            stats['errors'] += 1

            except Exception as e:
                logger.error(
                    f"[AI-TASK] OpenAI batch failed for org {org_id}: {e}",
                    exc_info=True
                )
                stats['ai_failed'] += len(org_blocks)

        logger.info(
            f"[AI-TASK] Complete: "
            f"pattern={stats['pattern_classified']}, "
            f"ai={stats['ai_classified']}, "
            f"failed={stats['ai_failed']}, "
            f"errors={stats['errors']}"
        )

        return stats

    except Exception as exc:
        logger.error(f"[AI-TASK] Task failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=120)


# ==================================================================
# HELPER FUNCTIONS (used by the task above)
# ==================================================================

def _apply_pattern_result(block, client_name, category, confidence):
    """Apply a pattern-match result to a block."""
    from tracker.models import Client
    from django.utils import timezone

    if client_name and not block.client:
        org = getattr(block, 'org', None)
        if org:
            try:
                client_obj = Client.objects.get(
                    org=org, name__iexact=client_name, is_active=True
                )
                block.client = client_obj
            except (Client.DoesNotExist, Client.MultipleObjectsReturned):
                pass

    if category:
        hours = round((block.minutes or 1) / 60.0, 2)
        block.category_hours = {category: hours}
        block.is_categorized = True
        block.categorized_at = timezone.now()
        block.categorized_by = 'pattern'
        block.ai_confidence = confidence
        block.save()


def _shorten(s, n=180):
    s = (s or "").strip()
    return s[:n] + ("…" if len(s) > n else "")


def _extract_json(s):
    """Extract JSON array from potentially markdown-wrapped response."""
    import re

    s = s.strip()
    if s.startswith("```"):
        parts = s.split("```")
        if len(parts) >= 3:
            s = parts[1]
            if s.lower().startswith("json"):
                s = s[4:].lstrip()

    m = re.search(r'\[\s*{', s)
    if m:
        start = m.start()
        depth, i = 0, start
        while i < len(s):
            if s[i] == '[':
                depth += 1
            elif s[i] == ']':
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
            i += 1
    return s


def _json_loads_loose(raw):
    """Parse JSON with tolerance for trailing commas."""
    import json
    import re

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raw2 = re.sub(r',\s*([}\]])', r'\1', raw)
        return json.loads(raw2)


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
    from tracker.views_integrations import qb_api_call
    from django.db.models import Q
    from datetime import datetime, timedelta
    from django.utils import timezone

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
    # Push entries one at a time, updating progress
    pushed = []
    errors = []
    consecutive_errors = 0

    for i, block in enumerate(blocks):
        # Update task progress for polling
        self.update_state(state='PROGRESS', meta={
            'current': i + 1,
            'total': total,
            'pushed': len(pushed),
            'errors': len(errors),
        })

        # Bail early if 3+ consecutive failures (auth is broken)
        if consecutive_errors >= 3:
            for b in blocks[i:]:
                errors.append({'block_id': b.id, 'error': 'Skipped — auth failed'})
            logger.error(f"[QBO-PUSH] Bailing after {consecutive_errors} consecutive errors")
            break

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
                consecutive_errors += 1
                continue

            consecutive_errors = 0  # Reset on success

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
            consecutive_errors += 1

    logger.info(f"[QBO-PUSH] Complete: {len(pushed)} pushed, {len(errors)} errors")

    return {
        'status': 'complete',
        'pushed_count': len(pushed),
        'error_count': len(errors),
        'total_hours': round(sum(p['hours'] for p in pushed), 2),
        'pushed': pushed,
        'errors': errors,
    }


@shared_task(name='tracker.refresh_integration_tokens')
def refresh_integration_tokens():
    """
    Proactively refresh OAuth tokens expiring within 15 minutes.
    Runs every 45 min to prevent mid-request token expiration.
    """
    from tracker.models import Integration
    from tracker.views_integrations import refresh_quickbooks_token, refresh_xero_token
    from django.utils import timezone
    from datetime import timedelta

    logger = logging.getLogger('tracker.tasks')
    threshold = timezone.now() + timedelta(minutes=15)

    integrations = Integration.objects.filter(
        is_connected=True,
        token_expires_at__lt=threshold,
    )

    refreshed = 0
    failed = 0

    for integration in integrations:
        if integration.provider == 'quickbooks':
            success = refresh_quickbooks_token(integration)
        elif integration.provider == 'xero':
            success = refresh_xero_token(integration)
        else:
            continue

        if success:
            refreshed += 1
            logger.info(f"[TOKEN-REFRESH] Refreshed {integration.provider} for org {integration.organization_id}")
        else:
            failed += 1
            logger.error(f"[TOKEN-REFRESH] Failed {integration.provider} for org {integration.organization_id}")
            # TODO: Send email to org owner to reconnect

    logger.info(f"[TOKEN-REFRESH] Done: {refreshed} refreshed, {failed} failed")
    return {'refreshed': refreshed, 'failed': failed}


@shared_task(name='tracker.check_payment_grace_periods')
def check_payment_grace_periods():
    """Deactivate devices for orgs past their payment grace deadline."""
    from tracker.models import Organization, AgentDevice, OrganizationMembership
    
    now = timezone.now()
    expired_orgs = Organization.objects.filter(
        payment_grace_deadline__isnull=False,
        payment_grace_deadline__lte=now,
    )
    
    total_deactivated = 0
    for org in expired_orgs:
        org_user_ids = OrganizationMembership.objects.filter(
            organization=org
        ).values_list('user_id', flat=True)
        
        deactivated = AgentDevice.objects.filter(
            user_id__in=org_user_ids, is_active=True
        ).update(is_active=False)
        
        total_deactivated += deactivated
        
        org.plan = 'none'
        org.seat_count = 0
        org.payment_grace_deadline = None
        org.save(update_fields=['plan', 'seat_count', 'payment_grace_deadline'])
        
        logger.info(f"[GRACE] Expired for {org.name}, deactivated {deactivated} devices")
    
    return {'expired_orgs': expired_orgs.count(), 'devices_deactivated': total_deactivated}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def sync_single_qb_invoice(self, realm_id, invoice_id, operation):
    """
    Targeted sync of a single QB invoice triggered by webhook.
    Much cheaper than a full pull — fetches one invoice by ID.
    """
    from tracker.models import Integration, Invoice as InvoiceModel, Client, InvoiceConflict
    from tracker.views_integrations import qb_api_call, refresh_quickbooks_token

    try:
        integration = Integration.objects.get(
            realm_id=realm_id,
            provider='quickbooks',
            is_connected=True,
        )
    except Integration.DoesNotExist:
        logger.warning(f"QB webhook: no connected integration for realm {realm_id}")
        return

    org = integration.organization

    # Handle deletes/voids
    if operation in ('Delete', 'Void'):
        updated = InvoiceModel.objects.filter(
            org=org, external_id=invoice_id
        ).update(status='voided')
        logger.info(f"QB webhook: marked invoice {invoice_id} as voided ({updated} rows)")
        return

    # Fetch the single invoice
    data, err = qb_api_call(integration, 'GET', f'/invoice/{invoice_id}')
    if err:
        logger.error(f"QB webhook: failed to fetch invoice {invoice_id}: {err}")
        try:
            raise self.retry()
        except self.MaxRetriesExceededError:
            pass
        return

    inv = data.get('Invoice', {})
    if not inv:
        return

    qb_customer_id = inv.get('CustomerRef', {}).get('value')
    client = Client.objects.filter(org=org, quickbooks_id=qb_customer_id).first()
    if not client:
        logger.info(f"QB webhook: invoice {invoice_id} — no matching TT client for QB customer {qb_customer_id}")
        return  # Will surface in unmatched invoice queue

    total = Decimal(str(inv.get('TotalAmt', 0)))
    balance = Decimal(str(inv.get('Balance', 0)))
    doc_number = inv.get('DocNumber') or f"QBO-{invoice_id}"
    inv_date = inv.get('TxnDate', str(date.today()))

    # Conflict detection — don't silently overwrite an existing amount change
    existing = InvoiceModel.objects.filter(org=org, external_id=str(invoice_id)).first()
    if existing and existing.amount != total and existing.status not in ('voided',):
        InvoiceConflict.objects.update_or_create(
            org=org,
            invoice=existing,
            defaults={
                'tt_amount': existing.amount,
                'source_amount': total,
                'source': 'quickbooks',
                'detected_at': timezone.now(),
                'resolved': False,
            }
        )
        logger.info(f"QB webhook: conflict flagged on invoice {doc_number} — ${existing.amount} → ${total}")
        return  # Hold for user review

    InvoiceModel.objects.update_or_create(
        org=org,
        external_id=str(invoice_id),
        defaults={
            'invoice_number': doc_number,
            'client': client,
            'client_name': client.name,
            'invoice_date': inv_date,
            'amount': total,
            'status': 'paid' if balance == 0 else 'sent',
            'source': 'quickbooks',
            'hours_billed': None,
        }
    )

    # Update sync timestamp
    integration.last_synced_at = timezone.now()
    integration.save(update_fields=['last_synced_at'])
    logger.info(f"QB webhook: synced invoice {doc_number} for {client.name}")


@shared_task
def reconcile_qb_invoices():
    """
    Fallback reconciliation — catches any invoices missed by webhook.
    Runs every 4 hours. Much cheaper than the old poll-only approach.
    """
    from tracker.models import Integration, Organization
    from tracker.views_integrations import quickbooks_pull_invoices
    from datetime import date, timedelta

    integrations = Integration.objects.filter(
        provider='quickbooks',
        is_connected=True,
    ).select_related('organization')

    for integration in integrations:
        try:
            # Pull last 7 days as a rolling window
            end = date.today().isoformat()
            start = (date.today() - timedelta(days=7)).isoformat()
            
            from tracker.views_integrations import qb_api_call
            query = (
                f"SELECT * FROM Invoice WHERE TxnDate >= '{start}' "
                f"AND TxnDate <= '{end}' ORDERBY TxnDate MAXRESULTS 1000"
            )
            data, err = qb_api_call(integration, 'GET', '/query', params={'query': query})
            if err:
                continue

            invoices = data.get('QueryResponse', {}).get('Invoice', [])
            logger.info(f"QB reconcile: {len(invoices)} invoices for org {integration.organization_id}")

            # Reuse your existing upsert logic
            from tracker.models import Invoice as InvoiceModel, Client
            from decimal import Decimal

            qb_map = {c.quickbooks_id: c for c in Client.objects.filter(
                org=integration.organization, quickbooks_id__isnull=False
            )}

            for inv in invoices:
                qb_customer_id = inv.get('CustomerRef', {}).get('value')
                client = qb_map.get(qb_customer_id)
                if not client:
                    continue

                total = Decimal(str(inv.get('TotalAmt', 0)))
                balance = Decimal(str(inv.get('Balance', 0)))
                doc_number = inv.get('DocNumber') or f"QBO-{inv.get('Id')}"

                InvoiceModel.objects.update_or_create(
                    org=integration.organization,
                    external_id=str(inv.get('Id')),
                    defaults={
                        'invoice_number': doc_number,
                        'client': client,
                        'client_name': client.name,
                        'invoice_date': inv.get('TxnDate', end),
                        'amount': total,
                        'status': 'paid' if balance == 0 else 'sent',
                        'source': 'quickbooks',
                        'hours_billed': None,
                    }
                )

            integration.last_synced_at = timezone.now()
            integration.save(update_fields=['last_synced_at'])

        except Exception as e:
            logger.error(f"QB reconcile failed for org {integration.organization_id}: {e}")