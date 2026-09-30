# Google (Gmail + Google Calendar) integration — setup and deploy

Per-user Gmail and Google Calendar connections, the Google Workspace
counterpart of the Outlook mail and calendar integrations. Code:

| Piece | File |
|---|---|
| OAuth + REST client (plain `requests`) | `server/tracker/integrations/google.py` |
| Connect / callback / status / disconnect views | `server/tracker/views_google.py` |
| Gmail sync (Celery) | `server/tracker/tasks_gmail.py` |
| Calendar sync (Celery) | `server/tracker/tasks_google_calendar.py` |
| Compose-time attribution | `server/tracker/services/mail_compose.py`, Stage 7a in `services/classification_service.py` — strong (auto-files) only when composing to one client covers ≥50% of the Gmail block's active time; otherwise a weak contributing signal; sends to 2+ clients in one block are flagged for review |
| Connections page cards | `frontend/src/components/GoogleConnectionTab.tsx` |
| Migration | `server/tracker/migrations/0176_google_mail_calendar.py` |

One Google Cloud project and **one OAuth client** serve both products (a single
`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` pair). Each connect
flow requests only its own scopes; the two flows have separate redirect URIs.

---

## 0. Prerequisite: the API custom domain

Google does not accept `onrender.com` as an authorized domain on an OAuth
consent screen, so the Google callbacks live on the API's custom domain:

    https://api.timetracker.mavops.ai

This needs, in order:

1. Render: add `api.timetracker.mavops.ai` as a custom domain on the
   **timetracker-api** web service.
2. Cloudflare: a `CNAME api.timetracker` → the Render target Render shows.
   (If Cloudflare proxying is on, Render's certificate issuance can stall —
   start "DNS only", switch to proxied after the certificate is issued.)
3. **Deploy this branch's `settings.py` change BEFORE anything points at the new
   domain.** It adds `api.timetracker.mavops.ai` to `ALLOWED_HOSTS` and
   `https://api.timetracker.mavops.ai` to `CSRF_TRUSTED_ORIGINS`. Without it,
   Django answers every request on that host with **400 Bad Request**.
   The `onrender.com` hosts stay: desktop agents and the Outlook callbacks
   still use them.
4. Check: `curl -sI https://api.timetracker.mavops.ai/api/whoami/` returns a
   Django response (401/403 is fine), not 400 and not a Cloudflare/Render error.

---

## 1. Google Cloud Console

Use a Google account that belongs to MavOps (not to a customer).

1. **Create a project** — console.cloud.google.com → project picker → *New
   project*, e.g. `timetracker-prod`.
2. **Enable APIs** — *APIs & Services → Library*: enable **Gmail API** and
   **Google Calendar API**. (A disabled API makes every sync 403 with
   `accessNotConfigured`; the sync marks the row disconnected and says so.)
3. **OAuth consent screen** (*APIs & Services → OAuth consent screen*, called
   "Google Auth Platform → Branding / Audience / Data access" in newer consoles):
   - **User type: External.** "Internal" only admits users of the Workspace
     that owns this Cloud project — i.e. MavOps, not the customer.
   - App name `TimeTracker`, support email, developer contact email.
   - App domain / homepage: `https://timetracker.mavops.ai`; privacy policy and
     terms URLs on the same domain (required before verification).
   - **Authorized domains:** `mavops.ai` (covers both
     `timetracker.mavops.ai` and `api.timetracker.mavops.ai`).
   - **Scopes** (*Data access*): add exactly these —
     - `openid`
     - `.../auth/userinfo.email` (shown for `email`)
     - `https://www.googleapis.com/auth/gmail.metadata` — **restricted**
     - `https://www.googleapis.com/auth/calendar.readonly` — sensitive
   - **Publishing status:** see §4. Do not leave the app in *Testing* for real
     users: refresh tokens issued to a Testing-status app with these scopes
     **expire after 7 days**, which shows up here as every connection flipping
     to "Gmail access needs to be granted again" a week after connecting.
