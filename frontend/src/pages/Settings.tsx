/**
 * Settings.tsx — Org Admin Settings Page with Role Management & Billing Rates
 * 
 * Tabs:
 * - Organization Info (name, billing contact)
 * - Team Members (view users, invite new, manage roles)
 * - Clients (add/edit/delete)
 * - Billing Rates (hourly rates per user/client)
 * - Registered Devices (see who's tracking)
 * - Install Token (view/regenerate for IT)
 */

import { useEffect, useState, useCallback } from "react";
import {
  Settings as SettingsIcon,
  Building2,
  Users,
  Briefcase,
  Monitor,
  Key,
  Plus,
  Pencil,
  Trash2,
  Copy,
  RefreshCw,
  Check,
  X,
  Mail,
  Clock,
  AlertCircle,
  CheckCircle2,
  UserPlus,
  Eye,
  EyeOff,
  DollarSign,
} from "lucide-react";
import { Header } from "@/components/common/Header";
import { DESIGN_SYSTEM } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// Types
type OrgInfo = {
  id: number;
  name: string;
  billing_email: string;
  billing_contact: string;
  created_at: string;
};

type TeamMember = {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  role: 'owner' | 'admin' | 'manager' | 'member';
  last_login: string | null;
  date_joined: string;
};

type Client = {
  id: number;
  name: string;
  code: string;
  is_active: boolean;
  created_at: string;
};

type Device = {
  id: number;
  user: string;
  user_id: number;
  machine_name: string;
  os: string;
  os_version: string;
  agent_version: string;
  first_seen: string;
  last_seen: string;
  is_active: boolean;
};

type InstallToken = {
  token: string;
  created_at: string;
  is_active: boolean;
};

type BillingRate = {
  id: number;
  user: number | null;
  user_name: string;
  client: number | null;
  client_name: string;
  task_type: number | null;
  task_type_name: string;
  hourly_rate: string;
  effective_date: string;
  end_date: string | null;
  is_default: boolean;
};

type Tab = 'organization' | 'team' | 'clients' | 'billing' | 'devices' | 'token';

