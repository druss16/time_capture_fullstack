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
from decimal import Decimal
from datetime import date


logger = logging.getLogger(__name__)


# ============================================================================
# DAILY NOTIFICATION TASKS
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
                    date_iso=yesterday.isoformat(),
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

        users = User.objects.filter(is_active=True)

        sent_count = 0
        skipped_count = 0

        for user in users:
            try:
                if not user.email:
                    skipped_count += 1
                    continue

                try:
                    pref = UserPreference.objects.get(user=user)
                    if not getattr(pref, 'email_weekly_summary', True):
                        skipped_count += 1
                        continue
                except UserPreference.DoesNotExist:
                    pass

                blocks = Block.objects.filter(
                    user=user,
                    day__gte=last_monday,
                    day__lte=last_sunday,
                )

                if not blocks.exists():
                    skipped_count += 1
                    continue

                total_minutes = sum(b.minutes or 0 for b in blocks)
                total_hours = total_minutes / 60

                if total_hours < 1:
                    skipped_count += 1
                    continue

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

        week_ago = (timezone.localdate() - timedelta(days=7)).isoformat()

        updated = UserPreference.objects.filter(
            last_timesheet_reminder_dismissed__lt=week_ago
        ).update(last_timesheet_reminder_dismissed=None)

        logger.info(f"[CLEANUP] Cleared {updated} old notification dismissals")

        return {'cleaned': updated}

    except Exception as e:
        logger.error(f"[CLEANUP] Notification dismissal cleanup failed: {e}")
        return {'error': str(e)}


@shared_task(name='tracker.tasks.notify_timesheet_submitted')
def notify_timesheet_submitted(timesheet_id: int):
    """Tell the approvers a week is waiting on them.

    A scheduled digest already existed, but it runs Tuesday morning: someone who
    submitted on Friday sat invisible for four days, and the submitter had no
    way to tell whether anyone had been told. This fires on the transition.
    """
    from tracker.models import Timesheet, OrganizationMembership
    from tracker.email_service import send_manager_pending_approvals

    try:
        ts = Timesheet.objects.select_related('user', 'org').get(id=timesheet_id)
    except Timesheet.DoesNotExist:
        return {'error': 'not_found'}

    if ts.status != 'submitted':
        return {'skipped': 'no longer submitted'}

    who = f"{ts.user.first_name} {ts.user.last_name}".strip() or ts.user.username
    week_str = ts.week_start.strftime('%b %d')
    hours = float(ts.total_hours or 0)

    approvers = (
        OrganizationMembership.objects
        .filter(organization=ts.org, role__in=['owner', 'admin', 'manager'])
        .exclude(user_id=ts.user_id)          # never ask someone to approve themselves
        .select_related('user')
    )

    sent = 0
    for m in approvers:
        if not m.user.email:
            continue
        try:
            send_manager_pending_approvals(
                to_email=m.user.email,
                manager_name=m.user.first_name or m.user.username,
                week_start_str=week_str,
                timesheet_count=1,
                total_hours=hours,
                summary_lines=[f"  \u2022 {who}: {hours}h"],
            )
            sent += 1
        except Exception as e:
            logger.error(f"[TIMESHEET] Could not notify approver {m.user.email}: {e}")

    logger.info(f"[TIMESHEET] {who}'s week of {week_str} submitted; notified {sent} approver(s)")
    return {'notified': sent}


@shared_task(name='tracker.tasks.notify_timesheet_decision')
def notify_timesheet_decision(timesheet_id: int, kind: str, actor_name: str, reason: str = ''):
    """Close the loop back to whoever submitted the week.

    Without this an approval is silent, so people re-check the page for days,
    and a rejection is worse — the work sits unrevised because nobody knows it
    was sent back.
    """
    from tracker.models import Timesheet, UserPreference
    from tracker.email_service import send_timesheet_approved, send_timesheet_rejected

    try:
        ts = Timesheet.objects.select_related('user').get(id=timesheet_id)
    except Timesheet.DoesNotExist:
        return {'error': 'not_found'}

    user = ts.user
    if not user.email:
        return {'skipped': 'no email'}

    pref = UserPreference.objects.filter(user=user).first()
    if pref and not getattr(pref, 'email_approval_notifications', True):
        return {'skipped': 'user preference'}

    week_str = ts.week_start.strftime('%b %d')
    name = user.first_name or user.username

    try:
        if kind == 'approved':
            send_timesheet_approved(
                to_email=user.email, user_name=name, week_str=week_str,
                total_hours=float(ts.total_hours or 0), approved_by=actor_name,
            )
        else:
            send_timesheet_rejected(
                to_email=user.email, user_name=name, week_str=week_str,
                rejected_by=actor_name, reason=reason,
            )
    except Exception as e:
        logger.error(f"[TIMESHEET] Could not send {kind} notice to {user.email}: {e}")
        return {'error': str(e)[:200]}

    return {'sent': True, 'kind': kind}


# ============================================================================
# TIMESHEET WORKFLOW TASKS
# ============================================================================

