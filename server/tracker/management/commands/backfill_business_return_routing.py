"""
Re-attribute UltraTax BUSINESS returns (1120, 1120S, 1065, 990) that were
misrouted to the firm's "Internal - Tax" client.

Root cause (fixed in tracker/utils/tax_software.py): the UltraTax return-type
parser read the return type from the text BEFORE the match span, which never
contained it, so every return defaulted to "1040" (individual). Business returns
therefore skipped the entity→client match and, for orgs with
route_individual_returns_to_internal_tax=True, landed in Internal - Tax.

This command re-extracts the (now-correct) tax context for blocks currently on
Internal - Tax and re-attributes any business return whose entity name matches a
real client. Dry-run by default; pass --apply to write.

    docker exec time_api python manage.py backfill_business_return_routing --org-id 21
    docker exec time_api python manage.py backfill_business_return_routing --org-id 21 --apply
"""
from django.core.management.base import BaseCommand

from tracker.models import Block, Client, Organization
from tracker.utils.tax_software import extract_tax_context


class Command(BaseCommand):
    help = "Re-attribute UltraTax business returns misrouted to Internal - Tax."

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None,
                            help='Limit to one org (default: all orgs).')
        parser.add_argument('--apply', action='store_true',
                            help='Write changes. Omit for a dry run.')

    def handle(self, *args, **opts):
        from tracker.services.classification_service import ClassificationService

        apply = opts['apply']
        org_ids = ([opts['org_id']] if opts.get('org_id')
                   else list(Organization.objects.values_list('id', flat=True)))

        grand_checked = grand_changed = 0

        for org_id in org_ids:
            org = Organization.objects.filter(id=org_id).first()
            if not org:
                continue
            internal_tax = Client.objects.filter(org=org, name__iexact='internal - tax').first()
            if not internal_tax:
                continue

            qs = Block.objects.filter(
                org=org, client=internal_tax, window_title__icontains='UltraTax',
            )

            svc = None
            checked = changed = 0
            for b in qs.iterator():
                ctx = extract_tax_context(b.window_title or '')
                if not ctx or not ctx.is_business_return:
                    continue
                checked += 1
                if svc is None:
                    svc = ClassificationService(org=org, user=b.user)
                    svc._clients = list(Client.objects.filter(org=org))
                match = svc._match_taxpayer_to_client(ctx.taxpayer_name)
                if match and match.id != b.client_id:
                    changed += 1
                    self.stdout.write(
                        f"  [{b.id}] {ctx.return_type} '{ctx.taxpayer_name}': "
                        f"Internal - Tax -> {match.name}"
                    )
                    if apply:
                        b.client = match
                        b.save(force_classifier=True)

            grand_checked += checked
            grand_changed += changed
            if checked:
                self.stdout.write(
                    f"org {org_id} ({org.name}): business_returns_on_internal_tax={checked} "
                    f"reattributed={changed}"
                )

        verb = 'reattributed' if apply else 'would-reattribute'
        self.stdout.write(self.style.SUCCESS(
            f"DONE — checked={grand_checked} {verb}={grand_changed} (apply={apply})"
        ))
