# The firm's own record of what it charged a client for a period — what makes
# the Fees page a finite piece of work rather than a report.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tracker", "0163_fee_schedule_entry"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillingDecision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("amount", models.DecimalField(
                    decimal_places=2,
                    help_text="What the firm charged for this period.",
                    max_digits=12)),
                ("hours_at_decision", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=8, null=True)),
                ("value_at_decision", models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text="Time at standard rates when the decision was made.",
                    max_digits=12, null=True)),
                ("note", models.CharField(blank=True, default="", max_length=200)),
                ("decided_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("client", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="billing_decisions", to="tracker.client")),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="billing_decisions", to="tracker.organization")),
                ("decided_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="billing_decisions",
                    to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name="billingdecision",
            index=models.Index(fields=["org", "period_start", "period_end"],
                               name="tracker_bil_org_id_2c0bca_idx"),
        ),
        migrations.AddConstraint(
            model_name="billingdecision",
            constraint=models.UniqueConstraint(
                fields=("org", "client", "period_start", "period_end"),
                name="uniq_billing_decision_client_period"),
        ),
    ]
