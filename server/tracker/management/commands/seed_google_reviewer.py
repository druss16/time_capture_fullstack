"""
seed_google_reviewer — a demo agency + one login for Google's OAuth verification reviewer.

Google's Third-Party Data Safety team needs a working TimeTracker login with no
MFA or billing blockers, so they can sign in, connect Gmail and Google Calendar
themselves, and see where the data shows up. This runs in PRODUCTION (that is
where the reviewer signs in), so a remote database host must be named back to
the command with --confirm-host.

    python manage.py seed_google_reviewer --confirm-host <db host>
    python manage.py seed_google_reviewer --confirm-host <db host> --reset     # refresh the dates
    python manage.py seed_google_reviewer --confirm-host <db host> --teardown  # after approval

Creates "Brightline Creative (Demo)":
  * one owner login (generated password, printed once unless --password is given)
  * four clients with mapped email domains (Settings → Email domains), plus any
    --domain CLIENT=domain.com you add — map a domain you can send from, and mail
    between it and the reviewer's Gmail is attributed to that client
  * calendar_classification_enabled = True, so a meeting the reviewer holds with
    an outside attendee becomes proposed time in Needs You after the sync
  * confirmed client work for the last --days weekdays, so Daily Review is not
    empty, plus two pending rows a day (one a Gmail block): pending rows are the
    only Daily Review rows with the "Why?" panel, which is where Gmail headers
    from around that time appear

Pending rows are seeded on PAST days only: /daily runs the live classifier on
today's unfiled blocks. Dates are relative to the run, so --reset before
sending the reviewer the login if a few weeks have passed.

What the reviewer cannot get from seeding: Gmail matches for a @gmail.com
correspondent (public domains never identify a client, by design) and compose
time on new mail (that needs the desktop agent's Gmail browser time). The demo
video carries those.
"""
from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

User = get_user_model()

ORG_SLUG = "google-review-demo"
ORG_NAME = "Brightline Creative (Demo)"
DEFAULT_EMAIL = "google-reviewer@demo.timetracker.mavops.ai"
TZ = ZoneInfo("America/New_York")
HOSTNAME = "brightline-mac"

# Client → email domain. `.example` is reserved: these never receive real mail.
CLIENTS = {
    "Harbor Point Marina": "harborpointmarina.example",
    "Copperline Brewing": "copperlinebrewing.example",
    "Maple Ridge Dental": "mapleridgedental.example",
    "Northstar Credit Union": "northstarcu.example",
}

# (hh:mm, minutes, client or "Internal", app, window title, url, category)
CONFIRMED_DAY = [
    ("09:00", 30, "Harbor Point Marina", "Google Chrome",
     "Re: Summer Boat Show proofs - Gmail", "https://mail.google.com/mail/u/0/#inbox", "Client Communication"),
    ("09:30", 90, "Copperline Brewing", "Figma",
     "Copperline – Fall Seasonal Launch – Figma", "", "Design"),
    ("11:00", 45, "Maple Ridge Dental", "Google Chrome",
     "Patient Newsletter (October) - Google Docs", "https://docs.google.com/document/d/demo", "Copywriting"),
    ("11:45", 30, "Internal", "Slack",
     "#standup - Brightline Creative - Slack", "", "Internal"),
    ("13:00", 60, "Harbor Point Marina", "Adobe Photoshop",
     "boat-show-banner.psd @ 50% (RGB/8)", "", "Design"),
    ("14:00", 45, "Northstar Credit Union", "Google Chrome",
     "Northstar Q4 media plan - Google Sheets", "https://docs.google.com/spreadsheets/d/demo", "Strategy"),
]
# Unfiled rows the reviewer can open with "Why?". The Gmail one is where
# headers of their own mail from around that time show up.
PENDING_DAY = [
    ("15:00", 20, "Copperline Brewing", "Google Chrome",
     "Inbox (4) - Gmail", "https://mail.google.com/mail/u/0/#inbox", 0.55,
     "Gmail was open; the inbox title alone doesn't name a client."),
    ("16:00", 25, "Northstar Credit Union", "Google Chrome",
     "Brand guidelines - Google Drive", "https://drive.google.com/drive/folders/demo", 0.60,
     "Same app as the Northstar work just before it."),
]


