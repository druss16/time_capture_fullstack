import React, { useState } from "react";
import { Check, Plus, X, Sparkles } from "lucide-react";
import { cn } from "@/lib/design-system";

export interface AliasSuggestion {
  client_id: number;
  client_name: string;
  alias: string;
}

interface Props {
  suggestion: AliasSuggestion;
  /** Persist the (possibly edited) alias. Parent owns the fetch + toast. */
  onAdd: (alias: string) => Promise<void>;
  onDismiss: () => void;
  className?: string;
}

/**
 * Post-correction "remember this name" prompt. Shown right after a reviewer
 * moves a block to a client whose title carried a distinctive name that didn't
 * already match. One tap teaches the alias so the same title auto-classifies
 * next time. "Edit…" lets them trim it before saving.
 */
export function AliasSuggestionCard({ suggestion, onAdd, onDismiss, className }: Props) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(suggestion.alias);
  const [busy, setBusy] = useState(false);

  const add = async () => {
    const alias = value.trim();
    if (!alias || busy) return;
    setBusy(true);
    try {
      await onAdd(alias);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={cn(
        "bg-emerald-50 border border-emerald-200 rounded-xl px-3.5 py-3",
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        <Sparkles className="w-[18px] h-[18px] text-emerald-600 mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] text-emerald-900 leading-snug">
            Remember{" "}
            <span className="font-semibold">&ldquo;{suggestion.alias}&rdquo;</span> for{" "}
            <span className="font-semibold">{suggestion.client_name}</span>?
          </p>
          <p className="text-[11px] text-emerald-600 mt-0.5">
            Next time this title shows up it'll classify automatically.
          </p>
        </div>
      </div>

      {editing && (
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") add();
            if (e.key === "Escape") setEditing(false);
          }}
          className="mt-2.5 ml-[28px] w-[calc(100%-28px)] border border-emerald-200 rounded-lg px-2.5 py-1.5 text-[13px] font-medium focus:border-primary focus:ring-1 focus:ring-primary/20 outline-none"
        />
      )}

      <div className="flex items-center gap-2 mt-3 ml-[28px]">
        <button
          onClick={add}
          disabled={busy}
          className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-white bg-primary rounded-lg px-3.5 py-1.5 hover:opacity-90 disabled:opacity-50"
        >
          {busy ? <Check className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
          Add alias
        </button>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="text-[12px] font-medium text-slate-500 border border-slate-300 rounded-lg px-3 py-1.5 hover:bg-slate-100"
          >
            Edit&hellip;
          </button>
        )}
        <button
          onClick={onDismiss}
          className="inline-flex items-center gap-1 text-[12px] font-medium text-slate-400 rounded-lg px-2 py-1.5 hover:text-slate-600"
        >
          <X className="w-3.5 h-3.5" />
          Dismiss
        </button>
      </div>
    </div>
  );
}
