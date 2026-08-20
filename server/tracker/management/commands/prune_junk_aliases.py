"""
Management command: prune_junk_aliases

Targeted cleanup of specific known-bad aliases that slipped in before the
ampersand / common-word guards were added to alias_derivation.py:

  * Glued ampersand tokens: "LandS", "BandS", "SandA", "RandG", "TandS", etc.
    (from the old "&"->"and" no-space replacement)
  * Bare common-word tokens that fuzzy-collide with English: "LandS",
    "Lands", "Works", "Place", "Group", "Service(s)", "Solutions", "Systems"
    when stored as a STANDALONE alias (not part of a multi-word alias).

These caused real false positives at TL Wall (IRS page + news headline both
matched "LandS LLC"). The deriver no longer produces them, but already-applied
data must be cleaned.

    # Preview
    python manage.py prune_junk_aliases --org-id 21 --dry-run

    # Apply
    python manage.py prune_junk_aliases --org-id 21
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Bare standalone tokens that should never be an alias on their own.
# Matched case-insensitively against the WHOLE alias (single-token only).
JUNK_STANDALONE = {
    "lands", "land", "works", "place", "home", "group",
    "service", "services", "solutions", "systems",

    # Corporate-structure words. These dominate legal client names — "Ridgeline
    # Holdings LLC", "Meyer & Partners", "Smith Family Trust" — and alias
    # derivation happily emits the bare token, which then matches every document
    # mentioning it. That is the ATU-alias shape: one over-broad alias took 204
    # billable minutes across seven users in a single day.
    "holding", "holdings", "partner", "partners", "associate", "associates",
    "company", "companies", "enterprise", "enterprises", "industries",
    "properties", "property", "ventures", "venture", "capital", "management",
    "consulting", "corporation", "incorporated", "international",

    # Estate and trust vocabulary. Ruinous at a firm that does estate work: a
    # standalone "Trust" or "Estate" alias matches nearly every document they
    # touch, and the mis-attribution lands on a client's bill.
    "trust", "trusts", "estate", "estates", "family", "foundation",
}

# Regex catching glued ampersand artifacts: a short initial-pair glued with
# "and", e.g. "LandS", "BandS", "SandA", "RandG", "TandS". Pattern: 1 letter +
# "and" + 1 letter, as a standalone token.
GLUED_AND = re.compile(r"^[A-Za-z]and[A-Za-z]$")


class Command(BaseCommand):
    help = "Remove known-junk ampersand/common-word standalone aliases."

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
        total_removed = 0
        to_write = {}

        for client in clients:
            current = [a for a in (client.aliases or []) if isinstance(a, str)]
            if not current:
                continue
            kept, removed = [], []
            for a in current:
                stripped = a.strip()
                is_single = len(stripped.split()) == 1
                low = stripped.lower()
                if is_single and (low in JUNK_STANDALONE or GLUED_AND.match(stripped)):
                    removed.append(a)
                else:
                    kept.append(a)
            if removed:
                total_removed += len(removed)
                to_write[client.pk] = (client, kept, removed)

        if not to_write:
            self.stdout.write(self.style.SUCCESS(
                f"Org {org.pk} ({org.name}): no junk aliases found. Clean."
            ))
            return

        self.stdout.write(
            f"Org {org.pk} ({org.name}): {total_removed} junk aliases to remove "
            f"across {len(to_write)} clients."
        )
        for cid, (client, kept, removed) in sorted(
            to_write.items(), key=lambda kv: kv[1][0].name.lower()
        ):
            self.stdout.write("\n  %s  (id=%s)" % (client.name, cid))
            for a in removed:
                self.stdout.write("      - %r" % a)

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing written."))
            return

        with transaction.atomic():
            for cid, (client, kept, removed) in to_write.items():
                client.aliases = kept
                client.save(update_fields=["aliases"])

        self.stdout.write(self.style.SUCCESS(
            "\nRemoved %d junk aliases for org %d." % (total_removed, org.pk)
        ))
