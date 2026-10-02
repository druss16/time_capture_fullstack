"""
Reports → AI agent activity: the firm owner's view of the agent-presence
measurement. Owners only; hidden per firm until MavOps turns it on.

Its own numbers on its own page. Nothing here is added to any timesheet,
report total, billing figure or analytic — the user's rule for agent time.

Rows to review are device-hours where the tracker would have booked a person
but the measurement says nobody's hands were on the machine:
  * macOS: unattended-active seconds whose cause is 'agent_busy' or
    'unexplained' (remote control, Universal Control, Sidecar, tablet drivers
    and jigglers are already excluded at the source — see agent_presence.py);
  * Windows: an hour with REVIEW_MIN_CLICKS+ synthetic clicks, outside a
    remote-desktop session, with the click monitor known to be working.
"""
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

REPORT_FLAG = 'ai_agent_report'

# Agents whose CPU means the agent is WORKING. Mirrors CORROBORATING_AGENTS in
# the desktop agent's agent_presence.py; Electron apps (Claude desktop,
# ChatGPT, Cursor) burn CPU just sitting open, so they only count as "open".
WORKING_AGENTS = {
    'claude_code', 'codex', 'claude_in_chrome', 'power_automate', 'uipath', 'autohotkey',
}
OPEN_ONLY_AGENTS = {'claude_desktop', 'chatgpt_desktop', 'chatgpt_atlas', 'cursor',
                    'windsurf', 'microsoft_copilot'}
EXPLAINED_CAUSES = {'remote_control', 'universal_control', 'sidecar', 'tablet_driver', 'keep_awake'}
CANDIDATE_CAUSES = ('agent_busy', 'unexplained')

TOOL_NAMES = {
    'claude_code': 'Claude Code', 'codex': 'Codex', 'claude_in_chrome': 'Claude in Chrome',
    'power_automate': 'Power Automate', 'uipath': 'UiPath', 'autohotkey': 'AutoHotkey',
    'claude_desktop': 'Claude (desktop app)', 'chatgpt_desktop': 'ChatGPT',
    'chatgpt_atlas': 'ChatGPT Atlas', 'cursor': 'Cursor', 'windsurf': 'Windsurf',
    'microsoft_copilot': 'Microsoft Copilot',
}

REVIEW_MIN_S = 300          # a Mac hour needs 5+ unattended minutes to be listed
REVIEW_MIN_CLICKS = 10      # a Windows hour needs 10+ synthetic clicks
MAX_REVIEW_ROWS = 200


def report_enabled(org) -> bool:
    """Off unless MavOps switched it on. Any error (e.g. migration pending) = off."""
    if org is None:
        return False
    try:
        from tracker.models import FirmFeatureFlag
        return FirmFeatureFlag.objects.filter(org_id=org.pk, key=REPORT_FLAG, enabled=True).exists()
    except Exception:
        return False


def set_report_enabled(org_id: int, enabled: bool):
    from tracker.models import FirmFeatureFlag
    FirmFeatureFlag.objects.update_or_create(
        org_id=org_id, key=REPORT_FLAG, defaults={'enabled': bool(enabled)})


def enabled_org_ids():
    from tracker.models import FirmFeatureFlag
    return list(FirmFeatureFlag.objects.filter(key=REPORT_FLAG, enabled=True)
                .values_list('org_id', flat=True))


def _person(user):
    if user is None:
        return 'Unknown'
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or user.email or user.username


def _top(d: dict):
    return max(d.items(), key=lambda kv: kv[1])[0] if d else ''


def build_firm_report(org, days: int = 7) -> dict:
    from tracker.models import AgentActivityReview, AgentPresenceSample, OrganizationMembership

    since = timezone.now() - timedelta(days=days)
    samples = list(
        AgentPresenceSample.objects
        .filter(org=org, bucket_start__gte=since)
        .select_related('user')
        .order_by('-bucket_start'))
    verdicts = dict(AgentActivityReview.objects
                    .filter(org_id=org.pk, sample_id__in=[s.pk for s in samples])
                    .values_list('sample_id', 'verdict'))

    tools = defaultdict(lambda: {'people': set(), 'working_min': 0, 'last_seen': None})
    people_using = set()
    explained_s = 0
    candidate_s = 0
    rows = []

    for s in samples:
        busy_here = []
        for label, p in (s.processes or {}).items():
            if label not in WORKING_AGENTS and label not in OPEN_ONLY_AGENTS:
                continue  # remote-control tools and anything unknown
            if not p.get('seen_min'):
                continue
            t = tools[label]
            if s.user_id:
                t['people'].add(s.user_id)
                people_using.add(s.user_id)
            if label in WORKING_AGENTS:
                t['working_min'] += p.get('busy_min', 0)
                if p.get('busy_min'):
                    busy_here.append(TOOL_NAMES.get(label, label))
            if t['last_seen'] is None or s.bucket_start > t['last_seen']:
                t['last_seen'] = s.bucket_start

        causes = s.unattended_by_cause or {}
        explained_s += sum(v for k, v in causes.items() if k in EXPLAINED_CAUSES)
        mac_candidate = sum(causes.get(c, 0) for c in CANDIDATE_CAUSES)
        candidate_s += mac_candidate

        row = None
        if mac_candidate >= REVIEW_MIN_S:
            row = {
                'kind': 'mac', 'minutes': round(mac_candidate / 60),
                'app': _top(s.unattended_active_by_app or {}),
                'evidence': (f"{', '.join(busy_here)} was working" if causes.get('agent_busy')
                             and busy_here else 'No explanation found'),
            }
        elif (s.input_monitor == 'ok' and not s.remote_session
              and s.clicks_synthetic >= REVIEW_MIN_CLICKS):
            row = {
                'kind': 'windows', 'clicks': s.clicks_synthetic,
                'app': _top(s.synthetic_by or {}),
                'evidence': (f"{', '.join(busy_here)} was working" if busy_here
                             else 'Simulated clicks, no agent seen'),
            }
        if row and len(rows) < MAX_REVIEW_ROWS:
            row.update({
                'sample_id': s.pk, 'person': _person(s.user), 'user_id': s.user_id,
                'hour_start': s.bucket_start.isoformat(),
                'verdict': verdicts.get(s.pk),
            })
            rows.append(row)

    members = OrganizationMembership.objects.filter(organization=org).count()
    tool_rows = sorted(
        ({'tool': label, 'name': TOOL_NAMES.get(label, label),
          'people': len(t['people']),
          'working_hours': round(t['working_min'] / 60, 1) if label in WORKING_AGENTS else None,
          'last_seen': t['last_seen'].isoformat() if t['last_seen'] else None}
         for label, t in tools.items()),
        key=lambda r: (r['working_hours'] is None, -(r['working_hours'] or 0), -r['people']))

    return {
        'days': days,
        'org_name': org.name,
        'devices_reporting': len({s.device_id for s in samples}),
        'tiles': {
            'agent_working_hours': round(sum(t['working_min'] for l, t in tools.items()
                                             if l in WORKING_AGENTS) / 60, 1),
            'review_hours': round(candidate_s / 3600, 1),
            'to_review': sum(1 for r in rows if not r['verdict']),
            'agents_in_use': len(tool_rows),
            'people_using': len(people_using),
            'people_total': members,
        },
        'tools': tool_rows,
        'review': rows,
        'explained_hours': round(explained_s / 3600, 1),
    }
