# Sign in with Microsoft / Google

Code: `tracker/views_sso.py`, `tracker/models_sso.py`, `frontend/src/pages/SSOComplete.tsx`.
The buttons on `/login` appear only for providers listed in `SSO_PROVIDERS`.

## Turning it on (order matters)

1. **Merge.** Render auto-deploys the code; the buttons stay hidden.
2. **Migrate** on Render (migrations are manual): `python manage.py migrate tracker`
   — creates `tracker_sociallogin`.
3. **Register the callback URIs** (below).
4. **Set `SSO_PROVIDERS`** on the API service, e.g. `microsoft,google`. Buttons appear.

Enabling before step 2 would 500 the callback on the missing table.

## Microsoft (Entra)

Uses the calendar app registration (`MS_GRAPH_CLIENT_ID/SECRET`) unless
`SSO_MICROSOFT_CLIENT_ID` + `SSO_MICROSOFT_CLIENT_SECRET` are both set.

- Entra → App registrations → the app → Authentication → Web → add
  `https://api.timetracker.mavops.ai/api/auth/sso/microsoft/callback/`
  (or whatever `SSO_MICROSOFT_REDIRECT_URI` is set to).
- Supported account types must include *any organizational directory*
  (multi-tenant). Sign-in uses the `organizations` authority: work/school
  accounts only, no personal outlook.com.
- Scopes requested: `openid profile email offline_access` — no Graph, so a
  tenant admin never has to approve anything.

## Google

Uses `GOOGLE_OAUTH_CLIENT_ID/SECRET` unless `SSO_GOOGLE_CLIENT_ID` +
`SSO_GOOGLE_CLIENT_SECRET` are both set.

- Google Cloud Console → APIs & Services → Credentials → the OAuth client →
  Authorized redirect URIs → add
  `https://api.timetracker.mavops.ai/api/auth/sso/google/callback/`.
- Scopes: `openid email profile` (non-sensitive; no extra verification).

## Behaviour

- **Never creates accounts.** The person must already exist (invite or
  `provision_firm`). First sign-in matches by verified email (Microsoft: the
  UPN; Google: `email` with `email_verified`) and stores a `SocialLogin`; later
  sign-ins match on the provider's subject, not the email.
- If the provider email doesn't match the email we have, the login page says
  "That account isn't set up in TimeTracker yet". Fix the user's email, or
  invite them under the address they sign in with.
- Password login keeps working alongside it.
