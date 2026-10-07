"""
Remove Chrome's "High memory usage - N MB" label from titles already stored.

New events lose it at ingestion (content_identity.normalize_ingested_title).
This cleans what arrived before that: Block.window_title, Block.title and
RawEvent.window_title. Only that label is removed; the rest of each title is
left exactly as it was. Uses .update(), so no block is re-classified and no
signal fires.

    python manage.py strip_chrome_memory_label              # counts only, last 30 days
    python manage.py strip_chrome_memory_label --apply
    python manage.py strip_chrome_memory_label --org 17 --days 0 --apply   # all time

RawEvent is the big table, hence the 30-day default.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Func, Value
from django.utils import timezone

from tracker.models import Block, OrganizationMembership, RawEvent
from tracker.utils.content_identity import CHROME_MEMORY_LABEL_PG

TARGETS = (
    (Block, 'window_title'),
    (Block, 'title'),
    (RawEvent, 'window_title'),
)


class Command(BaseCommand):
    help = "Strip Chrome's 'High memory usage - N MB' label from stored titles."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the change (default: count only).')
        parser.add_argument('--org', type=int, help='Limit to one org id.')
        parser.add_argument('--days', type=int, default=30, help='How far back (0 = all time). Default 30.')

    def handle(self, *args, **opts):
        total = 0
        with transaction.atomic():
            for model, field in TARGETS:
                qs = model.objects.all() if model is RawEvent else Block.all_objects.all()
                if opts['org']:
                    if model is Block:
                        qs = qs.filter(org_id=opts['org'])
                    else:  # RawEvent has no org column
                        qs = qs.filter(user_id__in=OrganizationMembership.objects.filter(
                            organization_id=opts['org']).values('user_id'))
                if opts['days']:
                    since = timezone.now() - timedelta(days=opts['days'])
                    qs = qs.filter(**({'start__gte': since} if model is Block else {'end_ts__gte': since}))
                qs = qs.filter(**{f'{field}__iregex': r'high memory usage\s*[-–—]\s*[0-9.,]+\s*[KMGT]B'})
                n = qs.count()
                total += n
                self.stdout.write(f"{model.__name__}.{field}: {n} row(s)")
                if opts['apply'] and n:
                    qs.update(**{field: Func(F(field), Value(CHROME_MEMORY_LABEL_PG), Value(''), Value('gi'),
                                             function='REGEXP_REPLACE')})
        verb = 'Stripped' if opts['apply'] else 'Would strip'
        self.stdout.write(self.style.SUCCESS(f"{verb} the label from {total} title(s)."
                                             + ('' if opts['apply'] else ' Re-run with --apply to write.')))
