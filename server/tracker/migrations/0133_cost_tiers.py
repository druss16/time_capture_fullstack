from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


# Default CPA-style ladder seeded per org. Firms can rename/re-rate/add/delete.
DEFAULT_TIERS = [
    ("Partner", 0),
    ("Manager", 1),
    ("Senior", 2),
    ("Staff", 3),
    ("Admin", 4),
]
# Best-guess seed from the *permission* role. Only a starting point — the tier
# is an independent field the firm corrects afterward.
ROLE_TO_TIER = {
    "owner": "Partner",
    "admin": "Admin",
    "manager": "Manager",
    "member": "Staff",
}


def seed_tiers(apps, schema_editor):
    Organization = apps.get_model("tracker", "Organization")
    CostTier = apps.get_model("tracker", "CostTier")
    Membership = apps.get_model("tracker", "OrganizationMembership")

    for org in Organization.objects.all():
        base = getattr(org, "cost_rate_default", None) or Decimal("75.00")
        tiers = {}
        for label, order in DEFAULT_TIERS:
            tier, _ = CostTier.objects.get_or_create(
                organization=org, label=label,
                defaults={"cost_rate": base, "sort_order": order},
            )
            tiers[label] = tier
        staff = tiers.get("Staff")
        for m in Membership.objects.filter(organization=org):
            m.cost_tier = tiers.get(ROLE_TO_TIER.get(m.role, "Staff"), staff)
            m.save(update_fields=["cost_tier"])


def unseed_tiers(apps, schema_editor):
    # Reverse: drop the FK links; CostTier rows are removed by the table drop.
    Membership = apps.get_model("tracker", "OrganizationMembership")
    Membership.objects.update(cost_tier=None)


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0132_organization_target_utilization"),
    ]

    operations = [
        migrations.CreateModel(
            name="CostTier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=64)),
                ("cost_rate", models.DecimalField(decimal_places=2, help_text="Loaded hourly cost for everyone in this tier", max_digits=10)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cost_tiers", to="tracker.organization")),
            ],
            options={
                "ordering": ["sort_order", "id"],
                "unique_together": {("organization", "label")},
            },
        ),
        migrations.AddField(
            model_name="organizationmembership",
            name="cost_tier",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="members", to="tracker.costtier"),
        ),
        migrations.RunPython(seed_tiers, unseed_tiers),
    ]
