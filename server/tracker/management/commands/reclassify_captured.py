"""
Management command: reclassify_captured

Re-runs the classification pipeline over an org's CAPTURED blocks (those with
no confirmed attribution) and measures how many now resolve to a client —
the value delivered by newly-added aliases (Stage 3 title matching).

SAFETY
------
* DRY-RUN BY DEFAULT. Prints the lift and writes nothing. You must pass
  --apply to actually persist reattributions.
* Touches ONLY classification_state='captured' blocks. Never committed,
  proposed, suppressed, or anything a user confirmed/corrected. Wayne's
  reviewed work is untouchable.
* skip_ai=True — does NOT call OpenAI (Stage 10). This isolates the lift to
  deterministic stages (aliases/Stage 3) and avoids per-block API cost. The
  signal handler will still enqueue AI later for anything that stays captured.

USAGE
-----
    # Measure only (default) — last 7 days
    python manage.py reclassify_captured --org-id 21

    # Different window
    python manage.py reclassify_captured --org-id 21 --days 14

    # Actually persist the reattributions
    python manage.py reclassify_captured --org-id 21 --apply
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = ("Reclassify captured blocks and report how many now resolve to a "
            "client (alias lift). Dry-run by default; use --apply to write.")

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--org-id", type=int)
        group.add_argument("--org-slug", type=str)
        parser.add_argument("--days", type=int, default=7,
                            help="Look back this many days (default 7).")
        parser.add_argument("--apply", action="store_true",
                            help="Persist reattributions. Without this, dry-run only.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Cap number of blocks processed (0 = no cap). "
                                 "Useful for a quick sample before a full run.")

    def handle(self, *args, **opts):
        from tracker.models import Block, Organization
        from tracker.services.classification_service import ClassificationService

        # ---- Resolve org ----
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

        apply_changes = opts["apply"]
        days = opts["days"]
        cutoff = timezone.now() - timedelta(days=days)

        # ---- Select captured blocks in window ----
        # ONLY captured. Never touch committed/proposed/suppressed or anything
        # a human confirmed. all_objects to be explicit we are not excluding
        # soft-deleted via the default manager unexpectedly — but we DO want to
        # skip deleted, so use the default manager (ActiveBlockManager).
        qs = (
            Block.objects
            .filter(org=org, classification_state='captured', start__gte=cutoff)
            .order_by('start')
        )
        if opts["limit"]:
            qs = qs[:opts["limit"]]

        blocks = list(qs)
        total = len(blocks)
        if total == 0:
            self.stdout.write(self.style.WARNING(
                f"No captured blocks for org {org.pk} in the last {days} days."
            ))
            return

        # Baseline: how many of these already have a client_id set (agent
        # stickiness) vs truly unattributed.
        had_client_before = sum(1 for b in blocks if b.client_id)
        no_client_before = total - had_client_before

        self.stdout.write(
            f"Org {org.pk} ({org.name}): {total} captured blocks in last {days}d "
            f"({no_client_before} with no client, {had_client_before} with a "
            f"stale agent client). Mode: {'APPLY' if apply_changes else 'DRY-RUN'}.\n"
        )

        service = ClassificationService(org=org, user=None)

        # Counters
        newly_attributed = 0     # had no client, now proposes/commits one
        changed_client = 0       # had a client, classifier proposes a different one
        still_unattributed = 0   # had no client, still none
        recommended_commit = 0
        recommended_propose = 0
        by_signal_type = {}      # dominant signal type -> count of new attributions
        examples = []            # (block_id, title snippet, client name, state)

        def _run_one(block):
            # ClassificationService is normally constructed per (org, user).
            # Captured blocks belong to various users; rebind user per block so
            # user-scoped stages (8/9) read the right context.
            svc = ClassificationService(org=org, user=block.user)
            decision = svc.classify(block, skip_ai=True)
            return svc, decision

        # Process. In dry-run we never call apply(). In apply mode we call
        # apply() inside the transaction.
        if apply_changes:
            ctx = transaction.atomic()
        else:
            # dummy context manager
            import contextlib
            ctx = contextlib.nullcontext()

        with ctx:
            for block in blocks:
                before_id = block.client_id
                svc, decision = _run_one(block)
                after_id = decision.client_id

                resolves = after_id is not None
                if resolves and not before_id:
                    newly_attributed += 1
                    # Identify dominant client-proposing signal type
                    dom = next(
                        (s.type for s in sorted(decision.matched_signals,
                                                key=lambda s: s.strength, reverse=True)
                         if s.proposed_client_id == after_id),
                        decision.source or 'unknown',
                    )
                    by_signal_type[dom] = by_signal_type.get(dom, 0) + 1
                    if len(examples) < 25:
                        client = next((c for c in svc._clients if c.id == after_id), None)
                        examples.append((
                            block.id,
                            (block.window_title or block.title or '')[:60],
                            client.name if client else str(after_id),
                            decision.recommended_state,
                        ))
                elif resolves and before_id and after_id != before_id:
                    changed_client += 1
                elif not resolves and not before_id:
                    still_unattributed += 1

                if decision.recommended_state == 'committed':
                    recommended_commit += 1
                elif decision.recommended_state == 'proposed':
                    recommended_propose += 1

                if apply_changes:
                    svc.apply(block, decision, source='classifier')

        # ---- Report ----
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"RESULTS ({'written' if apply_changes else 'dry-run, nothing written'})")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Blocks processed:            {total}")
        self.stdout.write(f"  Newly attributed to client:  {newly_attributed}")
        self.stdout.write(f"  Still unattributed:          {still_unattributed}")
        self.stdout.write(f"  Client changed (had stale):  {changed_client}")
        self.stdout.write(f"  Recommended commit:          {recommended_commit}")
        self.stdout.write(f"  Recommended propose:         {recommended_propose}")

        if no_client_before:
            pct = round(100.0 * newly_attributed / no_client_before, 1)
            self.stdout.write(
                f"\n  Recovery rate: {newly_attributed}/{no_client_before} "
                f"previously-unattributed blocks now resolve = {pct}%"
            )

        if by_signal_type:
            self.stdout.write("\n  New attributions by dominant signal:")
            for t, n in sorted(by_signal_type.items(), key=lambda x: -x[1]):
                self.stdout.write(f"      {t:32s} {n}")

        if examples:
            self.stdout.write("\n  Sample newly-attributed blocks:")
            for bid, title, cname, state in examples:
                self.stdout.write(f"      [{bid}] {title!r} -> {cname} ({state})")

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN — nothing written. Re-run with --apply to persist."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nApplied. {newly_attributed} blocks newly attributed."
            ))
