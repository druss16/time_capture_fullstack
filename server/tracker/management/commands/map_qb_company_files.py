"""
Map a firm's QuickBooks company FILES to their client records.

WHY THIS EXISTS
---------------
Stage 4.5 attributes QB work from the open .qbw path instead of the window
title, because QB titles carry the (non-unique) Company Name field: one firm's
directory holds 135 company files of which fourteen read "St. Mary's ...", and
the town that separates them lives only in the filename.

The path is unique, but turning it into a CLIENT still needs the client record's
name — or an alias — to appear in that filename. Where the firm names clients
differently from its files, Stage 4.5 abstains:

    client "Christ our Light Catholic Community"
    file   "Christ Our Light Church Pulaski_QB2024.QBW"   -> no shared identity

Abstaining is safe (it falls back to the old title behaviour) but it is coverage
left on the table. This command reports, file by file, which company files
Stage 4.5 resolves today and which need one alias to start resolving — and can
apply a reviewed list of those aliases.

READ-ONLY BY DEFAULT. Nothing is written without --apply AND --confirm.

USAGE
-----
  # 1. Report against a directory listing (dir output, or one filename a line)
  python manage.py map_qb_company_files --org 21 --listing qb_dir.txt

  # 2. Or against what the agent has actually observed (needs the Tier-1 agent)
  python manage.py map_qb_company_files --org 21 --from-observed --days 30

  # 3. Save the machine-readable report, review it, trim to what you approve
  python manage.py map_qb_company_files --org 21 --listing qb_dir.txt --json report.json

  # 4. Dry-run the approved aliases, then write them
  python manage.py map_qb_company_files --org 21 --apply approved.json
  python manage.py map_qb_company_files --org 21 --apply approved.json --confirm

`approved.json` is a list of {"client_id": <int>, "alias": "<string>"} — the
shape the report's suggestions emit, so the review step is deleting the lines
you do not want.
"""
import json
import re
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.models import Client, Organization, RawEvent
from tracker.services.qb_company_file import (
    clean_stem, match_stem, norm, parse_listing, listing_tokens,
)
from tracker.services.alias_suggestion import alias_is_safe_to_add


def observed_paths(org, days):
    """Company file paths the agent has actually reported for this org."""
    since = timezone.now() - timedelta(days=days)
    paths = set()
    qs = (RawEvent.objects
          .filter(block__org=org, start_ts__gte=since)
          .values_list('ctx', flat=True))
    for ctx in qs.iterator():
        if not isinstance(ctx, dict):
            continue
        if ctx.get('qb_company_path'):
            paths.add(ctx['qb_company_path'])
        for p in (ctx.get('qb_open_files') or []):
            if p:
                paths.add(p)
    return sorted(paths)


def rank_candidates(stem, clients, limit=3):
    """Clients most likely to own `stem`, by distinctive-token overlap.

    A ranking aid for the human review only — it never attributes anything and
    is deliberately looser than the matcher it is helping you fix.
    """
    file_toks = listing_tokens(stem)
    if not file_toks:
        return []
    scored = []
    for c in clients:
        c_toks = listing_tokens(c.name)
        if not c_toks:
            continue
        shared = file_toks & c_toks
        if not shared:
            continue
        # Fraction of the CLIENT's identity present in the filename, so a client
        # whose whole name appears scores 1.0 whatever else the file says.
        scored.append((len(shared) / len(c_toks), sorted(shared), c))
    scored.sort(key=lambda t: (-t[0], t[2].name))
    return scored[:limit]


def build_report(org, paths):
    clients = list(Client.objects.filter(org=org, is_active=True))
    candidates = []
    for c in clients:
        for matchable in [c.name] + list(c.aliases or []):
            candidates.append((c.id, c.name, matchable))

    resolved, unmatched = [], []
    seen_stems = set()
    for p in paths:
        stem = clean_stem(p)
        key = norm(stem)
        if not key or key in seen_stems:
            continue  # working copies of one file collapse to one identity
        seen_stems.add(key)

        hit = match_stem(p, candidates)
        if hit:
            client_id, client_name, matched_on = hit
            resolved.append({
                'file': p, 'stem': stem, 'client_id': client_id,
                'client_name': client_name, 'matched_on': matched_on,
                'via': 'name' if matched_on == client_name else 'alias',
            })
            continue

        suggestions = []
        for score, shared, c in rank_candidates(stem, clients):
            suggestions.append({
                'client_id': c.id,
                'client_name': c.name,
                'score': round(score, 2),
                'shared_tokens': shared,
                'alias': stem,
                'alias_is_safe': alias_is_safe_to_add(stem, c, clients),
            })
        unmatched.append({'file': p, 'stem': stem, 'suggestions': suggestions})

    return {'org_id': org.id, 'org_name': org.name,
            'clients': len(clients), 'company_files': len(seen_stems),
            'resolved': resolved, 'unmatched': unmatched}


