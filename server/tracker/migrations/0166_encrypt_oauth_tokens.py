"""Encrypt the columns that hold OAuth credentials.

Field-class change only: EncryptedTextField is a TextField underneath, so the
column type does not change and no data moves here. Existing rows stay
plaintext and are still readable — crypto_fields.decrypt() returns anything
without the Fernet prefix untouched.

Converting them is a separate, resumable step:

    python manage.py encrypt_stored_tokens            # report
    python manage.py encrypt_stored_tokens --apply    # rewrite

Set TOKEN_ENCRYPTION_KEYS before running it, or the rewrite is a no-op.
"""
from django.db import migrations

import tracker.crypto_fields


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0165_drop_billing_decision'),
    ]

    operations = [
        migrations.AlterField(
            model_name='integration',
            name='access_token',
            field=tracker.crypto_fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name='integration',
            name='refresh_token',
            field=tracker.crypto_fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name='userintegration',
            name='access_token',
            field=tracker.crypto_fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name='userintegration',
            name='refresh_token',
            field=tracker.crypto_fields.EncryptedTextField(blank=True),
        ),
    ]
