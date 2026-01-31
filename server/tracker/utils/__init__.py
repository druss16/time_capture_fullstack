# tracker/utils/__init__.py
"""
Utility functions for TimeTracker.

Cleaned up version - removed references to non-existent modules.
"""

from .monitoring import capture_exception        # noqa: F401
from .blocks import (                            # noqa: F401
    resolve_client_from_known,
    infer_task_for_block,
)

# Optional: If your blocks module exposes _compact_safe, re-export it
try:
    from .blocks import _compact_safe            # type: ignore  # noqa: F401
except ImportError:
    _compact_safe = None  # optional

# Client IP helper
try:
    from .utils_main import _client_ip           # noqa: F401
except ImportError:
    # If utils_main.py doesn't exist, provide a simple fallback
    def _client_ip(request):
        """Extract client IP from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')

__all__ = [
    "capture_exception",
    "resolve_client_from_known",
    "infer_task_for_block",
    "_client_ip",
]

# Include _compact_safe if it exists
if _compact_safe:
    __all__.append("_compact_safe")