class Command(BaseCommand):
    help = ("Report which QuickBooks company files Stage 4.5 can attribute, and "
            "which need an alias. Read-only unless --apply --confirm.")

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True, help='org id or name')
        parser.add_argument('--listing',
                            help='directory listing file (dir output or one filename per line)')
        parser.add_argument('--from-observed', action='store_true',
                            help='use company files the agent has reported')
        parser.add_argument('--days', type=int, default=30,
                            help='lookback for --from-observed (default 30)')
        parser.add_argument('--json', dest='json_out', help='write the full report here')
        parser.add_argument('--apply', dest='apply_file',
                            help='JSON list of {"client_id","alias"} to add')
        parser.add_argument('--confirm', action='store_true',
                            help='actually write the --apply aliases (otherwise dry-run)')

    def _resolve_org(self, val):
        org = (Organization.objects.filter(id=int(val)).first()
               if str(val).isdigit()
               else Organization.objects.filter(name__icontains=val).first())
        if not org:
            raise CommandError(f'org not found: {val!r}')
        return org

    def handle(self, *args, **opts):
        org = self._resolve_org(opts['org'])

        if opts.get('apply_file'):
            return self._apply(org, opts['apply_file'], opts['confirm'])

        if opts.get('listing'):
            with open(opts['listing'], encoding='utf-8', errors='replace') as fh:
                paths = parse_listing(fh.read())
            source = f"listing {opts['listing']}"
        elif opts.get('from_observed'):
            paths = observed_paths(org, opts['days'])
            source = f"agent observations, last {opts['days']}d"
        else:
            raise CommandError('give --listing <file> or --from-observed')

        if not paths:
            self.stdout.write(self.style.WARNING(
                f'No .qbw company files found via {source}.'))
            if opts.get('from_observed'):
                self.stdout.write(
                    '  The agent reports these only from the Tier-1 build onward. '
                    'If that agent IS deployed, the likeliest cause is that '
                    'psutil.open_files() cannot read the network share — check '
                    'ctx.qb_open_files on a recent QuickBooks event.')
            return

        rep = build_report(org, paths)

        self.stdout.write(
            f"\norg {org.id} {org.name!r} — {rep['clients']} active clients, "
            f"{rep['company_files']} distinct company files ({source})\n")

        n_res, n_un = len(rep['resolved']), len(rep['unmatched'])
        total = (n_res + n_un) or 1
        self.stdout.write(self.style.SUCCESS(
            f"  Stage 4.5 resolves TODAY : {n_res}/{total}  ({100 * n_res // total}%)"))
        self.stdout.write(f"  needs an alias           : {n_un}\n")

        if rep['resolved']:
            self.stdout.write("--- resolved ---")
            for r in sorted(rep['resolved'], key=lambda r: r['stem'].lower()):
                via = '' if r['via'] == 'name' else f"  [alias {r['matched_on']!r}]"
                self.stdout.write(f"  {r['stem'][:52]:54s} -> {r['client_name']}{via}")

        if rep['unmatched']:
            self.stdout.write("\n--- needs an alias (Stage 4.5 abstains on these) ---")
            for u in sorted(rep['unmatched'], key=lambda u: u['stem'].lower()):
                self.stdout.write(f"\n  FILE  {u['stem']}")
                if not u['suggestions']:
                    self.stdout.write("        no client resembles this file — a "
                                      "missing client record, or not billable work")
                    continue
                for s in u['suggestions']:
                    flag = ('' if s['alias_is_safe']
                            else '   UNSAFE: collides with a sibling client')
                    self.stdout.write(
                        f"        ~{s['score']:.2f}  client {s['client_id']} "
                        f"{s['client_name']!r}  (shared: "
                        f"{', '.join(s['shared_tokens'])}){flag}")

        if opts.get('json_out'):
            with open(opts['json_out'], 'w', encoding='utf-8') as fh:
                json.dump(rep, fh, indent=2)
            self.stdout.write(self.style.SUCCESS(f"\nfull report -> {opts['json_out']}"))
            self.stdout.write(
                "\nTo apply: copy the {client_id, alias} pairs you approve into a "
                "JSON list, then:\n"
                f"  python manage.py map_qb_company_files --org {org.id} "
                "--apply approved.json            # dry run\n"
                f"  python manage.py map_qb_company_files --org {org.id} "
                "--apply approved.json --confirm  # write")

    def _apply(self, org, apply_file, confirm):
        with open(apply_file, encoding='utf-8') as fh:
            decisions = json.load(fh)
        if not isinstance(decisions, list):
            raise CommandError('--apply file must be a JSON list of '
                               '{"client_id": int, "alias": str}')

        clients = list(Client.objects.filter(org=org, is_active=True))
        by_id = {c.id: c for c in clients}

        planned, skipped = [], []
        for d in decisions:
            cid, alias = d.get('client_id'), (d.get('alias') or '').strip()
            c = by_id.get(cid)
            if not c:
                skipped.append((d, f'client {cid} not in org {org.id}'))
            elif not alias:
                skipped.append((d, 'empty alias'))
            elif alias in list(c.aliases or []):
                skipped.append((d, 'already an alias'))
            elif not alias_is_safe_to_add(alias, c, clients):
                skipped.append((d, 'UNSAFE — collides with a sibling client'))
            else:
                planned.append((c, alias))

        self.stdout.write(f"\norg {org.id} {org.name!r} — {len(planned)} alias(es) "
                          f"to add, {len(skipped)} skipped\n")
        for c, alias in planned:
            self.stdout.write(f"  + {alias!r}  ->  client {c.id} {c.name!r}")
        for d, why in skipped:
            self.stdout.write(self.style.WARNING(f"  - skip {d}: {why}"))

        if not confirm:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing written. Re-run with --confirm to apply."))
            return

        for c, alias in planned:
            aliases = list(c.aliases or [])
            aliases.append(alias)
            c.aliases = aliases
            c.save(update_fields=['aliases'])
        self.stdout.write(self.style.SUCCESS(
            f"\nwrote {len(planned)} alias(es) to org {org.id}"))
