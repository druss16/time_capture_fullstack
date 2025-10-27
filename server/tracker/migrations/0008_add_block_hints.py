# tracker/migrations/0008_add_block_hints.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0007_block_attendees_block_category_hours_block_day_and_more"),  # ← use your exact 0007 filename basename
    ]

    operations = [
        migrations.AddField(
            model_name="block",
            name="hints",
            field=models.JSONField(default=dict, blank=True, null=True),
        ),
    ]
