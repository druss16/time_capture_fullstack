/**
 * CategorySummary.tsx
 */

import React, { useState, useRef, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  ChevronRight,
  GripVertical,
  AlertTriangle,
  Smartphone,
  Sparkles,
  AlertCircle,
  FileQuestion,
  CheckSquare,
  Square,
  X,
  ArrowRightLeft,
  MousePointerClick,
  Mail,
  CalendarClock,
  Clock
} from "lucide-react";
import { cn, getClientColor, SKELETON } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";

import { BlockEvidencePanel } from "@/components/BlockEvidencePanel";


const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api")
  ? RAW_BASE
  : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// ─── Types ────────────────────────────────────────────────────────────────────

export type Category = {
  name: string;
  hours: number;
  block_count: number;
  sample_activities: string[];
  needs_review?: boolean;
  task_type_code?: string | null;
  task_type_name?: string | null;
};
export type ClientTime = {
  client_id: number | null;
  client: string;
  total_hours: number;
  categories: Category[];
};
export type ClientOption = { id: number; name: string };
type FlaggedBlock = {
  block_id: number;
  client_name: string;
  review_reason: string;
  minutes: number;
  start: string;
  type?: 'mobile_review' | 'ai_disagreement' | 'mail_disagreement' | 'calendar_disagreement' | 'second_pass';
  ai_proposed_client_id?: number | null;
  ai_proposed_client_name?: string | null;
  ai_confidence?: number;
  ai_reasoning?: string;
  mail_proposed_client_id?: number | null;
  mail_proposed_client_name?: string | null;
  mail_confidence?: number;
  mail_reasoning?: string;
  // v1.3.42: Stage 6 calendar disagreement fields
  calendar_proposed_client_id?: number | null;
  calendar_proposed_client_name?: string | null;
  calendar_confidence?: number;
  calendar_reasoning?: string;
  calendar_disagreement_source?: 'classifier' | 'manual';
  window_title?: string;
  proposed_client_id?: number | null;
  proposed_client_name?: string | null;
  proposed_confidence?: number;
  proposed_category?: string | null;
  proposed_reasoning?: string;
};
type ProposedInline = {
  block_id: number;
  window_title: string;
  minutes: number;
  proposed_client_id: number | null;
  proposed_client_name: string | null;
  proposed_confidence: number;
  proposed_category: string;
};

type ParsedActivity = { blockId: number | null; blockIds: number[]; title: string };


// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (hours: number): string => {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
};

const parse = (activity: string): ParsedActivity => {
  // Supports multi-id rows: [id:44763,44767]
  const match = activity.match(/\[id:([\d,]+)\]\s*/);
  if (match) {
    const ids = match[1].split(",").map((s) => parseInt(s)).filter((n) => !isNaN(n));
    return {
      blockId: ids[0] ?? null,        // first id (back-compat for single-id callers)
      blockIds: ids,                   // ALL ids in this row
      title: activity.replace(/\[id:[\d,]+\]\s*/, "").trim(),
    };
  }
  return { blockId: null, blockIds: [], title: activity };
};

const isNonBillable = (name: string) => {
  const n = name.toLowerCase();
  return (
    n.includes("idle") ||
    n.includes("uncategorized") ||
    n.includes("personal") ||
    n.includes("pto") ||
    n.includes("time off")
  );
};

// Firm-internal clients ("Internal" / "Internal - <x>", e.g. Internal - Tax,
// Internal - Accounting) are never billable — mirrors the backend predicate
// tracker.industry_categories.is_internal_client_name. Daily Review dims these
// so the UI matches how reports/timesheet now treat the time.
const isInternalClient = (name: string) => {
  const n = (name || "").trim().toLowerCase();
  return n === "internal" || n.startsWith("internal -");
};

const CLIENT_ACCENTS = [
  { border: "border-l-teal-500",    header: "bg-teal-50",    hours: "text-teal-600"    },
  { border: "border-l-amber-400",   header: "bg-amber-50",   hours: "text-amber-500"   },
  { border: "border-l-violet-500",  header: "bg-violet-50",  hours: "text-violet-600"  },
  { border: "border-l-sky-500",     header: "bg-sky-50",     hours: "text-sky-600"     },
  { border: "border-l-rose-500",    header: "bg-rose-50",    hours: "text-rose-600"    },
  { border: "border-l-emerald-500", header: "bg-emerald-50", hours: "text-emerald-600" },
];

// ─── Move Popover ─────────────────────────────────────────────────────────────

function MovePopover({
  anchorEl, clients, categories, currentClientId, currentCategory, label, onApply, onClose,
}: {
  anchorEl?: HTMLElement | null;
  clients: ClientOption[]; categories: string[];
  currentClientId: number | null; currentCategory: string;
  label: string;
  onApply: (clientId: number | null, category: string) => void;
  onClose: () => void;
}) {
  const [selClient, setSelClient] = useState<number | null>(currentClientId);
  const [selCat, setSelCat] = useState(currentCategory);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const catRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    const el = anchorEl ?? document.body;
    const rect = el.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.right - 268, window.innerWidth - 276));
    setPos({ top: rect.bottom + window.scrollY + 6, left });
    setTimeout(() => catRef.current?.focus(), 60);
  }, []);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popRef.current && !popRef.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); onApply(selClient, selCat); }
    };
    document.addEventListener("keydown", handler, true);
    return () => document.removeEventListener("keydown", handler, true);
  }, [onClose, onApply, selClient, selCat]);

  const hasChanged = selClient !== currentClientId || selCat !== currentCategory;

  if (!pos) return null;

  return createPortal(
    <div
      ref={popRef}
      data-popover="true"
      style={{ position: "absolute", top: pos.top, left: pos.left, zIndex: 99999, width: 268 }}
      className="bg-white border border-slate-200 rounded-xl shadow-2xl p-4"
    >
      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">{label}</p>
      <div className="space-y-2 mb-3">
        <div>
          <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1 block">Client</label>
          <select
            value={selClient ?? ""}
            onChange={(e) => setSelClient(e.target.value ? parseInt(e.target.value) : null)}
            className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm font-medium bg-white focus:border-primary focus:ring-1 focus:ring-primary/20 focus:outline-none"
          >
            <option value="">Unassigned</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wide mb-1 block">Category</label>
          <select
            ref={catRef}
            value={selCat}
            onChange={(e) => setSelCat(e.target.value)}
            className="w-full border border-primary/40 rounded-lg px-3 py-2 text-sm font-medium bg-white focus:border-primary focus:ring-1 focus:ring-primary/20 focus:outline-none ring-1 ring-primary/10"
          >
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>
      <p className="text-[10px] text-slate-300 mb-3">Press Enter to apply · Escape to cancel</p>
      <div className="flex gap-2">
        <button
          onClick={() => onClose()}
          className="flex-1 py-2 border border-slate-200 rounded-lg text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={() => onApply(selClient, selCat)}
          disabled={!hasChanged}
          className={cn(
            "flex-1 py-2 rounded-lg text-sm font-semibold shadow-sm transition-all",
            hasChanged ? "bg-primary text-white hover:opacity-90" : "bg-slate-100 text-slate-400 cursor-not-allowed"
          )}
        >
          Apply
        </button>
      </div>
    </div>,
    document.body
  );
}

// ─── Inline Move Picker ───────────────────────────────────────────────────────

