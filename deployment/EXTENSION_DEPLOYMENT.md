# Deploying the "TimeTracker URL Reporter" extension with zero extra steps

Goal: make the browser extension install **automatically when IT installs the
agent** — no separate download, no per-user clicking. This is done with a browser
**force-install policy** (a registry key) that the agent installer writes.

The extension itself lives in [`browser_extension/`](../browser_extension/). It
reads the active tab's URL + title and sends them to the agent's local bus
(`127.0.0.1:7321`) — nothing leaves the machine.

---

## Read this first — the one real limitation

A force-install policy silently installs and pins the extension. It captures
**http/https and blob: (portal-download) URLs** with no user action. Good.

**But it CANNOT silently grant "Allow access to file URLs."** Chrome and Edge
deliberately make that a per-user toggle (security) with **no enterprise policy
to force it on** (confirm against current Edge/Chrome policy docs — this can
change). Practical consequence:

| PDF opened from…            | Captured silently by force-install? |
| --------------------------- | ----------------------------------- |
| a **web portal** (https/blob) | ✅ yes                              |
| a **local file** (`file://`)  | ❌ no — needs a one-time per-machine "Allow access to file URLs" toggle |

So: if your users' payroll/reconciliation PDFs open **from a portal**, Option 1
below fully solves it, silently. If they open **as local files**, the extension
can't read them without that manual toggle — the reliable *silent* path for
local files is the agent side (Option 2 in chat), which is untested Windows code.
Decide based on where those PDFs actually come from.

---

## Step 1 — Get a stable extension ID + a place to serve it

A force-install policy needs `<extensionID>;<updateURL>`. Pick ONE hosting route:

### Route A — Publish to the store (recommended: simplest, most reliable)
- **Edge Add-ons:** https://partner.microsoft.com/dashboard/microsoftedge → submit
  `browser_extension/` (zipped). Review is usually 1–3 days.
- **Chrome Web Store:** https://chrome.google.com/webstore/devconsole ($5 one-time
  dev fee) → submit the same zip. Edge can install Chrome-store extensions too.
- After approval you get a permanent **32-char extension ID**. Update URLs:
  - Edge store:   `https://edge.microsoft.com/extensionwebstorebase/v1/crx`
  - Chrome store: `https://clients2.google.com/service/update2/crx`
- Tip: you can list it **Unlisted** so it isn't publicly discoverable but still
  force-installable by ID.

### Route B — Self-host the `.crx` (no store, no review)
1. Give the extension a **stable ID** by adding a `key` to
   `browser_extension/manifest.json` (without it, the ID is random per machine and
   force-install can't target it):
   - In Chrome: `chrome://extensions` → enable Developer mode → **Pack extension**
     → point at `browser_extension/`. This produces a `.crx` **and** a `.pem`.
     Keep the `.pem` safe (it's your signing key). The generated ID is shown.
   - Add the public key it embeds to `manifest.json` as `"key": "<base64…>"` so
     the ID is fixed on every build.
2. Host two files on a URL you control (e.g. your site or an S3 bucket):
   - the `.crx`, and
   - an `update.xml` manifest pointing at it (Google's "autoupdate" format).
3. Use **your `update.xml` URL** as the update URL in the policy below, and
   add the ID to the browser's `ExtensionInstallAllowlist` if your org restricts
   sources.

---

## Step 2 — The installer change (ready to drop in)

Once you have `<extensionID>` (and, for self-host, your update URL), paste this
into `deployment/install_timetracker_template.ps1` right before the final
`Write-Host "TimeTracker deployment complete."`. It runs as the same admin
context the installer already uses, and finds a free numeric slot so it never
clobbers another IT-managed extension.

```powershell
# --- Force-install the TimeTracker URL Reporter extension (silent, pinned) ----
$extId     = "REPLACE_WITH_EXTENSION_ID"   # 32-char id from the store or your key
$edgeCrx   = "https://edge.microsoft.com/extensionwebstorebase/v1/crx"   # Edge store
$chromeCrx = "https://clients2.google.com/service/update2/crx"           # Chrome store
# For a SELF-HOSTED .crx, set both of the above to your update.xml URL instead.

foreach ($b in @(
    @{ Path = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist"; Crx = $edgeCrx },
    @{ Path = "HKLM:\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist";  Crx = $chromeCrx }
)) {
    if (-not (Test-Path $b.Path)) { New-Item -Path $b.Path -Force | Out-Null }
    $used = @((Get-Item $b.Path).Property | Where-Object { $_ -match '^\d+$' } | ForEach-Object { [int]$_ })
    $slot = 1; while ($used -contains $slot) { $slot++ }
    New-ItemProperty -Path $b.Path -Name "$slot" -Value "$extId;$($b.Crx)" -PropertyType String -Force | Out-Null
    Write-Host "Registered extension force-install in $($b.Path) [slot $slot]"
}
```

That's the whole change — one block, no new dependencies. (I'll wire it in for
you once you have the ID; until then the installer is untouched.)

---

## Step 3 — Verify on one machine

1. Run the updated installer as admin on a test PC.
2. Open Edge → `edge://extensions` (and/or `chrome://extensions`). The
   extension should appear, **enabled, "Installed by your organization,"** and
   un-removable.
3. Confirm URLs flow: browse to a client portal, then check that new blocks for
   that user carry a `url` (Daily Review will show a `Web` source tag).
4. **Local-file PDFs only:** if you need those too, on that machine toggle the
   extension's **"Allow access to file URLs"** once and confirm a `file://` PDF
   then reports its folder. (Remember: this toggle can't be pushed by policy.)

---

## Summary

- **Option 1 = this doc.** One-time: publish/host the extension → get an ID. Then
  a ~10-line installer block makes every agent install carry the extension
  silently. Best for **portal** PDFs and all normal web attribution.
- **You do the publish/host** (I can't); **I'll wire the installer block** once
  you have the ID.
- **Local-file PDFs** stay the exception — browsers won't let policy grant file
  access. If those matter, that's the agent-side capture path, which needs a real
  Windows test before release.
