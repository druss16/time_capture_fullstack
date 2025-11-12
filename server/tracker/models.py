from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import Group
import hashlib
import secrets  # ✅ add this import

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

# ===========================
# ======  CORE MODELS  ======
# ===========================
class Client(models.Model):
    org = models.ForeignKey(Group, on_delete=models.CASCADE)
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
    org = models.ForeignKey(Group, on_delete=models.CASCADE)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = (("org", "client", "name"),)
        indexes = [models.Index(fields=["org", "client", "name"])]

    def __str__(self):
        return f"{self.name} ({self.client.name})"


class Task(models.Model):
    org = models.ForeignKey(Group, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=200)
    billable = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}"


# ==============================
# ======  CLASSIFICATION  ======
# ==============================
class Block(models.Model):
    org = models.ForeignKey(Group, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    device_id = models.CharField(max_length=64, db_index=True, default="unknown")
    hostname = models.CharField(max_length=120)
    start = models.DateTimeField()
    end = models.DateTimeField()
    title = models.TextField(blank=True, default="")
    window_title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, default="")
    file_path = models.TextField(blank=True, default="")
    hints = models.JSONField(default=dict, blank=True)
    
    app_name = models.CharField(max_length=255, blank=True, default="")
    bundle_id = models.CharField(max_length=255, blank=True, default="")

    day = models.DateField(db_index=True, null=True, blank=True)
    minutes = models.IntegerField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    attendees = models.JSONField(default=list, blank=True)
    category_hours = models.JSONField(default=dict, blank=True)

    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)

    notes = models.TextField(blank=True, default="")
    locked = models.BooleanField(default=False)

    # AI classification metadata
    ai_extracted_client = models.CharField(max_length=255, blank=True, null=True)
    ai_confidence = models.FloatField(default=0.0)
    ai_category = models.CharField(max_length=100, blank=True, default="")
    ai_processed_at = models.DateTimeField(null=True, blank=True)
    ai_hash = models.CharField(max_length=64, blank=True, null=True)  # NEW
    updated_at = models.DateTimeField(auto_now=True)  # NEW

    def compute_ai_hash(self):
        """
        Hash title/url/path for quick change detection.
        """
        raw = f"{self.window_title or ''}|{self.url or ''}|{self.file_path or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def has_ai_inputs_changed(self):
        """
        Returns True if the hash changed since last save.
        """
        new_hash = self.compute_ai_hash()
        return self.ai_hash != new_hash

    def save(self, *args, **kwargs):
        # compute and store hash before save
        new_hash = self.compute_ai_hash()
        if not self.ai_hash or self.ai_hash != new_hash:
            self.ai_hash = new_hash
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=["org", "user", "day"]),
            models.Index(fields=["org", "start"]),
            models.Index(fields=["org", "client"]),
            models.Index(fields=["org", "project"]),
            models.Index(fields=["org", "task"]),
            models.Index(fields=["updated_at"]),  # optional

        ]

    def __str__(self):
        return f"{self.user.username} - {self.ai_category or 'Unclassified'} - {self.day}"


class Suggestion(models.Model):
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="suggestions")
    label_type = models.CharField(max_length=20, choices=[("client", "client"), ("project", "project"), ("task", "task")])
    value_text = models.CharField(max_length=255)
    confidence = models.FloatField(default=0.0)
    source = models.CharField(max_length=20, default="rule")
    created_at = models.DateTimeField(auto_now_add=True)


class Rule(models.Model):
    org = models.ForeignKey(Group, on_delete=models.CASCADE)
    pattern = models.CharField(max_length=500)
    field = models.CharField(max_length=20, choices=[("client", "client"), ("project", "project"), ("task", "task")])
    value_text = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=[("contains", "contains"), ("regex", "regex"), ("glob", "glob")], default="contains")
    active = models.BooleanField(default=True)


# ===============================
# ======  TIME ENTRIES  =========
# ===============================
class TimecardEntry(models.Model):
    org = models.ForeignKey(Group, on_delete=models.CASCADE)
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


# ===============================
# ======  AI + ORG CONFIG  ======
# ===============================
class AIProcessingLog(models.Model):
    org = models.ForeignKey(Group, on_delete=models.CASCADE)
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
    org = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="settings")
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
    org = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="known_entities")
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
    org = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="training_examples")
    text_content = models.TextField()
    correct_client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_examples")
    correct_project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_examples")
    correct_categories = models.JSONField(default=dict)
    original_prediction = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ===============================
# ======  CLASSIFICATION RULES ==
# ===============================
class ClientPattern(models.Model):
    org = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="client_patterns", db_index=True)
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
    org = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="task_patterns", db_index=True)
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