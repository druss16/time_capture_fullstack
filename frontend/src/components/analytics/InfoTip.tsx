/**
 * The little ⓘ next to a metric label, and the explanation it reveals.
 *
 * The panel renders in a PORTAL, positioned fixed against the icon.
 *
 * It has to. The previous version was `absolute … z-10` inside the tile, and
 * a tile is `relative` — so the tooltip lived in that tile's stacking context
 * and `z-10` only ever competed with the tile's own children. Any card later
 * in DOM order painted straight over it, which is exactly what happened: the
 * Billable Hours tooltip was sliced in half by the Utilization card beside it.
 * The same markup in the table header had it worse, sitting inside an
 * `overflow-x-auto` container that clips on both axes.
 *
 * A portal removes the whole class of problem: no ancestor's overflow, z-index
 * or transform can reach it.
 */
import {
  useCallback, useEffect, useId, useLayoutEffect, useRef, useState,
} from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import { cn } from "@/lib/design-system";

interface Props {
  text: string;
  /** Matches the icon to the surrounding type size. */
  size?: "sm" | "md";
  className?: string;
}

const WIDTH = 288;   // w-72
const GAP = 8;
const MARGIN = 12;

export default function InfoTip({ text, size = "sm", className }: Props) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const anchor = useRef<HTMLSpanElement>(null);
  const id = useId();

  const place = useCallback(() => {
    const el = anchor.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    // Prefer the right of the icon; flip left when that would run off screen.
    let left = r.right + GAP;
    if (left + WIDTH > window.innerWidth - MARGIN) {
      left = Math.max(MARGIN, r.left - GAP - WIDTH);
    }
    setPos({ top: Math.max(MARGIN, r.top), left });
  }, []);

  useLayoutEffect(() => { if (open) place(); }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    // `true` so scrolling any ancestor repositions, not just the window.
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open, place]);

  const dim = size === "md" ? "h-3.5 w-3.5" : "h-3 w-3";

  return (
    <span
      ref={anchor}
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        // Focusable so the explanation is reachable without a mouse — the old
        // hover-only span was invisible to keyboard users entirely.
        aria-describedby={open ? id : undefined}
        aria-label="What this measures"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={e => { e.stopPropagation(); setOpen(o => !o); }}
        className="inline-flex cursor-help items-center rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40"
      >
        <Info className={cn(dim, "text-slate-400 transition-colors hover:text-slate-600")} />
      </button>

      {open && pos && createPortal(
        <span
          id={id}
          role="tooltip"
          style={{ top: pos.top, left: pos.left, width: WIDTH }}
          className={cn(
            "pointer-events-none fixed z-[80] rounded-xl bg-slate-900/95 p-3",
            "text-[11px] font-normal normal-case leading-relaxed tracking-normal text-white",
            "whitespace-pre-line shadow-[0_8px_30px_-8px_rgba(2,6,23,0.6)] backdrop-blur-sm",
          )}
        >
          {text}
        </span>,
        document.body,
      )}
    </span>
  );
}
