# tracker/tasks.py
"""
Celery background tasks for TimeTracker:
1. Auto-compact recent events every 10 minutes
2. Run AI classification on uncategorized blocks
3. Clean up old raw events
4. Timesheet reminders (Monday 9am)
5. Timesheet auto-submit (Tuesday 9am)
6. Weekly timesheet creation (Monday 1am)
"""

from celery import shared_task
from django.utils import timezone
from django.db.models import Sum
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# TIMESHEET WORKFLOW TASKS
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
        from tracker.models import Block
        from tracker.views import pre_classify_obvious_categories
        from tracker.services.pattern_learning import PatternLearningService
        
        # Get block
        try:
            block = Block.objects.select_related('client', 'user').get(id=block_id)
        except Block.DoesNotExist:
            logger.warning(f"[CLASSIFY] Block {block_id} not found")
            return {"status": "not_found", "block_id": block_id}
        
        # Skip if already categorized
        if block.is_categorized:
            return {"status": "already_categorized", "block_id": block_id}
        
        # Step 1: Try obvious patterns (CPA tools, meetings, email)
        pre_class = pre_classify_obvious_categories(block)
        
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
                    # Apply learned pattern
                    if client_name and not block.client:
                        from tracker.models import Client
                        org = block.user.groups.first()
                        if org:
                            try:
                                client, _ = Client.objects.get_or_create(
                                    org=org,
                                    name=client_name,
                                    defaults={'is_active': True}
                                )
                                block.client = client
                            except Exception:
                                pass
                    
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
    Runs every 10 minutes via Celery beat.
    
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
    Runs every 15 minutes to learn patterns and auto-categorize.
    
    This ensures:
    1. AI learns from recent activity
    2. High-confidence blocks get auto-categorized
    3. Pattern learning happens continuously
    """
    try:
        from tracker.models import Block
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
        ).select_related('user', 'client').order_by('-start')[:limit]
        
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
                                # Auto-apply pattern
                                if client_name and not block.client:
                                    from tracker.models import Client
                                    try:
                                        client = Client.objects.get(
                                            org=user.groups.first(),
                                            name=client_name
                                        )
                                        block.client = client
                                    except Client.DoesNotExist:
                                        pass
                                
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