"""
Migration 0108 — External system mappings.

Creates three mapping tables hanging off the existing Integration model:
- ExternalClientMapping: Client ↔ external client ID
- ExternalTaskTypeMapping: TaskType ↔ external service code
- ExternalStaffMapping: User ↔ external staff ID

These tables are provider-agnostic — the same schema serves CCH Axcess,
QuickBooks, Xero, Karbon, etc. The provider is implicit via the
integration FK.

For QuickBooks/Xero, the existing Client.quickbooks_id and Client.xero_id
fields remain as legacy convenience accessors. New code should prefer
ExternalClientMapping going forward.
"""

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0107_seed_default_task_type_sets'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ─── ExternalClientMapping ───
        migrations.CreateModel(
            name='ExternalClientMapping',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.CharField(db_index=True, max_length=128)),
                ('external_code', models.CharField(
                    blank=True, default='', max_length=64,
                    help_text='Human-readable code if different from external_id.',
                )),
                ('external_name', models.CharField(blank=True, default='', max_length=255)),
                ('external_status', models.CharField(blank=True, default='', max_length=32)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_in_source', models.DateTimeField(
                    blank=True, null=True,
                    help_text='Last time this record was returned by the source API. '
                              'Stale records (not seen in >30 days) are candidates for archival.',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='external_mappings',
                    to='tracker.client',
                )),
                ('integration', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='client_mappings',
                    to='tracker.integration',
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name='externalclientmapping',
            constraint=models.UniqueConstraint(
                fields=('integration', 'external_id'),
                name='unique_ext_client_external_id',
            ),
        ),
        migrations.AddConstraint(
            model_name='externalclientmapping',
            constraint=models.UniqueConstraint(
                fields=('integration', 'client'),
                name='unique_ext_client_internal',
            ),
        ),
        migrations.AddIndex(
            model_name='externalclientmapping',
            index=models.Index(
                fields=['integration', 'external_id'],
                name='tracker_ext_cli_ext_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='externalclientmapping',
            index=models.Index(
                fields=['client'],
                name='tracker_ext_cli_int_idx',
            ),
        ),

        # ─── ExternalTaskTypeMapping ───
        migrations.CreateModel(
            name='ExternalTaskTypeMapping',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.CharField(db_index=True, max_length=128)),
                ('external_code', models.CharField(blank=True, default='', max_length=64)),
                ('external_name', models.CharField(blank=True, default='', max_length=255)),
                ('external_category', models.CharField(blank=True, default='', max_length=64)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_in_source', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_type_mappings',
                    to='tracker.integration',
                )),
                ('task_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='external_mappings',
                    to='tracker.tasktype',
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name='externaltasktypemapping',
            constraint=models.UniqueConstraint(
                fields=('integration', 'external_id'),
                name='unique_ext_tt_external_id',
            ),
        ),
        migrations.AddConstraint(
            model_name='externaltasktypemapping',
            constraint=models.UniqueConstraint(
                fields=('integration', 'task_type'),
                name='unique_ext_tt_internal',
            ),
        ),
        migrations.AddIndex(
            model_name='externaltasktypemapping',
            index=models.Index(
                fields=['integration', 'external_id'],
                name='tracker_ext_tt_ext_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='externaltasktypemapping',
            index=models.Index(
                fields=['task_type'],
                name='tracker_ext_tt_int_idx',
            ),
        ),

        # ─── ExternalStaffMapping ───
        migrations.CreateModel(
            name='ExternalStaffMapping',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.CharField(db_index=True, max_length=128)),
                ('external_code', models.CharField(blank=True, default='', max_length=64)),
                ('external_name', models.CharField(blank=True, default='', max_length=255)),
                ('external_email', models.EmailField(blank=True, default='', max_length=254)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_in_source', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='staff_mappings',
                    to='tracker.integration',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='external_staff_mappings',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name='externalstaffmapping',
            constraint=models.UniqueConstraint(
                fields=('integration', 'external_id'),
                name='unique_ext_staff_external_id',
            ),
        ),
        migrations.AddConstraint(
            model_name='externalstaffmapping',
            constraint=models.UniqueConstraint(
                fields=('integration', 'user'),
                name='unique_ext_staff_internal',
            ),
        ),
        migrations.AddIndex(
            model_name='externalstaffmapping',
            index=models.Index(
                fields=['integration', 'external_id'],
                name='tracker_ext_st_ext_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='externalstaffmapping',
            index=models.Index(
                fields=['user'],
                name='tracker_ext_st_int_idx',
            ),
        ),
    ]