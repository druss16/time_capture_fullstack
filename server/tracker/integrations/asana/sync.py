"""
Asana sync: link Asana projects and people to TimeTracker's, then read what
people did in Asana and when. Read-only toward Asana; never creates a Client
or a Project here (see models_asana.py for why).

    full_sync(integration)       projects + people + activity
    sync_activity(integration)   activity only — the every-few-minutes path

Activity is Asana "stories": every comment, edit, assignment and completion on
a task, stamped with who and when. Asana cannot list "everything Alannah did
today" on a free workspace (task search is a paid feature), so it is read per
linked project: the tasks modified since the last pass, then each one's
stories since then.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tracker.integrations.asana.client import AsanaClient, AsanaError, AsanaNotAvailable
from tracker.models import Integration, OrganizationMembership, Project
from tracker.models_asana import AsanaActivity, AsanaProjectLink
from tracker.models_task_type_sets import ExternalStaffMapping

logger = logging.getLogger(__name__)

# First pass reads this far back; later passes start at the project's cursor.
INITIAL_LOOKBACK = timedelta(days=2)
# Their clock and ours are not the same clock, and a story can be written a
# moment after its task's modified_at. Re-reading a little is free (stories
# are unique per integration); missing one is not.
CLOCK_SKEW = timedelta(minutes=2)
# A full sync (projects + people) at most this often; activity every pass.
FULL_SYNC_EVERY = timedelta(minutes=60)


def _gid(value) -> str:
    return str(value or '').strip()


def full_sync(integration: Integration, *, api=None) -> dict:
    stats = {'projects': {'seen': 0, 'linked': 0, 'unlinked': 0, 'ambiguous': 0},
             'staff': {'matched': 0, 'unmatched': 0},
             'activity': {}, 'errors': []}
    started = timezone.now()
    try:
        api = api or AsanaClient(integration)
        workspace = _workspace(integration, api)
        _sync_projects(integration, api, workspace, stats['projects'])
        stats['staff'] = _sync_staff(integration, api, workspace)
        stats['activity'] = sync_activity(integration, api=api)
        stats['people_activity'] = sync_people_activity(integration, api=api)
        integration.last_synced_at = started
        integration.last_sync_status = 'success'
        integration.last_sync_error = ''
        integration.save(update_fields=['last_synced_at', 'last_sync_status',
                                        'last_sync_error', 'updated_at'])
    except Exception as e:
        # Broad on purpose: on a worker an unrecorded failure is a card that
        # says "Connected" while nothing ever arrives.
        integration.last_sync_status = 'failed'
        integration.last_sync_error = f'{type(e).__name__}: {e}'[:500]
        integration.save(update_fields=['last_sync_status', 'last_sync_error', 'updated_at'])
        stats['errors'].append(str(e))
        logger.exception('Asana sync failed for integration %s', integration.id)
    return stats


def _workspace(integration, api) -> str:
    """The workspace this firm works in. Stored in tenant_id once chosen.

    A person can belong to several (a personal one alongside the firm's). The
    firm's is the one that is an organization, else the one with the most
    projects visible to the connected account.
    """
    if integration.tenant_id:
        return integration.tenant_id
    spaces = list(api.paginated('workspaces', opt_fields='name,is_organization'))
    if not spaces:
        raise AsanaError('The connected Asana account belongs to no workspace.')
    orgs = [w for w in spaces if w.get('is_organization')]
    candidates = orgs or spaces
    if len(candidates) > 1:
        def project_count(w):
            try:
                return sum(1 for _ in api.paginated('projects', workspace=_gid(w.get('gid')),
                                                    opt_fields='gid'))
            except AsanaError:
                return 0
        candidates = sorted(candidates, key=project_count, reverse=True)
    integration.tenant_id = _gid(candidates[0].get('gid'))[:100]
    integration.save(update_fields=['tenant_id', 'updated_at'])
    return integration.tenant_id


def _sync_projects(integration, api, workspace, stats):
    """Every Asana project in the workspace, linked to its TimeTracker project
    — or to its client alone — by name (see matching.py). A link made by hand
    stands."""
    from tracker.integrations.asana.matching import Matcher
    from tracker.models import Client
    org = integration.organization
    now = timezone.now()
    matcher = Matcher(
        Client.objects.filter(org=org, is_active=True)
        .only('id', 'name', 'aliases', 'email', 'alias_sources'),
        Project.objects.filter(org=org).only('id', 'name', 'client_id', 'is_active'))
    stats.setdefault('client_only', 0)
    links = {link.asana_gid: link for link in AsanaProjectLink.objects.filter(integration=integration)}

    for row in api.paginated('projects', workspace=workspace, opt_fields='name,archived'):
        gid = _gid(row.get('gid'))
        if not gid:
            continue
        stats['seen'] += 1
        name = (row.get('name') or '').strip()
        link = links.get(gid) or AsanaProjectLink(integration=integration, asana_gid=gid)
        link.asana_name = name[:500]
        link.archived = bool(row.get('archived'))
        link.last_seen_in_source = now
        if link.link_source != 'manual':
            project, client, how = matcher.match(name)
            link.project = project
            link.client_id = project.client_id if project else (client.id if client else None)
            link.link_source = how
        if link.client_id and not link.project_id:
            stats['client_only'] += 1
        try:
            with transaction.atomic():
                link.save()
        except IntegrityError:      # a concurrent sync made it first
            link = AsanaProjectLink.objects.get(integration=integration, asana_gid=gid)
        links[gid] = link
        stats['linked' if link.project_id else 'unlinked'] += 1


def _sync_staff(integration, api, workspace) -> dict:
    """Asana user ↔ TimeTracker member, by email, else a full name exactly one
    member has. Never creates a user; a hand-made link stands."""
    stats = {'matched': 0, 'unmatched': 0}
    members = [m.user for m in OrganizationMembership.objects
               .filter(organization=integration.organization).select_related('user')]
    by_email = {u.email.strip().lower(): u for u in members if u.email}
    by_name = {}
    for u in members:
        full = ' '.join((u.get_full_name() or '').lower().split())
        if full:
            by_name.setdefault(full, []).append(u)
    existing = {m.external_id: m for m in ExternalStaffMapping.objects.filter(integration=integration)}
    linked = {m.user_id: m.external_id for m in existing.values()}
    now = timezone.now()

    for row in api.paginated('users', workspace=workspace, opt_fields='name,email'):
        ext = _gid(row.get('gid'))
        if not ext:
            continue
        email = (row.get('email') or '').strip().lower()
        name = (row.get('name') or '').strip()
        mapping = existing.get(ext)
        user = by_email.get(email) if email else None
        if user is None and mapping is not None:
            user = mapping.user
        if user is None:
            same = by_name.get(' '.join(name.lower().split()), [])
            user = same[0] if len(same) == 1 else None
        if user is None or linked.get(user.id, ext) != ext:
            stats['unmatched'] += 1
            continue
        mapping = mapping or ExternalStaffMapping(integration=integration, external_id=ext, user=user)
        mapping.user = user
        mapping.external_name = name[:255]
        mapping.external_email = email[:254]
        mapping.last_synced_at = mapping.last_seen_in_source = now
        mapping.save()
        existing[ext] = mapping
        linked[user.id] = ext
        stats['matched'] += 1
    return stats


def _record_stories(integration, api, task, links_by_gid, people, since, stats):
    """Stories on one task by a linked person since `since`, filed under the
    first linked Asana project the task belongs to."""
    tgid = _gid(task.get('gid'))
    link = next((links_by_gid[g] for g in task.get('_project_gids', ()) if g in links_by_gid), None)
    if link is None:
        return
    try:
        stories = api.paginated(f'tasks/{tgid}/stories',
                                opt_fields='created_at,created_by,resource_subtype')
        for story in stories:
            stats['stories'] += 1
            at = parse_datetime(story.get('created_at') or '')
            who = people.get(_gid((story.get('created_by') or {}).get('gid')))
            if not at or at < since or who is None:
                continue
            _, made = AsanaActivity.objects.get_or_create(
                integration=integration, story_gid=_gid(story.get('gid')),
                defaults=dict(user_id=who, at=at, asana_project_gid=link.asana_gid,
                              project_id=link.project_id, client_id=link.client_id,
                              task_gid=tgid, task_name=(task.get('name') or '')[:500],
                              kind=(story.get('resource_subtype') or '')[:64]))
            stats['recorded'] += int(made)
    except AsanaNotAvailable:
        pass


def _linked(integration):
    from django.db.models import Q
    return {link.asana_gid: link for link in AsanaProjectLink.objects
            .filter(integration=integration, archived=False)
            .filter(Q(project__isnull=False) | Q(client__isnull=False))}


def _people(integration):
    """Asana user gid -> TimeTracker user id, for the firm's active members."""
    return dict(ExternalStaffMapping.objects.filter(integration=integration, user__is_active=True)
                .values_list('external_id', 'user_id'))


def sync_people_activity(integration, *, api=None) -> dict:
    """The every-5-minutes path: per linked PERSON, the tasks assigned to them
    that changed since the last pass, and their stories.

    One or two requests per person — a firm with one TimeTracker user asks
    Asana once — where reading every linked project was hundreds per pass and
    ran into Asana's per-minute limit. Its blind spot (a comment on a task
    assigned to someone else) is covered hourly by sync_activity."""
    stats = {'people': 0, 'tasks': 0, 'stories': 0, 'recorded': 0}
    people = _people(integration)
    workspace = integration.tenant_id
    if not people or not workspace:
        return stats
    api = api or AsanaClient(integration)
    links = _linked(integration)
    now = timezone.now()
    cursor_key = f'asana:people-cursor:{integration.id}'
    since = (_cursor_get(cursor_key) or (now - INITIAL_LOOKBACK)) - CLOCK_SKEW
    for asana_gid in people:
        stats['people'] += 1
        try:
            tasks = api.paginated('tasks', assignee=asana_gid, workspace=workspace,
                                  modified_since=since.isoformat(),
                                  opt_fields='name,modified_at,memberships.project')
            for task in tasks:
                stats['tasks'] += 1
                task['_project_gids'] = [_gid(((m or {}).get('project') or {}).get('gid'))
                                         for m in task.get('memberships') or []]
                _record_stories(integration, api, task, links, people, since, stats)
        except AsanaNotAvailable:
            continue
    _cursor_set(cursor_key, now)
    return stats


def sync_activity(integration, *, api=None) -> dict:
    """The hourly path: stories on tasks of every linked project since each
    project's cursor. Catches what the per-person pass cannot see."""
    stats = {'projects': 0, 'tasks': 0, 'stories': 0, 'recorded': 0}
    people = _people(integration)
    if not people:
        return stats
    api = api or AsanaClient(integration)
    now = timezone.now()
    links = _linked(integration)
    for link in links.values():
        since = (link.activity_cursor or (now - INITIAL_LOOKBACK)) - CLOCK_SKEW
        stats['projects'] += 1
        try:
            tasks = list(api.paginated('tasks', project=link.asana_gid,
                                       modified_since=since.isoformat(),
                                       opt_fields='name,modified_at'))
        except AsanaNotAvailable:
            continue        # no longer visible to the connected account
        for task in tasks:
            stats['tasks'] += 1
            task['_project_gids'] = [link.asana_gid]
            _record_stories(integration, api, task, links, people, since, stats)
        link.activity_cursor = now
        link.save(update_fields=['activity_cursor', 'updated_at'])
    return stats


# ============================================================================
# Celery
# ============================================================================

# The sync's lock lives in Redis with an expiry. It was a Postgres advisory
# lock, which belongs to one database session — and production reaches Neon
# through its pooler, which can run the lock and the unlock on different
# server sessions. The unlock then misses, and the lock stays held by a pooled
# session for good: from More Than Cars' first sync (2026-10-08) every later
# one, the 5-minute passes included, came back "already running". Expiring
# means a lost release blocks syncing for at most LOCK_TTL, never forever.
# Not Django's cache: it is per-process here, so the web thread and the
# worker would each have held their own "lock".
LOCK_TTL = 30 * 60


def _redis():
    try:
        import redis
        from django.conf import settings
        return redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=5)
    except Exception as e:                                       # noqa: BLE001
        logger.warning('Asana sync lock: Redis unavailable (%s)', e)
        return None


