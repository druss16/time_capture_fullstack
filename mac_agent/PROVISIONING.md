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
| Endpoint hit | `POST /api/deploy/auto-pair/`, falling back to `/api/deploy/claim/` | the same two |
| Who the device pairs to | hostname → AD username → email, from `DeviceProvisioningMap` | hostname → short name → directory email, from the same table |
| IT controls the mapping? | **yes** | **yes** |
| Falls back to a picker? | yes (`status: pick_user`) | yes |
| Works today? | **no** — see Known broken | yes |

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

**2. On first run** `mdm_deploy.do_org_token_claim()` walks the same three
endpoints the Windows agent does, in the same order:

1. **`POST /deploy/auto-pair/`** — hostname, then short name, matched against
   `DeviceProvisioningMap`. Both are uppercased, because `provision_firm`
   stores them that way (`machine_hostname=hostname.upper()`) and the server
   compares exactly. A trailing `.local` is stripped first: the map holds what
   IT exported from its inventory, which does not carry it.
2. **`POST /deploy/claim/`** on `unprovisioned` — the four-step ladder: known
   device, email match, provisioning map, then `pick_user`. The Mac sends its
   OpenDirectory `mail` attribute when the account has one (`dscl . -read
   /Users/<name> mail`), which is the nearest thing a Mac has to the AAD UPN
   Windows reads, and is what lets the email step succeed. On an unbound Mac
   there is usually no `mail` attribute, so the short name is all there is —
   which is exactly when the provisioning map earns its keep.
3. **A one-time picker**, then **`POST /deploy/confirm-user/`**.

Steps 1 and 2 are silent. Only step 3 involves a human.

`device_id` is the one `main.py` already keeps, passed in — not a second one
minted inside `mdm_deploy`, which is what the Windows copy does.

### Known broken

**The Windows MDM path cannot reach any of these endpoints.**
`windows_agent/mdm_deploy.py` builds its URLs as
`f"{api_base.rstrip('/')}/api/deploy/..."`, but `API_BASE` already ends in
`/api` (`windows_agent/main.py:394`, and every committed `api_base` value).
So all three resolve to `/api/api/deploy/...`, which is a Django routing 404:

```
POST /api/deploy/auto-pair/       -> {"error": "Invalid org token"}   route exists
POST /api/api/deploy/auto-pair/   -> <!doctype html> ... Not Found     route missing
```

`do_org_token_claim` then logs `⚠️ Org token claim failed — falling back to
manual pairing`, which is the one outcome org-token deployment exists to
avoid. The fix is to drop `/api` from those three f-strings. **Not done here**
— this file's change is Mac-only by design.

**`/agent/register/` is dead and the Mac agent no longer calls it.** It
find-or-created a user from the OS short name and minted
`shortname@yourorg.local`. Two reasons it went:

* It is a different identity namespace from the one Windows pairs into, so one
  person with a Mac and a PC became two users.
* It could not work anyway. `server/tracker/views.py` does
  `user.groups.add(org)`, but `Organization` is a plain `models.Model`, not a
  `Group` — Django's `ManyRelatedManager.add` raises `TypeError` on a
  wrong-model instance, so the call 500s *after* creating the user. And the key
  it returned lived in `AgentRegistration`, which `AgentKeyAuthentication`
  never consulted, so even past the crash it authenticated nothing.

The server view and its route are now gone too, and `AgentRegistration` was
dropped with them (migration 0167) — it had held zero rows in production for
its entire life. `AgentDevice` is the only installed-agent table.

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

On macOS it also writes `relink_requested` into the config, and the next start
consumes that flag and skips the org-token claim. Without it, Re-link would be
useless on precisely the managed fleets it matters most for: clearing the key
does not clear the org token, which lives in the plist under `/Library` where
the user cannot reach it, so the claim would run on the very next start and
put the device straight back on whoever `DeviceProvisioningMap` names — with
the pairing window never appearing. The flag fires once, so a later start, or
a fresh deploy, auto-pairs normally.

**Windows has no such flag.** `drop_api_key()` and `repair_device()` clear
`api_key` and `server_device_id` and leave `org_token` in place, so once the
`/api/api/` URL bug above is fixed, a repaired Windows machine will re-claim
silently rather than prompt. That is the documented intent — fix the
`DeviceProvisioningMap` row FIRST — but it is worth knowing before the fix
lands, because today the 404 makes every repair fall through to the picker.

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
