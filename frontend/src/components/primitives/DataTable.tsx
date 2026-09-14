/**
 * DataTable — sortable, format-aware table.
 *
 * Columns specify their format; cells render via formatValue().
 * Click a column header to sort. Default sort comes from the backend payload.
 */
import {
  useCallback, useEffect, useMemo, useRef, useState,
} from "react";
import { ArrowUpDown, ArrowUp, ArrowDown, Inbox, Info } from "lucide-react";
import { cn } from "@/lib/design-system";
import { formatValue } from "@/lib/analytics_v2/format";
import { API_BASE, safeFetchJson } from "@/lib/api";
import type { DataTablePayload, DataTableColumn } from "@/lib/analytics_v2/types";

/**
 * PhaseCell — the one piece of data entry in budget-vs-progress.
 *
 * Burn comes free from captured time; progress cannot. Someone has to say how
 * far along the job is, so the ask is one dropdown, inline, right next to the
 * number it corrects. Saving updates the row in place rather than reloading
 * the whole lens — the picker is next to a table people scan, and a full
 * refetch on every pick would make it feel like a form.
 */
interface PhaseOption { value: string; label: string; progress: number }

function PhaseCell({ row }: { row: Record<string, any> }) {
  const [phase, setPhase] = useState<string>(row.phase ?? "");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const options: PhaseOption[] = row.phase_options ?? [];
  const engagementId = row.engagement_id;

  if (!engagementId || options.length === 0) {
    return <span className="text-slate-400">{row.phase_label ?? "—"}</span>;
  }

  const save = async (next: string) => {
    const previous = phase;
    setPhase(next);
    setSaving(true);
    setFailed(false);
    try {
      await safeFetchJson(`${API_BASE}/engagements/${engagementId}/phase/`, {
        method: "POST",
        body: JSON.stringify({ phase: next }),
      });
    } catch {
      setPhase(previous);
      setFailed(true);
    } finally {
      setSaving(false);
    }
  };

  return (
    <select
      value={phase}
      disabled={saving}
      onClick={e => e.stopPropagation()}
      onChange={e => save(e.target.value)}
      title={failed ? "Could not save — try again" : "How far along is this job?"}
      className={cn(
        "rounded-md border px-2 py-1 text-xs bg-white",
        failed ? "border-rose-300 text-rose-700" : "border-slate-200 text-slate-700",
        saving && "opacity-60",
      )}
    >
      <option value="">Not set</option>
      {options.map(o => (
        <option key={o.value} value={o.value}>
          {o.label} · {o.progress}%
        </option>
      ))}
    </select>
  );
}

interface Props {
  table: DataTablePayload;
  onRowClick?: ((row: Record<string, any>) => void) | undefined;
}

