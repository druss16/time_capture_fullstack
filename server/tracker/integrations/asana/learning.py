"""
Which project an Asana project is, learned from what the firm itself
recorded — never asked of an operator who does not work there.

Names get most links (matching.py). The rest know their client and not
their project: "Tom Gill Buick GMC: 2026 Monthly Video Offers" could be any
of that dealer's projects. The firm already answered that, every day:

  * QuickBooks Time — the hours each person entered on a project jobcode,
    with times (a regular timesheet) or for the day (a manual one);
  * Daily Review — the blocks each person filed or corrected to a project.

Line those up against what the same person did in Asana at the same time
(AsanaActivity) and the pairing repeats: Asana project X was worked while
time went to project P, day after day. When it repeats enough, and nearly
always to the same P, X is linked to P (link_source 'learned').

Only projects of the link's own client count — the client is already known,
so this only ever chooses among that client's projects. Our own pushed
QuickBooks Time rows are left out (they came from our blocks), and so are
blocks whose project the machine set; only a person's choice is evidence.
"""
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

LEARN_DAYS = 30
# Activity this far either side of a span still belongs to it.
SLACK = timedelta(minutes=10)
# How much agreement makes a link: votes (a timed span is 1, a day shared
# between k projects of the client is 1/k each), on at least MIN_DAYS days,
# with the winner holding MIN_SHARE of all votes and twice the runner-up.
MIN_VOTES = 3.0
MIN_DAYS = 2
MIN_SHARE = 0.75

HUMAN_STATES = ('user', 'user_edit', 'correction')


def _tz(org):
    try:
        return ZoneInfo(org.timezone or 'America/New_York')
    except Exception:                                            # noqa: BLE001
        return ZoneInfo('America/New_York')


def qbt_spans(org, since, *, api=None):
    """(user_id, start, end, project_id, day_level) per QuickBooks Time
    timesheet a person entered on a project jobcode."""
    from tracker.integrations.qb_time.client import QBTimeClient
    from tracker.models import Integration
    from tracker.models_task_type_sets import (
        ExternalMatterMapping, ExternalStaffMapping, QbtPushedTimesheet,
    )
    qbt = Integration.objects.filter(organization=org, provider='qb_time', is_connected=True).first()
    if qbt is None:
        return []
    staff = dict(ExternalStaffMapping.objects.filter(integration=qbt)
                 .values_list('external_id', 'user_id'))
    jobs = dict(ExternalMatterMapping.objects.filter(integration=qbt)
                .values_list('external_id', 'project_id'))
    if not staff or not jobs:
        return []
    ours = set(QbtPushedTimesheet.objects.filter(integration=qbt)
               .values_list('timesheet_id', flat=True))
    tz = _tz(org)
    api = api or QBTimeClient(qbt)
    today = timezone.now().astimezone(tz).date()
    out = []
    users = sorted(staff)
    for i in range(0, len(users), 50):
        for ts in api.paginated('timesheets', start_date=str(since.astimezone(tz).date()),
                                end_date=str(today), user_ids=','.join(users[i:i + 50])):
            if str(ts.get('id') or '') in ours:
                continue
            uid = staff.get(str(ts.get('user_id')))
            pid = jobs.get(str(ts.get('jobcode_id')))
            if not uid or not pid:
                continue
            start = parse_datetime(str(ts.get('start') or ''))
            end = parse_datetime(str(ts.get('end') or ''))
            if start and end and end > start:
                out.append((uid, start, end, pid, False))
                continue
            try:
                day = datetime.strptime(str(ts.get('date') or '')[:10], '%Y-%m-%d').date()
            except ValueError:
                continue
            lo = datetime.combine(day, time.min, tzinfo=tz)
            out.append((uid, lo, lo + timedelta(days=1), pid, True))
    return out


def block_spans(org, since):
    """(user_id, start, end, project_id, False) per block a person filed."""
    from tracker.models import Block
    return [(u, s, e, p, False) for u, s, e, p in
            Block.objects.filter(org=org, start__gte=since, project__isnull=False,
                                 state_changed_by__in=HUMAN_STATES)
            .values_list('user_id', 'start', 'end', 'project_id')]


