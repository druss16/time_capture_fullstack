from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

from django.contrib.auth.models import Group
import hashlib
import secrets  # ✅ add this import

from tracker.industry_categories import INDUSTRY_CHOICES

from pgvector.django import VectorField, HnswIndex

# ===========================
# ======  ORG MODELS  ======
# ===========================
# tracker/models.py - Add this new model (or enhance Group)

# Replace your Organization model in tracker/models.py with this:

from decimal import Decimal

class ActiveOrgManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

class Organization(models.Model):
    """
    Represents a CPA firm - the tenant in multi-tenant setup.
    Each org has completely isolated data.
    """
    name = models.CharField(max_length=200)  # "Smith & Associates CPA"
    slug = models.SlugField(unique=True)      # "smith-associates"

        # ✅ ADD THIS FIELD
    industry_type = models.CharField(
        max_length=50,
        choices=INDUSTRY_CHOICES,
        default='general',
        help_text='Industry type determines available categories'
    )


    
    # Subscription/billing
    plan = models.CharField(max_length=20, choices=[
        ('none', 'No Plan'),
        ('professional', 'Professional'),
        ('executive', 'Executive'),
    ], default='none')

    stripe_customer_id = models.CharField(max_length=100, blank=True)

    # ADD these fields
    stripe_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    seat_count = models.IntegerField(default=1, help_text="Number of paid seats")
    
    # Settings
    timezone = models.CharField(max_length=50, default='America/New_York')
    
    # Default Rates
    billing_rate_default = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('150.00'),
        help_text="Default hourly billing rate charged to clients"
    )
    cost_rate_default = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('75.00'),
        help_text="Default hourly employee cost (for margin calculations)"
    )
    target_utilization = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('75.00'),
        help_text=(
            "Target billable utilization %, the benchmark for the Utilization KPI. "
            "Firm-wide default; drives the good/watch/bad band on the analytics dashboard."
        ),
    )
    capacity_hours_per_week = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('40.00'),
        help_text=(
            "Available working hours per week per employee (firm-wide default). "
            "Denominator for capacity-based utilization = billable ÷ available. "
            "Overridden per tier by CostTier.hours_per_week."
        ),
    )

    # Onboarding tracking (optional - add if you want to track progress)
    onboarding_completed = models.BooleanField(default=False)
    onboarding_step = models.IntegerField(default=1)

    payment_grace_deadline = models.DateTimeField(null=True, blank=True)

    auto_submit_timesheets = models.BooleanField(
        default=False,
        help_text="Auto-submit draft timesheets on Tuesday 9am"
    )

    ai_sensitivity = models.PositiveSmallIntegerField(
        default=50,
        help_text=(
            "Controls how aggressively the desktop agent matches window titles "
            "to clients (0 = conservative, 50 = balanced, 100 = aggressive). "
            "Admin-only setting."
        ),
    )

    disable_mail_integration = models.BooleanField(
        default=False,
        help_text=(
            'When True, mail integration is hidden from all users in this org and '
            'any existing connections are silently ignored. For firms with policies '
            'forbidding mail integration entirely.'
        ),
    )

    calendar_classification_enabled = models.BooleanField(
        default=False,
        help_text="Enable Stage 6 (calendar event overlap) in classifier",
    )

    sandwich_correlation_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Enable Stage Sandwich (temporal fallback attribution). When a block "
            "has no client signal but is tightly bracketed in time by blocks "
            "attributed to the SAME client, propose that client. Never "
            "auto-commits — always surfaces as a proposal for human review."
        ),
    )

    route_individual_returns_to_internal_tax = models.BooleanField(
        default=False,
        help_text=(
            "When True, Stage 2 routes individual tax returns (1040, 1041) to "
            "this org's 'Internal - Tax' client instead of leaving them unassigned. "
            "Enable for firms that bill individual returns as internal firm time. "
            "Disable for firms that handle taxpayer billing separately."
        ),
    )

    auto_confirm_name_matches = models.BooleanField(
        default=False,
        help_text=(
            "Auto-confirm (commit) a proposed block when the block's own text "
            "literally names the client — a window-title alias, file path, or "
            "domain match — and no other client competes. Converts the 'almost a "
            "literal match' proposal pile (e.g. 'Sacred Heart Basilica - "
            "QuickBooks…') into committed billable time with zero clicks. Only "
            "name-bearing evidence qualifies: email/calendar/temporal/AI-only "
            "guesses (e.g. a shared inbox routed by subject) still surface for "
            "human review. Same-family collisions never reach here — Stage 3 "
            "abstains on ties. Enable per-org once attribution accuracy is trusted."
        ),
    )

    auto_confirm_client_attributions = models.BooleanField(
        default=False,
        help_text=(
            "Broader than auto_confirm_name_matches: auto-confirm (commit) ANY "
            "proposed block that is already attributed to a single client with no "
            "competing client — even when the evidence is contextual (temporal / "
            "co-open / agent) rather than a literal name in the title. This is the "
            "'if it's already under a client, just confirm it' rule (e.g. 'Bank "
            "Statements - File Explorer' grouped under a church whose QuickBooks "
            "was open). Same safety rails: blocks flagged needs_review still "
            "surface, and same-family collisions are held back because a competing "
            "client trips the contradiction guard. Preserves each block's billable "
            "judgment. Enable per-org only once attribution accuracy is trusted."
        ),
    )

    arbitrate_disagreements = models.BooleanField(
        default=False,
        help_text=(
            "When True, and the backend classifier disagrees with the agent's "
            "attribution, resolve by evidence in the block's own window title "
            "instead of always keeping the agent's pick: if exactly one side's "
            "client name literally appears in the title, that side wins; if "
            "neither is evidenced by the title, the block is left 'proposed' "
            "(not auto-committed) so it goes to Daily Review rather than billing "
            "a no-evidence guess. Same-family (church/cemetery) ties still keep "
            "the agent's pick + disagreement flag. Default off; enable per-org "
            "after validating against ai_disagrees_with_agent history."
        ),
    )

    disable_mail_integration = models.BooleanField(
        default=False,
        help_text='Master switch — disables mail OAuth/sync/classifier for the whole org.',
    )
    mail_signal_retention_days = models.IntegerField(
        default=30,
        help_text='How long to retain MailSignal rows. Pruned nightly.',
    )
    mail_sync_interval_minutes = models.IntegerField(
        default=5,
        help_text='Per-org override for mail sync cadence. Default 5 min.',
    )
        
    mouse_idle_pause_seconds = models.IntegerField(default=600)

    trial_ends_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_demo = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # MavOps-admin-only "hide from the ops list" flag. Distinct from
    # deleted_at (soft delete): this does NOT hide the org from its own
    # members / product views — it only removes clutter (stale duplicates,
    # decommissioned firms) from the internal MavOps org list. Reversible.
    mavops_archived = models.BooleanField(default=False)

    # Seat-overage grace. Set when member_count first exceeds seat_count; the
    # org keeps working until this deadline, then the excess is blocked
    # (check_seat_overage_grace). DISTINCT from payment_grace_deadline, which
    # is owned by the Stripe past-due flow — do not conflate the two.
    seat_grace_deadline = models.DateTimeField(null=True, blank=True)

    objects = ActiveOrgManager()
    all_objects = models.Manager()

    def soft_delete(self):
        from django.utils import timezone
        self.deleted_at = timezone.now()
        self.save(update_fields=['deleted_at'])
    
    def __str__(self):
        return self.name

    def get_categories(self):
        '''Get category list for this org's industry type.'''
        from tracker.industry_categories import get_categories_for_industry
        return get_categories_for_industry(self.industry_type)
    
    def get_tool_detection(self):
        '''Get tool detection patterns for this org's industry type.'''
        from tracker.industry_categories import get_combined_tool_detection
        return get_combined_tool_detection(self.industry_type)
    
    @property
    def default_margin(self):
        """Calculate default profit margin percentage"""
        if self.billing_rate_default and self.billing_rate_default > 0:
            margin = self.billing_rate_default - (self.cost_rate_default or Decimal('0'))
            return round((margin / self.billing_rate_default) * 100, 1)
        return 0

    @property
    def is_trial_active(self):
        from django.utils import timezone
        if not self.trial_ends_at:
            return False
        return self.trial_ends_at > timezone.now()

    @property
    def trial_days_remaining(self):
        from django.utils import timezone
        if not self.trial_ends_at:
            return 0
        if self.trial_ends_at < timezone.now():
            return 0
        return (self.trial_ends_at - timezone.now()).days

    class Meta:
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
    

class OrganizationMembership(models.Model):
    """
    Links users to organizations with roles.
    A user can belong to multiple orgs (rare but possible).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    role = models.CharField(max_length=20, choices=[
        ('owner', 'Owner'),         # Full control, billing
        ('admin', 'Admin'),         # Manage users, settings
        ('manager', 'Manager'),     # Approve timecards
        ('member', 'Member'),       # Track time only
    ], default='member')
    
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='invites_sent'
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    # In OrganizationMembership class, after the role field:
    quickbooks_employee_id = models.CharField(
        max_length=50, blank=True, null=True,
        help_text='QuickBooks Employee ID for time entry push'
    )

    # Labor cost tier — drives profitability margin. Independent of `role`
    # (a permission concept). Nullable → falls back to org.cost_rate_default.
    cost_tier = models.ForeignKey(
        'CostTier', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='members',
    )

    class Meta:
        unique_together = ['user', 'organization']
    
    def __str__(self):
        return f"{self.user.username} @ {self.organization.name} ({self.role})"


# ===========================
# ======  RAW EVENTS  =======
# ===========================
# tracker/models.py — RawEvent class
# Replace the existing RawEvent class definition with this version.

class RawEvent(models.Model):
    """
    A single agent-emitted activity interval.

    DUAL TIMESTAMPS (v1.3.38)
    =========================
    Each event represents a real time interval, not a point. The agent
    emits events in three places:

      1. dwell start  — when user focuses a new window
      2. heartbeats   — every 60s while still on the same window
      3. dwell end    — window change, idle entry, or sleep

    For each emission, start_ts = last emit time, end_ts = now. So a
    5-minute dwell in Outlook becomes ~5 events of ~60s each, all with
    the same window signature. Compaction merges them into one block
    using the real durations instead of guessing via IDLE_CAP.

    Idle events have clear start/end semantics too (idle entry/exit),
    so they don't need heartbeats — one event per idle period.
    """

    # ── Dual interval timestamps ──
    start_ts = models.DateTimeField(db_index=True)
    end_ts = models.DateTimeField(db_index=True)

    # ── Window signature ──
    app_name = models.CharField(max_length=255, blank=True, null=True)
    bundle_id = models.CharField(max_length=255, blank=True, null=True)
    window_title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, null=True)
    file_path = models.TextField(blank=True, null=True)

    # ── Identity ──
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    device_id = models.CharField(max_length=64, db_index=True, default="unknown")
    hostname = models.CharField(max_length=255, blank=True, null=True, default="unknown")

    # ── Context ──
    ctx = models.JSONField(default=dict, blank=True)

    # ── Agent version (v1.3.49) ──
    # Reported by the agent at event-write time. Used for fleet visibility
    # and triage: when a class of bugs appears, we can correlate to which
    # agent versions are affected. NULL for events from pre-v1.3.24 agents
    # (no version field) and for events created server-side (test_meetings,
    # enrich_demo_titles, etc).
    agent_version = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        db_index=True,
        help_text="Agent app version that produced this event (e.g. '1.3.24')",
    )

    # Snapshot of the user's selected client at start_ts.
    # Captured at dwell_start time, NOT at write_event time, so AI-switcher
    # flips mid-dwell don't retroactively reattribute earlier heartbeats.
    current_client_id = models.IntegerField(null=True, blank=True, db_index=True)

    # ── Compaction linkage ──
    block = models.ForeignKey(
        "Block",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_events",
        help_text="The block this event was compacted into",
    )

    inference = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Agent inference output: structured client recognition result "
            "with confidence, evidence trail, and decay metadata. Populated "
            "by agent v1.4+. Empty dict for events from older agents."
        ),
    )

    class Meta:
        indexes = [
            models.Index(fields=["start_ts"]),
            models.Index(fields=["user", "start_ts"]),
            models.Index(fields=["user", "device_id", "start_ts"]),
            models.Index(fields=["user", "hostname"]),
        ]
        # ts_utc → start_ts: keep ordering on start_ts to preserve event order.
        ordering = ["start_ts"]

    @property
    def duration_seconds(self) -> float:
        """Real interval duration. Replaces IDLE_CAP-guessed durations."""
        return (self.end_ts - self.start_ts).total_seconds()

    def __str__(self):
        u = getattr(self.user, "username", self.user_id)
        return f"{u} {self.app_name} {self.start_ts}–{self.end_ts}"

# ===========================
# ======  AGENT MODELS  =====
# ===========================
# Add this model to tracker/models.py
# Add it near the other Agent models (after AgentDevice, before Client)

from django.db import models
from django.conf import settings
from django.utils import timezone

class CurrentClient(models.Model):
    """
    Tracks which client the user is currently working on for each device.
    This enables auto-tagging of events and blocks with the selected client.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="current_clients",
        db_index=True,
    )
    device_id = models.IntegerField(
        default=0,
        db_index=True,
        help_text="AgentDevice.id for per-device client selection (0 = all devices)"
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_selections",
    )
    started_at = models.DateTimeField(
        default=timezone.now,
        help_text="When the user switched to this client"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time this selection was confirmed/updated"
    )

    class Meta:
        unique_together = [["user", "device_id"]]
        indexes = [
            models.Index(fields=["user", "device_id"]),
            models.Index(fields=["user", "updated_at"]),
        ]
        verbose_name = "Current Client Selection"
        verbose_name_plural = "Current Client Selections"

    def __str__(self):
        username = getattr(self.user, 'username', self.user_id)
        client_name = self.client.name if self.client else "None"
        return f"{username} → {client_name}"


class AgentSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    hostname = models.CharField(max_length=120, db_index=True)

    last_seen = models.DateTimeField(db_index=True)
    last_app = models.CharField(max_length=120, blank=True)
    last_window_title = models.CharField(max_length=512, blank=True)

    platform = models.CharField(max_length=80, blank=True, default="")
    version = models.CharField(max_length=40, blank=True, default="")
    last_ip = models.CharField(max_length=45, blank=True, null=True)

    class Meta:
        unique_together = ("user", "hostname")

    def __str__(self):
        return f"{getattr(self.user, 'username', self.user_id)}@{self.hostname} • {self.last_seen.isoformat()}"


class AgentControl(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    host = models.CharField(max_length=255)
    stop = models.BooleanField(default=False, db_index=True)
    stop_until = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "host")

    def __str__(self):
        state = "STOP" if self.stop else "OK"
        return f"{state} {self.user.username}@{self.host}"

from django.db import models
from django.conf import settings
from django.utils import timezone
import secrets  # make sure this import exists

class AgentDevice(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_devices",
        null=True, blank=True,
    )
    os_username = models.CharField(max_length=255, blank=True, default="")
    device_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Stable UUID generated by the agent and stored locally",
    )
    hostname = models.CharField(max_length=128, blank=True, default="")
    platform = models.CharField(max_length=128, blank=True, default="")
    app_version = models.CharField(max_length=32, blank=True, default="")

    api_key = models.CharField(
        max_length=64,
        unique=True,
        null=True, blank=True,          # unpaired has no key
        db_index=True,
    )

    is_active = models.BooleanField(default=False)
    # Why a device was deactivated, when we did it programmatically. Lets us
    # reactivate only the devices WE blocked for seat overage (not ones a
    # payment failure or an admin turned off). Blank for manual/unknown.
    deactivated_reason = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    # MDM deployment tracking
    claimed_via_token = models.ForeignKey(
        'OrgDeploymentToken',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='claimed_devices'
    )
    auto_matched = models.BooleanField(
        default=False,
        help_text="True if user was auto-matched by email, False if manually selected"
    )

    log_requested = models.BooleanField(default=False)

    restart_requested = models.BooleanField(default=False)

    kill_requested = models.BooleanField(default=False)

    def rotate_key(self):
        import secrets
        self.api_key = secrets.token_hex(16)
        if not self.is_active:
            self.is_active = True
        from django.utils import timezone
        self.last_seen_at = timezone.now()
        self.save(update_fields=["api_key", "is_active", "last_seen_at"])

    def __str__(self):
        u = getattr(self.user, "username", None) or "unlinked"
        return f"{u}@{self.hostname or 'unknown'} • {self.device_id}"

    class Meta:
        indexes = [
            models.Index(fields=["user", "hostname"]),
            models.Index(fields=["is_active", "last_seen_at"]),
        ]
        constraints = [
            # If active, api_key must not be null
            models.CheckConstraint(
                name="api_key_required_when_active",
                check=(
                    models.Q(is_active=False) |
                    models.Q(api_key__isnull=False)
                ),
            ),
        ]

import secrets, string
from django.db import models
from django.conf import settings
from django.utils import timezone

class AgentPairCode(models.Model):
    """Short-lived code a signed-in user generates, consumed by the agent once."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pair_codes")
    code = models.CharField(max_length=8, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, user, ttl_seconds=600):
        """
        Generate an 8-character alphanumeric code (A–Z + 0–9),
        valid for ttl_seconds (default 10 minutes).
        """
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        return cls.objects.create(
            user=user,
            code=code,
            expires_at=timezone.now() + timezone.timedelta(seconds=ttl_seconds),
        )

    def consume(self):
        """Mark this code as used."""
        self.consumed_at = timezone.now()
        self.save(update_fields=["consumed_at"])

    def __str__(self):
        return f"{self.code} for {self.user.username}"


# tracker/models.py - FIX THE UserWorkPattern MODEL

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import json

User = get_user_model()


class UserWorkPattern(models.Model):
    """
    Learns and stores patterns about how each user works.
    Used to improve AI classification accuracy over time.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='work_patterns')
    org = models.ForeignKey('Organization', on_delete=models.CASCADE, null=True)
    
    # Pattern types
    PATTERN_TYPES = [
        ('app', 'Application Pattern'),
        ('domain', 'URL Domain Pattern'),
        ('window_title_prefix', 'Window Title Pattern'),
        ('file_path', 'File Path Pattern'),
        ('client_folder', 'Client Folder Mapping'),
        ('category_folder', 'Category Folder Pattern'),
        ('time_slot', 'Time Slot Pattern'),
        ('app_sequence', 'Application Sequence'),
    ]
    pattern_type = models.CharField(max_length=30, choices=PATTERN_TYPES, db_index=True)
    
    # Pattern data
    pattern_key = models.CharField(max_length=500, db_index=True)  # e.g., "/Users/dan/Documents/Clients/Acme/"
    
    # What this pattern predicts
    client = models.ForeignKey('Client', on_delete=models.CASCADE, null=True, blank=True)
    category = models.CharField(max_length=100, blank=True)  # e.g., "Tax Preparation"
    
    # Confidence metrics
    occurrence_count = models.IntegerField(default=1)
    correct_predictions = models.IntegerField(default=0)
    total_predictions = models.IntegerField(default=0)
    confidence_score = models.FloatField(default=0.5)  # Updated dynamically
    
    # Metadata
    metadata = models.JSONField(default=dict)  # Extra context (time ranges, co-occurring patterns, etc.)
    
    # Timestamps
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    last_confirmed = models.DateTimeField(null=True, blank=True)  # Last time user confirmed this pattern
    
    class Meta:
        db_table = 'tracker_userworkpattern'  # ✅ FIXED: Changed from db_name to db_table
        indexes = [
            models.Index(fields=['user', 'pattern_type']),
            models.Index(fields=['user', 'client']),
            models.Index(fields=['confidence_score']),
        ]
        unique_together = [['user', 'pattern_type', 'pattern_key']]
    
    def update_confidence(self, was_correct: bool):
        """Update confidence score based on prediction accuracy"""
        self.total_predictions += 1
        if was_correct:
            self.correct_predictions += 1
        
        # Bayesian update of confidence
        self.confidence_score = self.correct_predictions / max(1, self.total_predictions)
        self.save(update_fields=['confidence_score', 'correct_predictions', 'total_predictions'])
    
    def __str__(self):
        return f"{self.user.username} - {self.pattern_type}: {self.pattern_key[:50]}"


class AuthToken(models.Model):
    """
    Authentication token (used when cookies are blocked).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auth_tokens')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = "tracker_authtoken"  # ✅ Fixed: db_table, not db_name
    
    def is_valid(self):
        return timezone.now() < self.expires_at

# ===========================
# ======  CORE MODELS  ======
# ===========================
# UPDATE YOUR Client MODEL in tracker/models.py
# Add these fields after the existing fields:

class Client(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    
    code = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Short code like 'ACME' or 'JOHN'"
    )
    
    is_active = models.BooleanField(default=True)

    visibility = models.CharField(
        max_length=20, 
        choices=[('all', 'All'), ('assigned', 'Assigned'), ('confidential', 'Confidential')],
        default='all',
        null=True,
        blank=True
    )
    
    # ═══════════════════════════════════════════════════════════════════════
    # ADD THESE NEW FIELDS FOR INTEGRATIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    quickbooks_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        help_text='QuickBooks Customer ID'
    )
    
    xero_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        help_text='Xero Contact ID'
    )
    
    IMPORT_SOURCE_CHOICES = [
        ('', 'Manual'),
        ('quickbooks', 'QuickBooks'),
        ('xero', 'Xero'),
    ]
    imported_from = models.CharField(
        max_length=20,
        choices=IMPORT_SOURCE_CHOICES,
        blank=True,
        default='',
        help_text='Integration source this client was imported from'
    )

    email = models.EmailField(
        max_length=254,
        blank=True,
        default='',
        help_text='Primary contact email pulled from QB/Xero. Used for domain-alias derivation.'
    )

    aliases = models.JSONField(
        default=list,
        blank=True,
        help_text="Alternative names/abbreviations for AI client matching"
        )

    alias_sources = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Provenance map {alias_lower: 'derived'|'manual'} paralleling "
            "`aliases`. Lets the ambiguity self-heal remove only auto-derived "
            "aliases that later collide with a sibling client — manual and "
            "unmarked (legacy) aliases are never auto-removed. Not read by the "
            "classifier; `aliases` remains the flat string list Stage 3 uses."
        ),
    )

    quickbooks_realm_id = models.CharField(max_length=50, blank=True, null=True)
    xero_tenant_id = models.CharField(max_length=50, blank=True, null=True)

    # ── TaskType management (migration 0106) ──
    default_task_type_set = models.ForeignKey(
        'tracker.TaskTypeSet',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='clients_using_as_default',
        help_text='Optional: overrides the org default TaskTypeSet for this client.',
    )

    
    # ═══════════════════════════════════════════════════════════════════════
    
    class Meta:
        unique_together = [['org', 'code']]
        constraints = [
            # Prevent duplicate QB imports per org
            models.UniqueConstraint(
                fields=['org', 'quickbooks_id'],
                name='unique_quickbooks_client',
                condition=models.Q(quickbooks_id__isnull=False),
            ),
            # Prevent duplicate Xero imports per org
            models.UniqueConstraint(
                fields=['org', 'xero_id'],
                name='unique_xero_client',
                condition=models.Q(xero_id__isnull=False),
            ),
        ]
    
    def save(self, *args, **kwargs):
        if not self.code and self.name:
            self.code = self.name[:10].upper().replace(' ', '')[:10]
        super().save(*args, **kwargs)
    
    def __str__(self):
        source = f" [{self.imported_from.upper()}]" if self.imported_from else ""
        return f"{self.name}{source}"


class ClientBillingProfile(models.Model):
    """
    Per-client billing arrangement — the coordination layer the timesheet→billing
    export reads. It ties together HOW a client is billed (hourly / flat-fee /
    non-billable), WHICH system the approved time lands in (drives the export
    format), and the customer/item mapping.

    Deliberately thin — it does NOT duplicate what already exists:
      • Hourly RATES resolve through BillingRate.get_rate_for_block
        (Client+TaskType → Client → TaskType → defaults). Not stored here.
      • Customer mapping falls back to Client.quickbooks_id / QboCompanyMapping /
        ExternalClientMapping when the override fields below are blank.
    Only the genuinely missing concept lives here: the fee arrangement enum, the
    flat-fee amount (owner chose self-contained over ClientBudget), and the
    target-system selector.
    """
    BILLING_TYPE_CHOICES = [
        ('hourly', 'Hourly'),
        ('flat_fee', 'Flat fee / retainer'),
        ('non_billable', 'Non-billable'),
    ]
    BILLING_SYSTEM_CHOICES = [
        ('qb_desktop', 'QuickBooks Desktop'),
        ('qbo', 'QuickBooks Online'),
        ('xero', 'Xero'),
        ('csv_other', 'CSV / other'),
    ]
    FLAT_PERIOD_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annual', 'Annual'),
        ('per_project', 'Per project'),
    ]

    client = models.OneToOneField(
        Client, on_delete=models.CASCADE, related_name='billing_profile'
    )
    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='client_billing_profiles'
    )

    billing_type = models.CharField(
        max_length=20, choices=BILLING_TYPE_CHOICES, default='hourly',
        help_text='How this client is billed. Drives whether the export carries hours×rate, a flat fee, or nothing.',
    )

    # Flat-fee / retainer (used when billing_type='flat_fee').
    flat_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Fee amount when billing_type is flat_fee.',
    )
    flat_period = models.CharField(
        max_length=20, choices=FLAT_PERIOD_CHOICES, blank=True, default='',
        help_text='Billing cadence for the flat fee.',
    )

    # Target system → decides the export format for this client's approved time.
    billing_system = models.CharField(
        max_length=20, choices=BILLING_SYSTEM_CHOICES, default='csv_other',
    )

    # Customer + item mapping overrides. Blank → fall back to Client.quickbooks_id /
    # QboCompanyMapping and per-TaskType item mapping at export time.
    external_customer_id = models.CharField(
        max_length=100, blank=True, default='',
        help_text='Customer/Job ID in the billing system (e.g. QB "Customer:Job"). Falls back to Client.quickbooks_id.',
    )
    external_customer_name = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Customer/Job display name in the billing system, for export readability.',
    )
    default_item_name = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Default service/item on exported line items when a task type has no specific mapping.',
    )

    notes = models.TextField(blank=True, default='')

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )

    def __str__(self):
        return f"{self.client.name} — {self.get_billing_type_display()}"


# tracker/models.py - Update ClientAssignment

class ClientAssignment(models.Model):
    """
    Links users to clients they can access.
    If a client has no assignments, it's visible to everyone (legacy behavior).
    If a client has ANY assignments, only assigned users + admins can see it.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='client_assignments')
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='assignments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='client_assignments')
    
    # Role on this client (optional - for future use)
    ROLE_CHOICES = [
        ('Partner', 'Partner'),       # Engagement partner, signs off
        ('Manager', 'Manager'),       # Supervises work
        ('Senior', 'Senior'),         # Experienced staff
        ('Staff', 'Staff'),           # Does the work
        ('Admin', 'Admin'),           # Billing/admin support
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, null=True, blank=True)
    
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='assignments_made'
    )
    
    class Meta:
        unique_together = ['client', 'user']
        indexes = [
            models.Index(fields=['user', 'client']),
            models.Index(fields=['organization', 'user']),
        ]
    
    def __str__(self):
        return f"{self.user.username} → {self.client.name}"

# tracker/models.py

