import React from "react";
import {
  CalendarDays,
  CreditCard,
  Monitor,
  Users,
  Settings as SettingsIcon,
  Building2,
  UserRound,
  BriefcaseBusiness,
  Shield,
  Server,
  ArrowRight,
} from "lucide-react";

// If you're using shadcn/ui, these imports should work.
// If not, replace with your own components / HTML equivalents.
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

/**
 * TimeTracker — White Glove Onboarding
 * Enterprise MSI Deployment — Quick Reference
 *
 * Design goals:
 * - Uses your existing TimeTracker nav styling + brand green
 * - Linear-ish: clean spacing, crisp headers, minimal clutter
 * - CPA-friendly: very scannable steps + tables + clear "what we need" section
 */

const BRAND_GREEN = "#10B981"; // adjust to your exact brand hex if different
const NAV_BG = "#0B1220"; // dark navy from screenshot vibe
const PAGE_BG = "#F8FAFC";
const BORDER = "#E2E8F0";
const TEXT = "#0F172A";
const MUTED = "#64748B";

type NavItem = {
  label: string;
  icon: React.ReactNode;
};

const topNavItems: NavItem[] = [
  { label: "Daily Review", icon: <CalendarDays className="h-4 w-4" /> },
  { label: "Billing", icon: <CreditCard className="h-4 w-4" /> },
  { label: "Devices", icon: <Monitor className="h-4 w-4" /> },
  { label: "Clients", icon: <Users className="h-4 w-4" /> },
];

const sideNav = [
  { label: "Organization", icon: <Building2 className="h-4 w-4" /> },
  { label: "Team Members", icon: <UserRound className="h-4 w-4" />, active: true },
  { label: "Clients", icon: <BriefcaseBusiness className="h-4 w-4" /> },
  { label: "Client Access", icon: <Shield className="h-4 w-4" /> },
  { label: "Devices", icon: <Monitor className="h-4 w-4" /> },
  { label: "Integrations", icon: <Server className="h-4 w-4" /> },
];

