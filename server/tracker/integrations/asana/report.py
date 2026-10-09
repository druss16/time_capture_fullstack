"""
The onboarding link report: how a firm's Asana projects matched, and the
unmatched ones grouped by the client name they are written under, so an
operator fixes a whole group with one choice.

More Than Cars (2026-10-08) needed four rounds of shell scripts to find out
that "DeNooyer", "Fredy Chevy" and "MTC Media" were clients under other
names. This is that diagnosis as a screen: the biggest groups first, each
with the clients it could be.
"""
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from tracker.integrations.asana.matching import canon, split_name
from tracker.models_asana import AsanaNameMap, AsanaProjectLink

GROUP_LIMIT = 80
PICK_LIMIT = 150


def _suggestions(matcher, part, clients, n=3):
    """Clients the name could be: the matcher's own candidates first, then the
    closest names by spelling."""
    found = list(matcher.client_candidates(part)) if part else []
    key = canon(part)
    scored = sorted(clients, key=lambda c: -SequenceMatcher(None, key, canon(c.name)).ratio())
    for c in scored:
        if len(found) >= n:
            break
        if c not in found:
            found.append(c)
    return [{'id': c.id, 'name': c.name} for c in found[:n]]


def link_report(integration) -> dict:
    from tracker.integrations.asana.sync import build_matcher
    from tracker.models import Client

    links = list(AsanaProjectLink.objects.filter(integration=integration, archived=False)
                 .select_related('client'))
    counts = Counter()
    for link in links:
        counts['project' if link.project_id else 'client' if link.client_id
               else 'ignored' if link.link_source == 'ignored' else 'unlinked'] += 1

    matcher = build_matcher(integration)
    clients = list(Client.objects.filter(org=integration.organization, is_active=True)
                   .only('id', 'name').order_by('name'))
    maps = {m.prefix: m for m in AsanaNameMap.objects.filter(integration=integration)
            .select_related('client')}

    # Unmatched work, grouped by the client part of the name — or by team
    # when the name has none. Client-only links are grouped too: they are
    # right about the client and still ask for every project.
    groups = defaultdict(lambda: {'projects': [], 'labels': Counter(), 'client_only': 0,
                                  'clients': Counter()})
    for link in links:
        if link.project_id or link.link_source == 'ignored':
            continue
        part, _rest = split_name(link.asana_name)
        label = part or link.asana_team or ''
        key = canon(label) if label else ''
        g = groups[key]
        g['projects'].append(link.asana_name)
        g['labels'][label] += 1
        if link.client_id:
            g['client_only'] += 1
            g['clients'][link.client.name] += 1

    rows = []
    for key, g in groups.items():
        label = g['labels'].most_common(1)[0][0] if g['labels'] else ''
        m = maps.get(key)
        rows.append({
            'prefix': key,
            'label': label or '(no client in the name)',
            'count': len(g['projects']),
            'client_only': g['client_only'],
            'current_client': g['clients'].most_common(1)[0][0] if g['clients'] else None,
            'examples': g['projects'][:4],
            'mapped': ({'client_id': m.client_id, 'client_name': m.client.name if m.client else None,
                        'ignore': m.ignore} if m else None),
            'suggestions': _suggestions(matcher, label, clients) if key else [],
            'fixable': bool(key),
        })
    rows.sort(key=lambda r: (-(r['count'] - r['client_only']), -r['count']))

    # Client known, project not: the closest projects of that client, for a
    # person to accept in one click. Best guesses first.
    from datetime import timedelta
    from django.utils import timezone
    from tracker.models import Project
    from tracker.models_asana import AsanaActivity
    # What was actually worked on this week. A pick that moves 40 of a
    # person's actions matters more than one that moves none, so the list
    # leads with them — not with the closest-looking name.
    recent = Counter(AsanaActivity.objects
                     .filter(integration=integration, project__isnull=True, client__isnull=False,
                             at__gte=timezone.now() - timedelta(days=7))
                     .values_list('asana_project_gid', flat=True))
    by_client = defaultdict(list)
    for pid, name, cid in (Project.objects.filter(org=integration.organization, is_active=True)
                           .values_list('id', 'name', 'client_id').order_by('name')):
        by_client[cid].append({'id': pid, 'name': name})
    picks = []
    for link in links:
        if link.project_id or not link.client_id or link.link_source in ('manual', 'ignored'):
            continue
        cands = matcher.project_candidates(link.client_id, link.asana_name)
        worked = recent.get(link.asana_gid, 0)
        if not cands and not worked:
            continue
        picks.append({
            'asana_gid': link.asana_gid, 'asana_name': link.asana_name,
            'client_name': link.client.name if link.client else None,
            'activity_7d': worked,
            'candidates': [{'project_id': p.id, 'name': p.name, 'score': sc} for sc, p in cands],
            # The client's other projects, for when no guess is right.
            'others': by_client.get(link.client_id, [])[:80],
        })
    picks.sort(key=lambda r: (-r['activity_7d'],
                              -(r['candidates'][0]['score'] if r['candidates'] else 0)))
    picks_activity = sum(r['activity_7d'] for r in picks)

    live = len(links)
    matched = counts['project'] + counts['client'] + counts['ignored']
    return {
        'live': live,
        'linked_project': counts['project'],
        'linked_client': counts['client'],
        'ignored': counts['ignored'],
        'unlinked': counts['unlinked'],
        'matched_pct': round(100 * matched / live) if live else 0,
        'groups': rows[:GROUP_LIMIT],
        'project_picks': picks[:PICK_LIMIT],
        'project_picks_total': len(picks),
        # Client-only actions this week that one pick each would move to a project.
        'project_picks_activity_7d': picks_activity,
        'clients': [{'id': c.id, 'name': c.name} for c in clients],
        'has_team_or_field': any(l.asana_team or l.client_hint or l.qbt_ref for l in links),
        # Linked exactly through a "QB Time Project" field in Asana.
        'linked_by_field': sum(1 for l in links if l.link_source == 'field'),
        'qbt_field_unresolved': sum(1 for l in links if l.qbt_ref and l.link_source != 'field'
                                    and l.link_source != 'manual'),
    }


def map_name(integration, prefix: str, *, client=None, ignore=False, label='', user=None,
             clear=False) -> dict:
    """Decide one client name for every Asana project written under it, then
    relink them all — no call to Asana."""
    from tracker.integrations.asana.sync import relink
    key = canon(prefix)
    if not key:
        raise ValueError('That name is empty.')
    if clear:
        AsanaNameMap.objects.filter(integration=integration, prefix=key).delete()
    else:
        AsanaNameMap.objects.update_or_create(
            integration=integration, prefix=key,
            defaults={'client': None if ignore else client, 'ignore': bool(ignore),
                      'label': (label or prefix)[:255], 'created_by': user})
    return relink(integration)


def accept_project(integration, asana_gid: str, project) -> None:
    """A person picked the project: a hand link, kept by every later sync."""
    link = AsanaProjectLink.objects.get(integration=integration, asana_gid=asana_gid)
    link.project = project
    link.client_id = project.client_id
    link.link_source = 'manual'
    link.save(update_fields=['project', 'client', 'link_source', 'updated_at'])
    from tracker.integrations.asana.sync import carry_to_activity
    carry_to_activity(link)