def _try_lock(integration_id: int):
    """A token when this caller holds the lock, else None. With no Redis the
    sync runs unlocked — a duplicate pass is harmless (stories are unique),
    a sync that never runs is not."""
    import secrets
    token = secrets.token_hex(8)
    r = _redis()
    if r is None:
        return token
    try:
        return token if r.set(f'asana:sync-lock:{integration_id}', token, nx=True, ex=LOCK_TTL) else None
    except Exception as e:                                       # noqa: BLE001
        logger.warning('Asana sync lock unavailable (%s); running unlocked', e)
        return token


def _unlock(integration_id: int, token) -> None:
    r = _redis()
    if r is None or not token:
        return
    key = f'asana:sync-lock:{integration_id}'
    try:
        if (r.get(key) or b'').decode() == token:     # never release someone else's
            r.delete(key)
    except Exception as e:                                       # noqa: BLE001
        logger.warning('Asana sync unlock failed (%s); it expires on its own', e)


def _cursor_get(key):
    r = _redis()
    try:
        raw = r.get(key) if r is not None else None
        return parse_datetime(raw.decode()) if raw else None
    except Exception:                                            # noqa: BLE001
        return None


def _cursor_set(key, when) -> None:
    r = _redis()
    try:
        if r is not None:
            r.set(key, when.isoformat(), ex=7 * 24 * 3600)
    except Exception:                                            # noqa: BLE001
        pass


