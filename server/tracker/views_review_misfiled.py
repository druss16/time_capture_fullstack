# tracker/views_review_misfiled.py
"""
"Check for misfiled time" — the firm-facing mismatch sweep in Approvals.

Managers and owners approve a week of somebody else's time without ever having
seen the windows it came from. The Certain bucket is the dangerous half of that
week: it is time the classifier committed on its own and nothing re-examines
after the fact, so a block sitting on the wrong client is silent right up until
the client is billed for it. Daily Review's mismatch lane looks for exactly this
— but only at the reviewer's OWN blocks, one day at a time.

This is that same detector pointed at the whole week a manager is about to
approve, for every person in the queue. It runs
`services/mismatch_scan.scan_buckets`, the identical core behind the MavOps
Mismatches tab, so a firm and MavOps looking at the same org see the same
verdicts.

Detection is read-only. Every fix is a deliberate action a person takes on
`/api/review/misfiled/resolve/`.
"""
from datetime import timedelta
from itertools import chain

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication
from tracker.models import (
    Block, Client, ClassificationAudit, MismatchFlag,
    OrganizationMembership, Timesheet,
)
from tracker.services.billing_totals import committed_block_qs
from tracker.services.mismatch_scan import (
    build_indexes, bucket_payload, confirmed_correct_block_ids, scan_buckets,
)
from tracker.views_reports import _day_bounds_utc
from tracker.views_billing import get_request_org_override_billing

# Roles that may review other people's time. Same list the approval queue
# itself enforces — this panel lives on that tab and must not be a way around
# it. A member has no route here: their own misfiled time is Daily Review's job.
REVIEWER_ROLES = ('owner', 'admin', 'manager')

# Statuses whose time is still the reviewer's to change. Once a week is
# approved or locked it has gone downstream (invoice, Clio push), and quietly
# moving a block afterwards would disagree with what was already sent.
OPEN_STATUSES = ('draft', 'submitted', 'rejected')

MAX_BLOCKS_PER_CALL = 500


def _monday(block):
    """The Monday of the week a block falls in — the key Timesheet.week_start uses."""
    d = block.day or timezone.localtime(block.start).date()
    return d - timedelta(days=d.weekday())


def _reviewer_org(request):
    """(org, error_response). Resolves the org and enforces reviewer role."""
    org = get_request_org_override_billing(request)
    if not org:
        return None, Response({'error': 'No organization'}, status=400)

    if request.user.is_staff or request.user.is_superuser:
        return org, None

    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    if not membership or membership.role not in REVIEWER_ROLES:
        return None, Response(
            {'error': 'Only owners, admins and managers can review other people\'s time.'},
            status=403,
        )
    return org, None


# What a `scope` value covers. Default is `queue` — the weeks actually awaiting
# approval — because the panel sits directly above the approval table and has to
# describe THAT list. Scoping wider was tried and read as a bug: the panel
# reported 4 findings while the six timesheets listed beneath it had none,
# because every finding sat in a draft week nobody had submitted yet.
#
# Nothing is lost by the narrower scope. The detector is stateless and re-runs
# from scratch, so a misfile sitting in a draft week today is flagged the moment
# that week is submitted — which is the moment a manager can act on it. Approved
# and locked weeks stay out entirely, and writes to them are refused.
# This panel exists to check the timecards sitting in the approval queue, and
# nothing else. Weeks still in progress are not the reviewer's to approve, and
# scanning them made the panel report findings against a list it was not
# describing — "4 to review" above six clean timesheets.
#
# `open` and `all` are kept for support and diagnostics only; the product never
# asks for them.
SCOPES = {
    'queue': ('submitted',),
    'open': ('submitted', 'draft'),
    'all': ('submitted', 'draft', 'rejected', 'approved'),
}


