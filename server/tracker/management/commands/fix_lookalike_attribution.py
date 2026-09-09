"""
Management command: repair look-alike client attribution over a date range.

Two separate jobs, because they have very different costs:

  CORRECT   Blocks the improved matcher now reads differently. "St. Patrick's
            Church-Taberg" used to book to client 130 (which is named the bare
            "St. Patrick's Church" and swallowed its own sibling); it now books
            to 392. Deterministic, no human needed — the title names the parish
            outright, we were just reading it wrong.

  REOPEN    Blocks nothing can identify. A bare "St. Mary's Church" QuickBooks
            title fits a dozen parishes; whatever picked one did so with no
            evidence. These go back to `proposed` carrying their candidates, so
            Daily Review can ask. This COSTS review time, so it is opt-in.

Human decisions are never touched. A block a person filed or corrected is the
ground truth this whole system is trying to reach — re-deciding it would be the
worst bug in here.

Dry run by default. Nothing is written without --apply.

Usage:
  python manage.py fix_lookalike_attribution --org 21 --since 2026-07-01
  python manage.py fix_lookalike_attribution --org 21 --since 2026-07-01 --apply
  python manage.py fix_lookalike_attribution --org 21 --since 2026-07-01 \\
      --reopen-ambiguous --apply
"""
from collections import Counter, defaultdict
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import Block, Client
from tracker.services import client_families
from tracker.services.classification_service import (
    DOMAIN_COMMON_WORDS,
    EXCLUSIVE_ENTITY_CLASSES,
    ClassificationService,
    _canonical_entity_tokens,
)

# A block whose client a PERSON chose. Never re-decide these.
#
# `approved_by` counts too, and is checked separately: org 21 has 28,813
# approved blocks — essentially the whole dataset — because approval is mostly
# applied in bulk with no approver recorded. So `approved` alone does NOT mean
# a human vouched for the client, but a NAMED approver does.
HUMAN_SOURCES = {'manual', 'correction', 'user_edit', 'user'}

# Signals that identify a client on their own — mirrors the Stage-11 gate, so a
# reopen here can never contradict what the live classifier would decide.
IDENTIFYING = ClassificationService.IDENTIFYING_EVIDENCE_TYPES

AMBIGUOUS_SIGNAL = 'family_ambiguous'


