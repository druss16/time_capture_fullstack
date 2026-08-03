/* TEMPORARY visual-preview harness (no login) — delete before PR. */
import { useState } from "react";
import { RefreshCw, Check, Plus, BarChart3 } from "lucide-react";
import { cn } from "@/lib/design-system";
import CompactSummary from "@/components/CompactSummary";
import type { Lanes } from "@/lib/dailyReviewLanes";

const FONTS = [
  { label: "Jakarta (current)", css: '"Plus Jakarta Sans", sans-serif' },
  { label: "Inter", css: '"Inter", sans-serif' },
  { label: "Space Grotesk", css: '"Space Grotesk", sans-serif' },
  { label: "Fraunces", css: '"Fraunces", serif' },
  { label: "Instrument Serif", css: '"Instrument Serif", serif' },
];

const lanes: Lanes = {
  certain: {
    blockCount: 18,
    minutes: 297,
    billableMinutes: 262, // 4h 22m
    nonBillableMinutes: 35,
    groups: [
      {
        key: "id:1", clientId: 1, name: "Spirit of Hope Catholic Comm", internal: false, unassigned: false,
        minutes: 73, billableMinutes: 73, nonBillableMinutes: 0, billable: true, blockCount: 5, repCategory: "General Client Work",
        rows: [
          { ids: [1], title: "Qbw.Exe — Spirit of Hope Parish (Secondary)", category: "General Client Work", minutes: 35 },
          { ids: [2], title: "Qbw.Exe — Spirit of Hope Parish", category: "General Client Work", minutes: 23 },
          { ids: [3], title: "Qbw.Exe — Delete Transaction", category: "General Client Work", minutes: 4 },
          { ids: [4], title: "Excel.Exe — Find and Replace", category: "General Client Work", minutes: 1 },
          { ids: [5], title: "Excel.Exe — Column Width", category: "General Client Work", minutes: 1 },
        ],
      },
      { key: "id:2", clientId: 2, name: "St. Mary's of the Assumption", internal: false, unassigned: false, minutes: 41, billableMinutes: 41, nonBillableMinutes: 0, billable: true, blockCount: 3, repCategory: "General Client Work", rows: [{ ids: [6], title: "Qbw.Exe — St Mary's", category: "General Client Work", minutes: 41 }] },
      { key: "id:3", clientId: 3, name: "St. Francis of Assisi Church", internal: false, unassigned: false, minutes: 35, billableMinutes: 35, nonBillableMinutes: 0, billable: true, blockCount: 5, repCategory: "General Client Work", rows: [{ ids: [7], title: "Qbw.Exe — St Francis", category: "General Client Work", minutes: 35 }] },
      { key: "id:4", clientId: 4, name: "Immaculate Conception", internal: false, unassigned: false, minutes: 27, billableMinutes: 27, nonBillableMinutes: 0, billable: true, blockCount: 2, repCategory: "General Client Work", rows: [{ ids: [8], title: "Qbw.Exe — Immaculate Conception", category: "General Client Work", minutes: 27 }] },
      { key: "id:5", clientId: 5, name: "Basilica of The Sacred Heart of Jesus", internal: false, unassigned: false, minutes: 19, billableMinutes: 19, nonBillableMinutes: 0, billable: true, blockCount: 2, repCategory: "General Client Work", rows: [{ ids: [9], title: "Qbw.Exe — Sacred Heart", category: "General Client Work", minutes: 19 }] },
      { key: "none", clientId: null, name: "No client (browsing)", internal: false, unassigned: true, minutes: 22, billableMinutes: 0, nonBillableMinutes: 22, billable: false, blockCount: 3, repCategory: "Personal/Non-Billable", rows: [{ ids: [10], title: "Chrome — Gmail", category: "Personal/Non-Billable", minutes: 14 }, { ids: [11], title: "Chrome — news", category: "Personal/Non-Billable", minutes: 8 }] },
      { key: "id:9", clientId: 9, name: "Internal – Admin", internal: true, unassigned: false, minutes: 13, billableMinutes: 0, nonBillableMinutes: 13, billable: false, blockCount: 2, repCategory: "Billing / Admin", rows: [{ ids: [12], title: "Excel.Exe — TL Wall timesheet", category: "Billing / Admin", minutes: 13 }] },
    ],
  },
  needsYou: {
    count: 5,
    minutes: 74,
    pending: [
      { block_id: 100, window_title: "Excel.Exe — Bank Rec Worksheet 2026.xlsx", minutes: 56, proposed_client_id: null, proposed_client_name: null, proposed_confidence: 0, proposed_category: "General Client Work", proposed_reasoning: "No client session before or after — nothing to go on." },
      { block_id: 101, window_title: "Find and Replace", minutes: 3, proposed_client_id: 6, proposed_client_name: "St Margarets Church-Homer", proposed_confidence: 0.7, proposed_category: "General Client Work", proposed_reasoning: "Right before this, you were working on St Margarets Church-Homer." },
      { block_id: 102, window_title: "Enter Memorized Transactions", minutes: 3, proposed_client_id: 7, proposed_client_name: "St. Joseph's Church", proposed_confidence: 0.7, proposed_category: "General Client Work", proposed_reasoning: "Same QuickBooks session as St. Joseph's Church right after this block." },
    ],
    mismatch: [
      { block_id: 200, window_title: "Excel.Exe — SFA P&L 2025 — 2026 by Month", minutes: 7, category: "General Client Work", booked_client_id: 1, booked_client_name: "Spirit of Hope", looks_like_client_id: 3, looks_like_client_name: "St. Francis of Assisi" },
      { block_id: 201, window_title: "Excel.Exe — SMA P&L 2025 — 2026 by Month", minutes: 5, category: "General Client Work", booked_client_id: 1, booked_client_name: "Spirit of Hope", looks_like_client_id: 2, looks_like_client_name: "St. Mary's of the Assumption" },
    ],
  },
};

