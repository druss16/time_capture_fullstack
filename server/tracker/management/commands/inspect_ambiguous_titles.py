# tracker/management/commands/inspect_ambiguous_titles.py
"""
READ-ONLY diagnostic. For blocks whose title contains an ambiguous fragment
(e.g. "St. Mary") that the mismatch detector correctly refuses to auto-resolve,
dump ALL the raw signal the block carries — full window_title, url, app/exe,
bundle_id, and any extra fields — so we can see what (if anything) could
disambiguate it to the right client.

Nothing is modified. This just prints.

Usage:
    python manage.py inspect_ambiguous_titles --org 21 --contains "St. Mary"
    python manage.py inspect_ambiguous_titles --org 21 --contains "St. Mary" --days 120 --limit 40
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Dump raw fields for blocks whose title contains an ambiguous fragment."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--contains', type=str, required=True,
                            help='Substring to match in window_title, e.g. "St. Mary".')
        parser.add_argument('--days', type=int, default=120)
        parser.add_argument('--limit', type=int, default=30)

    def handle(self, *args, **opts):
        from tracker.models import Block, Client

        org_id = opts['org']
        needle = opts['contains']
        days = opts['days']
        limit = opts['limit']
        cutoff = timezone.now() - timedelta(days=days)

        # Show the org's roster first — so we can see which clients "St. Mary"
        # could plausibly map to (the source of the ambiguity).
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nClients in org {org_id} matching '{needle.split()[0]}' or 'mary':"
        ))
        roster = Client.objects.filter(org_id=org_id).only('id', 'name')
        low_needle_tokens = [t.lower() for t in needle.split() if len(t) > 1]
        for c in roster:
            nl = c.name.lower()
            if any(t in nl for t in low_needle_tokens):
                self.stdout.write(f"  [{c.id}] {c.name}")

        blocks = (
            Block.objects
            .filter(org_id=org_id, start__gte=cutoff, window_title__icontains=needle)
            .select_related('client', 'user')
            .order_by('-start')[:limit]
        )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nBlocks with '{needle}' in title (showing {limit} max):\n"
        ))

        # Discover which fields exist on Block so we print whatever signal is
        # there without assuming a schema.
        candidate_fields = [
            'window_title', 'url', 'app_name', 'exe_name', 'exe', 'process_name',
            'bundle_id', 'raw_title', 'document_path', 'file_path', 'company_file',
        ]
        present = []
        if blocks:
            sample = blocks[0]
            for f in candidate_fields:
                if hasattr(sample, f):
                    present.append(f)

        self.stdout.write(self.style.HTTP_INFO(
            f"Fields present on Block: {', '.join(present)}\n"
        ))

        count = 0
        for b in blocks:
            count += 1
            booked = b.client.name if b.client_id else "Unassigned"
            self.stdout.write(self.style.WARNING(
                f"── block {b.id} · booked: {booked} · "
                f"{timezone.localtime(b.start).date()} ──"
            ))
            for f in present:
                val = getattr(b, f, None)
                if val:
                    self.stdout.write(f"    {f:14s}: {val}")
            self.stdout.write("")

        if not count:
            self.stdout.write(self.style.SUCCESS("No matching blocks found."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Dumped {count} blocks. Look for a field that distinctively names "
            f"ONE client (a file path, company file, EIN, or fuller name) — that's "
            f"what a disambiguation rule could key on."
        ))