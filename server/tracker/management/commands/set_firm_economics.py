"""
Load a firm's real labor cost (and optionally a flat bill rate) from a CSV.

The Economics tab can do this by hand, but a firm's numbers arrive as a
spreadsheet and typing a dozen salaries into a web form is how digits get
transposed. This takes the file, shows you the resolved roster, and refuses the
half-done state that actually hurts: real wages for some people sitting beside
the seeded demo tier rate for the rest, which silently produces margins that are
part fact and part fiction.

CSV columns (case-insensitive): email OR username, cost_rate, and optional
bill_rate. Each cost_rate becomes an effective-dated EmployeeCostRate override,
which outranks the member's cost tier everywhere (analytics_v2/cost_rates.py).

Usage:
  # Dry run (default) — resolves every row, reports who is uncovered
  python manage.py set_firm_economics --org-id 21 --csv /tmp/costs.csv

  # Apply, and set one flat bill rate for the whole firm
  python manage.py set_firm_economics --org-id 21 --csv /tmp/costs.csv \
      --bill-rate 75 --apply

  # Only when the firm genuinely has no number for someone
  python manage.py set_firm_economics --org-id 21 --csv /tmp/costs.csv \
      --allow-partial --apply
"""

import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tracker.models import (
    CostTier, EmployeeCostRate, Organization, OrganizationMembership,
)


class Command(BaseCommand):
    help = "Load real per-person labor cost (and an optional flat bill rate) from a CSV."

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True)
        parser.add_argument("--csv", required=True, help="Path to the cost CSV")
        parser.add_argument(
            "--bill-rate",
            help="Set ONE flat bill rate firm-wide: org default + every cost tier. "
                 "Omit to leave bill rates alone.",
        )
        parser.add_argument(
            "--effective-date",
            help="Effective date for the cost rows (YYYY-MM-DD). Default: today.",
        )
        parser.add_argument(
            "--allow-partial",
            action="store_true",
            help="Proceed even when some members have no cost_rate. They keep "
                 "falling back to their tier rate — check that tier holds a real "
                 "number, not a seeded one, before you use this.",
        )
        parser.add_argument("--apply", action="store_true", help="Write. Default is dry run.")

    def handle(self, *args, **opts):
        try:
            org = Organization.objects.get(id=opts["org_id"])
        except Organization.DoesNotExist:
            raise CommandError(f"No organization with id {opts['org_id']}")

        today = timezone.now().date()
        if opts.get("effective_date"):
            from datetime import date
            try:
                today = date.fromisoformat(opts["effective_date"])
            except ValueError:
                raise CommandError("--effective-date must be YYYY-MM-DD")

        members = list(
            OrganizationMembership.objects
            .filter(organization=org)
            .select_related("user", "cost_tier")
        )
        by_email = {m.user.email.lower(): m for m in members if m.user.email}
        by_username = {m.user.username.lower(): m for m in members}

        # ── Resolve the CSV against the roster ────────────────────────────────
        resolved, unmatched = {}, []
        with open(opts["csv"], newline="") as fh:
            for row in csv.DictReader(fh):
                keys = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                ident = keys.get("email") or keys.get("username") or ""
                rate = _dec(keys.get("cost_rate"))
                if not ident:
                    continue
                m = by_email.get(ident.lower()) or by_username.get(ident.lower())
                if not m or rate is None:
                    unmatched.append((ident, keys.get("cost_rate", "")))
                    continue
                resolved[m.user_id] = (m, rate)

        covered = set(resolved)
        uncovered = [m for m in members if m.user_id not in covered]

        # ── Report ────────────────────────────────────────────────────────────
        self.stdout.write(f"\n{org.name} (id={org.id}) — cost effective {today}\n")
        self.stdout.write(f"{'person':22} {'role':9} {'tier':10} {'was':>10} {'becomes':>10}")
        self.stdout.write("-" * 66)
        for m, rate in sorted(resolved.values(), key=lambda x: x[0].user.username):
            prev = EmployeeCostRate.get_rate_for_user(m.user, org, today)
            was = f"${prev}" if prev is not None else (
                f"${m.cost_tier.cost_rate} (tier)" if m.cost_tier else "org default"
            )
            name = f"{m.user.first_name} {m.user.last_name}".strip() or m.user.username
            self.stdout.write(
                f"{name[:22]:22} {m.role:9} {(m.cost_tier.label if m.cost_tier else '—'):10} "
                f"{was:>10} {('$' + str(rate)):>10}"
            )

        if unmatched:
            self.stdout.write(self.style.WARNING(f"\n{len(unmatched)} CSV row(s) matched nobody:"))
            for ident, raw in unmatched:
                self.stdout.write(f"  {ident}  (cost_rate={raw!r})")

        if uncovered:
            self.stdout.write(self.style.WARNING(
                f"\n{len(uncovered)} member(s) have NO cost number in this file — they "
                f"keep falling back to their tier rate:"
            ))
            for m in uncovered:
                name = f"{m.user.first_name} {m.user.last_name}".strip() or m.user.username
                fallback = (f"${m.cost_tier.cost_rate} from tier '{m.cost_tier.label}'"
                            if m.cost_tier else f"${org.cost_rate_default} org default")
                self.stdout.write(f"  {name} ({m.role}) → {fallback}")

        if uncovered and not opts["allow_partial"]:
            raise CommandError(
                "Refusing to write a mixed roster: the people above would carry a "
                "tier rate next to real wages, and every margin the firm reads "
                "would be part fact and part placeholder. Supply their numbers, "
                "or pass --allow-partial once you've checked their tier rates are real."
            )

        bill = _dec(opts["bill_rate"]) if opts.get("bill_rate") else None
        if opts.get("bill_rate") and bill is None:
            raise CommandError(f"--bill-rate {opts['bill_rate']!r} is not a positive number")
        if bill is not None:
            tiers = CostTier.objects.filter(organization=org)
            self.stdout.write(
                f"\nBill rate → ${bill} flat: org default ${org.billing_rate_default} → ${bill}, "
                f"and {tiers.count()} tier bill rate(s) "
                f"({', '.join(f'{t.label} ${t.bill_rate}' for t in tiers if t.bill_rate is not None) or 'none set'}) "
                f"→ ${bill}."
            )
            self.stdout.write(
                "  NOTE: blocks are stamped with their rate at capture, so this "
                "applies to NEW time only. Existing blocks keep the rate they were "
                "captured at."
            )

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("\nDRY RUN — nothing written. Re-run with --apply.\n"))
            return

        # ── Write ─────────────────────────────────────────────────────────────
        with transaction.atomic():
            for m, rate in resolved.values():
                EmployeeCostRate.objects.update_or_create(
                    organization=org, user=m.user, effective_date=today,
                    defaults={"cost_rate": rate},
                )
            if bill is not None:
                org.billing_rate_default = bill
                org.save(update_fields=["billing_rate_default"])
                CostTier.objects.filter(organization=org).update(bill_rate=bill)

        self.stdout.write(self.style.SUCCESS(
            f"\nApplied: {len(resolved)} cost override(s)"
            + (f", bill rate ${bill} firm-wide" if bill is not None else "")
            + ".\n"
        ))


def _dec(v):
    if v in (None, ""):
        return None
    s = str(v).strip().replace("$", "").replace(",", "")
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return d if d > 0 else None
