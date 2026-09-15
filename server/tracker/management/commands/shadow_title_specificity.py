"""
Shadow harness for CENTER_ONLY_CANNOT_SUPPRESS.

READ-ONLY. Writes nothing, changes nothing. It runs the title detector twice
over the same blocks — once as production behaves today, once with the flag on
— and reports every block where the two disagree.

WHY IT EXISTS
-------------
A QB window title carries a "[Vendor Center: X]" tag naming somebody the client
does business with. `_named_only_in_center` has always refused to reroute a
block TO such a client, but it ran only on the winner and only after the
ambiguity gate — so a vendor could still be the runner-up that suppressed the
real answer. The flag drops center-only clients from the ranking entirely.

That mechanism is demonstrated on constructed rosters (tracker/
title_specificity_test.py). It is NOT yet demonstrated on a real one, which is
what this command is for. Turning the flag on without running it would be
guessing.

USAGE
-----
  # Why is ONE block silent? Prints the real scoring table and the exact gate.
  python manage.py shadow_title_specificity --org 21 --explain 48013

  # What would the flag change across the firm?
  python manage.py shadow_title_specificity --org 21 --days 120
  python manage.py shadow_title_specificity --org 21 --days 120 --samples 25

READING THE RESULT
------------------
  GAINED   silent before, names a client now. The point of the change.
  LOST     named a client before, silent now. Should be ZERO — the flag only
           ever removes a candidate that could not have won anyway. Any LOST
           row is a reason not to ship.
  CHANGED  named a DIFFERENT client. Read every one of these by hand. This is
           where a wrong answer would hide.

If GAINED is healthy and LOST/CHANGED are empty, flip the default in
tracker/utils/client_name_match.py:

    CENTER_ONLY_CANNOT_SUPPRESS = True
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.utils import client_name_match as cnm


class Command(BaseCommand):
    help = "Shadow-compare title detection with CENTER_ONLY_CANNOT_SUPPRESS on and off (read-only)."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--days', type=int, default=120)
        parser.add_argument('--explain', type=int, default=None,
                            help='A block id: show its full scoring table and which gate silenced it')
        parser.add_argument('--samples', type=int, default=10,
                            help='How many example rows to print per outcome')

    # ── helpers ─────────────────────────────────────────────────────────────

    def _detect(self, title, ctx, flag):
        before = cnm.CENTER_ONLY_CANNOT_SUPPRESS
        cnm.CENTER_ONLY_CANNOT_SUPPRESS = flag
        try:
            return cnm.detect_title_client(title, ctx.index, ctx.names,
                                           firm_name=ctx.firm_name)
        finally:
            cnm.CENTER_ONLY_CANNOT_SUPPRESS = before

    def handle(self, *args, **opts):
        from datetime import timedelta

        from django.utils import timezone

        from tracker.models import Block
        from tracker.services.misfile_evidence import context_for

        org_id = opts['org']
        ctx = context_for(org_id)
        if not ctx.names:
            raise CommandError(f"org {org_id} has no clients")

        if opts['explain'] is not None:
            return self._explain(opts['explain'], ctx)

        since = timezone.now().date() - timedelta(days=opts['days'])
        blocks = (Block.objects
                  .filter(org_id=org_id, deleted_at__isnull=True, date__gte=since)
                  .exclude(window_title='')
                  .exclude(window_title__isnull=True)
                  .only('id', 'window_title', 'client_id', 'date', 'minutes')
                  .order_by('id')
                  .iterator(chunk_size=500))

        gained, lost, changed = [], [], []
        scanned = 0
        # Titles repeat constantly (the same document alt-tabbed all morning),
        # and the detector is pure, so score each distinct one once.
        seen = {}
        for b in blocks:
            scanned += 1
            title = b.window_title or ''
            if title not in seen:
                old = self._detect(title, ctx, False)
                new = self._detect(title, ctx, True)
                seen[title] = (old, new)
            old, new = seen[title]
            old_id = old['client_id'] if old else None
            new_id = new['client_id'] if new else None
            if old_id == new_id:
                continue
            row = (b.id, b.date, title[:110],
                   ctx.names.get(b.client_id, '—'),
                   old['client_name'] if old else None,
                   new['client_name'] if new else None)
            if old_id is None:
                gained.append(row)
            elif new_id is None:
                lost.append(row)
            else:
                changed.append(row)

        w = self.stdout.write
        w("")
        w(f"org {org_id} · {opts['days']}d · {scanned:,} blocks "
          f"({len(seen):,} distinct titles) · {len(ctx.names):,} clients")
        w("")
        w(f"  GAINED   {len(gained):>6}   silent before, names a client now")
        w(f"  LOST     {len(lost):>6}   named a client before, silent now   "
          f"{'<-- MUST BE ZERO' if lost else 'ok'}")
        w(f"  CHANGED  {len(changed):>6}   names a DIFFERENT client now     "
          f"{'<-- READ EVERY ONE' if changed else 'ok'}")
        w("")

        for label, rows in (("CHANGED", changed), ("LOST", lost), ("GAINED", gained)):
            if not rows:
                continue
            w(f"── {label} " + "─" * 58)
            for bid, date, title, booked, old, new in rows[:opts['samples']]:
                w(f"  block {bid} · {date} · booked: {booked}")
                w(f"    {title}")
                w(f"    before: {old!r}")
                w(f"    after : {new!r}")
            if len(rows) > opts['samples']:
                w(f"  … and {len(rows) - opts['samples']:,} more "
                  f"(raise --samples to see them)")
            w("")

        if gained and not lost and not changed:
            w("Clean. Flip CENTER_ONLY_CANNOT_SUPPRESS = True in "
              "tracker/utils/client_name_match.py")
        elif not gained:
            w("No effect on this window — the flag is not worth shipping on "
              "this evidence.")
        else:
            w("Not clean. Read the LOST/CHANGED rows before shipping.")

    # ── one block, in full ──────────────────────────────────────────────────

    def _explain(self, block_id, ctx):
        """Why is this block's title silent? Against the REAL roster."""
        from tracker.models import Block

        b = Block.objects.filter(id=block_id).only(
            'id', 'window_title', 'client_id', 'org_id', 'date').first()
        if not b:
            raise CommandError(f"block {block_id} not found")

        title = b.window_title or ''
        w = self.stdout.write
        w("")
        w(f"block {b.id} · {b.date} · org {b.org_id}")
        w(f"  title  : {title}")
        w(f"  booked : {ctx.names.get(b.client_id, '—')}")
        stripped = cnm.strip_app_chrome(title)
        toks = set(cnm._tokenize(stripped))
        w(f"  after chrome strip: {stripped!r}")
        w(f"  has [Center:] tag : {bool(cnm._CENTER_BRACKET_RE.search(title))}")
        w("")

        scored = []
        for cid, name in ctx.names.items():
            cov, topw, abs_hit = cnm.score_title_against_client(toks, cid, ctx.index)
            if abs_hit > 0:
                scored.append((abs_hit, cid, name, cov, topw))
        scored.sort(key=lambda r: -r[0])

        w(f"  {'abs':>6} {'cov':>5} {'topw':>5}  {'ctr?':<5} client")
        for abs_hit, cid, name, cov, topw in scored[:12]:
            centre = cnm._named_only_in_center(title, cid, ctx.index)
            w(f"  {abs_hit:>6.2f} {cov:>5.2f} {topw:>5.2f}  "
              f"{'YES' if centre else '-':<5} {name} [{cid}]")
        if not scored:
            w("    (no client shares a token with this title)")
            return
        w("")

        best = scored[0]
        second = scored[1] if len(scored) > 1 else None
        w(f"  gates: cov>={cnm.STRONG_COVERAGE} {best[3] >= cnm.STRONG_COVERAGE} · "
          f"abs>={cnm.MIN_ABS_HIT} {best[0] >= cnm.MIN_ABS_HIT} · "
          f"topw>={cnm.MIN_TOP_TOKEN} {best[4] >= cnm.MIN_TOP_TOKEN}")
        if second:
            ratio = second[0] / best[0] if best[0] else 0
            w(f"  ambiguity: runner-up {second[2]!r} at {ratio:.0%} of the "
              f"winner (trips at {cnm.AMBIGUITY_RATIO:.0%}) -> "
              f"{'SUPPRESSED' if ratio >= cnm.AMBIGUITY_RATIO else 'ok'}")
        w("")
        for flag in (False, True):
            d = self._detect(title, ctx, flag)
            w(f"  CENTER_ONLY_CANNOT_SUPPRESS={str(flag):<5} -> "
              f"{d['client_name'] if d else None}")
        w("")