@shared_task(name='tracker.send_timesheet_reminders')
def send_timesheet_reminders():
    """
    Monday 9am: Send reminder emails for unsubmitted timesheets from last week.

    Schedule: crontab(hour=9, minute=0, day_of_week=1)  # Monday 9am
    """
    from tracker.models import Timesheet, Block
    from django.core.mail import send_mail
    from django.conf import settings

    # Use localdate() so this respects Django's TIME_ZONE setting
    today = timezone.localdate()

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

    Marks them with auto_submitted=True for audit purposes.

    Schedule: crontab(hour=9, minute=0, day_of_week=2)  # Tuesday 9am
    """
    from tracker.models import Timesheet, Block
    from django.core.mail import send_mail
    from django.conf import settings

    # -------------------------------------------------------------------------
    # TUESDAY GUARD
    # Must use localdate() (not now().date()) so Django's TIME_ZONE is respected.
    # Without this, Render's UTC clock can fire this on Monday night ET and
    # today.weekday() returns 0 (Monday), making last_monday point at the
    # CURRENT week — submitting timesheets a full day early.
    # -------------------------------------------------------------------------
    today = timezone.localdate()

    if today.weekday() != 1:  # Python: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
        logger.warning(
            f"[TIMESHEET] auto_submit_timesheets called on {today.strftime('%A %Y-%m-%d')} "
            f"— expected Tuesday. Aborting to prevent premature submission."
        )
        return {
            'aborted': True,
            'reason': f'Not Tuesday — got {today.strftime("%A %Y-%m-%d")}',
        }

    # Get last week's Monday (today is Tuesday, weekday=1)
    # days_since_monday = 1, so last_monday = today - 8 = correct prior Monday
    days_since_monday = today.weekday()  # Tuesday = 1
    last_monday = today - timedelta(days=days_since_monday + 7)
    last_sunday = last_monday + timedelta(days=6)

    logger.info(
        f"[TIMESHEET] auto_submit_timesheets running for week "
        f"{last_monday} - {last_sunday}"
    )

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
            blocks = Block.objects.filter(timesheet=timesheet).exclude(
                category_hours__has_key='Idle'
            )
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
        f"{skipped_empty} skipped, {errors} errors"
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

    today = timezone.localdate()

    # Get this week's Monday
    days_since_monday = today.weekday()
    this_monday = today - timedelta(days=days_since_monday)

    created_count = 0
    existing_count = 0

    # Organization has no is_active field either — the same FieldError as the
    # membership filter below, one line earlier and left behind when that one
    # was fixed. It raised on the FIRST line of the loop, so this task has never
    # created a single timesheet: no draft means auto-submit has nothing to
    # submit, which is why most people never reached a manager's approval queue
    # at all despite capturing time every week.
    #
    # Liveness is deleted_at plus the MavOps archive flag; both are real fields.
    for org in Organization.objects.filter(
        deleted_at__isnull=True, mavops_archived=False,
    ):
        # NOTE: OrganizationMembership has no is_active field — a member either
        # has a membership row or they don't. Filtering on is_active raised a
        # FieldError and silently killed this whole task, so draft timesheets
        # were never pre-created (see notify_managers_pending_approvals below,
        # which had the same bug).
        members = OrganizationMembership.objects.filter(
            organization=org,
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
    Tuesday 10am: Notify managers of pending approvals (1 hour after auto-submit).

    Schedule: crontab(hour=10, minute=0, day_of_week=2)  # Tuesday 10am
    """
    from tracker.models import Timesheet, OrganizationMembership
    from django.core.mail import send_mail
    from django.conf import settings
    from collections import defaultdict

    # TUESDAY GUARD — same reasoning as auto_submit_timesheets
    today = timezone.localdate()

    if today.weekday() != 1:  # 0=Mon, 1=Tue
        logger.warning(
            f"[TIMESHEET] notify_managers_pending_approvals called on "
            f"{today.strftime('%A %Y-%m-%d')} — expected Tuesday. Aborting."
        )
        return {
            'aborted': True,
            'reason': f'Not Tuesday — got {today.strftime("%A %Y-%m-%d")}',
        }

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
        # OrganizationMembership has no is_active field (see create_weekly_timesheets).
        managers = OrganizationMembership.objects.filter(
            organization_id=org_id,
            role__in=['owner', 'admin', 'manager'],
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
    Classify a single block using ClassificationService (new pipeline).
 
    Called by the post_save signal whenever a Block is created. Also called
    directly from management commands for batch reclassification.
 
    Immutability guarantee: blocks already in committed/proposed/suppressed
    state are NOT re-classified. Only blocks in captured/None state get
    processed. Once the state machine sets a final state, only user manual
    edits can change it.
 
    Args:
        block_id: ID of block to classify
    Returns:
        dict with classification result for monitoring/logging
    """
    try:
        from tracker.models import Block
        from tracker.services.classification_service import ClassificationService
 
        # Get block
        try:
            block = Block.objects.select_related('client', 'user', 'org').get(id=block_id)
        except Block.DoesNotExist:
            logger.warning(f"[CLASSIFY] Block {block_id} not found")
            return {"status": "not_found", "block_id": block_id}
 
        # Skip if legacy is_categorized flag is set
        if block.is_categorized:
            return {"status": "already_categorized", "block_id": block_id}
 
        # Immutability check: only process captured/legacy blocks
        current_state = getattr(block, 'classification_state', None)
        if current_state and current_state != 'captured':
            return {
                "status": "already_classified",
                "block_id": block_id,
                "state": current_state,
            }
 
        # Run ClassificationService
        org = getattr(block, 'org', None)
        user = getattr(block, 'user', None)
 
        if not org:
            logger.warning(f"[CLASSIFY] Block {block_id} has no org — skipping")
            return {"status": "skipped", "block_id": block_id, "reason": "no org"}
 
        service = ClassificationService(org=org, user=user)
        decision = service.classify(block)
        service.apply(block, decision)
 
        # Refresh from DB to get the final state after apply()
        block.refresh_from_db()
        final_state = block.classification_state
 
        # Map state to legacy status string for monitoring compatibility
        if final_state == 'committed':
            status = 'classified'
        elif final_state == 'proposed':
            status = 'needs_review'
        elif final_state == 'suppressed':
            status = 'suppressed'
        else:
            status = 'captured'
 
        logger.info(
            f"[CLASSIFY] Block {block_id} → state={final_state} "
            f"(client={block.client_id}, conf={block.proposed_confidence})"
        )
 
        return {
            "status": status,
            "block_id": block_id,
            "state": final_state,
            "client_id": block.client_id,
            "category": list((block.category_hours or {}).keys())[0] if block.category_hours else None,
            "confidence": float(block.proposed_confidence or 0.0),
            "source": "classification_service",
        }
 
    except Exception as exc:
        logger.error(f"[CLASSIFY] Error on block {block_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)


# ============================================================================
# BATCH TASKS
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
    5-minute safety-net task: catches blocks the real-time path missed.
 
    Real-time path (post_save → classify_block_task) handles new blocks
    immediately. This task picks up any block that ended up in 'captured'
    state — usually because the real-time path errored or the AI step
    timed out.
 
    Immutability guarantee: only processes blocks in 'captured' state.
    Once committed/proposed/suppressed, blocks are immutable to automated
    re-processing. No double-AI-call risk.
 
    Args:
        limit: Max blocks to process per run (default 80)
    """
    from datetime import timedelta
    from django.utils import timezone
 
    try:
        from tracker.models import Block
        from tracker.services.classification_service import ClassificationService
 
        from django.db.models import Q
        cutoff = timezone.now() - timedelta(hours=24)
        # Re-attempt throttle: a captured block that already went through
        # Stage 10 and stayed captured is (usually) unclassifiable (PDF,
        # payroll register, dialog). Without this, the 5-min task re-fired
        # OpenAI on the SAME block every cycle = ~288 calls/block/day
        # (one block hit 291 calls). Cap at 2 auto-attempts, >= 6h apart.
        # A manual reclassify resets ai_attempt_count so a block made
        # classifiable later (alias/fix/funded balance) can be retried.
        AI_MAX_AUTO_ATTEMPTS = 2
        ATTEMPT_CUTOFF = timezone.now() - timedelta(hours=6)
 
        # Only blocks still in 'captured' state — i.e., the real-time path
        # didn't successfully resolve them.
        captured_blocks = list(
            Block.objects.filter(
                classification_state='captured',
                start__gte=cutoff,
                deleted_at__isnull=True,
                is_categorized=False,
            )
            .filter(ai_attempt_count__lt=AI_MAX_AUTO_ATTEMPTS)
            .filter(
                Q(ai_last_attempt_at__isnull=True) |
                Q(ai_last_attempt_at__lt=ATTEMPT_CUTOFF)
            )
            .select_related('user', 'client', 'org')
            .order_by('-start')[:limit]
        )
 
        if not captured_blocks:
            return {'blocks_found': 0, 'message': 'No captured blocks to retry'}
 
        logger.info(f"[AI-SAFETY-NET] Found {len(captured_blocks)} captured blocks to retry")
 
        stats = {
            'blocks_found': len(captured_blocks),
            'committed': 0,
            'proposed': 0,
            'suppressed': 0,
            'still_captured': 0,
            'errors': 0,
        }
 
        # Group by org so we can reuse ClassificationService instances
        # (it caches client list and rules per-org)
        from collections import defaultdict
        by_org = defaultdict(list)
        for b in captured_blocks:
            if b.org_id:
                by_org[b.org_id].append(b)
 
        for org_id, org_blocks in by_org.items():
            org = org_blocks[0].org
            user = None  # service per-block has user context
 
            for block in org_blocks:
                try:
                    user = block.user
                    service = ClassificationService(org=org, user=user)
                    decision = service.classify(block)
                    service.apply(block, decision)
 
                    # Record the attempt so this block isn't re-fired to
                    # OpenAI every 5 min. .update() avoids the post_save
                    # classify signal. F() increments atomically.
                    from django.db.models import F
                    Block.objects.filter(pk=block.pk).update(
                        ai_attempt_count=F('ai_attempt_count') + 1,
                        ai_last_attempt_at=timezone.now(),
                    )
 
                    block.refresh_from_db()
                    final = block.classification_state
 
                    if final == 'committed':
                        stats['committed'] += 1
                    elif final == 'proposed':
                        stats['proposed'] += 1
                    elif final == 'suppressed':
                        stats['suppressed'] += 1
                    else:
                        stats['still_captured'] += 1
 
                except Exception as e:
                    logger.error(
                        f"[AI-SAFETY-NET] Failed on block {block.id}: {e}",
                        exc_info=True,
                    )
                    stats['errors'] += 1
                    
        # ── INTRADAY SECOND-PASS ──────────────────────────────────────────
        # After first-pass classification, second-pass the orgs we just
        # touched so proposals appear within ~5 min (not just nightly).
        # days=1 keeps it fast; nightly task sweeps the full 14-day window.
        try:
            from tracker.services.second_pass import run_second_pass
            for org_id in by_org.keys():
                sp = run_second_pass(org_id, days=1, dry_run=False)
                if sp.get('billed'):
                    logger.error(f"[SECOND-PASS intraday] org {org_id}: {sp['billed']} billed from guess!")
        except Exception as e:
            logger.error(f"[SECOND-PASS intraday] failed: {e}", exc_info=True)
        # ──────────────────────────────────────────────────────────────────
 
        logger.info(
            f"[AI-SAFETY-NET] Done: "
            f"committed={stats['committed']}, "
            f"proposed={stats['proposed']}, "
            f"suppressed={stats['suppressed']}, "
            f"still_captured={stats['still_captured']}, "
            f"errors={stats['errors']}"
        )
 
        return stats
 
    except Exception as exc:
        logger.error(f"[AI-SAFETY-NET] Task failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=120)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


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
        count = RawEvent.objects.filter(start_ts__lt=cutoff).delete()[0]

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

        blocks = Block.objects.filter(
            day=target_date,
            is_categorized=True
        ).select_related('user', 'client')

        by_user = defaultdict(list)
        for block in blocks:
            by_user[block.user_id].append(block)

        summaries = []

        for user_id, user_blocks in by_user.items():
            try:
                user = User.objects.get(id=user_id)

                total_minutes = sum(b.minutes for b in user_blocks if b.minutes)
                total_hours = round(total_minutes / 60.0, 2)

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
# MANUAL BATCH PROCESSING
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
    """Background push of time entries to QuickBooks."""
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

    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks', is_connected=True)
    except Integration.DoesNotExist:
        return {'status': 'error', 'error': 'QuickBooks not connected'}

    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()

    tz = timezone.get_current_timezone()
    start_aware = timezone.make_aware(datetime.combine(start_dt, datetime.min.time()), tz)
    end_aware = timezone.make_aware(datetime.combine(end_dt + timedelta(days=1), datetime.min.time()), tz)

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


SEAT_GRACE_DAYS = 15


def _notify_seat_overage(org, member_count):
    """Email the org's owner/admins that they're over their seat count."""
    from tracker.models import OrganizationMembership
    try:
        from tracker.email_service import send_seat_overage_notice
    except Exception:
        return
    admins = (
        OrganizationMembership.objects
        .filter(organization=org, role__in=['owner', 'admin'])
        .select_related('user')
        .order_by('joined_at', 'id')
    )
    recipients = [m.user.email for m in admins if getattr(m.user, 'email', None)]
    if not recipients:
        return
    for email in recipients:
        try:
            send_seat_overage_notice(
                to_email=email,
                org_name=org.name,
                member_count=member_count,
                seat_count=org.seat_count,
                grace_days=SEAT_GRACE_DAYS,
            )
        except Exception as e:
            logger.error(f"[SEAT-GRACE] notice failed for {email}: {e}")


@shared_task(name='tracker.check_seat_overage_grace')
def check_seat_overage_grace():
    """
    Enforce seat limits with a 15-day grace window.

    When an org's member count first exceeds its paid seats, start a grace
    deadline and email the admins. If still over when the deadline passes,
    block only the EXCESS members' devices (keep the earliest-joined
    seat_count members working). When resolved, clear grace and reactivate
    only the devices we blocked for seat overage.

    Distinct from check_payment_grace_periods (Stripe past-due): this uses
    seat_grace_deadline and never touches org.plan / seat_count.
    """
    from tracker.models import Organization, OrganizationMembership, AgentDevice

    now = timezone.now()
    started = enforced = resolved = 0

    # Only paid plans with a real seat cap can be "over". Skip archived/demo
    # orgs — we never email or enforce against junk duplicates or demos.
    orgs = (
        Organization.objects
        .filter(seat_count__gt=0, mavops_archived=False, is_demo=False)
        .exclude(plan='none')
    )
    for org in orgs:
        members = list(
            OrganizationMembership.objects
            .filter(organization=org)
            .order_by('joined_at', 'id')
        )
        member_count = len(members)
        over = member_count > org.seat_count

        if not over:
            if org.seat_grace_deadline:
                org.seat_grace_deadline = None
                org.save(update_fields=['seat_grace_deadline'])
                reactivated = AgentDevice.objects.filter(
                    user__memberships__organization=org,
                    is_active=False,
                    deactivated_reason='seat_overage',
                ).update(is_active=True, deactivated_reason='')
                resolved += 1
                logger.info(f"[SEAT-GRACE] Resolved for {org.name}; reactivated {reactivated} device(s)")
            continue

        if not org.seat_grace_deadline:
            org.seat_grace_deadline = now + timedelta(days=SEAT_GRACE_DAYS)
            org.save(update_fields=['seat_grace_deadline'])
            started += 1
            logger.info(
                f"[SEAT-GRACE] Started for {org.name}: {member_count}/{org.seat_count} seats, "
                f"deadline {org.seat_grace_deadline:%Y-%m-%d}"
            )
            _notify_seat_overage(org, member_count)
        elif now >= org.seat_grace_deadline:
            excess_user_ids = [m.user_id for m in members[org.seat_count:]]
            blocked = AgentDevice.objects.filter(
                user_id__in=excess_user_ids, is_active=True,
            ).update(is_active=False, deactivated_reason='seat_overage')
            if blocked:
                enforced += 1
                logger.info(
                    f"[SEAT-GRACE] Enforced for {org.name}: blocked {blocked} device(s) "
                    f"beyond {org.seat_count} seats"
                )
        # else: still within grace — MavOps shows the countdown, no action.

    return {'grace_started': started, 'enforced': enforced, 'resolved': resolved}


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

    if operation in ('Delete', 'Void'):
        updated = InvoiceModel.objects.filter(
            org=org, external_id=invoice_id
        ).update(status='voided')
        logger.info(f"QB webhook: marked invoice {invoice_id} as voided ({updated} rows)")
        return

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
        return

    total = Decimal(str(inv.get('TotalAmt', 0)))
    balance = Decimal(str(inv.get('Balance', 0)))
    email_status = inv.get('EmailStatus', 'NotSet')
    status = 'paid' if balance == 0 else ('sent' if email_status == 'EmailSent' else 'draft')
    doc_number = inv.get('DocNumber') or f"QBO-{invoice_id}"
    inv_date = inv.get('TxnDate', str(date.today()))

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
        return

    InvoiceModel.objects.update_or_create(
        org=org,
        external_id=str(invoice_id),
        defaults={
            'invoice_number': doc_number,
            'client': client,
            'client_name': client.name,
            'invoice_date': inv_date,
            'amount': total,
            'status': status,
            'source': 'quickbooks',
            'hours_billed': None,
        }
    )

    integration.last_synced_at = timezone.now()
    integration.save(update_fields=['last_synced_at'])
    logger.info(f"QB webhook: synced invoice {doc_number} for {client.name}")


def _sync_qb_invoices(integration, start, end):
    """Pull QBO invoices with TxnDate in [start, end] and upsert into Invoice.

    Pages through results with STARTPOSITION so a wide backfill window isn't
    silently capped at the 1000-row page limit. ``start``/``end`` are ISO date
    strings. Returns the number of invoices seen (matched or not)."""
    from tracker.models import Invoice as InvoiceModel, Client
    from tracker.views_integrations import qb_api_call
    from decimal import Decimal

    qb_map = {c.quickbooks_id: c for c in Client.objects.filter(
        org=integration.organization, quickbooks_id__isnull=False
    )}

    PAGE = 1000
    start_pos = 1
    seen = 0
    while True:
        query = (
            f"SELECT * FROM Invoice WHERE TxnDate >= '{start}' "
            f"AND TxnDate <= '{end}' ORDERBY TxnDate "
            f"STARTPOSITION {start_pos} MAXRESULTS {PAGE}"
        )
        data, err = qb_api_call(integration, 'GET', '/query', params={'query': query})
        if err:
            break
        invoices = data.get('QueryResponse', {}).get('Invoice', [])
        if not invoices:
            break

        for inv in invoices:
            seen += 1
            qb_customer_id = inv.get('CustomerRef', {}).get('value')
            client = qb_map.get(qb_customer_id)
            if not client:
                continue

            total = Decimal(str(inv.get('TotalAmt', 0)))
            balance = Decimal(str(inv.get('Balance', 0)))
            email_status = inv.get('EmailStatus', 'NotSet')
            status = 'paid' if balance == 0 else ('sent' if email_status == 'EmailSent' else 'draft')
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
                    'status': status,
                    'source': 'quickbooks',
                    'hours_billed': None,
                }
            )

        if len(invoices) < PAGE:
            break
        start_pos += PAGE

    integration.last_synced_at = timezone.now()
    integration.save(update_fields=['last_synced_at'])
    return seen


