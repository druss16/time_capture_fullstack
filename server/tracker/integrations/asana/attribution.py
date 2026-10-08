"""
Which project a block of Asana time belongs to, from what Asana knows.

Two signals, strongest first:

  1. url — a browser tab on app.asana.com carries the Asana project's id, in
     both address styles ("/0/<project>/<task>" and "/1/<ws>/project/<id>/…").
     A linked project names itself; nothing is inferred.
  2. activity — the Asana desktop app is titled "Asana" whatever is open, so
     there the evidence is what the person did in Asana during the block:
     comments, edits, completions (AsanaActivity). If everything they touched
     belongs to one project, the block is that project's. Several projects, or
     nothing touched, and it abstains — the block still asks.
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
    """(gid -> project_id, user_id -> [(at, project_id)], project_id -> client_id),
    or None when the firm has no Asana connection — or the tables do not
    exist yet (code ships before its migration runs)."""
    try:
        from tracker.models import Integration, Project
        from tracker.models_asana import AsanaActivity, AsanaProjectLink
        integ = Integration.objects.filter(organization=org, provider='asana').first()
        if integ is None:
            return None
        links = dict(AsanaProjectLink.objects.filter(integration=integ, project__isnull=False)
                     .values_list('asana_gid', 'project_id'))
        activity = defaultdict(list)
        for user_id, at, project_id in (AsanaActivity.objects
                                        .filter(integration=integ, at__gte=since - ACTIVITY_SLACK,
                                                project__isnull=False)
                                        .values_list('user_id', 'at', 'project_id')):
            activity[user_id].append((at, project_id))
        if not links and not activity:
            return None
        ids = set(links.values()) | {p for rows in activity.values() for _, p in rows}
        client_of = dict(Project.objects.filter(id__in=ids).values_list('id', 'client_id'))
        return {'links': links, 'activity': activity, 'client_of': client_of}
    except Exception as e:
        logger.warning('Asana attribution context unavailable for org %s: %s', org.id, e)
        return None


def project_for(block, ctx):
    """(project_id, 'asana_url' | 'asana_activity') or (None, None)."""
    if not ctx or not is_asana_block(block):
        return None, None
    gid = project_gid_in_url(getattr(block, 'url', '') or '')
    if gid and gid in ctx['links']:
        return ctx['links'][gid], 'asana_url'
    if not (block.start and block.end):
        return None, None
    lo, hi = block.start - ACTIVITY_SLACK, block.end + ACTIVITY_SLACK
    touched = {p for at, p in ctx['activity'].get(block.user_id, ()) if lo <= at <= hi}
    if len(touched) == 1:
        return next(iter(touched)), 'asana_activity'
    return None, None
