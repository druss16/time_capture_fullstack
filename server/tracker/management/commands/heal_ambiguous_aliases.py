"""
Management command: heal_ambiguous_aliases

Removes auto-derived client aliases that have become ambiguous against a
sibling client (the multi-parish problem). Example: "St. Mary's - Alaska"
gets a bare "St Mary's" alias while it's the only St Mary's; later
"St. Mary's - Texas" is added, and now "St Mary's" would mis-attribute
Texas activity to Alaska. Append-only derivation can PREVENT adding such an
alias, but cannot retroactively remove one written before the sibling
existed. This command closes that gap.

SAFE BY DESIGN — only removes aliases whose provenance in
Client.alias_sources is exactly 'derived'. Manually-entered aliases
('manual') and any unmarked/legacy aliases (no provenance entry) are NEVER
removed. The client's original name is never an alias to begin with.

    # Preview (writes nothing)
    python manage.py heal_ambiguous_aliases --org-id 21 --dry-run

    # Apply
    python manage.py heal_ambiguous_aliases --org-id 21

Runs automatically (append-only-safe) inside the per-create hook and the
nightly derive-client-aliases-sweep, right after derive_aliases.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tracker.services.alias_derivation import find_ambiguous_derived


class Command(BaseCommand):
    help = "Remove auto-derived aliases that now collide with a sibling client."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--org-id", type=int)
        group.add_argument("--org-slug", type=str)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        from tracker.models import Client, Organization

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

        clients = list(Client.objects.filter(org=org, is_active=True))
        if not clients:
            self.stdout.write(self.style.WARNING(
                f"No active clients for org {org.pk} ({org.name}); nothing to heal."
            ))
            return

        by_client = {c.pk: c for c in clients}
        flagged = find_ambiguous_derived(
            [(c.pk, c.name, c.aliases or []) for c in clients]
        )

        # Restrict removal to provenance == 'derived'. Anything else (manual or
        # unmarked legacy) is protected.
        to_remove = {}   # client_id -> list[alias]
        protected = 0
        for cid, aliases in flagged.items():
            client = by_client[cid]
            sources = client.alias_sources or {}
            removable = []
            for a in aliases:
                if sources.get(a.lower()) == "derived":
                    removable.append(a)
                else:
                    protected += 1
            if removable:
                to_remove[cid] = removable

        total = sum(len(v) for v in to_remove.values())
        self.stdout.write(
            f"Org {org.pk} ({org.name}): {len(clients)} active clients, "
            f"{total} ambiguous derived aliases to remove across {len(to_remove)} "
            f"clients ({protected} ambiguous but protected as manual/legacy)."
        )

        if not to_remove:
            self.stdout.write(self.style.SUCCESS("Nothing to heal."))
            return

        for cid in sorted(to_remove, key=lambda c: by_client[c].name.lower()):
            client = by_client[cid]
            self.stdout.write("\n  %s  (id=%s)" % (client.name, cid))
            for a in to_remove[cid]:
                self.stdout.write("      - %r" % a)

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing written."))
            return

        with transaction.atomic():
            for cid, removable in to_remove.items():
                client = by_client[cid]
                drop = {a.lower() for a in removable}
                client.aliases = [
                    a for a in (client.aliases or [])
                    if not (isinstance(a, str) and a.lower() in drop)
                ]
                client.alias_sources = {
                    k: v for k, v in (client.alias_sources or {}).items()
                    if k not in drop
                }
                client.save(update_fields=["aliases", "alias_sources"])

        self.stdout.write(self.style.SUCCESS(
            "\nRemoved %d ambiguous derived aliases for org %d." % (total, org.pk)
        ))
