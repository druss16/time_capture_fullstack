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