def _timesheets_in_scope(request, org):
    """The timesheets this sweep covers.

    `timesheet_id` → that one week (the row the manager clicked into).
    Otherwise → every week in `scope`, newest first.
    """
    qs = Timesheet.objects.filter(org=org).select_related('user')
    tid = request.GET.get('timesheet_id') or (
        request.data.get('timesheet_id') if hasattr(request, 'data') else None
    )
    if tid:
        try:
            return qs.filter(id=int(tid))
        except (TypeError, ValueError):
            return qs.none()

    scope = (request.GET.get('scope') or 'queue').strip()
    statuses = SCOPES.get(scope, SCOPES['queue'])
    return qs.filter(status__in=statuses).order_by('-week_start')


@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def review_misfiled_time(request):
    """
    GET /api/review/misfiled/
      ?timesheet_id=<id>   (optional — one week; default: the whole approval queue)
      &limit=<int>         (max flagged rows per bucket; default 200, max 1000)

    Sweeps the committed time on those weeks and returns three verdicts:

      client   — the title distinctively names a DIFFERENT business client than
                 the block is booked to. One nameable target, so one click fixes
                 it. This is the bucket that costs money.
      internal — the same disagreement against a firm/admin bucket. Worth a
                 glance, never a billing error, so it is collapsed by default.
      unsure   — the booked client is absent from the block's own title but
                 same-family rivals tie. Carries ranked `candidates` and no
                 auto-fix, because the tie is the point.

    Also returns `by_timesheet`, so each row in the approval queue can carry its
    own count before anyone clicks Approve.
    """
    org, err = _reviewer_org(request)
    if err:
        return err

    try:
        limit = min(max(int(request.GET.get('limit', 200)), 1), 1000)
    except (TypeError, ValueError):
        limit = 200

    sheets = list(_timesheets_in_scope(request, org))
    sheet_by_id = {t.id: t for t in sheets}

    names_by_org, index_by_org, firm_by_org = build_indexes([org.id])

    # Scope = each reviewee's WEEK, not Block.timesheet. The FK looks like the
    # precise choice and is the wrong one: on real data it is null on most
    # blocks (org 21: 22k unlinked vs 7k linked, and every currently-flagged
    # block is unlinked), because linkage happens at submission and anything
    # captured after — or in a week nobody has submitted yet — never gets it.
    # Scoping by it produced an empty panel over weeks that genuinely contained
    # misfiled time. The week is also what a manager means by "review Emily's
    # week", so it is the honest unit.
    #
    # committed_block_qs is the same confirmed-time queryset Reports and Daily
    # Review count, which is exactly the Certain bucket: filed by the classifier,
    # never re-examined after its verdict. Proposed blocks are deliberately out
    # — those are still sitting in the person's own Needs-you lane.
    per_week, uncommitted, uncommitted_min = [], 0, 0
    unconfirmed_blocks = []
    for t in sheets:
        start_utc, end_utc = _day_bounds_utc(t.week_start, t.week_start + timedelta(days=6))
        qs = (
            committed_block_qs(org, start_utc, end_utc,
                               user_id=t.user_id, can_see_all=False)
            .filter(client_id__isnull=False)
            .exclude(window_title__isnull=True)
            .exclude(window_title='')
            .select_related('client', 'user', 'org')
            .order_by('-start')
        )
        # Stamp the owning week onto each block so the flagged row can name it
        # without a second pass — the FK can't be trusted to do it.
        for b in qs:
            b._review_timesheet_id = t.id
            per_week.append(b)
        # The same week's UNCONFIRMED time. Nobody has accepted these yet, so
        # they are not what a manager is approving — but a wrong client on one
        # is not harmless either: if the person never opens Daily Review it
        # sits there forever, which is how time strands. Scanned separately and
        # reported separately, never mixed into the confirmed counts.
        unconf_qs = (
            Block.objects
            .filter(org=org, user_id=t.user_id, deleted_at__isnull=True,
                    start__gte=start_utc, start__lt=end_utc, is_categorized=False)
            .exclude(classification_state='suppressed')
            .select_related('client', 'user', 'org', 'proposed_client')
        )
        for b in unconf_qs:
            uncommitted += 1
            uncommitted_min += b.minutes or 0
            if b.client_id and b.window_title:
                b._review_timesheet_id = t.id
                unconfirmed_blocks.append(b)

    result = scan_buckets(
        chain(per_week), names_by_org, index_by_org, firm_by_org,
        limit=limit,
        # A judgement someone already made stays made. Without this the panel
        # asks the same question every Monday and stops being read.
        skip_block_ids=confirmed_correct_block_ids([org.id]),
    )

    # Same detector, same thresholds — only the input differs. A row here means
    # the title contradicts the client even though nobody has confirmed it yet.
    unconf = scan_buckets(
        unconfirmed_blocks, names_by_org, index_by_org, firm_by_org,
        limit=limit,
        skip_block_ids=confirmed_correct_block_ids([org.id]),
    )

    # Where the classifier has ALREADY staged a fix, that proposal is the answer
    # and the row's one-click action should simply accept it, rather than making
    # a manager re-derive what the system already worked out.
    _unconf_by_id = {b.id: b for b in unconfirmed_blocks}
    unconfirmed_rows = []
    for _bucket in ('client', 'unsure'):
        for r in unconf['flagged'][_bucket]:
            b = _unconf_by_id.get(r['block_id'])
            if b is not None and b.proposed_client_id and b.proposed_client_id != b.client_id:
                r['proposed_client_id'] = b.proposed_client_id
                r['proposed_client_name'] = b.proposed_client.name if b.proposed_client_id else None
                r['proposed_confidence'] = float(getattr(b, 'proposed_confidence', 0.0) or 0.0)
            r['confirmed'] = False
            unconfirmed_rows.append(r)
    unconfirmed_rows.sort(key=lambda r: (r['date'], r['block_id']), reverse=True)

    # Per-timesheet counts for the queue badges. Counted off the CLIENT bucket
    # only: an internal-bucket row is not a reason to hold up an approval, and a
    # badge that cries wolf gets ignored along with the ones that don't.
    by_timesheet = {}
    for row in result['flagged']['client']:
        tid = row.get('timesheet_id')
        if tid is None:
            continue
        b = by_timesheet.setdefault(str(tid), {'count': 0, 'minutes': 0})
        b['count'] += 1
        b['minutes'] += row.get('minutes') or 0

    return Response({
        'params': {
            'org_id': org.id,
            'scope': (request.GET.get('scope') or 'queue'),
            'timesheet_ids': list(sheet_by_id.keys()),
            'limit': limit,
        },
        'weeks': [{
            'timesheet_id': t.id,
            'user_id': t.user_id,
            'user_name': (f"{t.user.first_name} {t.user.last_name}".strip()
                          or t.user.username) if t.user_id else None,
            'week_start': t.week_start.isoformat(),
            'status': t.status,
            # Whether a fix is still allowed here, so the UI can show the row
            # without offering a button that would only 400.
            'editable': t.status in OPEN_STATUSES,
        } for t in sheets],
        'scanned_blocks': result['scanned'],
        # Visible rather than silent: a growing number means either the detector
        # keeps raising the same false alarm or someone is waving away real
        # errors, and both are worth being able to see.
        'dismissed_blocks': result['dismissed_hits'],
        'by_timesheet': by_timesheet,
        # Not a mismatch in confirmed time, but it belongs next to one: the
        # blocks nobody has accepted yet whose title already contradicts the
        # client they are sitting on. `blocks`/`minutes` size the whole
        # unconfirmed pile these weeks carry, flagged or not.
        'unconfirmed': {
            'total': unconf['counts']['client'] + unconf['counts']['unsure'],
            'returned': len(unconfirmed_rows),
            'histogram': [],
            'top_pairs': [],
            'mismatches': unconfirmed_rows,
            'blocks': uncommitted,
            'minutes': uncommitted_min,
        },
        'uncommitted_blocks': uncommitted,
        'client': bucket_payload(result, 'client'),
        'internal': bucket_payload(result, 'internal'),
        'unsure': bucket_payload(result, 'unsure'),
        # The roster for the "move to…" picker, so resolving a tie doesn't cost
        # a second round trip on a panel people open and close quickly.
        'clients': [
            {'id': c.id, 'name': c.name}
            for c in Client.objects.filter(org=org).only('id', 'name').order_by('name')
        ],
    })