const clients = [
  { id: 1, name: "Spirit of Hope" }, { id: 2, name: "St. Mary's of the Assumption" },
  { id: 3, name: "St. Francis of Assisi" }, { id: 6, name: "St Margarets Church-Homer" },
  { id: 7, name: "St. Joseph's Church" },
];

// mirrors DailyReview's StatCell
const Stat = ({ value, label, cls = "text-slate-800" }: { value: string; label: string; cls?: string }) => (
  <div className="flex flex-col items-end">
    <span className={cn("text-lg font-bold leading-none tabular-nums", cls)}>{value}</span>
    <span className="mt-0.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400">{label}</span>
  </div>
);

export default function LanePreview() {
  const [font, setFont] = useState(FONTS[3].css); // default: Fraunces
  return (
    <div className="min-h-screen bg-background">
      {/* toolbar — mirrors DailyReview: [Summary tab · + Add time] ... [date · Confirm all · refresh · 3 stats] */}
      <div className="sticky top-0 z-10 border-b border-border/60 bg-card/95 backdrop-blur-sm">
        <div className="flex h-14 items-center justify-between gap-4 px-5">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5 border-b-2 border-primary px-1 text-sm font-semibold text-primary">
              <BarChart3 className="h-3.5 w-3.5" /> Summary
            </span>
            <span className="h-5 w-px bg-border/60" />
            <button className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-muted">
              <Plus className="h-3.5 w-3.5" /> Add time
            </button>
          </div>
          <div className="flex items-center gap-2.5">
          <div className="rounded-lg border border-border/50 bg-muted/70 px-3 py-1.5 text-sm font-medium text-slate-700">08/03/2026</div>
          <button className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-primary/90">
            <Check className="h-4 w-4" /> Confirm all
          </button>
          <button className="rounded-lg p-1.5 text-slate-400 hover:bg-muted hover:text-slate-700"><RefreshCw className="h-4 w-4" /></button>
          <div className="flex items-center gap-4 border-l border-border/60 pl-3">
            <Stat value="4h 22m" label="Billable" cls="text-primary" />
            <Stat value="1h 14m" label="Needs review" cls="text-amber-500" />
            <Stat value="5h 36m" label="Total" cls="text-slate-800" />
          </div>
          </div>
        </div>
      </div>

      <div className="p-5">
        {/* font picker — TEMP, pick the winner then I apply it everywhere */}
        <div className="mx-auto mb-3 flex max-w-5xl flex-wrap items-center gap-2">
          <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700">PREVIEW · mock data</span>
          <span className="ml-2 text-xs text-slate-400">Headline font:</span>
          {FONTS.map((f) => (
            <button key={f.label} onClick={() => setFont(f.css)} style={{ fontFamily: f.css }}
              className={cn("rounded-full border px-3 py-1 text-xs transition-colors",
                font === f.css ? "border-primary bg-primary/10 text-primary" : "border-border text-slate-500 hover:bg-muted")}>
              {f.label}
            </button>
          ))}
        </div>
        <div className="mx-auto mb-7 max-w-5xl">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Thu, Jul 30</div>
          <h1 style={{ fontFamily: font }} className="mt-2.5 text-[32px] font-bold leading-[1.12] tracking-[-0.021em] text-slate-900">6h 15m sorted. 5 things need you.</h1>
          <p style={{ fontFamily: font }} className="mt-3 max-w-2xl text-[15px] leading-relaxed text-slate-500">
            Everything else matched a client with high confidence and was filed automatically. You can look, but you don’t have to.
          </p>
        </div>
        <CompactSummary
          lanes={lanes}
          availableClients={clients}
          availableCategories={["General Client Work"]}
          busy={false}
          autoFiled={true}
          onRefresh={() => {}}
          showToast={() => {}}
          onIgnoreMismatch={() => {}}
        />
      </div>
    </div>
  );
}
