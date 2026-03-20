// src/components/TimesheetHistory.tsx
// Timesheet history with inline expand — click any row to see
// client summary + individual activities for that week.

import { useState, useEffect, useCallback } from "react";
import {
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Clock,
  DollarSign,
  CheckCircle,
  Filter,
  Calendar,
  User,
  Briefcase,
  ArrowRight,
  AlertCircle,
} from "lucide-react";
import { safeFetchJson, API_BASE } from "@/lib/api";
import { cn } from "@/lib/design-system";

// ─── Types ─────────────────────────────────────────────────────────────────

interface Timesheet {
  id: number;
  user_id: number;
  user_username: string;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  week_start: string;
  week_end: string;
  status: string;
  total_hours: number;
  billable_hours: number;
  total_amount: string;
  auto_submitted: boolean;
  submitted_at: string | null;
  approved_at: string | null;
  approved_by_id: number | null;
  approved_by_username: string | null;
}

interface TimesheetDetail {
  id: number;
  week_start: string;
  week_end: string;
  status: string;
  total_hours: number;
  billable_hours: number;
  total_amount: number;
  entries: DetailEntry[];
}

interface DetailEntry {
  client_id: number | null;
  client_name: string;
  task_type_id: number | null;
  task_type_name: string;
  is_billable: boolean;
  days: Record<string, number>;
  total: number;
}

