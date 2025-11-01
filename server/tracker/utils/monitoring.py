# tracker/utils/monitoring.py
from django.conf import settings

def capture_exception(e):
    """
    Light wrapper so you can call capture_exception(e) anywhere
    without crashing if Sentry isn't configured.
    """
    dsn = getattr(settings, "SENTRY_DSN", None)
    try:
        if dsn:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        elif getattr(settings, "DEBUG", False):
            print(f"[Error] {e}")
    except Exception as _:
        # Never let monitoring throw
        if getattr(settings, "DEBUG", False):
            print(f"[monitoring wrapper failed] {e}")