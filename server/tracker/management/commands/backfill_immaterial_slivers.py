"""
Auto-commit immaterial (sub-2-minute) proposed blocks so they stop nagging in
Daily Review's "Needs you" lane.

A 1-minute sliver is too small to be worth a human review click. This backfills
the existing pile to match the go-forward rule in ClassificationService's
finalize gate (IMMATERIAL_MAX_MINUTES):

  - has a client -> commit to the client it is ALREADY booked under (keep the
                    current booking; we do NOT switch it to a differing
                    proposed_client_id — a 1-minute block is never worth a
                    silent reassignment). is_billable is preserved, so it lands
                    in "Certain" billable/non-billable exactly as flagged.
  - no client    -> commit as No-Client / Personal-Non-Billable.

Human decisions are never touched (categorized_by in manual/correction,
state_changed_by in user/user_edit/correction). Idle bundles are skipped.

Usage:
  # Dry run (default) — shows what would commit, grouped by client
  python manage.py backfill_immaterial_slivers --org-id 21

  # Apply
  python manage.py backfill_immaterial_slivers --org-id 21 --apply
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Sum, Q
from django.utils import timezone

from tracker.models import Block, Organization

SKIP_CATEGORIZED_BY = ('manual', 'correction')
SKIP_STATE_CHANGED_BY = ('user', 'user_edit', 'correction')

# Mirrors IMMATERIAL_MAX_MINUTES in classification_service / _MATERIAL_MIN_MINUTES
# in views_reports: a block with fewer minutes than this is an immaterial sliver.
IMMATERIAL_MAX_MINUTES = 2

NONBILL_CAT = 'Personal/Non-Billable'


class Command(BaseCommand):
    help = "Auto-commit sub-2-minute proposed blocks (keep current booking) so they leave 'Needs you'"

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None)
        parser.add_argument('--user-id', type=int, default=None)
        parser.add_argument('--start', type=str, default=None, help='day >= this (YYYY-MM-DD)')
        parser.add_argument('--end', type=str, default=None, help='day <= this (YYYY-MM-DD)')
        parser.add_argument('--apply', action='store_true',
                            help='Write changes. Omit for a dry run (default).')

    def _base_qs(self, opts):
        # EXACTLY the "Needs you" population, restricted to immaterial slivers:
        #   • classification_state='proposed' AND is_categorized=False — the
        #     latter is CRITICAL. Dropping it sweeps in the ~1.8k "proposed
        #     limbo" blocks (proposed + is_categorized=True), which are invisible
        #     in both billing and review and are healed by a separate process;
        #     committing those would be a large, unintended billing swing.
        #   • has a client guess OR a second-pass reason — mirrors the proposed
        #     branch of views_reports.is_pending_review_block, so we only touch
        #     blocks that actually surface in Needs you.
        qs = Block.objects.filter(
            classification_state='proposed',
            is_categorized=False,
            deleted_at__isnull=True,
            minutes__lt=IMMATERIAL_MAX_MINUTES,
        ).exclude(
            bundle_id__iexact='__idle__',
        ).exclude(
            categorized_by__in=SKIP_CATEGORIZED_BY,
        ).exclude(
            state_changed_by__in=SKIP_STATE_CHANGED_BY,
        ).filter(
            Q(proposed_client_id__isnull=False)
            | Q(proposed_reasoning__icontains='second-pass')
        )
        if opts.get('org_id'):
            qs = qs.filter(org_id=opts['org_id'])
        if opts.get('user_id'):
            qs = qs.filter(user_id=opts['user_id'])
        if opts.get('start'):
            qs = qs.filter(day__gte=opts['start'])
        if opts.get('end'):
            qs = qs.filter(day__lte=opts['end'])
        return qs

    def handle(self, *args, **opts):
        if opts.get('org_id'):
            try:
                org = Organization.objects.get(id=opts['org_id'])
                scope = f"org {org.id} ({org.name})"
            except Organization.DoesNotExist:
                raise CommandError(f"Org {opts['org_id']} not found")
        else:
            scope = "ALL orgs"

        base = self._base_qs(opts)
        with_client = base.filter(client_id__isnull=False)
        no_client = base.filter(client_id__isnull=True)

        def stat(qs):
            a = qs.aggregate(n=Count('id'), m=Sum('minutes'),
                             bill=Sum('minutes', filter=Q(is_billable=True)))
            return a['n'] or 0, a['m'] or 0, a['bill'] or 0

        wc_n, wc_m, wc_b = stat(with_client)
        nc_n, nc_m, _ = stat(no_client)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nBackfill immaterial slivers (< {IMMATERIAL_MAX_MINUTES}m) — {scope} — "
            f"{'APPLY' if opts['apply'] else 'DRY RUN'}"))
        self.stdout.write(
            f"\nWITH client → commit to current booking: {wc_n} blocks, {wc_m} min "
            f"(~{wc_m/60:.1f}h) — of which {wc_b} min become billable\n"
            f"NO client  → commit No-Client / Non-Billable: {nc_n} blocks, {nc_m} min\n"
        )

        self.stdout.write("Committing to current client, grouped (top 25) — eyeball for wrong churches:")
        rows = with_client.values('client__name').annotate(
            n=Count('id'), m=Sum('minutes'),
            bill=Sum('minutes', filter=Q(is_billable=True))).order_by('-m')
        for r in rows[:25]:
            self.stdout.write(
                f"  {str(r['client__name'])[:40]:40s} {r['n']:4d} blocks  "
                f"{r['m']:5d}m  ({r['bill'] or 0}m billable)")

        if not opts['apply']:
            self.stdout.write(self.style.NOTICE(
                "\nDRY RUN — no writes. Re-run with --apply to commit."))
            return

        now = timezone.now()
        with transaction.atomic():
            # Keep the CURRENT booking (client_id + is_billable ride along).
            wc = with_client.update(
                classification_state='committed',
                is_categorized=True,
                categorized_by='ai',
                categorized_at=now,
                state_changed_by='admin_bulk',
                state_changed_at=now,
            )
            # No-client slivers → non-billable. Per-block category_hours needs the
            # block's own minutes, so iterate (this bucket is tiny by nature).
            nc = 0
            for b in no_client.iterator():
                mins = b.minutes or 0
                b.category_hours = {NONBILL_CAT: round(mins / 60.0, 4)}
                b.client = None
                b.is_billable = False
                b.classification_state = 'committed'
                b.is_categorized = True
                b.categorized_by = 'ai'
                b.categorized_at = now
                b.state_changed_by = 'admin_bulk'
                b.state_changed_at = now
                b.save(update_fields=[
                    'category_hours', 'client', 'is_billable', 'classification_state',
                    'is_categorized', 'categorized_by', 'categorized_at',
                    'state_changed_by', 'state_changed_at',
                ])
                nc += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Committed {wc} client-attributed + {nc} no-client immaterial slivers. "
            f"They now live in Certain instead of Needs you."))
