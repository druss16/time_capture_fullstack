import React, { useRef } from "react";
import { useReactToPrint } from "react-to-print";
import { Shield, Users, ArrowRight } from "lucide-react";
import TeamActivation from "./TeamActivation";

const BRAND_GREEN = "#10B981";
const BORDER = "#E2E8F0";
const TEXT = "#0F172A";
const MUTED = "#64748B";

const steps = [
  { who: "IT Admin", what: "Export user/device list from Intune or AD (email, display name, machine hostname, Windows username). Send as CSV." },
  { who: "Office Manager", what: "Add role (staff/manager/admin) and billing rate to the team list. Provide a client list with names, rates, and assigned team members." },
  { who: "MavOps", what: "Import team roster, clients, and device map into TimeTracker. Generate the firm’s org token." },
  { who: "MavOps", what: "Build the MSI with the org token embedded. Test on a clean VM. Send MSI to IT Admin." },
  { who: "IT Admin", what: "Push MSI to all machines via Intune (server → portal → devices)." },
  { who: "Automatic", what: "Agent starts, reads org token, detects hostname/username, calls API, auto-pairs to the correct user. Zero user interaction." },
  { who: "MavOps", what: "Verify all devices paired in admin panel. Check-in call at day 2–3. Tune AI categorization as needed." },
];

const teamDeviceCsvExample = [
  ["email", "display_name", "role", "rate", "hostname", "win_user"],
  ["jsmith@firm.com", "John Smith", "staff", "150", "FIRM-PC-101", "FIRM\\jsmith"],
  ["mjones@firm.com", "Mary Jones", "manager", "200", "FIRM-PC-102", "FIRM\\mjones"],
];

const clientsExample = [
  ["client_name", "billing_rate", "assigned_team (emails)"],
  ["Acme Corp", "175", "jsmith@firm.com, mjones@firm.com"],
  ["Beta LLC", "150", "jsmith@firm.com"],
];

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-medium bg-slate-100 text-slate-700">
      {children}
    </span>
  );
}

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border bg-white" style={{ borderColor: BORDER }}>
      <div className="px-5 py-4">
        <div className="text-sm font-semibold" style={{ color: TEXT }}>{title}</div>
        {subtitle && <div className="mt-1 text-sm" style={{ color: MUTED }}>{subtitle}</div>}
      </div>
      <div className="border-t" style={{ borderColor: BORDER }} />
      <div className="p-5">{children}</div>
    </div>
  );
}

