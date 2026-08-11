/**
 * EmptyStateInvoiceless — friendly empty state for firms like TL Wall that
 * don't push invoices into TimeTracker. Used by the Realization lens
 * when the meta flag tells us this firm has zero invoices.
 */
import { FileX, ExternalLink } from "lucide-react";

export default function EmptyStateInvoiceless({
  metric = "realization",
}: {
  metric?: "realization" | "trends";
}) {
  const messages = {
    realization: {
      title: "Realization needs invoice data",
      body: "Your firm logs time in TimeTracker but invoices live elsewhere — so we can't compute billing realization. Connect QuickBooks or Xero to pull your invoices in and unlock this lens.",
    },
    trends: {
      title: "No invoice trend yet",
      body: "Monthly revenue trend is calculated from invoice records. Connect your billing software and invoices flow in automatically — this chart fills in from there.",
    },
  } as const;

  const m = messages[metric];

  return (
    <div className="rounded-[15px] border border-border/70 bg-white p-10 text-center shadow-[0_8px_22px_-16px_rgba(16,27,46,0.28)]">
      <FileX className="h-10 w-10 text-slate-300 mx-auto mb-3" />
      <h3 className="text-base font-semibold text-slate-900 mb-1.5">{m.title}</h3>
      <p className="text-sm text-slate-600 max-w-md mx-auto leading-relaxed">{m.body}</p>
      <a
        href="/settings?tab=integrations"
        className="inline-flex items-center gap-1.5 mt-4 rounded-lg border border-primary/30 bg-primary/[0.06] px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/10 transition-colors"
      >
        <span>Connect billing software</span>
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  );
}
