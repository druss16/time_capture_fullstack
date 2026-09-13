/**
 * A section whose children are alternatives rather than a sequence.
 *
 * "Where time goes" is one question asked of four dimensions — client,
 * project, category, billable. Stacking four charts makes the viewer scroll
 * between readings that are meant to be compared, and implies a narrative
 * order that isn't there. Tabs say plainly: same question, pick a lens.
 *
 * Tab labels come from each child's own title, so the backend decides what the
 * tabs are by deciding what it sends.
 */
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/design-system";
import type { Section as SectionPayload, SectionChild } from "@/lib/analytics_v2/types";
import SectionHeader from "@/components/primitives/SectionHeader";

interface Props {
  section: SectionPayload;
  renderChild: (child: SectionChild) => ReactNode;
}

function titleOf(child: SectionChild): string {
  return "title" in child && child.title ? child.title : child.id;
}

export default function TabbedSection({ section, renderChild }: Props) {
  const [index, setIndex] = useState(0);
  const children = section.children ?? [];
  if (children.length === 0) return null;

  // One child is not a choice. Render it plainly rather than drawing a tab
  // strip with a single tab in it.
  if (children.length === 1) {
    return (
      <section className="space-y-3">
        {section.title && <SectionHeader title={section.title} />}
        {renderChild(children[0])}
      </section>
    );
  }

  const active = children[Math.min(index, children.length - 1)];

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {section.title ? <SectionHeader title={section.title} /> : <span />}
        <div
          role="tablist"
          aria-label={section.title || "View"}
          className="flex flex-wrap gap-1 rounded-xl bg-slate-100/80 p-1 print:hidden"
        >
          {children.map((child, i) => (
            <button
              key={child.id}
              type="button"
              role="tab"
              aria-selected={i === index}
              onClick={() => setIndex(i)}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                i === index
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-800",
              )}
            >
              {titleOf(child)}
            </button>
          ))}
        </div>
      </div>

      {renderChild(active)}

      {/* Print gets every tab: a printed dashboard cannot be clicked, and a
          reader holding the page should not be missing three of four views. */}
      <div className="hidden print:block print:space-y-4">
        {children.filter((_, i) => i !== index).map(renderChild)}
      </div>
    </section>
  );
}
