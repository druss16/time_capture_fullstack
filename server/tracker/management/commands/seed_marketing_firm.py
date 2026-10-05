"""
seed_marketing_firm — a fictional agency for clicking through Client → Project.

LOCAL DATABASES ONLY. The command refuses to run unless the database host is
a local socket or localhost, because the default settings (and the `time_api`
container) point at production Neon.

    python manage.py seed_marketing_firm            # seed + run the attribution sweep
    python manage.py seed_marketing_firm --reset    # wipe and re-seed
    python manage.py seed_marketing_firm --no-sweep # leave every block unfiled
    python manage.py seed_marketing_firm --teardown

Creates two firms, so the gate can be checked from both sides:

  Brightline Creative (TEST) — industry 'marketing', keeps its own projects
    Harbor Point Marina    Summer Boat Show, Website Refresh, (archived) Spring Open House
    Copperline Brewing     Fall Seasonal Launch, Taproom Signage, Social Retainer
    Maple Ridge Dental     Patient Newsletter              <- sole project fallback
    Northstar Credit Union (none)                          <- "No project yet", inline create

  Ledgerline CPA (TEST) — industry 'cpa', has legacy "(General)" Project rows
    that must NOT surface: no Projects column, no project grouping.

Blocks cover the last five weekdays. Each day has work the sweep should file
by project name, work it should file by sole project, work it must leave
alone (an unnamed Copperline file — three projects, so it abstains), one block
already filed by hand, and Internal time (never in the project queue).

Logins (test only, local only):
  tt_test_owner     owner of Brightline      — Daily Review, Settings → Clients, CSV import
  tt_test_designer  member of Brightline     — import must be refused (admin-only)
  tt_test_mavops    is_staff, owner of Ledgerline — MavOps Admin, and the CPA side
Password for all three: brightline-local-test
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

User = get_user_model()

AGENCY_SLUG = "brightline-mktg-test"
CPA_SLUG = "ledgerline-cpa-test"
USER_PREFIX = "tt_test_"
PASSWORD = "brightline-local-test"
TZ = ZoneInfo("America/New_York")

AGENCY_CLIENTS = {
    "Harbor Point Marina": ["Summer Boat Show", "Website Refresh"],
    "Copperline Brewing": ["Fall Seasonal Launch", "Taproom Signage", "Social Retainer"],
    "Maple Ridge Dental": ["Patient Newsletter"],
    "Northstar Credit Union": [],
    # Their QuickBooks Time projects are billing buckets; Dropbox holds deliverables.
    "Easterns Automotive Group": ["Easterns KONETIQ Campaigns", "Easterns CDJR Social Ads"],
}
ARCHIVED = [("Harbor Point Marina", "Spring Open House")]

# One working day: (start hh:mm, minutes, client, app, window title, file path, expectation)
# The expectation is only printed, so whoever clicks through knows what each row is for.
DAY_PLAN = [
    ("09:00", 50, "Harbor Point Marina", "Adobe Photoshop",
     "Summer Boat Show poster v3.psd @ 66% (RGB/8) - Photoshop",
     "/Users/designer/Dropbox/Clients/Harbor Point/Summer Boat Show poster v3.psd", "by name"),
    ("10:00", 35, "Harbor Point Marina", "Google Chrome",
     "Website Refresh – sitemap draft - Google Docs - Google Chrome", "", "by name"),
    ("10:45", 40, "Copperline Brewing", "Adobe Illustrator",
     "Taproom Signage menu board.ai @ 50% (CMYK/Preview)",
     "/Users/designer/Dropbox/Clients/Copperline/Taproom Signage menu board.ai", "by name"),
    ("11:30", 25, "Copperline Brewing", "Adobe Illustrator",
     "untitled-3.ai @ 100% (RGB/Preview)", "", "ABSTAIN: 3 projects, no name"),
    ("13:00", 45, "Maple Ridge Dental", "Microsoft Word",
     "Q4 mailer draft.docx - Word",
     "/Users/designer/Documents/Maple Ridge/Q4 mailer draft.docx", "sole project"),
    ("14:00", 30, "Northstar Credit Union", "Google Chrome",
     "Northstar brand guidelines.pdf - Google Chrome", "", "no projects: stays unfiled"),
    ("14:45", 20, "Copperline Brewing", "Slack",
     "copperline-social | Brightline - Slack", "", "FILED BY HAND to Social Retainer"),
    ("15:15", 30, "Internal", "Microsoft Outlook",
     "Inbox - Outlook", "", "Internal: never in the project queue"),
]

# A real agency's Dropbox layout (More Than Cars): CODE_Name client folder, then
# CODE_date_ShortName_Deliverable. The sweep finds the CLIENT from these names
# with no setup; the project is one pick per deliverable folder, for everyone.
DROPBOX_TAIL = "Client-Work_2026/0074_Easterns-Auto-Group"
DELIVERABLES = [
    ("0074_2026-08_Easterns-Auto_Konetiq-Launch-Ads", ["hero_1080x1080.psd", "Exports/banner_300x250.png"]),
    ("0074_2026-09_Easterns-Auto_General-Collision-Center-Flyer-CDJR", ["flyer_front.indd", "Links/photo_bay3.psd"]),
]
HOME = {"owner": "/Users/olivia/Dropbox", "designer": "C:/Users/dana/Dropbox (Brightline)"}

CPA_CLIENTS = ["Ridgeview Hardware LLC", "Oakmont Family Trust"]


class Command(BaseCommand):
    help = "Seed a fictional marketing agency (plus a CPA control firm) for Client → Project testing. Local DB only."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Tear down, then seed again.")
        parser.add_argument("--teardown", action="store_true", help="Remove the test firms and users, then exit.")
        parser.add_argument("--no-sweep", action="store_true",
                            help="Skip the attribution sweep, so every project starts empty.")

    def handle(self, *args, **opts):
        self._refuse_remote_db()
        if opts["teardown"] or opts["reset"]:
            self.teardown()
            if opts["teardown"]:
                return
        self.seed(sweep=not opts["no_sweep"])

    # ── safety ────────────────────────────────────────────────────────────
    def _refuse_remote_db(self):
        host = (connection.settings_dict.get("HOST") or "").strip()
        if host and not (host.startswith("/") or host in {"localhost", "127.0.0.1", "::1"}):
            raise CommandError(
                f"Refusing to seed: database host is {host!r}. "
                "This command only runs against a local throwaway Postgres.")

    # ── teardown ──────────────────────────────────────────────────────────
    def teardown(self):
        from tracker.models import Organization
        with transaction.atomic():
            n_users, _ = User.objects.filter(username__startswith=USER_PREFIX).delete()
            n_orgs, _ = Organization.objects.filter(slug__in=[AGENCY_SLUG, CPA_SLUG]).delete()
        self.stdout.write(self.style.WARNING(f"Removed test firms and users ({n_orgs + n_users} rows incl. cascades)."))

    # ── seed ──────────────────────────────────────────────────────────────
    def seed(self, sweep: bool):
        from tracker.models import Organization
        if Organization.objects.filter(slug__in=[AGENCY_SLUG, CPA_SLUG]).exists():
            raise CommandError("Test firms already exist. Use --reset to re-seed or --teardown to remove.")

        with transaction.atomic():
            agency = Organization.objects.create(
                name="Brightline Creative (TEST)", slug=AGENCY_SLUG, industry_type="marketing")
            cpa = Organization.objects.create(
                name="Ledgerline CPA (TEST)", slug=CPA_SLUG, industry_type="cpa")

            owner = self._user("owner", "Olivia", "Owner", agency, "owner")
            designer = self._user("designer", "Dana", "Designer", agency, "member")
            mavops = self._user("mavops", "Max", "Ops", cpa, "owner", is_staff=True)

            clients, projects = self._agency_clients(agency)
            days = _last_weekdays(5)
            expectations = []
            for day in days:
                for person in (owner, designer):
                    expectations += self._agency_day(agency, person, day, clients, projects)
            self._cpa_firm(cpa, mavops, days)

        stats = None
        if sweep:
            from tracker.services.matter_attribution import attribute_matters_for_org
            stats = attribute_matters_for_org(agency, days=14)

        self._report(agency, cpa, days, expectations, stats)

    def _user(self, key, first, last, org, role, is_staff=False):
        from tracker.models import OrganizationMembership
        u = User.objects.create_user(
            username=f"{USER_PREFIX}{key}", email=f"{key}@{org.slug}.test",
            first_name=first, last_name=last, password=PASSWORD)
        if is_staff:
            u.is_staff = True
            u.save(update_fields=["is_staff"])
        OrganizationMembership.objects.create(user=u, organization=org, role=role)
        return u

    def _agency_clients(self, org):
        from tracker.models import Client, Project
        clients, projects = {}, {}
        for name, project_names in AGENCY_CLIENTS.items():
            c = Client.objects.create(org=org, name=name)
            clients[name] = c
            for p in project_names:
                projects[(name, p)] = Project.objects.create(org=org, client=c, name=p)
        for name, p in ARCHIVED:
            Project.objects.create(org=org, client=clients[name], name=p, is_active=False)
        # Every org gets its own Internal client on creation; reuse it.
        clients["Internal"] = _internal_client(org)
        return clients, projects

    def _agency_day(self, org, user, day, clients, projects):
        out = []
        for hhmm, minutes, client_name, app, title, path, expect in DAY_PLAN:
            project = projects[("Copperline Brewing", "Social Retainer")] if expect.startswith("FILED BY HAND") else None
            _block(org, user, day, hhmm, minutes, clients[client_name], app, title, path,
                   billable=client_name != "Internal", project=project)
            out.append((user.username, day, hhmm, client_name, title, expect))
        # Easterns work arrives with NO client: only the folder names say whose it is.
        root = HOME[user.username.removeprefix(USER_PREFIX)]
        for i, (folder, files) in enumerate(DELIVERABLES):
            for j, name in enumerate(files):
                path = f"{root}/{DROPBOX_TAIL}/{folder}/{name}"
                _block(org, user, day, f"{16 + i}:{15 * j:02d}", 15, None, "Adobe Photoshop",
                       f"{name.rsplit('/', 1)[-1]} @ 50% (RGB/8)", path, billable=True)
        return out

    def _cpa_firm(self, org, user, days):
        from tracker.models import Client, Project
        for i, name in enumerate(CPA_CLIENTS):
            c = Client.objects.create(org=org, name=name)
            # The legacy auto-created rows a CPA firm really has. They must stay invisible.
            Project.objects.create(org=org, client=c, name="(General)")
            for day in days:
                _block(org, user, day, f"{9 + 2 * i:02d}:00", 60, c, "Microsoft Excel",
                       f"{name} 2026 workpapers.xlsx - Excel", "", billable=True)

    def _report(self, agency, cpa, days, expectations, stats):
        w = self.stdout.write
        w(self.style.SUCCESS(f"\nSeeded {agency.name} (org {agency.id}, marketing) and {cpa.name} (org {cpa.id}, cpa)."))
        w(f"Days: {days[0]} → {days[-1]} (weekdays, America/New_York)")
        if stats is not None:
            w(f"Attribution sweep: {stats}")
        else:
            w("Attribution sweep skipped (--no-sweep): every agency block starts with no project.")
        w("\nWhat each daily row is for (same plan every day, for both agency users):")
        for _u, _d, hhmm, client, title, expect in expectations[:len(DAY_PLAN)]:
            w(f"  {hhmm}  {client:<24} {expect:<30} {title[:60]}")
        w("  16:00+ (no client)              Easterns Dropbox files: sweep names the client; "
          "pick a project once per deliverable folder")
        w(f"\nLogins (password in this command's docstring): {USER_PREFIX}owner, "
          f"{USER_PREFIX}designer, {USER_PREFIX}mavops (staff)")


def _internal_client(org):
    from tracker.models import Client
    return (Client.objects.filter(org=org, code="INTERNAL").first()
            or Client.objects.filter(org=org, name__iexact="Internal").first()
            or Client.objects.create(org=org, name="Internal"))


def _block(org, user, day, hhmm, minutes, client, app, title, path, billable, project=None):
    from tracker.models import Block
    h, m = (int(x) for x in hhmm.split(":"))
    start = datetime.combine(day, time(h, m), tzinfo=TZ)
    return Block.objects.create(
        org=org, user=user, hostname="brightline-mac", device_id=f"seed-{user.id}",
        start=start, end=start + timedelta(minutes=minutes), minutes=minutes, day=day,
        app_name=app, window_title=title, title=title, file_path=path,
        classification_state="committed", is_categorized=True, is_billable=billable,
        client=client, project=project, category_hours={"Design": round(minutes / 60, 2)},
    )


def _last_weekdays(n: int) -> list[date]:
    d = datetime.now(TZ).date()
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)
