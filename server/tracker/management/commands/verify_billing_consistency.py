# tracker/management/commands/verify_billing_consistency.py
"""
Assert Daily Review (today_time) and Reports (reports_summary) report the SAME
Billable / Non-billable / Needs-Review / Total for every user on a day.

Both now compute those four numbers through the one source of truth,
tracker.services.billing_totals, so this is the regression guard that they stay
in agreement on real data. Run it after any change to the billing math, the
today_time view, or the reports helpers.

Usage
-----
# Today, first org found:
python manage.py verify_billing_consistency

# A specific org + day:
python manage.py verify_billing_consistency --org tl-wall --date 2026-07-28

# A back-range of days ending on --date:
python manage.py verify_billing_consistency --date 2026-07-28 --days 7

Exit status is non-zero if any user/day disagrees, so it can gate a deploy.
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_date

from rest_framework.test import APIRequestFactory, force_authenticate

User = get_user_model()

GREEN = "\033[92m"; RED = "\033[91m"; CYAN = "\033[96m"; BOLD = "\033[1m"; RESET = "\033[0m"


def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def info(msg): print(f"  {CYAN}→{RESET}  {msg}")


class Command(BaseCommand):
    help = "Verify today_time and reports_summary agree on billable/non-bill/review/total."

    def add_arguments(self, parser):
        parser.add_argument("--org", default=None, help="Org slug or id (default: first org found)")
        parser.add_argument("--date", default=None, help="Anchor day YYYY-MM-DD (default: today)")
        parser.add_argument("--days", type=int, default=1, help="Number of days back from --date to check")

    def handle(self, *args, **opts):
        from tracker.models import Organization, OrganizationMembership, Block

        # ── Resolve org ──────────────────────────────────────────────────────
        org = None
        if opts["org"]:
            q = opts["org"]
            org = (Organization.objects.filter(slug=q).first()
                   or (Organization.objects.filter(id=q).first() if str(q).isdigit() else None))
            if not org:
                raise CommandError(f"Org not found: {q}")
        else:
            org = Organization.objects.first()
            if not org:
                raise CommandError("No organizations exist.")

        anchor = parse_date(opts["date"]) if opts["date"] else None
        if opts["date"] and not anchor:
            raise CommandError(f"Bad --date: {opts['date']}")
        if not anchor:
            from django.utils import timezone
            anchor = timezone.localdate()

        days = max(1, opts["days"])
        target_dates = [anchor - timedelta(days=i) for i in range(days)]

        info(f"Org: {org.name} (id={org.id})   days: {target_dates[-1]} → {target_dates[0]}")

        user_ids = list(
            OrganizationMembership.objects.filter(organization=org)
            .values_list("user_id", flat=True)
        )
        factory = APIRequestFactory()

        checked = passed = failed = 0
        FIELDS = ("billable", "non_billable", "review", "total")

        for d in target_dates:
            for uid in user_ids:
                # Skip users with no blocks that day — both sides are trivially 0.
                if not Block.objects.filter(user_id=uid, day=d).exists():
                    continue
                try:
                    user = User.objects.get(id=uid)
                except User.DoesNotExist:
                    continue

                tt = self._today_time(factory, user, d)
                rp = self._reports_row(factory, user, uid, d)

                checked += 1
                diffs = [f for f in FIELDS if abs(tt[f] - rp[f]) > 0.01]
                label = f"{d} {user.get_full_name() or user.username} (id={uid})"
                if diffs:
                    failed += 1
                    fail(label)
                    for f in diffs:
                        print(f"        {f}: today_time={tt[f]}  reports={rp[f]}")
                else:
                    passed += 1
                    ok(f"{label}  bill={tt['billable']} nonbill={tt['non_billable']} "
                       f"review={tt['review']} total={tt['total']}")

        print()
        print(f"{BOLD}Checked {checked} user-days: "
              f"{GREEN}{passed} passed{RESET}, "
              f"{(RED if failed else GREEN)}{failed} failed{RESET}")
        if failed:
            raise CommandError(f"{failed} user-day(s) disagree between Daily Review and Reports.")

    # ── Endpoint callers (authenticate AS the user → self scope) ─────────────
    def _today_time(self, factory, user, d):
        from tracker import views
        req = factory.get(f"/api/today-time/?date={d.isoformat()}")
        force_authenticate(req, user=user)
        data = views.today_time(req).data
        return {
            "billable": data.get("billable_hours", 0),
            "non_billable": data.get("non_billable_hours", 0),
            "review": data.get("needs_review_hours", 0),
            "total": data.get("global_hours", 0),
        }

    def _reports_row(self, factory, user, uid, d):
        from tracker import views_reports
        req = factory.get(
            f"/api/reports/summary/?period=day&group_by=employee&date={d.isoformat()}"
        )
        force_authenticate(req, user=user)
        data = views_reports.reports_summary(req).data
        row = next((r for r in data.get("rows", []) if r.get("id") == uid), None)
        if not row:
            return {"billable": 0, "non_billable": 0, "review": 0, "total": 0}
        return {
            "billable": row.get("billable_hours", 0),
            "non_billable": row.get("non_billable_hours", 0),
            "review": row.get("uncategorized_hours", 0),
            "total": row.get("total_hours", 0),
        }
