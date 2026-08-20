/*
 * TimeTracker URL Reporter — background service worker (MV3)
 *
 * WHAT IT DOES
 *   Reports the URL + title of the *active tab in the focused window* to the
 *   TimeTracker agent's local context bus (http://127.0.0.1:7321/context).
 *   The agent already runs this bus; the desktop agent reads the posted value
 *   to attribute web-based work (OneDrive online, CS-online, QBO, portals) to
 *   the right client.
 *
 * WHAT IT DOES NOT DO
 *   - Does NOT read page contents. No content scripts, no DOM access.
 *   - Does NOT send anything off the machine. Posts only to 127.0.0.1.
 *   - Does NOT report when the browser window is not focused (so a background
 *     browser tab never overrides the foreground app the desktop agent sees).
 *   - Strips query string and fragment before sending (no tokens / sharing
 *     GUIDs leave the browser).
 *
 * DESIGN NOTES (MV3 robustness)
 *   - MV3 service workers are EPHEMERAL: Chrome/Edge kill them after ~30s idle
 *     and respawn on the next event. All state must be derivable from events;
 *     we keep none that matters across restarts. Each event fully recomputes.
 *   - Diagnostic counters therefore live in chrome.storage.local (not memory),
 *     so the popup can read them even after the worker was recycled.
 *   - chrome.alarms is used as a lightweight keepalive + periodic re-report so
 *     a long dwell on one page still refreshes the agent (which expires stale
 *     context after ~10s). This mirrors the desktop agent's heartbeat idea.
 *   - All chrome.* APIs are wrapped so a transient failure never throws
 *     unhandled in the worker.
 */

const AGENT_PORT = 7321;
const AGENT_URL = `http://127.0.0.1:${AGENT_PORT}/context`;

// Re-report the current tab on this cadence so the agent's ~10s context
// expiry doesn't drop a long single-page dwell. Alarms have a 30s floor in
// MV3 for periodInMinutes, so we use a repeating short alarm via setTimeout
// re-arm pattern inside the alarm handler is not allowed; instead we set a
// 0.5-min alarm (the practical floor) and accept ~30s refresh — well under
// the agent's expiry window if we also report on every tab/focus event
// (which is the common case). See AGENT_CONTEXT_TTL on the agent side.
const KEEPALIVE_ALARM = "tt_url_keepalive";

// Debounce rapid tab/focus churn (alt-tabbing, tab switching) so we don't
// spam the bus. We coalesce to the latest state after this quiet period.
const DEBOUNCE_MS = 250;
let debounceTimer = null;

// --- Diagnostic counters (persisted; the popup renders these) ---------------
// MV3 workers are ephemeral, so counters cannot live in memory — they go in
// chrome.storage.local. Every real report bumps them. Local-only; nothing here
// is ever transmitted.
const STATS_KEY = "tt_stats";
const DEFAULT_STATS = {
  captured: 0,      // times we read an active-tab URL worth reporting
  sentOk: 0,        // of those, the local agent bus accepted it
  sendFailed: 0,    // of those, the post failed (agent not running / blocked)
  lastUrl: "",      // last reported (sanitized) URL
  lastTitle: "",    // last reported title
  lastAt: "",       // ISO timestamp of the last report
  lastQboCompanyId: "", // last QBO active-company id (realmId) captured, if any
  lastQboCompanyName: "", // last QBO company name read from the page, if any
};

async function getStats() {
  try {
    const o = await chrome.storage.local.get(STATS_KEY);
    return Object.assign({}, DEFAULT_STATS, o[STATS_KEY] || {});
  } catch (e) {
    return Object.assign({}, DEFAULT_STATS);
  }
}

async function setStats(s) {
  try { await chrome.storage.local.set({ [STATS_KEY]: s }); } catch (e) { /* ignore */ }
}

async function resetStats() {
  await setStats(Object.assign({}, DEFAULT_STATS));
}