interface HistoryData {
  timesheets: Timesheet[];
  summary: {
    total_timesheets: number;
    total_hours: number;
    billable_hours: number;
    total_amount: string;
    auto_submitted_count: number;
  };
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const fmtHours = (h: number | string) => {
  const n = parseFloat(String(h)) || 0;
  return `${n.toFixed(1)}h`;
};

const fmtMoney = (a: number | string) => {
  const n = parseFloat(String(a)) || 0;
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
};

const fmtDate = (iso: string | null) => {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

const fmtDateTime = (iso: string | null) => {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
};

const fmtWeek = (start: string, end: string) => {
  const s = new Date(start + "T00:00:00");
  const e = new Date(end + "T00:00:00");
  const sStr = s.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const eStr = e.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  return `${sStr} – ${eStr}`;
};

const userName = (ts: Timesheet) =>
  `${ts.user_first_name} ${ts.user_last_name}`.trim() || ts.user_username;

const userInitials = (ts: Timesheet) => {
  const name = userName(ts);
  return name.split(" ").map((n) => n[0]).join("").toUpperCase().slice(0, 2);
};

const AVATAR_COLORS = [
  "bg-teal-500", "bg-blue-500", "bg-violet-500", "bg-amber-500",
  "bg-rose-500", "bg-emerald-500", "bg-orange-500", "bg-indigo-500",
];

// ─── Expanded Detail ────────────────────────────────────────────────────────

function ExpandedDetail({ timesheetId }: { timesheetId: number }) {
  const [detail, setDetail] = useState<TimesheetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [expandedClients, setExpandedClients] = useState<Set<string>>(new Set());

  useEffect(() => {
    (async () => {
      try {
        const data = await safeFetchJson<TimesheetDetail>(
          `${API_BASE}/billing/timesheets/${timesheetId}/`
        );
        setDetail(data);
        // Expand all clients by default
        if (data.entries) {
          const clients = new Set(data.entries.map((e) => e.client_name));
          setExpandedClients(clients);
        }
      } catch (e: any) {
        setErr(e?.message || "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, [timesheetId]);

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center gap-2 text-slate-400">
        <RefreshCw className="w-4 h-4 animate-spin" />
        <span className="text-sm">Loading timesheet detail...</span>
      </div>
    );
  }

  if (err || !detail) {
    return (
      <div className="p-6 flex items-center gap-2 text-red-500 text-sm">
        <AlertCircle className="w-4 h-4" />
        {err || "No detail available"}
      </div>
    );
  }

  // Group entries by client
  const byClient: Record<string, DetailEntry[]> = {};
  for (const entry of detail.entries || []) {
    const key = entry.client_name || "Unassigned";
    if (!byClient[key]) byClient[key] = [];
    byClient[key].push(entry);
  }

  const toggleClient = (name: string) => {
    setExpandedClients((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  };

  const clientTotals = Object.entries(byClient).map(([name, entries]) => ({
    name,
    total: entries.reduce((s, e) => s + Number(e.total), 0),
    billable: entries.filter((e) => e.is_billable).reduce((s, e) => s + Number(e.total), 0),
    entries,
  }));

  return (
    <div className="border-t border-slate-100 bg-slate-50/50">
      {/* Summary bar */}
      <div className="grid grid-cols-3 gap-4 px-6 py-4 border-b border-slate-100 bg-white">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-slate-400" />
          <div>
            <p className="text-xs text-slate-500">Total hours</p>
            <p className="text-sm font-bold text-slate-800">{fmtHours(detail.total_hours)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Briefcase className="w-4 h-4 text-teal-500" />
          <div>
            <p className="text-xs text-slate-500">Billable hours</p>
            <p className="text-sm font-bold text-teal-700">{fmtHours(detail.billable_hours)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <DollarSign className="w-4 h-4 text-emerald-500" />
          <div>
            <p className="text-xs text-slate-500">Total amount</p>
            <p className="text-sm font-bold text-emerald-700">{fmtMoney(detail.total_amount)}</p>
          </div>
        </div>
      </div>

      {/* Client breakdown */}
      <div className="divide-y divide-slate-100">
        {clientTotals.length === 0 && (
          <p className="px-6 py-4 text-sm text-slate-400">No time entries for this week.</p>
        )}
        {clientTotals.map(({ name, total, billable, entries }) => {
          const isExpanded = expandedClients.has(name);
          return (
            <div key={name}>
              {/* Client header row */}
              <button
                onClick={() => toggleClient(name)}
                className="w-full flex items-center gap-3 px-6 py-3 hover:bg-slate-100/70 transition-colors text-left"
              >
                {isExpanded
                  ? <ChevronDown className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                  : <ChevronRight className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />}
                <Briefcase className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                <span className="font-semibold text-sm text-slate-800 flex-1">{name}</span>
                <span className="text-xs text-teal-600 font-bold">{fmtHours(billable)} billable</span>
                <span className="text-xs text-slate-500 ml-3">{fmtHours(total)} total</span>
              </button>

              {/* Activity rows */}
              {isExpanded && (
                <div className="bg-white border-t border-slate-50">
                  {entries.map((entry, idx) => (
                    <div
                      key={idx}
                      className="flex items-center gap-3 px-10 py-2.5 border-b border-slate-50 last:border-0 hover:bg-slate-50/50 transition-colors"
                    >
                      <ArrowRight className="w-3 h-3 text-slate-300 flex-shrink-0" />
                      <span className="text-sm text-slate-600 flex-1">{entry.task_type_name || "General"}</span>
                      {!entry.is_billable && (
                        <span className="text-xs text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded font-medium">
                          Non-billable
                        </span>
                      )}
                      <span className={cn(
                        "text-sm font-semibold",
                        entry.is_billable ? "text-teal-700" : "text-slate-400"
                      )}>
                        {fmtHours(Number(entry.total) / 60)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Timesheet Row ──────────────────────────────────────────────────────────

function TimesheetRow({ ts, colorIdx }: { ts: Timesheet; colorIdx: number }) {
  const [expanded, setExpanded] = useState(false);
  const color = AVATAR_COLORS[colorIdx % AVATAR_COLORS.length];

  return (
    <div className={cn(
      "border border-slate-200 rounded-xl overflow-hidden shadow-sm transition-all duration-200",
      expanded && "ring-2 ring-primary/20 border-primary/30"
    )}>
      {/* Main row — clickable */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-4 px-5 py-4 bg-white hover:bg-slate-50/70 transition-colors text-left"
      >
        {/* Expand indicator */}
        <div className="flex-shrink-0">
          {expanded
            ? <ChevronDown className="w-4 h-4 text-primary" />
            : <ChevronRight className="w-4 h-4 text-slate-400" />}
        </div>

        {/* Avatar */}
        <div className={cn("w-9 h-9 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0", color)}>
          {userInitials(ts)}
        </div>

        {/* Name + email */}
        <div className="min-w-0 flex-shrink-0 w-44">
          <p className="font-semibold text-slate-800 text-sm truncate">{userName(ts)}</p>
          <p className="text-xs text-slate-400 truncate">{ts.user_email}</p>
        </div>

        {/* Week */}
        <div className="flex items-center gap-1.5 flex-shrink-0 w-44">
          <Calendar className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-sm text-slate-600">{fmtWeek(ts.week_start, ts.week_end)}</span>
        </div>

        {/* Status badges */}
        <div className="flex items-center gap-1.5 flex-shrink-0 w-32">
          <span className="flex items-center gap-1 px-2 py-0.5 bg-emerald-50 border border-emerald-200 rounded-full text-xs font-semibold text-emerald-700">
            <CheckCircle className="w-3 h-3" />
            Approved
          </span>
          {ts.auto_submitted && (
            <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-50 border border-amber-200 rounded-full text-xs font-semibold text-amber-600">
              <Clock className="w-3 h-3" />
              Auto
            </span>
          )}
        </div>

        {/* Hours */}
        <div className="flex-shrink-0 w-20 text-right">
          <p className="text-sm font-bold text-slate-800">{fmtHours(ts.total_hours)}</p>
          <p className="text-xs text-slate-400">total</p>
        </div>

        {/* Billable */}
        <div className="flex-shrink-0 w-20 text-right">
          <p className="text-sm font-bold text-teal-700">{fmtHours(ts.billable_hours)}</p>
          <p className="text-xs text-slate-400">billable</p>
        </div>

        {/* Amount */}
        <div className="flex-shrink-0 w-24 text-right">
          <p className="text-sm font-bold text-emerald-700">{fmtMoney(ts.total_amount)}</p>
          <p className="text-xs text-slate-400">amount</p>
        </div>

        {/* Approved by */}
        <div className="flex-shrink-0 w-32 text-right ml-auto">
          <p className="text-xs text-slate-500">{fmtDateTime(ts.approved_at)}</p>
          {ts.approved_by_username && (
            <p className="text-xs text-slate-400">by {ts.approved_by_username}</p>
          )}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && <ExpandedDetail timesheetId={ts.id} />}
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

export default function TimesheetHistory() {
  const [data, setData] = useState<HistoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [filterUser, setFilterUser] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const d = await safeFetchJson<HistoryData>(`${API_BASE}/billing/timesheet-history/`);
      setData(d);
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const timesheets = data?.timesheets || [];
  const summary = data?.summary;

  // Unique users for filter
  const users = Array.from(new Set(timesheets.map((t) => userName(t)))).sort();

  const filtered = filterUser
    ? timesheets.filter((t) => userName(t) === filterUser)
    : timesheets;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Timesheet History</h1>
          <p className="text-slate-500 mt-0.5 text-sm">View approved and locked timesheets</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: "Timesheets", value: summary.total_timesheets, icon: <Calendar className="w-4 h-4" />, color: "text-slate-700" },
            { label: "Total Hours", value: fmtHours(summary.total_hours), icon: <Clock className="w-4 h-4" />, color: "text-slate-700" },
            { label: "Billable Hours", value: fmtHours(summary.billable_hours), icon: <Briefcase className="w-4 h-4" />, color: "text-teal-700" },
            { label: "Total Value", value: fmtMoney(summary.total_amount), icon: <DollarSign className="w-4 h-4" />, color: "text-emerald-700" },
            { label: "Auto-Submitted", value: summary.auto_submitted_count, icon: <Clock className="w-4 h-4" />, color: "text-amber-600" },
          ].map(({ label, value, icon, color }) => (
            <div key={label} className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm">
              <div className="flex items-center gap-1.5 text-slate-400 mb-1">
                {icon}
                <span className="text-xs font-medium">{label}</span>
              </div>
              <p className={cn("text-2xl font-bold", color)}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filter */}
      {users.length > 1 && (
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <select
            value={filterUser}
            onChange={(e) => setFilterUser(e.target.value)}
            className="border border-slate-200 rounded-lg px-3 py-1.5 text-sm font-medium text-slate-700 bg-white focus:border-primary focus:outline-none"
          >
            <option value="">All employees</option>
            {users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      )}

      {/* Error */}
      {err && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl flex items-center gap-2 text-red-700 text-sm">
          <AlertCircle className="w-4 h-4" />
          {err}
        </div>
      )}

      {/* Loading */}
      {loading && !data && (
        <div className="flex items-center justify-center py-16 gap-2 text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span>Loading history...</span>
        </div>
      )}

      {/* Hint */}
      {filtered.length > 0 && (
        <p className="text-xs text-slate-400">
          Click any row to expand and view client breakdown + activities
        </p>
      )}

      {/* Timesheet rows */}
      <div className="space-y-2">
        {filtered.map((ts, idx) => (
          <TimesheetRow key={ts.id} ts={ts} colorIdx={idx} />
        ))}
      </div>

      {/* Empty */}
      {!loading && filtered.length === 0 && (
        <div className="bg-white border border-slate-200 rounded-xl p-16 text-center">
          <CheckCircle className="w-12 h-12 text-slate-200 mx-auto mb-3" />
          <h3 className="text-slate-700 font-semibold mb-1">No approved timesheets yet</h3>
          <p className="text-slate-400 text-sm">Approved timesheets will appear here.</p>
        </div>
      )}
    </div>
  );
}