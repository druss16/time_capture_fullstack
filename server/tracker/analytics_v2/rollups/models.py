"""
Rollup tables for fast analytics queries.

These are *additive* — they do not replace or modify any existing model. They
sit alongside Block/Invoice/etc and are populated by the Celery jobs in
tasks.py. If they're stale or empty, v2 still works (it just falls back to
querying Block directly).

Schema philosophy: one row per (org, day, dimension_id), with all the columns
needed to compute any metric for that combination. Lets us answer most queries
with a single SELECT.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from tracker.models import Client, Organization


class ClientDailyRollup(models.Model):
    """One row per (org, client, day). Precomputed nightly."""
    org = models.ForeignKey(Organization, on_delete=models.CASCADE,
                            related_name="v2_client_daily_rollups")
    client = models.ForeignKey(Client, on_delete=models.CASCADE,
                               related_name="v2_daily_rollups")
    day = models.DateField(db_index=True)
    
    # Hours
    total_minutes = models.IntegerField(default=0)
    billable_minutes = models.IntegerField(default=0)
    
    # Money
    billing_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                          default=Decimal("0"))
    cost_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                       default=Decimal("0"))
    
    # Invoiced (from Invoice records dated this day)
    invoiced_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                           default=Decimal("0"))
    invoiced_hours = models.DecimalField(max_digits=8, decimal_places=2,
                                          default=Decimal("0"))
    
    # Data quality (Option B realization)
    explicit_rate_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                                default=Decimal("0"))
    default_rate_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                               default=Decimal("0"))
    
    # Maintenance
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "tracker_v2_client_daily_rollup"
        unique_together = [["org", "client", "day"]]
        indexes = [
            models.Index(fields=["org", "day"]),
            models.Index(fields=["org", "client", "day"]),
        ]
    
    def __str__(self):
        return f"{self.org_id}/{self.client_id} {self.day} {self.total_minutes}min"


class StaffDailyRollup(models.Model):
    """One row per (org, user, day). Precomputed nightly."""
    org = models.ForeignKey(Organization, on_delete=models.CASCADE,
                            related_name="v2_staff_daily_rollups")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="v2_daily_rollups")
    day = models.DateField(db_index=True)
    
    total_minutes = models.IntegerField(default=0)
    billable_minutes = models.IntegerField(default=0)
    billing_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                          default=Decimal("0"))
    cost_amount = models.DecimalField(max_digits=12, decimal_places=2,
                                       default=Decimal("0"))
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "tracker_v2_staff_daily_rollup"
        unique_together = [["org", "user", "day"]]
        indexes = [
            models.Index(fields=["org", "day"]),
            models.Index(fields=["org", "user", "day"]),
        ]
    
    def __str__(self):
        return f"{self.org_id}/u{self.user_id} {self.day} {self.total_minutes}min"


class WipSnapshot(models.Model):
    """
    Hourly snapshot of WIP state. Lets the dashboard show consistent numbers
    even as new approvals roll in throughout the day.
    """
    org = models.ForeignKey(Organization, on_delete=models.CASCADE,
                            related_name="v2_wip_snapshots")
    captured_at = models.DateTimeField(db_index=True)
    
    # Total + aging bands
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    aged_0_30 = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    aged_31_60 = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    aged_61_90 = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    aged_90_plus = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    
    # Per-client snapshot (JSON: {client_id: amount})
    by_client = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = "tracker_v2_wip_snapshot"
        indexes = [
            models.Index(fields=["org", "-captured_at"]),
        ]
        ordering = ["-captured_at"]
    
    def __str__(self):
        return f"WIP snapshot org={self.org_id} {self.captured_at} ${self.total}"


class SavedView(models.Model):
    """User-saved view (filter preset)."""
    org = models.ForeignKey(Organization, on_delete=models.CASCADE,
                            related_name="v2_saved_views")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="v2_saved_views")
    name = models.CharField(max_length=120)
    
    # Serialized query state — same shape as the request body to /query/
    query = models.JSONField()
    
    pinned = models.BooleanField(default=False)
    shared_with = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="v2_shared_views",
        blank=True,
    )
    
    # Optional scheduled email digest
    schedule = models.JSONField(null=True, blank=True)  # {"freq": "weekly", "day": "mon", "time": "08:00"}
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "tracker_v2_saved_view"
        indexes = [
            models.Index(fields=["user", "org"]),
            models.Index(fields=["org", "pinned"]),
        ]
    
    def __str__(self):
        return f"{self.user.username}: {self.name}"


class InsightDismissal(models.Model):
    """
    Per-user dismissal of an insight card. Insights re-appear after 7 days
    if their underlying condition still holds.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="v2_dismissed_insights")
    insight_signature = models.CharField(max_length=64, db_index=True)
    dismissed_at = models.DateTimeField(auto_now_add=True)
    dismiss_until = models.DateTimeField()
    
    class Meta:
        db_table = "tracker_v2_insight_dismissal"
        unique_together = [["user", "insight_signature"]]
    
    def __str__(self):
        return f"{self.user.username} dismissed {self.insight_signature} until {self.dismiss_until}"
