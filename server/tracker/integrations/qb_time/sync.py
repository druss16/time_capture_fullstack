"""
QuickBooks Time → Client / Project sync, for agencies.

WHY QUICKBOOKS TIME
-------------------
An agency that records its hours in QuickBooks Time already keeps its
Customer → Project list there, because nobody can clock a minute without
choosing one. That list is guaranteed current in a way a project tool or a
spreadsheet is not, and for firms on the Projects feature it also carries the
hours estimate each project is priced from.

THE SHAPE
---------
QuickBooks Time models work as a tree of JOBCODES:

    Ford Dealers               ← top-level jobcode            → Client
      └─ Spring Launch         ← child jobcode                → Project
           └─ Storyboards      ← grandchild (a task)          → ignored

Firms on the Projects feature also have PROJECT records, each pointing at its
jobcode (`jobcode_id`) and its customer (`parent_jobcode_id`), with a status,
dates and ESTIMATES (estimate → items → `estimated_seconds`). Where one exists
it decides that the jobcode is a project, whatever its depth, and supplies the
estimate. Where none exists, the second level of the tree is the project list.

WHAT IT DOES NOT DO
-------------------
  · Rename a Client. The mapping is the identity; the firm may have named
    the client its own way, and aliases were built against that name.
  · Create a Client for a top-level jobcode with no projects and no QuickBooks
    link — those are overhead codes ("Admin", "Training"), not customers.
  · Create users. QuickBooks Time users are matched to TimeTracker members by
    email so later steps (team narrowing, pushing time) can name them.

IDEMPOTENT — keyed on (integration, jobcode id), safe to re-run.
"""
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from tracker.integrations.qb_time.client import (
    QBTimeClient, QBTimeError, QBTimeNotAvailable,
)
from tracker.models import Client, Integration, OrganizationMembership, Project
from tracker.models_task_type_sets import (
    ExternalClientMapping, ExternalMatterMapping, ExternalStaffMapping,
)

logger = logging.getLogger(__name__)

# A completed project takes no new time, same as a closed matter.
CLOSED_PROJECT_STATUSES = {'complete', 'completed'}


def _norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (name or '').lower()).strip()


def _id(value) -> str:
    return str(value or '').strip() if value not in (None, 0, '0') else ''


def _date(value):
    raw = str(value or '')[:10]
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date() if raw else None
    except ValueError:
        return None


# ============================================================================
# Pure planning — what the tree says, with no database
# ============================================================================

def plan_tree(jobcodes: list, projects: list) -> dict:
    """
    Decide which jobcodes are customers and which are projects.

    Returns {
      'customers': {jobcode_id: jobcode},          # top-level, regular
      'projects':  {jobcode_id: (customer_id, jobcode, project_record|None)},
      'skipped_tasks': int,                         # deeper jobcodes, no project record
    }
    """
    by_id = {}
    for jc in jobcodes:
        jid = _id(jc.get('id'))
        if jid and (jc.get('type') or 'regular') == 'regular':
            by_id[jid] = jc

    def top_of(jid):
        seen = set()
        while jid and jid in by_id and jid not in seen:
            seen.add(jid)
            parent = _id(by_id[jid].get('parent_id'))
            if not parent:
                return jid
            jid = parent
        return None

    customers = {jid: jc for jid, jc in by_id.items() if not _id(jc.get('parent_id'))}
    project_by_jobcode = {_id(p.get('jobcode_id')): p for p in projects if _id(p.get('jobcode_id'))}

    planned = {}
    skipped_tasks = 0
    for jid, jc in by_id.items():
        if jid in customers:
            continue
        record = project_by_jobcode.get(jid)
        parent = _id(jc.get('parent_id'))
        if record is not None:
            customer = _id(record.get('parent_jobcode_id')) or top_of(jid)
            customer = top_of(customer) if customer else None
        elif parent in customers:
            customer = parent
        else:
            skipped_tasks += 1
            continue
        if customer and customer in customers:
            planned[jid] = (customer, jc, record)
        else:
            skipped_tasks += 1

    return {'customers': customers, 'projects': planned, 'skipped_tasks': skipped_tasks}


def estimate_hours_by_project(estimates: list, items: list) -> dict:
    """QB Time project id -> estimated hours, from active estimates' active items."""
    estimate_project = {
        _id(e.get('id')): _id(e.get('project_id'))
        for e in estimates if e.get('active', True) and _id(e.get('id'))
    }
    seconds = defaultdict(int)
    for item in items:
        if not item.get('active', True):
            continue
        project = estimate_project.get(_id(item.get('estimate_id')))
        if project:
            seconds[project] += int(item.get('estimated_seconds') or 0)
    return {pid: (Decimal(s) / Decimal(3600)).quantize(Decimal('0.01'))
            for pid, s in seconds.items() if s > 0}


# ============================================================================
# Orchestration
# ============================================================================

