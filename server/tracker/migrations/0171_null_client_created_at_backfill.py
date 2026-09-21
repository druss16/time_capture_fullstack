"""Undo the timestamp 0168 wrote onto every pre-existing client.

WHAT WENT WRONG
---------------
0168 added Client.created_at as `DateTimeField(auto_now_add=True, null=True)`
and stated in its own docstring that existing rows would stay NULL. They did
not. All 408 production clients came out carrying one identical timestamp —
the instant the migration ran, to the microsecond.

`null=True` governs what the COLUMN permits. It does not govern what AddField
writes into existing rows. Django's schema editor computes a value for those
rows via `effective_default()`, which has an explicit branch for auto_now /
auto_now_add fields returning `datetime.now()`. So auto_now_add silently
overrides the intent: the field is nullable, and the backfill fills it anyway.

WHY THIS MATTERED ENOUGH TO FIX IMMEDIATELY
-------------------------------------------
The field exists to answer "was this block captured before we knew the client
existed?". With every legacy client claiming to be seconds old, every
historical block predates its own client, and the answer comes back as a
catastrophe that never happened. That is worse than having no field at all,
because a wrong date reads as evidence. 0168's docstring says exactly this,
which is the irony of it.

WHAT THIS DOES
--------------
Sets those rows back to NULL, meaning "predates this field".

Targeted rather than blanket: it nulls only timestamps SHARED BY MORE THAN ONE
row. A backfill stamps every row from a single `datetime.now()` call, so those
rows are identical to the microsecond; clients created normally each get their
own call and never collide. That way an environment applying this later does
not lose dates it legitimately collected in between.

New rows are unaffected — auto_now_add still populates them correctly on
insert. The bug was only ever in the one-time backfill, and a fresh database
never sees it, because the table is empty when 0168 runs.
"""
from django.db import migrations
from django.db.models import Count


def null_backfilled_timestamps(apps, schema_editor):
    Client = apps.get_model('tracker', 'Client')

    shared = (
        Client.objects
        .filter(created_at__isnull=False)
        .values('created_at')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .values_list('created_at', flat=True)
    )
    stamps = list(shared)
    if not stamps:
        return

    updated = Client.objects.filter(created_at__in=stamps).update(created_at=None)
    print(f'  cleared {updated} backfilled created_at value(s) '
          f'across {len(stamps)} shared timestamp(s)')


def noop_reverse(apps, schema_editor):
    """Irreversible in substance — the original values were never real."""


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0170_merge_client_created_at'),
    ]

    operations = [
        migrations.RunPython(null_backfilled_timestamps, noop_reverse),
    ]
