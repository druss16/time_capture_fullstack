"""
Management command: map an email domain to a client, so mail attribution can fire.

Mail matching has two strategies (tracker/mail_matching.py):
  1. domain rule  — OrgCalendarRule(match_type='attendee_domain'), conf 0.95
  2. subject text — fuzzy match of a client name inside the subject, conf 0.80

Strategy 1 is the reliable one. For a long time it read a table with no API, no
admin and no UI, so it held ZERO rows and never fired for anyone. Settings →
Email domains is now the way in for firms; this command is the operator's way
in, and both go through tracker/services/mail_domains.py so they apply the same
validation (no public domains, no firm-own domain) and the same rematch.

Mail sync uses a DELTA query: once a message is synced it is never sent again.
So a new rule only affects FUTURE mail unless the rows already stored are
re-matched. The settings screen queues that automatically; here it is
--rematch, so an operator can dry-run it first.

Usage:
  python manage.py mail_domains --org 21 --observed        # what domains do we see?
  python manage.py mail_domains --org 21 --list            # what is mapped today?
  python manage.py mail_domains --org 21 --map acmecorp.com 412
  python manage.py mail_domains --org 21 --unmap acmecorp.com
  python manage.py mail_domains --org 21 --rematch         # dry run, shows what would change
  python manage.py mail_domains --org 21 --rematch --apply # write extracted_client

--observed and --list are read-only. --map/--unmap write one rule row.
--rematch needs --apply before it writes anything.
"""
from django.core.management.base import BaseCommand, CommandError

from tracker.models import Organization
from tracker.services import mail_domains as svc


class Command(BaseCommand):
    help = "Inspect observed email domains and map them to clients for mail attribution."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--observed', action='store_true',
                            help='List domains seen in mail + calendar with volume and current mapping')
        parser.add_argument('--list', action='store_true',
                            help='List the attendee_domain rules this org has')
        parser.add_argument('--map', nargs=2, metavar=('DOMAIN', 'CLIENT_ID'),
                            help='Map a domain to a client id (re-points an existing mapping)')
        parser.add_argument('--unmap', metavar='DOMAIN',
                            help='Remove the rule for a domain')
        parser.add_argument('--rematch', action='store_true',
                            help='Re-run matching over stored MailSignal rows (delta sync '
                                 'never resends old mail, so new rules need this)')
        parser.add_argument('--apply', action='store_true',
                            help='Actually write during --rematch')
        parser.add_argument('--days', type=int, default=svc.DEFAULT_WINDOW_DAYS,
                            help=f'Window for --observed and --rematch (default {svc.DEFAULT_WINDOW_DAYS})')

    def handle(self, *args, **opts):
        try:
            org = Organization.objects.get(id=opts['org'])
        except Organization.DoesNotExist:
            raise CommandError(f"No org with id {opts['org']}")

        did_something = False
        if opts['observed']:
            self._observed(org, opts['days'])
            did_something = True
        if opts['list']:
            self._list(org)
            did_something = True
        if opts['map']:
            self._map(org, opts['map'][0], opts['map'][1])
            did_something = True
        if opts['unmap']:
            self._unmap(org, opts['unmap'])
            did_something = True
        if opts['rematch']:
            self._rematch(org, opts['days'], opts['apply'])
            did_something = True

        if not did_something:
            self.stdout.write(self.style.WARNING(
                "Nothing to do. Pass --observed, --list, --map, --unmap or --rematch."
            ))

    # ─── read-only ────────────────────────────────────────────────────────────

    def _observed(self, org, days):
        activity = svc.domain_activity(org, days)
        mapped = {svc._rule_domain(r): r.target_client for r in svc.list_mappings(org)}
        own = svc.org_own_domains(org)
        ignored = {i.domain for i in svc.ignored_domains(org)}
        ctx = svc.SuggestionContext.for_org(org)

        self.stdout.write(f"\nDomains seen in the last {days} days (org {org.id}):\n")
        if not activity:
            self.stdout.write("  (none — is a mailbox or calendar connected, and is sync running?)")
            return

        self.stdout.write(f"  {'domain':40s} {'mail':>5s} {'cal':>5s}  status")
        rows = sorted(activity.items(), key=lambda kv: -(kv[1]['messages'] + kv[1]['events']))
        for d, a in rows:
            if d in mapped:
                status = f"→ {mapped[d].name}"
            elif d in svc.PUBLIC_DOMAINS:
                status = "public domain — cannot be mapped"
            elif d in own:
                status = "your firm's own domain"
            elif d in ignored:
                status = "ignored"
            else:
                s = svc.suggest_client(d, ctx)
                status = (f"unmapped — suggest {s['client_name']} (#{s['client_id']})"
                          if s else "unmapped")
            self.stdout.write(f"  {d:40s} {a['messages']:5d} {a['events']:5d}  {status}")
        self.stdout.write("")

    def _list(self, org):
        rules = svc.list_mappings(org, include_inactive=True)
        self.stdout.write(f"\nDomain rules for org {org.id}: {len(rules)}\n")
        for r in rules:
            flag = '' if r.is_active else '  (inactive)'
            client = r.target_client.name if r.target_client else '(no client)'
            self.stdout.write(f"  {r.match_value:40s} → {client}{flag}")
        self.stdout.write("")

    # ─── writes ───────────────────────────────────────────────────────────────

    def _map(self, org, domain, client_id):
        try:
            change = svc.map_domain(org, domain, client_id)
        except svc.DomainError as e:
            raise CommandError(str(e))
        verb = 'Created' if change.created else 'Updated'
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: {change.domain} → {change.rule.target_client.name}"))
        self.stdout.write("  Applies to mail synced from now on. For mail already "
                          "stored, run --rematch --apply.")

    def _unmap(self, org, domain):
        change = svc.unmap_domain(org, domain)
        if change:
            self.stdout.write(self.style.SUCCESS(f"Removed rule for {change.domain}"))
        else:
            self.stdout.write(self.style.WARNING(f"No rule for {domain.strip().lower()}"))

    def _rematch(self, org, days, apply):
        result = svc.rematch_mail(org, days=days, apply=apply)
        total = sum(result['changed'].values())
        mode = "APPLIED" if apply else "DRY RUN — nothing written"
        self.stdout.write(f"\n{mode}: {total} signal(s) would change ({days}d, org {org.id})\n")
        for line in result['examples']:
            self.stdout.write(line)
        if total and not apply:
            self.stdout.write("\nRe-run with --apply to write.")
        self.stdout.write("")
