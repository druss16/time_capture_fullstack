"""
Re-open blocks that were auto-filed as No-Client / non-billable while they were
still sub-2-minute slivers, and then GREW.

The pathology (fixed go-forward in compaction._should_reclassify_on_merge):

  1. compaction creates a block ~30 seconds into an activity and classifies it
     immediately. No client matched yet — the representative title may still be
     "Untitled - Message (HTML)".
  2. under 2 minutes, so the immaterial rule (ClassificationService's finalize
     gate) COMMITS it as No-Client / Personal-Non-Billable rather than leaving a
     sliver to nag in "Needs you".
  3. more events merge in. start / end / minutes / window_title are rewritten,
     the category is rescaled to the new duration — but nothing re-classifies a
     committed block, and every safety net downstream skips it for being
     committed (second_pass scans captured/proposed; the mismatch scan requires
     a booked client; auto_categorize_block early-returns on is_categorized).

Result: a 13-minute Outlook thread plainly titled "RE: From Odett at Christ Our
Light" filed as non-billable overhead, invisible in Daily Review's "Needs you".

This command finds that pile and re-asks the question. Anything that resolves to
a client is written as a PROPOSAL (is_billable=False, state='proposed'), never a
commit — a human confirms it in Daily Review. Blocks that still resolve to
nobody are left exactly as they are.

Usage:
  # Dry run (default)
  python manage.py reopen_stranded_slivers --org-id 21 --start 2026-08-04

  # Apply
  python manage.py reopen_stranded_slivers --org-id 21 --start 2026-08-04 --apply
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tracker.models import Block, ClassificationAudit, Client
from tracker.services.classification_service import (
    ClassificationService, IMMATERIAL_MAX_MINUTES,
)

SKIP_CATEGORIZED_BY = ('manual', 'correction')
SKIP_STATE_CHANGED_BY = ('user', 'user_edit', 'correction')

# The signal the immaterial no-client auto-commit stamps on its audit row. Only
# blocks carrying it are in scope — a no-client block that reached the same
# state some other way was judged on its full length and is not this bug.
IMMATERIAL_SIGNAL = 'auto_confirm_immaterial_noclient'


class Command(BaseCommand):
    help = ("Re-classify no-client blocks that were auto-filed as sub-2-minute "
            "slivers and later grew; surface any client as a proposal.")

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None)
        parser.add_argument('--user-id', type=int, default=None)
        parser.add_argument('--start', type=str, default=None, help='day >= this (YYYY-MM-DD)')
        parser.add_argument('--end', type=str, default=None, help='day <= this (YYYY-MM-DD)')
        parser.add_argument('--limit', type=int, default=None)
        parser.add_argument('--with-ai', action='store_true',
                            help='Let the classifier call the AI stage too (costs tokens). '
                                 'Default is deterministic stages only.')
        parser.add_argument('--apply', action='store_true',
                            help='Write changes. Omit for a dry run (default).')

    def _candidates(self, opts):
        qs = Block.objects.filter(
            classification_state='committed',
            client__isnull=True,
            deleted_at__isnull=True,
            minutes__gte=IMMATERIAL_MAX_MINUTES,
            invoiced=False,
        ).exclude(
            bundle_id__iexact='__idle__',
        ).exclude(
            categorized_by__in=SKIP_CATEGORIZED_BY,
        ).exclude(
            state_changed_by__in=SKIP_STATE_CHANGED_BY,
        ).exclude(window_title='')
        if opts.get('org_id'):
            qs = qs.filter(org_id=opts['org_id'])
        if opts.get('user_id'):
            qs = qs.filter(user_id=opts['user_id'])
        if opts.get('start'):
            qs = qs.filter(day__gte=opts['start'])
        if opts.get('end'):
            qs = qs.filter(day__lte=opts['end'])
        blocks = list(qs.select_related('org', 'user').order_by('-minutes'))

        # Keep only the ones the immaterial rule filed. The FIRST audit row is
        # the original verdict; later rows are re-runs or human edits.
        first_audit = {}
        for a in ClassificationAudit.objects.filter(
            block_id__in=[b.id for b in blocks]
        ).order_by('id').only('block_id', 'matched_signals'):
            first_audit.setdefault(a.block_id, a)
        out = []
        for b in blocks:
            a = first_audit.get(b.id)
            if not a:
                continue
            if any((s or {}).get('type') == IMMATERIAL_SIGNAL
                   for s in (a.matched_signals or [])):
                out.append(b)
        if opts.get('limit'):
            out = out[:opts['limit']]
        return out

    def handle(self, *args, **opts):
        apply_changes = opts['apply']
        skip_ai = not opts['with_ai']
        blocks = self._candidates(opts)

        self.stdout.write(
            f"{len(blocks)} block(s) auto-filed as no-client slivers that later grew "
            f"to >= {IMMATERIAL_MAX_MINUTES} min"
        )
        if not blocks:
            return

        services = {}
        resolved, unresolved, failed = [], 0, 0
        for b in blocks:
            svc = services.get((b.org_id, b.user_id))
            if svc is None:
                svc = services[(b.org_id, b.user_id)] = ClassificationService(
                    org=b.org, user=b.user
                )
            try:
                decision = svc.classify(b, skip_ai=skip_ai)
            except Exception as e:
                failed += 1
                self.stderr.write(f"  block {b.id}: classify failed — {e}")
                continue
            if not decision.client_id:
                unresolved += 1
                continue
            resolved.append((b, decision))

        names = dict(
            Client.objects.filter(id__in={d.client_id for _, d in resolved})
            .values_list('id', 'name')
        )
        for b, d in resolved:
            name = names.get(d.client_id, d.client_id)
            self.stdout.write(
                f"  #{b.id} {b.day} u{b.user_id} {b.minutes:>4}m "
                f"{(b.window_title or '')[:52]!r} -> propose {name} @ {d.confidence:.2f}"
            )

        total_min = sum(b.minutes or 0 for b, _ in resolved)
        self.stdout.write(
            f"\n{len(resolved)} would become proposals ({total_min} min), "
            f"{unresolved} still resolve to nobody (left alone), {failed} errored"
        )

        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written. Re-run with --apply."))
            return

        written = 0
        with transaction.atomic():
            for b, d in resolved:
                # PROPOSAL only. The classifier's own finalize gate may well say
                # "committed" now that the block is material, but this is a
                # retroactive sweep over time already filed as non-billable —
                # every one of these gets a human's eyes in Daily Review before
                # it can bill.
                b.proposed_client_id = d.client_id
                b.proposed_confidence = d.confidence
                b.proposed_reasoning = (
                    'reopened: auto-filed as a sub-2min sliver, grew to '
                    f'{b.minutes}m — {"; ".join(s.evidence for s in d.matched_signals)[:400]}'
                )
                b.client = None
                b.is_billable = False
                b.is_categorized = False
                b.classification_state = 'proposed'
                b.state_changed_at = timezone.now()
                b.state_changed_by = 'classifier'
                b.category_hours = {}
                b.save(force_update=True)
                written += 1
        self.stdout.write(self.style.SUCCESS(f"Wrote {written} proposal(s)."))
