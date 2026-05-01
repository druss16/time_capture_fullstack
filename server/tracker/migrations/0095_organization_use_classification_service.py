"""
Add Organization.use_classification_service feature flag.

This flag gates whether an org's blocks flow through the new
ClassificationService (built in classification-rebuild-phase-1-foundation)
or the legacy BlockClassifier path.

Default: False (legacy path) — no behavioral change on migrate.
Per-org enablement happens via:
    Organization.objects.filter(id=N).update(use_classification_service=True)

This is the foundation for the 5-step wire-up of ClassificationService into
production code paths. The field starts off everywhere; later commits add the
flag-gated branches in views.py / tasks.py / signals.py.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0094_userworkpattern_wipe'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='use_classification_service',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When True, this org uses the new ClassificationService pipeline '
                    '(state machine, contradiction detection, audit trail). '
                    'When False (default), uses the legacy BlockClassifier path.'
                ),
            ),
        ),
    ]