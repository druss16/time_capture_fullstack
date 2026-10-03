// src/pages/onboard/ProjectPage.tsx — one firm's onboarding: the playbook as a
// live checklist, the verify_firm report, contacts, and the audit trail.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft, CheckCircle2, ChevronDown, ChevronRight, Circle, MinusCircle,
  RefreshCw, Zap,
} from "lucide-react";
import { cn } from "@/lib/design-system";
import { onboardApi, type Phase, type ProjectDetail, type Step, type VerifyResult } from "./api";
import ActionDialog from "./StepActions";
import {
  ErrorNote, INSTALL_PATHS, Pill, WHO_LABEL, fmtDate, inputClass, labelClass,
  primaryBtnClass, secondaryBtnClass,
} from "./shared";

const ACTION_LABEL: Record<string, string> = {
  import_team: "Import", import_clients: "Import", import_task_types: "Import",
  mappings: "Open grid", invites: "Setup links", token: "Issue", pair_dry_run: "Check",
  stripe: "Set up", deploy_kit: "Build kit", intake: "Intake link", derive_aliases: "Run",
  clio_trigger: "Set", go_live: "Mark live",
};

export default function ProjectPage({ id }: { id: number }) {
  const [p, setP] = useState<ProjectDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [openPhases, setOpenPhases] = useState<Record<string, boolean>>({});
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await onboardApi.get(id);
      setP(d);
      setOpenPhases((o) => (Object.keys(o).length ? o : { [d.checklist.current_phase]: true }));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, [id]);

  const runVerify = useCallback(async () => {
    setVerifying(true);
    try { setVerify(await onboardApi.verify(id)); } catch { /* panel shows stale */ } finally { setVerifying(false); }
  }, [id]);

  useEffect(() => { load(); runVerify(); }, [load, runVerify]);

  const refresh = useCallback(() => { load(); runVerify(); }, [load, runVerify]);

  if (!p) return <div className="p-10 text-center text-sm text-slate-500">{err || "Loading…"}</div>;

  const { done, total } = p.checklist.progress;
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <Link to="/onboard" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-4 w-4" /> All onboardings
      </Link>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold text-slate-900">{p.org.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-500">
            <Pill tone="blue">{p.vertical_label}</Pill>
            <span>{p.org.slug} · org #{p.org.id}</span>
            <span>· plan {p.org.plan} · {p.org.seat_count} seats</span>
            {p.status === "live" && <Pill tone="green">Live since {fmtDate(p.went_live_at)}</Pill>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Install path" className={inputClass + " !w-auto py-1.5"} value={p.install_path}
            onChange={async (e) => { await onboardApi.patch(p.id, { install_path: e.target.value }); load(); }}>
            {INSTALL_PATHS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <select aria-label="Status" className={inputClass + " !w-auto py-1.5"} value={p.status}
            onChange={async (e) => { await onboardApi.patch(p.id, { status: e.target.value }); load(); }}>
            <option value="active">Onboarding</option><option value="paused">Paused</option>
            <option value="live">Live</option><option value="cancelled">Cancelled</option>
          </select>
          <button className={secondaryBtnClass} onClick={refresh}><RefreshCw className="h-4 w-4" /> Refresh</button>
        </div>
      </div>

      <div className="mt-5">
        <div className="flex items-center justify-between text-xs font-medium text-slate-500">
          <span>{done} of {total} steps</span><span>{pct}%</span>
        </div>
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-3">
          {p.checklist.phases.map((ph) => (
            <PhaseCard key={ph.key} phase={ph} open={!!openPhases[ph.key]} current={ph.key === p.checklist.current_phase}
              onToggle={() => setOpenPhases({ ...openPhases, [ph.key]: !openPhases[ph.key] })}
              projectId={p.id} onAction={setAction} onChanged={load} />
          ))}
        </div>
        <aside className="space-y-4">
          <HealthPanel verify={verify} busy={verifying} onRun={runVerify} />
          <DetailsPanel p={p} onSaved={load} />
          <AuditPanel id={p.id} stamp={p.last_activity_at} />
        </aside>
      </div>

      {action && <ActionDialog action={action} project={p} onClose={() => setAction(null)} onChanged={refresh} />}
    </div>
  );
}

