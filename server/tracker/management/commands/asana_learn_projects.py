"""
Management command: asana_learn_projects

Links Asana projects that know their client but not their project, from the
firm's own QuickBooks Time entries and Daily Review filings
(integrations/asana/learning.py). The hourly Asana sync does this on its own;
this shows what it would do, and can re-file older blocks afterwards.

    # Preview only — writes nothing
    python manage.py asana_learn_projects --org-id 44

    # Link, then re-file the last 14 days of blocks with the new links
    python manage.py asana_learn_projects --org-id 44 --apply --refile-days 14
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.models import Integration


class Command(BaseCommand):
    help = "Learn Asana project links from the firm's own time entries."

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true', help='Write the links (default: preview).')
        parser.add_argument('--days', type=int, default=30, help='Evidence window in days.')
        parser.add_argument('--refile-days', type=int, default=0,
                            help='After --apply, re-run project attribution this many days back.')

    def handle(self, *args, org_id, apply, days, refile_days, **opts):
        from tracker.integrations.asana.learning import learn_links
        integration = (Integration.objects.select_related('organization')
                       .filter(organization_id=org_id, provider='asana').first())
        if integration is None:
            raise CommandError(f'Org {org_id} has no Asana connection.')
        out = learn_links(integration, dry_run=not apply, days=days)
        verb = 'Linked' if apply else 'Would link'
        self.stdout.write(f"Evidence spans: {out.get('spans', 0)}; Asana projects with evidence: "
                          f"{out.get('considered', 0)}")
        for c in sorted(out['changes'], key=lambda c: -c['votes']):
            self.stdout.write(f"  {c['asana_name']!r} -> {c['project_name']!r} "
                              f"({c['votes']} votes over {c['days']} days)")
        self.stdout.write(f"{verb} {out['linked']} Asana projects.")
        if apply and refile_days:
            from tracker.services.matter_attribution import attribute_matters_for_org
            res = attribute_matters_for_org(integration.organization, days=refile_days)
            self.stdout.write(f'Re-filed: {res}')
