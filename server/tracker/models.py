from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

from django.contrib.auth.models import Group
import hashlib
import secrets  # ✅ add this import

# ===========================
# ======  ORG MODELS  ======
# ===========================
# tracker/models.py - Add this new model (or enhance Group)

class Organization(models.Model):
    """
    Represents a CPA firm - the tenant in multi-tenant setup.
    Each org has completely isolated data.
    """
    name = models.CharField(max_length=200)  # "Smith & Associates CPA"
    slug = models.SlugField(unique=True)      # "smith-associates"
    
    # Subscription/billing
    plan = models.CharField(max_length=20, choices=[
        ('trial', 'Trial'),
        ('starter', 'Starter'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
    ], default='trial')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True)
    
    # Settings
    timezone = models.CharField(max_length=50, default='America/New_York')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    billing_rate_default = models.DecimalField(
    max_digits=10, 
    decimal_places=2, 
    default=Decimal('150.00'),
    help_text="Default hourly billing rate"
    )  
    
    class Meta:
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"
    
    def __str__(self):
        return self.name


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
    
    class Meta:
        unique_together = ['user', 'organization']
    
    def __str__(self):
        return f"{self.user.username} @ {self.organization.name} ({self.role})"


# ===========================
# ======  RAW EVENTS  =======
# ===========================
class RawEvent(models.Model):
    ts_utc = models.DateTimeField()
    app_name = models.CharField(max_length=255, blank=True, null=True)
    bundle_id = models.CharField(max_length=255, blank=True, null=True)
    window_title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, null=True)
    file_path = models.TextField(blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    device_id = models.CharField(max_length=64, db_index=True, default="unknown")
    hostname = models.CharField(max_length=255, blank=True, null=True, default="unknown")
    ctx = models.JSONField(default=dict, blank=True)
    
    # NEW: Store which client was selected when this event was captured
    current_client_id = models.IntegerField(null=True, blank=True, db_index=True)
    
    class Meta:
        indexes = [
            models.Index(fields=["ts_utc"]),
            models.Index(fields=["user", "device_id", "ts_utc"]),
            models.Index(fields=["user", "hostname"]),
        ]
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
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

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
        ('file_path', 'File Path Pattern'),
        ('time_of_day', 'Time of Day Pattern'),
        ('day_of_week', 'Day of Week Pattern'),
        ('app_sequence', 'Application Sequence'),
        ('tool_usage', 'Tool Usage Pattern'),
        ('client_folder', 'Client Folder Mapping'),
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
class Client(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    
    # ✅ ADD THIS FIELD
    code = models.CharField(
        max_length=50,
        blank=True,
        default='',
        help_text="Short code like 'ACME' or 'JOHN'"
    )
    
    is_active = models.BooleanField(default=True)
    
    class Meta:
        # ✅ ADD THIS - Prevents duplicate codes per org
        unique_together = [['org', 'code']]
    
    def save(self, *args, **kwargs):
        # ✅ AUTO-GENERATE CODE IF EMPTY
        if not self.code and self.name:
            # Take first 4 letters, uppercase, remove spaces
            self.code = self.name[:10].upper().replace(' ', '')[:10]
        super().save(*args, **kwargs)


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
    # Soft delete
    # ===============================
    objects = ActiveBlockManager()  # Default excludes deleted
    all_objects = models.Manager()  # Use this to include deleted blocks
    deleted_at = models.DateTimeField(null=True, blank=True, default=None)

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
        # ===============================
        # 1. Auto-set day and minutes from start/end
        # ===============================
        if self.start:
            self.day = self.start.astimezone(timezone.get_current_timezone()).date()
        if self.start and self.end:
            mins = int((self.end - self.start).total_seconds() // 60)
            self.minutes = max(0, mins)
        
        # ===============================
        # 2. Auto-set immutability flags when categories assigned
        # ===============================
        if self.category_hours and not self.is_categorized:
            self.is_categorized = True
            self.categorized_at = timezone.now()
            if not self.categorized_by:
                self.categorized_by = 'ai'
        
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
                if old.is_protected() and not kwargs.pop('force_update', False):
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
class ClientPattern(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="client_patterns", db_index=True)
    MATCH_TYPES = [
        ("domain", "Domain (email domain or URL)"),
        ("path", "File path segment"),
        ("keyword", "Keyword"),
        ("regex", "Regex"),
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
    if instance.start and instance.end:
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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='billing_rates')
    
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

