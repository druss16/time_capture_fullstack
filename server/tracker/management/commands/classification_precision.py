# tracker/management/commands/classification_precision.py
"""
Per-source classification precision report.

Definition of "corrected": for a block that the classifier committed,
a LATER ClassificationAudit row with source='manual' that changed the
client to a different value. That manual override is the ground-truth
signal that the original attribution was wrong.

Run:
    python manage.py classification_precision --days 30
    python manage.py classification_precision --days 30 --org 21
"""
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q

from tracker.models import ClassificationAudit


class Command(BaseCommand):
    help = "Report classification precision per source/signal-type."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--org", type=int, default=None,
                            help="Restrict to a single org_id")

    def handle(self, *args, **opts):
        days = opts["days"]
        org_id = opts["org"]
        cutoff = timezone.now() - timedelta(days=days)

        audits = (
            ClassificationAudit.objects
            .filter(created_at__gte=cutoff)
            .select_related("block")
            .order_by("block_id", "created_at")
        )
        if org_id is not None:
            audits = audits.filter(block__org_id=org_id)

        # Group every audit row by block, in time order.
        by_block = defaultdict(list)
        for a in audits:
            by_block[a.block_id].append(a)

        # For each block: find the first NON-manual committing audit (the
        # classifier's attribution) and whether a LATER manual row changed
        # the client.
        #
        # source_stats[source] = {"total": n, "corrected": n}
        source_stats = defaultdict(lambda: {"total": 0, "corrected": 0})
        # signal_stats[signal_type] = {"total": n, "corrected": n}
        signal_stats = defaultdict(lambda: {"total": 0, "corrected": 0})

        for block_id, rows in by_block.items():
            # The classifier's attribution = first non-manual row that set a client.
            classifier_row = next(
                (r for r in rows
                 if r.source != "manual" and r.client_after_id is not None),
                None,
            )
            if classifier_row is None:
                continue

            attributed_client = classifier_row.client_after_id
            attributed_at = classifier_row.created_at

            # Was there a later manual override to a DIFFERENT client?
            corrected = any(
                r.source == "manual"
                and r.created_at > attributed_at
                and r.client_after_id is not None
                and r.client_after_id != attributed_client
                for r in rows
            )

            source = classifier_row.source
            source_stats[source]["total"] += 1
            if corrected:
                source_stats[source]["corrected"] += 1

            # Attribute the outcome to the dominant signal type. The dominant
            # signal is the highest-strength one that proposed the attributed
            # client. matched_signals is a list of dicts: {type, strength, ...}.
            signals = classifier_row.matched_signals or []
            dominant = None
            for s in sorted(signals, key=lambda x: x.get("strength", 0), reverse=True):
                detail = s.get("detail", {}) or {}
                if detail.get("client_id") == attributed_client:
                    dominant = s.get("type", "unknown")
                    break
            if dominant is None and signals:
                # Fall back to the single strongest signal even if it didn't
                # propose the final client (still informative).
                dominant = max(
                    signals, key=lambda x: x.get("strength", 0)
                ).get("type", "unknown")
            if dominant is None:
                dominant = "none"

            signal_stats[dominant]["total"] += 1
            if corrected:
                signal_stats[dominant]["corrected"] += 1

        self._print_table("BY SOURCE", source_stats)
        self._print_table("BY DOMINANT SIGNAL TYPE", signal_stats)

    def _print_table(self, heading, stats):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(heading))
        self.stdout.write(f"{'key':<28}{'total':>8}{'wrong':>8}{'precision':>12}")
        self.stdout.write("-" * 56)
        # Sort worst precision first — that's where you tune.
        def precision(v):
            return 1.0 - (v["corrected"] / v["total"]) if v["total"] else 1.0
        for key in sorted(stats, key=lambda k: precision(stats[k])):
            v = stats[key]
            p = precision(v)
            line = f"{key:<28}{v['total']:>8}{v['corrected']:>8}{p:>11.1%}"
            # Flag anything under 95% precision.
            if v["total"] >= 5 and p < 0.95:
                self.stdout.write(self.style.WARNING(line))
            else:
                self.stdout.write(line)