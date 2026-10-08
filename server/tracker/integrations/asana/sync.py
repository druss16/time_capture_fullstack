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

from tracker.integrations.asana.client import (
    AsanaAuthError, AsanaClient, AsanaError, AsanaNotAvailable,
)
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
    # The card shows "Syncing…" off this (with the lock — see sync_state).
    integration.last_sync_status = 'running'
    integration.last_sync_error = ''
    integration.save(update_fields=['last_sync_status', 'last_sync_error', 'updated_at'])
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


CLIENT_FIELD_NAMES = {'client', 'customer', 'account', 'client name', 'customer name', 'company'}


def build_matcher(integration):
    """The firm's matcher: its clients and projects, plus every name an
    operator decided in the onboarding link report (AsanaNameMap)."""
    from tracker.integrations.asana.matching import Matcher
    from tracker.models import Client
    from tracker.models_asana import AsanaNameMap
    org = integration.organization
    name_map = {}
    try:
        for m in AsanaNameMap.objects.filter(integration=integration).select_related('client'):
            name_map[m.prefix] = None if m.ignore else m.client
    except Exception as e:                                       # noqa: BLE001
        logger.warning('Asana name map unavailable (%s)', e)    # not migrated yet
    return Matcher(
        Client.objects.filter(org=org, is_active=True)
        .only('id', 'name', 'aliases', 'email', 'alias_sources'),
        Project.objects.filter(org=org).only('id', 'name', 'client_id', 'is_active'),
        name_map=name_map)


def _apply(link, matcher) -> None:
    """Re-decide one link from what is stored on it. A hand link stands."""
    if link.link_source == 'manual':
        return
    project, client, how = matcher.match(link.asana_name, team=getattr(link, 'asana_team', ''),
                                         client_hint=getattr(link, 'client_hint', ''))
    link.project = project
    link.client_id = project.client_id if project else (client.id if client else None)
    link.link_source = how


def relink(integration) -> dict:
    """Every stored Asana project, re-matched with no call to Asana — after an
    operator maps a name, the whole group moves at once."""
    matcher = build_matcher(integration)
    changed = 0
    for link in AsanaProjectLink.objects.filter(integration=integration):
        before = (link.project_id, link.client_id, link.link_source)
        _apply(link, matcher)
        if (link.project_id, link.client_id, link.link_source) != before:
            link.save(update_fields=['project', 'client', 'link_source', 'updated_at'])
            changed += 1
    return {'changed': changed}


def _client_field(row) -> str:
    for f in row.get('custom_fields') or []:
        if (f.get('name') or '').strip().lower() in CLIENT_FIELD_NAMES and f.get('display_value'):
            return str(f['display_value']).strip()
    return ''


def _project_rows(api, workspace):
    """Every project, with its team and custom fields when the app may read
    them (teams:read / custom_fields:read). Without those scopes Asana
    refuses the richer request; the names alone still link."""
    try:
        return list(api.paginated('projects', workspace=workspace, opt_fields=(
            'name,archived,team.name,custom_fields.name,custom_fields.display_value')))
    except AsanaAuthError:
        raise
    except AsanaError as e:
        logger.info('Asana projects without team/custom fields (%s)', e)
        return list(api.paginated('projects', workspace=workspace, opt_fields='name,archived'))


def _sync_projects(integration, api, workspace, stats):
    """Every Asana project in the workspace, linked to its TimeTracker project
    — or to its client alone — by name, team or Client field (see
    matching.py). A link made by hand stands."""
    now = timezone.now()
    matcher = build_matcher(integration)
    stats.setdefault('client_only', 0)
    links = {link.asana_gid: link for link in AsanaProjectLink.objects.filter(integration=integration)}
    rows = _project_rows(api, workspace)
    _progress(integration.id, 'projects', 0, len(rows))
    for n, row in enumerate(rows, 1):
        gid = _gid(row.get('gid'))
        if not gid:
            continue
        stats['seen'] += 1
        link = links.get(gid) or AsanaProjectLink(integration=integration, asana_gid=gid)
        link.asana_name = (row.get('name') or '').strip()[:500]
        link.archived = bool(row.get('archived'))
        link.asana_team = ((row.get('team') or {}).get('name') or '')[:255]
        link.client_hint = _client_field(row)[:255]
        link.last_seen_in_source = now
        _apply(link, matcher)
        if link.client_id and not link.project_id:
            stats['client_only'] += 1
        try:
            with transaction.atomic():
                link.save()
        except IntegrityError:      # a concurrent sync made it first
            link = AsanaProjectLink.objects.get(integration=integration, asana_gid=gid)
        links[gid] = link
        stats['linked' if link.project_id else 'unlinked'] += 1
        if n % 200 == 0:
            _progress(integration.id, 'projects', n, len(rows))


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


# Each run reads project activity for at most this long, oldest-read projects
# first, and leaves a backlog for the next run. Production Celery is eager —
# scheduled tasks run inside the beat process, and a deploy restarts it — so a
# sync that tries to read 800 projects in one go is one that gets killed half
# way. In chunks it always finishes something, and resumes where it stopped.
ACTIVITY_BUDGET_SECONDS = 150


