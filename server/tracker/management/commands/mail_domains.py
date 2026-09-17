"""
Management command: map an email domain to a client, so mail attribution can fire.

Mail matching has two strategies (tracker/mail_matching.py):
  1. domain rule  — OrgCalendarRule(match_type='attendee_domain'), conf 0.95
  2. subject text — fuzzy match of a client name inside the subject, conf 0.80

Strategy 1 is the reliable one, and it reads a table with no API, no admin and
no UI anywhere in the product — so in practice it held ZERO rows and never
fired for anyone. Every mail signal that lacked a client name spelled out in
its subject line stored with extracted_client=NULL, and the Stage 7 classifier
filters those out (extracted_client__isnull=False), so the mail integration
could sync perfectly and still attribute nothing. This command is the way in
until that table gets a real settings screen.

Mail sync uses a Graph DELTA query: once a message is synced it is never sent
again. So a new rule only affects FUTURE mail unless you also re-run matching
over the rows already stored — that is what --rematch is for.

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
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from tracker.models import Client, MailSignal, OrgCalendarRule, Organization
from tracker.tasks_mail import PUBLIC_EMAIL_DOMAINS


class Command(BaseCommand):
    help = "Inspect observed email domains and map them to clients for mail attribution."

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, required=True)
        parser.add_argument('--observed', action='store_true',
                            help='List domains seen in MailSignal with volume and current mapping')
        parser.add_argument('--list', action='store_true',
                            help='List the attendee_domain rules this org has')
        parser.add_argument('--map', nargs=2, metavar=('DOMAIN', 'CLIENT_ID'),
                            help='Map a domain to a client id')
        parser.add_argument('--unmap', metavar='DOMAIN',
                            help='Remove the rule for a domain')
        parser.add_argument('--rematch', action='store_true',
                            help='Re-run matching over stored MailSignal rows (delta sync '
                                 'never resends old mail, so new rules need this)')
        parser.add_argument('--apply', action='store_true',
                            help='Actually write during --rematch')
        parser.add_argument('--days', type=int, default=90,
                            help='Window for --observed and --rematch (default 90)')

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
        from django.utils import timezone
        from datetime import timedelta

        since = timezone.now() - timedelta(days=days)
        rows = (MailSignal.objects
                .filter(org=org, occurred_at__gte=since)
                .values('other_party_domain')
                .annotate(n=Count('id'))
                .order_by('-n'))

        mapped = {
            (r.match_value or '').lower().lstrip('@'): r.target_client
            for r in OrgCalendarRule.objects.filter(
                org=org, match_type='attendee_domain', is_active=True,
            ).select_related('target_client')
        }

        self.stdout.write(f"\nDomains seen in the last {days} days (org {org.id}):\n")
        if not rows:
            self.stdout.write("  (none — is a mailbox connected, and is sync running?)")
            return

        self.stdout.write(f"  {'domain':40s} {'seen':>5s}  status")
        for r in rows:
            d = (r['other_party_domain'] or '').lower()
            if d in mapped:
                status = f"→ {mapped[d].name}"
            elif d in PUBLIC_EMAIL_DOMAINS:
                status = "public domain — cannot be mapped"
            else:
                status = "unmapped"
            self.stdout.write(f"  {d:40s} {r['n']:5d}  {status}")
        self.stdout.write("")

    def _list(self, org):
        rules = (OrgCalendarRule.objects
                 .filter(org=org, match_type='attendee_domain')
                 .select_related('target_client')
                 .order_by('match_value'))
        self.stdout.write(f"\nDomain rules for org {org.id}: {rules.count()}\n")
        for r in rules:
            flag = '' if r.is_active else '  (inactive)'
            client = r.target_client.name if r.target_client else '(no client)'
            self.stdout.write(f"  {r.match_value:40s} → {client}{flag}")
        self.stdout.write("")

    # ─── writes ───────────────────────────────────────────────────────────────

    def _map(self, org, domain, client_id):
        domain = (domain or '').strip().lower().lstrip('@')
        if not domain or '.' not in domain:
            raise CommandError(f"{domain!r} does not look like a domain")
        if domain in PUBLIC_EMAIL_DOMAINS:
            # match_by_domain_rule refuses these at match time, so a rule here
            # would be silently dead. Say so instead of writing a no-op row.
            raise CommandError(
                f"{domain} is a public email domain — matching refuses it, so the rule "
                f"would never fire. Everyone shares that domain; it identifies nobody."
            )
        try:
            client = Client.objects.get(id=int(client_id), org=org)
        except (Client.DoesNotExist, ValueError):
            raise CommandError(f"No client {client_id} in org {org.id}")

        rule, created = OrgCalendarRule.objects.update_or_create(
            org=org,
            match_type='attendee_domain',
            match_value=domain,
            defaults={'target_client': client, 'is_active': True},
        )
        verb = 'Created' if created else 'Updated'
        self.stdout.write(self.style.SUCCESS(f"{verb}: {domain} → {client.name}"))
        self.stdout.write("  Applies to mail synced from now on. For mail already "
                          "stored, run --rematch --apply.")

    def _unmap(self, org, domain):
        domain = (domain or '').strip().lower().lstrip('@')
        deleted, _ = OrgCalendarRule.objects.filter(
            org=org, match_type='attendee_domain', match_value=domain,
        ).delete()
        if deleted:
            self.stdout.write(self.style.SUCCESS(f"Removed rule for {domain}"))
        else:
            self.stdout.write(self.style.WARNING(f"No rule for {domain}"))

    def _rematch(self, org, days, apply):
        from datetime import timedelta

        from django.utils import timezone

        from tracker.mail_matching import find_mail_match
        from tracker.utils.db_iter import keyset_chunks

        since = timezone.now() - timedelta(days=days)
        clients_cache = list(
            Client.objects.filter(org=org, is_active=True).only('id', 'name', 'code', 'aliases')
        )
        rules_cache = list(
            OrgCalendarRule.objects.filter(
                org=org, is_active=True, match_type='attendee_domain',
            ).select_related('target_client').order_by('-priority', 'id')
        )

        signals = MailSignal.objects.filter(org=org, occurred_at__gte=since)
        changed = Counter()
        examples = []

        # keyset_chunks, not .iterator(): this loop writes to the rows it walks,
        # and a named server-side cursor dies on the first write under Neon's
        # transaction pooler (see tracker/utils/db_iter.py).
        for page in keyset_chunks(signals.select_related('extracted_client')):
            for sig in page:
                # The stored subject is only ever populated for an already-matched
                # signal, so a previously unmatched row has no subject to re-read.
                # Domain rules are what this pass can newly apply.
                client, conf, method, _subj = find_mail_match(
                    mail_dict={
                        'other_party_domain': sig.other_party_domain,
                        'subject': sig.subject_extract or '',
                        'direction': 'in' if sig.direction == 'in' else 'out',
                    },
                    org=org,
                    clients_cache=clients_cache,
                    rules_cache=rules_cache,
                )
                new_client = client if (client and conf >= 0.70) else None
                if (new_client.id if new_client else None) == sig.extracted_client_id:
                    continue

                changed[(sig.other_party_domain,
                         new_client.name if new_client else None)] += 1
                if len(examples) < 10:
                    examples.append(
                        f"  {sig.occurred_at:%Y-%m-%d} {sig.other_party_domain:30s} "
                        f"{(sig.extracted_client.name if sig.extracted_client else 'none')} "
                        f"→ {new_client.name if new_client else 'none'}"
                    )
                if apply:
                    sig.extracted_client = new_client
                    sig.save(update_fields=['extracted_client'])

        total = sum(changed.values())
        mode = "APPLIED" if apply else "DRY RUN — nothing written"
        self.stdout.write(f"\n{mode}: {total} signal(s) would change ({days}d, org {org.id})\n")
        for line in examples:
            self.stdout.write(line)
        if total and not apply:
            self.stdout.write("\nRe-run with --apply to write.")
        self.stdout.write("")
