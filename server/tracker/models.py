from django.db import models
from django.utils import timezone  # ADD THIS LINE if not there


class RawEvent(models.Model):
    ts_utc = models.DateTimeField()
    app_name = models.CharField(max_length=255, blank=True, null=True)
    bundle_id = models.CharField(max_length=255, blank=True, null=True)
    window_title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, null=True)
    file_path = models.TextField(blank=True, null=True)
    user = models.CharField(max_length=255, blank=True, null=True)
    hostname = models.CharField(max_length=255, blank=True, null=True)
    ctx = models.JSONField(default=dict, blank=True)   # <<— NEW

    class Meta:
        indexes = [
            models.Index(fields=['ts_utc']),
            models.Index(fields=['user', 'hostname']),
        ]

        
class SuggestedBlock(models.Model):
    start=models.DateTimeField()
    end=models.DateTimeField()
    label=models.CharField(max_length=255, blank=True, null=True)
    client=models.CharField(max_length=255, blank=True, null=True)
    engagement=models.CharField(max_length=255, blank=True, null=True)
    task_code=models.CharField(max_length=64, blank=True, null=True)
    description=models.TextField(blank=True, null=True)
    confidence=models.FloatField(default=0.0)
    source_ids=models.JSONField(default=list)
    user=models.CharField(max_length=255, blank=True, null=True)
    hostname=models.CharField(max_length=255, blank=True, null=True)

# --- core master data ---
class Client(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)    # your tenant
    name = models.CharField(max_length=200, unique=False)
    is_active = models.BooleanField(default=True)

class Project(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

class Task(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=200)
    billable = models.BooleanField(default=True)

# --- classification ---
class Block(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    user = models.CharField(max_length=120)      # “danrussell” from agent
    hostname = models.CharField(max_length=120)
    start = models.DateTimeField()
    end = models.DateTimeField()
    title = models.TextField(blank=True, default="")
    window_title = models.TextField(blank=True, null=True)
    url = models.TextField(blank=True, default="")
    file_path = models.TextField(blank=True, default="")
    hints = models.JSONField(default=dict, blank=True)   # stores merged context (browser/vscode/shell etc.)

    # denormalized fields for filtering + UI
    day = models.DateField(db_index=True, null=True, blank=True)
    minutes = models.IntegerField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    attendees = models.JSONField(default=list, blank=True)
    # optional: category → hours (used when user edits a single block)
    category_hours = models.JSONField(default=dict, blank=True)

    # human choices
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL)
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True, default="")
    locked = models.BooleanField(default=False)  # after approval/export
    ai_extracted_client = models.CharField(max_length=255, blank=True, null=True)
    ai_confidence = models.FloatField(default=0.0)
    ai_category = models.CharField(max_length=100, blank=True, default="")
    ai_processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['org', 'user', 'day']),
            models.Index(fields=['org', 'start']),
        ]



class Suggestion(models.Model):
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="suggestions")
    label_type = models.CharField(max_length=20, choices=[("client","client"),("project","project"),("task","task")])
    value_text = models.CharField(max_length=255)     # human label
    confidence = models.FloatField(default=0.0)
    source = models.CharField(max_length=20, default="rule")   # rule|ml
    created_at = models.DateTimeField(auto_now_add=True)

# --- rules (admin-maintained, first line of automation) ---
class Rule(models.Model):
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    pattern = models.CharField(max_length=500)   # glob/regex for url/title/path
    field = models.CharField(max_length=20, choices=[("client","client"),("project","project"),("task","task")])
    value_text = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=[("contains","contains"),("regex","regex"),("glob","glob")], default="contains")
    active = models.BooleanField(default=True)


class TimecardEntry(models.Model):
    """AI-generated timecard entries ready for approval"""
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    user = models.CharField(max_length=120)
    date = models.DateField(db_index=True)
    
    client = models.ForeignKey("Client", on_delete=models.CASCADE, null=True, blank=True)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True, blank=True)
    
    total_hours = models.DecimalField(max_digits=5, decimal_places=2)
    category_breakdown = models.JSONField(default=dict)
    activities_summary = models.JSONField(default=list)
    
    confidence_score = models.FloatField(default=1.0)
    needs_review = models.BooleanField(default=False)
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    
    block_ids = models.JSONField(default=list)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date', '-total_hours']
        # ADD THIS:
        unique_together = [['org', 'user', 'date', 'client']]
        indexes = [
            models.Index(fields=['org', 'user', 'date']),
            models.Index(fields=['status']),
        ]
        
    def __str__(self):
        client_name = self.client.name if self.client else 'Unknown'
        return f"{self.user} - {client_name} - {self.date} ({self.total_hours}h)"
        
    def approve(self, notes=''):
        """Approve this timecard entry"""
        self.status = 'approved'
        self.reviewed_at = timezone.now()
        if notes:
            self.notes = notes
        self.save()
        
        # Lock source blocks
        if self.block_ids:
            Block.objects.filter(id__in=self.block_ids).update(locked=True)
        
    def reject(self, reason=''):
        """Reject this timecard entry"""
        self.status = 'rejected'
        self.reviewed_at = timezone.now()
        self.notes = reason
        self.save()