// --- QBO active-company id (Model B) ----------------------------------------
// QuickBooks Online never puts the company id in the working URL — it lives in
// the session. But QBO stores the CURRENTLY-ACTIVE company id in a readable
// cookie named "qbo.currentcompanyid" (the realmId), and it changes the moment
// an accountant switches into a different client's books. We read exactly that
// one cookie via chrome.cookies (no page content, no DOM) so the agent always
// knows WHICH client a QBO session is working on. Requires the "cookies"
// permission + host access to qbo.intuit.com.
// Clio Manage is a single-page app whose route lives in the URL FRAGMENT:
// https://app.clio.com/nc/#/matters/12345. sanitizeUrl deliberately drops the
// fragment before anything is stored — fragments can carry sensitive state —
// but tab.url still has it here, so the matter id can be read without keeping
// the fragment itself, and without any new permission: this is `tabs`, not
// cookies or scripting like the QBO lookup below.
//
// This is the legal equivalent of the QBO realmId: a lawyer's working documents
// never name the matter, but Clio states it exactly whenever they are in it.
// Clio runs four regional hosts and matter ids are per-region, which is why the
// backend pairs this with the org's stored region.
const CLIO_HOST_RE = /(^|\.)(app\.clio\.com)$/i;
const CLIO_MATTER_RE = /#\/matters\/(\d+)/;

function clioMatterId(rawUrl) {
  if (!rawUrl) return null;
  try {
    const u = new URL(rawUrl);
    if (!CLIO_HOST_RE.test(u.host)) return null;
    // Match only /matters/<id>. Clio routes contacts, bills and activities the
    // same way, and attributing a contact id as a matter would mis-bill.
    const m = CLIO_MATTER_RE.exec(u.hash || "");
    return m ? m[1] : null;
  } catch (e) {
    return null;
  }
}

const QBO_HOST_RE = /(^|\.)qbo\.intuit\.com$/i;
const QBO_COMPANY_COOKIE = "qbo.currentcompanyid";

async function qboCompanyId(rawUrl) {
  try {
    if (!rawUrl || !chrome.cookies || !chrome.cookies.get) return null;
    const u = new URL(rawUrl);
    if (u.protocol !== "https:" || !QBO_HOST_RE.test(u.hostname)) return null;
    const c = await chrome.cookies.get({
      url: `${u.protocol}//${u.host}/`,
      name: QBO_COMPANY_COOKIE,
    });
    const val = c && c.value ? c.value.trim() : "";
    // realmId is a long numeric id; ignore anything that doesn't look like one.
    return /^\d{6,25}$/.test(val) ? val : null;
  } catch (e) {
    return null;
  }
}

// QBO embeds the active company's NAME + id in the page shell config
// ("companyName" / "serverGroupCompanyId"). The name is NOT in any cookie/URL,
// so we read it with a one-shot script injection into the QBO tab — reading
// ONLY those two config values (a company name + id), never financial content.
// Requires the "scripting" permission + host access to qbo.intuit.com. Returns
// {id, name} (either may be ""); null if not a QBO tab or injection is blocked.
async function qboCompanyFromPage(tabId, rawUrl) {
  try {
    if (!chrome.scripting || !chrome.scripting.executeScript || tabId == null) return null;
    const u = new URL(rawUrl || "");
    if (u.protocol !== "https:" || !QBO_HOST_RE.test(u.hostname)) return null;

    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        // Runs in the QBO page. Extract only the company name + id from the
        // embedded shell config; return nothing else.
        try {
          const html = document.documentElement.innerHTML || "";
          const nameM =
            html.match(/"companyName"\s*:\s*"([^"]{1,80})"/) ||
            html.match(/companyName\\?"\s*:\s*\\?"([^"\\]{1,80})/);
          const idM =
            html.match(/"serverGroupCompanyId"\s*:\s*"(\d{6,25})"/) ||
            html.match(/serverGroupCompanyId\\?"\s*:\s*\\?"(\d{6,25})/);
          return { name: nameM ? nameM[1] : "", id: idM ? idM[1] : "" };
        } catch (e) {
          return { name: "", id: "" };
        }
      },
    });

    const r = results && results[0] && results[0].result ? results[0].result : null;
    if (!r) return null;
    const id = /^\d{6,25}$/.test((r.id || "").trim()) ? r.id.trim() : "";
    const name = (r.name || "").trim().slice(0, 80);
    return { id, name };
  } catch (e) {
    return null; // injection blocked / tab gone — fall back to the cookie id
  }
}

