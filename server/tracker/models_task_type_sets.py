"""
TaskType Sets, per-Client overrides, and external system mappings.

DESIGN PRINCIPLES
-----------------
1. Uses your existing TaskType model as the canonical "service code" —
   does NOT create a parallel ServiceCode table.

2. Three layers:
     - TaskTypeSet: named bundle of TaskTypes (e.g. "Standard", "Audit-Only")
     - ClientTaskType: per-client override when a client needs custom codes
     - External*Mapping: maps internal TaskType/Client/User to external
       system IDs (CCH Axcess, future: Karbon, Drake, etc.)

3. Matrix rules (which staff can use which TaskType for which Client) live
   in your existing OrgRoutingRule with source='cch_axcess_sync'.

4. Use FK 'org' (not 'organization') to match your existing convention.

INTEGRATION POINTS
------------------
- Block.task_type already exists — no change needed
- Client gets one new field: default_task_type_set (added in migration 0086)
- Integration.PROVIDER_CHOICES needs 'cch_axcess' added (1-line edit
  in tracker/models.py — no migration needed since CharField)
- OrgRoutingRule gets a 'source' field (migration 0089)

Import this module from tracker/models.py:
    from tracker.models_task_type_sets import (
        TaskTypeSet,
        TaskTypeSetMember,
        ClientTaskType,
        ExternalClientMapping,
        ExternalTaskTypeMapping,
        ExternalStaffMapping,
    )
"""

from django.db import models
from django.conf import settings
from django.utils import timezone


# ============================================================================
# TaskType Sets — bundle TaskTypes for default lists / templates
# ============================================================================

class TaskTypeSet(models.Model):
    """
    A named bundle of TaskTypes representing a default list.

    Examples per org:
      - "Standard" (default for most clients)
      - "Audit-Only" (used for assurance clients)
      - "Bookkeeping-Only" (used for monthly write-up clients)
      - "Tax Resolution" (specialty bundle)

    A firm has one or more TaskTypeSets. One can be marked is_default=True
    and serves as the firm-wide default. Clients can override by pointing
    Client.default_task_type_set at a different set, OR by adding
    ClientTaskType rows for finer-grained per-client control.
    """
    org = models.ForeignKey(
        'tracker.Organization',
        on_delete=models.CASCADE,
        related_name='task_type_sets',
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True, default='')

    # Exactly one set per org can be is_default=True (enforced by save())
    is_default = models.BooleanField(
        default=False,
        help_text='If True, this set is the firm-wide default for clients '
                  'that have no specific default_task_type_set assigned.',
    )

    # Source of truth — manual or synced from external system
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('cch_axcess_sync', 'CCH Axcess Sync'),
        ('seed', 'Seeded from default'),
    ]
    source = models.CharField(
        max_length=32, choices=SOURCE_CHOICES, default='manual',
        help_text='Where this set came from. Synced sets are read-only in admin UI.',
    )

    # Many-to-many to TaskType through TaskTypeSetMember for ordering
    task_types = models.ManyToManyField(
        'tracker.TaskType',
        through='TaskTypeSetMember',
        related_name='in_sets',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='task_type_sets_created',
    )

    class Meta:
        unique_together = [['org', 'name']]
        ordering = ['name']
        indexes = [
            models.Index(fields=['org', 'is_default']),
        ]

    def __str__(self):
        default_tag = ' [DEFAULT]' if self.is_default else ''
        return f'{self.name}{default_tag} ({self.task_types.count()} types)'

    def save(self, *args, **kwargs):
        # Enforce: only one is_default=True per org
        if self.is_default:
            TaskTypeSet.objects.filter(
                org=self.org, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class TaskTypeSetMember(models.Model):
    """
    Through-model for TaskTypeSet ↔ TaskType many-to-many.
    Provides sort_order so the UI can show TaskTypes in a deliberate order.
    """
    set = models.ForeignKey(
        TaskTypeSet,
        on_delete=models.CASCADE,
        related_name='members',
    )
    task_type = models.ForeignKey(
        'tracker.TaskType',
        on_delete=models.CASCADE,
        related_name='set_memberships',
    )
    sort_order = models.IntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['set', 'task_type']]
        ordering = ['sort_order', 'task_type__name']
        indexes = [
            models.Index(fields=['set', 'sort_order']),
        ]

    def __str__(self):
        return f'{self.set.name} → {self.task_type.name}'


# ============================================================================
# ClientTaskType — per-Client TaskType overrides
# ============================================================================

class ClientTaskType(models.Model):
    """
    Per-Client override of which TaskTypes are allowed.

    RESOLUTION ORDER (see services/task_type_resolver.py):
      1. If ClientTaskType rows exist for the client → use them (custom mode)
      2. Else if Client.default_task_type_set is set → use that set
      3. Else if org has a TaskTypeSet with is_default=True → use that
      4. Else → all active TaskTypes for the org

    A row with allowed=False explicitly DISABLES a TaskType for the client
    even if it's in the resolved set. This is how you remove one specific
    TaskType from the default list without redefining the whole list.
    """
    client = models.ForeignKey(
        'tracker.Client',
        on_delete=models.CASCADE,
        related_name='task_type_overrides',
    )
    task_type = models.ForeignKey(
        'tracker.TaskType',
        on_delete=models.CASCADE,
        related_name='client_overrides',
    )

    allowed = models.BooleanField(
        default=True,
        help_text='True = explicitly allow this TaskType for this client. '
                  'False = explicitly forbid even if in default set.',
    )

    # Optional per-client billing override
    override_rate = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True,
        help_text='If set, overrides TaskType.default_rate for this client.',
    )

    # Source — manual or synced from CCH Axcess matrix
    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('cch_axcess_sync', 'CCH Axcess Sync'),
    ]
    source = models.CharField(
        max_length=32, choices=SOURCE_CHOICES, default='manual',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='client_task_types_created',
    )

    class Meta:
        unique_together = [['client', 'task_type']]
        ordering = ['task_type__sort_order', 'task_type__name']
        indexes = [
            models.Index(fields=['client', 'allowed']),
            models.Index(fields=['source']),
        ]

    def __str__(self):
        flag = '✓' if self.allowed else '✗'
        return f'{flag} {self.client.name} → {self.task_type.name}'


