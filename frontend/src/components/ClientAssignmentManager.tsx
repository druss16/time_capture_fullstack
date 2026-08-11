// src/components/ClientAssignmentManager.tsx

import { useState, useEffect } from 'react';
import {
  Users,
  Briefcase,
  Plus,
  Upload,
  Copy,
  X,
  Loader2,
  Download,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';
import {
  SettingsPage,
  SettingsSection,
  inputClass,
  labelClass,
  primaryBtnClass,
  secondaryBtnClass,
} from '@/pages/settings/ui';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface Assignment {
  id: number;
  client_id: number;
  client_name: string;
  client_code: string;
  user_id: number;
  user_name: string;
  user_email: string;
  assigned_at: string;
}

interface User {
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
  visibility: string;
}

export default function ClientAssignmentManager({
  users,
  clients,
  onSuccess,
  onError,
}: {
  users: User[];
  clients: Client[];
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  
  // Filters
  const [filterUser, setFilterUser] = useState<string>('');
  const [filterClient, setFilterClient] = useState<string>('');
  
  // Add assignment modal
  const [showAdd, setShowAdd] = useState(false);
  const [selectedUsers, setSelectedUsers] = useState<number[]>([]);
  const [selectedClients, setSelectedClients] = useState<number[]>([]);
  
  // Bulk copy modal
  const [showBulkCopy, setShowBulkCopy] = useState(false);
  const [copyFromUser, setCopyFromUser] = useState<number | null>(null);
  const [copyToUsers, setCopyToUsers] = useState<number[]>([]);
  
  // CSV import modal
  const [showImport, setShowImport] = useState(false);
  const [csvContent, setCsvContent] = useState('');
  const [importResult, setImportResult] = useState<any>(null);

  useEffect(() => {
    loadAssignments();
  }, []);

  const loadAssignments = async () => {
    setLoading(true);
    try {
      const data = await safeFetchJson<Assignment[]>(`${API_BASE}/settings/client-assignments/`);
      setAssignments(data || []);
    } catch (err) {
      console.error('Failed to load assignments:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleBulkAssign = async () => {
    if (selectedUsers.length === 0 || selectedClients.length === 0) {
      onError('Select at least one user and one client');
      return;
    }
    
    setSaving(true);
    try {
      const data = await safeFetchJson(`${API_BASE}/settings/client-assignments/bulk/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_ids: selectedClients,
          user_ids: selectedUsers,
        }),
      });
      
      onSuccess(`Created ${data.created} assignments (${data.skipped_duplicates} already existed)`);
      setShowAdd(false);
      setSelectedUsers([]);
      setSelectedClients([]);
      loadAssignments();
    } catch (err: any) {
      onError(err.message || 'Failed to create assignments');
    } finally {
      setSaving(false);
    }
  };

  const handleCopyAssignments = async () => {
    if (!copyFromUser || copyToUsers.length === 0) {
      onError('Select a source user and target users');
      return;
    }
    
    setSaving(true);
    try {
      const data = await safeFetchJson(`${API_BASE}/settings/client-assignments/bulk/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          copy_from_user_id: copyFromUser,
          to_user_ids: copyToUsers,
        }),
      });
      
      onSuccess(`Copied ${data.created} assignments to ${copyToUsers.length} users`);
      setShowBulkCopy(false);
      setCopyFromUser(null);
      setCopyToUsers([]);
      loadAssignments();
    } catch (err: any) {
      onError(err.message || 'Failed to copy assignments');
    } finally {
      setSaving(false);
    }
  };

  const handleImportCSV = async () => {
    if (!csvContent.trim()) {
      onError('Paste CSV content');
      return;
    }
    
    setSaving(true);
    setImportResult(null);
    try {
      const data = await safeFetchJson(`${API_BASE}/settings/client-assignments/import/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_content: csvContent }),
      });
      
      setImportResult(data);
      
      if (data.created > 0) {
        onSuccess(`Imported ${data.created} assignments`);
        loadAssignments();
      }
    } catch (err: any) {
      onError(err.message || 'Failed to import');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (assignmentId: number) => {
    if (!confirm('Remove this access?')) return;
    
    try {
      await safeFetchJson(`${API_BASE}/settings/client-assignments/${assignmentId}/`, {
        method: 'DELETE',
      });
      onSuccess('Access removed');
      loadAssignments();
    } catch (err: any) {
      onError(err.message || 'Failed to remove');
    }
  };

  const downloadTemplate = () => {
    const template = 'email,client_code\njohn@yourfirm.com,ACME\njane@yourfirm.com,BIGCO';
    const blob = new Blob([template], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'client_assignments_template.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  // Filter assignments
  const filteredAssignments = assignments.filter(a => {
    if (filterUser && a.user_id !== parseInt(filterUser)) return false;
    if (filterClient && a.client_id !== parseInt(filterClient)) return false;
    return true;
  });

  // Group by user for display
  const groupedByUser = filteredAssignments.reduce((acc, a) => {
    if (!acc[a.user_id]) {
      acc[a.user_id] = { user_name: a.user_name, user_email: a.user_email, clients: [] };
    }
    acc[a.user_id].clients.push(a);
    return acc;
  }, {} as Record<number, { user_name: string; user_email: string; clients: Assignment[] }>);

  const getUserDisplayName = (u: User) => {
    const name = `${u.first_name || ''} ${u.last_name || ''}`.trim();
    return name || u.username || u.email;
  };

  return (
    <SettingsPage
      title="Client Access"
      subtitle="Control which team members can see and log time to each client"
      actions={
        <>
          <button onClick={() => setShowImport(true)} className={secondaryBtnClass}>
            <Upload className="w-4 h-4" />
            Import
          </button>
          <button onClick={() => setShowBulkCopy(true)} className={secondaryBtnClass}>
            <Copy className="w-4 h-4" />
            Copy From User
          </button>
          <button onClick={() => setShowAdd(true)} className={primaryBtnClass}>
            <Plus className="w-4 h-4" />
            Assign Clients
          </button>
        </>
      }
    >
      <div className="space-y-4">
      {/* Quick Info */}
      <div className="p-4 bg-blue-50 border border-blue-200/70 rounded-2xl">
        <p className="text-sm text-blue-700 font-medium">
          💡 <strong>How it works:</strong> Clients with "Assigned Only" visibility will only be visible to users listed here.
          Clients with "All Team Members" visibility are visible to everyone regardless of assignments.
        </p>
      </div>

      {/* Filters */}
      <SettingsSection>
        <div className="flex gap-4">
          <div className="flex-1">
            <label className={labelClass}>Filter by User</label>
            <select
              value={filterUser}
              onChange={(e) => setFilterUser(e.target.value)}
              className={inputClass}
            >
              <option value="">All Users</option>
              {users.map(u => (
                <option key={u.id} value={u.id}>{getUserDisplayName(u)}</option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label className={labelClass}>Filter by Client</label>
            <select
              value={filterClient}
              onChange={(e) => setFilterClient(e.target.value)}
              className={inputClass}
            >
              <option value="">All Clients</option>
              {clients.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
        </div>
      </SettingsSection>

      {/* Assignment List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
      ) : Object.keys(groupedByUser).length === 0 ? (
        <div className="text-center py-12 border-2 border-dashed border-slate-200 rounded-2xl">
          <Users className="w-12 h-12 mx-auto mb-3 text-slate-300" />
          <p className="font-bold text-slate-700">No client assignments yet</p>
          <p className="text-sm text-slate-500 mt-1">
            Assign clients to team members to control access
          </p>
          <button
            onClick={() => setShowAdd(true)}
            className={`${primaryBtnClass} mt-4`}
          >
            <Plus className="w-4 h-4" />
            Create First Assignment
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {Object.entries(groupedByUser).map(([userId, data]) => (
            <div key={userId} className="rounded-2xl border border-slate-200/70 overflow-hidden">
              <div className="bg-slate-50/80 px-4 py-3 flex items-center justify-between">
                <div>
                  <p className="font-bold text-slate-900">{data.user_name}</p>
                  <p className="text-xs text-slate-500">{data.user_email}</p>
                </div>
                <span className="text-xs bg-primary/10 text-primary px-2.5 py-1 rounded-full font-bold">
                  {data.clients.length} client(s)
                </span>
              </div>
              <div className="p-4">
                <div className="flex flex-wrap gap-2">
                  {data.clients.map(a => (
                    <div
                      key={a.id}
                      className="flex items-center gap-2 bg-slate-100 rounded-lg px-3 py-1.5 group hover:bg-slate-200 transition-colors"
                    >
                      <Briefcase className="w-3.5 h-3.5 text-slate-500" />
                      <span className="font-medium text-sm text-slate-800">
                        {a.client_name}
                        {a.client_code && (
                          <span className="text-slate-500 ml-1">({a.client_code})</span>
                        )}
                      </span>
                      <button
                        onClick={() => handleDelete(a.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 text-red-500 hover:bg-red-100 rounded transition-all"
                        title="Remove access"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      </div>

      {/* ================================================================ */}
      {/* Assign Clients Modal                                            */}
      {/* ================================================================ */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold text-slate-900">Assign Clients to Users</h3>
              <button onClick={() => setShowAdd(false)} className="p-2 hover:bg-slate-100 rounded-lg">
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="grid md:grid-cols-2 gap-6">
              {/* Select Users */}
              <div>
                <label className={labelClass}>
                  Select Users ({selectedUsers.length})
                </label>
                <div className="border border-slate-200/70 rounded-2xl max-h-48 overflow-y-auto">
                  {users.map(u => (
                    <label
                      key={u.id}
                      className="flex items-center gap-3 px-3 py-2 hover:bg-slate-50 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={selectedUsers.includes(u.id)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedUsers([...selectedUsers, u.id]);
                          } else {
                            setSelectedUsers(selectedUsers.filter(id => id !== u.id));
                          }
                        }}
                        className="w-4 h-4 text-primary rounded"
                      />
                      <span className="text-sm font-medium text-slate-800">
                        {getUserDisplayName(u)}
                      </span>
                    </label>
                  ))}
                </div>
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={() => setSelectedUsers(users.map(u => u.id))}
                    className="text-xs text-primary font-bold hover:underline"
                  >
                    Select All
                  </button>
                  <button
                    onClick={() => setSelectedUsers([])}
                    className="text-xs text-slate-500 font-bold hover:underline"
                  >
                    Clear
                  </button>
                </div>
              </div>

              {/* Select Clients */}
              <div>
                <label className={labelClass}>
                  Select Clients ({selectedClients.length})
                </label>
                <div className="border border-slate-200/70 rounded-2xl max-h-48 overflow-y-auto">
                  {clients.map(c => (
                    <label
                      key={c.id}
                      className="flex items-center gap-3 px-3 py-2 hover:bg-slate-50 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={selectedClients.includes(c.id)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedClients([...selectedClients, c.id]);
                          } else {
                            setSelectedClients(selectedClients.filter(id => id !== c.id));
                          }
                        }}
                        className="w-4 h-4 text-primary rounded"
                      />
                      <span className="text-sm font-medium text-slate-800">
                        {c.name}
                        {c.code && <span className="text-slate-500 ml-1">({c.code})</span>}
                      </span>
                    </label>
                  ))}
                </div>
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={() => setSelectedClients(clients.map(c => c.id))}
                    className="text-xs text-primary font-bold hover:underline"
                  >
                    Select All
                  </button>
                  <button
                    onClick={() => setSelectedClients([])}
                    className="text-xs text-slate-500 font-bold hover:underline"
                  >
                    Clear
                  </button>
                </div>
              </div>
            </div>

            {/* Summary */}
            <div className="mt-4 p-3 bg-slate-50 rounded-2xl">
              <p className="text-sm text-slate-600 font-medium">
                This will give <span className="font-bold text-primary">{selectedUsers.length}</span> user(s)
                access to <span className="font-bold text-primary">{selectedClients.length}</span> client(s)
              </p>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowAdd(false)}
                className={`${secondaryBtnClass} flex-1 justify-center`}
              >
                Cancel
              </button>
              <button
                onClick={handleBulkAssign}
                disabled={saving || selectedUsers.length === 0 || selectedClients.length === 0}
                className={`${primaryBtnClass} flex-1 justify-center`}
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                Create Assignments
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Copy From User Modal                                            */}
      {/* ================================================================ */}
      {showBulkCopy && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-lg w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold text-slate-900">Copy Client Access</h3>
              <button onClick={() => setShowBulkCopy(false)} className="p-2 hover:bg-slate-100 rounded-lg">
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <p className="text-sm text-slate-600 font-medium mb-4">
              Copy all client assignments from one user to other users. Great for onboarding new team members.
            </p>

            <div className="space-y-4">
              <div>
                <label className={labelClass}>Copy FROM</label>
                <select
                  value={copyFromUser || ''}
                  onChange={(e) => setCopyFromUser(parseInt(e.target.value) || null)}
                  className={inputClass}
                >
                  <option value="">Select user to copy from...</option>
                  {users.map(u => {
                    const count = assignments.filter(a => a.user_id === u.id).length;
                    return (
                      <option key={u.id} value={u.id}>
                        {getUserDisplayName(u)} ({count} clients)
                      </option>
                    );
                  })}
                </select>
              </div>

              <div>
                <label className={labelClass}>Copy TO</label>
                <div className="border border-slate-200/70 rounded-2xl max-h-48 overflow-y-auto">
                  {users.filter(u => u.id !== copyFromUser).map(u => (
                    <label
                      key={u.id}
                      className="flex items-center gap-3 px-3 py-2 hover:bg-slate-50 cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={copyToUsers.includes(u.id)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setCopyToUsers([...copyToUsers, u.id]);
                          } else {
                            setCopyToUsers(copyToUsers.filter(id => id !== u.id));
                          }
                        }}
                        className="w-4 h-4 text-primary rounded"
                      />
                      <span className="text-sm font-medium text-slate-800">
                        {getUserDisplayName(u)}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowBulkCopy(false)}
                className={`${secondaryBtnClass} flex-1 justify-center`}
              >
                Cancel
              </button>
              <button
                onClick={handleCopyAssignments}
                disabled={saving || !copyFromUser || copyToUsers.length === 0}
                className={`${primaryBtnClass} flex-1 justify-center`}
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Copy className="w-4 h-4" />}
                Copy Access
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* CSV Import Modal                                                */}
      {/* ================================================================ */}
      {showImport && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-lg w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold text-slate-900">Import from CSV</h3>
              <button onClick={() => { setShowImport(false); setImportResult(null); setCsvContent(''); }} className="p-2 hover:bg-slate-100 rounded-lg">
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="mb-4 p-4 bg-slate-50 rounded-2xl">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm text-slate-700 font-bold">Expected format:</p>
                <button
                  onClick={downloadTemplate}
                  className="text-xs text-primary font-bold hover:underline flex items-center gap-1"
                >
                  <Download className="w-3 h-3" />
                  Download Template
                </button>
              </div>
              <code className="text-xs text-slate-800 bg-slate-200 px-2 py-1 rounded block font-mono">
                email,client_code<br/>
                john@firm.com,ACME<br/>
                jane@firm.com,BIGCO
              </code>
              <p className="text-xs text-slate-500 mt-2">
                Flexible column names: email/user_email, client/client_code/client_name
              </p>
            </div>

            <textarea
              value={csvContent}
              onChange={(e) => setCsvContent(e.target.value)}
              placeholder="Paste your CSV here, or copy from Excel..."
              rows={8}
              className={`${inputClass} font-mono`}
            />

            {/* Import Results */}
            {importResult && (
              <div className={cn(
                'mt-4 p-4 rounded-2xl',
                importResult.created > 0 ? 'bg-emerald-50 border border-emerald-200/70' : 'bg-amber-50 border border-amber-200/70'
              )}>
                <p className="font-bold text-sm">
                  ✓ Created: {importResult.created} | Skipped (duplicates): {importResult.skipped_duplicates}
                </p>
                {importResult.errors?.length > 0 && (
                  <div className="mt-2 max-h-24 overflow-y-auto">
                    {importResult.errors.map((err: string, i: number) => (
                      <p key={i} className="text-xs text-red-600">{err}</p>
                    ))}
                    {importResult.total_errors > importResult.errors.length && (
                      <p className="text-xs text-red-600 font-bold">
                        ... and {importResult.total_errors - importResult.errors.length} more errors
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="flex gap-3 mt-4">
              <button
                onClick={() => { setShowImport(false); setImportResult(null); setCsvContent(''); }}
                className={`${secondaryBtnClass} flex-1 justify-center`}
              >
                {importResult ? 'Close' : 'Cancel'}
              </button>
              <button
                onClick={handleImportCSV}
                disabled={saving || !csvContent.trim()}
                className={`${primaryBtnClass} flex-1 justify-center`}
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                Import
              </button>
            </div>
          </div>
        </div>
      )}
    </SettingsPage>
  );
}