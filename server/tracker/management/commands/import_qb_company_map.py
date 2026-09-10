"""
Management command: load the firm's Customer/Company list.

QuickBooks Desktop shows only its Company Name, and a dozen of org 21's files
answer to "St. Mary's Church". Every other mechanism in this codebase infers the
parish — from the filename, the vendor on screen, the file the user picked, the
block before it. This command reads the firm's own list and stops the guessing
for every company on it.

Measured on org 21 before it existed: 483 blocks already agreed with the list,
178 blocks (27.9 h) did not. Every disagreement was a bare "St. Mary's Church"
filed to a parish the firm's own list does not name.

MOST ROWS CARRY NO RISK AT ALL. "1001 Services, LLC" is that client's company
file and nobody else's; importing it can only ever be right. Those go in.

The rows worth a second look are the ones where the company name is a name
SEVERAL clients answer to — the dozen parishes whose QuickBooks file all reads
"St. Mary's Church". The list is the only thing in this codebase that can
settle those, which is exactly why a stale row there is expensive: org 21's
"St. Mary's Church" points at St. Mary's Church-Hamilton, which has no captured
time in five weeks. Either the firm no longer serves them, and importing that
row books live work to a former client, or the work has been landing on the
wrong parish all along and Hamilton only LOOKS gone. That is the firm's
question, not this command's, so an ambiguous name pointing at a client with no
recent time is reported and skipped. --include-dormant imports it anyway.

Note what is NOT a reason to skip: a client with no captured time whose company
name is unmistakably theirs. A book of business has annual clients and clients
onboarded before TimeTracker; "never seen" there means the mapping has not been
needed yet, not that it is wrong.

Reads .xlsx (needs openpyxl) or .csv. Expects a Customer column and a Company
column, found by header name in any order.

Usage:
  python manage.py import_qb_company_map --org 21 --file "Customer-Company List.xlsx"
  python manage.py import_qb_company_map --org 21 --file list.xlsx --apply
  python manage.py import_qb_company_map --org 21 --file list.xlsx --apply --include-dormant
"""
import csv
import os
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker.models import Block, Client, Organization, QBCompanyClient
from tracker.services import client_families
from tracker.services.classification_service import ClassificationService

# A client with no captured time in this long is treated as dormant: its rows
# are reported for a human to confirm rather than imported. Long enough to
# survive a quiet client and a holiday, short enough to catch one that left.
DORMANT_AFTER = timedelta(days=45)

# A much shorter bar for a company name that singles NOBODY out — the bare
# "St. Mary's Church" that eleven parishes answer to. Those rows are not one
# client's mapping, they are the routing rule for a whole family: every block
# carrying that title goes wherever the row points, at 0.95, with no human in
# the loop. Six weeks of silence is a perfectly ordinary gap for one client and
# a loud signal for the one client a whole family's traffic is about to land on
# — org 21's "St. Mary's Church" points at Hamilton, quiet 36 days, while its
# siblings Clinton and Sacred Heart both have time booked today.
AMBIGUOUS_DORMANT_AFTER = timedelta(days=14)


def _read_rows(path):
    """[(customer, company)] from an .xlsx or .csv, located by header name."""
    if path.lower().endswith('.csv'):
        with open(path, newline='', encoding='utf-8-sig') as fh:
            table = [row for row in csv.reader(fh)]
    else:
        try:
            import openpyxl
        except ImportError:
            raise CommandError(
                'Reading .xlsx needs openpyxl (pip install openpyxl), or export '
                'the sheet to .csv and pass that instead.')
        book = openpyxl.load_workbook(path, data_only=True)
        table = [list(r) for r in book.active.iter_rows(values_only=True)]

    if not table:
        raise CommandError(f'{path} is empty')

    # Find the header row and the two columns by name — the real sheet leads
    # with a blank spacer column, so fixed indexes would be wrong.
    cust_i = comp_i = None
    start = 0
    for n, row in enumerate(table[:10]):
        cells = {str(c).strip().lower(): i for i, c in enumerate(row) if c}
        if 'customer' in cells and 'company' in cells:
            cust_i, comp_i, start = cells['customer'], cells['company'], n + 1
            break
    if cust_i is None:
        raise CommandError(
            'No header row with both a "Customer" and a "Company" column in the '
            f'first 10 rows of {path}')

    out = []
    for row in table[start:]:
        if len(row) <= max(cust_i, comp_i):
            continue
        cust, comp = row[cust_i], row[comp_i]
        cust = str(cust).strip() if cust is not None else ''
        comp = str(comp).strip() if comp is not None else ''
        if cust and comp and comp.lower() != 'none':
            out.append((cust, comp))
    return out


