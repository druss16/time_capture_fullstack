from django.db import migrations, models


def enable_for_pilot_org(apps, schema_editor):
    """Turn Stage Sandwich on for org 21 (TL Wall Accounting), the pilot firm.
    No-ops in any environment where org 21 doesn't exist (dev/staging)."""
    Organization = apps.get_model('tracker', 'Organization')
    Organization.objects.filter(id=21).update(sandwich_correlation_enabled=True)


def disable_for_pilot_org(apps, schema_editor):
    Organization = apps.get_model('tracker', 'Organization')
    Organization.objects.filter(id=21).update(sandwich_correlation_enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0123_orgreportpreset'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='sandwich_correlation_enabled',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Enable Stage Sandwich (temporal fallback attribution). When a '
                    'block has no client signal but is tightly bracketed in time by '
                    'blocks attributed to the SAME client, propose that client. '
                    'Never auto-commits — always surfaces as a proposal for human '
                    'review.'
                ),
            ),
        ),
        migrations.RunPython(enable_for_pilot_org, disable_for_pilot_org),
    ]