@shared_task
def reconcile_qb_invoices():
    """
    Fallback reconciliation — catches any invoices missed by webhook.
    Runs every 4 hours. Much cheaper than the old poll-only approach.
    """
    from tracker.models import Integration
    from datetime import date, timedelta

    integrations = Integration.objects.filter(
        provider='quickbooks',
        is_connected=True,
    ).select_related('organization')

    for integration in integrations:
        try:
            # Rolling 7-day window keeps recent invoices fresh.
            end = date.today().isoformat()
            start = (date.today() - timedelta(days=7)).isoformat()
            n = _sync_qb_invoices(integration, start, end)
            logger.info(f"QB reconcile: {n} invoices for org {integration.organization_id}")
        except Exception as e:
            logger.error(f"QB reconcile failed for org {integration.organization_id}: {e}")


@shared_task
def backfill_qb_invoices(org_id, days=365):
    """One-shot historical backfill, kicked off right after a firm connects
    QuickBooks so realization/leakage/gross-margin have history immediately
    instead of waiting for the rolling reconcile to slowly fill in.
    """
    from tracker.models import Integration
    from datetime import date, timedelta

    integration = Integration.objects.filter(
        provider='quickbooks', is_connected=True, organization_id=org_id,
    ).select_related('organization').first()
    if not integration:
        logger.warning(f"QB backfill: no connected integration for org {org_id}")
        return

    try:
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=days)).isoformat()
        n = _sync_qb_invoices(integration, start, end)
        logger.info(f"QB backfill: {n} invoices ({days}d) for org {org_id}")
    except Exception as e:
        logger.error(f"QB backfill failed for org {org_id}: {e}")


