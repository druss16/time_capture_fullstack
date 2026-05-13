"""
Migration 0106 — TaskType Sets and per-Client overrides.

⚠️ BEFORE APPLYING:
    Run: python manage.py showmigrations tracker | tail -5
    Confirm the last applied migration is '0105_alter_rawevent_options_and_more'.
    If different, update the `dependencies` line below to match.

This migration:
1. Creates TaskTypeSet (named bundle of TaskTypes)
2. Creates TaskTypeSetMember (through-model for ordering)
3. Creates ClientTaskType (per-client overrides)
4. Adds Client.default_task_type_set FK (nullable)

No data is modified. Existing TaskType rows are untouched.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        # ⚠️ VERIFY: change to your actual latest migration if not 0105
        ('tracker', '0105_alter_rawevent_options_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TaskTypeSet',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.CharField(blank=True, default='', max_length=255)),
                ('is_default', models.BooleanField(
                    default=False,
                    help_text='If True, this set is the firm-wide default for clients that have no specific default_task_type_set assigned.',
                )),
                ('source', models.CharField(
                    choices=[
                        ('manual', 'Manual'),
                        ('cch_axcess_sync', 'CCH Axcess Sync'),
                        ('seed', 'Seeded from default'),
                    ],
                    default='manual',
                    max_length=32,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='task_type_sets_created',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('org', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_type_sets',
                    to='tracker.organization',
                )),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='TaskTypeSetMember',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sort_order', models.IntegerField(default=0)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('set', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='members',
                    to='tracker.tasktypeset',
                )),
                ('task_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='set_memberships',
                    to='tracker.tasktype',
                )),
            ],
            options={
                'ordering': ['sort_order', 'task_type__name'],
            },
        ),
        migrations.AddField(
            model_name='tasktypeset',
            name='task_types',
            field=models.ManyToManyField(
                related_name='in_sets',
                through='tracker.TaskTypeSetMember',
                to='tracker.tasktype',
            ),
        ),
        migrations.AddConstraint(
            model_name='tasktypeset',
            constraint=models.UniqueConstraint(
                fields=('org', 'name'),
                name='unique_tasktypeset_per_org',
            ),
        ),
        migrations.AddConstraint(
            model_name='tasktypesetmember',
            constraint=models.UniqueConstraint(
                fields=('set', 'task_type'),
                name='unique_member_per_set',
            ),
        ),
        migrations.AddIndex(
            model_name='tasktypeset',
            index=models.Index(
                fields=['org', 'is_default'],
                name='tracker_tt_set_org_def_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='tasktypesetmember',
            index=models.Index(
                fields=['set', 'sort_order'],
                name='tracker_tt_set_mem_idx',
            ),
        ),

        # ─── ClientTaskType ───
        migrations.CreateModel(
            name='ClientTaskType',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('allowed', models.BooleanField(
                    default=True,
                    help_text='True = explicitly allow this TaskType for this client. False = explicitly forbid even if in default set.',
                )),
                ('override_rate', models.DecimalField(
                    blank=True,
                    decimal_places=2,
                    help_text='If set, overrides TaskType.default_rate for this client.',
                    max_digits=10,
                    null=True,
                )),
                ('source', models.CharField(
                    choices=[
                        ('manual', 'Manual'),
                        ('cch_axcess_sync', 'CCH Axcess Sync'),
                    ],
                    default='manual',
                    max_length=32,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='task_type_overrides',
                    to='tracker.client',
                )),
                ('task_type', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='client_overrides',
                    to='tracker.tasktype',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='client_task_types_created',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['task_type__sort_order', 'task_type__name'],
            },
        ),
        migrations.AddConstraint(
            model_name='clienttasktype',
            constraint=models.UniqueConstraint(
                fields=('client', 'task_type'),
                name='unique_client_task_type',
            ),
        ),
        migrations.AddIndex(
            model_name='clienttasktype',
            index=models.Index(
                fields=['client', 'allowed'],
                name='tracker_cli_tt_allow_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='clienttasktype',
            index=models.Index(
                fields=['source'],
                name='tracker_cli_tt_src_idx',
            ),
        ),

        # ─── Client.default_task_type_set ───
        migrations.AddField(
            model_name='client',
            name='default_task_type_set',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='clients_using_as_default',
                to='tracker.tasktypeset',
            ),
        ),
    ]