"""
Migration 0154 — where an asynchronous Clio push reports back.

Pushing moved off the approval request. A fifty-attorney week is a thousand-plus
writes against a fifty-per-minute ceiling — roughly twenty minutes, which no
proxy holds open. The approval now returns immediately and the push runs on a
worker, so its outcome needs somewhere to live.

Additive and defaulted, so it can be applied before the code deploys.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0153_accuracy_sample_dimensions'),
    ]

    operations = [
        migrations.AddField(
            model_name='timesheet',
            name='clio_push_status',
            field=models.CharField(
                blank=True, default='', max_length=16,
                choices=[
                    ('', 'Not pushed'), ('queued', 'Queued'),
                    ('running', 'Sending to Clio'), ('done', 'Sent'),
                    ('failed', 'Failed'),
                ],
            ),
        ),
        migrations.AddField(
            model_name='timesheet',
            name='clio_push_result',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Counts, skips and errors from the last push, for display.',
            ),
        ),
    ]
