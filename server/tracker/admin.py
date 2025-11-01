# tracker/admin.py
from django.contrib import admin
from .models import (
    RawEvent, Block, TimecardEntry,
    AgentControl, AgentSession, Client, Project, Task,
    Rule, OrganizationSettings, KnownEntity, AITrainingExample, AIProcessingLog
)

@admin.register(AgentControl)
class AgentControlAdmin(admin.ModelAdmin):
    list_display = ("user", "host", "stop", "stop_until", "reason", "updated_at")
    list_filter  = ("stop",)
    search_fields = ("user__username", "host", "reason")
    autocomplete_fields = ("user",)

# tracker/admin.py
@admin.register(AgentSession)
class AgentSessionAdmin(admin.ModelAdmin):
    list_display = ("username", "hostname", "last_seen", "platform", "version")
    search_fields = ("user__username", "hostname")

    def username(self, obj):
        return getattr(obj.user, "username", obj.user_id)

@admin.register(RawEvent)
class RawEventAdmin(admin.ModelAdmin):
    list_display = ("ts_utc", "user", "hostname", "app_name", "bundle_id")
    search_fields = ("user__username", "hostname", "app_name", "bundle_id", "window_title", "url", "file_path")
    list_filter = ("app_name", "bundle_id")

from django.contrib import admin
from .models import Block
from django.utils.html import format_html

@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = (
        "id", "day", "user", "hostname",
        "short_title", "minutes",
        "client", "project", "task",
        "ai_extracted_client", "ai_category", "ai_confidence",
        "updated_at", "locked",
    )
    list_filter = (
        "day", "locked", "client", "project", "task",
        "ai_extracted_client", "ai_category",
    )
    search_fields = (
        "user__username", "hostname",
        "title", "window_title", "url", "file_path",
        "ai_extracted_client", "ai_category",
    )
    readonly_fields = ("ai_hash", "ai_confidence", "updated_at")
    actions = ["reclassify_selected"]

    def short_title(self, obj):
        t = obj.window_title or obj.title or ""
        return t[:60] + ("…" if len(t) > 60 else "")
    short_title.short_description = "Title"

    def reclassify_selected(self, request, queryset):
        # Queue Celery tasks to reclassify in background
        try:
            from tracker.tasks import classify_block_task
        except Exception:
            self.message_user(request, "Celery task not available; did you set up Celery?", level="error")
            return
        count = 0
        for b in queryset:
            classify_block_task.delay(b.pk)
            count += 1
        self.message_user(request, f"Queued reclassification for {count} block(s).")
    reclassify_selected.short_description = "Reclassify with AI"
@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = (
        "id", "day", "window_title", "ai_extracted_client", "ai_category", "ai_confidence", "updated_at"
    )
    list_filter = ("ai_extracted_client", "ai_category", "day")
    search_fields = ("window_title", "url", "file_path")
    readonly_fields = ("ai_hash", "ai_confidence")

@admin.register(TimecardEntry)
class TimecardEntryAdmin(admin.ModelAdmin):
    list_display = ("date", "user", "client", "project", "total_hours", "status", "needs_review", "reviewed_at")
    list_filter = ("status", "needs_review", "client")
    search_fields = ("user__username", "client__name", "project__name")

admin.site.register(Client)
admin.site.register(Project)
admin.site.register(Task)
admin.site.register(Rule)
admin.site.register(OrganizationSettings)
admin.site.register(KnownEntity)
admin.site.register(AITrainingExample)
admin.site.register(AIProcessingLog)