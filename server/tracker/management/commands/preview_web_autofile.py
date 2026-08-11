"""
Preview (or apply) the second-pass "web auto-file" decisions WITHOUT relying on
the global feature flag. Use this to validate the personal/news vs client-work
split — including the live gpt-4o-mini verdicts — before enabling
SECOND_PASS_WEB_AUTOFILE in production.

It runs the exact same classify_block logic run_second_pass uses (with
web_autofile forced ON), and for residual unrecognized browser blocks it calls
the real LLM verdict. By default it writes NOTHING — it just prints, for the
current Needs-You pile, what each browser block would become:

  SWEEP    -> auto-filed to No-Client / Non-Billable (personal/news)
  PROTECT  -> kept in Needs You as a work tool / work-like (never swept)
  KEEP     -> stays in Needs You (LLM said work/unsure, or non-browser)

Usage:
  # Dry preview (default) — calls the LLM but writes nothing
  python manage.py preview_web_autofile --org-id 21 --days 14

  # Only show what WOULD be swept to non-billable
  python manage.py preview_web_autofile --org-id 21 --sweeps-only

  # Skip the LLM (heuristics only) — free, no OpenAI calls
  python manage.py preview_web_autofile --org-id 21 --no-llm

  # Actually apply the sweep (writes) — same as enabling the flag for one run
  python manage.py preview_web_autofile --org-id 21 --apply
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import timedelta

from tracker.models import Block, Organization
from tracker.services import second_pass as sp


class Command(BaseCommand):
    help = "Preview/apply second-pass web auto-file (personal/news -> No-Client/Non-Billable)."

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, required=True)
        parser.add_argument('--days', type=int, default=14)
        parser.add_argument('--sweeps-only', action='store_true',
                            help='Only print blocks that would be auto-filed non-billable.')
        parser.add_argument('--no-llm', action='store_true',
                            help='Skip the gpt-4o-mini fallback (heuristics only).')
        parser.add_argument('--apply', action='store_true',
                            help='Actually write the sweep (default is preview only).')

    def handle(self, *args, **opts):
        org_id = opts['org_id']
        days = opts['days']
        sweeps_only = opts['sweeps_only']
        use_llm = not opts['no_llm']
        apply = opts['apply']

        if not Organization.objects.filter(id=org_id).exists():
            raise CommandError(f'Organization {org_id} not found')

        since = (timezone.now() - timedelta(days=days)).date()
        client_forms = sp._build_client_forms(org_id)
        title_index = sp._build_title_index(org_id, since)

        pile = Block.objects.filter(
            org_id=org_id, deleted_at__isnull=True, start__date__gte=since,
            classification_state__in=['captured', 'proposed'], client_id__isnull=True,
        ).exclude(minutes__lt=2).order_by('-start')

        counts = {'SWEEP': 0, 'PROTECT': 0, 'KEEP': 0, 'OTHER': 0}
        sweep_minutes = 0
        rows = []

        for b in pile:
            if b.categorized_by in ('manual', 'correction'):
                continue
            action, cid, conf, reason = sp.classify_block(
                b, client_forms, title_index, web_autofile=True)

            verdict = None
            if action == 'llm_web_check':
                if use_llm:
                    verdict = sp.llm_web_verdict(b)
                    if verdict == 'personal':
                        label, detail = 'SWEEP', 'AI: personal/news'
                    else:
                        label, detail = 'KEEP', f'AI: {verdict}'
                else:
                    label, detail = 'KEEP', 'AI skipped (--no-llm)'
            elif action == 'commit_nb':
                label, detail = 'SWEEP', reason.replace('second-pass: ', '')
            elif action == 'propose_needs':
                label = 'PROTECT' if 'work tool' in reason else 'KEEP'
                detail = reason.replace('second-pass: ', '')
            elif action == 'propose_high':
                label, detail = 'KEEP', reason.replace('second-pass: ', '')
            else:
                label, detail = 'OTHER', action

            counts[label if label in counts else 'OTHER'] += 1
            if label == 'SWEEP':
                sweep_minutes += (b.minutes or 0)

            if sweeps_only and label != 'SWEEP':
                continue
            rows.append((label, b, detail))

        # ---- report ----
        self.stdout.write('')
        for label, b, detail in rows:
            app = (b.app_name or '')[:14]
            url = (b.url or '')[:34]
            title = (b.window_title or '')[:60]
            self.stdout.write(
                f'  {label:8s} min={(b.minutes or 0):3d} [{app:14s}] '
                f'{detail:26s} url={url!r} :: {title!r}')

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Summary'))
        self.stdout.write(
            f"  SWEEP (auto non-billable): {counts['SWEEP']:4d}  ({sweep_minutes} min)")
        self.stdout.write(f"  PROTECT (work tool, kept): {counts['PROTECT']:4d}")
        self.stdout.write(f"  KEEP (stays in Needs You): {counts['KEEP']:4d}")
        if counts['OTHER']:
            self.stdout.write(f"  OTHER: {counts['OTHER']}")

        if not apply:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'PREVIEW ONLY — nothing written. Re-run with --apply to commit the SWEEP set.'))
            return

        # Apply: reuse run_second_pass's write path by forcing the flag on for
        # this org via a one-shot run. We call it directly so writes match prod.
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('Applying sweep via run_second_pass (writes)...'))
        # Temporarily force enablement regardless of the global flag.
        orig = sp.web_autofile_enabled
        try:
            sp.web_autofile_enabled = lambda _oid: True
            result = sp.run_second_pass(org_id, days=days, dry_run=False)
        finally:
            sp.web_autofile_enabled = orig
        self.stdout.write(self.style.SUCCESS(f'  done: {result}'))