@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def review_misfiled_resolve(request):
    """
    POST /api/review/misfiled/resolve/
      body: {
        "block_ids": [123, 456],
        "action": "move" | "correct" | "reopen",
        "client_id": 169          (required for "move")
      }

    move    — put these blocks on the client the reviewer named. The id they
              send is the authority: this endpoint never re-derives a target
              from the title, because the rows that most need a human are
              precisely the ones the matcher could not call. The block is
              stamped human-set, which takes it out of the accuracy sample (we
              measure our own filing, not someone's judgement) and stops the
              scan re-raising what a person already settled.
    correct — "this is actually right." Records a resolved MismatchFlag and
              touches nothing on the block, so the row stops coming back.
    reopen  — undo a "correct". "It's right" is one click on a dense list and
              will get mis-clicked; without a way back the only route is a
              hand-written database delete.
    """
    block_ids = request.data.get('block_ids') or []

    # Reviewing OTHER people's time needs a reviewer role. Fixing your OWN needs
    # nothing — it is your time, you are the one who knows which client it was,
    # and making a member leave the page to correct their own block is the
    # friction that stops anyone correcting anything. So: reviewer role, OR
    # every targeted block belongs to the requester.
    org, err = _reviewer_org(request)
    if err:
        if not isinstance(block_ids, list) or not block_ids:
            return err
        own = set(
            Block.objects
            .filter(id__in=block_ids, user=request.user, deleted_at__isnull=True)
            .values_list('id', flat=True)
        )
        if own != set(block_ids):
            return err
        membership = (OrganizationMembership.objects
                      .filter(user=request.user).select_related('organization').first())
        if not membership:
            return err
        org = membership.organization

    action = (request.data.get('action') or '').strip()
    client_id = request.data.get('client_id')

    if action not in ('move', 'correct', 'reopen'):
        return Response({'error': "action must be 'move', 'correct' or 'reopen'."}, status=400)
    if not isinstance(block_ids, list) or not block_ids:
        return Response({'error': 'block_ids (non-empty list) is required.'}, status=400)
    if len(block_ids) > MAX_BLOCKS_PER_CALL:
        return Response(
            {'error': f'Too many blocks (max {MAX_BLOCKS_PER_CALL} per call).'}, status=400
        )

    if action == 'reopen':
        deleted, _ = (MismatchFlag.objects
                      .filter(org=org, block_id__in=block_ids,
                              resolved_reason='confirmed_correct')
                      .delete())
        return Response({'action': 'reopen', 'restored': deleted})

    # Org-scoped fetch: block_ids come off a page, so they are never trusted to
    # belong here.
    blocks = list(
        Block.objects
        .filter(id__in=block_ids, org=org, deleted_at__isnull=True)
        .select_related('client')
    )

    if action == 'correct':
        dismissed = 0
        for b in blocks:
            _resolve_flag(
                b, org, reason='confirmed_correct',
                title_client_id=None, title_client_name='', score=0.0,
            )
            dismissed += 1
        return Response({'action': 'correct', 'dismissed': dismissed})

    # ── move ────────────────────────────────────────────────────────────────
    if not client_id:
        return Response(
            {'error': 'client_id is required — this endpoint does not guess.'}, status=400
        )
    target = Client.objects.filter(id=client_id, org=org).only('id', 'name').first()
    if not target:
        return Response({'error': 'client_id does not belong to this organization.'}, status=404)

    # Which week each block sits in, resolved by (user, Monday) rather than
    # Block.timesheet — that FK is null on most blocks, so trusting it here
    # would wave through edits to weeks that are already approved.
    status_by_week = {
        (t.user_id, t.week_start): t.status
        for t in Timesheet.objects.filter(
            org=org,
            week_start__in={_monday(b) for b in blocks if b.user_id},
        ).only('user_id', 'week_start', 'status')
    }

    planned, skipped = [], []
    for b in blocks:
        # Same refusal as splitting: once time is invoiced or pushed to a
        # billing system, moving it here would silently disagree with what the
        # client was already billed.
        if b.invoiced or getattr(b, 'qb_time_activity_id', None) or getattr(b, 'xero_invoice_id', None):
            skipped.append({'block_id': b.id, 'reason': 'already invoiced or synced to billing'})
            continue
        week_status = status_by_week.get((b.user_id, _monday(b)))
        if week_status and week_status not in OPEN_STATUSES:
            skipped.append({
                'block_id': b.id,
                'reason': f'week is {week_status} — reopen it to make changes',
            })
            continue
        if b.client_id == target.id:
            skipped.append({'block_id': b.id, 'reason': 'already on that client'})
            continue
        planned.append(b)

    from tracker.services.classification_service import ClassificationService

    changed = 0
    with transaction.atomic():
        # Re-fetch for update so two reviewers on the same queue can't race.
        ids = [b.id for b in planned]
        was_on = {b.id: (b.client_id, b.client.name if b.client_id else None) for b in planned}
        for b in Block.objects.select_for_update().filter(id__in=ids):
            old_client_id, old_client_name = was_on.get(b.id, (b.client_id, None))
            cat_before = ClassificationService._extract_dominant_category(b)

            b.client_id = target.id
            # A person settled this, so record it as such: the heal commands,
            # the mismatch scan and the accuracy sampler all key off these.
            b.state_changed_by = 'correction'
            b.state_changed_at = timezone.now()
            b.categorized_by = 'correction'
            b.save(
                update_fields=['client_id', 'state_changed_by',
                               'state_changed_at', 'categorized_by'],
                force_classifier=True,
            )

            ClassificationAudit.objects.create(
                block=b, source='manual',
                client_before_id=old_client_id, client_after_id=target.id,
                category_before=cat_before,
                category_after=ClassificationService._extract_dominant_category(b),
                confidence_client=1.0, confidence_category=1.0, overall_confidence=1.0,
                matched_signals=[{
                    'type': 'review_misfiled_move',
                    'strength': 1.0,
                    'evidence': (
                        f"{request.user.get_username()} moved this to {target.name!r} "
                        f"while reviewing timesheets (was {old_client_name!r})."
                    ),
                    'detail': (b.window_title or '')[:200],
                }],
                corrected_by_user=True,
            )

            _resolve_flag(
                b, org, reason='reconciled',
                title_client_id=target.id, title_client_name=target.name, score=1.0,
                booked_client_id=old_client_id,
            )
            changed += 1

    return Response({
        'action': 'move',
        'moved': changed,
        'skipped': len(skipped),
        'skips': skipped[:100],
        'to_client_name': target.name,
    })