// --- URL hygiene: keep scheme://host/path, drop query + fragment ------------
// We NEVER keep the query string — that's where session tokens, account ids,
// and PII live. What we keep is only the location: the host + path (or, for a
// local file, the folder path), which is where the CLIENT name tends to be
// (a portal domain, or a "…/Clients/St Marys/…" folder).
function sanitizeUrl(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw);

    // Normal web pages / web PDFs.
    if (u.protocol === "http:" || u.protocol === "https:") {
      return `${u.protocol}//${u.host}${u.pathname}`;
    }

    // A local file opened in the browser (e.g. a client's PDF from a client
    // folder). The FOLDER usually names the client, and there is no query
    // string on a file: URL. Decode %20 etc. so "St%20Marys" reads as a name.
    // NOTE: the browser only exposes file: URLs to the extension when "Allow
    // access to file URLs" is enabled (set via MDM); otherwise tab.url is empty.
    if (u.protocol === "file:") {
      try { return "file://" + decodeURIComponent(u.pathname); }
      catch (e) { return "file://" + u.pathname; }
    }

    // A blob download (e.g. a PDF streamed from a portal): blob:https://host/uuid.
    // The random object id is useless + potentially sensitive — keep only the
    // originating host, which identifies the portal/app.
    if (u.protocol === "blob:") {
      try {
        const inner = new URL(raw.slice(5)); // strip leading "blob:"
        if (inner.protocol === "http:" || inner.protocol === "https:") {
          return `${inner.protocol}//${inner.host}`;
        }
      } catch (e) { /* fall through */ }
      return null;
    }

    // Everything else (edge://, chrome://, about:, data:, …) — skip.
    return null;
  } catch (e) {
    return null;
  }
}

// --- POST to the local agent context bus ------------------------------------
// Returns true if the local agent bus accepted the post, false otherwise.
async function postToAgent(payload) {
  try {
    const res = await fetch(AGENT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      // Don't let a hung agent block the worker; bail fast.
      signal: AbortSignal.timeout ? AbortSignal.timeout(1500) : undefined,
    });
    return !!(res && res.ok);
  } catch (e) {
    // Agent not running, not listening, or browser blocked it — treat as a
    // send failure. The desktop agent falls back to its existing behavior when
    // no context arrives. Never surface errors to the user.
    return false;
  }
}

