# Provisioning the agent at scale

How a machine gets paired without anyone clicking anything, on both
platforms, and how to re-pair one that is on the wrong account.

Written from the code, not from memory. Line references are to the files
named; if you change the flow, change this.

---

## The short version

| | Windows | macOS |
|---|---|---|
| Config IT deploys | `C:\ProgramData\TimeTracker\config.json` | `/Library/Application Support/TimeTracker/config.plist` |
| Key in it | `org_token` | `OrgToken` |
| Endpoint hit | `POST /api/deploy/auto-pair/`, falling back to `/api/deploy/claim/` | `POST /api/agent/register/` |
| Who the device pairs to | hostname → AD username → email, from `DeviceProvisioningMap` | find-or-create a user from the OS username |
| IT controls the mapping? | **yes** | **no** — see the gap below |
| Falls back to a picker? | yes (`status: pick_user`) | no |

Both agents try the deployed config **before** showing a pairing window, so a
provisioned machine never prompts. `run_agent()` in `main.py`: MDM config
first, interactive pairing only if that returns nothing.

---

## Windows, end to end

**1. Create a deployment token.** Settings → Connections → MDM Deploy, or
`POST /api/deploy/tokens/create/`. A token can carry `max_devices`; null means
unlimited. Each successful claim increments `devices_claimed`.

**2. (Recommended) Pre-map machines to people.** Populate
`DeviceProvisioningMap` from an Intune or AD export. Each row carries:

    machine_hostname   e.g. FIRM-PC-101
    windows_username   e.g. FIRMNAME\jsmith
    email              the user this device should pair to

This is what makes the pairing deliberate rather than a guess.

**3. Deploy the config** to every machine:

```json
{
  "org_token": "tt_org_...",
  "api_base": "https://timetracker-api-k375.onrender.com/api"
}
```

at `C:\ProgramData\TimeTracker\config.json`.

**4. Install the agent.** On first run `mdm_deploy.do_org_token_claim()` tries
`/api/deploy/auto-pair/` first (`views_autopair.auto_pair_device`), which
matches the hostname and `windows_username` against `DeviceProvisioningMap`
and answers either:

    200  {"status": "paired", "match_method": "hostname", "user_email": ...}
    202  {"status": "unprovisioned"}          → no pre-provisioned match

On `unprovisioned` it falls back to `/api/deploy/claim/`, where the server
walks a four-step ladder (`views_deployment.deploy_claim`):

1. **Hostname already registered** → reuse that device row.
2. **Email match from the OS username** (`_match_user_by_email`).
3. **Provisioning map** (`_match_via_provisioning_map`) — hostname first
   (most reliable from an Intune/AD export), then `windows_username`, exact
   first and then with the `DOMAIN\` prefix stripped.
4. **No match** → returns `status: "pick_user"` with the member list, and the
   agent shows a one-time picker.

Steps 1–3 are silent. Only step 4 involves a human, and populating the
provisioning map is what avoids it.

---

## macOS, end to end

**1 and 3 are the same** — same deployment token, but the config is a plist:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
    <key>OrgToken</key>
    <string>tt_org_...</string>
    <key>ApiEndpoint</key>
    <string>https://timetracker-api-k375.onrender.com/api</string>
</dict>
</plist>
```

at `/Library/Application Support/TimeTracker/config.plist`. Deploy it with
whatever you use for Macs (Jamf, Kandji, Mosyle, or a postinstall script).
`get_mdm_config()` also accepts the Windows JSON path, so a cross-platform MDM
payload can carry either.

**2. On first run** `register_with_org_token()` posts `org_token` plus the OS
username to `/api/agent/register/`, which validates the token and then
**find-or-creates a user from that username**:

```python
user, user_created = User.objects.get_or_create(
    username=username,
    defaults={'email': f'{username}@{org.name.lower().replace(" ", "")}.local', ...}
)
```

Note the invented email: an unrecognised shortname produces a user with a
`…@yourorg.local` address that reaches nobody.

### The gap, stated plainly

The Mac path does **not** consult `DeviceProvisioningMap`. It cannot: the
endpoint it calls takes a username and creates a user if none matches.

So on Windows, IT decides which person a machine belongs to, and an unmatched
machine says so (`unprovisioned`, then a picker). On macOS the answer comes
from whatever the Mac's login shortname happens to be, and a shortname nobody
recognises quietly creates a NEW user with a fake `.local` email rather than
failing or asking.

Both platforms deploy silently at scale. Only Windows deploys *deliberately*.

Closing this means pointing the Mac agent at `/api/deploy/claim/` like Windows
does, which is a real change and is not done. Until then, for Mac fleets:

- Make sure Mac login shortnames match the local part of the user's email, so
  `_match_user_by_email`-style matching has something to work with, **or**
- Accept that you will tidy up auto-created users afterwards, **or**
- Pair Macs by hand, which does not scale but is at least correct.

---

## Re-pairing a machine that is on the wrong account

The agent offers its pairing window **only when it has no key at all**:

```python
key = config.get("api_key") or API_KEY
if key:
    return key          # already paired — never prompts again
```

So a machine with a bad or wrong-account key will never ask. There are two
ways back.

**By hand, one machine** — the Re-link Device item in the menu bar (macOS) or
tray (Windows). It clears the pairing, shows the pairing window and restarts
the agent. This is why that item is never hidden behind the vendor ticker
flag: it is the only route back, and hiding it makes a device unrecoverable.

**Scripted, for IT** — delete the stored key and restart. The deployed config
is still on disk, so the agent re-claims with the org token on next start with
no user interaction:

macOS:
```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".timetracker/config.json"
d = json.loads(p.read_text()); d.pop("api_key", None)
p.write_text(json.dumps(d, indent=2))
PY
launchctl kickstart -k "gui/$(id -u)/com.mavops.timetracker"
```

Windows — remove `api_key` from `%USERPROFILE%\.timetracker\config.json`, then
restart the agent's scheduled task.

Re-claiming lands wherever the ladder points, so on Windows fix the
`DeviceProvisioningMap` row FIRST or it will pair to the same wrong user again.

---

## Checking it worked

The installer reports success for a package whose agent never starts, so
check the agent, not the installer.

macOS:
```bash
launchctl list | grep com.mavops.timetracker
```
A pid in the first column means running. A number in the second with no pid is
the exit status of a job that failed — `2` is file-not-found.

Both platforms — confirm the server agrees the device exists, and on which
account:
```bash
curl -s -X POST -H "Authorization: DeviceKey <key>" \
     -H "Content-Type: application/json" \
     -d '{"hostname":"...","app_version":"...","device_id":"...","os_username":"..."}' \
     https://timetracker-api-k375.onrender.com/api/agents/hello2/
```
It returns the `user_id` and `username` the device is bound to. Settings →
Connections → Devices lists them per user, but only for the account you are
signed in as — a device on a colleague's user will not appear in yours.
