/**
 * People | AI agents — the switch at the top of Reports.
 *
 * Two views, never a blend: there is deliberately no "both" option, because
 * agent hours must never be added into human totals. The toggle only renders
 * when the AI agent report is available to this user (firm owner, and MavOps
 * has switched it on for the firm); everyone else sees Reports as before.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bot, Users } from "lucide-react";
import { API_BASE } from "@/lib/api";

function getAuthToken(): string | null {
  return localStorage.getItem("auth_token") || localStorage.getItem("tt_auth_token")
    || localStorage.getItem("authToken") || localStorage.getItem("token");
}

/** Whether this user can see Reports → AI agents. False until the server says yes. */
export function useAiAgentsReportAvailable(): boolean {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    const token = getAuthToken();
    const imp = localStorage.getItem("impersonating_org_id");
    fetch(`${API_BASE}/reports/ai-agents/status/${imp ? `?org_id=${imp}` : ""}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: "include",
    })
      .then(r => (r.ok ? r.json() : { available: false }))
      .then(d => setAvailable(Boolean(d.available)))
      .catch(() => setAvailable(false));
  }, []);
  return available;
}

const SEG = "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md transition-colors";

export default function ReportsViewToggle({ active }: { active: "people" | "agents" }) {
  const item = (to: string, key: "people" | "agents", icon: JSX.Element, label: string) => (
    <Link
      to={to}
      aria-current={active === key ? "page" : undefined}
      className={`${SEG} ${active === key
        ? "bg-white text-slate-900 shadow-[0_1px_2px_rgba(16,27,46,0.12)]"
        : "text-slate-500 hover:text-slate-800"}`}
    >
      {icon} {label}
    </Link>
  );
  return (
    <nav aria-label="Report view"
      className="inline-flex items-center gap-0.5 rounded-lg border border-border/60 bg-slate-100/70 p-0.5">
      {item("/reports", "people", <Users className="h-3.5 w-3.5" />, "People")}
      {item("/reports/ai-agents", "agents", <Bot className="h-3.5 w-3.5" />, "AI agents")}
    </nav>
  );
}
