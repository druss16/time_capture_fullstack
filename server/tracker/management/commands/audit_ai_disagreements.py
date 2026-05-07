"""
Show Stage 10 AI vs agent disagreements over the last N days.

Useful for tuning the disagreement threshold or finding systematic
issues (e.g. "AI keeps wanting to switch X to Y, what's the pattern?")

Usage:
  python manage.py audit_ai_disagreements
  python manage.py audit_ai_disagreements --days 7
  python manage.py audit_ai_disagreements --org "TL Wall Accounting"
"""

import json
from collections import Counter, defaultdict
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from tracker.models import AIProcessingLog, Organization


class Command(BaseCommand):
    help = 'Audit Stage 10 AI vs agent disagreements'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=1,
            help='Look back N days (default: 1)',
        )
        parser.add_argument(
            '--org', type=str,
            help='Limit to a single org name',
        )
        parser.add_argument(
            '--show-blocks', action='store_true',
            help='Print each disagreement individually',
        )

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts['days'])

        qs = AIProcessingLog.objects.filter(
            created_at__gte=cutoff,
            operation_type__in=[
                'stage_10_validation_agree',
                'stage_10_validation_uncertain',
                'stage_10_validation_disagree',
            ],
        )

        if opts['org']:
            try:
                org = Organization.objects.get(name=opts['org'])
                qs = qs.filter(org=org)
                self.stdout.write(f'Org: {org.name}')
            except Organization.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'Org {opts["org"]!r} not found'))
                return

        total = qs.count()
        agree = qs.filter(operation_type='stage_10_validation_agree').count()
        uncertain = qs.filter(operation_type='stage_10_validation_uncertain').count()
        disagree = qs.filter(operation_type='stage_10_validation_disagree').count()

        self.stdout.write(f'\n=== Last {opts["days"]} day(s) ===')
        self.stdout.write(f'Total Stage 10 validations: {total}')
        self.stdout.write(self.style.SUCCESS(f'  Agreed:    {agree} ({agree*100//total if total else 0}%)'))
        self.stdout.write(self.style.WARNING(f'  Uncertain: {uncertain} ({uncertain*100//total if total else 0}%)'))
        self.stdout.write(self.style.ERROR(f'  Disagreed: {disagree} ({disagree*100//total if total else 0}%)'))

        if disagree == 0:
            return

        # Breakdown of disagreements by which client the agent had vs which AI proposed
        self.stdout.write(f'\n=== Disagreement patterns ===')
        switch_pairs = Counter()
        confidence_buckets = defaultdict(int)

        disagreement_logs = qs.filter(operation_type='stage_10_validation_disagree')

        for log in disagreement_logs:
            inp = log.input_data or {}
            out = log.output_data or {}
            agent_name = inp.get('agent_client_name', '?')
            ai_name = out.get('ai_client_name', '?')
            conf = out.get('ai_confidence', 0)

            switch_pairs[(agent_name, ai_name)] += 1

            if conf >= 0.95:
                confidence_buckets['0.95+'] += 1
            elif conf >= 0.90:
                confidence_buckets['0.90-0.94'] += 1
            elif conf >= 0.85:
                confidence_buckets['0.85-0.89'] += 1
            else:
                confidence_buckets['<0.85'] += 1

        self.stdout.write('\nMost common disagreement pairs (agent → AI):')
        for (agent_name, ai_name), count in switch_pairs.most_common(20):
            self.stdout.write(f'  {count:3d}x  {agent_name!r:40s} → {ai_name!r}')

        self.stdout.write('\nConfidence distribution:')
        for bucket in ['0.95+', '0.90-0.94', '0.85-0.89', '<0.85']:
            count = confidence_buckets.get(bucket, 0)
            self.stdout.write(f'  {bucket}: {count}')

        if opts['show_blocks']:
            self.stdout.write('\n=== Individual disagreements ===')
            for log in disagreement_logs[:50]:
                inp = log.input_data or {}
                out = log.output_data or {}
                self.stdout.write(
                    f'  Block {inp.get("block_id")}: '
                    f'agent={inp.get("agent_client_name")} → '
                    f'AI proposed={out.get("ai_client_name")} '
                    f'(conf={out.get("ai_confidence", 0):.2f})\n'
                    f'    Title: {inp.get("title", "")[:80]}'
                )