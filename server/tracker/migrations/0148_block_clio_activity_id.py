"""
Migration 0148 — Block.clio_activity_id.

Records which Clio Activity a block's time has been reflected in. Audit trail
only: push computes a delta from (user, matter, day) totals rather than from
this flag, so a day that was partly pushed stays correct on re-run.

⚠️ ORDERING: Block is a large, hot table. This column is additive with a
default, so it is backward-compatible with the currently-running code — apply
it BEFORE the new code deploys and the 500-window is zero. Applying it after
the deploy breaks every Block query for every org.

Deliberately NO index. The column is only read inside an org+date-window slice
that existing indexes already cover, and building an index on a table this size
would take a lock on deploy for no query benefit.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0147_clio_integration'),
    ]

    operations = [
        migrations.AddField(
            model_name='block',
            name='clio_activity_id',
            field=models.CharField(
                blank=True, default='', max_length=64,
                help_text='Clio Activity (TimeEntry) this block has been reflected in. '
                          'Audit trail only — push computes a delta from day totals '
                          'rather than from this flag, so a day that was partly pushed '
                          'stays correct on the next run.',
            ),
        ),
    ]
