/*
 * TimeTracker URL Reporter — popup diagnostic panel.
 *
 * Read-only view of the counters the background worker keeps in
 * chrome.storage.local. "Capture now" forces one report; "Reset" zeroes the
 * counters. No page access, no network of its own — it only talks to the
 * background worker via chrome.runtime messaging.
 */

function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString(); }
  catch (e) { return "—"; }
}

function render(s) {
  s = s || {};
  document.getElementById("captured").textContent = s.captured || 0;
  document.getElementById("sentOk").textContent = s.sentOk || 0;
  document.getElementById("sendFailed").textContent = s.sendFailed || 0;
  document.getElementById("lastAt").textContent = fmtTime(s.lastAt);
  document.getElementById("lastUrl").textContent = s.lastUrl || "";
}

function send(type) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage({ type }, (resp) => {
        // Touch lastError so Chrome doesn't log "unchecked runtime.lastError".
        void chrome.runtime.lastError;
        resolve(resp);
      });
    } catch (e) {
      resolve(null);
    }
  });
}

document.getElementById("capture").addEventListener("click", async () => {
  render(await send("captureNow"));
});

document.getElementById("reset").addEventListener("click", async () => {
  render(await send("reset"));
});

// Initial paint.
(async () => { render(await send("getStats")); })();
