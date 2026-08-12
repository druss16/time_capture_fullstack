"""Shared Block-queryset helpers for analytics.

`exclude_idle` drops idle / lock-screen blocks. The agent records idle time as
"Idle/Uncategorized" (app_name "Idle") and lock-screen time (app_name "Lockapp")
blocks — they're captured but they are NOT active working time, so they must not
sit in the utilization "tracked" denominator (or they deflate every ratio).
"""
from __future__ import annotations

from django.db.models import Q

# App names / task-type names that represent idle or away-from-desk time.
IDLE_APP_NAMES = ("idle", "lockapp")
IDLE_TASK_TYPE_NAMES = ("idle",)


def exclude_idle(qs):
    """Return `qs` without idle / lock-screen blocks."""
    q = Q()
    for name in IDLE_APP_NAMES:
        q |= Q(app_name__iexact=name)
    for name in IDLE_TASK_TYPE_NAMES:
        q |= Q(task_type__name__iexact=name)
    return qs.exclude(q)
