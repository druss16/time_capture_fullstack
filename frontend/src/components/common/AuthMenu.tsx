import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

const BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api").replace(/\/+$/,"");

export default function AuthMenu() {
  const [username, setUsername] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const r = await fetch(`${BASE}/whoami/`, { credentials: "include" });
      const j = r.ok ? await r.json() : { username: "" };
      setUsername(j?.username || "");
    } catch { setUsername(""); }
  }

  async function logout() {
    setBusy(true);
    try {
      await fetch(`${BASE}/auth/logout/`, { method: "POST", credentials: "include" });
    } finally {
      setBusy(false);
      refresh();
    }
  }

  useEffect(() => { refresh(); }, []);

  if (!username) {
    return (
      <Link className="px-3 py-1 border rounded hover:bg-accent/20" to="/login">
        Login
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <button
        className="px-3 py-1 border rounded hover:bg-accent/20"
        onClick={() => window.dispatchEvent(new CustomEvent("open-pair-modal"))}
        title="Pair your Mac agent"
      >
        Pair Device
      </button>
      <div className="px-3 py-1 rounded bg-primary/10 border border-primary/30">{username}</div>
      <button className="px-3 py-1 hover:bg-muted border rounded" onClick={logout} disabled={busy}>
        {busy ? "…" : "Logout"}
      </button>
    </div>
  );
}