def tally(links, spans, activity, client_of, tz):
    """gid -> {project_id: votes}, gid -> {project_id: set(days)}.

    links: gid -> client_id (client-only links); activity: user_id ->
    [(at, gid)]; client_of: project_id -> client_id."""
    votes = defaultdict(lambda: defaultdict(float))
    days = defaultdict(lambda: defaultdict(set))
    # A day-level entry says only "some of today went to P". Split the day
    # between the client's projects that person logged that day.
    day_projects = defaultdict(set)
    for uid, lo, _hi, pid, day_level in spans:
        if day_level:
            day_projects[(uid, lo.date(), client_of.get(pid))].add(pid)
    seen = set()
    for uid, lo, hi, pid, day_level in spans:
        client = client_of.get(pid)
        if client is None:
            continue
        touched = {gid for at, gid in activity.get(uid, ())
                   if lo - SLACK <= at <= hi + SLACK and links.get(gid) == client}
        weight = 1.0 / len(day_projects[(uid, lo.date(), client)]) if day_level else 1.0
        for gid in touched:
            key = (uid, lo, hi, pid, gid)
            if key in seen:
                continue
            seen.add(key)
            votes[gid][pid] += weight
            days[gid][pid].add(lo.astimezone(tz).date())
    return votes, days


def decide(votes, days):
    """gid -> project_id, where the evidence agrees enough."""
    out = {}
    for gid, by_project in votes.items():
        ranked = sorted(by_project.items(), key=lambda kv: -kv[1])
        pid, top = ranked[0]
        total = sum(by_project.values())
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if (top >= MIN_VOTES and len(days[gid][pid]) >= MIN_DAYS
                and top / total >= MIN_SHARE and top >= 2 * second):
            out[gid] = pid
    return out


def learn_links(integration, *, dry_run=False, api=None, days=LEARN_DAYS) -> dict:
    """Link client-only Asana projects to the project the firm's own time
    says they are. Returns what was (or would be) linked."""
    from tracker.integrations.asana.sync import carry_to_activity
    from tracker.models import Project
    from tracker.models_asana import AsanaActivity, AsanaProjectLink

    org = integration.organization
    since = timezone.now() - timedelta(days=days)
    candidates = {l.asana_gid: l for l in AsanaProjectLink.objects.filter(
        integration=integration, archived=False, client__isnull=False,
        link_source__in=('client', 'learned'))}
    if not candidates:
        return {'linked': 0, 'changes': []}
    links = {gid: l.client_id for gid, l in candidates.items()}
    activity = defaultdict(list)
    for uid, at, gid in (AsanaActivity.objects
                         .filter(integration=integration, at__gte=since - SLACK,
                                 asana_project_gid__in=list(links))
                         .values_list('user_id', 'at', 'asana_project_gid')):
        activity[uid].append((at, gid))
    if not activity:
        return {'linked': 0, 'changes': []}

    spans = block_spans(org, since)
    try:
        spans += qbt_spans(org, since, api=api)
    except Exception as e:                                       # noqa: BLE001
        # QuickBooks Time down or not connected: Daily Review alone still teaches.
        logger.warning('Asana learning: QuickBooks Time timesheets unavailable for org %s: %s',
                       org.id, e)
    client_of = dict(Project.objects.filter(org=org, is_active=True).values_list('id', 'client_id'))
    votes, day_sets = tally(links, spans, activity, client_of, _tz(org))
    decided = decide(votes, day_sets)

    names = dict(Project.objects.filter(id__in=set(decided.values())).values_list('id', 'name'))
    changes = []
    for gid, pid in decided.items():
        link = candidates[gid]
        if link.project_id == pid:
            continue
        changes.append({'asana_gid': gid, 'asana_name': link.asana_name,
                        'from_project_id': link.project_id, 'project_id': pid,
                        'project_name': names.get(pid, ''),
                        'votes': round(votes[gid][pid], 2), 'days': len(day_sets[gid][pid])})
        if dry_run:
            continue
        link.project_id = pid
        link.link_source = 'learned'
        link.save(update_fields=['project', 'link_source', 'updated_at'])
        carry_to_activity(link)
    if changes and not dry_run:
        logger.info('Asana learning for org %s linked %s projects', org.id, len(changes))
    return {'linked': len(changes), 'changes': changes,
            'considered': len(votes), 'spans': len(spans)}
