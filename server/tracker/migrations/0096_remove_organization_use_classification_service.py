"""
Drop the now-unused Organization.use_classification_service field.

Background:
- This field was added in migration 0095 as a feature flag for the
  ClassificationService rollout.
- Step 4 of the wire-up plan removed all callers of the flag — every
  classification path now goes through ClassificationService unconditionally.
- The field has no remaining callers as of Step 5b. Removing the column
  is pure cleanup.

This migration is reversible (the reverse adds the column back with
default=False, so re-applying 0095 wouldn't conflict with any data).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0095_organization_use_classification_service'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='organization',
            name='use_classification_service',
        ),
    ]