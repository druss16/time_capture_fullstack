"""
Management command: prune_low_conf_aliases

One-off cleanup. Re-derives aliases for an org and removes any CURRENTLY-STORED
alias whose derived confidence is below --min-confidence. This undoes an apply
that ran at a lower floor than intended, leaving exactly the set that would
have been written at the given floor.

Only removes aliases that (a) are currently on the client AND (b) the deriver
would NOT have produced at >= min_confidence. Aliases that were already present
before derivation (e.g. QB-synced codes, hand-added) are preserved UNLESS they
exactly match a low-confidence derived candidate — to be safe we only strip
aliases that the current derivation run classifies as below the floor, so any
alias the deriver doesn't recognize at all is left untouched.

    # Preview what would be removed
    python manage.py prune_low_conf_aliases --org-id 21 --min-confidence 0.8 --dry-run

    # Apply
    python manage.py prune_low_conf_aliases --org-id 21 --min-confidence 0.8
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tracker.services.alias_derivation import derive_for_org


class Command(BaseCommand):
    help = "Remove stored aliases below a confidence floor (undo a low-floor apply)."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--org-id", type=int)
        group.add_argument("--org-slug", type=str)
        parser.add_argument("--min-confidence", type=float, required=True,
                            help="Keep aliases at or above this; strip below.")
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

        floor = opts["min_confidence"]
        clients = list(Client.objects.filter(org=org, is_active=True))
        if not clients:
            self.stdout.write(self.style.WARNING("No active clients; nothing to do."))
            return

        # Re-derive to learn each candidate alias's confidence.
        derived = derive_for_org([(c.pk, c.name) for c in clients])

        # client_id -> {alias_lower: best_confidence}
        conf_by_client: dict[object, dict[str, float]] = {}
        for d in derived:
            m = conf_by_client.setdefault(d.client_id, {})
            lk = d.alias.lower()
            if lk not in m or d.confidence > m[lk]:
                m[lk] = d.confidence

        by_client = {c.pk: c for c in clients}
        total_removed = 0
        to_write = {}  # client_id -> new alias list

        for cid, client in by_client.items():
            current = [a for a in (client.aliases or []) if isinstance(a, str)]
            if not current:
                continue
            derived_conf = conf_by_client.get(cid, {})

            kept, removed = [], []
            for a in current:
                lk = a.lower()
                # If this alias was a derived candidate BELOW the floor, strip it.
                # If it's at/above floor, or the deriver doesn't recognize it
                # (pre-existing, hand-added, original name), keep it.
                if lk in derived_conf and derived_conf[lk] < floor:
                    removed.append((a, derived_conf[lk]))
                else:
                    kept.append(a)

            if removed:
                total_removed += len(removed)
                to_write[cid] = kept
                if opts["dry_run"]:
                    self.stdout.write("\n  %s  (id=%s)" % (client.name, cid))
                    for a, c in sorted(removed, key=lambda x: x[1]):
                        self.stdout.write("      - %r   [%s]" % (a, c))

        self.stdout.write(
            "\nOrg %d (%s): %d aliases below %.2f to remove across %d clients."
            % (org.pk, org.name, total_removed, floor, len(to_write))
        )

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written."))
            return

        with transaction.atomic():
            for cid, new_list in to_write.items():
                c = by_client[cid]
                c.aliases = new_list
                c.save(update_fields=["aliases"])

        self.stdout.write(self.style.SUCCESS(
            "Removed %d low-confidence aliases for org %d." % (total_removed, org.pk)
        ))
