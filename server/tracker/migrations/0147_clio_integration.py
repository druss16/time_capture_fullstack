"""
Migration 0147 — Clio Manage integration foundation.

Three changes, all additive and backward-compatible:

1. Integration.provider gains 'clio'.
2. Integration.api_region — Clio runs four independent data regions
   (US/CA/EU/AU) whose tokens are not portable between them, so the region
   has to be pinned per firm at connect time. Blank for every existing row
   and for every non-region-partitioned provider.
3. ExternalMatterMapping — Project ↔ Clio matter. Legal time cannot be
   pushed at client granularity: a Clio TimeEntry without a matter id is
   rejected, so matters need a first-class mapping the way clients already
   have one.

No data migration and no backfill: existing QBO/Xero/CCH rows are untouched
and read `api_region` as ''.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0146_engagements_and_wip_relief'),
    ]

    operations = [
        migrations.AlterField(
            model_name='integration',
            name='provider',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('quickbooks', 'QuickBooks Online'),
                    ('xero', 'Xero'),
                    ('karbon', 'Karbon'),
                    ('cch_axcess', 'CCH Axcess Practice'),
                    ('clio', 'Clio Manage'),
                ],
            ),
        ),
        migrations.AlterField(
            model_name='client',
            name='imported_from',
            field=models.CharField(
                blank=True, default='', max_length=20,
                choices=[
                    ('', 'Manual'),
                    ('quickbooks', 'QuickBooks'),
                    ('xero', 'Xero'),
                    ('clio', 'Clio'),
                ],
                help_text='Integration source this client was imported from',
            ),
        ),
        migrations.AddField(
            model_name='integration',
            name='api_region',
            field=models.CharField(
                blank=True, default='', max_length=8,
                choices=[
                    ('us', 'United States'),
                    ('ca', 'Canada'),
                    ('eu', 'European Union'),
                    ('au', 'Australia'),
                ],
                help_text='Data region for region-partitioned providers (Clio). '
                          'Blank means the provider is not region-partitioned.',
            ),
        ),
        migrations.CreateModel(
            name='ExternalMatterMapping',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_id', models.CharField(db_index=True, max_length=128)),
                ('display_number', models.CharField(
                    blank=True, default='', max_length=128,
                    help_text='Human-facing matter number, e.g. "00123-Smith". Appears in '
                              'filenames and window titles, so it is prime alias material.',
                )),
                ('external_name', models.CharField(blank=True, default='', max_length=500)),
                ('external_status', models.CharField(
                    blank=True, default='', max_length=32,
                    help_text='Open / Pending / Closed. Closed matters reject new time.',
                )),
                ('billing_method', models.CharField(
                    blank=True, default='', max_length=32,
                    help_text='hourly / flat / contingency. Time on a flat-fee matter is '
                              'tracked for realization but must not create a billable line.',
                )),
                ('requires_utbms', models.BooleanField(
                    default=False,
                    help_text='Matter mandates UTBMS/LEDES activity + task codes. Pushing '
                              'without them is a 422.',
                )),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('last_seen_in_source', models.DateTimeField(
                    blank=True, null=True,
                    help_text='Last time this matter was returned by the source API. '
                              'Stale records are candidates for archival.',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='matter_mappings',
                    to='tracker.integration',
                )),
                ('project', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='external_mappings',
                    to='tracker.project',
                )),
            ],
            options={
                'unique_together': {
                    ('integration', 'external_id'),
                    ('integration', 'project'),
                },
            },
        ),
        migrations.AddIndex(
            model_name='externalmattermapping',
            index=models.Index(
                fields=['integration', 'external_id'],
                name='tracker_extmatter_int_ext_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='externalmattermapping',
            index=models.Index(
                fields=['project'],
                name='tracker_extmatter_proj_idx',
            ),
        ),
    ]
