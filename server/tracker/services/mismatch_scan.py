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

# ─────────────────────────────────────────────────────────────────────────────
# Bucketed sweep — the core behind BOTH the MavOps Mismatches tab and the
# firm-facing "Check for misfiled time" panel in Approvals.
#
# Lifted out of views_mavops so the two surfaces run ONE detector. A manager
# clearing a row in Approvals and MavOps looking at the same org have to be
# looking at the same verdict, or the tool that is supposed to build trust
# becomes the thing that undermines it.
# ─────────────────────────────────────────────────────────────────────────────
BUCKETS = ("client", "internal", "unsure")


def build_indexes(org_ids):
    """Public alias for the per-org name map / token index / firm name triple."""
    return _indexes_for_orgs(org_ids)


def confirmed_correct_block_ids(org_ids):
    """Blocks a human has already declared correctly booked.

    Read once per scan and used to skip, so "yes I checked, it's right" is a
    decision that sticks instead of one the panel asks for again tomorrow.
    """
    from tracker.models import MismatchFlag

    ids = [o for o in (org_ids or []) if o]
    if not ids:
        return set()
    return set(
        MismatchFlag.objects
        .filter(org_id__in=ids, resolved_reason='confirmed_correct')
        .values_list('block_id', flat=True)
    )


def _set_by(b):
    """Who put the block on this client.

    A person deliberately allocating time reads identically to a classifier
    error in the numbers, but the two want opposite responses — so every row
    says which it was, and the UI can lead with the classifier's mistakes.
    """
    return 'user' if (b.state_changed_by in ('user', 'user_edit', 'correction')
                      or b.categorized_by == 'manual') else 'classifier'


def _base_row(b, oid, names, day):
    """The fields every flagged row carries, whichever verdict produced it."""
    return {
        'block_id': b.id,
        'org_id': oid,
        'org_name': b.org.name if b.org_id else None,
        'user': (b.user.get_full_name().strip() or b.user.username) if b.user_id else None,
        'user_id': b.user_id,
        # Minutes are why a manager cares: a 4-minute misfile and a 3-hour one
        # are the same row without them.
        'minutes': b.minutes or 0,
        # `_review_timesheet_id` is stamped by the Approvals sweep, which
        # groups by the reviewee's WEEK because Block.timesheet is null on most
        # rows. Falls back to the FK for callers that don't stamp (MavOps).
        'timesheet_id': getattr(b, '_review_timesheet_id', None) or getattr(b, 'timesheet_id', None),
        'date': day,
        'window_title': (b.window_title or '')[:200],
        'app_name': getattr(b, 'app_name', '') or '',
        'booked_client_id': b.client_id,
        'booked_client_name': names[b.client_id],
        'set_by': _set_by(b),
    }