4. **OAuth client** — *Credentials → Create credentials → OAuth client ID*:
   - Application type **Web application**, name `TimeTracker API`.
   - **Authorized redirect URIs** — add BOTH, exactly (trailing slash included):
     - `https://api.timetracker.mavops.ai/api/google/gmail/auth/callback/`
     - `https://api.timetracker.mavops.ai/api/google/calendar/auth/callback/`
   - Optional, for local development: the same two paths on
     `http://localhost:7123`.
   - No JavaScript origins are needed (the browser never talks to Google's
     token endpoint; the API does).
   - Copy the **Client ID** and **Client secret**.

What each connect flow asks for (built in `google.build_auth_url`):

| Flow | Scopes requested | Redirect URI |
|---|---|---|
| Gmail | `openid email gmail.metadata` | `.../api/google/gmail/auth/callback/` |
| Google Calendar | `openid email calendar.readonly` | `.../api/google/calendar/auth/callback/` |

Both send `access_type=offline`, `prompt=consent` (a refresh token is only
issued on a consent screen) and `include_granted_scopes=true` (a person who
connects both products ends up with one grant covering both). On callback the
server checks the granted `scope` string contains the flow's own data scope;
if the user unticked it on Google's granular consent screen, nothing is stored
and the card shows **Permission not granted**.

---

## 2. Render environment variables

Set on **every Django service** — `timetracker-api`, `timetracker-api-rebuild`
and `timetracker-worker` (beat runs inside the worker). The web service runs
the OAuth callback; the worker runs the syncs and needs the client ID/secret
to refresh tokens.

| Variable | Value |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | from §1.4 |
| `GOOGLE_OAUTH_CLIENT_SECRET` | from §1.4 |
| `GOOGLE_GMAIL_REDIRECT_URI` | `https://api.timetracker.mavops.ai/api/google/gmail/auth/callback/` |
| `GOOGLE_CALENDAR_REDIRECT_URI` | `https://api.timetracker.mavops.ai/api/google/calendar/auth/callback/` |

The two redirect URIs default to exactly those values in `settings.py`, but set
them explicitly anyway. They are deliberately independent settings: deriving
one URI from another by string replacement is how Outlook mail lost every new
connection for four months.

Also required (already set for Outlook): `TOKEN_ENCRYPTION_KEYS` (tokens are
stored in the encrypted `UserIntegration.access_token/refresh_token` columns)
and `FRONTEND_BASE_URL=https://timetracker.mavops.ai` (where the callback sends
the browser back to: `/account/connections?gmail=…` / `?gcal=…`).

Until the client ID/secret are set, the Connections page shows the Google
cards with a disabled Connect button ("not set up on this server yet") and
`/auth/start/` returns 503.

---

## 3. Deploy checklist

Order matters — Render auto-deploys code on merge, **migrations are manual**.

1. Custom domain + `settings.py` hosts live (§0).
2. **Apply the migration first** (additive + nullable, safe to run ahead of the
   code): Render → timetracker-api → *Shell*:
   ```
   python manage.py migrate tracker 0176
   python manage.py showmigrations tracker | tail -3
   ```
   `0176_google_mail_calendar` adds nullable `MailSignal.from_address`,
   `from_name`, `to_recipients`, `cc_recipients`, `subject`,
   `compose_seconds` and `UserIntegration.sync_cursor`, `sync_cursor_set_at`.
3. Set the env vars (§2) on all three services.
4. Merge. Code deploys automatically to the web service and the worker.
5. **Beat registration.** Production beat uses
   `django_celery_beat.schedulers.DatabaseScheduler`: the live schedule is the
   `PeriodicTask` table, not `celery_app.py`. On start-up, DatabaseScheduler
   copies `app.conf.beat_schedule` into `PeriodicTask` rows
   (`setup_schedule → update_from_dict`), so the two new entries —
   `sync-all-gmail-every-5-min` (`tracker.sync_all_gmail`) and
   `sync-google-calendars` (`tracker.sync_all_google_calendars`) — are created
   when the worker/beat service restarts on deploy. Verify in the worker Shell:
   ```
   python manage.py verify_beat_tasks
   python manage.py shell -c "from django_celery_beat.models import PeriodicTask as P; print(list(P.objects.filter(task__contains='google').values_list('name','enabled')) + list(P.objects.filter(task='tracker.sync_all_gmail').values_list('name','enabled')))"
   ```
   If the rows are missing (beat did not restart), redeploy the worker service.
   The tasks are also re-exported from `tracker/tasks.py`, without which the
   worker would discard beat's messages as unregistered.
