import React from "react";
import ReactDOM from "react-dom/client";
import App from "./pages/App"; // ✅ Points to merged App
import "./index.css";
import { installViewAsFetch } from "./lib/viewAs";

// MavOps "View as": patch window.fetch before anything renders, so the very
// first request of the session already carries the header. Installed
// unconditionally — it is a pass-through unless a view-as is active.
installViewAsFetch();

// Backstop for stale-chunk failures after a deploy: Vite fires this event when
// a dynamically-imported module (a lazy route chunk) fails to load. Reload once
// to pull the fresh index.html + current chunk hashes. The sessionStorage guard
// (shared with lazyWithRetry) prevents a reload loop.
window.addEventListener("vite:preloadError", () => {
  if (!window.sessionStorage.getItem("chunk-reload-attempted")) {
    window.sessionStorage.setItem("chunk-reload-attempted", "1");
    window.location.reload();
  }
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);