class ClientRequest(models.Model):
    """Requests from users to add new clients."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='client_requests')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='client_requests')
    client_name = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='approved_client_requests'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']



# tracker/models_billing.py
# Add these to your existing models.py or as a separate file

from django.db import models
from django.conf import settings


class Invoice(models.Model):
    """
    Tracks invoiced amounts per client for realization calculations.
    Can be imported from CSV, QuickBooks, or Xero.
    """
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.CASCADE,
        related_name='invoices',
        null=True,
        blank=True
    )
    
    # Invoice details
    invoice_number = models.CharField(max_length=100)
    invoice_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    hours_billed = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    
    # For matching before client is linked
    client_code = models.CharField(max_length=50, blank=True)
    client_name = models.CharField(max_length=255, blank=True)
    
    # Source tracking
    SOURCE_CHOICES = [
        ('csv', 'CSV Import'),
        ('quickbooks', 'QuickBooks'),
        ('xero', 'Xero'),
        ('manual', 'Manual Entry'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('voided', 'Voided'),
        ('overdue', 'Overdue'),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='sent', blank=True)

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    external_id = models.CharField(max_length=100, blank=True)  # QBO/Xero invoice ID
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_invoices'
    )
    
    class Meta:
        ordering = ['-invoice_date', '-created_at']
        unique_together = [
            ['org', 'invoice_number'],  # Prevent duplicate invoice numbers per org
        ]
        indexes = [
            models.Index(fields=['org', 'invoice_date']),
            models.Index(fields=['org', 'client']),
            models.Index(fields=['client_code']),
        ]
    
    def __str__(self):
        return f"{self.invoice_number} - {self.client_name or self.client_code} - ${self.amount}"


class ClientBudget(models.Model):
    """
    Optional: Track budget/retainer hours per client per period.
    Useful for firms with fixed-fee or retainer arrangements.
    """
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='client_budgets'
    )
    client = models.ForeignKey(
        'Client',
        on_delete=models.CASCADE,
        related_name='budgets'
    )
    
    # Budget period
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Budget amounts
    budget_hours = models.DecimalField(max_digits=8, decimal_places=2)
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Notes
    description = models.CharField(max_length=255, blank=True)  # e.g., "Q1 2026 Tax Prep"
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-period_start']
    
    def __str__(self):
        return f"{self.client.name} - {self.period_start} to {self.period_end} - {self.budget_hours}h"


# ============================================================================
# ADD TO tracker/models.py - Client Groups for Bulk Assignment
# ============================================================================

class ClientGroup(models.Model):
    """
    Groups clients for easier bulk assignment.
    Examples: "Partner: Smith", "Tax Clients", "Audit Clients", "New 2024"
    """
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='client_groups'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    color = models.CharField(
        max_length=20,
        default='slate',
        help_text='Color for UI display: slate, red, orange, amber, emerald, blue, purple, pink'
    )
    icon = models.CharField(
        max_length=50,
        default='folder',
        help_text='Icon name: folder, briefcase, users, star, tag'
    )
    
    # Many-to-many with clients
    clients = models.ManyToManyField(
        'Client',
        related_name='groups',
        blank=True
    )
    
    # Optional: Default team members for this group
    # When a new client is added to the group, auto-assign these users
    default_assignees = models.ManyToManyField(
        'auth.User',
        related_name='default_group_assignments',
        blank=True,
        help_text='Users automatically assigned when clients are added to this group'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_client_groups'
    )
    
    class Meta:
        unique_together = ['org', 'name']
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} ({self.clients.count()} clients)"
    
    @property
    def client_count(self):
        return self.clients.count()
    
    def assign_team_to_all_clients(self, user_ids, created_by=None):
        """
        Assign a list of users to ALL clients in this group.
        Returns count of assignments created.
        """
        from .models import ClientAssignment  # Avoid circular import
        
        created = 0
        for client in self.clients.all():
            for user_id in user_ids:
                _, was_created = ClientAssignment.objects.get_or_create(
                    org=self.org,
                    client=client,
                    user_id=user_id,
                    defaults={'assigned_by': created_by}
                )
                if was_created:
                    created += 1
        return created


# tracker/models.py - Add Integration model

class Integration(models.Model):
    """OAuth integrations with external services."""
    PROVIDER_CHOICES = [
        ('quickbooks', 'QuickBooks Online'),
        ('xero', 'Xero'),
        ('karbon', 'Karbon'),
        ('cch_axcess', 'CCH Axcess Practice'),
    ]
    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='integrations')
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)
    
    is_connected = models.BooleanField(default=False)
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Provider-specific
    realm_id = models.CharField(max_length=100, blank=True)  # QuickBooks
    tenant_id = models.CharField(max_length=100, blank=True)  # Xero
    
    oauth_state = models.CharField(max_length=100, blank=True)  # For OAuth flow
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    last_synced_at = models.DateTimeField(null=True, blank=True)

    # ── CCH Axcess sync extensions (migration 0109) ──
    enforce_matrix = models.BooleanField(
        default=False,
        help_text='If True, the validator enforces the client/task/staff matrix '
                  'rules synced from this integration. If False, matrix rules are '
                  'advisory only (logged but not blocking).',
    )
    auto_create_internal_records = models.BooleanField(
        default=True,
        help_text='If True, sync auto-creates internal Client / TaskType records '
                  'when it encounters external records with no mapping.',
    )
    last_sync_status = models.CharField(
        max_length=32, blank=True, default='',
        help_text='Result of last sync: success, partial, failed.',
    )
    last_sync_error = models.TextField(blank=True, default='')
    
    class Meta:
        unique_together = ['organization', 'provider']


class QboCompanyMapping(models.Model):
    """Server-owned map: a QuickBooks Online company (realmId) -> a Client.

    The browser extension reads the active company id from the
    `qbo.currentcompanyid` cookie and the desktop agent carries it to the
    backend as `qbo_company_id` (persisted on RawEvent.ctx and lifted onto
    Block.hints in compaction). Accountants switch between many client
    *companies* in QBO, and the working URL never names the company — so this
    map is how a QBO work block is attributed to the right client.

    A row with `client=None` is an UNMAPPED company that has been seen but not
    yet linked — i.e. a review queue. `suggested_name` is an advisory best guess
    (e.g. the block's window title) to help whoever maps it. This is the online
    cousin of the QuickBooks Desktop company-id mapping.
    """
    org = models.ForeignKey('Organization', on_delete=models.CASCADE, related_name='qbo_company_mappings')
    realm_id = models.CharField(
        max_length=50, db_index=True,
        help_text='QBO company id (realmId) from the qbo.currentcompanyid cookie',
    )
    client = models.ForeignKey(
        'Client', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='qbo_company_mappings',
        help_text='Mapped client; null = unmapped / queued for review',
    )
    suggested_name = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Advisory best-guess company/client name shown in the mapping UI',
    )
    times_seen = models.PositiveIntegerField(default=0)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['org', 'realm_id']]
        indexes = [models.Index(fields=['org', 'client'], name='tracker_qbo_org_id_client_idx')]

    def __str__(self):
        return f"QBO {self.realm_id} -> {self.client_id or 'UNMAPPED'} (org {self.org_id})"




class Project(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = (("org", "client", "name"),)
        indexes = [models.Index(fields=["org", "client", "name"])]

    def __str__(self):
        return f"{self.name} ({self.client.name})"


class InvoiceConflict(models.Model):
    """Tracks invoice amount discrepancies between TimeTracker and billing source."""
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='invoice_conflicts')
    invoice = models.ForeignKey('Invoice', on_delete=models.CASCADE, related_name='conflicts')
    tt_amount = models.DecimalField(max_digits=10, decimal_places=2)
    source_amount = models.DecimalField(max_digits=10, decimal_places=2)
    source = models.CharField(max_length=50)  # 'quickbooks', 'xero', 'csv'
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='resolved_conflicts'
    )
    resolution = models.CharField(
        max_length=20, blank=True,
        choices=[('accept_source', 'Accept source'), ('keep_tt', 'Keep TimeTracker')]
    )

    class Meta:
        ordering = ['-detected_at']


class Task(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=200)
    billable = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}"


 # tracker/models.py

class Invitation(models.Model):
    """Pending invitation to join an org"""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(max_length=20, default='member')
    token = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    
    @classmethod
    def create_invite(cls, org, email, role, invited_by):
        import secrets
        return cls.objects.create(
            organization=org,
            email=email,
            role=role,
            invited_by=invited_by,
            token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + timedelta(days=7),
        )

# ==============================
# ======  CLASSIFICATION  ======
# ==============================
# tracker/models.py - REPLACE YOUR Block MODEL

import hashlib
from django.db import models
from django.conf import settings
from django.contrib.auth.models import Group
from django.utils import timezone

class ActiveBlockManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)

# tracker/models.py - COMPLETE BLOCK MODEL
# Replace your existing Block class with this

class Block(models.Model):
    # ===============================
    # Core identification
    # ===============================
    org = models.ForeignKey('Organization', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    device_id = models.CharField(max_length=64, db_index=True, default="unknown")
    hostname = models.CharField(max_length=120)
    
    # ===============================
    # Time tracking
    # ===============================
    start = models.DateTimeField()
    end = models.DateTimeField()
    day = models.DateField(db_index=True, null=True, blank=True)
    minutes = models.IntegerField(null=True, blank=True)
    
    # ===============================
    # Activity context
    # ===============================
    title = models.TextField(blank=True, default="")
    window_title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, default="")
    file_path = models.TextField(blank=True, default="")
    app_name = models.CharField(max_length=255, blank=True, default="")
    bundle_id = models.CharField(max_length=255, blank=True, default="")
    hints = models.JSONField(default=dict, blank=True)
    
    # ===============================
    # Meeting metadata
    # ===============================
    description = models.TextField(blank=True, default="")
    attendees = models.JSONField(default=list, blank=True)
    
    # ===============================
    # Classification (the valuable data)
    # ===============================
    category_hours = models.JSONField(default=dict, blank=True)
    client = models.ForeignKey('Client', null=True, blank=True, on_delete=models.SET_NULL)
    project = models.ForeignKey('Project', null=True, blank=True, on_delete=models.SET_NULL)
    task = models.ForeignKey('Task', null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True, default="")
    
    # Legacy lock (keep for backwards compatibility)
    locked = models.BooleanField(default=False)

    # ===============================
    # NEW: Classification state machine (Phase 1 rebuild)
    # ===============================
    classification_state = models.CharField(
        max_length=20,
        choices=[
            ('captured',   'Captured — no classification yet'),
            ('proposed',   'Proposed — classifier guessed, awaiting confirmation'),
            ('committed',  'Committed — confirmed, billable'),
            ('suppressed', 'Suppressed — not a real activity'),
        ],
        default='captured',
        db_index=True,
        help_text='Explicit state machine replacing the binary is_categorized flag.',
    )
    state_changed_at = models.DateTimeField(null=True, blank=True)
    state_changed_by = models.CharField(
        max_length=30,
        choices=[
            ('classifier',      'Auto-classified by ClassificationService'),
            ('user',            'User confirmed via UI'),
            ('user_edit',       'User edited and committed'),
            ('admin_bulk',      'Admin bulk operation'),
            ('auto_commit_eod', 'End-of-day auto-commit'),
            ('rule',            'Org routing rule'),
            ('correction',      'User corrected after commit'),
        ],
        null=True, blank=True,
    )

    # ===============================
    # NEW: Proposed classification (audit trail of classifier output)
    # ===============================
    proposed_client = models.ForeignKey(
        'Client',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    proposed_category = models.CharField(max_length=100, blank=True, default='')
    proposed_confidence = models.FloatField(default=0.0)
    proposed_at = models.DateTimeField(null=True, blank=True)
    proposed_signals = models.JSONField(default=list, blank=True)
    proposed_reasoning = models.TextField(blank=True, default='')

    # ===============================
    # AI attempt tracking (Stage 10 re-fire prevention)
    # ===============================
    # The 5-min safety-net task (ai_classify_uncategorized_blocks) re-queries
    # all captured blocks every cycle. Without this, an unclassifiable block
    # (PDF, payroll register, dialog) gets re-sent to OpenAI every 5 minutes
    # for 24h = ~288 wasted calls/block/day. These fields let the task skip
    # blocks already attempted N times / too recently. A manual reclassify
    # resets the counter so a block made classifiable later can be re-tried.
    ai_attempt_count = models.IntegerField(default=0)
    ai_last_attempt_at = models.DateTimeField(null=True, blank=True)

    # ===============================
    # AI vs Agent disagreement tracking (Stage 10 validation)
    # ===============================
    # When Stage 10 runs to validate the agent's deterministic client choice
    # and disagrees with high confidence (>=0.85), these fields capture it
    # for surfacing in the web app's daily review. The block's actual client
    # field stays as the agent set it — these fields are advisory only.
    ai_disagrees_with_agent = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Stage 10 AI proposes a different client than the agent assigned',
    )
    ai_proposed_client = models.ForeignKey(
        'Client',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text='Client AI proposed when disagreeing with agent',
    )
    ai_proposed_confidence = models.FloatField(
        default=0.0,
        help_text='AI confidence in its proposed client (0.85-1.0)',
    )
    ai_disagreement_reasoning = models.TextField(
        blank=True, default='',
        help_text='AI evidence for the disagreement, shown in daily review tooltip',
    )
    ai_disagreement_resolved_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the user reviewed and dismissed/accepted the AI suggestion',
    )
    ai_disagreement_resolution = models.CharField(
        max_length=20,
        choices=[
            ('accepted', 'User accepted AI suggestion'),
            ('dismissed', 'User kept agent client'),
            ('changed_to_other', 'User picked a different client entirely'),
        ],
        null=True, blank=True,
        help_text='How the user resolved the disagreement',
    )

    # Mail signal disagreement — set by Stage 7 classifier when MailSignals
    # in the block's time window point to a different client than the one
    # the agent / classifier ultimately attributed to. Surfaced in daily
    # review for user confirmation, but does NOT auto-overwrite the client.
    mail_disagrees_with_agent = models.BooleanField(
        default=False,
        help_text='True when Stage 7 mail signal points to a different client than the block was attributed to.',
    )
    mail_proposed_client = models.ForeignKey(
        'Client',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='mail_proposed_blocks',
        help_text='Client that mail signals suggest, if different from block.client.',
    )
    mail_proposed_confidence = models.FloatField(
        null=True, blank=True,
        help_text='Stage 7 signal confidence for the mail-proposed client (0.0-1.0).',
    )
    mail_disagreement_reasoning = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Human-readable explanation of why mail signal disagrees, shown in Daily Review.',
    )

    # Mirrors ai_disagreement_resolved_at — set when user actions the mail
    # disagreement (accept / dismiss / change). today_time filters by this
    # being null to know what's still "open" for the user to review.
    mail_disagreement_resolved_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the user resolved the mail disagreement; null = still pending review.',
    )
 
    # Mirrors ai_disagreement_resolution. Stores the user's action so we
    # can compute mail-signal accuracy stats later.
    mail_disagreement_resolution = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text='How the user resolved the mail disagreement: accepted / dismissed / changed_to_other.',
    )

    # ─────────────────────────────────────────────────────────────────────
    # Calendar signal disagreement — set by Stage 6 classifier (v1.3.42)
    # when an overlapping CalendarEvent with a matched client disagrees with
    # the block's final attribution. Surfaced in Daily Review for user
    # confirmation, but does NOT auto-overwrite the client. Mirrors the
    # mail_disagrees_with_agent pattern above.
    # ─────────────────────────────────────────────────────────────────────
    calendar_disagrees_with_agent = models.BooleanField(
        default=False,
        help_text='True when Stage 6 calendar event points to a different client than the block was attributed to.',
    )
    calendar_proposed_client = models.ForeignKey(
        'Client',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='calendar_proposed_blocks',
        help_text='Client that the overlapping calendar event suggests, if different from block.client.',
    )
    calendar_proposed_confidence = models.FloatField(
        null=True, blank=True,
        help_text='Stage 6 signal confidence for the calendar-proposed client (0.55-0.85).',
    )
    calendar_disagreement_reasoning = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Human-readable explanation of why calendar signal disagrees, shown in Daily Review.',
    )

    # Source of the calendar disagreement — 'classifier' (auto-attribution)
    # vs 'manual' (user explicitly picked a different client). Drives banner
    # copy in Daily Review: classifier disagreements get the standard
    # "reassign?" prompt; manual disagreements get a softer "keep or reassign?".
    calendar_disagreement_source = models.CharField(
        max_length=20,
        blank=True,
        default='',
        choices=[
            ('classifier', 'Classifier picked vs. calendar'),
            ('manual', 'User manually picked vs. calendar'),
        ],
        help_text='Which attribution path produced the conflict. Drives Daily Review banner copy.',
    )

    # Mirrors mail_disagreement_resolved_at — set when user actions the
    # calendar disagreement (accept / dismiss / change). today_time filters
    # by this being null to know what's still "open" for the user to review.
    calendar_disagreement_resolved_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When the user resolved the calendar disagreement; null = still pending review.',
    )

    # Mirrors mail_disagreement_resolution. Stores the user's action so we
    # can compute calendar-signal accuracy stats later.
    calendar_disagreement_resolution = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text='User action when resolving (e.g. accepted, dismissed, reassigned).',
    )
 

    # ===============================
    # Mobile review flags
    # ===============================
    needs_review = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Flagged for manual review — timer vs calendar discrepancy or unusual duration',
    )
    review_reason = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Human-readable reason why this entry was flagged for review',
    )

    # ===============================
    # Soft delete
    # ===============================
    objects = ActiveBlockManager()  # Default excludes deleted
    all_objects = models.Manager()  # Use this to include deleted blocks
    deleted_at = models.DateTimeField(null=True, blank=True, default=None)

    taxpayer_bucket = models.ForeignKey(
    'TaxpayerBucket',
    null=True, blank=True,
    on_delete=models.SET_NULL,
    related_name='blocks',
    )
    
    taxpayer_name = models.CharField(max_length=120, blank=True, null=True)
    taxpayer_id_hash = models.CharField(max_length=16, blank=True, null=True, db_index=True)
    tax_return_type = models.CharField(max_length=16, blank=True, null=True)

    # ===============================
    # Immutability Tracking
    # ===============================
    is_categorized = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True once categories are assigned - block becomes immutable"
    )
    categorized_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when this block was first categorized"
    )
    categorized_by = models.CharField(
        max_length=20,
        choices=[
            ('ai', 'AI Auto-Categorized'),
            ('manual', 'User Manual Entry'),
            ('correction', 'User Corrected AI'),
            ('import', 'Imported Data'),
            ('pattern', 'Learned Pattern'),
        ],
        null=True,
        blank=True,
        db_index=True,
        help_text="Source of the categorization"
    )

    
    # ===============================
    # Approval Workflow
    # ===============================
    approved = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Approved for billing by user/manager"
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this block was approved"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='approved_blocks',
        help_text="Who approved this block"
    )

    # ===============================
    # Task Type (Firm-wide categories)
    # ===============================
    task_type = models.ForeignKey(
        'TaskType',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='blocks',
        help_text="Firm-wide activity type (Tax Prep, Research, etc.)"
    )

    # ===============================
    # Billing Fields
    # ===============================
    is_billable = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this time is billable to client"
    )
    billing_rate = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Hourly rate applied to this block"
    )
    billing_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Calculated: (minutes/60) * billing_rate"
    )
    
    # ===============================
    # Timesheet Link
    # ===============================
    timesheet = models.ForeignKey(
        'Timesheet',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='blocks',
        help_text="Weekly timesheet this block belongs to"
    )
    
    # ===============================
    # Invoice Fields
    # ===============================
    description_override = models.TextField(
        blank=True,
        default='',
        help_text="Custom description for invoice line item (overrides auto-generated)"
    )
    invoiced = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Has this block been included in an invoice?"
    )
    invoiced_at = models.DateTimeField(
        null=True,
        blank=True
    )
    invoice_reference = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Reference to external invoice (e.g., QBO invoice ID)"
    )
    # Integration push tracking
    qb_time_activity_id = models.CharField(
        max_length=64, blank=True, null=True, db_index=True,
        help_text='QuickBooks TimeActivity ID after push'
    )
    xero_invoice_id = models.CharField(
        max_length=64, blank=True, null=True, db_index=True,
        help_text='Xero Invoice ID after push'
    )

    is_meeting = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if this block represents a detected video/audio meeting"
    )
    meeting_app = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text="Canonical meeting app key: zoom, teams, meet, webex, facetime, slack, discord"
    )
    meeting_detection_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="0.0-1.0 confidence score from detector (signal count / 3)"
    )
    meeting_detection_sources = models.JSONField(
        null=True,
        blank=True,
        help_text="List of detection sources: ['audio','camera','process','title']"
    )

    # ===============================
    # AI Classification Metadata
    # ===============================
    ai_extracted_client = models.CharField(max_length=255, blank=True, null=True)
    ai_confidence = models.FloatField(default=0.0)
    ai_category = models.CharField(max_length=100, blank=True, default="")
    ai_processed_at = models.DateTimeField(null=True, blank=True)
    ai_hash = models.CharField(max_length=64, blank=True, null=True)
    
    # ===============================
    # Timestamps
    # ===============================
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    # ===============================
    # METHODS
    # ===============================
    
    def compute_ai_hash(self):
        """Hash title/url/path for quick change detection."""
        raw = f"{self.window_title or ''}|{self.url or ''}|{self.file_path or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    
    def has_ai_inputs_changed(self):
        """Returns True if the hash changed since last save."""
        new_hash = self.compute_ai_hash()
        return self.ai_hash != new_hash
    
    def is_protected(self):
        """
        Returns True if this block should not be modified.
        Protected blocks: categorized, approved, or explicitly locked.
        """
        return self.is_categorized or self.approved or self.locked
    
    def can_edit(self, user=None):
        """
        Check if a user can edit this block.
        Rules:
        - Uncategorized blocks: Anyone can edit
        - AI-categorized blocks: Original user can correct once
        - Manual/corrected blocks: Need manager approval
        - Approved blocks: Locked unless manager
        """
        if not self.is_categorized:
            return True
        
        if self.approved:
            return False
        
        if self.categorized_by == 'ai' and user and user == self.user:
            return True
        
        if self.categorized_by in ('manual', 'correction'):
            return False
        
        return False
    
    def save(self, *args, **kwargs):
        # Pull out our new flag before passing kwargs to super
        force_classifier = kwargs.pop('force_classifier', False)

        # ===============================
        # 1. Auto-set day and minutes from start/end
        # ===============================
        if self.start:
            self.day = self.start.astimezone(timezone.get_current_timezone()).date()
        if self.start and self.end and not self.minutes:
            mins = int((self.end - self.start).total_seconds() // 60)
            self.minutes = max(0, mins)

        # ===============================
        # 1b. Internal firm work is never billable
        # ===============================
        # Blocks tied to an internal client ("Internal" or "Internal - <x>",
        # e.g. Internal - Tax / Internal - Accounting) never bill, regardless of
        # category or how is_billable was set upstream. Enforcing it here — the
        # single write chokepoint — keeps reports, the weekly timesheet, and
        # invoicing in agreement (they all read this stored flag / filter on it
        # in SQL, so a report-only rule can't reach them).
        if self.is_billable and self.client_id:
            from tracker.industry_categories import is_internal_client_name
            cache = getattr(getattr(self, "_state", None), "fields_cache", {})
            cached_client = cache.get("client")
            if cached_client is not None:
                client_name = cached_client.name
            else:
                client_name = (
                    Client.objects.filter(pk=self.client_id)
                    .values_list("name", flat=True)
                    .first()
                )
            if client_name and is_internal_client_name(client_name):
                self.is_billable = False

        # ===============================
        # 2. Auto-set immutability flags when categories assigned
        # ===============================
        # NOTE: All auto-promotion of classification fields removed in Approach B.
        # ClassificationService and explicit user-action paths (in views.py) are
        # the only writers of is_categorized and classification_state. Any code
        # that wants to mark a block as categorized must do so explicitly.
        
        # ===============================
        # 3. Compute and store hash for change detection
        # ===============================
        new_hash = self.compute_ai_hash()
        if not self.ai_hash or self.ai_hash != new_hash:
            self.ai_hash = new_hash
        
        # ===============================
        # 4. Auto-calculate billing amount
        # ===============================
        if self.is_billable and self.billing_rate and self.minutes:
            self.billing_amount = (Decimal(self.minutes) / 60) * self.billing_rate
        elif not self.is_billable:
            self.billing_amount = Decimal('0.00')
        
        # ===============================
        # 5. Prevent modification of protected blocks
        # ===============================
        if self.pk:  # Only check on updates, not creates
            try:
                old = Block.all_objects.get(pk=self.pk)
                # NEW: ClassificationService can update Captured/Proposed blocks freely
                if force_classifier and old.classification_state in ('captured', 'proposed', 'committed'):
                    pass  # Skip protection check — allows AI/mail disagreement resolution
                          # to modify committed blocks when user accepts the suggestion
                elif old.is_protected() and not kwargs.pop('force_update', False):
                    protected_fields = {
                        'category_hours', 'client', 'project', 'task',
                        'start', 'end', 'minutes'
                    }
                    for field in protected_fields:
                        if getattr(old, field) != getattr(self, field):
                            raise ValueError(
                                f"Cannot modify protected block {self.pk}. "
                                f"Block is {old.categorized_by} and "
                                f"{'approved' if old.approved else 'categorized'}."
                            )
            except Block.DoesNotExist:
                pass
        
        super().save(*args, **kwargs)
    
    # ===============================
    # META
    # ===============================
    class Meta:
        indexes = [
            # Core lookups
            models.Index(fields=["org", "user", "day"]),
            models.Index(fields=["org", "start"]),
            models.Index(fields=["org", "client"]),
            models.Index(fields=["org", "project"]),
            models.Index(fields=["org", "task"]),
            models.Index(fields=["updated_at"]),
            
            # Immutability & approval
            models.Index(fields=["is_categorized", "user", "start"]),
            models.Index(fields=["categorized_by", "org"]),
            models.Index(fields=["approved", "user", "day"]),
            models.Index(fields=["approved", "org", "client"]),
            
            # AI processing
            models.Index(fields=["is_categorized", "org", "day"]),
            models.Index(fields=["is_categorized", "ai_processed_at"]),
            
            # Billing & invoicing
            models.Index(fields=['is_billable', 'org', 'client']),
            models.Index(fields=['timesheet', 'user']),
            models.Index(fields=['invoiced', 'approved', 'client']),

            # NEW: classification state machine (Phase 1 rebuild)
            models.Index(fields=['classification_state', 'user', 'day']),
            models.Index(fields=['org', 'classification_state']),

            # Stage 10 disagreements — used by daily review to surface flagged blocks
            models.Index(fields=['user', 'day', 'ai_disagrees_with_agent']),
            models.Index(fields=['ai_disagrees_with_agent', 'ai_disagreement_resolved_at']),
        ]
        
        ordering = ['-start']
    
    def __str__(self):
        status = "✅" if self.is_categorized else "⏳"
        category = self.ai_category or (list(self.category_hours.keys())[0] if self.category_hours else 'Unclassified')
        return f"{status} {self.user.username} - {category} - {self.day}"



class Suggestion(models.Model):
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="suggestions")
    label_type = models.CharField(max_length=20, choices=[("client", "client"), ("project", "project"), ("task", "task")])
    value_text = models.CharField(max_length=255)
    confidence = models.FloatField(default=0.0)
    source = models.CharField(max_length=20, default="rule")
    created_at = models.DateTimeField(auto_now_add=True)


class Rule(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    pattern = models.CharField(max_length=500)
    field = models.CharField(max_length=20, choices=[("client", "client"), ("project", "project"), ("task", "task")])
    value_text = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=[("contains", "contains"), ("regex", "regex"), ("glob", "glob")], default="contains")
    active = models.BooleanField(default=True)


# ===============================
# ======  TIME ENTRIES  =========
# ===============================
class TimecardEntry(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    date = models.DateField(db_index=True)

    client = models.ForeignKey(Client, on_delete=models.CASCADE, null=True, blank=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True)

    total_hours = models.DecimalField(max_digits=5, decimal_places=2)
    category_breakdown = models.JSONField(default=dict)
    activities_summary = models.JSONField(default=list)

    confidence_score = models.FloatField(default=1.0)
    needs_review = models.BooleanField(default=False)

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("pending", "Pending Review"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    block_ids = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-total_hours"]
        unique_together = [["org", "user", "date", "client"]]
        indexes = [
            models.Index(fields=["org", "user", "date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        client_name = self.client.name if self.client else "Unknown"
        return f"{self.user} - {client_name} - {self.date} ({self.total_hours}h)"

    def approve(self, notes=""):
        self.status = "approved"
        self.reviewed_at = timezone.now()
        if notes:
            self.notes = notes
        self.save()
        if self.block_ids:
            Block.objects.filter(id__in=self.block_ids).update(locked=True)

    def reject(self, reason=""):
        self.status = "rejected"
        self.reviewed_at = timezone.now()
        self.notes = reason
        self.save()


# tracker/models.py - ADD THIS NEW MODEL (after Client, before Project)

class TaskType(models.Model):
    """
    Firm-wide task/activity categories.
    Examples: "Tax Preparation", "Email/Communication", "Research", "Bookkeeping"
    These apply across ALL clients and projects.
    """
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="task_types")
    name = models.CharField(max_length=100)  # "Tax Preparation", "Research"
    code = models.CharField(max_length=20, blank=True, default='')  # "TAX", "RES"
    
    # Billing
    is_billable = models.BooleanField(default=True)
    default_rate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    
    # UI
    color = models.CharField(max_length=7, default='#3B82F6')  # Hex color for charts
    icon = models.CharField(max_length=50, blank=True, default='')  # Optional icon name
    sort_order = models.IntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = [['org', 'name']]
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['org', 'is_active']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.code and self.name:
            self.code = self.name[:6].upper().replace(' ', '')
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name


# Default task types to seed for new CPA firms
DEFAULT_CPA_TASK_TYPES = [
    {'name': 'Tax Preparation', 'code': 'TAX', 'color': '#10B981', 'is_billable': True},
    {'name': 'Tax Planning', 'code': 'TAXPL', 'color': '#059669', 'is_billable': True},
    {'name': 'Audit & Assurance', 'code': 'AUDIT', 'color': '#6366F1', 'is_billable': True},
    {'name': 'Bookkeeping', 'code': 'BOOK', 'color': '#8B5CF6', 'is_billable': True},
    {'name': 'Payroll', 'code': 'PAY', 'color': '#A855F7', 'is_billable': True},
    {'name': 'Advisory/Consulting', 'code': 'ADV', 'color': '#EC4899', 'is_billable': True},
    {'name': 'Client Communication', 'code': 'COMM', 'color': '#F59E0B', 'is_billable': True},
    {'name': 'Research', 'code': 'RES', 'color': '#3B82F6', 'is_billable': True},
    {'name': 'Document Review', 'code': 'DOC', 'color': '#06B6D4', 'is_billable': True},
    {'name': 'Admin/Internal', 'code': 'ADMIN', 'color': '#6B7280', 'is_billable': False},
    {'name': 'Training', 'code': 'TRAIN', 'color': '#F97316', 'is_billable': False},
]

# ===============================
# ======  AI + ORG CONFIG  ======
# ===============================
class AIProcessingLog(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    operation_type = models.CharField(max_length=50)
    input_data = models.JSONField()
    output_data = models.JSONField()
    model_used = models.CharField(max_length=50)
    tokens_used = models.IntegerField(default=0)
    processing_time_ms = models.IntegerField(default=0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-timestamp"]


class OrganizationSettings(models.Model):
    org = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="settings")
    company_name = models.CharField(max_length=200)
    industry = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    internal_keywords = models.JSONField(default=list)
    default_internal_project = models.CharField(max_length=200, blank=True)
    custom_instructions = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organization Settings"
        verbose_name_plural = "Organization Settings"

    def __str__(self):
        return f"Settings for {self.company_name}"


class KnownEntity(models.Model):
    ENTITY_TYPES = [
        ("client", "Client"),
        ("project", "Project"),
        ("category", "Category"),
        ("person", "Person"),
    ]
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="known_entities")
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPES)
    name = models.CharField(max_length=200)
    aliases = models.JSONField(default=list)
    parent_client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL)
    description = models.TextField(blank=True)
    is_internal = models.BooleanField(default=False)
    confidence_boost = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["org", "entity_type", "name"]
        ordering = ["entity_type", "name"]

    def __str__(self):
        return f"{self.entity_type}: {self.name}"


class AITrainingExample(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="training_examples")
    text_content = models.TextField()
    correct_client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_examples")
    correct_project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_examples")
    correct_categories = models.JSONField(default=dict)
    original_prediction = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class OrgInstallToken(models.Model):
    """Token for MDM/silent agent installation"""
    org = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='install_token')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    is_active = models.BooleanField(default=True)
    
    def save(self, *args, **kwargs):
        if not self.token:
            self.token = f"tt_org_{secrets.token_urlsafe(24)}"
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.org.name} - {self.token[:20]}..."


class AgentRegistration(models.Model):
    """Track installed desktop agents"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agents')
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='agents')
    machine_name = models.CharField(max_length=255)
    os = models.CharField(max_length=20)  # 'windows' or 'macos'
    os_version = models.CharField(max_length=100, blank=True)
    agent_key = models.CharField(max_length=100, unique=True, db_index=True)
    agent_version = models.CharField(max_length=20, blank=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['user', 'machine_name']
    
    def __str__(self):
        return f"{self.user.username} @ {self.machine_name}"


class OrgProfile(models.Model):
    '''Extended profile for organization/group'''
    org = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='profile')
    billing_email = models.EmailField(blank=True, null=True)
    billing_contact = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Profile for {self.org.name}"

