/**
 * Sidebar — scope / lens / time / compare picker.
 *
 * Pulls available capabilities from /api/analytics/permissions/ to know
 * what to show (owner sees firm, manager sees team, etc.).
 *
 * State flows: user clicks → onChange fires with new query body →
 * parent updates URL → URL re-parses → sidebar re-renders.
 *
 * Client/staff pickers are stubs for v2.0 — they show a "Coming soon" label.
 * Full multi-select pickers ship in v2.1 with the saved views feature.
 */
import { Building2, Briefcase, User, Layers, FilePieChart, BarChart3, Clock4, TrendingUp, Sparkles } from "lucide-react";
import { cn } from "@/lib/design-system";
import { useAnalyticsPermissions } from "@/hooks/useAnalyticsQuery";
import {
  LENS_OPTIONS, TIME_OPTIONS, COMPARE_OPTIONS,
} from "@/lib/analytics_v2/urlState";
import type { AnalyticsQueryBody, LensKey, ScopeType } from "@/lib/analytics_v2/types";

interface Props {
  body: AnalyticsQueryBody;
  onChange: (next: Partial<AnalyticsQueryBody>) => void;
}

const SCOPE_ICONS: Record<ScopeType, any> = {
  firm: Building2,
  client: Briefcase,
  staff: User,
  service: Layers,
  engagement: Layers,
  composite: Layers,
};

const LENS_ICONS: Record<LensKey, any> = {
  pulse: Sparkles,
  profitability: FilePieChart,
  realization: TrendingUp,
  utilization: Clock4,
  wip: BarChart3,
  trends: TrendingUp,
};

export default function Sidebar({ body, onChange }: Props) {
  const { data: perms } = useAnalyticsPermissions();
  const availableLenses = new Set(perms?.capabilities?.available_lenses ?? ["pulse", "profitability", "realization", "utilization", "wip"]);
  const canFirm = perms?.capabilities?.can_firm ?? false;

  return (
    <aside className="w-64 shrink-0 border-r border-slate-200/80 bg-slate-50/30 px-4 py-6 space-y-6 overflow-y-auto">
      {/* Scope section */}
      <section>
        <SectionLabel>Scope</SectionLabel>
        <div className="space-y-1">
          <ScopeOption
            label="Whole firm"
            icon={SCOPE_ICONS.firm}
            active={body.scope.type === "firm"}
            disabled={!canFirm}
            onClick={() => onChange({ scope: { type: "firm", ids: [] } })}
          />
          {/* Client / staff pickers will land in v2.1 */}
          <ScopeOption
            label="By client"
            icon={SCOPE_ICONS.client}
            active={body.scope.type === "client"}
            disabled
            comingSoon
            onClick={() => {}}
          />
          <ScopeOption
            label="By staff"
            icon={SCOPE_ICONS.staff}
            active={body.scope.type === "staff"}
            disabled
            comingSoon
            onClick={() => {}}
          />
        </div>
      </section>

      {/* Lens section */}
      <section>
        <SectionLabel>Lens</SectionLabel>
        <div className="space-y-1">
          {LENS_OPTIONS.map(opt => {
            const Icon = LENS_ICONS[opt.value];
            const enabled = availableLenses.has(opt.value);
            return (
              <LensOption
                key={opt.value}
                label={opt.label}
                description={opt.description}
                icon={Icon}
                active={body.lens === opt.value}
                disabled={!enabled}
                onClick={() => onChange({ lens: opt.value })}
              />
            );
          })}
        </div>
      </section>

      {/* Time section */}
      <section>
        <SectionLabel>Time period</SectionLabel>
        <select
          value={typeof body.time.value === "string" ? body.time.value : "this_quarter"}
          onChange={(e) => onChange({ time: { type: "relative", value: e.target.value } })}
          className="w-full text-sm rounded-lg border border-slate-200 bg-white px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50"
        >
          {Object.entries(groupByKey(TIME_OPTIONS, "group")).map(([group, opts]) => (
            <optgroup key={group} label={group}>
              {opts.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </section>

      {/* Compare section */}
      <section>
        <SectionLabel>Compare</SectionLabel>
        <select
          value={body.compare?.value as string ?? ""}
          onChange={(e) => onChange({
            compare: e.target.value
              ? { type: "relative", value: e.target.value }
              : null,
          })}
          className="w-full text-sm rounded-lg border border-slate-200 bg-white px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50"
        >
          <option value="">No comparison</option>
          {COMPARE_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </section>
    </aside>
  );
}

// ─── Subcomponents ───────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[10px] uppercase tracking-wider font-semibold text-slate-500 mb-2">
      {children}
    </h3>
  );
}

function ScopeOption({
  label, icon: Icon, active, disabled, comingSoon, onClick,
}: {
  label: string;
  icon: any;
  active: boolean;
  disabled?: boolean;
  comingSoon?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "w-full flex items-center gap-2 text-sm rounded-lg px-2.5 py-1.5 text-left transition-colors",
        active && "bg-amber-100/70 text-amber-900 font-medium",
        !active && !disabled && "text-slate-700 hover:bg-white",
        disabled && "text-slate-400 cursor-not-allowed",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="flex-1">{label}</span>
      {comingSoon && (
        <span className="text-[10px] text-slate-400 uppercase tracking-wider">Soon</span>
      )}
    </button>
  );
}

function LensOption({
  label, description, icon: Icon, active, disabled, onClick,
}: {
  label: string;
  description: string;
  icon: any;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={description}
      className={cn(
        "w-full flex items-start gap-2 text-sm rounded-lg px-2.5 py-1.5 text-left transition-colors",
        active && "bg-slate-900 text-white",
        !active && !disabled && "text-slate-700 hover:bg-white",
        disabled && "text-slate-400 cursor-not-allowed",
      )}
    >
      <Icon className={cn("h-4 w-4 shrink-0 mt-0.5", active && "text-amber-400")} />
      <div className="flex-1">
        <div className={cn("font-medium", active && "text-white")}>{label}</div>
        <div className={cn(
          "text-[10px] leading-tight mt-0.5",
          active ? "text-slate-300" : "text-slate-500",
        )}>
          {description}{disabled && " (Executive)"}
        </div>
      </div>
    </button>
  );
}

function groupByKey<T extends Record<string, any>>(arr: T[], key: keyof T): Record<string, T[]> {
  return arr.reduce((acc, item) => {
    const k = item[key] as string;
    if (!acc[k]) acc[k] = [];
    acc[k].push(item);
    return acc;
  }, {} as Record<string, T[]>);
}