# ============================================================================
# DATABASE MAINTENANCE
# ============================================================================

from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


@shared_task
def purge_processed_raw_events():
    """
    Delete raw events older than 90 days that have already been
    rolled into a block. Safe to run nightly — never deletes
    unprocessed events regardless of age.
    """
    from tracker.models import RawEvent

    cutoff = timezone.now() - timedelta(days=90)
    deleted, _ = RawEvent.objects.filter(
        start_ts__lt=cutoff,
        block_id__isnull=False  # only purge if already processed into a block
    ).delete()
    logger.info(f"purge_processed_raw_events: deleted {deleted} rows")
    return deleted


@shared_task
def log_queue_health():
    """
    Warn if Celery tasks are backing up in the queue.
    Upgrade the worker instance if pending count stays above 10.
    """
    from django_celery_results.models import TaskResult

    pending = TaskResult.objects.filter(
        status='PENDING',
        date_created__lt=timezone.now() - timedelta(seconds=30)
    ).count()

    if pending > 10:
        logger.warning(f"log_queue_health: {pending} tasks pending >30s — consider upgrading Celery worker")
    else:
        logger.info(f"log_queue_health: queue healthy ({pending} tasks pending)")

    return pending


# Calendar sync tasks
from tracker.tasks_calendar import sync_all_calendars, sync_user_calendar  # noqa: F401

