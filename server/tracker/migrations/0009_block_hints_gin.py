# tracker/migrations/0009_block_hints_gin.py
from django.db import migrations

class Migration(migrations.Migration):
    atomic = False  # required for CONCURRENTLY

    dependencies = [
        ("tracker", "0008_add_block_hints"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS block_hints_gin
                ON tracker_block
                USING GIN ((hints::jsonb));
            """,
            reverse_sql="""
                DROP INDEX CONCURRENTLY IF EXISTS block_hints_gin;
            """,
        ),
    ]
