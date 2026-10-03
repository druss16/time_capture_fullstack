// src/pages/onboard/StepActions.tsx — the dialog behind every action step.
// Each one calls the same provisioning code the CLI runs; nothing is
// re-implemented in the browser.
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ExternalLink, Loader2, Sparkles, Upload } from "lucide-react";
import { onboardApi, type IssuedInvite, type KitFile, type ProjectDetail, type RosterRow } from "./api";
import {
  CopyButton, DownloadButton, ErrorNote, Modal, OutputLog, Pill, fmtDate,
  inputClass, labelClass, primaryBtnClass, secondaryBtnClass,
} from "./shared";

interface Props { project: ProjectDetail; onClose: () => void; onChanged: () => void; }

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function ActionDialog({ action, ...p }: Props & { action: string }) {
  switch (action) {
    case "import_team": return <ImportDialog kind="team" {...p} />;
    case "import_clients": return <ImportDialog kind="clients" {...p} />;
    case "import_task_types": return <ImportDialog kind="task_types" {...p} />;
    case "mappings": return <MappingsDialog {...p} />;
    case "invites": return <InvitesDialog {...p} />;
    case "token": return <TokenDialog {...p} />;
    case "pair_dry_run": return <PairingDialog {...p} />;
    case "stripe": return <StripeDialog {...p} />;
    case "deploy_kit": return <DeployKitDialog {...p} />;
    case "intake": return <IntakeDialog {...p} />;
    case "derive_aliases": return <AliasesDialog {...p} />;
    case "clio_trigger": return <ClioTriggerDialog {...p} />;
    case "go_live": return <GoLiveDialog {...p} />;
    default: return null;
  }
}

// ── CSV import ─────────────────────────────────────────────────────────────

const IMPORTS: Record<string, { title: string; header: string; sample: string; intakeLabel: string }> = {
  team: {
    title: "Import team",
    header: "email,display_name,role,billing_rate,cost_rate,machine_hostname,windows_username",
    sample: "jsmith@firm.com,Jane Smith,manager,175,70,FIRM-PC-101,FIRM\\jsmith",
    intakeLabel: "the team the firm entered",
  },
  clients: {
    title: "Import clients",
    header: "client_name,billing_rate,assigned_team",
    sample: "Acme Corp,175,jsmith@firm.com;mjones@firm.com",
    intakeLabel: "the clients the firm entered",
  },
  task_types: {
    title: "Import service codes",
    header: "name,code,is_billable,default_rate",
    sample: "1040 Prep,PREP1040,true,175",
    intakeLabel: "the services the firm entered",
  },
};

