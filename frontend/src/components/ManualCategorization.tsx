/**
 * ManualCategorization.tsx - Compact manual time block categorization interface
 */

import { useState, useEffect, useCallback } from 'react';
import { Clock, RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react';
import BlockCard from './BlockCard';

import { safeFetchJson } from "@/lib/api";  // ✅ ADD THIS

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

interface Suggestion {
  client: string;
  category: string;
  confidence: number;
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
  stats: {
    uncategorized_count: number;
    total_minutes: number;
    original_block_count?: number;
  };
}

interface ManualCategorizationProps {
  onComplete?: () => void;
}


const ManualCategorization = ({ onComplete }: ManualCategorizationProps) => {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const today = new Date();
    return today.toLocaleDateString('en-CA');
  });
  
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<CategorizationData['stats'] | null>(null);

  const fetchCategorizationData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const url = `${API_BASE}/categorization/data/?date=${selectedDate}`;
      console.log('🔍 Fetching:', url);  // ✅ ADD THIS
      
      const data = await safeFetchJson<CategorizationData>(url);
      
      console.log('✅ Got data:', data);  // ✅ ADD THIS
      
      setBlocks(data.blocks || []);
      setClients(data.clients || []);
      setCategories(data.categories || []);
      setStats(data.stats || null);
    } catch (error: any) {
      console.error('❌ Failed to load data:', error);
      setError(error.message || 'Failed to load blocks');
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  const categorizeBlock = useCallback(async (
    blockId: number, 
    blockIds: number[],
    clientId: number | null, 
    category: string, 
    notes?: string
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
          body: JSON.stringify(payload)
        }
      );

      // ✅ OPTIMISTIC UPDATE: Remove categorized block from local state
      // instead of refetching everything
      setBlocks(prevBlocks => prevBlocks.filter(b => b.id !== blockId));
      
      // Update stats
      if (stats) {
        const categorizedBlock = blocks.find(b => b.id === blockId);
        const minutesRemoved = categorizedBlock?.duration_minutes || 0;
        setStats({
          ...stats,
          uncategorized_count: Math.max(0, stats.uncategorized_count - 1),
          total_minutes: Math.max(0, stats.total_minutes - minutesRemoved),
        });
      }
      
      if (onComplete) {
        onComplete();
      }
      
      return result;
    } catch (error: any) {
      console.error('categorizeBlock ERROR:', error);
      setError(error.message || 'Failed to save categorization');
      // ✅ On error, refetch to get correct state
      await fetchCategorizationData();
      throw error;
    }
  }, [blocks, stats, onComplete, fetchCategorizationData]);

  const totalHours = stats ? (stats.total_minutes / 60).toFixed(1) : '0.0';

  useEffect(() => {
    fetchCategorizationData();
  }, [fetchCategorizationData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="w-6 h-6 text-primary animate-spin mr-2" />
        <span className="text-sm text-muted-foreground">Loading blocks...</span>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      {/* Compact Header */}
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
          <button
            onClick={fetchCategorizationData}
            disabled={loading}
            className="mt-5 px-3 py-1.5 bg-primary text-primary-foreground rounded text-sm hover:bg-primary/90 transition-colors flex items-center gap-1.5"
          >
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {/* Compact Stats */}
        <div className="bg-gradient-to-r from-primary/10 to-accent/10 border border-primary/30 rounded-lg p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-primary" />
              <div>
                <div className="text-lg font-bold text-foreground">
                  {blocks.length} group{blocks.length !== 1 ? 's' : ''} to categorize
                </div>
                <div className="text-xs text-muted-foreground">
                  {totalHours} hours total
                  {stats?.original_block_count && stats.original_block_count > blocks.length && (
                    <span className="ml-1">
                      ({stats.original_block_count} blocks merged)
                    </span>
                  )}
                </div>
              </div>
            </div>
            {blocks.length > 0 && stats && (
              <div className="text-right">
                <div className="text-xs text-muted-foreground">Avg duration</div>
                <div className="text-base font-semibold text-primary">
                  {(stats.total_minutes / blocks.length).toFixed(0)} min
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Error Banner */}
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

      {/* Blocks */}
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
        <div className="space-y-3">
          {blocks.map((block) => (
            <BlockCard
              key={block.id}
              block={block}
              clients={clients}
              categories={categories}
              onCategorize={categorizeBlock}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default ManualCategorization;