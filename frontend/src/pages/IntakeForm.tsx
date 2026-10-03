// src/pages/IntakeForm.tsx — the firm's side of onboarding, at /intake/:token.
// Replaces the emailed intake doc and the spreadsheet chase. No login: the
// link is single-use, hashed server-side, and can only read and write these
// answers. Saves as a draft so several people at the firm can fill it in.
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { CheckCircle2, ClipboardPaste, Loader2, Plus, Trash2 } from "lucide-react";
import { intakeRequest } from "./onboard/api";
import { inputClass, labelClass, primaryBtnClass, secondaryBtnClass } from "./settings/ui";

type Row = Record<string, string | boolean>;
interface Answers {
  contacts: Record<string, Record<string, string>>;
  team: Row[]; services: Row[]; clients: Row[];
  answers: Record<string, string | boolean>;
}
interface Meta {
  firm: string; vertical: string; install_path: string; terms: Record<string, string>;
  answers: Partial<Answers>; submitted_at: string | null; editable: boolean;
}

const EMPTY: Answers = { contacts: {}, team: [], services: [], clients: [], answers: {} };

interface Col { key: string; label: string; placeholder?: string; type?: "text" | "email" | "number" | "select" | "bool"; options?: [string, string][]; width?: string; }

export default function IntakeForm() {
  const { token = "" } = useParams();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [a, setA] = useState<Answers>(EMPTY);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState<"" | "save" | "submit">("");
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const dirty = useRef(false);

  useEffect(() => {
    intakeRequest(token).then((m: Meta) => { setMeta(m); setA({ ...EMPTY, ...m.answers } as Answers); })
      .catch((e) => setErr(e.message));
  }, [token]);

  const update = (next: Answers) => { setA(next); dirty.current = true; };

  const save = useCallback(async (submit = false) => {
    setSaving(submit ? "submit" : "save"); setErr(null);
    try {
      const m: Meta = await intakeRequest(token, { answers: a, submit });
      setMeta(m); setSavedAt(new Date()); dirty.current = false;
      if (submit) window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setSaving(""); }
  }, [a, token]);

  // Quiet autosave so a half-finished form survives a closed tab.
  useEffect(() => {
    const t = setInterval(() => { if (dirty.current && meta?.editable) save(false); }, 30_000);
    return () => clearInterval(t);
  }, [save, meta?.editable]);

  if (!meta) {
    return <Shell><div className="py-20 text-center text-sm text-slate-600">{err || "Loading…"}</div></Shell>;
  }

  const v = meta.vertical;
  const mac = meta.install_path.startsWith("mac");
  const autoPair = meta.install_path === "windows_gpo" || meta.install_path === "mac_mdm";
  const ro = !meta.editable;
  const tt = meta.terms.task_types || "Services";
  const clientsWord = meta.terms.clients || "Clients";
  const set = (patch: Partial<Answers>) => update({ ...a, ...patch });
  const setAns = (k: string, val: string | boolean) => set({ answers: { ...a.answers, [k]: val } });

  const contactRoles: [string, string, string][] = [
    ["owner", "Owner / managing partner", "Decides who controls billing and sees cost & margin."],
    ["billing", "Billing contact", "Receives the TimeTracker invoice."],
    ...(autoPair ? [["it_admin", "IT admin", "Deploys the app to everyone's computer."] as [string, string, string]] : []),
    ...(v === "marketing" ? [["qbo_admin", "QuickBooks Online admin", "Approves the QuickBooks connection once (about 10 minutes)."] as [string, string, string]] : []),
    ...(v === "legal" ? [["clio_admin", "Clio admin", "Connects Clio once so clients and matters come across."] as [string, string, string]] : []),
    ...(mac ? [["mac_admin", "Who holds the Mac admin password(s)", "Needed for about 5 minutes per Mac on install day. Just tell us who — never send the password."] as [string, string, string]] : []),
  ];

  const teamCols: Col[] = [
    { key: "email", label: "Work email", type: "email", placeholder: "jane@firm.com", width: "w-52" },
    { key: "display_name", label: "Name", placeholder: "Jane Smith", width: "w-40" },
    { key: "role", label: "Access", type: "select", width: "w-32", options: [["member", "Member"], ["manager", "Manager"], ["admin", "Admin"], ["owner", "Owner"]] },
    { key: "billing_rate", label: "Bill rate $/h", type: "number", width: "w-24" },
    { key: "cost_rate", label: "Cost $/h (optional)", type: "number", width: "w-24" },
    { key: "machine_hostname", label: mac ? "Mac's Local hostname" : "Computer name", placeholder: mac ? "Janes-MacBook-Pro" : "FIRM-PC-101", width: "w-44" },
    ...(meta.install_path === "windows_gpo" ? [{ key: "windows_username", label: "Windows login", placeholder: "FIRM\\jsmith", width: "w-36" }] : []),
    ...(v === "marketing" ? [{ key: "department", label: "Department", placeholder: "Creative", width: "w-32" }] : []),
    ...(mac ? [{ key: "mac_chip", label: "Mac chip", type: "select" as const, width: "w-32", options: [["", "—"], ["apple", "M1 or later"], ["intel", "Intel"], ["unsure", "Not sure"]] as [string, string][] }] : []),
  ];
  const serviceCols: Col[] = [
    { key: "name", label: "Name", placeholder: v === "legal" ? "Legal Research" : v === "marketing" ? "Graphic Design" : "1040 Prep", width: "w-56" },
    { key: "code", label: "Code (if you have one)", placeholder: v === "cpa" ? "PREP1040" : "", width: "w-32" },
    { key: "is_billable", label: "Billable", type: "bool", width: "w-20" },
    { key: "default_rate", label: "Rate $/h", type: "number", width: "w-24" },
  ];
  const clientCols: Col[] = [
    { key: "client_name", label: "Name", width: "w-72" },
    { key: "billing_rate", label: "Rate $/h", type: "number", width: "w-24" },
  ];

  const intelCount = a.team.filter((r) => r.mac_chip === "intel").length;
  const clientSource = (a.answers.clients_source as string) || "";
  const pullFrom = v === "legal" ? "Clio" : v === "marketing" ? "QuickBooks Online" : "our practice-management system";

  return (
    <Shell firm={meta.firm}>
      {meta.submitted_at && (
        <div className="flex items-start gap-3 rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <div>
            <div className="font-semibold text-emerald-900">Thank you — this is with Mavops now.</div>
            <div className="mt-1 text-sm text-emerald-800">We'll be in touch about install day. Need to change something? Ask us for an edit link; your answers are kept.</div>
          </div>
        </div>
      )}

      <Section n={1} title="Who we'll work with" sub="A few names so we email the right person at each step.">
        <div className="space-y-4">
          {contactRoles.map(([key, label, help]) => (
            <div key={key}>
              <div className="text-sm font-medium text-slate-800">{label}</div>
              <div className="mb-1.5 text-xs text-slate-500">{help}</div>
              <div className="grid gap-2 sm:grid-cols-3">
                {(["name", "email", "phone"] as const).map((f) => (
                  <input key={f} disabled={ro} aria-label={`${label} ${f}`} placeholder={f === "name" ? "Name" : f === "email" ? "Email" : "Phone (optional)"}
                    className={inputClass} value={a.contacts[key]?.[f] || ""}
                    onChange={(e) => set({ contacts: { ...a.contacts, [key]: { ...(a.contacts[key] || {}), [f]: e.target.value } } })} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section n={2} title="Your team" sub={<>Everyone who should track time. {mac
        ? <>On each Mac the hostname is in <b>System Settings → General → Sharing → Local hostname</b> (without “.local”). TimeTracker needs an Apple-chip Mac (M1 or later).</>
        : <>The computer name is in <b>Settings → System → About → Device name</b>.</>}</>}>
        <RowsEditor cols={teamCols} rows={a.team} disabled={ro} onChange={(team) => set({ team })} addLabel="Add a person" />
        {intelCount > 0 && (
          <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {intelCount} Intel Mac{intelCount > 1 ? "s" : ""}: TimeTracker can't run on Intel Macs yet. We'll talk about options.
          </p>
        )}
      </Section>

      <Section n={3} title={`Your ${tt.toLowerCase()}`} sub={v === "cpa"
        ? "Your service codes — an export from CCH Axcess or your practice system is perfect. Time comes back described in your words."
        : v === "legal" ? "Your activity types / rate codes, as in Clio."
        : "What you invoice for — usually your QuickBooks Products & Services."}>
        <RowsEditor cols={serviceCols} rows={a.services} disabled={ro} onChange={(services) => set({ services })} addLabel="Add one"
          newRow={{ is_billable: true }} />
      </Section>

      <Section n={4} title={`Your ${clientsWord.toLowerCase()}`} sub="If they already live in another system, we pull them from there — retyping a list is how duplicates happen.">
        <div className="space-y-2">
          {[["pull", `Pull them from ${pullFrom}`], ["list", "We'll list them here"], ["file", "We'll send a file"]].map(([val, label]) => (
            <label key={val} className="flex items-center gap-2 text-sm">
              <input type="radio" name="clients_source" disabled={ro} checked={clientSource === val} onChange={() => setAns("clients_source", val)} /> {label}
            </label>
          ))}
        </div>
        {clientSource === "list" && (
          <div className="mt-3"><RowsEditor cols={clientCols} rows={a.clients} disabled={ro} onChange={(clients) => set({ clients })} addLabel="Add one" /></div>
        )}
      </Section>

      {(v === "marketing" || v === "legal") && (
        <Section n={5} title="A couple of decisions">
          {v === "marketing" && (
            <div className="space-y-4">
              <Choice label="How do you charge clients?" name="billing_model" value={a.answers.billing_model as string} disabled={ro}
                options={[["hourly", "Hourly"], ["retainer", "Monthly retainer"], ["mix", "A mix"]]} onChange={(x) => setAns("billing_model", x)} />
              <Choice label="Where does an hourly rate come from?" name="rate_source" value={a.answers.rate_source as string} disabled={ro}
                options={[["person", "The person"], ["service", "The service"], ["client", "The client"]]} onChange={(x) => setAns("rate_source", x)} />
            </div>
          )}
          {v === "legal" && (
            <div className="space-y-4">
              <Choice label="When should time go into Clio?" name="clio_push_trigger" value={a.answers.clio_push_trigger as string} disabled={ro}
                options={[["approve", "After a manager approves it"], ["submit", "As soon as the timekeeper submits"]]} onChange={(x) => setAns("clio_push_trigger", x)} />
              <Choice label="Do you bill client email?" name="email_billable" value={a.answers.email_billable as string} disabled={ro}
                options={[["yes", "Yes"], ["no", "No"]]} onChange={(x) => setAns("email_billable", x)} />
            </div>
          )}
        </Section>
      )}

      <Section n={(v === "marketing" || v === "legal") ? 6 : 5} title="Anything else?">
        <textarea rows={4} disabled={ro} className={inputClass} placeholder="Folder conventions, naming habits, people starting soon…"
          value={(a.answers.notes as string) || ""} onChange={(e) => setAns("notes", e.target.value)} />
      </Section>

      <p className="text-xs text-slate-500">
        TimeTracker records app names, window titles, file names and web addresses. It takes no screenshots and no keystrokes, and never reads what's inside your documents or messages.
      </p>

      {err && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{err}</div>}

      {!ro && (
        <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center justify-end gap-3 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-2xl sm:border">
          <span className="mr-auto text-xs text-slate-500">{savedAt ? `Saved ${savedAt.toLocaleTimeString()}` : "Saves as you go — come back to this link anytime."}</span>
          <button className={secondaryBtnClass} disabled={!!saving} onClick={() => save(false)}>
            {saving === "save" && <Loader2 className="h-4 w-4 animate-spin" />} Save draft
          </button>
          <button className={primaryBtnClass} disabled={!!saving || a.team.length === 0}
            title={a.team.length === 0 ? "Add at least one person first" : undefined}
            onClick={() => window.confirm("Send this to Mavops? You won't be able to edit it afterwards without asking us.") && save(true)}>
            {saving === "submit" && <Loader2 className="h-4 w-4 animate-spin" />} Send to Mavops
          </button>
        </div>
      )}
    </Shell>
  );
}

function Shell({ firm, children }: { firm?: string; children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-slate-50 font-[Inter,system-ui,sans-serif] text-slate-900">
      <div className="mx-auto max-w-5xl space-y-5 px-4 py-8 sm:px-6">
        <header>
          <div className="text-xs font-semibold uppercase tracking-wider text-primary">TimeTracker · Mavops</div>
          <h1 className="mt-1 text-2xl font-semibold">{firm ? `Getting ${firm} set up` : "Getting set up"}</h1>
          {firm && <p className="mt-1 text-sm text-slate-600">About 20 minutes. Several people can fill this in — it saves as you go.</p>}
        </header>
        {children}
      </div>
    </div>
  );
}

function Section({ n, title, sub, children }: { n: number; title: string; sub?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex items-baseline gap-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">{n}</span>
        <div className="min-w-0">
          <h2 className="font-semibold">{title}</h2>
          {sub && <div className="mt-0.5 text-sm text-slate-600">{sub}</div>}
        </div>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Choice({ label, name, value, options, onChange, disabled }: {
  label: string; name: string; value?: string; options: [string, string][]; onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <fieldset>
      <legend className={labelClass}>{label}</legend>
      <div className="flex flex-wrap gap-2">
        {options.map(([v, l]) => (
          <label key={v} className={"flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm " + (value === v ? "border-primary bg-primary/5" : "border-slate-200")}>
            <input type="radio" name={name} disabled={disabled} checked={value === v} onChange={() => onChange(v)} /> {l}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Editable rows, plus "paste from a spreadsheet" in the column order shown. */
function RowsEditor({ cols, rows, onChange, disabled, addLabel, newRow = {} }: {
  cols: Col[]; rows: Row[]; onChange: (r: Row[]) => void; disabled?: boolean; addLabel: string; newRow?: Row;
}) {
  const [paste, setPaste] = useState<string | null>(null);
  const setCell = (i: number, k: string, v: string | boolean) => onChange(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  const applyPaste = () => {
    const parsed = (paste || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((line) => {
      const cells = line.includes("\t") ? line.split("\t") : line.split(",");
      const r: Row = { ...newRow };
      cols.forEach((c, i) => {
        const raw = (cells[i] ?? "").trim();
        if (!raw) return;
        r[c.key] = c.type === "bool" ? !/^(no|false|n|0)$/i.test(raw) : c.type === "select" ? raw.toLowerCase() : raw;
      });
      return r;
    }).filter((r) => cols.some((c) => r[c.key] !== undefined && r[c.key] !== newRow[c.key]));
    // Drop a header row if one was pasted.
    const body = parsed.filter((r) => String(r[cols[0].key] ?? "").toLowerCase() !== cols[0].label.toLowerCase());
    onChange([...rows, ...body]); setPaste(null);
  };

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-600">
            <tr>{cols.map((c) => <th key={c.key} className={"px-2 py-2 " + (c.width || "")}>{c.label}</th>)}<th className="w-8" /></tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={cols.length + 1} className="px-3 py-4 text-center text-xs text-slate-500">Nothing yet.</td></tr>}
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-100">
                {cols.map((c) => (
                  <td key={c.key} className="px-1.5 py-1">
                    {c.type === "select" ? (
                      <select disabled={disabled} aria-label={c.label} className={inputClass + " px-2 py-1.5"} value={String(r[c.key] ?? c.options?.[0]?.[0] ?? "")}
                        onChange={(e) => setCell(i, c.key, e.target.value)}>
                        {c.options?.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                    ) : c.type === "bool" ? (
                      <input type="checkbox" disabled={disabled} aria-label={c.label} checked={r[c.key] !== false} onChange={(e) => setCell(i, c.key, e.target.checked)} className="ml-3" />
                    ) : (
                      <input disabled={disabled} aria-label={c.label} type={c.type === "number" ? "text" : c.type || "text"} inputMode={c.type === "number" ? "decimal" : undefined}
                        placeholder={c.placeholder} className={inputClass + " px-2 py-1.5"} value={String(r[c.key] ?? "")}
                        onChange={(e) => setCell(i, c.key, e.target.value)} />
                    )}
                  </td>
                ))}
                <td className="px-1">
                  {!disabled && <button aria-label="Remove row" onClick={() => onChange(rows.filter((_, j) => j !== i))} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <button className={secondaryBtnClass + " py-1.5"} onClick={() => onChange([...rows, { ...newRow }])}><Plus className="h-4 w-4" /> {addLabel}</button>
          <button className={secondaryBtnClass + " py-1.5"} onClick={() => setPaste(paste === null ? "" : null)}><ClipboardPaste className="h-4 w-4" /> Paste from a spreadsheet</button>
        </div>
      )}
      {paste !== null && (
        <div className="space-y-2 rounded-xl border border-slate-200 p-3">
          <div className="text-xs text-slate-600">Copy rows from Excel or Google Sheets with the columns in this order: <b>{cols.map((c) => c.label).join(", ")}</b>.</div>
          <textarea autoFocus rows={5} className={inputClass + " font-mono text-xs"} value={paste} onChange={(e) => setPaste(e.target.value)} />
          <div className="flex justify-end gap-2">
            <button className={secondaryBtnClass + " py-1.5"} onClick={() => setPaste(null)}>Cancel</button>
            <button className={primaryBtnClass + " py-1.5"} onClick={applyPaste} disabled={!paste.trim()}>Add these rows</button>
          </div>
        </div>
      )}
    </div>
  );
}
