// src/components/ClientAssignmentManager.tsx

import { useState, useEffect } from 'react';
import {
  Users,
  Briefcase,
  Plus,
  Trash2,
  Upload,
  Copy,
  Search,
  Check,
  X,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Filter,
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface Assignment {
  id: number;
  client_id: number;
  client_name: string;
  client_code: string;
  user_id: number;
  user_name: string;
  user_email: string;
  role: string;
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
  const [selectedRole, setSelectedRole] = useState('staff');
  
  // Bulk actions
  const [showBulkCopy, setShowBulkCopy] = useState(false);
  const [copyFromUser, setCopyFromUser] = useState<number | null>(null);
  const [copyToUsers, setCopyToUsers] = useState<number[]>([]);
  
  // CSV import
  const [showImport, setShowImport] = useState(false);
  const [csvContent, setCsvContent] = useState('');

  useEffect(() => {
    loadAssignments();
  }, []);

  const loadAssignments = async () => {
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/settings/client-assignments/`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (response.ok) {
        const data = await response.json();
        setAssignments(data);
      }
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
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/settings/client-assignments/bulk/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          client_ids: selectedClients,
          user_ids: selectedUsers,
          role: selectedRole,
        }),
      });
      
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      
      onSuccess(`Created ${data.created} assignments (${data.skipped_duplicates} already existed)`);
      setShowAdd(false);
      setSelectedUsers([]);
      setSelectedClients([]);
      loadAssignments();
    } catch (err: any) {
      onError(err.message);
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
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/settings/client-assignments/bulk/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          copy_from_user_id: copyFromUser,
          to_user_ids: copyToUsers,
        }),
      });
      
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      
      onSuccess(`Copied ${data.created} assignments to ${copyToUsers.length} users`);
      setShowBulkCopy(false);
      setCopyFromUser(null);
      setCopyToUsers([]);
      loadAssignments();
    } catch (err: any) {
      onError(err.message);
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
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/settings/client-assignments/import/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ csv_content: csvContent }),
      });
      
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      
      let msg = `Imported ${data.created} assignments`;
      if (data.skipped_duplicates > 0) msg += ` (${data.skipped_duplicates} duplicates skipped)`;
      if (data.total_errors > 0) msg += ` (${data.total_errors} errors)`;
      
      onSuccess(msg);
      setShowImport(false);
      setCsvContent('');
      loadAssignments();
    } catch (err: any) {
      onError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (assignmentId: number) => {
    if (!confirm('Remove this assignment?')) return;
    
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/settings/client-assignments/${assignmentId}/`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` },
      });
      
      if (response.ok) {
        onSuccess('Assignment removed');
        loadAssignments();
      }
    } catch (err: any) {
      onError(err.message);
    }
  };

  // Filter assignments
  const filteredAssignments = assignments.filter(a => {
    if (filterUser && a.user_id !== parseInt(filterUser)) return false;
    if (filterClient && a.client_id !== parseInt(filterClient)) return false;
    return true;
  });

  // Group by user or client for display
  const groupedByUser = filteredAssignments.reduce((acc, a) => {
    if (!acc[a.user_id]) {
      acc[a.user_id] = { user_name: a.user_name, user_email: a.user_email, clients: [] };
    }
    acc[a.user_id].clients.push(a);
    return acc;
  }, {} as Record<number, { user_name: string; user_email: string; clients: Assignment[] }>);

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'lead': return 'bg-purple-100 text-purple-700';
      case 'manager': return 'bg-blue-100 text-blue-700';
      case 'reviewer': return 'bg-amber-100 text-amber-700';
      default: return 'bg-slate-100 text-slate-700';
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Users className="w-5 h-5 text-primary" />
          Client Assignments
          <span className="text-sm font-bold text-slate-500">({assignments.length})</span>
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
          >
            <Upload className="w-4 h-4" />
            Import CSV
          </button>
          <button
            onClick={() => setShowBulkCopy(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
          >
            <Copy className="w-4 h-4" />
            Copy From User
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25"
          >
            <Plus className="w-4 h-4" />
            Assign Clients
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4 mb-6">
        <div className="flex-1">
          <label className="block text-xs font-bold text-slate-600 mb-1">Filter by User</label>
          <select
            value={filterUser}
            onChange={(e) => setFilterUser(e.target.value)}
            className="w-full border-2 border-slate-200 rounded-lg px-3 py-2 text-sm font-medium"
          >
            <option value="">All Users</option>
            {users.map(u => (
              <option key={u.id} value={u.id}>
                {u.first_name} {u.last_name || u.username}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs font-bold text-slate-600 mb-1">Filter by Client</label>
          <select
            value={filterClient}
            onChange={(e) => setFilterClient(e.target.value)}
            className="w-full border-2 border-slate-200 rounded-lg px-3 py-2 text-sm font-medium"
          >
            <option value="">All Clients</option>
            {clients.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Assignment List - Grouped by User */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
      ) : Object.keys(groupedByUser).length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          <Users className="w-12 h-12 mx-auto mb-3 text-slate-300" />
          <p className="font-medium">No client assignments yet</p>
          <p className="text-sm mt-1">Assign clients to team members to restrict visibility</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(groupedByUser).map(([userId, data]) => (
            <div key={userId} className="border-2 border-slate-200 rounded-xl overflow-hidden">
              <div className="bg-slate-50 px-4 py-3 flex items-center justify-between">
                <div>
                  <p className="font-bold text-slate-900">{data.user_name}</p>
                  <p className="text-xs text-slate-500">{data.user_email}</p>
                </div>
                <span className="text-xs bg-slate-200 text-slate-700 px-2 py-1 rounded-full font-bold">
                  {data.clients.length} client(s)
                </span>
              </div>
              <div className="p-4">
                <div className="flex flex-wrap gap-2">
                  {data.clients.map(a => (
                    <div
                      key={a.id}
                      className="flex items-center gap-2 bg-slate-100 rounded-lg px-3 py-1.5 group"
                    >
                      <Briefcase className="w-3.5 h-3.5 text-slate-500" />
                      <span className="font-medium text-sm text-slate-800">
                        {a.client_name}
                        {a.client_code && <span className="text-slate-500 ml-1">({a.client_code})</span>}
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded font-bold ${getRoleBadgeColor(a.role)}`}>
                        {a.role}
                      </span>
                      <button
                        onClick={() => handleDelete(a.id)}
                        className="opacity-0 group-hover:opacity-100 p-1 text-red-500 hover:bg-red-100 rounded transition-all"
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

      {/* Bulk Assign Modal */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-extrabold text-slate-900">Assign Clients to Users</h3>
              <button onClick={() => setShowAdd(false)} className="p-2 hover:bg-slate-100 rounded-lg">
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="grid md:grid-cols-2 gap-6">
              {/* Select Users */}
              <div>
                <label className="block text-sm font-bold text-slate-700 mb-2">
                  Select Users ({selectedUsers.length})
                </label>
                <div className="border-2 border-slate-200 rounded-xl max-h-48 overflow-y-auto">
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
                        {u.first_name} {u.last_name || u.username}
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
                <label className="block text-sm font-bold text-slate-700 mb-2">
                  Select Clients ({selectedClients.length})
                </label>
                <div className="border-2 border-slate-200 rounded-xl max-h-48 overflow-y-auto">
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

            {/* Role Selection */}
            <div className="mt-4">
              <label className="block text-sm font-bold text-slate-700 mb-2">Role</label>
              <select
                value={selectedRole}
                onChange={(e) => setSelectedRole(e.target.value)}
                className="border-2 border-slate-200 rounded-xl px-4 py-2 font-medium"
              >
                <option value="staff">Staff</option>
                <option value="manager">Manager</option>
                <option value="lead">Engagement Lead</option>
                <option value="reviewer">Reviewer</option>
              </select>
            </div>

            {/* Summary */}
            <div className="mt-4 p-3 bg-slate-50 rounded-xl">
              <p className="text-sm text-slate-600 font-medium">
                This will create <span className="font-bold text-primary">{selectedUsers.length * selectedClients.length}</span> assignments
                ({selectedUsers.length} users × {selectedClients.length} clients)
              </p>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowAdd(false)}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkAssign}
                disabled={saving || selectedUsers.length === 0 || selectedClients.length === 0}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Create Assignments
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Copy From User Modal */}
      {showBulkCopy && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-lg w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-extrabold text-slate-900">Copy Assignments From User</h3>
              <button onClick={() => setShowBulkCopy(false)} className="p-2 hover:bg-slate-100 rounded-lg">
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-bold text-slate-700 mb-2">Copy FROM</label>
                <select
                  value={copyFromUser || ''}
                  onChange={(e) => setCopyFromUser(parseInt(e.target.value) || null)}
                  className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium"
                >
                  <option value="">Select user to copy from...</option>
                  {users.map(u => {
                    const count = assignments.filter(a => a.user_id === u.id).length;
                    return (
                      <option key={u.id} value={u.id}>
                        {u.first_name} {u.last_name || u.username} ({count} clients)
                      </option>
                    );
                  })}
                </select>
              </div>

              <div>
                <label className="block text-sm font-bold text-slate-700 mb-2">Copy TO</label>
                <div className="border-2 border-slate-200 rounded-xl max-h-48 overflow-y-auto">
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
                        {u.first_name} {u.last_name || u.username}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setShowBulkCopy(false)}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                onClick={handleCopyAssignments}
                disabled={saving || !copyFromUser || copyToUsers.length === 0}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Copy className="w-4 h-4" />}
                Copy Assignments
              </button>
            </div>
          </div>
        </div>
      )}

      {/* CSV Import Modal */}
      {showImport && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 max-w-lg w-full mx-4 shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xl font-extrabold text-slate-900">Import from CSV</h3>
              <button onClick={() => setShowImport(false)} className="p-2 hover:bg-slate-100 rounded-lg">
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            <div className="mb-4 p-3 bg-slate-50 rounded-xl">
              <p className="text-sm text-slate-600 font-medium mb-2">Expected CSV format:</p>
              <code className="text-xs text-slate-800 bg-slate-200 px-2 py-1 rounded block">
                user_email,client_code,role<br/>
                john@firm.com,ACME,staff<br/>
                jane@firm.com,ACME,lead
              </code>
            </div>

            <textarea
              value={csvContent}
              onChange={(e) => setCsvContent(e.target.value)}
              placeholder="Paste CSV content here..."
              rows={8}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
            />

            <div className="flex gap-3 mt-4">
              <button
                onClick={() => setShowImport(false)}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                onClick={handleImportCSV}
                disabled={saving || !csvContent.trim()}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                Import
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}