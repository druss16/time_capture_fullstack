"""
Tracking pauses — a person chose "Pause Tracking" in the desktop agent's menu
bar (Mac v1.9.29+). While paused the agent records nothing, so in every time
table a pause is just a gap, indistinguishable from the machine being off.
This table is what tells the two apart, for the per-employee Reports column.

Written only by the desktop agent (POST /api/agent/pauses/), keyed by
(device, started_at): the agent posts once when the pause starts (ended_at
null) and again when it ends, and a re-sent post overwrites itself. Read by
reports only; nothing that computes billable time looks here.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class TrackingPause(models.Model):
    org = models.ForeignKey(
        'tracker.Organization', on_delete=models.CASCADE,
        related_name='tracking_pauses')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='tracking_pauses')
    device = models.ForeignKey(
        'tracker.AgentDevice', on_delete=models.CASCADE,
        related_name='tracking_pauses')
    started_at = models.DateTimeField()
    # Null while the pause is still on.
    ended_at = models.DateTimeField(null=True, blank=True)
    # When a timed pause (15 min / 30 min / 1 hour) was set to end; null for
    # "Until I resume". An open pause is never counted past this.
    planned_until = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['device', 'started_at'],
                                    name='uniq_tracking_pause_device_start'),
        ]
        indexes = [models.Index(fields=['org', 'started_at'])]
        ordering = ['-started_at']

    def __str__(self):
        return f"TrackingPause(user={self.user_id}, {self.started_at} → {self.ended_at or 'open'})"
