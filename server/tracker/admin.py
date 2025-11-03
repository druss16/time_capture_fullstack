# tracker/admin.py
from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from .models import Client, Project, Task, Block, TimecardEntry, Rule, KnownEntity, AITrainingExample, ClientPattern, TaskPattern

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