def full_sync(integration: Integration, *, api=None) -> dict:
    stats = {
        'clients': {'created': 0, 'matched': 0, 'skipped': 0},
        'projects': {'fetched': 0, 'created': 0, 'updated': 0, 'closed': 0, 'tasks_ignored': 0},
        'estimates': {'available': False, 'projects_with_estimate': 0},
        'staff': {'matched': 0, 'unmatched': 0},
        'errors': [],
    }
    try:
        api = api or QBTimeClient(integration)
        jobcodes = list(api.paginated('jobcodes', active='both'))

        # Projects + estimates are a paid feature. Its absence is a normal
        # account, not a failed sync.
        project_records, estimates, items = [], [], []
        try:
            project_records = list(api.paginated('projects', active='both'))
            estimates = list(api.paginated('estimates'))
            items = list(api.paginated('estimate_items'))
            stats['estimates']['available'] = True
        except QBTimeNotAvailable as e:
            logger.info('QB Time projects/estimates unavailable for org %s: %s',
                        integration.organization_id, e)

        plan = plan_tree(jobcodes, project_records)
        hours = estimate_hours_by_project(estimates, items)
        stats['projects']['tasks_ignored'] = plan['skipped_tasks']

        clients = _sync_clients(integration, plan, stats['clients'])
        _sync_projects(integration, plan, clients, hours, stats)

        try:
            stats['staff'] = _sync_staff(integration, list(api.paginated('users', active='both')))
        except QBTimeError as e:
            logger.warning('QB Time user sync failed for org %s: %s', integration.organization_id, e)

        if stats['clients']['created']:
            try:
                from tracker.views_integrations import run_post_import_alias_derivation
                run_post_import_alias_derivation(integration.organization)
            except Exception as e:
                logger.warning('QB Time alias derivation failed: %s', e, exc_info=True)

        try:
            from tracker.services.matter_attribution import attribute_matters_for_org
            stats['attribution'] = attribute_matters_for_org(integration.organization)
        except Exception as e:
            logger.warning('Attribution after QB Time sync failed: %s', e, exc_info=True)
            stats['attribution'] = {'error': str(e)[:200]}

        integration.last_synced_at = timezone.now()
        integration.last_sync_status = 'success'
        integration.last_sync_error = ''
        integration.save(update_fields=[
            'last_synced_at', 'last_sync_status', 'last_sync_error', 'updated_at',
        ])
    except Exception as e:
        # Broad on purpose: this also runs on a worker, where an unrecorded
        # failure is a card that says "Connected" while nothing ever arrives.
        integration.last_sync_status = 'failed'
        integration.last_sync_error = f'{type(e).__name__}: {e}'[:500]
        integration.save(update_fields=['last_sync_status', 'last_sync_error', 'updated_at'])
        stats['errors'].append(str(e))
        logger.exception('QB Time sync failed for integration %s', integration.id)
    return stats


def _sync_clients(integration, plan, stats) -> dict:
    """customer jobcode id -> Client."""
    org = integration.organization
    now = timezone.now()
    mappings = {m.external_id: m for m in
                ExternalClientMapping.objects.filter(integration=integration).select_related('client')}
    by_name = {}
    for c in Client.objects.filter(org=org):
        by_name.setdefault(_norm(c.name), c)

    has_projects = {customer for customer, _jc, _r in plan['projects'].values()}
    out = {}
    for jid, jc in plan['customers'].items():
        name = (jc.get('name') or '').strip()
        mapping = mappings.get(jid)
        if mapping:
            client = mapping.client
            stats['matched'] += 1
        else:
            client = by_name.get(_norm(name))
            if client is None:
                worth_a_client = jid in has_projects or bool(jc.get('connect_with_quickbooks'))
                if not name or not worth_a_client or not integration.auto_create_internal_records:
                    stats['skipped'] += 1
                    continue
                client = Client.objects.create(org=org, name=name[:200], is_active=True,
                                               imported_from='qb_time')
                by_name[_norm(name)] = client
                stats['created'] += 1
            else:
                stats['matched'] += 1
            mapping = ExternalClientMapping.objects.create(
                integration=integration, client=client, external_id=jid)
            mappings[jid] = mapping
        mapping.external_name = name[:255]
        mapping.external_code = str(jc.get('short_code') or '')[:64]
        mapping.external_status = 'active' if jc.get('active', True) else 'inactive'
        mapping.last_synced_at = mapping.last_seen_in_source = now
        mapping.save(update_fields=['external_name', 'external_code', 'external_status',
                                    'last_synced_at', 'last_seen_in_source', 'updated_at'])
        out[jid] = client
    return out


