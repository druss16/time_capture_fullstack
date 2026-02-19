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
    
    # =========================================================================
    # DAILY NOTIFICATIONS (Mon-Fri)
    # =========================================================================
    
    # ✅ DAILY 9:00 AM (Mon-Fri): Review yesterday's hours
    # "You have 6.5 hours from yesterday to review"
    'daily-timesheet-review-reminder': {
        'task': 'tracker.tasks.send_daily_timesheet_reminders_task',
        'schedule': crontab(hour=9, minute=0, day_of_week='1-5'),  # Mon-Fri 9am
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