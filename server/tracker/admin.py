# tracker/admin.py
from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from .models import Client, Project, Task, Block, TimecardEntry, Rule, KnownEntity, AITrainingExample, ClientPattern, TaskPattern, OrgInstallToken, AgentRegistration

# ---- Helpers to be idempotent ----
def _unregister(model):
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass

# Unregister before (re)register to avoid AlreadyRegistered on reloads / refactors
for m in (Block, Client, Project, Task, TimecardEntry, Rule, KnownEntity, AITrainingExample, ClientPattern, TaskPattern):
    _unregister(m)

@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = (
        "start", "end", "user", "hostname", "minutes",
        "client", "project", "task", "locked",
        "ai_extracted_client", "ai_category", "ai_confidence", "ai_processed_at",
    )
    search_fields = ("user__username", "hostname", "title", "window_title", "url", "file_path", "ai_extracted_client", "ai_category")
    list_filter = ("locked", "client", "project", "task", "ai_category")
    readonly_fields = ("minutes", "day", "ai_processed_at", "ai_confidence", "ai_extracted_client", "ai_category", "ai_hash", "updated_at")

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("org", "name", "is_active")
    search_fields = ("name",)
    list_filter = ("is_active", "org")

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("org", "client", "name", "is_active")
    search_fields = ("name", "client__name")
    list_filter = ("is_active", "org", "client")

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("org", "project", "name", "billable")
    search_fields = ("name", "project__name")
    list_filter = ("billable", "org", "project")

@admin.register(TimecardEntry)
class TimecardEntryAdmin(admin.ModelAdmin):
    list_display = ("org", "user", "date", "client", "project", "total_hours", "status", "confidence_score", "needs_review")
    list_filter = ("status", "needs_review", "org", "client", "project")
    search_fields = ("user__username", "client__name", "project__name")
    readonly_fields = ("created_at", "updated_at")

@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ("org", "field", "kind", "value_text", "active")
    list_filter = ("org", "field", "kind", "active")
    search_fields = ("pattern", "value_text")

@admin.register(KnownEntity)
class KnownEntityAdmin(admin.ModelAdmin):
    list_display = ("org", "entity_type", "name", "is_internal", "confidence_boost", "updated_at")
    list_filter = ("org", "entity_type", "is_internal")
    search_fields = ("name",)

@admin.register(AITrainingExample)
class AITrainingExampleAdmin(admin.ModelAdmin):
    list_display = ("org", "correct_client", "correct_project", "created_at")
    list_filter = ("org", "correct_client", "correct_project")
    search_fields = ("text_content",)

@admin.register(ClientPattern)
class ClientPatternAdmin(admin.ModelAdmin):
    list_display = ("client_name", "match_type", "pattern", "weight")
    list_filter = ("match_type",)
    search_fields = ("client_name", "pattern")

@admin.register(TaskPattern)
class TaskPatternAdmin(admin.ModelAdmin):
    list_display = ("task_category", "match_type", "pattern", "weight")
    list_filter = ("match_type",)
    search_fields = ("task_category", "pattern")



@admin.register(OrgInstallToken)
class OrgInstallTokenAdmin(admin.ModelAdmin):
    list_display = ['org', 'token', 'is_active', 'created_at']
    list_filter = ['is_active', 'org']
    readonly_fields = ['token', 'created_at']
    
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing existing
            return ['token', 'org', 'created_at']
        return ['token', 'created_at']

@admin.register(AgentRegistration)
class AgentRegistrationAdmin(admin.ModelAdmin):
    list_display = ['user', 'org', 'machine_name', 'os', 'last_seen', 'is_active']
    list_filter = ['org', 'os', 'is_active']
    search_fields = ['user__username', 'machine_name']
    readonly_fields = ['agent_key', 'first_seen', 'last_seen']


# Add this to tracker/admin.py (or create the file)

"""
Django admin configuration for TimeTracker models.
Provides nice UI for managing Organizations and Memberships.
"""

from django.contrib import admin
from tracker.models import Organization, OrganizationMembership


