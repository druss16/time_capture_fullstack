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

@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("start", "end", "user", "hostname", "title", "minutes", "client", "project", "task", "locked")
    search_fields = ("user__username", "hostname", "title", "window_title", "url", "file_path")
    list_filter = ("locked", "client", "project", "task")

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