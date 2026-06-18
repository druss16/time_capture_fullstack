"""
tracker/management/commands/suppress_oversized_blocks.py

One-time (and re-runnable) cleanup for the sleep/wake block-capping artifact:
blocks whose wall-clock span (end - start) is implausibly long for a single
work session — almost always an overnight "machine left on" block (Explorer/
desktop focused for 10h while asleep). These inflate Daily Review, the Reports
page, billing, and the classifier.

The agent fix (close dwell at sleep) prevents NEW ones; this cleans up the
ones already in the database.

Default action: mark matching blocks classification_state='suppressed' (the
state the rest of the app already treats as "not a real activity"). This drops
them from Daily Review, the report, and billing while preserving the row for
audit — fully reversible, unlike delete.

SAFETY:
  - Dry-run by default. Prints what it WOULD touch; writes nothing.
  - Must pass --commit to actually write.
  - Skips blocks that are already committed/approved/invoiced unless --force,
    so we never silently suppress something a human already confirmed or billed.
  - Scope to one org with --org (recommended: run TL Wall first).

USAGE:
  # See what it would touch for TL Wall (org_id=21), no writes:
  python manage.py suppress_oversized_blocks --org 21 --hours 6

  # Actually suppress them once the list looks right:
  python manage.py suppress_oversized_blocks --org 21 --hours 6 --commit

  # All orgs (careful):
  python manage.py suppress_oversized_blocks --hours 6 --commit
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.utils import timezone

from tracker.models import Block


class Command(BaseCommand):
    help = "Suppress oversized (overnight-artifact) blocks whose span exceeds --hours."

    def add_arguments(self, parser):
        parser.add_argument(
            "--org", type=int, default=None,
            help="Limit to a single organization id (recommended). Omit for all orgs.",
        )
        parser.add_argument(
            "--hours", type=float, default=6.0,
            help="Span threshold in hours. Blocks with (end - start) > this are "
                 "treated as artifacts. Default 6.0 (matches the report guardrail).",
        )
        parser.add_argument(
            "--commit", action="store_true",
            help="Actually write changes. Without this, runs as a dry-run.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Also suppress blocks that are committed/approved/invoiced. "
                 "Off by default so human-confirmed/billed time is never touched.",
        )
        parser.add_argument(
            "--days", type=int, default=None,
            help="Optional: only consider blocks whose start is within the last "
                 "N days. Omit to scan all history.",
        )

    def handle(self, *args, **opts):
        org_id = opts["org"]
        threshold_hours = opts["hours"]
        commit = opts["commit"]
        force = opts["force"]
        days = opts["days"]

        threshold = timedelta(hours=threshold_hours)

        # Base: non-deleted blocks with a real start/end.
        qs = Block.objects.filter(
            deleted_at__isnull=True,
            start__isnull=False,
            end__isnull=False,
        )

        if org_id is not None:
            qs = qs.filter(org_id=org_id)

        if days is not None:
            since = timezone.now() - timedelta(days=days)
            qs = qs.filter(start__gte=since)

        # Span filter at the DB level: end - start > threshold.
        qs = qs.filter(end__gt=F("start") + threshold)

        # Don't re-touch already-suppressed blocks.
        qs = qs.exclude(classification_state="suppressed")

        # Protect human-confirmed / billed time unless --force.
        protected_q = Q(approved=True) | Q(invoiced=True) | Q(is_categorized=True)
        if not force:
            qs = qs.exclude(protected_q)

        qs = qs.select_related("user", "client", "org").order_by("user_id", "start")

        total = qs.count()

        mode = "COMMIT" if commit else "DRY-RUN"
        scope = f"org={org_id}" if org_id is not None else "ALL ORGS"
        self.stdout.write(self.style.WARNING(
            f"\n[{mode}] suppress_oversized_blocks — {scope}, "
            f"span > {threshold_hours}h"
            + (f", last {days} days" if days else "")
            + (", INCLUDING protected (--force)" if force else "")
        ))

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No matching blocks. Nothing to do.\n"))
            return

        # Report per block + a per-user tally so you can eyeball it.
        by_user = {}
        total_minutes = 0
        for b in qs:
            span_min = (b.end - b.start).total_seconds() / 60.0
            uname = (b.user.get_full_name().strip() or b.user.username) if b.user_id else "Unknown"
            by_user.setdefault(uname, {"count": 0, "span_min": 0.0, "rec_min": 0})
            by_user[uname]["count"] += 1
            by_user[uname]["span_min"] += span_min
            by_user[uname]["rec_min"] += (b.minutes or 0)
            total_minutes += (b.minutes or 0)

            self.stdout.write(
                f"  block#{b.id}  {uname:<20}  "
                f"span={span_min/60:5.1f}h  recorded={ (b.minutes or 0)/60:5.1f}h  "
                f"{b.start:%Y-%m-%d %H:%M}→{b.end:%H:%M}  "
                f"app={(b.app_name or '')[:24]:<24}  "
                f"state={b.classification_state}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Per-user summary:"))
        for uname, agg in sorted(by_user.items(), key=lambda kv: -kv[1]["rec_min"]):
            self.stdout.write(
                f"  {uname:<20}  {agg['count']:>3} blocks  "
                f"recorded={agg['rec_min']/60:6.1f}h  "
                f"(wall-span={agg['span_min']/60:6.1f}h)"
            )
        self.stdout.write("")
        self.stdout.write(
            f"TOTAL: {total} blocks, {total_minutes/60:.1f}h of recorded time would be suppressed."
        )

        if not commit:
            self.stdout.write(self.style.NOTICE(
                "\nDRY-RUN — nothing written. Re-run with --commit to apply.\n"
            ))
            return

        # Commit: mark suppressed. We set state + a review_reason breadcrumb so
        # it's auditable why these were removed. We do NOT delete.
        now = timezone.now()
        updated = 0
        for b in qs:
            span_h = (b.end - b.start).total_seconds() / 3600.0
            b.classification_state = "suppressed"
            b.state_changed_at = now
            b.state_changed_by = "admin_bulk"
            b.needs_review = False
            reason = (
                f"Auto-suppressed: wall-clock span {span_h:.1f}h exceeds "
                f"{threshold_hours}h (sleep/wake overnight artifact)."
            )
            # review_reason is a 500-char field; keep it short.
            b.review_reason = reason[:500]
            # force_update bypasses the protected-block guard in Block.save();
            # safe here because we deliberately excluded protected rows above
            # (unless --force, in which case the operator opted in).
            b.save(update_fields=[
                "classification_state", "state_changed_at",
                "state_changed_by", "needs_review", "review_reason",
            ])
            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Suppressed {updated} blocks. "
            f"They will drop out of Daily Review, Reports, and billing.\n"
            f"Reversible: set classification_state back from 'suppressed' if needed.\n"
        ))