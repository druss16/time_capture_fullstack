from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0134_merge_0133_cost_tiers_arbitrate"),
    ]

    operations = [
        migrations.AddField(
            model_name="costtier",
            name="bill_rate",
            field=models.DecimalField(
                max_digits=10, decimal_places=2, null=True, blank=True,
                help_text=(
                    "Standard hourly BILL rate for this tier (what the client is charged). "
                    "Used as a revenue fallback when a block/client has no explicit rate, "
                    "before the org default. Null -> use org billing_rate_default."
                ),
            ),
        ),
    ]
