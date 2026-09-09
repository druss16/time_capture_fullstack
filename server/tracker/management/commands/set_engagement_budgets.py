# tracker/management/commands/set_engagement_budgets.py
"""
Set engagement budgets from the firm's fee schedule, via CSV.

WHY THIS EXISTS
---------------
`derive_engagements` budgets a job from the PRIOR PERIOD'S ACTUAL HOURS. That is
the right instinct and the wrong input while capture is incomplete: org 21's
agent sees roughly 42% of the working week, so a month where we recorded 0.5 h
becomes next month's 0.5 h budget, and the month after reads 1273% burn. The
firm didn't overrun anything — the baseline was 42% of reality. Deriving a
budget from the same under-captured data you're then measuring against is
circular, and no floor value fixes that.

A fee is not circular. A $450/month bookkeeping engagement at a $75 rate is six
hours of budget whether or not the agent was running. So this reads the numbers
the firm already has on paper and writes them in as `manual`, which
`derive_budget` refuses to overwrite — set once, and the automatic ladder leaves
them alone forever after.

CSV FORMAT
----------
    client,engagement_type,budget_hours,monthly_fee

  client           name or code; matched case-insensitively, then by alias
  engagement_type  bookkeeping | payroll | tax_return
  budget_hours     hours per period — use this when you know the hours
  monthly_fee      OR the fee; hours = fee / the org's default bill rate

Give exactly one of budget_hours or monthly_fee. Blank rows and a leading '#'
are ignored, so the file can carry comments.

    python manage.py set_engagement_budgets --org 21 --csv fees.csv
    python manage.py set_engagement_budgets --org 21 --csv fees.csv --apply
    python manage.py set_engagement_budgets --org 21 --template > fees.csv

Dry run by default: it prints every engagement it would touch and writes nothing
without --apply.
"""
from __future__ import annotations

import csv
import sys
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"
BOLD = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"

VALID_TYPES = {"bookkeeping", "payroll", "tax_return"}


