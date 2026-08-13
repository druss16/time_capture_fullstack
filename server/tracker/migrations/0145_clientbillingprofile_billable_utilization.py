from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0144_alter_costtier_counts_toward_utilization_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientbillingprofile',
            name='counts_billable_utilization',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Count this client's time as BILLABLE for utilization "
                    "analytics even though it is not invoiced through the system "
                    "(e.g. tax work billed outside, parked under an Internal "
                    "client). Lifts utilization without touching billing or export."
                ),
            ),
        ),
    ]