# At the end of your existing tracker/tasks.py, add:

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def batch_ai_classify_async(self, block_ids, org_id, user_id=None):
    """
    Background task: Classify blocks via Stage 10 (OpenAI).
    
    Emits WebSocket event when complete so frontend refreshes in real-time.
    """
    from django.contrib.auth import get_user_model
    from tracker.models import Organization, Block
    from tracker.services.classification_service import ClassificationService
    
    User = get_user_model()
    
    try:
        org = Organization.objects.get(id=org_id)
        user = User.objects.get(id=user_id) if user_id else None
        
        # Fetch blocks that still need AI
        blocks = list(Block.objects.filter(
            id__in=block_ids,
            classification_state='captured'
        ))
        
        if not blocks:
            logger.info(f"[ASYNC-AI] No blocks needing AI (all resolved or deleted)")
            return {'status': 'skipped', 'reason': 'no_blocks_needing_ai'}
        
        logger.info(f"[ASYNC-AI] Starting background classification for {len(blocks)} blocks (org={org_id})")
        
        service = ClassificationService(org=org, user=user)
        from tracker.views import _batch_ai_classify
        _batch_ai_classify(blocks, service, org, user)
        
        logger.info(f"[ASYNC-AI] ✅ Completed background classification for {len(blocks)} blocks")
        
        # ✨ NEW: Emit WebSocket event to notify frontend
        try:
            from django_eventstream import send_event
            
            send_event(
                f'org_{org_id}_ai_ready',
                {
                    'status': 'complete',
                    'org_id': org_id,
                    'user_id': user_id,
                    'block_ids': block_ids,
                    'blocks_processed': len(blocks),
                    'timestamp': str(timezone.now()),
                }
            )
            logger.info(f"[ASYNC-AI] ✅ WebSocket event emitted to org_{org_id}_ai_ready")
        except Exception as e:
            logger.warning(f"[ASYNC-AI] Failed to emit WebSocket event: {e}")
        
        return {'status': 'success', 'blocks_processed': len(blocks)}
        
    except Exception as e:
        logger.error(f"[ASYNC-AI] ❌ Failed: {e}", exc_info=True)
        raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))

