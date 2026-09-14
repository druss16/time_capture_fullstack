/**
 * An anchored popover for the Analytics control bar.
 *
 * The panel renders in a PORTAL on document.body, positioned with `fixed`
 * against the trigger's measured rect — it is not a child of the trigger.
 *
 * That is not premature engineering. The view-tab row is `overflow-x-auto` so
 * the tabs can scroll on a narrow screen, and per CSS spec `overflow-x: auto`
 * forces `overflow-y` from `visible` to `auto`. An absolutely-positioned child
 * is therefore clipped on BOTH axes: the "More" menu opened, rendered all
 * seven of its items into the DOM at y=114, and was cut off by a container
 * ending at y=106. The chevron flipped and nothing appeared. A portal is the
 * fix that cannot regress if some future ancestor gains a scrollbar.
 *
 * Closes on outside click, on Escape, and on scroll/resize (a fixed panel
 * would otherwise drift away from a trigger that has moved).
 */
import {
  useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/design-system";

interface Props {
  label: ReactNode;
  caption?: string | undefined;
  children: (close: () => void) => ReactNode;
  align?: "left" | "right";
  active?: boolean;
  widthClass?: string;
}

const GAP = 8;        // space between trigger and panel
const MARGIN = 12;    // keep the panel this far inside the viewport

export default function Dropdown({
  label, caption, children, align = "left", active = false,
  widthClass = "w-72",
}: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; maxHeight: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const place = useCallback(() => {
    const t = triggerRef.current;
    if (!t) return;
    const r = t.getBoundingClientRect();
    const panelWidth = panelRef.current?.offsetWidth ?? 288;

    let left = align === "right" ? r.right - panelWidth : r.left;
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - panelWidth - MARGIN));

    setPos({
      top: r.bottom + GAP,
      left,
      // Never taller than the space below the trigger.
      maxHeight: Math.max(160, window.innerHeight - r.bottom - GAP - MARGIN),
    });
  }, [align]);

  useLayoutEffect(() => { if (open) place(); }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (triggerRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    // `true` so a scroll inside any ancestor repositions, not just the window.
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-haspopup="true"
        className={cn(
          // The trigger sits on the dark masthead; the PANEL stays light,
          // because a menu of twelve items is easier to read on white.
          "group flex items-center gap-2 rounded-xl border px-3 py-1.5 text-left",
          "transition-[background-color,border-color] duration-150",
          active
            ? "border-teal-400/40 bg-teal-400/15 text-teal-100"
            : "border-white/10 bg-white/5 text-slate-200 hover:border-white/20 hover:bg-white/10",
        )}
      >
        <span className="min-w-0">
          {caption && (
            <span className="mb-0.5 block text-[9.5px] font-semibold uppercase leading-none tracking-[0.12em] text-slate-400">
              {caption}
            </span>
          )}
          <span className="block truncate text-sm font-medium">{label}</span>
        </span>
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 text-slate-400 transition-transform duration-150",
                        open && "rotate-180")}
        />
      </button>

      {open && pos && createPortal(
        <div
          ref={panelRef}
          style={{ top: pos.top, left: pos.left, maxHeight: pos.maxHeight }}
          className={cn(
            "fixed z-[60] overflow-y-auto overscroll-contain rounded-2xl border border-slate-200/80",
            "bg-white/95 p-1.5 backdrop-blur-xl",
            "shadow-[0_1px_2px_rgba(16,27,46,0.04),0_12px_32px_-8px_rgba(16,27,46,0.18)]",
            widthClass,
          )}
        >
          {children(() => setOpen(false))}
        </div>,
        document.body,
      )}
    </>
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
        "w-full rounded-xl px-3 py-2 text-left text-sm transition-colors duration-100",
        selected
          ? "bg-teal-50 font-medium text-teal-900"
          : "text-slate-700 hover:bg-slate-100/70",
      )}
    >
      {children}
    </button>
  );
}

export function MenuGroupLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-3 pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
      {children}
    </p>
  );
}
