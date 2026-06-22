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

// --- URL hygiene: strip query + fragment, keep scheme://host/path ----------
function sanitizeUrl(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    // Only report http/https. Skip edge://, chrome://, about:, file:, etc.
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    // Drop query + fragment entirely
    return `${u.protocol}//${u.host}${u.pathname}`;
  } catch (e) {
    return null;
  }
}

// --- POST to the local agent context bus ------------------------------------
async function postToAgent(payload) {
  try {
    await fetch(AGENT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      // Don't let a hung agent block the worker; bail fast.
      signal: AbortSignal.timeout ? AbortSignal.timeout(1500) : undefined,
    });
  } catch (e) {
    // Agent not running, not listening, or browser blocked it — silently
    // ignore. The desktop agent falls back to its existing behavior when no
    // context arrives. Never surface errors to the user.
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

    await postToAgent({
      source: "browser_extension",
      url: url,
      title: tab.title || "",
      window_focused: true,
      tab_focused_at: new Date().toISOString(),
    });
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
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(KEEPALIVE_ALARM, { periodInMinutes: 0.5 });
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === KEEPALIVE_ALARM) {
    reportActiveTab();
  }
});

// Report once as soon as the worker spins up (covers the case where the
// worker was killed and respawned by an event).
reportActiveTab();
