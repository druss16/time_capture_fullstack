// src/components/ClientGroupManager.tsx
/**
 * Client Groups Manager - Organize clients into groups for bulk assignment
 * 
 * Key Features:
 * - Create/edit/delete groups
 * - Drag clients into groups or multi-select
 * - Assign entire team to a group with one click
 * - Import group assignments from CSV
 * - Visual overview of ungrouped clients
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Folder,
  FolderPlus,
  Users,
  Briefcase,
  Plus,
  Trash2,
  Pencil,
  X,
  Check,
  Loader2,
  Upload,
  Download,
  UserPlus,
  UserMinus,
  ChevronDown,
  ChevronRight,
  Search,
  AlertCircle,
  CheckCircle2,
  CheckSquare,
  Square,
  MinusSquare,
  Palette,
  Star,
  Tag,
  FileSpreadsheet,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// ============================================================================
// Types
// ============================================================================

interface ClientGroup {
  id: number;
  name: string;
  description: string;
  color: string;
  icon: string;
  client_count: number;
  client_ids: number[];
  default_assignee_ids: number[];
  created_at: string;
}

interface Client {
  id: number;
  name: string;
  code: string;
  is_active: boolean;
}

interface TeamMember {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
}

interface Props {
  users: TeamMember[];
  clients: Client[];
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

// ============================================================================
// Color & Icon Options
// ============================================================================

const COLORS = [
  { id: 'slate', bg: 'bg-slate-100', border: 'border-slate-300', text: 'text-slate-700', label: 'Gray' },
  { id: 'red', bg: 'bg-red-100', border: 'border-red-300', text: 'text-red-700', label: 'Red' },
  { id: 'orange', bg: 'bg-orange-100', border: 'border-orange-300', text: 'text-orange-700', label: 'Orange' },
  { id: 'amber', bg: 'bg-amber-100', border: 'border-amber-300', text: 'text-amber-700', label: 'Amber' },
  { id: 'emerald', bg: 'bg-emerald-100', border: 'border-emerald-300', text: 'text-emerald-700', label: 'Green' },
  { id: 'blue', bg: 'bg-blue-100', border: 'border-blue-300', text: 'text-blue-700', label: 'Blue' },
  { id: 'purple', bg: 'bg-purple-100', border: 'border-purple-300', text: 'text-purple-700', label: 'Purple' },
  { id: 'pink', bg: 'bg-pink-100', border: 'border-pink-300', text: 'text-pink-700', label: 'Pink' },
];

const ICONS = [
  { id: 'folder', icon: Folder, label: 'Folder' },
  { id: 'briefcase', icon: Briefcase, label: 'Briefcase' },
  { id: 'users', icon: Users, label: 'Team' },
  { id: 'star', icon: Star, label: 'Star' },
  { id: 'tag', icon: Tag, label: 'Tag' },
];

const getColorClasses = (colorId: string) => {
  return COLORS.find(c => c.id === colorId) || COLORS[0];
};

const getIconComponent = (iconId: string) => {
  const found = ICONS.find(i => i.id === iconId);
  return found ? found.icon : Folder;
};

const getUserDisplayName = (user: TeamMember): string => {
  const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim();
  return fullName || user.username || user.email || `User ${user.id}`;
};

// ============================================================================
// Main Component
// ============================================================================

export default function ClientGroupManager({ users, clients, onSuccess, onError }: Props) {
  const [groups, setGroups] = useState<ClientGroup[]>([]);
  const [ungroupedClients, setUngroupedClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  
  // UI State
  const [expandedGroupId, setExpandedGroupId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  
  // Modals
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [editingGroup, setEditingGroup] = useState<ClientGroup | null>(null);
  const [assignTeamGroup, setAssignTeamGroup] = useState<ClientGroup | null>(null);
  const [addClientsGroup, setAddClientsGroup] = useState<ClientGroup | null>(null);
  const [showImportCSV, setShowImportCSV] = useState(false);

  // ============================================================================
  // Data Loading
  // ============================================================================

  const loadGroups = useCallback(async () => {
    setLoading(true);
    try {
      const [groupsData, ungroupedData] = await Promise.all([
        safeFetchJson<{ groups: ClientGroup[] }>(`${API_BASE}/settings/client-groups/`),
        safeFetchJson<{ clients: Client[] }>(`${API_BASE}/settings/clients/ungrouped/`).catch(() => ({ clients: [] })),
      ]);
      
      setGroups(groupsData.groups || []);
      setUngroupedClients(ungroupedData.clients || []);
    } catch (err) {
      console.error('Failed to load groups:', err);
      onError('Failed to load client groups');
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    loadGroups();
  }, [loadGroups]);

  // ============================================================================
  // Group CRUD
  // ============================================================================

  const handleCreateGroup = async (data: { name: string; description: string; color: string; icon: string }) => {
    setSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/client-groups/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      
      onSuccess(`Group "${data.name}" created`);
      setShowCreateGroup(false);
      loadGroups();
    } catch (err: any) {
      onError(err.message || 'Failed to create group');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateGroup = async (groupId: number, data: Partial<ClientGroup>) => {
    setSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/client-groups/${groupId}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      
      onSuccess('Group updated');
      setEditingGroup(null);
      loadGroups();
    } catch (err: any) {
      onError(err.message || 'Failed to update group');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteGroup = async (group: ClientGroup) => {
    if (!confirm(`Delete group "${group.name}"? This won't delete the clients, just the group.`)) return;
    
    try {
      await safeFetchJson(`${API_BASE}/settings/client-groups/${group.id}/`, {
        method: 'DELETE',
      });
      
      onSuccess(`Group "${group.name}" deleted`);
      loadGroups();
    } catch (err: any) {
      onError(err.message || 'Failed to delete group');
    }
  };

  // ============================================================================
  // Team Assignment
  // ============================================================================

  const handleAssignTeam = async (groupId: number, userIds: number[], mode: 'add' | 'replace') => {
    setSaving(true);
    try {
      const result = await safeFetchJson<any>(`${API_BASE}/settings/client-groups/${groupId}/assign-team/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_ids: userIds, mode }),
      });
      
      onSuccess(result.message || `Assigned ${userIds.length} users to ${result.clients_affected} clients`);
      setAssignTeamGroup(null);
      loadGroups();
    } catch (err: any) {
      onError(err.message || 'Failed to assign team');
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveTeamFromGroup = async (group: ClientGroup) => {
    if (!confirm(`Remove ALL team assignments from clients in "${group.name}"?`)) return;
    
    try {
      const result = await safeFetchJson<any>(`${API_BASE}/settings/client-groups/${group.id}/remove-team/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_ids: [] }), // Empty = remove all
      });
      
      onSuccess(`Removed ${result.assignments_removed} assignments`);
    } catch (err: any) {
      onError(err.message || 'Failed to remove team');
    }
  };

  // ============================================================================
  // Add Clients to Group
  // ============================================================================

  const handleAddClientsToGroup = async (groupId: number, clientIds: number[]) => {
    setSaving(true);
    try {
      const result = await safeFetchJson<any>(`${API_BASE}/settings/client-groups/${groupId}/add-clients/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_ids: clientIds }),
      });
      
      onSuccess(result.message || `Added ${result.added} clients`);
      setAddClientsGroup(null);
      loadGroups();
    } catch (err: any) {
      onError(err.message || 'Failed to add clients');
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveClientFromGroup = async (groupId: number, clientId: number) => {
    try {
      await safeFetchJson(`${API_BASE}/settings/client-groups/${groupId}/remove-clients/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_ids: [clientId] }),
      });
      
      onSuccess('Client removed from group');
      loadGroups();
    } catch (err: any) {
      onError(err.message || 'Failed to remove client');
    }
  };

  // ============================================================================
  // Filtered Data
  // ============================================================================

  const filteredGroups = groups.filter(g => 
    g.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    g.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const totalClientsInGroups = groups.reduce((sum, g) => sum + g.client_count, 0);
  const totalAssigned = new Set(groups.flatMap(g => g.client_ids)).size; // Unique clients

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
            <Folder className="w-5 h-5 text-primary" />
            Client Groups
            <span className="text-sm font-bold text-slate-500">({groups.length})</span>
          </h2>
          <p className="text-sm text-slate-500 font-medium mt-1">
            Organize clients into groups for easy bulk team assignment
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowImportCSV(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
          >
            <Upload className="w-4 h-4" />
            Import CSV
          </button>
          <button
            onClick={() => setShowCreateGroup(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25"
          >
            <FolderPlus className="w-4 h-4" />
            New Group
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-slate-50 border-2 border-slate-200 rounded-xl p-4">
          <p className="text-2xl font-extrabold text-slate-900">{groups.length}</p>
          <p className="text-sm text-slate-500 font-bold">Groups</p>
        </div>
        <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-4">
          <p className="text-2xl font-extrabold text-emerald-700">{totalAssigned}</p>
          <p className="text-sm text-emerald-600 font-bold">Clients Grouped</p>
        </div>
        <div className="bg-amber-50 border-2 border-amber-200 rounded-xl p-4">
          <p className="text-2xl font-extrabold text-amber-700">{ungroupedClients.length}</p>
          <p className="text-sm text-amber-600 font-bold">Ungrouped</p>
        </div>
        <div className="bg-blue-50 border-2 border-blue-200 rounded-xl p-4">
          <p className="text-2xl font-extrabold text-blue-700">{clients.length}</p>
          <p className="text-sm text-blue-600 font-bold">Total Clients</p>
        </div>
      </div>

      {/* Search */}
      <div className="relative mb-6">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search groups..."
          className="w-full pl-12 pr-4 py-3 border-2 border-slate-200 rounded-xl text-slate-900 font-medium focus:border-primary focus:outline-none"
        />
      </div>

      {/* Groups List */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
      ) : filteredGroups.length === 0 ? (
        <div className="text-center py-12 border-2 border-dashed border-slate-200 rounded-xl">
          <Folder className="w-12 h-12 mx-auto mb-3 text-slate-300" />
          <p className="font-bold text-slate-700">No client groups yet</p>
          <p className="text-sm text-slate-500 mt-1">
            Create groups to organize clients and assign teams in bulk
          </p>
          <button
            onClick={() => setShowCreateGroup(true)}
            className="mt-4 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90"
          >
            <FolderPlus className="w-4 h-4 inline mr-2" />
            Create First Group
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredGroups.map((group) => {
            const color = getColorClasses(group.color);
            const IconComponent = getIconComponent(group.icon);
            const isExpanded = expandedGroupId === group.id;
            const groupClients = clients.filter(c => group.client_ids.includes(c.id));
            
            return (
              <div
                key={group.id}
                className={cn(
                  'border-2 rounded-xl overflow-hidden transition-all',
                  color.border,
                  isExpanded ? 'shadow-lg' : ''
                )}
              >
                {/* Group Header */}
                <div
                  className={cn(
                    'flex items-center justify-between px-4 py-3 cursor-pointer transition-colors',
                    color.bg,
                    'hover:opacity-90'
                  )}
                  onClick={() => setExpandedGroupId(isExpanded ? null : group.id)}
                >
                  <div className="flex items-center gap-3">
                    <button className="p-1">
                      {isExpanded ? (
                        <ChevronDown className={cn('w-5 h-5', color.text)} />
                      ) : (
                        <ChevronRight className={cn('w-5 h-5', color.text)} />
                      )}
                    </button>
                    <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center', color.bg, 'border', color.border)}>
                      <IconComponent className={cn('w-5 h-5', color.text)} />
                    </div>
                    <div>
                      <p className="font-bold text-slate-900">{group.name}</p>
                      {group.description && (
                        <p className="text-xs text-slate-500">{group.description}</p>
                      )}
                    </div>
                    <span className={cn('ml-2 px-2.5 py-1 rounded-full text-xs font-bold', color.bg, color.text, 'border', color.border)}>
                      {group.client_count} client{group.client_count !== 1 ? 's' : ''}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => setAssignTeamGroup(group)}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg text-sm font-bold hover:opacity-90 shadow-sm"
                    >
                      <UserPlus className="w-4 h-4" />
                      Assign Team
                    </button>
                    <button
                      onClick={() => setAddClientsGroup(group)}
                      className="p-2 hover:bg-white/50 rounded-lg transition-colors"
                      title="Add clients"
                    >
                      <Plus className={cn('w-4 h-4', color.text)} />
                    </button>
                    <button
                      onClick={() => setEditingGroup(group)}
                      className="p-2 hover:bg-white/50 rounded-lg transition-colors"
                      title="Edit group"
                    >
                      <Pencil className={cn('w-4 h-4', color.text)} />
                    </button>
                    <button
                      onClick={() => handleDeleteGroup(group)}
                      className="p-2 hover:bg-red-100 rounded-lg transition-colors"
                      title="Delete group"
                    >
                      <Trash2 className="w-4 h-4 text-red-500" />
                    </button>
                  </div>
                </div>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="bg-white p-4 border-t border-slate-200">
                    {groupClients.length === 0 ? (
                      <div className="text-center py-6">
                        <Briefcase className="w-10 h-10 mx-auto mb-2 text-slate-300" />
                        <p className="text-slate-500 font-medium">No clients in this group yet</p>
                        <button
                          onClick={() => setAddClientsGroup(group)}
                          className="mt-2 text-primary font-bold text-sm hover:underline"
                        >
                          + Add clients
                        </button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {groupClients.map((client) => (
                          <div
                            key={client.id}
                            className="flex items-center gap-2 bg-slate-100 rounded-lg px-3 py-1.5 group hover:bg-slate-200 transition-colors"
                          >
                            <Briefcase className="w-3.5 h-3.5 text-slate-500" />
                            <span className="font-medium text-sm text-slate-800">
                              {client.name}
                              {client.code && (
                                <span className="text-slate-500 ml-1">({client.code})</span>
                              )}
                            </span>
                            <button
                              onClick={() => handleRemoveClientFromGroup(group.id, client.id)}
                              className="opacity-0 group-hover:opacity-100 p-1 text-red-500 hover:bg-red-100 rounded transition-all"
                              title="Remove from group"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Ungrouped Clients Section */}
      {ungroupedClients.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-bold text-slate-900 mb-4 flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-amber-500" />
            Ungrouped Clients
            <span className="text-sm font-bold text-amber-600">({ungroupedClients.length})</span>
          </h3>
          <div className="border-2 border-amber-200 bg-amber-50 rounded-xl p-4">
            <div className="flex flex-wrap gap-2">
              {ungroupedClients.slice(0, 20).map((client) => (
                <div
                  key={client.id}
                  className="flex items-center gap-2 bg-white border border-amber-200 rounded-lg px-3 py-1.5"
                >
                  <Briefcase className="w-3.5 h-3.5 text-amber-600" />
                  <span className="font-medium text-sm text-slate-800">
                    {client.name}
                    {client.code && <span className="text-slate-500 ml-1">({client.code})</span>}
                  </span>
                </div>
              ))}
              {ungroupedClients.length > 20 && (
                <span className="text-sm text-amber-700 font-bold px-3 py-1.5">
                  +{ungroupedClients.length - 20} more...
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* Create/Edit Group Modal                                          */}
      {/* ================================================================ */}
      {(showCreateGroup || editingGroup) && (
        <GroupFormModal
          group={editingGroup}
          onSave={(data) => {
            if (editingGroup) {
              handleUpdateGroup(editingGroup.id, data);
            } else {
              handleCreateGroup(data);
            }
          }}
          onClose={() => {
            setShowCreateGroup(false);
            setEditingGroup(null);
          }}
          saving={saving}
        />
      )}

      {/* ================================================================ */}
      {/* Assign Team Modal                                                */}
      {/* ================================================================ */}
      {assignTeamGroup && (
        <AssignTeamModal
          group={assignTeamGroup}
          users={users}
          onAssign={(userIds, mode) => handleAssignTeam(assignTeamGroup.id, userIds, mode)}
          onClose={() => setAssignTeamGroup(null)}
          saving={saving}
        />
      )}

      {/* ================================================================ */}
      {/* Add Clients Modal                                                */}
      {/* ================================================================ */}
      {addClientsGroup && (
        <AddClientsModal
          group={addClientsGroup}
          clients={clients}
          onAdd={(clientIds) => handleAddClientsToGroup(addClientsGroup.id, clientIds)}
          onClose={() => setAddClientsGroup(null)}
          saving={saving}
        />
      )}

      {/* ================================================================ */}
      {/* Import CSV Modal                                                 */}
      {/* ================================================================ */}
      {showImportCSV && (
        <ImportCSVModal
          onImport={async (csvContent) => {
            setSaving(true);
            try {
              const result = await safeFetchJson<any>(`${API_BASE}/settings/client-groups/import/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ csv_content: csvContent }),
              });
              
              onSuccess(`Created ${result.groups_created} groups, ${result.assignments_made} assignments`);
              setShowImportCSV(false);
              loadGroups();
              return result;
            } catch (err: any) {
              onError(err.message || 'Import failed');
              throw err;
            } finally {
              setSaving(false);
            }
          }}
          onClose={() => setShowImportCSV(false)}
          saving={saving}
        />
      )}
    </div>
  );
}

// ============================================================================
// Group Form Modal
// ============================================================================

function GroupFormModal({ 
  group, 
  onSave, 
  onClose, 
  saving 
}: { 
  group: ClientGroup | null;
  onSave: (data: { name: string; description: string; color: string; icon: string }) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [name, setName] = useState(group?.name || '');
  const [description, setDescription] = useState(group?.description || '');
  const [color, setColor] = useState(group?.color || 'slate');
  const [icon, setIcon] = useState(group?.icon || 'folder');

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-xl font-extrabold text-slate-900">
            {group ? 'Edit Group' : 'Create Group'}
          </h3>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Group Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Partner: Smith"
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-medium focus:border-primary focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Description</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description"
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-medium focus:border-primary focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Color</label>
            <div className="flex flex-wrap gap-2">
              {COLORS.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setColor(c.id)}
                  className={cn(
                    'w-10 h-10 rounded-xl border-2 transition-all',
                    c.bg,
                    color === c.id ? 'ring-2 ring-offset-2 ring-primary border-primary' : c.border
                  )}
                  title={c.label}
                />
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Icon</label>
            <div className="flex gap-2">
              {ICONS.map((i) => {
                const IconComp = i.icon;
                return (
                  <button
                    key={i.id}
                    onClick={() => setIcon(i.id)}
                    className={cn(
                      'w-10 h-10 rounded-xl border-2 flex items-center justify-center transition-all',
                      icon === i.id ? 'border-primary bg-primary/10 text-primary' : 'border-slate-200 text-slate-500 hover:border-slate-300'
                    )}
                    title={i.label}
                  >
                    <IconComp className="w-5 h-5" />
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave({ name, description, color, icon })}
            disabled={saving || !name.trim()}
            className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            {group ? 'Update' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Assign Team Modal
// ============================================================================

function AssignTeamModal({
  group,
  users,
  onAssign,
  onClose,
  saving,
}: {
  group: ClientGroup;
  users: TeamMember[];
  onAssign: (userIds: number[], mode: 'add' | 'replace') => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [mode, setMode] = useState<'add' | 'replace'>('add');
  const [search, setSearch] = useState('');

  const filteredUsers = users.filter(u => {
    const name = getUserDisplayName(u).toLowerCase();
    const email = u.email?.toLowerCase() || '';
    const query = search.toLowerCase();
    return name.includes(query) || email.includes(query);
  });

  const toggleUser = (userId: number) => {
    const newSelected = new Set(selectedUserIds);
    if (newSelected.has(userId)) {
      newSelected.delete(userId);
    } else {
      newSelected.add(userId);
    }
    setSelectedUserIds(newSelected);
  };

  const toggleAll = () => {
    if (selectedUserIds.size === filteredUsers.length) {
      setSelectedUserIds(new Set());
    } else {
      setSelectedUserIds(new Set(filteredUsers.map(u => u.id)));
    }
  };

  const color = getColorClasses(group.color);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden">
        <div className={cn('px-6 py-4 border-b-2', color.bg, color.border)}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center border', color.border, color.bg)}>
                <UserPlus className={cn('w-5 h-5', color.text)} />
              </div>
              <div>
                <h3 className="font-bold text-slate-900">Assign Team to "{group.name}"</h3>
                <p className="text-sm text-slate-500">{group.client_count} clients will be affected</p>
              </div>
            </div>
            <button onClick={onClose} className="p-2 hover:bg-white/50 rounded-lg">
              <X className="w-5 h-5 text-slate-500" />
            </button>
          </div>
        </div>

        <div className="p-6">
          {/* Mode Selection */}
          <div className="mb-4">
            <label className="block text-sm font-bold text-slate-800 mb-2">Assignment Mode</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => setMode('add')}
                className={cn(
                  'p-3 border-2 rounded-xl text-left transition-all',
                  mode === 'add' ? 'border-primary bg-primary/5' : 'border-slate-200 hover:border-slate-300'
                )}
              >
                <div className="flex items-center gap-2 mb-1">
                  <UserPlus className={cn('w-4 h-4', mode === 'add' ? 'text-primary' : 'text-slate-500')} />
                  <span className={cn('font-bold text-sm', mode === 'add' ? 'text-primary' : 'text-slate-700')}>Add</span>
                </div>
                <p className="text-xs text-slate-500">Keep existing, add selected</p>
              </button>
              <button
                onClick={() => setMode('replace')}
                className={cn(
                  'p-3 border-2 rounded-xl text-left transition-all',
                  mode === 'replace' ? 'border-primary bg-primary/5' : 'border-slate-200 hover:border-slate-300'
                )}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Users className={cn('w-4 h-4', mode === 'replace' ? 'text-primary' : 'text-slate-500')} />
                  <span className={cn('font-bold text-sm', mode === 'replace' ? 'text-primary' : 'text-slate-700')}>Replace</span>
                </div>
                <p className="text-xs text-slate-500">Remove existing, set to selected only</p>
              </button>
            </div>
          </div>

          {/* Search */}
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search team members..."
              className="w-full pl-10 pr-4 py-2 border-2 border-slate-200 rounded-xl text-sm font-medium focus:border-primary focus:outline-none"
            />
          </div>

          {/* Select All */}
          <button
            onClick={toggleAll}
            className="flex items-center gap-2 px-3 py-2 mb-2 hover:bg-slate-50 rounded-lg transition-colors"
          >
            {selectedUserIds.size === filteredUsers.length && filteredUsers.length > 0 ? (
              <CheckSquare className="w-5 h-5 text-primary" />
            ) : selectedUserIds.size > 0 ? (
              <MinusSquare className="w-5 h-5 text-primary" />
            ) : (
              <Square className="w-5 h-5 text-slate-400" />
            )}
            <span className="text-sm font-bold text-slate-700">
              Select All ({filteredUsers.length})
            </span>
          </button>

          {/* User List */}
          <div className="border-2 border-slate-200 rounded-xl max-h-64 overflow-y-auto">
            {filteredUsers.map((user) => {
              const displayName = getUserDisplayName(user);
              return (
                <button
                  key={user.id}
                  onClick={() => toggleUser(user.id)}
                  className={cn(
                    'w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors border-b border-slate-100 last:border-b-0',
                    selectedUserIds.has(user.id) && 'bg-primary/5'
                  )}
                >
                  {selectedUserIds.has(user.id) ? (
                    <CheckSquare className="w-5 h-5 text-primary flex-shrink-0" />
                  ) : (
                    <Square className="w-5 h-5 text-slate-400 flex-shrink-0" />
                  )}
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <span className="text-xs font-bold text-primary">{displayName[0].toUpperCase()}</span>
                  </div>
                  <div className="flex-1 text-left">
                    <p className="font-bold text-slate-900 text-sm">{displayName}</p>
                    <p className="text-xs text-slate-500">{user.email || `@${user.username}`}</p>
                  </div>
                </button>
              );
            })}
          </div>

          {selectedUserIds.size > 0 && (
            <p className="mt-2 text-sm text-primary font-bold">
              {selectedUserIds.size} member{selectedUserIds.size !== 1 ? 's' : ''} selected
            </p>
          )}
        </div>

        <div className="flex gap-3 px-6 py-4 border-t-2 border-slate-200 bg-slate-50">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
          >
            Cancel
          </button>
          <button
            onClick={() => onAssign(Array.from(selectedUserIds), mode)}
            disabled={saving || selectedUserIds.size === 0}
            className="flex-1 px-4 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
            Assign to {group.client_count} Clients
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Add Clients Modal
// ============================================================================

function AddClientsModal({
  group,
  clients,
  onAdd,
  onClose,
  saving,
}: {
  group: ClientGroup;
  clients: Client[];
  onAdd: (clientIds: number[]) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState('');

  // Filter out clients already in the group
  const availableClients = clients.filter(c => !group.client_ids.includes(c.id));
  
  const filteredClients = availableClients.filter(c => {
    const query = search.toLowerCase();
    return c.name.toLowerCase().includes(query) || (c.code?.toLowerCase() || '').includes(query);
  });

  const toggleClient = (clientId: number) => {
    const newSelected = new Set(selectedIds);
    if (newSelected.has(clientId)) {
      newSelected.delete(clientId);
    } else {
      newSelected.add(clientId);
    }
    setSelectedIds(newSelected);
  };

  const toggleAll = () => {
    if (selectedIds.size === filteredClients.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredClients.map(c => c.id)));
    }
  };

  const color = getColorClasses(group.color);

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden">
        <div className={cn('px-6 py-4 border-b-2', color.bg, color.border)}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center border', color.border, color.bg)}>
                <Plus className={cn('w-5 h-5', color.text)} />
              </div>
              <div>
                <h3 className="font-bold text-slate-900">Add Clients to "{group.name}"</h3>
                <p className="text-sm text-slate-500">{availableClients.length} clients available</p>
              </div>
            </div>
            <button onClick={onClose} className="p-2 hover:bg-white/50 rounded-lg">
              <X className="w-5 h-5 text-slate-500" />
            </button>
          </div>
        </div>

        <div className="p-6">
          {/* Search */}
          <div className="relative mb-3">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search clients..."
              className="w-full pl-10 pr-4 py-2 border-2 border-slate-200 rounded-xl text-sm font-medium focus:border-primary focus:outline-none"
            />
          </div>

          {/* Select All */}
          <button
            onClick={toggleAll}
            className="flex items-center gap-2 px-3 py-2 mb-2 hover:bg-slate-50 rounded-lg transition-colors"
          >
            {selectedIds.size === filteredClients.length && filteredClients.length > 0 ? (
              <CheckSquare className="w-5 h-5 text-primary" />
            ) : selectedIds.size > 0 ? (
              <MinusSquare className="w-5 h-5 text-primary" />
            ) : (
              <Square className="w-5 h-5 text-slate-400" />
            )}
            <span className="text-sm font-bold text-slate-700">
              Select All ({filteredClients.length})
            </span>
          </button>

          {/* Client List */}
          <div className="border-2 border-slate-200 rounded-xl max-h-64 overflow-y-auto">
            {filteredClients.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                <Briefcase className="w-10 h-10 mx-auto mb-2 text-slate-300" />
                <p className="font-medium">No clients available</p>
                <p className="text-sm">All clients are already in this group</p>
              </div>
            ) : (
              filteredClients.map((client) => (
                <button
                  key={client.id}
                  onClick={() => toggleClient(client.id)}
                  className={cn(
                    'w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors border-b border-slate-100 last:border-b-0',
                    selectedIds.has(client.id) && 'bg-primary/5'
                  )}
                >
                  {selectedIds.has(client.id) ? (
                    <CheckSquare className="w-5 h-5 text-primary flex-shrink-0" />
                  ) : (
                    <Square className="w-5 h-5 text-slate-400 flex-shrink-0" />
                  )}
                  <Briefcase className="w-4 h-4 text-slate-400 flex-shrink-0" />
                  <div className="flex-1 text-left">
                    <p className="font-bold text-slate-900 text-sm">{client.name}</p>
                    {client.code && <p className="text-xs text-slate-500 font-mono">{client.code}</p>}
                  </div>
                </button>
              ))
            )}
          </div>

          {selectedIds.size > 0 && (
            <p className="mt-2 text-sm text-primary font-bold">
              {selectedIds.size} client{selectedIds.size !== 1 ? 's' : ''} selected
            </p>
          )}
        </div>

        <div className="flex gap-3 px-6 py-4 border-t-2 border-slate-200 bg-slate-50">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
          >
            Cancel
          </button>
          <button
            onClick={() => onAdd(Array.from(selectedIds))}
            disabled={saving || selectedIds.size === 0}
            className="flex-1 px-4 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Add {selectedIds.size} Client{selectedIds.size !== 1 ? 's' : ''}
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Import CSV Modal
// ============================================================================

function ImportCSVModal({
  onImport,
  onClose,
  saving,
}: {
  onImport: (csvContent: string) => Promise<any>;
  onClose: () => void;
  saving: boolean;
}) {
  const [csvContent, setCsvContent] = useState('');
  const [result, setResult] = useState<any>(null);

  const handleImport = async () => {
    try {
      const res = await onImport(csvContent);
      setResult(res);
    } catch (err) {
      // Error handled by parent
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const response = await fetch(`${API_BASE}/settings/client-groups/template/`, {
        credentials: 'include',
      });
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'client_groups_template.csv';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      console.error('Failed to download template:', err);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center">
              <FileSpreadsheet className="w-5 h-5 text-blue-600" />
            </div>
            <h3 className="font-bold text-slate-900">Import Client Groups</h3>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-lg">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        <div className="p-6">
          {result ? (
            <div className="text-center py-6">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="w-8 h-8 text-emerald-600" />
              </div>
              <h4 className="text-xl font-bold text-slate-900 mb-2">Import Complete!</h4>
              <p className="text-slate-600">
                {result.groups_created} groups created, {result.assignments_made} clients assigned
              </p>
              {result.errors?.length > 0 && (
                <div className="mt-4 text-left bg-amber-50 border-2 border-amber-200 rounded-xl p-4 max-h-32 overflow-y-auto">
                  <p className="font-bold text-amber-700 mb-2">Some rows had issues:</p>
                  {result.errors.slice(0, 10).map((err: string, i: number) => (
                    <p key={i} className="text-sm text-amber-600">• {err}</p>
                  ))}
                </div>
              )}
              <button
                onClick={onClose}
                className="mt-6 px-6 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90"
              >
                Done
              </button>
            </div>
          ) : (
            <>
              {/* Template Download */}
              <div className="mb-4 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-bold text-blue-800 text-sm">Download Template</p>
                    <p className="text-xs text-blue-600">Pre-filled with your clients</p>
                  </div>
                  <button
                    onClick={handleDownloadTemplate}
                    className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-bold hover:bg-blue-700"
                  >
                    <Download className="w-4 h-4" />
                    Template
                  </button>
                </div>
              </div>

              {/* CSV Format */}
              <div className="mb-4 p-3 bg-slate-50 border border-slate-200 rounded-xl">
                <p className="text-sm font-bold text-slate-700 mb-1">Expected format:</p>
                <code className="text-xs text-slate-600 bg-slate-200 px-2 py-1 rounded block font-mono">
                  client_code,group_name<br />
                  ACME,Partner: Smith<br />
                  BIGCO,Tax Clients
                </code>
              </div>

              {/* CSV Input */}
              <textarea
                value={csvContent}
                onChange={(e) => setCsvContent(e.target.value)}
                placeholder="Paste your CSV here..."
                rows={8}
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:outline-none"
              />
            </>
          )}
        </div>

        {!result && (
          <div className="flex gap-3 px-6 py-4 border-t-2 border-slate-200 bg-slate-50">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              onClick={handleImport}
              disabled={saving || !csvContent.trim()}
              className="flex-1 px-4 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              Import
            </button>
          </div>
        )}
      </div>
    </div>
  );
}