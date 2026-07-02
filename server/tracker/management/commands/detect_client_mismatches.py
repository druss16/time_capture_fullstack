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

        by_day = defaultdict(int)
        by_pair = defaultdict(int)
        examples = []
        scanned = 0

        for b in blocks.iterator(chunk_size=1000):
            scanned += 1
            names = names_by_org.get(b.org_id)
            index = index_by_org.get(b.org_id)
            if not index or not names or b.client_id not in names:
                continue
            m = detect_mismatch(b.window_title, b.client_id, index, names)
            if not m:
                continue
            day = timezone.localtime(b.start).date().isoformat()
            by_day[day] += 1
            by_pair[f'{names[b.client_id]} → {m["looks_like_client_name"]}'] += 1
            if len(examples) < show:
                examples.append((day, b.id, names[b.client_id], m['looks_like_client_name'], b.window_title[:80]))

        total = sum(by_day.values())

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nScanned {scanned} blocks over {days}d"
            f"{f' (org {org_id})' if org_id else ' (all orgs)'}"
        ))
        self.stdout.write(self.style.WARNING(f"Flagged {total} mismatches\n"))

        if not total:
            self.stdout.write(self.style.SUCCESS("No mismatches found. ✅"))
            return

        # ── Per-day histogram — the historical-vs-ongoing signal ──
        self.stdout.write(self.style.MIGRATE_HEADING("Per-day histogram:"))
        peak = max(by_day.values())
        for day in sorted(by_day.keys()):
            count = by_day[day]
            bar = "█" * max(1, int(40 * count / peak))
            self.stdout.write(f"  {day}  {bar} {count}")

        # Is the newest mismatch recent or stale? Quick verdict.
        newest = max(by_day.keys())
        newest_dt = timezone.datetime.fromisoformat(newest).date()
        age = (timezone.localdate() - newest_dt).days
        self.stdout.write("")
        if age <= 3:
            self.stdout.write(self.style.ERROR(
                f"⚠ Most recent mismatch was {age}d ago ({newest}) — looks ONGOING, "
                f"needs a live classifier fix."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"✓ Most recent mismatch was {age}d ago ({newest}) — no recent "
                f"mismatches; likely an older-classifier artifact. Consider a "
                f"one-time recategorization cleanup rather than a live fix."
            ))

        # ── Worst client pairs ──
        self.stdout.write(self.style.MIGRATE_HEADING("\nWorst client pairs (booked → looks like):"))
        for row in sorted(by_pair.items(), key=lambda x: -x[1])[:15]:
            self.stdout.write(f"  {row[1]:4d}×  {row[0]}")

        # ── Examples ──
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nExamples (first {len(examples)}):"))
        for day, bid, booked, looks, title in examples:
            self.stdout.write(f"  [{day}] block {bid}: booked '{booked}' but title says '{looks}'")
            self.stdout.write(self.style.HTTP_INFO(f"       title: {title}"))