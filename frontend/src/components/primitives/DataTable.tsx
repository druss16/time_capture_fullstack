/**
 * DataTable — sortable, format-aware table.
 *
 * Columns specify their format; cells render via formatValue().
 * Click a column header to sort. Default sort comes from the backend payload.
 */
import { useMemo, useState } from "react";
import { ArrowUpDown, ArrowUp, ArrowDown, Inbox } from "lucide-react";
import { cn } from "@/lib/design-system";
import { formatValue } from "@/lib/analytics_v2/format";
import type { DataTablePayload } from "@/lib/analytics_v2/types";

interface Props {
  table: DataTablePayload;
  onRowClick?: (row: Record<string, any>) => void;
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

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="rounded-[15px] border border-border/70 bg-white overflow-hidden shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)]">
      <header className="px-5 py-4 border-b border-slate-100">
        <h3 className="text-sm font-semibold text-slate-900">{table.title}</h3>
        {table.subtitle && (
          <p className="text-xs text-slate-500 mt-0.5">{table.subtitle}</p>
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
                  <th
                    key={col.key}
                    onClick={col.sortable ? () => handleSort(col.key) : undefined}
                    className={cn(
                      "text-left text-xs font-medium uppercase tracking-wider text-slate-600 px-4 py-3",
                      col.format !== "text" && "text-right",
                      col.sortable && "cursor-pointer hover:bg-slate-100/60 select-none",
                    )}
                  >
                    <div className={cn(
                      "flex items-center gap-1.5",
                      col.format !== "text" && "justify-end",
                    )}>
                      <span>{col.label}</span>
                      {col.sortable && <SortIcon active={sortKey === col.key} dir={sortDir} />}
                    </div>
                  </th>
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
                        "px-4 py-3 text-slate-700",
                        col.format !== "text" && "text-right tabular-nums font-medium",
                      )}
                    >
                      {col.format === "text"
                        ? String(row[col.key] ?? "")
                        : formatValue(row[col.key], col.format)}
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

function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <ArrowUpDown className="h-3 w-3 text-slate-400" />;
  return dir === "asc"
    ? <ArrowUp className="h-3 w-3 text-primary" />
    : <ArrowDown className="h-3 w-3 text-primary" />;
}
