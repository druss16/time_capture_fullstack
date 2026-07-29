"""
tracker/management/commands/backfill_title_wins.py

One-off corrective backfill for the "stale manual-override leak" — committed
blocks whose OWN TEXT deterministically names a client (Stage-3 title-alias /
file-path / domain) that differs from the client the block was committed to,
because a decaying agent tray-override forward-filled onto the window.

This mirrors the go-forward fix in ClassificationService.apply() (the
"TITLE-WINS EXCEPTION"), but for blocks already committed. It is deliberately
self-contained: it RE-RUNS the classifier (skip_ai=True — deterministic, no
network) and re-derives the title-wins predicate from live signals rather than
trusting the stored proposed_client_id, so a stale/pre-guard proposal (e.g. a
cemetery title that used to resolve to a church) can never drive a wrong flip.

A block is flipped only when ALL hold:
  • an authoritative name-bearing signal names the classifier's client, AND
  • no authoritative name-bearing signal names the currently-committed client, AND
  • the classifier's client differs from what's committed.

Corrections go through ClassificationService.recommit() so every flip writes an
audited ('manual', corrected_by_user=True) ground-truth label, exactly like a
Daily Review correction.

USAGE:
    # Dry run (default) — print what WOULD flip, change nothing
    python manage.py backfill_title_wins --org-id 21 --days 30

    # Restrict to one user
    python manage.py backfill_title_wins --org-id 21 --days 30 --user-id 49

    # Actually apply (writes to the DB)
    python manage.py backfill_title_wins --org-id 21 --days 30 --apply
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

logger = logging.getLogger(__name__)

# Authoritative, name-bearing Stage-3 signal types — the block text literally
# contains the client's name/alias/file/domain. Kept in sync with the
# _NAME_BEARING set in ClassificationService.apply().
NAME_BEARING = {
    'title_match_title_alias',
    'title_match_file_path',
    'title_match_domain',
}

# Agent-side evidence sources that mean the agent read the client out of the
# WINDOW ITSELF (as opposed to carried-forward context). If the agent's
# attribution came from one of these, its pick is window-truth and must not be
# overridden by a server title match — this is what protects a correct
# same-family agent match from a server alias-coverage gap. Kept in sync with
# _AGENT_WINDOW_TEXT_SOURCES in ClassificationService.apply().
AGENT_WINDOW_TEXT_SOURCES = {
    'title_alias_match', 'file_path_client_folder',
    'url_domain_match', 'email_thread_match',
    'tax_software_taxpayer', 'qb_company_file',
}


class Command(BaseCommand):
    help = (
        'Backfill committed blocks mis-attributed by a stale agent override '
        'when the block text authoritatively names a different client '
        '(title-wins). Dry-run by default; pass --apply to write.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, required=True)
        parser.add_argument('--days', type=int, default=30,
                            help='Look back this many days (by block.day).')
        parser.add_argument('--user-id', type=int, default=None,
                            help='Restrict to a single user.')
        parser.add_argument('--apply', action='store_true',
                            help='Write the corrections. Omit for a dry run.')

    def handle(self, *args, **opts):
        from tracker.models import Block, Client, Organization
        from tracker.services.classification_service import ClassificationService

        org_id = opts['org_id']
        days = opts['days']
        user_id = opts['user_id']
        do_apply = opts['apply']

        try:
            org = Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist:
            raise CommandError(f'Organization {org_id} not found')

        since = (timezone.now() - timedelta(days=days)).date()
        qs = Block.objects.filter(
            org_id=org_id,
            classification_state='committed',
            day__gte=since,
        ).exclude(client_id=None)
        if user_id:
            qs = qs.filter(user_id=user_id)

        total = qs.count()
        self.stdout.write(
            f'Scanning {total} committed blocks in org {org_id} '
            f'since {since}{f" (user {user_id})" if user_id else ""}...'
        )

        # Cache client names for readable output.
        names = {c.id: c.name for c in Client.objects.filter(org_id=org_id)}

        # One service per user (context is per-user).
        svc_cache = {}
        flips = []

        for block in qs.iterator():
            svc = svc_cache.get(block.user_id)
            if svc is None:
                svc = ClassificationService(org=org, user=block.user)
                svc_cache[block.user_id] = svc

            committed_id = block.client_id
            # classify() is pure — it does not write to the block.
            try:
                decision = svc.classify(block, skip_ai=True)
            except Exception as e:  # never let one bad block abort the sweep
                logger.warning('classify failed for block %s: %s', block.id, e)
                continue

            new_id = decision.client_id
            if not new_id or new_id == committed_id:
                continue

            names_new = any(
                s.type in NAME_BEARING and s.detail
                and s.detail.get('client_id') == new_id
                for s in decision.matched_signals
            )
            names_committed = any(
                s.type in NAME_BEARING and s.detail
                and s.detail.get('client_id') == committed_id
                for s in decision.matched_signals
            )
            # Guard b: the committed (agent) pick must be stale context, not a
            # client the agent read from the window itself.
            agent_sigs = [
                s for s in decision.matched_signals
                if s.type == 'agent_inference' and s.detail
                and s.detail.get('client_id') == committed_id
            ]
            agent_read_window_text = any(
                src in AGENT_WINDOW_TEXT_SOURCES
                for s in agent_sigs
                for src in (s.detail.get('inference_evidence_sources') or [])
            )
            agent_pick_is_stale = bool(agent_sigs) and not agent_read_window_text
            if names_new and not names_committed and agent_pick_is_stale:
                flips.append((block, committed_id, new_id))

        # Report.
        billable = sum(1 for b, _, _ in flips if b.is_billable)
        self.stdout.write('')
        self.stdout.write(
            f'{"APPLYING" if do_apply else "DRY RUN — would flip"} '
            f'{len(flips)} block(s) ({billable} billable):'
        )
        for block, old_id, new_id in flips:
            self.stdout.write(
                f'  blk {block.id} day={block.day} u={block.user_id} '
                f'bill={block.is_billable}  '
                f'{old_id} ({names.get(old_id, "?")}) -> '
                f'{new_id} ({names.get(new_id, "?")})  '
                f'| {(block.window_title or "")[:50]}'
            )

        if not do_apply:
            self.stdout.write('')
            self.stdout.write('Dry run only — nothing written. Re-run with --apply to commit.')
            return

        applied = 0
        for block, old_id, new_id in flips:
            svc = svc_cache[block.user_id]
            svc.recommit(
                block, user=block.user,
                override={'client_id': new_id},
                audit_detail={
                    'reason': 'backfill_title_wins_stale_override_leak',
                    'window_title': block.window_title,
                    'from_client_id': old_id,
                },
            )
            applied += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Applied {applied} correction(s).'))
