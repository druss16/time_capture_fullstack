"""
Find — and optionally fix — client names and aliases that cannot identify
their own client.

    python manage.py fix_client_ambiguity --org 21
    python manage.py fix_client_ambiguity --org 21 --apply     # prunes aliases only

Why this exists. Org 21 books 436 hours a quarter to a look-alike client with
nothing in the text to prove it — not because the matcher is weak, but because
several clients answer to the same words. "St. Mary's Church" fits six
parishes at identical mass, so whichever wins, wins by tie-break. No detector
can fix that; the names have to stop colliding.

Two kinds of problem, and only ONE of them is safe to fix automatically:

  PRUNE  (safe, --apply does it)
         The client HAS a word that separates it from its look-alikes, and an
         alias omits that word. Such an alias can only ever match the group,
         never the member — it is strictly worse than the client's own name and
         it actively widens the ambiguity gate, suppressing correct matches.
         Deleting it removes a magnet and loses nothing.

  RENAME (never automatic — reported only)
         Nothing in the client's name or aliases separates it from its
         look-alikes at all. There is no correct answer to invent, so the
         command mines the org's own captured window titles for a longer form
         of the name somebody has actually typed, and proposes it. A person
         decides, because renaming a client changes what appears on an invoice.
"""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction


def _stem(w):
    """Fold a trailing possessive/plural s so leo and leos are one word.

    Without this the command recommended deleting "St Leo & St Ann Church" from
    "St Leo's & St Ann's Church" because the name keeps "leos" (4 letters, so
    the normalizer leaves it) while the alias yields "leo" (3 letters, dropped
    before comparison). Same word, different spelling of the same possessive —
    and a deletion proposed on that basis is the kind of wrong that makes a
    person stop trusting the whole list.
    """
    return w[:-1] if len(w) > 3 and w.endswith('s') else w


def _carries(alias_words, disting):
    """Does this alias carry any of the distinguishing words, stems and all?"""
    a = {_stem(w) for w in alias_words}
    return bool(a & {_stem(w) for w in disting})