def scan_buckets(blocks, names_by_org, index_by_org, firm_by_org,
                 limit=500, skip_block_ids=frozenset()):
    """
    Walk `blocks` once and sort every flagged one into three verdicts.

      client   — the title distinctively names a DIFFERENT business client than
                 the block is booked to. The money bucket: one nameable target,
                 so it has a one-click fix.
      internal — same disagreement, but one side is a firm/admin bucket. Real,
                 and worth a glance, but not a client billing error.
      unsure   — the booked client is ABSENT from the block's own title, yet
                 same-family rivals tie so no single replacement can be named.
                 A third verdict, not a weaker mismatch: nothing here is
                 auto-fixable, and the tie is the point.

    Detection-only — never mutates a Block. Returns raw tallies; callers shape
    them into a response with `bucket_payload`.
    """
    from tracker.utils.client_name_match import detect_mismatch, detect_booked_absent
    from django.utils import timezone

    flagged = {b: [] for b in BUCKETS}
    by_day = {b: defaultdict(int) for b in BUCKETS}
    by_pair = {b: defaultdict(int) for b in BUCKETS}
    counts = {b: 0 for b in BUCKETS}
    scanned = 0
    dismissed_hits = 0

    for b in blocks:
        scanned += 1
        oid = b.org_id
        index = index_by_org.get(oid)
        names = names_by_org.get(oid)
        if not index or not names or b.client_id not in names:
            continue

        if b.id in skip_block_ids:
            dismissed_hits += 1
            continue

        firm = firm_by_org.get(oid)
        day = timezone.localtime(b.start).date().isoformat()

        m = detect_mismatch(b.window_title, b.client_id, index, names, firm_name=firm)
        if not m:
            # No nameable replacement — but the title may still not name the
            # booked client at all, which is its own reportable verdict.
            absent = detect_booked_absent(
                b.window_title, b.client_id, index, names, firm_name=firm,
            )
            if not absent:
                continue
            bucket = absent.get('bucket', 'unsure')
            cands = absent['candidates']
            by_day[bucket][day] += 1
            # Pair on the top candidate only, so the summary stays readable;
            # the row itself keeps the full ranked list.
            by_pair[bucket][f'{names[b.client_id]} → ?{cands[0]["client_name"]}'] += 1
            counts[bucket] += 1
            if len(flagged[bucket]) < limit:
                flagged[bucket].append({
                    **_base_row(b, oid, names, day),
                    'bucket': bucket,
                    'verdict': 'booked_absent',
                    'booked_is_internal': absent.get('booked_is_internal', False),
                    'candidates': cands,
                    'confidence': {
                        'booked_coverage': absent['booked_coverage'],
                        'top_candidate_coverage': cands[0]['coverage'],
                        'abs_hit': cands[0]['abs_hit'],
                    },
                })
            continue

        bucket = m.get('bucket', 'client')
        by_day[bucket][day] += 1
        by_pair[bucket][f'{names[b.client_id]} → {m["looks_like_client_name"]}'] += 1
        counts[bucket] += 1
        if len(flagged[bucket]) < limit:
            flagged[bucket].append({
                **_base_row(b, oid, names, day),
                'looks_like_client_id': m['looks_like_client_id'],
                'looks_like_client_name': m['looks_like_client_name'],
                'bucket': bucket,
                'confidence': {
                    'looks_like_coverage': m['looks_like_coverage'],
                    'abs_hit': m['looks_like_abs_hit'],
                    'booked_coverage': m['booked_coverage'],
                    'top_token_weight': m['top_token_weight'],
                },
            })

    # pk-desc paging is only ~chronological (backfills and late syncs land out
    # of order), so sort the sample the UI shows by the block's own date.
    for rows in flagged.values():
        rows.sort(key=lambda r: (r['date'], r['block_id']), reverse=True)

    return {
        'scanned': scanned,
        'dismissed_hits': dismissed_hits,
        'flagged': flagged,
        'by_day': by_day,
        'by_pair': by_pair,
        'counts': counts,
    }


def bucket_payload(result, bucket, pair_limit=25):
    """Shape one bucket of a `scan_buckets` result into the API response body."""
    d = result['by_day'][bucket]
    pairs = sorted(
        ({'pair': k, 'count': v} for k, v in result['by_pair'][bucket].items()),
        key=lambda x: -x['count'],
    )[:pair_limit]
    return {
        'total': result['counts'][bucket],
        'returned': len(result['flagged'][bucket]),
        'histogram': [{'date': k, 'count': d[k]} for k in sorted(d.keys())],
        'top_pairs': pairs,
        'mismatches': result['flagged'][bucket],
    }


def week_has_client_misfiles(org, user, week_start):
    """
    Does this person's CONFIRMED time for that week contain a block whose title
    distinctively names a different business client than it is booked to?

    Used to decide whether an owner's timesheet may auto-approve. Deliberately
    the CLIENT bucket only — the money bucket. Internal/admin disagreements and
    same-family ties are real but are not reasons to hold a week: a gate that
    fires often is a gate people learn to route around.

    High precision by construction: org 21 sees roughly 0-4 client-bucket rows
    across 8,500 blocks in 90 days, so this is expected to almost never fire.
    When it does, a client was about to be billed for another client's work.
    """
    from datetime import timedelta

    from tracker.services.billing_totals import committed_block_qs
    from tracker.views_reports import _day_bounds_utc

    start_utc, end_utc = _day_bounds_utc(week_start, week_start + timedelta(days=6))
    blocks = (
        committed_block_qs(org, start_utc, end_utc, user_id=user.id, can_see_all=False)
        .filter(client_id__isnull=False)
        .exclude(window_title__isnull=True)
        .exclude(window_title='')
        .select_related('client', 'user', 'org')
    )

    names_by_org, index_by_org, firm_by_org = _indexes_for_orgs([org.id])
    result = scan_buckets(
        blocks, names_by_org, index_by_org, firm_by_org,
        limit=1,                                  # existence, not a list
        skip_block_ids=confirmed_correct_block_ids([org.id]),
    )
    return result['counts']['client'] > 0
