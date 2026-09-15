"""
Shadow harness for TITLE_SIGNAL_TRUSTS_THE_FLAG.

READ-ONLY. Drafts every row the Mismatches tab shows, twice — once as
production behaves today, once with the title signal asking the detector that
raised the row — and reports how the VERDICTS move.

WHY IT EXISTS
-------------
Org 21, 120 days: 145 flagged rows, of which 76 came back `needs_human` — over
half the queue arriving as "there is no recommendation to make" on rows the
detector had a specific accusation about.

`Draft.verdict` defaults to needs_human, and `draft_from_signals` returns early
with that default whenever `rivals` is empty. `rivals` is empty when no signal
supports any client other than the booked one — which happened because
`_title_signal` asked `detect_title_client` (ranks every client, abstains on a
tie) while the row had been raised by `detect_mismatch` (ranks only the others).
A title naming the booked client AND a rival gives those two opposite answers.

READING THE RESULT
------------------
  RESCUED    needs_human -> reassign. A row that now carries the accusation the
             detector actually made. The point of the change.
  REGRESSED  anything -> needs_human. Should be ZERO.
  RETARGETED was already reassign, now names a DIFFERENT client. Read every
             one: this is where a wrong answer hides, because these rows were
             already actionable and the change moved them.
  OTHER      any other verdict transition.

RESCUED rows are only a win if the accusation is RIGHT. They are the same
accusations `detect_mismatch` already makes on the tab today — this does not
invent new ones, it stops the evidence layer contradicting them — but read the
samples before flipping.

USAGE
-----
  python manage.py shadow_needs_human --org 21 --days 120
  python manage.py shadow_needs_human --org 21 --days 120 --samples 25
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.services import misfile_evidence as me


class Command(BaseCommand):
    help = "Shadow-compare misfile drafts with TITLE_SIGNAL_TRUSTS_THE_FLAG on and off (read-only)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--days', type=int, default=120)
        parser.add_argument('--samples', type=int, default=12)

    def _draft(self, block, ctx, flag):
        before = me.TITLE_SIGNAL_TRUSTS_THE_FLAG
        me.TITLE_SIGNAL_TRUSTS_THE_FLAG = flag
        try:
            return me.draft_for_block(block, ctx)
        finally:
            me.TITLE_SIGNAL_TRUSTS_THE_FLAG = before

    def handle(self, *args, **opts):
        org_id = opts['org']
        ctx = me.context_for(org_id)
        if not ctx.names:
            raise CommandError(f"org {org_id} has no clients")
        w = self.stdout.write

        blocks, scanned_blocks = me.flagged_blocks_for_org(org_id, opts['days'])
        w(f"  scanned {scanned_blocks:,} committed blocks")

        rescued, regressed, retargeted, other = [], [], [], []
        before_v, after_v = {}, {}
        n = 0
        for b in blocks:
            n += 1
            old = self._draft(b, ctx, False)
            new = self._draft(b, ctx, True)
            before_v[old.verdict] = before_v.get(old.verdict, 0) + 1
            after_v[new.verdict] = after_v.get(new.verdict, 0) + 1
            if (old.verdict == new.verdict
                    and old.target_client_id == new.target_client_id):
                continue
            row = (b.id, b.day, (b.window_title or '')[:100],
                   ctx.names.get(b.client_id, '—'),
                   old.verdict, old.target_client_name or None,
                   new.verdict, new.target_client_name or None)
            if (old.verdict == me.VERDICT_HUMAN
                    and new.verdict == me.VERDICT_REASSIGN):
                rescued.append(row)
            elif new.verdict == me.VERDICT_HUMAN:
                regressed.append(row)
            elif (old.verdict == me.VERDICT_REASSIGN
                  and new.verdict == me.VERDICT_REASSIGN):
                retargeted.append(row)
            else:
                other.append(row)

        w("")
        w(f"org {org_id} · {opts['days']}d · {n:,} flagged rows drafted twice")
        w("")
        w("  VERDICTS                before -> after")
        for v in sorted(set(before_v) | set(after_v)):
            w(f"    {v:<24} {before_v.get(v, 0):>5} -> {after_v.get(v, 0):>5}")
        w("")
        w(f"  RESCUED     {len(rescued):>5}   needs_human -> reassign")
        w(f"  REGRESSED   {len(regressed):>5}   now needs_human   "
          f"{'<-- MUST BE ZERO' if regressed else 'ok'}")
        w(f"  RETARGETED  {len(retargeted):>5}   already actionable, now a "
          f"DIFFERENT client  {'<-- READ EVERY ONE' if retargeted else 'ok'}")
        w(f"  OTHER       {len(other):>5}")
        w("")

        for label, rows in (("REGRESSED", regressed), ("RETARGETED", retargeted),
                            ("OTHER", other), ("RESCUED", rescued)):
            if not rows:
                continue
            w(f"── {label} " + "─" * 56)
            for bid, day, title, booked, ov, ot, nv, nt in rows[:opts['samples']]:
                w(f"  block {bid} · {day} · booked: {booked}")
                w(f"    {title}")
                w(f"    before: {ov:<13} {ot!r}")
                w(f"    after : {nv:<13} {nt!r}")
            if len(rows) > opts['samples']:
                w(f"  … and {len(rows) - opts['samples']:,} more")
            w("")

        if n == 0:
            w("Nothing to measure — the scan flagged no rows. Widen --days.")
        elif regressed or retargeted:
            w("NOT clean. Read the REGRESSED/RETARGETED rows before shipping.")
        elif not rescued:
            w("No effect on this window — not worth shipping on this evidence.")
        else:
            w(f"{len(rescued)} row(s) stop saying 'no recommendation' and carry "
              f"the accusation the detector already made. Spot-check the "
              f"samples above, then flip TITLE_SIGNAL_TRUSTS_THE_FLAG = True "
              f"in tracker/services/misfile_evidence.py")