class Command(BaseCommand):
    help = "Report (and optionally prune) client names/aliases that cannot identify their client."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--days', type=int, default=90,
                            help='Window for the billable-hours figures and title mining.')
        parser.add_argument('--apply', action='store_true',
                            help='Delete the magnet ALIASES. Never renames anything.')
        parser.add_argument('--limit', type=int, default=40)

    def handle(self, *args, **o):
        from datetime import timedelta

        from django.db.models import Sum
        from django.utils import timezone

        from tracker.models import Block, Client
        from tracker.services import client_families

        org_id = o['org']
        la = client_families.for_org(org_id, use_cache=False)
        clients = list(Client.objects.filter(org_id=org_id).only('id', 'name', 'aliases'))
        by_id = {c.id: c for c in clients}

        cut = timezone.now() - timedelta(days=o['days'])
        hours = {
            r['client_id']: (r['m'] or 0) / 60
            for r in Block.objects.filter(
                org_id=org_id, deleted_at__isnull=True, client_id__isnull=False,
                classification_state='committed', is_billable=True, start__gte=cut,
            ).values('client_id').annotate(m=Sum('minutes'))
        }

        prune, rename = [], []
        for c in clients:
            peers = [p.id for p in clients
                     if p.id != c.id and la.are_lookalikes(c.id, p.id)]
            if not peers:
                continue
            disting = la.distinguishing_words(c.id, [c.id] + peers)
            # Only words that NAME somebody count. `distinguishing_words`
            # happily returns "church" when the sibling is a cemetery — true,
            # but the entity-class rule already separates those, so pruning on
            # it would delete a working alias to fix nothing. St. Peters Church
            # was recommended for exactly that before this line existed.
            disting &= la.identifying_words(c.id)
            peer_names = [by_id[p].name for p in peers]

            if not disting:
                rename.append({
                    'client': c, 'peers': peer_names,
                    'hours': hours.get(c.id, 0.0),
                })
                continue

            bad = [a for a in (c.aliases or [])
                   if not _carries(client_families.text_words(a), disting)]
            if bad:
                prune.append({
                    'client': c, 'aliases': bad, 'keep': disting,
                    'peers': peer_names, 'hours': hours.get(c.id, 0.0),
                    'load_bearing': {},
                })

        # Which of those aliases are actually CARRYING work right now.
        #
        # "Strictly worse than the client's own name" is true of the alias as a
        # NAME and false as a bridge: if captured titles say "St Marys Cemetery"
        # and never say "Bville", that alias is the only thing connecting real
        # work to this client, and deleting it trades an ambiguous attribution
        # for no attribution at all. Worse, quietly — the time simply stops
        # arriving. So an alias that is load-bearing is reported and NEVER
        # auto-deleted, whatever the name-theory says.
        self._mark_load_bearing(org_id, cut, prune, la)

        prune.sort(key=lambda r: -r['hours'])
        rename.sort(key=lambda r: -r['hours'])

        # ── PRUNE ────────────────────────────────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'MAGNET ALIASES — drop the word that identifies their own client '
            f'({sum(len(r["aliases"]) for r in prune)} across {len(prune)} clients)'))
        self.stdout.write(
            '  Each can only ever match the look-alike GROUP, never the member.\n')
        for r in prune[:o['limit']]:
            self.stdout.write(
                f"  {r['hours']:>6.1f}h  {r['client'].name[:44]}"
                f"   (needs one of: {', '.join(sorted(r['keep'])[:4])})")
            for a in r['aliases']:
                hits = r['load_bearing'].get(a, 0)
                if hits:
                    self.stdout.write(self.style.ERROR(
                        f"        KEEP    {a!r} — matches {hits} block"
                        f"{'' if hits == 1 else 's'} the client's own name does not"))
                else:
                    self.stdout.write(self.style.WARNING(f"        delete  {a!r}"))
            self.stdout.write(
                f"        collides with: {', '.join(p[:30] for p in r['peers'][:3])}")

        # ── RENAME ───────────────────────────────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'NO DISTINGUISHING WORD AT ALL — {len(rename)} clients'))
        self.stdout.write(
            '  Nothing in the roster separates these from their look-alikes.\n'
            '  Renaming is the only lever, and it is never done automatically.\n')

        suggestions = self._mine_titles(org_id, cut, [r['client'] for r in rename], la)
        for r in rename[:o['limit']]:
            c = r['client']
            self.stdout.write(
                f"  {r['hours']:>6.1f}h  [{c.id}] {c.name}")
            self.stdout.write(
                f"        collides with: {', '.join(p[:34] for p in r['peers'][:4])}")
            for text, n in suggestions.get(c.id, [])[:3]:
                self.stdout.write(self.style.SUCCESS(
                    f"        seen in your own titles {n:>3}x:  {text}"))
            if not suggestions.get(c.id):
                self.stdout.write(
                    "        no longer form found in captured titles — needs a human")

        # ── APPLY ────────────────────────────────────────────────────────────
        self.stdout.write('')
        if not o['apply']:
            n = sum(len(r['aliases']) for r in prune)
            self.stdout.write(self.style.SUCCESS(
                f'  dry run — nothing changed. --apply would delete {n} alias'
                f'{"" if n == 1 else "es"} and rename nothing.'))
            return

        deleted = held = 0
        with transaction.atomic():
            for r in prune:
                c = r['client']
                drop = [a for a in r['aliases'] if not r['load_bearing'].get(a)]
                held += len(r['aliases']) - len(drop)
                if not drop:
                    continue
                keep = [a for a in (c.aliases or []) if a not in drop]
                deleted += len(c.aliases or []) - len(keep)
                c.aliases = keep
                c.save(update_fields=['aliases'])
        self.stdout.write(self.style.SUCCESS(
            f'  deleted {deleted} magnet aliases. No client was renamed.'))
        if held:
            self.stdout.write(self.style.ERROR(
                f'  kept {held} that are load-bearing — deleting those would '
                f'have cost attribution, not ambiguity.'))
        self.stdout.write(
            '  Re-run `attribution_audit --org %s` to see the effect.' % org_id)

    # -------------------------------------------------------------------------

    def _mark_load_bearing(self, org_id, cut, prune, la):
        """Count blocks each doomed alias matches that the client's name does not."""
        from tracker.models import Block
        from tracker.services import client_families
        from tracker.utils.client_name_match import strip_app_chrome
        from tracker.utils.db_iter import keyset_iter

        if not prune:
            return
        watch = []          # (row, alias, alias_words, own_words)
        for r in prune:
            own = la.identifying_words(r['client'].id) & set(r['keep'])
            for a in r['aliases']:
                aw = client_families.text_words(a)
                if aw:
                    watch.append((r, a, aw, own))

        qs = (Block.objects.filter(org_id=org_id, deleted_at__isnull=True,
                                   start__gte=cut)
              .exclude(window_title__isnull=True).exclude(window_title=''))
        for b in keyset_iter(qs.only('id', 'window_title', 'file_path'), 1000):
            text = f"{b.window_title or ''} {b.file_path or ''}"
            words = client_families.text_words(strip_app_chrome(text))
            if not words:
                continue
            for row, alias, aw, own in watch:
                if aw <= words and not (own & words):
                    row['load_bearing'][alias] = row['load_bearing'].get(alias, 0) + 1

    def _mine_titles(self, org_id, cut, clients, la):
        """Longer forms of these clients' names that somebody has actually typed.

        The point is not to guess a name — it is to surface the one the CLIENT
        already uses. "Assumption Church" has no distinguishing word, but org
        21's own captured titles contain "Franciscan Church of the Assumption
        Ministries", which does. That is a rename proposal with evidence
        behind it rather than an invention.
        """
        from tracker.models import Block
        from tracker.utils.client_name_match import strip_app_chrome
        from tracker.utils.db_iter import keyset_iter

        if not clients:
            return {}
        ident = {c.id: la.identifying_words(c.id) for c in clients}
        out = defaultdict(Counter)

        qs = (Block.objects.filter(org_id=org_id, deleted_at__isnull=True,
                                   start__gte=cut)
              .exclude(window_title__isnull=True).exclude(window_title=''))
        for b in keyset_iter(qs.only('id', 'window_title'), 1000):
            raw = strip_app_chrome(b.window_title or '')
            words = client_families_text_words(raw)
            if not words:
                continue
            for cid, iw in ident.items():
                if not iw or not iw <= words:
                    continue                       # title must carry the whole name
                extra = words - iw
                if not extra:
                    continue                       # no MORE than the name: useless
                out[cid][raw.strip()[:80]] += 1

        return {cid: [t for t in c.most_common(6)] for cid, c in out.items()}


def client_families_text_words(text):
    from tracker.services import client_families
    return client_families.text_words(text)