@shared_task(name='tracker.compact_and_classify_org', bind=True, max_retries=0)
def compact_and_classify_org(self, org_id):
    """
    Full per-org pipeline off the request path:
    compaction → Stages 0-9 → queue Stage 10.
    Shares the same lock as ai_suggestions_today so the view
    and this task never run the heavy work concurrently.
    """
    from django.core.cache import cache
    from tracker.models import Organization, Block
    from tracker.services.classification_service import ClassificationService
    from tracker.services.compaction import compact_rawevents_into_blocks
    from tracker.views import _start_of_local_day_utc  # adjust import if it lives elsewhere

    lock_key = f"compact-classify:{org_id}"
    if not cache.add(lock_key, "1", timeout=300):
        return {'status': 'skipped', 'reason': 'already running'}

    try:
        org = Organization.objects.get(id=org_id)
        compact_rawevents_into_blocks(org=org)

        start_utc = _start_of_local_day_utc()
        pending = list(Block.objects.filter(
            org=org,
            start__gte=start_utc,
            is_categorized=False,
        ).filter(
            classification_state__in=['captured']
        ) | Block.objects.filter(
            org=org, start__gte=start_utc,
            is_categorized=False, classification_state__isnull=True,
        ))[:200]

        for b in pending:
            try:
                service = ClassificationService(org=org, user=b.user)
                decision = service.classify(b, skip_ai=True)
                service.apply(b, decision)
            except Exception as e:
                logger.error(f"[COMPACT-CLASSIFY] Block {b.id} failed: {e}")
                continue

        ai_ids = list(Block.objects.filter(
            org=org,
            start__gte=start_utc,
            classification_state='captured',
            proposed_client_id__isnull=True,
        ).exclude(
            proposed_reasoning__startswith='AI:'   # ← already attempted, don't re-send
        ).values_list('id', flat=True)[:200])

        if ai_ids:
            batch_ai_classify_async.delay(block_ids=ai_ids, org_id=org_id, user_id=None)

        return {'status': 'ok', 'classified': len(pending), 'queued_for_ai': len(ai_ids)}
    finally:
        cache.delete(lock_key)


