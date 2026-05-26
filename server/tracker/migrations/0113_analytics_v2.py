"""
Migration for analytics v2.

What this migration does:
  Creates 5 new tables (additive, no existing tables touched):
    tracker_v2_client_daily_rollup
    tracker_v2_staff_daily_rollup
    tracker_v2_wip_snapshot
    tracker_v2_saved_view
    tracker_v2_insight_dismissal

NOTE: The 'member' -> 'staff' role rename has been deferred. We'll do that
as a separate focused effort after auditing every code reference to 'member'.
The v2 dashboard works fine with 'member' as the role name.
"""
from django.conf import settings
from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):
    
    dependencies = [
        ("tracker", "0112_block_calendar_disagreement_reasoning_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    
    operations = [
        # --- ClientDailyRollup ---
        migrations.CreateModel(
            name="ClientDailyRollup",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("day", models.DateField(db_index=True)),
                ("total_minutes", models.IntegerField(default=0)),
                ("billable_minutes", models.IntegerField(default=0)),
                ("billing_amount", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("cost_amount", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("invoiced_amount", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("invoiced_hours", models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0"))),
                ("explicit_rate_amount", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("default_rate_amount", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                              related_name="v2_daily_rollups",
                                              to="tracker.client")),
                ("org", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                           related_name="v2_client_daily_rollups",
                                           to="tracker.organization")),
            ],
            options={
                "db_table": "tracker_v2_client_daily_rollup",
                "unique_together": {("org", "client", "day")},
            },
        ),
        migrations.AddIndex(
            model_name="clientdailyrollup",
            index=models.Index(fields=["org", "day"], name="v2_cdr_org_day_idx"),
        ),
        migrations.AddIndex(
            model_name="clientdailyrollup",
            index=models.Index(fields=["org", "client", "day"], name="v2_cdr_org_cli_day_idx"),
        ),
        
        # --- StaffDailyRollup ---
        migrations.CreateModel(
            name="StaffDailyRollup",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("day", models.DateField(db_index=True)),
                ("total_minutes", models.IntegerField(default=0)),
                ("billable_minutes", models.IntegerField(default=0)),
                ("billing_amount", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("cost_amount", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("org", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                           related_name="v2_staff_daily_rollups",
                                           to="tracker.organization")),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                            related_name="v2_daily_rollups",
                                            to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "tracker_v2_staff_daily_rollup",
                "unique_together": {("org", "user", "day")},
            },
        ),
        migrations.AddIndex(
            model_name="staffdailyrollup",
            index=models.Index(fields=["org", "day"], name="v2_sdr_org_day_idx"),
        ),
        migrations.AddIndex(
            model_name="staffdailyrollup",
            index=models.Index(fields=["org", "user", "day"], name="v2_sdr_org_usr_day_idx"),
        ),
        
        # --- WipSnapshot ---
        migrations.CreateModel(
            name="WipSnapshot",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("captured_at", models.DateTimeField(db_index=True)),
                ("total", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("aged_0_30", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("aged_31_60", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("aged_61_90", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("aged_90_plus", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))),
                ("by_client", models.JSONField(blank=True, default=dict)),
                ("org", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                           related_name="v2_wip_snapshots",
                                           to="tracker.organization")),
            ],
            options={
                "db_table": "tracker_v2_wip_snapshot",
                "ordering": ["-captured_at"],
            },
        ),
        migrations.AddIndex(
            model_name="wipsnapshot",
            index=models.Index(fields=["org", "-captured_at"], name="v2_wip_org_capt_idx"),
        ),
        
        # --- SavedView ---
        migrations.CreateModel(
            name="SavedView",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("query", models.JSONField()),
                ("pinned", models.BooleanField(default=False)),
                ("schedule", models.JSONField(null=True, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("org", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                           related_name="v2_saved_views",
                                           to="tracker.organization")),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                            related_name="v2_saved_views",
                                            to=settings.AUTH_USER_MODEL)),
                ("shared_with", models.ManyToManyField(blank=True,
                                                        related_name="v2_shared_views",
                                                        to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "tracker_v2_saved_view"},
        ),
        migrations.AddIndex(
            model_name="savedview",
            index=models.Index(fields=["user", "org"], name="v2_sv_user_org_idx"),
        ),
        migrations.AddIndex(
            model_name="savedview",
            index=models.Index(fields=["org", "pinned"], name="v2_sv_org_pinned_idx"),
        ),
        
        # --- InsightDismissal ---
        migrations.CreateModel(
            name="InsightDismissal",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                ("insight_signature", models.CharField(max_length=64, db_index=True)),
                ("dismissed_at", models.DateTimeField(auto_now_add=True)),
                ("dismiss_until", models.DateTimeField()),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE,
                                            related_name="v2_dismissed_insights",
                                            to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "tracker_v2_insight_dismissal",
                "unique_together": {("user", "insight_signature")},
            },
        ),
    ]