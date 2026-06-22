/**
 * BlockRow.tsx — v1.3.60 Phase 2 (replaces BlockCard.tsx)
 *
 * Compact one-line row for the Categorize tab. Replaces the ~500px card with
 * a ~64px row. Eight rows fit on one screen instead of one.
 *
 * Behavior:
 *   - Pre-fills client + category from block.suggestions[0] (set by backend
 *     classifier proposal + FIX 6 + heuristic fallback in get_categorization_data)
 *   - One-click Confirm when suggestion is "Personal/Non-Billable" (no client needed)
 *   - One-click Confirm when suggestion has BOTH client + category
 *   - Confirm disabled when category is billable but client is empty
 *   - Click the row body to expand inline (full title, client picker, notes)
 *   - Checkbox for bulk-select (handled by parent — see ManualCategorization)
 *
 * Non-billable category list mirrors backend FALLBACK_CATEGORIES non-billable
 * values + the CPA-industry "Personal/Non-Billable" / "Idle" pattern.
 */

import { useState, useMemo } from 'react';
import {
  Check,
  ChevronDown,
  ChevronRight,
  Sparkles,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { cn } from '@/lib/design-system';

import { BlockEvidencePanel } from '@/components/BlockEvidencePanel';

interface Suggestion {
  client: string;
  category: string;
  confidence: number;
  reasoning?: string;
}

interface Block {
  id: number;
  block_ids?: number[];
  block_count?: number;
  span_minutes?: number;
  start: string;
  end: string;
  duration_minutes: number;
  app_name: string;
  window_title: string;
  url: string;
  file_path: string;
  current_client: string | null;
  current_client_id: number | null;
  suggestions?: Suggestion[];
  classification_state?: string;
  is_billable_suggested?: boolean;
  display?: {
    title: string;
    app: string;
    duration: string;
  };
}

interface Client {
  id: number;
  name: string;
  code: string;
}

interface BlockRowProps {
  block: Block;
  clients: Client[];
  categories: string[];
  internalCategories?: string[];
  isSelected: boolean;
  onToggleSelect: (blockId: number, shift: boolean) => void;
  onCategorize: (
    blockId: number,
    blockIds: number[],
    clientId: number | null,
    category: string,
    notes?: string,
  ) => Promise<any>;
  onRefresh?: () => void;          // ← add this
}

// Categories that don't require a client to be set before confirming.
// Matches the backend's FALLBACK_CATEGORIES non-billable values.
const NON_BILLABLE_CATEGORIES = new Set([
  'Personal/Non-Billable',
  'Idle',
  'Uncategorized',
]);

const isNonBillableCategory = (cat: string): boolean =>
  NON_BILLABLE_CATEGORIES.has(cat) || cat.toLowerCase().includes('personal');

const formatTime = (dateStr: string): string => {
  return new Date(dateStr).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  });
};

