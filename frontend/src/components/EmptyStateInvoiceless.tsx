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
      body: "Your firm logs time in TimeTracker but invoices live elsewhere — so we can't compute billing realization. Connect your invoice source to unlock this lens.",
    },
    trends: {
      title: "No invoice trend yet",
      body: "Monthly revenue trend is calculated from invoice records. Once invoices are flowing through TimeTracker, this chart fills in automatically.",
    },
  } as const;

  const m = messages[metric];

  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-10 text-center">
      <FileX className="h-10 w-10 text-slate-300 mx-auto mb-3" />
      <h3 className="text-base font-semibold text-slate-900 mb-1.5">{m.title}</h3>
      <p className="text-sm text-slate-600 max-w-md mx-auto leading-relaxed">{m.body}</p>
      <a
        href="/settings"
        className="inline-flex items-center gap-1.5 mt-4 text-xs font-medium text-amber-700 hover:text-amber-900 transition-colors"
      >
        <span>Configure invoice import</span>
        <ExternalLink className="h-3 w-3" />
      </a>
    </div>
  );
}
