# TimeTracker Deployment Assets

This folder contains IT deployment files for enterprise rollouts.

---

## Files

| File | Purpose |
|------|---------|
| `TimeTrackerWatchdog_GPO.xml` | GPO Preferences XML — deploys the watchdog scheduled task to all users |
| `install_timetracker_template.ps1` | Template logon script — customize per client before sending to IT |

---

## How the config works

The agent reads config from two places:

1. `%PROGRAMDATA%\TimeTracker\deploy.json` — written by the IT logon script, contains `org_token` and `server_url`. Machine-wide, readable by all users.
2. `~/.timetracker/config.json` — written by the agent after pairing, contains `api_key`. Per-user.

The deploy.json is only used for initial pairing. Once the agent pairs successfully, it writes the `api_key` to the user config and ignores `org_token` from that point on.

---

## Per-Client Deployment Checklist

### Step 1 — Get the release assets
Download from https://github.com/druss16/timetracker-releases/releases/latest:
- `TimeTracker-Windows-Setup.exe`

### Step 2 — Customize the install script
1. Copy `install_timetracker_template.ps1`
2. Rename to `install_timetracker_FIRMSLUG.ps1` (e.g. `install_timetracker_tlwall.ps1`)
3. Replace `REPLACE_WITH_ORG_TOKEN` with the client's org token from the TimeTracker admin dashboard
4. Place script + installer on the client's network share (e.g. `\\SERVER\Software\TimeTracker\`)

### Step 3 — Send to IT
Send the client's IT contact:
- Network share path with both files
- `TimeTrackerWatchdog_GPO.xml`
- The IT onboarding email (template in Notion)

### Step 4 — IT deploys via GPO
IT does two things in Group Policy Management:

**Install script (Logon script):**
`User Configuration → Policies → Windows Settings → Scripts → Logon`
Add `install_timetracker_FIRMSLUG.ps1`

**Watchdog task (GPO Preference):**
`User Configuration → Preferences → Control Panel Settings → Scheduled Tasks`
Right-click → New → Scheduled Task (At least Windows 7) → XML tab → paste `TimeTrackerWatchdog_GPO.xml`

---

## Important Notes
- The install script is idempotent — safe to re-run, skips already-installed machines
- Auto-update is fully automatic after initial install — IT never needs to push updates again
- Per-client `.ps1` files should NEVER be committed to this repo (they contain org tokens)
- `install_timetracker_*.ps1` is in `.gitignore` as a safeguard