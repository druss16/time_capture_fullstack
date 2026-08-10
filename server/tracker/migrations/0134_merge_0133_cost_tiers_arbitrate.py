from django.db import migrations


class Migration(migrations.Migration):
    """Merge the two 0133 leaves that were authored in parallel off 0132:
      - 0133_cost_tiers (analytics cost tiers)
      - 0133_organization_arbitrate_disagreements
    Both are additive with no overlapping fields, so this merge is a no-op join.
    """

    dependencies = [
        ('tracker', '0133_cost_tiers'),
        ('tracker', '0133_organization_arbitrate_disagreements'),
    ]

    operations = []
