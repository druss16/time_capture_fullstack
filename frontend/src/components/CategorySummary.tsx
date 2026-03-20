/**
 * CategorySummary.tsx
 *
 * Features:
 *  - Click checkbox (or shift+click) to multi-select activity rows
 *  - Floating action bar appears when items are selected: Move | Delete | Clear
 *  - "Move selected" opens a popover → calls recategorize_block for all IDs
 *  - Single "Move" button per row for quick one-off moves
 *  - "Move all" on category header for bulk category reassign
 *  - Drag rows with yellow insertion line showing drop position
 *  - Teal ghost pill follows cursor while dragging
 */

import React, { useState, useRef, useCallback, useEffect } from "react";
import {
  ChevronDown,
  ChevronRight,
  GripVertical,
  AlertTriangle,
  Smartphone,
  FileQuestion,
  ArrowRight,
  CheckSquare,
  Square,
  X,
  ArrowRightLeft,
} from "lucide-react";
import { cn, getClientColor, SKELETON } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api")
  ? RAW_BASE
  : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// ─── Types ─────────────────────────────────────────────────────────────────────

export type Category = {
  name: string;
  hours: number;
  block_count: number;
  sample_activities: string[];
  needs_review?: boolean;
};
export type ClientTime = {
  client_id: number | null;
  client: string;
  total_hours: number;
  categories: Category[];
};
export type ClientOption = { id: number; name: string };
export type FlaggedBlock = {
  block_id: number;
  client_name: string;
  review_reason: string;
  minutes: number;
  start: string;
};
type ParsedActivity = { blockId: number | null; title: string };

// ─── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (hours: number): string => {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
};

const parse = (activity: string): ParsedActivity => {
  const match = activity.match(/\[id:(\d+)\]\s*/);
  if (match)
    return { blockId: parseInt(match[1]), title: activity.replace(/\[id:\d+\]\s*/, "").trim() };
  return { blockId: null, title: activity };
};

const isNonBillable = (name: string) => {
  const n = name.toLowerCase();
  return n.includes("idle") || n.includes("uncategorized") || n.includes("personal") || n.includes("pto") || n.includes("time off");
};

// ─── Move Popover ───────────────────────────────────────────────────────────────

function MovePopover({
  clients, categories, currentClientId, currentCategory, label, onApply, onClose,
}: {
  clients: ClientOption[]; categories: string[];
  currentClientId: number | null; currentCategory: string;
  label: string;
  onApply: (clientId: number | null, category: string) => void;
  onClose: () => void;
}) {
  const [selClient, setSelClient] = useState<number | null>(currentClientId);
  const [selCat, setSelCat] = useState(currentCategory);
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
      style={{ position: "absolute", right: 0, top: "calc(100% + 4px)", zIndex: 9999, width: 260 }}
      className="bg-white border-2 border-slate-200 rounded-xl shadow-2xl p-4"
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-bold text-slate-400 uppercase tracking-wide mb-3">{label}</p>
      <div className="space-y-2 mb-4">
        <select
          value={selClient ?? ""}
          onChange={(e) => setSelClient(e.target.value ? parseInt(e.target.value) : null)}
          className="w-full border-2 border-slate-200 rounded-lg px-3 py-2 text-sm font-medium bg-white focus:border-primary focus:outline-none"
        >
          <option value="">Unassigned</option>
          {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select
          value={selCat}
          onChange={(e) => setSelCat(e.target.value)}
          className="w-full border-2 border-slate-200 rounded-lg px-3 py-2 text-sm font-medium bg-white focus:border-primary focus:outline-none"
        >
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="flex gap-2">
        <button onClick={onClose} className="flex-1 py-2 border-2 border-slate-200 rounded-lg text-sm font-bold text-slate-600 hover:bg-slate-100 transition-all">
          Cancel
        </button>
        <button
          onClick={() => onApply(selClient, selCat)}
          className="flex-1 py-2 bg-primary text-white rounded-lg text-sm font-bold hover:opacity-90 shadow-lg shadow-primary/20 transition-all"
        >
          Apply
        </button>
      </div>
    </div>
  );
}

// ─── Inline Move Picker (used by SelectionBar, renders above it) ───────────────

