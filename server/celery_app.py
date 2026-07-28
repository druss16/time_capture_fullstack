# timeserver/celery.py
"""
Celery configuration for TimeTracker background tasks.

Includes:
- Block compaction and AI classification (every 5 min)
- Timesheet workflow (weekly reminders, auto-submit, manager notifications)
- Daily timesheet review notifications (Mon-Fri 9am)
- Weekly summary emails (Monday 9:30am)
- Maintenance (cleanup, daily summaries)
"""

import os
from celery import Celery
from celery.schedules import crontab
import warnings
warnings.filterwarnings('ignore', message='.*ssl_cert_reqs.*')

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'timeserver.settings')

# Create Celery app
app = Celery('timeserver')

# Load configuration from Django settings (CELERY_ namespace)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# ============================================================================
# BEAT SCHEDULE: Background tasks that run automatically
# ============================================================================

app.conf.beat_schedule = {
    # =========================================================================
    # BLOCK PROCESSING (Frequent)
    # =========================================================================
    
    # ✅ AUTO-COMPACT: Every 5 minutes ⚡
    # Creates blocks from raw events automatically
    'auto-compact-every-5-minutes': {
        'task': 'tracker.auto_compact_recent_events',
        'schedule': crontab(minute='*/5'),
        'options': {
            'expires': 300,
        }
    },
    
    # ✅ AI CLASSIFICATION: Every 5 minutes ⚡
    # Learns patterns and auto-categorizes high-confidence blocks
    'ai-classify-every-5-minutes': {
        'task': 'tracker.ai_classify_uncategorized_blocks',
        'schedule': crontab(minute='*/5'),
        'options': {
            'expires': 300,
        }
    },

    # ✅ COMPACT + CLASSIFY DISPATCH: Every 90 seconds ⚡
    # Per-org pipeline: compaction → Stages 0-9 → queue Stage 10.
    # Shares the compact-classify lock with ai_suggestions_today.
    'compact-classify-dispatch': {
        'task': 'tracker.dispatch_compact_classify_all',
        'schedule': 90.0,
        'options': {
            'expires': 90,   # skip stale runs if beat backs up
        }
    },

    'second-pass-categorize-nightly': {
        'task': 'tracker.tasks.second_pass_categorize_all',
        'schedule': crontab(hour=2, minute=30),
    },

    # ✅ EVERY 15 MIN: QB-chrome attribution (intraday second pass).
    # Attributes unattributed QuickBooks dialog blocks to the concurrently-open
    # company file's client, over a trailing 2-day window with a 60-min settle
    # delay. Frequent so a 5pm reviewer sees today's QB dialogs already out of
    # review. Gated on org.auto_confirm_client_attributions. Idempotent.
    'attribute-qb-chrome-sweep': {
        'task': 'tracker.tasks.attribute_qb_chrome_all',
        'schedule': crontab(minute='*/15'),
        'options': {
            'expires': 600,
        }
    },

    # ✅ NIGHTLY 3:00 AM: Client-name mismatch backstop scan.
    # Detection-only — opens/resolves MismatchFlag rows over a 7-day rolling
    # window. Watched in MavOps Admin org-health; feeds the pre-invoice gate.
    'scan-mismatches-nightly': {
        'task': 'tracker.tasks.scan_org_mismatches',
        'schedule': crontab(hour=3, minute=0),
        'options': {
            'expires': 3600,
        }
    },
    
    # =========================================================================
    # DAILY NOTIFICATIONS (Mon-Fri)
    # =========================================================================
    
    # ✅ DAILY 9:00 AM (Mon-Fri): Review yesterday's hours
    # "You have 6.5 hours from yesterday to review"
    'daily-timesheet-review-reminder': {
        'task': 'tracker.tasks.send_daily_timesheet_reminders_task',
        'schedule': crontab(hour=8, minute=0, day_of_week='1-5'),  # Mon-Fri 9am
        'options': {
            'expires': 3600,
        }
    },
    
    # =========================================================================
    # TIMESHEET WORKFLOW (Weekly)
    # =========================================================================
    
    # ✅ MONDAY 1:00 AM: Pre-create timesheets for new week
    # Ensures everyone has a DRAFT timesheet ready when they start
    'create-weekly-timesheets': {
        'task': 'tracker.create_weekly_timesheets',
        'schedule': crontab(hour=1, minute=0, day_of_week=1),  # Monday 1am
        'options': {
            'expires': 3600,
        }
    },
    
    # ✅ MONDAY 9:00 AM: Remind users to submit last week's timesheet
    # "Your timesheet for Dec 1-7 is ready to submit!"
    'timesheet-reminder-monday': {
        'task': 'tracker.send_timesheet_reminders',
        'schedule': crontab(hour=9, minute=0, day_of_week=1),  # Monday 9am
        'options': {
            'expires': 3600,
        }
    },
    
    # ✅ MONDAY 9:30 AM: Weekly summary email
    # Shows last week's time breakdown by client
    'weekly-summary-email': {
        'task': 'tracker.tasks.send_weekly_summary_task',
        'schedule': crontab(hour=9, minute=30, day_of_week=1),  # Monday 9:30am
        'options': {
            'expires': 3600,
        }
    },
    
    # ✅ TUESDAY 9:00 AM: Auto-submit any remaining DRAFT timesheets
    # Marks with auto_submitted=True so managers know it wasn't manually reviewed
    'timesheet-auto-submit-tuesday': {
        'task': 'tracker.auto_submit_timesheets',
        'schedule': crontab(hour=9, minute=0, day_of_week=2),  # Tuesday 9am
        'options': {
            'expires': 3600,
        }
    },
    
    # ✅ TUESDAY 10:00 AM: Notify managers of pending approvals
    # "You have 5 timesheets pending approval"
    'notify-managers-pending-approvals': {
        'task': 'tracker.notify_managers_pending_approvals',
        'schedule': crontab(hour=10, minute=0, day_of_week=2),  # Tuesday 10am
        'options': {
            'expires': 3600,
        }
    },

    # =========================================================================
    # STRIPE - CHECK GRACE PERIOD
    # =========================================================================

    'check-payment-grace-periods': {
    'task': 'tracker.check_payment_grace_periods',
    'schedule': crontab(hour=6, minute=0),  # Daily at 6am
    'options': {'expires': 3600},
    },
    
    # =========================================================================
    # MAINTENANCE (Daily/Weekly)
    # =========================================================================
    
    # ✅ CLEANUP: Daily at 2 AM
    # Removes old raw events to prevent database bloat
    'cleanup-old-events-daily': {
        'task': 'tracker.cleanup_old_raw_events',
        'schedule': crontab(hour=2, minute=0),  # 2:00 AM daily
        'kwargs': {
            'days_to_keep': 30  # Keep 30 days of raw events
        }
    },
    
    # ✅ DAILY SUMMARY: Daily at 6 AM
    # Pre-compute summaries for fast dashboard loading
    'generate-daily-summary': {
        'task': 'tracker.generate_daily_summary',
        'schedule': crontab(hour=6, minute=0),  # 6:00 AM daily
        'kwargs': {
            'days_back': 1  # Generate summary for yesterday
        }
    },
    
    # ✅ CLEANUP NOTIFICATION DISMISSALS: Sunday at midnight
    # Clean up old reminder dismissal records
    'cleanup-notification-dismissals': {
        'task': 'tracker.tasks.cleanup_old_notification_dismissals',
        'schedule': crontab(hour=0, minute=0, day_of_week=0),  # Sunday midnight
        'options': {
            'expires': 3600,
        }
    },

    'refresh-integration-tokens': {
        'task': 'tracker.refresh_integration_tokens',
        'schedule': crontab(minute='*/45'),
        'options': {'expires': 2700},
    },

    # ✅ CLIENT ALIAS SWEEP: daily at 4am
    # Append-only alias derivation across all orgs — safety net for clients
    # added after onboarding via any path (CSV, request approval, CCH sync).
    # Never removes aliases; the per-create hook handles instant coverage.
    'derive-client-aliases-sweep': {
        'task': 'tracker.derive_client_aliases_all_orgs',
        'schedule': crontab(hour=4, minute=0),  # 4am daily
        'options': {'expires': 3600},
    },

    # =========================================================================
    # INTEGRATIONS - QB RECONCILE (Fallback for missed webhooks)
    # =========================================================================

    'qb-reconcile-sync': {
        'task': 'tracker.tasks.reconcile_qb_invoices',
        'schedule': crontab(hour='*/4', minute=0),  # ← add minute=0
        'options': {'expires': 3600},
    },


    # =========================================================================
    # DATABASE CLEANSE - PURGE RAW EVENTS AND LOG QUEUE HEALTH
    # =========================================================================

    "purge-raw-events": {
        "task": "tracker.tasks.purge_processed_raw_events",
        "schedule": crontab(hour=2, minute=0),  # 2am daily
    },
    "queue-health-check": {
        "task": "tracker.tasks.log_queue_health",
        "schedule": crontab(minute="*/15"),  # every 15 minutes
    },

    # =========================================================================
    # CALENDAR SYNC (Per-user)
    # =========================================================================

    'sync-microsoft-calendars': {
        'task': 'tracker.sync_all_calendars',
        'schedule': crontab(minute='*/15'),  # every 15 minutes
        'options': {'expires': 600},  # don't run if 10 min old
    },


    # =========================================================================
    # MAIL SYNC (Per-user)
    # =========================================================================

    'sync-all-mail-every-5-min': {
        'task':     'tracker.sync_all_mail',
        'schedule': 300.0,  # 5 minutes
    },
    'prune-mail-signals-nightly': {
        'task':     'tracker.prune_mail_signals',
        'schedule': 86400.0,  # 24 hours
        # If you use crontab() in your beat schedule, prefer:
        # from celery.schedules import crontab
        # 'schedule': crontab(hour=3, minute=0),  # 3 AM daily
    },

    "v2-rollup-client-daily": {
        "task": "tracker.v2_rollup_yesterday_client_daily",
        "schedule": crontab(hour=2, minute=15),
        "options": {"queue": "default"},
    },
    "v2-rollup-staff-daily": {
        "task": "tracker.v2_rollup_yesterday_staff_daily",
        "schedule": crontab(hour=2, minute=30),
        "options": {"queue": "default"},
    },
    "v2-snapshot-wip-hourly": {
        "task": "tracker.v2_snapshot_wip",
        "schedule": crontab(minute=10),  # 10 past every hour
        "options": {"queue": "default"},
    },

}

