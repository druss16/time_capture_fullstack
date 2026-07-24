"""
Heal blocks stuck in the "proposed limbo" state.

A block is in limbo when it has BOTH:
  - classification_state = 'proposed'   (an unconfirmed AI guess)
  - is_categorized = True               (flagged as if confirmed)

That combination is contradictory. Every consumer hides it:
  - today_time / reports billable filter excludes classification_state='proposed'
  - the review-pile filter (is_pending_review_block) requires is_categorized=False
So the block appears in NEITHER the billable totals NOR the Daily Review
"confirm" queue — its time silently vanishes from billing.

Root cause (the classifier writing is_categorized=True for proposed blocks) is
fixed in ClassificationService.apply_decision(). This command heals the rows
that were already minted before that fix shipped.

The healed invariant is: is_categorized == (classification_state == 'committed').

Two modes:

  surface  (default, SAFE): nothing is auto-billed. Every limbo block is routed
           so it shows up in the Daily Review / Categorize "confirm" queue for a
           human to approve:
             - has client + a competing proposal (proposal != client)
                 -> is_categorized=False (shows as "AI suggests <proposal>")
             - has client, no/own proposal
                 -> is_categorized=False, proposed_client_id := client_id
                    (shows as "confirm as <client>")
             - no client
                 -> is_categorized=False, classification_state='captured'
                    (shows in the "assign a client" review path)

  hybrid   (FASTER, riskier): auto-commits the non-conflicting blocks under their
           existing client (immediately billable) and surfaces only the genuine
           "AI suggests a different client" ones for review. Bakes in whatever the
           AI guessed on the non-conflicting blocks — including same-family client
           collisions — without a human check. Use with care.

Human decisions are never touched: categorized_by IN ('manual','correction')
and state_changed_by IN ('user','user_edit','correction') are skipped.

Usage:
  # Dry run (default) — shows the breakdown, writes nothing
  python manage.py heal_proposed_limbo --org-id 21

  # Apply the safe surface heal
  python manage.py heal_proposed_limbo --org-id 21 --apply

  # Hybrid (auto-commit non-conflicting) — preview then apply
  python manage.py heal_proposed_limbo --org-id 21 --mode hybrid
  python manage.py heal_proposed_limbo --org-id 21 --mode hybrid --apply

  # All orgs, or a single user
  python manage.py heal_proposed_limbo --apply
  python manage.py heal_proposed_limbo --org-id 21 --user-id 54 --apply
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F, Q, Count, Sum
from django.utils import timezone

from tracker.models import Block, Organization


SKIP_CATEGORIZED_BY = ('manual', 'correction')
SKIP_STATE_CHANGED_BY = ('user', 'user_edit', 'correction')


class Command(BaseCommand):
    help = "Heal blocks stuck in the proposed + is_categorized=True limbo state"

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None,
                            help='Limit to one org (default: all orgs)')
        parser.add_argument('--user-id', type=int, default=None,
                            help='Limit to one user')
        parser.add_argument('--start', type=str, default=None,
                            help='Only heal blocks with day >= this (YYYY-MM-DD)')
        parser.add_argument('--end', type=str, default=None,
                            help='Only heal blocks with day <= this (YYYY-MM-DD, inclusive)')
        parser.add_argument('--mode', choices=['surface', 'hybrid'],
                            default='surface',
                            help="'surface' (default, nothing auto-billed) or "
                                 "'hybrid' (auto-commit non-conflicting blocks)")
        parser.add_argument('--apply', action='store_true',
                            help='Write changes. Omit for a dry run (default).')

    def _base_qs(self, opts):
        qs = Block.objects.filter(
            classification_state='proposed',
            is_categorized=True,
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

        # Three disjoint sub-groups.
        genuine_change = base.filter(
            client_id__isnull=False,
            proposed_client_id__isnull=False,
        ).exclude(proposed_client_id=F('client_id'))

        has_client_no_conflict = base.filter(client_id__isnull=False).filter(
            Q(proposed_client_id__isnull=True) | Q(proposed_client_id=F('client_id'))
        )

        no_client = base.filter(client_id__isnull=True)

        def stat(qs):
            a = qs.aggregate(n=Count('id'), m=Sum('minutes'))
            return a['n'] or 0, a['m'] or 0

        gc_n, gc_m = stat(genuine_change)
        hc_n, hc_m = stat(has_client_no_conflict)
        nc_n, nc_m = stat(no_client)
        tot_n, tot_m = stat(base)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nProposed-limbo heal — {scope} — mode={opts['mode']} — "
            f"{'APPLY' if opts['apply'] else 'DRY RUN'}"))
        self.stdout.write(
            f"\nTotal limbo blocks: {tot_n}  ({tot_m} min, ~{tot_m/60:.1f} h)\n"
            f"  A) genuine change (proposal != client): {gc_n}  ({gc_m} min)\n"
            f"  B) has client, no/own proposal:         {hc_n}  ({hc_m} min)\n"
            f"  C) no client:                           {nc_n}  ({nc_m} min)\n"
        )

        # Per-org breakdown when running across all orgs.
        if not opts.get('org_id'):
            self.stdout.write("By org:")
            for row in base.values('org_id').annotate(
                    n=Count('id'), m=Sum('minutes')).order_by('-n'):
                self.stdout.write(f"  org {row['org_id']}: {row['n']} blocks, "
                                  f"{row['m'] or 0} min")

        if opts['mode'] == 'surface':
            self.stdout.write(self.style.WARNING(
                "\nsurface mode — nothing auto-billed. All blocks routed to the "
                "confirm/review queue:"))
            self.stdout.write(
                f"  A ({gc_n}) -> is_categorized=False (shows 'AI suggests …')\n"
                f"  B ({hc_n}) -> is_categorized=False, proposed_client:=client "
                f"(shows 'confirm as <client>')\n"
                f"  C ({nc_n}) -> is_categorized=False, state='captured' "
                f"(assign-a-client review)\n")
        else:
            self.stdout.write(self.style.WARNING(
                "\nhybrid mode — auto-commits the non-conflicting blocks:"))
            self.stdout.write(
                f"  A ({gc_n}) -> SURFACE for review (is_categorized=False)\n"
                f"  B ({hc_n}) -> COMMIT under current client (billable now)\n"
                f"  C ({nc_n}) -> is_categorized=False, state='captured' "
                f"(assign-a-client review)\n")

        # Sample
        self.stdout.write("Sample (up to 15):")
        for b in base.select_related('client', 'proposed_client').order_by('-day')[:15]:
            cn = b.client.name if b.client_id else '(no client)'
            pn = b.proposed_client.name if b.proposed_client_id else '-'
            self.stdout.write(
                f"  {b.pk} | {b.day} | {b.minutes or 0:3d}m | bill={b.is_billable!s:5s} "
                f"| {cn[:28]:28s} -> {pn[:24]}")

        if not opts['apply']:
            self.stdout.write(self.style.NOTICE(
                "\nDRY RUN — no writes. Re-run with --apply to commit."))
            return

        now = timezone.now()
        with transaction.atomic():
            if opts['mode'] == 'surface':
                a = genuine_change.update(
                    is_categorized=False,
                    state_changed_by='admin_bulk', state_changed_at=now)
                b = has_client_no_conflict.update(
                    is_categorized=False,
                    proposed_client_id=F('client_id'),
                    state_changed_by='admin_bulk', state_changed_at=now)
                c = no_client.update(
                    is_categorized=False,
                    classification_state='captured',
                    state_changed_by='admin_bulk', state_changed_at=now)
                self.stdout.write(self.style.SUCCESS(
                    f"\n✅ Surfaced {a + b + c} blocks (A={a}, B={b}, C={c}). "
                    f"They now appear in the Categorize / Daily Review confirm "
                    f"queue. Nothing was billed automatically."))
            else:
                a = genuine_change.update(
                    is_categorized=False,
                    state_changed_by='admin_bulk', state_changed_at=now)
                b = has_client_no_conflict.update(
                    classification_state='committed',
                    categorized_by='ai', categorized_at=now,
                    state_changed_by='admin_bulk', state_changed_at=now)
                c = no_client.update(
                    is_categorized=False,
                    classification_state='captured',
                    state_changed_by='admin_bulk', state_changed_at=now)
                self.stdout.write(self.style.SUCCESS(
                    f"\n✅ Healed {a + b + c} blocks: committed {b} under their "
                    f"current client (now billable), surfaced {a} genuine-change "
                    f"+ {c} no-client for review."))