def sync_activity(integration, *, api=None, budget=ACTIVITY_BUDGET_SECONDS) -> dict:
    """The hourly path: stories on tasks of every linked project since each
    project's cursor. Catches what the per-person pass cannot see."""
    import time
    stats = {'projects': 0, 'tasks': 0, 'stories': 0, 'recorded': 0, 'remaining': 0}
    people = _people(integration)
    if not people:
        _backlog(integration.id, False)
        return stats
    api = api or AsanaClient(integration)
    now = timezone.now()
    links = _linked(integration)
    queue = sorted(links.values(), key=lambda l: (l.activity_cursor is not None,
                                                   l.activity_cursor or now))
    started = time.monotonic()
    for n, link in enumerate(queue):
        if budget is not None and time.monotonic() - started > budget:
            stats['remaining'] = len(queue) - n
            break
        if n % 10 == 0:
            _progress(integration.id, 'activity', n, len(queue))
        since = (link.activity_cursor or (now - INITIAL_LOOKBACK)) - CLOCK_SKEW
        stats['projects'] += 1
        try:
            tasks = list(api.paginated('tasks', project=link.asana_gid,
                                       modified_since=since.isoformat(),
                                       opt_fields='name,modified_at'))
        except AsanaNotAvailable:
            tasks = []      # no longer visible to the connected account
        for task in tasks:
            stats['tasks'] += 1
            task['_project_gids'] = [link.asana_gid]
            _record_stories(integration, api, task, links, people, since, stats)
        link.activity_cursor = now
        link.save(update_fields=['activity_cursor', 'updated_at'])
    _backlog(integration.id, stats['remaining'] > 0)
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


def _try_lock(integration_id: int, kind: str = 'full'):
    """A token when this caller holds the lock, else None. With no Redis the
    sync runs unlocked — a duplicate pass is harmless (stories are unique),
    a sync that never runs is not. The token starts with the kind ('full' /
    'activity'), so the card can say a full sync is running."""
    import secrets
    token = f'{kind}:{secrets.token_hex(8)}'
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


def running_kind(integration_id: int):
    """'full' / 'activity' while a sync holds the lock, else None (or None
    when Redis cannot say)."""
    r = _redis()
    try:
        raw = r.get(f'asana:sync-lock:{integration_id}') if r is not None else None
        return raw.decode().split(':', 1)[0] if raw else None
    except Exception:                                            # noqa: BLE001
        return None


def sync_state(integration) -> dict:
    """What the card says about the sync itself.

    A full sync marks the row 'running' when it starts and 'success' /
    'failed' when it ends. 'running' with no full sync holding the lock means
    it died without reaching either — a restart killed the thread, or the
    worker its task ran on — and the card must say so rather than show the
    time of the last sync that finished."""
    syncing = running_kind(integration.id) == 'full'
    status = integration.last_sync_status or ''
    error = integration.last_sync_error or ''
    if status == 'running' and not syncing:
        status = 'failed'
        error = error or ('The last sync stopped before it finished (the server restarted '
                          'mid-sync). Press Sync Asana to run it again.')
    out = {'syncing': syncing, 'last_sync_status': status or None, 'last_sync_error': error or None}
    if syncing:
        out['progress'] = _progress_get(integration.id)
    return out


def _progress(integration_id: int, phase: str, done: int, total: int) -> None:
    """What the card says while syncing: 'Reading activity 120 of 379'."""
    import json
    r = _redis()
    try:
        if r is not None:
            r.set(f'asana:progress:{integration_id}',
                  json.dumps({'phase': phase, 'done': done, 'total': total}), ex=LOCK_TTL)
    except Exception:                                            # noqa: BLE001
        pass


def _progress_get(integration_id: int):
    import json
    r = _redis()
    try:
        raw = r.get(f'asana:progress:{integration_id}') if r is not None else None
        return json.loads(raw) if raw else None
    except Exception:                                            # noqa: BLE001
        return None


def _backlog(integration_id: int, pending: bool = None):
    """Project activity left for the next run. Set: the 5-minute pass works
    it down, a chunk at a time, instead of waiting an hour."""
    r = _redis()
    key = f'asana:backlog:{integration_id}'
    try:
        if r is None:
            return False
        if pending is None:
            return bool(r.get(key))
        if pending:
            r.set(key, '1', ex=24 * 3600)
        else:
            r.delete(key)
        return pending
    except Exception:                                            # noqa: BLE001
        return False


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
    due = (not integration.last_synced_at
           or timezone.now() - integration.last_synced_at >= FULL_SYNC_EVERY
           # Marked running, nobody holding the lock: it died (a deploy
           # restarted the process). Run it again now, not in an hour.
           or (integration.last_sync_status == 'running' and running_kind(integration.id) is None))
    token = _try_lock(integration.id, 'full' if (full or due) else 'activity')
    if not token:
        return {'skipped': 'already_running'}
    try:
        if full or due:
            return full_sync(integration)
        try:
            out = {'activity': sync_people_activity(integration)}
            if _backlog(integration.id):
                out['backlog'] = sync_activity(integration)
            return out
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
