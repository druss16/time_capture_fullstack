// src/components/BulkAssignmentTools.tsx
/**
 * Bulk Assignment Tools for Clients
 * - Bulk assign employees to multiple clients
 * - Import assignments from CSV
 * - Copy team from one client to others
 */

import React, { useState, useRef } from 'react';
import {
  X,
  Users,
  Upload,
  Download,
  Copy,
  CheckSquare,
  Square,
  MinusSquare,
  Loader2,
  AlertCircle,
  CheckCircle2,
  UserPlus,
  UserMinus,
  FileSpreadsheet,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// ============================================================================
// Types
// ============================================================================

interface TeamMember {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

interface Client {
  id: number;
  name: string;
  code: string;
}

interface BulkAssignModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedClients: Client[];
  users: TeamMember[];
  onSuccess: () => void;
}

interface CSVImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

interface CopyAssignmentsModalProps {
  isOpen: boolean;
  onClose: () => void;
  clients: Client[];
  onSuccess: () => void;
}

// ============================================================================
// Bulk Assign Modal
// ============================================================================

export function BulkAssignModal({ 
  isOpen, 
  onClose, 
  selectedClients, 
  users, 
  onSuccess 
}: BulkAssignModalProps) {
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [role, setRole] = useState('Staff');
  const [mode, setMode] = useState<'add' | 'replace'>('add');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const handleToggleUser = (userId: number) => {
    const newSelected = new Set(selectedUserIds);
    if (newSelected.has(userId)) {
      newSelected.delete(userId);
    } else {
      newSelected.add(userId);
    }
    setSelectedUserIds(newSelected);
  };

  const handleSelectAll = () => {
    if (selectedUserIds.size === users.length) {
      setSelectedUserIds(new Set());
    } else {
      setSelectedUserIds(new Set(users.map(u => u.id)));
    }
  };

  const handleSubmit = async () => {
    if (selectedUserIds.size === 0) {
      setError('Please select at least one employee');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await safeFetchJson(`${API_BASE}/clients/bulk-assign/`, {
        method: 'POST',
        body: JSON.stringify({
          client_ids: selectedClients.map(c => c.id),
          user_ids: Array.from(selectedUserIds),
          role,
          mode,
        }),
      });

      setResult(response);
      
      // Auto-close after success
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 2000);
      
    } catch (err: any) {
      setError(err.message || 'Failed to assign employees');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setSelectedUserIds(new Set());
    setRole('Staff');
    setMode('add');
    setError(null);
    setResult(null);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center">
              <UserPlus className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900">Bulk Assign Team</h2>
              <p className="text-sm text-slate-500 font-medium">
                {selectedClients.length} client{selectedClients.length !== 1 ? 's' : ''} selected
              </p>
            </div>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-slate-200 rounded-lg">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {result ? (
            // Success state
            <div className="text-center py-6">
              <CheckCircle2 className="w-16 h-16 text-emerald-500 mx-auto mb-4" />
              <h3 className="text-xl font-bold text-slate-900 mb-2">Assignment Complete!</h3>
              <p className="text-slate-600 font-medium">{result.summary}</p>
              <div className="mt-4 grid grid-cols-3 gap-4">
                <div className="bg-emerald-50 rounded-xl p-3">
                  <p className="text-2xl font-bold text-emerald-600">{result.created}</p>
                  <p className="text-sm text-emerald-700">Created</p>
                </div>
                <div className="bg-slate-50 rounded-xl p-3">
                  <p className="text-2xl font-bold text-slate-600">{result.updated}</p>
                  <p className="text-sm text-slate-700">Updated</p>
                </div>
                {result.removed > 0 && (
                  <div className="bg-amber-50 rounded-xl p-3">
                    <p className="text-2xl font-bold text-amber-600">{result.removed}</p>
                    <p className="text-sm text-amber-700">Removed</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <>
              {/* Selected Clients Preview */}
              <div className="mb-4">
                <h4 className="font-bold text-slate-900 mb-2">Assigning to:</h4>
                <div className="flex flex-wrap gap-2">
                  {selectedClients.slice(0, 5).map(client => (
                    <span key={client.id} className="px-3 py-1 bg-slate-100 rounded-full text-sm font-medium text-slate-700">
                      {client.name}
                    </span>
                  ))}
                  {selectedClients.length > 5 && (
                    <span className="px-3 py-1 bg-slate-200 rounded-full text-sm font-bold text-slate-600">
                      +{selectedClients.length - 5} more
                    </span>
                  )}
                </div>
              </div>

              {/* Role Selection */}
              <div className="mb-4">
                <label className="block font-bold text-slate-900 mb-2">Role</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full px-4 py-2.5 border-2 border-slate-200 rounded-xl font-medium focus:border-primary focus:outline-none"
                >
                  <option value="Partner">Partner</option>
                  <option value="Manager">Manager</option>
                  <option value="Senior">Senior</option>
                  <option value="Staff">Staff</option>
                  <option value="Admin">Admin</option>
                </select>
              </div>

              {/* Mode Selection */}
              <div className="mb-4">
                <label className="block font-bold text-slate-900 mb-2">Assignment Mode</label>
                <div className="flex gap-3">
                  <button
                    onClick={() => setMode('add')}
                    className={cn(
                      'flex-1 px-4 py-3 rounded-xl border-2 font-medium transition-all',
                      mode === 'add'
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                    )}
                  >
                    <UserPlus className="w-5 h-5 mx-auto mb-1" />
                    <span className="block text-sm">Add to existing</span>
                  </button>
                  <button
                    onClick={() => setMode('replace')}
                    className={cn(
                      'flex-1 px-4 py-3 rounded-xl border-2 font-medium transition-all',
                      mode === 'replace'
                        ? 'border-amber-500 bg-amber-50 text-amber-700'
                        : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                    )}
                  >
                    <Users className="w-5 h-5 mx-auto mb-1" />
                    <span className="block text-sm">Replace existing</span>
                  </button>
                </div>
                {mode === 'replace' && (
                  <p className="text-sm text-amber-600 mt-2 font-medium">
                    ⚠️ This will remove all existing team members from selected clients first
                  </p>
                )}
              </div>

              {/* Employee Selection */}
              <div className="mb-4">
                <div className="flex items-center justify-between mb-2">
                  <label className="font-bold text-slate-900">Select Employees</label>
                  <button
                    onClick={handleSelectAll}
                    className="text-sm text-primary hover:underline font-medium"
                  >
                    {selectedUserIds.size === users.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
                <div className="border-2 border-slate-200 rounded-xl max-h-48 overflow-y-auto">
                  {users.map(user => (
                    <button
                      key={user.id}
                      onClick={() => handleToggleUser(user.id)}
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 border-b border-slate-100 last:border-0"
                    >
                      {selectedUserIds.has(user.id) ? (
                        <CheckSquare className="w-5 h-5 text-primary" />
                      ) : (
                        <Square className="w-5 h-5 text-slate-300" />
                      )}
                      <div className="text-left">
                        <p className="font-bold text-slate-900">
                          {user.first_name} {user.last_name}
                        </p>
                        <p className="text-sm text-slate-500">{user.email || user.username}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              {error && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-500" />
                  <span className="text-red-700 font-medium">{error}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!result && (
          <div className="px-6 py-4 border-t-2 border-slate-200 bg-slate-50 flex justify-end gap-3">
            <button
              onClick={handleClose}
              className="px-4 py-2.5 text-slate-600 font-bold hover:bg-slate-200 rounded-xl"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={loading || selectedUserIds.size === 0}
              className="px-6 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <UserPlus className="w-5 h-5" />
              )}
              Assign {selectedUserIds.size} Employee{selectedUserIds.size !== 1 ? 's' : ''}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// CSV Import Modal
// ============================================================================

export function CSVImportModal({ isOpen, onClose, onSuccess }: CSVImportModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      setError(null);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const response = await safeFetchJson(`${API_BASE}/clients/assignment-template/`);
      
      // Create and download the CSV file
      const blob = new Blob([response.template], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'assignment_template.csv';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to download template:', err);
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${API_BASE}/clients/import-assignments/`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Import failed');
      }

      setResult(data);

      if (data.summary.errors === 0) {
        setTimeout(() => {
          onSuccess();
          handleClose();
        }, 3000);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to import assignments');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setFile(null);
    setError(null);
    setResult(null);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center">
              <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900">Import Assignments from CSV</h2>
              <p className="text-sm text-slate-500 font-medium">Bulk assign employees to clients</p>
            </div>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-slate-200 rounded-lg">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {result ? (
            // Results state
            <div>
              <div className="text-center mb-6">
                {result.summary.errors === 0 ? (
                  <CheckCircle2 className="w-16 h-16 text-emerald-500 mx-auto mb-4" />
                ) : (
                  <AlertCircle className="w-16 h-16 text-amber-500 mx-auto mb-4" />
                )}
                <h3 className="text-xl font-bold text-slate-900 mb-2">
                  {result.summary.errors === 0 ? 'Import Complete!' : 'Import Completed with Issues'}
                </h3>
              </div>

              {/* Summary Stats */}
              <div className="grid grid-cols-4 gap-3 mb-6">
                <div className="bg-slate-50 rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold text-slate-600">{result.summary.total_rows}</p>
                  <p className="text-xs text-slate-500 font-medium">Total Rows</p>
                </div>
                <div className="bg-emerald-50 rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold text-emerald-600">{result.summary.created}</p>
                  <p className="text-xs text-emerald-700 font-medium">Created</p>
                </div>
                <div className="bg-blue-50 rounded-xl p-3 text-center">
                  <p className="text-2xl font-bold text-blue-600">{result.summary.updated}</p>
                  <p className="text-xs text-blue-700 font-medium">Updated</p>
                </div>
                <div className={cn(
                  'rounded-xl p-3 text-center',
                  result.summary.errors > 0 ? 'bg-red-50' : 'bg-slate-50'
                )}>
                  <p className={cn(
                    'text-2xl font-bold',
                    result.summary.errors > 0 ? 'text-red-600' : 'text-slate-600'
                  )}>{result.summary.errors}</p>
                  <p className={cn(
                    'text-xs font-medium',
                    result.summary.errors > 0 ? 'text-red-700' : 'text-slate-500'
                  )}>Errors</p>
                </div>
              </div>

              {/* Error Details */}
              {result.results.errors.length > 0 && (
                <div className="mb-4">
                  <h4 className="font-bold text-red-800 mb-2 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4" />
                    Errors ({result.results.errors.length})
                  </h4>
                  <div className="bg-red-50 border border-red-200 rounded-xl max-h-40 overflow-y-auto">
                    {result.results.errors.map((err: any, idx: number) => (
                      <div key={idx} className="px-3 py-2 text-sm border-b border-red-100 last:border-0">
                        <span className="font-bold text-red-700">Row {err.row}:</span>{' '}
                        <span className="text-red-600">{err.error}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Created Details */}
              {result.results.created.length > 0 && (
                <div className="mb-4">
                  <h4 className="font-bold text-emerald-800 mb-2 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4" />
                    Created ({result.results.created.length})
                  </h4>
                  <div className="bg-emerald-50 border border-emerald-200 rounded-xl max-h-32 overflow-y-auto">
                    {result.results.created.slice(0, 10).map((item: any, idx: number) => (
                      <div key={idx} className="px-3 py-2 text-sm border-b border-emerald-100 last:border-0">
                        <span className="font-bold text-emerald-800">{item.employee}</span>
                        <span className="text-emerald-600"> → {item.client}</span>
                        <span className="text-emerald-500 ml-2">({item.role})</span>
                      </div>
                    ))}
                    {result.results.created.length > 10 && (
                      <div className="px-3 py-2 text-sm text-emerald-600 font-medium">
                        +{result.results.created.length - 10} more...
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            // Upload state
            <>
              {/* Template Download */}
              <div className="mb-6 p-4 bg-slate-50 rounded-xl border-2 border-slate-200">
                <h4 className="font-bold text-slate-900 mb-2">CSV Format</h4>
                <p className="text-sm text-slate-600 mb-3">
                  Your CSV should have columns: <code className="bg-slate-200 px-1 rounded">client_name</code>,{' '}
                  <code className="bg-slate-200 px-1 rounded">employee_email</code>,{' '}
                  <code className="bg-slate-200 px-1 rounded">role</code>
                </p>
                <button
                  onClick={handleDownloadTemplate}
                  className="flex items-center gap-2 px-4 py-2 bg-white border-2 border-slate-300 rounded-xl text-slate-700 font-bold hover:bg-slate-100"
                >
                  <Download className="w-4 h-4" />
                  Download Template
                </button>
              </div>

              {/* File Upload */}
              <div
                onClick={() => fileInputRef.current?.click()}
                className={cn(
                  'border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all',
                  file 
                    ? 'border-emerald-300 bg-emerald-50' 
                    : 'border-slate-300 hover:border-primary hover:bg-slate-50'
                )}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                {file ? (
                  <>
                    <FileSpreadsheet className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
                    <p className="font-bold text-emerald-800">{file.name}</p>
                    <p className="text-sm text-emerald-600">Click to change file</p>
                  </>
                ) : (
                  <>
                    <Upload className="w-12 h-12 text-slate-400 mx-auto mb-3" />
                    <p className="font-bold text-slate-700">Click to upload CSV file</p>
                    <p className="text-sm text-slate-500">or drag and drop</p>
                  </>
                )}
              </div>

              {error && (
                <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-500" />
                  <span className="text-red-700 font-medium">{error}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t-2 border-slate-200 bg-slate-50 flex justify-end gap-3">
          <button
            onClick={handleClose}
            className="px-4 py-2.5 text-slate-600 font-bold hover:bg-slate-200 rounded-xl"
          >
            {result ? 'Close' : 'Cancel'}
          </button>
          {!result && (
            <button
              onClick={handleUpload}
              disabled={loading || !file}
              className="px-6 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Upload className="w-5 h-5" />
              )}
              Import Assignments
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Copy Assignments Modal
// ============================================================================

export function CopyAssignmentsModal({ isOpen, onClose, clients, onSuccess }: CopyAssignmentsModalProps) {
  const [sourceClientId, setSourceClientId] = useState<number | null>(null);
  const [selectedTargetIds, setSelectedTargetIds] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<'add' | 'replace'>('add');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const handleToggleTarget = (clientId: number) => {
    if (clientId === sourceClientId) return; // Can't select source as target
    
    const newSelected = new Set(selectedTargetIds);
    if (newSelected.has(clientId)) {
      newSelected.delete(clientId);
    } else {
      newSelected.add(clientId);
    }
    setSelectedTargetIds(newSelected);
  };

  const handleSubmit = async () => {
    if (!sourceClientId) {
      setError('Please select a source client');
      return;
    }
    if (selectedTargetIds.size === 0) {
      setError('Please select at least one target client');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await safeFetchJson(`${API_BASE}/clients/copy-assignments/`, {
        method: 'POST',
        body: JSON.stringify({
          source_client_id: sourceClientId,
          target_client_ids: Array.from(selectedTargetIds),
          mode,
        }),
      });

      setResult(response);
      setTimeout(() => {
        onSuccess();
        handleClose();
      }, 2000);
    } catch (err: any) {
      setError(err.message || 'Failed to copy assignments');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    setSourceClientId(null);
    setSelectedTargetIds(new Set());
    setMode('add');
    setError(null);
    setResult(null);
    onClose();
  };

  if (!isOpen) return null;

  const sourceClient = clients.find(c => c.id === sourceClientId);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center">
              <Copy className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-900">Copy Team Assignments</h2>
              <p className="text-sm text-slate-500 font-medium">Copy team from one client to others</p>
            </div>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-slate-200 rounded-lg">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {result ? (
            <div className="text-center py-6">
              <CheckCircle2 className="w-16 h-16 text-emerald-500 mx-auto mb-4" />
              <h3 className="text-xl font-bold text-slate-900 mb-2">Assignments Copied!</h3>
              <p className="text-slate-600 font-medium">{result.summary}</p>
            </div>
          ) : (
            <>
              {/* Source Client Selection */}
              <div className="mb-4">
                <label className="block font-bold text-slate-900 mb-2">Copy team from:</label>
                <select
                  value={sourceClientId || ''}
                  onChange={(e) => {
                    setSourceClientId(Number(e.target.value));
                    setSelectedTargetIds(new Set()); // Reset targets
                  }}
                  className="w-full px-4 py-2.5 border-2 border-slate-200 rounded-xl font-medium focus:border-primary focus:outline-none"
                >
                  <option value="">Select source client...</option>
                  {clients.map(client => (
                    <option key={client.id} value={client.id}>{client.name}</option>
                  ))}
                </select>
              </div>

              {/* Target Client Selection */}
              {sourceClientId && (
                <div className="mb-4">
                  <label className="block font-bold text-slate-900 mb-2">
                    Copy to: ({selectedTargetIds.size} selected)
                  </label>
                  <div className="border-2 border-slate-200 rounded-xl max-h-48 overflow-y-auto">
                    {clients
                      .filter(c => c.id !== sourceClientId)
                      .map(client => (
                        <button
                          key={client.id}
                          onClick={() => handleToggleTarget(client.id)}
                          className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 border-b border-slate-100 last:border-0"
                        >
                          {selectedTargetIds.has(client.id) ? (
                            <CheckSquare className="w-5 h-5 text-primary" />
                          ) : (
                            <Square className="w-5 h-5 text-slate-300" />
                          )}
                          <span className="font-medium text-slate-900">{client.name}</span>
                        </button>
                      ))}
                  </div>
                </div>
              )}

              {/* Mode Selection */}
              {sourceClientId && selectedTargetIds.size > 0 && (
                <div className="mb-4">
                  <label className="block font-bold text-slate-900 mb-2">Mode</label>
                  <div className="flex gap-3">
                    <button
                      onClick={() => setMode('add')}
                      className={cn(
                        'flex-1 px-4 py-2 rounded-xl border-2 font-medium text-sm',
                        mode === 'add'
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-slate-200 text-slate-600'
                      )}
                    >
                      Add to existing
                    </button>
                    <button
                      onClick={() => setMode('replace')}
                      className={cn(
                        'flex-1 px-4 py-2 rounded-xl border-2 font-medium text-sm',
                        mode === 'replace'
                          ? 'border-amber-500 bg-amber-50 text-amber-700'
                          : 'border-slate-200 text-slate-600'
                      )}
                    >
                      Replace existing
                    </button>
                  </div>
                </div>
              )}

              {error && (
                <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-500" />
                  <span className="text-red-700 font-medium">{error}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!result && (
          <div className="px-6 py-4 border-t-2 border-slate-200 bg-slate-50 flex justify-end gap-3">
            <button
              onClick={handleClose}
              className="px-4 py-2.5 text-slate-600 font-bold hover:bg-slate-200 rounded-xl"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={loading || !sourceClientId || selectedTargetIds.size === 0}
              className="px-6 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Copy className="w-5 h-5" />
              )}
              Copy to {selectedTargetIds.size} Client{selectedTargetIds.size !== 1 ? 's' : ''}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Bulk Actions Toolbar
// ============================================================================

interface BulkActionsToolbarProps {
  selectedCount: number;
  onAssign: () => void;
  onUnassign: () => void;
  onClearSelection: () => void;
}

export function BulkActionsToolbar({ 
  selectedCount, 
  onAssign, 
  onUnassign,
  onClearSelection 
}: BulkActionsToolbarProps) {
  if (selectedCount === 0) return null;

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-900 text-white px-6 py-3 rounded-2xl shadow-2xl flex items-center gap-4 z-40 animate-in slide-in-from-bottom">
      <span className="font-bold">
        {selectedCount} client{selectedCount !== 1 ? 's' : ''} selected
      </span>
      
      <div className="w-px h-6 bg-slate-700" />
      
      <button
        onClick={onAssign}
        className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 rounded-xl font-bold transition-colors"
      >
        <UserPlus className="w-4 h-4" />
        Assign Team
      </button>
      
      <button
        onClick={onUnassign}
        className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 rounded-xl font-bold transition-colors"
      >
        <UserMinus className="w-4 h-4" />
        Remove Team
      </button>
      
      <button
        onClick={onClearSelection}
        className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
        title="Clear selection"
      >
        <X className="w-5 h-5" />
      </button>
    </div>
  );
}