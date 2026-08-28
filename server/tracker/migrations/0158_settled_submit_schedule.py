"""Schedule the settled-submit task, and retire the dead Monday auto-submit row.

Beat runs django_celery_beat's DatabaseScheduler, so the live schedule is the
PeriodicTask table — `app.conf.beat_schedule` in celery_app.py is decorative and
a task added only there never fires. Scheduling therefore belongs in a migration,
where it is versioned and repeatable, rather than typed into a shell once.

Two changes:

  · submit-settled-timesheets, nightly. Any draft for a week that has ended goes
    as soon as every day carrying time in it has been reviewed. Tuesday remains
    the backstop for weeks that never settle.

  · timesheet-auto-submit-monday is DISABLED, not deleted. Its task aborts on any
    day but Tuesday, so it has only ever fired and returned — a scheduled job
    that exists to do nothing. Disabling is reversible; a delete would lose the
    crontab if it turns out something depended on the row.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    try:
        from django_celery_beat.models import CrontabSchedule, PeriodicTask
    except Exception:                       # beat not installed in some contexts
        return

    # 02:30 local: after the day has closed and after the Clio nightly at 02:15,
    # so a week that settles tonight is pushed by tomorrow's run rather than
    # racing it.
    cron, _ = CrontabSchedule.objects.get_or_create(
        minute='30', hour='2', day_of_week='*', day_of_month='*',
        month_of_year='*', timezone='America/New_York',
    )
    PeriodicTask.objects.update_or_create(
        name='submit-settled-timesheets',
        defaults={
            'task': 'tracker.submit_settled_timesheets',
            'crontab': cron,
            'enabled': True,
            'description': (
                'Send a closed week as soon as every day with time in it has '
                'been reviewed. Tuesday auto-submit remains the backstop.'
            ),
        },
    )

    PeriodicTask.objects.filter(name='timesheet-auto-submit-monday').update(
        enabled=False,
        description='Disabled: the task aborts on any day but Tuesday, so this '
                    'row only ever fired and returned.',
    )


def backwards(apps, schema_editor):
    try:
        from django_celery_beat.models import PeriodicTask
    except Exception:
        return
    PeriodicTask.objects.filter(name='submit-settled-timesheets').delete()
    PeriodicTask.objects.filter(name='timesheet-auto-submit-monday').update(enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0157_dayreview'),
        ('django_celery_beat', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