class Command(BaseCommand):
    help = "Set engagement budgets from a fee-schedule CSV (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--org", type=int, required=False,
                            help="Org ID (required unless --template)")
        parser.add_argument("--csv", default=None, help="Path to the fee CSV")
        parser.add_argument("--template", action="store_true",
                            help="Print a starter CSV of this org's clients and exit")
        parser.add_argument("--open-only", action="store_true", default=True,
                            help="Only budget engagements still open (default)")
        parser.add_argument("--all-periods", action="store_true",
                            help="Also rewrite budgets on closed periods")
        parser.add_argument("--apply", action="store_true",
                            help="Write. Without it nothing changes.")

    # ── entry ───────────────────────────────────────────────────────────────
    def handle(self, *args, **opts):
        from tracker.models import Organization

        if not opts["org"]:
            raise CommandError("--org is required")
        org = Organization.objects.filter(id=opts["org"]).first()
        if not org:
            raise CommandError(f"Org {opts['org']} not found")

        if opts["template"]:
            self._print_template(org)
            return

        if not opts["csv"]:
            raise CommandError("--csv is required (or use --template to start one)")

        rows = self._read_csv(opts["csv"])
        self._apply_rows(org, rows, opts)

    # ── template ────────────────────────────────────────────────────────────
    def _print_template(self, org):
        """Emit a starter file listing the clients that actually have engagements,
        so the firm fills in fees rather than inventing the client list."""
        from tracker.models import Engagement

        pairs = (Engagement.objects.filter(org=org, status="open")
                 .exclude(client=None)
                 .values_list("client__name", "engagement_type")
                 .distinct().order_by("client__name", "engagement_type"))
        w = csv.writer(sys.stdout)
        w.writerow(["client", "engagement_type", "budget_hours", "monthly_fee"])
        for name, etype in pairs:
            w.writerow([name, etype, "", ""])

    # ── read ────────────────────────────────────────────────────────────────
    def _read_csv(self, path) -> list[dict]:
        try:
            with open(path, newline="", encoding="utf-8-sig") as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            raise CommandError(f"No such file: {path}")

        # Strip leading comment/blank lines BEFORE DictReader, or it takes the
        # first '#' line as the header and every row comes back empty.
        offset = 0
        while offset < len(lines) and (not lines[offset].strip()
                                       or lines[offset].lstrip().startswith("#")):
            offset += 1
        if offset >= len(lines):
            raise CommandError(f"{path} has no header row")

        rows = []
        try:
            for i, r in enumerate(csv.DictReader(lines[offset:]), start=offset + 2):
                first = (r.get("client") or "").strip()
                if not first or first.startswith("#"):
                    continue
                r["_line"] = i
                rows.append(r)
            return rows
        except csv.Error as exc:
            raise CommandError(f"Could not read {path}: {exc}")

    # ── resolve + write ─────────────────────────────────────────────────────
    def _resolve_client(self, org, raw: str):
        from tracker.models import Client
        name = (raw or "").strip()
        c = (Client.objects.filter(org=org, name__iexact=name).first()
             or Client.objects.filter(org=org, code__iexact=name).first())
        if c:
            return c
        # aliases are a JSON list on the client; fall back to a contains match
        for cand in Client.objects.filter(org=org).only("id", "name", "aliases"):
            for a in (cand.aliases or []):
                if str(a).strip().lower() == name.lower():
                    return cand
        return None

    def _apply_rows(self, org, rows, opts):
        from tracker.models import Engagement

        rate = float(getattr(org, "billing_rate_default", 0) or 0)
        mode = f"{RED}APPLY{RESET}" if opts["apply"] else f"{CYAN}DRY RUN{RESET}"
        print(f"  {BOLD}{org.name}{RESET} (id={org.id})   {len(rows)} CSV rows   "
              f"bill rate ${rate:,.2f}   {mode}")
        if not opts["apply"]:
            print(f"  {DIM}nothing will be written — re-run with --apply{RESET}")
        print()

        touched = skipped = 0
        problems: list[str] = []

        for r in rows:
            line = r["_line"]
            etype = (r.get("engagement_type") or "").strip().lower()
            if etype not in VALID_TYPES:
                problems.append(f"line {line}: engagement_type {etype!r} "
                                f"not one of {sorted(VALID_TYPES)}")
                continue

            client = self._resolve_client(org, r.get("client"))
            if not client:
                problems.append(f"line {line}: no client matches {r.get('client')!r}")
                continue

            hours = self._hours_for(r, rate, line, problems)
            if hours is None:
                continue

            qs = Engagement.objects.filter(
                org=org, client=client, engagement_type=etype,
            )
            if not opts["all_periods"]:
                qs = qs.filter(status="open")
            engagements = list(qs.order_by("period_start"))
            if not engagements:
                problems.append(f"line {line}: {client.name} has no "
                                f"{'open ' if not opts['all_periods'] else ''}"
                                f"{etype} engagements")
                continue

            for e in engagements:
                before = float(e.budget_hours) if e.budget_hours else None
                if before is not None and abs(before - hours) < 0.01 and e.budget_source == "manual":
                    skipped += 1
                    continue
                print(f"  {client.name[:30]:32} {etype:12} {e.period_label:9} "
                      f"{(f'{before:.1f}h' if before is not None else '—'):>7} → "
                      f"{hours:5.1f}h   {DIM}was {e.budget_source or 'unset'}{RESET}")
                touched += 1
                if opts["apply"]:
                    e.budget_hours = Decimal(str(round(hours, 2)))
                    e.budget_amount = (Decimal(str(round(hours * rate, 2)))
                                       if rate else None)
                    e.budget_source = "manual"   # derive_budget will not overwrite
                    e.budget_basis = f"fee schedule ({r.get('monthly_fee') or 'hours'})"
                    e.budget_set_at = timezone.now()
                    e.save(update_fields=[
                        "budget_hours", "budget_amount", "budget_source",
                        "budget_basis", "budget_set_at", "updated_at",
                    ])

        print()
        print(f"  {BOLD}{touched} engagement(s) {'updated' if opts['apply'] else 'would change'}{RESET}"
              f", {skipped} already correct")
        if problems:
            print(f"\n  {RED}{len(problems)} row(s) could not be applied:{RESET}")
            for p in problems[:40]:
                print(f"    {p}")
            if len(problems) > 40:
                print(f"    … and {len(problems) - 40} more")
        if not opts["apply"]:
            print(f"\n  {CYAN}Dry run — nothing written.{RESET}")
        else:
            print(f"\n  {GREEN}Written as budget_source='manual'{RESET} — "
                  f"derive_engagements will not overwrite these.")

    def _hours_for(self, r, rate, line, problems) -> float | None:
        raw_h = (r.get("budget_hours") or "").strip()
        raw_f = (r.get("monthly_fee") or "").strip().replace("$", "").replace(",", "")
        if raw_h and raw_f:
            problems.append(f"line {line}: give budget_hours OR monthly_fee, not both")
            return None
        try:
            if raw_h:
                return float(Decimal(raw_h))
            if raw_f:
                if rate <= 0:
                    problems.append(f"line {line}: monthly_fee needs a firm bill rate "
                                    f"(Settings → Economics → Firm defaults)")
                    return None
                return float(Decimal(raw_f)) / rate
        except (InvalidOperation, ValueError):
            problems.append(f"line {line}: could not read a number from "
                            f"{raw_h or raw_f!r}")
            return None
        problems.append(f"line {line}: needs budget_hours or monthly_fee")
        return None