@shared_task(name='tracker.dispatch_compact_classify_all')
def dispatch_compact_classify_all():
    """Fan out for orgs with uncompacted events OR unclassified blocks."""
    from tracker.models import RawEvent, Block

    cutoff = timezone.now() - timedelta(minutes=5)
    block_cutoff = timezone.now() - timedelta(hours=24)

    # RawEvent has no org FK (only user + block). Reach the org through the
    # user's membership — the same path compaction uses (compact_day). block is
    # NULL here, so the block->org route isn't available.
    event_orgs = set(RawEvent.objects
                     .filter(start_ts__gte=cutoff, block__isnull=True)
                     .values_list('user__memberships__organization_id', flat=True)
                     .distinct())

    block_orgs = set(Block.objects
                     .filter(classification_state='captured', start__gte=block_cutoff)
                     .values_list('org_id', flat=True).distinct())

    org_ids = {oid for oid in (event_orgs | block_orgs) if oid}
    for oid in org_ids:
        compact_and_classify_org.delay(oid)
    return {'orgs_dispatched': len(org_ids)}


@shared_task(name='tracker.tasks.second_pass_categorize_all', bind=True, max_retries=2)
def second_pass_categorize_all(self):
    from tracker.models import Organization
    from tracker.services.second_pass import run_second_pass
    import logging
    log = logging.getLogger('timetracker')
    for oid in Organization.objects.values_list('id', flat=True):
        try:
            s = run_second_pass(oid, days=14, dry_run=False)
            if s.get('billed'):
                log.error(f"[SECOND-PASS] org {oid}: {s['billed']} billed from guess!")
            log.info(f"[SECOND-PASS] org {oid}: {s}")
        except Exception as e:
            log.exception(f"[SECOND-PASS] org {oid} failed: {e}")


@shared_task(name='tracker.tasks.scan_org_mismatches')
def scan_org_mismatches(days=7, org_id=None):
    """
    Nightly client-name mismatch scan (detection-only backstop).

    Scans committed, non-deleted, client-booked blocks in a rolling window and
    reconciles MismatchFlag rows:
      - opens a flag for each NEW client-bucket mismatch,
      - marks a previously-open flag resolved ('reconciled') when its block no
        longer mismatches.

    Never mutates a Block. Read by the pre-invoice gate and MavOps Admin
    org-health. Default 7-day window matches the review-and-approve cycle; use
    the `detect_client_mismatches` management command for deep historical sweeps.
    """
    from tracker.models import Block, MismatchFlag, Organization
    from tracker.services.mismatch_scan import _indexes_for_orgs, scan_blocks

    cutoff = timezone.now() - timedelta(days=days)

    org_ids = [org_id] if org_id else list(
        Organization.objects.values_list('id', flat=True)
    )
    if not org_ids:
        return {'orgs': 0, 'opened': 0, 'resolved': 0}

    names_by_org, index_by_org, firm_by_org = _indexes_for_orgs(org_ids)

    blocks = (
        Block.objects
        .filter(deleted_at__isnull=True, client_id__isnull=False,
                start__gte=cutoff, org_id__in=org_ids)
        .exclude(window_title__isnull=True)
        .exclude(window_title='')
        .select_related('client')
        .order_by('start')
    )

    # Current mismatches in-window, keyed by block_id (client bucket only).
    current = {}
    for row in scan_blocks(blocks.iterator(chunk_size=1000),
                           names_by_org, index_by_org, firm_by_org):
        if row['bucket'] == 'client':
            current[row['block_id']] = row

    opened = 0
    resolved = 0

    # Open flags for new mismatches (skip blocks that already have an open flag).
    existing_open = set(
        MismatchFlag.objects
        .filter(block_id__in=current.keys(), resolved_at__isnull=True)
        .values_list('block_id', flat=True)
    )
    to_create = []
    for block_id, row in current.items():
        if block_id in existing_open:
            continue
        to_create.append(MismatchFlag(
            org_id=row['org_id'],
            block_id=block_id,
            booked_client_id=row['booked_client_id'],
            title_client_id=row['looks_like_client_id'],
            title_client_name=row['looks_like_client_name'],
            bucket='client',
            match_score=row['score'],
            window_title=row['window_title'],
        ))
    if to_create:
        MismatchFlag.objects.bulk_create(to_create, ignore_conflicts=True)
        opened = len(to_create)

    # Resolve any open flag whose block is no longer mismatching in this window.
    stale_open = (
        MismatchFlag.objects
        .filter(org_id__in=org_ids, resolved_at__isnull=True,
                block__start__gte=cutoff)
        .exclude(block_id__in=current.keys())
    )
    resolved = stale_open.update(
        resolved_at=timezone.now(),
        resolved_reason='reconciled',
    )

    logger = logging.getLogger(__name__)
    logger.info(
        f"[MISMATCH-SCAN] orgs={len(org_ids)} window={days}d "
        f"current={len(current)} opened={opened} resolved={resolved}"
    )
    return {'orgs': len(org_ids), 'current': len(current),
            'opened': opened, 'resolved': resolved}


# ============================================================================
# CLIENT ALIAS DERIVATION
# ============================================================================
#
# Auto-generate name aliases for clients added AFTER onboarding (Settings UI,
# CSV import, client-request approval, CCH sync, etc.). During onboarding the
# QB/Xero imports already call run_post_import_alias_derivation; these two
# tasks extend the same coverage to every other client-creation path.
#
# NON-DESTRUCTIVE by design. Two steps run per org:
#   * derive_aliases        — strictly append-only (skips existing, never
#                             re-adds the client's own name).
#   * heal_ambiguous_aliases — removes ONLY aliases whose provenance is
#                             'derived' AND that now collide with a sibling
#                             client. Manual and unmarked/legacy aliases are
#                             never removed.
# They deliberately do NOT run `prune_junk_aliases` (which could delete a
# legit standalone manual alias like "Home"/"Group").