def run_sync(integration_id: int, *, full: bool = False) -> dict:
    """One firm's sync under its lock: full when asked or due, else activity."""
    try:
        integration = Integration.objects.select_related('organization').get(
            id=integration_id, provider='asana', is_connected=True)
    except Integration.DoesNotExist:
        return {'error': 'integration_not_found'}
    token = _try_lock(integration.id)
    if not token:
        return {'skipped': 'already_running'}
    try:
        due = (not integration.last_synced_at
               or timezone.now() - integration.last_synced_at >= FULL_SYNC_EVERY)
        if full or due:
            return full_sync(integration)
        try:
            return {'activity': sync_people_activity(integration)}
        except Exception as e:
            logger.warning('Asana activity sync failed for integration %s: %s',
                           integration.id, e, exc_info=True)
            return {'error': str(e)[:200]}
    finally:
        _unlock(integration.id, token)


# CELERY_TASK_TIME_LIMIT is 3 minutes; a full sync of a 3,000-project
# workspace runs past it, and a task killed mid-sync is how a lock is left.
@shared_task(name='tracker.sync_asana_full', time_limit=25 * 60, soft_time_limit=24 * 60)
def sync_asana_full(integration_id: int) -> dict:
    return run_sync(integration_id, full=True)


@shared_task(name='tracker.sync_all_asana', time_limit=25 * 60, soft_time_limit=24 * 60)
def sync_all_asana() -> dict:
    """Every few minutes: each connected firm's activity, and a full sync when
    one is due. Activity has to be fresh for the 2-minute attribution sweep to
    file a block while its person still remembers it."""
    done = 0
    for integration_id in Integration.objects.filter(
            provider='asana', is_connected=True).values_list('id', flat=True):
        run_sync(integration_id)
        done += 1
    return {'integrations': done}
