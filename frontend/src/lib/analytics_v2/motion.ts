/**
 * Motion for the analytics dashboard.
 *
 * Two effects, both deliberately small: figures count up on arrival, and cards
 * fade up in sequence. The point is to make the page feel like it is reporting
 * something rather than that it was already sitting there — a number that
 * lands is read; a number that was always on screen is scrolled past.
 *
 * Both are OFF for anyone who asked for reduced motion, and both are strictly
 * cosmetic: the final value is the real value, rendered immediately if the
 * animation never runs. Nothing here gates the data.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";

/** Does this viewer want motion at all? */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

const DURATION_MS = 650;

/** Ease-out cubic: fast first, settling at the end. */
const ease = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * Count from 0 to `value` once, on mount and whenever `value` changes.
 *
 * Returns `value` unchanged when motion is reduced, when the figure is not a
 * finite number, or once the run finishes — so the displayed number is always
 * exactly what was passed in by the time it settles.
 */
export function useCountUp(value: number | null | undefined): number | null | undefined {
  const reduced = usePrefersReducedMotion();
  const [shown, setShown] = useState(value);
  const frame = useRef<number>();
  const safety = useRef<ReturnType<typeof setTimeout>>();

  // useLayoutEffect, not useEffect: the starting value has to be in place
  // BEFORE the browser paints. With useEffect the tile paints once at the
  // final figure and then snaps back to zero to begin — a visible jump
  // backwards on every load.
  useLayoutEffect(() => {
    if (reduced || typeof value !== "number" || !isFinite(value)) {
      setShown(value);
      return;
    }

    let started = false;
    setShown(0);

    const tick = (now: number) => {
      started = true;
      const t = Math.min(1, (now - start) / DURATION_MS);
      if (t >= 1) {
        setShown(value);            // land on the exact value, never a lerp
        return;
      }
      setShown(value * ease(t));
      frame.current = requestAnimationFrame(tick);
    };

    const start = performance.now();
    frame.current = requestAnimationFrame(tick);

    // requestAnimationFrame does not fire in a hidden tab, a background
    // window, or a screenshot/thumbnail renderer. Without this the figure
    // would sit at zero in exactly those cases — a dashboard reading 0h
    // because nobody was looking at it. If no frame has run shortly after
    // mount, skip the animation and show the real number.
    safety.current = setTimeout(() => {
      if (!started) setShown(value);
    }, 120);

    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      if (safety.current) clearTimeout(safety.current);
    };
  }, [value, reduced]);

  return shown;
}

/**
 * Inline style for a card that fades up in sequence.
 *
 * `index` is its position in the page; the stagger is capped so a long page
 * does not keep animating after the viewer has started reading. Unlike the
 * count-up this is pure CSS, so a hidden tab simply arrives already-finished
 * rather than needing a fallback.
 */
export function stagger(index: number, reduced: boolean): React.CSSProperties {
  if (reduced) return {};
  return {
    animation: "tt-rise 420ms cubic-bezier(0.22, 1, 0.36, 1) both",
    animationDelay: `${Math.min(index, 8) * 45}ms`,
  };
}
