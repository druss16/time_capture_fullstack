"""
MavOps-controlled per-org feature switches (OrgFeatureFlag).

Read through here, never off the model directly: this answers False on ANY
database error, so a deploy that lands before its migration degrades to
"feature off" instead of failing the request that asked.
"""
import logging

logger = logging.getLogger(__name__)

PROJECT_SWITCH = 'project_switch'


def feature_enabled(org, key: str) -> bool:
    if org is None:
        return False
    try:
        from tracker.models import OrgFeatureFlag
        return OrgFeatureFlag.objects.filter(org=org, key=key, enabled=True).exists()
    except Exception as e:
        logger.warning('feature flag %s unreadable for org %s: %s', key, getattr(org, 'id', '?'), e)
        return False


def flags_for_orgs(org_ids, key: str) -> set:
    """org ids with `key` on — one query for a list page."""
    try:
        from tracker.models import OrgFeatureFlag
        return set(OrgFeatureFlag.objects.filter(org_id__in=list(org_ids), key=key, enabled=True)
                   .values_list('org_id', flat=True))
    except Exception as e:
        logger.warning('feature flags %s unreadable: %s', key, e)
        return set()


def set_feature(org, key: str, enabled: bool, user=None):
    from tracker.models import OrgFeatureFlag
    flag, _ = OrgFeatureFlag.objects.update_or_create(
        org=org, key=key, defaults={'enabled': bool(enabled), 'updated_by': user})
    return flag
