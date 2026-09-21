from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Rename the MailSignal.direction display labels: Received/Sent → Inbound/Outbound.

    Labels only — no column, no data, no index changes. The stored values stay
    'in' and 'out'. 'Sent' read like the name of a mail folder and a customer's
    IT took it as evidence we were reading Sent Items; we only ever read the
    Inbox, and direction comes off the message headers.
    """

    dependencies = [
        ('tracker', '0171_null_client_created_at_backfill'),
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