# ===============================
# ======  CLASSIFICATION RULES ==
# ===============================
class OrgRoutingRule(models.Model):
    """
    A per-firm rule that routes window activity to a specific client
    based on what app/title/file is in focus.
    """
 
    # -- What triggers the rule -----------------------------------------
    MATCH_TYPE_CHOICES = [
        ('exe', 'Exact Process Name (exe)'),
        ('exe_family', 'App Family (matches multiple versions)'),
        ('title_contains', 'Title Contains (case-insensitive)'),
        ('title_regex', 'Title Matches Regex'),
        ('file_path_contains', 'File Path Contains'),
        # NEW (Phase 1 rebuild) — matcher.py already supports these
        ('duration_gt', 'Block Duration Greater Than (minutes)'),
        ('inside_meeting', 'Block Is Inside a Meeting'),
        ('idle_gt', 'Idle Duration Greater Than (minutes)'),
        ('task_type_matrix', 'TaskType Matrix Rule'),
    ]
    match_type = models.CharField(
        max_length=32,
        choices=MATCH_TYPE_CHOICES,
        help_text="What part of the window event this rule matches on.",
    )
    match_value = models.CharField(
        max_length=255,
        help_text=(
            "The value to match. For exe_family, use a short key like "
            "'taxwise', 'ultratax', 'lacerte' — agent maps these to exe "
            "name prefixes."
        ),
    )
 
    # -- What happens when it triggers ----------------------------------
    ACTION_CHOICES = [
        ('route_to_client', 'Route Tracking to a Specific Client'),
        ('never_switch_away', 'Stay on Currently Selected Client'),
        ('suppress', 'Ignore This Window Entirely'),
        ('assign_category',   'Assign Category'),
        ('mark_non_billable', 'Mark Non-Billable'),
        ('cap_duration_at',   'Cap Duration At'),
        ('flag_for_review',   'Flag For Review'),
        # NEW (Phase 1 rebuild) — provides signal but does not auto-commit
        ('propose_only', 'Propose Only (always require review)'),
    ]
    action = models.CharField(
        max_length=32,
        choices=ACTION_CHOICES,
        default='route_to_client',
    )
    target_client = models.ForeignKey(
        'tracker.Client',            # ← adjust to your app label
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='routing_rules',
        help_text="Required when action='route_to_client'.",
    )
 
    # -- Scope and ordering ---------------------------------------------
    org = models.ForeignKey(
        'tracker.Organization',
        on_delete=models.CASCADE,
        related_name='routing_rules',
    )
    priority = models.IntegerField(
        default=100,
        help_text=(
            "Higher priority rules evaluated first. Defaults:\n"
            "  500 = org-specific hard rules (tax software, etc.)\n"
            "  300 = default baseline rules shipped to all orgs\n"
            "  100 = user-created soft rules"
        ),
    )
    enabled = models.BooleanField(default=True)


    # ──────────────────────────────────────────────────────────────
    # Rule system extension fields (PR #1)
    # ──────────────────────────────────────────────────────────────

    CATEGORY_CHOICES = [
        ('routing', 'Routing'),
        ('categorization', 'Categorization'),
        ('billing', 'Billing'),
        ('flagging', 'Flagging'),
    ]
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='routing',
        help_text="What kind of rule this is — drives which engine evaluates it.",
    )

    RUNS_AT_CHOICES = [
        ('agent', 'Agent (live, on-device)'),
        ('classifier', 'Classifier (server, real-time)'),
        ('both', 'Agent + Classifier (default for routing rules)'),
        ('compaction', 'Compaction (server, hourly)'),
        ('post_save', 'Post-save (server, after write)'),
    ]
    runs_at = models.CharField(
        max_length=20,
        choices=RUNS_AT_CHOICES,
        default='agent',
        help_text="Which engine stage evaluates this rule.",
    )

    target_category = models.CharField(
        max_length=100, blank=True, default='',
        help_text="For categorization rules: the category name to assign.",
    )

    threshold_minutes = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="For flagging/billing rules: minutes threshold (e.g. flag blocks > 240 min).",
    )

    flag_reason = models.CharField(
        max_length=200, blank=True, default='',
        help_text="For flagging rules: human-readable reason shown to reviewers.",
    )
     
    # -- Metadata / audit -----------------------------------------------
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Human-readable explanation; shown in admin UI.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text=(
            "True for rules seeded from default_routing_rules.json. "
            "Firm admins can disable but not delete these; MavOps can "
            "push updates to them globally."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='routing_rules_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    # Telemetry — updated asynchronously by the rule firing pipeline
    fire_count = models.IntegerField(default=0)
    last_fired_at = models.DateTimeField(null=True, blank=True)

    # ── Source tracking (migration 0109) ──
    source = models.CharField(
        max_length=32,
        choices=[
            ('manual', 'Manual'),
            ('default_seed', 'Default Seed'),
            ('cch_axcess_sync', 'CCH Axcess Sync'),
        ],
        default='manual',
        help_text='How this rule was created. Synced rules are managed by the '
                  'integration and should not be manually edited.',
    )
 
    class Meta:
        ordering = ['-priority', 'id']
        indexes = [
            models.Index(fields=['org', 'enabled', '-priority']),
        ]
 
    def __str__(self):
        action_desc = self.get_action_display()
        if self.action == 'route_to_client' and self.target_client:
            action_desc = f"→ {self.target_client.name}"
        return f"[{self.org.name}] {self.match_type}='{self.match_value}' {action_desc}"
 
    def clean(self):
        """Validate that routing rules have targets and regexes compile."""
        from django.core.exceptions import ValidationError
 
        if self.action == 'route_to_client' and not self.target_client_id:
            raise ValidationError({
                'target_client': 'Required when action is "Route to Client".'
            })
 
        if self.action == 'route_to_client' and self.target_client:
            if self.target_client.org_id != self.org_id:
                raise ValidationError({
                    'target_client': 'Client must belong to the same org as the rule.',
                })
 
        if self.match_type == 'title_regex':
            import re
            try:
                re.compile(self.match_value)
            except re.error as e:
                raise ValidationError({
                    'match_value': f'Invalid regex: {e}',
                })
 
    # -- Serialization for agent sync -----------------------------------
    def to_agent_dict(self) -> dict:
        """
        Serialize for the agent sync endpoint. Keep keys stable —
        the agent deserializes these in ai_client_switcher.py.
        """
        return {
            'id': self.id,
            'match_type': self.match_type,
            'match_value': self.match_value,
            'action': self.action,
            'target_client_id': self.target_client_id,
            'target_client_name': self.target_client.name if self.target_client else None,
            'priority': self.priority,
            'description': self.description,
        }


class OrgReportPreset(models.Model):
    ROW_AXES = [
        ("employee", "Employee"),
        ("day", "Day"),
        ("week", "Week"),
        ("month", "Month"),
        ("quarter", "Quarter"),
        ("year", "Year"),
    ]
    METRICS = [
        ("total", "Total hours"),
        ("billable", "Billable hours"),
        ("non_billable", "Non-billable hours"),
    ]
 
    org = models.ForeignKey(
        "Organization", on_delete=models.CASCADE, related_name="report_presets"
    )
    name = models.CharField(max_length=120)
 
    # Layout. CLIENT is always the column axis (fixed), so we only store the row
    # axis + which number fills each cell.
    rows_axis = models.CharField(max_length=16, choices=ROW_AXES, default="employee")
    metric = models.CharField(max_length=16, choices=METRICS, default="billable")
 
    # Presentation flags — this is where "no pagination, expand all" lives.
    expand_all = models.BooleanField(default=False)   # render every row/col at once
    paginate = models.BooleanField(default=True)      # false = show everything
    show_totals = models.BooleanField(default=True)   # row/col total lines
 
    is_default = models.BooleanField(default=False)   # one default per org (enforced in view)
 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        unique_together = [("org", "name")]
        indexes = [models.Index(fields=["org", "is_default"])]
 
    def __str__(self):
        return f"{self.org_id}:{self.name} ({self.rows_axis}×client/{self.metric})"
 

class RuleSuggestion(models.Model):
    org = models.ForeignKey(
        'tracker.Organization',
        on_delete=models.CASCADE,
        related_name='rule_suggestions',
    )
    suggested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='rule_suggestions_made',
    )
 
    # The blind-spot signature being flagged.
    label = models.CharField(max_length=255, help_text="Display label, e.g. 'Outlook.Exe — Inbox'")
    app_hint = models.CharField(max_length=255, blank=True, default='')
    title_hint = models.CharField(max_length=255, blank=True, default='')
 
    # Impact context captured at submission time (so reviewers see why it mattered).
    minutes = models.IntegerField(default=0)
    block_count = models.IntegerField(default=0)
    user_count = models.IntegerField(default=0)
 
    note = models.TextField(blank=True, default='', help_text="Optional free-text from the submitter.")
 
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('actioned', 'Actioned'),   # a rule was created from it
        ('dismissed', 'Dismissed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
 
    # Set when MavOps turns this into a real rule — links suggestion → rule.
    resulting_rule = models.ForeignKey(
        'tracker.OrgRoutingRule',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='source_suggestions',
    )
 
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='rule_suggestions_reviewed',
    )
 
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['org', 'status']),
        ]
 
    def __str__(self):
        return f"Suggestion #{self.pk}: {self.label} ({self.status})"
 