@shared_task(name='tracker.derive_client_aliases_for_org')
def derive_client_aliases_for_org(org_id, min_confidence: float = 0.8):
    """
    Append-only alias derivation for a single org. Dispatched (best-effort)
    right after a client is created through a manual/UI path so the new
    client picks up derived aliases immediately.

    Two append-only-safe steps run in order:
      1. derive_aliases — appends new derived aliases (never removes anything).
      2. heal_ambiguous_aliases — removes ONLY auto-derived aliases that now
         collide with a sibling client (e.g. a stale bare "St Mary's" once a
         second St Mary's exists). Manual/legacy aliases are never touched.

    Whole-org scope is intentional: a new client's alias might collide with an
    existing client, and both the derive collision guard and the heal step
    need the full client list to judge ambiguity safely.
    """
    try:
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("derive_aliases", org_id=org_id,
                     min_confidence=min_confidence, stdout=out)
        call_command("heal_ambiguous_aliases", org_id=org_id, stdout=out)
        logger.info("[ALIAS] Derived + healed aliases for org %s:\n%s",
                    org_id, out.getvalue())
        return {'ok': True, 'org_id': org_id}
    except Exception as e:
        logger.warning("[ALIAS] Alias derivation failed for org %s: %s",
                       org_id, e, exc_info=True)
        return {'error': str(e), 'org_id': org_id}


@shared_task(name='tracker.derive_client_aliases_all_orgs')
def derive_client_aliases_all_orgs(min_confidence: float = 0.8):
    """
    Nightly safety-net sweep: append-only alias derivation across every org.

    Catches clients added through paths that don't dispatch the per-create
    hook (CSV bulk import, client-request approval, CCH Axcess sync, direct
    create_client). Idempotent and non-destructive — orgs with no new aliases
    are no-ops, and nothing is ever removed.

    Schedule: crontab(hour=4, minute=0)  # 4am daily
    """
    from tracker.models import Organization

    ok = 0
    failed = 0
    for org_id in Organization.objects.values_list('id', flat=True):
        result = derive_client_aliases_for_org.run(org_id, min_confidence=min_confidence)
        if result.get('ok'):
            ok += 1
        else:
            failed += 1

    logger.info("[ALIAS] Nightly sweep complete: %d orgs ok, %d failed", ok, failed)
    return {'ok': ok, 'failed': failed}

# ---------------------------------------------------------------------------
# WIP relief — drain WIP as invoices land
# ---------------------------------------------------------------------------

@shared_task(name='tracker.relieve_wip_all_orgs')
def relieve_wip_all_orgs():
    """
    Nightly: apply synced invoices against uninvoiced WIP so WIP goes down when
    the firm bills. Without this, WIP aging is a ramp that only grows.

    Opt-in per org via Organization.wip_auto_relief — an org whose invoice feed
    isn't trusted yet should run `manage.py relieve_wip --org N` dry first.

    Schedule: crontab(hour=3, minute=45)  # after the nightly invoice syncs
    """
    from tracker.models import Organization
    from tracker.services.wip_relief import relieve_org

    totals = {'orgs': 0, 'invoices_applied': 0, 'blocks_relieved': 0, 'wip_relieved': 0.0}
    for org in Organization.objects.filter(wip_auto_relief=True):
        try:
            report = relieve_org(org, dry_run=False)
        except Exception as e:
            logger.warning("[WIP-RELIEF] org %s failed: %s", org.id, e, exc_info=True)
            continue
        totals['orgs'] += 1
        totals['invoices_applied'] += report['invoices_applied']
        totals['blocks_relieved'] += report['blocks_relieved']
        totals['wip_relieved'] += report['wip_relieved']
        if report['invoices_applied']:
            logger.info(
                "[WIP-RELIEF] org %s: %d invoices relieved $%.2f across %d blocks",
                org.id, report['invoices_applied'], report['wip_relieved'],
                report['blocks_relieved'],
            )

    return totals


# ---------------------------------------------------------------------------
# Engagements — keep budgets and progress current
# ---------------------------------------------------------------------------

@shared_task(name='tracker.derive_engagements_all_orgs')
def derive_engagements_all_orgs():
    """
    Nightly: fold new time into engagements, refresh budgets from history, and
    re-run the shadow phase inference.

    Safe to run on every org — assignment only touches blocks with no
    engagement, budget derivation never overwrites a manual budget, and
    inference writes only to `inferred_phase`, never to the phase a preparer set.

    Schedule: crontab(hour=4, minute=20)  # after alias derivation
    """
    from tracker.models import Organization
    from tracker.services.engagements import assign_engagements, derive_budgets
    from tracker.services.phase_inference import refresh_inferred_phases

    totals = {'orgs': 0, 'engagements_created': 0, 'blocks_assigned': 0}
    for org in Organization.objects.all():
        try:
            assigned = assign_engagements(org, dry_run=False)
            derive_budgets(org, dry_run=False)
            refresh_inferred_phases(org, dry_run=False)
        except Exception as e:
            logger.warning("[ENGAGEMENTS] org %s failed: %s", org.id, e, exc_info=True)
            continue
        totals['orgs'] += 1
        totals['engagements_created'] += assigned['engagements_created']
        totals['blocks_assigned'] += assigned['blocks_assigned']

    logger.info("[ENGAGEMENTS] nightly: %s", totals)
    return totals
