/**
 * Settings.tsx — Org Admin Settings Page
 * STRONGER FONTS - darker text, bolder weights
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
  AlertCircle,
  CheckCircle2,
  UserPlus,
  Eye,
  EyeOff,
  DollarSign,
} from "lucide-react";
import { cn } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// Types
type OrgInfo = {
  id: number;
  name: string;
  billing_email: string;
  billing_contact: string;
  billing_rate_default: string;
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
  rate: string;
  hourly_rate?: string;
  effective_date: string;
  end_date: string | null;
  is_default: boolean;
};

type EmployeeCostRate = {
  id: number;
  user: number;
  user_name: string;
  cost_rate: string;
  effective_date: string;
  end_date: string | null;
};

type Tab = 'organization' | 'team' | 'clients' | 'billing' | 'costs' | 'devices' | 'token';

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
  const [employeeCostRates, setEmployeeCostRates] = useState<EmployeeCostRate[]>([]);
  
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [currentUserRole, setCurrentUserRole] = useState<string>('member');

  const showSuccess = (msg: string) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(null), 3000);
  };

  const showError = (msg: string) => {
    setError(msg);
    setTimeout(() => setError(null), 5000);
  };

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
          const [clientsForRates, teamForRates] = await Promise.all([
            safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
            safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
          ]);
          setClients(clientsForRates || []);
          setTeamMembers(teamForRates || []);
          break;
        case 'costs':
          const costRates = await safeFetchJson<EmployeeCostRate[]>(`${API_BASE}/billing/cost-rates/`).catch(() => []);
          setEmployeeCostRates(costRates || []);
          const teamForCosts = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []);
          setTeamMembers(teamForCosts || []);
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

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'organization', label: 'Organization', icon: <Building2 className="w-4 h-4" /> },
    { id: 'team', label: 'Team Members', icon: <Users className="w-4 h-4" /> },
    { id: 'clients', label: 'Clients', icon: <Briefcase className="w-4 h-4" /> },
    { id: 'billing', label: 'Billing Rates', icon: <DollarSign className="w-4 h-4" /> },
    { id: 'costs', label: 'Employee Costs', icon: <Users className="w-4 h-4" /> },
    { id: 'devices', label: 'Devices', icon: <Monitor className="w-4 h-4" /> },
    { id: 'token', label: 'Install Token', icon: <Key className="w-4 h-4" /> },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Toast Notifications */}
      {success && (
        <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-xl flex items-center gap-2 bg-emerald-500 text-white font-bold animate-in slide-in-from-right">
          <CheckCircle2 className="w-4 h-4" />
          <span className="text-sm">{success}</span>
        </div>
      )}
      {error && (
        <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-xl flex items-center gap-2 bg-red-500 text-white font-bold animate-in slide-in-from-right">
          <AlertCircle className="w-4 h-4" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Page Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/25">
            <SettingsIcon className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">Settings</h1>
            <p className="text-slate-600 font-medium">Manage your organization</p>
          </div>
        </div>

        <div className="flex gap-6">
          {/* Sidebar Tabs */}
          <div className="w-56 flex-shrink-0">
            <nav className="space-y-1">
              {tabs.map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    'w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-bold transition-all',
                    activeTab === tab.id
                      ? 'bg-primary text-white shadow-lg shadow-primary/25'
                      : 'text-slate-600 hover:bg-slate-200 hover:text-slate-900'
                  )}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>

          {/* Content Area */}
          <div className="flex-1 min-w-0">
            <div className="bg-white border-2 border-slate-200 rounded-2xl p-6 shadow-sm">
              {loading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="text-center">
                    <RefreshCw className="w-6 h-6 text-primary animate-spin mx-auto mb-2" />
                    <p className="text-slate-600 font-semibold">Loading...</p>
                  </div>
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
                      orgDefaultRate={orgInfo?.billing_rate_default || '150.00'}
                      onRefresh={() => loadTabData('billing')}
                      onSuccess={showSuccess}
                      onError={showError}
                    />
                  )}
                  {activeTab === 'costs' && (
                    <EmployeeCostRatesTab
                      rates={employeeCostRates}
                      users={teamMembers}
                      onRefresh={() => loadTabData('costs')}
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
    billing_rate_default: '150.00',
  });

  useEffect(() => {
    if (orgInfo) {
      setForm({
        name: orgInfo.name || '',
        billing_email: orgInfo.billing_email || '',
        billing_contact: orgInfo.billing_contact || '',
        billing_rate_default: orgInfo.billing_rate_default || '150.00',
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
    return <div className="text-slate-500 font-medium">No organization data</div>;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Building2 className="w-5 h-5 text-primary" />
          Organization Info
        </h2>
        {!editing && (
          <button
            onClick={() => setEditing(true)}
            className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all"
          >
            <Pencil className="w-4 h-4" />
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-5 max-w-md">
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Organization Name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
            />
          </div>
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Billing Email</label>
            <input
              type="email"
              value={form.billing_email}
              onChange={(e) => setForm({ ...form, billing_email: e.target.value })}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
            />
          </div>
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Billing Contact Name</label>
            <input
              type="text"
              value={form.billing_contact}
              onChange={(e) => setForm({ ...form, billing_contact: e.target.value })}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
            />
          </div>
          
          <div className="pt-4 border-t-2 border-slate-200">
            <label className="block text-sm font-bold text-slate-800 mb-2 flex items-center gap-2">
              <DollarSign className="w-4 h-4" />
              Default Hourly Billing Rate
            </label>
            <div className="relative max-w-xs">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold">$</span>
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.billing_rate_default}
                onChange={(e) => setForm({ ...form, billing_rate_default: e.target.value })}
                className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl text-slate-900 font-semibold focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
                placeholder="150.00"
              />
            </div>
            <p className="text-sm text-slate-600 font-medium mt-2">
              This rate applies to all billable time unless overridden in Billing Rates
            </p>
          </div>

          <div className="flex gap-3 pt-4">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <p className="text-sm text-slate-500 font-semibold mb-1">Organization Name</p>
              <p className="text-slate-900 font-bold">{orgInfo.name}</p>
            </div>
            <div>
              <p className="text-sm text-slate-500 font-semibold mb-1">Created</p>
              <p className="text-slate-900 font-bold">{new Date(orgInfo.created_at).toLocaleDateString()}</p>
            </div>
            <div>
              <p className="text-sm text-slate-500 font-semibold mb-1">Billing Email</p>
              <p className="text-slate-900 font-bold">{orgInfo.billing_email || '—'}</p>
            </div>
            <div>
              <p className="text-sm text-slate-500 font-semibold mb-1">Billing Contact</p>
              <p className="text-slate-900 font-bold">{orgInfo.billing_contact || '—'}</p>
            </div>
          </div>
          
          <div className="pt-4 border-t-2 border-slate-200">
            <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-emerald-700 font-bold flex items-center gap-2">
                    <DollarSign className="w-4 h-4" />
                    Default Hourly Billing Rate
                  </p>
                  <p className="text-3xl font-extrabold text-emerald-700 mt-1">
                    ${parseFloat(orgInfo.billing_rate_default || '150.00').toFixed(2)}/hr
                  </p>
                </div>
                <span className="bg-emerald-100 text-emerald-800 px-3 py-1.5 rounded-full text-xs font-bold">
                  Firm Default
                </span>
              </div>
              <p className="text-sm text-emerald-600 font-medium mt-3">
                All new time entries use this rate unless a custom rate is configured in Billing Rates
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Team Tab
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
    if (!confirm(`Promote ${username} to admin?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/promote/`, { method: 'POST' });
      onSuccess('User promoted to admin');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to promote');
    }
  };

  const handleDemote = async (userId: number, username: string, targetRole: 'member' | 'manager' = 'member') => {
    if (!confirm(`Demote ${username} to ${targetRole}?`)) return;
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
    if (!confirm(`Promote ${username} to manager?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/set-manager/`, { method: 'POST' });
      onSuccess('User promoted to manager');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to promote');
    }
  };

  const handleRemove = async (userId: number, username: string) => {
    if (!confirm(`Remove ${username} from the team?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/team/${userId}/`, { method: 'DELETE' });
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
      case 'owner': return 'bg-purple-100 text-purple-800';
      case 'admin': return 'bg-blue-100 text-blue-800';
      case 'manager': return 'bg-emerald-100 text-emerald-800';
      default: return 'bg-slate-100 text-slate-700';
    }
  };

  const isOwner = currentUserRole === 'owner';
  const isAdminOrOwner = currentUserRole === 'owner' || currentUserRole === 'admin';

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Users className="w-5 h-5 text-primary" />
          Team Members
          <span className="text-sm font-bold text-slate-500">({members.length})</span>
        </h2>
        <button
          onClick={() => setShowInvite(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
        >
          <UserPlus className="w-4 h-4" />
          Invite Member
        </button>
      </div>

      {showInvite && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-3">Invite Team Member</h3>
          <div className="flex gap-2">
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="email@company.com"
              className="flex-1 border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
            />
            <button
              onClick={handleInvite}
              disabled={inviting || !inviteEmail.trim()}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 transition-all"
            >
              {inviting ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
              Send
            </button>
            <button
              onClick={() => setShowInvite(false)}
              className="px-4 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">User</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Email</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Role</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Last Active</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {members.map(member => {
              const isCurrentUser = member.id === currentUserId;
              const canModify = isOwner && !isCurrentUser && member.role !== 'owner';
              const canSetManager = isAdminOrOwner && !isCurrentUser && member.role === 'member';
              
              return (
                <tr key={member.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center">
                        <span className="text-sm font-bold text-primary">
                          {(member.first_name?.[0] || member.username[0]).toUpperCase()}
                        </span>
                      </div>
                      <div>
                        <p className="font-bold text-slate-900 text-sm">
                          {member.first_name} {member.last_name || member.username}
                          {isCurrentUser && <span className="ml-2 text-xs text-slate-500 font-semibold">(you)</span>}
                        </p>
                        <p className="text-xs text-slate-500 font-medium">@{member.username}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-700 font-medium">{member.email || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={cn('text-xs px-2.5 py-1 rounded-full font-bold', getRoleBadge(member.role))}>
                      {member.role.charAt(0).toUpperCase() + member.role.slice(1)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-500 font-medium">
                    {formatLastSeen(member.last_login)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {canSetManager && (
                        <button onClick={() => handleSetManager(member.id, member.username)} className="text-xs px-2 py-1 text-emerald-600 font-bold hover:underline">→ Manager</button>
                      )}
                      {canModify && (member.role === 'member' || member.role === 'manager') && (
                        <button onClick={() => handlePromote(member.id, member.username)} className="text-xs px-2 py-1 text-blue-600 font-bold hover:underline">→ Admin</button>
                      )}
                      {canModify && member.role === 'admin' && (
                        <button onClick={() => handleDemote(member.id, member.username, 'member')} className="text-xs px-2 py-1 text-amber-600 font-bold hover:underline">→ Member</button>
                      )}
                      {!isCurrentUser && member.role !== 'owner' && (
                        <button onClick={() => handleRemove(member.id, member.username)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors">
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
          <div className="text-center py-8 text-slate-500 font-medium">No team members yet</div>
        )}
      </div>
      
      <div className="mt-4 p-4 bg-slate-100 rounded-xl">
        <div className="text-sm text-slate-600 font-medium space-y-1">
          <p><span className="inline-block px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 font-bold text-xs">Owner</span> — Full control, manage admins</p>
          <p><span className="inline-block px-2 py-0.5 rounded-full bg-blue-100 text-blue-800 font-bold text-xs">Admin</span> — Manage settings, invite users</p>
          <p><span className="inline-block px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-bold text-xs">Manager</span> — Approve timecards</p>
          <p><span className="inline-block px-2 py-0.5 rounded-full bg-slate-200 text-slate-700 font-bold text-xs">Member</span> — Track time only</p>
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
    if (!confirm(`Delete client "${clientName}"?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/clients/${clientId}/`, { method: 'DELETE' });
      onSuccess('Client deleted');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Briefcase className="w-5 h-5 text-primary" />
          Clients
          <span className="text-sm font-bold text-slate-500">({clients.length})</span>
        </h2>
        <button
          onClick={() => { resetForm(); setShowAdd(true); }}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
        >
          <Plus className="w-4 h-4" />
          Add Client
        </button>
      </div>

      {showAdd && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-4">{editingId ? 'Edit Client' : 'Add Client'}</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Client Name *</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Acme Corporation"
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all"
              />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Code (optional)</label>
              <input
                type="text"
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                placeholder="ACME"
                maxLength={10}
                className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all uppercase"
              />
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button
              onClick={handleSave}
              disabled={saving || !form.name.trim()}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {editingId ? 'Update' : 'Add'}
            </button>
            <button
              onClick={resetForm}
              className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Client Name</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Code</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Status</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Added</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {clients.map(client => (
              <tr key={client.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-4 py-3 font-bold text-slate-900">{client.name}</td>
                <td className="px-4 py-3 text-sm text-slate-500 font-mono font-semibold">{client.code || '—'}</td>
                <td className="px-4 py-3">
                  <span className={cn(
                    'text-xs px-2.5 py-1 rounded-full font-bold',
                    client.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
                  )}>
                    {client.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-slate-500 font-medium">
                  {new Date(client.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => handleEdit(client)} className="p-1.5 text-primary hover:bg-primary/10 rounded-lg transition-colors">
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button onClick={() => handleDelete(client.id, client.name)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {clients.length === 0 && (
          <div className="text-center py-8 text-slate-500 font-medium">No clients yet. Add your first client to get started.</div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Billing Rates Tab
// ============================================================================
function BillingRatesTab({
  rates,
  users,
  clients,
  orgDefaultRate,
  onRefresh,
  onSuccess,
  onError,
}: {
  rates: BillingRate[];
  users: TeamMember[];
  clients: Client[];
  orgDefaultRate: string;
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
    setForm({ user: '', client: '', hourly_rate: '150.00', effective_date: new Date().toISOString().split('T')[0] });
    setShowAdd(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, any> = { rate: form.hourly_rate, effective_date: form.effective_date };
      if (form.user) payload.user_id = parseInt(form.user, 10);
      if (form.client) payload.client_id = parseInt(form.client, 10);
      
      await safeFetchJson(`${API_BASE}/billing/rates/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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
      await safeFetchJson(`${API_BASE}/billing/rates/${rateId}/`, { method: 'DELETE' });
      onSuccess('Rate deleted');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-primary" />
          Billing Rates
          <span className="text-sm font-bold text-slate-500">({rates.length} custom)</span>
        </h2>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
        >
          <Plus className="w-4 h-4" />
          Add Custom Rate
        </button>
      </div>

      {/* Org Default Rate */}
      <div className="mb-6 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-emerald-700 font-bold">Organization Default Rate</p>
            <p className="text-3xl font-extrabold text-emerald-700">${parseFloat(orgDefaultRate).toFixed(2)}/hr</p>
          </div>
          <div className="text-right">
            <span className="bg-emerald-100 text-emerald-800 px-3 py-1.5 rounded-full text-xs font-bold">Base Rate</span>
            <p className="text-xs text-emerald-600 font-medium mt-1">Edit in Organization tab</p>
          </div>
        </div>
      </div>

      {/* Rate Priority Info */}
      <div className="mb-6 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl">
        <h4 className="font-bold text-blue-800 mb-2">Rate Priority (highest to lowest):</h4>
        <ol className="text-sm text-blue-700 font-medium space-y-1 list-decimal list-inside">
          <li><strong>User + Client</strong> — "John at Acme Corp = $200/hr"</li>
          <li><strong>Client</strong> — "Any user at Acme Corp = $175/hr"</li>
          <li><strong>User</strong> — "John = $150/hr everywhere"</li>
          <li><strong>Default</strong> — ${parseFloat(orgDefaultRate).toFixed(2)}/hr</li>
        </ol>
      </div>

      {showAdd && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-4">Add Custom Rate Override</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">User <span className="font-medium text-slate-500">(blank = all)</span></label>
              <select value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all bg-white">
                <option value="">All Users</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name || u.username}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Client <span className="font-medium text-slate-500">(blank = all)</span></label>
              <select value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all bg-white">
                <option value="">All Clients</option>
                {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Hourly Rate ($)</label>
              <input type="number" step="0.01" min="0" value={form.hourly_rate} onChange={(e) => setForm({ ...form, hourly_rate: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-semibold focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Effective Date</label>
              <input type="date" value={form.effective_date} onChange={(e) => setForm({ ...form, effective_date: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" />
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button onClick={handleSave} disabled={saving || (!form.user && !form.client)} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save Rate
            </button>
            <button onClick={resetForm} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
          </div>
          {!form.user && !form.client && (
            <p className="text-sm text-amber-600 font-semibold mt-3">⚠️ Select a user and/or client. To change the org default, go to the Organization tab.</p>
          )}
        </div>
      )}

      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">User</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Client</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Rate/Hour</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Effective</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {rates.length === 0 ? (
              <tr><td colSpan={5} className="text-center py-8 text-slate-500 font-medium">No custom rate overrides. All billing uses default (${parseFloat(orgDefaultRate).toFixed(2)}/hr).</td></tr>
            ) : (
              rates.map((rate) => (
                <tr key={rate.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-semibold text-slate-900">{rate.user_name || <span className="text-slate-400 italic font-medium">All Users</span>}</td>
                  <td className="px-4 py-3 font-semibold text-slate-900">{rate.client_name || <span className="text-slate-400 italic font-medium">All Clients</span>}</td>
                  <td className="px-4 py-3 text-right"><span className="font-extrabold text-emerald-600 text-lg">${parseFloat(rate.rate || rate.hourly_rate || '0').toFixed(2)}</span></td>
                  <td className="px-4 py-3 text-sm text-slate-500 font-medium">{new Date(rate.effective_date).toLocaleDateString()}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => handleDelete(rate.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-4 h-4" /></button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================================
// Employee Cost Rates Tab
// ============================================================================
function EmployeeCostRatesTab({
  rates,
  users,
  onRefresh,
  onSuccess,
  onError,
}: {
  rates: EmployeeCostRate[];
  users: TeamMember[];
  onRefresh: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ user: '', cost_rate: '75.00', effective_date: new Date().toISOString().split('T')[0] });

  const resetForm = () => {
    setForm({ user: '', cost_rate: '75.00', effective_date: new Date().toISOString().split('T')[0] });
    setShowAdd(false);
  };

  const handleSave = async () => {
    if (!form.user) { onError('Please select an employee'); return; }
    setSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/billing/cost-rates/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: parseInt(form.user, 10), cost_rate: form.cost_rate, effective_date: form.effective_date }),
      });
      onSuccess('Cost rate added');
      resetForm();
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (rateId: number) => {
    if (!confirm('Delete this cost rate?')) return;
    try {
      await safeFetchJson(`${API_BASE}/billing/cost-rates/${rateId}/`, { method: 'DELETE' });
      onSuccess('Cost rate deleted');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Users className="w-5 h-5 text-primary" />
          Employee Cost Rates
          <span className="text-sm font-bold text-slate-500">({rates.length})</span>
        </h2>
        <button onClick={() => setShowAdd(true)} className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all">
          <Plus className="w-4 h-4" />
          Add Cost Rate
        </button>
      </div>

      <div className="mb-6 p-4 bg-amber-50 border-2 border-amber-200 rounded-xl">
        <h4 className="font-bold text-amber-800 mb-2">What is a Cost Rate?</h4>
        <p className="text-sm text-amber-700 font-medium">
          The <strong>cost rate</strong> is what you pay an employee per hour (loaded labor cost). 
          Used to calculate profit: <em>Margin = Billing Rate - Cost Rate</em>.
        </p>
        <p className="text-sm text-amber-700 font-medium mt-2">
          Example: Bill client $150/hr, employee costs $75/hr → margin is $75/hr (50%).
        </p>
      </div>

      {showAdd && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-4">Add Employee Cost Rate</h3>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Employee *</label>
              <select value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all bg-white" required>
                <option value="">Select Employee</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name || u.username}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Hourly Cost ($)</label>
              <input type="number" step="0.01" min="0" value={form.cost_rate} onChange={(e) => setForm({ ...form, cost_rate: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-semibold focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Effective Date</label>
              <input type="date" value={form.effective_date} onChange={(e) => setForm({ ...form, effective_date: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" />
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button onClick={handleSave} disabled={saving || !form.user} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save Cost Rate
            </button>
            <button onClick={resetForm} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
          </div>
        </div>
      )}

      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Employee</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Cost/Hour</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Effective</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {rates.length === 0 ? (
              <tr><td colSpan={4} className="text-center py-8 text-slate-500 font-medium">No employee cost rates configured yet. Add cost rates to calculate profit margins.</td></tr>
            ) : (
              rates.map((rate) => (
                <tr key={rate.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3 font-bold text-slate-900">{rate.user_name}</td>
                  <td className="px-4 py-3 text-right"><span className="font-extrabold text-amber-600 text-lg">${parseFloat(rate.cost_rate).toFixed(2)}</span></td>
                  <td className="px-4 py-3 text-sm text-slate-500 font-medium">{new Date(rate.effective_date).toLocaleDateString()}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => handleDelete(rate.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-4 h-4" /></button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-6 p-4 bg-slate-100 rounded-xl">
        <h4 className="font-bold text-slate-800 text-sm mb-2">Calculating Loaded Labor Cost</h4>
        <div className="text-sm text-slate-600 font-medium space-y-1">
          <p>• Base salary ÷ 2080 hours = base hourly rate</p>
          <p>• + Benefits (health insurance, 401k match)</p>
          <p>• + Payroll taxes (FICA, unemployment)</p>
          <p>• + Overhead allocation (office, software)</p>
          <p className="mt-2 text-slate-700"><strong>Rule of thumb:</strong> Loaded cost is typically 1.25x to 1.5x base salary</p>
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
    if (diffHours < 1) return 'bg-emerald-500';
    if (diffHours < 24) return 'bg-amber-500';
    return 'bg-slate-400';
  };

  const handleDeactivate = async (deviceId: number, machineName: string) => {
    if (!confirm(`Deactivate agent on "${machineName}"?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/devices/${deviceId}/deactivate/`, { method: 'POST' });
      onSuccess('Device deactivated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to deactivate');
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Monitor className="w-5 h-5 text-primary" />
          Registered Devices
          <span className="text-sm font-bold text-slate-500">({devices.length})</span>
        </h2>
        <button onClick={onRefresh} className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>

      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100">
            <tr>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Status</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">User</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Machine</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">OS</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Version</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Last Seen</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {devices.map(device => (
              <tr key={device.id} className={cn('hover:bg-slate-50 transition-colors', !device.is_active && 'opacity-50')}>
                <td className="px-4 py-3"><div className={cn('w-3 h-3 rounded-full', device.is_active ? getStatusColor(device.last_seen) : 'bg-slate-300')} /></td>
                <td className="px-4 py-3 font-bold text-slate-900 text-sm">{device.user}</td>
                <td className="px-4 py-3 text-sm text-slate-700 font-medium">{device.machine_name}</td>
                <td className="px-4 py-3 text-sm text-slate-700 font-medium capitalize">{device.os}</td>
                <td className="px-4 py-3 text-sm text-slate-500 font-mono font-semibold">{device.agent_version || '—'}</td>
                <td className="px-4 py-3 text-sm text-slate-500 font-medium">{formatLastSeen(device.last_seen)}</td>
                <td className="px-4 py-3 text-right">
                  {device.is_active && (
                    <button onClick={() => handleDeactivate(device.id, device.machine_name)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors"><X className="w-4 h-4" /></button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {devices.length === 0 && (
          <div className="text-center py-8 text-slate-500 font-medium">No devices registered yet. Install the agent to start tracking.</div>
        )}
      </div>

      <div className="flex items-center gap-6 mt-4 text-sm text-slate-600 font-medium">
        <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-emerald-500" />Active now</div>
        <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-amber-500" />Active today</div>
        <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-slate-400" />Inactive</div>
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
      await safeFetchJson(`${API_BASE}/settings/install-token/regenerate/`, { method: 'POST' });
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
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Key className="w-5 h-5 text-primary" />
          Install Token
        </h2>
      </div>

      <div className="bg-slate-50 border-2 border-slate-200 rounded-xl p-6">
        <p className="text-sm text-slate-600 font-medium mb-4">
          Share this token with your IT team for MDM deployment. Agents will automatically register with your organization.
        </p>

        {token ? (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Organization Token</label>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-white border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm text-slate-900 font-semibold">
                  {showToken ? token.token : '••••••••••••••••••••••••••••••••'}
                </div>
                <button onClick={() => setShowToken(!showToken)} className="p-2.5 border-2 border-slate-200 rounded-xl hover:bg-slate-100 transition-all">
                  {showToken ? <EyeOff className="w-5 h-5 text-slate-600" /> : <Eye className="w-5 h-5 text-slate-600" />}
                </button>
                <button onClick={handleCopy} className="p-2.5 border-2 border-slate-200 rounded-xl hover:bg-slate-100 transition-all">
                  {copied ? <Check className="w-5 h-5 text-emerald-600" /> : <Copy className="w-5 h-5 text-slate-600" />}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <p className="text-sm text-slate-500 font-medium">Created: {new Date(token.created_at).toLocaleString()}</p>
              <button onClick={handleRegenerate} disabled={regenerating} className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-red-200 text-red-600 rounded-xl font-bold hover:bg-red-50 transition-all disabled:opacity-50">
                {regenerating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                Regenerate Token
              </button>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-slate-500 font-medium mb-4">No install token exists yet.</p>
            <button onClick={handleRegenerate} disabled={regenerating} className="px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">Generate Token</button>
          </div>
        )}
      </div>

      <div className="mt-6 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl">
        <h3 className="font-bold text-blue-900 mb-3">MDM Deployment Instructions</h3>
        <ol className="text-sm text-blue-800 font-medium space-y-2 list-decimal list-inside">
          <li>Download the TimeTracker installer (.pkg for Mac, .msi for Windows)</li>
          <li>Create a configuration file with the token above</li>
          <li>Deploy both via your MDM (Jamf, Intune, Kandji, etc.)</li>
          <li>Agents will auto-register when users log in</li>
        </ol>
        <p className="text-sm text-blue-600 font-semibold mt-4">Need help? Contact support@mavops.ai</p>
      </div>
    </div>
  );
}