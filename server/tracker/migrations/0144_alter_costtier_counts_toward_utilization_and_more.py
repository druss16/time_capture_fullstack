"""Align CostTier.counts_toward_utilization / target_utilization migration state
with the model's help_text (0139/0140 used slightly reworded text to dodge
special characters). No schema change — clears the makemigrations drift warning.

Named to match the migration Django's makemigrations produced and that was
already applied to the database, so the file and the recorded state agree.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0143_workcalendar_avg_pto'),
    ]

    operations = [
        migrations.AlterField(
            model_name='costtier',
            name='counts_toward_utilization',
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Whether members in this tier are chargeable staff who count toward "
                    "firm utilization. Turn OFF for non-billing roles (admin, ops, "
                    "non-charging partners) so their capacity doesn't drag the firm number "
                    "down. Excluded members are still shown, just separated out."
                ),
            ),
        ),
        migrations.AlterField(
            model_name='costtier',
            name='target_utilization',
            field=models.DecimalField(
                max_digits=5, decimal_places=2, null=True, blank=True,
                help_text=(
                    "Expected billable utilization % for this tier (cohort target). "
                    "Staff carry a higher target than managers/partners; the by-tier "
                    "view measures variance-to-target so a partner at 30% reads as "
                    "on-target, not underperforming. Null → org target_utilization."
                ),
            ),
        ),
    ]