class Command(BaseCommand):
    help = "Repair look-alike client attribution (St. Mary's, St. Patrick's, …) over a date range."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--since', required=True, help='YYYY-MM-DD (inclusive)')
        parser.add_argument('--until', default=None, help='YYYY-MM-DD (inclusive); default today')
        parser.add_argument('--apply', action='store_true', help='Write changes (default: dry run)')
        parser.add_argument('--reopen-ambiguous', action='store_true',
                            help='Also send un-identifiable blocks back to `proposed` for review')
        parser.add_argument('--limit', type=int, default=0, help='Cap blocks scanned (debugging)')

    def handle(self, *args, **opts):
        org_id = opts['org']
        since = datetime.strptime(opts['since'], '%Y-%m-%d').date()
        until = (datetime.strptime(opts['until'], '%Y-%m-%d').date()
                 if opts['until'] else None)
        apply_changes = opts['apply']

        lookalikes = client_families.for_org(org_id, use_cache=False)
        names = {c.id: c.name for c in Client.objects.filter(org_id=org_id).only('id', 'name')}

        qs = Block.objects.filter(org_id=org_id, day__gte=since, client__isnull=False)
        if until:
            qs = qs.filter(day__lte=until)
        qs = qs.exclude(classification_state='rejected').order_by('id')
        if opts['limit']:
            qs = qs[:opts['limit']]
        blocks = list(qs)

        corrections, reopens = [], []
        skipped_human = 0

        for block in blocks:
            if ((block.state_changed_by or '') in HUMAN_SOURCES
                    or block.approved_by_id is not None):
                skipped_human += 1
                continue

            words = client_families.text_words(
                block.window_title or block.title or '',
                block.file_path or '',
                block.url or '',
            )
            resolved = lookalikes.resolve(words)

            # CORRECT: the text names one client outright and it isn't this one.
            #
            # Restricted to a swap BETWEEN LOOK-ALIKES. resolve() answers "given
            # this is one of these, which one" — it is not a general "who is
            # this" matcher, and using it as one re-attributes wildly: an early
            # version of this command wanted to move 48 hours from Internal-Tax
            # to a client whose name appeared in an UltraTax title, and to send
            # "Assumption Church" work to "Revive Hope and Healing Ministries"
            # because one title contained a word from each. Requiring the two
            # clients to be confusable with EACH OTHER keeps this to what it is
            # for: St. Patrick's Chittenango vs Taberg.
            swap = (resolved is not None
                    and resolved != block.client_id
                    and lookalikes.are_lookalikes(block.client_id, resolved))
            if swap and self._safe_to_correct(lookalikes, block, resolved, words):
                corrections.append((block, resolved))
                continue

            # A swap the guards refused is not "fine as it is" — it means two
            # look-alikes both fit and the text can't settle it. That is the
            # definition of a pick, so it falls through to REOPEN rather than
            # being left on whatever the classifier originally guessed.
            unsafe_swap = swap

            if not opts['reopen_ambiguous']:
                continue
            if block.classification_state != 'committed':
                continue

            # REOPEN: the text names a group, not a member, and no other signal
            # knows better either.
            types = {
                s.get('type') for s in (block.proposed_signals or [])
                if isinstance(s, dict)
            }
            if types & set(IDENTIFYING):
                continue
            candidates = lookalikes.candidates_for(words)
            if len(candidates) < 2 or block.client_id not in candidates:
                continue
            if resolved and not unsafe_swap:
                continue  # the text does name one, and naming it was safe
            # Ask the same question the live suggestion asks. candidates_for is
            # generous by design, and a reopen spends someone's attention: over
            # org 21 since June it offers 118 blocks, 41 of which are candidate
            # piles that share one incidental word and no family. family_for
            # also narrows the real ones — a "St Marys Baldwinsville" title goes
            # from fourteen buttons to the two that differ (church vs school).
            family = lookalikes.family_for(words, candidates)
            if not family or block.client_id not in family:
                continue
            reopens.append((block, family, words))

        self._report(blocks, corrections, reopens, skipped_human, names,
                     opts['reopen_ambiguous'])

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                '\nDRY RUN — nothing written. Re-run with --apply to commit.'))
            return

        self._write(corrections, reopens, lookalikes)
        self.stdout.write(self.style.SUCCESS(
            f'\nAPPLIED: {len(corrections)} corrected, {len(reopens)} reopened.'))


    # ------------------------------------------------------------------ guards

    @staticmethod
    def _safe_to_correct(lookalikes, block, target, words):
        """
        Is this swap PROVEN by the text, or merely the roster's best fit?

        Two ways an apparently-clean correction is actually a guess, both found
        by inspecting real July blocks before applying anything:

        1. The only thing separating the winner is an ENTITY-CLASS word.
           "St. Mary's Church Cemetery" resolves to client 125 solely because
           125 is the one St-Mary cemetery on the roster — so it absorbs every
           parish's cemetery work, exactly the magnet pattern that made client
           130 swallow Taberg. A cemetery file for Hamilton's parish is not
           Baldwinsville's just because Hamilton has no cemetery client. The
           title has to carry a PLACE or NAME word (Taberg, Boonville,
           Syracuse), not just a kind-of-thing word.

        2. The swap CHANGES entity class without the text saying so. A file
           called "St Marys Bville MT Bank Statements" says nothing about a
           cemetery, so moving it from a church client to a cemetery client is
           unsupported — "Bville" only looks decisive because 125 spells the
           place "Bville" and 790 spells it "Baldwinsville".

        Blocked swaps aren't lost: with --reopen-ambiguous they become a pick.
        """
        entity_words = set().union(*EXCLUSIVE_ENTITY_CLASSES)
        candidates = lookalikes.candidates_for(words)
        evidence = lookalikes.distinguishing_words(target, candidates) & set(words)

        # (1) at least one word that names a PLACE or PERSON, not a kind.
        core = {
            word for word in evidence
            if word not in entity_words and word not in DOMAIN_COMMON_WORDS
        }
        if not core:
            return False

        # (2) don't move across entity classes on a text that never named the
        # class we're moving TO.
        target_classes = set().union(*[
            group & _canonical_entity_tokens(lookalikes._words.get(target, set()))
            for group in EXCLUSIVE_ENTITY_CLASSES
        ])
        if target_classes and not (target_classes & _canonical_entity_tokens(words)):
            return False
        return True

    # ------------------------------------------------------------------ report

    def _report(self, blocks, corrections, reopens, skipped_human, names,
                reopen_requested):
        w = self.stdout.write
        mins = lambda rows: sum((r[0].minutes or 0) for r in rows)  # noqa: E731

        w(f"\nscanned {len(blocks)} attributed blocks "
          f"({skipped_human} skipped — a person had already decided or approved them)")
        w(f"\nCORRECT  {len(corrections):5d} blocks  {mins(corrections) / 60:7.1f} h "
          f"— the title names a different client than the one they're booked to")
        pairs = Counter()
        for block, target in corrections:
            pairs[(names.get(block.client_id, '?'), names.get(target, '?'))] += (block.minutes or 0)
        for (was, now), m in pairs.most_common(20):
            w(f"    {m:6d}m  {was[:36]:36} -> {now}")

        if not reopen_requested:
            # Without the flag this phase never ran. Printing "REOPEN 0 blocks"
            # reads as "nothing to reopen", which is the opposite of the truth.
            w('\nREOPEN   not requested — pass --reopen-ambiguous to also send '
              'blocks nothing can identify back for a pick')
            return
        w(f"\nREOPEN   {len(reopens):5d} blocks  {mins(reopens) / 60:7.1f} h "
          f"— nothing identifies which client; would go back for a pick")
        by_title = defaultdict(int)
        for block, _, _ in reopens:
            by_title[(block.window_title or block.title or '')[:56]] += (block.minutes or 0)
        for title, m in sorted(by_title.items(), key=lambda kv: -kv[1])[:12]:
            w(f"    {m:6d}m  {title}")

    # ------------------------------------------------------------------- write

    def _write(self, corrections, reopens, lookalikes):
        with transaction.atomic():
            for block, target in corrections:
                # Record where it came from. A bulk re-attribution with no
                # record of the previous client is not reversible, and this
                # command touches months of already-billed time.
                signals = list(block.proposed_signals or [])
                signals.append({
                    'type': 'lookalike_backfill',
                    'strength': 0.0,
                    'evidence': (
                        f'Backfill moved this block from client '
                        f'{block.client_id} to {target}: the title names {target}'
                    ),
                    'detail': {'from_client_id': block.client_id,
                               'to_client_id': target},
                })
                block.proposed_signals = signals
                block.client_id = target
                block.state_changed_by = 'backfill_lookalike'
                # Block.save() refuses to touch a "protected" block, which is
                # anything categorized/approved/locked — i.e. every committed
                # block there is. force_classifier is the documented path for a
                # classifier-driven correction to a committed block, and is what
                # ClassificationService.apply() uses; it still refuses anything
                # outside captured/proposed/committed.
                block.save(force_classifier=True, update_fields=[
                    'client_id', 'state_changed_by', 'proposed_signals',
                ])

            for block, ranked, words in reopens:
                signals = [
                    s for s in (block.proposed_signals or [])
                    if not (isinstance(s, dict) and s.get('type') == AMBIGUOUS_SIGNAL)
                ]
                signals.append({
                    'type': AMBIGUOUS_SIGNAL,
                    'strength': 0.5,
                    'evidence': (
                        f'{len(ranked)} clients fit this text; nothing in it says which'
                    ),
                    'detail': {
                        'chosen_client_id': block.client_id,
                        'candidate_client_ids': ranked,
                        'candidate_labels': {
                            str(c): lookalikes.short_name(c, words, ranked) for c in ranked
                        },
                    },
                })
                block.proposed_signals = signals
                block.classification_state = 'proposed'
                # is_categorized marks a block as CONFIRMED, and the invariant
                # apply() enforces is is_categorized == (state == 'committed').
                # Reopening a committed block without clearing it strands the
                # block in the proposed-limbo state: today_time's review pile
                # and Confirm-all both filter is_categorized=False, so the block
                # disappears from the queue that is supposed to ask about it.
                block.is_categorized = False
                block.needs_review = True
                block.review_reason = (
                    'The title names a group of look-alike clients but not which one'
                )
                block.state_changed_by = 'backfill_lookalike'
                block.save(force_classifier=True, update_fields=[
                    'proposed_signals', 'classification_state', 'is_categorized',
                    'needs_review', 'review_reason', 'state_changed_by',
                ])