def _resolve_flag(block, org, *, reason, title_client_id, title_client_name,
                  score, booked_client_id=None):
    """Close the loop in MismatchFlag so the history table sees this decision.

    Upsert: if the nightly scan already opened a flag for this block, resolve
    THAT one; otherwise write a resolved flag directly. One row per open
    occurrence, which is what the partial-unique (open) constraint allows.
    """
    booked = booked_client_id if booked_client_id is not None else block.client_id
    if booked is None:
        # booked_client is a required FK. A block with nobody on it can't be a
        # "booked to the wrong client" record, so there is nothing to write.
        return

    existing = MismatchFlag.objects.filter(block=block, resolved_at__isnull=True).first()
    if existing:
        existing.resolved_at = timezone.now()
        existing.resolved_reason = reason
        existing.save(update_fields=['resolved_at', 'resolved_reason'])
        return

    MismatchFlag.objects.create(
        org=org,
        block=block,
        # The client it was on when the reviewer looked at it — for a move that
        # is the OLD one, which the caller passes because the block has already
        # been reassigned by the time we get here.
        booked_client_id=booked,
        title_client_id=title_client_id,
        title_client_name=title_client_name,
        bucket='client',
        match_score=score,
        window_title=(block.window_title or '')[:512],
        resolved_at=timezone.now(),
        resolved_reason=reason,
    )
