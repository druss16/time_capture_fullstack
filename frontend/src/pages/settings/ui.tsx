// src/pages/settings/ui.tsx
// Shared UI primitives for the Settings tabs — the "Lightning" look that
// Daily Review / Timesheet / Economics share. Use these instead of hand-rolling
// cards, headers, and inputs so every tab stays visually consistent.
import type { ReactNode } from 'react';
import { cn } from '@/lib/design-system';

// ── Shared class tokens ─────────────────────────────────────────────────────
// Import these where a bare <input>/<button> is needed so styling stays in sync.

/** Standard text/number/email input. */
export const inputClass =
  'w-full px-3 py-2 border border-border/60 rounded-lg text-sm font-medium text-slate-900 ' +
  'focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white transition-all';

/** Uppercase field label above an input. */
export const labelClass =
  'block text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5';

/** Primary (filled) action button. */
export const primaryBtnClass =
  'inline-flex items-center gap-1.5 px-4 py-2 bg-primary text-white rounded-lg text-sm font-semibold ' +
  'hover:opacity-90 disabled:opacity-50 transition-all';

/** Secondary (outlined) action button. */
export const secondaryBtnClass =
  'inline-flex items-center gap-1.5 px-4 py-2 border border-border/60 rounded-lg text-sm font-semibold ' +
  'text-slate-700 hover:bg-slate-50 transition-all';

// ── Page shell ──────────────────────────────────────────────────────────────

interface SettingsPageProps {
  title: string;
  subtitle?: ReactNode;
  /** Right-aligned controls in the title row (e.g. Refresh / Edit / Add). */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Top-level wrapper for a Settings tab body. Applies the Inter font and renders
 * the standard page title + subtitle row with optional right-aligned actions.
 */
export function SettingsPage({ title, subtitle, actions, children }: SettingsPageProps) {
  return (
    <div style={{ fontFamily: '"Inter", sans-serif' }}>
      <div className="flex items-start justify-between gap-4 mb-5">
        <div className="min-w-0">
          <h2 className="text-[20px] font-bold tracking-[-0.01em] text-slate-900">{title}</h2>
          {subtitle && (
            <p className="text-[12.5px] text-slate-500 mt-1 leading-snug">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

// ── Section header (icon + title + sub) ──────────────────────────────────────

interface SectionHeaderProps {
  icon?: ReactNode;
  title: string;
  sub?: string | undefined;
  /** Right-aligned controls in the header row. */
  actions?: ReactNode;
  className?: string;
}

/** Header used inside a SettingsSection (or standalone above a table). */
export function SectionHeader({ icon, title, sub, actions, className }: SectionHeaderProps) {
  return (
    <div className={cn('flex items-start justify-between gap-3 mb-4', className)}>
      <div className="min-w-0">
        <p className="text-[13px] font-bold tracking-[-0.01em] text-slate-900 flex items-center gap-1.5">
          {icon && <span className="text-slate-300">{icon}</span>}
          {title}
        </p>
        {sub && <p className="text-[12px] text-slate-400 mt-0.5 leading-snug">{sub}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

// ── Section card ─────────────────────────────────────────────────────────────

interface SettingsSectionProps {
  icon?: ReactNode;
  title?: string;
  sub?: string;
  /** Right-aligned controls in the header row. */
  actions?: ReactNode;
  /** Soft mint tint for a "primary" section (matches Economics firm-defaults). */
  tint?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * A rounded card section. Pass title/sub/icon to render a SectionHeader inside;
 * omit them to use it as a bare card. `tint` applies the mint background.
 */
export function SettingsSection({
  icon, title, sub, actions, tint, className, children,
}: SettingsSectionProps) {
  return (
    <div
      className={cn(
        'rounded-2xl border border-slate-200/70 p-4 sm:p-5',
        tint && 'bg-[#f7faf9]',
        className,
      )}
    >
      {(title || actions) && (
        <SectionHeader icon={icon} title={title ?? ''} sub={sub} actions={actions} />
      )}
      {children}
    </div>
  );
}
