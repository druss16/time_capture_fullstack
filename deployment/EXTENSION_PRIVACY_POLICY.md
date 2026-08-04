# TimeTracker URL Reporter — Privacy Policy

_Last updated: 2026-08-04_

The Edge Add-ons store requires a public privacy-policy URL for any extension
that touches browsing data. Host this page at a stable URL (e.g.
`https://<your-domain>/timetracker-extension-privacy`) and use that URL in the
store listing. Edit the bracketed bits (company name, contact email) before
publishing.

---

## What this extension is

TimeTracker URL Reporter is a companion to the TimeTracker desktop agent that
[Company] installs on managed workstations. It helps attribute browser-based
work to the correct client.

## What data it accesses

- The **URL and title of the active browser tab**, only while a browser window
  is focused.
- Before use, the **query string and fragment are removed** from the URL, so
  session tokens, account identifiers, and sharing links are discarded.

It does **not** access:

- Page contents, form fields, passwords, or anything in the page DOM (there are
  no content scripts).
- Your browsing history, bookmarks, cookies, or other tabs.
- Any activity while the browser is not the focused window.

## Where the data goes

- The sanitized URL and title are sent **only to the TimeTracker desktop agent
  running on the same computer**, at `http://127.0.0.1:7321` (localhost).
- **Nothing is transmitted over the internet by this extension.** No data is
  sent to [Company], the extension publisher, or any third party.
- If the local agent is not running, no data is sent anywhere.

Once the local agent receives the URL, its handling of that information is
governed by [Company]'s TimeTracker service agreement and privacy practices —
the same terms covering the desktop agent your organization already runs.

## Data retention & selling

- This extension stores no data itself and retains nothing between browser
  sessions.
- [Company] does **not** sell or share this data with third parties.

## Permissions

- **`tabs`** — to read the active tab's URL and title for attribution.
- **Host access to `http://127.0.0.1/*`** — the only network destination, used
  to reach the local desktop agent.

## Contact

Questions about this extension or your data: [support@your-domain].
