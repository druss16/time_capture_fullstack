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
