# tracker/migrations/0104_rawevent_dual_timestamps.py
"""
v1.3.38 — Dual-timestamp RawEvent migration.

WHAT
====
Replaces the single `ts_utc` field with `start_ts` and `end_ts` on RawEvent.
Every event now carries its actual interval, eliminating the IDLE_CAP
duration-guessing that capped long dwells (Outlook reads, document review)
at 10 minutes per event.

WHY
===
Compaction can't tell how long a single-timestamp event represents. It has
to guess via gap-walking to the next event, capped at IDLE_CAP=10min. A
30-minute Outlook read becomes 3-4 events of "<=10 min each" instead of
one 30-minute window. With dual timestamps, the agent reports the truth.

ROLLOUT
=======
Hard cutover. v1.3.38 agent sends `start_ts` and `end_ts`. Older agents
get 400'd at the POST endpoint. TL Wall is beta — acceptable.

BACKFILL STRATEGY
=================
Historical events only have `ts_utc`. We backfill conservatively:
  - start_ts = ts_utc
  - end_ts   = ts_utc + 10 seconds
The 10-second window matches AGENT_POLL_SECONDS (5s) plus a small buffer.
This under-counts historical dwells slightly but never invents time.
"""

from django.db import migrations, models


SQL_BACKFILL = """
    UPDATE tracker_rawevent
       SET start_ts = ts_utc,
           end_ts   = ts_utc + INTERVAL '10 seconds'
     WHERE start_ts IS NULL;
"""

SQL_REVERSE = """
    -- No-op: reverse migration drops the columns entirely.
    -- See rollback plan for data preservation steps before reverting.
"""


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0103_block_mail_disagreement_reasoning_and_more"),
    ]

    operations = [
        # 1. Add new fields as nullable so the backfill can populate them.
        migrations.AddField(
            model_name="rawevent",
            name="start_ts",
            field=models.DateTimeField(null=True, db_index=True),
        ),
        migrations.AddField(
            model_name="rawevent",
            name="end_ts",
            field=models.DateTimeField(null=True, db_index=True),
        ),

        # 2. Backfill historical rows (start_ts = ts_utc, end_ts = ts_utc + 10s).
        migrations.RunSQL(SQL_BACKFILL, reverse_sql=SQL_REVERSE),

        # 3. Now that every row has values, enforce NOT NULL.
        migrations.AlterField(
            model_name="rawevent",
            name="start_ts",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="rawevent",
            name="end_ts",
            field=models.DateTimeField(db_index=True),
        ),

        # 4. Composite index for compaction queries
        #    (compact_day filters by user + date range, orders by start_ts).
        migrations.AddIndex(
            model_name="rawevent",
            index=models.Index(
                fields=["user", "start_ts"],
                name="rawevent_user_start_ts_idx",
            ),
        ),

        # 5. Drop the legacy ts_utc field.
        #    Hard cutover: no compat period, no second migration later.
        migrations.RemoveField(
            model_name="rawevent",
            name="ts_utc",
        ),
    ]