"""
Add this model to server/tracker/models.py — anywhere works, but the
"CLASSIFICATION RULES" section (right after OrgRoutingRule) is most natural.

After adding, run:
    python manage.py makemigrations tracker
    python manage.py migrate tracker
"""

from django.db import models
from django.utils import timezone


class RuleFireLog(models.Model):
    """
    Audit log of every rule fire, across all engines.

    PURPOSE
    -------
    1. Customer-support debugging ("why was this block categorized?")
    2. LLM #3 (rule explanation) — reads from this table
    3. Top-firing-rules dashboard
    4. Silent-regression detection (rule fires drop suddenly)
    5. Compliance — defensible audit of every billing-affecting decision

    DATA RETENTION
    --------------
    Rows here grow linearly with usage. Recommend a periodic cleanup
    task (e.g. delete rows > 90 days old, or archive to cold storage).
    For now, no auto-cleanup — let it accumulate while we observe usage.

    ENGINES THAT WRITE HERE
    -----------------------
    - AgentEngine        (windows_agent — via /api/routing-rules/fire/)
    - ClassifierEngine   (block_classifier.py Stage 0c)
    - CompactionEngine   (compaction.py)
    - PostSaveEngine     (post_save signal on Block)
    """

    # ---- Which rule fired ----
    rule = models.ForeignKey(
        'OrgRoutingRule',
        on_delete=models.CASCADE,
        related_name='fire_logs',
        db_index=True,
        help_text='The rule that fired.',
    )
    rule_version = models.IntegerField(
        default=1,
        help_text=(
            'Snapshot of the rule version at fire time. Lets us tell '
            "if a rule's behavior changed since this fire."
        ),
    )

    # ---- Org scoping (denormalized for fast filtering) ----
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='rule_fire_logs',
        db_index=True,
    )

    # ---- What it fired on ----
    block = models.ForeignKey(
        'Block',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rule_fires',
        help_text='The block, if applicable. Null for agent-stage fires.',
    )

    # ---- Which engine ----
    ENGINE_CHOICES = [
        ('agent',      'Desktop Agent'),
        ('classifier', 'Block Classifier'),
        ('compaction', 'Compaction'),
        ('post_save',  'Post-Save Signal'),
    ]
    engine = models.CharField(
        max_length=20,
        choices=ENGINE_CHOICES,
        db_index=True,
    )

    # ---- The match context (what the rule "saw") ----
    context = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'What the engine saw when matching: window title, exe, file_path, '
            'duration, etc. Useful for debugging and LLM #3 explanations.'
        ),
    )

    # ---- The outcome (what the rule "did") ----
    outcome = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'What the rule did: assigned category, switched client, flagged, '
            'marked non-billable, etc.'
        ),
    )

    # ---- Timing ----
    fired_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
    )

    class Meta:
        ordering = ['-fired_at']
        indexes = [
            models.Index(fields=['org', '-fired_at']),
            models.Index(fields=['rule', '-fired_at']),
            models.Index(fields=['block', '-fired_at']),
            models.Index(fields=['engine', '-fired_at']),
        ]

    def __str__(self):
        block_ref = f'block {self.block_id}' if self.block_id else 'no-block'
        return f'[{self.engine}] rule {self.rule_id} fired on {block_ref} @ {self.fired_at:%Y-%m-%d %H:%M}'

