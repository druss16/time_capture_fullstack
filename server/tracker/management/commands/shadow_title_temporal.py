"""
Shadow harness for TITLE_OUTRANKS_TEMPORAL.

READ-ONLY. Writes nothing. Replays the misfile agent's draft for real blocks
twice — once with the old straight sum of signal weights, once with the rule
that the block's own title outranks the work around it — and reports every
block where the two disagree.

WHY IT EXISTS
-------------
The draft's target was `max(rivals, key=sum of weight)`. A title signal caps at
0.85; a neighbour (0.70) plus a same-day sighting (0.55) sums to 1.25. So a
block whose title named one client could be recommended to a different one on
the strength of two clock-based witnesses — the inversion the firm's standing
rule exists to prevent.

The rule is not in doubt; its blast radius is. Two effects are worth measuring
before this runs on a whole firm:

  FLIPPED   the draft now recommends the client the title named, instead of the
            one the clock named. This is the fix working.
  WITHDRAWN the draft now makes NO recommendation, because the title named the
            booked client and only temporal evidence argued otherwise. These
            rows stop proposing a move and become "needs a person".

WITHDRAWN is the number to look at. Each one is a recommendation the firm used
to get and no longer will. That is correct under the rule — a neighbour should
not move a block whose own title agrees with where it sits — but if it is a
large share of the queue, that is worth knowing before, not after.

USAGE
-----
  python manage.py shadow_title_temporal --org 21 --days 120
  python manage.py shadow_title_temporal --org 21 --days 120 --samples 25
  python manage.py shadow_title_temporal --org 21 --explain 48013
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.services import misfile_evidence as me


class Command(BaseCommand):
    help = "Shadow-compare misfile drafts with TITLE_OUTRANKS_TEMPORAL on and off (read-only)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--days', type=int, default=120)
        parser.add_argument('--samples', type=int, default=12)
        parser.add_argument('--explain', type=int, default=None,
                            help='A block id: show its signals and both drafts')

    def _draft(self, block, ctx, flag):
        before = me.TITLE_OUTRANKS_TEMPORAL
        me.TITLE_OUTRANKS_TEMPORAL = flag
        try:
            return me.draft_for_block(block, ctx)
        finally:
            me.TITLE_OUTRANKS_TEMPORAL = before

    def handle(self, *args, **opts):
        from datetime import timedelta

        from django.utils import timezone

        from tracker.models import Block, MismatchFlag

        org_id = opts['org']
        ctx = me.context_for(org_id)
        w = self.stdout.write

        if opts['explain'] is not None:
            b = Block.objects.filter(id=opts['explain']).first()
            if not b:
                raise CommandError(f"block {opts['explain']} not found")
            w("")
            w(f"block {b.id} · {b.day} · booked {ctx.names.get(b.client_id, '—')}")
            w(f"  title: {b.window_title}")
            w("")
            w("  signals:")
            for s in me.gather_signals(b, ctx):
                w(f"    {s.kind:<16} -> {ctx.names.get(s.supports, '—'):<34} "
                  f"w={s.weight:.2f} {'independent' if s.independent else 'from title'}")
            w("")
            for flag in (False, True):
                d = self._draft(b, ctx, flag)
                w(f"  TITLE_OUTRANKS_TEMPORAL={str(flag):<5} -> "
                  f"{d.verdict} · {d.target_client_name or '—'} · "
                  f"confidence {d.confidence:.0%}")
            w("")
            return

        since = timezone.now().date() - timedelta(days=opts['days'])
        # Only FLAGGED blocks are ever drafted, so they are the only population
        # whose behaviour can change. Drafting every block in the window would
        # report differences on rows nobody is shown, and each draft costs
        # neighbour queries.
        flagged = (MismatchFlag.objects
                   .filter(org_id=org_id, detected_at__day__gte=since)
                   .values_list('block_id', flat=True))
        # Deliberately NO .only(): draft_for_block reaches for invoiced,
        # qb_time_activity_id, xero_invoice_id, state_changed_by and
        # categorized_by inside the veto check, and a deferred field there is
        # one refresh_from_db per row — the N+1 that SIGKILLed a worker in
        # PR #439. Flagged rows are few; load them whole.
        blocks = (Block.objects
                  .filter(id__in=list(flagged), org_id=org_id,
                          deleted_at__isnull=True, client_id__isnull=False)
                  .order_by('id'))

        flipped, withdrawn, other = [], [], []
        scanned = 0
        for b in blocks.iterator(chunk_size=200):
            scanned += 1
            old = self._draft(b, ctx, False)
            new = self._draft(b, ctx, True)
            if (old.target_client_id == new.target_client_id
                    and old.verdict == new.verdict):
                continue
            row = (b.id, b.day, (b.window_title or '')[:100],
                   ctx.names.get(b.client_id, '—'),
                   old.target_client_name or None, old.verdict,
                   new.target_client_name or None, new.verdict)
            if new.target_client_id is None and old.target_client_id is not None:
                withdrawn.append(row)
            elif (new.target_client_id is not None
                  and old.target_client_id is not None):
                flipped.append(row)
            else:
                other.append(row)

        w("")
        w(f"org {org_id} · {opts['days']}d · {scanned:,} blocks drafted twice")
        w("")
        w(f"  FLIPPED    {len(flipped):>6}   now recommends the client the TITLE named")
        w(f"  WITHDRAWN  {len(withdrawn):>6}   now makes no recommendation "
          f"(title named the booked client)")
        w(f"  OTHER      {len(other):>6}   any other disagreement — read these")
        w("")
        for label, rows in (("FLIPPED", flipped), ("WITHDRAWN", withdrawn),
                            ("OTHER", other)):
            if not rows:
                continue
            w(f"── {label} " + "─" * 56)
            for bid, date, title, booked, ot, ov, nt, nv in rows[:opts['samples']]:
                w(f"  block {bid} · {date} · booked: {booked}")
                w(f"    {title}")
                w(f"    before: {ov:<13} {ot!r}")
                w(f"    after : {nv:<13} {nt!r}")
            if len(rows) > opts['samples']:
                w(f"  … and {len(rows) - opts['samples']:,} more")
            w("")