function InlineMovePicker({
  clients, categories, count, currentClientId, currentCategory, onApply, onClose,
}: {
  clients: ClientOption[]; categories: string[];
  count: number;
  currentClientId: number | null;
  currentCategory: string;
  onApply: (clientId: number | null, category: string) => void;
  onClose: () => void;
}) {
  const [selClient, setSelClient] = useState<number | null>(currentClientId);
  const [selCat, setSelCat] = useState(currentCategory || categories[0] || "");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2 w-64 bg-white border border-slate-200 rounded-xl shadow-xl p-4"
      style={{ zIndex: 9999 }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-3">
        Move {count} selected activit{count !== 1 ? "ies" : "y"}
      </p>
      <div className="space-y-2 mb-4">
        <select
          value={selClient ?? ""}
          onChange={(e) => setSelClient(e.target.value ? parseInt(e.target.value) : null)}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm font-medium bg-white text-slate-900 focus:border-primary focus:ring-1 focus:ring-primary/20 focus:outline-none"
        >
          <option value="">Unassigned</option>
          {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select
          value={selCat}
          onChange={(e) => setSelCat(e.target.value)}
          className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm font-medium bg-white text-slate-900 focus:border-primary focus:ring-1 focus:ring-primary/20 focus:outline-none"
        >
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="flex gap-2">
        <button onClick={onClose} className="flex-1 py-2 border border-slate-200 rounded-lg text-sm font-semibold text-slate-600 hover:bg-slate-50 transition-colors">
          Cancel
        </button>
        <button onClick={() => onApply(selClient, selCat)} className="flex-1 py-2 bg-primary text-white rounded-lg text-sm font-semibold hover:opacity-90 transition-all">
          Apply
        </button>
      </div>
    </div>
  );
}

// ─── Floating Selection Bar ───────────────────────────────────────────────────

function SelectionBar({
  count, clients, categories, currentClientId, currentCategory, onMove, onClear,
}: {
  count: number;
  clients: ClientOption[];
  categories: string[];
  currentClientId: number | null;
  currentCategory: string;
  onMove: (clientId: number | null, category: string) => void;
  onClear: () => void;
}) {
  const [showPopover, setShowPopover] = useState(false);
  if (count === 0) return null;

  return (
    <div
      className="fixed bottom-6 left-1/2 z-50 flex items-center gap-3 px-4 py-2.5 bg-slate-900 text-white rounded-2xl shadow-2xl"
      style={{ transform: "translateX(-50%)" }}
    >
      <span className="text-sm font-semibold text-white/80">
        {count} item{count !== 1 ? "s" : ""} selected
      </span>
      <div className="w-px h-4 bg-white/20" />
      <div className="relative">
        <button
          onClick={() => setShowPopover((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary rounded-xl text-xs font-bold hover:opacity-90 transition-all"
        >
          <ArrowRightLeft className="w-3 h-3" />
          Move selected
        </button>
        {showPopover && (
          <InlineMovePicker
            clients={clients}
            categories={categories}
            count={count}
            currentClientId={currentClientId}
            currentCategory={currentCategory}
            onApply={(clientId, category) => { setShowPopover(false); onMove(clientId, category); }}
            onClose={() => setShowPopover(false)}
          />
        )}
      </div>
      <button
        onClick={onClear}
        className="flex items-center gap-1 px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-xl text-xs font-bold text-white/70 transition-all"
      >
        <X className="w-3 h-3" />
        Clear
      </button>
    </div>
  );
}

// ─── App grouping ─────────────────────────────────────────────────────────────

const APP_PREFIXES = [
  "Chrome", "Safari", "Firefox", "Edge", "Sublime Text", "VS Code",
  "Xcode", "Terminal", "iTerm", "Finder", "Excel", "Word",
  "Outlook", "Slack", "Zoom", "Timetrackeragent",
];

type AppGroup = {
  app: string;
  activities: string[];
  totalMinutes: number;
};

const extractApp = (title: string): string | null => {
  for (const prefix of APP_PREFIXES) {
    if (title.startsWith(prefix + " - ") || title.startsWith(prefix + " · ") || title === prefix) {
      return prefix;
    }
  }
  return null;
};

const extractMinutes = (title: string): number => {
  const m = title.match(/\((\d+)m\)$/);
  return m ? parseInt(m[1]) : 0;
};

const groupActivities = (activities: string[]): AppGroup[] => {
  const groups: Map<string, AppGroup> = new Map();
  const ungrouped: string[] = [];

  for (const raw of activities) {
    const { title } = parse(raw);
    const app = extractApp(title);
    if (app) {
      if (!groups.has(app)) groups.set(app, { app, activities: [], totalMinutes: 0 });
      const g = groups.get(app)!;
      g.activities.push(raw);
      g.totalMinutes += extractMinutes(title);
    } else {
      ungrouped.push(raw);
    }
  }

  const result: AppGroup[] = [];
  for (const [app, group] of groups) {
    if (group.activities.length >= 2) result.push(group);
    else ungrouped.push(...group.activities);
  }

  for (const raw of ungrouped) {
    const { title } = parse(raw);
    result.push({ app: "", activities: [raw], totalMinutes: extractMinutes(title) });
  }

  return result.sort((a, b) => {
    if (a.activities.length > 1 && b.activities.length === 1) return -1;
    if (a.activities.length === 1 && b.activities.length > 1) return 1;
    return b.totalMinutes - a.totalMinutes;
  });
};

// ─── App Group Header ─────────────────────────────────────────────────────────

function AppGroupHeader({
  app, count, totalMinutes, expanded, onToggle,
  allClients, allCategories, currentClientId, categoryName,
  blockIds, onMoveAll,
}: {
  app: string; count: number; totalMinutes: number; expanded: boolean;
  onToggle: () => void;
  allClients: ClientOption[]; allCategories: string[];
  currentClientId: number | null; categoryName: string;
  blockIds: number[];
  onMoveAll: (clientId: number | null, category: string) => void;
}) {
  const [showMove, setShowMove] = useState(false);

  return (
    <li style={{ listStyle: "none" }} className="relative">
      <div className="flex items-center gap-1.5 px-2 py-1 group/appgrp">
        <button
          onClick={onToggle}
          className="flex items-center gap-1.5 flex-1 min-w-0 text-left"
        >
          {expanded
            ? <ChevronDown className="w-3 h-3 text-slate-400 flex-shrink-0" />
            : <ChevronRight className="w-3 h-3 text-slate-400 flex-shrink-0" />}
          <span className="text-xs font-bold text-slate-500 truncate">{app}</span>
          <span className="text-[10px] text-slate-400 font-medium flex-shrink-0">
            {count} {count === 1 ? "entry" : "entries"} · {totalMinutes}m
          </span>
        </button>
        {blockIds.length > 0 && (() => {
          const btnRef = React.createRef<HTMLButtonElement>();
          return (
            <div className="relative flex-shrink-0">
              <button
                ref={btnRef}
                onClick={(e) => { e.stopPropagation(); setShowMove((v) => !v); }}
                className="opacity-0 group-hover/appgrp:opacity-100 px-2 py-0.5 text-[10px] font-semibold border border-slate-200 rounded-md hover:border-primary hover:text-primary text-slate-400 transition-all"
              >
                Move all
              </button>
              {showMove && (
                <MovePopover
                  anchorEl={btnRef.current}
                  clients={allClients}
                  categories={allCategories}
                  currentClientId={currentClientId}
                  currentCategory={categoryName}
                  label={`Move all ${count} ${app} entries`}
                  onApply={(clientId, category) => { setShowMove(false); onMoveAll(clientId, category); }}
                  onClose={() => setShowMove(false)}
                />
              )}
            </div>
          );
        })()}
      </div>
    </li>
  );
}

// ─── Activity List ────────────────────────────────────────────────────────────

function ActivityList({
  activities, client, categoryName, allClients, allCategories,
  onMove, onCrossMove, draggingBlockId, selectedIds, onToggleSelect,
}: {
  activities: string[];
  client: ClientTime;
  categoryName: string;
  allClients: ClientOption[];
  allCategories: string[];
  onMove: (blockId: number, clientId: number | null, category: string) => Promise<void>;
  onCrossMove: (blockId: number, clientId: number | null, category: string) => Promise<void>;
  draggingBlockId: number | null;
  selectedIds: Set<number>;
  onToggleSelect: (rowKey: string, idx: number, shift: boolean) => void;
}) {
  const [insertAfterIdx, setInsertAfterIdx] = useState<number | null>(null);
  const [collapsedApps, setCollapsedApps] = useState<Set<string>>(new Set());
  const listRef = useRef<HTMLUListElement>(null);

  const nonZero = activities.filter((a) => !/ \(0m\)$/.test(parse(a).title));
  const groups = groupActivities(nonZero);

  const handleRowDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault(); e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setInsertAfterIdx(e.clientY < rect.top + rect.height / 2 ? idx - 1 : idx);
  };

  const handleListDragLeave = (e: React.DragEvent) => {
    if (!listRef.current?.contains(e.relatedTarget as Node)) setInsertAfterIdx(null);
  };

  const handleRowDrop = async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setInsertAfterIdx(null);
    let raw = "";
    try { raw = e.dataTransfer.getData("application/x-block"); } catch {}
    if (!raw) return;
    let parsed2: any;
    try { parsed2 = JSON.parse(raw); } catch { return; }
    const { blockId, fromClient, fromCategory } = parsed2;
    if (!blockId) return;
    if (fromClient !== client.client || fromCategory !== categoryName)
      await onCrossMove(blockId, client.client_id, categoryName);
  };

  const InsertionLine = () => (
    <li style={{ listStyle: "none", padding: 0, margin: "1px 0" }}>
      <div style={{ height: 2, background: "#EAB308", borderRadius: 2, margin: "0 8px" }} />
    </li>
  );

  let globalIdx = 0;

  return (
    <ul
      ref={listRef}
      className="pb-2 px-3 space-y-0 ml-6"
      onDragLeave={handleListDragLeave}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleRowDrop}
    >
      {groups.map((group, groupIdx) => {
        const isGrouped = group.app && group.activities.length >= 2;
        const isCollapsed = isGrouped && collapsedApps.has(group.app);
        const groupBlockIds = group.activities
          .map((a) => parse(a).blockId)
          .filter((id): id is number => id !== null);

        return (
          <React.Fragment key={group.app || `ungrouped-${groupIdx}`}>
            {isGrouped && (
              <AppGroupHeader
                app={group.app}
                count={group.activities.length}
                totalMinutes={group.totalMinutes}
                expanded={!isCollapsed}
                onToggle={() => setCollapsedApps((prev) => {
                  const next = new Set(prev);
                  next.has(group.app) ? next.delete(group.app) : next.add(group.app);
                  return next;
                })}
                allClients={allClients}
                allCategories={allCategories}
                currentClientId={client.client_id}
                categoryName={categoryName}
                blockIds={groupBlockIds}
                onMoveAll={async (clientId, category) => {
                  for (const id of groupBlockIds) await onMove(id, clientId, category);
                }}
              />
            )}

            {!isCollapsed && group.activities.map((activity) => {
              const parsed = parse(activity);
              const isBeingDragged = parsed.blockId === draggingBlockId;
              const idx = globalIdx++;
              const rowKey = `${parsed.blockId ?? "no-id"}-${idx}`;
              const isSelected = selectedIds.has(rowKey as any);
              const displayTitle = isGrouped
                ? parse(activity).title.replace(
                    new RegExp(`^${group.app}\\s*[-·]\\s*`), ""
                  ).trim()
                : undefined;

              // All blocks in THIS category section sharing this row's title.
              // "Click to move" moves the whole title-group at once (e.g. all
              // 115 "Sacred Heart-Rome-Budgets" rows), not one block at a time.
              const thisTitle = parsed.title;
              const parsedRow = parse(activity);
              const siblingBlockIds = parsedRow.blockIds.length > 0
                ? parsedRow.blockIds
                : (parsedRow.blockId ? [parsedRow.blockId] : []);

              return (
                <React.Fragment key={rowKey}>
                  {insertAfterIdx === idx - 1 && <InsertionLine />}
                  <ActivityRow
                    activity={activity}
                    displayTitle={displayTitle}
                    client={client}
                    categoryName={categoryName}
                    allClients={allClients}
                    allCategories={allCategories}
                    onMove={onMove}
                    isBeingDragged={isBeingDragged}
                    isSelected={isSelected}
                    onDragOver={(e) => handleRowDragOver(e, idx)}
                    onToggleSelect={(_shift) => onToggleSelect(rowKey, idx, false)}
                    indented={isGrouped}
                    siblingBlockIds={siblingBlockIds}
                  />
                  {insertAfterIdx === idx && <InsertionLine />}
                </React.Fragment>
              );
            })}
          </React.Fragment>
        );
      })}
    </ul>
  );
}

// ─── Activity Row ─────────────────────────────────────────────────────────────

function ActivityRow({
  activity, displayTitle, client, categoryName, allClients, allCategories,
  onMove, isBeingDragged, isSelected, onDragOver, onToggleSelect, indented,
  siblingBlockIds,
}: {
  activity: string;
  displayTitle?: string;
  client: ClientTime;
  categoryName: string;
  allClients: ClientOption[];
  allCategories: string[];
  onMove: (blockId: number, clientId: number | null, category: string) => Promise<void>;
  isBeingDragged: boolean;
  isSelected: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onToggleSelect: (shift: boolean) => void;
  indented?: boolean;
  siblingBlockIds?: number[];
}) {
  const [showPopover, setShowPopover] = useState(false);
  const [checkboxActive, setCheckboxActive] = useState(false);
  const liRef = useRef<HTMLLIElement>(null);
  const parsed = parse(activity);

  const handleDragStart = (e: React.DragEvent) => {
    if (checkboxActive) { e.preventDefault(); return; }
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData(
      "application/x-block",
      JSON.stringify({ blockId: parsed.blockId, fromClient: client.client, fromCategory: categoryName })
    );
    const ghost = document.createElement("div");
    Object.assign(ghost.style, {
      position: "fixed", top: "-999px", left: "-999px",
      background: "#2B9D90", color: "white",
      padding: "5px 12px", borderRadius: "99px",
      fontSize: "12px", fontWeight: "600", whiteSpace: "nowrap",
      maxWidth: "320px", overflow: "hidden", textOverflow: "ellipsis",
      boxShadow: "0 4px 12px rgba(0,0,0,0.2)", pointerEvents: "none",
    });
    ghost.textContent = `↗ ${parsed.title}`;
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, 16, 16);
    setTimeout(() => document.body.removeChild(ghost), 0);
  };

  const handleApply = async (clientId: number | null, category: string) => {
    setShowPopover(false);
    const ids = (siblingBlockIds && siblingBlockIds.length > 0)
      ? siblingBlockIds
      : (parsed.blockId ? [parsed.blockId] : []);
    for (const id of ids) await onMove(id, clientId, category);
  };

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.stopPropagation(); e.preventDefault();
    e.nativeEvent.stopImmediatePropagation();
    onToggleSelect(false);
  };

  const [showActivity, setShowActivity] = useState(false);
  const [activityCtx, setActivityCtx] = useState<{ dominant: string[]; brief: string[] } | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);

  const toggleActivity = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    const next = !showActivity;
    setShowActivity(next);
    if (next && activityCtx === null && parsed.blockId) {
      setActivityLoading(true);
      try {
        const ctx = await safeFetchJson<{ dominant: string[]; brief: string[] }>(
          `${API_BASE}/blocks/${parsed.blockId}/tab-context/`
        );
        setActivityCtx(ctx);
      } catch {
        setActivityCtx({ dominant: [], brief: [] });
      } finally {
        setActivityLoading(false);
      }
    }
  }, [showActivity, activityCtx, parsed.blockId]);

  return (
    <li
      ref={liRef}
      draggable={!!parsed.blockId && !isSelected}
      onDragStart={handleDragStart}
      onDragOver={onDragOver}
      onClick={parsed.blockId ? (e) => {
        const target = e.target as HTMLElement;
        if (target.closest("[data-popover]") || target.closest("button") || target.closest("select") || target.closest("label")) return;
        if (isSelected) {
          setCheckboxActive(true);
          handleCheckboxClick(e as any);
          setTimeout(() => setCheckboxActive(false), 300);
          return;
        }
        e.stopPropagation();
        setShowPopover((v) => !v);
      } : undefined}
      className={cn(
        "flex items-center gap-1.5 group/item rounded-lg px-2 py-1.5 transition-all relative select-none",
        indented && "pl-5",
        parsed.blockId && !isSelected && "cursor-pointer hover:bg-slate-50",
        parsed.blockId && isSelected && "cursor-pointer",
        isBeingDragged && "opacity-30",
        isSelected && !isBeingDragged && "bg-primary/8 ring-1 ring-primary/25",
      )}
      style={{ listStyle: "none" }}
    >
      {parsed.blockId ? (
        <div
          className={cn(
            "flex-shrink-0 w-4 h-4 flex items-center justify-center transition-opacity",
            isSelected ? "opacity-100" : "opacity-0 group-hover/item:opacity-40"
          )}
          onClick={(e) => {
            e.stopPropagation();
            setCheckboxActive(true);
            handleCheckboxClick(e as any);
            setTimeout(() => setCheckboxActive(false), 300);
          }}
        >
          {isSelected
            ? <CheckSquare className="w-3.5 h-3.5 text-primary" />
            : <Square className="w-3.5 h-3.5 text-slate-400" />}
        </div>
      ) : <span className="w-4 flex-shrink-0" />}

      {parsed.blockId && !isSelected ? (
        <GripVertical className="w-3 h-3 text-slate-200 group-hover/item:text-slate-400 flex-shrink-0 transition-colors" />
      ) : <span className="w-3 flex-shrink-0" />}

      <span className="w-2 h-px bg-slate-200 flex-shrink-0" />

      <span
        title={displayTitle ?? parsed.title}
        className={cn(
          "text-sm flex-1 truncate",
          isSelected ? "text-primary font-semibold" : "text-slate-600 font-medium"
        )}
      >
        {displayTitle ?? parsed.title}
      </span>

      {parsed.blockId && !isSelected && (
        <div className="flex items-center gap-1 flex-shrink-0 relative">
          <span className="text-[11px] font-medium text-slate-300 group-hover/item:text-primary transition-colors">
            click to move
          </span>
          {showPopover && (
            <MovePopover
              anchorEl={liRef.current}
              clients={allClients}
              categories={allCategories}
              currentClientId={client.client_id}
              currentCategory={categoryName}
              label="Move this activity"
              onApply={handleApply}
              onClose={() => setShowPopover(false)}
            />
          )}
        </div>
      )}

      {parsed.blockId && (
        <button
          onClick={toggleActivity}
          title="See what this block touched"
          className="text-[11px] font-medium text-slate-300 hover:text-primary transition-colors flex-shrink-0 ml-1"
        >
          {showActivity ? "hide" : "activity"}
        </button>
      )}

      {showActivity && (
        <div
          className="basis-full mt-1.5 ml-9 mr-2 space-y-1 text-[11px]"
          onClick={(e) => e.stopPropagation()}
        >
          {activityLoading && <span className="text-slate-400">Loading…</span>}
          {activityCtx?.dominant && activityCtx.dominant.length > 0 && (
            <div className="text-slate-500">
              <span className="font-semibold text-slate-600">Worked on:</span>{" "}
              {activityCtx.dominant.join(" · ")}
            </div>
          )}
          {activityCtx?.brief && activityCtx.brief.length > 0 && (
            <div className="text-amber-700 bg-amber-50 border border-amber-100 rounded px-2 py-1">
              <span className="font-semibold">Also briefly:</span>{" "}
              {activityCtx.brief.join(" · ")}
            </div>
          )}
          {!activityLoading && activityCtx &&
            activityCtx.dominant?.length === 0 && activityCtx.brief?.length === 0 && (
              <span className="text-slate-400">No additional activity detail.</span>
            )}
        </div>
      )}
    </li>
  );
}

