import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """New tables only — safe in the gap between Render deploying and migrating."""

    dependencies = [
        ('tracker', '0189_block_filing_log'),
    ]

    operations = [
        migrations.CreateModel(
            name='QbtPushSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('push_trigger', models.CharField(choices=[('off', 'Only when an admin sends it'), ('approve', 'When a manager approves the timesheet')], default='off', max_length=16)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='qbt_push_settings', to='tracker.integration')),
            ],
        ),
        migrations.CreateModel(
            name='QbtTimesheetPush',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timesheet_id', models.PositiveIntegerField()),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Sending to QuickBooks Time'), ('done', 'Sent'), ('failed', 'Failed')], default='queued', max_length=16)),
                ('result', models.JSONField(blank=True, default=dict, help_text='Counts, skips and errors from the last push, for display.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='qbt_timesheet_pushes', to='tracker.integration')),
            ],
            options={
                'unique_together': {('integration', 'timesheet_id')},
            },
        ),
    ]
