"""
How much AI-agent activity is on customers' machines, and how much of it the
tracker is mistaking for people. Read-only; summarises AgentPresenceSample.

    python manage.py agent_presence_summary --days 7
    python manage.py agent_presence_summary --days 14 --org 21
    python manage.py agent_presence_summary --json

"Driven hours" are device-hours with at least DRIVEN_CLICKS synthetic clicks:
an hour in which something other than a person was clicking. Before trusting
that number, read input_monitor and remote_session — remote-desktop input may
also look synthetic, and that is exactly what this measurement is meant to
find out.
"""
import json
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.models import AgentDevice, AgentPresenceSample

DRIVEN_CLICKS = 10


def summarise(samples):
    devices = set()
    hours, monitor = Counter(), Counter()
    remote_hours = 0
    clicks_real = clicks_syn = 0
    syn_by, syn_devices, driven = Counter(), set(), Counter()
    driven_remote = 0
    idle_secs = idle_changes = 0
    idle_by_app = Counter()
    unattended_s, unattended_by_app, unattended_devices = 0, Counter(), set()
    unattended_by_cause = Counter()
    proc_devices, proc_seen, proc_busy = defaultdict(set), Counter(), Counter()
    log_devices, log_sessions = defaultdict(set), Counter()

    for s in samples:
        devices.add(s.device_id)
        hours['observed'] += s.seconds_observed / 3600
        monitor[s.input_monitor or 'unknown'] += 1
        remote_hours += s.remote_session
        if s.input_monitor == 'ok':
            clicks_real += s.clicks_real
            clicks_syn += s.clicks_synthetic
            syn_by.update(s.synthetic_by or {})
            if s.clicks_synthetic:
                syn_devices.add(s.device_id)
            if s.clicks_synthetic >= DRIVEN_CLICKS:
                driven[s.device_id] += 1
                driven_remote += s.remote_session
        idle_secs += s.idle_seconds
        idle_changes += s.idle_changes
        idle_by_app.update(s.idle_changes_by_app or {})
        unattended_s += s.unattended_active_seconds
        unattended_by_cause.update(s.unattended_by_cause or {})
        unattended_by_app.update(s.unattended_active_by_app or {})
        if s.unattended_active_seconds:
            unattended_devices.add(s.device_id)
        for label, p in (s.processes or {}).items():
            proc_devices[label].add(s.device_id)
            proc_seen[label] += p.get('seen_min', 0) / 60
            proc_busy[label] += p.get('busy_min', 0) / 60
        for tool, n in (s.local_sessions or {}).items():
            log_devices[tool].add(s.device_id)
            log_sessions[tool] += n

    total_clicks = clicks_real + clicks_syn
    return {
        'devices_reporting': len(devices),
        'device_hours': len(samples),
        'hours_observed': round(hours['observed'], 1),
        'input_monitor': dict(monitor),
        'remote_session_device_hours': remote_hours,
        'clicks': {
            'real': clicks_real, 'synthetic': clicks_syn,
            'synthetic_share': round(clicks_syn / total_clicks, 4) if total_clicks else 0,
            'devices_with_synthetic': len(syn_devices),
            'driven_device_hours': sum(driven.values()),
            'driven_device_hours_remote': driven_remote,
            'devices_with_driven_hours': len(driven),
            'top_sources': syn_by.most_common(10),
        },
        'unattended_active': {
            'hours': round(unattended_s / 3600, 1),
            # Only these two could be an agent; every other cause is a person
            # (remote control, Universal Control, Sidecar, a tablet driver) or
            # a jiggler. Read 'candidate_agent_hours', not 'hours'.
            'candidate_agent_hours': round(
                (unattended_by_cause['agent_busy'] + unattended_by_cause['unexplained']) / 3600, 1),
            'by_cause_hours': {c: round(sec / 3600, 1) for c, sec in unattended_by_cause.most_common()},
            'devices': len(unattended_devices),
            'share_of_observed': round(unattended_s / (hours['observed'] * 3600), 4) if hours['observed'] else 0,
            'top_apps': [(a, round(sec / 3600, 1)) for a, sec in unattended_by_app.most_common(10)],
        },
        'idle_activity': {
            'idle_hours': round(idle_secs / 3600, 1),
            'changes': idle_changes,
            'changes_per_idle_hour': round(idle_changes / (idle_secs / 3600), 1) if idle_secs else 0,
            'top_apps': idle_by_app.most_common(10),
        },
        'agent_processes': {
            label: {'devices': len(proc_devices[label]),
                    'running_hours': round(proc_seen[label], 1),
                    'busy_hours': round(proc_busy[label], 1)}
            for label in sorted(proc_devices, key=lambda l: -len(proc_devices[l]))
        },
        'local_agent_logs': {
            tool: {'devices': len(log_devices[tool]), 'session_hours': log_sessions[tool]}
            for tool in sorted(log_devices)
        },
    }


