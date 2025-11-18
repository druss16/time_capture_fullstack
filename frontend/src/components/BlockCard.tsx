/**
 * BlockCard.tsx - Compact individual block categorization card
 * Place in: frontend/src/components/BlockCard.tsx
 */

import { useState } from 'react';
import { Clock, CheckCircle2, AlertCircle, Edit3, Save, X, Timer } from 'lucide-react';

interface Suggestion {
  client: string;
  category: string;
  confidence: number;
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
}

interface Client {
  id: number;
  name: string;
  code: string;
}

interface BlockCardProps {
  block: Block;
  clients: Client[];
  categories: string[];
  onCategorize: (
    blockId: number, 
    blockIds: number[], 
    clientId: number | null, 
    category: string, 
    notes?: string
  ) => Promise<any>;
}

const BlockCard = ({ block, clients, categories, onCategorize }: BlockCardProps) => {
  const [isEditing, setIsEditing] = useState(false);
  const [selectedClient, setSelectedClient] = useState<string>(block.current_client_id?.toString() || '');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const blockIds = block.block_ids || [block.id];
  const isMerged = (block.block_count || 1) > 1;
  const hasSignificantSpan = block.span_minutes && 
    block.span_minutes > block.duration_minutes * 1.2;

  const handleQuickSave = async () => {
    if (!selectedCategory) {
      setLocalError('Please select a category');
      return;
    }

    setSaving(true);
    setLocalError(null);

    try {
      await onCategorize(
        block.id,
        blockIds,
        selectedClient ? parseInt(selectedClient) : null,
        selectedCategory,
        notes || undefined
      );
    } catch (error: any) {
      setLocalError(error.message || 'Failed to save categorization');
    } finally {
      setSaving(false);
    }
  };

  const handleEditSave = async () => {
    await handleQuickSave();
    if (!localError) {
      setIsEditing(false);
    }
  };

  const handleUseSuggestion = (suggestion: Suggestion) => {
    if (suggestion.client) {
      const client = clients.find(c => c.name === suggestion.client);
      if (client) {
        setSelectedClient(client.id.toString());
      }
    }
    if (suggestion.category) {
      setSelectedCategory(suggestion.category);
    }
  };

  const formatTime = (dateStr: string) => {
    return new Date(dateStr).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const urlDomain = block.url ? (() => {
    try {
      return new URL(block.url).hostname;
    } catch {
      return null;
    }
  })() : null;

  const isIdle = block.app_name?.toLowerCase() === 'idle' || 
                 block.window_title?.toLowerCase().includes('idle');

  return (
    <div className={`border rounded-lg p-3 shadow-sm hover:shadow transition-shadow ${
      isIdle ? 'border-gray-300 bg-gray-50' : 'border-border bg-card'
    }`}>
      {/* Compact header with time and duration */}
      <div className="flex justify-between items-start mb-2 pb-2 border-b border-border">
        <div className="flex-1">
          <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
            <Clock className="w-3 h-3" />
            <span className="font-medium">{formatTime(block.start)} - {formatTime(block.end)}</span>
            
            {isMerged && (
              <span className="px-1.5 py-0.5 bg-primary/20 text-primary text-xs font-semibold rounded">
                {block.block_count} merged
              </span>
            )}
            
            {isIdle && (
              <span className="px-1.5 py-0.5 bg-gray-300 text-gray-700 text-xs font-semibold rounded">
                💤 Idle
              </span>
            )}
          </div>
          
          <div className="text-xs text-muted-foreground mt-1 flex items-center gap-3">
            <span className="flex items-center gap-1">
              <Timer className="w-3 h-3" />
              <span className="font-medium">{block.duration_minutes} min</span>
            </span>
            
            {hasSignificantSpan && (
              <span className="text-yellow-600 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {Math.round(block.span_minutes!)} min span
              </span>
            )}
          </div>
        </div>
        
        <div className="text-right ml-3">
          <div className="text-xl font-bold text-primary">
            {(block.duration_minutes / 60).toFixed(2)}h
          </div>
        </div>
      </div>

      {/* Compact activity details */}
      <div className="mb-2 space-y-1">
        {block.app_name && (
          <div className="text-xs flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[50px]">App:</span>
            <span className="text-foreground font-medium truncate">{block.app_name}</span>
          </div>
        )}
        {block.window_title && (
          <div className="text-xs flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[50px]">Title:</span>
            <span className="text-foreground truncate">{block.window_title}</span>
          </div>
        )}
        {urlDomain && (
          <div className="text-xs flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[50px]">Domain:</span>
            <span className="text-foreground">🌐 {urlDomain}</span>
          </div>
        )}
        {block.file_path && (
          <div className="text-xs flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[50px]">File:</span>
            <span className="text-foreground font-mono text-xs truncate">📄 {block.file_path}</span>
          </div>
        )}
      </div>

      {/* Compact AI Suggestions */}
      {block.suggestions && block.suggestions.length > 0 && (
        <div className="mb-2 p-2 bg-yellow-50 border border-yellow-200 rounded">
          <div className="text-xs font-semibold text-yellow-900 mb-1 flex items-center gap-1">
            💡 Suggestions
          </div>
          <div className="space-y-1">
            {block.suggestions.map((suggestion, idx) => (
              <button
                key={idx}
                onClick={() => handleUseSuggestion(suggestion)}
                disabled={saving}
                className="text-xs text-left w-full hover:bg-yellow-100 p-1.5 rounded transition-colors flex items-center justify-between disabled:opacity-50"
              >
                <div className="truncate">
                  {suggestion.client && <span className="font-semibold text-yellow-900">{suggestion.client}</span>}
                  {suggestion.category && <span className="text-yellow-800"> → {suggestion.category}</span>}
                </div>
                <span className="text-xs text-yellow-600 font-medium ml-2 flex-shrink-0">
                  {(suggestion.confidence * 100).toFixed(0)}%
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Local Error */}
      {localError && (
        <div className="mb-2 bg-destructive/10 border border-destructive/30 rounded p-2 flex items-center gap-2">
          <AlertCircle className="w-3 h-3 text-destructive flex-shrink-0" />
          <span className="text-xs text-destructive">{localError}</span>
        </div>
      )}

      {/* Compact categorization form */}
      {!isEditing ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                Client <span className="text-muted-foreground font-normal">(Optional)</span>
              </label>
              <select
                value={selectedClient}
                onChange={(e) => setSelectedClient(e.target.value)}
                className="w-full border border-border rounded px-2 py-1.5 bg-card text-foreground text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                disabled={saving}
              >
                <option value="">-- Select --</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name} {client.code && `(${client.code})`}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                Category <span className="text-destructive">*</span>
              </label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full border border-border rounded px-2 py-1.5 bg-card text-foreground text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                required
                disabled={saving}
              >
                <option value="">-- Select --</option>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleQuickSave}
              disabled={!selectedCategory || saving}
              className={`flex-1 px-3 py-1.5 rounded font-medium text-xs transition-all flex items-center justify-center gap-1.5 ${
                selectedCategory && !saving
                  ? 'bg-green-600 text-white hover:bg-green-700 shadow-sm'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
              }`}
            >
              {saving ? (
                <>
                  <Clock className="w-3 h-3 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-3 h-3" />
                  Confirm
                </>
              )}
            </button>
            <button
              onClick={() => setIsEditing(true)}
              disabled={saving}
              className="px-3 py-1.5 border border-border rounded font-medium text-xs hover:bg-accent transition-colors flex items-center gap-1.5"
            >
              <Edit3 className="w-3 h-3" />
              Edit
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                Client <span className="text-muted-foreground font-normal">(Optional)</span>
              </label>
              <select
                value={selectedClient}
                onChange={(e) => setSelectedClient(e.target.value)}
                className="w-full border border-border rounded px-2 py-1.5 bg-card text-foreground text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                disabled={saving}
              >
                <option value="">-- Select --</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name} {client.code && `(${client.code})`}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-foreground mb-1">
                Category <span className="text-destructive">*</span>
              </label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full border border-border rounded px-2 py-1.5 bg-card text-foreground text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                required
                disabled={saving}
              >
                <option value="">-- Select --</option>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-foreground mb-1">
              Notes <span className="text-muted-foreground font-normal">(Optional)</span>
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes..."
              className="w-full border border-border rounded px-2 py-1.5 bg-card text-foreground text-xs focus:outline-none focus:ring-1 focus:ring-primary min-h-[60px]"
              disabled={saving}
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleEditSave}
              disabled={!selectedCategory || saving}
              className={`flex-1 px-3 py-1.5 rounded font-medium text-xs transition-all flex items-center justify-center gap-1.5 ${
                selectedCategory && !saving
                  ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
              }`}
            >
              {saving ? (
                <>
                  <Clock className="w-3 h-3 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-3 h-3" />
                  Save
                </>
              )}
            </button>
            <button
              onClick={() => setIsEditing(false)}
              disabled={saving}
              className="px-3 py-1.5 border border-border rounded font-medium text-xs hover:bg-accent transition-colors flex items-center gap-1.5"
            >
              <X className="w-3 h-3" />
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default BlockCard;