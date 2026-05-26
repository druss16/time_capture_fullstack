/**
 * InsightCard — Pulse "needs attention" cards.
 *
 * Severity drives color treatment. Source tag (rule/threshold/ai) is shown subtly.
 * Drilldown click takes the user to the relevant lens at the relevant scope.
 */
import { AlertTriangle, AlertCircle, CheckCircle2, Info, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/design-system";
import type { InsightCardPayload } from "@/lib/analytics_v2/types";

interface Props {
  card: InsightCardPayload;
  onDrilldown?: (drilldown: NonNullable<InsightCardPayload["drilldown"]>) => void;
  onDismiss?: (id: string) => void;
}

const SEVERITY_CONFIG = {
  bad: {
    icon: AlertTriangle,
    iconClass: "text-rose-600",
    borderClass: "border-rose-200",
    bgClass: "bg-rose-50/40",
    label: "Needs attention",
    labelClass: "text-rose-700 bg-rose-100/80",
  },
  watch: {
    icon: AlertCircle,
    iconClass: "text-amber-600",
    borderClass: "border-amber-200",
    bgClass: "bg-amber-50/40",
    label: "Watch",
    labelClass: "text-amber-800 bg-amber-100/80",
  },
  good: {
    icon: CheckCircle2,
    iconClass: "text-emerald-600",
    borderClass: "border-emerald-200",
    bgClass: "bg-emerald-50/40",
    label: "Good news",
    labelClass: "text-emerald-700 bg-emerald-100/80",
  },
  info: {
    icon: Info,
    iconClass: "text-slate-600",
    borderClass: "border-slate-200",
    bgClass: "bg-slate-50/40",
    label: "Info",
    labelClass: "text-slate-700 bg-slate-100/80",
  },
} as const;

export default function InsightCard({ card, onDrilldown, onDismiss }: Props) {
  const cfg = SEVERITY_CONFIG[card.severity];
  const Icon = cfg.icon;
  const interactive = !!(card.drilldown && onDrilldown);

  return (
    <div className={cn(
      "rounded-2xl border p-4 transition-all relative group",
      cfg.borderClass, cfg.bgClass,
      interactive && "hover:shadow-md cursor-pointer",
    )}
      onClick={interactive
        ? () => card.drilldown && onDrilldown && onDrilldown(card.drilldown)
        : undefined}
    >
      <div className="flex items-start gap-3">
        <Icon className={cn("h-5 w-5 shrink-0 mt-0.5", cfg.iconClass)} />

        <div className="flex-1 min-w-0">
          {/* Severity tag + source */}
          <div className="flex items-center gap-2 mb-1.5">
            <span className={cn(
              "text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full",
              cfg.labelClass,
            )}>
              {cfg.label}
            </span>
            {card.source !== "threshold" && (
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-medium">
                {card.source === "ai" ? "AI" : "Custom rule"}
              </span>
            )}
          </div>

          {/* Headline */}
          <h4 className="text-sm font-semibold text-slate-900 leading-tight">
            {card.headline}
          </h4>

          {/* Body */}
          {card.body && (
            <p className="mt-1.5 text-xs text-slate-600 leading-relaxed">
              {card.body}
            </p>
          )}

          {/* Evidence chips */}
          {card.evidence?.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-2">
              {card.evidence.map((e, i) => (
                <div key={i} className="inline-flex items-center gap-1.5 text-[11px] bg-white/70 border border-slate-200/60 rounded-md px-2 py-1">
                  <span className="text-slate-500">{e.label}:</span>
                  <span className="font-medium text-slate-800">{e.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Action arrow on hover */}
        {interactive && (
          <ChevronRight className="h-4 w-4 text-slate-400 group-hover:text-slate-700 mt-1 shrink-0" />
        )}
      </div>

      {/* Dismiss button (top-right, appears on hover) */}
      {card.dismissible && onDismiss && (
        <button
          onClick={(e) => { e.stopPropagation(); onDismiss(card.id); }}
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-white/80"
          title="Dismiss for 7 days"
        >
          <X className="h-3 w-3 text-slate-500" />
        </button>
      )}
    </div>
  );
}
