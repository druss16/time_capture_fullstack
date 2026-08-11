from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0138_organization_show_client_widget'),
    ]

    operations = [
        migrations.AddField(
            model_name='costtier',
            name='counts_toward_utilization',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'Whether members in this tier are chargeable staff who count '
                    'toward firm utilization. Turn OFF for non-billing roles '
                    '(admin, ops, non-charging partners) so their capacity does '
                    "not drag the firm number down. Excluded members are still "
                    'shown, just separated out.'
                ),
            ),
        ),
    ]