function ImportDialog({ kind, project, onClose, onChanged }: Props & { kind: "team" | "clients" | "task_types" }) {
  const cfg = IMPORTS[kind];
  const [csv, setCsv] = useState("");
  const [update, setUpdate] = useState(false);
  const [busy, setBusy] = useState<"" | "preview" | "commit" | "intake">("");
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; output: string; errors: string } | null>(null);
  const [previewed, setPreviewed] = useState<string | null>(null);   // the exact text that passed a dry run
  const [committed, setCommitted] = useState(false);
  const hasIntake = !!project.intake?.last_saved_at;

  const run = async (dry: boolean) => {
    setBusy(dry ? "preview" : "commit"); setErr(null);
    try {
      const r = await onboardApi.runImport(project.id, { kind, csv, dry_run: dry, update });
      setResult(r);
      if (dry) setPreviewed(r.ok ? csv : null);
      else if (r.ok) { setCommitted(true); onChanged(); }
    } catch (e) { setErr(msg(e)); } finally { setBusy(""); }
  };

  const loadIntake = async () => {
    setBusy("intake"); setErr(null);
    try { setCsv((await onboardApi.intakeCsv(project.id, kind)).csv); setResult(null); setPreviewed(null); }
    catch (e) { setErr(msg(e)); } finally { setBusy(""); }
  };

  return (
    <Modal title={cfg.title} wide onClose={onClose}
      subtitle={<>Runs <code className="text-xs">provision_firm</code> for {project.org.name}. Preview first — the preview is the importer in dry-run mode.</>}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <label className={secondaryBtnClass + " cursor-pointer"}>
            <Upload className="h-4 w-4" /> Choose CSV
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) { setCsv(await f.text()); setResult(null); setPreviewed(null); }
            }} />
          </label>
          {hasIntake && (
            <button className={secondaryBtnClass} onClick={loadIntake} disabled={!!busy}>
              {busy === "intake" && <Loader2 className="h-4 w-4 animate-spin" />} Use {cfg.intakeLabel}
            </button>
          )}
          <button className="text-xs font-medium text-slate-500 underline-offset-2 hover:underline"
            onClick={() => { setCsv(`${cfg.header}\n${cfg.sample}\n`); setPreviewed(null); }}>
            Start from the template
          </button>
        </div>
        <textarea value={csv} onChange={(e) => { setCsv(e.target.value); setPreviewed(null); }}
          rows={10} spellCheck={false} placeholder={cfg.header}
          className={inputClass + " font-mono text-xs"} />
        {kind === "team" && (
          <p className="text-xs text-slate-500">
            <code>machine_hostname</code> is required — rows without one are skipped. On a Mac it is the Local hostname
            from System Settings → General → Sharing, uppercased, without <code>.local</code>. Only give <code>owner</code> to
            the person who controls billing; cost and margin are owner-only.
          </p>
        )}
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={update} onChange={(e) => { setUpdate(e.target.checked); setPreviewed(null); }} />
          Update existing records (roles, rates, names) instead of skipping them
        </label>
        <ErrorNote message={err} />
        {result && <OutputLog text={result.output} errors={result.errors} />}
        {committed && <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">Imported. The checklist has updated.</div>}
        <div className="flex justify-end gap-2">
          <button className={secondaryBtnClass} onClick={onClose}>Close</button>
          <button className={secondaryBtnClass} disabled={!csv.trim() || !!busy} onClick={() => run(true)}>
            {busy === "preview" && <Loader2 className="h-4 w-4 animate-spin" />} Preview (dry run)
          </button>
          <button className={primaryBtnClass} disabled={previewed !== csv || !csv.trim() || !!busy || committed}
            title={previewed !== csv ? "Preview this exact file first" : undefined} onClick={() => run(false)}>
            {busy === "commit" && <Loader2 className="h-4 w-4 animate-spin" />} Import for real
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ── Category mapping grid ──────────────────────────────────────────────────

function MappingsDialog({ project, onClose, onChanged }: Props) {
  const [grid, setGrid] = useState<Awaited<ReturnType<typeof onboardApi.mappings>> | null>(null);
  const [sel, setSel] = useState<Record<string, number | "">>({});
  const [hints, setHints] = useState<Record<string, { confidence: string; reasoning: string }>>({});
  const [busy, setBusy] = useState<"" | "suggest" | "save">("");
  const [err, setErr] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    onboardApi.mappings(project.id).then((g) => {
      setGrid(g);
      setSel(Object.fromEntries(g.rows.map((r) => [r.category, r.task_type_id ?? ""])));
    }).catch((e) => setErr(msg(e)));
  }, [project.id]);

  const filled = grid ? grid.rows.filter((r) => sel[r.category]).length : 0;
  const total = grid?.rows.length ?? 0;

  const suggest = async () => {
    if (!grid) return;
    setBusy("suggest"); setErr(null);
    try {
      const s = await onboardApi.suggestMappings(project.id);
      setWarning(s.warning);
      const byCode = Object.fromEntries(grid.task_types.map((t) => [t.code, t.id]));
      const next = { ...sel };
      const h: typeof hints = {};
      for (const r of s.rows) {
        // Never overwrite a choice already on the grid with a guess.
        if (!next[r.category] && r.task_type_code && byCode[r.task_type_code]) next[r.category] = byCode[r.task_type_code];
        h[r.category] = { confidence: r.confidence, reasoning: r.reasoning };
      }
      setSel(next); setHints(h); setSaved(false);
    } catch (e) { setErr(msg(e)); } finally { setBusy(""); }
  };

  const save = async () => {
    setBusy("save"); setErr(null);
    try {
      await onboardApi.saveMappings(project.id, Object.fromEntries(
        Object.entries(sel).filter(([, v]) => v).map(([k, v]) => [k, Number(v)])));
      setSaved(true); onChanged();
    } catch (e) { setErr(msg(e)); } finally { setBusy(""); }
  };

  const term = project.terms?.task_type || "service code";
  return (
    <Modal title="Map every category" wide onClose={onClose}
      subtitle={`${total} ${project.vertical_label} categories → this firm's ${term.toLowerCase()}s. Review every row; several categories sharing one code is fine.`}>
      {!grid ? <div className="py-8 text-center text-sm text-slate-500">{err || "Loading…"}</div> : grid.task_types.length === 0 ? (
        <ErrorNote message="This firm has no service codes yet. Import them first, then map." />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm text-slate-600"><span className="font-semibold text-slate-900">{filled}/{total}</span> mapped</div>
            <button className={secondaryBtnClass} onClick={suggest} disabled={!!busy}>
              {busy === "suggest" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Fill the blanks with a draft
            </button>
          </div>
          {warning && <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{warning}</div>}
          <div className="max-h-[55vh] overflow-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Category</th><th className="px-3 py-2">{term}</th><th className="px-3 py-2">Draft</th></tr>
              </thead>
              <tbody>
                {grid.rows.map((r) => {
                  const h = hints[r.category];
                  return (
                    <tr key={r.category} className={sel[r.category] ? "border-t border-slate-100" : "border-t border-slate-100 bg-amber-50/50"}>
                      <td className="px-3 py-1.5 font-medium text-slate-800">{r.category}</td>
                      <td className="px-3 py-1.5">
                        <select aria-label={`${term} for ${r.category}`} value={sel[r.category] ?? ""}
                          onChange={(e) => { setSel({ ...sel, [r.category]: e.target.value ? Number(e.target.value) : "" }); setSaved(false); }}
                          className={inputClass + " py-1.5"}>
                          <option value="">— choose —</option>
                          {grid.task_types.map((t) => (
                            <option key={t.id} value={t.id}>{t.code} · {t.name}{t.is_billable ? "" : " (non-billable)"}</option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-1.5 text-xs text-slate-500">
                        {h && <Pill tone={h.confidence === "HIGH" ? "green" : h.confidence === "MEDIUM" ? "amber" : "red"}>{h.confidence}</Pill>}
                        {h && <span className="ml-1.5">{h.reasoning}</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <ErrorNote message={err} />
          {saved && <div className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">Saved — {total}/{total} resolve.</div>}
          <div className="flex justify-end gap-2">
            <button className={secondaryBtnClass} onClick={onClose}>Close</button>
            <button className={primaryBtnClass} disabled={filled < total || !!busy} onClick={save}
              title={filled < total ? `${total - filled} still blank` : undefined}>
              {busy === "save" && <Loader2 className="h-4 w-4 animate-spin" />} Save all {total}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── Setup links ────────────────────────────────────────────────────────────

function InvitesDialog({ project, onClose, onChanged }: Props) {
  const [roster, setRoster] = useState<RosterRow[] | null>(null);
  const [issued, setIssued] = useState<IssuedInvite[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { onboardApi.invites(project.id).then((r) => setRoster(r.roster)).catch((e) => setErr(msg(e))); }, [project.id]);
  const pending = roster?.filter((r) => !r.signed_in).length ?? 0;
  const planNone = project.org.plan === "none";

  const send = async () => {
    setBusy(true); setErr(null);
    try { const r = await onboardApi.sendInvites(project.id); setIssued(r.issued); setRoster(r.roster); onChanged(); }
    catch (e) { setErr(msg(e)); } finally { setBusy(false); }
  };

  return (
    <Modal title="Setup links" wide onClose={onClose}
      subtitle="One single-use link per person, valid 7 days. Re-sending only touches people who have never signed in.">
      <div className="space-y-4">
        {planNone && (
          <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> Plan is still "none" — people will hit the billing wall. Link Stripe first.
          </div>
        )}
        {issued && issued.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm font-semibold text-slate-900">Links issued — {issued.filter((i) => i.emailed === "yes").length} of {issued.length} emailed</div>
            <p className="text-xs text-slate-500">Each link signs in as that person. Send each one only to its owner — never the whole list in one message.</p>
            <div className="divide-y divide-slate-100 rounded-xl border border-slate-200">
              {issued.map((i) => (
                <div key={i.email} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                  <div className="min-w-0"><span className="font-medium">{i.name}</span> <span className="text-slate-500">{i.email}</span></div>
                  <div className="flex items-center gap-2">
                    <Pill tone={i.emailed === "yes" ? "green" : "amber"}>{i.emailed === "yes" ? "emailed" : "send by hand"}</Pill>
                    <CopyButton text={i.invite_url} label="Copy link" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {roster && (
          <div className="max-h-72 overflow-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Person</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">Status</th></tr>
              </thead>
              <tbody>
                {roster.map((r) => (
                  <tr key={r.email} className="border-t border-slate-100">
                    <td className="px-3 py-1.5"><div className="font-medium">{r.name}</div><div className="text-xs text-slate-500">{r.email}</div></td>
                    <td className="px-3 py-1.5 text-slate-600">{r.role}</td>
                    <td className="px-3 py-1.5">
                      {r.signed_in ? <Pill tone="green">signed in</Pill>
                        : r.link_expires ? <Pill tone="blue">link out · until {fmtDate(r.link_expires)}</Pill>
                        : <Pill tone="amber">no live link</Pill>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ErrorNote message={err} />
        <div className="flex justify-end gap-2">
          <button className={secondaryBtnClass} onClick={onClose}>Close</button>
          <button className={primaryBtnClass} onClick={send} disabled={busy || pending === 0}>
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {pending === 0 ? "Everyone has signed in" : `Issue links to ${pending} ${pending === 1 ? "person" : "people"}`}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ── Token, auto-pair, aliases, Clio trigger, go-live ───────────────────────

function TokenDialog({ project, onClose, onChanged }: Props) {
  const [tok, setTok] = useState<{ token: string; created: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    onboardApi.token(project.id).then((t) => { setTok(t); if (t.created) onChanged(); }).catch((e) => setErr(msg(e)));
  }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Modal title="Deployment token" onClose={onClose} subtitle="Baked into the install script or Mac config so devices auto-pair by hostname.">
      <ErrorNote message={err} />
      {tok && (
        <div className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3">
          <code className="text-lg font-semibold tracking-wider">{tok.token}</code>
          <div className="flex items-center gap-2">{tok.created && <Pill tone="green">new</Pill>}<CopyButton text={tok.token} /></div>
        </div>
      )}
    </Modal>
  );
}

function PairingDialog({ project, onClose }: Props) {
  const [r, setR] = useState<Awaited<ReturnType<typeof onboardApi.pairing>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => { onboardApi.pairing(project.id).then(setR).catch((e) => setErr(msg(e))); }, [project.id]);
  useEffect(load, [load]);
  return (
    <Modal title="Auto-pair dry run" wide onClose={onClose}
      subtitle="Checks the token and every hostname the way the agent will — without pairing anything, so there is nothing to reset afterwards.">
      <ErrorNote message={err} />
      {r && (
        <div className="space-y-3">
          <div className={"rounded-lg px-3 py-2 text-sm " + (r.ok ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-800")}>{r.summary}</div>
          <div className="max-h-[50vh] overflow-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Hostname</th><th className="px-3 py-2">Person</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Problems</th></tr>
              </thead>
              <tbody>
                {r.rows.map((m) => (
                  <tr key={m.hostname + m.email} className="border-t border-slate-100">
                    <td className="px-3 py-1.5 font-mono text-xs">{m.hostname || "—"}</td>
                    <td className="px-3 py-1.5">{m.display_name || m.email}</td>
                    <td className="px-3 py-1.5"><Pill tone={m.status === "paired" ? "green" : m.status === "failed" ? "red" : "slate"}>{m.status}</Pill></td>
                    <td className="px-3 py-1.5 text-xs text-red-700">{m.issues.join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-end"><button className={secondaryBtnClass} onClick={load}>Re-check</button></div>
        </div>
      )}
    </Modal>
  );
}

function AliasesDialog({ project, onClose, onChanged }: Props) {
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<{ ok: boolean; output: string; errors: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true); setErr(null);
    try { setR(await onboardApi.aliases(project.id)); onChanged(); } catch (e) { setErr(msg(e)); } finally { setBusy(false); }
  };
  return (
    <Modal title="Derive client aliases" onClose={onClose}
      subtitle="Runs derive_aliases for this firm. A client with no aliases is close to unmatchable from a window title.">
      <div className="space-y-3">
        <ErrorNote message={err} />
        {r && <OutputLog text={r.output} errors={r.errors} />}
        <div className="flex justify-end gap-2">
          <button className={secondaryBtnClass} onClick={onClose}>Close</button>
          <button className={primaryBtnClass} onClick={run} disabled={busy}>{busy && <Loader2 className="h-4 w-4 animate-spin" />} Run</button>
        </div>
      </div>
    </Modal>
  );
}

function ClioTriggerDialog({ project, onClose, onChanged }: Props) {
  const [trigger, setTrigger] = useState(project.clio_push_trigger || "approve");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    setBusy(true); setErr(null);
    try { await onboardApi.clioTrigger(project.id, trigger); onChanged(); onClose(); } catch (e) { setErr(msg(e)); } finally { setBusy(false); }
  };
  const opt = (value: string, title: string, body: string) => (
    <label className={"flex cursor-pointer gap-3 rounded-xl border p-3 " + (trigger === value ? "border-primary bg-primary/5" : "border-slate-200")}>
      <input type="radio" name="trigger" checked={trigger === value} onChange={() => setTrigger(value)} className="mt-1" />
      <div><div className="text-sm font-semibold">{title}</div><div className="text-sm text-slate-600">{body}</div></div>
    </label>
  );
  return (
    <Modal title="When does time go to Clio?" onClose={onClose} subtitle="Confirm the firm's choice out loud on the call.">
      <div className="space-y-3">
        {opt("approve", "On approve", "Time reaches Clio after a manager signs off. Right for firms that review before anything is billable.")}
        {opt("submit", "On submit", "Time reaches Clio as soon as the timekeeper submits. Right when approval is a formality.")}
        <ErrorNote message={err} />
        <div className="flex justify-end gap-2">
          <button className={secondaryBtnClass} onClick={onClose}>Cancel</button>
          <button className={primaryBtnClass} onClick={save} disabled={busy}>Save as confirmed</button>
        </div>
      </div>
    </Modal>
  );
}

function GoLiveDialog({ project, onClose, onChanged }: Props) {
  const open = project.checklist.progress.total - project.checklist.progress.done;
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={`Mark ${project.org.name} live?`} onClose={onClose}
      subtitle={open > 1 ? `${open - 1} other step(s) are still open. You can mark it live anyway; the checklist stays visible.` : "Every other step is done."}>
      <div className="flex justify-end gap-2">
        <button className={secondaryBtnClass} onClick={onClose}>Cancel</button>
        <button className={primaryBtnClass} disabled={busy}
          onClick={async () => { setBusy(true); await onboardApi.goLive(project.id).catch(() => null); onChanged(); onClose(); }}>
          Mark live
        </button>
      </div>
    </Modal>
  );
}

// ── Stripe ─────────────────────────────────────────────────────────────────

function StripeDialog({ project, onClose, onChanged }: Props) {
  const [cfg, setCfg] = useState<Awaited<ReturnType<typeof onboardApi.stripe>> | null>(null);
  const [form, setForm] = useState({ plan: "professional", interval: "monthly", seats: project.org.seat_count, coupon_months: 0, billing_email: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<{ customer: string; subscription: string } | null>(null);

  useEffect(() => {
    onboardApi.stripe(project.id).then((c) => {
      setCfg(c);
      setForm((f) => ({ ...f, seats: c.seat_count, coupon_months: c.coupon_months, billing_email: c.billing_email }));
    }).catch((e) => setErr(msg(e)));
  }, [project.id]);

  const priceOk = cfg?.prices[`${form.plan}_${form.interval}`];
  const submit = async () => {
    if (!window.confirm(`Create a real Stripe subscription for ${project.org.name}: ${form.seats} × ${form.plan} (${form.interval})${form.coupon_months ? `, ${form.coupon_months} months free` : ""}? Stripe will send the invoice to ${form.billing_email}.`)) return;
    setBusy(true); setErr(null);
    try { setDone(await onboardApi.setupStripe(project.id, form)); onChanged(); } catch (e) { setErr(msg(e)); } finally { setBusy(false); }
  };

  return (
    <Modal title="Stripe" onClose={onClose}
      subtitle="Coupon → customer → subscription (send invoice) → linked to the org. One action instead of four dashboard screens and a shell snippet.">
      {!cfg ? <div className="py-6 text-center text-sm text-slate-500">{err || "Loading…"}</div> : cfg.linked || done ? (
        <div className="space-y-2 text-sm">
          <div className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">Linked — {project.org.name} is on {done ? form.plan : cfg.plan}.</div>
          <div className="text-slate-600">Customer <code>{done?.customer || cfg.customer}</code> · Subscription <code>{done?.subscription || cfg.subscription}</code></div>
          <a className="inline-flex items-center gap-1 text-sm font-medium text-primary" target="_blank" rel="noreferrer"
             href={`https://dashboard.stripe.com/subscriptions/${done?.subscription || cfg.subscription}`}>Open in Stripe <ExternalLink className="h-3.5 w-3.5" /></a>
        </div>
      ) : (
        <div className="space-y-4">
          {!cfg.key_configured && <ErrorNote message="STRIPE_SECRET_KEY is not set on this server." />}
          <div className="grid grid-cols-2 gap-3">
            <div><label className={labelClass}>Plan</label>
              <select className={inputClass} value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })}>
                <option value="professional">Professional</option><option value="executive">Executive</option>
              </select></div>
            <div><label className={labelClass}>Billing</label>
              <select className={inputClass} value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })}>
                <option value="monthly">Monthly</option><option value="yearly">Yearly</option>
              </select></div>
            <div><label className={labelClass}>Seats</label>
              <input type="number" min={1} className={inputClass} value={form.seats} onChange={(e) => setForm({ ...form, seats: Number(e.target.value) })} /></div>
            <div><label className={labelClass}>Free months (coupon)</label>
              <input type="number" min={0} className={inputClass} value={form.coupon_months} onChange={(e) => setForm({ ...form, coupon_months: Number(e.target.value) })} /></div>
            <div className="col-span-2"><label className={labelClass}>Billing contact email</label>
              <input type="email" className={inputClass} value={form.billing_email} onChange={(e) => setForm({ ...form, billing_email: e.target.value })} /></div>
          </div>
          {cfg.key_configured && !priceOk && <ErrorNote message={`No Stripe price configured for ${form.plan} ${form.interval}.`} />}
          <ErrorNote message={err} />
          <div className="flex justify-end gap-2">
            <button className={secondaryBtnClass} onClick={onClose}>Cancel</button>
            <button className={primaryBtnClass} onClick={submit} disabled={busy || !cfg.key_configured || !priceOk || !form.billing_email || form.seats < 1}>
              {busy && <Loader2 className="h-4 w-4 animate-spin" />} Create subscription
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── Deployment kit ─────────────────────────────────────────────────────────

function DeployKitDialog({ project, onClose, onChanged }: Props) {
  const [kit, setKit] = useState<{ token: string; files: KitFile[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    onboardApi.deployKit(project.id).then((k) => { setKit(k); onChanged(); }).catch((e) => setErr(msg(e)));
  }, [project.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Modal title="Deployment kit" wide onClose={onClose}
      subtitle={<>Everything IT needs for {project.install_path_label}, filled in with token <code>{kit?.token ?? "…"}</code>.</>}>
      <ErrorNote message={err} />
      {kit && (
        <div className="space-y-2">
          {kit.files.map((f) => (
            <div key={f.name} className="rounded-xl border border-slate-200">
              <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                <div className="min-w-0"><div className="font-mono text-sm font-medium">{f.name}</div><div className="text-xs text-slate-500">{f.note}</div></div>
                <div className="flex items-center gap-2">
                  {f.url && <a href={f.url} className={secondaryBtnClass + " py-1 text-xs"} target="_blank" rel="noreferrer"><ExternalLink className="h-3.5 w-3.5" /> Latest release</a>}
                  {f.content && <>
                    <button className="text-xs font-medium text-slate-500 hover:text-slate-800" onClick={() => setOpen(open === f.name ? null : f.name)}>{open === f.name ? "Hide" : "View"}</button>
                    <CopyButton text={f.content} />
                    <DownloadButton name={f.name} content={f.content} />
                  </>}
                </div>
              </div>
              {open === f.name && f.content && <div className="border-t border-slate-100 p-3"><OutputLog text={f.content} /></div>}
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}

const ANSWER_LABEL: Record<string, string> = {
  billing_model: "Charges by", rate_source: "Rate comes from", clio_push_trigger: "Push to Clio on",
  email_billable: "Bills client email", clients_source: "Clients", notes: "Notes",
};

// ── Intake link ────────────────────────────────────────────────────────────

function IntakeDialog({ project, onClose, onChanged }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const intake = project.intake;
  const payload = intake?.payload || {};
  const counts = useMemo(() => ({
    team: (payload.team || []).length, services: (payload.services || []).length, clients: (payload.clients || []).length,
  }), [payload]);

  const issue = async (reopen: boolean) => {
    setBusy(true); setErr(null);
    try { const r = reopen ? await onboardApi.reopenIntake(project.id) : await onboardApi.issueIntake(project.id); setUrl(r.url || null); onChanged(); }
    catch (e) { setErr(msg(e)); } finally { setBusy(false); }
  };

  return (
    <Modal title="Firm intake" onClose={onClose}
      subtitle="One link for the firm: contacts, team, services, and the decisions this playbook needs. No login on their side.">
      <div className="space-y-4">
        {intake ? (
          <div className="rounded-xl border border-slate-200 p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              {intake.submitted_at ? <Pill tone="green">Submitted {fmtDate(intake.submitted_at)}</Pill>
                : intake.is_open ? <Pill tone="blue">Open until {fmtDate(intake.expires_at)}</Pill>
                : <Pill tone="amber">Expired or replaced</Pill>}
              {intake.last_saved_at && !intake.submitted_at && <Pill>Last saved {fmtDate(intake.last_saved_at)}</Pill>}
            </div>
            {intake.last_saved_at && (
              <div className="mt-3 text-slate-600">
                {counts.team} people · {counts.services} services · {counts.clients} clients. Import them from the Team / Services / Clients steps — "Use what the firm entered".
              </div>
            )}
            {Object.entries(payload.answers || {}).filter(([, v]) => v !== "" && v !== null).length > 0 && (
              <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-slate-100 pt-3 text-xs">
                {Object.entries(payload.answers || {}).filter(([, v]) => v !== "" && v !== null).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-slate-500">{ANSWER_LABEL[k] || k}</dt>
                    <dd className="whitespace-pre-wrap text-slate-800">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        ) : <p className="text-sm text-slate-600">No link issued yet.</p>}

        {url && (
          <div className="space-y-1.5 rounded-xl border border-emerald-200 bg-emerald-50 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">New link — shown once</div>
            <div className="flex items-center gap-2"><code className="min-w-0 flex-1 truncate text-xs">{url}</code><CopyButton text={url} /></div>
            <div className="text-xs text-emerald-800">Any earlier open link stops working. Answers carry over.</div>
          </div>
        )}
        <ErrorNote message={err} />
        <div className="flex flex-wrap justify-end gap-2">
          <button className={secondaryBtnClass} onClick={onClose}>Close</button>
          {intake?.submitted_at
            ? <button className={primaryBtnClass} disabled={busy} onClick={() => issue(true)}>Reopen for edits (new link)</button>
            : <button className={primaryBtnClass} disabled={busy} onClick={() => issue(false)}>{intake ? "Issue a new link" : "Create intake link"}</button>}
        </div>
      </div>
    </Modal>
  );
}
