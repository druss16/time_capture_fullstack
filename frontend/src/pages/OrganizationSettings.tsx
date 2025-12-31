/**
 * Settings.tsx — Org Admin Settings Page
 * Simpler layout with tabs in content area (not full sidebar)
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

// Types (same as before)
type OrgInfo = { id: number; name: string; billing_email: string; billing_contact: string; billing_rate_default: string; created_at: string; };
type TeamMember = { id: number; username: string; email: string; first_name: string; last_name: string; is_active: boolean; role: 'owner' | 'admin' | 'manager' | 'member'; last_login: string | null; date_joined: string; };
type Client = { id: number; name: string; code: string; is_active: boolean; created_at: string; };
type Device = { id: number; user: string; user_id: number; machine_name: string; os: string; os_version: string; agent_version: string; first_seen: string; last_seen: string; is_active: boolean; };
type InstallToken = { token: string; created_at: string; is_active: boolean; };
type BillingRate = { id: number; user: number | null; user_name: string; client: number | null; client_name: string; task_type: number | null; task_type_name: string; rate: string; hourly_rate?: string; effective_date: string; end_date: string | null; is_default: boolean; };
type EmployeeCostRate = { id: number; user: number; user_name: string; cost_rate: string; effective_date: string; end_date: string | null; };
type Tab = 'organization' | 'team' | 'clients' | 'billing' | 'costs' | 'devices' | 'token';

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'organization', label: 'Organization', icon: Building2 },
  { id: 'team', label: 'Team', icon: Users },
  { id: 'clients', label: 'Clients', icon: Briefcase },
  { id: 'billing', label: 'Billing Rates', icon: DollarSign },
  { id: 'costs', label: 'Costs', icon: Users },
  { id: 'devices', label: 'Devices', icon: Monitor },
  { id: 'token', label: 'Token', icon: Key },
];

export default function Settings() {
  const [activeTab, setActiveTab] = useState<Tab>('organization');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [orgInfo, setOrgInfo] = useState<OrgInfo | null>(null);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [installToken, setInstallToken] = useState<InstallToken | null>(null);
  const [billingRates, setBillingRates] = useState<BillingRate[]>([]);
  const [employeeCostRates, setEmployeeCostRates] = useState<EmployeeCostRate[]>([]);
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [currentUserRole, setCurrentUserRole] = useState<string>('member');

  const showSuccess = (msg: string) => { setSuccess(msg); setTimeout(() => setSuccess(null), 3000); };
  const showError = (msg: string) => { setError(msg); setTimeout(() => setError(null), 5000); };

  useEffect(() => {
    safeFetchJson<any>(`${API_BASE}/whoami/`).then(w => setCurrentUserId(w.user_id)).catch(() => {});
  }, []);

  const loadTabData = useCallback(async (tab: Tab) => {
    setLoading(true);
    setError(null);
    try {
      switch (tab) {
        case 'organization': setOrgInfo(await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`)); break;
        case 'team':
          const team = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`);
          setTeamMembers(team || []);
          if (currentUserId) { const m = team.find(t => t.id === currentUserId); if (m) setCurrentUserRole(m.role); }
          break;
        case 'clients': setClients(await safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`) || []); break;
        case 'billing':
          setBillingRates(await safeFetchJson<BillingRate[]>(`${API_BASE}/billing/rates/`) || []);
          setClients(await safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []) || []);
          setTeamMembers(await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []) || []);
          break;
        case 'costs':
          setEmployeeCostRates(await safeFetchJson<EmployeeCostRate[]>(`${API_BASE}/billing/cost-rates/`).catch(() => []) || []);
          setTeamMembers(await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []) || []);
          break;
        case 'devices': setDevices(await safeFetchJson<Device[]>(`${API_BASE}/settings/devices/`) || []); break;
        case 'token': setInstallToken(await safeFetchJson<InstallToken>(`${API_BASE}/settings/install-token/`)); break;
      }
    } catch (err: any) { showError(err?.message || 'Failed to load'); }
    finally { setLoading(false); }
  }, [currentUserId]);

  useEffect(() => { loadTabData(activeTab); }, [activeTab, loadTabData]);

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Toasts */}
      {success && <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-xl flex items-center gap-2 bg-emerald-500 text-white font-bold"><CheckCircle2 className="w-4 h-4" />{success}</div>}
      {error && <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-xl flex items-center gap-2 bg-red-500 text-white font-bold"><AlertCircle className="w-4 h-4" />{error}</div>}

      <div className="max-w-6xl mx-auto p-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/25">
            <SettingsIcon className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">Settings</h1>
            <p className="text-slate-600 font-medium">Manage your organization</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="bg-white rounded-2xl border-2 border-slate-200 shadow-sm overflow-hidden">
          <div className="border-b-2 border-slate-200 px-4 overflow-x-auto">
            <nav className="flex gap-1 -mb-0.5">
              {TABS.map(tab => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'flex items-center gap-2 px-4 py-3 text-sm font-bold border-b-2 transition-all whitespace-nowrap',
                      isActive
                        ? 'border-primary text-primary'
                        : 'border-transparent text-slate-500 hover:text-slate-900 hover:border-slate-300'
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    {tab.label}
                  </button>
                );
              })}
            </nav>
          </div>

          {/* Content */}
          <div className="p-6">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <RefreshCw className="w-6 h-6 text-primary animate-spin" />
              </div>
            ) : (
              <>
                {activeTab === 'organization' && <OrganizationTab orgInfo={orgInfo} onUpdate={setOrgInfo} onSuccess={showSuccess} onError={showError} />}
                {activeTab === 'team' && <TeamTab members={teamMembers} currentUserId={currentUserId} currentUserRole={currentUserRole} onRefresh={() => loadTabData('team')} onSuccess={showSuccess} onError={showError} />}
                {activeTab === 'clients' && <ClientsTab clients={clients} onRefresh={() => loadTabData('clients')} onSuccess={showSuccess} onError={showError} />}
                {activeTab === 'billing' && <BillingRatesTab rates={billingRates} users={teamMembers} clients={clients} orgDefaultRate={orgInfo?.billing_rate_default || '150.00'} onRefresh={() => loadTabData('billing')} onSuccess={showSuccess} onError={showError} />}
                {activeTab === 'costs' && <EmployeeCostRatesTab rates={employeeCostRates} users={teamMembers} onRefresh={() => loadTabData('costs')} onSuccess={showSuccess} onError={showError} />}
                {activeTab === 'devices' && <DevicesTab devices={devices} onRefresh={() => loadTabData('devices')} onSuccess={showSuccess} onError={showError} />}
                {activeTab === 'token' && <TokenTab token={installToken} onRefresh={() => loadTabData('token')} onSuccess={showSuccess} onError={showError} />}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Tab Components (simplified versions - same styling, less verbose)
// ============================================================================

function OrganizationTab({ orgInfo, onUpdate, onSuccess, onError }: { orgInfo: OrgInfo | null; onUpdate: (o: OrgInfo) => void; onSuccess: (m: string) => void; onError: (m: string) => void; }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: '', billing_email: '', billing_contact: '', billing_rate_default: '150.00' });

  useEffect(() => { if (orgInfo) setForm({ name: orgInfo.name || '', billing_email: orgInfo.billing_email || '', billing_contact: orgInfo.billing_contact || '', billing_rate_default: orgInfo.billing_rate_default || '150.00' }); }, [orgInfo]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      onUpdate(updated); setEditing(false); onSuccess('Organization updated');
    } catch (e: any) { onError(e?.message || 'Failed'); } finally { setSaving(false); }
  };

  if (!orgInfo) return <div className="text-slate-500 font-medium">No organization data</div>;

  return editing ? (
    <div className="space-y-5 max-w-lg">
      <div><label className="block text-sm font-bold text-slate-800 mb-2">Organization Name</label><input type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:outline-none" /></div>
      <div><label className="block text-sm font-bold text-slate-800 mb-2">Billing Email</label><input type="email" value={form.billing_email} onChange={e => setForm({ ...form, billing_email: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:outline-none" /></div>
      <div><label className="block text-sm font-bold text-slate-800 mb-2">Billing Contact</label><input type="text" value={form.billing_contact} onChange={e => setForm({ ...form, billing_contact: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:outline-none" /></div>
      <div className="pt-4 border-t-2 border-slate-200">
        <label className="block text-sm font-bold text-slate-800 mb-2">Default Billing Rate</label>
        <div className="relative max-w-xs"><span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold">$</span><input type="number" step="0.01" value={form.billing_rate_default} onChange={e => setForm({ ...form, billing_rate_default: e.target.value })} className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl text-slate-900 font-semibold focus:border-primary focus:outline-none" /></div>
      </div>
      <div className="flex gap-3 pt-4">
        <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold disabled:opacity-50">{saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}Save</button>
        <button onClick={() => setEditing(false)} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700">Cancel</button>
      </div>
    </div>
  ) : (
    <div className="space-y-6">
      <div className="flex justify-between items-start">
        <div className="grid grid-cols-2 gap-6">
          <div><p className="text-sm text-slate-500 font-semibold mb-1">Organization Name</p><p className="text-slate-900 font-bold">{orgInfo.name}</p></div>
          <div><p className="text-sm text-slate-500 font-semibold mb-1">Created</p><p className="text-slate-900 font-bold">{new Date(orgInfo.created_at).toLocaleDateString()}</p></div>
          <div><p className="text-sm text-slate-500 font-semibold mb-1">Billing Email</p><p className="text-slate-900 font-bold">{orgInfo.billing_email || '—'}</p></div>
          <div><p className="text-sm text-slate-500 font-semibold mb-1">Billing Contact</p><p className="text-slate-900 font-bold">{orgInfo.billing_contact || '—'}</p></div>
        </div>
        <button onClick={() => setEditing(true)} className="flex items-center gap-2 px-4 py-2 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-50"><Pencil className="w-4 h-4" />Edit</button>
      </div>
      <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-4 flex items-center justify-between">
        <div><p className="text-sm text-emerald-700 font-bold flex items-center gap-2"><DollarSign className="w-4 h-4" />Default Hourly Rate</p><p className="text-2xl font-extrabold text-emerald-700">${parseFloat(orgInfo.billing_rate_default || '150').toFixed(2)}/hr</p></div>
        <span className="bg-emerald-100 text-emerald-800 px-3 py-1.5 rounded-full text-xs font-bold">Firm Default</span>
      </div>
    </div>
  );
}

function TeamTab({ members, currentUserId, currentUserRole, onRefresh, onSuccess, onError }: { members: TeamMember[]; currentUserId: number | null; currentUserRole: string; onRefresh: () => void; onSuccess: (m: string) => void; onError: (m: string) => void; }) {
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviting, setInviting] = useState(false);

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    try {
      const r = await safeFetchJson<any>(`${API_BASE}/settings/team/invite/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: inviteEmail }) });
      if (r.temp_password && !r.email_sent) alert(`User created!\nUsername: ${r.username}\nTemp Password: ${r.temp_password}`);
      onSuccess(r.email_sent ? 'Invitation sent' : 'User created');
      setInviteEmail(''); setShowInvite(false); onRefresh();
    } catch (e: any) { onError(e?.message || 'Failed'); } finally { setInviting(false); }
  };

  const getRoleBadge = (role: string) => ({ owner: 'bg-purple-100 text-purple-800', admin: 'bg-blue-100 text-blue-800', manager: 'bg-emerald-100 text-emerald-800' }[role] || 'bg-slate-100 text-slate-700');
  const formatLastSeen = (d: string | null) => { if (!d) return 'Never'; const diff = (Date.now() - new Date(d).getTime()) / 60000; if (diff < 1) return 'Just now'; if (diff < 60) return `${Math.floor(diff)}m ago`; if (diff < 1440) return `${Math.floor(diff/60)}h ago`; return new Date(d).toLocaleDateString(); };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-600 font-medium">{members.length} team member{members.length !== 1 ? 's' : ''}</p>
        <button onClick={() => setShowInvite(true)} className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm"><UserPlus className="w-4 h-4" />Invite</button>
      </div>
      {showInvite && (
        <div className="mb-4 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl flex gap-2">
          <input type="email" value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} placeholder="email@company.com" className="flex-1 border-2 border-slate-200 rounded-xl px-4 py-2 font-medium focus:border-primary focus:outline-none" />
          <button onClick={handleInvite} disabled={inviting || !inviteEmail.trim()} className="px-4 py-2 bg-primary text-white rounded-xl font-bold disabled:opacity-50">{inviting ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Send'}</button>
          <button onClick={() => setShowInvite(false)} className="px-4 py-2 border-2 border-slate-200 rounded-xl font-bold">Cancel</button>
        </div>
      )}
      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100"><tr><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">User</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Email</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Role</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Last Active</th></tr></thead>
          <tbody className="divide-y divide-slate-200">
            {members.map(m => (
              <tr key={m.id} className="hover:bg-slate-50">
                <td className="px-4 py-3"><div className="flex items-center gap-3"><div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-sm font-bold text-primary">{(m.first_name?.[0] || m.username[0]).toUpperCase()}</div><div><p className="font-bold text-slate-900 text-sm">{m.first_name} {m.last_name || m.username}{m.id === currentUserId && <span className="ml-1 text-xs text-slate-500">(you)</span>}</p><p className="text-xs text-slate-500">@{m.username}</p></div></div></td>
                <td className="px-4 py-3 text-sm text-slate-700">{m.email || '—'}</td>
                <td className="px-4 py-3"><span className={cn('text-xs px-2 py-1 rounded-full font-bold', getRoleBadge(m.role))}>{m.role.charAt(0).toUpperCase() + m.role.slice(1)}</span></td>
                <td className="px-4 py-3 text-sm text-slate-500">{formatLastSeen(m.last_login)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {members.length === 0 && <div className="text-center py-8 text-slate-500 font-medium">No team members</div>}
      </div>
    </div>
  );
}

function ClientsTab({ clients, onRefresh, onSuccess, onError }: { clients: Client[]; onRefresh: () => void; onSuccess: (m: string) => void; onError: (m: string) => void; }) {
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: '', code: '' });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/clients/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      onSuccess('Client added'); setForm({ name: '', code: '' }); setShowAdd(false); onRefresh();
    } catch (e: any) { onError(e?.message || 'Failed'); } finally { setSaving(false); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-600 font-medium">{clients.length} client{clients.length !== 1 ? 's' : ''}</p>
        <button onClick={() => setShowAdd(true)} className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm"><Plus className="w-4 h-4" />Add Client</button>
      </div>
      {showAdd && (
        <div className="mb-4 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div><label className="block text-sm font-bold text-slate-800 mb-1">Name *</label><input type="text" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2 font-medium focus:border-primary focus:outline-none" /></div>
            <div><label className="block text-sm font-bold text-slate-800 mb-1">Code</label><input type="text" value={form.code} onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2 font-medium focus:border-primary focus:outline-none uppercase" /></div>
          </div>
          <div className="flex gap-2"><button onClick={handleSave} disabled={saving || !form.name.trim()} className="px-4 py-2 bg-primary text-white rounded-xl font-bold disabled:opacity-50">{saving ? 'Saving...' : 'Add'}</button><button onClick={() => setShowAdd(false)} className="px-4 py-2 border-2 border-slate-200 rounded-xl font-bold">Cancel</button></div>
        </div>
      )}
      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100"><tr><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Client</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Code</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Status</th></tr></thead>
          <tbody className="divide-y divide-slate-200">
            {clients.map(c => (
              <tr key={c.id} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-bold text-slate-900">{c.name}</td>
                <td className="px-4 py-3 text-sm text-slate-500 font-mono font-semibold">{c.code || '—'}</td>
                <td className="px-4 py-3"><span className={cn('text-xs px-2 py-1 rounded-full font-bold', c.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500')}>{c.is_active ? 'Active' : 'Inactive'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        {clients.length === 0 && <div className="text-center py-8 text-slate-500 font-medium">No clients yet</div>}
      </div>
    </div>
  );
}

function BillingRatesTab({ rates, users, clients, orgDefaultRate, onRefresh, onSuccess, onError }: { rates: BillingRate[]; users: TeamMember[]; clients: Client[]; orgDefaultRate: string; onRefresh: () => void; onSuccess: (m: string) => void; onError: (m: string) => void; }) {
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ user: '', client: '', rate: '150.00' });

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: any = { rate: form.rate, effective_date: new Date().toISOString().split('T')[0] };
      if (form.user) payload.user_id = parseInt(form.user);
      if (form.client) payload.client_id = parseInt(form.client);
      await safeFetchJson(`${API_BASE}/billing/rates/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      onSuccess('Rate added'); setForm({ user: '', client: '', rate: '150.00' }); setShowAdd(false); onRefresh();
    } catch (e: any) { onError(e?.message || 'Failed'); } finally { setSaving(false); }
  };

  const handleDelete = async (id: number) => { if (!confirm('Delete?')) return; try { await safeFetchJson(`${API_BASE}/billing/rates/${id}/`, { method: 'DELETE' }); onSuccess('Deleted'); onRefresh(); } catch (e: any) { onError(e?.message || 'Failed'); } };

  return (
    <div>
      <div className="mb-4 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl flex items-center justify-between">
        <div><p className="text-sm text-emerald-700 font-bold">Default Rate</p><p className="text-2xl font-extrabold text-emerald-700">${parseFloat(orgDefaultRate).toFixed(2)}/hr</p></div>
        <span className="text-xs text-emerald-600 font-medium">Edit in Organization tab</span>
      </div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-600 font-medium">{rates.length} custom rate{rates.length !== 1 ? 's' : ''}</p>
        <button onClick={() => setShowAdd(true)} className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm"><Plus className="w-4 h-4" />Add Rate</button>
      </div>
      {showAdd && (
        <div className="mb-4 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div><label className="block text-sm font-bold text-slate-800 mb-1">User</label><select value={form.user} onChange={e => setForm({ ...form, user: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2 font-medium bg-white"><option value="">All</option>{users.map(u => <option key={u.id} value={u.id}>{u.first_name} {u.last_name}</option>)}</select></div>
            <div><label className="block text-sm font-bold text-slate-800 mb-1">Client</label><select value={form.client} onChange={e => setForm({ ...form, client: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2 font-medium bg-white"><option value="">All</option>{clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
            <div><label className="block text-sm font-bold text-slate-800 mb-1">Rate ($)</label><input type="number" step="0.01" value={form.rate} onChange={e => setForm({ ...form, rate: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2 font-semibold" /></div>
          </div>
          <div className="flex gap-2"><button onClick={handleSave} disabled={saving || (!form.user && !form.client)} className="px-4 py-2 bg-primary text-white rounded-xl font-bold disabled:opacity-50">{saving ? 'Saving...' : 'Add'}</button><button onClick={() => setShowAdd(false)} className="px-4 py-2 border-2 border-slate-200 rounded-xl font-bold">Cancel</button></div>
        </div>
      )}
      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100"><tr><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">User</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Client</th><th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Rate</th><th className="w-12"></th></tr></thead>
          <tbody className="divide-y divide-slate-200">
            {rates.length === 0 ? <tr><td colSpan={4} className="text-center py-8 text-slate-500 font-medium">No custom rates</td></tr> : rates.map(r => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-semibold text-slate-900">{r.user_name || <span className="text-slate-400 italic">All</span>}</td>
                <td className="px-4 py-3 font-semibold text-slate-900">{r.client_name || <span className="text-slate-400 italic">All</span>}</td>
                <td className="px-4 py-3 text-right font-extrabold text-emerald-600">${parseFloat(r.rate || r.hourly_rate || '0').toFixed(2)}</td>
                <td className="px-4 py-3"><button onClick={() => handleDelete(r.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg"><Trash2 className="w-4 h-4" /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EmployeeCostRatesTab({ rates, users, onRefresh, onSuccess, onError }: { rates: EmployeeCostRate[]; users: TeamMember[]; onRefresh: () => void; onSuccess: (m: string) => void; onError: (m: string) => void; }) {
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ user: '', cost_rate: '75.00' });

  const handleSave = async () => {
    if (!form.user) { onError('Select employee'); return; }
    setSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/billing/cost-rates/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user: parseInt(form.user), cost_rate: form.cost_rate, effective_date: new Date().toISOString().split('T')[0] }) });
      onSuccess('Cost rate added'); setForm({ user: '', cost_rate: '75.00' }); setShowAdd(false); onRefresh();
    } catch (e: any) { onError(e?.message || 'Failed'); } finally { setSaving(false); }
  };

  const handleDelete = async (id: number) => { if (!confirm('Delete?')) return; try { await safeFetchJson(`${API_BASE}/billing/cost-rates/${id}/`, { method: 'DELETE' }); onSuccess('Deleted'); onRefresh(); } catch (e: any) { onError(e?.message || 'Failed'); } };

  return (
    <div>
      <div className="mb-4 p-4 bg-amber-50 border-2 border-amber-200 rounded-xl"><p className="font-bold text-amber-800">Cost Rate</p><p className="text-sm text-amber-700 font-medium">What you pay employees per hour. Margin = Billing Rate - Cost Rate.</p></div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-600 font-medium">{rates.length} cost rate{rates.length !== 1 ? 's' : ''}</p>
        <button onClick={() => setShowAdd(true)} className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm"><Plus className="w-4 h-4" />Add</button>
      </div>
      {showAdd && (
        <div className="mb-4 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div><label className="block text-sm font-bold text-slate-800 mb-1">Employee *</label><select value={form.user} onChange={e => setForm({ ...form, user: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2 font-medium bg-white"><option value="">Select</option>{users.map(u => <option key={u.id} value={u.id}>{u.first_name} {u.last_name}</option>)}</select></div>
            <div><label className="block text-sm font-bold text-slate-800 mb-1">Hourly Cost ($)</label><input type="number" step="0.01" value={form.cost_rate} onChange={e => setForm({ ...form, cost_rate: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2 font-semibold" /></div>
          </div>
          <div className="flex gap-2"><button onClick={handleSave} disabled={saving || !form.user} className="px-4 py-2 bg-primary text-white rounded-xl font-bold disabled:opacity-50">{saving ? 'Saving...' : 'Add'}</button><button onClick={() => setShowAdd(false)} className="px-4 py-2 border-2 border-slate-200 rounded-xl font-bold">Cancel</button></div>
        </div>
      )}
      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100"><tr><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Employee</th><th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Cost/Hr</th><th className="w-12"></th></tr></thead>
          <tbody className="divide-y divide-slate-200">
            {rates.length === 0 ? <tr><td colSpan={3} className="text-center py-8 text-slate-500 font-medium">No cost rates</td></tr> : rates.map(r => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-bold text-slate-900">{r.user_name}</td>
                <td className="px-4 py-3 text-right font-extrabold text-amber-600">${parseFloat(r.cost_rate).toFixed(2)}</td>
                <td className="px-4 py-3"><button onClick={() => handleDelete(r.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg"><Trash2 className="w-4 h-4" /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DevicesTab({ devices, onRefresh, onSuccess, onError }: { devices: Device[]; onRefresh: () => void; onSuccess: (m: string) => void; onError: (m: string) => void; }) {
  const formatLastSeen = (d: string) => { const diff = (Date.now() - new Date(d).getTime()) / 60000; if (diff < 1) return 'Just now'; if (diff < 60) return `${Math.floor(diff)}m ago`; if (diff < 1440) return `${Math.floor(diff/60)}h ago`; return new Date(d).toLocaleDateString(); };
  const getStatusColor = (d: string) => { const h = (Date.now() - new Date(d).getTime()) / 3600000; return h < 1 ? 'bg-emerald-500' : h < 24 ? 'bg-amber-500' : 'bg-slate-400'; };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-600 font-medium">{devices.length} device{devices.length !== 1 ? 's' : ''}</p>
        <button onClick={onRefresh} className="flex items-center gap-2 px-4 py-2 border-2 border-slate-200 rounded-xl font-bold text-slate-700 text-sm"><RefreshCw className="w-4 h-4" />Refresh</button>
      </div>
      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100"><tr><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Status</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">User</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Machine</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">OS</th><th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Last Seen</th></tr></thead>
          <tbody className="divide-y divide-slate-200">
            {devices.length === 0 ? <tr><td colSpan={5} className="text-center py-8 text-slate-500 font-medium">No devices</td></tr> : devices.map(d => (
              <tr key={d.id} className={cn('hover:bg-slate-50', !d.is_active && 'opacity-50')}>
                <td className="px-4 py-3"><div className={cn('w-3 h-3 rounded-full', d.is_active ? getStatusColor(d.last_seen) : 'bg-slate-300')} /></td>
                <td className="px-4 py-3 font-bold text-slate-900 text-sm">{d.user}</td>
                <td className="px-4 py-3 text-sm text-slate-700">{d.machine_name}</td>
                <td className="px-4 py-3 text-sm text-slate-700 capitalize">{d.os}</td>
                <td className="px-4 py-3 text-sm text-slate-500">{formatLastSeen(d.last_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {devices.length > 0 && <div className="flex items-center gap-6 mt-4 text-sm text-slate-500 font-medium"><div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-emerald-500" />Now</div><div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-amber-500" />Today</div><div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-slate-400" />Inactive</div></div>}
    </div>
  );
}

function TokenTab({ token, onRefresh, onSuccess, onError }: { token: InstallToken | null; onRefresh: () => void; onSuccess: (m: string) => void; onError: (m: string) => void; }) {
  const [show, setShow] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => { if (token?.token) { navigator.clipboard.writeText(token.token); setCopied(true); setTimeout(() => setCopied(false), 2000); } };
  const handleRegenerate = async () => { if (!confirm('Regenerate? Old token will stop working.')) return; setRegenerating(true); try { await safeFetchJson(`${API_BASE}/settings/install-token/regenerate/`, { method: 'POST' }); onSuccess('Token regenerated'); onRefresh(); } catch (e: any) { onError(e?.message || 'Failed'); } finally { setRegenerating(false); } };

  return (
    <div className="max-w-xl">
      <p className="text-sm text-slate-600 font-medium mb-4">Share this token with IT for MDM deployment. Agents will auto-register.</p>
      {token ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <div className="flex-1 bg-slate-100 border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm font-semibold">{show ? token.token : '••••••••••••••••••••••••••••••••'}</div>
            <button onClick={() => setShow(!show)} className="p-2.5 border-2 border-slate-200 rounded-xl hover:bg-slate-50">{show ? <EyeOff className="w-5 h-5 text-slate-600" /> : <Eye className="w-5 h-5 text-slate-600" />}</button>
            <button onClick={handleCopy} className="p-2.5 border-2 border-slate-200 rounded-xl hover:bg-slate-50">{copied ? <Check className="w-5 h-5 text-emerald-600" /> : <Copy className="w-5 h-5 text-slate-600" />}</button>
          </div>
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500">Created: {new Date(token.created_at).toLocaleString()}</p>
            <button onClick={handleRegenerate} disabled={regenerating} className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-red-200 text-red-600 rounded-xl font-bold hover:bg-red-50 disabled:opacity-50">{regenerating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}Regenerate</button>
          </div>
        </div>
      ) : (
        <div className="text-center py-8"><p className="text-slate-500 font-medium mb-4">No token yet.</p><button onClick={handleRegenerate} disabled={regenerating} className="px-5 py-2.5 bg-primary text-white rounded-xl font-bold disabled:opacity-50">Generate Token</button></div>
      )}
    </div>
  );
}