class Command(BaseCommand):
    help = "Seed a demo agency and a login for Google's OAuth verification reviewer."

    def add_arguments(self, parser):
        parser.add_argument("--confirm-host", default="",
                            help="Required when the database is remote: the database host, typed back.")
        parser.add_argument("--email", default=DEFAULT_EMAIL, help="Login email for the reviewer account.")
        parser.add_argument("--password", default="",
                            help="Password for the reviewer account (default: generate one and print it).")
        parser.add_argument("--days", type=int, default=10, help="Weekdays of confirmed work to seed.")
        parser.add_argument("--domain", action="append", default=[], metavar="CLIENT=DOMAIN",
                            help="Extra client + mapped domain, e.g. 'Acme Co=acme.com'. Repeatable.")
        parser.add_argument("--reset", action="store_true", help="Tear down, then seed again.")
        parser.add_argument("--teardown", action="store_true", help="Remove the demo org and login, then exit.")

    def handle(self, *args, **opts):
        self._check_host(opts["confirm_host"])
        extra = _parse_domains(opts["domain"])
        if opts["teardown"] or opts["reset"]:
            self.teardown()
            if opts["teardown"]:
                return
        password = opts["password"] or secrets.token_urlsafe(12)
        org, user = self.seed(opts["email"], password, max(opts["days"], 1), extra)
        self._report(org, user, password, generated=not opts["password"])

    # ── safety ────────────────────────────────────────────────────────────
    def _check_host(self, confirm):
        host = (connection.settings_dict.get("HOST") or "").strip()
        local = not host or host.startswith("/") or host in {"localhost", "127.0.0.1", "::1"}
        if not local and confirm != host:
            raise CommandError(
                f"This writes to the database at {host!r}. "
                f"Re-run with --confirm-host {host} if that is intended.")

    # ── teardown ──────────────────────────────────────────────────────────
    def teardown(self):
        from tracker.models import Organization
        with transaction.atomic():
            n_users, _ = User.objects.filter(username__in=_reviewer_usernames()).delete()
            n_orgs, _ = Organization.all_objects.filter(slug=ORG_SLUG).delete()
        self.stdout.write(self.style.WARNING(
            f"Removed the demo org and reviewer login ({n_orgs + n_users} rows incl. cascades)."))

    # ── seed ──────────────────────────────────────────────────────────────
    def seed(self, email, password, days, extra):
        from tracker.models import Client, Organization, OrganizationMembership
        from tracker.services import mail_domains

        if Organization.all_objects.filter(slug=ORG_SLUG).exists() or User.objects.filter(username=email.lower()).exists():
            raise CommandError("The demo org or login already exists. Use --reset to re-seed or --teardown to remove.")

        with transaction.atomic():
            org = Organization.objects.create(
                name=ORG_NAME, slug=ORG_SLUG, industry_type="general", plan="executive",
                seat_count=5, onboarding_completed=True, is_demo=True,
                calendar_classification_enabled=True,
            )
            user = User.objects.create_user(
                username=email.lower(), email=email.lower(), password=password,
                first_name="Google", last_name="Reviewer",
            )
            OrganizationMembership.objects.create(user=user, organization=org, role="owner")

            clients = {"Internal": _internal_client(org)}
            for name, domain in {**CLIENTS, **extra}.items():
                clients[name] = Client.objects.get_or_create(org=org, name=name)[0]
                try:
                    mail_domains.create_mapping(org, domain, clients[name].id)
                except mail_domains.DomainError as e:
                    raise CommandError(f"{name}: {e}")

            now = timezone.now()
            for day in _last_weekdays(days):
                past = day < now.astimezone(TZ).date()
                for hhmm, minutes, client, app, title, url, category in CONFIRMED_DAY:
                    start = _at(day, hhmm)
                    if start + timedelta(minutes=minutes) <= now:
                        _confirmed(org, user, start, minutes, clients[client], app, title, url, category)
                if past:
                    for hhmm, minutes, client, app, title, url, conf, why in PENDING_DAY:
                        _pending(org, user, _at(day, hhmm), minutes, clients[client], app, title, url, conf, why)
        return org, user

    def _report(self, org, user, password, generated):
        from tracker.models import Block
        w = self.stdout.write
        blocks = Block.objects.filter(org=org)
        w(self.style.SUCCESS(f"\nSeeded {org.name} (org {org.id}, slug {org.slug})."))
        w(f"Blocks: {blocks.filter(classification_state='committed').count()} confirmed, "
          f"{blocks.filter(classification_state='proposed').count()} pending")
        w(f"Login: {user.email}")
        if generated:
            w(f"Password: {password}")
            w("This password is shown once. Put it in the reply to Google, nowhere else.")
        w("Sign in at https://timetracker.mavops.ai — Account → Connections to connect Gmail / Calendar.")


def _reviewer_usernames():
    # Usernames are the lowercased email (#635). Members of the demo org cover
    # a custom --email; the default covers a half-finished earlier run.
    from tracker.models import OrganizationMembership
    names = set(OrganizationMembership.objects.filter(organization__slug=ORG_SLUG)
                .values_list("user__username", flat=True))
    return names | {DEFAULT_EMAIL}


def _parse_domains(pairs):
    out = {}
    for pair in pairs:
        name, sep, domain = pair.partition("=")
        if not sep or not name.strip() or not domain.strip():
            raise CommandError(f"--domain expects CLIENT=domain.com, got {pair!r}")
        out[name.strip()] = domain.strip()
    return out


def _internal_client(org):
    from tracker.models import Client
    return (Client.objects.filter(org=org, code="INTERNAL").first()
            or Client.objects.filter(org=org, name__iexact="Internal").first()
            or Client.objects.create(org=org, name="Internal"))


def _at(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=TZ)


def _confirmed(org, user, start, minutes, client, app, title, url, category):
    from tracker.models import Block
    billable = client.name != "Internal"
    return Block.objects.create(
        org=org, user=user, hostname=HOSTNAME, device_id=f"seed-{user.id}",
        start=start, end=start + timedelta(minutes=minutes),
        app_name=app, window_title=title, title=title, url=url,
        classification_state="committed", state_changed_by="user", is_categorized=True,
        is_billable=billable, client=client,
        category_hours={category: round(minutes / 60, 2)},
    )


def _pending(org, user, start, minutes, client, app, title, url, confidence, reasoning):
    # 'proposed' with a proposed_client is a Needs You row, and the classify
    # signal and the 5-minute AI sweep only pick up 'captured' blocks.
    from tracker.models import Block
    return Block.objects.create(
        org=org, user=user, hostname=HOSTNAME, device_id=f"seed-{user.id}",
        start=start, end=start + timedelta(minutes=minutes),
        app_name=app, window_title=title, title=title, url=url,
        classification_state="proposed", is_categorized=False,
        proposed_client=client, proposed_confidence=confidence, proposed_at=start,
        proposed_reasoning=reasoning,
    )


def _last_weekdays(n: int) -> list[date]:
    d = datetime.now(TZ).date()
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)