function PhaseCard({ phase, open, current, onToggle, projectId, onAction, onChanged }: {
  phase: Phase; open: boolean; current: boolean; onToggle: () => void;
  projectId: number; onAction: (a: string) => void; onChanged: () => void;
}) {
  return (
    <section className={cn("rounded-2xl border bg-white", current ? "border-primary/40 shadow-sm" : "border-slate-200")}>
      <button onClick={onToggle} aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-3.5 text-left">
        <div className="flex items-center gap-2.5">
          {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
          <span className="font-semibold text-slate-900">{phase.title}</span>
          {current && <Pill tone="blue">current</Pill>}
        </div>
        {phase.done ? <Pill tone="green">done</Pill> : <span className="text-xs font-medium text-slate-500">{phase.open} open</span>}
      </button>
      {open && (
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {phase.steps.map((s) => <StepRow key={s.key} step={s} projectId={projectId} onAction={onAction} onChanged={onChanged} />)}
        </ul>
      )}
    </section>
  );
}

function StepRow({ step, projectId, onAction, onChanged }: {
  step: Step; projectId: number; onAction: (a: string) => void; onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [note, setNote] = useState(step.note);
  const [err, setErr] = useState<string | null>(null);
  const tickable = !step.live;

  const mark = async (body: { done?: boolean; not_applicable?: boolean; note?: string }) => {
    setErr(null);
    try { await onboardApi.mark(projectId, step.key, body); onChanged(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const icon = step.not_applicable ? <MinusCircle className="h-5 w-5 text-slate-300" />
    : step.done ? <CheckCircle2 className="h-5 w-5 text-emerald-500" />
    : <Circle className="h-5 w-5 text-slate-300" />;

  return (
    <li className={cn("px-5 py-3", step.not_applicable && "opacity-60")}>
      <div className="flex items-start gap-3">
        {tickable && !step.not_applicable ? (
          <button onClick={() => mark({ done: !step.done })} aria-label={step.done ? `Untick ${step.title}` : `Tick ${step.title}`}
            className="mt-0.5 rounded-full hover:ring-4 hover:ring-slate-100">{icon}</button>
        ) : <span className="mt-0.5" title="Ticks itself from live data">{icon}</span>}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className={cn("text-sm font-medium", step.done ? "text-slate-500" : "text-slate-900")}>{step.title}</span>
            {step.live && <Zap className="h-3.5 w-3.5 text-amber-500" aria-label="Live check" />}
            {step.who !== "us" && <Pill>{WHO_LABEL[step.who]}</Pill>}
          </div>
          {(step.detail || step.error) && (
            <div className={cn("mt-0.5 text-xs", step.error ? "text-red-600" : step.done ? "text-slate-500" : "text-amber-700")}>
              {step.error ? `check failed: ${step.error}` : step.detail}
            </div>
          )}
          {step.note && !expanded && <div className="mt-1 text-xs italic text-slate-500">“{step.note}”</div>}
          {expanded && (
            <div className="mt-2 space-y-2">
              {step.help && <p className="text-sm text-slate-600">{step.help}</p>}
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                placeholder="Note (who you spoke to, what they decided…)" className={inputClass + " text-sm"} />
              <div className="flex flex-wrap gap-2">
                <button className={secondaryBtnClass + " py-1 text-xs"} onClick={() => mark({ note })}>Save note</button>
                <button className={secondaryBtnClass + " py-1 text-xs"} onClick={() => mark({ not_applicable: !step.not_applicable, note })}>
                  {step.not_applicable ? "It applies after all" : "Not applicable"}
                </button>
              </div>
              {step.marked_by && <div className="text-xs text-slate-400">Last marked by {step.marked_by} · {fmtDate(step.marked_at)}</div>}
            </div>
          )}
          <ErrorNote message={err} />
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {step.action && !step.not_applicable && (
            <button className={cn(step.done ? secondaryBtnClass : primaryBtnClass, "px-3 py-1.5 text-xs")} onClick={() => onAction(step.action)}>
              {ACTION_LABEL[step.action] || "Open"}
            </button>
          )}
          <button onClick={() => setExpanded(!expanded)} aria-label="More" aria-expanded={expanded}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} />
          </button>
        </div>
      </div>
    </li>
  );
}

function HealthPanel({ verify, busy, onRun }: { verify: VerifyResult | null; busy: boolean; onRun: () => void }) {
  const tone = { ok: "text-emerald-600", warn: "text-amber-600", bad: "text-red-600" };
  const mark = { ok: "✓", warn: "⚠", bad: "✗" };
  return (
    <section className="rounded-2xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div><div className="text-sm font-semibold text-slate-900">Health</div><div className="text-xs text-slate-500">verify_firm, live</div></div>
        <button className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100" onClick={onRun} aria-label="Re-run checks">
          <RefreshCw className={cn("h-4 w-4", busy && "animate-spin")} />
        </button>
      </div>
      {!verify ? <div className="p-4 text-sm text-slate-500">Running…</div> : (
        <div className="p-4">
          <ul className="space-y-1 font-mono text-xs">
            {verify.lines.map((l, i) => (
              <li key={i} className="flex gap-2"><span className={tone[l.state]}>{mark[l.state]}</span>
                <span className="w-28 shrink-0 text-slate-500">{l.label}</span><span className="min-w-0 break-words text-slate-800">{l.detail}</span></li>
            ))}
          </ul>
          {verify.issues.length > 0 && (
            <ul className="mt-3 space-y-1.5 border-t border-slate-100 pt-3 text-xs">
              {verify.issues.map((i, n) => <li key={n} className={tone[i.state]}><span className="font-semibold">{i.label}:</span> <span className="text-slate-700">{i.fix}</span></li>)}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

const CONTACT_ROLES: { key: string; label: string; verticals?: string[] }[] = [
  { key: "owner", label: "Firm owner / partner" },
  { key: "it_admin", label: "IT admin" },
  { key: "billing", label: "Billing contact" },
  { key: "qbo_admin", label: "QuickBooks admin", verticals: ["marketing"] },
  { key: "clio_admin", label: "Clio admin", verticals: ["legal"] },
  { key: "mac_admin", label: "Holds the Mac admin passwords", verticals: ["marketing"] },
];

function DetailsPanel({ p, onSaved }: { p: ProjectDetail; onSaved: () => void }) {
  const [contacts, setContacts] = useState(p.contacts || {});
  const [notes, setNotes] = useState(p.notes);
  const [target, setTarget] = useState(p.target_go_live || "");
  const [seats, setSeats] = useState(p.org.seat_count);
  const [billingModel, setBillingModel] = useState(p.billing_model);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const roles = CONTACT_ROLES.filter((r) => !r.verticals || r.verticals.includes(p.vertical));
  const setC = (role: string, field: string, v: string) =>
    setContacts({ ...contacts, [role]: { ...(contacts[role] || {}), [field]: v } });

  const save = async () => {
    setSaving(true); setMsg(null);
    try {
      await onboardApi.patch(p.id, { contacts, notes, target_go_live: target || null, seat_count: seats,
        ...(p.vertical === "marketing" ? { billing_model: billingModel } : {}) });
      setMsg("Saved"); onSaved();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); } finally { setSaving(false); }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold text-slate-900">Details</div>
      <div className="mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <div><label className={labelClass}>Target go-live</label>
            <input type="date" className={inputClass + " py-1.5"} value={target} onChange={(e) => setTarget(e.target.value)} /></div>
          <div><label className={labelClass}>Seats</label>
            <input type="number" min={1} className={inputClass + " py-1.5"} value={seats} onChange={(e) => setSeats(Number(e.target.value))} /></div>
        </div>
        {p.vertical === "marketing" && (
          <div><label className={labelClass}>Billing model</label>
            <select className={inputClass + " py-1.5"} value={billingModel} onChange={(e) => setBillingModel(e.target.value)}>
              <option value="">Not confirmed</option><option value="hourly">Hourly</option>
              <option value="retainer">Retainer</option><option value="mix">Mix</option>
            </select></div>
        )}
        {roles.map((r) => (
          <div key={r.key}>
            <label className={labelClass}>{r.label}</label>
            <div className="grid grid-cols-2 gap-2">
              <input className={inputClass + " py-1.5"} placeholder="Name" value={contacts[r.key]?.name || ""} onChange={(e) => setC(r.key, "name", e.target.value)} />
              <input className={inputClass + " py-1.5"} placeholder="Email" value={contacts[r.key]?.email || ""} onChange={(e) => setC(r.key, "email", e.target.value)} />
            </div>
          </div>
        ))}
        <div><label className={labelClass}>Notes</label>
          <textarea rows={3} className={inputClass + " text-sm"} value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
        <div className="flex items-center justify-end gap-2">
          {msg && <span className="text-xs text-slate-500">{msg}</span>}
          <button className={primaryBtnClass + " py-1.5"} onClick={save} disabled={saving}>Save</button>
        </div>
      </div>
    </section>
  );
}

function AuditPanel({ id, stamp }: { id: number; stamp: string }) {
  const [events, setEvents] = useState<{ action: string; detail: any; actor: any; at: string }[] | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (open) onboardApi.audit(id).then((r) => setEvents(r.events)).catch(() => setEvents([])); }, [id, open, stamp]);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between px-4 py-3 text-left">
        <span className="text-sm font-semibold text-slate-900">Activity</span>
        <ChevronDown className={cn("h-4 w-4 text-slate-400 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="max-h-80 space-y-2 overflow-auto border-t border-slate-100 px-4 py-3 text-xs">
          {events === null ? <li className="text-slate-500">Loading…</li> : events.length === 0 ? <li className="text-slate-500">Nothing yet.</li> :
            events.map((e, i) => (
              <li key={i}>
                <span className="font-medium text-slate-800">{e.action}</span>{" "}
                <span className="text-slate-500">· {e.actor?.name || "the firm (intake)"} · {new Date(e.at).toLocaleString()}</span>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}