6. Connect one test account end to end (a real Google consent round trip is
   the only proof — it cannot be exercised locally), then:
   ```
   python manage.py integration_health
   python manage.py mail_domains --org <id> --observed
   ```

---

## 4. Google verification — `gmail.metadata` is a RESTRICTED scope

- `gmail.metadata` is on Google's **restricted** scope list;
  `calendar.readonly` is **sensitive**.
- **Public availability** (any Google user can connect) requires Google's
  OAuth app verification, and for restricted scopes additionally an
  **annual third-party security assessment** (CASA, performed by a
  Google-approved assessor, paid by us, renewed yearly). Budget weeks, not
  days, for the first one.
- **Before verification**, an External app in production can still be used,
  but users see Google's "unverified app" warning and there is a lifetime cap
  of 100 users; in *Testing* status only listed test users can connect and
  refresh tokens die after 7 days.
- **Single Workspace customer (the marketing agency) — to be confirmed
  against Google's current documentation before relying on it:** a Workspace
  super admin can mark our OAuth client as **Trusted** in *Admin console →
  Security → Access and data control → API controls → Manage Third-Party App
  Access → Add app → OAuth App Name or Client ID* (paste our Client ID, set
  access to **Trusted**). Google documents that apps an admin has configured
  as trusted are exempt from the unverified-app block for users in that
  domain, which should let that agency's users connect without our app being
  verified. Confirm (a) the exemption still applies to restricted Gmail
  scopes, and (b) whether the 100-user cap and refresh-token rules still bite,
  before promising the customer a date. Their admin may also need to allow
  "Gmail" / "Calendar" as accessible services for third-party apps in the
  same screen.

---

## 5. What is stored, and who can see it

See the `MailSignal` model docstring (PRIVACY GUARANTEES) — it is the source
of truth. In short, for Gmail:

- **Stored:** sender address + display name, To/Cc addresses + display names,
  full subject, time, direction (SENT label → outbound), counterparty domain,
  matched client, and for sent mail the compose time.
- **Never stored or even fetched:** body, snippet, attachment names or
  contents. `messages.get` is called with `format=metadata` and a `fields`
  mask that leaves `snippet` and the MIME parts out of the response.
- **Visible only to the mailbox owner** (their own block evidence). Managers,
  org admins and MavOps admins see the matched client and domain only; the
  classifier's evidence strings (stored on blocks, visible to managers) name a
  domain and client, never an address or subject.
- Internal mail (everyone in the user's own domain) is dropped at sync.
- Disconnect deletes every stored Gmail signal / Google calendar event for
  that user immediately. It does not revoke the Google grant (one grant covers
  both products under `include_granted_scopes`; revoking it would kill the
  other one) — the user can remove it at myaccount.google.com/permissions.

Google Calendar events are stored exactly like Outlook events (title,
description, attendees + domains, times) and follow the same rules.

---

## 6. Domain → client mapping (needed for attribution)

Gmail and Outlook signals go through the same matcher
(`tracker/mail_matching.py`): an `OrgCalendarRule(match_type='attendee_domain')`
mapping a counterparty domain to a client (confidence 0.95), else a client
name found in the subject (0.80). There is **no UI for the domain rules yet**;
use the management command:

```
python manage.py mail_domains --org <id> --observed        # domains seen, volume, mapping
python manage.py mail_domains --org <id> --map acme.com 412
python manage.py mail_domains --org <id> --rematch --apply # re-match stored rows
```

Public domains (gmail.com, outlook.com, …) never map to a client. Without
rules, mail for an agency whose client names are not in subject lines will
sync perfectly and attribute nothing.
