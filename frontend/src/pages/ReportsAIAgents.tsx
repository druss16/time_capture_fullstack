/**
 * Reports → AI agent activity  (/reports/ai-agents)
 *
 * The firm owner's view of the desktop agent's agent-presence measurement:
 * which AI agents the firm uses, how long they worked, and the hours the
 * tracker booked to a person while nobody's hands were on the machine.
 *
 * Its own numbers on its own page — never added to Time Summary, timesheets,
 * billing or analytics. Owners only, and hidden per firm until MavOps turns it
 * on; the server answers 404/403 otherwise and this page says so.
 *
 * "It was me" / "It was an agent" are RECORD ONLY: they shrink the list and
 * grade the measurement. They never move a minute of anyone's time.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Info, Lock, ArrowLeft, Bot, Undo2, ChevronDown, ChevronRight } from "lucide-react";
import { API_BASE } from "@/lib/api";

// Same "Lightning" tokens as ReportsSummary, so the Reports pages read as one.
const INTER = { fontFamily: '"Inter", sans-serif' } as const;
const GROUND = "#eef4f3";
const LANE_CARD =
  "overflow-hidden rounded-[15px] border border-border/70 bg-white shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)]";
const EYEBROW = "text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400";
const CONTROL =
  "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-border/60 bg-white/70 text-slate-600 hover:bg-white hover:text-slate-800 transition-colors";

interface ToolRow { tool: string; name: string; people: number; working_hours: number | null; last_seen: string | null }
interface ReviewRow {
  sample_id: number; kind: "mac" | "windows"; person: string; hour_start: string;
  minutes?: number; clicks?: number; app: string; evidence: string; verdict: "human" | "agent" | null;
}
interface Report {
  days: number; org_name: string; devices_reporting: number;
  tiles: { agent_working_hours: number; review_hours: number; to_review: number;
           agents_in_use: number; people_using: number; people_total: number };
  tools: ToolRow[]; review: ReviewRow[]; explained_hours: number;
}

function getAuthToken(): string | null {
  return localStorage.getItem("auth_token") || localStorage.getItem("tt_auth_token")
    || localStorage.getItem("authToken") || localStorage.getItem("token");
}

function orgParam(): string {
  const imp = localStorage.getItem("impersonating_org_id");
  return imp ? `&org_id=${imp}` : "";
}

const appName = (a: string) => (a ? a.charAt(0).toUpperCase() + a.slice(1) : "an app");

function hourLabel(iso: string) {
  const start = new Date(iso);
  const end = new Date(start.getTime() + 3600e3);
  const day = start.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const t = (d: Date) => d.toLocaleTimeString(undefined, { hour: "numeric" });
  return `${day} · ${t(start)}–${t(end)}`;
}

function ago(iso: string | null) {
  if (!iso) return "—";
  const h = (Date.now() - new Date(iso).getTime()) / 3600e3;
  if (h < 24) return "today";
  if (h < 48) return "yesterday";
  return `${Math.floor(h / 24)} days ago`;
}

function Tile({ label, value, sub, warn = false }: { label: string; value: string; sub: string; warn?: boolean }) {
  return (
    <div className="rounded-xl bg-white border border-border/60 px-4 py-3">
      <div className="text-[12px] text-slate-500">{label}</div>
      <div className={`text-[22px] font-bold tabular-nums ${warn ? "text-amber-600" : "text-slate-900"}`}>{value}</div>
      <div className="text-[11.5px] text-slate-400">{sub}</div>
    </div>
  );
}

export default function ReportsAIAgents() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<Report | null>(null);
  const [status, setStatus] = useState<"loading" | "ok" | "hidden" | "owners" | "error">("loading");
  const [showExplained, setShowExplained] = useState(false);
  const [saving, setSaving] = useState<number | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    const token = getAuthToken();
    try {
      const res = await fetch(`${API_BASE}/reports/ai-agents/?days=${days}${orgParam()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: "include",
      });
      if (res.status === 404) return setStatus("hidden");
      if (res.status === 403) return setStatus("owners");
      if (!res.ok) throw new Error(String(res.status));
      setData(await res.json());
      setStatus("ok");
    } catch {
      setStatus("error");
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const answer = async (row: ReviewRow, verdict: "human" | "agent" | "clear") => {
    setSaving(row.sample_id);
    const token = getAuthToken();
    try {
      const res = await fetch(`${API_BASE}/reports/ai-agents/review/?${orgParam().slice(1)}`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ sample_id: row.sample_id, verdict }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const v = verdict === "clear" ? null : verdict;
      setData(d => d && {
        ...d,
        review: d.review.map(r => r.sample_id === row.sample_id ? { ...r, verdict: v } : r),
        tiles: { ...d.tiles, to_review: d.tiles.to_review + (row.verdict ? 0 : -1) + (v ? 0 : 1) },
      });
    } catch {
      setStatus("error");
    } finally {
      setSaving(null);
    }
  };

  const open = data?.review.filter(r => !r.verdict) ?? [];
  const answered = data?.review.filter(r => r.verdict) ?? [];

  return (
    <div className="mx-auto w-full max-w-[1120px] my-6 rounded-2xl p-4 sm:p-6 space-y-5" style={{ ...INTER, backgroundColor: GROUND }}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link to="/reports" className={`${EYEBROW} inline-flex items-center gap-1 hover:text-slate-600`}>
            <ArrowLeft className="h-3 w-3" /> Reports
          </Link>
          <h1 className="mt-1.5 text-[22px] font-bold tracking-[-0.01em] text-slate-900 flex items-center gap-2">
            <Bot className="h-5 w-5 text-slate-500" /> AI agent activity
          </h1>
          {data && <p className="text-[12.5px] text-slate-500 mt-1">{data.org_name} · last {data.days} days · {data.devices_reporting} computers reporting</p>}
        </div>
        <select value={days} onChange={e => setDays(Number(e.target.value))} className={CONTROL} aria-label="Timeframe">
          {[7, 14, 30, 90].map(d => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>

      <div className="flex items-start gap-2 rounded-xl bg-sky-50 border border-sky-100 px-3.5 py-2.5 text-[13px] text-sky-800">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <span>Kept separate from your team's time. Nothing on this page changes timesheets, reports or billing.</span>
      </div>

      {status === "loading" && <div className="flex items-center gap-2 text-slate-500 text-sm py-10 justify-center"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>}
      {status === "hidden" && <div className={`${LANE_CARD} p-8 text-center text-slate-500 text-sm`}>This report isn't turned on for your firm yet.</div>}
      {status === "owners" && <div className={`${LANE_CARD} p-8 text-center text-slate-500 text-sm`}>AI agent activity is visible to firm owners only.</div>}
      {status === "error" && <div className={`${LANE_CARD} p-8 text-center text-slate-500 text-sm`}>Couldn't load this report. <button onClick={load} className="underline">Try again</button></div>}

      {status === "ok" && data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Tile label="Agent work" value={`${data.tiles.agent_working_hours} h`} sub="agents confirmed working" />
            <Tile label="Time to review" value={`${data.tiles.review_hours} h`} sub="booked to people, no hands" warn={data.tiles.review_hours > 0} />
            <Tile label="Agents in use" value={String(data.tiles.agents_in_use)} sub="tools across the firm" />
            <Tile label="People using agents" value={`${data.tiles.people_using} of ${data.tiles.people_total}`} sub="on any computer" />
          </div>

          <section className={LANE_CARD}>
            <div className="px-4 py-3 border-b border-border/60 text-[14px] font-semibold text-slate-800">Agents in use</div>
            {data.tools.length === 0 ? (
              <div className="px-4 py-6 text-sm text-slate-500">No AI agents seen in this period.</div>
            ) : (
              <table className="w-full text-[13px]">
                <thead><tr className="text-left text-[11.5px] text-slate-400">
                  <th className="px-4 py-2 font-medium">Tool</th><th className="px-4 py-2 font-medium">People</th>
                  <th className="px-4 py-2 font-medium">Working</th><th className="px-4 py-2 font-medium">Last seen</th>
                </tr></thead>
                <tbody>
                  {data.tools.map(t => (
                    <tr key={t.tool} className="border-t border-border/50">
                      <td className="px-4 py-2.5 text-slate-800">{t.name}</td>
                      <td className="px-4 py-2.5 tabular-nums text-slate-600">{t.people}</td>
                      <td className="px-4 py-2.5 tabular-nums text-slate-600">
                        {t.working_hours === null ? <span className="text-slate-400" title="Desktop apps use CPU just by being open, so we can't tell when they're working">open only</span> : `${t.working_hours} h`}
                      </td>
                      <td className="px-4 py-2.5 text-slate-500">{ago(t.last_seen)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className={LANE_CARD}>
            <div className="px-4 py-3 border-b border-border/60">
              <div className="text-[14px] font-semibold text-slate-800">Time to review <span className="ml-1 text-slate-400 font-normal tabular-nums">{open.length}</span></div>
              <div className="text-[12.5px] text-slate-500">Counted as someone working, but nobody touched the keyboard or mouse. Your answer is only recorded — it doesn't change anyone's time.</div>
            </div>
            {open.length === 0 && <div className="px-4 py-6 text-sm text-slate-500">Nothing to review.</div>}
            {open.map(r => (
              <div key={r.sample_id} className="flex flex-wrap items-center gap-3 px-4 py-3 border-t border-border/50 first:border-t-0">
                <div className="flex-1 min-w-[220px]">
                  <div className="text-[13.5px] font-semibold text-slate-800">{r.person} · {hourLabel(r.hour_start)}</div>
                  <div className="text-[12.5px] text-slate-500">
                    {r.kind === "mac" ? `${r.minutes} min in ${appName(r.app)}` : `${r.clicks} simulated clicks in ${appName(r.app)}`}
                    {" · "}
                    <span className={r.evidence.endsWith("working") ? "text-amber-700" : "text-slate-400"}>{r.evidence}</span>
                  </div>
                </div>
                <button disabled={saving === r.sample_id} onClick={() => answer(r, "human")} className={CONTROL}>It was a person</button>
                <button disabled={saving === r.sample_id} onClick={() => answer(r, "agent")} className={CONTROL}>It was an agent</button>
              </div>
            ))}
            {answered.length > 0 && (
              <div className="border-t border-border/60 bg-slate-50/60">
                {answered.map(r => (
                  <div key={r.sample_id} className="flex items-center gap-3 px-4 py-2 text-[12.5px] text-slate-500">
                    <span className="flex-1">{r.person} · {hourLabel(r.hour_start)} — marked <b className="text-slate-700">{r.verdict === "agent" ? "an agent" : "a person"}</b></span>
                    <button onClick={() => answer(r, "clear")} className="inline-flex items-center gap-1 hover:text-slate-800"><Undo2 className="h-3 w-3" /> Undo</button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <button onClick={() => setShowExplained(v => !v)} className="w-full text-left flex items-center gap-2 rounded-xl bg-white/70 border border-border/60 px-4 py-2.5 text-[13px] text-slate-600">
            {showExplained ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            {data.explained_hours} h left out because a person was working through remote desktop, Universal Control, Sidecar or a drawing tablet
          </button>
          {showExplained && (
            <div className="rounded-xl bg-white/70 border border-border/60 px-4 py-3 text-[12.5px] text-slate-500 -mt-3">
              When someone works through remote-control software, another device or a tablet driver, their input looks like software too. We recognise those tools and never count that time here.
            </div>
          )}

          <div className="flex items-center gap-1.5 text-[12px] text-slate-400"><Lock className="h-3 w-3" /> We record app names and counts only — never screens, keystrokes or what anyone typed.</div>
        </>
      )}
    </div>
  );
}