# ============================================================================
# CELERY CONFIGURATION
# ============================================================================

app.conf.update(
    # Task routing
    task_routes={
        'tracker.*': {'queue': 'default'},
    },
    
    # Task execution
    task_acks_late=True,  # Acknowledge task after completion
    task_reject_on_worker_lost=True,  # Reject task if worker dies
    
    # Time limits
    task_time_limit=300,  # 5 minutes hard limit
    task_soft_time_limit=240,  # 4 minutes soft limit
    
    # Result backend (optional - uncomment if you want to store results)
    # result_backend='redis://localhost:6379/1',
    # result_expires=3600,  # Results expire after 1 hour
    
    # Logging
    worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s] [%(task_name)s(%(task_id)s)] %(message)s',
)


# ============================================================================
# DEBUG TASK (for testing)
# ============================================================================

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to verify Celery is working"""
    print(f'Request: {self.request!r}')
    return 'Celery is working!'


# ============================================================================
# STARTUP CHECK
# ============================================================================

@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Verify beat schedule is loaded correctly"""
    print("=" * 80)
    print("CELERY BEAT SCHEDULE LOADED:")
    print("=" * 80)
    
    for task_name, task_config in sorted(app.conf.beat_schedule.items()):
        print(f"  ✓ {task_name}")
        print(f"    Task: {task_config['task']}")
        print(f"    Schedule: {task_config['schedule']}")
        print()
    
    print("=" * 80)
    print("WEEKLY SCHEDULE OVERVIEW:")
    print("=" * 80)
    print("""
    DAILY (Mon-Fri)
    └── 9:00 AM   📧 Daily review reminder: "Review yesterday's hours"
    
    SUNDAY     
    ├── Week ends (users can now submit)
    └── 12:00 AM  🧹 Cleanup notification dismissals
    
    MONDAY     
    ├── 1:00 AM   Create DRAFT timesheets for new week
    ├── 9:00 AM   📧 Reminder: "Submit your timesheet!"
    └── 9:30 AM   📊 Weekly summary emails
    
    TUESDAY    
    ├── 9:00 AM   ⚡ Auto-submit remaining DRAFTs
    └── 10:00 AM  📧 Notify managers of pending approvals
    
    DAILY
    ├── 2:00 AM   🧹 Cleanup old raw events
    └── 6:00 AM   📈 Generate daily summaries
    """)
    print("=" * 80)