class ClientPattern(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="client_patterns", db_index=True)
    MATCH_TYPES = [
        ("domain", "Domain (email domain or URL)"),
        ("path", "File path segment"),
        ("keyword", "Keyword"),
        ("regex", "Regex"),
        ("app", "App name"),        # ← ADD
        ("title", "Window title"),  # ← ADD
    ]
    client_name = models.CharField(max_length=255)
    match_type = models.CharField(max_length=20, choices=MATCH_TYPES)
    pattern = models.TextField()
    weight = models.IntegerField(default=1)

    class Meta:
        indexes = [
            models.Index(fields=["org", "match_type"]),
            models.Index(fields=["org", "client_name"]),
        ]

    def __str__(self):
        return f"{self.client_name} ({self.match_type}: {self.pattern})"


class TaskPattern(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="task_patterns", db_index=True)
    MATCH_TYPES = [
        ("bundle", "App Bundle ID"),
        ("keyword", "Keyword"),
        ("regex", "Regex"),
        ("path_ext", "File Extension"),
    ]
    task_category = models.CharField(max_length=100)
    match_type = models.CharField(max_length=20, choices=MATCH_TYPES)
    pattern = models.TextField()
    weight = models.IntegerField(default=1)

    class Meta:
        indexes = [
            models.Index(fields=["org", "match_type"]),
            models.Index(fields=["org", "task_category"]),
        ]

    def __str__(self):
        return f"{self.task_category} ({self.match_type}: {self.pattern})"


class ClassificationOverride(models.Model):
    raw_event = models.ForeignKey(RawEvent, on_delete=models.CASCADE, related_name="overrides", db_index=True)
    client_name = models.CharField(max_length=255, blank=True, null=True)
    task_category = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["raw_event"])]

    def __str__(self):
        return f"Override #{self.raw_event_id} ({self.client_name or '-'} / {self.task_category or '-'})"


# ===============================
# ======  SIGNALS  ==============
# ===============================
from django.db.models.signals import pre_save
from django.dispatch import receiver

@receiver(pre_save, sender=Block)
def _denormalize_block(sender, instance: Block, **kwargs):
    if instance.start:
        instance.day = instance.start.astimezone(timezone.get_current_timezone()).date()
    if instance.start and instance.end and not instance.minutes:
        mins = int((instance.end - instance.start).total_seconds() // 60)
        instance.minutes = max(0, mins)



# ===============================
# ======  BILLING MODELS  =======
# ===============================
# ADD THESE TO tracker/models.py

from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal


class BillingRate(models.Model):
    """
    Staff billing rates - can be default rate or client-specific.
    Rates can change over time (effective_date).
    """
    org = models.ForeignKey('Organization', on_delete=models.CASCADE, related_name='billing_rates')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True,
        blank=True, related_name='billing_rates')
    
    # If null, this is the user's default rate; if set, it's client-specific
    client = models.ForeignKey('Client', on_delete=models.CASCADE, null=True, blank=True, related_name='billing_rates')
    
    rate = models.DecimalField(max_digits=10, decimal_places=2, help_text="Hourly billing rate in dollars")
    effective_date = models.DateField(default=timezone.now, help_text="Rate effective from this date")
    
    # Optional: different rates for different work types
    task_type = models.ForeignKey('TaskType', on_delete=models.SET_NULL, null=True, blank=True,
                                   help_text="Optional: rate for specific task type")
    
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-effective_date']
        indexes = [
            models.Index(fields=['org', 'user', 'effective_date']),
            models.Index(fields=['org', 'user', 'client']),
        ]
        # Prevent duplicate rates for same user/client/task_type/date combo
        constraints = [
            models.UniqueConstraint(
                fields=['org', 'user', 'client', 'task_type', 'effective_date'],
                name='unique_billing_rate'
            )
        ]
    
    @classmethod
    def get_rate_for_block(cls, block):
        """
        Get the applicable billing rate for a block.
        Priority: Client+TaskType > Client > TaskType > User Default > Org Default
        """
        from django.db.models import Q
        
        rates = cls.objects.filter(
            org=block.org,
            user=block.user,
            effective_date__lte=block.start.date()
        ).order_by('-effective_date')
        
        # Try client + task_type specific
        if block.client and block.task_type:
            rate = rates.filter(client=block.client, task_type=block.task_type).first()
            if rate:
                return rate.rate
        
        # Try client specific
        if block.client:
            rate = rates.filter(client=block.client, task_type__isnull=True).first()
            if rate:
                return rate.rate
        
        # Try task_type specific
        if block.task_type:
            rate = rates.filter(client__isnull=True, task_type=block.task_type).first()
            if rate:
                return rate.rate
            # Also check task_type's default rate
            if block.task_type.default_rate:
                return block.task_type.default_rate
        
        # Try user default rate
        rate = rates.filter(client__isnull=True, task_type__isnull=True).first()
        if rate:
            return rate.rate
        
        # Fall back to org default
        return block.org.billing_rate_default
    
    def __str__(self):
        client_str = f" → {self.client.name}" if self.client else " (default)"
        task_str = f" [{self.task_type.code}]" if self.task_type else ""
        return f"{self.user.username}{client_str}{task_str}: ${self.rate}/hr"


class Timesheet(models.Model):
    """
    Weekly timesheet container for approval workflow.
    Aggregates blocks for a given week.
    """
    org = models.ForeignKey('Organization', on_delete=models.CASCADE, related_name='timesheets')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='timesheets')
    
    # Week identification (always Monday)
    week_start = models.DateField(db_index=True, help_text="Monday of the timesheet week")
    
    # Status workflow
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('locked', 'Locked'),  # After invoicing
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True)
    
    # Submission tracking
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_notes = models.TextField(blank=True, default='', help_text="Notes from employee on submission")
    auto_submitted = models.BooleanField(
        default=False, 
        help_text="True if timesheet was automatically submitted by system (Tuesday auto-submit)"
    )
    
    # Approval tracking
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='approved_timesheets'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_notes = models.TextField(blank=True, default='')
    
    # Rejection tracking
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='rejected_timesheets'
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    
    # Cached totals (updated on save/submit)
    total_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    billable_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    non_billable_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = [['org', 'user', 'week_start']]
        ordering = ['-week_start']
        indexes = [
            models.Index(fields=['org', 'status', 'week_start']),
            models.Index(fields=['org', 'user', 'status']),
            models.Index(fields=['approved_by', 'status']),
        ]
    
    def get_week_end(self):
        """Returns Sunday of the timesheet week"""
        from datetime import timedelta
        return self.week_start + timedelta(days=6)
    
    def can_submit(self):
        """
        Check if timesheet can be submitted.
        Option A: Can only submit AFTER the week has ended.
        """
        from datetime import timedelta
        today = timezone.now().date()
        week_end = self.week_start + timedelta(days=6)
        
        if today <= week_end:
            return False, f"Cannot submit until after {week_end.isoformat()}. Week still in progress."
        
        if self.status not in ('draft', 'rejected'):
            return False, f"Cannot submit timesheet with status '{self.status}'."
        
        return True, None
    
    def recalculate_totals(self):
        """
        Recalculate totals from linked blocks.
        Call this after blocks are added/modified.
        """
        from django.db.models import Sum, Case, When, F, DecimalField
        from decimal import Decimal
        
        blocks = self.blocks.all()
        
        # Sum up minutes and convert to hours
        totals = blocks.aggregate(
            total_mins=Sum('minutes'),
            billable_mins=Sum(
                Case(
                    When(is_billable=True, then=F('minutes')),
                    default=0,
                    output_field=models.IntegerField()
                )
            ),
            total_amt=Sum(
                Case(
                    When(is_billable=True, then=F('minutes') * F('billing_rate') / 60),
                    default=Decimal('0'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )
        
        self.total_hours = Decimal(totals['total_mins'] or 0) / 60
        self.billable_hours = Decimal(totals['billable_mins'] or 0) / 60
        self.non_billable_hours = self.total_hours - self.billable_hours
        self.total_amount = totals['total_amt'] or Decimal('0.00')
        
        self.save(update_fields=['total_hours', 'billable_hours', 'non_billable_hours', 'total_amount', 'updated_at'])
    
    def submit(self, notes='', auto=False):
        """
        Submit timesheet for approval.
        
        Args:
            notes: Optional submission notes from employee
            auto: True if this is an auto-submit (system-triggered)
        """
        if self.status not in ('draft', 'rejected'):
            raise ValueError(f"Can only submit draft/rejected timesheets, current status: {self.status}")
        
        self.recalculate_totals()
        self.status = 'submitted'
        self.submitted_at = timezone.now()
        self.submitted_notes = notes
        self.auto_submitted = auto
        
        # Clear rejection fields if resubmitting
        if self.rejected_at:
            self.rejection_reason = ''
            self.rejected_at = None
            self.rejected_by = None
        
        self.save()
        
        # Auto-approve owner timesheets — no one above them to review
        membership = OrganizationMembership.objects.filter(
            user=self.user, organization=self.org
        ).first()
        if membership and membership.role == 'owner':
            self.approve(approved_by=self.user, notes='Auto-approved (owner)')
            return
        
        # Lock associated blocks
        self.blocks.update(approved=False)  # Mark as pending approval

    
    def approve(self, approved_by, notes=''):
        """Approve the timesheet"""
        if self.status != 'submitted':
            raise ValueError(f"Can only approve submitted timesheets, current status: {self.status}")
        
        self.status = 'approved'
        self.approved_by = approved_by
        self.approved_at = timezone.now()
        self.approval_notes = notes
        self.save()
        
        # Mark all blocks as approved
        self.blocks.update(
            approved=True,
            approved_at=timezone.now(),
            approved_by=approved_by
        )
    
    def reject(self, rejected_by, reason=''):
        """Reject the timesheet, allowing re-submission"""
        if self.status != 'submitted':
            raise ValueError(f"Can only reject submitted timesheets, current status: {self.status}")
        
        self.status = 'rejected'
        self.rejected_by = rejected_by
        self.rejected_at = timezone.now()
        self.rejection_reason = reason
        self.save()
        
        # Unlock blocks for editing
        self.blocks.update(approved=False)
    
    def reopen(self):
        """Reopen a rejected timesheet as draft"""
        if self.status != 'rejected':
            raise ValueError("Can only reopen rejected timesheets")
        
        self.status = 'draft'
        self.save()
    
    def lock(self):
        """Lock timesheet after invoicing - no more changes allowed"""
        if self.status != 'approved':
            raise ValueError("Can only lock approved timesheets")
        
        self.status = 'locked'
        self.save()
        
        # Permanently lock blocks
        self.blocks.update(locked=True)
    
    @classmethod
    def get_or_create_for_date(cls, org, user, date):
        """
        Get or create a timesheet for the week containing the given date.
        """
        from datetime import timedelta
        
        # Find Monday of the week
        days_since_monday = date.weekday()
        week_start = date - timedelta(days=days_since_monday)
        
        timesheet, created = cls.objects.get_or_create(
            org=org,
            user=user,
            week_start=week_start,
            defaults={'status': 'draft'}
        )
        return timesheet, created
    
    def __str__(self):
        auto_tag = " [AUTO]" if self.auto_submitted else ""
        return f"{self.user.username} - Week of {self.week_start} ({self.status}){auto_tag}"


# ===============================
# ======  AUDIT TRAIL  ==========
# ===============================

class BlockAuditLog(models.Model):
    """
    Tracks all changes to blocks for compliance/audit purposes.
    """
    block = models.ForeignKey('Block', on_delete=models.CASCADE, related_name='audit_logs')
    
    ACTION_CHOICES = [
        ('create', 'Created'),
        ('update', 'Updated'),
        ('categorize', 'Categorized'),
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ('lock', 'Locked'),
        ('delete', 'Deleted'),
    ]
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    
    # Who made the change
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='block_audit_actions'
    )
    
    # What changed
    field_name = models.CharField(max_length=100, blank=True, default='')
    old_value = models.TextField(blank=True, default='')
    new_value = models.TextField(blank=True, default='')
    
    # Full snapshot (for complex changes)
    snapshot = models.JSONField(default=dict, blank=True)
    
    # Context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['block', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]
    
    def __str__(self):
        return f"{self.action} Block #{self.block_id} by {self.user} at {self.timestamp}"

class AgentLog(models.Model):
    user        = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='agent_logs')
    device      = models.ForeignKey('AgentDevice', on_delete=models.SET_NULL, null=True, blank=True)
    agent_device_id = models.CharField(max_length=255, db_index=True)  # ← renamed
    hostname    = models.CharField(max_length=255)
    platform    = models.CharField(max_length=20, default='unknown')
    app_version = models.CharField(max_length=50, blank=True)
    trigger     = models.CharField(max_length=50, default='scheduled')
    log_text    = models.TextField()
    line_count  = models.IntegerField(default=0)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.hostname} ({self.platform}) - {self.created_at}"

