# tracker/migrations/0058_add_integration_sync_fields.py

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0057_alter_userworkpattern_pattern_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='block',
            name='qb_time_activity_id',
            field=models.CharField(
                max_length=64, blank=True, null=True, db_index=True,
                help_text='QuickBooks TimeActivity ID after push',
            ),
        ),
        migrations.AddField(
            model_name='block',
            name='xero_invoice_id',
            field=models.CharField(
                max_length=64, blank=True, null=True, db_index=True,
                help_text='Xero Invoice ID after push',
            ),
        ),
    ]