function SimpleTable({ data }: { data: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: BORDER }}>
      <table className="min-w-[720px] w-full text-sm">
        <thead className="bg-slate-50">
          <tr>
            {data[0].map((h) => (
              <th key={h} className="px-4 py-3 text-left font-semibold" style={{ color: TEXT, borderBottom: `1px solid ${BORDER}` }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.slice(1).map((row, idx) => (
            <tr key={idx} className="hover:bg-slate-50" style={{ borderBottom: idx === data.length - 2 ? "none" : `1px solid ${BORDER}` }}>
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-3" style={{ color: TEXT }}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StepRow({ n, who, what }: { n: number; who: string; what: string }) {
  const tone =
    who === "MavOps"
      ? "bg-emerald-50 text-emerald-900 border-emerald-200"
      : who === "Automatic"
      ? "bg-slate-50 text-slate-900 border-slate-200"
      : "bg-white text-slate-900 border-slate-200";

  return (
    <div className="flex gap-4 py-4">
      <div className="w-8 shrink-0">
        <div className="flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold bg-white" style={{ borderColor: BORDER, color: TEXT }}>
          {n}
        </div>
      </div>
      <div className="flex-1">
        <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${tone}`}>{who}</span>
        <div className="mt-2 text-sm leading-6" style={{ color: TEXT }}>{what}</div>
      </div>
    </div>
  );
}

export default function WhiteGloveOnboarding() {
  const printRef = useRef<HTMLDivElement>(null);

  const handlePrint = useReactToPrint({
    content: () => printRef.current,
    documentTitle: "TimeTracker_White_Glove_Onboarding",
    pageStyle: `
      @page { size: letter; margin: 16mm; }
      @media print {
        body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
      }
    `,
  });

  return (
    <div className="space-y-6">
      {/* Live rollout state. Deliberately outside printRef: this is the working
          view, while everything below is the reference doc handed to IT. */}
      <TeamActivation />

      {/* Top actions (not printed) */}
      <div className="flex flex-col md:flex-row gap-3 md:items-center md:justify-between">
        <div className="flex flex-wrap gap-2">
          <Pill>Typical rollout: 48–72 hours</Pill>
          <Pill>End users: zero interaction</Pill>
          <Pill>Intune / AD supported</Pill>
        </div>
        <div className="flex gap-2">
          <button
            className="rounded-xl border px-4 py-2 text-sm font-medium hover:bg-slate-50"
            style={{ borderColor: BORDER, color: TEXT }}
            onClick={handlePrint}
          >
            Print / Save as PDF
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-xl px-4 py-2 text-sm font-semibold text-white"
            style={{ backgroundColor: BRAND_GREEN }}
          >
            Download PDF
          </button>
        </div>
      </div>

      {/* Printable area */}
      <div ref={printRef} className="space-y-6">
        <div className="flex items-center gap-3">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-2xl" style={{ backgroundColor: "rgba(16,185,129,.12)" }}>
            <Shield className="h-5 w-5" style={{ color: BRAND_GREEN }} />
          </div>
          <div>
            <h1 className="text-2xl font-semibold" style={{ color: TEXT }}>White Glove Onboarding</h1>
            <p className="text-sm" style={{ color: MUTED }}>Enterprise MSI Deployment — Quick Reference</p>
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Card title="Overview">
            <p className="text-sm leading-6" style={{ color: TEXT }}>
              TimeTracker provides <span className="font-semibold">zero-interaction</span> enterprise deployment using Microsoft Intune or Active Directory.
              <br />
              <span className="font-semibold">MavOps</span> handles provisioning. Your <span className="font-semibold">IT team</span> handles distribution.{" "}
              <span className="font-semibold">End users do nothing.</span>
            </p>
            <div className="mt-3 flex items-center gap-2 text-sm" style={{ color: MUTED }}>
              <ArrowRight className="h-4 w-4" />
              Agent auto-pairs using hostname + Windows username (fallback to manual code if needed).
            </div>
          </Card>

          <Card title="What We Need From You" subtitle="Two exports + a quick spreadsheet update.">
            <ul className="text-sm leading-6 list-disc pl-5" style={{ color: TEXT }}>
              <li><span className="font-semibold">IT Admin:</span> Device/user CSV (Intune or AD)</li>
              <li><span className="font-semibold">Office Manager:</span> Roles + billing rates + client assignments</li>
              <li><span className="font-semibold">MavOps:</span> Build MSI + test + deliver to IT</li>
            </ul>
          </Card>
        </div>

        <Card title="Deployment Flow (Who Does What)">
          <div className="divide-y" style={{ borderColor: BORDER }}>
            {steps.map((s, i) => (
              <div key={i}>
                <StepRow n={i + 1} who={s.who} what={s.what} />
              </div>
            ))}
          </div>
        </Card>

        <Card
          title="What IT Admin Provides (CSV)"
          subtitle="One row per device. If a user has a laptop + desktop, include multiple rows."
        >
          <div className="space-y-4">
            <div className="text-sm font-semibold" style={{ color: TEXT }}>
              Team & Devices (IT exports, Office Manager adds role + rate)
            </div>
            <SimpleTable data={teamDeviceCsvExample} />
          </div>
        </Card>

        <Card title="Clients (From Office Manager)">
          <SimpleTable data={clientsExample} />
        </Card>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Card title="How Auto-Pair Works">
            <div className="space-y-2 text-sm leading-6" style={{ color: TEXT }}>
              <div>Agent starts → reads org token</div>
              <div>Grabs hostname + Windows username</div>
              <div>Calls API → backend matches pre-provisioned map</div>
              <div>Device paired automatically (no user action)</div>
              <div style={{ color: MUTED }}>Fallback: manual pairing code (if no match found)</div>
            </div>
          </Card>

          <Card title="Where IT Gets the Data">
            <div className="space-y-2 text-sm leading-6" style={{ color: TEXT }}>
              <div><span className="font-semibold">Intune:</span> <span style={{ color: MUTED }}>Devices → All Devices → Export (2 min)</span></div>
              <div><span className="font-semibold">AD/Server:</span> <span style={{ color: MUTED }}>PowerShell export (standard IT task)</span></div>
              <div><span className="font-semibold">Roles + Rates:</span> <span style={{ color: MUTED }}>From Office Manager (not IT systems)</span></div>
            </div>
          </Card>
        </div>

        <div className="pt-2 text-xs" style={{ color: MUTED }}>
          TimeTracker by MavOps — Secure. Zero-friction. Enterprise-ready.
        </div>
      </div>
    </div>
  );
}