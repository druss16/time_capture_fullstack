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


# ── Writes — shared by `manage.py agent_presence_switch` and MavOps Admin ──

def env_disabled_value() -> str:
    return (os.environ.get("AGENT_PRESENCE_DISABLED") or "").strip()


def set_switch(enabled: bool, org_id=None, device_pk=None, note: str = ""):
    """Upsert one scope's row (both ids None = everyone). Takes effect on
    agents within ~CACHE_S + 10s."""
    from tracker.models import AgentPresenceSwitch
    row, _ = AgentPresenceSwitch.objects.update_or_create(
        org_id=org_id or None, device_pk=device_pk or None,
        defaults={'enabled': bool(enabled), 'note': (note or '')[:255]})
    clear_cache()
    return row


def clear_switch(org_id=None, device_pk=None) -> int:
    """Remove one scope's row so it inherits again."""
    from tracker.models import AgentPresenceSwitch
    n, _ = AgentPresenceSwitch.objects.filter(
        org_id=org_id or None, device_pk=device_pk or None).delete()
    clear_cache()
    return n


def switch_rows():
    """Every row, labelled, most specific first — for display."""
    from tracker.models import AgentDevice, AgentPresenceSwitch, Organization
    rows = list(AgentPresenceSwitch.objects.all())
    orgs = dict(Organization.objects.filter(
        pk__in=[r.org_id for r in rows if r.org_id]).values_list('pk', 'name'))
    devices = {d.pk: d for d in AgentDevice.objects.filter(
        pk__in=[r.device_pk for r in rows if r.device_pk]).select_related('user')}
    out = []
    for r in rows:
        d = devices.get(r.device_pk)
        scope = 'device' if r.device_pk else 'org' if r.org_id else 'all'
        out.append({
            'id': r.pk, 'scope': scope, 'enabled': r.enabled, 'note': r.note,
            'updated_at': r.updated_at.isoformat(),
            'org_id': r.org_id, 'org_name': orgs.get(r.org_id, ''),
            'device_pk': r.device_pk,
            'device_label': (f"{d.hostname or d.device_id}" + (f" · {d.user.email}" if d.user else ''))
                            if d else ('(deleted device)' if r.device_pk else ''),
        })
    order = {'device': 0, 'org': 1, 'all': 2}
    return sorted(out, key=lambda r: order[r['scope']])