class OrganizationMembershipInline(admin.TabularInline):
    """Inline for viewing/editing memberships from Organization page"""
    model = OrganizationMembership
    extra = 0
    fields = ['user', 'role', 'invited_by', 'joined_at']
    readonly_fields = ['joined_at']
    autocomplete_fields = ['user', 'invited_by']


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """Admin interface for Organizations"""
    list_display = ['name', 'slug', 'plan', 'created_at', 'member_count']  # ✅ Only fields that exist
    list_filter = ['plan']
    search_fields = ['name', 'slug']  # ✅ Only fields that exist
    readonly_fields = ['created_at', 'updated_at']
    inlines = [OrganizationMembershipInline]
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'slug')
        }),
        ('Subscription', {
            'fields': ('plan', 'trial_ends_at', 'stripe_customer_id')
        }),
        ('Settings', {
            'fields': ('timezone', 'billing_rate_default')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def member_count(self, obj):
        """Show number of members in the org"""
        return obj.memberships.count()
    member_count.short_description = 'Members'


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    """Admin interface for Organization Memberships"""
    list_display = ['user', 'organization', 'role', 'invited_by', 'joined_at']
    list_filter = ['role', 'organization']
    search_fields = ['user__username', 'user__email', 'organization__name']
    readonly_fields = ['joined_at']
    autocomplete_fields = ['user', 'organization', 'invited_by']
    
    fieldsets = (
        ('Membership', {
            'fields': ('user', 'organization', 'role')
        }),
        ('Metadata', {
            'fields': ('invited_by', 'joined_at'),
            'classes': ('collapse',)
        }),
    )

from tracker.models import AgentError

@admin.register(AgentError)
class AgentErrorAdmin(admin.ModelAdmin):
    list_display = ['id', 'error_type', 'user', 'hostname', 'app_version', 'created_at', 'resolved']
    list_filter = ['error_type', 'app_version', 'resolved', 'created_at']
    search_fields = ['hostname', 'device_id', 'error_message', 'user__username', 'os_username']
    readonly_fields = ['created_at', 'client_timestamp']
    date_hierarchy = 'created_at'
    
    list_per_page = 50
    
    fieldsets = (
        ('Error', {
            'fields': ('error_type', 'error_message', 'traceback')
        }),
        ('Device', {
            'fields': ('user', 'hostname', 'device_id', 'os_username', 'app_version', 'platform')
        }),
        ('Context', {
            'fields': ('context',),
            'classes': ('collapse',)
        }),
        ('Resolution', {
            'fields': ('resolved', 'resolved_at', 'resolved_by', 'notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'client_timestamp'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_resolved', 'mark_unresolved']
    
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True, resolved_at=timezone.now(), resolved_by=request.user)
    mark_resolved.short_description = "Mark selected errors as resolved"
    
    def mark_unresolved(self, request, queryset):
        queryset.update(resolved=False, resolved_at=None, resolved_by=None)
    mark_unresolved.short_description = "Mark selected errors as unresolved"


"""
tracker/admin_provisioning.py

Admin registration for provisioning models.
Import in your admin.py:
    from tracker.admin_provisioning import *
"""

from django.contrib import admin
from tracker.models_provisioning import OnboardingBatch, DeviceProvisioningMap


class DeviceProvisioningMapInline(admin.TabularInline):
    model = DeviceProvisioningMap
    extra = 0
    readonly_fields = ('status', 'paired_device', 'paired_user', 'paired_at', 'match_method')
    fields = (
        'machine_hostname', 'windows_username', 'email', 'display_name',
        'role', 'billing_rate', 'status', 'match_method', 'paired_at',
    )


@admin.register(OnboardingBatch)
class OnboardingBatchAdmin(admin.ModelAdmin):
    list_display = (
        'organization', 'status', 'total_users', 'total_devices',
        'devices_paired', 'pair_percentage', 'created_at',
    )
    list_filter = ('status', 'organization')
    readonly_fields = (
        'total_users', 'total_devices', 'total_clients',
        'devices_paired', 'created_at', 'updated_at', 'completed_at',
    )
    inlines = [DeviceProvisioningMapInline]
    
    def pair_percentage(self, obj):
        return f'{obj.pair_percentage}%'
    pair_percentage.short_description = 'Paired %'


@admin.register(DeviceProvisioningMap)
class DeviceProvisioningMapAdmin(admin.ModelAdmin):
    list_display = (
        'machine_hostname', 'email', 'display_name', 'role',
        'status', 'match_method', 'paired_at', 'organization',
    )
    list_filter = ('status', 'organization', 'role')
    search_fields = ('machine_hostname', 'windows_username', 'email', 'display_name')
    readonly_fields = ('paired_device', 'paired_user', 'paired_at', 'match_method', 'error_message')
    
    fieldsets = (
        ('Device Matching', {
            'fields': ('organization', 'batch', 'machine_hostname', 'windows_username')
        }),
        ('Target User', {
            'fields': ('email', 'display_name', 'role', 'billing_rate', 'cost_rate')
        }),
        ('Pairing Result', {
            'fields': ('status', 'paired_device', 'paired_user', 'paired_at', 'match_method', 'error_message')
        }),
    )