"""
Migration 0151 — when time reaches Clio.

Manager approval is a firm's control over what gets billed. Pushing at submit
hands unreviewed time straight to Clio and bypasses that control — fine for a
solo practitioner, wrong for a firm where a partner reviews an associate's week.

Defaults to 'approve': the safe default is the one that respects the control,
and firms wanting speed opt out knowingly. It also avoids the retraction
problem — a rejected timesheet whose time is already in Clio means deleting
billing records.

Additive and defaulted, so it can be applied before the code deploys.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0150_matter_disambiguation_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='clio_push_trigger',
            field=models.CharField(
                default='approve', max_length=16,
                choices=[
                    ('approve', 'When a manager approves the timesheet'),
                    ('submit', 'As soon as the person submits it'),
                ],
                help_text='When captured time is written to Clio. "approve" keeps manager '
                          'review as the gate on what reaches the billing system.',
            ),
        ),
    ]