export default function DataTable({ table, onRowClick }: Props) {
  const [sortKey, setSortKey] = useState<string>(table.default_sort?.key ?? "");
  const [sortDir, setSortDir] = useState<"asc" | "desc">(table.default_sort?.direction ?? "desc");

  const sortedRows = useMemo(() => {
    if (!sortKey) return table.rows;
    const copy = [...table.rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      const as = String(av).toLowerCase();
      const bs = String(bv).toLowerCase();
      return sortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    });
    return copy;
  }, [table.rows, sortKey, sortDir]);

  // Max per bar column, for scaling the in-cell proportion bars. Computed over
  // ALL rows, not the sorted page, so the bars keep their meaning when the
  // viewer re-sorts by a different column.
  const barMax = useMemo(() => {
    const out: Record<string, number> = {};
    for (const key of table.bar_columns ?? []) {
      out[key] = Math.max(
        0, ...table.rows.map(r => (typeof r[key] === "number" ? Math.abs(r[key]) : 0)));
    }
    return out;
  }, [table.rows, table.bar_columns]);

  // Is there more table to the right than is currently visible?
  const scrollRef = useRef<HTMLDivElement>(null);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const updateScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setCanScrollRight(el.scrollWidth - el.clientWidth - el.scrollLeft > 1);
  }, []);
  useEffect(() => {
    updateScroll();
    window.addEventListener("resize", updateScroll);
    return () => window.removeEventListener("resize", updateScroll);
  }, [updateScroll, table.rows, table.columns]);

  // Rank is fixed to the order the backend sent — the ranking the subtitle
  // names ("top 20 by hours"). Re-sorting by margin re-orders these twenty; it
  // does not renumber them 1..20 by margin, which would claim a different
  // ranking than the one that selected the rows.
  const rankOf = useMemo(() => {
    const m = new Map<Record<string, any>, number>();
    table.rows.forEach((r, i) => m.set(r, i + 1));
    return m;
  }, [table.rows]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="rounded-2xl border border-[rgba(15,42,60,0.08)] bg-white overflow-hidden shadow-[0_1px_2px_rgba(16,27,46,0.04),0_8px_24px_-12px_rgba(16,27,46,0.10)]">
      <header className="px-5 py-4 border-b border-slate-100">
        <h3 className="text-[15px] font-bold tracking-[-0.015em] text-slate-900">{table.title}</h3>
        {table.subtitle && (
          <p className="text-xs text-slate-500 mt-0.5">{table.subtitle}</p>
        )}
        {table.footnote && (
          <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
            {table.footnote}
          </p>
        )}
      </header>

      {table.state === "empty" || table.rows.length === 0 ? (
        <div className="py-12 flex flex-col items-center text-slate-400">
          <Inbox className="h-8 w-8 mb-2" />
          <p className="text-sm">No data for this period</p>
        </div>
      ) : (
        // Nine money columns will not always fit, and how wide they are
        // depends on how long this firm's client names happen to be — so the
        // table scrolls, and the fade makes that obvious. Without it a clipped
        // "Margin %" reads as a missing column rather than an off-screen one.
        <div className="relative">
          {canScrollRight && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-y-0 right-0 z-[11] w-12 bg-gradient-to-l from-white to-transparent"
            />
          )}
          <div ref={scrollRef} onScroll={updateScroll} className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[rgba(15,42,60,0.10)] bg-slate-50/70">
                {table.ranked && (
                  <th className="sticky top-0 z-10 w-8 bg-slate-50/95 py-2.5 pl-4 pr-1 text-left text-[10.5px] font-semibold uppercase tracking-[0.1em] text-slate-400 backdrop-blur" />
                )}
                {table.columns.map(col => (
                  <HeaderCell
                    key={col.key}
                    col={col}
                    active={sortKey === col.key}
                    dir={sortDir}
                    onSort={col.sortable ? () => handleSort(col.key) : undefined}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row, i) => (
                <tr
                  key={i}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "border-b border-[rgba(15,42,60,0.05)] transition-colors last:border-0",
                    onRowClick && "cursor-pointer hover:bg-teal-50/50",
                  )}
                >
                  {table.ranked && (
                    <td className="w-8 py-2.5 pl-4 pr-1 text-left align-middle text-[11px] font-semibold tabular-nums text-slate-300">
                      {rankOf.get(row) ?? ""}
                    </td>
                  )}
                  {table.columns.map((col, ci) => (
                    <td
                      key={col.key}
                      className={cn(
                        "relative py-2.5 align-middle",
                        ci === 0 ? "pl-4 pr-3" : "px-2",
                        col.key === "flag_label" && "w-px whitespace-nowrap",
                        (table.bar_columns ?? []).includes(col.key) && "pb-4",
                        // The first column is the row's identity: it carries
                        // the weight, and enough width that a real client name
                        // does not stack three lines tall and make every row a
                        // different height.
                        ci === 0
                          ? "min-w-[11rem] max-w-[18rem] font-semibold leading-snug text-slate-900"
                          : "text-slate-600",
                        col.format !== "text" && col.format !== "phase_picker" &&
                          "whitespace-nowrap text-right font-medium tabular-nums text-slate-800",
                      )}
                      style={col.format !== "text" && col.format !== "phase_picker"
                        ? { fontVariantNumeric: "tabular-nums",
                            letterSpacing: "-0.01em" }
                        : undefined}
                    >
                      {/* A thin rule under the figure, not a wash behind it.
                          The filled block this replaced read as a selected
                          cell rather than as a measure, and its right-anchored
                          growth made the geometry hard to parse. This is a
                          baseline-anchored bar with a rounded data-end — the
                          same mark spec the charts use. */}
                      {barMax[col.key] > 0 && typeof row[col.key] === "number" && (
                        <span
                          aria-hidden
                          className="absolute inset-x-2 bottom-1.5 h-[3px] rounded-full bg-slate-100"
                        >
                          <span
                            className={cn(
                              "absolute inset-y-0 right-0 rounded-full",
                              row[col.key] < 0 ? "bg-rose-500/80" : "bg-teal-600/70",
                            )}
                            style={{
                              width: `${Math.min(100, Math.max(
                                (Math.abs(row[col.key]) / barMax[col.key]) * 100, 0))}%`,
                            }}
                          />
                        </span>
                      )}
                      <span className="relative">
                        {col.format === "phase_picker" ? (
                          <PhaseCell row={row} />
                        ) : col.format === "text" ? (
                          renderText(row[col.key], col.key)
                        ) : (
                          formatValue(row[col.key], col.format)
                        )}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Text cells render as text, with one exception: the flag column carries a
 * " · "-joined list of short phrases, and as plain text they run together into
 * a sentence. Rendered as pills they read as the tags they are.
 */
/**
 * Flags are shortened for the column and coloured by severity — "Losing money"
 * is not the same news as "Hours growing fast", and one amber for all of them
 * said it was.
 */
/** Badges shown inline before the rest fold into a "+N". */
const MAX_FLAGS = 2;

const FLAG_SHORT: Record<string, string> = {
  "Losing money": "Losing $",
  "Below typical margin": "Low margin",
  "Heavy non-billable": "Non-billable",
  "Hours growing fast": "Growing",
};

const FLAG_TONE: Record<string, string> = {
  "Losing money": "bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200",
  "Below typical margin": "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200",
  "Heavy non-billable": "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200",
  "Hours growing fast": "bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200",
  _default: "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200",
};

function renderText(value: unknown, key: string) {
  const text = String(value ?? "");
  if (key !== "flag_label" || !text) return text || (key === "flag_label" ? "" : text);

  // At most two badges. A third pushed the flag column wide enough to shove
  // Margin % off the right edge of the table, and the backend already orders
  // flags worst-first — so the two shown are the two that matter. The rest are
  // still readable on hover.
  const all = text.split(" · ");
  const shown = all.slice(0, MAX_FLAGS);
  const hidden = all.slice(MAX_FLAGS);

  return (
    <span className="flex flex-nowrap items-center gap-1">
      {shown.map(part => (
        <span
          key={part}
          title={part}
          // Squared-off, not a soft blob, and never wrapping: a two-line pill
          // pushed every row in the table taller than its neighbours.
          className={cn(
            "inline-block whitespace-nowrap rounded-md px-1.5 py-0.5",
            "text-[10px] font-semibold uppercase tracking-[0.06em]",
            FLAG_TONE[part] ?? FLAG_TONE._default,
          )}
        >
          {FLAG_SHORT[part] ?? part}
        </span>
      ))}
      {hidden.length > 0 && (
        <span
          title={hidden.join(" · ")}
          className="inline-block whitespace-nowrap rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500 ring-1 ring-inset ring-slate-200"
        >
          +{hidden.length}
        </span>
      )}
    </span>
  );
}

function HeaderCell({
  col, active, dir, onSort,
}: {
  col: DataTableColumn;
  active: boolean;
  dir: "asc" | "desc";
  onSort: (() => void) | undefined;
}) {
  const [showTip, setShowTip] = useState(false);
  const numeric = col.format !== "text";
  return (
    <th
      onClick={onSort}
      className={cn(
        // Sticky so the column meanings survive a 52-client scroll.
        "group/th sticky top-0 z-10 whitespace-nowrap bg-slate-50/95 py-2.5 backdrop-blur",
        numeric ? "px-2" : "pl-4 pr-3",
        "text-left text-[10.5px] font-semibold uppercase tracking-[0.1em] text-slate-500",
        numeric && "text-right",
        onSort && "cursor-pointer select-none hover:bg-slate-100 hover:text-slate-800",
      )}
    >
      <div className={cn("flex items-center gap-1.5", numeric && "justify-end")}>
        <span>{col.label}</span>
        {col.tooltip && (
          <span
            className="relative inline-flex"
            onMouseEnter={() => setShowTip(true)}
            onMouseLeave={() => setShowTip(false)}
            onClick={(e) => e.stopPropagation()}
          >
            <Info className="h-3 w-3 text-slate-400 hover:text-slate-600 cursor-help" />
            {showTip && (
              <span className={cn(
                "absolute top-5 z-20 w-60 rounded-lg bg-slate-900 text-white text-[11px] normal-case tracking-normal font-normal p-2.5 shadow-lg leading-snug",
                numeric ? "right-0" : "left-0",
              )}>
                {col.tooltip}
              </span>
            )}
          </span>
        )}
        {col.sortable && (active
          ? <SortIcon active dir={dir} />
          : <ArrowUpDown className="h-3 w-3 text-slate-300 opacity-0 transition-opacity group-hover/th:opacity-100" />)}
      </div>
    </th>
  );
}

function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <ArrowUpDown className="h-3 w-3 text-slate-400" />;
  return dir === "asc"
    ? <ArrowUp className="h-3 w-3 text-primary" />
    : <ArrowDown className="h-3 w-3 text-primary" />;
}
