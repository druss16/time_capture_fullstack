from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0135_costtier_bill_rate"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="capacity_hours_per_week",
            field=models.DecimalField(
                max_digits=5, decimal_places=2, default=Decimal("40.00"),
                help_text=(
                    "Available working hours per week per employee (firm-wide default). "
                    "Denominator for capacity-based utilization = billable / available. "
                    "Overridden per tier by CostTier.hours_per_week."
                ),
            ),
        ),
        migrations.AddField(
            model_name="costtier",
            name="hours_per_week",
            field=models.DecimalField(
                max_digits=5, decimal_places=2, null=True, blank=True,
                help_text=(
                    "Available working hours per week for this tier (capacity). Drives "
                    "capacity-based utilization. Null -> use org capacity_hours_per_week."
                ),
            ),
        ),
    ]
