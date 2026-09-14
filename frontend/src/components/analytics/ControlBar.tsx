/**
 * The Analytics control bar: what you are looking at, over what period,
 * against what, narrowed by what.
 *
 * It replaced a left sidebar. The sidebar cost 256px of every screen to hold
 * four controls that are read once and then ignored, which on a dashboard
 * whose whole job is wide tables and charts is the most expensive real estate
 * in the product. A sticky top bar keeps the same controls one click away and
 * gives the data the full width.
 *
 * Filters apply to every view, so they live here rather than inside any one of
 * them, and they survive drilling into a client or a person.
 *
 * There is no Team filter. The data model has no team — staff belong to cost
 * tiers, which are a cost grouping, not an org chart — and offering a Team
 * control backed by tiers would label something as a team that is not one.
 */
import { useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Calendar, Clock, Printer, RefreshCw, Settings, X,
} from "lucide-react";
import { cn } from "@/lib/design-system";
import {
  useAnalyticsCategories, useAnalyticsClients, useAnalyticsPermissions,
  useAnalyticsProjects, useAnalyticsStaff,
} from "@/hooks/useAnalyticsQuery";
import {
  COMPARE_OPTIONS, TIME_OPTIONS, VIEW_OPTIONS, compareLabelFor,
  countActiveFilters, timeLabelFor,
} from "@/lib/analytics_v2/urlState";
import type {
  AnalyticsQueryBody, BillableFilter, LensKey, ScopeFilters,
} from "@/lib/analytics_v2/types";
import { getUserDisplayName } from "@/pages/settings/types";
import Dropdown, { MenuGroupLabel, MenuItem } from "./Dropdown";

interface Props {
  body: AnalyticsQueryBody;
  availableViews: Set<LensKey>;
  /** The resolved view sentence — "TL Wall Accounting · Q3 2026". */
  sentence: string;
  dataFreshness?: string | null | undefined;
  generatedAt?: string | null | undefined;
  isFetching: boolean;
  onRefresh: () => void;
  /**
   * The scope label the backend resolved for the current response. The URL
   * carries only `client:42` — putting the name in it would rot the moment a
   * client is renamed — so the readable name comes back with the data.
   */
  scopeLabel?: string | undefined;
  onChange: (next: Partial<AnalyticsQueryBody>) => void;
}

const BILLABLE_OPTIONS: Array<{ value: BillableFilter; label: string }> = [
  { value: "all",          label: "All time" },
  { value: "billable",     label: "Billable only" },
  { value: "non_billable", label: "Non-billable only" },
];