class CostTier(models.Model):
    """A firm-defined labor cost band (e.g., Partner, Manager, Senior, Staff).

    Members are assigned a tier (OrganizationMembership.cost_tier); the tier's
    cost_rate drives margin/profitability unless a per-person EmployeeCostRate
    override exists. This is the scale lever: a firm sets a handful of tier rates
    instead of a rate for every employee. Separate from the *permission* role.
    """
    organization = models.ForeignKey(
        'Organization', on_delete=models.CASCADE, related_name='cost_tiers'
    )
    label = models.CharField(max_length=64)
    cost_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Loaded hourly cost for everyone in this tier",
    )
    bill_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text=(
            "Standard hourly BILL rate for this tier (what the client is charged). "
            "Used as a revenue fallback when a block/client has no explicit rate, "
            "before the org default. Null → use org billing_rate_default."
        ),
    )
    hours_per_week = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text=(
            "Available working hours per week for this tier (capacity). Drives "
            "capacity-based utilization. Null → use org capacity_hours_per_week."
        ),
    )
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'id']
        unique_together = ['organization', 'label']

    def __str__(self):
        return f"{self.label} (${self.cost_rate}/hr)"


class EmployeeCostRate(models.Model):
    """
    What you PAY employees per hour (loaded labor cost).
    Used to calculate profit margins.

    Margin = Billing Rate - Cost Rate
    """
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='employee_cost_rates'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cost_rates'
    )
    cost_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Hourly cost (loaded labor rate)"
    )
    effective_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-effective_date']
        unique_together = ['organization', 'user', 'effective_date']

    def __str__(self):
        return f"{self.user.username}: ${self.cost_rate}/hr"

    @classmethod
    def get_rate_for_user(cls, user, organization, date=None):
        """Get the applicable cost rate for a user on a given date."""
        if date is None:
            date = timezone.now().date()
        
        rate = cls.objects.filter(
            organization=organization,
            user=user,
            effective_date__lte=date
        ).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=date)
        ).order_by('-effective_date').first()
        
        return rate.cost_rate if rate else None



class AgentError(models.Model):
    """Track agent errors from all clients for debugging."""
    
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, 
        null=True, blank=True,
        related_name='agent_errors'
    )
    org = models.ForeignKey(
        'Organization', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='agent_errors'
    )
    
    # Error details
    error_type = models.CharField(max_length=50, db_index=True)
    error_message = models.TextField()
    traceback = models.TextField(blank=True)
    
    # Device info
    device_id = models.CharField(max_length=100, db_index=True)
    hostname = models.CharField(max_length=100, db_index=True)
    app_version = models.CharField(max_length=20, db_index=True)
    platform = models.CharField(max_length=100, blank=True)
    python_version = models.CharField(max_length=20, blank=True)
    os_username = models.CharField(max_length=100, blank=True)
    
    # Context
    context = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    client_timestamp = models.DateTimeField(null=True, blank=True)
    
    # Status
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='resolved_errors'
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['error_type', 'created_at']),
            models.Index(fields=['device_id', 'created_at']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['resolved', 'created_at']),
            models.Index(fields=['app_version', 'created_at']),
        ]
    
    def __str__(self):
        username = self.user.username if self.user else self.os_username or 'unknown'
        return f"{self.error_type} | {username}@{self.hostname} | {self.created_at:%Y-%m-%d %H:%M}"


class UserPreference(models.Model):
    """User preferences including notification settings."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='preferences'
    )
    
    # Notification preferences
    email_timesheet_reminders = models.BooleanField(
        default=True,
        help_text="Receive daily email reminders for unreviewed timesheets"
    )
    email_weekly_summary = models.BooleanField(
        default=True,
        help_text="Receive weekly time summary emails"
    )
    email_approval_notifications = models.BooleanField(
        default=True,
        help_text="Receive emails when timesheets are approved/rejected"
    )
    desktop_notifications = models.BooleanField(
        default=True,
        help_text="Show desktop notifications from the agent"
    )
    reminder_time = models.CharField(
        max_length=5,
        default='09:00',
        help_text="Preferred time for reminders (HH:MM)"
    )
    
    # Tracking
    last_timesheet_reminder_dismissed = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Date of last dismissed reminder (YYYY-MM-DD)"
    )
    
    # Other preferences
    default_view = models.CharField(
        max_length=20,
        default='timesheet',
        choices=[
            ('timesheet', 'My Timesheet'),
            ('dashboard', 'Dashboard'),
            ('reports', 'Reports'),
        ]
    )
    timezone = models.CharField(max_length=50, default='America/New_York')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Preference'
        verbose_name_plural = 'User Preferences'
    
    def __str__(self):
        return f"Preferences for {self.user.username}"


"""
OrgDeploymentToken model and related helpers.

