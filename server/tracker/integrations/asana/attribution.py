"""
Which project — or at least which client — a block of Asana time belongs to,
from what Asana knows.

Two signals, strongest first:

  1. url — a browser tab on app.asana.com carries the Asana project's id, in
     both address styles ("/0/<project>/<task>" and "/1/<ws>/project/<id>/…").
     A linked Asana project names itself; nothing is inferred.
  2. activity — the Asana desktop app is titled "Asana" whatever is open, so
     there the evidence is what the person did in Asana during the block:
     comments, edits, completions (AsanaActivity). Everything they touched in
     one project: that project. In several projects of one client: that
     client. Nothing touched, or several clients: it abstains — the block
     still asks.

An Asana project linked only to a client (its name says whose work it is but
no project of that client fits — see matching.py) gives the client alone.
"""
import logging
import re
from collections import defaultdict
from datetime import timedelta

logger = logging.getLogger(__name__)

# A story is stamped when it is saved; the window it belongs to may have
# closed a moment earlier (the block ends on the last keystroke).
ACTIVITY_SLACK = timedelta(minutes=2)

_URL_PROJECT = re.compile(
    r'app\.asana\.com/(?:0/(\d{6,})(?:/|$)|\d+/\d+/project/(\d{6,}))', re.I)


def is_asana_block(block) -> bool:
    app = (getattr(block, 'app_name', '') or '').lower()
    url = (getattr(block, 'url', '') or '').lower()
    title = (getattr(block, 'window_title', '') or getattr(block, 'title', '') or '').strip().lower()
    return ('asana' in app or 'app.asana.com' in url
            or title == 'asana' or title.endswith(' - asana'))


def project_gid_in_url(url: str) -> str:
    m = _URL_PROJECT.search(url or '')
    return (m.group(1) or m.group(2)) if m else ''


def load_context(org, since):
    """{'links': gid -> (project_id, client_id), 'activity': user_id ->
    [(at, project_id, client_id)]}, or None when the firm has no Asana
    connection — or the tables do not exist yet (code ships before its
    migration runs)."""
    try:
        from tracker.models import Integration, Project
        from tracker.models_asana import AsanaActivity, AsanaProjectLink
        integ = Integration.objects.filter(organization=org, provider='asana').first()
        if integ is None:
            return None
        rows = (AsanaProjectLink.objects.filter(integration=integ)
                .exclude(project__isnull=True, client__isnull=True)
                .values_list('asana_gid', 'project_id', 'client_id'))
        project_client = {}
        links = {}
        for gid, pid, cid in rows:
            links[gid] = (pid, cid)
        activity = defaultdict(list)
        for user_id, at, pid, cid in (AsanaActivity.objects
                                      .filter(integration=integ, at__gte=since - ACTIVITY_SLACK)
                                      .exclude(project__isnull=True, client__isnull=True)
                                      .values_list('user_id', 'at', 'project_id', 'client_id')):
            activity[user_id].append((at, pid, cid))
        if not links and not activity:
            return None
        ids = {p for p, _ in links.values() if p} | {p for rows in activity.values() for _, p, _ in rows if p}
        project_client = dict(Project.objects.filter(id__in=ids).values_list('id', 'client_id'))
        return {'links': links, 'activity': activity, 'client_of': project_client}
    except Exception as e:
        logger.warning('Asana attribution context unavailable for org %s: %s', org.id, e)
        return None


def project_for(block, ctx):
    """(project_id or None, client_id or None, tier) or (None, None, None).

    tier: 'asana_url' / 'asana_activity' with a project, or
    'asana_url_client' / 'asana_activity_client' with the client alone."""
    if not ctx or not is_asana_block(block):
        return None, None, None

    def resolve(pid, cid):
        return pid, (ctx['client_of'].get(pid) if pid else None) or cid

    gid = project_gid_in_url(getattr(block, 'url', '') or '')
    if gid and gid in ctx['links']:
        pid, cid = resolve(*ctx['links'][gid])
        return pid, cid, 'asana_url' if pid else 'asana_url_client'
    if not (block.start and block.end):
        return None, None, None
    lo, hi = block.start - ACTIVITY_SLACK, block.end + ACTIVITY_SLACK
    touched = [resolve(p, c) for at, p, c in ctx['activity'].get(block.user_id, ()) if lo <= at <= hi]
    if not touched:
        return None, None, None
    projects = {p for p, _ in touched}
    clients = {c for _, c in touched}
    if len(clients) != 1 or None in clients:
        return None, None, None
    client = next(iter(clients))
    if len(projects) == 1 and None not in projects:
        return next(iter(projects)), client, 'asana_activity'
    return None, client, 'asana_activity_client'


# What a story's resource_subtype says the person did, as a past-tense verb
# phrase. Anything unlisted reads as "updated".
_DID = {
    'comment_added': 'commented on',
    'marked_complete': 'completed',
    'marked_incomplete': 'reopened',
    'assigned': 'assigned',
    'unassigned': 'unassigned',
    'due_date_changed': 'changed the due date on',
    'dependency_due_date_changed': 'changed the due date on',
    'start_date_changed': 'changed the start date on',
    'name_changed': 'renamed',
    'notes_changed': 'edited',
    'attachment_added': 'attached a file to',
    'added_to_project': 'added',
    'section_changed': 'moved',
    'enum_custom_field_changed': 'updated',
    'liked': 'liked',
}


