from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0139_costtier_counts_toward_utilization'),
    ]

    operations = [
        migrations.AddField(
            model_name='costtier',
            name='target_utilization',
            field=models.DecimalField(
                max_digits=5, decimal_places=2, null=True, blank=True,
                help_text=(
                    'Expected billable utilization % for this tier (cohort '
                    'target). Staff carry a higher target than managers/'
                    'partners; the by-tier view measures variance-to-target so '
                    'a partner at 30% reads as on-target, not underperforming. '
                    'Null uses the org target_utilization.'
                ),
            ),
        ),
    ]
