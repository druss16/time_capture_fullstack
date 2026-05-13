"""
Migration 0107 — Seed default TaskTypeSet "Standard" for existing orgs.

For each org that has TaskType rows, creates a TaskTypeSet named "Standard"
(is_default=True) containing all currently-active TaskTypes. This makes
the new resolver behavior identical to "use any TaskType the firm has"
for existing customers — no behavior change until they edit.

Safe to run multiple times (idempotent).
"""

from django.db import migrations


def seed_default_sets(apps, schema_editor):
    Organization = apps.get_model('tracker', 'Organization')
    TaskType = apps.get_model('tracker', 'TaskType')
    TaskTypeSet = apps.get_model('tracker', 'TaskTypeSet')
    TaskTypeSetMember = apps.get_model('tracker', 'TaskTypeSetMember')

    for org in Organization.objects.all():
        active_types = list(TaskType.objects.filter(org=org, is_active=True).order_by('sort_order', 'name'))
        if not active_types:
            continue

        # Idempotent: skip if a Standard set already exists for this org
        if TaskTypeSet.objects.filter(org=org, name='Standard').exists():
            continue

        # If org already has a default set, leave it alone
        if TaskTypeSet.objects.filter(org=org, is_default=True).exists():
            continue

        ts = TaskTypeSet.objects.create(
            org=org,
            name='Standard',
            description='Default firm-wide TaskType list (seeded from existing TaskTypes).',
            is_default=True,
            source='seed',
        )

        for idx, tt in enumerate(active_types):
            TaskTypeSetMember.objects.create(
                set=ts,
                task_type=tt,
                sort_order=idx * 10,
            )


def reverse_seed(apps, schema_editor):
    """Delete only sets created by this migration (source='seed')."""
    TaskTypeSet = apps.get_model('tracker', 'TaskTypeSet')
    TaskTypeSet.objects.filter(source='seed', name='Standard').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0106_task_type_sets'),
    ]

    operations = [
        migrations.RunPython(seed_default_sets, reverse_seed),
    ]