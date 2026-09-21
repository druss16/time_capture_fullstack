from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Rename the MailSignal.direction display labels: Received/Sent → Inbound/Outbound.

    Labels only — no column, no data, no index changes. The stored values stay
    'in' and 'out'. 'Sent' read like the name of a mail folder and a customer's
    IT took it as evidence we were reading Sent Items; we only ever read the
    Inbox, and direction comes off the message headers.

    This also closes a fork in the migration graph: 0167_clio_webhook had grown
    TWO children on main (0168_client_created_at from one PR, and
    0168_drop_agent_registration → 0169_drop_org_install_token from another),
    which leaves Django with multiple leaf nodes and makes `migrate` refuse to
    run at all. Depending on both leaves rejoins them.
    """

    dependencies = [
        ('tracker', '0168_client_created_at'),
        ('tracker', '0169_drop_org_install_token'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mailsignal',
            name='direction',
            field=models.CharField(
                choices=[('in', 'Inbound'), ('out', 'Outbound')],
                max_length=10,
            ),
        ),
    ]
