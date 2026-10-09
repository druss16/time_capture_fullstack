/**
 * The filters narrowing the current view, listed under the page title.
 *
 * The control bar only says "2 filters", which tells a viewer — or whoever
 * opens a shared link, or reads a printout — that the numbers are narrowed but
 * not by what. Each chip names one filter and removes it on click.
 */
import { X } from "lucide-react";
import { useAnalyticsPermissions } from "@/hooks/useAnalyticsQuery";
import type { FilterDim, ScopeFilters } from "@/lib/analytics_v2/types";
import {
  BILLABLE_OPTIONS, useCategoryOptions, useClientOptions, useProjectOptions,
  useStaffOptions, type Option,
} from "./ControlBar";

interface Props {
  filters: ScopeFilters | undefined;
  onChange: (next: ScopeFilters) => void;
}

interface Chip { key: string; dim: string; value: string; remove: () => ScopeFilters }

export default function ActiveFilters({ filters, onChange }: Props) {
  const { data: perms } = useAnalyticsPermissions();
  // Same queries the control bar already holds, so these resolve from cache.
  const options: Record<FilterDim, Option[]> = {
    client: useClientOptions(perms?.capabilities?.can_pick_any_client ?? false),
    engagement: useProjectOptions(),
    staff: useStaffOptions(perms?.capabilities?.can_pick_any_staff ?? false),
    service: useCategoryOptions(),
  };

  const f = filters ?? {};
  const DIMS: Array<{ dim: FilterDim; label: string }> = [
    { dim: "client", label: "Client" },
    { dim: "engagement", label: "Project" },
    { dim: "staff", label: "Employee" },
    { dim: "service", label: "Category" },
  ];

  const chips: Chip[] = [];
  for (const { dim, label } of DIMS) {
    for (const id of f[dim] ?? []) {
      chips.push({
        key: `${dim}-${id}`,
        dim: label,
        // Option lists can still be loading; an id is better than a blank chip.
        value: options[dim].find(o => o.id === id)?.label ?? `#${id}`,
        remove: () => ({ ...f, [dim]: (f[dim] ?? []).filter(x => x !== id) }),
      });
    }
  }
  if (f.billable && f.billable !== "all") {
    chips.push({
      key: "billable",
      dim: "Time",
      value: BILLABLE_OPTIONS.find(o => o.value === f.billable)?.label ?? f.billable,
      remove: () => ({ ...f, billable: "all" }),
    });
  }

  if (!chips.length) return null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mr-0.5">
        Filtered by
      </span>
      {chips.map(c => (
        <span
          key={c.key}
          className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 pl-2.5 pr-1 py-0.5 text-[12px] text-sky-900"
        >
          <span className="text-sky-700/70">{c.dim}:</span>
          <span className="font-semibold">{c.value}</span>
          <button
            type="button"
            onClick={() => onChange(c.remove())}
            className="ml-0.5 rounded-full p-0.5 text-sky-600 hover:bg-sky-100 hover:text-sky-900 print:hidden"
            aria-label={`Remove ${c.dim} filter ${c.value}`}
            title="Remove filter"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
    </div>
  );
}
