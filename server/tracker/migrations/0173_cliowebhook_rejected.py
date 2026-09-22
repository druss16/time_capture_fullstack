"""Count callbacks we refused.

A rejected callback and a callback that never arrived both showed as
events_received == 0 with an empty last_error — identical from the outside,
opposite in cause. One means Clio is not sending; the other means Clio IS
sending and we are refusing to verify it, which is worse precisely because it
presents as silence.

Numbered 0173, not 0172: 0172_mailsignal_direction_labels landed on main while
this branch was open. Migration numbers are a shared namespace and concurrent
branches cannot see each other — rebase and check the number is free before
opening a PR, or the next person gets a graph with two leaves and no migration
runs at all until someone merges them.

Additive and defaulted, so it is backward compatible with the running code.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0172_mailsignal_direction_labels'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliowebhook',
            name='rejected_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='cliowebhook',
            name='last_rejected_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
