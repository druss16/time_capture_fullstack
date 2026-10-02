"""
Is the desktop agent's agent-presence MEASUREMENT switched on for this device?

Answered on every agent control check-in (every ~10s per agent), so the switch
rows are cached per process for CACHE_S: a flip reaches every agent within
about CACHE_S + 10 seconds, and the check-in costs no query in between.

Precedence, most specific first: device row, firm row, everyone row, default
ON. The AGENT_PRESENCE_DISABLED env var beats all of it — the emergency path
that needs no database and no migration.

Never raises: if anything goes wrong (the table not migrated yet included), the
answer is "on", which is exactly the behaviour agents had before this switch
existed — and the server never makes tracking itself depend on it.
"""
import logging
import os
import time

logger = logging.getLogger(__name__)

CACHE_S = 30
_cache = {"at": 0.0, "rows": None}


def _env_disabled() -> bool:
    return (os.environ.get("AGENT_PRESENCE_DISABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def _rows():
    now = time.monotonic()
    if _cache["rows"] is None or now - _cache["at"] > CACHE_S:
        from tracker.models import AgentPresenceSwitch
        everyone, by_org, by_device = None, {}, {}
        for r in AgentPresenceSwitch.objects.all().values('org_id', 'device_pk', 'enabled'):
            if r['device_pk']:
                by_device[r['device_pk']] = r['enabled']
            elif r['org_id']:
                by_org[r['org_id']] = r['enabled']
            else:
                everyone = r['enabled']
        _cache.update(at=now, rows=(everyone, by_org, by_device))
    return _cache["rows"]


def clear_cache():
    _cache.update(at=0.0, rows=None)


def presence_enabled_for(device) -> bool:
    if _env_disabled():
        return False
    try:
        everyone, by_org, by_device = _rows()
        if device is not None and device.pk in by_device:
            return by_device[device.pk]
        if device is not None and by_org and device.user_id:
            from tracker.models import OrganizationMembership
            org_ids = OrganizationMembership.objects.filter(
                user_id=device.user_id).values_list('organization_id', flat=True)
            for oid in org_ids:
                if oid in by_org:
                    return by_org[oid]
        return True if everyone is None else everyone
    except Exception as e:  # e.g. migration not applied yet
        logger.warning("[agent_presence_switch] defaulting to on: %s", e)
        return True
