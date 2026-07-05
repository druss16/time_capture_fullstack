# tracker/services/mismatch_scan.py
"""
Shared client-name mismatch detection core.

Wraps the distinctive-token matcher (tracker.utils.client_name_match) so the
nightly Celery scan and the pre-invoice gate run IDENTICAL detection logic.
Detection-only — never mutates a Block.
"""
from collections import defaultdict

from tracker.utils.client_name_match import build_token_index, detect_mismatch


def _indexes_for_orgs(org_ids):
    """Build per-org {client_id: name} maps, token indexes, and firm names."""
    from tracker.models import Client, Organization

    names_by_org = defaultdict(dict)
    for c in Client.objects.filter(org_id__in=org_ids).only('id', 'name', 'org_id'):
        names_by_org[c.org_id][c.id] = c.name

    index_by_org = {oid: build_token_index(names) for oid, names in names_by_org.items()}

    firm_by_org = {}
    for o in Organization.objects.filter(id__in=org_ids).only('id', 'name'):
        firm_by_org[o.id] = o.name

    return names_by_org, index_by_org, firm_by_org


def scan_blocks(blocks, names_by_org, index_by_org, firm_by_org):
    """
    Yield a mismatch dict per block whose title names a different client than
    it's booked to. `blocks` is any iterable of Block instances.

    Each dict:
      {
        'block_id', 'org_id', 'booked_client_id', 'booked_client_name',
        'looks_like_client_name', 'looks_like_client_id' (may be None),
        'bucket' ('client'|'internal'), 'score', 'window_title'
      }
    """
    for b in blocks:
        names = names_by_org.get(b.org_id)
        index = index_by_org.get(b.org_id)
        if not index or not names or b.client_id not in names:
            continue
        m = detect_mismatch(
            b.window_title, b.client_id, index, names,
            firm_name=firm_by_org.get(b.org_id),
        )
        if not m:
            continue
        yield {
            'block_id': b.id,
            'org_id': b.org_id,
            'booked_client_id': b.client_id,
            'booked_client_name': names[b.client_id],
            'looks_like_client_name': m['looks_like_client_name'],
            'looks_like_client_id': m.get('looks_like_client_id'),
            'bucket': m.get('bucket', 'client'),
            'score': m.get('score', 0.0),
            'window_title': (b.window_title or '')[:512],
        }


def check_invoice_mismatches(org, block_ids):
    """
    Synchronous gate for the billing path. Returns a list of CLIENT-bucket
    mismatch dicts (billing-impacting only; internal/admin noise excluded) for
    the given block_ids. Empty list => safe to invoice.
    """
    from tracker.models import Block

    if not block_ids:
        return []

    names_by_org, index_by_org, firm_by_org = _indexes_for_orgs([org.id])

    blocks = (
        Block.objects
        .filter(id__in=block_ids, org=org, deleted_at__isnull=True,
                client_id__isnull=False)
        .exclude(window_title__isnull=True)
        .exclude(window_title='')
        .select_related('client')
    )

    return [
        row for row in scan_blocks(blocks, names_by_org, index_by_org, firm_by_org)
        if row['bucket'] == 'client'
    ]