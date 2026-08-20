"""
Tell same-named QuickBooks parishes apart by the vendors in their window titles.

WHY
---
QuickBooks shows only its Company Name, and fourteen of this firm's files answer
to some form of "St. Mary's Church". The distinguishing town lives in the
filename, which QuickBooks never displays and the agent cannot read.

But QuickBooks DOES show the open screen:

    "St. Mary's Church - QuickBooks ... - [Vendor Center: Clinton Agway]"

Clinton Agway is a Clinton, NY supplier. A Hamilton parish does not buy from it.
Vendors, customers and employees are precisely what one parish's books contain
and another's do not — so they identify the file the company name cannot, from
data already in the database, going back months.

READ-ONLY. Reports groups and coverage; writes nothing.

    python manage.py qb_vendor_groups --org 21
    python manage.py qb_vendor_groups --org 21 --days 120 --company "St. Mary's Church"
"""
import re
from collections import defaultdict, Counter
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from django.db import transaction

from tracker.models import (Organization, RawEvent, Client, Block,
                            ClassificationAudit, QBVendorClient)
from tracker.services.qb_vendor_fingerprint import (
    split_title, is_identifying, find_generic_vendors, group_sessions,
    suggest_town, classify_groups,
)


class Command(BaseCommand):
    help = ("Group QuickBooks sessions by the vendors inside their window "
            "titles, to tell same-named company files apart (read-only).")

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True)
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--company', help='limit to one company name')
        parser.add_argument('--min-sessions', type=int, default=2)
        parser.add_argument(
            '--assign', action='append', default=[], metavar='VENDOR=CLIENT_ID',
            help='Assign every session whose vendor set contains VENDOR to '
                 'CLIENT_ID. An anchor vendor is used rather than a group '
                 'number because group numbers shift between runs while '
                 '"the file that pays Clinton Agway" does not. Repeatable.')
        parser.add_argument(
            '--confirm', action='store_true',
            help='Actually write the reassignments (otherwise a dry run).')

    def handle(self, *args, **opts):
        val = opts['org']
        org = (Organization.objects.filter(id=int(val)).first() if str(val).isdigit()
               else Organization.objects.filter(name__icontains=val).first())
        if not org:
            raise CommandError(f'org not found: {val!r}')

        since = timezone.now() - timedelta(days=opts['days'])
        rows = (RawEvent.objects
                .filter(block__org=org, start_ts__gte=since,
                        app_name__istartswith='qbw')
                .exclude(window_title='')
                .values_list('window_title', 'start_ts', 'hostname',
                             'block_id', 'block__minutes', 'block__client__name'))

        # A session is one person, one company name, one day: a stretch of work
        # in a single company file.
        sess_vendors = defaultdict(set)
        sess_blocks = defaultdict(set)
        block_client = {}
        block_minutes = {}
        vendor_companies = defaultdict(set)
        company_titles = Counter()
        bracketed = total = 0

        for wt, ts, host, bid, mins, client_name in rows:
            company, screen, party = split_title(wt)
            if not company:
                continue
            total += 1
            company_titles[company] += 1
            key = (company, host, ts.date())
            if bid:
                sess_blocks[key].add(bid)
                block_minutes[bid] = mins or 0
                # Keyed by BLOCK, not accumulated: a block yields many events
                # and adding its minutes per event inflated a 5.5h group to
                # 238.9h in the first run of this command.
                block_client[bid] = client_name or '(none)'
            if screen:
                bracketed += 1
            if is_identifying(screen, party):
                sess_vendors[key].add(party)
                vendor_companies[party].add(company)

        # Drop vendors shared across company names BEFORE grouping — one shared
        # supplier is enough to merge two parishes into a single group.
        generic = find_generic_vendors(vendor_companies)
        for k in list(sess_vendors):
            sess_vendors[k] -= generic
            if not sess_vendors[k]:
                del sess_vendors[k]

        # Place names only. Without this, entity words are read as towns and
        # a group whose one vendor is "St. Mary's Cemetery" is reported as
        # "looks like Cemetery", which is not a place.
        NOT_A_PLACE = {
            'church', 'cemetery', 'school', 'parish', 'saint', 'catholic',
            'community', 'association', 'chapel', 'basilica', 'diocese',
            'ministries', 'assumption', 'sacred', 'heart', 'blessed', 'trinity',
            'family', 'lady', 'hope', 'mercy', 'divine', 'christ', 'jesus',
            'savior', 'evangelist', 'baptist', 'episcopal', 'lutheran',
            'silver', 'first', 'north', 'south', 'east', 'west', 'incorporated',
        }
        # Towns of the parishes this firm keeps books for. Client names are
        # full of saints and suffixes, and mining them for towns produced
        # "looks like Theresa" and "looks like Accounting".
        towns = [
            'Clinton', 'Hamilton', 'Baldwinsville', 'Bville', 'Minoa', 'Rome',
            'Oswego', 'Boonville', 'Cazenovia', 'Pulaski', 'Cicero', 'Utica',
            'Jordan', 'Taberg', 'Chittenango', 'Chadwick', 'Sherrill', 'Homer',
            'Syracuse', 'Camillus', 'Manlius', 'Fulton', 'Auburn', 'Liverpool',
        ]

        self.stdout.write(
            f"\norg {org.id} {org.name!r} — {total:,} QuickBooks titles in "
            f"{opts['days']}d, {bracketed:,} with a screen bracket "
            f"({100*bracketed//max(total,1)}%), "
            f"{len(generic)} vendor(s) filtered as shared\n")

        assigns = {}
        for spec in opts.get('assign') or []:
            if '=' not in spec:
                raise CommandError(f'--assign wants VENDOR=CLIENT_ID, got {spec!r}')
            vendor, _, cid = spec.rpartition('=')
            client = Client.objects.filter(org=org, id=int(cid)).first()
            if not client:
                raise CommandError(f'client {cid} not in org {org.id}')
            assigns[vendor.strip()] = client
        planned = []   # (block_id, before_client, after_client, minutes, anchor)
        learn = []     # (vendors, client, company_name)

        wanted = opts.get('company')
        for company in sorted(company_titles, key=lambda c: -company_titles[c]):
            if wanted and wanted.lower() not in company.lower():
                continue
            all_keys = [k for k in sess_blocks if k[0] == company]
            keyed = {k: v for k, v in sess_vendors.items() if k[0] == company}
            if len(all_keys) < opts['min_sessions']:
                continue
            groups = group_sessions(keyed)
            confident, fragments = classify_groups(groups, keyed)
            if len(confident) < 2:
                continue    # fewer than two well-evidenced files: nothing proven

            def mins(keys):
                return sum(block_minutes.get(b, 0)
                           for k in keys for b in sess_blocks[k])

            tot_min = mins(all_keys)
            cov_min = mins([k for g, _ in confident for k in g])
            self.stdout.write(self.style.WARNING(
                f"\n{company!r}  —  at least {len(confident)} DISTINCT company "
                f"files behind one name"))
            self.stdout.write(
                f"   {tot_min/60:.1f}h total, {cov_min/60:.1f}h with solid "
                f"vendor evidence ({100*cov_min//max(tot_min,1)}%)")
            for i, (g, vend) in enumerate(confident, 1):
                booked = Counter()
                for k in g:
                    for b in sess_blocks[k]:
                        booked[block_client.get(b, '(none)')] += block_minutes.get(b, 0)
                town = suggest_town(vend, towns)
                label = (self.style.SUCCESS(f"looks like {town}") if town
                         else "needs one answer")
                self.stdout.write(
                    f"\n   FILE {i}: {len(g)} session(s), {mins(g)/60:.1f}h, "
                    f"{len(vend)} vendors — {label}")
                self.stdout.write(
                    f"      vendors : {', '.join(sorted(vend)[:6])}")
                self.stdout.write(
                    "      booked  : " + ', '.join(
                        f"{c} {m/60:.1f}h" for c, m in booked.most_common(3)))
                for anchor, client in assigns.items():
                    if anchor not in vend:
                        continue
                    self.stdout.write(self.style.SUCCESS(
                        f"      ASSIGN  : {anchor!r} -> {client.name!r}"))
                    # Teach the classifier every vendor in this group, not just
                    # the anchor. Fixing the past and fixing the future are the
                    # same action: any future block touching any of these
                    # vendors resolves without anyone running a command.
                    learn.append((sorted(vend), client, company))
                    for k in g:
                        for b in sess_blocks[k]:
                            before = block_client.get(b, '(none)')
                            if before != client.name:
                                planned.append((b, before, client,
                                                block_minutes.get(b, 0), anchor))
            if fragments:
                fmin = sum(mins(g) for g, _ in fragments)
                self.stdout.write(
                    f"\n   ({len(fragments)} fragment(s), {fmin/60:.1f}h — too "
                    f"little evidence to place; NOT counted as separate files)")

        if not assigns:
            return

        if not planned and not learn:
            self.stdout.write(self.style.WARNING(
                "\nNothing to do — no group contained an --assign vendor."))
            return
        if not planned:
            # Blocks are already on the right client — but the classifier may
            # still not KNOW why, so teaching must not be skipped just because
            # the past happens to be clean.
            self.stdout.write(
                "\nNo blocks need reassigning; teaching the classifier only.")

        total = sum(p[3] for p in planned)
        if planned:
            self.stdout.write(self.style.WARNING(
                f"\n\n{len(planned)} block(s), {total/60:.1f}h to reassign:"))
        moves = Counter()
        for _bid, before, client, mins, _a in planned:
            moves[(before, client.name)] += mins
        for (before, after), mins in moves.most_common():
            self.stdout.write(f"   {mins/60:6.1f}h   {before!r}  ->  {after!r}")

        if learn:
            n_v = sum(len(v) for v, _c, _n in learn)
            self.stdout.write(
                f"\n{n_v} vendor(s) would be taught to the classifier, so future "
                f"blocks touching them resolve automatically.")

        if not opts['confirm']:
            self.stdout.write(self.style.WARNING(
                "\nDRY RUN — nothing written. Re-run with --confirm to apply."))
            return

        # Audit every change. These blocks were already committed, some of them
        # billed; a silent reassignment would leave no way to see what moved or
        # to undo it.
        # Which of these blocks did a PERSON actually decide? Block.save marks
        # a block protected when categorized_by says 'correction', but that flag
        # is also set by automated paths: every one of the 48 blocks here was
        # written by src=pattern with corrected_by_user=False. Treating an
        # automated guess as a human decision would freeze the exact mistake we
        # are trying to correct, so ask the audit trail who really chose.
        human_ids = set(
            ClassificationAudit.objects
            .filter(block_id__in=[p[0] for p in planned], corrected_by_user=True)
            .values_list('block_id', flat=True)
        )
        self.stdout.write(
            f"\n   of those, {len(human_ids)} block(s) were decided by a PERSON "
            f"and will be left alone")

        changed = 0
        protected = []
        with transaction.atomic():
            for bid, before, client, _mins, anchor in planned:
                blk = Block.objects.filter(id=bid).first()
                if not blk:
                    continue
                if bid in human_ids:
                    protected.append((bid, (blk.client.name if blk.client else '(none)'),
                                      client.name, 'human decision'))
                    continue
                prev = blk.client
                blk.client = client
                try:
                    # force_update bypasses the protected-block guard. Justified
                    # only because we checked above that no human decided this
                    # block; a person's choice is never overwritten here.
                    blk.save(update_fields=['client'], force_update=True)
                except ValueError as e:
                    # Block.save protects blocks a HUMAN corrected. Leave them
                    # alone: a person looked at this one and decided, and an
                    # inference from vendor names does not outrank that. Where
                    # their answer differs from ours it is reported below —
                    # that disagreement is information, not an obstacle.
                    protected.append((bid, prev.name if prev else '(none)',
                                      client.name, str(e)[:60]))
                    continue
                try:
                    ClassificationAudit.objects.create(
                        # ClassificationAudit.source is varchar(20).
                        block=blk, source='vendor_fingerprint',
                        client_before=prev, client_after=client,
                        corrected_by_user=False,
                        matched_signals={
                            'anchor_vendor': anchor,
                            'why': ('QuickBooks company name is shared by several '
                                    'parishes; the vendors inside this file '
                                    'identify which one.'),
                        },
                    )
                except Exception as e:
                    self.stdout.write(self.style.WARNING(
                        f"   (audit row failed for block {bid}: {e})"))
                changed += 1
        taught = 0
        for vendors, client, company in learn:
            for v in vendors:
                _row, created = QBVendorClient.objects.update_or_create(
                    org=org, vendor=v[:200],
                    defaults={'client': client, 'company_name': (company or '')[:255],
                              'source': 'group'},
                )
                taught += 1 if created else 0
        self.stdout.write(self.style.SUCCESS(
            f"\nReassigned {changed} block(s); taught {taught} new vendor(s)."))
        if protected:
            self.stdout.write(self.style.WARNING(
                f"\n{len(protected)} block(s) left untouched — a person already "
                f"corrected them, and a human decision outranks this inference:"))
            disagree = [p for p in protected if p[1] != p[2]]
            for bid, was, would, _why in protected[:10]:
                flag = '   <-- disagrees with the vendor evidence' if was != would else ''
                self.stdout.write(f"   block {bid}: human said {was!r}, "
                                  f"vendors say {would!r}{flag}")
            if disagree:
                self.stdout.write(
                    f"   ({len(disagree)} disagreement(s) — worth checking: either "
                    f"the person knew something the vendors do not, or the vendor "
                    f"grouping is wrong.)")
