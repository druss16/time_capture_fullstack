"""Clio webhook subscriptions — one row per (firm, watched model).

Creates the table only. No subscription is registered by this migration:
registration needs a live Clio token and a publicly reachable callback URL,
so it happens when a firm connects (or on the next nightly renewal pass for
firms already connected).

Safe to apply while the old manual-sync-only path is running — nothing reads
this table until the webhook code is deployed.
"""
from django.db import migrations, models
import django.db.models.deletion

import tracker.crypto_fields


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0166_encrypt_oauth_tokens'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClioWebhook',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('model', models.CharField(
                    choices=[('contact', 'Contact'), ('matter', 'Matter')],
                    max_length=32)),
                ('external_id', models.CharField(
                    blank=True, db_index=True, default='', max_length=64)),
                ('url_token', models.CharField(
                    db_index=True, max_length=64, unique=True)),
                ('shared_secret', tracker.crypto_fields.EncryptedTextField(
                    blank=True, default='')),
                ('handshake_secret', tracker.crypto_fields.EncryptedTextField(
                    blank=True, default='')),
                ('status', models.CharField(
                    choices=[('pending', 'Pending handshake'), ('active', 'Active'),
                             ('failed', 'Failed'), ('expired', 'Expired')],
                    db_index=True, default='pending', max_length=16)),
                ('expires_at', models.DateTimeField(
                    blank=True, null=True,
                    help_text='When Clio stops delivering. Renewed nightly well '
                              'ahead of this.')),
                ('last_event_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('events_received', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='clio_webhooks', to='tracker.integration')),
            ],
        ),
        migrations.AddIndex(
            model_name='cliowebhook',
            index=models.Index(fields=['status', 'expires_at'],
                               name='tracker_cli_status_aff867_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='cliowebhook',
            unique_together={('integration', 'model')},
        ),
    ]
