"""
CCH Axcess Practice sync orchestration.

Pulls clients, staff, service codes, and matrix rules from CCH Axcess and
syncs them into:
  - Client (one row per Axcess client, with ExternalClientMapping link)
  - TaskType (one row per Axcess service code, with ExternalTaskTypeMapping link)
  - User + ExternalStaffMapping (staff member mapping)
  - OrgRoutingRule with source='cch_axcess_sync' and match_type='task_type_matrix'
    (matrix rules — which staff can use which service code for which client)

IDEMPOTENT — safe to re-run. Each entity is keyed by (integration, external_id).

WRITES INTO EXISTING TABLES — no shadow tables. This means:
  - QuickBooks-imported clients with imported_from='quickbooks' get an
    additional ExternalClientMapping row if they're also in Axcess
    (rare but possible: the same client tracked in both systems).
  - Manual TaskTypes are not touched. Only synced TaskTypes are tagged
    via ExternalTaskTypeMapping.

⚠️ The API response shapes (field names like 'clientId', 'name', etc.)
are PLACEHOLDERS based on common WK API conventions. Once you have
WK developer portal access, verify and adjust the .get() calls below.
"""

import logging
from datetime import datetime
from typing import Optional

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from tracker.integrations.cch_axcess.client import AxcessClient, AxcessError
from tracker.models import (
    Client,
    Integration,
    OrgRoutingRule,
    TaskType,
)
from tracker.models_task_type_sets import (
    ExternalClientMapping,
    ExternalStaffMapping,
    ExternalTaskTypeMapping,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ============================================================================
# Top-level orchestrator
# ============================================================================

def full_sync(integration: Integration) -> dict:
    """
    Run a full sync of clients, service codes, staff, and matrix rules.

    Returns a stats dict suitable for storing in a sync log or displaying
    in the admin UI.
    """
    started_at = timezone.now()
    client = AxcessClient(integration)

    stats = {
        'started_at': started_at.isoformat(),
        'integration_id': integration.id,
        'org_id': integration.organization_id,
        'service_codes': {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0},
        'clients': {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0},
        'staff': {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0},
        'matrix_rules': {'fetched': 0, 'created': 0, 'errors': 0},
        'errors': [],
    }

    try:
        stats['service_codes'] = sync_service_codes(client)
        stats['clients'] = sync_clients(client)
        stats['staff'] = sync_staff(client)
        stats['matrix_rules'] = sync_matrix_rules(client)

        integration.last_synced_at = timezone.now()
        integration.last_sync_status = 'success'
        integration.last_sync_error = ''
        integration.save(update_fields=[
            'last_synced_at', 'last_sync_status', 'last_sync_error', 'updated_at',
        ])

    except AxcessError as e:
        integration.last_sync_status = 'failed'
        integration.last_sync_error = str(e)[:500]
        integration.save(update_fields=['last_sync_status', 'last_sync_error', 'updated_at'])
        stats['errors'].append(str(e))
        logger.exception('CCH Axcess sync failed for integration %s', integration.id)

    stats['completed_at'] = timezone.now().isoformat()
    return stats


# ============================================================================
# Service codes (TaskType)
# ============================================================================

def sync_service_codes(client: AxcessClient) -> dict:
    """
    Pull service codes from Axcess → upsert TaskType + ExternalTaskTypeMapping.

    Uses TaskType.code matching when possible to merge with existing manual
    TaskTypes (e.g. firm already has a "TAX" TaskType — link it instead of
    creating a duplicate).
    """
    integration = client.integration
    org = integration.organization
    stats = {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0}

    now = timezone.now()

    for record in client.paginated_get('/service-codes'):
        try:
            ext_id = str(record.get('id') or record.get('serviceCodeId') or '')
            ext_code = (record.get('code') or '').strip()
            ext_name = (record.get('name') or record.get('description') or '').strip()
            is_billable = record.get('billable', True)

            if not ext_id:
                stats['errors'] += 1
                logger.warning('Skipping service code with no id: %r', record)
                continue

            stats['fetched'] += 1

            with transaction.atomic():
                # Try to find an existing mapping
                mapping = ExternalTaskTypeMapping.objects.filter(
                    integration=integration,
                    external_id=ext_id,
                ).first()

                if mapping:
                    tt = mapping.task_type
                    # Update display fields on the TaskType only if we created it via sync
                    if tt.code == ext_code:
                        tt.name = ext_name or tt.name
                        tt.is_billable = is_billable
                        tt.save(update_fields=['name', 'is_billable'])
                        stats['updated'] += 1
                else:
                    # No mapping yet — try to match by code first
                    tt = TaskType.objects.filter(org=org, code__iexact=ext_code).first()
                    if tt is None and integration.auto_create_internal_records:
                        tt = TaskType.objects.create(
                            org=org,
                            name=ext_name or ext_code or f'Axcess-{ext_id}',
                            code=ext_code[:20],
                            is_billable=is_billable,
                        )
                        stats['created'] += 1
                    elif tt is None:
                        # auto_create disabled and no match — skip
                        logger.info('No TaskType for Axcess code %s; auto-create disabled', ext_code)
                        continue

                    mapping = ExternalTaskTypeMapping.objects.create(
                        integration=integration,
                        task_type=tt,
                        external_id=ext_id,
                        external_code=ext_code,
                        external_name=ext_name,
                        external_category=record.get('category', '')[:64],
                    )

                mapping.external_code = ext_code
                mapping.external_name = ext_name
                mapping.last_synced_at = now
                mapping.last_seen_in_source = now
                mapping.save()

        except Exception as e:
            stats['errors'] += 1
            logger.exception('Error syncing service code %r: %s', record, e)

    return stats


# ============================================================================
# Clients
# ============================================================================

def sync_clients(client: AxcessClient) -> dict:
    """
    Pull clients from Axcess → upsert Client + ExternalClientMapping.

    For new clients, uses Axcess client code as Client.code if available
    (or generates one from the name).
    """
    integration = client.integration
    org = integration.organization
    stats = {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0}

    now = timezone.now()

    for record in client.paginated_get('/clients'):
        try:
            ext_id = str(record.get('id') or record.get('clientId') or '')
            ext_code = (record.get('code') or record.get('clientCode') or '').strip()
            ext_name = (record.get('name') or record.get('clientName') or '').strip()
            ext_status = (record.get('status') or 'active').strip()

            if not ext_id:
                stats['errors'] += 1
                continue

            stats['fetched'] += 1

            with transaction.atomic():
                mapping = ExternalClientMapping.objects.filter(
                    integration=integration,
                    external_id=ext_id,
                ).first()

                if mapping:
                    cl = mapping.client
                    if ext_name and cl.name != ext_name:
                        cl.name = ext_name
                        cl.save(update_fields=['name'])
                    cl.is_active = (ext_status.lower() == 'active')
                    cl.save(update_fields=['is_active'])
                    stats['updated'] += 1
                else:
                    # Try to match by code first if the firm uses matching codes
                    cl = None
                    if ext_code:
                        cl = Client.objects.filter(org=org, code__iexact=ext_code).first()

                    if cl is None and integration.auto_create_internal_records:
                        cl = Client.objects.create(
                            org=org,
                            name=ext_name or f'Axcess-{ext_id}',
                            code=ext_code[:50] if ext_code else '',
                            is_active=(ext_status.lower() == 'active'),
                            imported_from='',  # Existing field; leave blank for axcess (not in choices)
                        )
                        stats['created'] += 1
                    elif cl is None:
                        logger.info('No Client for Axcess id %s; auto-create disabled', ext_id)
                        continue

                    mapping = ExternalClientMapping.objects.create(
                        integration=integration,
                        client=cl,
                        external_id=ext_id,
                        external_code=ext_code,
                        external_name=ext_name,
                        external_status=ext_status,
                    )

                mapping.external_code = ext_code
                mapping.external_name = ext_name
                mapping.external_status = ext_status
                mapping.last_synced_at = now
                mapping.last_seen_in_source = now
                mapping.save()

        except Exception as e:
            stats['errors'] += 1
            logger.exception('Error syncing client %r: %s', record, e)

    return stats


# ============================================================================
# Staff
# ============================================================================

def sync_staff(client: AxcessClient) -> dict:
    """
    Pull staff from Axcess → ExternalStaffMapping.

    Does NOT create new User accounts. Matches by email against existing
    users in the org. Unmatched staff are logged for admin review.
    """
    integration = client.integration
    org = integration.organization
    stats = {'fetched': 0, 'created': 0, 'updated': 0, 'errors': 0}

    now = timezone.now()

    # Build email → User map for this org
    org_users = User.objects.filter(memberships__organization=org).distinct()
    users_by_email = {u.email.lower(): u for u in org_users if u.email}

    for record in client.paginated_get('/staff'):
        try:
            ext_id = str(record.get('id') or record.get('staffId') or '')
            ext_code = (record.get('code') or '').strip()
            ext_name = (record.get('name') or record.get('fullName') or '').strip()
            ext_email = (record.get('email') or '').strip().lower()

            if not ext_id:
                stats['errors'] += 1
                continue

            stats['fetched'] += 1

            # Match by email
            user = users_by_email.get(ext_email) if ext_email else None
            if user is None:
                logger.info(
                    'No user match for Axcess staff %s (email=%s) — skipping',
                    ext_code or ext_id, ext_email or 'n/a',
                )
                continue

            with transaction.atomic():
                mapping, created = ExternalStaffMapping.objects.get_or_create(
                    integration=integration,
                    external_id=ext_id,
                    defaults={
                        'user': user,
                        'external_code': ext_code,
                        'external_name': ext_name,
                        'external_email': ext_email,
                    },
                )
                if created:
                    stats['created'] += 1
                else:
                    mapping.external_code = ext_code
                    mapping.external_name = ext_name
                    mapping.external_email = ext_email
                    stats['updated'] += 1

                mapping.last_synced_at = now
                mapping.last_seen_in_source = now
                mapping.save()

        except Exception as e:
            stats['errors'] += 1
            logger.exception('Error syncing staff %r: %s', record, e)

    return stats


# ============================================================================
# Matrix rules → OrgRoutingRule with source='cch_axcess_sync'
# ============================================================================

def sync_matrix_rules(client: AxcessClient) -> dict:
    """
    Pull matrix rules (which staff/service codes are allowed per client)
    from Axcess → write OrgRoutingRule rows with source='cch_axcess_sync'.

    Strategy:
      1. Delete all existing rules with source='cch_axcess_sync' for this org
         (wipe + recreate; manual rules are untouched).
      2. For each matrix rule in Axcess, create a new OrgRoutingRule with:
           match_type = 'task_type_matrix'
           match_value = JSON: {"client_id": ..., "task_type_id": ..., "user_id": ...}
           action = 'suppress' (forbidden combos) or 'flag_for_review' (advisory)
    """
    import json as _json

    integration = client.integration
    org = integration.organization
    stats = {'fetched': 0, 'created': 0, 'errors': 0}

    # 1. Wipe existing synced rules
    deleted, _ = OrgRoutingRule.objects.filter(
        org=org,
        source='cch_axcess_sync',
        match_type='task_type_matrix',
    ).delete()
    logger.info('Wiped %d existing synced matrix rules for org %s', deleted, org.id)

    # Build external_id → internal_id lookups
    client_ext_to_int = dict(
        ExternalClientMapping.objects.filter(integration=integration)
        .values_list('external_id', 'client_id')
    )
    tt_ext_to_int = dict(
        ExternalTaskTypeMapping.objects.filter(integration=integration)
        .values_list('external_id', 'task_type_id')
    )
    staff_ext_to_int = dict(
        ExternalStaffMapping.objects.filter(integration=integration)
        .values_list('external_id', 'user_id')
    )

    # 2. Pull and write new rules
    for record in client.paginated_get('/matrix-rules'):
        try:
            stats['fetched'] += 1

            ext_client = record.get('clientId')
            ext_tt = record.get('serviceCodeId')
            ext_staff = record.get('staffId')
            allowed = record.get('allowed', True)

            # Resolve external → internal IDs (or "*" wildcard)
            internal_client = '*' if ext_client in (None, '', '*') else client_ext_to_int.get(str(ext_client))
            internal_tt = '*' if ext_tt in (None, '', '*') else tt_ext_to_int.get(str(ext_tt))
            internal_staff = '*' if ext_staff in (None, '', '*') else staff_ext_to_int.get(str(ext_staff))

            # Skip rules where we couldn't resolve an ID (means we don't have
            # the parent record synced yet — they'll be picked up next run).
            if any(v is None for v in (internal_client, internal_tt, internal_staff)):
                logger.warning(
                    'Skipping matrix rule with unresolved IDs: client=%s tt=%s staff=%s',
                    ext_client, ext_tt, ext_staff,
                )
                stats['errors'] += 1
                continue

            match_value = _json.dumps({
                'client_id': internal_client,
                'task_type_id': internal_tt,
                'user_id': internal_staff,
            })

            # Only create rules for FORBIDDEN combos — "allowed" combos are
            # the default. (Axcess matrix is typically allow-list with explicit
            # denies; we model the denies as suppress rules.)
            if allowed:
                continue

            OrgRoutingRule.objects.create(
                org=org,
                match_type='task_type_matrix',
                match_value=match_value,
                action='suppress',
                category='billing',
                runs_at='classifier',
                source='cch_axcess_sync',
                priority=400,  # Above default rules (300), below org-specific hard rules (500)
                enabled=True,
                is_default=False,
                description=f'CCH Axcess matrix: forbidden combo (synced).',
                flag_reason='This combination is not allowed per CCH Axcess matrix.',
            )
            stats['created'] += 1

        except Exception as e:
            stats['errors'] += 1
            logger.exception('Error syncing matrix rule %r: %s', record, e)

    return stats


# ============================================================================
# Celery task wrapper
# ============================================================================

@shared_task(name='tracker.integrations.cch_axcess.sync_axcess_full')
def sync_axcess_full(integration_id: int) -> dict:
    """
    Celery entrypoint. Runs full_sync for a single integration.

    Schedule via celery beat:
        CELERY_BEAT_SCHEDULE = {
            'axcess-nightly-sync': {
                'task': 'tracker.integrations.cch_axcess.sync_axcess_full',
                'schedule': crontab(hour=2, minute=0),
                'args': [<integration_id>],
            },
        }
    """
    try:
        integration = Integration.objects.get(id=integration_id, provider='cch_axcess')
    except Integration.DoesNotExist:
        logger.error('No cch_axcess integration with id=%s', integration_id)
        return {'error': 'integration not found'}

    return full_sync(integration)