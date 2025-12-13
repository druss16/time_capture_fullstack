# timeserver/celery.py
"""
Celery configuration for TimeTracker background tasks.

Includes:
- Block compaction and AI classification (every 5 min)
- Timesheet workflow (weekly reminders, auto-submit, manager notifications)
- Maintenance (cleanup, daily summaries)
"""

import os
from celery import Celery
from celery.schedules import crontab

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
    # MAINTENANCE (Daily)
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
    
    # Group tasks by category for cleaner output
    categories = {
        'BLOCK PROCESSING': ['auto-compact', 'ai-classify'],
        'TIMESHEET WORKFLOW': ['timesheet', 'create-weekly', 'notify-managers'],
        'MAINTENANCE': ['cleanup', 'summary'],
    }
    
    for task_name, task_config in sorted(app.conf.beat_schedule.items()):
        print(f"  ✓ {task_name}")
        print(f"    Task: {task_config['task']}")
        print(f"    Schedule: {task_config['schedule']}")
        print()
    
    print("=" * 80)
    print("WEEKLY TIMESHEET WORKFLOW:")
    print("=" * 80)
    print("""
    SUNDAY     Week ends (users can now submit)
    
    MONDAY     
    ├── 1:00 AM   Create DRAFT timesheets for new week
    └── 9:00 AM   📧 Reminder: "Submit your timesheet!"
    
    TUESDAY    
    ├── 9:00 AM   ⚡ Auto-submit remaining DRAFTs
    └── 10:00 AM  📧 Notify managers of pending approvals
    """)
    print("=" * 80)