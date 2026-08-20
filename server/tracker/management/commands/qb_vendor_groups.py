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

from tracker.models import Organization, RawEvent, Client
from tracker.services.qb_vendor_fingerprint import (
    split_title, is_identifying, find_generic_vendors, group_sessions,
    suggest_town,
)


class Command(BaseCommand):
    help = ("Group QuickBooks sessions by the vendors inside their window "
            "titles, to tell same-named company files apart (read-only).")

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True)
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--company', help='limit to one company name')
        parser.add_argument('--min-sessions', type=int, default=2)

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
        towns = sorted({
            t for c in Client.objects.filter(org=org, is_active=True)
            for t in re.split(r'[^A-Za-z]+', c.name or '')
            if len(t) >= 5 and t.lower() not in NOT_A_PLACE
        })

        self.stdout.write(
            f"\norg {org.id} {org.name!r} — {total:,} QuickBooks titles in "
            f"{opts['days']}d, {bracketed:,} with a screen bracket "
            f"({100*bracketed//max(total,1)}%), "
            f"{len(generic)} vendor(s) filtered as shared\n")

        wanted = opts.get('company')
        for company in sorted(company_titles, key=lambda c: -company_titles[c]):
            if wanted and wanted.lower() not in company.lower():
                continue
            all_keys = [k for k in sess_blocks if k[0] == company]
            keyed = {k: v for k, v in sess_vendors.items() if k[0] == company}
            if len(all_keys) < opts['min_sessions']:
                continue
            groups = group_sessions(keyed)
            if len(groups) < 2:
                continue    # one group = one file = nothing to disentangle

            def mins(keys):
                return sum(block_minutes.get(b, 0)
                           for k in keys for b in sess_blocks[k])

            tot_min = mins(all_keys)
            cov_min = mins([k for g in groups for k in g])
            self.stdout.write(self.style.WARNING(
                f"\n{company!r}  —  {len(groups)} DISTINCT company files behind "
                f"one name"))
            self.stdout.write(
                f"   {tot_min/60:.1f}h total, {cov_min/60:.1f}h identifiable "
                f"({100*cov_min//max(tot_min,1)}% of the time)")
            for i, g in enumerate(groups, 1):
                vend = set()
                for k in g:
                    vend |= keyed[k]
                booked = Counter()
                for k in g:
                    for b in sess_blocks[k]:
                        booked[block_client.get(b, '(none)')] += block_minutes.get(b, 0)
                town = suggest_town(vend, towns)
                label = (self.style.SUCCESS(f"looks like {town}") if town
                         else "needs one answer")
                self.stdout.write(
                    f"\n   GROUP {i}: {len(g)} session(s), {mins(g)/60:.1f}h — {label}")
                self.stdout.write(
                    f"      vendors : {', '.join(sorted(vend)[:6])}")
                self.stdout.write(
                    "      booked  : " + ', '.join(
                        f"{c} {m/60:.1f}h" for c, m in booked.most_common(3)))
