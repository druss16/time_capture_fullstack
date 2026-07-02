# tracker/management/commands/detect_client_mismatches.py
"""
Full-scan client-name mismatch detector (offline QA).

Scans committed blocks whose window title names a DIFFERENT client than the one
the time is booked to, using the distinctive-token matcher. Prints a per-day
histogram so you can see whether mismatches cluster in a past window (older
classifier, already fixed → cleanup) or continue to today (live bug).

Usage:
    python manage.py detect_client_mismatches
    python manage.py detect_client_mismatches --org 21 --days 90
    python manage.py detect_client_mismatches --org 21 --days 120 --show 40
"""
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tracker.utils.client_name_match import build_token_index, detect_mismatch


class Command(BaseCommand):
    help = "Detect blocks whose window title names a different client than booked."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None, help='Limit to one org id.')
        parser.add_argument('--days', type=int, default=90, help='Lookback window (default 90).')
        parser.add_argument('--show', type=int, default=25, help='How many example rows to print.')

    def handle(self, *args, **opts):
        from tracker.models import Block, Client

        org_id = opts['org']
        days = opts['days']
        show = opts['show']
        cutoff = timezone.now() - timedelta(days=days)

        # Per-org client name index.
        client_qs = Client.objects.all()
        if org_id:
            client_qs = client_qs.filter(org_id=org_id)
        names_by_org = defaultdict(dict)
        for c in client_qs.only('id', 'name', 'org_id'):
            names_by_org[c.org_id][c.id] = c.name
        index_by_org = {oid: build_token_index(names) for oid, names in names_by_org.items()}

        # Firm name per org (for internal/firm-self detection).
        from tracker.models import Organization
        firm_by_org = {}
        org_qs = Organization.objects.all()
        if org_id:
            org_qs = org_qs.filter(id=org_id)
        for o in org_qs.only('id', 'name'):
            firm_by_org[o.id] = o.name

        blocks = (
            Block.objects
            .filter(deleted_at__isnull=True, client_id__isnull=False, start__gte=cutoff)
            .exclude(window_title__isnull=True)
            .exclude(window_title='')
            .select_related('client', 'user', 'org')
            .order_by('start')
        )
        if org_id:
            blocks = blocks.filter(org_id=org_id)

        by_day = {"client": defaultdict(int), "internal": defaultdict(int)}
        by_pair = {"client": defaultdict(int), "internal": defaultdict(int)}
        examples = {"client": [], "internal": []}
        scanned = 0

        for b in blocks.iterator(chunk_size=1000):
            scanned += 1
            names = names_by_org.get(b.org_id)
            index = index_by_org.get(b.org_id)
            if not index or not names or b.client_id not in names:
                continue
            m = detect_mismatch(
                b.window_title, b.client_id, index, names,
                firm_name=firm_by_org.get(b.org_id),
            )
            if not m:
                continue
            bucket = m.get("bucket", "client")
            day = timezone.localtime(b.start).date().isoformat()
            by_day[bucket][day] += 1
            by_pair[bucket][f'{names[b.client_id]} → {m["looks_like_client_name"]}'] += 1
            if len(examples[bucket]) < show:
                examples[bucket].append((day, b.id, names[b.client_id], m['looks_like_client_name'], b.window_title[:80]))

        client_total = sum(by_day["client"].values())
        internal_total = sum(by_day["internal"].values())

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nScanned {scanned} blocks over {days}d"
            f"{f' (org {org_id})' if org_id else ' (all orgs)'}"
        ))
        self.stdout.write(self.style.WARNING(
            f"Client mismatches (billing-impacting): {client_total}"
        ))
        self.stdout.write(
            f"Internal/admin mismatches (noise, shown separately): {internal_total}\n"
        )

        if not client_total and not internal_total:
            self.stdout.write(self.style.SUCCESS("No mismatches found. ✅"))
            return

        # ═══ CLIENT bucket — the money bucket, verdict runs on THIS ═══
        if client_total:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "═══ CLIENT MISMATCHES (billing-impacting) ═══"
            ))
            self.stdout.write("Per-day histogram:")
            peak = max(by_day["client"].values())
            for day in sorted(by_day["client"].keys()):
                count = by_day["client"][day]
                bar = "█" * max(1, int(40 * count / peak))
                self.stdout.write(f"  {day}  {bar} {count}")

            newest = max(by_day["client"].keys())
            newest_dt = timezone.datetime.fromisoformat(newest).date()
            age = (timezone.localdate() - newest_dt).days
            self.stdout.write("")
            if age <= 3:
                self.stdout.write(self.style.ERROR(
                    f"⚠ Most recent CLIENT mismatch was {age}d ago ({newest}) — "
                    f"ONGOING, needs a live classifier fix."
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Most recent CLIENT mismatch was {age}d ago ({newest}) — "
                    f"no recent recurrences; likely an older-classifier artifact. "
                    f"Consider a one-time recategorization cleanup."
                ))

            self.stdout.write(self.style.MIGRATE_HEADING("\nWorst client pairs (booked → looks like):"))
            for row in sorted(by_pair["client"].items(), key=lambda x: -x[1])[:15]:
                self.stdout.write(f"  {row[1]:4d}×  {row[0]}")

            self.stdout.write(self.style.MIGRATE_HEADING(f"\nExamples (first {len(examples['client'])}):"))
            for day, bid, booked, looks, title in examples["client"]:
                self.stdout.write(f"  [{day}] block {bid}: booked '{booked}' but title says '{looks}'")
                self.stdout.write(self.style.HTTP_INFO(f"       title: {title}"))

        # ═══ INTERNAL bucket — real but not a client billing error ═══
        if internal_total:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n═══ INTERNAL / ADMIN MISMATCHES (noise — firm buckets) ═══"
            ))
            self.stdout.write(
                "These touch an Internal/admin bucket or the firm itself. Worth a "
                "glance for accuracy, but they are not client billing errors.\n"
            )
            self.stdout.write("Worst internal pairs:")
            for row in sorted(by_pair["internal"].items(), key=lambda x: -x[1])[:10]:
                self.stdout.write(f"  {row[1]:4d}×  {row[0]}")
            self.stdout.write(self.style.MIGRATE_HEADING(f"\nExamples (first {len(examples['internal'])}):"))
            for day, bid, booked, looks, title in examples["internal"]:
                self.stdout.write(f"  [{day}] block {bid}: booked '{booked}' → '{looks}'")
                self.stdout.write(self.style.HTTP_INFO(f"       title: {title}"))