// src/pages/onboard/shared.tsx — small building blocks for the Onboarding Console.
import { useEffect, useState, type ReactNode } from "react";
import { Check, Copy, Download, X } from "lucide-react";
import { cn } from "@/lib/design-system";

export { inputClass, labelClass, primaryBtnClass, secondaryBtnClass } from "@/pages/settings/ui";

export const VERTICALS: { value: string; label: string; defaultPath: string }[] = [
  { value: "cpa", label: "CPA / Accounting", defaultPath: "windows_gpo" },
  { value: "legal", label: "Law firm", defaultPath: "windows_gpo" },
  { value: "marketing", label: "Marketing agency", defaultPath: "mac_hand" },
  { value: "ai_consulting", label: "AI / Tech consulting", defaultPath: "windows_hand" },
  { value: "general", label: "General professional services", defaultPath: "windows_hand" },
];

export const INSTALL_PATHS: { value: string; label: string }[] = [
  { value: "windows_gpo", label: "Windows — GPO logon script" },
  { value: "windows_hand", label: "Windows — by hand" },
  { value: "mac_hand", label: "Mac — by hand" },
  { value: "mac_mdm", label: "Mac — MDM" },
];

export const WHO_LABEL: Record<string, string> = {
  us: "Mavops", firm: "The firm", firm_it: "Firm's IT", system: "Automatic",
};

export function Modal({ title, subtitle, onClose, children, wide }: {
  title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 sm:p-8"
         onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title}
           className={cn("w-full rounded-2xl bg-white shadow-xl", wide ? "max-w-5xl" : "max-w-2xl")}>
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-900">{title}</h2>
            {subtitle && <div className="mt-0.5 text-sm text-slate-500">{subtitle}</div>}
          </div>
          <button onClick={onClose} aria-label="Close"
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

export function Pill({ tone = "slate", children }: { tone?: "slate" | "green" | "amber" | "red" | "blue"; children: ReactNode }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-800",
    red: "bg-red-50 text-red-700",
    blue: "bg-sky-50 text-sky-700",
  };
  return <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{message}</div>;
}

/** The provisioning command's own report, verbatim. */
export function OutputLog({ text, errors }: { text: string; errors?: string }) {
  if (!text && !errors) return null;
  return (
    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-100">
      {text}
      {errors && <span className="text-red-300">{"\n"}{errors}</span>}
    </pre>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button"
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ }
      }}
      className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50">
      {done ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
      {done ? "Copied" : label}
    </button>
  );
}

export function downloadText(name: string, content: string) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function DownloadButton({ name, content }: { name: string; content: string }) {
  return (
    <button type="button" onClick={() => downloadText(name, content)}
      className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50">
      <Download className="h-3.5 w-3.5" /> Download
    </button>
  );
}

export function fmtDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function daysSince(iso: string) {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}
