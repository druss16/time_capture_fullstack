"""
Migration 0155 — reconcile ExternalMatterMapping with what Django expects.

0147 was written by hand and drifted from the model in two ways: it named the
indexes explicitly while Meta.indexes leaves naming to Django, and it declared
`id` as AutoField while this project's DEFAULT_AUTO_FIELD is BigAutoField.

Neither breaks anything, but every `makemigrations` from now on would offer to
generate this, and a warning that is always present is a warning nobody reads —
including the one time it means something.

Cheap to apply: index renames are metadata, and the primary key widening touches
a table holding one row per matter per firm.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0154_timesheet_clio_push_status'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='externalmattermapping',
            new_name='tracker_ext_integra_85fd4f_idx',
            old_name='tracker_extmatter_int_ext_idx',
        ),
        migrations.RenameIndex(
            model_name='externalmattermapping',
            new_name='tracker_ext_project_cf94c8_idx',
            old_name='tracker_extmatter_proj_idx',
        ),
        migrations.AlterField(
            model_name='externalmattermapping',
            name='id',
            field=models.BigAutoField(
                auto_created=True, primary_key=True,
                serialize=False, verbose_name='ID',
            ),
        ),
    ]
