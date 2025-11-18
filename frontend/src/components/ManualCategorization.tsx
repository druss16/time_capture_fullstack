/**
 * ManualCategorization.tsx - Manual time block categorization interface
 * Complete working version with local timezone date handling
 */

import { useState, useEffect, useCallback } from 'react';
import { Clock, RefreshCw, CheckCircle2, AlertCircle } from 'lucide-react';
import BlockCard from './BlockCard';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

console.log('🔵 API_BASE:', API_BASE);

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

// Helper to get CSRF token
const getCsrfToken = (): string => {
  const token = document.cookie
    .split('; ')
    .find(row => row.startsWith('csrftoken='))
    ?.split('=')[1];
  console.log('🔵 CSRF Token:', token ? 'Found' : 'NOT FOUND');
  return token || '';
};

const ManualCategorization = ({ onComplete }: ManualCategorizationProps) => {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  
  // ✅ Fixed: Use local timezone for today's date (not UTC)
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const today = new Date();
    return today.toLocaleDateString('en-CA'); // YYYY-MM-DD format in local timezone
  });
  
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<CategorizationData['stats'] | null>(null);

  const fetchCategorizationData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      const url = `${API_BASE}/categorization/data/?date=${selectedDate}`;
      console.log('🔵 Fetching categorization data from:', url);
      
      const response = await fetch(url, {
        credentials: 'include',
      });
      
      console.log('🔵 Categorization data response status:', response.status);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data: CategorizationData = await response.json();
      console.log('🔵 Categorization data received:', {
        blocks: data.blocks?.length,
        clients: data.clients?.length,
        categories: data.categories?.length
      });
      
      setBlocks(data.blocks || []);
      setClients(data.clients || []);
      setCategories(data.categories || []);
      setStats(data.stats || null);
    } catch (error: any) {
      console.error('🔴 Failed to load data:', error);
      setError(error.message || 'Failed to load blocks');
    } finally {
      setLoading(false);
    }
  }, [selectedDate]);

  useEffect(() => {
    fetchCategorizationData();
  }, [fetchCategorizationData]);

  const categorizeBlock = useCallback(async (
    blockId: number, 
    blockIds: number[],
    clientId: number | null, 
    category: string, 
    notes?: string
  ) => {
    console.log('🔵 categorizeBlock CALLED:', {
      blockId,
      blockIds,
      clientId,
      category,
      notes
    });

    try {
      const url = `${API_BASE}/categorization/save/`;
      const csrfToken = getCsrfToken();
      
      const payload = {
        block_id: blockId,
        block_ids: blockIds,
        client_id: clientId,
        category: category,
        notes: notes || undefined,
      };
      
      console.log('🔵 About to POST to:', url);
      console.log('🔵 Payload:', payload);
      console.log('🔵 Headers:', {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken ? 'present' : 'MISSING'
      });
      
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify(payload)
      });

      console.log('🔵 Response status:', response.status);
      console.log('🔵 Response ok:', response.ok);

      if (!response.ok) {
        const errorText = await response.text();
        console.error('🔴 Error response:', errorText);
        
        let errorData;
        try {
          errorData = JSON.parse(errorText);
        } catch {
          throw new Error(`HTTP ${response.status}: ${errorText.substring(0, 200)}`);
        }
        throw new Error(errorData.error || 'Failed to save');
      }

      const result = await response.json();
      console.log('✅ Categorization successful:', result);
      
      // Refresh data
      await fetchCategorizationData();
      
      // Notify parent
      if (onComplete) {
        onComplete();
      }
      
      return result;
    } catch (error: any) {
      console.error('🔴 categorizeBlock ERROR:', error);
      setError(error.message || 'Failed to save categorization');
      throw error;
    }
  }, [fetchCategorizationData, onComplete]);

  const totalHours = stats ? (stats.total_minutes / 60).toFixed(1) : '0.0';

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <RefreshCw className="w-8 h-8 text-primary animate-spin mr-3" />
        <span className="text-muted-foreground">Loading blocks...</span>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-4 mb-4">
          <div className="flex-1">
            <label className="block text-sm font-medium text-muted-foreground mb-2">
              Select Date:
            </label>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="w-full max-w-xs border border-border rounded-lg px-4 py-2 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <button
            onClick={fetchCategorizationData}
            disabled={loading}
            className="mt-6 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {/* Stats */}
        <div className="bg-gradient-to-r from-primary/10 to-accent/10 border border-primary/30 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Clock className="w-6 h-6 text-primary" />
              <div>
                <div className="text-2xl font-bold text-foreground">
                  {blocks.length} group{blocks.length !== 1 ? 's' : ''} to categorize
                </div>
                <div className="text-sm text-muted-foreground">
                  {totalHours} hours total
                  {stats?.original_block_count && stats.original_block_count > blocks.length && (
                    <span className="ml-2">
                      ({stats.original_block_count} blocks merged)
                    </span>
                  )}
                </div>
              </div>
            </div>
            {blocks.length > 0 && stats && (
              <div className="text-right">
                <div className="text-sm text-muted-foreground">Average duration</div>
                <div className="text-lg font-semibold text-primary">
                  {(stats.total_minutes / blocks.length).toFixed(0)} min
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="mb-6 bg-destructive/10 border border-destructive/30 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-destructive flex-shrink-0" />
          <div>
            <div className="font-semibold text-destructive">Error</div>
            <div className="text-sm text-destructive/80">{error}</div>
          </div>
          <button
            onClick={() => setError(null)}
            className="ml-auto text-destructive hover:text-destructive/80"
          >
            ✕
          </button>
        </div>
      )}

      {/* Blocks */}
      {blocks.length === 0 ? (
        <div className="text-center py-16 bg-card border border-border rounded-lg shadow-sm">
          <div className="w-16 h-16 bg-success/20 rounded-full flex items-center justify-center mx-auto mb-4">
            <CheckCircle2 className="w-8 h-8 text-success" />
          </div>
          <p className="text-xl font-semibold text-foreground mb-2">
            ✨ All blocks categorized!
          </p>
          <p className="text-sm text-muted-foreground">
            All time blocks for {selectedDate} have been properly categorized.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
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