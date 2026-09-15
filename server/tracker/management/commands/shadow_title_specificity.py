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
THE QUEUE comes first, because it is what decides. `detect_mismatch` is the
detector that RAISES a row into the Mismatches tab, and it shares rank_rivals
with the reading detector, so the flag can add accusations people have to work.

  NEW FLAGS      rows that become an accusation. Read every one.
  DROPPED FLAGS  accusations that disappear.
  RETARGETED     now accuse a different client. Read every one.

THE READING is `detect_title_client` — what the evidence cards explain with. It
is the quieter half: a wrong answer here misleads a reviewer, but does not by
itself put a row in front of anybody.

  CONFIRMS   silent before, now names THE CLIENT IT IS ALREADY BOOKED TO.
             These can only help: the worst case is the detector agreeing with
             a booking nobody was going to question.
  ACCUSES    silent before, now names a DIFFERENT client. Every one of these is
             a NEW accusation against a booking. Read them all. A gain is not
             free just because nothing was lost — this is where a wrong answer
             hides, and it is the bucket an earlier version of this command
             wrongly counted as clean.
  LOST       named a client before, silent now. Should be ZERO — the flag only
             ever removes a candidate that could not have won anyway.
  CHANGED    named one client before, a different one now. Read every one.

Flip the default only when LOST and CHANGED are empty AND every ACCUSES row
has been read and is right:

    CENTER_ONLY_CANNOT_SUPPRESS = True   # tracker/utils/client_name_match.py
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

    def _mismatch(self, title, booked_cid, ctx, flag):
        """The detector that actually raises a row into the queue."""
        if not booked_cid or booked_cid not in ctx.names:
            return None
        before = cnm.CENTER_ONLY_CANNOT_SUPPRESS
        cnm.CENTER_ONLY_CANNOT_SUPPRESS = flag
        try:
            return cnm.detect_mismatch(title, booked_cid, ctx.index, ctx.names,
                                       firm_name=ctx.firm_name)
        finally:
            cnm.CENTER_ONLY_CANNOT_SUPPRESS = before

    def handle(self, *args, **opts):
        from datetime import timedelta

        from django.utils import timezone

        from tracker.models import Block
        from tracker.services.misfile_evidence import context_for
        from tracker.utils.db_iter import keyset_iter

        org_id = opts['org']
        ctx = context_for(org_id)
        if not ctx.names:
            raise CommandError(f"org {org_id} has no clients")

        if opts['explain'] is not None:
            return self._explain(opts['explain'], ctx)

        since = timezone.now().date() - timedelta(days=opts['days'])
        # keyset_iter, not .iterator(): the Neon pooler silently truncates
        # server-side cursors, and a shadow run that stops early reports
        # numbers that look fine and are wrong (see utils/db_iter).
        blocks = keyset_iter(
            Block.objects
            .filter(org_id=org_id, deleted_at__isnull=True, day__gte=since)
            .exclude(window_title='')
            .exclude(window_title__isnull=True)
            .only('id', 'window_title', 'client_id', 'day', 'minutes'),
            chunk_size=1000)

        confirms, accuses, lost, changed = [], [], [], []
        # detect_title_client is only half the story, and the quieter half.
        # `detect_mismatch` is what RAISES a row into the Mismatches queue, and
        # it runs through the same rank_rivals, so the flag can add or remove
        # accusations a person actually has to work. Measuring only the first
        # one answered "does the detector see more?" when the question that
        # decides the flip is "does the QUEUE get bigger, and is it right?".
        new_flags, dropped_flags, retargeted = [], [], []
        scanned = 0
        # Titles repeat constantly (the same document alt-tabbed all morning),
        # and the detector is pure, so score each distinct one once.
        # detect_mismatch also depends on the booked client, so its cache is
        # keyed on the pair.
        seen, seen_mm = {}, {}
        for b in blocks:
            scanned += 1
            title = b.window_title or ''
            if title not in seen:
                old = self._detect(title, ctx, False)
                new = self._detect(title, ctx, True)
                seen[title] = (old, new)

            mk = (title, b.client_id)
            if mk not in seen_mm:
                seen_mm[mk] = (self._mismatch(title, b.client_id, ctx, False),
                               self._mismatch(title, b.client_id, ctx, True))
            mo, mn = seen_mm[mk]
            mo_id = mo['looks_like_client_id'] if mo else None
            mn_id = mn['looks_like_client_id'] if mn else None
            if mo_id != mn_id:
                mrow = (b.id, b.day, title[:110], ctx.names.get(b.client_id, '—'),
                        mo['looks_like_client_name'] if mo else None,
                        mn['looks_like_client_name'] if mn else None)
                if mo_id is None:
                    new_flags.append(mrow)
                elif mn_id is None:
                    dropped_flags.append(mrow)
                else:
                    retargeted.append(mrow)

            old, new = seen[title]
            old_id = old['client_id'] if old else None
            new_id = new['client_id'] if new else None
            if old_id == new_id:
                continue
            row = (b.id, b.day, title[:110],
                   ctx.names.get(b.client_id, '—'),
                   old['client_name'] if old else None,
                   new['client_name'] if new else None)
            if old_id is None:
                # Split the gains by what they imply. Naming the client the
                # block is already on is a confirmation; naming a different one
                # is an accusation, and the two do not deserve the same line in
                # a summary somebody decides from.
                (confirms if new_id == b.client_id else accuses).append(row)
            elif new_id is None:
                lost.append(row)
            else:
                changed.append(row)

        w = self.stdout.write
        w("")
        w(f"org {org_id} · {opts['days']}d · {scanned:,} blocks "
          f"({len(seen):,} distinct titles) · {len(ctx.names):,} clients")
        w("")
        w("  THE QUEUE — detect_mismatch, what people actually have to work")
        w(f"    NEW FLAGS      {len(new_flags):>6}   rows that become an "
          f"accusation  {'<-- READ EVERY ONE' if new_flags else 'ok'}")
        w(f"    DROPPED FLAGS  {len(dropped_flags):>6}   accusations that "
          f"disappear")
        w(f"    RETARGETED     {len(retargeted):>6}   accuse a different client "
          f"than before  {'<-- READ EVERY ONE' if retargeted else 'ok'}")
        w("")
        w("  THE READING — detect_title_client, what the cards explain with")
        w(f"  CONFIRMS {len(confirms):>6}   now names the client it is already "
          f"booked to — safe")
        w(f"  ACCUSES  {len(accuses):>6}   now names a DIFFERENT client — a NEW "
          f"accusation  {'<-- READ EVERY ONE' if accuses else 'ok'}")
        w(f"  LOST     {len(lost):>6}   named a client before, silent now   "
          f"{'<-- MUST BE ZERO' if lost else 'ok'}")
        w(f"  CHANGED  {len(changed):>6}   named a different client than before "
          f"{'<-- READ EVERY ONE' if changed else 'ok'}")
        w("")

        for label, rows in (("NEW FLAGS", new_flags),
                            ("RETARGETED", retargeted),
                            ("DROPPED FLAGS", dropped_flags),
                            ("ACCUSES", accuses), ("CHANGED", changed),
                            ("LOST", lost), ("CONFIRMS", confirms)):
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

        if new_flags or retargeted:
            w(f"The QUEUE changes: {len(new_flags)} new accusation(s), "
              f"{len(retargeted)} retargeted. Those are rows a person has to "
              f"work, so read them above before flipping anything — this is "
              f"the number that decides it, not the reading counts below.")
            w("")
        if not (confirms or accuses or lost or changed):
            w("No effect on this window — the flag is not worth shipping on "
              "this evidence.")
        elif lost or changed:
            w("NOT clean. Read the LOST/CHANGED rows before shipping.")
        elif accuses:
            w(f"{len(accuses)} row(s) became a NEW ACCUSATION against a "
              f"booking. Read every one above and satisfy yourself it is "
              f"right before flipping the flag — a gain is not free just "
              f"because nothing was lost.")
            w("")
            w("If one looks wrong, check the BOOKED client's spelling in the "
              "roster first: _tokenize does not stem, so a roster reading "
              "'St. Peters Church' cannot match a document saying "
              "\"St. Peter's\" — peters and peter are different tokens — and "
              "the correct client is then invisible in its own file.")
        elif new_flags or retargeted:
            pass          # already said above, and it outranks the rest
        else:
            w("Clean — every gain confirms an existing booking, and the queue "
              "is unchanged. Flip CENTER_ONLY_CANNOT_SUPPRESS = True in "
              "tracker/utils/client_name_match.py")

    # ── one block, in full ──────────────────────────────────────────────────

    def _explain(self, block_id, ctx):
        """Why is this block's title silent? Against the REAL roster."""
        from tracker.models import Block

        b = Block.objects.filter(id=block_id).only(
            'id', 'window_title', 'client_id', 'org_id', 'day').first()
        if not b:
            raise CommandError(f"block {block_id} not found")

        title = b.window_title or ''
        w = self.stdout.write
        w("")
        w(f"block {b.id} · {b.day} · org {b.org_id}")
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
