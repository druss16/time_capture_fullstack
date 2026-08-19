"""
Engagements — the unit of work a budget and a completion percentage attach to.

WHY THIS EXISTS
---------------
"We've burned 65% of the budget but we're only 35% done" is the question
firms actually want answered, and it needs three numbers:

    burn      hours spent so far        ← already captured, per minute, free
    budget    hours the job should take ← derived here, from prior-year actuals
    progress  how far along it really is ← phase, set by the preparer or inferred

Hours can never supply the third one. That's the trap the question describes:
burn tells you nothing about completion. So an Engagement carries an explicit
phase, and progress is the cumulative weight of the phases finished.

WHY NOT Project
---------------
`Project` already exists (org + client + name) and blocks carry `project_id`,
but nothing populates it — it's a manual bucket. An Engagement is derived
automatically from what the agent already captures (client, taxpayer, return
type, work date), so the firm gets budgets and progress without data entry.
Project stays as-is for firms that use it.

BUDGETS WITHOUT DATA ENTRY
--------------------------
For a recurring firm the best budget is what the same job took last year, for
the same client and the same return type. Failing that, the median of
comparable engagements. A firm that never types a budget still gets one; a firm
that wants to override just sets budget_source='manual'.
"""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


# Phase ladders. The weight is CUMULATIVE completion once that phase is
# reached — "in review" means prep is behind you, so you're 85% done.
# Ordered; the last entry must be 1.0.
PHASE_LADDERS: dict[str, list[tuple[str, str, float]]] = {
    "tax_return": [
        ("gathering",  "Gathering source docs", 0.10),
        ("preparing",  "Preparing the return",  0.55),
        ("review",     "In review",             0.85),
        ("assembly",   "Assembly / e-file",     0.95),
        ("done",       "Delivered",             1.00),
    ],
    "bookkeeping": [
        ("gathering",  "Waiting on records",    0.15),
        ("preparing",  "Posting / reconciling", 0.70),
        ("review",     "Review",                0.90),
        ("done",       "Closed",                1.00),
    ],
    "default": [
        ("gathering",  "Starting",              0.15),
        ("preparing",  "In progress",           0.60),
        ("review",     "Review",                0.90),
        ("done",       "Delivered",             1.00),
    ],
}


def ladder_for(engagement_type: str) -> list[tuple[str, str, float]]:
    return PHASE_LADDERS.get(engagement_type, PHASE_LADDERS["default"])


def phase_progress(engagement_type: str, phase: str) -> float | None:
    """Cumulative completion (0..1) for a phase, or None if the phase is unset."""
    if not phase:
        return None
    for key, _label, weight in ladder_for(engagement_type):
        if key == phase:
            return weight
    return None


class Engagement(models.Model):
    """One billable job: this client, this service, this period."""

    TYPE_CHOICES = [
        ("tax_return",  "Tax return"),
        ("bookkeeping", "Bookkeeping / close"),
        ("payroll",     "Payroll"),
        ("advisory",    "Advisory"),
        ("other",       "Other"),
    ]
    STATUS_CHOICES = [
        ("open",     "Open"),
        ("done",     "Delivered"),
        ("written_off", "Written off"),
    ]
    BUDGET_SOURCE_CHOICES = [
        ("prior_year", "Prior-year actual"),
        ("comparable", "Median of comparable engagements"),
        ("manual",     "Set by the firm"),
        ("none",       "No budget yet"),
    ]
    PHASE_SOURCE_CHOICES = [
        ("user",     "Set by the preparer"),
        ("inferred", "Inferred from captured activity"),
    ]

    org = models.ForeignKey(
        "Organization", on_delete=models.CASCADE, related_name="engagements",
    )
    client = models.ForeignKey(
        "Client", on_delete=models.CASCADE, related_name="engagements",
    )
    # Tax work is per-taxpayer, not per-client: one client can carry several
    # 1040s (spouse, kids, trusts). TaxpayerBucket is that identity.
    taxpayer_bucket = models.ForeignKey(
        "TaxpayerBucket", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagements",
    )

    engagement_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="other")
    return_type = models.CharField(
        max_length=16, blank=True, default="",
        help_text='Tax return form, e.g. "1040", "1120S". Blank for non-tax work.',
    )

    # Period the work belongs to. `period_label` is what humans read
    # ("TY2025", "2026-07"); the dates make it queryable.
    period_label = models.CharField(max_length=20)
    period_start = models.DateField()
    period_end = models.DateField()

    name = models.CharField(max_length=200, blank=True, default="")

    # ---- Budget ------------------------------------------------------------
    budget_hours = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
    )
    budget_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    budget_source = models.CharField(
        max_length=20, choices=BUDGET_SOURCE_CHOICES, default="none",
    )
    budget_basis = models.CharField(
        max_length=200, blank=True, default="",
        help_text='How the budget was derived, e.g. "TY2024 actual: 12.4h across 31 blocks".',
    )
    budget_set_at = models.DateTimeField(null=True, blank=True)

    # ---- Progress ----------------------------------------------------------
    phase = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Current phase key from the type's PHASE_LADDERS.",
    )
    phase_source = models.CharField(
        max_length=10, choices=PHASE_SOURCE_CHOICES, blank=True, default="",
    )
    phase_set_at = models.DateTimeField(null=True, blank=True)
    phase_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="engagement_phase_updates",
    )

    # Shadow inference — written by the inference pass, never authoritative
    # until it has been shown to agree with what preparers actually say.
    inferred_phase = models.CharField(max_length=20, blank=True, default="")
    inferred_phase_confidence = models.FloatField(null=True, blank=True)
    inferred_phase_at = models.DateTimeField(null=True, blank=True)
    inferred_phase_signals = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tracker_engagement"
        ordering = ["-period_end", "client__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "client", "taxpayer_bucket", "engagement_type",
                        "return_type", "period_label"],
                name="uniq_engagement_per_period",
            ),
        ]
        indexes = [
            models.Index(fields=["org", "status"]),
            models.Index(fields=["org", "client", "period_label"]),
            models.Index(fields=["org", "engagement_type", "return_type"]),
        ]

    def __str__(self):
        who = self.taxpayer_bucket.display_name if self.taxpayer_bucket else self.client.name
        what = self.return_type or self.get_engagement_type_display()
        return f"{who} — {what} {self.period_label}"

    # -- Progress helpers ----------------------------------------------------

    @property
    def ladder(self) -> list[tuple[str, str, float]]:
        return ladder_for(self.engagement_type)

    @property
    def progress(self) -> float | None:
        """0..1 completion from the phase the preparer set. None = unknown.

        Deliberately does NOT fall back to the inferred phase — a guess and a
        statement shouldn't be indistinguishable in the number people bill on.
        Callers that want the guess read `inferred_phase` explicitly.
        """
        return phase_progress(self.engagement_type, self.phase)

    def display_name(self) -> str:
        return self.name or str(self)
