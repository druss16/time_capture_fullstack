/**
 * BlockCard.tsx - Individual block categorization card with session span info
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
  span_minutes?: number;  // Total wall-clock time
  start: string;
  end: string;
  duration_minutes: number;  // Active time
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
  
  // Check if there's a significant span (gaps/idle between blocks)
  const hasSignificantSpan = block.span_minutes && 
    block.span_minutes > block.duration_minutes * 1.2; // 20% difference

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
      // Success - parent will refresh
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

  // Check if this is an idle block
  const isIdle = block.app_name?.toLowerCase() === 'idle' || 
                 block.window_title?.toLowerCase().includes('idle');

  return (
    <div className={`border rounded-lg p-6 shadow-sm hover:shadow-md transition-shadow ${
      isIdle ? 'border-gray-300 bg-gray-50' : 'border-border bg-card'
    }`}>
      {/* Time info header */}
      <div className="flex justify-between items-start mb-4 pb-4 border-b border-border">
        <div className="flex-1">
          <div className="text-sm text-muted-foreground flex items-center gap-2 flex-wrap">
            <Clock className="w-4 h-4" />
            <span>{formatTime(block.start)} - {formatTime(block.end)}</span>
            
            {isMerged && (
              <span className="px-2 py-0.5 bg-primary/20 text-primary text-xs font-semibold rounded">
                {block.block_count} blocks merged
              </span>
            )}
            
            {isIdle && (
              <span className="px-2 py-0.5 bg-gray-300 text-gray-700 text-xs font-semibold rounded">
                💤 Idle
              </span>
            )}
          </div>
          
          <div className="text-xs text-muted-foreground mt-2 space-y-1">
            <div className="flex items-center gap-2">
              <Timer className="w-3 h-3" />
              <span className="font-semibold">{block.duration_minutes} minutes active</span>
            </div>
            
            {hasSignificantSpan && (
              <div className="flex items-center gap-2 text-yellow-600">
                <Clock className="w-3 h-3" />
                <span>
                  Spanning {Math.round(block.span_minutes!)} min total 
                  <span className="text-xs ml-1">
                    (includes breaks/idle)
                  </span>
                </span>
              </div>
            )}
          </div>
        </div>
        
        <div className="text-right ml-4">
          <div className="text-2xl font-bold text-primary">
            {(block.duration_minutes / 60).toFixed(2)}h
          </div>
          {hasSignificantSpan && (
            <div className="text-xs text-muted-foreground mt-1">
              {(block.span_minutes! / 60).toFixed(1)}h span
            </div>
          )}
        </div>
      </div>

      {/* Activity details */}
      <div className="mb-4 space-y-2">
        {block.app_name && (
          <div className="text-sm flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[60px]">App:</span>
            <span className="text-foreground font-medium">{block.app_name}</span>
          </div>
        )}
        {block.window_title && (
          <div className="text-sm flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[60px]">Title:</span>
            <span className="text-foreground">{block.window_title}</span>
          </div>
        )}
        {urlDomain && (
          <div className="text-sm flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[60px]">Domain:</span>
            <span className="text-foreground">🌐 {urlDomain}</span>
          </div>
        )}
        {block.url && !urlDomain && (
          <div className="text-sm flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[60px]">URL:</span>
            <a 
              href={block.url} 
              target="_blank" 
              rel="noopener noreferrer" 
              className="text-primary hover:underline break-all text-xs"
            >
              {block.url}
            </a>
          </div>
        )}
        {block.file_path && (
          <div className="text-sm flex items-start gap-2">
            <span className="font-medium text-muted-foreground min-w-[60px]">File:</span>
            <span className="text-foreground break-all font-mono text-xs">📄 {block.file_path}</span>
          </div>
        )}
      </div>

      {/* AI Suggestions */}
      {block.suggestions && block.suggestions.length > 0 && (
        <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
          <div className="text-sm font-semibold text-yellow-900 mb-2 flex items-center gap-2">
            💡 AI Suggestions
          </div>
          <div className="space-y-2">
            {block.suggestions.map((suggestion, idx) => (
              <button
                key={idx}
                onClick={() => handleUseSuggestion(suggestion)}
                disabled={saving}
                className="text-sm text-left w-full hover:bg-yellow-100 p-2 rounded transition-colors flex items-center justify-between disabled:opacity-50"
              >
                <div>
                  {suggestion.client && <span className="font-semibold text-yellow-900">{suggestion.client}</span>}
                  {suggestion.category && <span className="text-yellow-800"> → {suggestion.category}</span>}
                </div>
                <span className="text-xs text-yellow-600 font-medium">
                  {(suggestion.confidence * 100).toFixed(0)}% confident
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Local Error */}
      {localError && (
        <div className="mb-4 bg-destructive/10 border border-destructive/30 rounded-lg p-3 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
          <span className="text-sm text-destructive">{localError}</span>
        </div>
      )}

      {/* Categorization form */}
      {!isEditing ? (
        // Quick categorization mode
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Client selector */}
            <div>
              <label className="block text-sm font-semibold text-foreground mb-2">
                Client <span className="text-muted-foreground font-normal">(Optional)</span>
              </label>
              <select
                value={selectedClient}
                onChange={(e) => setSelectedClient(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                disabled={saving}
              >
                <option value="">-- Select Client --</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name} {client.code && `(${client.code})`}
                  </option>
                ))}
              </select>
            </div>

            {/* Category selector */}
            <div>
              <label className="block text-sm font-semibold text-foreground mb-2">
                Category <span className="text-destructive">*</span>
              </label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                required
                disabled={saving}
              >
                <option value="">-- Select Category --</option>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleQuickSave}
              disabled={!selectedCategory || saving}
              className={`flex-1 px-6 py-3 rounded-lg font-semibold transition-all flex items-center justify-center gap-2 ${
                selectedCategory && !saving
                  ? 'bg-green-600 text-white hover:bg-green-700 shadow-sm hover:shadow-md'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
              }`}
            >
              {saving ? (
                <>
                  <Clock className="w-5 h-5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-5 h-5" />
                  ✓ Confirm
                </>
              )}
            </button>
            <button
              onClick={() => setIsEditing(true)}
              disabled={saving}
              className="px-6 py-3 border border-border rounded-lg font-semibold hover:bg-accent transition-colors flex items-center gap-2"
            >
              <Edit3 className="w-4 h-4" />
              Edit
            </button>
          </div>
        </div>
      ) : (
        // Edit mode with notes
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Client selector */}
            <div>
              <label className="block text-sm font-semibold text-foreground mb-2">
                Client <span className="text-muted-foreground font-normal">(Optional)</span>
              </label>
              <select
                value={selectedClient}
                onChange={(e) => setSelectedClient(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                disabled={saving}
              >
                <option value="">-- Select Client --</option>
                {clients.map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name} {client.code && `(${client.code})`}
                  </option>
                ))}
              </select>
            </div>

            {/* Category selector */}
            <div>
              <label className="block text-sm font-semibold text-foreground mb-2">
                Category <span className="text-destructive">*</span>
              </label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full border border-border rounded-lg px-3 py-2 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                required
                disabled={saving}
              >
                <option value="">-- Select Category --</option>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Notes field */}
          <div>
            <label className="block text-sm font-semibold text-foreground mb-2">
              Notes <span className="text-muted-foreground font-normal">(Optional)</span>
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add any notes about this time block..."
              className="w-full border border-border rounded-lg px-3 py-2 bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-primary min-h-[80px]"
              disabled={saving}
            />
          </div>

          {/* Action buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleEditSave}
              disabled={!selectedCategory || saving}
              className={`flex-1 px-6 py-3 rounded-lg font-semibold transition-all flex items-center justify-center gap-2 ${
                selectedCategory && !saving
                  ? 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm hover:shadow-md'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
              }`}
            >
              {saving ? (
                <>
                  <Clock className="w-5 h-5 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Save className="w-5 h-5" />
                  Save Changes
                </>
              )}
            </button>
            <button
              onClick={() => setIsEditing(false)}
              disabled={saving}
              className="px-6 py-3 border border-border rounded-lg font-semibold hover:bg-accent transition-colors flex items-center gap-2"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default BlockCard;