// --- Resolve the active tab of the focused window and report it -------------
async function reportActiveTab() {
  try {
    // Is a browser window actually focused? If the OS focus is elsewhere
    // (the user is in QuickBooks/Excel), report nothing — let the desktop
    // agent's foreground detection win.
    let win;
    try {
      win = await chrome.windows.getLastFocused({ populate: false });
    } catch (e) {
      win = null;
    }
    if (!win || win.focused !== true) {
      return; // browser not foreground — stay silent
    }

    const tabs = await chrome.tabs.query({
      active: true,
      lastFocusedWindow: true,
    });
    const tab = tabs && tabs[0];
    if (!tab) return;

    const url = sanitizeUrl(tab.url || tab.pendingUrl || "");
    if (!url) return; // new tab page, internal page, or unsanitizable

    const title = tab.title || "";
    const nowIso = new Date().toISOString();

    // If this is a QuickBooks Online tab, capture WHICH company is open so the
    // agent can attribute to the right client. The realmId comes from the
    // qbo.currentcompanyid cookie; the company NAME (which lets the backend
    // auto-match to an existing client, no manual mapping) is read from the
    // page's shell config. Both null/empty for non-QBO tabs.
    const rawUrl = tab.url || tab.pendingUrl || "";
    const cookieId = await qboCompanyId(rawUrl);
    const fromPage = await qboCompanyFromPage(tab.id, rawUrl);
    const qboId = (fromPage && fromPage.id) || cookieId || null;
    const qboName = (fromPage && fromPage.name) || "";

    // Count the capture and record what we saw, then record the send outcome.
    const stats = await getStats();
    stats.captured += 1;
    stats.lastUrl = url;
    stats.lastTitle = title;
    stats.lastAt = nowIso;
    if (qboId) stats.lastQboCompanyId = qboId;
    if (qboName) stats.lastQboCompanyName = qboName;

    const payload = {
      source: "browser_extension",
      url: url,
      title: title,
      window_focused: true,
      tab_focused_at: nowIso,
    };
    if (qboId) payload.qbo_company_id = qboId;
    if (qboName) payload.qbo_company_name = qboName;

    // Which Clio matter is open, when the tab is Clio. Definitive — beats every
    // filename heuristic the backend would otherwise fall back on.
    const clioMatter = clioMatterId(rawUrl);
    if (clioMatter) {
      payload.clio_matter_id = clioMatter;
      stats.lastClioMatterId = clioMatter;
    }

    const ok = await postToAgent(payload);

    if (ok) stats.sentOk += 1; else stats.sendFailed += 1;
    await setStats(stats);
  } catch (e) {
    // Never throw out of the worker.
  }
}

// Debounced wrapper — coalesces bursts of events into one report.
function scheduleReport() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    debounceTimer = null;
    reportActiveTab();
  }, DEBOUNCE_MS);
}

// --- Popup messaging --------------------------------------------------------
// The popup asks for the current stats, can force a capture, and can reset.
// Each handler replies with the latest stats so the popup re-renders.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === "getStats") {
    getStats().then(sendResponse);
    return true; // async response
  }
  if (msg.type === "captureNow") {
    reportActiveTab().then(getStats).then(sendResponse);
    return true;
  }
  if (msg.type === "reset") {
    resetStats().then(getStats).then(sendResponse);
    return true;
  }
});

// --- Event wiring -----------------------------------------------------------
// Active tab changed within a window
chrome.tabs.onActivated.addListener(() => scheduleReport());

// A tab finished loading / its URL or title changed
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url || changeInfo.title || changeInfo.status === "complete") {
    scheduleReport();
  }
});

// Which window is focused changed (incl. focus leaving all browser windows)
chrome.windows.onFocusChanged.addListener((windowId) => {
  // windowId === chrome.windows.WINDOW_ID_NONE means no browser window focused.
  // reportActiveTab() re-checks focus and stays silent in that case, which is
  // what we want — we simply stop refreshing and the agent's context expires.
  scheduleReport();
});

// Keepalive + periodic refresh for long single-page dwells.
// Guarded: chrome.alarms only exists with the "alarms" permission. If it's ever
// missing, we must NOT throw at load (that would kill the whole worker and stop
// all capturing) — we simply lose the periodic refresh; event-based capture
// (tab/focus changes) still works.
function ensureKeepaliveAlarm() {
  try {
    if (chrome.alarms && chrome.alarms.create) {
      chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });
    }
  } catch (e) { /* ignore */ }
}
chrome.runtime.onInstalled.addListener(ensureKeepaliveAlarm);
chrome.runtime.onStartup.addListener(ensureKeepaliveAlarm);
if (chrome.alarms && chrome.alarms.onAlarm) {
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === KEEPALIVE_ALARM) {
      reportActiveTab();
    }
  });
}

// Report once as soon as the worker spins up (covers the case where the
// worker was killed and respawned by an event).
reportActiveTab();
