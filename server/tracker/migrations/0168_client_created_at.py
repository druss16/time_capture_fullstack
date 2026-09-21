"""Record when a client first appeared here.

Additive and nullable, so it is backward compatible with the currently running
code and safe to apply before a deploy.

NOTHING IS BACKFILLED, deliberately. The field exists to answer "was this block
captured before we knew the client existed?" — stamping existing rows with
now() would make every legacy client look brand new, every historical block
look like it predates its own client, and the answer come back as a disaster
that never occurred. Existing rows stay NULL, meaning "predates this field",
and queries must exclude nulls rather than coalesce them.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0167_clio_webhook'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='created_at',
            field=models.DateTimeField(
                auto_now_add=True, null=True,
                help_text='When this client first appeared here. NULL means '
                          '"unknown" — see the note below; never read a NULL '
                          'as a date.',
            ),
        ),
    ]
