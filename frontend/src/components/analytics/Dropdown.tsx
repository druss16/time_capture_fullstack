/**
 * A small anchored popover for the Analytics control bar.
 *
 * Deliberately local rather than a dependency: the bar needs three of these
 * (period, comparison, filters), they all behave identically, and the app has
 * no popover primitive to reuse. Closes on outside click and on Escape, and
 * traps nothing — these are menus, not dialogs, and a viewer who tabs away
 * should simply leave.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/design-system";

interface Props {
  /** What the closed button shows. */
  label: ReactNode;
  /** Small grey word above the value, e.g. "Period". */
  caption?: string;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
  /** Renders the trigger in the active/teal treatment. */
  active?: boolean;
  widthClass?: string;
}

export default function Dropdown({
  label, caption, children, align = "left", active = false,
  widthClass = "w-72",
}: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-haspopup="true"
        className={cn(
          "flex items-center gap-2 rounded-xl border px-3 py-2 text-left transition-colors",
          active
            ? "border-teal-300 bg-teal-50/70 text-teal-900"
            : "border-slate-200 bg-white text-slate-800 hover:border-slate-300",
        )}
      >
        <span className="min-w-0">
          {caption && (
            <span className="block text-[10px] uppercase tracking-wider text-slate-400 leading-none mb-0.5">
              {caption}
            </span>
          )}
          <span className="block text-sm font-medium truncate">{label}</span>
        </span>
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 text-slate-400 transition-transform",
                        open && "rotate-180")}
        />
      </button>

      {open && (
        <div
          className={cn(
            "absolute z-30 mt-2 rounded-xl border border-slate-200 bg-white p-2 shadow-xl shadow-slate-900/10",
            widthClass,
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

export function MenuItem({
  children, selected, onClick,
}: {
  children: ReactNode; selected?: boolean; onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg px-3 py-2 text-left text-sm transition-colors",
        selected
          ? "bg-teal-50 font-medium text-teal-900"
          : "text-slate-700 hover:bg-slate-50",
      )}
    >
      {children}
    </button>
  );
}

export function MenuGroupLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
      {children}
    </p>
  );
}
