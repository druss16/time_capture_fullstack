// src/pages/onboard/OnboardConsole.tsx
// The Onboarding Console — Mavops' own tool for onboarding firms at scale.
// Standalone (no AppLayout, no org nav): it is not part of any firm's app and
// not part of Mavops admin. Access is the server's "Onboarding Operator" role.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ClipboardCheck, Loader2, Lock, Plus } from "lucide-react";
import { cn } from "@/lib/design-system";
import { onboardApi, type ProjectSummary } from "./api";
import ProjectPage from "./ProjectPage";
import {
  ErrorNote, INSTALL_PATHS, Modal, Pill, VERTICALS, daysSince, fmtDate,
  inputClass, labelClass, primaryBtnClass, secondaryBtnClass,
} from "./shared";

export default function OnboardConsole() {
  const { id } = useParams();
  const [gate, setGate] = useState<"loading" | "signin" | "denied" | "ok">("loading");
  const [who, setWho] = useState<string>("");

  useEffect(() => {
    onboardApi.me()
      .then((m) => {
        setWho(m.user?.name || "");
        setGate(!m.authenticated ? "signin" : m.is_operator ? "ok" : "denied");
      })
      .catch(() => setGate("signin"));
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 font-[Inter,system-ui,sans-serif] text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
          <Link to="/onboard" className="flex items-center gap-2 font-semibold">
            <ClipboardCheck className="h-5 w-5 text-primary" /> Onboarding Console
            <span className="hidden text-xs font-normal text-slate-400 sm:inline">Mavops internal</span>
          </Link>
          {who && <span className="text-xs text-slate-500">{who}</span>}
        </div>
      </header>
      {gate === "loading" && <div className="p-10 text-center text-sm text-slate-500">Loading…</div>}
      {gate === "signin" && (
        <Gate title="Sign in first" body="Sign in to TimeTracker with your Mavops account, then come back here.">
          <a className={primaryBtnClass} href={`/login?next=${encodeURIComponent(window.location.pathname)}`}>Sign in</a>
        </Gate>
      )}
      {gate === "denied" && (
        <Gate title="No access" body="The Onboarding Console needs the Onboarding Operator role. Being staff or a Mavops admin is not enough on its own. Ask Dan to run grant_onboarding_operator for your email." />
      )}
      {gate === "ok" && (id ? <ProjectPage id={Number(id)} /> : <Board />)}
    </div>
  );
}

function Gate({ title, body, children }: { title: string; body: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto mt-16 max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center">
      <Lock className="mx-auto h-6 w-6 text-slate-400" />
      <h1 className="mt-3 text-lg font-semibold">{title}</h1>
      <p className="mt-2 text-sm text-slate-600">{body}</p>
      {children && <div className="mt-5">{children}</div>}
    </div>
  );
}

const FILTERS = [
  { key: "open", label: "In progress" }, { key: "live", label: "Live" }, { key: "all", label: "All" },
];

function Board() {
  const [filter, setFilter] = useState("open");
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    setProjects(null);
    onboardApi.list(filter).then((r) => setProjects(r.projects)).catch((e) => setErr(e.message));
  }, [filter]);
  useEffect(load, [load]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Firms being onboarded</h1>
          <p className="mt-1 text-sm text-slate-500">Each firm's playbook as a live checklist. Steps with ⚡ tick themselves from the firm's own data.</p>
        </div>
        <button className={primaryBtnClass} onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New onboarding</button>
      </div>

      <div className="mt-5 inline-flex rounded-lg border border-slate-200 bg-white p-0.5" role="tablist">
        {FILTERS.map((f) => (
          <button key={f.key} role="tab" aria-selected={filter === f.key} onClick={() => setFilter(f.key)}
            className={cn("rounded-md px-3 py-1.5 text-sm font-medium", filter === f.key ? "bg-slate-900 text-white" : "text-slate-600 hover:text-slate-900")}>
            {f.label}
          </button>
        ))}
      </div>

      <div className="mt-4">
        <ErrorNote message={err} />
        {projects === null && !err && <div className="py-10 text-center text-sm text-slate-500">Loading…</div>}
        {projects?.length === 0 && (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
            Nothing here. Start one with <span className="font-medium text-slate-700">New onboarding</span>.
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {projects?.map((p) => <ProjectCard key={p.id} p={p} />)}
        </div>
      </div>

      {creating && <NewOnboarding onClose={() => setCreating(false)} />}
    </div>
  );
}

function ProjectCard({ p }: { p: ProjectSummary }) {
  if (p.error) {
    return <div className="rounded-2xl border border-red-200 bg-white p-4 text-sm"><div className="font-semibold">{p.org.name}</div><div className="mt-1 text-red-700">{p.error}</div></div>;
  }
  const pct = p.progress.total ? Math.round((p.progress.done / p.progress.total) * 100) : 0;
  const idle = daysSince(p.last_activity_at);
  const phase = p.phases.find((ph) => ph.key === p.current_phase);
  return (
    <Link to={`/onboard/${p.id}`} className="block rounded-2xl border border-slate-200 bg-white p-4 transition hover:border-slate-300 hover:shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold text-slate-900">{p.org.name}</div>
          <div className="mt-0.5 text-xs text-slate-500">{p.vertical_label} · {p.install_path_label}</div>
        </div>
        {p.status === "live" ? <Pill tone="green">Live</Pill> : p.status === "paused" ? <Pill tone="amber">Paused</Pill>
          : p.status === "cancelled" ? <Pill>Cancelled</Pill> : <Pill tone="blue">{phase?.title ?? "—"}</Pill>}
      </div>
      <div className="mt-4 flex gap-1" aria-label="Phases">
        {p.phases.map((ph) => (
          <div key={ph.key} title={`${ph.title}: ${ph.done ? "done" : `${ph.open} open`}`}
            className={cn("h-1.5 flex-1 rounded-full", ph.done ? "bg-emerald-500" : ph.key === p.current_phase ? "bg-sky-400" : "bg-slate-200")} />
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
        <span>{p.progress.done}/{p.progress.total} steps · {pct}%</span>
        <span className={cn(idle >= 7 && p.status === "active" && "font-medium text-amber-700")}>
          {p.target_go_live ? `go-live ${fmtDate(p.target_go_live)} · ` : ""}{idle === 0 ? "active today" : `quiet ${idle}d`}
        </span>
      </div>
    </Link>
  );
}

function NewOnboarding({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [mode, setMode] = useState<"new" | "adopt">("new");
  const [form, setForm] = useState({ name: "", vertical: "", install_path: "", seat_count: 5, target_go_live: "", org_id: "" });
  const [orgs, setOrgs] = useState<{ id: number; name: string; slug: string; industry_type: string }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { if (mode === "adopt" && orgs === null) onboardApi.adoptable().then((r) => setOrgs(r.orgs)).catch(() => setOrgs([])); }, [mode, orgs]);

  const chosenOrg = useMemo(() => orgs?.find((o) => String(o.id) === form.org_id), [orgs, form.org_id]);
  const pickVertical = (v: string) => {
    const def = VERTICALS.find((x) => x.value === v)?.defaultPath || "windows_gpo";
    setForm({ ...form, vertical: v, install_path: form.install_path || def });
  };
  const ready = form.vertical && form.install_path && (mode === "new" ? form.name.trim() : form.org_id);

  const create = async () => {
    setBusy(true); setErr(null);
    try {
      const p = await onboardApi.create(mode === "new"
        ? { name: form.name, vertical: form.vertical, install_path: form.install_path, seat_count: form.seat_count, target_go_live: form.target_go_live || null }
        : { org_id: Number(form.org_id), vertical: form.vertical, install_path: form.install_path, target_go_live: form.target_go_live || null });
      nav(`/onboard/${p.id}`);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  };

  return (
    <Modal title="New onboarding" onClose={onClose}
      subtitle="The vertical is set here, before anything is imported — the playbook adapts to it.">
      <div className="space-y-4">
        <div className="inline-flex rounded-lg border border-slate-200 p-0.5">
          {(["new", "adopt"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={cn("rounded-md px-3 py-1.5 text-sm font-medium", mode === m ? "bg-slate-900 text-white" : "text-slate-600")}>
              {m === "new" ? "New firm" : "Firm already in TimeTracker"}
            </button>
          ))}
        </div>

        {mode === "new" ? (
          <div className="grid gap-3 sm:grid-cols-[1fr_120px]">
            <div><label className={labelClass}>Firm name</label>
              <input autoFocus className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Smith & Associates CPA" /></div>
            <div><label className={labelClass}>Seats</label>
              <input type="number" min={1} className={inputClass} value={form.seat_count} onChange={(e) => setForm({ ...form, seat_count: Number(e.target.value) })} /></div>
          </div>
        ) : (
          <div><label className={labelClass}>Organization</label>
            <select className={inputClass} value={form.org_id} onChange={(e) => {
              const o = orgs?.find((x) => String(x.id) === e.target.value);
              setForm({ ...form, org_id: e.target.value, vertical: form.vertical || (o?.industry_type ?? "") });
            }}>
              <option value="">{orgs === null ? "Loading…" : "Choose a firm"}</option>
              {orgs?.map((o) => <option key={o.id} value={o.id}>{o.name} ({o.slug})</option>)}
            </select></div>
        )}

        <div>
          <label className={labelClass}>Vertical</label>
          <div className="grid gap-2 sm:grid-cols-3">
            {VERTICALS.slice(0, 3).map((v) => (
              <button key={v.value} type="button" onClick={() => pickVertical(v.value)}
                className={cn("rounded-xl border px-3 py-2.5 text-left text-sm font-medium",
                  form.vertical === v.value ? "border-primary bg-primary/5 text-slate-900" : "border-slate-200 text-slate-700 hover:border-slate-300")}>
                {v.label}
              </button>
            ))}
          </div>
          <select className={inputClass + " mt-2 py-1.5 text-xs"} value={VERTICALS.slice(3).some((v) => v.value === form.vertical) ? form.vertical : ""}
            onChange={(e) => e.target.value && pickVertical(e.target.value)}>
            <option value="">Other vertical…</option>
            {VERTICALS.slice(3).map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
          </select>
          {chosenOrg && form.vertical && chosenOrg.industry_type !== form.vertical && (
            <p className="mt-2 text-xs text-amber-700">This firm is set to "{chosenOrg.industry_type}". Starting will switch it to "{form.vertical}" — its categories and wording change.</p>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div><label className={labelClass}>How it gets installed</label>
            <select className={inputClass} value={form.install_path} onChange={(e) => setForm({ ...form, install_path: e.target.value })}>
              <option value="">Choose…</option>
              {INSTALL_PATHS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select></div>
          <div><label className={labelClass}>Target go-live (optional)</label>
            <input type="date" className={inputClass} value={form.target_go_live} onChange={(e) => setForm({ ...form, target_go_live: e.target.value })} /></div>
        </div>

        <ErrorNote message={err} />
        <div className="flex justify-end gap-2">
          <button className={secondaryBtnClass} onClick={onClose}>Cancel</button>
          <button className={primaryBtnClass} disabled={!ready || busy} onClick={create}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />} Start onboarding
          </button>
        </div>
      </div>
    </Modal>
  );
}