class AIProcessingLog(models.Model):
    """Track AI processing for debugging and cost monitoring"""
    org = models.ForeignKey("auth.Group", on_delete=models.CASCADE)
    user = models.CharField(max_length=120)
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
        ordering = ['-timestamp']


"""
Add these models to your Django models.py file
These will store organization-specific context for the AI
"""

from django.db import models
from django.contrib.auth.models import Group

class OrganizationSettings(models.Model):
    """
    Store organization-specific settings and context for AI
    """
    org = models.OneToOneField(Group, on_delete=models.CASCADE, related_name='settings')
    
    # Company information
    company_name = models.CharField(max_length=200, help_text="Your company name (e.g., 'PredictorEdge')")
    industry = models.CharField(max_length=200, blank=True, help_text="Industry/sector")
    description = models.TextField(blank=True, help_text="Brief description of what your company does")
    
    # AI training context
    internal_keywords = models.JSONField(
        default=list,
        help_text="Keywords that indicate internal work (e.g., ['admin', 'internal', 'team meeting'])"
    )
    
    default_internal_project = models.CharField(
        max_length=200,
        blank=True,
        help_text="Default project name for internal work"
    )
    
    # Additional context for AI
    custom_instructions = models.TextField(
        blank=True,
        help_text="Custom instructions for the AI classifier (e.g., 'Anything mentioning standup is internal')"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Organization Settings"
        verbose_name_plural = "Organization Settings"
    
    def __str__(self):
        return f"Settings for {self.company_name}"


class KnownEntity(models.Model):
    """
    Store known clients, projects, and categories for better AI classification
    """
    ENTITY_TYPES = [
        ('client', 'Client'),
        ('project', 'Project'),
        ('category', 'Category'),
        ('person', 'Person'),
    ]
    
    org = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='known_entities')
    entity_type = models.CharField(max_length=20, choices=ENTITY_TYPES)
    name = models.CharField(max_length=200)
    
    # Aliases and keywords to help AI recognize this entity
    aliases = models.JSONField(
        default=list,
        help_text="Alternative names or keywords (e.g., ['ACME', 'Acme Corp', 'acme.com'])"
    )
    
    # Relationships
    parent_client = models.ForeignKey(
        'Client',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="For projects, link to parent client"
    )
    
    # Additional context
    description = models.TextField(blank=True)
    is_internal = models.BooleanField(
        default=False,
        help_text="Mark as internal (not a real client)"
    )
    
    # Metadata
    confidence_boost = models.FloatField(
        default=0.0,
        help_text="Boost confidence when this entity is detected (-1.0 to 1.0)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['org', 'entity_type', 'name']
        ordering = ['entity_type', 'name']
    
    def __str__(self):
        return f"{self.entity_type}: {self.name}"
    
    def matches_text(self, text: str) -> bool:
        """Check if this entity matches the given text"""
        text_lower = text.lower()
        if self.name.lower() in text_lower:
            return True
        return any(alias.lower() in text_lower for alias in self.aliases)


class AITrainingExample(models.Model):
    """
    Store examples to improve AI classification over time
    User corrections become training data
    """
    org = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='training_examples')
    
    # Input
    text_content = models.TextField(help_text="The text that was classified")
    
    # Expected output (user's correction)
    correct_client = models.ForeignKey(
        'Client',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='training_examples'
    )
    correct_project = models.ForeignKey(
        'Project',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='training_examples'
    )
    correct_categories = models.JSONField(default=dict, help_text="Category -> hours")
    
    # What the AI originally predicted
    original_prediction = models.JSONField(default=dict)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Example: {self.text_content[:50]}..."

# at bottom of models.py
from django.db.models.signals import pre_save
from django.dispatch import receiver

@receiver(pre_save, sender=Block)
def _denormalize_block(sender, instance: Block, **kwargs):
    if instance.start:
        instance.day = instance.start.astimezone(timezone.get_current_timezone()).date()
    if instance.start and instance.end:
        mins = int((instance.end - instance.start).total_seconds() // 60)
        instance.minutes = max(0, mins)

