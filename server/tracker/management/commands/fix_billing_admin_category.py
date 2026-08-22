"""Normalise the 'Billing / Admin' category string to 'Billing/Admin'.

is_internal_firm_work() emitted the spaced form while industry_categories and
every TaskType row use the unspaced one, so those blocks sat on a category that
matched no task type — invisible to billable rules, reports and the task-type
matrix. The emitter is fixed; this repairs what it already wrote.

Deliberately narrower than migrate_block_categories, which remaps the whole
category vocabulary for an org. This touches one string and nothing else, so it
can be run on a live firm without reviewing a thousand other rewrites.

Writes with .update() rather than .save(): a pure string normalisation should
not fire classification side effects. Billability is unaffected either way —
nothing derives it from the category today, which is the reason the orphan went
unnoticed for so long.
"""
from django.core.management.base import BaseCommand

from tracker.models import Block, Organization

WRONG = 'Billing / Admin'
RIGHT = 'Billing/Admin'


class Command(BaseCommand):
    help = "Rename the 'Billing / Admin' category to 'Billing/Admin'."

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true',
                            help='Write the change. Without it, this is a dry run.')

    def handle(self, *args, **opts):
        org_id = opts['org_id']
        apply_ = opts['apply']
        org = Organization.objects.filter(id=org_id).first()
        if not org:
            self.stderr.write(f'No org {org_id}.')
            return

        hit_hours, hit_ai, hit_proposed, minutes = [], [], [], 0
        # Materialised, not .iterator(): a named server-side cursor does not
        # survive this database's transaction pooler.
        blocks = Block.objects.filter(org_id=org_id, deleted_at__isnull=True).only(
            'id', 'category_hours', 'ai_category', 'proposed_category', 'minutes')
        for b in blocks:
            if isinstance(b.category_hours, dict) and WRONG in b.category_hours:
                hit_hours.append(b)
                minutes += b.minutes or 0
            if b.ai_category == WRONG:
                hit_ai.append(b.id)
            if b.proposed_category == WRONG:
                hit_proposed.append(b.id)

        self.stdout.write(f'{"APPLY" if apply_ else "DRY RUN"} — org {org_id} ({org.name})')
        self.stdout.write(f'  category_hours carrying {WRONG!r}: {len(hit_hours)} blocks, '
                          f'{minutes / 60:.1f} h')
        self.stdout.write(f'  ai_category      equal to {WRONG!r}: {len(hit_ai)} blocks')
        self.stdout.write(f'  proposed_category equal to {WRONG!r}: {len(hit_proposed)} blocks')

        if not apply_:
            self.stdout.write('  nothing written — pass --apply to commit')
            return

        changed = 0
        for b in hit_hours:
            hours = dict(b.category_hours)
            # Merge rather than overwrite: a block could legitimately carry both
            # spellings, and dropping one would lose its minutes.
            hours[RIGHT] = (hours.get(RIGHT) or 0) + (hours.pop(WRONG) or 0)
            Block.objects.filter(id=b.id).update(category_hours=hours)
            changed += 1
        if hit_ai:
            Block.objects.filter(id__in=hit_ai).update(ai_category=RIGHT)
        if hit_proposed:
            Block.objects.filter(id__in=hit_proposed).update(proposed_category=RIGHT)

        self.stdout.write(self.style.SUCCESS(f'  rewrote {changed} blocks'))
