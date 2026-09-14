/**
 * DataTable — sortable, format-aware table.
 *
 * Columns specify their format; cells render via formatValue().
 * Click a column header to sort. Default sort comes from the backend payload.
 */
import { useMemo, useState } from "react";
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
        0, ...table.rows.map(r => (typeof r[key] === "number" ? r[key] : 0)));
    }
    return out;
  }, [table.rows, table.bar_columns]);

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
        <h3 className="text-sm font-semibold text-slate-900">{table.title}</h3>
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
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/50">
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
                    "border-b border-slate-50 last:border-0",
                    onRowClick && "hover:bg-primary/[0.05] cursor-pointer",
                  )}
                >
                  {table.columns.map(col => (
                    <td
                      key={col.key}
                      className={cn(
                        "relative px-4 py-3 text-slate-700",
                        col.format !== "text" && col.format !== "phase_picker" &&
                          "text-right tabular-nums font-medium",
                      )}
                    >
                      {barMax[col.key] > 0 && typeof row[col.key] === "number" && (
                        <span
                          aria-hidden
                          className="absolute inset-y-1 right-1 rounded bg-teal-500/10"
                          style={{
                            width: `${Math.max(
                              (row[col.key] / barMax[col.key]) * 100, 0)}%`,
                          }}
                        />
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
      )}
    </div>
  );
}

/**
 * Text cells render as text, with one exception: the flag column carries a
 * " · "-joined list of short phrases, and as plain text they run together into
 * a sentence. Rendered as pills they read as the tags they are.
 */
function renderText(value: unknown, key: string) {
  const text = String(value ?? "");
  if (key !== "flag_label" || !text) return text || (key === "flag_label" ? "" : text);
  return (
    <span className="flex flex-wrap gap-1">
      {text.split(" · ").map(part => (
        <span
          key={part}
          className="inline-block rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-inset ring-amber-200/70"
        >
          {part}
        </span>
      ))}
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
        "text-left text-xs font-medium uppercase tracking-wider text-slate-600 px-4 py-3",
        numeric && "text-right",
        onSort && "cursor-pointer hover:bg-slate-100/60 select-none",
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
        {col.sortable && <SortIcon active={active} dir={dir} />}
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
