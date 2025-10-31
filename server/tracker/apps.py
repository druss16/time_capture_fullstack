# tracker/apps.py
from django.apps import AppConfig

class TrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tracker"

    def ready(self):
        # Auto-import signal handlers (so Blocks classify automatically)
        import tracker.signals  # noqa