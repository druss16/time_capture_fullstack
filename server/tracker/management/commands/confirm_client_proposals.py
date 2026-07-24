"""
Confirm 'proposed' blocks that are already attributed to a single client.

Business rule (per TL Wall): if a block is already sitting UNDER a client in
Daily Review — even when the activity title doesn't literally contain the
client's name (e.g. "Bank Statements - File Explorer" grouped under Our Lady of
Hope because that church's QuickBooks was open) — it should just be confirmed,
not left in the "Pending — confirm to count as billable" pile.

This commits those proposals so they count (billable ones become billable,
non-billable stay non-billable — the block's is_billable judgment is preserved).

Two cases are deliberately HELD BACK for human review:
  - no client            -> nothing to confirm; a human assigns the client
  - genuine change        -> proposed_client_id is set AND != client_id, i.e.
                             the AI suggests a DIFFERENT client. This is the
                             same-family collision guard (e.g. a "St. Mary's"
                             QuickBooks file the classifier wants to move to a
                             different St. Mary's). We never auto-bill a disputed
                             attribution.

Human decisions are never touched (categorized_by in manual/correction,
state_changed_by in user/user_edit/correction).

Usage:
  # Dry run (default) — shows what would confirm, grouped by client
  python manage.py confirm_client_proposals --org-id 21 --start 2026-07-01 --end 2026-07-31

  # Apply
  python manage.py confirm_client_proposals --org-id 21 --start 2026-07-01 --end 2026-07-31 --apply
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q, Count, Sum
from django.utils import timezone

from tracker.models import Block, Organization


SKIP_CATEGORIZED_BY = ('manual', 'correction')
SKIP_STATE_CHANGED_BY = ('user', 'user_edit', 'correction')


class Command(BaseCommand):
    help = "Confirm proposed blocks already attributed to a single (undisputed) client"

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None)
        parser.add_argument('--user-id', type=int, default=None)
        parser.add_argument('--start', type=str, default=None,
                            help='day >= this (YYYY-MM-DD)')
        parser.add_argument('--end', type=str, default=None,
                            help='day <= this (YYYY-MM-DD, inclusive)')
        parser.add_argument('--apply', action='store_true',
                            help='Write changes. Omit for a dry run (default).')

    def _base_qs(self, opts):
        qs = Block.objects.filter(
            classification_state='proposed',
            deleted_at__isnull=True,
        ).exclude(
            bundle_id__iexact='__idle__',
        ).exclude(
            categorized_by__in=SKIP_CATEGORIZED_BY,
        ).exclude(
            state_changed_by__in=SKIP_STATE_CHANGED_BY,
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

        # CONFIRM: has a client, and NO competing proposal (proposal null or == client)
        confirm = base.filter(client_id__isnull=False).filter(
            Q(proposed_client_id__isnull=True) | Q(proposed_client_id=F('client_id'))
        )
        # HELD BACK
        genuine_change = base.filter(
            client_id__isnull=False, proposed_client_id__isnull=False,
        ).exclude(proposed_client_id=F('client_id'))
        no_client = base.filter(client_id__isnull=True)

        def stat(qs):
            a = qs.aggregate(n=Count('id'), m=Sum('minutes'),
                             bill=Sum('minutes', filter=Q(is_billable=True)))
            return a['n'] or 0, a['m'] or 0, a['bill'] or 0

        c_n, c_m, c_b = stat(confirm)
        g_n, g_m, _ = stat(genuine_change)
        nc_n, nc_m, _ = stat(no_client)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nConfirm client proposals — {scope} — "
            f"{'APPLY' if opts['apply'] else 'DRY RUN'}"))
        self.stdout.write(
            f"\nWILL CONFIRM (has client, undisputed): {c_n} blocks, {c_m} min "
            f"(~{c_m/60:.1f}h) — of which {c_b} min billable\n"
            f"HELD for review:\n"
            f"  genuine change (AI suggests a different client): {g_n} blocks, {g_m} min\n"
            f"  no client (you assign):                          {nc_n} blocks, {nc_m} min\n"
        )

        self.stdout.write("Confirming, grouped by client (top 25) — eyeball for wrong churches:")
        rows = confirm.values('client__name').annotate(
            n=Count('id'), m=Sum('minutes'),
            bill=Sum('minutes', filter=Q(is_billable=True))).order_by('-m')
        for r in rows[:25]:
            self.stdout.write(
                f"  {str(r['client__name'])[:40]:40s} {r['n']:4d} blocks  "
                f"{r['m']:5d}m  ({r['bill'] or 0}m billable)")

        if not opts['apply']:
            self.stdout.write(self.style.NOTICE(
                "\nDRY RUN — no writes. Re-run with --apply to confirm."))
            return

        now = timezone.now()
        with transaction.atomic():
            n = confirm.update(
                classification_state='committed',
                is_categorized=True,
                categorized_by='ai',
                categorized_at=now,
                state_changed_by='admin_bulk',
                state_changed_at=now,
            )
        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Confirmed {n} client-attributed blocks (now committed/billable). "
            f"Held {g_n} genuine-change + {nc_n} no-client for review."))
