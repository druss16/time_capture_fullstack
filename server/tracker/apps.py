# tracker/apps.py
from django.apps import AppConfig


class TrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tracker"
    
    def ready(self):
        # Auto-import signal handlers (so Blocks classify automatically)
        import tracker.signals  # noqa
        
        # Connect billing rate signal
        from django.db.models.signals import pre_save
        from tracker.models import Block
        from tracker.utils.billing import apply_billing_rate_on_save
        
        pre_save.connect(apply_billing_rate_on_save, sender=Block)