export default function ControlBar({
  body, availableViews, scopeLabel, sentence, dataFreshness, generatedAt,
  isFetching, onRefresh, onChange,
}: Props) {
  const { data: perms } = useAnalyticsPermissions();
  const canPickClient = perms?.capabilities?.can_pick_any_client ?? false;
  const canPickStaff = perms?.capabilities?.can_pick_any_staff ?? false;

  // Option lists are resolved here, at the top level of the component, NOT
  // inside the filter popover's render callback — that callback only runs
  // while the popover is open, so hooks called from it would mount and
  // unmount with the menu.
  const clientOptions = useClientOptions(canPickClient);
  const projectOptions = useProjectOptions();
  const staffOptions = useStaffOptions(canPickStaff);
  const categoryOptions = useCategoryOptions();

  const filters = body.scope.filters ?? {};
  const activeCount = countActiveFilters(filters);

  const setFilters = (next: ScopeFilters) =>
    onChange({ scope: { ...body.scope, filters: next } });

  const primary = VIEW_OPTIONS.filter(v => !v.secondary && availableViews.has(v.value));
  const secondary = VIEW_OPTIONS.filter(v => v.secondary && availableViews.has(v.value));
  const currentView = VIEW_OPTIONS.find(v => v.value === body.lens);
  const inSecondary = Boolean(currentView?.secondary);

  return (
    /* One masthead, continuous with the app nav above it.
       This replaced three stacked grey bands — tabs, controls, then a tall
       title block — which cost about 200px of chrome before any data and gave
       the page no focal point. Dark ground also makes the white cards below
       read as lit, which is where the energy comes from: contrast, not
       louder charts. */
    <div className="sticky top-0 z-20 bg-slate-800 text-white shadow-[0_10px_30px_-20px_rgba(2,6,23,0.9)] print:static print:bg-white print:text-black print:shadow-none">
      {/* Title + actions */}
      <div className="mx-auto flex max-w-[1560px] items-center justify-between gap-4 px-6 pt-4">
        <div className="min-w-0">
          <h1 className="truncate text-[22px] font-bold leading-none tracking-[-0.025em] text-white print:text-black">
            {sentence || "Analytics"}
          </h1>
          {dataFreshness && (
            <p className="mt-1.5 flex items-center gap-1 text-[11px] tabular-nums text-slate-400 print:text-slate-600">
              <Clock className="h-3 w-3" />
              Data through {formatRelative(dataFreshness)}
            </p>
          )}
          <p className="mt-1 hidden text-[11px] tabular-nums text-slate-600 print:block">
            Printed {new Date().toLocaleString(undefined, {
              year: "numeric", month: "short", day: "numeric",
              hour: "numeric", minute: "2-digit",
            })}
            {generatedAt ? ` · data generated ${new Date(generatedAt).toLocaleString(undefined, {
              month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
            })}` : ""}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1.5 print:hidden">
          <IconAction icon={Printer} label="Print" onClick={() => window.print()} />
          <IconAction
            icon={RefreshCw}
            label={isFetching ? "Refreshing" : "Refresh"}
            spinning={isFetching}
            onClick={onRefresh}
          />
          <Link
            to="/settings?tab=economics"
            title="Economics & capacity settings"
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5 text-xs font-semibold text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
          >
            <Settings className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Settings</span>
          </Link>
        </div>
      </div>

      {/* Views */}
      {/* overflow-x-auto clips on BOTH axes; the dropdowns here render through
          a portal so they are not caught by it. See Dropdown.tsx. */}
      <div className="mx-auto flex max-w-[1560px] flex-wrap items-end justify-between gap-x-6 gap-y-2 px-6 pt-3 print:hidden">
      <div className="flex items-end gap-0.5 overflow-x-auto">
        {primary.map(v => (
          <ViewTab
            key={v.value}
            label={v.label}
            title={v.description}
            active={body.lens === v.value}
            onClick={() => onChange({ lens: v.value })}
          />
        ))}

        {secondary.length > 0 && (
          <Dropdown
            align="right"
            widthClass="w-72"
            active={inSecondary}
            label={inSecondary ? currentView!.label : "More"}
          >
            {close => (
              <>
                <MenuGroupLabel>Focused views</MenuGroupLabel>
                {secondary.map(v => (
                  <MenuItem
                    key={v.value}
                    selected={body.lens === v.value}
                    onClick={() => { onChange({ lens: v.value }); close(); }}
                  >
                    <span className="block">{v.label}</span>
                    <span className="block text-xs text-slate-500">{v.description}</span>
                  </MenuItem>
                ))}
              </>
            )}
          </Dropdown>
        )}
      </div>

      {/* Controls */}
      </div>
      <div className="flex flex-wrap items-center gap-2 pb-3">
        <PeriodPicker body={body} onChange={onChange} />

        <Dropdown
          caption="Compare to"
          label={compareLabelFor(body.compare)}
          active={Boolean(body.compare)}
          widthClass="w-60"
        >
          {close => (
            <>
              {COMPARE_OPTIONS.map(o => (
                <MenuItem
                  key={o.value || "none"}
                  selected={(body.compare?.value ?? "") === o.value}
                  onClick={() => {
                    onChange({
                      compare: o.value
                        ? { type: "relative", value: o.value }
                        : null,
                    });
                    close();
                  }}
                >
                  {o.label}
                </MenuItem>
              ))}
            </>
          )}
        </Dropdown>

        <Dropdown
          caption="Filters"
          label={activeCount ? `${activeCount} applied` : "None"}
          active={activeCount > 0}
          widthClass="w-80"
          align="left"
        >
          {() => (
            <div className="max-h-[60vh] overflow-y-auto">
              <MultiFilter
                title="Client"
                selected={filters.client ?? []}
                options={clientOptions}
                onChange={ids => setFilters({ ...filters, client: ids })}
              />
              <MultiFilter
                title="Project"
                selected={filters.engagement ?? []}
                options={projectOptions}
                onChange={ids => setFilters({ ...filters, engagement: ids })}
              />
              <MultiFilter
                title="Employee"
                selected={filters.staff ?? []}
                options={staffOptions}
                onChange={ids => setFilters({ ...filters, staff: ids })}
              />
              <MultiFilter
                title="Category"
                selected={filters.service ?? []}
                options={categoryOptions}
                onChange={ids => setFilters({ ...filters, service: ids })}
              />

              <MenuGroupLabel>Billable</MenuGroupLabel>
              {BILLABLE_OPTIONS.map(o => (
                <MenuItem
                  key={o.value}
                  selected={(filters.billable ?? "all") === o.value}
                  onClick={() => setFilters({ ...filters, billable: o.value })}
                >
                  {o.label}
                </MenuItem>
              ))}
            </div>
          )}
        </Dropdown>

        {activeCount > 0 && (
          <button
            type="button"
            onClick={() => setFilters({})}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-400 transition-colors hover:bg-white/10 hover:text-white"
          >
            <X className="h-3 w-3" /> Clear filters
          </button>
        )}

        {body.scope.type !== "firm" && (
          <button
            type="button"
            onClick={() => onChange({
              scope: { type: "firm", ids: [], filters: body.scope.filters },
            })}
            className="inline-flex items-center gap-1 rounded-lg border border-teal-400/30 bg-teal-400/15 px-2.5 py-1 text-xs font-semibold text-teal-200 transition-colors hover:bg-teal-400/25"
            title="Back to the whole firm"
          >
            {scopeLabel || body.scope.label || "Showing one item"}
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
    </div>
  );
}

function IconAction({
  icon: Icon, label, onClick, spinning,
}: {
  icon: typeof Printer; label: string; onClick: () => void; spinning?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={spinning}
      title={label}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1.5",
        "text-xs font-semibold text-slate-300 transition-colors hover:bg-white/10 hover:text-white",
        spinning && "cursor-not-allowed opacity-60",
      )}
    >
      <Icon className={cn("h-3.5 w-3.5", spinning && "animate-spin")} />
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}

function formatRelative(iso: string): string {
  try {
    const d = new Date(iso);
    const diffMin = Math.round((Date.now() - d.getTime()) / 60_000);
    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin} min ago`;
    const diffHr = Math.round(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ─── View tab ────────────────────────────────────────────────────────────────

function ViewTab({
  label, title, active, onClick,
}: { label: string; title: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative whitespace-nowrap rounded-t-lg px-3.5 py-2.5 text-sm",
        "transition-colors duration-150",
        "after:absolute after:inset-x-3 after:bottom-0 after:h-[2.5px] after:rounded-full",
        active
          ? "font-semibold text-white after:bg-teal-400"
          : "text-slate-400 hover:text-white after:bg-transparent hover:after:bg-white/20",
      )}
    >
      {label}
    </button>
  );
}

// ─── Period ──────────────────────────────────────────────────────────────────

function PeriodPicker({
  body, onChange,
}: { body: AnalyticsQueryBody; onChange: Props["onChange"] }) {
  const grouped = useMemo(() => {
    const out: Record<string, typeof TIME_OPTIONS> = {};
    for (const o of TIME_OPTIONS) (out[o.group] ??= []).push(o);
    return out;
  }, []);

  const custom = body.time.type === "absolute" && typeof body.time.value === "object"
    ? body.time.value
    : null;

  const setCustom = (start: string, end: string) => {
    // Guard here as well as in the parser: an end before its start produces a
    // window the backend rejects outright, and a 400 is a poor way to tell
    // someone they typed the dates the wrong way round.
    if (!start || !end || start > end) return;
    onChange({ time: { type: "absolute", value: { start, end } } });
  };

  return (
    <Dropdown
      caption="Period"
      label={
        <span className="inline-flex items-center gap-1.5">
          <Calendar className="h-3.5 w-3.5 text-slate-400" />
          {timeLabelFor(body.time)}
        </span>
      }
      widthClass="w-72"
    >
      {close => (
        <div className="max-h-[60vh] overflow-y-auto">
          {Object.entries(grouped).map(([group, opts]) => (
            <div key={group}>
              <MenuGroupLabel>{group}</MenuGroupLabel>
              {opts.map(o => (
                <MenuItem
                  key={o.value}
                  selected={body.time.type === "relative" && body.time.value === o.value}
                  onClick={() => {
                    onChange({ time: { type: "relative", value: o.value } });
                    close();
                  }}
                >
                  {o.label}
                </MenuItem>
              ))}
            </div>
          ))}

          <MenuGroupLabel>Custom</MenuGroupLabel>
          <div className="flex items-center gap-2 px-3 pb-2">
            <input
              type="date"
              aria-label="Start date"
              value={custom?.start ?? ""}
              onChange={e => setCustom(e.target.value, custom?.end ?? e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs"
            />
            <span className="text-xs text-slate-400">to</span>
            <input
              type="date"
              aria-label="End date"
              value={custom?.end ?? ""}
              onChange={e => setCustom(custom?.start ?? e.target.value, e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-xs"
            />
          </div>
        </div>
      )}
    </Dropdown>
  );
}

// ─── Multi-select filter ─────────────────────────────────────────────────────

interface Option { id: number; label: string }

function MultiFilter({
  title, options, selected, onChange,
}: {
  title: string;
  options: Option[];
  selected: number[];
  onChange: (ids: number[]) => void;
}) {
  // A dimension a firm has never populated (no projects, no task types) gets
  // no control at all. An empty dropdown invites the reader to wonder what
  // they did wrong.
  if (options.length === 0) return null;

  const toggle = (id: number) => {
    onChange(selected.includes(id)
      ? selected.filter(x => x !== id)
      : [...selected, id]);
  };

  return (
    <div>
      <MenuGroupLabel>
        {title}{selected.length > 0 && ` · ${selected.length} selected`}
      </MenuGroupLabel>
      <div className="max-h-44 overflow-y-auto">
        {options.map(o => (
          <label
            key={o.id}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            <input
              type="checkbox"
              checked={selected.includes(o.id)}
              onChange={() => toggle(o.id)}
              className="h-3.5 w-3.5 rounded border-slate-300 text-teal-600 focus:ring-teal-500"
            />
            <span className="truncate">{o.label}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

// ─── Option lists ────────────────────────────────────────────────────────────

function useClientOptions(enabled: boolean): Option[] {
  const { data } = useAnalyticsClients(enabled);
  return useMemo(
    () => (data ?? [])
      .filter(c => c.is_active)
      .map(c => ({ id: c.id, label: c.name }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    [data],
  );
}

function useStaffOptions(enabled: boolean): Option[] {
  const { data } = useAnalyticsStaff(enabled);
  return useMemo(
    () => (data ?? [])
      .filter(u => u.is_active)
      .map(u => ({ id: u.id, label: getUserDisplayName(u) }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    [data],
  );
}

function useProjectOptions(): Option[] {
  const { data } = useAnalyticsProjects(true);
  return useMemo(
    () => (data ?? [])
      .map(p => ({ id: p.id, label: p.name }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    [data],
  );
}

function useCategoryOptions(): Option[] {
  const { data } = useAnalyticsCategories(true);
  return useMemo(
    () => (data ?? [])
      .map(t => ({ id: t.id, label: t.name }))
      .sort((a, b) => a.label.localeCompare(b.label)),
    [data],
  );
}