const steps = [
  {
    who: "IT Admin",
    what: "Export user/device list from Intune or AD (email, display name, machine hostname, Windows username). Send as CSV.",
  },
  {
    who: "Office Manager",
    what: "Add role (staff/manager/admin) and billing rate to the team list. Provide a client list with names, rates, and assigned team members.",
  },
  {
    who: "MavOps",
    what: "Import team roster, clients, and device map into TimeTracker. Generate the firm’s org token.",
  },
  {
    who: "MavOps",
    what: "Build the MSI with the org token embedded. Test on a clean VM. Send MSI to IT Admin.",
  },
  {
    who: "IT Admin",
    what: "Push MSI to all machines via Intune (server → portal → devices).",
  },
  {
    who: "Automatic",
    what: "Agent starts, reads org token, detects hostname/username, calls API, auto-pairs to the correct user. Zero user interaction.",
  },
  {
    who: "MavOps",
    what: "Verify all devices paired in admin panel. Check-in call at day 2–3. Tune AI categorization as needed.",
  },
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

function classNames(...v: Array<string | false | undefined | null>) {
  return v.filter(Boolean).join(" ");
}

function ProgressBar({ used, total }: { used: number; total: number }) {
  const pct = Math.min(100, Math.round((used / total) * 100));
  return (
    <div className="w-full">
      <div className="flex items-center justify-between text-sm">
        <div className="font-medium" style={{ color: TEXT }}>
          Team Seats
        </div>
        <div className="text-sm" style={{ color: MUTED }}>
          <span className="font-semibold" style={{ color: TEXT }}>
            {used}
          </span>{" "}
          / {total} used
        </div>
      </div>
      <div className="mt-2 h-2 w-full rounded-full" style={{ backgroundColor: "#E5E7EB" }}>
        <div
          className="h-2 rounded-full"
          style={{
            width: `${pct}%`,
            backgroundColor: BRAND_GREEN,
          }}
        />
      </div>
      <div className="mt-2 text-xs" style={{ color: MUTED }}>
        {total - used} seat{total - used === 1 ? "" : "s"} remaining
      </div>
    </div>
  );
}

function SimpleTable({ data }: { data: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-xl border" style={{ borderColor: BORDER }}>
      <table className="min-w-[720px] w-full text-sm">
        <thead style={{ backgroundColor: "#F1F5F9" }}>
          <tr>
            {data[0].map((h) => (
              <th
                key={h}
                className="px-4 py-3 text-left font-semibold"
                style={{ color: TEXT, borderBottom: `1px solid ${BORDER}` }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.slice(1).map((row, idx) => (
            <tr
              key={idx}
              className="hover:bg-slate-50"
              style={{ borderBottom: idx === data.length - 2 ? "none" : `1px solid ${BORDER}` }}
            >
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-3" style={{ color: TEXT }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StepRow({ n, who, what }: { n: number; who: string; what: string }) {
  const whoTone =
    who === "MavOps"
      ? "bg-emerald-50 text-emerald-900 border-emerald-200"
      : who === "Automatic"
      ? "bg-slate-50 text-slate-900 border-slate-200"
      : "bg-white text-slate-900 border-slate-200";

  return (
    <div className="flex gap-4 py-4">
      <div className="w-8 shrink-0">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold"
          style={{ borderColor: BORDER, color: TEXT, backgroundColor: "white" }}
        >
          {n}
        </div>
      </div>
      <div className="flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={classNames("rounded-full border px-2.5 py-1 text-xs font-medium", whoTone)}>
            {who}
          </span>
        </div>
        <div className="mt-2 text-sm leading-6" style={{ color: TEXT }}>
          {what}
        </div>
      </div>
    </div>
  );
}

export default function TimeTrackerOnboardingQuickReference() {
  return (
    <div className="min-h-screen" style={{ backgroundColor: PAGE_BG }}>
      {/* Top Navigation (matches your screenshot vibe) */}
      <header className="w-full" style={{ backgroundColor: NAV_BG }}>
        <div className="mx-auto max-w-7xl px-6 py-4">
          <div className="flex items-center justify-between">
            {/* Logo / Brand */}
            <div className="flex items-center gap-3">
              <div
                className="flex h-10 w-10 items-center justify-center rounded-full"
                style={{ backgroundColor: "rgba(16,185,129,.18)" }}
              >
                <div
                  className="flex h-8 w-8 items-center justify-center rounded-full"
                  style={{ backgroundColor: BRAND_GREEN }}
                >
                  <div className="h-3 w-3 rounded-full bg-white" />
                </div>
              </div>
              <div className="leading-tight">
                <div className="text-base font-semibold text-white">TimeTracker</div>
                <div className="text-xs" style={{ color: "rgba(255,255,255,.65)" }}>
                  by MavOps
                </div>
              </div>
            </div>

            {/* Main nav */}
            <nav className="hidden md:flex items-center gap-6">
              {topNavItems.map((item) => (
                <button
                  key={item.label}
                  className="flex items-center gap-2 text-sm font-medium hover:text-white"
                  style={{ color: "rgba(255,255,255,.75)" }}
                >
                  {item.icon}
                  {item.label}
                </button>
              ))}

              {/* Active Settings pill (matches your screenshot) */}
              <button
                className="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-white"
                style={{
                  backgroundColor: "rgba(16,185,129,.95)",
                }}
              >
                <SettingsIcon className="h-4 w-4" />
                Settings
              </button>
            </nav>
          </div>
        </div>
      </header>

      {/* Body */}
      <main className="mx-auto max-w-7xl px-6 py-10">
        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-8">
          {/* Sidebar */}
          <aside className="hidden lg:block">
            <div className="rounded-2xl border bg-white" style={{ borderColor: BORDER }}>
              <div className="px-5 py-5">
                <div className="flex items-center gap-3">
                  <div
                    className="flex h-11 w-11 items-center justify-center rounded-2xl"
                    style={{ backgroundColor: "rgba(16,185,129,.12)" }}
                  >
                    <SettingsIcon className="h-5 w-5" style={{ color: BRAND_GREEN }} />
                  </div>
                  <div>
                    <div className="text-lg font-semibold" style={{ color: TEXT }}>
                      Settings
                    </div>
                    <div className="text-sm" style={{ color: MUTED }}>
                      Manage your organization
                    </div>
                  </div>
                </div>
              </div>

              <Separator />

              <div className="px-2 py-2">
                {sideNav.map((item) => (
                  <button
                    key={item.label}
                    className={classNames(
                      "w-full flex items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-medium",
                      item.active ? "" : "hover:bg-slate-50"
                    )}
                    style={{
                      backgroundColor: item.active ? "rgba(16,185,129,.12)" : "transparent",
                      color: item.active ? TEXT : "#334155",
                      borderLeft: item.active ? `4px solid ${BRAND_GREEN}` : "4px solid transparent",
                    }}
                  >
                    <span style={{ color: item.active ? BRAND_GREEN : "#64748B" }}>{item.icon}</span>
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </aside>

          {/* Main Content */}
          <section className="space-y-6">
            {/* Header row */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <div
                  className="inline-flex h-9 w-9 items-center justify-center rounded-2xl"
                  style={{ backgroundColor: "rgba(16,185,129,.12)" }}
                >
                  <Shield className="h-4 w-4" style={{ color: BRAND_GREEN }} />
                </div>
                <h1 className="text-2xl font-semibold" style={{ color: TEXT }}>
                  White Glove Onboarding
                </h1>
              </div>
              <p className="text-sm" style={{ color: MUTED }}>
                Enterprise MSI Deployment — Quick Reference (clean + CPA-friendly)
              </p>
            </div>

            {/* Summary / Actions */}
            <div className="flex flex-col md:flex-row gap-3 md:items-center md:justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="rounded-full">
                  Typical rollout: 48–72 hours
                </Badge>
                <Badge variant="secondary" className="rounded-full">
                  End users: zero interaction
                </Badge>
                <Badge variant="secondary" className="rounded-full">
                  Intune / AD supported
                </Badge>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" className="rounded-xl">
                  Print
                </Button>
                <Button className="rounded-xl" style={{ backgroundColor: BRAND_GREEN }}>
                  Download PDF
                </Button>
              </div>
            </div>

            {/* Seats + Invite (styled like your settings page) */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <Card className="rounded-2xl border" style={{ borderColor: BORDER }}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2" style={{ color: TEXT }}>
                    <Users className="h-4 w-4" style={{ color: BRAND_GREEN }} />
                    Team Members
                    <span className="text-sm font-normal" style={{ color: MUTED }}>
                      (example)
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <ProgressBar used={3} total={4} />
                  <Separator />
                  <div className="space-y-2">
                    <div className="text-sm font-semibold" style={{ color: TEXT }}>
                      Invite Team Member
                    </div>
                    <div className="text-sm" style={{ color: MUTED }}>
                      Add a team member to your organization. (Example UI)
                    </div>
                    <div className="flex gap-2">
                      <Input className="rounded-xl" placeholder="name@firm.com" />
                      <Button className="rounded-xl" style={{ backgroundColor: BRAND_GREEN }}>
                        Invite
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="rounded-2xl border" style={{ borderColor: BORDER }}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base flex items-center gap-2" style={{ color: TEXT }}>
                    <Shield className="h-4 w-4" style={{ color: BRAND_GREEN }} />
                    Overview
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <p className="text-sm leading-6" style={{ color: TEXT }}>
                    TimeTracker provides <span className="font-semibold">zero-interaction</span> enterprise deployment
                    using Microsoft Intune or Active Directory.
                    <br />
                    <span className="font-semibold">MavOps</span> handles provisioning. Your <span className="font-semibold">IT team</span>{" "}
                    handles distribution. <span className="font-semibold">End users do nothing.</span>
                  </p>
                  <div className="flex items-center gap-2 text-sm" style={{ color: MUTED }}>
                    <ArrowRight className="h-4 w-4" />
                    Agent auto-pairs devices using hostname + Windows username (fallback to manual code if needed).
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Deployment Flow */}
            <Card className="rounded-2xl border" style={{ borderColor: BORDER }}>
              <CardHeader>
                <CardTitle className="text-base" style={{ color: TEXT }}>
                  Deployment Flow (Who Does What)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="divide-y" style={{ borderColor: BORDER }}>
                  {steps.map((s, i) => (
                    <div key={i} className={i === 0 ? "pt-0" : ""}>
                      <StepRow n={i + 1} who={s.who} what={s.what} />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* What IT Provides */}
            <div className="grid grid-cols-1 gap-6">
              <Card className="rounded-2xl border" style={{ borderColor: BORDER }}>
                <CardHeader>
                  <CardTitle className="text-base" style={{ color: TEXT }}>
                    What IT Admin Provides (CSV)
                  </CardTitle>
                  <div className="text-sm" style={{ color: MUTED }}>
                    One row per device. If a user has a laptop + desktop, they get two rows.
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="text-sm font-semibold" style={{ color: TEXT }}>
                    Team & Devices (IT exports, Office Manager adds role + rate)
                  </div>
                  <SimpleTable data={teamDeviceCsvExample} />
                </CardContent>
              </Card>

              <Card className="rounded-2xl border" style={{ borderColor: BORDER }}>
                <CardHeader>
                  <CardTitle className="text-base" style={{ color: TEXT }}>
                    Clients (From Office Manager)
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <SimpleTable data={clientsExample} />
                </CardContent>
              </Card>
            </div>

            {/* Auto-pair + Data sources */}
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <Card className="rounded-2xl border" style={{ borderColor: BORDER }}>
                <CardHeader>
                  <CardTitle className="text-base" style={{ color: TEXT }}>
                    How Auto-Pair Works
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm leading-6" style={{ color: TEXT }}>
                  <div>Agent starts → reads org token</div>
                  <div>Grabs hostname + Windows username</div>
                  <div>Calls API → backend matches pre-provisioned map</div>
                  <div>Device paired automatically (no user action)</div>
                  <div style={{ color: MUTED }}>
                    If no match is found: falls back to manual pairing code.
                  </div>
                </CardContent>
              </Card>

              <Card className="rounded-2xl border" style={{ borderColor: BORDER }}>
                <CardHeader>
                  <CardTitle className="text-base" style={{ color: TEXT }}>
                    Where IT Gets the Data
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-sm leading-6" style={{ color: TEXT }}>
                  <div>
                    <span className="font-semibold">Intune:</span>{" "}
                    <span style={{ color: MUTED }}>Devices → All Devices → Export (2 min)</span>
                  </div>
                  <div>
                    <span className="font-semibold">AD/Server:</span>{" "}
                    <span style={{ color: MUTED }}>PowerShell export of users + devices (standard IT task)</span>
                  </div>
                  <div>
                    <span className="font-semibold">Role + Billing Rate:</span>{" "}
                    <span style={{ color: MUTED }}>Provided by Office Manager, not IT systems</span>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Footer */}
            <div className="py-4 text-xs" style={{ color: MUTED }}>
              TimeTracker by MavOps — Secure. Zero-friction. Enterprise-ready.
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}