"""
Is a firm's client list what the firm actually works for?

Nothing noticed when one agency went from ~30 clients to 412: an import of its
whole QuickBooks customer list, plus every QuickBooks project imported a
second time as an empty client. The cost was invisible in totals (none of them
had time) but real in matching: the firm's own name ("Easterns") named a dozen
clients and so matched none of them, and the agent matched window titles
against vendors and card processors.

Three signals, each with the command that clears it:

  idle     imported clients with no time, no project, no timecard row and no
           invoice, when there are many of them or they are most of the list
           -> prune_dormant_clients
  twins    clients named exactly like another client's project (a QuickBooks
           sub-customer imported as a client)  -> fold_subcustomer_clients
  vertical QuickBooks connected while the firm is still "general": the
           agency import rule (clients_need_projects) can't apply
"""
from __future__ import annotations

from collections import Counter

from tracker.models import Integration, Organization

# Flag idle clients when there are this many, or when they are most of the
# list (and more than a handful, so a new firm with 3 of 5 idle isn't noise).
IDLE_MIN = 25
IDLE_SHARE = 0.5
IDLE_SHARE_MIN = 10

QB_PROVIDERS = ('quickbooks', 'qb_time')


def client_hygiene_by_org(org_ids) -> dict[int, dict]:
    """{org_id: {'active', 'idle', 'twins', 'vertical_unset', 'reasons'}}."""
    from tracker.services.client_conversion import find_project_twins
    from tracker.services.dormant_clients import dormant_counts_by_org

    org_ids = list(org_ids)
    counts = dormant_counts_by_org(org_ids)
    twins = Counter(t.org_id for t in find_project_twins(None) if t.org_id in set(org_ids))
    qb_orgs = set(Integration.objects.filter(
        organization_id__in=org_ids, provider__in=QB_PROVIDERS, is_connected=True,
    ).values_list('organization_id', flat=True))
    general = set(Organization.objects.filter(id__in=org_ids).filter(
        industry_type__in=('', 'general')).values_list('id', flat=True)) | set(
        Organization.objects.filter(id__in=org_ids, industry_type__isnull=True).values_list('id', flat=True))

    out = {}
    for org_id in org_ids:
        c = counts.get(org_id, {'active': 0, 'dormant': 0})
        h = {
            'active': c['active'],
            'idle': c['dormant'],
            'twins': twins.get(org_id, 0),
            'vertical_unset': org_id in qb_orgs and org_id in general,
        }
        h['reasons'] = hygiene_reasons(h)
        out[org_id] = h
    return out


def hygiene_reasons(h: dict) -> list[str]:
    reasons = []
    idle, active = h.get('idle', 0), h.get('active', 0)
    if idle >= IDLE_MIN or (idle >= IDLE_SHARE_MIN and active and idle / active > IDLE_SHARE):
        reasons.append(f"{idle} of {active} clients idle (no time or projects): prune_dormant_clients")
    if h.get('twins'):
        n = h['twins']
        reasons.append(f"{n} client{'s' if n != 1 else ''} named like a project: fold_subcustomer_clients")
    if h.get('vertical_unset'):
        reasons.append("QuickBooks connected but vertical is 'general'")
    return reasons
