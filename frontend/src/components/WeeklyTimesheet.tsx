// src/components/WeeklyTimesheet.tsx
// Read-only weekly timesheet, styled to match the refreshed Daily Review "Lightning"
// look (faint teal ground, quiet dotted rows, billable/non-billable badges).
// "Summary" drills client → category; "By day" drills day → client → category.
// Time is auto-captured by the desktop agent, so cells are not editable here —
// adjustments happen in Daily Review.

import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { safeFetchJson, API_BASE } from '@/lib/api';
import { fetchWhoAmI } from '@/lib/whoami';
import { MatterPicker } from '@/components/MatterPicker';
import {
  ChevronLeft, ChevronRight, ChevronDown, Clock, CheckCircle2, Lock,
  AlertTriangle, Info, RefreshCw, Search, X, Layers, CalendarDays, Sparkles, Copy,
  FolderInput, Check,
  Briefcase,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

// ── Types ─────────────────────────────────────────────────────────────────────

interface TimesheetEntry {
  client_id: number | null;
  client_name: string;
  task_type_id: number | null;
  task_type_name: string;
  is_billable: boolean;
  days: Record<string, number>;
  total: number;
}

interface TimesheetData {
  week_start: string;
  week_end: string;
  timesheet_id: number;
  status: 'draft' | 'submitted' | 'approved' | 'rejected' | 'locked';
  entries: TimesheetEntry[];
  daily_totals: Record<string, number>;
  grand_total: number;
  billable_total: number;
  // Workday span per day: first→last activity clock times ("8:41a"→"4:00p").
  daily_span?: Record<string, { start: string; end: string } | null>;
  auto_submitted?: boolean;
  submitted_at?: string | null;
  rejection_reason?: string;
}

interface DayHeader {
  date: string;
  label: string;
  dayNum: number;
  isWeekend: boolean;
  isToday: boolean;
}

// One captured block from the timesheet-detail timeline (block-level drill).
interface DetailBlock {
  id: number;
  started_at: string | null;
  ended_at: string | null;
  duration_minutes: number;
  client_name: string | null;
  task_type_name: string | null;
  is_billable: boolean;
  window_title: string | null;
  application: string | null;
  taxpayer_name: string | null;
  matter_label?: string | null;
  matter_options?: number;
}

interface TimesheetDetail {
  timesheet_id: number;
  days: { date: string; blocks: DetailBlock[]; total_minutes: number }[];
}

interface TaskTypeOption {
  id: number;
  name: string;
  is_billable: boolean;
}

// Lets a deeply-nested BlockRow move a block without threading callbacks through
// four component levels. Null when moves aren't available (e.g. detail failed).
// Matter picking rides on the same context as category moves: both are "fix
// this row" actions on a block, with the same busy/refresh plumbing.
const MoveContext = React.createContext<{
  clioEnabled?: boolean;
  onSetMatter?: (blockIds: number[], projectId: number) => Promise<void>;
  taskTypes: TaskTypeOption[];
  movingId: number | null;
  onMove: (blockIds: number[], taskTypeId: number) => void;
} | null>(null);

// Index blocks by client + category (and by day) so a category row can list its
// captured blocks. Detail blocks carry names (no ids), so we join on the same
// fallbacks the weekly grid uses: null client → "Unassigned", null task → "General".
const blockClientKey = (name: string | null) => name || 'Unassigned';
const blockCatKey    = (name: string | null) => name || 'General';
const wKey = (clientName: string, taskName: string) => `${clientName}||${taskName}`;
const dKey = (date: string, clientName: string, taskName: string) => `${date}||${clientName}||${taskName}`;

// A friendly one-line label for a captured block.
const blockLabel = (b: DetailBlock): string =>
  (b.window_title || b.application || b.taxpayer_name || b.task_type_name || 'Captured activity').trim();

// Identical captured blocks (same title) get merged into one display row with a
// summed duration and a ×N count, so a long tail of repeated app windows reads
// as a single line. Purely cosmetic — `ids` keeps every underlying block so a
// move still acts on all of them. Rows stay in chronological order (earliest
// occurrence first), which matches the un-merged timeline.
interface AggBlock {
  key: string;
  label: string;
  minutes: number;
  count: number;
  firstStart: string | null;
  is_billable: boolean;
  taskTypeName: string | null;
  ids: number[];
  // Matter state, so the row can show it rather than the user having to open a
  // menu to find out. `matterLabel` null with matterOptions > 1 is the only
  // case that actually needs a person.
  matterLabel: string | null;
  matterOptions: number;
}
const aggregateBlocks = (blocks: DetailBlock[]): AggBlock[] => {
  const map = new Map<string, AggBlock>();
  for (const b of blocks) {
    const label = blockLabel(b);
    const ex = map.get(label);
    if (ex) {
      ex.minutes += b.duration_minutes || 0;
      ex.count += 1;
      ex.ids.push(b.id);
      // Merged rows share a title but can sit on different matters. Only claim
      // a matter when every block in the row agrees; otherwise the row is mixed
      // and saying "00003-Vance" would be a lie about some of its time.
      if ((b.matter_label ?? null) !== ex.matterLabel) ex.matterLabel = null;
      ex.matterOptions = Math.max(ex.matterOptions, b.matter_options ?? 0);
      if (b.started_at && (!ex.firstStart || b.started_at < ex.firstStart)) ex.firstStart = b.started_at;
    } else {
      map.set(label, {
        key: label,
        label,
        minutes: b.duration_minutes || 0,
        count: 1,
        firstStart: b.started_at,
        is_billable: b.is_billable,
        taskTypeName: b.task_type_name,
        ids: [b.id],
        matterLabel: b.matter_label ?? null,
        matterOptions: b.matter_options ?? 0,
      });
    }
  }
  return [...map.values()].sort(
    (a, b) => (a.firstStart || '').localeCompare(b.firstStart || '') || b.minutes - a.minutes
  );
};

const formatClock = (iso: string | null): string => {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
};

// Week-view block rows span days, so lead with a weekday; day view uses the clock.
const formatBlockWhen = (iso: string | null, withDay: boolean): string => {
  if (!iso) return '';
  const d = new Date(iso);
  const t = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(/\s/g, '').toLowerCase();
  return withDay ? `${d.toLocaleDateString('en-US', { weekday: 'short' })} ${t}` : formatClock(iso);
};

const formatMinutes = (m: number): string => {
  if (!m) return '—';
  const h = Math.floor(m / 60);
  const min = m % 60;
  if (h === 0) return `${min}m`;
  if (min === 0) return `${h}h`;
  return `${h}h ${min}m`;
};

// A client aggregated across all its task rows for the Summary view.
interface ClientAgg {
  key: string;
  clientId: number | null;
  clientName: string;
  total: number;
  billable: number;
  nonBillable: number;
  taskCount: number;
  primaryTask: string;
  allBillable: boolean;
  allNonBillable: boolean;
  entries: TimesheetEntry[];
}

// The unassigned bucket ("No client") always sorts to the bottom of the list.
const isNoClient = (agg: Pick<ClientAgg, 'clientId'>) => agg.clientId == null;
const displayClientName = (agg: Pick<ClientAgg, 'clientId' | 'clientName'>) =>
  isNoClient(agg) ? 'No client' : agg.clientName;

// Clients whose whole week is under this many hours get rolled into one row.
const GAP_PAGE = 8;   // rows shown in the needs-a-matter banner before "show more"
const TAIL_THRESHOLD_HOURS = 0.25; // 15 minutes

// ── Utilities ─────────────────────────────────────────────────────────────────

const formatHours = (hours: number | string): string => {
  const num = parseFloat(String(hours)) || 0;
  if (num === 0) return '—';
  const h = Math.floor(num);
  const m = Math.round((num - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
};

// Decimal hours (e.g. 2.93) for the H:M / decimal toggle — the billing-style view.
const formatHoursDecimal = (hours: number | string): string => {
  const num = parseFloat(String(hours)) || 0;
  if (num === 0) return '—';
  return num.toFixed(2);
};

type HourFmt = 'hm' | 'decimal';

// Lets any nested row honor the user's H:M / decimal toggle without threading a
// formatter through every component. Defaults to H:M.
const HourFmtContext = React.createContext<(h: number | string) => string>(formatHours);
const useFmtHours = () => React.useContext(HourFmtContext);

const getMonday = (date: Date): Date => {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.setDate(diff));
};

const formatWeekRange = (weekStart: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return `${start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${end.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
};

const isWeekEnded = (weekStart: string): boolean => {
  const start = new Date(weekStart + 'T00:00:00');
  const weekEnd = new Date(start);
  weekEnd.setDate(weekEnd.getDate() + 6);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return today > weekEnd;
};

const getCanSubmitDate = (weekStart: string): string => {
  const start = new Date(weekStart + 'T00:00:00');
  const monday = new Date(start);
  monday.setDate(monday.getDate() + 7);
  return monday.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
};

const getDaysUntilSubmit = (weekStart: string): number => {
  const start = new Date(weekStart + 'T00:00:00');
  const weekEnd = new Date(start);
  weekEnd.setDate(weekEnd.getDate() + 6);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = weekEnd.getTime() - today.getTime();
  return Math.ceil(diff / (1000 * 60 * 60 * 24)) + 1;
};

const todayIso = () => new Date().toISOString().split('T')[0];

const pct = (part: number, whole: number): number =>
  whole > 0 ? Math.max(0, Math.min(100, (part / whole) * 100)) : 0;

// ── Status Badge ──────────────────────────────────────────────────────────────

const StatusBadge: React.FC<{ status: TimesheetData['status']; autoSubmitted?: boolean }> = ({
  status, autoSubmitted,
}) => {
  const map: Record<string, { cls: string; label: string }> = {
    draft:     { cls: 'bg-muted text-muted-foreground border-border',      label: 'Draft' },
    submitted: { cls: 'bg-amber-50 text-amber-700 border-amber-200',       label: 'Pending Approval' },
    approved:  { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: 'Approved' },
    rejected:  { cls: 'bg-red-50 text-red-600 border-red-200',             label: 'Rejected' },
    locked:    { cls: 'bg-muted text-muted-foreground border-border',      label: 'Locked' },
  };
  const { cls, label } = map[status] || map.draft;
  return (
    <div className="flex items-center gap-2">
      <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border', cls)}>
        {status === 'draft'     && <span className="w-1.5 h-1.5 bg-muted-foreground/60 rounded-full" />}
        {status === 'submitted' && <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />}
        {status === 'approved'  && <CheckCircle2 className="w-3.5 h-3.5" />}
        {status === 'locked'    && <Lock className="w-3 h-3" />}
        {label}
      </span>
      {autoSubmitted && (
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-600 border border-amber-200">
          <Clock className="w-3 h-3" /> Auto-submitted
        </span>
      )}
    </div>
  );
};

// ── Banner ────────────────────────────────────────────────────────────────────

const Banner: React.FC<{
  type: 'info' | 'warning' | 'error';
  title: string;
  message: React.ReactNode;
}> = ({ type, title, message }) => {
  const styles = {
    info:    { wrap: 'bg-primary/5 border-primary/20',  icon: 'text-primary',   text: 'text-primary/80',  Title: 'text-primary' },
    warning: { wrap: 'bg-amber-50 border-amber-200',    icon: 'text-amber-500', text: 'text-amber-700',   Title: 'text-amber-800' },
    error:   { wrap: 'bg-red-50 border-red-200',        icon: 'text-red-500',   text: 'text-red-600',     Title: 'text-red-700' },
  }[type];
  const Icon = type === 'info' ? Info : AlertTriangle;
  return (
    <div className={cn('flex items-start gap-3 px-4 py-3 rounded-lg border text-sm', styles.wrap)}>
      <Icon className={cn('w-4 h-4 mt-0.5 shrink-0', styles.icon)} />
      <div>
        <p className={cn('font-semibold', styles.Title)}>{title}</p>
        <p className={cn('mt-0.5', styles.text)}>{message}</p>
      </div>
    </div>
  );
};

// ── Design language (shared by Summary + By-day drills) ─────────────────────────
// Faint teal ground + quiet dotted rows + calm billable/non-billable badges,
// matching the refreshed Daily Review "Lightning" look.
const BADGE_BILL  = 'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide bg-primary/10 text-primary';
const BADGE_NON   = 'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide bg-muted text-muted-foreground';
const HOURS_CELL  = 'text-right font-mono text-[12.5px] font-semibold text-foreground tabular-nums shrink-0 w-[64px]';

// Daily Review "Lightning" primitives, reused so the timesheet reads the same.
const LANE_CARD   = 'overflow-hidden rounded-[15px] border border-border/70 bg-card shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)]';
const MIN_CHIP    = 'inline-flex items-center justify-center shrink-0 min-w-[52px] rounded-md bg-muted px-1.5 py-1 font-mono text-[10.5px] font-bold tabular-nums text-muted-foreground';
const UPPER_LABEL = 'text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70';
// Font stacks: Inter for the hero voice, mono for captured titles/minutes.
const INTER       = { fontFamily: '"Inter", sans-serif' } as const;
const pctOfLabel  = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

const Badge: React.FC<{ billable: boolean }> = ({ billable }) => (
  <span className={billable ? BADGE_BILL : BADGE_NON}>{billable ? 'Billable' : 'Non-billable'}</span>
);

// ── Main Component ────────────────────────────────────────────────────────────

type ViewMode = 'summary' | 'byday' | 'work_summary';

type SubmissionMode = 'push' | 'review' | 'auto' | 'off';

interface WeeklyTimesheetProps {
  /** How this firm actually uses submit/approve. Absent = treat as 'review'
   *  so nothing regresses for a caller that has not been updated. */
  submission?: { mode: SubmissionMode; reason: string } | null;
}

const WeeklyTimesheet: React.FC<WeeklyTimesheetProps> = ({ submission }) => {
  const [loading, setLoading]               = useState(true);
  const [error, setError]                   = useState<string | null>(null);
  const [weekStart, setWeekStart]           = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    const p = params.get('week');
    if (p && /^\d{4}-\d{2}-\d{2}$/.test(p)) return p;
    return getMonday(new Date()).toISOString().split('T')[0];
  });
  const [timesheetData, setTimesheetData]   = useState<TimesheetData | null>(null);
  const [detail, setDetail]                 = useState<TimesheetDetail | null>(null);
  const [taskTypes, setTaskTypes]           = useState<TaskTypeOption[]>([]);
  const [movingId, setMovingId]             = useState<number | null>(null);
  const [submitting, setSubmitting]         = useState(false);
  const [submitNotes, setSubmitNotes]       = useState('');
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  // What submitting would send to Clio. Null for firms with no Clio connection,
  // so nothing about this appears for them.
  const [clioEnabled, setClioEnabled] = useState(false);
  const [matterGapOpen, setMatterGapOpen] = useState(false);
  // A banner is a prompt, not a workspace. Attribution can leave dozens of rows
  // unresolved — a firm mid-rollout, or before the extension ships — and an
  // unbounded list inside a banner pushes the actual timesheet off the screen.
  const [gapShown, setGapShown] = useState(GAP_PAGE);
  // Rows resolved in this session. Assigning a matter used to refetch the whole
  // timesheet, so the page flickered and the list re-rendered underneath the
  // person mid-triage. The row simply leaves instead; the next natural reload
  // carries the server's version, and this set is cleared when it arrives.
  const [assignedBlockIds, setAssignedBlockIds] = useState<Set<number>>(new Set());
  const [clioPreview, setClioPreview] = useState<any | null>(null);
  // "This is additional work" decisions, keyed user:matter:day. Empty almost
  // always — Clio does not capture time on its own, so a firm using TimeTracker
  // only has manual Clio entries for work we never saw: court, calls, travel.
  const [forcedConflicts, setForcedConflicts] = useState<string[]>([]);
  const [clioResult, setClioResult] = useState<any | null>(null);
  const [search, setSearch]                 = useState('');
  const [view, setView]                     = useState<ViewMode>('summary');
  const [expanded, setExpanded]             = useState<Set<string>>(new Set());
  const [tailOpen, setTailOpen]             = useState(false);
  const [laneOpen, setLaneOpen]             = useState(false); // "This week" starts collapsed
  const [hourFmt, setHourFmt]               = useState<HourFmt>('hm'); // H:M vs decimal

  const searchRef = useRef<HTMLInputElement>(null);

  const fetchTimesheet = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await safeFetchJson<TimesheetData>(
        `${API_BASE}/billing/weekly/?week_start=${weekStart}`
      );
      setTimesheetData(data);
      // Block-level detail powers the category → block drill. Best-effort:
      // if it fails, the page still works (categories just don't expand).
      setDetail(null);
      if (data?.timesheet_id) {
        safeFetchJson<TimesheetDetail>(
          `${API_BASE}/billing/timesheets/${data.timesheet_id}/detail/`
        ).then(setDetail).catch(() => setDetail(null));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load timesheet');
    } finally {
      setLoading(false);
    }
  }, [weekStart]);

  // Index detail blocks by client+category (week) and day+client+category.
  const { weekBlocks, dayBlocks } = useMemo(() => {
    const week = new Map<string, DetailBlock[]>();
    const day  = new Map<string, DetailBlock[]>();
    const push = (m: Map<string, DetailBlock[]>, k: string, b: DetailBlock) => {
      const arr = m.get(k);
      if (arr) arr.push(b); else m.set(k, [b]);
    };
    for (const d of detail?.days ?? []) {
      for (const b of d.blocks) {
        if (!b.duration_minutes) continue;
        const ck = blockClientKey(b.client_name);
        const tk = blockCatKey(b.task_type_name);
        push(week, wKey(ck, tk), b);
        push(day, dKey(d.date, ck, tk), b);
      }
    }
    return { weekBlocks: week, dayBlocks: day };
  }, [detail]);

  // Time that cannot reach a bill until someone picks a matter. Only counts
  // blocks whose client actually HAS matters to choose between — a client with
  // none is not a task, and counting it would make the number un-actionable.
  const matterGap = useMemo(() => {
    let minutes = 0;
    const clients = new Set<string>();
    for (const d of detail?.days ?? []) {
      for (const b of d.blocks) {
        if (!b.duration_minutes) continue;
        if (b.matter_label) continue;
        if ((b.matter_options ?? 0) < 1) continue;
        if (assignedBlockIds.has(b.id)) continue;  // just resolved, here
        minutes += b.duration_minutes;
        clients.add(blockClientKey(b.client_name));
      }
    }
    return { minutes, clientKeys: clients };
  }, [detail, assignedBlockIds]);

  // The rows themselves, flat. Expanding the tree cannot reach them: a client
  // may sit inside the collapsed "under 15 min" tail, and the activity rows
  // live behind CategoryRow's own local state, which nothing outside can open.
  // So this lists them directly instead of asking anyone to navigate.
  // Server data replaced the optimistic view — drop the local overrides so a
  // row the server still considers unassigned reappears rather than staying
  // hidden on a stale assumption.
  useEffect(() => { setAssignedBlockIds(new Set()); }, [detail]);

  const matterGapRows = useMemo(() => {
    const needs: DetailBlock[] = [];
    for (const d of detail?.days ?? []) {
      for (const b of d.blocks) {
        if (!b.duration_minutes) continue;
        if (b.matter_label) continue;
        if ((b.matter_options ?? 0) < 1) continue;
        needs.push(b);
      }
    }
    return aggregateBlocks(needs)
      .filter(a => !a.ids.every(id => assignedBlockIds.has(id)))
      .map(a => ({
        ...a,
        clientName: needs.find(b => b.id === a.ids[0])?.client_name ?? null,
      }));
  }, [detail, assignedBlockIds]);

  useEffect(() => { fetchTimesheet(); }, [fetchTimesheet]);
  useEffect(() => { setSearch(''); setExpanded(new Set()); setTailOpen(false); }, [weekStart]);

  // Category options for the per-block move menu (loaded once).
  useEffect(() => {
    safeFetchJson<TaskTypeOption[]>(`${API_BASE}/options/task-types/`)
      .then(list => setTaskTypes(Array.isArray(list) ? list : []))
      .catch(() => setTaskTypes([]));
  }, []);

  // Move mis-filed block(s) to a different category, then reload so every view
  // (this timesheet, its totals) reflects the change. Identical captured blocks
  // are merged into one display row, so a move can span several block ids —
  // POST each, then reload once.
  const moveBlocks = useCallback(async (blockIds: number[], taskTypeId: number) => {
    if (!blockIds.length) return;
    setMovingId(blockIds[0]);
    setError(null);
    try {
      for (const id of blockIds) {
        await safeFetchJson(`${API_BASE}/blocks/${id}/move-task-type/`, {
          method: 'POST', body: JSON.stringify({ task_type_id: taskTypeId }),
        });
      }
      await fetchTimesheet();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not move those blocks');
    } finally {
      setMovingId(null);
    }
  }, [fetchTimesheet]);

  const goToWeek = (dir: number) => {
    const d = new Date(weekStart + 'T00:00:00');
    d.setDate(d.getDate() + dir * 7);
    setWeekStart(d.toISOString().split('T')[0]);
  };

  const daysUntilSubmit = useMemo(() => {
    if (!timesheetData) return 0;
    return getDaysUntilSubmit(timesheetData.week_start);
  }, [timesheetData]);

  // Entries filtered by the search box (client or task name).
  const searchedEntries = useMemo(() => {
    const entries = (timesheetData?.entries ?? []).filter(e => e.total > 0);
    if (!search.trim()) return entries;
    const q = search.toLowerCase();
    return entries.filter(e =>
      e.client_name.toLowerCase().includes(q) ||
      e.task_type_name.toLowerCase().includes(q)
    );
  }, [timesheetData?.entries, search]);

  // Aggregate task rows into one row per client, ranked by total desc.
  const clients = useMemo<ClientAgg[]>(() => {
    const map = new Map<string, ClientAgg>();
    for (const e of searchedEntries) {
      const key = String(e.client_id ?? e.client_name);
      let agg = map.get(key);
      if (!agg) {
        agg = {
          key, clientId: e.client_id, clientName: e.client_name, total: 0, billable: 0, nonBillable: 0,
          taskCount: 0, primaryTask: e.task_type_name, allBillable: true, allNonBillable: true,
          entries: [],
        };
        map.set(key, agg);
      }
      agg.total += e.total;
      agg.billable += e.is_billable ? e.total : 0;
      agg.nonBillable += e.is_billable ? 0 : e.total;
      agg.taskCount += 1;
      agg.entries.push(e);
      if (e.is_billable) agg.allNonBillable = false; else agg.allBillable = false;
    }
    const list = Array.from(map.values());
    // Pick the biggest task as the "primary" label; sort tasks within a client.
    for (const agg of list) {
      agg.entries.sort((a, b) => b.total - a.total);
      agg.primaryTask = agg.entries[0]?.task_type_name ?? agg.primaryTask;
    }
    // Rank by time, but the "No client" bucket always sinks to the bottom.
    return list.sort((a, b) => {
      const au = isNoClient(a) ? 1 : 0;
      const bu = isNoClient(b) ? 1 : 0;
      if (au !== bu) return au - bu;
      return b.total - a.total;
    });
  }, [searchedEntries]);

  // Every client is listed. Folding the small ones into "N more clients under
  // 15 min" hid exactly the rows most likely to need attention — a two-minute
  // block on a client with two matters is still a billing decision, and it was
  // the one row you could not reach. Short entries are the norm in legal work,
  // not an edge case worth collapsing. The sort already sinks "No client" to
  // the bottom, so it lands there naturally once nothing renders after it.
  const { mainClients, tailClients } = useMemo(
    () => ({ mainClients: clients, tailClients: [] as ClientAgg[] }),
    [clients],
  );

  const tailTotals = useMemo(() => {
    return tailClients.reduce(
      (acc, c) => ({ billable: acc.billable + c.billable, nonBillable: acc.nonBillable + c.nonBillable, total: acc.total + c.total }),
      { billable: 0, nonBillable: 0, total: 0 }
    );
  }, [tailClients]);

  useEffect(() => {
    let alive = true;
    fetchWhoAmI()
      .then((me: any) => {
        if (alive) setClioEnabled(!!me?.primary_integrations?.includes?.('clio'));
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Assigning a matter also teaches the folder, so one correction fixes every
  // future document filed alongside it — see matter_attribution.build_folder_index.
  const setMatterForBlocks = useCallback(async (blockIds: number[], projectId: number) => {
    for (const id of blockIds) {
      await safeFetchJson(`${API_BASE}/blocks/${id}/set-matter/`, {
        method: 'POST', body: JSON.stringify({ project_id: projectId }),
      });
    }
    fetchTimesheet();
  }, [fetchTimesheet]);

  const moveValue = useMemo(
    () => (taskTypes.length
      ? { taskTypes, movingId, onMove: moveBlocks, clioEnabled, onSetMatter: setMatterForBlocks }
      : null),
    [taskTypes, movingId, moveBlocks, clioEnabled, setMatterForBlocks]
  );

  // Accordion: one client open at a time. Opening a client collapses any other
  // so the review stays a focused "verify one, move on" flow instead of a wall
  // of expanded clients. Clicking the open client closes it.
  const toggleExpand = (key: string) => {
    setExpanded(prev => (prev.has(key) ? new Set() : new Set([key])));
  };

  // Loaded when the confirm dialog opens, not on every render: it calls Clio,
  // and the answer is only worth having at the moment someone is deciding.
  useEffect(() => {
    if (!showSubmitModal || !timesheetData?.timesheet_id) return;
    let alive = true;
    setClioPreview(null);
    const q = forcedConflicts.length
      ? '?' + forcedConflicts.map(k => `force=${encodeURIComponent(k)}`).join('&')
      : '';
    safeFetchJson(`${API_BASE}/billing/timesheets/${timesheetData.timesheet_id}/clio-preview/${q}`)
      .then((d: any) => { if (alive) setClioPreview(d); })
      // NOT {connected:false}. That is a legitimate state — an org with no Clio
      // — so using it for failures made a crash in build_push_plan render as
      // "this firm does not use Clio", and the whole section silently vanished.
      // A failure has to look like a failure.
      .catch((e: any) => {
        if (alive) setClioPreview({
          connected: true, available: false,
          error: e?.message || 'Could not reach the server',
        });
      });
    return () => { alive = false; };
  }, [showSubmitModal, timesheetData?.timesheet_id, forcedConflicts]);

  const handleSubmit = async () => {
    if (!timesheetData?.timesheet_id) return;
    setSubmitting(true);
    setError(null);
    try {
      const res: any = await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetData.timesheet_id}/submit/`,
        { method: 'POST', body: JSON.stringify({ notes: submitNotes, force_conflicts: forcedConflicts }) }
      );
      setShowSubmitModal(false);
      setSubmitNotes('');
      // Confirm what actually reached Clio. The submit succeeded either way —
      // this only reports the copy that went to billing.
      if (res?.clio) setClioResult(res.clio);
      fetchTimesheet();
    } catch (err: any) {
      const d = err?.data || {};
      setError(d.can_submit_on
        ? `Cannot submit yet. Available starting ${d.can_submit_on}.`
        : err instanceof Error ? err.message : 'Submit failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReopen = async () => {
    if (!timesheetData?.timesheet_id) return;
    try {
      await safeFetchJson(
        `${API_BASE}/billing/timesheets/${timesheetData.timesheet_id}/reopen/`,
        { method: 'POST' }
      );
      fetchTimesheet();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reopen');
    }
  };

  const getDayHeaders = (): DayHeader[] => {
    if (!timesheetData) return [];
    const today = todayIso();
    const start = new Date(timesheetData.week_start + 'T00:00:00');
    return Array.from({ length: 7 }, (_, i) => {
      const day = new Date(start);
      day.setDate(day.getDate() + i);
      const date = day.toISOString().split('T')[0];
      return {
        date,
        label: day.toLocaleDateString('en-US', { weekday: 'short' }),
        dayNum: day.getDate(),
        isWeekend: i >= 5,
        isToday: date === today,
      };
    });
  };

  const days          = getDayHeaders();
  const weekHasEnded  = timesheetData ? isWeekEnded(timesheetData.week_start) : false;
  const nonBillable   = (timesheetData?.grand_total ?? 0) - (timesheetData?.billable_total ?? 0);
  const billable      = timesheetData?.billable_total ?? 0;
  const grandTotal    = timesheetData?.grand_total ?? 0;
  const totalClients  = clients.length;
  const billablePctLabel = grandTotal > 0 ? Math.round(pct(billable, grandTotal)) : 0;
  const isEmpty       = totalClients === 0;
  // The client list ("This week") starts collapsed; an active search always
  // reveals it so results aren't hidden behind the collapse.
  const bodyOpen      = laneOpen || search.trim().length > 0;
  const fmtHours      = hourFmt === 'decimal' ? formatHoursDecimal : formatHours;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[300px]">
        <RefreshCw className="w-5 h-5 text-muted-foreground/50 animate-spin" />
      </div>
    );
  }

  // What submitting is worth here differs per firm, so the control does too.
  // A firm that auto-submits, or has never approved anything, was being told to
  // perform a ritual it does not perform — which teaches people to ignore the
  // page. Absent mode behaves as before.
  const mode: SubmissionMode = submission?.mode ?? 'review';

  const submitButton = (() => {
    if (timesheetData?.status === 'draft') {
      if (mode === 'auto') {
        // It goes on its own, so nobody should think the week is waiting on
        // them — but saying that is not a reason to take the action away.
        // Anyone finishing on Friday still needs a way to send it now rather
        // than wait for Tuesday.
        return (
          <div className="flex items-center gap-3">
            <span className="text-[12.5px] text-muted-foreground">
              {submission?.reason || 'This week submits itself.'}
            </span>
            <button
              onClick={() => setShowSubmitModal(true)}
              className="px-3 py-1.5 border border-border text-muted-foreground text-[12.5px] font-semibold rounded-lg hover:bg-muted/60 transition-all flex items-center gap-1.5"
            >
              <CheckCircle2 className="w-3.5 h-3.5" /> Send it now
            </button>
          </div>
        );
      }
      // Submission is available any day of the week; the confirm modal guards
      // against accidental early submits.
      const quiet = mode === 'off';
      return (
        <button
          onClick={() => setShowSubmitModal(true)}
          title={submission?.reason || undefined}
          className={cn(
            'px-4 py-2 text-sm font-semibold rounded-lg transition-all flex items-center gap-1.5',
            quiet
              ? 'border border-border text-muted-foreground hover:bg-muted/60'
              : 'bg-primary text-primary-foreground hover:opacity-90'
          )}
        >
          <CheckCircle2 className="w-4 h-4" />
          {quiet ? 'Submit anyway' : 'Submit for Approval'}
        </button>
      );
    }
    if (timesheetData?.status === 'rejected') {
      return (
        <>
          <button onClick={handleReopen} className="px-4 py-2 bg-muted text-foreground text-sm font-semibold rounded-lg hover:bg-muted transition-all">
            Edit
          </button>
          <button onClick={() => setShowSubmitModal(true)} className="px-4 py-2 bg-primary text-primary-foreground text-sm font-semibold rounded-lg hover:opacity-90 transition-all">
            Resubmit
          </button>
        </>
      );
    }
    return null;
  })();

  return (
    <HourFmtContext.Provider value={fmtHours}>
    <div className="mx-auto w-full max-w-[1120px] bg-[#eef4f3] p-4 sm:p-6 rounded-2xl">

      {/* ── Hero: Inter voice, Daily Review "Lightning" look ───────────── */}
      <div style={INTER}>
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">My Timesheet</span>
            {timesheetData && (
              <StatusBadge status={timesheetData.status} autoSubmitted={timesheetData.auto_submitted ?? false} />
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <div className="flex items-center gap-0.5 bg-card border border-border/50 rounded-lg overflow-hidden">
              <button onClick={() => goToWeek(-1)} className="px-1.5 py-1.5 text-muted-foreground/70 hover:text-foreground hover:bg-muted transition-all">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={() => setWeekStart(getMonday(new Date()).toISOString().split('T')[0])}
                className="px-2.5 py-1.5 text-xs font-semibold text-muted-foreground hover:bg-muted transition-all"
              >
                This week
              </button>
              <button onClick={() => goToWeek(1)} className="px-1.5 py-1.5 text-muted-foreground/70 hover:text-foreground hover:bg-muted transition-all">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            <span className="text-[12.5px] font-medium text-muted-foreground whitespace-nowrap tabular-nums">
              {timesheetData && formatWeekRange(timesheetData.week_start)}
            </span>
          </div>
        </div>

        <div className="mt-3 flex items-baseline justify-between gap-4">
          <div className="min-w-0">
            <span className="text-[22px] font-bold tracking-[-0.01em] text-foreground tabular-nums">
              {fmtHours(grandTotal)}
            </span>
            <span className="ml-2 text-[13px] font-semibold text-muted-foreground">
              active · <b className="text-primary tabular-nums">{billablePctLabel}%</b> billable
            </span>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <div className="flex bg-card border border-border/50 rounded-lg p-0.5" title="Toggle hours format">
              {(['hm', 'decimal'] as HourFmt[]).map(m => (
                <button
                  key={m}
                  onClick={() => setHourFmt(m)}
                  className={cn(
                    'px-2 py-0.5 font-mono text-[11px] font-semibold rounded-md transition-all',
                    hourFmt === m ? 'bg-card text-primary shadow-sm' : 'text-muted-foreground/70 hover:text-muted-foreground'
                  )}
                >
                  {m === 'hm' ? 'H:M' : 'Dec'}
                </button>
              ))}
            </div>
            <span className="font-mono text-[12px] tabular-nums text-muted-foreground/70">
              {totalClients} client{totalClients !== 1 ? 's' : ''}
            </span>
          </div>
        </div>

        <div className="mt-3 h-2 rounded-full bg-muted overflow-hidden flex shadow-[inset_0_1px_2px_rgba(0,0,0,0.06)]">
          <div className="h-full bg-gradient-to-r from-primary to-accent" style={{ width: `${pct(billable, grandTotal)}%` }} />
          <div className="h-full bg-muted-foreground/30" style={{ width: `${pct(nonBillable, grandTotal)}%` }} />
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-1 mt-2 text-[12.5px] text-muted-foreground">
          <span className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-[3px] bg-gradient-to-r from-primary to-accent inline-block" />
            <b className="text-foreground tabular-nums">{fmtHours(billable)}</b> billable
          </span>
          <span className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-[3px] bg-muted-foreground/30 inline-block" />
            <b className="text-foreground tabular-nums">{fmtHours(nonBillable)}</b> non-billable
          </span>
        </div>
      </div>

      {/* ── Banners: errors + rejections only ─────────────────────────── */}
      {(error || timesheetData?.status === 'rejected' || timesheetData?.status === 'submitted' || timesheetData?.status === 'approved') && (
        <div className="space-y-2 mt-4">
          {error && <Banner type="error" title="Error" message={error} />}

          {/* What actually reached Clio. The timesheet submitted either way —
              this reports the copy that went to billing, including anything
              held back, so nobody discovers missing hours at invoicing. */}
          {clioResult && (
            <Banner
              type={clioResult.error || clioResult.errors?.length ? 'error' : 'info'}
              title={
                clioResult.error
                  ? 'Submitted — but Clio could not be reached'
                  : clioResult.errors?.length
                    ? 'Submitted — but Clio did not accept everything'
                    // Push moved to a worker, so at submit time there is no
                    // count yet. Saying "nothing new for Clio" here would be a
                    // flat lie about time that is on its way.
                    : clioResult.queued
                      ? 'Submitted — sending to Clio'
                      : clioResult.entries > 0
                        ? `Sent ${formatMinutes(clioResult.minutes ?? 0)} to Clio`
                        : 'Submitted — nothing new for Clio'
              }
              message={
                clioResult.error
                  ? `Your timesheet is submitted. Clio reported: ${clioResult.error}`
                  : clioResult.errors?.length
                    ? `Your timesheet is submitted. ${clioResult.errors.length} entr${clioResult.errors.length === 1 ? 'y' : 'ies'} were rejected by Clio.`
                    : clioResult.queued
                      ? 'Your time is being sent in the background, so submitting is not held up by it.'
                      : clioResult.skipped?.length
                        ? `${clioResult.entries ?? 0} matter${clioResult.entries !== 1 ? 's' : ''} updated. ${clioResult.skipped.length} item${clioResult.skipped.length !== 1 ? 's' : ''} were not sent — open the timesheet to see why.`
                        : `${clioResult.entries ?? 0} matter${clioResult.entries !== 1 ? 's' : ''} updated in Clio.`
              }
            />
          )}
          {/* Submitting used to end in silence: a small "Pending Approval"
              badge and nothing about who now has it or how you would find out.
              People re-opened the page for days. Say what happens next. */}
          {timesheetData?.status === 'submitted' && (
            <Banner
              type="info"
              title={
                timesheetData.auto_submitted
                  ? 'Submitted automatically — with your manager'
                  : 'Submitted — with your manager'
              }
              message={
                `Your week is waiting for approval${
                  timesheetData.submitted_at
                    ? ` (sent ${new Date(timesheetData.submitted_at).toLocaleString(undefined, {
                        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
                      })})`
                    : ''
                }. Your approvers have been emailed, and you'll get an email the moment it's approved or sent back. Nothing else is needed from you.`
              }
            />
          )}

          {timesheetData?.status === 'approved' && (
            <Banner
              type="info"
              title="Approved"
              message="This week is approved and locked. It's counted as billable and, if your firm bills through an integration, it's on its way there."
            />
          )}

          {timesheetData?.status === 'rejected' && (
            <Banner
              type="error"
              title="Sent back for changes"
              message={
                (timesheetData.rejection_reason
                  ? `${timesheetData.rejection_reason} `
                  : '') +
                'Fix what\u2019s needed below, then resubmit \u2014 your approvers are notified again automatically.'
              }
            />
          )}
        </div>
      )}

      {/* ── Lane card: the week's clients ─────────────────────────────── */}
      <div className={cn('mt-4', LANE_CARD)}>

        {/* Time held back for want of a matter. Surfaced here so nobody has to
            open rows one by one looking for it — the whole point of the amber
            state on the row is defeated if you must first find the row. */}
        {matterGap.minutes > 0 && (
          <div className="flex items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2.5">
            <span className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
            <span className="font-mono text-[12px] text-amber-900">
              <b className="tabular-nums">{formatMinutes(matterGap.minutes)}</b> needs a matter
              <span className="hidden sm:inline"> — it will not reach Clio until you choose one</span>
            </span>
            <span className="flex-1" />
            <button
              onClick={() => setMatterGapOpen(o => !o)}
              className="shrink-0 rounded-lg border border-amber-300 bg-card px-3 py-1.5 font-sans text-[12px] font-medium text-amber-800 shadow-[0_1px_2px_rgba(16,27,46,0.05)] hover:bg-amber-100"
            >
              {matterGapOpen ? 'Hide' : 'Show these'}
            </button>
          </div>
        )}

        {/* The rows, right here — client, what was captured, and the picker.
            Nothing to expand, nothing to hunt for. */}
        {matterGap.minutes > 0 && matterGapOpen && (
          <div className="flex flex-col border-b border-amber-200 bg-amber-50/40 px-4 py-2">
            {matterGapRows.slice(0, gapShown).map(row => (
              <div key={row.key} className="flex items-center gap-2 py-1 min-w-0">
                <span className="w-[76px] shrink-0 truncate font-sans text-[12px] font-semibold text-foreground">
                  {row.clientName || 'No client'}
                </span>
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground" title={row.label}>
                  {row.label}
                </span>
                <span className="w-[52px] shrink-0 text-right font-mono text-[12px] tabular-nums text-muted-foreground/70">
                  {formatMinutes(row.minutes)}
                </span>
                {/* MatterPicker, not BlockMatterMenu: this banner sits ABOVE the
                    MoveContext.Provider, and BlockMatterMenu returns null without
                    that context — so the rows rendered and the button silently
                    did not. The prop-driven picker has no such dependency. */}
                <MatterPicker
                  blockIds={row.ids}
                  label="Choose matter"
                  onAssigned={() => setAssignedBlockIds(prev => {
                    const next = new Set(prev);
                    row.ids.forEach(id => next.add(id));
                    return next;
                  })}
                />
              </div>
            ))}
            {matterGapRows.length > gapShown && (
              <button
                onClick={() => setGapShown(n => n + GAP_PAGE)}
                className="mt-1 self-start rounded-md px-1.5 py-0.5 text-[11px] font-semibold text-amber-800 underline-offset-2 hover:underline"
              >
                Show {Math.min(GAP_PAGE, matterGapRows.length - gapShown)} more
                {' '}of {matterGapRows.length}
              </button>
            )}
          </div>
        )}

        {/* Lane header: collapse toggle / search / view toggle */}
        <div className={cn('flex items-center gap-3 px-4 py-3.5', bodyOpen && 'border-b border-border/70')}>
          {/* Fills the bar up to the search rather than hugging the label.
              The empty stretch beside a disclosure control looks like part of
              it, so clicking there and getting nothing reads as the page being
              broken - and it is the easiest part of the row to hit. */}
          <button
            onClick={() => setLaneOpen(o => !o)}
            aria-expanded={bodyOpen}
            className="group flex flex-1 min-w-0 items-center gap-2.5 -ml-1 pl-1 pr-2 py-1 text-left rounded-md transition-colors"
          >
            <ChevronRight className={cn('w-4 h-4 text-primary/60 shrink-0 transition-transform group-hover:text-primary', bodyOpen && 'rotate-90')} />
            <span className="font-sans text-[15px] font-bold tracking-[-0.01em] text-primary">This week</span>
          </button>
          <div className="relative w-44 shrink-0">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/70 pointer-events-none" />
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search clients…"
              className="w-full pl-8 pr-7 py-1.5 text-sm bg-card border border-border/50 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/40 transition-all"
            />
            {search && (
              <button
                onClick={() => { setSearch(''); searchRef.current?.focus(); }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/70 hover:text-muted-foreground"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="flex bg-muted border border-border/50 rounded-lg p-0.5">
            {([
              { id: 'summary', label: 'Summary', icon: Layers },
              { id: 'byday',   label: 'By day',  icon: CalendarDays },
              { id: 'work_summary', label: 'Work summary', icon: Sparkles },
            ] as { id: ViewMode; label: string; icon: React.ElementType }[]).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => { setView(id); setLaneOpen(true); }}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-md transition-all',
                  view === id ? 'bg-card text-primary shadow-sm' : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <MoveContext.Provider value={moveValue}>
        <div>
          {!bodyOpen ? null : isEmpty ? (
            <div className="text-center py-20 text-muted-foreground/70">
              {search ? (
                <>
                  <Search className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
                  <p className="font-medium text-muted-foreground">No clients match “{search}”</p>
                  <button onClick={() => setSearch('')} className="mt-2 text-sm text-primary hover:underline">Clear search</button>
                </>
              ) : (
                <>
                  <Clock className="w-10 h-10 text-muted-foreground/40 mx-auto mb-3" />
                  <p className="font-medium text-muted-foreground">No time tracked this week</p>
                  <p className="text-sm mt-1">Time appears here as it's captured by your desktop agent</p>
                </>
              )}
            </div>
          ) : view === 'summary' ? (
            <SummaryView
              mainClients={mainClients}
              tailClients={tailClients}
              tailTotals={tailTotals}
              expanded={expanded}
              tailOpen={tailOpen}
              onToggle={toggleExpand}
              onToggleTail={() => setTailOpen(o => !o)}
              weekBlocks={weekBlocks}
            />
          ) : view === 'byday' ? (
            <ByDayView clients={clients} days={days} dailyTotals={timesheetData?.daily_totals ?? {}} dailySpan={timesheetData?.daily_span ?? {}} grandTotal={grandTotal} dayBlocks={dayBlocks} />
          ) : (
            <WorkSummaryView clients={clients} weekEnd={timesheetData?.week_end ?? weekStart} weekLabel={formatWeekRange(weekStart)} />
          )}
        </div>
        </MoveContext.Provider>

      </div>

      {/* ── Sticky submit bar: stays reachable as the page scrolls ─────── */}
      <div className="sticky bottom-2 z-10 mt-4 rounded-[15px] border border-border/70 bg-card/95 backdrop-blur shadow-[0_8px_22px_-14px_rgba(16,27,46,0.32)] px-5 py-3 flex items-center justify-between gap-4">
        <div className="flex items-baseline gap-2.5">
          <span className={UPPER_LABEL}>Week total</span>
          <span className="font-mono text-base font-extrabold text-foreground tabular-nums">{fmtHours(grandTotal)}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground/70">
            <Lock className="w-3.5 h-3.5 text-muted-foreground/50" />
            Auto-captured ·{' '}
            <a href="/daily" className="text-primary font-medium hover:underline">Adjust in Daily Review →</a>
          </span>
          {submitButton}
        </div>
      </div>

      {/* ── Submit Modal ──────────────────────────────────────────────── */}
      {showSubmitModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-card rounded-2xl shadow-xl max-w-3xl w-full mx-4 max-h-[88vh] flex flex-col overflow-hidden">
            <div className="px-6 py-4 border-b border-border/50">
              <h3 className="text-base font-bold text-foreground">Submit Timesheet</h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                {timesheetData && formatWeekRange(timesheetData.week_start)}
              </p>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto">
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Total',    value: fmtHours(grandTotal), cls: 'text-foreground' },
                  { label: 'Billable', value: fmtHours(billable),   cls: 'text-primary' },
                  { label: 'Non-bill', value: fmtHours(nonBillable), cls: 'text-muted-foreground/70' },
                ].map(({ label, value, cls }) => (
                  <div key={label} className="text-center p-3 bg-muted/40 rounded-lg border border-border/50">
                    <p className={cn('text-lg font-bold tabular-nums', cls)}>{value}</p>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 mt-0.5">{label}</p>
                  </div>
                ))}
              </div>

              {/* Notes and the Clio summary sit side by side. Stacked, this
                  dialog ran taller than most laptop screens and the submit
                  button fell below the fold — the one control everything else
                  exists to inform. */}
              <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
                  Notes <span className="text-muted-foreground/70 normal-case font-normal">(optional)</span>
                </label>
                <textarea
                  value={submitNotes}
                  onChange={(e) => setSubmitNotes(e.target.value)}
                  placeholder="Anything your manager should know..."
                  className="w-full px-3 py-2.5 text-sm border border-border/60 rounded-lg focus:ring-2 focus:ring-primary/30 focus:border-primary resize-none"
                  rows={3}
                />
              </div>
              {/* What submitting sends to Clio. Absent entirely for firms
                  with no Clio connection. */}
              {clioPreview?.connected && clioPreview?.available === false && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
                  <p className="text-xs font-bold text-amber-800">Couldn't check Clio</p>
                  <p className="mt-0.5 text-[11px] text-amber-700">
                    {clioPreview.error || 'The preview failed to load.'} You can still submit —
                    time is sent when your manager approves, and nothing is lost.
                  </p>
                </div>
              )}
              {clioPreview?.connected && clioPreview?.available && (
                <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2.5">
                  <p className="text-xs font-bold text-indigo-800">
                    {clioPreview.totals?.entries > 0
                      ? (clioPreview.push_trigger === 'submit'
                          // Submitting IS the write, so say so.
                          ? `Submitting sends ${formatMinutes(clioPreview.totals.minutes)} across ${clioPreview.totals.entries} matter${clioPreview.totals.entries !== 1 ? 's' : ''} to Clio.`
                          // Approval is the gate. Promising "submitting sends" here
                          // would be false, and someone who believes their time
                          // reached billing will not chase the approval that
                          // actually releases it.
                          : `${formatMinutes(clioPreview.totals.minutes)} across ${clioPreview.totals.entries} matter${clioPreview.totals.entries !== 1 ? 's' : ''} goes to Clio once your manager approves this week.`)
                      : 'Nothing new to send to Clio — everything here is already there.'}
                  </p>
                  {clioPreview.entries?.length > 0 && (
                    <ul className="mt-1.5 space-y-0.5">
                      {clioPreview.entries.slice(0, 6).map((e: any, i: number) => (
                        <li key={i} className="text-[11px] text-indigo-700 flex justify-between gap-3">
                          <span className="truncate">{e.matter}</span>
                          <span className="tabular-nums shrink-0">{formatMinutes(e.push_minutes)}</span>
                        </li>
                      ))}
                      {clioPreview.entries.length > 6 && (
                        <li className="text-[11px] text-indigo-600">
                          + {clioPreview.entries.length - 6} more
                        </li>
                      )}
                    </ul>
                  )}
                  {clioPreview.skipped?.length > 0 && (
                    <details className="mt-1.5">
                      <summary className="text-[11px] font-semibold text-indigo-700 cursor-pointer">
                        {clioPreview.skipped.length} not being sent
                      </summary>
                      <ul className="mt-1 space-y-0.5">
                        {clioPreview.skipped.slice(0, 6).map((sk: any, i: number) => (
                          <li key={i} className="text-[11px] text-indigo-600">
                            <span>{sk.matter || sk.block_id}: {sk.detail}</span>
                            {/* Only an already-in-Clio skip is resolvable by a
                                person, and only then is there anything to show.
                                Every other reason renders exactly as before. */}
                            {sk.conflict_key && (
                              <span className="mt-0.5 block rounded bg-card px-2 py-1">
                                {sk.existing?.map((e: any, j: number) => (
                                  <span key={j} className="block truncate text-[10px] text-muted-foreground">
                                    already in Clio: {e.minutes}m — {e.note || '(no note)'}
                                  </span>
                                ))}
                                <button
                                  onClick={() => setForcedConflicts(prev =>
                                    prev.includes(sk.conflict_key) ? prev : [...prev, sk.conflict_key])}
                                  className="mt-1 rounded border border-indigo-300 px-2 py-0.5 text-[10px] font-semibold text-indigo-700 hover:bg-indigo-100"
                                >
                                  That's different work — send it too
                                </button>
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}
              </div>

              {!weekHasEnded && (
                <p className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-500" />
                  This week isn't over yet. You can submit early, but make sure your time is complete first.
                </p>
              )}
            </div>
            <div className="px-6 py-4 bg-muted/60 border-t border-border/50 flex items-center gap-3">
              <p className="hidden flex-1 text-xs text-muted-foreground/70 sm:block">
                Once submitted, you can't edit until your manager reviews it.
              </p>
              <button
                onClick={() => setShowSubmitModal(false)}
                className="px-4 py-2 text-sm font-semibold text-muted-foreground hover:bg-muted rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="px-5 py-2 bg-primary text-primary-foreground text-sm font-semibold rounded-lg hover:opacity-90 transition-all disabled:opacity-50 flex items-center gap-2"
              >
                {submitting
                  ? <><RefreshCw className="w-4 h-4 animate-spin" /> Submitting...</>
                  : <><CheckCircle2 className="w-4 h-4" /> Submit for Approval</>
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </HourFmtContext.Provider>
  );
};

// ── Summary View ──────────────────────────────────────────────────────────────

// Row popovers have to escape their container.
//
// The activity rows live in a wrapper with `overflow-hidden` (for the rounded
// corners and dividers), which clips any absolutely-positioned child. When a
// category group holds a single row that wrapper is about one row tall, so a
// menu opened from it was clipped to near-invisibility — it looked like the
// button did nothing.
//
// Rendering into a portal with fixed coordinates from the button's own rect
// sidesteps every clipping ancestor. Flips above the button when there is not
// room below.
const RowMenuPortal: React.FC<{
  anchorEl: HTMLElement | null;
  onClose: () => void;
  width: number;
  children: React.ReactNode;
}> = ({ anchorEl, onClose, width, children }) => {
  if (!anchorEl) return null;
  const r = anchorEl.getBoundingClientRect();
  const MAX_H = 288;
  const openUp = r.bottom + MAX_H > window.innerHeight && r.top > MAX_H;
  const style: React.CSSProperties = {
    position: 'fixed',
    left: Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8)),
    width,
    maxHeight: MAX_H,
    ...(openUp ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
  };
  return createPortal(
    <>
      <button className="fixed inset-0 z-[60] cursor-default"
              onClick={(e) => { e.stopPropagation(); onClose(); }} aria-label="Close" />
      <div style={style}
           className="z-[61] overflow-auto rounded-lg border border-border bg-card shadow-xl py-1">
        {children}
      </div>
    </>,
    document.body,
  );
};

// Popover menu to move a block to a different category (task type).
const BlockMoveMenu: React.FC<{ agg: AggBlock }> = ({ agg }) => {
  const ctx = React.useContext(MoveContext);
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  if (!ctx) return null;
  const busy = ctx.movingId != null && agg.ids.includes(ctx.movingId);
  const currentName = agg.taskTypeName || 'General';
  return (
    <span className="relative shrink-0">
      <button
        ref={btnRef}
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        disabled={busy}
        title={agg.count > 1 ? `Move these ${agg.count} blocks to another category` : 'Move this block to another category'}
        className="flex shrink-0 items-center gap-1 rounded-md border border-primary/25 bg-primary/5 px-2 py-1 text-[11px] font-semibold text-primary transition-colors hover:bg-primary/15 disabled:opacity-50"
      >
        {busy ? <RefreshCw className="w-3 h-3 animate-spin" /> : <FolderInput className="w-3 h-3" />}
        Move
      </button>
      {open && !busy && (
        <RowMenuPortal anchorEl={btnRef.current} onClose={() => setOpen(false)} width={224}>
          <p className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">Move to category</p>
            {ctx.taskTypes.map(tt => {
              const isCurrent = tt.name === currentName;
              return (
                <button
                  key={tt.id}
                  onClick={(e) => { e.stopPropagation(); setOpen(false); if (!isCurrent) ctx.onMove(agg.ids, tt.id); }}
                  className={cn('w-full flex items-center gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-muted/40',
                    isCurrent ? 'text-muted-foreground/70' : 'text-foreground')}
                >
                  <span className="flex-1 truncate">{tt.name}</span>
                  {isCurrent && <Check className="w-3.5 h-3.5 text-muted-foreground/50" />}
                  {!isCurrent && !tt.is_billable && <span className="text-[10px] text-muted-foreground/70">non-bill</span>}
                </button>
              );
            })}
        </RowMenuPortal>
      )}
    </span>
  );
};

// "opened Mar 2026" — month and year is enough to separate two matters and
// short enough to sit on one line.
const fmtMatterDate = (iso: string): string => {
  const d = new Date(iso + 'T00:00:00');
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
};

// Pick the matter this work belongs to, for the rows attribution abstained on.
//
// Only rendered for firms on Clio. Options are fetched when the menu opens
// rather than per row, because most rows already have a matter and a fetch per
// row would be one request per line of the timesheet.
//
// The note about future files is not decoration: assigning a matter teaches the
// folder, so the same choice never has to be made twice for that folder.
const BlockMatterMenu: React.FC<{
  agg: AggBlock;
  label?: string;
  tone?: 'resolved' | 'needed';
}> = ({ agg, label = 'Matter', tone = 'needed' }) => {
  const ctx = React.useContext(MoveContext);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState<any | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  if (!ctx?.clioEnabled || !ctx.onSetMatter) return null;

  const load = async () => {
    setLoading(true);
    try {
      const d = await safeFetchJson(`${API_BASE}/blocks/${agg.ids[0]}/matter-options/`);
      setData(d);
    } catch {
      setData({ options: [] });
    } finally {
      setLoading(false);
    }
  };

  const choose = async (projectId: number) => {
    setOpen(false);
    setSaving(true);
    try { await ctx.onSetMatter!(agg.ids, projectId); }
    finally { setSaving(false); }
  };

  return (
    <span className="relative shrink-0">
      <button
        ref={btnRef}
        onClick={(e) => {
          e.stopPropagation();
          const next = !open;
          setOpen(next);
          if (next && !data) load();
        }}
        disabled={saving}
        title={agg.count > 1
          ? `Set the matter for these ${agg.count} activities`
          : 'Set the matter this work belongs to'}
        className={cn(
          'flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition-colors disabled:opacity-50',
          tone === 'resolved'
            // Settled: legible but recessive. It is information, not a task.
            ? 'border-transparent bg-transparent text-muted-foreground hover:bg-muted'
            // Unresolved and actionable: amber, because this is the row that
            // will silently fail to reach a bill if nobody touches it.
            : 'border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100',
        )}
      >
        {saving ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Briefcase className="w-3 h-3" />}
        {label}
      </button>
      {open && !saving && (
        <RowMenuPortal anchorEl={btnRef.current} onClose={() => setOpen(false)} width={288}>
          <p className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">
              {data?.client_name ? `Matters for ${data.client_name}` : 'Set matter'}
            </p>
            {loading && <p className="px-3 py-2 text-[12px] text-muted-foreground/70">Loading…</p>}
            {!loading && data && data.options?.length === 0 && (
              <p className="px-3 py-2 text-[12px] text-muted-foreground">
                {data.client_id
                  ? `${data.client_name || 'This client'} has no open matters in Clio. Open one there, then sync from Settings → Integrations.`
                  : 'Assign a client first — a matter belongs to a client.'}
              </p>
            )}
            {!loading && data?.options?.map((o: any, i: number) => {
              const isCurrent = o.project_id === data.current_project_id;
              // Matters this person has actually worked come first; the divider
              // marks where that run ends so the ordering is legible rather
              // than mysterious.
              const prev = data.options[i - 1];
              const startsRest = !o.last_worked && (i === 0 || prev?.last_worked);
              // Same description on two matters is ordinary practice, so the
              // row has to carry something that separates them.
              const facts = [
                o.open_date ? `opened ${fmtMatterDate(o.open_date)}` : null,
                o.responsible_attorney || null,
                o.practice_area || null,
              ].filter(Boolean);
              return (
                <React.Fragment key={o.project_id}>
                  {i === 0 && o.last_worked && (
                    <p className="px-3 pt-1 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70">
                      Recently worked
                    </p>
                  )}
                  {startsRest && i > 0 && (
                    <p className="px-3 pt-2 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground/70 border-t border-border/50 mt-1">
                      Other matters
                    </p>
                  )}
                  <button
                    onClick={(e) => { e.stopPropagation(); if (!isCurrent) choose(o.project_id); }}
                    className={cn('w-full flex items-start gap-2 px-3 py-1.5 text-left text-[13px] hover:bg-muted/40',
                      isCurrent ? 'text-muted-foreground/70' : 'text-foreground')}
                  >
                    <span className="flex-1 min-w-0">
                      <span className="block truncate font-semibold">{o.display_number}</span>
                      {o.description && (
                        <span className="block truncate text-[11px] text-muted-foreground">{o.description}</span>
                      )}
                      {facts.length > 0 && (
                        <span className="block truncate text-[10px] text-muted-foreground/70">{facts.join(' · ')}</span>
                      )}
                      {o.requires_utbms && (
                        <span className="block text-[10px] text-amber-600">needs UTBMS codes — will not push</span>
                      )}
                      {(o.billing_method === 'flat' || o.billing_method === 'contingency') && (
                        <span className="block text-[10px] text-amber-600">{o.billing_method} fee — tracked, not pushed</span>
                      )}
                    </span>
                    {isCurrent && <Check className="w-3.5 h-3.5 text-muted-foreground/50 mt-0.5 shrink-0" />}
                  </button>
                </React.Fragment>
              );
            })}
          {!loading && data?.options?.length > 0 && (
            <p className="px-3 pt-1.5 pb-1 text-[10px] text-muted-foreground/70 border-t border-border/50 mt-1">
              Future work in the same folder goes here automatically.
            </p>
          )}
        </RowMenuPortal>
      )}
    </span>
  );
};

// What the row says about its matter, without anyone opening a menu.
//
// Three states, and only one of them needs a person:
//   * already on a matter  — show which, quietly. Clicking still changes it.
//   * no matter, but the client has several — this is the ONLY case a human can
//     resolve, so it is the only one that draws the eye.
//   * no matter and nothing to pick — say nothing. A client with no matters in
//     Clio is not a task, and an amber prompt there would be noise on every row.
//
// The single-matter case never reaches here: attribution assigns it
// automatically (the sole_matter tier), which is why it shows as resolved.
const MatterState: React.FC<{ agg: AggBlock }> = ({ agg }) => {
  const ctx = React.useContext(MoveContext);
  if (!ctx?.clioEnabled) return null;

  if (agg.matterLabel) {
    return <BlockMatterMenu agg={agg} label={agg.matterLabel} tone="resolved" />;
  }
  if (agg.matterOptions > 1) {
    return <BlockMatterMenu agg={agg} label="Choose matter" tone="needed" />;
  }
  if (agg.matterOptions === 1) {
    // One option but unassigned — attribution has not run over this block yet.
    return <BlockMatterMenu agg={agg} label="Set matter" tone="needed" />;
  }
  return null;
};

// One merged captured-activity row (all blocks sharing a title), listed under
// its category. Read-only info + a move menu. Captured title + time render in
// mono — the Daily Review signal for "text we read off the screen", vs the
// product's Plus Jakarta Sans UI voice. `title` exposes the full (untruncated)
// label on hover so long window titles stay readable.
const AggBlockRow: React.FC<{
  agg: AggBlock;
  withDay: boolean;
  categoryName?: string;
  categoryBillable?: boolean;
}> = ({ agg, withDay, categoryName, categoryBillable }) => (
  <div className="group flex items-center gap-2 pl-6 pr-1 py-0.5 min-w-0">
    <span className="font-mono text-[11px] text-muted-foreground/60 tabular-nums shrink-0 w-[76px] whitespace-nowrap">{formatBlockWhen(agg.firstStart, withDay)}</span>
    <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted-foreground" title={agg.label}>{agg.label}</span>
    {categoryName && (
      <span
        title={categoryBillable ? 'Billable' : 'Non-billable'}
        className={cn(
          'hidden shrink-0 rounded-full px-2 py-0.5 font-sans text-[10px] font-semibold sm:inline',
          categoryBillable ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
        )}
      >
        {categoryName}
      </span>
    )}
    {agg.count > 1 && (
      <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] font-semibold text-muted-foreground/70" title={`${agg.count} identical blocks merged`}>×{agg.count}</span>
    )}
    <span className="shrink-0 font-mono text-[12px] tabular-nums text-muted-foreground/70 w-[52px] text-right">{formatMinutes(agg.minutes)}</span>
    <MatterState agg={agg} />
    <BlockMoveMenu agg={agg} />
  </div>
);

// A single billable/non-billable category row inside a client (or a day→client).
// `hours` lets callers pass a day-scoped subtotal; defaults to the week total.
// `blocks` (when present) makes the row expand to its captured blocks.
const CategoryRow: React.FC<{ entry: TimesheetEntry; hours?: number; pctOf?: number; blocks?: DetailBlock[] | undefined; blocksWithDay?: boolean }> = ({ entry, hours, pctOf, blocks, blocksWithDay = false }) => {
  const [open, setOpen] = useState(false);
  const fmtHours = useFmtHours();
  const hasBlocks = !!blocks && blocks.length > 0;
  const mins = hours ?? entry.total;
  return (
    <>
      <div
        role={hasBlocks ? 'button' : undefined}
        onClick={hasBlocks ? () => setOpen(o => !o) : undefined}
        className={cn('flex items-center gap-2 py-2 min-w-0', hasBlocks && 'cursor-pointer')}
      >
        {hasBlocks
          ? <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform', open && 'rotate-90')} />
          : <span className="w-3.5 shrink-0" />}
        <span className="min-w-0 flex-1 truncate font-sans text-[13px] text-foreground">{entry.task_type_name}</span>
        <span className="hidden shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/70 sm:inline">
          {entry.is_billable ? 'billable' : 'non-bill'}
        </span>
        <span className="shrink-0 font-mono text-[12px] tabular-nums font-semibold text-foreground">{fmtHours(mins)}</span>
      </div>
      {hasBlocks && open && (
        <div className="mb-1 flex flex-col pb-1 pl-6">
          {aggregateBlocks(blocks!).map(ab => <AggBlockRow key={ab.key} agg={ab} withDay={blocksWithDay} />)}
        </div>
      )}
    </>
  );
};

// Every activity for a client, in time order, each tagged with the category it
// came from. Flattens the client → category → activity tree by one level.
const clientActivityRows = (
  agg: ClientAgg,
  weekBlocks: Map<string, DetailBlock[]>,
): { agg: AggBlock; categoryName: string; isBillable: boolean }[] => {
  const out: { agg: AggBlock; categoryName: string; isBillable: boolean }[] = [];
  for (const e of agg.entries) {
    const blocks = weekBlocks.get(wKey(blockClientKey(e.client_name), blockCatKey(e.task_type_name)));
    if (!blocks?.length) continue;
    for (const ab of aggregateBlocks(blocks)) {
      out.push({ agg: ab, categoryName: e.task_type_name || 'General', isBillable: e.is_billable });
    }
  }
  return out.sort((a, b) =>
    (a.agg.firstStart || '').localeCompare(b.agg.firstStart || '') || b.agg.minutes - a.agg.minutes);
};

const ClientRow: React.FC<{
  agg: ClientAgg;
  isExpanded: boolean;
  onToggle: (key: string) => void;
  weekBlocks: Map<string, DetailBlock[]>;
}> = ({ agg, isExpanded, onToggle, weekBlocks }) => {
  const noClient = isNoClient(agg);
  const fmtHours = useFmtHours();
  return (
    <>
      <button
        onClick={() => onToggle(agg.key)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-left hover:bg-muted/40 transition-colors"
      >
        <ChevronRight className={cn('w-3.5 h-3.5 text-muted-foreground/50 shrink-0 transition-transform', isExpanded && 'rotate-90')} />
        <span className={cn('flex-1 font-sans text-[14px] font-semibold truncate leading-tight',
          noClient ? 'italic text-muted-foreground' : 'text-foreground')}>
          {displayClientName(agg)}
        </span>
        {/* Same split Daily Review shows on every client, in the same words and
            the same type. Rendered even when a client is entirely one or the
            other: leaving those blank puts gaps down the column, and a gap
            reads as data that failed to load rather than as "all billable". */}
        <span className="hidden shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/70 sm:inline">
          {agg.billable > 0 && agg.nonBillable > 0
            ? `${fmtHours(agg.billable)} billable · ${fmtHours(agg.nonBillable)} non-bill`
            : agg.nonBillable > 0 ? 'all non-bill'
            : agg.billable > 0 ? 'all billable'
            : ''}
        </span>
        <span className="text-right font-mono text-[12.5px] font-semibold text-foreground tabular-nums shrink-0 w-[64px]">
          {fmtHours(agg.total)}
        </span>
      </button>

      {isExpanded && (
        <div className="px-4 pb-3 pt-1.5 bg-muted/40">
          <div className="ml-[26px] flex flex-col">
            {/* One click reaches the work. The category used to be a second
                expansion between client and activity, which put every block two
                clicks from the top and hid the rows that need a matter. It rides
                on the row as a chip instead — same information, no extra level. */}
            {clientActivityRows(agg, weekBlocks).map(({ agg: ab, categoryName, isBillable }) => (
              <AggBlockRow
                key={ab.key}
                agg={ab}
                withDay
                categoryName={categoryName}
                categoryBillable={isBillable}
              />
            ))}
          </div>
        </div>
      )}
    </>
  );
};

// ── Work summary: an AI-drafted, client-ready narrative of the week's work ──────
// Opt-in, read-only. Reuses GET /api/clients/<id>/work-summary/ scoped to this
// timesheet week (date=week_end, days=7) — a draft to review before it becomes a
// submission note or an invoice narrative. Never touches time or billing.
const isInternalName = (name: string) => {
  const n = (name || '').trim().toLowerCase();
  return n === 'internal' || n.startsWith('internal -');
};

type SummaryCell = { loading: boolean; text?: string; empty?: boolean; error?: boolean };

const WorkSummaryView: React.FC<{
  clients: ClientAgg[];
  weekEnd: string;
  weekLabel: string;
}> = ({ clients, weekEnd, weekLabel }) => {
  const [cell, setCell] = useState<SummaryCell>({ loading: false });
  const [copied, setCopied] = useState(false);

  // Real, billable-to clients only — skip Unassigned (null) and internal buckets.
  const real = useMemo(
    () => clients.filter(c => (c.entries[0]?.client_id ?? null) != null && !isInternalName(c.clientName)),
    [clients]
  );

  // One personable recap of the whole week across clients (not one per client).
  const gen = useCallback(async () => {
    setCell({ loading: true });
    try {
      const d = await safeFetchJson<{ summary: string; empty?: boolean; message?: string }>(
        `${API_BASE}/work-summary/week/?date=${weekEnd}&days=7`
      );
      setCell(d.empty
        ? { loading: false, empty: true, ...(d.message ? { text: d.message } : {}) }
        : { loading: false, text: d.summary || '' });
    } catch {
      setCell({ loading: false, error: true });
    }
  }, [weekEnd]);

  const copy = () => {
    if (!cell.text) return;
    try {
      navigator.clipboard?.writeText(cell.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch { /* noop */ }
  };

  if (!real.length) {
    return (
      <div className="text-center py-20 text-muted-foreground/70">
        <Sparkles className="w-10 h-10 text-muted-foreground/40 mx-auto mb-3" />
        <p className="font-medium text-muted-foreground">No client work to summarize this week</p>
        <p className="text-sm mt-1">The recap covers billable client time — not unassigned or internal work.</p>
      </div>
    );
  }

  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
          <Sparkles className="w-3.5 h-3.5 text-primary" /> Your week in review · {weekLabel}
        </div>
        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">AI draft — review before sending</span>
        <span className="flex-1" />
        {cell.text ? (
          <div className="flex items-center gap-2">
            <button onClick={copy} className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline">
              <Copy className="w-3 h-3" /> {copied ? 'Copied' : 'Copy'}
            </button>
            <button onClick={gen} className="text-[11px] font-medium text-muted-foreground/70 hover:text-muted-foreground">Regenerate</button>
          </div>
        ) : (
          <button onClick={gen} disabled={cell.loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/15 disabled:opacity-40">
            <Sparkles className="w-3.5 h-3.5" /> {cell.loading ? 'Writing…' : 'Generate my week summary'}
          </button>
        )}
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        {cell.loading ? (
          <div className="text-[12.5px] text-muted-foreground/70">Pulling together your week…</div>
        ) : cell.error ? (
          <div className="text-[12.5px] text-muted-foreground">Couldn’t generate right now. <button onClick={gen} className="font-medium text-primary hover:underline">Try again</button></div>
        ) : cell.empty ? (
          <div className="text-[12.5px] text-muted-foreground/70">{cell.text || 'No client work to summarize this week.'}</div>
        ) : cell.text ? (
          <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground">{cell.text}</div>
        ) : (
          <div className="text-[12.5px] text-muted-foreground/70">
            A friendly, bulleted recap of everything you worked on across {real.length} client{real.length !== 1 ? 's' : ''} this week — one summary, not one per client.
          </div>
        )}
      </div>
    </div>
  );
};

const SummaryView: React.FC<{
  mainClients: ClientAgg[];
  tailClients: ClientAgg[];
  tailTotals: { billable: number; nonBillable: number; total: number };
  expanded: Set<string>;
  tailOpen: boolean;
  onToggle: (key: string) => void;
  onToggleTail: () => void;
  weekBlocks: Map<string, DetailBlock[]>;
}> = ({ mainClients, tailClients, tailTotals, expanded, tailOpen, onToggle, onToggleTail, weekBlocks }) => {
  const fmtHours = useFmtHours();
  return (
  <div className="divide-y divide-border/60">
    {mainClients.map(agg => (
      <ClientRow key={agg.key} agg={agg} isExpanded={expanded.has(agg.key)} onToggle={onToggle} weekBlocks={weekBlocks} />
    ))}

    {tailClients.length > 0 && (
      <>
        <button
          onClick={onToggleTail}
          className="w-full flex items-center gap-2.5 px-4 py-2.5 text-left hover:bg-muted/40 transition-colors"
        >
          <ChevronDown className={cn('w-3.5 h-3.5 text-muted-foreground/50 shrink-0 transition-transform', tailOpen && 'rotate-180')} />
          <span className="flex-1 font-sans text-[13px] font-semibold text-muted-foreground truncate">
            {tailClients.length} more client{tailClients.length !== 1 ? 's' : ''} under 15 min
          </span>
          <span className="text-right font-mono text-[12.5px] font-semibold text-muted-foreground tabular-nums shrink-0 w-[64px]">{fmtHours(tailTotals.total)}</span>
        </button>

        {tailOpen && tailClients.map(agg => (
          <ClientRow key={agg.key} agg={agg} isExpanded={expanded.has(agg.key)} onToggle={onToggle} weekBlocks={weekBlocks} />
        ))}
      </>
    )}
  </div>
  );
};

// ── By-day View (day → client → category drill, mirrors Summary) ────────────────

type DayClient = { agg: ClientAgg; dayTotal: number; entries: TimesheetEntry[] };
type DayGroup  = { day: DayHeader; total: number; clients: DayClient[] };

const ByDayClientRow: React.FC<{
  dc: DayClient;
  date: string;
  isOpen: boolean;
  onToggle: (id: string) => void;
  dayBlocks: Map<string, DetailBlock[]>;
}> = ({ dc, date, isOpen, onToggle, dayBlocks }) => {
  const { agg } = dc;
  const noClient = isNoClient(agg);
  const fmtHours = useFmtHours();
  const id = `${date}::${agg.key}`;
  return (
    <>
      <button
        onClick={() => onToggle(id)}
        className="w-full flex items-center gap-3 pl-9 pr-5 py-2.5 text-left hover:bg-muted/40 transition-colors"
      >
        <ChevronRight className={cn('w-3.5 h-3.5 text-muted-foreground/50 shrink-0 transition-transform', isOpen && 'rotate-90')} />
        <span className={cn('flex-1 text-[13px] font-bold truncate leading-tight',
          noClient ? 'italic text-muted-foreground/70 font-semibold' : 'text-foreground')}>
          {displayClientName(agg)}
        </span>
        <span className={HOURS_CELL}>{fmtHours(dc.dayTotal)}</span>
      </button>
      {isOpen && (
        <div className="px-4 pb-3 pt-1.5 bg-muted/40">
          <div className="ml-[26px] flex flex-col">
            {dc.entries.map(e => (
              <CategoryRow
                key={`${e.client_id}-${e.task_type_id}`}
                entry={e}
                hours={e.days[date] || 0}
                pctOf={dc.dayTotal}
                blocks={dayBlocks.get(dKey(date, blockClientKey(e.client_name), blockCatKey(e.task_type_name)))}
              />
            ))}
          </div>
        </div>
      )}
    </>
  );
};

const ByDayView: React.FC<{
  clients: ClientAgg[];
  days: DayHeader[];
  dailyTotals: Record<string, number>;
  dailySpan: Record<string, { start: string; end: string } | null>;
  grandTotal: number;
  dayBlocks: Map<string, DetailBlock[]>;
}> = ({ clients, days, dailyTotals, dailySpan, grandTotal, dayBlocks }) => {
  const fmtHours = useFmtHours();
  // One group per day that had time; clients ranked by that day's minutes, No client last.
  const groups = useMemo<DayGroup[]>(() =>
    days.map(day => {
      const dayClients: DayClient[] = clients
        .map(agg => {
          const entries = agg.entries.filter(e => (e.days[day.date] || 0) > 0);
          const dayTotal = entries.reduce((s, e) => s + (e.days[day.date] || 0), 0);
          return { agg, dayTotal, entries };
        })
        .filter(c => c.dayTotal > 0)
        .sort((a, b) => {
          const au = isNoClient(a.agg) ? 1 : 0;
          const bu = isNoClient(b.agg) ? 1 : 0;
          if (au !== bu) return au - bu;
          return b.dayTotal - a.dayTotal;
        });
      return { day, clients: dayClients, total: dailyTotals[day.date] || dayClients.reduce((s, c) => s + c.dayTotal, 0) };
    }).filter(g => g.clients.length > 0),
  [clients, days, dailyTotals]);

  // Accordion: all days start collapsed; opening one closes any other. Clients closed by default.
  const [openDay, setOpenDay]         = useState<string | null>(null);
  const [openClients, setOpenClients] = useState<Set<string>>(new Set());
  const toggleDay    = (d: string) => setOpenDay(prev => (prev === d ? null : d));
  const toggleClient = (id: string) => setOpenClients(p => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });

  if (!groups.length) {
    return (
      <div className="text-center py-20 text-muted-foreground/70">
        <CalendarDays className="w-10 h-10 text-muted-foreground/40 mx-auto mb-3" />
        <p className="font-medium text-muted-foreground">No time tracked on any day this week</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-border/40">
      {groups.map(({ day, total, clients: dayClients }) => {
        const dayOpen = openDay === day.date;
        const span = dailySpan[day.date];
        return (
          <div key={day.date}>
            <button
              onClick={() => toggleDay(day.date)}
              className={cn('w-full flex items-center gap-3 px-5 py-2.5 text-left transition-colors',
                day.isWeekend ? 'bg-muted/40' : '', 'hover:bg-muted/40')}
            >
              <ChevronDown className={cn('w-3.5 h-3.5 text-muted-foreground/70 shrink-0 transition-transform', !dayOpen && '-rotate-90')} />
              <span className={cn('text-[10px] font-bold uppercase tracking-widest shrink-0 w-9',
                day.isToday ? 'text-primary' : 'text-muted-foreground/70')}>
                {day.label}
              </span>
              <span className={cn('text-sm font-bold shrink-0 tabular-nums',
                day.isToday ? 'text-primary' : 'text-foreground')}>
                {day.dayNum}
              </span>
              {day.isToday && <span className="text-[10px] font-bold text-primary">Today</span>}
              <span className="flex-1" />
              {span && (
                <span
                  className="text-[11px] font-medium text-muted-foreground/70 tabular-nums shrink-0 hidden md:inline"
                  title="Workday span: your first to last tracked activity that day (clock-in/out estimated from activity)."
                >
                  {span.start}–{span.end}
                </span>
              )}
              <span className="text-[11px] text-muted-foreground/70 tabular-nums shrink-0 hidden sm:inline">
                {dayClients.length} client{dayClients.length !== 1 ? 's' : ''}
              </span>
              <span className="text-right text-[15px] font-extrabold text-foreground tabular-nums shrink-0 w-[64px]">
                {fmtHours(total)}
              </span>
            </button>
            {dayOpen && (
              <div className="divide-y divide-border/20 border-t border-border/20">
                {dayClients.map(dc => (
                  <ByDayClientRow
                    key={dc.agg.key}
                    dc={dc}
                    date={day.date}
                    isOpen={openClients.has(`${day.date}::${dc.agg.key}`)}
                    onToggle={toggleClient}
                    dayBlocks={dayBlocks}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      <div className="flex items-center gap-3 px-5 py-3 bg-card border-t-2 border-border/50">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70">Week total</span>
        <span className="flex-1" />
        <span className="text-right text-[15px] font-extrabold text-primary tabular-nums w-[64px]">{fmtHours(grandTotal)}</span>
      </div>
    </div>
  );
};

export default WeeklyTimesheet;
