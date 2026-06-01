"""
Management command: derive_aliases

Derives client-name aliases for an org and appends new ones to each
Client.aliases JSON list (the flat string list Stage 3 of the classifier
reads). Existing aliases are preserved; only genuinely-new strings are added.

    # Preview only — writes nothing. Use this first against TL Wall.
    python manage.py derive_aliases --org-id 21 --dry-run

    # Skip low-confidence derived aliases (acronyms 0.7, single-tokens 0.6)
    python manage.py derive_aliases --org-id 21 --dry-run --min-confidence 0.8

    # Apply for real
    python manage.py derive_aliases --org-id 21

Hook from sync / onboarding code instead of shelling out:

    from django.core.management import call_command
    call_command("derive_aliases", org_id=new_org.id)

NOTES
-----
* Aliases are stored as plain strings in Client.aliases. Stage 3 calls
  .lower() on each element, so ONLY strings may be written — never dicts.
* Confidence is not persisted (Stage 3 scores by match type at classify
  time). The --min-confidence flag filters which derived candidates get
  written, but the written value is just the alias string.
* Client's FK to Organization is `org`, and Client has no soft-delete
  field — active clients are filtered via is_active=True.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tracker.services.alias_derivation import derive_for_org


class Command(BaseCommand):
    help = "Derive client aliases for an org and append new ones to Client.aliases."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--org-id", type=int)
        group.add_argument("--org-slug", type=str)
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print what would be added without writing anything.",
        )
        parser.add_argument(
            "--min-confidence", type=float, default=0.0,
            help="Skip derived aliases below this confidence "
                 "(e.g. 0.8 drops acronyms and single-token guesses).",
        )

    def handle(self, *args, **opts):
        from tracker.models import Client, Organization

        # ---- Resolve org ----
        if opts.get("org_id") is not None:
            try:
                org = Organization.objects.get(pk=opts["org_id"])
            except Organization.DoesNotExist:
                raise CommandError(f"No org with id={opts['org_id']}")
        else:
            try:
                org = Organization.objects.get(slug=opts["org_slug"])
            except Organization.DoesNotExist:
                raise CommandError(f"No org with slug={opts['org_slug']!r}")

        # ---- Load active clients ----
        clients = list(Client.objects.filter(org=org, is_active=True))
        if not clients:
            self.stdout.write(self.style.WARNING(
                f"No active clients for org {org.pk} ({org.name}); nothing to derive."
            ))
            return

        # ---- Derive ----
        name_pairs = [(c.pk, c.name) for c in clients]
        derived = derive_for_org(name_pairs)

        min_conf = opts["min_confidence"]
        derived = [d for d in derived if d.confidence >= min_conf]

        # ---- Group derived aliases by client, skipping existing (case-insensitive) ----
        by_client = {c.pk: c for c in clients}
        to_add = {}   # client_id -> list[(alias, confidence)]
        skipped = 0

        for d in derived:
            client = by_client.get(d.client_id)
            if client is None:
                continue

            existing_lower = {
                a.lower() for a in (client.aliases or []) if isinstance(a, str)
            }
            # Never re-add the original name or an alias already present.
            if d.alias.lower() == client.name.lower():
                skipped += 1
                continue
            if d.alias.lower() in existing_lower:
                skipped += 1
                continue
            # Avoid adding the same new alias twice within this run.
            already_queued = {a.lower() for a, _ in to_add.get(d.client_id, [])}
            if d.alias.lower() in already_queued:
                continue

            to_add.setdefault(d.client_id, []).append((d.alias, d.confidence))

        total_new = sum(len(v) for v in to_add.values())

        self.stdout.write(
            f"Org {org.pk} ({org.name}): {len(clients)} active clients, "
            f"{len(derived)} derived candidates (min_conf={min_conf}), "
            f"{skipped} already present, {total_new} new aliases to add "
            f"across {len(to_add)} clients."
        )

        # ---- DRY RUN ----
        if opts["dry_run"]:
            for cid in sorted(to_add, key=lambda c: by_client[c].name.lower()):
                client = by_client[cid]
                self.stdout.write("\n  %s  (id=%s)" % (client.name, cid))
                for alias, conf in sorted(to_add[cid], key=lambda x: -x[1]):
                    self.stdout.write("      + %r   [%s]" % (alias, conf))
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing written."))
            return

        # ---- APPLY ----
        updated = 0
        with transaction.atomic():
            for cid, new_aliases in to_add.items():
                client = by_client[cid]
                current = list(client.aliases or [])
                current.extend(alias for alias, _ in new_aliases)
                client.aliases = current
                client.save(update_fields=["aliases"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            "Added %d aliases across %d clients for org %d." % (total_new, updated, org.pk)
        ))