# ============================================================================
# External system mappings — hang off existing Integration model
# ============================================================================

class ExternalClientMapping(models.Model):
    """
    Maps internal Client to an external system's identifier.

    Example: TL Wall's "Smith, Inc." (Client.id=42) maps to CCH Axcess
    client code "SMITH001" via integration.id=7 (cch_axcess for org=21).
    """
    integration = models.ForeignKey(
        'tracker.Integration',
        on_delete=models.CASCADE,
        related_name='client_mappings',
    )
    client = models.ForeignKey(
        'tracker.Client',
        on_delete=models.CASCADE,
        related_name='external_mappings',
    )

    # External identifier — varies by provider:
    #   cch_axcess:  practice client code
    #   quickbooks:  customer ID (also stored on Client.quickbooks_id for legacy)
    #   xero:        contact ID (also stored on Client.xero_id for legacy)
    external_id = models.CharField(max_length=128, db_index=True)
    external_code = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Human-readable code if different from external_id.',
    )

    # Cached display fields from the external system
    external_name = models.CharField(max_length=255, blank=True, default='')
    external_status = models.CharField(max_length=32, blank=True, default='')

    # Sync state
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_seen_in_source = models.DateTimeField(
        null=True, blank=True,
        help_text='Last time this record was returned by the source API. '
                  'Stale records (not seen in >30 days) are candidates for archival.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ['integration', 'external_id'],
            ['integration', 'client'],
        ]
        indexes = [
            models.Index(fields=['integration', 'external_id']),
            models.Index(fields=['client']),
        ]

    def __str__(self):
        return f'{self.integration.provider}: {self.client.name} ↔ {self.external_code or self.external_id}'


class ExternalTaskTypeMapping(models.Model):
    """
    Maps internal TaskType to an external system's service/activity code.

    Example: TaskType code "TAX" maps to CCH Axcess service code "1040PREP".
    """
    integration = models.ForeignKey(
        'tracker.Integration',
        on_delete=models.CASCADE,
        related_name='task_type_mappings',
    )
    task_type = models.ForeignKey(
        'tracker.TaskType',
        on_delete=models.CASCADE,
        related_name='external_mappings',
    )

    external_id = models.CharField(max_length=128, db_index=True)
    external_code = models.CharField(max_length=64, blank=True, default='')
    external_name = models.CharField(max_length=255, blank=True, default='')

    # Provider may classify codes (e.g. CCH Axcess: "Service" vs "Activity")
    external_category = models.CharField(max_length=64, blank=True, default='')

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_seen_in_source = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ['integration', 'external_id'],
            ['integration', 'task_type'],
        ]
        indexes = [
            models.Index(fields=['integration', 'external_id']),
            models.Index(fields=['task_type']),
        ]

    def __str__(self):
        return f'{self.integration.provider}: {self.task_type.name} ↔ {self.external_code or self.external_id}'


class ExternalStaffMapping(models.Model):
    """
    Maps internal User (staff member) to an external system's staff ID.

    Required for pushing time entries — CCH Axcess WIP entries must specify
    who logged the time using their CCH staff code.
    """
    integration = models.ForeignKey(
        'tracker.Integration',
        on_delete=models.CASCADE,
        related_name='staff_mappings',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='external_staff_mappings',
    )

    external_id = models.CharField(max_length=128, db_index=True)
    external_code = models.CharField(max_length=64, blank=True, default='')
    external_name = models.CharField(max_length=255, blank=True, default='')
    external_email = models.EmailField(blank=True, default='')

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_seen_in_source = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ['integration', 'external_id'],
            ['integration', 'user'],
        ]
        indexes = [
            models.Index(fields=['integration', 'external_id']),
            models.Index(fields=['user']),
        ]

    def __str__(self):
        return f'{self.integration.provider}: {self.user.username} ↔ {self.external_code or self.external_id}'


class CategoryTaskTypeMapping(models.Model):
    """
    Maps a canonical classifier category string to an org's TaskType.

    Layer 1 (the classifier's universal category vocabulary) -> Layer 2
    (this firm's TaskType records). Populated at onboarding, read by
    resolve_task_type_for_category() in the classification pipeline AND by
    the billing export.

    Example: canonical category "Tax Preparation" -> this org's TaskType
    with code "1040PREP".
    """
    SOURCE_CHOICES = [
        ('seed', 'Seed (1:1 default from onboarding)'),
        ('manual', 'Manually configured'),
        ('cch_sync', 'CCH Axcess sync'),
    ]

    org = models.ForeignKey(
        'tracker.Organization',
        on_delete=models.CASCADE,
        related_name='category_task_type_mappings',
    )
    # The canonical Layer 1 category string the classifier emits.
    # Not a FK — Layer 1 is a code-level constant list, not a DB table.
    category = models.CharField(max_length=100, db_index=True)

    task_type = models.ForeignKey(
        'tracker.TaskType',
        on_delete=models.CASCADE,
        related_name='category_mappings',
    )

    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default='manual',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['org', 'category']]
        ordering = ['org_id', 'category']
        verbose_name = 'Category → TaskType Mapping'
        verbose_name_plural = 'Category → TaskType Mappings'

    def __str__(self):
        return f'{self.org_id}: "{self.category}" → {self.task_type.code}'