"""
Management command: heal_false_ambiguity

Retracts Stage-11 "which of these clients?" questions that were never real
questions, on blocks that already carry the signal.

Two kinds, both fixed at the source in the classifier — this only cleans up
what is already in the queue, since a stored signal is a snapshot and nothing
re-asks it:

  SETTLED   The block committed to NO client and was already filed
            non-billable (personal browsing, overhead). The gate demoted that
            commit to a proposal and flagged it for review, so a Pandora tab
            titled "Listen to Your Favorite Music, Podcasts, and Radio Stations
            for Free!" asked which of two clients with "Music" in their names
            it belonged to. The signal is dropped and the non-billable commit
            is restored.

  NOT A FAMILY
            The candidates share one everyday word and nothing else —
            "Homepage - Tarbell Management Group" against two unrelated firms
            whose names contain "Management". The signal is dropped; the
            block's client and state are left exactly as they are, so it
            reverts to whatever it was before the question was asked.

Never touches a block a human decided (categorized_by manual/correction), and
never changes which client a block is on.

    # Preview (writes nothing) — this is the default
    python manage.py heal_false_ambiguity --org-id 21 --days 30

    # Apply
    python manage.py heal_false_ambiguity --org-id 21 --days 30 --apply
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tracker.utils.db_iter import keyset_chunks

SIGNAL_TYPE = 'family_ambiguous'

# Signals that mean the classifier had already decided this block was nobody's
# billable work. Both auto-commit in the safe direction; see FIX 6 in
# ClassificationService._finalize_decision.
SETTLED_TYPES = {'personal_browsing', 'overhead_auto_nonbillable'}


class Command(BaseCommand):
    help = ("Retract Stage-11 look-alike questions that are not real "
            "questions. Dry-run by default; use --apply to write.")

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--org-id", type=int)
        group.add_argument("--org-slug", type=str)
        parser.add_argument("--days", type=int, default=30,
                            help="Look back this many days (default 30).")
        parser.add_argument("--apply", action="store_true",
                            help="Persist the retractions. Without this, dry-run.")

    def handle(self, *args, **opts):
        from tracker.models import Block, Organization
        from tracker.services import client_families

        if opts.get("org_id") is not None:
            try:
                org = Organization.objects.get(pk=opts["org_id"])
            except Organization.DoesNotExist:
                raise CommandError(f"No org with id={opts['org_id']}")
        else:
            try:
                org = Organization.objects.get(slug=opts["org_slug"])
            except Organization.DoesNotExist:
                raise CommandError(f"No org with slug={opts['org_slug']!r}")

        apply_writes = bool(opts["apply"])
        since = timezone.now() - timedelta(days=opts["days"])
        roster = client_families.for_org(org.pk, use_cache=False)

        blocks = Block.objects.filter(
            org=org, deleted_at__isnull=True, start__gte=since,
            classification_state__in=('proposed', 'captured'),
        ).exclude(categorized_by__in=('manual', 'correction'))

        settled, not_family, kept = [], [], 0
        # keyset paging, not .iterator(): Neon's pooler invalidates a named
        # server-side cursor the moment this loop writes.
        for page in keyset_chunks(blocks, chunk_size=500):
            for b in page:
                sigs = [s for s in (b.proposed_signals or []) if isinstance(s, dict)]
                if not any(s.get('type') == SIGNAL_TYPE for s in sigs):
                    continue
                if not b.client_id and any(s.get('type') in SETTLED_TYPES
                                           for s in sigs):
                    settled.append(b)
                    continue
                words = client_families.text_words(
                    b.window_title or b.title or '',
                    getattr(b, 'file_path', '') or '',
                    getattr(b, 'url', '') or '')
                if len(roster.family_for(words)) < 2:
                    not_family.append(b)
                else:
                    kept += 1

        def _mins(rows):
            return sum(r.minutes or 0 for r in rows)

        w = self.stdout.write
        w(f"org {org.pk} ({org.name}) — last {opts['days']} days")
        w(f"  settled non-billable, wrongly re-opened : "
          f"{len(settled):4d} blocks {_mins(settled):5d} min")
        w(f"  candidates were never a look-alike family: "
          f"{len(not_family):4d} blocks {_mins(not_family):5d} min")
        w(f"  real questions, left alone               : {kept:4d} blocks")

        for label, rows in (("SETTLED", settled), ("NOT A FAMILY", not_family)):
            for b in rows[:15]:
                w(f"    {label:12s} {b.pk:7d} {(b.window_title or '')[:70]}")
            if len(rows) > 15:
                w(f"    {label:12s} ... and {len(rows) - 15} more")

        if not apply_writes:
            w(self.style.WARNING("\nDRY RUN — nothing written. Re-run with --apply."))
            return

        def _strip(block):
            block.proposed_signals = [
                s for s in (block.proposed_signals or [])
                if not (isinstance(s, dict) and s.get('type') == SIGNAL_TYPE)
            ]

        with transaction.atomic():
            for b in not_family:
                # Only the question goes. Whatever the block was attributed to
                # before the gate spoke, it stays attributed to.
                _strip(b)
                b.save(update_fields=['proposed_signals'], force_classifier=True)

            for b in settled:
                # Put back the commit the gate demoted. Client and category are
                # already right — the block was filed Personal/Non-Billable and
                # then re-opened — so this only restores the state that keeps it
                # out of the review queue.
                _strip(b)
                b.classification_state = 'committed'
                b.is_categorized = True
                b.is_billable = False
                b.needs_review = False
                b.review_reason = ''
                b.state_changed_at = timezone.now()
                b.state_changed_by = 'classifier'
                b.save(update_fields=[
                    'proposed_signals', 'classification_state', 'is_categorized',
                    'is_billable', 'needs_review', 'review_reason',
                    'state_changed_at', 'state_changed_by',
                ], force_classifier=True)

        w(self.style.SUCCESS(
            f"\nApplied: {len(settled)} re-committed non-billable, "
            f"{len(not_family)} questions retracted."))