def _sync_projects(integration, plan, clients, hours, stats):
    org = integration.organization
    now = timezone.now()
    s = stats['projects']
    mappings = {m.external_id: m for m in
                ExternalMatterMapping.objects.filter(integration=integration).select_related('project')}
    seen = set()

    for jid, (customer, jc, record) in plan['projects'].items():
        client = clients.get(customer)
        if client is None:
            continue
        s['fetched'] += 1
        seen.add(jid)
        name = ((record or {}).get('name') or jc.get('name') or '').strip()[:200]
        if not name:
            continue
        status = str((record or {}).get('status') or '').lower()
        live = bool(jc.get('active', True)) and status not in CLOSED_PROJECT_STATUSES
        if record is not None and record.get('active') is False:
            live = False

        with transaction.atomic():
            mapping = mappings.get(jid)
            if mapping:
                project = mapping.project
                changed = []
                if project.name != name and not Project.objects.filter(
                        org=org, client=client, name=name).exclude(id=project.id).exists():
                    project.name = name
                    changed.append('name')
                if project.client_id != client.id:
                    project.client = client
                    changed.append('client')
                if project.is_active != live:
                    project.is_active = live
                    changed.append('is_active')
                if changed:
                    project.save(update_fields=changed)
                s['updated'] += 1
            else:
                if not integration.auto_create_internal_records:
                    continue
                # Adopts a project someone already created here by hand (step-1
                # inline creation) instead of making a twin.
                project = (Project.objects.filter(org=org, client=client, name__iexact=name).first()
                           or Project.objects.create(org=org, client=client, name=name, is_active=live))
                if project.is_active != live:
                    project.is_active = live
                    project.save(update_fields=['is_active'])
                mapping = ExternalMatterMapping.objects.create(
                    integration=integration, project=project, external_id=jid)
                mappings[jid] = mapping
                s['created'] += 1

            qbt_project_id = _id((record or {}).get('id'))
            est = hours.get(qbt_project_id) if qbt_project_id else None
            if est is not None:
                stats['estimates']['projects_with_estimate'] += 1
            # display_number stays blank: agency projects are known by name,
            # and the name tier of attribution only reads number-less rows.
            mapping.display_number = ''
            mapping.external_name = name[:500]
            mapping.external_status = 'open' if live else 'closed'
            mapping.estimated_hours = est
            mapping.open_date = _date((record or {}).get('start_date'))
            mapping.due_date = _date((record or {}).get('due_date'))
            mapping.last_synced_at = mapping.last_seen_in_source = now
            mapping.save(update_fields=[
                'display_number', 'external_name', 'external_status', 'estimated_hours',
                'open_date', 'due_date', 'last_synced_at', 'last_seen_in_source', 'updated_at',
            ])

    # Gone from QuickBooks Time entirely (deleted, or its customer was): it
    # takes no new time. The Project stays, because time already filed to it
    # is part of the record.
    for jid, mapping in mappings.items():
        if jid in seen or mapping.external_status == 'closed':
            continue
        mapping.external_status = 'closed'
        mapping.save(update_fields=['external_status', 'updated_at'])
        if mapping.project.is_active:
            mapping.project.is_active = False
            mapping.project.save(update_fields=['is_active'])
        s['closed'] += 1


def _sync_staff(integration, users: list) -> dict:
    """QB Time user ↔ TimeTracker member, by email only. Never creates a user."""
    stats = {'matched': 0, 'unmatched': 0}
    members = {m.user.email.strip().lower(): m.user for m in
               OrganizationMembership.objects.filter(organization=integration.organization)
               .select_related('user') if m.user.email}
    now = timezone.now()
    for u in users:
        ext = _id(u.get('id'))
        email = str(u.get('email') or '').strip().lower()
        user = members.get(email) if email else None
        if not ext or user is None:
            stats['unmatched'] += 1
            continue
        mapping, _ = ExternalStaffMapping.objects.get_or_create(
            integration=integration, external_id=ext, defaults={'user': user})
        mapping.user = user
        mapping.external_name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()[:255]
        mapping.external_email = email[:254]
        mapping.last_synced_at = mapping.last_seen_in_source = now
        mapping.save(update_fields=['user', 'external_name', 'external_email',
                                    'last_synced_at', 'last_seen_in_source', 'updated_at'])
        stats['matched'] += 1
    return stats


# ============================================================================
# Celery
# ============================================================================

@shared_task(name='tracker.sync_qb_time_full')
def sync_qb_time_full(integration_id: int) -> dict:
    try:
        integration = Integration.objects.select_related('organization').get(
            id=integration_id, provider='qb_time')
    except Integration.DoesNotExist:
        return {'error': 'integration_not_found'}
    return full_sync(integration)


@shared_task(name='tracker.sync_all_qb_time_orgs')
def sync_all_qb_time_orgs(min_age_minutes: int = 45) -> dict:
    """Hourly: keep every connected firm's project list current.

    QuickBooks Time has no webhooks for jobcodes, so this sweep IS the live
    path — a project created at 10:05 is selectable by about 11:05, or at once
    if someone presses Sync.
    """
    cutoff = timezone.now() - timedelta(minutes=min_age_minutes)
    queued = skipped = 0
    for integration in Integration.objects.filter(provider='qb_time', is_connected=True) \
            .only('id', 'last_synced_at'):
        if integration.last_synced_at and integration.last_synced_at > cutoff:
            skipped += 1
            continue
        sync_qb_time_full.delay(integration.id)
        queued += 1
    return {'queued': queued, 'skipped': skipped}
