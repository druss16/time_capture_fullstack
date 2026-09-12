"""
Read the mismatch queue and say what should happen to every row in it.

    python manage.py mismatch_agent --org 21 --days 90
    python manage.py mismatch_agent --org 21 --days 90 --explain
    python manage.py mismatch_agent --org 21 --apply

Read-only by default, and that is the mode worth running: it prints the draft
for every open flag with the evidence behind it, so you can see what the agent
would have done to real rows before letting it do anything. `--apply` still
respects the per-org opt-in (Organization.mismatch_agent_autoresolve); pass
`--force` to override it for one deliberate operator sweep.
"""
from django.core.management.base import BaseCommand

from tracker.services.mismatch_agent import (
    VERDICT_CONFIRM, VERDICT_HUMAN, VERDICT_REASSIGN, run,
)


class Command(BaseCommand):
    help = "Draft (and optionally apply) resolutions for open client-name mismatch flags."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, default=None,
                            help='Organization id. Omit for every org.')
        parser.add_argument('--days', type=int, default=90,
                            help='Only flags on blocks newer than this (default 90).')
        parser.add_argument('--limit', type=int, default=500,
                            help='Max flags to draft (default 500).')
        parser.add_argument('--apply', action='store_true',
                            help='Act on drafts above the bar, for opted-in orgs.')
        parser.add_argument('--force', action='store_true',
                            help='With --apply: ignore the per-org opt-in.')
        parser.add_argument('--explain', action='store_true',
                            help='Print every evidence line, not just the verdict.')

    def handle(self, *args, **o):
        org_ids = [o['org']] if o['org'] else None
        summary = run(org_ids=org_ids, days=o['days'], apply=o['apply'],
                      limit=o['limit'], respect_optin=not o['force'])

        drafts = summary.pop('drafts', [])
        by_verdict = {VERDICT_REASSIGN: [], VERDICT_CONFIRM: [], VERDICT_HUMAN: []}
        for d in drafts:
            by_verdict.setdefault(d.verdict, []).append(d)

        for verdict, label in (
            (VERDICT_REASSIGN, 'MOVE'),
            (VERDICT_CONFIRM, 'LEAVE IT'),
            (VERDICT_HUMAN, 'NEEDS A PERSON'),
        ):
            rows = by_verdict.get(verdict) or []
            if not rows:
                continue
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'{label} — {len(rows)} row{"s" if len(rows) != 1 else ""}'))
            for d in sorted(rows, key=lambda x: -x.confidence):
                mark = '✓ auto' if d.auto else '· queued'
                self.stdout.write(
                    f'  {mark}  block {d.block_id}  conf {d.confidence:.2f}  '
                    f'{d.booked_client_name or "?"} → {d.target_client_name or "—"}')
                self.stdout.write(f'          {d.summary}')
                if o['explain']:
                    for s in d.signals:
                        tag = 'indep' if s.independent else '     '
                        self.stdout.write(
                            f'          [{tag}] {s.kind:<18} {s.weight:.2f}  {s.text}')
                    for v in d.vetoes:
                        self.stdout.write(self.style.ERROR(f'          [veto ] {v}'))
                    for c in d.caveats:
                        self.stdout.write(self.style.WARNING(f'          [note ] {c}'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"drafted={summary['drafted']} "
            f"auto-reassigned={summary['auto_reassigned']} "
            f"auto-confirmed={summary['auto_confirmed']} "
            f"queued={summary['queued']} skipped={summary['skipped']}"))
        if o['apply']:
            acting = summary.get('acting_orgs') or []
            self.stdout.write(f"  acting for orgs: {acting or 'none (nobody opted in)'}")
        else:
            self.stdout.write('  (dry run — nothing was changed)')
