from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0131_clientbillingprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='target_utilization',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('75.00'),
                help_text=(
                    'Target billable utilization %, the benchmark for the Utilization KPI. '
                    'Firm-wide default; drives the good/watch/bad band on the analytics dashboard.'
                ),
                max_digits=5,
            ),
        ),
    ]