class Command(BaseCommand):
    help = "Load the firm's Customer/Company list so QuickBooks company names resolve directly."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--file', required=True, help='.xlsx or .csv')
        parser.add_argument('--apply', action='store_true',
                            help='Write the mappings (default: dry run)')
        parser.add_argument('--include-dormant', action='store_true',
                            help='Import rows whose client has no recent captured time')

    def handle(self, *args, **opts):
        org = Organization.objects.filter(id=opts['org']).first()
        if not org:
            raise CommandError(f"org {opts['org']} not found")
        path = os.path.expanduser(opts['file'])
        if not os.path.exists(path):
            raise CommandError(f'no such file: {path}')

        rows = _read_rows(path)
        clients = list(Client.objects.filter(org=org))
        by_key = {ClassificationService._normalize_name(c.name): c for c in clients}

        # Last captured block per client, to spot rows that have gone stale.
        cutoff = (timezone.now() - DORMANT_AFTER).date()
        tight_cutoff = (timezone.now() - AMBIGUOUS_DORMANT_AFTER).date()
        # Does a company name single one client out, or is it a whole family's?
        lookalikes = client_families.for_org(org.id)
        last_seen = {}
        for cid, day in Block.objects.filter(
                org=org, client__isnull=False).values_list('client_id', 'day'):
            if day and (cid not in last_seen or day > last_seen[cid]):
                last_seen[cid] = day

        ready, dormant, unknown, mapped = [], [], [], []
        collisions = defaultdict(list)
        for customer, company in rows:
            client = by_key.get(ClassificationService._normalize_name(customer))
            if not client:
                unknown.append((customer, company))
                continue
            collisions[ClassificationService._normalize_name(company)].append(
                (company, client))

        for key, entries in collisions.items():
            # One company name naming two clients cannot resolve anything, and
            # importing it would have the classifier pick by row order.
            if len({c.id for _, c in entries}) > 1:
                continue
            company, client = entries[0]
            if not client.is_active:
                # Deactivated is the firm saying so outright; never route to it.
                dormant.append((company, client, last_seen.get(client.id), 'inactive'))
                continue
            # Most rows just restate the client's own name — "JV Graphics LLC"
            # keeps its books in a company file called "JV Graphics LLC". Those
            # teach the classifier nothing it could get wrong, and there are
            # 291 of them; reviewing them would bury the ones that matter.
            #
            # A row where the company name is NOT the client's name is the row
            # doing real work: it is the only thing that can tell a bare "St.
            # Mary's Church" from eleven others, and the only kind that can be
            # confidently wrong. Those get looked at.
            if key == ClassificationService._normalize_name(client.name):
                ready.append((company, client))
                continue
            # How much silence is too much depends on how much this row decides.
            singles_out = lookalikes.resolve(
                client_families.text_words(company)) is not None
            bar = cutoff if singles_out else tight_cutoff
            seen = last_seen.get(client.id)
            mapped.append((company, client, seen, singles_out))
            if not seen or seen < bar:
                dormant.append((company, client, seen,
                                'no recent time' if singles_out
                                else 'a whole family routes here'))
            else:
                ready.append((company, client))

        ambiguous = [(k, v) for k, v in collisions.items()
                     if len({c.id for _, c in v}) > 1]

        self._report(rows, ready, dormant, unknown, ambiguous, mapped,
                     self._live_traffic(org, dormant), opts)

        if not opts['apply']:
            self.stdout.write(self.style.WARNING(
                '\nDRY RUN — nothing written. Re-run with --apply.'))
            return

        to_write = list(ready)
        if opts['include_dormant']:
            to_write += [(company, client) for company, client, _, _ in dormant]

        written = 0
        for company, client in to_write:
            key = ClassificationService._normalize_name(company)
            QBCompanyClient.objects.update_or_create(
                org=org, company_key=key,
                defaults={'company_name': company, 'client': client,
                          'source': 'import'},
            )
            written += 1
        self.stdout.write(self.style.SUCCESS(f'\nAPPLIED: {written} company mappings.'))

    # ------------------------------------------------------------------ report

    def _live_traffic(self, org, dormant):
        """For each held row: is anyone actually working in that company file?

        "Last seen 36 days ago" is the wrong question to end on, because the
        reason a client goes quiet may be that this system stopped attributing
        its work to it. Org 21's "St. Mary's Church" row was held as stale while
        43 hours of work in a file with exactly that company name went on
        happening — booked to Sacred Heart, to Clinton, to Baldwinsville, to
        every parish except the one whose file it is.

        So for each held row, count the QuickBooks time whose company name IS
        that row's, and say where it is going now. A row with live traffic is
        not a dead client; it is a client being robbed by its look-alikes.
        """
        from tracker.services.qb_company_file import extract_qb_company
        keys = {ClassificationService._normalize_name(c): (c, cl)
                for c, cl, _, _ in dormant}
        if not keys:
            return {}
        since = (timezone.now() - timedelta(days=60)).date()
        names = dict(Client.objects.filter(org=org).values_list('id', 'name'))
        out = defaultdict(lambda: defaultdict(int))
        for b in Block.objects.filter(org=org, day__gte=since,
                                      app_name__istartswith='qbw').only(
                                          'window_title', 'title', 'minutes',
                                          'client_id'):
            company = extract_qb_company(
                ClassificationService._strip_qb_screen_bracket(
                    b.window_title or b.title or ''))
            if not company:
                continue
            key = ClassificationService._normalize_name(company)
            if key in keys:
                out[key][names.get(b.client_id, 'no client')] += b.minutes or 0
        return out

    def _report(self, rows, ready, dormant, unknown, ambiguous, mapped,
                traffic, opts):
        w = self.stdout.write
        w(f'\nread {len(rows)} Customer/Company rows')
        w(f'  {len(ready):4d} ready to import')
        w(f'  {len(dormant):4d} SKIPPED — points at a client with no recent time')
        w(f'  {len(mapped):4d} of those rows name a company that is NOT the '
          f'client\'s own name')
        w(f'  {len(unknown):4d} customer not on this org\'s roster')
        w(f'  {len(ambiguous):4d} company name naming two clients (cannot resolve, skipped)')

        if mapped:
            w('\n  the rows that do real work — a company name that is not the')
            w('  client\'s own name. These are what resolve a generic title:')
            held_ids = {(c, cl.id) for c, cl, _, _ in dormant}
            for company, client, seen, singles in sorted(mapped,
                                                         key=lambda m: m[0].lower()):
                flag = '   HELD' if (company, client.id) in held_ids else ''
                fam = '' if singles else '   [a whole family answers to this name]'
                w(f'     {company[:38]:40} -> [{client.id}] {client.name[:30]:32} '
                  f'last seen {seen or "never"}{flag}{fam}')

        if dormant:
            w('\n  confirm these before importing them — the company name is not')
            w('  the client\'s own, and that client has gone quiet:')
            for company, client, seen, why in sorted(dormant, key=lambda d: str(d[2] or '')):
                w(f'     {company[:38]:40} -> [{client.id}] {client.name[:30]:32} '
                  f'last seen {seen or "never"}  ({why})')
                where = traffic.get(ClassificationService._normalize_name(company))
                if where:
                    total = sum(where.values())
                    w(f'        BUT {total/60:.1f}h of QuickBooks work in a file with '
                      f'exactly this company name happened in the last 60 days.')
                    w('        It is going to: ' + ', '.join(
                        f'{n} {m}m' for n, m in
                        sorted(where.items(), key=lambda kv: -kv[1])[:4]))
                    w('        A client this quiet with traffic this live is not '
                      'gone — its work is landing on its look-alikes.')
            w('     (--include-dormant imports them anyway)')

        if ambiguous:
            w('\n  one company name, two clients — nothing can resolve these:')
            for key, entries in ambiguous[:6]:
                names = ', '.join(sorted({c.name for _, c in entries}))
                w(f'     {entries[0][0][:38]:40} -> {names[:60]}')

        if unknown and opts.get('verbosity', 1) > 1:
            w('\n  customers not on the roster:')
            for cust, comp in unknown[:20]:
                w(f'     {cust[:44]}')