// ============================================================================
// Component
// ============================================================================
export default function Settings() {
  const [activeTab, setActiveTab] = useState<Tab>('organization');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Data states
  const [orgInfo, setOrgInfo] = useState<OrgInfo | null>(null);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [installToken, setInstallToken] = useState<InstallToken | null>(null);
  const [billingRates, setBillingRates] = useState<BillingRate[]>([]);
  
  // Track current user
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [currentUserRole, setCurrentUserRole] = useState<string>('member');

  // Show toast
  const showSuccess = (msg: string) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(null), 3000);
  };

  const showError = (msg: string) => {
    setError(msg);
    setTimeout(() => setError(null), 5000);
  };

  // Load current user info
  useEffect(() => {
    const loadUserInfo = async () => {
      try {
        const whoami = await safeFetchJson<any>(`${API_BASE}/whoami/`);
        setCurrentUserId(whoami.user_id);
      } catch (err) {
        console.error('Failed to load user info:', err);
      }
    };
    loadUserInfo();
  }, []);

  // Load data based on active tab
  const loadTabData = useCallback(async (tab: Tab) => {
    setLoading(true);
    setError(null);
    try {
      switch (tab) {
        case 'organization':
          const org = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`);
          setOrgInfo(org);
          break;
        case 'team':
          const team = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`);
          setTeamMembers(team || []);
          if (currentUserId) {
            const myMembership = team.find((m: TeamMember) => m.id === currentUserId);
            if (myMembership) {
              setCurrentUserRole(myMembership.role);
            }
          }
          break;
        case 'clients':
          const clientList = await safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`);
          setClients(clientList || []);
          break;
        case 'billing':
          const rates = await safeFetchJson<BillingRate[]>(`${API_BASE}/billing/rates/`);
          setBillingRates(rates || []);
          // Also load clients and team for dropdowns
          const [clientsForRates, teamForRates] = await Promise.all([
            safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
            safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
          ]);
          setClients(clientsForRates || []);
          setTeamMembers(teamForRates || []);
          break;
        case 'devices':
          const deviceList = await safeFetchJson<Device[]>(`${API_BASE}/settings/devices/`);
          setDevices(deviceList || []);
          break;
        case 'token':
          const token = await safeFetchJson<InstallToken>(`${API_BASE}/settings/install-token/`);
          setInstallToken(token);
          break;
      }
    } catch (err: any) {
      showError(err?.message || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [currentUserId]);

  useEffect(() => {
    loadTabData(activeTab);
  }, [activeTab, loadTabData]);

  // Tab definitions
  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'organization', label: 'Organization', icon: <Building2 className="w-4 h-4" /> },
    { id: 'team', label: 'Team Members', icon: <Users className="w-4 h-4" /> },
    { id: 'clients', label: 'Clients', icon: <Briefcase className="w-4 h-4" /> },
    { id: 'billing', label: 'Billing Rates', icon: <DollarSign className="w-4 h-4" /> },
    { id: 'devices', label: 'Devices', icon: <Monitor className="w-4 h-4" /> },
    { id: 'token', label: 'Install Token', icon: <Key className="w-4 h-4" /> },
  ];

  return (
    <div className="min-h-screen bg-background">
      <Header
        title="Settings"
        subtitle="Manage your organization"
        icon={<SettingsIcon className="w-6 h-6 text-primary-foreground" />}
      />

      {/* Toast Notifications */}
      {success && (
        <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 bg-green-600 text-white animate-in slide-in-from-right">
          <CheckCircle2 className="w-4 h-4" />
          <span className="text-sm font-medium">{success}</span>
        </div>
      )}
      {error && (
        <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 bg-red-600 text-white animate-in slide-in-from-right">
          <AlertCircle className="w-4 h-4" />
          <span className="text-sm font-medium">{error}</span>
        </div>
      )}

      <div className={DESIGN_SYSTEM.spacing.container + " py-6"}>
        <div className="flex gap-6">
          {/* Sidebar Tabs */}
          <div className="w-56 flex-shrink-0">
            <nav className="space-y-1">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                    activeTab === tab.id
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>

          {/* Content Area */}
          <div className="flex-1 min-w-0">
            <div className="bg-card border border-border rounded-xl p-6 shadow-sm">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <RefreshCw className="w-6 h-6 text-primary animate-spin" />
                </div>
              ) : (
                <>
                  {activeTab === 'organization' && (
                    <OrganizationTab
                      orgInfo={orgInfo}
                      onUpdate={(updated) => setOrgInfo(updated)}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  )}
                  {activeTab === 'team' && (
                    <TeamTab
                      members={teamMembers}
                      currentUserId={currentUserId}
                      currentUserRole={currentUserRole}
                      onRefresh={() => loadTabData('team')}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  )}
                  {activeTab === 'clients' && (
                    <ClientsTab
                      clients={clients}
                      onRefresh={() => loadTabData('clients')}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  )}
                  {activeTab === 'billing' && (
                    <BillingRatesTab
                      rates={billingRates}
                      users={teamMembers}
                      clients={clients}
                      onRefresh={() => loadTabData('billing')}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  )}
                  {activeTab === 'devices' && (
                    <DevicesTab
                      devices={devices}
                      onRefresh={() => loadTabData('devices')}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  )}
                  {activeTab === 'token' && (
                    <TokenTab
                      token={installToken}
                      onRefresh={() => loadTabData('token')}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Organization Tab
// ============================================================================
function OrganizationTab({
  orgInfo,
  onUpdate,
  onSuccess,
  onError,
}: {
  orgInfo: OrgInfo | null;
  onUpdate: (org: OrgInfo) => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: '',
    billing_email: '',
    billing_contact: '',
  });

  useEffect(() => {
    if (orgInfo) {
      setForm({
        name: orgInfo.name || '',
        billing_email: orgInfo.billing_email || '',
        billing_contact: orgInfo.billing_contact || '',
      });
    }
  }, [orgInfo]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      onUpdate(updated);
      setEditing(false);
      onSuccess('Organization updated');
    } catch (err: any) {
      onError(err?.message || 'Failed to update');
    } finally {
      setSaving(false);
    }
  };

  if (!orgInfo) {
    return <div className="text-muted-foreground">No organization data</div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Building2 className="w-5 h-5 text-primary" />
          Organization Info
        </h2>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-accent transition-colors"
          >
            <Pencil className="w-4 h-4" />
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-4 max-w-md">
          <div>
            <label className="block text-sm font-medium mb-1.5">Organization Name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Billing Email</label>
            <input
              type="email"
              value={form.billing_email}
              onChange={(e) => setForm({ ...form, billing_email: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Billing Contact Name</label>
            <input
              type="text"
              value={form.billing_contact}
              onChange={(e) => setForm({ ...form, billing_contact: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>
          <div className="flex gap-2 pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-4 py-2 border border-border rounded-lg font-medium hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-sm text-muted-foreground">Organization Name</p>
              <p className="font-medium">{orgInfo.name}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Created</p>
              <p className="font-medium">{new Date(orgInfo.created_at).toLocaleDateString()}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Billing Email</p>
              <p className="font-medium">{orgInfo.billing_email || '—'}</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Billing Contact</p>
              <p className="font-medium">{orgInfo.billing_contact || '—'}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Team Tab with Role Management
// ============================================================================
function TeamTab({
  members,
  currentUserId,
  currentUserRole,
  onRefresh,
  onSuccess,
  onError,
}: {
  members: TeamMember[];
  currentUserId: number | null;
  currentUserRole: string;
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviting, setInviting] = useState(false);

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    try {
      const response = await safeFetchJson<any>(`${API_BASE}/settings/team/invite/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: inviteEmail }),
      });
      
      if (response.temp_password && !response.email_sent) {
        alert(`User created!\n\nUsername: ${response.username}\nTemp Password: ${response.temp_password}\n\nPlease share these credentials with the user.`);
      }
      
      onSuccess(response.email_sent ? 'Invitation sent' : 'User created (share credentials manually)');
      setInviteEmail('');
      setShowInvite(false);
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to invite');
    } finally {
      setInviting(false);
    }
  };

  const handlePromote = async (userId: number, username: string) => {
    if (!confirm(`Promote ${username} to admin? They will be able to manage settings and team members.`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/promote/`, {
        method: 'POST',
      });
      onSuccess('User promoted to admin');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to promote');
    }
  };

  const handleDemote = async (userId: number, username: string, targetRole: 'member' | 'manager' = 'member') => {
    if (!confirm(`Demote ${username} to ${targetRole}? They will lose admin access.`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/demote/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_role: targetRole }),
      });
      onSuccess(`User demoted to ${targetRole}`);
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to demote');
    }
  };

  const handleSetManager = async (userId: number, username: string) => {
    if (!confirm(`Promote ${username} to manager? They will be able to approve timecards.`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/set-manager/`, {
        method: 'POST',
      });
      onSuccess('User promoted to manager');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to promote');
    }
  };

  const handleRemove = async (userId: number, username: string) => {
    if (!confirm(`Remove ${username} from the team?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/`, {
        method: 'DELETE',
      });
      onSuccess('Team member removed');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to remove');
    }
  };

  const formatLastSeen = (dateStr: string | null) => {
    if (!dateStr) return 'Never';
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getRoleBadge = (role: string) => {
    switch (role) {
      case 'owner':
        return 'bg-purple-100 text-purple-800';
      case 'admin':
        return 'bg-blue-100 text-blue-800';
      case 'manager':
        return 'bg-green-100 text-green-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const isOwner = currentUserRole === 'owner';
  const isAdminOrOwner = currentUserRole === 'owner' || currentUserRole === 'admin';

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Users className="w-5 h-5 text-primary" />
          Team Members
          <span className="text-sm font-normal text-muted-foreground">({members.length})</span>
        </h2>
        <button
          onClick={() => setShowInvite(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium text-sm hover:bg-primary/90 transition-colors"
        >
          <UserPlus className="w-4 h-4" />
          Invite Member
        </button>
      </div>

      {showInvite && (
        <div className="mb-6 p-4 bg-accent/50 border border-border rounded-lg">
          <h3 className="font-medium mb-3">Invite Team Member</h3>
          <div className="flex gap-2">
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="email@company.com"
              className="flex-1 border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            <button
              onClick={handleInvite}
              disabled={inviting || !inviteEmail.trim()}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
            >
              {inviting ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
              Send
            </button>
            <button
              onClick={() => setShowInvite(false)}
              className="px-4 py-2 border border-border rounded-lg hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">User</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Email</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Role</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Last Active</th>
              <th className="text-right px-4 py-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {members.map(member => {
              const isCurrentUser = member.id === currentUserId;
              const canModify = isOwner && !isCurrentUser && member.role !== 'owner';
              const canSetManager = isAdminOrOwner && !isCurrentUser && member.role === 'member';
              
              return (
                <tr key={member.id} className="hover:bg-accent/30">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
                        <span className="text-sm font-medium text-primary">
                          {(member.first_name?.[0] || member.username[0]).toUpperCase()}
                        </span>
                      </div>
                      <div>
                        <p className="font-medium text-sm">
                          {member.first_name} {member.last_name || member.username}
                          {isCurrentUser && <span className="ml-2 text-xs text-muted-foreground">(you)</span>}
                        </p>
                        <p className="text-xs text-muted-foreground">@{member.username}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm">{member.email || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-1 rounded-full font-medium ${getRoleBadge(member.role)}`}>
                      {member.role.charAt(0).toUpperCase() + member.role.slice(1)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {formatLastSeen(member.last_login)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {canSetManager && (
                        <button
                          onClick={() => handleSetManager(member.id, member.username)}
                          className="text-xs px-2 py-1 text-green-600 hover:text-green-800 hover:underline"
                          title="Promote to Manager"
                        >
                          → Manager
                        </button>
                      )}
                      
                      {canModify && (member.role === 'member' || member.role === 'manager') && (
                        <button
                          onClick={() => handlePromote(member.id, member.username)}
                          className="text-xs px-2 py-1 text-blue-600 hover:text-blue-800 hover:underline"
                          title="Promote to Admin"
                        >
                          → Admin
                        </button>
                      )}
                      
                      {canModify && member.role === 'admin' && (
                        <button
                          onClick={() => handleDemote(member.id, member.username, 'member')}
                          className="text-xs px-2 py-1 text-orange-600 hover:text-orange-800 hover:underline"
                          title="Demote to Member"
                        >
                          → Member
                        </button>
                      )}
                      
                      {!isCurrentUser && member.role !== 'owner' && (
                        <button
                          onClick={() => handleRemove(member.id, member.username)}
                          className="p-1.5 text-red-500 hover:bg-red-50 rounded transition-colors"
                          title="Remove from team"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {members.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            No team members yet
          </div>
        )}
      </div>
      
      <div className="mt-4 p-3 bg-muted/30 rounded-lg">
        <div className="text-xs text-muted-foreground space-y-1">
          <p><span className="inline-block px-2 py-0.5 rounded bg-purple-100 text-purple-800 font-medium">Owner</span> — Full control, manage admins</p>
          <p><span className="inline-block px-2 py-0.5 rounded bg-blue-100 text-blue-800 font-medium">Admin</span> — Manage settings, invite users</p>
          <p><span className="inline-block px-2 py-0.5 rounded bg-green-100 text-green-800 font-medium">Manager</span> — Approve timecards</p>
          <p><span className="inline-block px-2 py-0.5 rounded bg-gray-100 text-gray-800 font-medium">Member</span> — Track time only</p>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Clients Tab
// ============================================================================
function ClientsTab({
  clients,
  onRefresh,
  onSuccess,
  onError,
}: {
  clients: Client[];
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({ name: '', code: '' });
  const [saving, setSaving] = useState(false);

  const resetForm = () => {
    setForm({ name: '', code: '' });
    setShowAdd(false);
    setEditingId(null);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      if (editingId) {
        await safeFetchJson(`${API_BASE}/settings/clients/${editingId}/`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        });
        onSuccess('Client updated');
      } else {
        await safeFetchJson(`${API_BASE}/settings/clients/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        });
        onSuccess('Client added');
      }
      resetForm();
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (client: Client) => {
    setForm({ name: client.name, code: client.code || '' });
    setEditingId(client.id);
    setShowAdd(true);
  };

  const handleDelete = async (clientId: number, clientName: string) => {
    if (!confirm(`Delete client "${clientName}"? This cannot be undone.`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/clients/${clientId}/`, {
        method: 'DELETE',
      });
      onSuccess('Client deleted');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Briefcase className="w-5 h-5 text-primary" />
          Clients
          <span className="text-sm font-normal text-muted-foreground">({clients.length})</span>
        </h2>
        <button
          onClick={() => { resetForm(); setShowAdd(true); }}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium text-sm hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add Client
        </button>
      </div>

      {showAdd && (
        <div className="mb-6 p-4 bg-accent/50 border border-border rounded-lg">
          <h3 className="font-medium mb-3">{editingId ? 'Edit Client' : 'Add Client'}</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1.5">Client Name *</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Acme Corporation"
                className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5">Code (optional)</label>
              <input
                type="text"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                placeholder="ACME"
                maxLength={10}
                className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50 uppercase"
              />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button
              onClick={handleSave}
              disabled={saving || !form.name.trim()}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {editingId ? 'Update' : 'Add'}
            </button>
            <button
              onClick={resetForm}
              className="px-4 py-2 border border-border rounded-lg font-medium hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Client Name</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Code</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Status</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Added</th>
              <th className="text-right px-4 py-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {clients.map(client => (
              <tr key={client.id} className="hover:bg-accent/30">
                <td className="px-4 py-3 font-medium">{client.name}</td>
                <td className="px-4 py-3 text-sm text-muted-foreground font-mono">{client.code || '—'}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-1 rounded-full ${
                    client.is_active
                      ? 'bg-green-100 text-green-700'
                      : 'bg-muted text-muted-foreground'
                  }`}>
                    {client.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-muted-foreground">
                  {new Date(client.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={() => handleEdit(client)}
                      className="p-1.5 text-primary hover:bg-primary/10 rounded transition-colors"
                      title="Edit"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(client.id, client.name)}
                      className="p-1.5 text-red-500 hover:bg-red-50 rounded transition-colors"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {clients.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            No clients yet. Add your first client to get started.
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Billing Rates Tab (NEW)
// ============================================================================
function BillingRatesTab({
  rates,
  users,
  clients,
  onRefresh,
  onSuccess,
  onError,
}: {
  rates: BillingRate[];
  users: TeamMember[];
  clients: Client[];
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    user: '',
    client: '',
    hourly_rate: '150.00',
    effective_date: new Date().toISOString().split('T')[0],
  });

  const resetForm = () => {
    setForm({
      user: '',
      client: '',
      hourly_rate: '150.00',
      effective_date: new Date().toISOString().split('T')[0],
    });
    setShowAdd(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/billing/rates/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user: form.user || null,
          client: form.client || null,
          hourly_rate: form.hourly_rate,
          effective_date: form.effective_date,
        }),
      });
      onSuccess('Rate added');
      resetForm();
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (rateId: number) => {
    if (!confirm('Delete this billing rate?')) return;
    try {
      await safeFetchJson(`${API_BASE}/billing/rates/${rateId}/`, {
        method: 'DELETE',
      });
      onSuccess('Rate deleted');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-primary" />
          Billing Rates
          <span className="text-sm font-normal text-muted-foreground">({rates.length})</span>
        </h2>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium text-sm hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add Rate
        </button>
      </div>

      {/* Rate Priority Info */}
      <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h4 className="font-medium text-blue-800 mb-2">Rate Priority (highest to lowest):</h4>
        <ol className="text-sm text-blue-700 space-y-1 list-decimal list-inside">
          <li>User + Client specific rate (e.g., "John at Acme Corp = $200/hr")</li>
          <li>Client specific rate (e.g., "Any user at Acme Corp = $175/hr")</li>
          <li>User default rate (e.g., "John = $150/hr everywhere")</li>
          <li>Organization default rate (no user, no client selected)</li>
        </ol>
      </div>

      {/* Add Rate Form */}
      {showAdd && (
        <div className="mb-6 p-4 bg-accent/50 border border-border rounded-lg">
          <h3 className="font-medium mb-4">Add Billing Rate</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1.5">
                User <span className="text-muted-foreground font-normal">(blank = all users)</span>
              </label>
              <select
                value={form.user}
                onChange={(e) => setForm({ ...form, user: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="">All Users (Default)</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.first_name} {u.last_name || u.username}
                  </option>
                ))}
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium mb-1.5">
                Client <span className="text-muted-foreground font-normal">(blank = all clients)</span>
              </label>
              <select
                value={form.client}
                onChange={(e) => setForm({ ...form, client: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="">All Clients (Default)</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium mb-1.5">Hourly Rate ($)</label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.hourly_rate}
                onChange={(e) => setForm({ ...form, hourly_rate: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium mb-1.5">Effective Date</label>
              <input
                type="date"
                value={form.effective_date}
                onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            </div>
          </div>
          
          <div className="flex gap-2 mt-4">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save Rate
            </button>
            <button
              onClick={resetForm}
              className="px-4 py-2 border border-border rounded-lg font-medium hover:bg-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Rates Table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">User</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Client</th>
              <th className="text-right px-4 py-3 text-sm font-medium text-muted-foreground">Rate/Hour</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Effective</th>
              <th className="text-right px-4 py-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rates.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-center py-8 text-muted-foreground">
                  No billing rates configured yet. Add your first rate to enable billing calculations.
                </td>
              </tr>
            ) : (
              rates.map((rate) => (
                <tr key={rate.id} className="hover:bg-accent/30">
                  <td className="px-4 py-3">
                    {rate.user_name || (
                      <span className="text-muted-foreground italic">All Users</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {rate.client_name || (
                      <span className="text-muted-foreground italic">All Clients</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="font-semibold text-green-600">
                      ${parseFloat(rate.hourly_rate).toFixed(2)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">
                    {new Date(rate.effective_date).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleDelete(rate.id)}
                      className="p-1.5 text-red-500 hover:bg-red-50 rounded transition-colors"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Example Setup */}
      <div className="mt-6 p-4 bg-muted/30 rounded-lg">
        <h4 className="font-medium text-sm mb-2">Example Rate Setup:</h4>
        <div className="text-xs text-muted-foreground space-y-1">
          <p>• <strong>Organization Default:</strong> User = blank, Client = blank, Rate = $150/hr</p>
          <p>• <strong>Senior Staff:</strong> User = "John Smith", Client = blank, Rate = $200/hr</p>
          <p>• <strong>Premium Client:</strong> User = blank, Client = "Acme Corp", Rate = $175/hr</p>
          <p>• <strong>Specific Combo:</strong> User = "John Smith", Client = "Acme Corp", Rate = $225/hr</p>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Devices Tab
// ============================================================================
function DevicesTab({
  devices,
  onRefresh,
  onSuccess,
  onError,
}: {
  devices: Device[];
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const formatLastSeen = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const getStatusColor = (lastSeen: string) => {
    const date = new Date(lastSeen);
    const now = new Date();
    const diffHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);
    if (diffHours < 1) return 'bg-green-500';
    if (diffHours < 24) return 'bg-yellow-500';
    return 'bg-gray-400';
  };

  const handleDeactivate = async (deviceId: number, machineName: string) => {
    if (!confirm(`Deactivate agent on "${machineName}"?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/devices/${deviceId}/deactivate/`, {
        method: 'POST',
      });
      onSuccess('Device deactivated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to deactivate');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Monitor className="w-5 h-5 text-primary" />
          Registered Devices
          <span className="text-sm font-normal text-muted-foreground">({devices.length})</span>
        </h2>
        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-accent transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Status</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">User</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Machine</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">OS</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Version</th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">Last Seen</th>
              <th className="text-right px-4 py-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {devices.map(device => (
              <tr key={device.id} className={`hover:bg-accent/30 ${!device.is_active ? 'opacity-50' : ''}`}>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className={`w-2.5 h-2.5 rounded-full ${device.is_active ? getStatusColor(device.last_seen) : 'bg-gray-300'}`} />
                  </div>
                </td>
                <td className="px-4 py-3 font-medium text-sm">{device.user}</td>
                <td className="px-4 py-3 text-sm">{device.machine_name}</td>
                <td className="px-4 py-3 text-sm capitalize">{device.os}</td>
                <td className="px-4 py-3 text-sm text-muted-foreground font-mono">{device.agent_version || '—'}</td>
                <td className="px-4 py-3 text-sm text-muted-foreground">{formatLastSeen(device.last_seen)}</td>
                <td className="px-4 py-3 text-right">
                  {device.is_active && (
                    <button
                      onClick={() => handleDeactivate(device.id, device.machine_name)}
                      className="p-1.5 text-red-500 hover:bg-red-50 rounded transition-colors"
                      title="Deactivate"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {devices.length === 0 && (
          <div className="text-center py-8 text-muted-foreground">
            No devices registered yet. Install the agent to start tracking.
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 mt-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
          Active now
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-yellow-500" />
          Active today
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-full bg-gray-400" />
          Inactive
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Token Tab
// ============================================================================
function TokenTab({
  token,
  onRefresh,
  onSuccess,
  onError,
}: {
  token: InstallToken | null;
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [showToken, setShowToken] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    if (token?.token) {
      navigator.clipboard.writeText(token.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleRegenerate = async () => {
    if (!confirm('Regenerate install token? The old token will stop working immediately.')) return;
    setRegenerating(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/install-token/regenerate/`, {
        method: 'POST',
      });
      onSuccess('Token regenerated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to regenerate');
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <Key className="w-5 h-5 text-primary" />
          Install Token
        </h2>
      </div>

      <div className="bg-accent/50 border border-border rounded-lg p-6">
        <p className="text-sm text-muted-foreground mb-4">
          Share this token with your IT team for MDM deployment. Agents will automatically register with your organization.
        </p>

        {token ? (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Organization Token</label>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-white border border-border rounded-lg px-4 py-3 font-mono text-sm">
                  {showToken ? token.token : '••••••••••••••••••••••••••••••••'}
                </div>
                <button
                  onClick={() => setShowToken(!showToken)}
                  className="p-2.5 border border-border rounded-lg hover:bg-accent transition-colors"
                  title={showToken ? 'Hide' : 'Show'}
                >
                  {showToken ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
                <button
                  onClick={handleCopy}
                  className="p-2.5 border border-border rounded-lg hover:bg-accent transition-colors"
                  title="Copy"
                >
                  {copied ? <Check className="w-5 h-5 text-green-600" /> : <Copy className="w-5 h-5" />}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <p className="text-xs text-muted-foreground">
                Created: {new Date(token.created_at).toLocaleString()}
              </p>
              <button
                onClick={handleRegenerate}
                disabled={regenerating}
                className="flex items-center gap-2 px-4 py-2 text-sm border border-red-200 text-red-600 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
              >
                {regenerating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Regenerate Token
              </button>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-muted-foreground mb-4">No install token exists yet.</p>
            <button
              onClick={handleRegenerate}
              disabled={regenerating}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              Generate Token
            </button>
          </div>
        )}
      </div>

      <div className="mt-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h3 className="font-medium text-blue-900 mb-2">MDM Deployment Instructions</h3>
        <ol className="text-sm text-blue-800 space-y-1.5 list-decimal list-inside">
          <li>Download the TimeTracker installer (.pkg for Mac, .msi for Windows)</li>
          <li>Create a configuration file with the token above</li>
          <li>Deploy both via your MDM (Jamf, Intune, Kandji, etc.)</li>
          <li>Agents will auto-register when users log in</li>
        </ol>
        <p className="text-xs text-blue-600 mt-3">
          Need help? Contact support@mavops.ai
        </p>
      </div>
    </div>
  );
}