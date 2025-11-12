# tracker/utils/__init__.py
from .monitoring import capture_exception        # noqa: F401
from .agent import resolve_agent_user            # noqa: F401
from .org import get_org_or_default              # noqa: F401
from .blocks import (                            # noqa: F401
    resolve_client_from_known,
    infer_task_for_block,
    compact_rawevents_into_blocks,
)

# If your compactor exposes _compact_safe, re-export it for convenience.
try:
    from .blocks import _compact_safe            # type: ignore  # noqa: F401
except Exception:
    _compact_safe = None  # optional

from .utils_main import _client_ip               # noqa: F401

# Classifier guarded wrapper
from tracker.services.classify_block import classify_block as _classify_block_impl

def _classify_block_guarded(block, *, allow_llm: bool):
    """
    Per-call toggle for LLM usage in classification.
    UI/real-time paths should pass allow_llm=False to avoid blocking on LLM.
    """
    return _classify_block_impl(block, allow_llm=allow_llm)

__all__ = [
    "capture_exception",
    "resolve_agent_user",
    "get_org_or_default",
    "resolve_client_from_known",
    "infer_task_for_block",
    "compact_rawevents_into_blocks",
    "_client_ip",
    "_classify_block_guarded",
]

# Optionally include _compact_safe in __all__ if it exists
if _compact_safe:
    __all__.append("_compact_safe")