Add to server/tracker/models.py (or create as a new file and import).
Then run: python manage.py makemigrations && python manage.py migrate
"""
import secrets
import string
from django.db import models
from django.conf import settings
from django.utils import timezone


def generate_org_token():
    """Generate a readable org deployment token like ODT-XKCD-9F3A."""
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(4))
    part2 = ''.join(secrets.choice(chars) for _ in range(4))
    return f"ODT-{part1}-{part2}"


class OrgDeploymentToken(models.Model):
    """
    A token that allows bulk device enrollment for an organization.
    IT admins bake this into MSI installs for MDM (Intune) deployment.
    """
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='deployment_tokens'
    )
    token = models.CharField(
        max_length=20,
        unique=True,
        default=generate_org_token,
        db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_deployment_tokens'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    max_devices = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Max devices that can claim this token. Null = unlimited."
    )
    devices_claimed = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.token} ({self.organization.name})"

    @property
    def is_valid(self):
        """Check if token can still be used to claim devices."""
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        if self.max_devices and self.devices_claimed >= self.max_devices:
            return False
        return True

    def claim(self):
        """Increment claim count. Call after successful device registration."""
        self.devices_claimed = models.F('devices_claimed') + 1
        self.save(update_fields=['devices_claimed'])


import secrets
from django.db import models
from django.conf import settings
from django.utils import timezone


class OnboardingBatch(models.Model):
    """
    Tracks a white-glove onboarding job for a firm.
    One batch = one firm onboarding. Links all provisioning records together.
    """
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='onboarding_batches'
    )
    
    STATUS_CHOICES = [
        ('draft', 'Draft - Data collected, not yet imported'),
        ('imported', 'Imported - Users/clients/devices loaded'),
        ('msi_built', 'MSI Built - Installer ready for IT'),
        ('deployed', 'Deployed - MSI pushed to machines'),
        ('active', 'Active - Devices pairing'),
        ('complete', 'Complete - All devices paired'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Link to the deployment token used for this batch
    deployment_token = models.ForeignKey(
        'OrgDeploymentToken',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='onboarding_batch'
    )
    
    # Stats (updated as provisioning progresses)
    total_users = models.IntegerField(default=0)
    total_devices = models.IntegerField(default=0)
    total_clients = models.IntegerField(default=0)
    devices_paired = models.IntegerField(default=0)
    
    # Who ran this onboarding
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='onboarding_batches_created'
    )
    
    notes = models.TextField(blank=True, default='')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Onboarding Batch'
        verbose_name_plural = 'Onboarding Batches'
    
    def __str__(self):
        return f"{self.organization.name} - {self.status} ({self.devices_paired}/{self.total_devices} paired)"
    
    def refresh_stats(self):
        """Recalculate stats from provisioning map."""
        maps = self.provisioning_maps.all()
        self.total_devices = maps.count()
        self.total_users = maps.values('email').distinct().count()
        self.devices_paired = maps.filter(status='paired').count()
        self.save(update_fields=['total_devices', 'total_users', 'devices_paired', 'updated_at'])
        
        # Auto-complete if all devices paired
        if self.total_devices > 0 and self.devices_paired >= self.total_devices:
            self.status = 'complete'
            self.completed_at = timezone.now()
            self.save(update_fields=['status', 'completed_at'])
    
    @property
    def pair_percentage(self):
        if self.total_devices == 0:
            return 0
        return round((self.devices_paired / self.total_devices) * 100, 1)


class DeviceProvisioningMap(models.Model):
    """
    Pre-provisioned mapping of machine hostname / Windows username to a user email.
    
    Created BEFORE MSI deployment so the agent can auto-pair on first boot.
    
    Flow:
    1. MavOps imports CSV with hostname + windows_username + email
    2. IT Admin pushes MSI with org token to all machines
    3. Agent starts, sends org_token + hostname + windows_username to API
    4. API matches against this table → auto-pairs device to user
    """
    organization = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='provisioning_maps'
    )
    batch = models.ForeignKey(
        OnboardingBatch,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='provisioning_maps'
    )
    
    # ─── Matching fields (what the agent sends) ───
    machine_hostname = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Machine hostname from Intune/AD export (e.g., FIRM-PC-101)"
    )
    windows_username = models.CharField(
        max_length=255,
        blank=True, default='',
        db_index=True,
        help_text="DOMAIN\\username from AD (e.g., FIRMNAME\\jsmith)"
    )
    
    # ─── Target user ───
    email = models.EmailField(
        db_index=True,
        help_text="User email to pair this device to"
    )
    display_name = models.CharField(max_length=255, blank=True, default='')
    
    # ─── Role & rate (used when creating user accounts) ───
    role = models.CharField(
        max_length=20,
        choices=[
            ('owner', 'Owner'),
            ('admin', 'Admin'),
            ('manager', 'Manager'),
            ('member', 'Member'),
        ],
        default='member'
    )
    billing_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Hourly billing rate for this user"
    )
    cost_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text="Hourly cost rate for this user"
    )
    
    # ─── Pairing status ───
    STATUS_CHOICES = [
        ('pending', 'Pending - Waiting for agent to connect'),
        ('paired', 'Paired - Device matched and linked'),
        ('failed', 'Failed - Agent connected but match failed'),
        ('manual', 'Manual - Fell back to manual pairing'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    
    # ─── Result tracking ───
    paired_device = models.ForeignKey(
        'AgentDevice',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='provisioning_map'
    )
    paired_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='provisioned_devices'
    )
    paired_at = models.DateTimeField(null=True, blank=True)
    match_method = models.CharField(
        max_length=20,
        blank=True, default='',
        help_text="How the match was made: hostname, windows_username, or manual"
    )
    error_message = models.TextField(blank=True, default='')
    
    # ─── Timestamps ───
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['organization', 'machine_hostname']),
            models.Index(fields=['organization', 'windows_username']),
            models.Index(fields=['organization', 'email']),
            models.Index(fields=['status', 'organization']),
        ]
        # Same hostname shouldn't be provisioned twice for same org
        unique_together = ['organization', 'machine_hostname']
        verbose_name = 'Device Provisioning Map'
        verbose_name_plural = 'Device Provisioning Maps'
    
    def __str__(self):
        status_icon = {'pending': '⏳', 'paired': '✅', 'failed': '❌', 'manual': '🔧'}.get(self.status, '?')
        return f"{status_icon} {self.machine_hostname} → {self.email} ({self.status})"
    
    def mark_paired(self, device, user, method='hostname'):
        """Mark this provisioning entry as successfully paired."""
        self.status = 'paired'
        self.paired_device = device
        self.paired_user = user
        self.paired_at = timezone.now()
        self.match_method = method
        self.save()
        
        # Update batch stats
        if self.batch:
            self.batch.refresh_stats()
    
    def mark_failed(self, error=''):
        """Mark as failed match."""
        self.status = 'failed'
        self.error_message = error
        self.save()


class ClassificationAudit(models.Model):
    SOURCE_CHOICES = [
        ('deterministic', 'Deterministic'),
        ('pattern', 'Pattern'),
        ('ai', 'AI'),
        ('manual', 'Manual'),
        ('error', 'Error'),
    ]

    block = models.ForeignKey('Block', on_delete=models.CASCADE, related_name='audits')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    client_before = models.ForeignKey('Client', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+')
    client_after = models.ForeignKey('Client', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='+')
    category_before = models.CharField(max_length=100, blank=True)
    category_after = models.CharField(max_length=100, blank=True)
    confidence_client = models.FloatField(default=0)
    confidence_category = models.FloatField(default=0)
    overall_confidence = models.FloatField(default=0)
    matched_signals = models.JSONField(default=list)
    corrected_by_user = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['block']),
            models.Index(fields=['source']),
            models.Index(fields=['created_at']),
        ]


class SupportDoc(models.Model):
    """
    A chunk of knowledge-base documentation, embedded for retrieval.
    One markdown doc usually becomes several SupportDoc rows (one per chunk).
    """
    title = models.CharField(max_length=255)
    source = models.CharField(
        max_length=255,
        help_text="Origin file/section, e.g. 'agent-install.md#windows'",
    )
    content = models.TextField()
    # Dim must match your embedding model (voyage-3-lite / text-embedding-3-small = 1536).
    embedding = VectorField(dimensions=512, null=True, blank=True)
 
    # Global doc (org null) or org-specific.
    org = models.ForeignKey(
        'Organization',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='support_docs',
        help_text='Null = global doc shown to all orgs. Set = org-specific.',
    )
    is_active = models.BooleanField(default=True)
 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        indexes = [
            HnswIndex(
                name="supportdoc_embedding_idx",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            models.Index(fields=['org', 'is_active']),
        ]
 
    def __str__(self):
        return f"{self.title} ({self.source})"
 
 
class SupportConversation(models.Model):
    """A chat thread between one user and the AI assistant."""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="support_conversations",
    )
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='support_conversations',
    )
    title = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=['user', '-updated_at']),
            models.Index(fields=['org', '-updated_at']),
        ]
 
    def __str__(self):
        return f"{self.user.username} — {self.title[:40] or 'support chat'}"
 
 
class SupportMessage(models.Model):
    """One turn in a SupportConversation."""
    ROLE_CHOICES = [("user", "user"), ("assistant", "assistant")]
 
    conversation = models.ForeignKey(
        SupportConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
 
    # For assistant turns: which docs grounded the answer, and confidence.
    cited_doc_ids = models.JSONField(default=list, blank=True)
    was_grounded = models.BooleanField(
        default=True,
        help_text='False = classifier fell back / was unsure and escalated.',
    )
 
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]
 
    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
 
 
class SupportTicket(models.Model):
    """
    Email-style ticket. Created when AI escalates, or user opts to email.
    Replies handled in your inbox; this is the system-of-record + history.
    """
    STATUS_CHOICES = [
        ("open", "Open"),
        ("pending", "Pending"),
        ("resolved", "Resolved"),
    ]
 
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='support_tickets',
    )
    subject = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open", db_index=True)
 
    # Link back to the chat that spawned it, if any.
    conversation = models.ForeignKey(
        SupportConversation,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="tickets",
    )
 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=['org', 'status', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
 
    def __str__(self):
        return f"#{self.pk} [{self.status}] {self.subject}"


class TaxpayerBucket(models.Model):
    """
    Virtual grouping for individual tax return time blocks.

    One row per unique taxpayer per org. Allows the dashboard to show
    "Wood, Michael — 1h 42m Tax Preparation" as a named bucket without
    requiring a Client record for every individual taxpayer.

    SECURITY:
      taxpayer_id_hash is a truncated SHA-256 of the SSN or EIN extracted
      from the tax software window title. The raw SSN/EIN is never stored
      anywhere in TimeTracker — it is hashed in tracker/utils/tax_software.py
      and discarded immediately.

    DEDUP:
      Two people named "Wood, Michael" are distinguished by their hash
      (different SSNs → different hashes → different buckets).
      When a collision occurs on display_name, the frontend appends (1), (2)
      and admins can rename to "Wood, Michael Sr." / "Wood, Michael Jr."
    """
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='taxpayer_buckets',
    )

    # Dedup key — sha256(ssn_or_ein)[:12]
    taxpayer_id_hash = models.CharField(max_length=16, db_index=True)

    # Editable display name — admin can correct after initial extraction
    display_name = models.CharField(max_length=120)

    # Which return types this taxpayer has had open (informational only)
    return_types_seen = models.JSONField(default=list, blank=True)

    # Which software generated this bucket
    software = models.CharField(max_length=32, blank=True, default='')

    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tracker_taxpayer_bucket'
        ordering = ['display_name']
        constraints = [
            models.UniqueConstraint(
                fields=['org', 'taxpayer_id_hash'],
                name='unique_taxpayer_per_org',
            )
        ]

    def __str__(self):
        return f"{self.display_name} ({self.org})"


# ============================================================================
# Phase 1 rebuild — Calendar/Mail integration models
# ============================================================================

class CalendarEvent(models.Model):
    """
    Calendar event from Google Calendar or Microsoft Graph.
    Used as Stage 6 classification signal. Per-user opt-in via UserIntegration.
    """
    PROVIDER_CHOICES = [
        ('google',    'Google Calendar'),
        ('microsoft', 'Microsoft Graph (Outlook)'),
    ]

    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='calendar_events',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='calendar_events',
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    external_id = models.CharField(max_length=255, db_index=True)

    # Event content
    title = models.TextField()
    description = models.TextField(blank=True, default='')
    location = models.CharField(max_length=255, blank=True, default='')
    meeting_url = models.TextField(
        blank=True, default='',
        help_text='Zoom/Teams/Meet URL extracted from event description or location.',
    )

    # Time window
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField(db_index=True)

    # Attendees as list of {email, domain, response_status}
    attendees = models.JSONField(default=list, blank=True)

    # Pre-computed classification hints
    extracted_client = models.ForeignKey(
        'Client',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='calendar_events',
    )
    extraction_confidence = models.FloatField(default=0.0)

    # Sync tracking
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'provider', 'external_id']]
        indexes = [
            models.Index(fields=['user', 'start', 'end']),
            models.Index(fields=['org', 'start']),
        ]
        ordering = ['-start']

    def __str__(self):
        return f"{self.user.username} | {self.title[:50]} | {self.start}"

    def overlap_minutes_with(self, other_start, other_end):
        """
        Compute the number of minutes this event overlaps with the given window.
        Returns 0 if no overlap.
        """
        latest_start = max(self.start, other_start)
        earliest_end = min(self.end, other_end)
        if latest_start >= earliest_end:
            return 0
        return int((earliest_end - latest_start).total_seconds() / 60)


class MailSignal(models.Model):
    """
    Lightweight metadata about email activity. Used as Stage 7 classification signal.

    PRIVACY GUARANTEES (CRITICAL — DO NOT relax):
      - NEVER stores message body
      - NEVER stores attachment contents or names
      - NEVER stores email addresses (only domain extracted)
      - Subject ONLY stored if cleanly matches a known client (extraction_confidence >= 0.85)
    """
    PROVIDER_CHOICES = [
        ('google',    'Gmail'),
        ('microsoft', 'Microsoft Graph'),
    ]
    DIRECTION_CHOICES = [
        ('in',  'Received'),
        ('out', 'Sent'),
    ]

    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='mail_signals',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mail_signals',
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    external_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text='Provider message ID, used for dedup and idempotent sync.',
    )

    occurred_at = models.DateTimeField(db_index=True)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)

    other_party_domain = models.CharField(
        max_length=120,
        db_index=True,
        help_text="Domain of the OTHER party. Inbound: sender's. Outbound: dominant recipient's.",
    )

    subject_extract = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Subject text, ONLY stored if a client was successfully extracted from it.',
    )

    is_inbox = models.BooleanField(default=False)
    has_attachment = models.BooleanField(default=False)

    extracted_client = models.ForeignKey(
        'Client',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='mail_signals',
    )

    class Meta:
        unique_together = [['user', 'provider', 'external_id']]
        indexes = [
            models.Index(fields=['user', 'occurred_at']),
            models.Index(fields=['user', 'other_party_domain']),
            models.Index(fields=['org', 'occurred_at']),
            models.Index(fields=['org', 'occurred_at', 'direction'], name='mailsig_org_time_dir_idx'),
        ]
        ordering = ['-occurred_at']

    def __str__(self):
        return f"{self.user.username} | {self.direction} | {self.other_party_domain} | {self.occurred_at}"


class UserIntegration(models.Model):
    """
    Per-user OAuth connections for calendar and mail providers.
    Distinct from the existing org-level Integration model.
    """
    PROVIDER_CHOICES = [
        ('google_calendar',    'Google Calendar'),
        ('microsoft_calendar', 'Microsoft Calendar (Graph)'),
        ('gmail',              'Gmail (metadata only)'),
        ('microsoft_mail',     'Microsoft Mail (metadata only)'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_integrations',
    )
    org = models.ForeignKey(
        'Organization',
        on_delete=models.CASCADE,
        related_name='user_integrations',
    )
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES)

    is_connected = models.BooleanField(default=False)
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    scopes = models.JSONField(default=list, blank=True)

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True, default='')
    sync_failure_count = models.IntegerField(
        default=0,
        help_text='Consecutive failed syncs. After 5, sync is paused until user re-auths.',
    )

    oauth_state = models.CharField(max_length=128, blank=True, default='')
    provider_account_id = models.CharField(max_length=255, blank=True, default='')
    provider_email = models.EmailField(blank=True, default='')

    mail_delta_link = models.TextField(
        blank=True,
        default='',
        help_text=(
            'Microsoft Graph delta link for /messages/delta. '
            'Empty = next sync is initial (last 30 days). '
            'Populated = next sync is incremental from this token.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'provider']]
        indexes = [
            models.Index(fields=['user', 'is_connected']),
            models.Index(fields=['org', 'provider']),
        ]

    def __str__(self):
        connected = '✓' if self.is_connected else '✗'
        return f"{connected} {self.user.username} → {self.get_provider_display()}"

    @property
    def is_calendar(self) -> bool:
        return self.provider in ('google_calendar', 'microsoft_calendar')

    @property
    def is_mail(self) -> bool:
        return self.provider in ('gmail', 'microsoft_mail')

    @property
    def is_token_expired(self) -> bool:
        if not self.token_expires_at:
            return False
        return timezone.now() >= self.token_expires_at

    def disconnect(self):
        """
        Disconnect this integration. Clears tokens, marks not connected,
        and triggers cleanup of all derived data (CalendarEvent / MailSignal).
        """
        if self.is_calendar:
            CalendarEvent.objects.filter(
                user=self.user,
                provider='google' if self.provider == 'google_calendar' else 'microsoft',
            ).delete()
        elif self.is_mail:
            MailSignal.objects.filter(
                user=self.user,
                provider='google' if self.provider == 'gmail' else 'microsoft',
            ).delete()

        self.is_connected = False
        self.access_token = ''
        self.refresh_token = ''
        self.token_expires_at = None
        self.scopes = []
        self.last_sync_error = ''
        self.sync_failure_count = 0
        self.save()


# tracker/models.py
class MismatchFlag(models.Model):
    """A block whose window title names a different client than it's booked to.
    Written by the nightly scan; read by the pre-invoice gate and admin review.
    Detection-only — never mutates the block."""
    org = models.ForeignKey('Organization', on_delete=models.CASCADE, related_name='mismatch_flags')
    block = models.ForeignKey('Block', on_delete=models.CASCADE, related_name='mismatch_flags')
    booked_client = models.ForeignKey('Client', on_delete=models.CASCADE, related_name='+')
    title_client_id = models.IntegerField(null=True, blank=True)   # client the title points to (may be null: detector returns name)
    title_client_name = models.CharField(max_length=255, blank=True)
    bucket = models.CharField(max_length=16, default='client')     # 'client' (billing-impacting) | 'internal' (noise)
    match_score = models.FloatField(default=0.0)
    window_title = models.CharField(max_length=512, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_reason = models.CharField(max_length=64, blank=True)  # 'reconciled' | 'confirmed_correct' | 'invoiced_anyway'

    class Meta:
        indexes = [
            models.Index(fields=['org', 'resolved_at']),
            models.Index(fields=['block']),
        ]
        constraints = [
            # One OPEN flag per block at a time; resolved flags stay as history.
            models.UniqueConstraint(
                fields=['block'],
                condition=models.Q(resolved_at__isnull=True),
                name='uniq_open_mismatch_flag_per_block',
            ),
        ]

    def __str__(self):
        return f"MismatchFlag(block={self.block_id}, {self.booked_client_id}→{self.title_client_name!r}, {'open' if not self.resolved_at else 'resolved'})"


# Calendar matching rules
from tracker.models_calendar_rules import OrgCalendarRule  # noqa: F401, E402
from tracker.models_task_type_sets import (
    TaskTypeSet, TaskTypeSetMember, ClientTaskType,
    ExternalClientMapping, ExternalTaskTypeMapping, ExternalStaffMapping,
)


