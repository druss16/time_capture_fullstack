/**
 * Active filters, repeated on every card.
 *
 * The chips under the page title say what narrows the view, but a card
 * scrolled to, screenshotted or printed on its own loses that. A table of
 * "High Efficiency Clients" filtered to one employee reads like the firm's
 * numbers when it is one person's. Each chart and table header carries this
 * compact, read-only summary so no card can be read out of context.
 *
 * Fed by a context the dashboard provides; anywhere else these primitives
 * render (no provider) it shows nothing.
 */
import { createContext, useContext } from "react";
import { Filter } from "lucide-react";

export const ActiveFilterContext = createContext<string[]>([]);

export default function FilterBadge() {
  const labels = useContext(ActiveFilterContext);
  if (!labels.length) return null;
  const text = labels.join(" · ");
  return (
    <span
      className="inline-flex max-w-full items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-800"
      title={`Filtered by ${text}`}
    >
      <Filter className="h-3 w-3 shrink-0" />
      <span className="truncate">{text}</span>
    </span>
  );
}
