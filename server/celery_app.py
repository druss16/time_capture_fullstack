# server/celery_app.py
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "timeserver.settings")
app = Celery("timeserver")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Use simple in-memory scheduler (not django_celery_beat)
app.conf.beat_scheduler = 'celery.beat:PersistentScheduler'

app.conf.beat_schedule = {
    'auto-compact-every-10-minutes': {
        'task': 'tracker.tasks.auto_compact_recent_events',
        'schedule': crontab(minute='*/10'),  # Every 10 minutes
    },
}