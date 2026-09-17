"""Does every scheduled task exist on the worker?

tasks_mail.py went four months sending five-minute messages into a worker
that had never imported it — autodiscover_tasks() only walks each app's
`tasks` module, so the task names were not in the registry and every message
was discarded as unregistered. Nothing surfaced it: beat logged a successful
send, the enqueueing web process had the module imported so .delay() returned
cleanly, and the fields that would have shown a problem are written by the
task itself.

The mismatch is cheap to detect, so detect it — at worker startup, and in CI.
"""
import logging

logger = logging.getLogger(__name__)


def scheduled_task_names(app):
    """
    Task names the schedule will send, by where they are scheduled.

    Two sources, because both can fire: the PeriodicTask table is the live
    schedule under DatabaseScheduler, and app.conf.beat_schedule is what the
    code declares. A name in either one must be runnable.

    The database is consulted only if it answers — this runs in CI, where
    there is no database, and a missing one must not mask the check of the
    declared schedule.
    """
    sources = {}

    for entry in (app.conf.beat_schedule or {}).values():
        task = entry.get('task') if isinstance(entry, dict) else getattr(entry, 'task', None)
        if task:
            sources.setdefault(task, set()).add('celery_app.py')

    try:
        from django_celery_beat.models import PeriodicTask
        for task in PeriodicTask.objects.filter(enabled=True).values_list('task', flat=True):
            if task:
                sources.setdefault(task, set()).add('PeriodicTask')
    except Exception as exc:  # no database, app not installed, table absent
        logger.debug(f"[BEAT-CHECK] Skipping PeriodicTask rows: {exc}")

    return sources


def unregistered_scheduled_tasks(app):
    """
    {task name: sorted sources} for scheduled tasks this process cannot run.

    import_default_modules() forces the autodiscovery this is here to audit,
    so the registry read afterwards is the one a worker would use.
    """
    scheduled = scheduled_task_names(app)
    app.loader.import_default_modules()
    registered = set(app.tasks)
    return {
        name: sorted(sources)
        for name, sources in sorted(scheduled.items())
        if name not in registered
    }
