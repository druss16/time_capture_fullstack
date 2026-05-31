/**
 * BlockCard.tsx - Premium Block Categorization Card
 * Clean, modern design inspired by Laurel AI
 */
import { useState } from 'react';
import { 
  Clock, 
  CheckCircle2, 
  AlertCircle, 
  Edit3, 
  Save, 
  X, 
  Timer,
  Sparkles,
  Globe,
  FileText,
  Zap
} from 'lucide-react';

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
  internalCategories?: string[];  // ← ADD THIS
  onCategorize: (
    blockId: number, 
    blockIds: number[], 
    clientId: number | null, 
    category: string, 
    notes?: string
  ) => Promise<any>;
}

const BlockCard = ({ block, clients, categories, internalCategories, onCategorize }: BlockCardProps) => {
  const [isEditing, setIsEditing] = useState(false);
  const topSuggestion = block.suggestions?.[0];
  const suggestedClientObj = topSuggestion?.client
    ? clients.find(c => c.name === topSuggestion.client)
    : null;

  const [selectedClient, setSelectedClient] = useState<string>(
    block.current_client_id?.toString() ||
    suggestedClientObj?.id.toString() ||
    ''
  );
  const [selectedCategory, setSelectedCategory] = useState<string>(
    topSuggestion?.category || ''
  );
  const [notes, setNotes] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const selectedClientObj = clients.find(c => c.id.toString() === selectedClient);
  const activeCategories = (selectedClientObj?.name === 'Internal' && internalCategories)
    ? internalCategories
    : categories;

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
      setLocalError(error.message || 'Failed to save');
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
    return new Date(dateStr).toLocaleTimeString([], { 
      hour: '2-digit', 
      minute: '2-digit' 
    });
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
    <div className={`
      rounded-2xl border overflow-hidden
      transition-all duration-300
      hover:shadow-lg hover:-translate-y-0.5
      ${isIdle 
        ? 'border-border/50 bg-muted/30' 
        : 'border-border/50 bg-card shadow-sm'
      }
    `}>
      {/* Header */}
      <div className="px-5 py-4 border-b border-border/50 bg-gradient-to-r from-muted/30 to-transparent">
        <div className="flex items-start justify-between">
          <div className="space-y-1.5">
            {/* Time Range */}
            <div className="flex items-center gap-2 text-sm">
              <Clock className="w-4 h-4 text-muted-foreground" />
              <span className="font-semibold text-foreground">
                {formatTime(block.start)} — {formatTime(block.end)}
              </span>
            </div>
            
            {/* Badges */}
            <div className="flex items-center gap-2 flex-wrap">
              {isMerged && (
                <span className="
                  inline-flex items-center gap-1 
                  px-2 py-0.5 rounded-full 
                  bg-primary/10 text-primary 
                  text-xs font-semibold
                ">
                  <Zap className="w-3 h-3" />
                  {block.block_count} merged
                </span>
              )}
              
              {isIdle && (
                <span className="
                  inline-flex items-center gap-1 
                  px-2 py-0.5 rounded-full 
                  bg-muted text-muted-foreground 
                  text-xs font-semibold
                ">
                  💤 Idle
                </span>
              )}
              
              {hasSignificantSpan && (
                <span className="
                  inline-flex items-center gap-1 
                  px-2 py-0.5 rounded-full 
                  bg-warning/10 text-warning 
                  text-xs font-semibold
                ">
                  <Timer className="w-3 h-3" />
                  {Math.round(block.span_minutes!)}min span
                </span>
              )}
            </div>
          </div>
          
          {/* Hours */}
          <div className="text-right">
            <div className="text-2xl font-bold text-primary">
              {(block.duration_minutes / 60).toFixed(2)}
              <span className="text-sm font-medium text-muted-foreground ml-0.5">h</span>
            </div>
            <div className="text-xs text-muted-foreground">
              {block.duration_minutes} min
            </div>
          </div>
        </div>
      </div>

      {/* Activity Details */}
      <div className="px-5 py-4 space-y-2.5">
        {block.app_name && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
              <span className="text-sm">📱</span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Application
              </p>
              <p className="text-sm font-medium text-foreground truncate">
                {block.app_name}
              </p>
            </div>
          </div>
        )}
        
        {block.window_title && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
              <FileText className="w-4 h-4 text-muted-foreground" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Window
              </p>
              <p className="text-sm text-foreground truncate">
                {block.window_title}
              </p>
            </div>
          </div>
        )}
        
        {urlDomain && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
              <Globe className="w-4 h-4 text-muted-foreground" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                Domain
              </p>
              <p className="text-sm text-foreground truncate">
                {urlDomain}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* AI Suggestions */}
      {block.suggestions && block.suggestions.length > 0 && (
        <div className="px-5 pb-4">
          <div className="
            p-4 rounded-xl 
            bg-gradient-to-br from-amber-50 to-orange-50 
            border border-amber-200/50
          ">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles className="w-4 h-4 text-amber-600" />
              <span className="text-sm font-semibold text-amber-900">
                AI Suggestions
              </span>
            </div>
            <div className="space-y-2">
              {block.suggestions.map((suggestion, idx) => (
                <button
                  key={idx}
                  onClick={() => handleUseSuggestion(suggestion)}
                  disabled={saving}
                  className="
                    w-full text-left px-3 py-2.5 rounded-lg
                    bg-white/80 hover:bg-white
                    border border-amber-200/50 hover:border-amber-300
                    transition-all duration-200
                    disabled:opacity-50
                    group
                  "
                >
                  <div className="flex items-center justify-between">
                    <div className="truncate">
                      {suggestion.client && (
                        <span className="font-semibold text-amber-900">
                          {suggestion.client}
                        </span>
                      )}
                      {suggestion.category && (
                        <span className="text-amber-700">
                          {suggestion.client ? ' → ' : ''}{suggestion.category}
                        </span>
                      )}
                    </div>
                    <span className="
                      text-xs font-semibold px-2 py-0.5 rounded-full
                      bg-amber-100 text-amber-700
                      group-hover:bg-amber-200
                    ">
                      {(suggestion.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {localError && (
        <div className="px-5 pb-4">
          <div className="
            flex items-center gap-2 p-3 rounded-xl
            bg-destructive/10 border border-destructive/20
          ">
            <AlertCircle className="w-4 h-4 text-destructive flex-shrink-0" />
            <span className="text-sm text-destructive">{localError}</span>
          </div>
        </div>
      )}

      {/* Categorization Form */}
      <div className="px-5 pb-5">
        {!isEditing ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Client
                </label>
                <select
                  value={selectedClient}
                  onChange={(e) => setSelectedClient(e.target.value)}
                  disabled={saving}
                  className="
                    w-full px-3 py-2.5 rounded-xl
                    bg-muted/50 border border-border/50
                    text-sm font-medium text-foreground
                    transition-all duration-200
                    focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none
                    disabled:opacity-50
                  "
                >
                  <option value="">Select client...</option>
                  {clients.map((client) => (
                    <option key={client.id} value={client.id}>
                      {client.name} {client.code && `(${client.code})`}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Category <span className="text-destructive">*</span>
                </label>
                <select
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  disabled={saving}
                  className="
                    w-full px-3 py-2.5 rounded-xl
                    bg-muted/50 border border-border/50
                    text-sm font-medium text-foreground
                    transition-all duration-200
                    focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none
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

            <div className="flex gap-2">
              <button
                onClick={handleQuickSave}
                disabled={!selectedCategory || saving}
                className={`
                  flex-1 flex items-center justify-center gap-2
                  px-4 py-2.5 rounded-xl
                  text-sm font-semibold
                  transition-all duration-200
                  ${selectedCategory && !saving
                    ? 'bg-success text-success-foreground shadow-lg shadow-success/25 hover:shadow-xl hover:shadow-success/30'
                    : 'bg-muted text-muted-foreground cursor-not-allowed'
                  }
                `}
              >
                {saving ? (
                  <>
                    <div className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-4 h-4" />
                    Confirm
                  </>
                )}
              </button>
              <button
                onClick={() => setIsEditing(true)}
                disabled={saving}
                className="
                  px-4 py-2.5 rounded-xl
                  text-sm font-semibold
                  border border-border
                  text-muted-foreground hover:text-foreground hover:bg-muted
                  transition-all duration-200
                  flex items-center gap-2
                "
              >
                <Edit3 className="w-4 h-4" />
                Notes
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Client
                </label>
                <select
                  value={selectedClient}
                  onChange={(e) => setSelectedClient(e.target.value)}
                  disabled={saving}
                  className="
                    w-full px-3 py-2.5 rounded-xl
                    bg-muted/50 border border-border/50
                    text-sm font-medium text-foreground
                    transition-all duration-200
                    focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none
                    disabled:opacity-50
                  "
                >
                  <option value="">Select client...</option>
                  {clients.map((client) => (
                    <option key={client.id} value={client.id}>
                      {client.name} {client.code && `(${client.code})`}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  Category <span className="text-destructive">*</span>
                </label>
                <select
                  value={selectedCategory}
                  onChange={(e) => setSelectedCategory(e.target.value)}
                  disabled={saving}
                  className="
                    w-full px-3 py-2.5 rounded-xl
                    bg-muted/50 border border-border/50
                    text-sm font-medium text-foreground
                    transition-all duration-200
                    focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none
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

            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                Notes
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Add notes about this time entry..."
                disabled={saving}
                className="
                  w-full px-3 py-2.5 rounded-xl
                  bg-muted/50 border border-border/50
                  text-sm text-foreground
                  placeholder:text-muted-foreground/60
                  transition-all duration-200
                  focus:bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none
                  disabled:opacity-50
                  min-h-[80px] resize-none
                "
              />
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleEditSave}
                disabled={!selectedCategory || saving}
                className={`
                  flex-1 flex items-center justify-center gap-2
                  px-4 py-2.5 rounded-xl
                  text-sm font-semibold
                  transition-all duration-200
                  ${selectedCategory && !saving
                    ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30'
                    : 'bg-muted text-muted-foreground cursor-not-allowed'
                  }
                `}
              >
                {saving ? (
                  <>
                    <div className="w-4 h-4 border-2 border-current/30 border-t-current rounded-full animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="w-4 h-4" />
                    Save
                  </>
                )}
              </button>
              <button
                onClick={() => setIsEditing(false)}
                disabled={saving}
                className="
                  px-4 py-2.5 rounded-xl
                  text-sm font-semibold
                  border border-border
                  text-muted-foreground hover:text-foreground hover:bg-muted
                  transition-all duration-200
                  flex items-center gap-2
                "
              >
                <X className="w-4 h-4" />
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default BlockCard;
