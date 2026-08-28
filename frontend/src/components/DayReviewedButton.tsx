// src/components/DayReviewedButton.tsx
/**
 * "Looks right" — the only way a person can say a day is correct without
 * changing anything.
 *
 * Editing a block already proves someone looked. A day where everything was
 * already correct leaves no trace at all, and is indistinguishable from a day
 * nobody opened. That ambiguity is why time cannot safely flow to a billing
 * system unattended, so this exists to remove it — and it only appears when
 * there is nothing else to go on.
 */
import { useCallback, useEffect, useState } from "react";
import { safeFetchJson, API_BASE } from "@/lib/api";
import { Check, CircleCheck } from "lucide-react";
import { cn } from "@/lib/design-system";

type State = {
  reviewed: boolean;
  explicit: boolean;
  derived_from_edits: boolean;
  /** Looked at once, but time has landed since. */
  stale: boolean;
};

export default function DayReviewedButton({
  date,
  hasTime,
  onChange,
}: {
  date: string;
  /** Nothing captured means nothing to vouch for. */
  hasTime: boolean;
  onChange?: (reviewed: boolean) => void;
}) {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setState(await safeFetchJson<State>(`${API_BASE}/daily/${date}/reviewed/`));
    } catch {
      setState(null);
    }
  }, [date]);

  useEffect(() => {
    if (hasTime) load();
  }, [load, hasTime]);

  if (!hasTime || !state) return null;

  // Already evidenced by their own edits — saying it twice adds nothing.
  if (state.derived_from_edits && !state.explicit) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
        <CircleCheck className="h-3.5 w-3.5 text-primary" />
        Reviewed
      </span>
    );
  }

  async function toggle() {
    if (busy) return;
    setBusy(true);
    const next = !state!.explicit;
    try {
      const r = await safeFetchJson<State>(`${API_BASE}/daily/${date}/reviewed/`, {
        method: next ? "POST" : "DELETE",
      });
      setState(r);
      onChange?.(r.reviewed);
    } catch {
      /* leave the previous state showing rather than a false confirmation */
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      title={
        state.stale
          ? "You checked this day, but more time has been captured since."
          : state.explicit
          ? "You marked this day as correct. Click to undo."
          : "Confirm this day is correct — nothing here needs changing."
      }
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12.5px] font-semibold transition-all disabled:opacity-50",
        state.explicit
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:border-primary/40 hover:bg-primary/5 hover:text-primary"
      )}
    >
      <Check className="h-3.5 w-3.5" />
      {state.explicit ? "Marked correct" : state.stale ? "Check again" : "Looks right"}
    </button>
  );
}