def explain(block, org):
    """What the firm's Asana says about this block, read straight from the
    database — for the classifier (one block at a time) and the Daily Review
    "why" line. Same rules as project_for; adds the words.

    {'project_id', 'client_id', 'tier', 'reason', 'task_name', 'count'} or None.

    A block with no Asana action of its own — reading, not changing — is
    named by the actions either side of it (tier 'asana_between'), see
    _bracket.
    """
    if not is_asana_block(block) or org is None:
        return None
    try:
        from tracker.models import Client, Integration, Project
        from tracker.models_asana import AsanaActivity, AsanaProjectLink
        integ = Integration.objects.filter(organization=org, provider='asana').first()
        if integ is None:
            return None

        def resolve(pid, cid):
            if pid:
                cid = Project.objects.filter(id=pid).values_list('client_id', flat=True).first() or cid
            return pid, cid

        def name_of(cid):
            return Client.objects.filter(id=cid).values_list('name', flat=True).first() or ''

        gid = project_gid_in_url(getattr(block, 'url', '') or '')
        if gid:
            link = (AsanaProjectLink.objects.filter(integration=integ, asana_gid=gid)
                    .exclude(project__isnull=True, client__isnull=True)
                    .values('project_id', 'client_id', 'asana_name').first())
            if link:
                pid, cid = resolve(link['project_id'], link['client_id'])
                return {'project_id': pid, 'client_id': cid,
                        'tier': 'asana_url' if pid else 'asana_url_client',
                        'reason': f"Open in Asana: the {link['asana_name'] or 'project'} project"
                                  f" ({name_of(cid)}).",
                        'task_name': '', 'count': 0}

        if not (block.start and block.end):
            return None
        rows = list(AsanaActivity.objects
                    .filter(integration=integ, user_id=block.user_id,
                            at__gte=block.start - ACTIVITY_SLACK,
                            at__lte=block.end + ACTIVITY_SLACK)
                    .exclude(project__isnull=True, client__isnull=True)
                    .order_by('-at')
                    .values('project_id', 'client_id', 'task_name', 'kind'))
        if not rows:
            return _bracket(block, org, integ, resolve, name_of)
        touched = [resolve(r['project_id'], r['client_id']) for r in rows]
        projects = {p for p, _ in touched}
        clients = {c for _, c in touched}
        if len(clients) != 1 or None in clients:
            return None
        client = next(iter(clients))
        project = next(iter(projects)) if len(projects) == 1 and None not in projects else None

        # Lead with the task the person did the most to; the latest breaks ties.
        counts = defaultdict(int)
        for r in rows:
            counts[r['task_name']] += 1
        task = max(counts, key=lambda t: counts[t]) if counts else ''
        kind = next((r['kind'] for r in rows if r['task_name'] == task), '')
        did = _DID.get(kind, 'updated')
        others = len({r['task_name'] for r in rows}) - 1
        what = f"“{task}”" if task else 'a task'
        if others > 0:
            what += f" and {others} other task{'s' if others != 1 else ''}"
        return {'project_id': project, 'client_id': client,
                'tier': 'asana_activity' if project else 'asana_activity_client',
                'reason': f"In Asana you {did} {what} ({name_of(client)}).",
                'task_name': task, 'count': len(rows)}
    except Exception as e:
        logger.warning('Asana explanation unavailable for block %s: %s',
                       getattr(block, 'pk', '?'), e)
        return None


# How far either side of a quiet block an Asana action may sit and still speak
# for it. Long enough to cover reading a task thread before replying to it;
# short enough that a lunch break between two Easterns edits is not "Easterns".
BRACKET_GAP = timedelta(minutes=20)


def _bracket(block, org, integ, resolve, name_of):
    """An Asana block in which the person changed nothing — reading tasks,
    which Asana never records — between two actions on the SAME client.

    Weaker than an action inside the block (the classifier proposes it rather
    than filing it), and never a project: both sides must name the one client,
    and the nearest action on each side must be within BRACKET_GAP of the
    block's edge. Anything else — one side missing, two clients — is nothing."""
    from tracker.models_asana import AsanaActivity
    base = (AsanaActivity.objects.filter(integration=integ, user_id=block.user_id)
            .exclude(project__isnull=True, client__isnull=True))
    before = (base.filter(at__lt=block.start - ACTIVITY_SLACK,
                          at__gte=block.start - ACTIVITY_SLACK - BRACKET_GAP)
              .order_by('-at').values('at', 'project_id', 'client_id', 'task_name').first())
    after = (base.filter(at__gt=block.end + ACTIVITY_SLACK,
                         at__lte=block.end + ACTIVITY_SLACK + BRACKET_GAP)
             .order_by('at').values('at', 'project_id', 'client_id', 'task_name').first())
    if not (before and after):
        return None
    _, c1 = resolve(before['project_id'], before['client_id'])
    _, c2 = resolve(after['project_id'], after['client_id'])
    if not c1 or c1 != c2:
        return None
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(getattr(org, 'timezone', None) or 'America/New_York')
    except Exception:
        tz = None

    def at(t):
        t = t.astimezone(tz) if tz else t
        return t.strftime('%I:%M %p').lstrip('0')

    task = before['task_name'] or after['task_name'] or ''
    return {'project_id': None, 'client_id': c1, 'tier': 'asana_between',
            'reason': f"No Asana changes in this stretch, but you worked on {name_of(c1)} "
                      f"tasks in Asana just before ({at(before['at'])}) and just after "
                      f"({at(after['at'])}).",
            'task_name': task, 'count': 0}
