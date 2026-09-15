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
        from tracker.models import Block

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

        # One derivation, shared with shadow_needs_human — see
        # misfile_evidence.flagged_blocks_for_org for why this must not be a
        # MismatchFlag query.
        blocks, scanned_blocks = me.flagged_blocks_for_org(org_id, opts['days'])
        w(f"  scanned {scanned_blocks:,} committed blocks")

        flipped, withdrawn, other = [], [], []
        scanned = 0
        # A zero in the three buckets below is ambiguous on its own: the rule
        # might be changing nothing because the title and the clock always
        # agree, or because the title signal is never there to be outvoted in
        # the first place. Those are opposite findings, so the population is
        # counted as well as the diff. See the SIGNALS block in the output.
        pop = {'title': 0, 'temporal': 0, 'both': 0, 'disagree': 0,
               'title_is_booked': 0, 'neither': 0}
        verdicts = {}
        live = 0
        # No .iterator(): the Neon pooler silently TRUNCATES server-side
        # cursors (see utils/db_iter), and a shadow run that quietly stops
        # early reports numbers that look fine and are wrong. Flagged rows fit
        # in memory; the wider scan in shadow_title_specificity pages by key.
        for b in blocks:
            scanned += 1
            old = self._draft(b, ctx, False)
            new = self._draft(b, ctx, True)
            verdicts[old.verdict] = verdicts.get(old.verdict, 0) + 1

            # Count the population ONLY over rows whose draft actually reaches
            # draft_from_signals. draft_for_block asks _stale_flag_draft first
            # and short-circuits when the detector no longer flags the block —
            # and a queue fills up with those (org 21 once had 19 open flags,
            # 18 already correct). An earlier version of this command counted
            # signals for every row via gather_signals directly, so it could
            # report "5 rows where the title and the clock disagree" about rows
            # whose verdict never consulted either. That is what produced a
            # contradiction between the SIGNALS block and a zero diff.
            if old.verdict == me.VERDICT_STALE:
                continue
            live += 1
            sigs = me.gather_signals(b, ctx)
            t = next((x for x in sigs
                      if x.kind == 'title' and x.supports is not None), None)
            temporal = [x for x in sigs if x.kind in me.TEMPORAL_KINDS
                        and x.supports is not None]
            if t:
                pop['title'] += 1
                if t.supports == b.client_id:
                    pop['title_is_booked'] += 1
            if temporal:
                pop['temporal'] += 1
            if t and temporal:
                pop['both'] += 1
                # Only a temporal signal backing a different RIVAL can change
                # the target. One backing the BOOKED client never competed for
                # it — draft_from_signals keeps those in booked_sigs, outside
                # `rivals` entirely — so counting it as a disagreement invented
                # a contradiction with the zero diff that was not there.
                if any(x.supports not in (t.supports, b.client_id)
                       for x in temporal):
                    pop['disagree'] += 1
            if not t and not temporal:
                pop['neither'] += 1
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
        stale = verdicts.get(me.VERDICT_STALE, 0)
        w("  VERDICTS — what these flagged rows actually are")
        for v, n in sorted(verdicts.items(), key=lambda kv: -kv[1]):
            note = ("   <- already fixed; draft_for_block short-circuits "
                    "before any signal is weighed" if v == me.VERDICT_STALE else "")
            w(f"    {v:<24} {n:>6}{note}")
        w("")
        w(f"  SIGNALS — over the {live:,} rows that reach the rule "
          f"({stale:,} stale rows excluded)")
        w(f"    title names somebody      {pop['title']:>6}   "
          f"({pop['title_is_booked']} of them name the client it is already on)")
        w(f"    temporal evidence present {pop['temporal']:>6}")
        w(f"    both present              {pop['both']:>6}")
        w(f"    …backing a different RIVAL{pop['disagree']:>6}   "
          f"<- the only rows this rule can change")
        w(f"    neither                   {pop['neither']:>6}")
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

        if not (flipped or withdrawn or other):
            if scanned == 0:
                w("Nothing to measure: the scan flagged no rows at all in "
                  "this window. Widen --days.")
            elif live == 0:
                w(f"No change, and no row could have changed: all {scanned:,} "
                  f"flagged blocks are STALE — the detector no longer flags "
                  f"them, so draft_for_block returns 'already fixed' before "
                  f"any signal is weighed. This window says nothing about the "
                  f"rule either way.")
            elif pop['disagree'] == 0 and pop['title'] == 0:
                w("No change, and the reason is that the title signal never "
                  "fired on any of these rows — there was nothing to outvote. "
                  "That is a finding about the TITLE MATCHER, not about this "
                  "rule: run shadow_title_specificity --explain on one of "
                  "these blocks to see which gate is silencing it.")
            elif pop['disagree'] == 0:
                w("No change, and the reason is that on every row where the "
                  "title spoke, the clock either agreed with it or backed the "
                  "client the block is already on — which never competed for "
                  "the target anyway. The rule is correct and idle here.")
            else:
                w(f"No change, but {pop['disagree']} rows DID have the title "
                  f"and the clock disagreeing. That combination should have "
                  f"produced a difference — suspect the harness before "
                  f"believing the zero.")