def build_report(days: int, org=None) -> dict:
    """The whole summary as data — shared by this command and MavOps Admin."""
    since = timezone.now() - timedelta(days=days)
    qs = AgentPresenceSample.objects.filter(bucket_start__gte=since)
    devices_active = AgentDevice.objects.filter(is_active=True, last_seen_at__gte=since)
    if org:
        qs = qs.filter(org_id=org)
        devices_active = devices_active.filter(user__memberships__organization_id=org)

    # Every field summarise() reads is in this list: a deferred field read per
    # row would be one query per row (see the deferred-field N+1 incident).
    by_org = defaultdict(list)
    for s in qs.select_related('org').only(
            'device_id', 'org__name', 'seconds_observed', 'idle_seconds', 'remote_session',
            'input_monitor', 'clicks_real', 'clicks_synthetic', 'synthetic_by',
            'idle_changes', 'idle_changes_by_app', 'unattended_active_seconds',
            'unattended_active_by_app', 'unattended_by_cause', 'processes', 'local_sessions'):
        by_org[(s.org_id, s.org.name)].append(s)

    all_samples = [s for ss in by_org.values() for s in ss]
    return {
        'days': days,
        'active_devices': devices_active.distinct().count(),
        'fleet': summarise(all_samples),
        'orgs': {f'{oid} {name}': summarise(ss) for (oid, name), ss in sorted(by_org.items())},
    }


class Command(BaseCommand):
    help = "Summarise agent-presence measurement (read-only)."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--org', type=int, default=None)
        parser.add_argument('--json', action='store_true', dest='as_json')

    def handle(self, *args, days, org, as_json, **opts):
        report = build_report(days, org)
        if as_json:
            self.stdout.write(json.dumps(report, indent=2, default=str))
            return

        def show(title, r):
            c, i = r['clicks'], r['idle_activity']
            self.stdout.write(f"\n== {title} ==")
            self.stdout.write(f"  devices reporting {r['devices_reporting']}, "
                              f"{r['hours_observed']}h observed, input monitor {r['input_monitor']}, "
                              f"remote-session device-hours {r['remote_session_device_hours']}")
            self.stdout.write(f"  clicks: {c['synthetic']} synthetic of {c['real'] + c['synthetic']} "
                              f"({c['synthetic_share']:.1%}); driven device-hours {c['driven_device_hours']} "
                              f"on {c['devices_with_driven_hours']} devices "
                              f"({c['driven_device_hours_remote']} of them remote)")
            if c['top_sources']:
                self.stdout.write(f"    synthetic sources: {c['top_sources']}")
            u = r['unattended_active']
            self.stdout.write(f"  unattended-active (Mac): {u['candidate_agent_hours']}h candidate agent time "
                              f"of {u['hours']}h on {u['devices']} devices; by cause {u['by_cause_hours']} "
                              f"({u['share_of_observed']:.1%} of observed); top {u['top_apps'][:5]}")
            self.stdout.write(f"  idle: {i['changes']} window changes in {i['idle_hours']}h idle "
                              f"({i['changes_per_idle_hour']}/idle-hour); top {i['top_apps'][:5]}")
            for label, p in r['agent_processes'].items():
                self.stdout.write(f"  process {label}: {p['devices']} devices, "
                                  f"{p['running_hours']}h running, {p['busy_hours']}h busy")
            for tool, l in r['local_agent_logs'].items():
                self.stdout.write(f"  local logs {tool}: {l['devices']} devices, {l['session_hours']} session-hours")

        self.stdout.write(f"Last {days} days — {report['active_devices']} active devices")
        show('FLEET', report['fleet'])
        for name, r in report['orgs'].items():
            show(name, r)
