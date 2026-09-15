# Generated for the fee schedule: a firm's price for a client x kind of work,
# held apart from any one period of it.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tracker", "0162_mismatch_agent"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeeScheduleEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("engagement_type", models.CharField(
                    choices=[("tax_return", "Tax return"),
                             ("bookkeeping", "Bookkeeping / close"),
                             ("payroll", "Payroll"),
                             ("advisory", "Advisory"),
                             ("other", "Other")],
                    max_length=20)),
                ("budget_hours", models.DecimalField(decimal_places=2, max_digits=8)),
                ("fee_quoted", models.DecimalField(
                    blank=True, decimal_places=2,
                    help_text="The fee as the firm stated it, when they gave a fee "
                              "rather than hours. Display only — budget_hours is "
                              "what applies.",
                    max_digits=12, null=True)),
                ("set_in", models.CharField(
                    blank=True, default="",
                    help_text='Where it came from: "Fees", "Settings", "fee schedule CSV".',
                    max_length=40)),
                ("applied_count", models.IntegerField(default=0)),
                ("last_applied_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="fee_schedule", to="tracker.client")),
                ("org", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="fee_schedule", to="tracker.organization")),
                ("set_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="fee_schedule_entries",
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name_plural": "fee schedule entries"},
        ),
        migrations.AddIndex(
            model_name="feescheduleentry",
            index=models.Index(fields=["org", "client", "engagement_type"],
                               name="tracker_fee_org_id_0a89d1_idx"),
        ),
        migrations.AddConstraint(
            model_name="feescheduleentry",
            constraint=models.UniqueConstraint(
                fields=("org", "client", "engagement_type"),
                name="uniq_fee_schedule_client_type"),
        ),
    ]
