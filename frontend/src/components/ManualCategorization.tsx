/**
 * ManualCategorization.tsx — v1.3.60 Phase 2
 *
 * Rewrites the categorize page around dense rows + bulk action. Replaces the
 * BlockCard render loop with BlockRow, adds a floating SelectionBar for bulk
 * confirm/categorize.
 *
 * UX guarantees:
 *   - Pre-filled suggestions surface from the backend (see BlockRow)
 *   - "Confirm all suggestions" button at the top one-click-clears the obvious
 *     blocks (those with pre-filled client+category or non-billable suggestions)
 *   - Multi-select via shift-click for range selection
 *   - Bulk action: assign one client+category to N selected blocks
 *
 * Mobile note: SelectionBar floats at bottom on mobile too. The row layout
 * collapses the suggestion chip below 768px (handled in BlockRow via `md:flex`).
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Clock,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Briefcase,
  Sparkles,
  X,
  ArrowRightLeft,
} from 'lucide-react';
import BlockRow from './BlockRow';

import { safeFetchJson } from '@/lib/api';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api')
  ? RAW_BASE
  : `${RAW_BASE.replace(/\/+$/, '')}/api`;

const INTERNAL_CATEGORIES = [
  'Idle',
  'Personal/Non-Billable',
  'Administration',
  'Team Meetings',
  'Training/Professional Development',
  'Business Development/Sales',
  'Hiring/HR',
  'Company Planning',
  'Internal Projects',
  'Marketing (Own Firm)',
  'IT/Tech Support',
  'Finance/Accounting (Own Firm)',
  'PTO/Time Off',
  'Email/Communication',
];

interface Suggestion {
  client: string;
  category: string;
  confidence: number;
  reasoning?: string;
}

interface Block {
  id: number;
  block_ids: number[];
  block_count: number;
  start: string;
  end: string;
  duration_minutes: number;
  span_minutes?: number;
  app_name: string;
  window_title: string;
  url: string;
  file_path: string;
  current_client: string | null;
  current_client_id: number | null;
  suggestions: Suggestion[];
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

interface CategorizationData {
  date: string;
  blocks: Block[];
  clients: Client[];
  categories: string[];
  industry_type?: string;
  stats: {
    uncategorized_count: number;
    total_minutes: number;
    original_block_count?: number;
  };
}

interface ManualCategorizationProps {
  onComplete?: () => void;
}

const INDUSTRY_LABELS: Record<string, string> = {
  cpa: 'CPA / Accounting',
  ai_consulting: 'AI / Tech Consulting',
  marketing: 'Marketing Agency',
  legal: 'Legal Services',
  general: 'General',
};

const NON_BILLABLE_CATEGORIES = new Set([
  'Personal/Non-Billable',
  'Idle',
  'Uncategorized',
]);

const isNonBillableCategory = (cat: string): boolean =>
  NON_BILLABLE_CATEGORIES.has(cat) || cat.toLowerCase().includes('personal');

// A suggestion is "one-click-confirmable" if either:
//   - The category is non-billable (no client needed), OR
//   - Both client AND category are pre-filled
const isOneClickSuggestion = (block: Block): boolean => {
  const s = block.suggestions?.[0];
  if (!s || !s.category) return false;
  if (isNonBillableCategory(s.category)) return true;
  return !!s.client; // billable but has a client → still one-click
};

const ManualCategorization = ({ onComplete }: ManualCategorizationProps) => {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [industryType, setIndustryType] = useState<string>('general');

  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const today = new Date();
    return today.toLocaleDateString('en-CA');
  });

  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<CategorizationData['stats'] | null>(null);

  // Multi-select state
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const lastClickedIdRef = useRef<number | null>(null);

  // Bulk action state
  const [bulkSaving, setBulkSaving] = useState(false);

  // Filter out short blocks (< 2 min) from the unassigned queue by default.
  // These are typically alt-tab noise (brief focus, app switching) rather than
  // real billable work. User can untoggle to see them.
  const [hideShortBlocks, setHideShortBlocks] = useState(true);
  const SHORT_BLOCK_THRESHOLD_MINUTES = 2;

  const fetchCategorizationData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const url = `${API_BASE}/categorization/data/?date=${selectedDate}`;
      const data = await safeFetchJson<CategorizationData>(url);

      setBlocks(data.blocks || []);
      setClients(data.clients || []);
      setCategories(data.categories || []);
      setIndustryType(data.industry_type || 'general');
      setStats(data.stats || null);
      // Clear selection on reload
      setSelectedIds(new Set());
    } catch (err: any) {
      setError(err.message || 'Failed to load blocks');
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  const categorizeBlock = useCallback(
    async (
      blockId: number,
      blockIds: number[],
      clientId: number | null,
      category: string,
      notes?: string,
    ) => {
      try {
        const payload = {
          block_id: blockId,
          block_ids: blockIds,
          client_id: clientId,
          category: category,
          notes: notes || undefined,
        };

        const result = await safeFetchJson(
          `${API_BASE}/categorization/save/`,
          {
            method: 'POST',
            body: JSON.stringify(payload),
          },
        );

        // Optimistic update: remove the block from local state after a brief delay
        // so the user sees the "Confirmed" feedback
        setTimeout(() => {
          setBlocks((prev) => prev.filter((b) => b.id !== blockId));
          setSelectedIds((prev) => {
            const next = new Set(prev);
            next.delete(blockId);
            return next;
          });
          if (stats) {
            const cat = blocks.find((b) => b.id === blockId);
            const minutesRemoved = cat?.duration_minutes || 0;
            setStats({
              ...stats,
              uncategorized_count: Math.max(0, stats.uncategorized_count - 1),
              total_minutes: Math.max(0, stats.total_minutes - minutesRemoved),
            });
          }
        }, 400);

        if (onComplete) onComplete();

        return result;
      } catch (error: any) {
        setError(error.message || 'Failed to save categorization');
        await fetchCategorizationData();
        throw error;
      }
    },
    [blocks, stats, onComplete, fetchCategorizationData],
  );

  // ── Selection handlers ────────────────────────────────────────────────

  const handleToggleSelect = useCallback(
    (blockId: number, shift: boolean) => {
      setSelectedIds((prev) => {
        const next = new Set(prev);

        // Shift-click extends from last-clicked to this one
        if (shift && lastClickedIdRef.current !== null) {
          const ids = blocks.map((b) => b.id);
          const lastIdx = ids.indexOf(lastClickedIdRef.current);
          const thisIdx = ids.indexOf(blockId);
          if (lastIdx !== -1 && thisIdx !== -1) {
            const [from, to] =
              lastIdx < thisIdx ? [lastIdx, thisIdx] : [thisIdx, lastIdx];
            for (let i = from; i <= to; i++) {
              next.add(ids[i]);
            }
            lastClickedIdRef.current = blockId;
            return next;
          }
        }

        if (next.has(blockId)) {
          next.delete(blockId);
        } else {
          next.add(blockId);
        }
        lastClickedIdRef.current = blockId;
        return next;
      });
    },
    [blocks],
  );

  // Visible blocks after short-block filter applied.
  // Used for both rendering AND bulk-select so users can't accidentally
  // bulk-action hidden blocks they can't see.
  const visibleBlocks = useMemo(
    () =>
      hideShortBlocks
        ? blocks.filter((b) => (b.duration_minutes ?? 0) >= SHORT_BLOCK_THRESHOLD_MINUTES)
        : blocks,
    [blocks, hideShortBlocks],
  );
  const hiddenBlockCount = blocks.length - visibleBlocks.length;

  const handleSelectAll = useCallback(() => {
    // Toggle based on visibleBlocks (what user can see), not raw blocks.
    // With the short-block filter active, blocks.length > visibleBlocks.length,
    // so checking against blocks.length would make toggle-off impossible.
    if (selectedIds.size === visibleBlocks.length && visibleBlocks.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(visibleBlocks.map((b) => b.id)));
    }
  }, [selectedIds, visibleBlocks]);

  const handleClearSelection = useCallback(() => {
    setSelectedIds(new Set());
    lastClickedIdRef.current = null;
  }, []);

  // ── Bulk action handlers ──────────────────────────────────────────────

  const oneClickSuggestionBlocks = useMemo(
    () => blocks.filter(isOneClickSuggestion),
    [blocks],
  );

  const handleConfirmAllSuggestions = useCallback(async () => {
    if (oneClickSuggestionBlocks.length === 0) return;
    setBulkSaving(true);
    setError(null);

    try {
      // Build the bulk_categorize payload
      const items = oneClickSuggestionBlocks.map((b) => {
        const s = b.suggestions[0];
        const suggestedClient = s.client
          ? clients.find((c) => c.name === s.client)
          : null;
        return {
          block_id: b.id,
          client_id: suggestedClient?.id || null,
          category: s.category,
        };
      });

      await safeFetchJson(`${API_BASE}/categorization/bulk/`, {
        method: 'POST',
        body: JSON.stringify({ blocks: items }),
      });

      // Reload to get accurate counts (bulk endpoint doesn't return them per-item)
      await fetchCategorizationData();
    } catch (err: any) {
      setError(err.message || 'Bulk confirm failed');
    } finally {
      setBulkSaving(false);
    }
  }, [oneClickSuggestionBlocks, clients, fetchCategorizationData]);

  const handleBulkPersonal = useCallback(async () => {
    if (selectedIds.size === 0) return;
    setBulkSaving(true);
    setError(null);

    try {
      const items = Array.from(selectedIds).map((blockId) => ({
        block_id: blockId,
        client_id: null,
        category: 'Personal/Non-Billable',
      }));

      await safeFetchJson(`${API_BASE}/categorization/bulk/`, {
        method: 'POST',
        body: JSON.stringify({ blocks: items }),
      });

      await fetchCategorizationData();
    } catch (err: any) {
      setError(err.message || 'Bulk action failed');
    } finally {
      setBulkSaving(false);
    }
  }, [selectedIds, fetchCategorizationData]);

  const totalHours = stats ? (stats.total_minutes / 60).toFixed(1) : '0.0';

  useEffect(() => {
    fetchCategorizationData();
  }, [fetchCategorizationData]);

  // Keyboard shortcut: Escape clears selection
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedIds.size > 0) {
        handleClearSelection();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [selectedIds.size, handleClearSelection]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-6 h-6 text-primary animate-spin mr-2" />
        <span className="text-sm text-muted-foreground">Loading blocks...</span>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto pb-24">
      {/* ── Compact header ──────────────────────────────────────────── */}
      <div className="mb-4">
        <div className="flex items-center gap-3 mb-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Select Date:
            </label>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="w-full max-w-xs border border-border rounded px-3 py-1.5 bg-card text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {industryType && industryType !== 'general' && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/10 text-primary text-xs font-semibold rounded-full">
              <Briefcase className="w-3 h-3" />
              {INDUSTRY_LABELS[industryType] || industryType}
            </div>
          )}

          <button
            onClick={fetchCategorizationData}
            disabled={loading}
            className="mt-5 px-3 py-1.5 bg-primary text-primary-foreground rounded text-sm hover:bg-primary/90 transition-colors flex items-center gap-1.5"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {/* Summary strip + one-click-all */}
        <div
          className={cn(
            'flex items-center justify-between gap-3',
            'px-3 py-2.5 rounded-lg',
            'bg-gradient-to-r from-primary/10 to-accent/10 border border-primary/30',
          )}
        >
          <div className="flex items-center gap-2 flex-1">
            <Clock className="w-4 h-4 text-primary flex-shrink-0" />
            <div>
              <div className="text-sm font-bold text-foreground">
                {blocks.length} block{blocks.length !== 1 ? 's' : ''} to review
              </div>
              <div className="text-xs text-muted-foreground">
                {totalHours}h total
                {stats?.original_block_count &&
                  stats.original_block_count > blocks.length && (
                    <span className="ml-1">
                      ({stats.original_block_count} merged)
                    </span>
                  )}
              </div>
            </div>
          </div>

          {/* One-click confirm all suggestions */}
          {oneClickSuggestionBlocks.length > 0 && (
            <button
              onClick={handleConfirmAllSuggestions}
              disabled={bulkSaving}
              className="
                flex items-center gap-1.5 px-3 py-1.5 rounded-md
                bg-emerald-500 text-white text-sm font-semibold
                hover:bg-emerald-600 transition-colors
                disabled:opacity-50
                shadow-sm
              "
              title={`Accept the classifier's suggestion for ${oneClickSuggestionBlocks.length} blocks in one click`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              Confirm {oneClickSuggestionBlocks.length} suggested
            </button>
          )}
        </div>

        {/* Select all toggle */}
        {blocks.length > 1 && (
          <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
            <button
              onClick={handleSelectAll}
              className="hover:text-foreground hover:underline"
            >
              {selectedIds.size === blocks.length ? 'Deselect all' : 'Select all'}
            </button>
            <span>·</span>
            <span>Shift-click to select a range · Esc to clear</span>
          </div>
        )}
      </div>

      {/* ── Error banner ────────────────────────────────────────────── */}
      {error && (
        <div className="mb-4 bg-destructive/10 border border-destructive/30 rounded p-3 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
          <div className="flex-1">
            <div className="font-semibold text-destructive text-sm">Error</div>
            <div className="text-xs text-destructive/80">{error}</div>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-destructive hover:text-destructive/80 text-lg leading-none"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Block rows ──────────────────────────────────────────────── */}
      {blocks.length === 0 ? (
        <div className="text-center py-12 bg-card border border-border rounded-lg shadow-sm">
          <div className="w-12 h-12 bg-success/20 rounded-full flex items-center justify-center mx-auto mb-3">
            <CheckCircle2 className="w-6 h-6 text-success" />
          </div>
          <p className="text-base font-semibold text-foreground mb-1">
            ✨ All blocks categorized!
          </p>
          <p className="text-sm text-muted-foreground">
            All time blocks for {selectedDate} have been categorized.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {/* Short-block filter toggle */}
          <div className="flex items-center justify-between mb-2 px-1 text-xs">
            <label className="flex items-center gap-2 text-gray-600 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={hideShortBlocks}
                onChange={(e) => setHideShortBlocks(e.target.checked)}
                className="rounded border-gray-300"
              />
              Hide short blocks (under {SHORT_BLOCK_THRESHOLD_MINUTES} min)
            </label>
            {hiddenBlockCount > 0 && hideShortBlocks && (
              <button
                onClick={() => setHideShortBlocks(false)}
                className="text-blue-600 hover:underline"
              >
                Show {hiddenBlockCount} hidden
              </button>
            )}
          </div>
          {visibleBlocks.map((block) => (
            <BlockRow
              key={block.id}
              block={block}
              clients={clients}
              categories={categories}
              internalCategories={INTERNAL_CATEGORIES}
              isSelected={selectedIds.has(block.id)}
              onToggleSelect={handleToggleSelect}
              onCategorize={categorizeBlock}
            />
          ))}
        </div>
      )}

      {/* ── Floating selection bar (when items selected) ────────────── */}
      {selectedIds.size > 0 && (
        <div
          className="
            fixed bottom-6 left-1/2 -translate-x-1/2 z-50
            flex items-center gap-3 px-4 py-3 rounded-2xl
            bg-slate-900 text-white shadow-2xl
            animate-in slide-in-from-bottom-4 duration-200
          "
        >
          <span className="text-sm font-semibold text-white/90">
            {selectedIds.size} selected
          </span>
          <div className="w-px h-4 bg-white/20" />
          <button
            onClick={handleBulkPersonal}
            disabled={bulkSaving}
            className="
              flex items-center gap-1.5 px-3 py-1.5 rounded-lg
              bg-emerald-500 text-white text-xs font-bold
              hover:bg-emerald-600 transition-colors
              disabled:opacity-50
            "
          >
            <CheckCircle2 className="w-3 h-3" />
            Mark all Personal/Non-Billable
          </button>
          <button
            onClick={handleClearSelection}
            className="
              flex items-center gap-1 px-2 py-1.5 rounded-lg
              bg-white/10 hover:bg-white/20 transition-colors
              text-xs font-bold text-white/70
            "
          >
            <X className="w-3 h-3" />
            Clear
          </button>
        </div>
      )}
    </div>
  );
};

// Local cn() since we don't have the import handy in this isolated component
function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

export default ManualCategorization;