// ─── Category Section ─────────────────────────────────────────────────────────

function CategorySection({
  cat, client, allClients, allCategories,
  onMoveActivity, onMoveAll,
  draggingBlockId, onCatDragOver, onCatDragLeave, onCatDrop, isCatDropTarget,
  selectedIds, onToggleSelect,
}: {
  cat: Category; client: ClientTime;
  allClients: ClientOption[]; allCategories: string[];
  onMoveActivity: (blockId: number, clientId: number | null, category: string) => Promise<void>;
  onMoveAll: (blockIds: number[], clientId: number | null, category: string) => Promise<void>;
  draggingBlockId: number | null;
  onCatDragOver: (e: React.DragEvent) => void;
  onCatDragLeave: () => void;
  onCatDrop: (e: React.DragEvent) => void;
  isCatDropTarget: boolean;
  selectedIds: Set<number>;
  onToggleSelect: (rowKey: string, idx: number, shift: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [showMoveAll, setShowMoveAll] = useState(false);
  // Internal-client work is non-billable regardless of the category name.
  const nonBillable = isNonBillable(cat.name) || isInternalClient(client.client);

  const allBlockIds = cat.sample_activities
    .map((a) => parse(a).blockId)
    .filter((id): id is number => id !== null);

  const selectedInCat = allBlockIds.filter((id) =>
    Array.from(selectedIds).some((k: any) => k.startsWith(`${id}-`))
  ).length;

  return (
    <div
      className={cn(
        "border-t border-slate-100 transition-colors",
        isCatDropTarget && "bg-amber-50"
      )}
      onDragOver={onCatDragOver}
      onDragLeave={onCatDragLeave}
      onDrop={onCatDrop}
    >
      <div className={cn(
        "flex items-center gap-2 group/cat relative",
        nonBillable && "opacity-55"
      )}>
        <div className={cn(
          "w-0.5 self-stretch flex-shrink-0 ml-4 rounded-full",
          nonBillable ? "bg-slate-200" : "bg-slate-300"
        )} />

        <div className="flex-1 flex items-center gap-2 px-2 py-2.5 min-w-0">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="p-0.5 hover:bg-slate-100 rounded-md transition-colors flex-shrink-0"
          >
            {expanded
              ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
              : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
          </button>

          <span
            className={cn(
              "font-bold text-sm flex-1 truncate",
              nonBillable ? "text-slate-400" : "text-slate-800"
            )}
            title={
              cat.task_type_code
                ? `TaskType: ${cat.task_type_name ?? cat.name} (${cat.task_type_code})`
                : undefined
            }
          >
            {cat.name}
          </span>

          {selectedInCat > 0 && (
            <span className="text-[11px] font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full flex-shrink-0">
              {selectedInCat} selected
            </span>
          )}

          {cat.needs_review && (
            <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-50 border border-amber-200 rounded-full text-[11px] font-semibold text-amber-600 flex-shrink-0">
              <AlertTriangle className="w-2.5 h-2.5" />
              Review
            </span>
          )}

          {isCatDropTarget && (
            <span className="text-[11px] font-bold text-amber-700 bg-amber-100 border border-amber-200 px-2 py-0.5 rounded-full flex-shrink-0 animate-pulse">
              Drop here
            </span>
          )}

          <span className={cn(
            "flex-shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold tabular-nums",
            nonBillable
              ? "bg-slate-100 text-slate-400"
              : "bg-emerald-50 text-emerald-700"
          )}>
            {fmt(cat.hours)}
            {cat.block_count > 0 && (
              <span className={cn(
                "text-[10px] font-semibold",
                nonBillable ? "text-slate-300" : "text-emerald-400"
              )}>
                · {cat.block_count}
              </span>
            )}
          </span>

          {allBlockIds.length > 0 && (() => {
            const btnRef = React.createRef<HTMLButtonElement>();
            return (
              <div className="relative flex-shrink-0">
                <button
                  ref={btnRef}
                  onClick={(e) => { e.stopPropagation(); setShowMoveAll((v) => !v); }}
                  className="opacity-0 group-hover/cat:opacity-100 px-2 py-0.5 text-[11px] font-semibold border border-slate-200 rounded-md hover:border-primary hover:text-primary text-slate-400 transition-all"
                >
                  Move all
                </button>
                {showMoveAll && (
                  <MovePopover
                    anchorEl={btnRef.current}
                    clients={allClients}
                    categories={allCategories}
                    currentClientId={client.client_id}
                    currentCategory={cat.name}
                    label={`Move all ${allBlockIds.length} activities`}
                    onApply={(clientId, category) => { setShowMoveAll(false); onMoveAll(allBlockIds, clientId, category); }}
                    onClose={() => setShowMoveAll(false)}
                  />
                )}
              </div>
            );
          })()}
        </div>
      </div>

      {expanded && cat.sample_activities.length > 0 && (
        <ActivityList
          activities={cat.sample_activities}
          client={client}
          categoryName={cat.name}
          allClients={allClients}
          allCategories={allCategories}
          onMove={onMoveActivity}
          onCrossMove={onMoveActivity}
          draggingBlockId={draggingBlockId}
          selectedIds={selectedIds}
          onToggleSelect={onToggleSelect}
        />
      )}
    </div>
  );
}

// ─── Evidence Expansion ─────────────────────────────────────────────────

function EvidenceExpansion({
  blockId,
  isExpanded,
  onToggle,
  colorScheme,
}: {
  blockId: number;
  isExpanded: boolean;
  onToggle: () => void;
  colorScheme: 'blue' | 'violet' | 'cyan';
}) {
  // Color tokens per scheme — matches the parent banner so the panel
  // feels like part of the same card, not a foreign element.
  const colors = {
    blue:   { text: 'text-blue-600 hover:text-blue-800',     border: 'border-blue-200',   bg: 'bg-white/60' },
    violet: { text: 'text-violet-600 hover:text-violet-800', border: 'border-violet-200', bg: 'bg-white/60' },
    cyan:   { text: 'text-cyan-600 hover:text-cyan-800',     border: 'border-cyan-200',   bg: 'bg-white/60' },
  }[colorScheme];

  return (
    <>
      <button
        onClick={onToggle}
        className={cn(
          "flex items-center gap-1 mt-2 ml-5 text-[11px] font-semibold transition-colors",
          colors.text
        )}
      >
        {isExpanded
          ? <ChevronDown className="w-3 h-3" />
          : <ChevronRight className="w-3 h-3" />
        }
        <span>{isExpanded ? 'Hide details' : 'Show details'}</span>
      </button>

      {isExpanded && (
        <div className={cn(
          "mt-2 ml-5 rounded-lg overflow-hidden border",
          colors.border, colors.bg
        )}>
          <BlockEvidencePanel blockId={blockId} />
        </div>
      )}
    </>
  );
}

// ─── Flagged Banner ───────────────────────────────────────────────────────────

function FlaggedBanner({
  flagged,
  onDismiss,
  onResolveDisagreement,
  onConfirmProposal,          // ADD
}: {
  flagged: FlaggedBlock[];
  onDismiss: (id: number) => void;
  onResolveDisagreement?: (id: number, action: 'accept' | 'dismiss') => void;
  onConfirmProposal?: (blockId: number, clientId: number | null, category: string) => void;  // ADD
}) {
  // Hooks FIRST — must run on every render
  const [expandedBlocks, setExpandedBlocks] = useState<Set<number>>(new Set());
  const toggleExpanded = (blockId: number) => {
    setExpandedBlocks((prev) => {
      const next = new Set(prev);
      next.has(blockId) ? next.delete(blockId) : next.add(blockId);
      return next;
    });
  };

  // THEN the early return
  if (!flagged.length) return null;

  // Then everything else
  const mobileFlags = flagged.filter(f => (f.type === 'mobile_review' || (!f.type)) && !f.review_reason?.includes("Mixed content"));
  const aiDisagreements = flagged.filter(f => f.type === 'ai_disagreement');
  const mailDisagreements = flagged.filter(f => f.type === 'mail_disagreement');
  const calendarDisagreements = flagged.filter(f => f.type === 'calendar_disagreement');

  return (

    <>
      {/* Mobile review flags — existing UI unchanged */}
      {mobileFlags.length > 0 && (
        <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 overflow-hidden">
          <div className="px-4 py-2 bg-amber-100/70 border-b border-amber-200 flex items-center gap-2">
            <Smartphone className="w-3.5 h-3.5 text-amber-600" />
            <span className="text-amber-800 font-semibold text-sm">
              {mobileFlags.length} mobile {mobileFlags.length === 1 ? "entry needs" : "entries need"} review
            </span>
          </div>
          <div className="divide-y divide-amber-100">
            {mobileFlags.map((f) => (
              <div key={f.block_id} className="px-4 py-3 flex items-start justify-between gap-4">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-sm font-semibold text-amber-900">{f.client_name} — {fmt(f.minutes / 60)}</p>
                    <p className="text-xs text-amber-600 mt-0.5">{f.review_reason}</p>
                  </div>
                </div>
                <button
                  onClick={() => onDismiss(f.block_id)}
                  className="shrink-0 px-3 py-1.5 text-xs font-semibold bg-amber-200 hover:bg-amber-300 text-amber-900 rounded-lg transition-all"
                >
                  Looks correct
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
 
      {/* AI disagreement flags — blue */}
      {/* Hidden: classifier reliability (collision deferral + keystone + root fix)
          makes this review banner redundant — proposals are now resolved inline
          in the main block list. Flip `false` to `aiDisagreements.length > 0`
          to restore. */}
      {false && aiDisagreements.length > 0 && (
        <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50 overflow-hidden">
          <div className="px-4 py-2 bg-blue-100/70 border-b border-blue-200 flex items-center gap-2">
            <Sparkles className="w-3.5 h-3.5 text-blue-600" />
            <span className="text-blue-800 font-semibold text-sm">
              AI suggests {aiDisagreements.length} {aiDisagreements.length === 1 ? "change" : "changes"} for review
            </span>
          </div>
          <div className="divide-y divide-blue-100">
            {aiDisagreements.map((f) => (
              <div key={f.block_id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-4 mb-2">
                  <div className="flex items-start gap-2 min-w-0">
                    <AlertCircle className="w-3.5 h-3.5 text-blue-500 mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-blue-900">
                        Currently: {f.client_name} — {fmt(f.minutes / 60)}
                      </p>
                      <p className="text-sm font-semibold text-blue-900 mt-1">
                        AI suggests: {f.ai_proposed_client_name}
                        {f.ai_confidence && (
                          <span className="text-blue-600 font-normal ml-1.5">
                            ({Math.round(f.ai_confidence * 100)}% confident)
                          </span>
                        )}
                      </p>
                      {f.ai_reasoning && (
                        <p className="text-xs text-blue-600 mt-1.5 italic line-clamp-2">
                          {f.ai_reasoning}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2 mt-2 ml-5">
                  <button
                    onClick={() => onResolveDisagreement?.(f.block_id, 'accept')}
                    className="px-3 py-1.5 text-xs font-semibold bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-all"
                  >
                    Switch to {f.ai_proposed_client_name}
                  </button>
                  <button
                    onClick={() => onResolveDisagreement?.(f.block_id, 'dismiss')}
                    className="px-3 py-1.5 text-xs font-semibold bg-blue-100 hover:bg-blue-200 text-blue-900 rounded-lg transition-all"
                  >
                    Keep {f.client_name}
                  </button>
                </div>
                <EvidenceExpansion
                  blockId={f.block_id}
                  isExpanded={expandedBlocks.has(f.block_id)}
                  onToggle={() => toggleExpanded(f.block_id)}
                  colorScheme="blue"
                />
              </div>
            ))}
          </div>
        </div>
      )}
 
      {/* Mail disagreement flags — purple, distinct from AI's blue */}
      {mailDisagreements.length > 0 && (
        <div className="mb-4 rounded-xl border border-violet-200 bg-violet-50 overflow-hidden">
          <div className="px-4 py-2 bg-violet-100/70 border-b border-violet-200 flex items-center gap-2">
            <Mail className="w-3.5 h-3.5 text-violet-600" />
            <span className="text-violet-800 font-semibold text-sm">
              Email suggests {mailDisagreements.length} {mailDisagreements.length === 1 ? "change" : "changes"} for review
            </span>
          </div>
          <div className="divide-y divide-violet-100">
            {mailDisagreements.map((f) => (
              <div key={f.block_id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-4 mb-2">
                  <div className="flex items-start gap-2 min-w-0">
                    <AlertCircle className="w-3.5 h-3.5 text-violet-500 mt-0.5 shrink-0" />
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-violet-900">
                        Currently: {f.client_name} — {fmt(f.minutes / 60)}
                      </p>
                      <p className="text-sm font-semibold text-violet-900 mt-1">
                        Email suggests: {f.mail_proposed_client_name}
                        {f.mail_confidence && (
                          <span className="text-violet-600 font-normal ml-1.5">
                            ({Math.round(f.mail_confidence * 100)}% confident)
                          </span>
                        )}
                      </p>
                      {f.mail_reasoning && (
                        <p className="text-xs text-violet-600 mt-1.5 italic line-clamp-2">
                          {f.mail_reasoning}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2 mt-2 ml-5">
                  <button
                    onClick={() => onResolveDisagreement?.(f.block_id, 'accept')}
                    className="px-3 py-1.5 text-xs font-semibold bg-violet-600 hover:bg-violet-700 text-white rounded-lg transition-all"
                  >
                    Switch to {f.mail_proposed_client_name}
                  </button>
                  <button
                    onClick={() => onResolveDisagreement?.(f.block_id, 'dismiss')}
                    className="px-3 py-1.5 text-xs font-semibold bg-violet-100 hover:bg-violet-200 text-violet-900 rounded-lg transition-all"
                  >
                    Keep {f.client_name}
                  </button>
                </div>
                <EvidenceExpansion
                    blockId={f.block_id}
                    isExpanded={expandedBlocks.has(f.block_id)}
                    onToggle={() => toggleExpanded(f.block_id)}
                    colorScheme="violet"
                />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Calendar disagreement flags — teal-cyan, distinct from mail's violet and AI's blue */}
      {calendarDisagreements.length > 0 && (
        <div className="mb-4 rounded-xl border border-cyan-200 bg-cyan-50 overflow-hidden">
          <div className="px-4 py-2 bg-cyan-100/70 border-b border-cyan-200 flex items-center gap-2">
            <CalendarClock className="w-3.5 h-3.5 text-cyan-600" />
            <span className="text-cyan-800 font-semibold text-sm">
              Calendar suggests {calendarDisagreements.length} {calendarDisagreements.length === 1 ? "change" : "changes"} for review
            </span>
          </div>
          <div className="divide-y divide-cyan-100">
            {calendarDisagreements.map((f) => {
              // Source-aware secondary copy. classifier = standard reassign prompt.
              // manual = softer "you picked X, calendar says Y" prompt.
              const isManual = f.calendar_disagreement_source === 'manual';
              const headerCopy = isManual
                ? `You picked: ${f.client_name} — ${fmt(f.minutes / 60)}`
                : `Currently: ${f.client_name} — ${fmt(f.minutes / 60)}`;
              const dismissCopy = isManual
                ? `Keep my pick (${f.client_name})`
                : `Keep ${f.client_name}`;
       
              return (
                <div key={f.block_id} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-4 mb-2">
                    <div className="flex items-start gap-2 min-w-0">
                      <AlertCircle className="w-3.5 h-3.5 text-cyan-500 mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-cyan-900">
                          {headerCopy}
                        </p>
                        <p className="text-sm font-semibold text-cyan-900 mt-1">
                          Calendar suggests: {f.calendar_proposed_client_name}
                          {f.calendar_confidence && (
                            <span className="text-cyan-600 font-normal ml-1.5">
                              ({Math.round(f.calendar_confidence * 100)}% confident)
                            </span>
                          )}
                        </p>
                        {f.calendar_reasoning && (
                          <p className="text-xs text-cyan-600 mt-1.5 italic line-clamp-2">
                            {f.calendar_reasoning}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2 mt-2 ml-5">
                    <button
                      onClick={() => onResolveDisagreement?.(f.block_id, 'accept')}
                      className="px-3 py-1.5 text-xs font-semibold bg-cyan-600 hover:bg-cyan-700 text-white rounded-lg transition-all"
                    >
                      Switch to {f.calendar_proposed_client_name}
                    </button>
                    <button
                      onClick={() => onResolveDisagreement?.(f.block_id, 'dismiss')}
                      className="px-3 py-1.5 text-xs font-semibold bg-cyan-100 hover:bg-cyan-200 text-cyan-900 rounded-lg transition-all"
                    >
                      {dismissCopy}
                    </button>
                  </div>
                  <EvidenceExpansion
                    blockId={f.block_id}
                    isExpanded={expandedBlocks.has(f.block_id)}
                    onToggle={() => toggleExpanded(f.block_id)}
                    colorScheme="cyan"
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}


// ─── Onboarding Hint ──────────────────────────────────────────────────────────

const HINT_KEY = "tt_category_hint_dismissed";

function OnboardingHint() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem(HINT_KEY)) setVisible(true);
    } catch {}
  }, []);

  const dismiss = () => {
    try { localStorage.setItem(HINT_KEY, "1"); } catch {}
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="mb-4 flex items-start gap-3 px-4 py-3 bg-primary/5 border border-primary/20 rounded-xl">
      <div className="p-1.5 bg-primary/10 rounded-lg flex-shrink-0 mt-0.5">
        <MousePointerClick className="w-3.5 h-3.5 text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-700 mb-0.5">How to use this view</p>
        <p className="text-xs text-slate-500 leading-relaxed">
          <span className="font-semibold text-slate-600">Click any activity</span> to instantly move it to a different client or category.{" "}
          <span className="font-semibold text-slate-600">Drag rows</span> to reorder.{" "}
          <span className="font-semibold text-slate-600">Check multiple rows</span> then use the floating bar to bulk-move.
        </p>
      </div>
      <button
        onClick={dismiss}
        className="text-slate-300 hover:text-slate-500 transition-colors flex-shrink-0 mt-0.5"
        title="Got it"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}



// ─── Main ─────────────────────────────────────────────────────────────────────

// Group proposed blocks by title so 20× "Christ Our Hope" → one row.
type ProposedGroup = {
  title: string;
  blockIds: number[];
  totalMinutes: number;
  proposed_client_id: number | null;
  proposed_client_name: string | null;
  proposed_category: string;
};

function groupProposed(items: ProposedInline[]): ProposedGroup[] {
  const map = new Map<string, ProposedGroup>();
  for (const p of items) {
    const key = `${p.proposed_client_id ?? 'none'}::${(p.window_title || '').trim()}`;
    if (!map.has(key)) {
      map.set(key, {
        title: p.window_title || '(untitled)',
        blockIds: [],
        totalMinutes: 0,
        proposed_client_id: p.proposed_client_id,
        proposed_client_name: p.proposed_client_name,
        proposed_category: p.proposed_category,
      });
    }
    const g = map.get(key)!;
    g.blockIds.push(p.block_id);
    g.totalMinutes += p.minutes || 0;
  }
  return [...map.values()].sort((a, b) => b.totalMinutes - a.totalMinutes);
}

// One grouped pending row: red clock, "Nm · Nx", Confirm-all / No Client / Other.
function ProposedGroupRow({
  g, allClients, allCategories, onConfirm,
}: {
  g: ProposedGroup;
  allClients: ClientOption[];
  allCategories: string[];
  onConfirm: (blockIds: number[], clientId: number | null, category: string) => void;
}) {
  const [showPicker, setShowPicker] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const h = Math.floor(g.totalMinutes / 60);
  const m = g.totalMinutes % 60;
  const timeStr = h === 0 ? `${m}m` : m === 0 ? `${h}h` : `${h}h ${m}m`;
  const hasGuess = !!g.proposed_client_id;
  const guessCategory = g.proposed_category || "General Client Work";
  const n = g.blockIds.length;

  const [showActivity, setShowActivity] = useState(false);
  const [activityCtx, setActivityCtx] = useState<{ dominant: string[]; brief: string[] } | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);

  const toggleActivity = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    const next = !showActivity;
    setShowActivity(next);
    if (next && activityCtx === null && g.blockIds.length > 0) {
      setActivityLoading(true);
      try {
        const ctx = await safeFetchJson<{ dominant: string[]; brief: string[] }>(
          `${API_BASE}/blocks/${g.blockIds[0]}/tab-context/`
        );
        setActivityCtx(ctx);
      } catch {
        setActivityCtx({ dominant: [], brief: [] });
      } finally {
        setActivityLoading(false);
      }
    }
  }, [showActivity, activityCtx, g.blockIds]);

  return (
    <div ref={ref} className="flex items-center gap-2 px-3 py-1.5 ml-6 rounded-lg bg-amber-50/50 relative">
      <Clock className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
      <span className="text-sm flex-1 truncate text-slate-600" title={g.title}>
        {g.title}
      </span>
      {n > 1 && (
        <span className="text-[10px] font-semibold text-slate-400 flex-shrink-0">
          {n}×
        </span>
      )}
      <span className="text-[11px] font-bold text-red-500 bg-red-50 px-1.5 py-0.5 rounded tabular-nums flex-shrink-0">
        {timeStr}
      </span>
      {hasGuess ? (
        <>
          <button
            onClick={() => onConfirm(g.blockIds, g.proposed_client_id, guessCategory)}
            className="px-2 py-0.5 text-[11px] font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-md transition-all flex-shrink-0"
            title={`Assign ${n} to ${g.proposed_client_name}`}
          >
            Confirm{n > 1 ? ` all ${n}` : ''}
          </button>
          <button
            onClick={() => onConfirm(g.blockIds, null, "Personal/Non-Billable")}
            className="px-2 py-0.5 text-[11px] font-semibold border border-slate-300 text-slate-500 hover:bg-slate-100 rounded-md transition-all flex-shrink-0"
          >No Client</button>
          <div className="relative flex-shrink-0">
            <button
              onClick={() => setShowPicker((v) => !v)}
              className="px-2 py-0.5 text-[11px] font-semibold border border-amber-300 text-amber-700 hover:bg-amber-100 rounded-md transition-all"
            >Other…</button>
            {showPicker && (
              <MovePopover
                anchorEl={ref.current}
                clients={allClients}
                categories={allCategories}
                currentClientId={g.proposed_client_id}
                currentCategory={guessCategory}
                label="Pick a different client"
                onApply={(clientId, category) => { setShowPicker(false); onConfirm(g.blockIds, clientId, category); }}
                onClose={() => setShowPicker(false)}
              />
            )}
          </div>
        </>
      ) : (
        <>
          <div className="relative flex-shrink-0">
            <button
              onClick={() => setShowPicker((v) => !v)}
              className="px-2 py-0.5 text-[11px] font-semibold border border-amber-300 text-amber-700 hover:bg-amber-100 rounded-md transition-all"
            >Assign client</button>
            {showPicker && (
              <MovePopover
                anchorEl={ref.current}
                clients={allClients}
                categories={allCategories}
                currentClientId={null}
                currentCategory={g.proposed_category || (allCategories[0] ?? "")}
                label={`Assign ${n > 1 ? `these ${n} entries` : 'this entry'}`}
                onApply={(clientId, category) => { setShowPicker(false); onConfirm(g.blockIds, clientId, category); }}
                onClose={() => setShowPicker(false)}
              />
            )}
          </div>
          <button
            onClick={() => onConfirm(g.blockIds, null, "Personal/Non-Billable")}
            className="px-2 py-0.5 text-[11px] font-semibold border border-slate-300 text-slate-500 hover:bg-slate-100 rounded-md transition-all flex-shrink-0"
          >No Client</button>
        </>
      )}

      {g.blockIds.length > 0 && (
        <button
          onClick={toggleActivity}
          title="See what this block touched"
          className="text-[11px] font-medium text-slate-400 hover:text-primary transition-colors flex-shrink-0"
        >
          {showActivity ? "hide" : "activity"}
        </button>
      )}

      {showActivity && (
        <div
          className="basis-full mt-1.5 ml-6 mr-2 space-y-1 text-[11px]"
          onClick={(e) => e.stopPropagation()}
        >
          {activityLoading && <span className="text-slate-400">Loading…</span>}
          {n > 1 && activityCtx &&
            (activityCtx.dominant.length > 0 || activityCtx.brief.length > 0) && (
              <div className="text-[10px] text-slate-400 italic">showing first of {n} blocks</div>
            )}
          {activityCtx?.dominant && activityCtx.dominant.length > 0 && (
            <div className="text-slate-500">
              <span className="font-semibold text-slate-600">Worked on:</span>{" "}
              {activityCtx.dominant.join(" · ")}
            </div>
          )}
          {activityCtx?.brief && activityCtx.brief.length > 0 && (
            <div className="text-amber-700 bg-amber-50 border border-amber-100 rounded px-2 py-1">
              <span className="font-semibold">Also briefly:</span>{" "}
              {activityCtx.brief.join(" · ")}
            </div>
          )}
          {!activityLoading && activityCtx &&
            activityCtx.dominant?.length === 0 && activityCtx.brief?.length === 0 && (
              <span className="text-slate-400">No additional activity detail.</span>
            )}
        </div>
      )}
    </div>
  );
}

export default function CategorySummary({
  timeSummary,
  availableClients,
  availableCategories,
  flaggedBlocks,
  busy,
  onDismissReview,
  onResolveDisagreement,
  onRefresh,
  showToast,
  proposedInline = [],
}: {
  timeSummary: ClientTime[];
  availableClients: ClientOption[];
  availableCategories: string[];
  flaggedBlocks: FlaggedBlock[];
  busy: boolean;
  onDismissReview: (id: number) => void;
  onResolveDisagreement?: (id: number, action: 'accept' | 'dismiss') => void;
  onRefresh: () => void;
  showToast: (msg: string, type: "success" | "error") => void;
  proposedInline?: ProposedInline[];
}) {
  const [collapsedClients, setCollapsedClients] = useState<Set<string>>(new Set());
  const [catDropTarget, setCatDropTarget] = useState<string | null>(null);
  const [clientDropTarget, setClientDropTarget] = useState<string | null>(null);
  const [draggingBlockId, setDraggingBlockId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  // EDIT 1 of 4: per-client reveal state for parked non-billable / no-client time.
  const [revealedNonBill, setRevealedNonBill] = useState<Set<string>>(new Set());

  const pendingToggleRef = useRef<Set<string>>(new Set());
  const handleToggleSelect = useCallback((rowKey: string, _idx: number, _shift: boolean) => {
    if (pendingToggleRef.current.has(rowKey)) return;
    pendingToggleRef.current.add(rowKey);
    setTimeout(() => pendingToggleRef.current.delete(rowKey), 500);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(rowKey) ? next.delete(rowKey) : next.add(rowKey);
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  useEffect(() => {
    const onEnd = () => {
      setDraggingBlockId(null);
      setCatDropTarget(null);
      setClientDropTarget(null);
    };
    document.addEventListener("dragend", onEnd);
    return () => document.removeEventListener("dragend", onEnd);
  }, []);

  // Resolve the current client/category shared by the current selection.
  // Selection keys are `${blockId}-${idx}`; map each block id back to the
  // client/category it currently lives in. If the whole selection shares one
  // client (and/or one category), pre-populate the move picker with it;
  // otherwise leave that field neutral (mixed selection).
  const selectionCurrent = React.useMemo(() => {
    const selectedBlockIds = new Set(
      Array.from(selectedIds)
        .map((k) => parseInt(k.split("-")[0]))
        .filter((n) => !isNaN(n) && n > 0)
    );
    if (selectedBlockIds.size === 0) return { clientId: null, category: "" };

    const clientIds = new Set<number | null>();
    const categories = new Set<string>();

    for (const client of timeSummary) {
      for (const cat of client.categories) {
        for (const a of cat.sample_activities) {
          const p = parse(a);
          const ids = p.blockIds.length > 0 ? p.blockIds : (p.blockId ? [p.blockId] : []);
          if (ids.some((id) => selectedBlockIds.has(id))) {
            clientIds.add(client.client_id);
            categories.add(cat.name);
          }
        }
      }
    }

    return {
      clientId: clientIds.size === 1 ? [...clientIds][0] : null,
      category: categories.size === 1 ? [...categories][0] : "",
    };
  }, [selectedIds, timeSummary]);

  const toggleClient = (key: string) =>
    setCollapsedClients((prev) => {
      const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s;
    });

  const moveActivity = useCallback(async (blockId: number, clientId: number | null, category: string, source?: string): Promise<boolean> => {
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/recategorize/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        // `source` tags a deliberate single confirm so the backend teaches the
        // pattern learner. Drags / bulk-moves omit it and stay non-teaching.
        body: JSON.stringify({ category, client_id: clientId, ...(source ? { source } : {}) }),
      });
      return true;
    } catch (e: any) {
      if (e?.status === 404 || e?.message?.includes("404") || e?.message?.includes("Not found")) return false;
      throw e;
    }
  }, []);

  const moveMany = useCallback(async (blockIds: number[] | string[], clientId: number | null, category: string) => {
    const resolvedIds = (blockIds as any[])
      .map((id: any) => {
        const n = typeof id === "string" ? parseInt(id.split("-")[0]) : id as number;
        return n;
      })
      .filter((n: number) => !isNaN(n) && n > 0);
    const uniqueIds = [...new Set(resolvedIds)];
    if (!uniqueIds.length) {
      showToast("No moveable entries selected", "error");
      return;
    }
    try {
      const results = await Promise.all(uniqueIds.map((id) => moveActivity(id, clientId, category)));
      const moved = results.filter(Boolean).length;
      showToast(
        moved > 0 ? `Moved ${moved} activit${moved !== 1 ? "ies" : "y"}` : "Nothing to move",
        moved > 0 ? "success" : "error"
      );
      clearSelection();
      onRefresh();
    } catch (e: any) {
      showToast(e?.message || "Move failed", "error");
    }
  }, [moveActivity, clearSelection, onRefresh, showToast]);

  const moveSingle = useCallback(async (blockId: number, clientId: number | null, category: string) => {
    try {
      await moveActivity(blockId, clientId, category);
      showToast("Moved", "success");
      onRefresh();
    } catch (e: any) {
      showToast(e?.message || "Move failed", "error");
    }
  }, [moveActivity, onRefresh, showToast]);

  const confirmProposalInline = useCallback(async (blockIds: number[], clientId: number | null, category: string) => {
    try {
      for (const id of blockIds) {
        // Per-row "Confirm" chip → tag as single_confirm so the backend learns
        // this name → client mapping for future auto-classification.
        await moveActivity(id, clientId, category || "General Client Work", "single_confirm");
      }
      // Sum the minutes we just confirmed (from the proposed groups) and name
      // the destination, so the user can SEE what landed where.
      const confirmedMins = proposedInline
        .filter((p) => blockIds.includes(p.block_id))
        .reduce((s, p) => s + (p.minutes || 0), 0);
      const destName = clientId == null
        ? "No Client"
        : (availableClients.find((c) => c.id === clientId)?.name || "client");
      const h = Math.floor(confirmedMins / 60);
      const m = confirmedMins % 60;
      const timeStr = h === 0 ? `${m}m` : m === 0 ? `${h}h` : `${h}h ${m}m`;
      showToast(`Confirmed ${timeStr} → ${destName}`, "success");
      onRefresh();
    } catch (e: any) {
      showToast(e?.message || "Confirm failed", "error");
    }
  }, [moveActivity, onRefresh, showToast, proposedInline, availableClients]);

  const makeCatDragOver = (catKey: string) => (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setCatDropTarget(catKey);
  };

  const makeCatDrop = (clientId: number | null, catName: string) => async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation();
    setCatDropTarget(null); setClientDropTarget(null);
    const raw = e.dataTransfer.getData("application/x-block");
    if (!raw) return;
    const { blockId, fromClient, fromCategory } = JSON.parse(raw);
    const targetClientName = timeSummary.find((c) => c.client_id === clientId)?.client ?? "";
    if (fromClient === targetClientName && fromCategory === catName) return;
    setDraggingBlockId(blockId);
    await moveSingle(blockId, clientId, catName);
    setDraggingBlockId(null);
  };

  const makeClientDrop = (targetClient: ClientTime) => async (e: React.DragEvent) => {
    e.preventDefault();
    setCatDropTarget(null); setClientDropTarget(null);
    const raw = e.dataTransfer.getData("application/x-block");
    if (!raw) return;
    const { blockId, fromClient, fromCategory } = JSON.parse(raw);
    if (fromClient === targetClient.client) return;
    setDraggingBlockId(blockId);
    await moveSingle(blockId, targetClient.client_id, fromCategory);
    setDraggingBlockId(null);
  };

  const getBillable = (c: ClientTime) =>
    c.categories.filter((cat) => !isNonBillable(cat.name)).reduce((s, cat) => s + cat.hours, 0);

  const getNonBillable = (c: ClientTime) =>
    c.categories.filter((cat) => isNonBillable(cat.name)).reduce((s, cat) => s + cat.hours, 0);

  // Group proposed blocks (collapses duplicate titles), then bucket by guessed client.
  const proposedGroups = groupProposed(proposedInline);
  const groupsByClient = new Map<number | null, ProposedGroup[]>();
  for (const g of proposedGroups) {
    const k = g.proposed_client_id ?? null;
    if (!groupsByClient.has(k)) groupsByClient.set(k, []);
    groupsByClient.get(k)!.push(g);
  }
  const summaryClientIds = new Set(timeSummary.map((c) => c.client_id));
  // guessed-clients that have NO card today → render their own pending sub-card
  const orphanGuessIds = [...groupsByClient.keys()].filter(
    (k) => k !== null && !summaryClientIds.has(k)
  );
  const noClientGroups = groupsByClient.get(null) || [];

  // Orphan guesses (a guessed client with no committed card today) get their
  // OWN synthetic zero-time card so their pending proposals nest under the
  // right client header (like a client that has committed time), instead of
  // falling into the No-Client bucket. Only proposals with NO guessed client
  // (noClientGroups) are truly homeless and render under No Client.
  const orphanGuessCards: ClientTime[] = orphanGuessIds.map((cid) => {
    const grp = groupsByClient.get(cid) || [];
    const name = grp[0]?.proposed_client_name || "Client";
    return { client_id: cid, client: name, total_hours: 0, categories: [] };
  });

  // Pending groups with no client card at all → render under No Client.
  const homelessPendingGroups: ProposedGroup[] = [...noClientGroups];

  // Does timeSummary already contain an Unassigned/No-Client card?
  const hasUnassignedCard = timeSummary.some(
    (c) => c.client_id == null || c.client.toLowerCase() === "unassigned"
  );

  // Build the render list: real clients, plus a synthetic No-Client card
  // ONLY if there are homeless pending groups and no Unassigned card exists.
  const renderClients: ClientTime[] = [
    ...timeSummary,
    ...orphanGuessCards,
    ...((homelessPendingGroups.length > 0 && !hasUnassignedCard)
      ? [{ client_id: null, client: "Unassigned", total_hours: 0, categories: [] } as ClientTime]
      : []),
  ];

  return (
    <div>
      <FlaggedBanner 
        flagged={flaggedBlocks} 
        onDismiss={onDismissReview}
        onResolveDisagreement={onResolveDisagreement}
        onConfirmProposal={confirmProposalInline}
      />
      <OnboardingHint />

      {timeSummary.length > 1 && (
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs text-slate-400">
            Click any activity to move it · drag to reorder · select multiple with checkboxes
          </p>
          <button
            onClick={() => {
              if (collapsedClients.size === 0)
                setCollapsedClients(new Set(timeSummary.map((c) => `${c.client_id}-${c.client}`)));
              else setCollapsedClients(new Set());
            }}
            className="text-xs text-slate-500 hover:text-slate-800 font-semibold px-2.5 py-1 rounded-lg hover:bg-slate-100 transition-all"
          >
            {collapsedClients.size === 0 ? "Collapse all" : "Expand all"}
          </button>
        </div>
      )}

      {busy && timeSummary.length === 0 && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => <div key={i} className={cn(SKELETON.card, "h-32")} />)}
        </div>
      )}

      {!busy && timeSummary.length === 0 && (
        <div className="text-center py-16 bg-white rounded-2xl border border-slate-200">
          <FileQuestion className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <h3 className="text-base font-bold text-slate-700 mb-1">No time tracked yet</h3>
          <p className="text-sm text-slate-400">Activity appears automatically as you work, or add time manually.</p>
        </div>
      )}

      <div className="space-y-3">
        {renderClients.map((client, clientIndex) => {
          const clientKey = `${client.client_id}-${client.client}`;
          const isCollapsed = collapsedClients.has(clientKey);
          const unassigned = client.client.toLowerCase() === "unassigned";
          // Display-only relabel: "Unassigned" reads as a to-do, but for
          // intentionally client-less work it's a resolved state. "No Client"
          // states the fact without implying an unfinished task. The control
          // value (`unassigned`) still keys off the real backend string.
          const displayName = unassigned ? "No Client" : client.client;
          const isClientDrop = clientDropTarget === clientKey;

          // Internal firm work is non-billable — dim it like No-Client, but keep
          // its real name and hours visible so managers still see the time spent.
          const isInternal = isInternalClient(client.client);
          const dimmed = unassigned || isInternal;

          const accent = dimmed
            ? { border: "border-l-slate-300", header: "bg-slate-50", hours: "text-slate-400" }
            : CLIENT_ACCENTS[clientIndex % CLIENT_ACCENTS.length];

          const visibleCategories = client.categories.filter(
            (cat) => cat.hours > 0 || cat.sample_activities.length > 0
          );

          // EDIT 2 of 4: split parked non-billable/no-client categories out of
          // the main view. Only applies inside the Unassigned bucket — billable
          // client-less work stays visible (it genuinely needs attention).
          const parkedCats = unassigned
            ? visibleCategories.filter((cat) => isNonBillable(cat.name))
            : [];
          const mainCats = unassigned
            ? visibleCategories.filter((cat) => !isNonBillable(cat.name))
            : visibleCategories;
          const isRevealed = revealedNonBill.has(clientKey);
          const parkedMinutes = parkedCats.reduce((s, cat) => s + cat.hours, 0);
          const parkedCount = parkedCats.reduce((s, cat) => s + cat.block_count, 0);

          const hiddenZeroCount = client.categories.length - visibleCategories.length;
          const totalActivityCount = visibleCategories.reduce((sum, cat) => sum + cat.block_count, 0);

          return (
            <div
              key={clientKey}
              className={cn(
                "rounded-xl border border-slate-200 border-l-[5px] bg-white shadow-sm overflow-hidden transition-all",
                accent.border,
                // No-Client is an unresolved to-do → dim the whole card to nudge
                // action. Internal is a resolved, intentional non-billable state →
                // keep the card (and its name) crisp; the slate accent + greyed
                // rows/hours already signal non-billable.
                unassigned && "opacity-70",
                isClientDrop && "ring-2 ring-primary/30 ring-offset-1"
              )}
              onDragOver={(e) => { e.preventDefault(); setClientDropTarget(clientKey); }}
              onDragLeave={() => setClientDropTarget(null)}
              onDrop={makeClientDrop(client)}
            >
              <button
                onClick={() => toggleClient(clientKey)}
                className={cn(
                  "w-full px-4 py-3 flex items-center justify-between text-left transition-colors",
                  accent.header,
                  "hover:brightness-95"
                )}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  {isCollapsed
                    ? <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
                    : <ChevronDown className="w-4 h-4 text-slate-400 flex-shrink-0" />}
                  <span className={cn(
                    "font-bold text-base truncate",
                    // Keep the Internal client name crisp/legible (identifier, not
                    // a billable signal); only No-Client gets the muted name.
                    unassigned ? "text-slate-500" : "text-slate-900"
                  )}>
                    {displayName}
                  </span>
                  {isCollapsed ? (
                    <span className="text-xs text-slate-400 font-medium flex-shrink-0">
                      {visibleCategories.length} {visibleCategories.length === 1 ? "category" : "categories"}
                      {totalActivityCount > 0 && (
                        <span className="ml-1 text-slate-300">
                          · {totalActivityCount} {totalActivityCount === 1 ? "entry" : "entries"}
                        </span>
                      )}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400 font-medium flex-shrink-0">
                      {visibleCategories.length} {visibleCategories.length === 1 ? "category" : "categories"}
                    </span>
                  )}
                  {isClientDrop && (
                    <span className="text-xs font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full flex-shrink-0 animate-pulse">
                      Drop to reassign
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3 flex-shrink-0 ml-4">
                  {!dimmed && (() => {
                    const billable = getBillable(client);
                    const nonBillable = getNonBillable(client);
                    return (
                      <>
                        <div className="flex flex-col items-end">
                          <span className={cn("text-lg font-extrabold tabular-nums leading-none", accent.hours)}>
                            {fmt(billable)}
                          </span>
                          <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">
                            billable
                          </span>
                        </div>
                        {nonBillable > 0 && (
                          <>
                            <div className="w-px h-6 bg-black/10 flex-shrink-0" />
                            <div className="flex flex-col items-end">
                              <span className="text-lg font-extrabold tabular-nums leading-none text-slate-400">
                                {fmt(nonBillable)}
                              </span>
                              <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">
                                non-bill
                              </span>
                            </div>
                          </>
                        )}
                      </>
                    );
                  })()}
                  {dimmed && (
                    <div className="flex flex-col items-end">
                      <span className="text-lg font-extrabold tabular-nums leading-none text-slate-400">
                        {fmt(client.total_hours)}
                      </span>
                      <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mt-0.5">
                        {isInternal ? "non-bill" : "total"}
                      </span>
                    </div>
                  )}
                </div>
              </button>

              {!isCollapsed && (
                <div>
                  {/* EDIT 3 of 4: render mainCats (parked non-billable split out below) */}
                  {mainCats.map((cat) => {
                    const catKey = `${client.client_id}-${cat.name}`;
                    return (
                      <CategorySection
                        key={cat.name}
                        cat={cat}
                        client={client}
                        allClients={availableClients}
                        allCategories={availableCategories}
                        onMoveActivity={moveSingle}
                        onMoveAll={moveMany}
                        draggingBlockId={draggingBlockId}
                        onCatDragOver={makeCatDragOver(catKey)}
                        onCatDragLeave={() => setCatDropTarget(null)}
                        onCatDrop={makeCatDrop(client.client_id, cat.name)}
                        isCatDropTarget={catDropTarget === catKey}
                        selectedIds={selectedIds}
                        onToggleSelect={handleToggleSelect}
                      />
                    );
                  })}

                  {(() => {
                    const isNoClient = client.client_id == null || client.client.toLowerCase() === "unassigned";
                    const pendingForCard = isNoClient
                      ? homelessPendingGroups
                      : (groupsByClient.get(client.client_id) || []);
                    if (pendingForCard.length === 0) return null;
                    return (
                      <div className="border-t border-amber-100 bg-amber-50/30 py-2">
                        <p className="text-[10px] font-bold text-amber-600 uppercase tracking-wide px-5 mb-1">
                          Pending — confirm to count as billable
                        </p>
                        {pendingForCard.map((g) => (
                          <ProposedGroupRow
                            key={`${g.proposed_client_id}-${g.title}`}
                            g={g}
                            allClients={availableClients}
                            allCategories={availableCategories}
                            onConfirm={confirmProposalInline}
                          />
                        ))}
                      </div>
                    );
                  })()}

                  {/* EDIT 4 of 4: collapsed parked non-billable / no-client time
                      with a reveal toggle, mirroring the empty-categories footer. */}
                  {parkedCats.length > 0 && (
                    <div className="border-t border-slate-100">
                      <button
                        onClick={() => setRevealedNonBill((prev) => {
                          const next = new Set(prev);
                          next.has(clientKey) ? next.delete(clientKey) : next.add(clientKey);
                          return next;
                        })}
                        className="w-full px-5 py-2 flex items-center gap-1.5 text-left hover:bg-slate-50 transition-colors"
                      >
                        {isRevealed
                          ? <ChevronDown className="w-3 h-3 text-slate-300" />
                          : <ChevronRight className="w-3 h-3 text-slate-300" />}
                        <span className="text-[11px] text-slate-400 font-medium">
                          {parkedCount} non-billable / no-client {parkedCount === 1 ? "entry" : "entries"}
                          {" "}({fmt(parkedMinutes)}) {isRevealed ? "— hide" : "— show"}
                        </span>
                      </button>

                      {isRevealed && parkedCats.map((cat) => {
                        const catKey = `${client.client_id}-${cat.name}`;
                        return (
                          <CategorySection
                            key={cat.name}
                            cat={cat}
                            client={client}
                            allClients={availableClients}
                            allCategories={availableCategories}
                            onMoveActivity={moveSingle}
                            onMoveAll={moveMany}
                            draggingBlockId={draggingBlockId}
                            onCatDragOver={makeCatDragOver(catKey)}
                            onCatDragLeave={() => setCatDropTarget(null)}
                            onCatDrop={makeCatDrop(client.client_id, cat.name)}
                            isCatDropTarget={catDropTarget === catKey}
                            selectedIds={selectedIds}
                            onToggleSelect={handleToggleSelect}
                          />
                        );
                      })}
                    </div>
                  )}

                  {hiddenZeroCount > 0 && (
                    <div className="px-5 py-2 border-t border-slate-100">
                      <span className="text-[11px] text-slate-300 font-medium">
                        {hiddenZeroCount} empty {hiddenZeroCount === 1 ? "category" : "categories"} hidden
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {timeSummary.length > 0 && !busy && (() => {
        const totalBillable = timeSummary.reduce((s, c) => s + getBillable(c), 0);
        const totalNonBillable = timeSummary.reduce((s, c) => s + getNonBillable(c), 0);
        const totalAll = totalBillable + totalNonBillable;
        const clientCount = timeSummary.filter((c) => c.client.toLowerCase() !== "unassigned").length;
        const activityCount = timeSummary.reduce(
          (s, c) => s + c.categories.reduce((cs, cat) => cs + cat.block_count, 0), 0
        );
        return (
          <div className="mt-4 px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">
              {activityCount} {activityCount === 1 ? "entry" : "entries"} across {clientCount} {clientCount === 1 ? "client" : "clients"}
            </span>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-extrabold text-primary tabular-nums">{fmt(totalBillable)}</span>
                <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">billable</span>
              </div>
              {totalNonBillable > 0 && (
                <>
                  <div className="w-px h-4 bg-slate-200" />
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-extrabold text-slate-400 tabular-nums">{fmt(totalNonBillable)}</span>
                    <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">non-bill</span>
                  </div>
                </>
              )}
              <div className="w-px h-4 bg-slate-200" />
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-extrabold text-slate-700 tabular-nums">{fmt(totalAll)}</span>
                <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">total</span>
              </div>
            </div>
          </div>
        );
      })()}

      <SelectionBar
        count={selectedIds.size}
        clients={availableClients}
        categories={availableCategories}
        currentClientId={selectionCurrent.clientId}
        currentCategory={selectionCurrent.category}
        onMove={(clientId, category) => moveMany(Array.from(selectedIds) as any, clientId, category)}
        onClear={clearSelection}
      />
    </div>
  );
}