function InlineMovePicker({
  clients, categories, count, onApply, onClose,
}: {
  clients: ClientOption[]; categories: string[];
  count: number;
  onApply: (clientId: number | null, category: string) => void;
  onClose: () => void;
}) {
  const [selClient, setSelClient] = useState<number | null>(null);
  const [selCat, setSelCat] = useState(categories[0] ?? "");
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
      className="absolute bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2 w-64 bg-white border-2 border-slate-200 rounded-xl shadow-2xl p-4"
      style={{ zIndex: 9999 }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-bold text-slate-400 uppercase tracking-wide mb-3">
        Move {count} selected activit{count !== 1 ? "ies" : "y"}
      </p>
      <div className="space-y-2 mb-4">
        <select
          value={selClient ?? ""}
          onChange={(e) => setSelClient(e.target.value ? parseInt(e.target.value) : null)}
          className="w-full border-2 border-slate-200 rounded-lg px-3 py-2 text-sm font-medium bg-white text-slate-900 focus:border-primary focus:outline-none"
        >
          <option value="">Unassigned</option>
          {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select
          value={selCat}
          onChange={(e) => setSelCat(e.target.value)}
          className="w-full border-2 border-slate-200 rounded-lg px-3 py-2 text-sm font-medium bg-white text-slate-900 focus:border-primary focus:outline-none"
        >
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div className="flex gap-2">
        <button onClick={onClose} className="flex-1 py-2 border-2 border-slate-200 rounded-lg text-sm font-bold text-slate-600 hover:bg-slate-100">
          Cancel
        </button>
        <button
          onClick={() => onApply(selClient, selCat)}
          className="flex-1 py-2 bg-primary text-white rounded-lg text-sm font-bold hover:opacity-90"
        >
          Apply
        </button>
      </div>
    </div>
  );
}

// ─── Floating Selection Bar ─────────────────────────────────────────────────────

function SelectionBar({
  count, clients, categories, onMove, onClear,
}: {
  count: number;
  clients: ClientOption[];
  categories: string[];
  onMove: (clientId: number | null, category: string) => void;
  onClear: () => void;
}) {
  const [showPopover, setShowPopover] = useState(false);

  if (count === 0) return null;

  return (
    <div
      className="fixed bottom-6 left-1/2 z-50 flex items-center gap-3 px-5 py-3 bg-slate-900 text-white rounded-2xl shadow-2xl"
      style={{ transform: "translateX(-50%)" }}
    >
      <span className="text-sm font-bold text-white/90">
        {count} item{count !== 1 ? "s" : ""} selected
      </span>

      <div className="w-px h-5 bg-white/20" />

      {/* Move selected */}
      <div className="relative">
        <button
          onClick={() => setShowPopover((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary rounded-xl text-sm font-bold hover:opacity-90 transition-all"
        >
          <ArrowRightLeft className="w-3.5 h-3.5" />
          Move selected
        </button>
        {showPopover && (
          <InlineMovePicker
            clients={clients}
            categories={categories}
            count={count}
            onApply={(clientId, category) => { setShowPopover(false); onMove(clientId, category); }}
            onClose={() => setShowPopover(false)}
          />
        )}
      </div>

      {/* Deselect all */}
      <button
        onClick={onClear}
        className="flex items-center gap-1.5 px-3 py-1.5 bg-white/10 hover:bg-white/20 rounded-xl text-sm font-bold text-white/80 transition-all"
      >
        <X className="w-3.5 h-3.5" />
        Deselect all
      </button>
    </div>
  );
}

// ─── Activity List ──────────────────────────────────────────────────────────────

function ActivityList({
  activities, client, categoryName, allClients, allCategories,
  onMove, onCrossMove, draggingBlockId,
  selectedIds, onToggleSelect,
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
  const PREVIEW = 3;
  const [showAll, setShowAll] = useState(false);
  const [insertAfterIdx, setInsertAfterIdx] = useState<number | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const hasMore = activities.length > PREVIEW;
  const visible = showAll ? activities : activities.slice(0, PREVIEW);

  const handleRowDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setInsertAfterIdx(e.clientY < rect.top + rect.height / 2 ? idx - 1 : idx);
  };

  const handleListDragLeave = (e: React.DragEvent) => {
    if (!listRef.current?.contains(e.relatedTarget as Node)) setInsertAfterIdx(null);
  };

  const handleRowDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setInsertAfterIdx(null);
    let raw = "";
    try { raw = e.dataTransfer.getData("application/x-block"); } catch {}
    if (!raw) return;
    let parsed2: any;
    try { parsed2 = JSON.parse(raw); } catch { return; }
    const { blockId, fromClient, fromCategory } = parsed2;
    if (!blockId) return;
    if (fromClient !== client.client || fromCategory !== categoryName) {
      await onCrossMove(blockId, client.client_id, categoryName);
    }
  };

  const InsertionLine = () => (
    <li style={{ listStyle: "none", padding: 0, margin: "1px 0" }}>
      <div style={{ height: 2, background: "#EAB308", borderRadius: 2, margin: "0 8px" }} />
    </li>
  );

  return (
    <ul
      ref={listRef}
      className="pb-3 px-4 space-y-0 ml-8"
      onDragLeave={handleListDragLeave}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleRowDrop}
    >
      {visible.map((activity, idx) => {
        const parsed = parse(activity);
        const isBeingDragged = parsed.blockId === draggingBlockId;
        const rowKey = `${parsed.blockId ?? "no-id"}-${idx}`;
        const isSelected = selectedIds.has(rowKey);
        return (
          <React.Fragment key={rowKey}>
            {insertAfterIdx === idx - 1 && <InsertionLine />}
            <ActivityRow
              activity={activity}
              client={client}
              categoryName={categoryName}
              allClients={allClients}
              allCategories={allCategories}
              onMove={onMove}
              isBeingDragged={isBeingDragged}
              isSelected={isSelected}
              onDragOver={(e) => handleRowDragOver(e, idx)}
              onToggleSelect={(_shift) => {
                onToggleSelect(rowKey, idx, false);
              }}
            />
            {insertAfterIdx === idx && idx === visible.length - 1 && <InsertionLine />}
          </React.Fragment>
        );
      })}
      {hasMore && (
        <li style={{ listStyle: "none" }} className="pt-1 pb-1">
          <button
            onClick={() => setShowAll((v) => !v)}
            className="text-xs font-bold text-primary hover:underline ml-2"
          >
            {showAll ? "▲ Show less" : `▶ Show all ${activities.length} activities`}
          </button>
        </li>
      )}
    </ul>
  );
}

// ─── Activity Row ──────────────────────────────────────────────────────────────

function ActivityRow({
  activity, client, categoryName, allClients, allCategories,
  onMove, isBeingDragged, isSelected, onDragOver, onToggleSelect,
}: {
  activity: string;
  client: ClientTime;
  categoryName: string;
  allClients: ClientOption[];
  allCategories: string[];
  onMove: (blockId: number, clientId: number | null, category: string) => Promise<void>;
  isBeingDragged: boolean;
  isSelected: boolean;
  onDragOver: (e: React.DragEvent) => void;
  onToggleSelect: (shift: boolean) => void; // fires with rowKey internally
}) {
  const [showPopover, setShowPopover] = useState(false);
  const [checkboxActive, setCheckboxActive] = useState(false);
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
      padding: "6px 14px", borderRadius: "99px",
      fontSize: "13px", fontWeight: "600",
      whiteSpace: "nowrap", maxWidth: "360px",
      overflow: "hidden", textOverflow: "ellipsis",
      boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
      pointerEvents: "none",
    });
    ghost.textContent = `↗ ${parsed.title}`;
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, 16, 16);
    setTimeout(() => document.body.removeChild(ghost), 0);
  };

  const handleApply = async (clientId: number | null, category: string) => {
    setShowPopover(false);
    if (parsed.blockId) await onMove(parsed.blockId, clientId, category);
  };

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    e.nativeEvent.stopImmediatePropagation();
    onToggleSelect(false);
  };

  return (
    <li
      draggable={!!parsed.blockId}
      onDragStart={handleDragStart}
      onDragOver={onDragOver}
      className={cn(
        "flex items-center gap-2 group/item rounded-lg px-2 py-1.5 transition-all relative",
        parsed.blockId && "cursor-grab",
        isBeingDragged && "opacity-30 bg-slate-100",
        isSelected && !isBeingDragged && "bg-primary/8 ring-1 ring-primary/30",
        !isBeingDragged && !isSelected && "hover:bg-slate-50"
      )}
      style={{ listStyle: "none" }}
    >
      {/* Checkbox — always visible on hover, visible when selected */}
      {parsed.blockId ? (
        <button
          onMouseDown={(e) => { setCheckboxActive(true); handleCheckboxClick(e); }}
          onMouseUp={() => setTimeout(() => setCheckboxActive(false), 300)}
          className={cn(
            "flex-shrink-0 transition-all",
            isSelected
              ? "opacity-100"
              : "opacity-0 group-hover/item:opacity-100"
          )}
          title="Select (shift+click for range)"
        >
          {isSelected
            ? <CheckSquare className="w-3.5 h-3.5 text-primary" />
            : <Square className="w-3.5 h-3.5 text-slate-400" />}
        </button>
      ) : (
        <span className="w-3.5 flex-shrink-0" />
      )}

      {/* Drag handle — shown when not selected */}
      {parsed.blockId && !isSelected ? (
        <GripVertical className="w-3.5 h-3.5 text-slate-300 group-hover/item:text-slate-500 flex-shrink-0 transition-colors" />
      ) : (
        <span className="w-3.5 flex-shrink-0" />
      )}

      <ArrowRight className="w-3 h-3 text-slate-300 flex-shrink-0" />

      <span className={cn(
        "text-sm font-medium flex-1 truncate",
        isSelected ? "text-primary font-semibold" : "text-slate-600"
      )}>
        {parsed.title}
      </span>

      {/* Hover actions — only when not in selection mode */}
      {parsed.blockId && !isSelected && (
        <div className="flex items-center gap-1 opacity-0 group-hover/item:opacity-100 transition-opacity flex-shrink-0 relative">
          <button
            onClick={(e) => { e.stopPropagation(); setShowPopover((v) => !v); }}
            className="px-2 py-1 text-xs font-bold border-2 border-slate-200 rounded-lg hover:border-primary hover:text-primary text-slate-500 transition-all"
          >
            Move
          </button>
          {showPopover && (
            <MovePopover
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
    </li>
  );
}

// ─── Category Section ──────────────────────────────────────────────────────────

function CategorySection({
  cat, client, allClients, allCategories,
  onMoveActivity, onMoveAll,
  draggingBlockId,
  onCatDragOver, onCatDragLeave, onCatDrop, isCatDropTarget,
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
  const nonBillable = isNonBillable(cat.name);

  const allBlockIds = cat.sample_activities
    .map((a) => parse(a).blockId)
    .filter((id): id is number => id !== null);

  // How many in this category are selected
  const selectedInCat = allBlockIds.filter((id) =>
    Array.from(selectedIds).some(k => k.startsWith(`${id}-`))
  ).length;

  return (
    <div
      className={cn(
        "border-t border-slate-100 transition-all",
        isCatDropTarget && "bg-amber-50 border-t-2 border-t-amber-400"
      )}
      onDragOver={onCatDragOver}
      onDragLeave={onCatDragLeave}
      onDrop={onCatDrop}
    >
      <div className={cn("px-4 py-3 flex items-center gap-3 group/cat relative", nonBillable && "opacity-60")}>
        <button
          onClick={() => setExpanded((v) => !v)}
          className="p-1 hover:bg-slate-100 rounded-lg transition-colors flex-shrink-0"
        >
          {expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
            : <ChevronRight className="w-3.5 h-3.5 text-slate-400" />}
        </button>

        <span className={cn("font-bold text-sm flex-1", nonBillable ? "text-slate-500" : "text-slate-800")}>
          {cat.name}
        </span>

        {selectedInCat > 0 && (
          <span className="text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full flex-shrink-0">
            {selectedInCat} selected
          </span>
        )}

        {cat.needs_review && (
          <span className="flex items-center gap-1 px-2 py-0.5 bg-amber-100 border border-amber-300 rounded-full text-xs font-bold text-amber-700 flex-shrink-0">
            <AlertTriangle className="w-3 h-3" />Review
          </span>
        )}

        {isCatDropTarget && (
          <span className="text-xs font-bold text-amber-700 bg-amber-100 border border-amber-300 px-2 py-0.5 rounded-full flex-shrink-0 animate-pulse">
            Drop to move here
          </span>
        )}

        <span className={cn("font-extrabold text-base flex-shrink-0", nonBillable ? "text-slate-400" : "text-emerald-600")}>
          {fmt(cat.hours)}
        </span>

        {allBlockIds.length > 0 && (
          <div className="relative flex-shrink-0">
            <button
              onClick={(e) => { e.stopPropagation(); setShowMoveAll((v) => !v); }}
              className="opacity-0 group-hover/cat:opacity-100 px-2 py-1 text-xs font-bold border-2 border-slate-200 rounded-lg hover:border-primary hover:text-primary text-slate-500 transition-all"
            >
              Move all
            </button>
            {showMoveAll && (
              <MovePopover
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
        )}
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

// ─── Flagged Banner ─────────────────────────────────────────────────────────────

function FlaggedBanner({ flagged, onDismiss }: { flagged: FlaggedBlock[]; onDismiss: (id: number) => void }) {
  if (!flagged.length) return null;
  return (
    <div className="mb-4 rounded-xl border-2 border-amber-300 bg-amber-50 overflow-hidden">
      <div className="px-4 py-2 bg-amber-100 border-b border-amber-200 flex items-center gap-2">
        <Smartphone className="w-4 h-4 text-amber-600" />
        <span className="text-amber-800 font-bold text-sm">
          {flagged.length} mobile {flagged.length === 1 ? "entry needs" : "entries need"} review
        </span>
      </div>
      <div className="divide-y divide-amber-100">
        {flagged.map((f) => (
          <div key={f.block_id} className="px-4 py-3 flex items-start justify-between gap-4">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5 shrink-0" />
              <div>
                <p className="text-sm font-semibold text-amber-900">{f.client_name} — {fmt(f.minutes / 60)}</p>
                <p className="text-xs text-amber-700 mt-0.5">{f.review_reason}</p>
              </div>
            </div>
            <button
              onClick={() => onDismiss(f.block_id)}
              className="shrink-0 px-3 py-1.5 text-xs font-bold bg-amber-200 hover:bg-amber-300 text-amber-900 rounded-lg transition-all"
            >
              Looks correct
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main ───────────────────────────────────────────────────────────────────────

export default function CategorySummary({
  timeSummary, availableClients, availableCategories,
  flaggedBlocks, busy, onDismissReview, onRefresh, showToast,
}: {
  timeSummary: ClientTime[];
  availableClients: ClientOption[];
  availableCategories: string[];
  flaggedBlocks: FlaggedBlock[];
  busy: boolean;
  onDismissReview: (id: number) => void;
  onRefresh: () => void;
  showToast: (msg: string, type: "success" | "error") => void;
}) {
  const [collapsedClients, setCollapsedClients] = useState<Set<string>>(new Set());
  const [catDropTarget, setCatDropTarget] = useState<string | null>(null);
  const [clientDropTarget, setClientDropTarget] = useState<string | null>(null);
  const [draggingBlockId, setDraggingBlockId] = useState<number | null>(null);

  // ── Multi-select state ────────────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const lastSelectedIdx = null; // kept for prop compat

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

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  // ── Global drag tracking ──────────────────────────────────────────────────
  useEffect(() => {
    const onEnd = () => setDraggingBlockId(null);
    document.addEventListener("dragend", onEnd);
    return () => document.removeEventListener("dragend", onEnd);
  }, []);

  const toggleClient = (key: string) =>
    setCollapsedClients((prev) => {
      const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s;
    });

  // ── API ───────────────────────────────────────────────────────────────────

  const moveActivity = useCallback(async (blockId: number, clientId: number | null, category: string): Promise<boolean> => {
    try {
      await safeFetchJson(`${API_BASE}/blocks/${blockId}/recategorize/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, client_id: clientId }),
      });
      return true;
    } catch (e: any) {
      // 404 = block was deleted or doesn't exist — skip silently
      if (e?.status === 404 || e?.message?.includes("404") || e?.message?.includes("Not found")) {
        return false;
      }
      throw e;
    }
  }, []);

  const moveMany = useCallback(async (blockIds: number[] | string[], clientId: number | null, category: string) => {
    // Support both raw blockIds and rowKeys
    const resolvedIds = (blockIds as any[]).map((id: any) => {
      if (typeof id === "string") return parseInt(id.split("-")[0]);
      return id as number;
    }).filter((n: number) => !isNaN(n) && n > 0);
    blockIds = [...new Set(resolvedIds)];
    if (!blockIds.length) return;
    try {
      const results = await Promise.all(blockIds.map((id) => moveActivity(id, clientId, category)));
      const moved = results.filter(Boolean).length;
      if (moved > 0) {
        showToast(`Moved ${moved} activit${moved !== 1 ? "ies" : "y"}`, "success");
      } else {
        showToast("Nothing to move — blocks may have been removed", "error");
      }
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



  // ── Category / client drop ────────────────────────────────────────────────

  const makeCatDragOver = (catKey: string) => (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setCatDropTarget(catKey);
  };

  const makeCatDrop = (clientId: number | null, catName: string) => async (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setCatDropTarget(null);
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
    e.preventDefault(); setClientDropTarget(null);
    const raw = e.dataTransfer.getData("application/x-block");
    if (!raw) return;
    const { blockId, fromClient, fromCategory } = JSON.parse(raw);
    if (fromClient === targetClient.client) return;
    setDraggingBlockId(blockId);
    await moveSingle(blockId, targetClient.client_id, fromCategory);
    setDraggingBlockId(null);
  };

  // ── Render ────────────────────────────────────────────────────────────────

  const getBillable = (c: ClientTime) =>
    c.categories.filter((cat) => !isNonBillable(cat.name)).reduce((s, cat) => s + cat.hours, 0);

  return (
    <div>
      <FlaggedBanner flagged={flaggedBlocks} onDismiss={onDismissReview} />

      {timeSummary.length > 1 && (
        <div className="mb-3 flex items-center justify-between">
          <p className="text-xs text-slate-400 font-medium">
            Click checkboxes to select · use floating bar to move or delete
          </p>
          <button
            onClick={() => {
              if (collapsedClients.size === 0) {
                setCollapsedClients(new Set(timeSummary.map((c) => `${c.client_id}-${c.client}`)));
              } else {
                setCollapsedClients(new Set());
              }
            }}
            className="text-sm text-slate-500 hover:text-slate-900 font-semibold px-3 py-1.5 rounded-lg hover:bg-slate-100 transition-all"
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
        <div className="text-center py-16 bg-white rounded-2xl border-2 border-slate-200">
          <FileQuestion className="w-12 h-12 text-slate-300 mx-auto mb-3" />
          <h3 className="text-lg font-bold text-slate-800 mb-1">No time tracked yet</h3>
          <p className="text-slate-500 font-medium">Activity appears automatically as you work, or add time manually.</p>
        </div>
      )}

      <div className="space-y-3">
        {timeSummary.map((client, clientIndex) => {
          const clientKey = `${client.client_id}-${client.client}`;
          const isCollapsed = collapsedClients.has(clientKey);
          const unassigned = client.client.toLowerCase() === "unassigned";
          const isClientDrop = clientDropTarget === clientKey;

          const colors = unassigned
            ? { bg: "bg-slate-50", border: "border-slate-200", accent: "bg-slate-100", text: "text-slate-400", hours: "text-slate-400" }
            : getClientColor(clientIndex);

          return (
            <div
              key={clientKey}
              className={cn(
                "rounded-2xl border-2 shadow-sm transition-all duration-200",
                colors.bg, colors.border,
                unassigned && "opacity-70",
                isClientDrop && "ring-2 ring-primary ring-offset-1"
              )}
              onDragOver={(e) => { e.preventDefault(); setClientDropTarget(clientKey); }}
              onDragLeave={() => setClientDropTarget(null)}
              onDrop={makeClientDrop(client)}
            >
              <button
                onClick={() => toggleClient(clientKey)}
                className={cn("w-full px-4 py-3 flex items-center justify-between rounded-t-2xl", colors.accent)}
              >
                <div className="flex items-center gap-3">
                  <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center", unassigned ? "bg-slate-200" : "bg-white/70")}>
                    {isCollapsed
                      ? <ChevronRight className={cn("w-4 h-4", colors.text)} />
                      : <ChevronDown className={cn("w-4 h-4", colors.text)} />}
                  </div>
                  <span className={cn("font-extrabold text-lg tracking-tight", unassigned ? "text-slate-500" : "text-slate-900")}>
                    {client.client}
                  </span>
                  <span className="text-sm text-slate-500 font-semibold">
                    {client.categories.length} {client.categories.length === 1 ? "category" : "categories"}
                  </span>
                  {isClientDrop && (
                    <span className="text-xs font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full animate-pulse">
                      Drop to reassign client
                    </span>
                  )}
                </div>
                <span className={cn("text-2xl font-extrabold", colors.hours)}>
                  {fmt(unassigned ? client.total_hours : getBillable(client))}
                </span>
              </button>

              {!isCollapsed && (
                <div className="bg-white rounded-b-2xl">
                  {client.categories.map((cat) => {
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
            </div>
          );
        })}
      </div>

      {/* Floating selection action bar */}
      <SelectionBar
        count={selectedIds.size}
        clients={availableClients}
        categories={availableCategories}
        onMove={(clientId, category) => moveMany(Array.from(selectedIds) as any, clientId, category)}
        onClear={clearSelection}
      />
    </div>
  );
}