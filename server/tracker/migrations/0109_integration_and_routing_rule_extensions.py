"""
Migration 0109 — Extend Integration and OrgRoutingRule for Axcess sync.

Adds:
- Integration.enforce_matrix: whether to enforce client/task/staff matrix
- Integration.auto_create_internal_records: whether to auto-create internal
  Client/TaskType/User records when external records are encountered
- Integration.last_sync_status / last_sync_error: status tracking
- OrgRoutingRule.source: distinguishes manual rules from synced ones,
  so sync can safely wipe + recreate without touching manual rules

⚠️ ALSO REQUIRES (one-line edit in tracker/models.py — no migration needed):

    class Integration(models.Model):
        PROVIDER_CHOICES = [
            ('quickbooks', 'QuickBooks Online'),
            ('xero', 'Xero'),
            ('karbon', 'Karbon'),
            ('cch_axcess', 'CCH Axcess Practice'),  # ← ADD THIS
        ]

    class OrgRoutingRule(models.Model):
        MATCH_TYPE_CHOICES = [
            # ... existing choices ...
            ('task_type_matrix', 'TaskType Matrix Rule'),  # ← ADD THIS
        ]

Since PROVIDER_CHOICES and MATCH_TYPE_CHOICES are just CharField choices,
they don't need a migration — Django doesn't track choices in the DB schema.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0108_external_mappings'),
    ]

    operations = [
        # ─── Integration extensions ───
        migrations.AddField(
            model_name='integration',
            name='enforce_matrix',
            field=models.BooleanField(
                default=False,
                help_text='If True, the validator enforces the client/task/staff matrix '
                          'rules synced from this integration. If False, matrix rules are '
                          'advisory only (logged but not blocking).',
            ),
        ),
        migrations.AddField(
            model_name='integration',
            name='auto_create_internal_records',
            field=models.BooleanField(
                default=True,
                help_text='If True, sync will auto-create internal Client / TaskType records '
                          'when it encounters external records that have no mapping. '
                          'If False, sync will skip unmapped records and log them.',
            ),
        ),
        migrations.AddField(
            model_name='integration',
            name='last_sync_status',
            field=models.CharField(
                blank=True, default='', max_length=32,
                help_text='Result of last sync: success, partial, failed.',
            ),
        ),
        migrations.AddField(
            model_name='integration',
            name='last_sync_error',
            field=models.TextField(blank=True, default=''),
        ),

        # ─── OrgRoutingRule.source ───
        migrations.AddField(
            model_name='orgroutingrule',
            name='source',
            field=models.CharField(
                choices=[
                    ('manual', 'Manual'),
                    ('default_seed', 'Default Seed'),
                    ('cch_axcess_sync', 'CCH Axcess Sync'),
                ],
                default='manual',
                max_length=32,
                help_text='How this rule was created. Synced rules are managed by the '
                          'integration and should not be manually edited — they get wiped '
                          'and recreated on each sync.',
            ),
        ),
        migrations.AddIndex(
            model_name='orgroutingrule',
            index=models.Index(
                fields=['org', 'source'],
                name='tracker_routing_src_idx',
            ),
        ),
    ]