const BlockRow = ({
  block,
  clients,
  categories,
  internalCategories,
  isSelected,
  onToggleSelect,
  onCategorize,
  onRefresh,                       // ← add this
}: BlockRowProps) => {
  const topSuggestion = block.suggestions?.[0];

  // Resolve suggestion's client name → client object (suggestions come as names)
  const suggestedClientObj = useMemo(
    () =>
      topSuggestion?.client
        ? clients.find((c) => c.name === topSuggestion.client)
        : null,
    [topSuggestion, clients],
  );

  const [expanded, setExpanded] = useState(false);
  // Only pre-fill the form from a suggestion the classifier is reasonably sure
  // about (>= 0.65, the same line as the "Likely" tier). Below that, leave the
  // form empty so the user picks deliberately instead of un-doing a weak guess.
  const suggestionIsConfident = (topSuggestion?.confidence ?? 0) >= 0.65;
  const [selectedClient, setSelectedClient] = useState<string>(
    block.current_client_id?.toString() ||
      (suggestionIsConfident ? suggestedClientObj?.id.toString() : '') ||
      '',
  );
  const [selectedCategory, setSelectedCategory] = useState<string>(
    suggestionIsConfident ? (topSuggestion?.category || '') : '',
  );
  const [notes, setNotes] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);

  const selectedClientObj = clients.find(
    (c) => c.id.toString() === selectedClient,
  );
  const activeCategories =
    selectedClientObj?.name === 'Internal' && internalCategories
      ? internalCategories
      : categories;

  const blockIds = block.block_ids || [block.id];
  const isMerged = (block.block_count || 1) > 1;

  // The Confirm button is enabled when:
  //   - A category is selected, AND
  //   - Either the category is non-billable (no client needed) OR a client is selected
  const categoryIsNonBillable = isNonBillableCategory(selectedCategory);
  const canConfirm =
    !!selectedCategory && (categoryIsNonBillable || !!selectedClient);

  // Suggestion display strength — bucket the raw confidence
  const suggestionLabel = useMemo(() => {
    if (!topSuggestion) return null;
    if (topSuggestion.confidence >= 0.8) return 'High confidence';
    if (topSuggestion.confidence >= 0.65) return 'Likely';
    return 'Suggested';
  }, [topSuggestion]);

  const handleConfirm = async (e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (!canConfirm || saving) return;

    setSaving(true);
    setError(null);

    try {
      await onCategorize(
        block.id,
        blockIds,
        selectedClient ? parseInt(selectedClient) : null,
        selectedCategory,
        notes || undefined,
      );
      setConfirmed(true);
      // Parent removes the block from the list after success, but show a
      // brief checkmark first for feedback.
    } catch (err: any) {
      setError(err?.message || 'Failed to save');
      setSaving(false);
    }
  };

  const handleRowClick = (e: React.MouseEvent) => {
    // Don't toggle expand when clicking interactive elements
    const target = e.target as HTMLElement;
    if (
      target.closest('button') ||
      target.closest('select') ||
      target.closest('input') ||
      target.closest('textarea')
    ) {
      return;
    }
    setExpanded((v) => !v);
  };

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onToggleSelect(block.id, e.shiftKey);
  };

  if (confirmed) {
    // Brief fade-out state. Parent will remove this row from the list shortly.
    return (
      <div
        className="
          flex items-center gap-3 px-4 py-3
          border border-emerald-200 bg-emerald-50 rounded-lg
          transition-opacity duration-300
        "
      >
        <Check className="w-4 h-4 text-emerald-600 flex-shrink-0" />
        <span className="text-sm text-emerald-700 font-medium">Confirmed</span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'border border-border/60 bg-card rounded-lg transition-all',
        'hover:border-border hover:shadow-sm',
        isSelected && 'border-primary bg-primary/5 ring-1 ring-primary/20',
        expanded && 'shadow-sm',
      )}
    >
      {/* ── Main row (always visible) ────────────────────────────────── */}
      <div
        className="flex items-center gap-3 px-3 py-2.5 cursor-pointer"
        onClick={handleRowClick}
      >
        {/* Checkbox */}
        <div
          className="flex-shrink-0 cursor-pointer p-1 -m-1"
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect(block.id, e.shiftKey);
          }}
        >
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => {}}
            className="
              w-4 h-4 rounded border-2 border-border
              text-primary focus:ring-primary focus:ring-2 focus:ring-offset-0
              cursor-pointer
            "
          />
        </div>
        {/* Expand chevron */}
        <div className="flex-shrink-0 text-muted-foreground">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
        </div>

        {/* Time + duration column */}
        <div className="flex-shrink-0 w-20 text-xs text-muted-foreground tabular-nums">
          <div className="font-medium text-foreground">
            {formatTime(block.start)}
          </div>
          <div>{block.duration_minutes}m</div>
        </div>

        {/* App + title (truncated) */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            {block.display?.app || block.app_name}
            {isMerged && (
              <span className="ml-1.5 text-[10px] font-bold text-primary">
                · {block.block_count} merged
              </span>
            )}
          </div>
          <div className="text-sm text-foreground truncate" title={block.window_title}>
            {block.display?.title || block.window_title || '(no title)'}
          </div>
        </div>

        {/* Suggestion chip — styled by confidence so an unsure guess doesn't
            masquerade as a confident answer. >=0.65 shows the proposal in a
            calm, confident style; below that it reads as a question the user
            should resolve, not an answer to accept. */}
        {topSuggestion && !expanded && (
          suggestionIsConfident ? (
            <div className="flex-shrink-0 hidden md:flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-50 border border-emerald-200">
              <Sparkles className="w-3 h-3 text-emerald-600" />
              <span className="text-xs font-semibold text-emerald-900">
                {topSuggestion.client || topSuggestion.category || 'Suggestion'}
              </span>
              {topSuggestion.client && topSuggestion.category && (
                <span className="text-xs text-emerald-700">· {topSuggestion.category}</span>
              )}
            </div>
          ) : (
            <div className="flex-shrink-0 hidden md:flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-50 border border-slate-200">
              <AlertCircle className="w-3 h-3 text-slate-400" />
              <span className="text-xs font-medium text-slate-500">needs you</span>
            </div>
          )
        )}

        {/* Confirm button */}
        <button
          onClick={handleConfirm}
          disabled={!canConfirm || saving}
          className={cn(
            'flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-semibold',
            'transition-all',
            canConfirm && !saving
              ? 'bg-emerald-500 text-white hover:bg-emerald-600 shadow-sm'
              : 'bg-muted text-muted-foreground cursor-not-allowed',
          )}
          title={
            !canConfirm
              ? selectedCategory
                ? 'Select a client first (billable categories require a client)'
                : 'Select a category first'
              : 'Confirm and remove from review pile'
          }
        >
          {saving ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Check className="w-3.5 h-3.5" />
          )}
          Confirm
        </button>
      </div>

      {/* ── Expanded detail (toggle on row click) ─────────────────────── */}
      {expanded && (
        <div className="px-3 pb-3 border-t border-border/40 pt-3 space-y-3">
          {/* Full window title */}
          <div className="text-xs text-muted-foreground break-words">
            <span className="font-semibold uppercase tracking-wide">
              Full title:
            </span>{' '}
            <span className="text-foreground">{block.window_title || '(empty)'}</span>
          </div>

          {/* Suggestion details */}
          {topSuggestion && (
            <div className="px-3 py-2 rounded-md bg-amber-50 border border-amber-200">
              <div className="flex items-start gap-2">
                <Sparkles className="w-3.5 h-3.5 text-amber-600 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-amber-900">
                    {suggestionLabel}: {topSuggestion.category}
                    {topSuggestion.client && ` for ${topSuggestion.client}`}
                  </div>
                  {topSuggestion.reasoning && (
                    <div className="text-xs text-amber-700 mt-0.5 italic">
                      {topSuggestion.reasoning}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* v1.3.63: surrounding-context advisor for no-client blocks (QB
              nameless modals/splash). Shows the client open before/after with
              one-click assign on confident cases. Hidden once a client is set. */}
          {!block.current_client_id && (
            <div
              className="rounded-md border border-slate-200 overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              <BlockEvidencePanel blockId={block.id} onAssigned={onRefresh} />
            </div>
          )}

          {/* Client + Category pickers */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">
                Client {!categoryIsNonBillable && <span className="text-destructive">*</span>}
              </label>
              <select
                value={selectedClient}
                onChange={(e) => setSelectedClient(e.target.value)}
                disabled={saving}
                onClick={(e) => e.stopPropagation()}
                className="
                  w-full px-2 py-1.5 rounded-md text-sm
                  border border-border bg-card text-foreground
                  focus:border-primary focus:ring-1 focus:ring-primary/20 focus:outline-none
                  disabled:opacity-50
                "
              >
                <option value="">
                  {categoryIsNonBillable ? 'No client (non-billable)' : 'Select client...'}
                </option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name}
                    {client.code ? ` (${client.code})` : ''}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[10px] font-bold text-muted-foreground uppercase tracking-wider mb-1">
                Category <span className="text-destructive">*</span>
              </label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                disabled={saving}
                onClick={(e) => e.stopPropagation()}
                className="
                  w-full px-2 py-1.5 rounded-md text-sm
                  border border-border bg-card text-foreground
                  focus:border-primary focus:ring-1 focus:ring-primary/20 focus:outline-none
                  disabled:opacity-50
                "
              >
                <option value="">Select category...</option>
                {activeCategories.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Quick "Personal / Non-Billable" — the pile has real personal
              browsing (news, shopping); this saves a dropdown hunt. Sets the
              category and immediately confirms (no client needed). */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              setSelectedClient('');
              setSelectedCategory('Personal/Non-Billable');
            }}
            disabled={saving}
            className="
              text-xs font-medium text-slate-500 hover:text-slate-800
              underline underline-offset-2 disabled:opacity-50
            "
          >
            Mark as Personal / Non-Billable
          </button>

          {/* Notes (optional, hidden until toggled) */}
          <details onClick={(e) => e.stopPropagation()}>
            <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground">
              Add notes
            </summary>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional notes about this time entry..."
              disabled={saving}
              onClick={(e) => e.stopPropagation()}
              className="
                mt-2 w-full px-2 py-1.5 rounded-md text-sm
                border border-border bg-card text-foreground
                placeholder:text-muted-foreground/60
                focus:border-primary focus:ring-1 focus:ring-primary/20 focus:outline-none
                disabled:opacity-50
                min-h-[60px] resize-none
              "
            />
          </details>

          {error && (
            <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-destructive/10 border border-destructive/30">
              <AlertCircle className="w-3.5 h-3.5 text-destructive flex-shrink-0" />
              <span className="text-xs text-destructive">{error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default BlockRow;
