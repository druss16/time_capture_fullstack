# Edge Add-ons submission — copy & answers (ready to paste)

Everything the Edge Partner Center form asks for, pre-written to match what the
extension actually does (`browser_extension/background.js`). Submit the extension
**Unlisted** (Availability → "Hidden"): not publicly discoverable, still
force-installable by ID.

Portal: https://partner.microsoft.com/dashboard/microsoftedge/overview
Zip `browser_extension/` (the folder's *contents*: `manifest.json`, `background.js`,
`icons/`) and upload that.

---

## Store listing fields

**Name**
> TimeTracker URL Reporter

**Short / summary description**
> Reports the active tab's address to your locally-installed TimeTracker agent so
> web work is attributed to the right client. Reads the tab URL and title only —
> never page contents — and sends them only to the agent on this same computer.

**Category**
> Productivity

**Detailed description**
> TimeTracker URL Reporter is a companion to the TimeTracker desktop agent your
> organization installs. When you work in a browser — a client portal,
> QuickBooks Online, OneDrive online, or a downloaded PDF — this extension tells
> the desktop agent which site or file is in front of you, so your time is
> attributed to the correct client automatically instead of landing in a
> "pick a client" queue.
>
> What it reads: the URL and title of the active tab in the focused browser
> window. It strips the query string and fragment first, so session tokens and
> sharing IDs never leave the browser.
>
> What it does NOT do:
> • It does not read, collect, or transmit page contents. There are no content
>   scripts and no access to page DOM.
> • It does not send anything over the internet. The URL and title are POSTed
>   only to the TimeTracker agent running on the same computer
>   (http://127.0.0.1:7321). If the agent is not running, nothing is sent.
> • It does nothing while the browser window is not focused, so background tabs
>   never override the app you are actually using.
>
> This extension is intended for managed deployment alongside the TimeTracker
> desktop agent. Without that local agent it takes no action.

**Privacy policy URL** (required — host the page below, see EXTENSION_PRIVACY_POLICY.md)
> https://<your-domain>/timetracker-extension-privacy

**Support / website URL**
> https://<your-domain>  (or a support mailbox link)

---

## "Why do you need each permission?" (the part reviewers actually read)

Edge asks you to justify every permission in `manifest.json`. Answer verbatim:

**`tabs`**
> Used to read the URL and title of the active tab in the focused window
> (`chrome.tabs.query({active:true, lastFocusedWindow:true})`) so the local
> TimeTracker agent can attribute the current web work to the correct client.
> Only the active tab's URL and title are accessed; page contents are never
> read. No content scripts are injected.

**`storage`**
> Stores small local diagnostic counters (URLs captured, sent-OK, send-failed,
> last capture) so the extension's troubleshooting popup can display them.
> `chrome.storage.local` only — never synced, never transmitted.

**`cookies` (+ host access to `qbo.intuit.com`)**
> Reads exactly one cookie, `qbo.currentcompanyid`, on `qbo.intuit.com`. This is
> the id of the QuickBooks Online company the user currently has open. Accounting
> staff switch between many client companies in QBO, and this id is how the local
> TimeTracker agent attributes the session to the correct client. No other
> cookies are read, and no page contents are accessed. The value is sent only to
> the local agent (127.0.0.1), never to any external host.

**Host permission `http://127.0.0.1/*`**
> The only network destination the extension contacts. It POSTs the active tab's
> sanitized URL and title to the TimeTracker desktop agent's local context
> endpoint (http://127.0.0.1:7321/context) running on the same machine. No
> external hosts are contacted.

**`scripting` (QBO pages only)**
> On `qbo.intuit.com` tabs, the extension runs a one-shot script that reads only
> two values from the page's shell config — the active company's display name
> (`companyName`) and id (`serverGroupCompanyId`) — so the local agent can
> attribute the session to the correct client. It reads no other page content
> (no transactions, balances, customers, or form data) and injects nothing into
> any other site. These values are sent only to the local agent (127.0.0.1).

**Host permission `https://qbo.intuit.com/*` (and `https://*.qbo.intuit.com/*`)**
> Scopes the `cookies` and `scripting` access above to QuickBooks Online only —
> to read the `qbo.currentcompanyid` cookie and the company name/id from the QBO
> page. No other site is affected.

**Why not `activeTab` instead of `tabs`?**  (reviewers sometimes ask)
> `activeTab` only grants access after a user gesture (toolbar click). This
> extension must report tab changes passively and continuously for accurate,
> hands-off time attribution, which requires the `tabs` permission. It still
> reads only URL + title, never content.

---

## Data-use / privacy declarations (dashboard checkboxes)

Answer the Partner Center "data collection" section as:

| Question | Answer |
| --- | --- |
| Does your extension collect personally identifiable information? | **No** — data is sent only to the user's own machine (127.0.0.1); nothing is collected by the publisher or any server. |
| Does it collect web browsing activity? | Technically it reads the active tab URL, but it is **transmitted only to localhost and never to us or any third party.** State this in the notes field. |
| Do you sell or transfer data to third parties? | **No.** |
| Is data transmitted off the user's device? | **No.** Only to 127.0.0.1 on the same device. |

If the form forces a single certification checkbox, certify that the extension's
data handling is disclosed in the privacy policy (it is — see the policy page).

---

## Notes for the reviewer (put in the "notes to certification team" box)

> This extension is a localhost-only companion to a desktop agent. It reads the
> active tab's URL + title and POSTs them exclusively to http://127.0.0.1:7321
> on the same machine (see background.js `postToAgent`). It injects no content
> scripts, reads no page DOM, and contacts no external servers. Query strings
> and fragments are stripped before sending. It is deployed to managed
> workstations that also run the TimeTracker desktop agent.

---

## After approval

You get a permanent **32-char extension ID**. Bring it back and I'll wire the
force-install block (already drafted in `EXTENSION_DEPLOYMENT.md` Step 2) into
`install_timetracker_template.ps1`. Update URL for the Edge store is
`https://edge.microsoft.com/extensionwebstorebase/v1/crx`.
