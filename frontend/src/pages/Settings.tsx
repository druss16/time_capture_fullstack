/**
 * Settings.tsx — Org Admin Settings Page
 * With Plan-Based Feature Gating & Bulk Assignment
 * Professional plan: Organization, Team, Clients, Devices, Token
 * Executive plan: All features including Billing Rates & Employee Costs
 * 
 * FIXES APPLIED:
 * 1. Added getUserDisplayName() helper for consistent name display
 * 2. Fixed employee dropdowns in BillingRatesTab, EmployeeCostRatesTab
 * 3. Fixed OrganizationTab state refresh after save
 * 4. Fixed BulkAssignModal user display
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { ShieldCheck } from "lucide-react";
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
  UserMinus,
  Eye,
  EyeOff,
  DollarSign,
  Lock,
  Shield,
  Sparkles,
  Upload,
  CheckSquare,
  Square,
  MinusSquare,
  FileSpreadsheet,
  Download,
  Loader2,
  ChevronDown,
  Calendar,
  Folder,
} from "lucide-react";
import { cn } from "@/lib/design-system";
import { safeFetchJson } from "@/lib/api";

import ClientAssignmentManager from '@/components/ClientAssignmentManager';
import ClientImportWizard from '@/components/ClientImportWizard';
import ClientGroupManager from '@/components/ClientGroupManager';  // ← ADD THIS

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

// Types
type PlanType = 'professional' | 'executive' | 'none';
type RoleType = 'owner' | 'admin' | 'manager' | 'member';

type OrgInfo = {
  id: number;
  name: string;
  slug?: string;
  plan: PlanType;
  trial_ends_at: string | null;
  billing_email: string;
  billing_contact: string;
  billing_rate_default: string;
  cost_rate_default?: string;
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
  visibility: 'all' | 'assigned' | 'confidential';
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

type Tab = 'organization' | 'team' | 'clients' | 'assignments' | 'groups' | 'billing' | 'costs' | 'devices' | 'token';
//                                                              
// Define which plans can access which features
const PROFESSIONAL_PLANS: PlanType[] = ['professional', 'executive'];
const EXECUTIVE_PLANS: PlanType[] = ['executive'];

interface TabConfig {
  id: Tab;
  label: string;
  icon: React.ReactNode;
  requiredPlan?: PlanType[];
  requiredRole?: ('owner' | 'admin' | 'manager')[];
}

// ============================================================================
// HELPER: Get user display name with fallbacks
// ============================================================================
const getUserDisplayName = (user: TeamMember): string => {
  // Try full name first
  const fullName = `${user.first_name || ''} ${user.last_name || ''}`.trim();
  if (fullName) return fullName;
  
  // Fallback to first_name only
  if (user.first_name) return user.first_name;
  
  // Fallback to last_name only
  if (user.last_name) return user.last_name;
  
  // Fallback to username
  if (user.username) return user.username;
  
  // Fallback to email
  if (user.email) return user.email;
  
  // Last resort: User ID
  return `User ${user.id}`;
};

// ============================================================================
// Upgrade Prompt Component
// ============================================================================
function UpgradePrompt({ featureName }: { featureName: string }) {
  return (
    <div className="relative flex items-center justify-center min-h-[400px]">
      <div className="absolute inset-0 overflow-hidden rounded-2xl">
        <div className="w-full h-full bg-gradient-to-br from-slate-100 to-slate-200 opacity-60 blur-sm" />
        <div className="absolute inset-0 p-6 opacity-30 blur-[2px]">
          <div className="h-8 w-48 bg-slate-300 rounded mb-4" />
          <div className="h-20 bg-emerald-100 rounded-xl mb-4" />
          <div className="h-16 bg-blue-50 rounded-xl mb-6" />
          <div className="space-y-3">
            <div className="h-12 bg-slate-200 rounded-lg" />
            <div className="h-12 bg-slate-200 rounded-lg" />
            <div className="h-12 bg-slate-200 rounded-lg" />
          </div>
        </div>
      </div>
      
      <div className="relative z-10 text-center p-8 bg-white/95 backdrop-blur-sm rounded-2xl shadow-xl border-2 border-slate-200 max-w-md">
        <div className="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <Lock className="w-8 h-8 text-slate-400" />
        </div>
        <h3 className="text-xl font-extrabold text-slate-900 mb-2">
          {featureName}
        </h3>
        <p className="text-slate-600 font-medium mb-6">
          This feature is available on the <span className="font-bold text-primary">Executive</span> plan.
          Upgrade to unlock advanced billing rate management and profitability tracking.
        </p>
        <a
          href="/account/billing"
          className="inline-flex items-center gap-2 px-6 py-3 bg-primary text-white font-bold rounded-xl hover:opacity-90 transition-all shadow-lg shadow-primary/25"
        >
          <Sparkles className="w-5 h-5" />
          Upgrade to Executive
        </a>
        <p className="text-sm text-slate-500 font-medium mt-4">
          See pricing in Billing
        </p>
      </div>
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================
export default function Settings() {
  const [activeTab, setActiveTab] = useState<Tab>('organization');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [orgInfo, setOrgInfo] = useState<OrgInfo | null>(null);
  const [orgPlan, setOrgPlan] = useState<PlanType>('professional');
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
        setCurrentUserRole(whoami.role || 'member');
      } catch (err) {
        console.error('Failed to load user info:', err);
      }
    };
    loadUserInfo();
  }, []);

  useEffect(() => {
    const loadOrgPlan = async () => {
      try {
        const org = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`);
        setOrgInfo(org);
        setOrgPlan(org.plan || 'professional');
      } catch (err) {
        console.error('Failed to load org plan:', err);
        setOrgPlan('professional');
      }
    };
    loadOrgPlan();
  }, []);

  const loadTabData = useCallback(async (tab: Tab) => {
    setLoading(true);
    setError(null);
    try {
      switch (tab) {
        case 'organization':
          const org = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`);
          setOrgInfo(org);
          setOrgPlan(org.plan || 'professional');
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

        case 'groups':
          const [groupClients, groupTeam] = await Promise.all([
            safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
            safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
          ]);
          setClients(groupClients || []);
          setTeamMembers(groupTeam || []);
          break;
          
        case 'clients':
          const [clientList, clientsTeam] = await Promise.all([
            safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
            safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
          ]);
          setClients(clientList || []);
          setTeamMembers(clientsTeam || []);
          break;
          
        case 'assignments':
          const [assignmentClients, assignmentTeam] = await Promise.all([
            safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
            safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
          ]);
          setClients(assignmentClients || []);
          setTeamMembers(assignmentTeam || []);
          break;
          
        case 'billing':
          if (EXECUTIVE_PLANS.includes(orgPlan)) {
            const rates = await safeFetchJson<BillingRate[]>(`${API_BASE}/billing/rates/`);
            setBillingRates(rates || []);
            const [clientsForRates, teamForRates] = await Promise.all([
              safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
              safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
            ]);
            setClients(clientsForRates || []);
            setTeamMembers(teamForRates || []);
          }
          break;
          
        case 'costs':
          if (EXECUTIVE_PLANS.includes(orgPlan)) {
            const costRates = await safeFetchJson<EmployeeCostRate[]>(`${API_BASE}/billing/cost-rates/`).catch(() => []);
            setEmployeeCostRates(costRates || []);
            const teamForCosts = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []);
            setTeamMembers(teamForCosts || []);
          }
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
  }, [currentUserId, orgPlan]);

  useEffect(() => {
    loadTabData(activeTab);
  }, [activeTab, loadTabData]);

  const tabs: TabConfig[] = [
  { id: 'organization', label: 'Organization', icon: <Building2 className="w-4 h-4" /> },
  { id: 'team', label: 'Team Members', icon: <Users className="w-4 h-4" /> },
  { id: 'clients', label: 'Clients', icon: <Briefcase className="w-4 h-4" /> },
  { id: 'assignments', label: 'Client Access', icon: <Shield className="w-4 h-4" />, requiredRole: ['owner', 'admin', 'manager'] },
  { id: 'groups', label: 'Client Groups', icon: <Folder className="w-4 h-4" />, requiredRole: ['owner', 'admin', 'manager'] },  // ← ADD THIS
  { id: 'billing', label: 'Billing Rates', icon: <DollarSign className="w-4 h-4" />, requiredPlan: EXECUTIVE_PLANS },
  { id: 'costs', label: 'Employee Costs', icon: <Users className="w-4 h-4" />, requiredPlan: EXECUTIVE_PLANS },
  { id: 'devices', label: 'Devices', icon: <Monitor className="w-4 h-4" /> },
  { id: 'token', label: 'Install Token', icon: <Key className="w-4 h-4" /> },
];

  const isTabLocked = (tab: TabConfig): boolean => {
    if (!tab.requiredPlan) return false;
    return !tab.requiredPlan.includes(orgPlan);
  };

  const getLockedFeatureName = (tabId: Tab): string => {
    switch (tabId) {
      case 'billing': return 'Billing Rates';
      case 'costs': return 'Employee Cost Rates';
      default: return 'This Feature';
    }
  };

  const getPlanLabel = (plan: PlanType) => {
    switch (plan) {
      case 'executive': return '💎 Executive';
      case 'professional': return '⭐ Professional';
      default: return '🚫 No Plan';
    }
  };
  const planLabel = getPlanLabel(orgPlan);

  return (
    <div className="min-h-screen bg-slate-50">
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
          <div className="w-56 flex-shrink-0">
            <nav className="space-y-1">
              {tabs.map(tab => {
                const isLocked = isTabLocked(tab);
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-bold transition-all',
                      isLocked ? 'text-slate-400 hover:bg-slate-100'
                        : activeTab === tab.id ? 'bg-primary text-white shadow-lg shadow-primary/25'
                        : 'text-slate-600 hover:bg-slate-200 hover:text-slate-900'
                    )}
                  >
                    <span className="relative">
                      {tab.icon}
                      {isLocked && <Lock className="w-2.5 h-2.5 absolute -top-1 -right-1 text-slate-400" />}
                    </span>
                    <span className="flex-1 text-left">{tab.label}</span>
                    {isLocked && <Lock className="w-3.5 h-3.5 text-slate-400" />}
                  </button>
                );
              })}
            </nav>

            <div className="mt-4">
              <div className={cn(
                'px-4 py-3 rounded-xl text-center border-2',
                orgPlan === 'executive' ? 'bg-primary/10 border-primary/20' : 'bg-amber-50 border-amber-200'
              )}>
                <p className={cn('text-sm font-bold', orgPlan === 'executive' ? 'text-primary' : 'text-amber-700')}>
                  {planLabel}
                </p>
                {orgPlan === 'professional' && (
                  <a href="/account/billing" className="text-xs text-amber-600 font-semibold hover:underline mt-1 block">
                    Upgrade for more features →
                  </a>
                )}
              </div>
            </div>
          </div>

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
                  {isTabLocked(tabs.find(t => t.id === activeTab)!) ? (
                    <UpgradePrompt featureName={getLockedFeatureName(activeTab)} />
                  ) : (
                    <>
                      {activeTab === 'organization' && (
                        <OrganizationTab orgInfo={orgInfo} orgPlan={orgPlan} onUpdate={(updated) => { setOrgInfo(updated); setOrgPlan(updated.plan || 'professional'); }} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'team' && (
                        <TeamTab members={teamMembers} currentUserId={currentUserId} currentUserRole={currentUserRole} onRefresh={() => loadTabData('team')} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'clients' && (
                        <ClientsTab clients={clients} currentUserRole={currentUserRole as RoleType} users={teamMembers} onRefresh={() => loadTabData('clients')} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'billing' && (
                        <BillingRatesTab rates={billingRates} users={teamMembers} clients={clients} orgDefaultRate={orgInfo?.billing_rate_default || '150.00'} onRefresh={() => loadTabData('billing')} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'costs' && (
                        <EmployeeCostRatesTab rates={employeeCostRates} users={teamMembers} onRefresh={() => loadTabData('costs')} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'devices' && (
                        <DevicesTab devices={devices} onRefresh={() => loadTabData('devices')} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'assignments' && (
                        <ClientAssignmentManager users={teamMembers} clients={clients} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'assignments' && (
                        <ClientAssignmentManager users={teamMembers} clients={clients} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'groups' && (
                        <ClientGroupManager users={teamMembers} clients={clients} onSuccess={showSuccess} onError={showError} />
                      )}
                      {activeTab === 'token' && (
                        <TokenTab token={installToken} onRefresh={() => loadTabData('token')} onSuccess={showSuccess} onError={showError} />
                      )}
                    </>
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
// Organization Tab - FIXED: Form state refresh after save
// ============================================================================
function OrganizationTab({ orgInfo, orgPlan, onUpdate, onSuccess, onError }: { orgInfo: OrgInfo | null; orgPlan: PlanType; onUpdate: (org: OrgInfo) => void; onSuccess: (msg: string) => void; onError: (msg: string) => void; }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ name: '', billing_email: '', billing_contact: '', billing_rate_default: '150.00' });

  useEffect(() => {
    if (orgInfo) {
      setForm({ 
        name: orgInfo.name || '', 
        billing_email: orgInfo.billing_email || '', 
        billing_contact: orgInfo.billing_contact || '', 
        billing_rate_default: orgInfo.billing_rate_default || '150.00' 
      });
    }
  }, [orgInfo]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`, { 
        method: 'PATCH', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify(form) 
      });
      
      // FIX: Update both parent state AND local form state
      onUpdate(updated);
      
      // Sync form state with returned data to ensure consistency
      setForm({
        name: updated.name || '',
        billing_email: updated.billing_email || '',
        billing_contact: updated.billing_contact || '',
        billing_rate_default: updated.billing_rate_default || '150.00'
      });
      
      setEditing(false);
      onSuccess('Organization updated');
    } catch (err: any) {
      onError(err?.message || 'Failed to update');
    } finally {
      setSaving(false);
    }
  };

  if (!orgInfo) return <div className="text-slate-500 font-medium">No organization data</div>;

  const planLabel = orgPlan === 'executive' ? '💎 Executive' : orgPlan === 'professional' ? '⭐ Professional' : '🚫 No Plan';

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Building2 className="w-5 h-5 text-primary" />
          Organization Info
        </h2>
        {!editing && (
          <button onClick={() => setEditing(true)} className="flex items-center gap-2 px-4 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">
            <Pencil className="w-4 h-4" />
            Edit
          </button>
        )}
      </div>

      {editing ? (
        <div className="space-y-5 max-w-md">
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Organization Name</label>
            <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" />
          </div>
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Billing Email</label>
            <input type="email" value={form.billing_email} onChange={(e) => setForm({ ...form, billing_email: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" />
          </div>
          <div>
            <label className="block text-sm font-bold text-slate-800 mb-2">Billing Contact Name</label>
            <input type="text" value={form.billing_contact} onChange={(e) => setForm({ ...form, billing_contact: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" />
          </div>
          <div className="pt-4 border-t-2 border-slate-200">
            <label className="block text-sm font-bold text-slate-800 mb-2 flex items-center gap-2">
              <DollarSign className="w-4 h-4" />
              Default Hourly Billing Rate
            </label>
            <div className="relative max-w-xs">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold">$</span>
              <input type="number" step="0.01" min="0" value={form.billing_rate_default} onChange={(e) => setForm({ ...form, billing_rate_default: e.target.value })} className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl text-slate-900 font-semibold focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none transition-all" placeholder="150.00" />
            </div>
          </div>
          <div className="flex gap-3 pt-4">
            <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Save
            </button>
            <button onClick={() => setEditing(false)} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-6">
            <div><p className="text-sm text-slate-500 font-semibold mb-1">Organization Name</p><p className="text-slate-900 font-bold">{orgInfo.name}</p></div>
            <div><p className="text-sm text-slate-500 font-semibold mb-1">Created</p><p className="text-slate-900 font-bold">{new Date(orgInfo.created_at).toLocaleDateString()}</p></div>
            <div><p className="text-sm text-slate-500 font-semibold mb-1">Billing Email</p><p className="text-slate-900 font-bold">{orgInfo.billing_email || '—'}</p></div>
            <div><p className="text-sm text-slate-500 font-semibold mb-1">Billing Contact</p><p className="text-slate-900 font-bold">{orgInfo.billing_contact || '—'}</p></div>
          </div>
          <div className="pt-4 border-t-2 border-slate-200">
            <div className={cn('rounded-xl p-4 border-2', orgPlan === 'executive' ? 'bg-primary/5 border-primary/20' : orgPlan === 'professional' ? 'bg-amber-50 border-amber-200' : 'bg-red-50 border-red-200')}>
              <div className="flex items-center justify-between">
                <div>
                  <p className={cn('text-sm font-bold', orgPlan === 'executive' ? 'text-primary' : orgPlan === 'professional' ? 'text-amber-700' : 'text-red-700')}>Current Plan</p>
                  <p className={cn('text-2xl font-extrabold mt-1', orgPlan === 'executive' ? 'text-primary' : orgPlan === 'professional' ? 'text-amber-700' : 'text-red-700')}>{planLabel}</p>
                </div>
                {orgPlan !== 'executive' && (
                  <a href="/account/billing" className="px-4 py-2 bg-primary text-white font-bold rounded-xl hover:opacity-90 transition-all shadow-lg shadow-primary/25 flex items-center gap-2">
                    <Sparkles className="w-4 h-4" />
                    {orgPlan === 'none' ? 'Subscribe' : 'Upgrade'}
                  </a>
                )}
              </div>
            </div>
          </div>
          <div className="pt-4 border-t-2 border-slate-200">
            <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-emerald-700 font-bold flex items-center gap-2"><DollarSign className="w-4 h-4" />Default Hourly Billing Rate</p>
                  <p className="text-3xl font-extrabold text-emerald-700 mt-1">${parseFloat(orgInfo.billing_rate_default || '150.00').toFixed(2)}/hr</p>
                </div>
                <span className="bg-emerald-100 text-emerald-800 px-3 py-1.5 rounded-full text-xs font-bold">Firm Default</span>
              </div>
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
function TeamTab({ members, currentUserId, currentUserRole, onRefresh, onSuccess, onError }: { members: TeamMember[]; currentUserId: number | null; currentUserRole: string; onRefresh: () => void; onSuccess: (msg: string) => void; onError: (msg: string) => void; }) {
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviting, setInviting] = useState(false);
  const [seatInfo, setSeatInfo] = useState<{ seat_count: number; members: number; pending_invites: number; seats_available: number; can_invite: boolean; } | null>(null);

  useEffect(() => {
    const loadSeatInfo = async () => {
      try {
        const data = await safeFetchJson<any>(`${API_BASE}/settings/seats/`);
        setSeatInfo(data);
      } catch (err) {
        console.error('Failed to load seat info:', err);
      }
    };
    loadSeatInfo();
  }, [members]);

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    try {
      const response = await safeFetchJson<any>(`${API_BASE}/settings/team/invite/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: inviteEmail }) });
      if (response.temp_password && !response.email_sent) {
        alert(`User created!\n\nUsername: ${response.username}\nTemp Password: ${response.temp_password}\n\nPlease share these credentials with the user.`);
      }
      onSuccess(response.email_sent ? 'Invitation sent' : 'User created (share credentials manually)');
      setInviteEmail('');
      setShowInvite(false);
      onRefresh();
      const seatData = await safeFetchJson<any>(`${API_BASE}/settings/seats/`);
      setSeatInfo(seatData);
    } catch (err: any) {
      if (err?.upgrade_required) {
        onError(`No seats available. You have ${err.seat_count} seats with ${err.current_members} members.`);
      } else {
        onError(err?.message || 'Failed to invite');
      }
    } finally {
      setInviting(false);
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

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Users className="w-5 h-5 text-primary" />
          Team Members
          <span className="text-sm font-bold text-slate-500">({members.length})</span>
        </h2>
        <button onClick={() => setShowInvite(true)} disabled={seatInfo !== null && !seatInfo.can_invite} className={cn("flex items-center gap-2 px-4 py-2.5 rounded-xl font-bold text-sm transition-all", seatInfo && !seatInfo.can_invite ? "bg-slate-200 text-slate-500 cursor-not-allowed" : "bg-primary text-white hover:opacity-90 shadow-lg shadow-primary/25")}>
          <UserPlus className="w-4 h-4" />
          Invite Member
        </button>
      </div>

      {seatInfo && seatInfo.seat_count > 0 && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
          <div className="flex items-center justify-between mb-2">
            <div>
              <p className="text-sm text-slate-600 font-semibold">Team Seats</p>
              <p className="text-2xl font-extrabold text-slate-900">{seatInfo.members} / {seatInfo.seat_count}<span className="text-sm font-medium text-slate-500 ml-2">used</span></p>
            </div>
            {!seatInfo.can_invite && (
              <a href="/account/billing" className="flex items-center gap-2 px-4 py-2 bg-primary text-white font-bold rounded-xl hover:opacity-90 text-sm shadow-lg shadow-primary/25">
                <Plus className="w-4 h-4" />
                Add Seats
              </a>
            )}
          </div>
          <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
            <div className={cn("h-full rounded-full transition-all", seatInfo.members >= seatInfo.seat_count ? "bg-red-500" : seatInfo.members >= seatInfo.seat_count * 0.8 ? "bg-amber-500" : "bg-emerald-500")} style={{ width: `${Math.min(100, (seatInfo.members / seatInfo.seat_count) * 100)}%` }} />
          </div>
        </div>
      )}

      {showInvite && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-3">Invite Team Member</h3>
          <div className="flex gap-2">
            <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="email@company.com" className="flex-1 border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" />
            <button onClick={handleInvite} disabled={inviting || !inviteEmail.trim()} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 transition-all">
              {inviting ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
              Send
            </button>
            <button onClick={() => setShowInvite(false)} className="px-4 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
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
              const displayName = getUserDisplayName(member);
              return (
                <tr key={member.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center">
                        <span className="text-sm font-bold text-primary">{displayName[0].toUpperCase()}</span>
                      </div>
                      <div>
                        <p className="font-bold text-slate-900 text-sm">{displayName}{isCurrentUser && <span className="ml-2 text-xs text-slate-500 font-semibold">(you)</span>}</p>
                        <p className="text-xs text-slate-500 font-medium">@{member.username}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-700 font-medium">{member.email || '—'}</td>
                  <td className="px-4 py-3"><span className={cn('text-xs px-2.5 py-1 rounded-full font-bold', getRoleBadge(member.role))}>{member.role.charAt(0).toUpperCase() + member.role.slice(1)}</span></td>
                  <td className="px-4 py-3 text-sm text-slate-500 font-medium">{formatLastSeen(member.last_login)}</td>
                  <td className="px-4 py-3 text-right">
                    {!isCurrentUser && member.role !== 'owner' && (
                      <button onClick={() => handleRemove(member.id, member.username)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-4 h-4" /></button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {members.length === 0 && <div className="text-center py-8 text-slate-500 font-medium">No team members yet</div>}
      </div>
    </div>
  );
}

// ============================================================================
// Clients Tab (with Bulk Assignment)
// ============================================================================
function ClientsTab({ clients, currentUserRole, users, onRefresh, onSuccess, onError }: { clients: Client[]; currentUserRole: RoleType; users: TeamMember[]; onRefresh: () => void; onSuccess: (msg: string) => void; onError: (msg: string) => void; }) {
  const [showAdd, setShowAdd] = useState(false);
  const [showImportWizard, setShowImportWizard] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({ name: '', code: '', visibility: 'all' });
  const [saving, setSaving] = useState(false);
  
  const [selectedClientIds, setSelectedClientIds] = useState<Set<number>>(new Set());
  const [showBulkAssignModal, setShowBulkAssignModal] = useState(false);
  const [showCSVImportModal, setShowCSVImportModal] = useState(false);
  const [showCopyModal, setShowCopyModal] = useState(false);
  const [showImportDropdown, setShowImportDropdown] = useState(false);

  const canManageClients = ['owner', 'admin'].includes(currentUserRole);

  const toggleClientSelection = (clientId: number) => {
    const newSelected = new Set(selectedClientIds);
    if (newSelected.has(clientId)) newSelected.delete(clientId);
    else newSelected.add(clientId);
    setSelectedClientIds(newSelected);
  };

  const toggleSelectAll = () => {
    if (selectedClientIds.size === clients.length) setSelectedClientIds(new Set());
    else setSelectedClientIds(new Set(clients.map(c => c.id)));
  };

  const clearSelection = () => setSelectedClientIds(new Set());

  const selectedClients = clients.filter(c => selectedClientIds.has(c.id));

  const resetForm = () => { setForm({ name: '', code: '', visibility: 'all' }); setShowAdd(false); setEditingId(null); };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      if (editingId) {
        await safeFetchJson(`${API_BASE}/settings/clients/${editingId}/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
        onSuccess('Client updated');
      } else {
        await safeFetchJson(`${API_BASE}/settings/clients/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
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
    if (!canManageClients) return;
    setForm({ name: client.name, code: client.code || '', visibility: client.visibility || 'all' });
    setEditingId(client.id);
    setShowAdd(true);
  };

  const handleDelete = async (clientId: number, clientName: string) => {
    if (!canManageClients) return;
    if (!confirm(`Delete client "${clientName}"?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/clients/${clientId}/`, { method: 'DELETE' });
      onSuccess('Client deleted');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to delete');
    }
  };

  const handleBulkUnassign = async () => {
    if (!confirm(`Remove all team assignments from ${selectedClientIds.size} clients?`)) return;
    try {
      await safeFetchJson(`${API_BASE}/clients/bulk-unassign/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_ids: Array.from(selectedClientIds) }) });
      onSuccess(`Removed team from ${selectedClientIds.size} clients`);
      onRefresh();
      clearSelection();
    } catch (err: any) {
      onError(err?.message || 'Failed to remove assignments');
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
        
        {canManageClients && (
          <div className="flex items-center gap-2">
            <div className="relative">
              <button onClick={() => setShowImportDropdown(!showImportDropdown)} className="flex items-center gap-2 px-3 py-2 text-sm border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">
                <Upload className="w-4 h-4" />Import<ChevronDown className="w-4 h-4" />
              </button>
              
              {showImportDropdown && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowImportDropdown(false)} />
                  <div className="absolute right-0 top-full mt-1 bg-white border-2 border-slate-200 rounded-xl shadow-xl z-20 min-w-[220px] overflow-hidden">
                    <button onClick={() => { setShowImportWizard(true); setShowImportDropdown(false); }} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 text-left transition-colors">
                      <Upload className="w-4 h-4 text-emerald-600" />
                      <div><p className="font-bold text-slate-900 text-sm">Import Clients</p><p className="text-xs text-slate-500">From QuickBooks or Xero</p></div>
                    </button>
                    <button onClick={() => { setShowCSVImportModal(true); setShowImportDropdown(false); }} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 text-left border-t border-slate-100 transition-colors">
                      <FileSpreadsheet className="w-4 h-4 text-blue-600" />
                      <div><p className="font-bold text-slate-900 text-sm">Import Assignments</p><p className="text-xs text-slate-500">CSV file upload</p></div>
                    </button>
                    <button onClick={() => { setShowCopyModal(true); setShowImportDropdown(false); }} className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 text-left border-t border-slate-100 transition-colors">
                      <Copy className="w-4 h-4 text-purple-600" />
                      <div><p className="font-bold text-slate-900 text-sm">Copy Team</p><p className="text-xs text-slate-500">From another client</p></div>
                    </button>
                  </div>
                </>
              )}
            </div>
            
            <button onClick={() => { resetForm(); setShowAdd(true); }} className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all">
              <Plus className="w-4 h-4" />Add Client
            </button>
          </div>
        )}
      </div>

      {!canManageClients && (
        <div className="mb-6 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl">
          <p className="text-sm text-blue-700 font-medium">💡 Only administrators can add or edit clients.</p>
        </div>
      )}

      {showAdd && canManageClients && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-4">{editingId ? 'Edit Client' : 'Add Client'}</h3>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Client Name *</label>
              <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Acme Corporation" className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Code</label>
              <input type="text" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="ACME" maxLength={10} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all uppercase" />
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Visibility</label>
              <select value={form.visibility} onChange={(e) => setForm({ ...form, visibility: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all bg-white">
                <option value="all">All Team Members</option>
                <option value="assigned">Assigned Users Only</option>
                <option value="confidential">Confidential</option>
              </select>
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button onClick={handleSave} disabled={saving || !form.name.trim()} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {editingId ? 'Update' : 'Add'}
            </button>
            <button onClick={resetForm} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
          </div>
        </div>
      )}

      <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead className="bg-slate-100">
            <tr>
              {canManageClients && (
                <th className="px-4 py-3 w-12">
                  <button onClick={toggleSelectAll} className="p-1 hover:bg-slate-200 rounded transition-colors">
                    {selectedClientIds.size === clients.length && clients.length > 0 ? <CheckSquare className="w-5 h-5 text-primary" /> : selectedClientIds.size > 0 ? <MinusSquare className="w-5 h-5 text-primary" /> : <Square className="w-5 h-5 text-slate-400" />}
                  </button>
                </th>
              )}
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Client Name</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Code</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Visibility</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Status</th>
              {canManageClients && <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {clients.map(client => (
              <tr key={client.id} className={cn("hover:bg-slate-50 transition-colors", selectedClientIds.has(client.id) && "bg-primary/5")}>
                {canManageClients && (
                  <td className="px-4 py-3">
                    <button onClick={() => toggleClientSelection(client.id)} className="p-1 hover:bg-slate-200 rounded transition-colors">
                      {selectedClientIds.has(client.id) ? <CheckSquare className="w-5 h-5 text-primary" /> : <Square className="w-5 h-5 text-slate-400" />}
                    </button>
                  </td>
                )}
                <td className="px-4 py-3 font-bold text-slate-900">{client.name}</td>
                <td className="px-4 py-3 text-sm text-slate-500 font-mono font-semibold">{client.code || '—'}</td>
                <td className="px-4 py-3">
                  <span className={cn('text-xs px-2.5 py-1 rounded-full font-bold', client.visibility === 'all' ? 'bg-emerald-100 text-emerald-700' : client.visibility === 'assigned' ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700')}>
                    {client.visibility === 'all' ? '👥 All' : client.visibility === 'assigned' ? '🔒 Assigned' : '🔐 Confidential'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={cn('text-xs px-2.5 py-1 rounded-full font-bold', client.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500')}>{client.is_active ? 'Active' : 'Inactive'}</span>
                </td>
                {canManageClients && (
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button onClick={() => handleEdit(client)} className="p-1.5 text-primary hover:bg-primary/10 rounded-lg transition-colors"><Pencil className="w-4 h-4" /></button>
                      <button onClick={() => handleDelete(client.id, client.name)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-4 h-4" /></button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {clients.length === 0 && (
          <div className="text-center py-12">
            <Briefcase className="w-12 h-12 mx-auto mb-3 text-slate-300" />
            <p className="font-bold text-slate-700">No clients yet</p>
            {canManageClients && <button onClick={() => setShowImportWizard(true)} className="mt-4 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90"><Upload className="w-4 h-4 inline mr-2" />Import Clients</button>}
          </div>
        )}
      </div>

      {/* Bulk Actions Floating Toolbar */}
      {selectedClientIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-900 text-white px-6 py-3 rounded-2xl shadow-2xl flex items-center gap-4 z-40 animate-in slide-in-from-bottom">
          <span className="font-bold">{selectedClientIds.size} client{selectedClientIds.size !== 1 ? 's' : ''} selected</span>
          <div className="w-px h-6 bg-slate-700" />
          <button onClick={() => setShowBulkAssignModal(true)} className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 rounded-xl font-bold transition-colors"><UserPlus className="w-4 h-4" />Assign Team</button>
          <button onClick={handleBulkUnassign} className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 rounded-xl font-bold transition-colors"><UserMinus className="w-4 h-4" />Remove Team</button>
          <button onClick={clearSelection} className="p-2 hover:bg-slate-700 rounded-lg transition-colors" title="Clear selection"><X className="w-5 h-5" /></button>
        </div>
      )}

      {/* Modals */}
      {showImportWizard && <ClientImportWizard onClose={() => setShowImportWizard(false)} onSuccess={() => { onRefresh(); onSuccess('Clients imported!'); }} users={users} />}
      {showBulkAssignModal && <BulkAssignModal isOpen={showBulkAssignModal} onClose={() => setShowBulkAssignModal(false)} selectedClients={selectedClients} users={users} onSuccess={() => { onRefresh(); clearSelection(); onSuccess('Team assigned!'); }} />}
      {showCSVImportModal && <CSVImportModal isOpen={showCSVImportModal} onClose={() => setShowCSVImportModal(false)} onSuccess={() => { onRefresh(); onSuccess('Assignments imported!'); }} />}
      {showCopyModal && <CopyAssignmentsModal isOpen={showCopyModal} onClose={() => setShowCopyModal(false)} clients={clients} onSuccess={() => { onRefresh(); onSuccess('Team copied!'); }} />}
    </div>
  );
}

// ============================================================================
// Bulk Assign Modal - FIXED: User display with getUserDisplayName
// ============================================================================
function BulkAssignModal({ isOpen, onClose, selectedClients, users, onSuccess }: { isOpen: boolean; onClose: () => void; selectedClients: Client[]; users: TeamMember[]; onSuccess: () => void; }) {
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [role, setRole] = useState('Staff');
  const [mode, setMode] = useState<'add' | 'replace'>('add');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const handleToggleUser = (userId: number) => {
    const newSelected = new Set(selectedUserIds);
    if (newSelected.has(userId)) newSelected.delete(userId);
    else newSelected.add(userId);
    setSelectedUserIds(newSelected);
  };

  const handleSubmit = async () => {
    if (selectedUserIds.size === 0) { setError('Select at least one employee'); return; }
    setLoading(true);
    setError(null);
    try {
      const response = await safeFetchJson<any>(`${API_BASE}/clients/bulk-assign/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client_ids: selectedClients.map(c => c.id), user_ids: Array.from(selectedUserIds), role, mode }) });
      setResult(response);
      setTimeout(() => { onSuccess(); handleClose(); }, 2000);
    } catch (err: any) {
      setError(err.message || 'Failed to assign');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => { setSelectedUserIds(new Set()); setRole('Staff'); setMode('add'); setError(null); setResult(null); onClose(); };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center"><UserPlus className="w-5 h-5 text-primary" /></div>
            <div><h2 className="text-lg font-bold text-slate-900">Bulk Assign Team</h2><p className="text-sm text-slate-500 font-medium">{selectedClients.length} client{selectedClients.length !== 1 ? 's' : ''} selected</p></div>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-slate-200 rounded-lg transition-colors"><X className="w-5 h-5 text-slate-500" /></button>
        </div>

        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {result ? (
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4"><CheckCircle2 className="w-8 h-8 text-emerald-600" /></div>
              <h3 className="text-xl font-bold text-slate-900 mb-2">Assignment Complete!</h3>
              <p className="text-slate-600">{result.created} assignments created{result.updated > 0 && `, ${result.updated} updated`}</p>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border-2 border-red-200 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                  <p className="text-sm text-red-700 font-medium">{error}</p>
                </div>
              )}

              {/* Mode Selection */}
              <div className="mb-6">
                <label className="block text-sm font-bold text-slate-800 mb-3">Assignment Mode</label>
                <div className="grid grid-cols-2 gap-3">
                  <button onClick={() => setMode('add')} className={cn('p-4 border-2 rounded-xl text-left transition-all', mode === 'add' ? 'border-primary bg-primary/5' : 'border-slate-200 hover:border-slate-300')}>
                    <div className="flex items-center gap-2 mb-1">
                      <UserPlus className={cn('w-4 h-4', mode === 'add' ? 'text-primary' : 'text-slate-500')} />
                      <span className={cn('font-bold', mode === 'add' ? 'text-primary' : 'text-slate-700')}>Add to Team</span>
                    </div>
                    <p className="text-xs text-slate-500">Keep existing members, add new ones</p>
                  </button>
                  <button onClick={() => setMode('replace')} className={cn('p-4 border-2 rounded-xl text-left transition-all', mode === 'replace' ? 'border-primary bg-primary/5' : 'border-slate-200 hover:border-slate-300')}>
                    <div className="flex items-center gap-2 mb-1">
                      <RefreshCw className={cn('w-4 h-4', mode === 'replace' ? 'text-primary' : 'text-slate-500')} />
                      <span className={cn('font-bold', mode === 'replace' ? 'text-primary' : 'text-slate-700')}>Replace Team</span>
                    </div>
                    <p className="text-xs text-slate-500">Remove existing, assign only selected</p>
                  </button>
                </div>
              </div>

              {/* Role Selection */}
              <div className="mb-6">
                <label className="block text-sm font-bold text-slate-800 mb-2">Default Role</label>
                <select value={role} onChange={(e) => setRole(e.target.value)} className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all bg-white">
                  <option value="Staff">Staff</option>
                  <option value="Manager">Manager</option>
                  <option value="Partner">Partner</option>
                  <option value="Lead">Lead</option>
                </select>
              </div>

              {/* User Selection - FIXED with getUserDisplayName */}
              <div>
                <label className="block text-sm font-bold text-slate-800 mb-3">Select Team Members</label>
                <div className="border-2 border-slate-200 rounded-xl max-h-64 overflow-y-auto">
                  {users.map(user => {
                    const displayName = getUserDisplayName(user);
                    return (
                      <button key={user.id} onClick={() => handleToggleUser(user.id)} className={cn('w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors border-b border-slate-100 last:border-b-0', selectedUserIds.has(user.id) && 'bg-primary/5')}>
                        {selectedUserIds.has(user.id) ? <CheckSquare className="w-5 h-5 text-primary flex-shrink-0" /> : <Square className="w-5 h-5 text-slate-400 flex-shrink-0" />}
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
                  {users.length === 0 && <div className="text-center py-8 text-slate-500">No team members</div>}
                </div>
                {selectedUserIds.size > 0 && (
                  <p className="mt-2 text-sm text-primary font-semibold">{selectedUserIds.size} member{selectedUserIds.size !== 1 ? 's' : ''} selected</p>
                )}
              </div>
            </>
          )}
        </div>

        {!result && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t-2 border-slate-200 bg-slate-50">
            <button onClick={handleClose} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
            <button onClick={handleSubmit} disabled={loading || selectedUserIds.size === 0} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
              Assign to {selectedClients.length} Client{selectedClients.length !== 1 ? 's' : ''}
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
function CSVImportModal({ isOpen, onClose, onSuccess }: { isOpen: boolean; onClose: () => void; onSuccess: () => void; }) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [preview, setPreview] = useState<any[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      setError(null);
      // Preview first few rows
      const reader = new FileReader();
      reader.onload = (event) => {
        const text = event.target?.result as string;
        const lines = text.split('\n').slice(0, 6);
        const previewData = lines.map(line => line.split(',').map(cell => cell.trim().replace(/"/g, '')));
        setPreview(previewData);
      };
      reader.readAsText(selectedFile);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const response = await fetch(`${API_BASE}/clients/assignment-template/`, {
        credentials: 'include',
      });
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'client_assignments_template.csv';
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err) {
      setError('Failed to download template');
    }
  };

  const handleSubmit = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const response = await fetch(`${API_BASE}/clients/import-assignments/`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      });
      
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.error || 'Import failed');
      }
      
      const data = await response.json();
      setResult(data);
      setTimeout(() => { onSuccess(); handleClose(); }, 2000);
    } catch (err: any) {
      setError(err.message || 'Failed to import');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => { setFile(null); setError(null); setResult(null); setPreview([]); onClose(); };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center"><FileSpreadsheet className="w-5 h-5 text-blue-600" /></div>
            <div><h2 className="text-lg font-bold text-slate-900">Import Assignments from CSV</h2><p className="text-sm text-slate-500 font-medium">Bulk assign team members via spreadsheet</p></div>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-slate-200 rounded-lg transition-colors"><X className="w-5 h-5 text-slate-500" /></button>
        </div>

        <div className="p-6">
          {result ? (
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4"><CheckCircle2 className="w-8 h-8 text-emerald-600" /></div>
              <h3 className="text-xl font-bold text-slate-900 mb-2">Import Complete!</h3>
              <p className="text-slate-600">{result.created} assignments created, {result.updated} updated</p>
              {result.errors && result.errors.length > 0 && (
                <div className="mt-4 text-left bg-red-50 border-2 border-red-200 rounded-xl p-4">
                  <p className="font-bold text-red-700 mb-2">Some rows had errors:</p>
                  <ul className="text-sm text-red-600 space-y-1">
                    {result.errors.slice(0, 5).map((err: string, i: number) => <li key={i}>• {err}</li>)}
                    {result.errors.length > 5 && <li>...and {result.errors.length - 5} more</li>}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border-2 border-red-200 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                  <p className="text-sm text-red-700 font-medium">{error}</p>
                </div>
              )}

              {/* Template Download */}
              <div className="mb-6 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-bold text-blue-800">Download Template</p>
                    <p className="text-sm text-blue-600">Get a pre-filled CSV with your clients and team members</p>
                  </div>
                  <button onClick={handleDownloadTemplate} className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl font-bold hover:bg-blue-700 transition-colors">
                    <Download className="w-4 h-4" />
                    Template
                  </button>
                </div>
              </div>

              {/* File Upload */}
              <div className="mb-6">
                <label className="block text-sm font-bold text-slate-800 mb-3">Upload CSV File</label>
                <div 
                  onClick={() => fileInputRef.current?.click()}
                  className={cn(
                    'border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all',
                    file ? 'border-emerald-300 bg-emerald-50' : 'border-slate-300 hover:border-primary hover:bg-primary/5'
                  )}
                >
                  <input ref={fileInputRef} type="file" accept=".csv" onChange={handleFileChange} className="hidden" />
                  {file ? (
                    <>
                      <CheckCircle2 className="w-10 h-10 text-emerald-600 mx-auto mb-2" />
                      <p className="font-bold text-emerald-800">{file.name}</p>
                      <p className="text-sm text-emerald-600">Click to change file</p>
                    </>
                  ) : (
                    <>
                      <Upload className="w-10 h-10 text-slate-400 mx-auto mb-2" />
                      <p className="font-bold text-slate-700">Click to select a CSV file</p>
                      <p className="text-sm text-slate-500">or drag and drop</p>
                    </>
                  )}
                </div>
              </div>

              {/* Preview */}
              {preview.length > 0 && (
                <div className="mb-6">
                  <label className="block text-sm font-bold text-slate-800 mb-3">Preview</label>
                  <div className="border-2 border-slate-200 rounded-xl overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-100">
                        <tr>
                          {preview[0]?.map((header: string, i: number) => (
                            <th key={i} className="px-3 py-2 text-left font-bold text-slate-700 whitespace-nowrap">{header}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.slice(1).map((row, i) => (
                          <tr key={i} className="border-t border-slate-100">
                            {row.map((cell: string, j: number) => (
                              <td key={j} className="px-3 py-2 text-slate-600 whitespace-nowrap">{cell}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="text-xs text-slate-500 mt-2">Showing first {preview.length - 1} rows</p>
                </div>
              )}

              {/* Format Instructions */}
              <div className="p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
                <p className="font-bold text-slate-800 mb-2">CSV Format</p>
                <p className="text-sm text-slate-600">Required columns: <code className="bg-slate-200 px-1 rounded">client_code</code>, <code className="bg-slate-200 px-1 rounded">user_email</code>, <code className="bg-slate-200 px-1 rounded">role</code></p>
                <p className="text-sm text-slate-500 mt-1">Optional: <code className="bg-slate-200 px-1 rounded">client_name</code>, <code className="bg-slate-200 px-1 rounded">user_name</code></p>
              </div>
            </>
          )}
        </div>

        {!result && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t-2 border-slate-200 bg-slate-50">
            <button onClick={handleClose} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
            <button onClick={handleSubmit} disabled={loading || !file} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              Import Assignments
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Copy Assignments Modal
// ============================================================================
function CopyAssignmentsModal({ isOpen, onClose, clients, onSuccess }: { isOpen: boolean; onClose: () => void; clients: Client[]; onSuccess: () => void; }) {
  const [sourceClientId, setSourceClientId] = useState<number | null>(null);
  const [targetClientIds, setTargetClientIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const [searchSource, setSearchSource] = useState('');
  const [searchTarget, setSearchTarget] = useState('');

  const filteredSourceClients = clients.filter(c => c.name.toLowerCase().includes(searchSource.toLowerCase()) || c.code?.toLowerCase().includes(searchSource.toLowerCase()));
  const filteredTargetClients = clients.filter(c => c.id !== sourceClientId && (c.name.toLowerCase().includes(searchTarget.toLowerCase()) || c.code?.toLowerCase().includes(searchTarget.toLowerCase())));

  const handleToggleTarget = (clientId: number) => {
    const newSelected = new Set(targetClientIds);
    if (newSelected.has(clientId)) newSelected.delete(clientId);
    else newSelected.add(clientId);
    setTargetClientIds(newSelected);
  };

  const handleSubmit = async () => {
    if (!sourceClientId || targetClientIds.size === 0) return;
    setLoading(true);
    setError(null);
    try {
      const response = await safeFetchJson<any>(`${API_BASE}/clients/copy-assignments/`, { 
        method: 'POST', 
        headers: { 'Content-Type': 'application/json' }, 
        body: JSON.stringify({ source_client_id: sourceClientId, target_client_ids: Array.from(targetClientIds) }) 
      });
      setResult(response);
      setTimeout(() => { onSuccess(); handleClose(); }, 2000);
    } catch (err: any) {
      setError(err.message || 'Failed to copy');
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => { setSourceClientId(null); setTargetClientIds(new Set()); setError(null); setResult(null); setSearchSource(''); setSearchTarget(''); onClose(); };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-purple-100 rounded-xl flex items-center justify-center"><Copy className="w-5 h-5 text-purple-600" /></div>
            <div><h2 className="text-lg font-bold text-slate-900">Copy Team Assignments</h2><p className="text-sm text-slate-500 font-medium">Clone team from one client to others</p></div>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-slate-200 rounded-lg transition-colors"><X className="w-5 h-5 text-slate-500" /></button>
        </div>

        <div className="p-6 max-h-[60vh] overflow-y-auto">
          {result ? (
            <div className="text-center py-8">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4"><CheckCircle2 className="w-8 h-8 text-emerald-600" /></div>
              <h3 className="text-xl font-bold text-slate-900 mb-2">Copy Complete!</h3>
              <p className="text-slate-600">{result.created} assignments created across {result.clients_updated} clients</p>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-50 border-2 border-red-200 rounded-xl flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                  <p className="text-sm text-red-700 font-medium">{error}</p>
                </div>
              )}

              {/* Source Client Selection */}
              <div className="mb-6">
                <label className="block text-sm font-bold text-slate-800 mb-3">Copy From (Source Client)</label>
                <input 
                  type="text" 
                  placeholder="Search clients..." 
                  value={searchSource} 
                  onChange={(e) => setSearchSource(e.target.value)} 
                  className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 mb-2 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" 
                />
                <div className="border-2 border-slate-200 rounded-xl max-h-40 overflow-y-auto">
                  {filteredSourceClients.map(client => (
                    <button 
                      key={client.id} 
                      onClick={() => { setSourceClientId(client.id); setTargetClientIds(new Set()); }} 
                      className={cn('w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors border-b border-slate-100 last:border-b-0', sourceClientId === client.id && 'bg-purple-50')}
                    >
                      {sourceClientId === client.id ? <CheckSquare className="w-5 h-5 text-purple-600 flex-shrink-0" /> : <Square className="w-5 h-5 text-slate-400 flex-shrink-0" />}
                      <div className="flex-1 text-left">
                        <p className="font-bold text-slate-900 text-sm">{client.name}</p>
                        {client.code && <p className="text-xs text-slate-500 font-mono">{client.code}</p>}
                      </div>
                    </button>
                  ))}
                  {filteredSourceClients.length === 0 && <div className="text-center py-4 text-slate-500">No clients found</div>}
                </div>
              </div>

              {/* Target Clients Selection */}
              {sourceClientId && (
                <div>
                  <label className="block text-sm font-bold text-slate-800 mb-3">Copy To (Target Clients)</label>
                  <input 
                    type="text" 
                    placeholder="Search clients..." 
                    value={searchTarget} 
                    onChange={(e) => setSearchTarget(e.target.value)} 
                    className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 mb-2 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" 
                  />
                  <div className="border-2 border-slate-200 rounded-xl max-h-48 overflow-y-auto">
                    {filteredTargetClients.map(client => (
                      <button 
                        key={client.id} 
                        onClick={() => handleToggleTarget(client.id)} 
                        className={cn('w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition-colors border-b border-slate-100 last:border-b-0', targetClientIds.has(client.id) && 'bg-primary/5')}
                      >
                        {targetClientIds.has(client.id) ? <CheckSquare className="w-5 h-5 text-primary flex-shrink-0" /> : <Square className="w-5 h-5 text-slate-400 flex-shrink-0" />}
                        <div className="flex-1 text-left">
                          <p className="font-bold text-slate-900 text-sm">{client.name}</p>
                          {client.code && <p className="text-xs text-slate-500 font-mono">{client.code}</p>}
                        </div>
                      </button>
                    ))}
                    {filteredTargetClients.length === 0 && <div className="text-center py-4 text-slate-500">No other clients available</div>}
                  </div>
                  {targetClientIds.size > 0 && (
                    <p className="mt-2 text-sm text-primary font-semibold">{targetClientIds.size} client{targetClientIds.size !== 1 ? 's' : ''} selected</p>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {!result && (
          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t-2 border-slate-200 bg-slate-50">
            <button onClick={handleClose} className="px-5 py-2.5 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-all">Cancel</button>
            <button onClick={handleSubmit} disabled={loading || !sourceClientId || targetClientIds.size === 0} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Copy className="w-4 h-4" />}
              Copy to {targetClientIds.size || 0} Client{targetClientIds.size !== 1 ? 's' : ''}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Billing Rates Tab - FIXED: Employee dropdown with getUserDisplayName
// ============================================================================
function BillingRatesTab({ rates, users, clients, orgDefaultRate, onRefresh, onSuccess, onError }: { rates: BillingRate[]; users: TeamMember[]; clients: Client[]; orgDefaultRate: string; onRefresh: () => void; onSuccess: (msg: string) => void; onError: (msg: string) => void; }) {
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ user: '', client: '', rate: '', effective_date: new Date().toISOString().split('T')[0] });

  const resetForm = () => { setForm({ user: '', client: '', rate: '', effective_date: new Date().toISOString().split('T')[0] }); setShowAdd(false); setEditingId(null); };

  const handleSave = async () => {
    if (!form.rate) return;
    setSaving(true);
    try {
      const payload = { 
        user: form.user || null, 
        client: form.client || null, 
        rate: form.rate, 
        effective_date: form.effective_date 
      };
      if (editingId) {
        await safeFetchJson(`${API_BASE}/billing/rates/${editingId}/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Rate updated');
      } else {
        await safeFetchJson(`${API_BASE}/billing/rates/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Rate added');
      }
      resetForm();
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (rate: BillingRate) => {
    setForm({ user: rate.user?.toString() || '', client: rate.client?.toString() || '', rate: rate.rate || rate.hourly_rate || '', effective_date: rate.effective_date });
    setEditingId(rate.id);
    setShowAdd(true);
  };

  const handleDelete = async (rateId: number) => {
    if (!confirm('Delete this rate?')) return;
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
          <span className="text-sm font-bold text-slate-500">({rates.length})</span>
        </h2>
        <button onClick={() => { resetForm(); setShowAdd(true); }} className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all">
          <Plus className="w-4 h-4" />Add Rate
        </button>
      </div>

      {/* Default Rate Banner */}
      <div className="mb-6 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-emerald-700 font-bold flex items-center gap-2"><DollarSign className="w-4 h-4" />Organization Default Rate</p>
            <p className="text-2xl font-extrabold text-emerald-700 mt-1">${parseFloat(orgDefaultRate).toFixed(2)}/hr</p>
          </div>
          <span className="bg-emerald-100 text-emerald-800 px-3 py-1.5 rounded-full text-xs font-bold">Fallback Rate</span>
        </div>
      </div>

      {showAdd && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-4">{editingId ? 'Edit Rate' : 'Add Rate Override'}</h3>
          <div className="grid grid-cols-4 gap-4">
            {/* FIXED: Employee dropdown with getUserDisplayName */}
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Employee</label>
              <select value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all bg-white">
                <option value="">All Employees</option>
                {users.map(u => (
                  <option key={u.id} value={u.id}>{getUserDisplayName(u)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Client</label>
              <select value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all bg-white">
                <option value="">All Clients</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Hourly Rate *</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold">$</span>
                <input type="number" step="0.01" min="0" value={form.rate} onChange={(e) => setForm({ ...form, rate: e.target.value })} className="w-full pl-10 pr-4 py-2.5 border-2 border-slate-200 rounded-xl text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" placeholder="175.00" />
              </div>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Effective Date</label>
              <input type="date" value={form.effective_date} onChange={(e) => setForm({ ...form, effective_date: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" />
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button onClick={handleSave} disabled={saving || !form.rate} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {editingId ? 'Update' : 'Add'}
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
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Client</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Rate</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Effective</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {rates.map(rate => (
              <tr key={rate.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-4 py-3 font-medium text-slate-900">{rate.user_name || <span className="text-slate-400 italic">All</span>}</td>
                <td className="px-4 py-3 font-medium text-slate-900">{rate.client_name || <span className="text-slate-400 italic">All</span>}</td>
                <td className="px-4 py-3"><span className="font-bold text-emerald-700">${parseFloat(rate.rate || rate.hourly_rate || '0').toFixed(2)}/hr</span></td>
                <td className="px-4 py-3 text-sm text-slate-500">{new Date(rate.effective_date).toLocaleDateString()}</td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => handleEdit(rate)} className="p-1.5 text-primary hover:bg-primary/10 rounded-lg transition-colors"><Pencil className="w-4 h-4" /></button>
                    <button onClick={() => handleDelete(rate.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-4 h-4" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rates.length === 0 && (
          <div className="text-center py-12">
            <DollarSign className="w-12 h-12 mx-auto mb-3 text-slate-300" />
            <p className="font-bold text-slate-700">No rate overrides yet</p>
            <p className="text-sm text-slate-500 mt-1">Using organization default: ${parseFloat(orgDefaultRate).toFixed(2)}/hr</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Employee Cost Rates Tab - FIXED: Employee dropdown with getUserDisplayName
// ============================================================================
function EmployeeCostRatesTab({ rates, users, onRefresh, onSuccess, onError }: { rates: EmployeeCostRate[]; users: TeamMember[]; onRefresh: () => void; onSuccess: (msg: string) => void; onError: (msg: string) => void; }) {
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({ user: '', cost_rate: '', effective_date: new Date().toISOString().split('T')[0] });

  const resetForm = () => { setForm({ user: '', cost_rate: '', effective_date: new Date().toISOString().split('T')[0] }); setShowAdd(false); setEditingId(null); };

  const handleSave = async () => {
    if (!form.user || !form.cost_rate) return;
    setSaving(true);
    try {
      const payload = { user: parseInt(form.user), cost_rate: form.cost_rate, effective_date: form.effective_date };
      if (editingId) {
        await safeFetchJson(`${API_BASE}/billing/cost-rates/${editingId}/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Cost rate updated');
      } else {
        await safeFetchJson(`${API_BASE}/billing/cost-rates/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        onSuccess('Cost rate added');
      }
      resetForm();
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (rate: EmployeeCostRate) => {
    setForm({ user: rate.user.toString(), cost_rate: rate.cost_rate, effective_date: rate.effective_date });
    setEditingId(rate.id);
    setShowAdd(true);
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
        <button onClick={() => { resetForm(); setShowAdd(true); }} className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all">
          <Plus className="w-4 h-4" />Add Cost Rate
        </button>
      </div>

      <div className="mb-6 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl">
        <p className="text-sm text-blue-700 font-medium">💡 Cost rates represent the internal cost per hour for each employee. This is used for profitability calculations.</p>
      </div>

      {showAdd && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl">
          <h3 className="font-bold text-slate-900 mb-4">{editingId ? 'Edit Cost Rate' : 'Add Cost Rate'}</h3>
          <div className="grid grid-cols-3 gap-4">
            {/* FIXED: Employee dropdown with getUserDisplayName */}
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Employee *</label>
              <select value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all bg-white">
                <option value="">Select Employee</option>
                {users.map(u => (
                  <option key={u.id} value={u.id}>{getUserDisplayName(u)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Hourly Cost *</label>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 font-bold">$</span>
                <input type="number" step="0.01" min="0" value={form.cost_rate} onChange={(e) => setForm({ ...form, cost_rate: e.target.value })} className="w-full pl-10 pr-4 py-2.5 border-2 border-slate-200 rounded-xl text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" placeholder="75.00" />
              </div>
            </div>
            <div>
              <label className="block text-sm font-bold text-slate-800 mb-2">Effective Date</label>
              <input type="date" value={form.effective_date} onChange={(e) => setForm({ ...form, effective_date: e.target.value })} className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 text-slate-900 font-medium focus:border-primary focus:outline-none transition-all" />
            </div>
          </div>
          <div className="flex gap-3 mt-4">
            <button onClick={handleSave} disabled={saving || !form.user || !form.cost_rate} className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 shadow-lg shadow-primary/25 transition-all">
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {editingId ? 'Update' : 'Add'}
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
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Cost Rate</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Effective</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">End Date</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {rates.map(rate => (
              <tr key={rate.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-4 py-3 font-bold text-slate-900">{rate.user_name}</td>
                <td className="px-4 py-3"><span className="font-bold text-amber-700">${parseFloat(rate.cost_rate).toFixed(2)}/hr</span></td>
                <td className="px-4 py-3 text-sm text-slate-500">{new Date(rate.effective_date).toLocaleDateString()}</td>
                <td className="px-4 py-3 text-sm text-slate-500">{rate.end_date ? new Date(rate.end_date).toLocaleDateString() : <span className="text-emerald-600 font-medium">Current</span>}</td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={() => handleEdit(rate)} className="p-1.5 text-primary hover:bg-primary/10 rounded-lg transition-colors"><Pencil className="w-4 h-4" /></button>
                    <button onClick={() => handleDelete(rate.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors"><Trash2 className="w-4 h-4" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {rates.length === 0 && (
          <div className="text-center py-12">
            <Users className="w-12 h-12 mx-auto mb-3 text-slate-300" />
            <p className="font-bold text-slate-700">No cost rates defined</p>
            <p className="text-sm text-slate-500 mt-1">Add cost rates to track profitability</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Devices Tab
// ============================================================================
function DevicesTab({ devices, onRefresh, onSuccess, onError }: { devices: Device[]; onRefresh: () => void; onSuccess: (msg: string) => void; onError: (msg: string) => void; }) {
  const handleDeactivate = async (deviceId: number, machineName: string) => {
    if (!confirm(`Deactivate device "${machineName}"? The agent will need to be re-registered.`)) return;
    try {
      await safeFetchJson(`${API_BASE}/settings/devices/${deviceId}/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: false }) });
      onSuccess('Device deactivated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to deactivate');
    }
  };

  const handleActivate = async (deviceId: number) => {
    try {
      await safeFetchJson(`${API_BASE}/settings/devices/${deviceId}/`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: true }) });
      onSuccess('Device activated');
      onRefresh();
    } catch (err: any) {
      onError(err?.message || 'Failed to activate');
    }
  };

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

  const getOSIcon = (os: string) => {
    const osLower = os.toLowerCase();
    if (osLower.includes('mac') || osLower.includes('darwin')) return '🍎';
    if (osLower.includes('win')) return '🪟';
    if (osLower.includes('linux')) return '🐧';
    return '💻';
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Monitor className="w-5 h-5 text-primary" />
          Devices
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
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Device</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">User</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">OS</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Agent Version</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Last Seen</th>
              <th className="text-left px-4 py-3 text-sm font-bold text-slate-700">Status</th>
              <th className="text-right px-4 py-3 text-sm font-bold text-slate-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {devices.map(device => (
              <tr key={device.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{getOSIcon(device.os)}</span>
                    <span className="font-bold text-slate-900">{device.machine_name}</span>
                  </div>
                </td>
                <td className="px-4 py-3 text-sm text-slate-700 font-medium">{device.user}</td>
                <td className="px-4 py-3 text-sm text-slate-500">{device.os} {device.os_version}</td>
                <td className="px-4 py-3 text-sm text-slate-500 font-mono">{device.agent_version || '—'}</td>
                <td className="px-4 py-3 text-sm text-slate-500">{formatLastSeen(device.last_seen)}</td>
                <td className="px-4 py-3">
                  <span className={cn('text-xs px-2.5 py-1 rounded-full font-bold', device.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500')}>
                    {device.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {device.is_active ? (
                    <button onClick={() => handleDeactivate(device.id, device.machine_name)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg transition-colors" title="Deactivate">
                      <X className="w-4 h-4" />
                    </button>
                  ) : (
                    <button onClick={() => handleActivate(device.id)} className="p-1.5 text-emerald-500 hover:bg-emerald-50 rounded-lg transition-colors" title="Activate">
                      <Check className="w-4 h-4" />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {devices.length === 0 && (
          <div className="text-center py-12">
            <Monitor className="w-12 h-12 mx-auto mb-3 text-slate-300" />
            <p className="font-bold text-slate-700">No devices registered</p>
            <p className="text-sm text-slate-500 mt-1">Install the TimeTracker agent on your team's computers</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Token Tab
// ============================================================================
function TokenTab({ token, onRefresh, onSuccess, onError }: { token: InstallToken | null; onRefresh: () => void; onSuccess: (msg: string) => void; onError: (msg: string) => void; }) {
  const [showToken, setShowToken] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const handleCopy = async () => {
    if (!token?.token) return;
    try {
      await navigator.clipboard.writeText(token.token);
      onSuccess('Token copied to clipboard');
    } catch (err) {
      onError('Failed to copy token');
    }
  };

  const handleRegenerate = async () => {
    if (!confirm('Regenerate the install token? Existing tokens will be invalidated.')) return;
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

  const maskedToken = token?.token ? token.token.substring(0, 8) + '••••••••••••••••' + token.token.slice(-4) : '';

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-extrabold text-slate-900 flex items-center gap-2">
          <Key className="w-5 h-5 text-primary" />
          Install Token
        </h2>
      </div>

      <div className="mb-6 p-4 bg-blue-50 border-2 border-blue-200 rounded-xl">
        <p className="text-sm text-blue-700 font-medium">
          💡 Use this token when installing the TimeTracker agent on team members' computers. The token links devices to your organization.
        </p>
      </div>

      {token ? (
        <div className="space-y-6">
          <div className="p-6 bg-slate-50 border-2 border-slate-200 rounded-xl">
            <label className="block text-sm font-bold text-slate-800 mb-3">Organization Install Token</label>
            <div className="flex items-center gap-3">
              <div className="flex-1 bg-white border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm text-slate-700">
                {showToken ? token.token : maskedToken}
              </div>
              <button onClick={() => setShowToken(!showToken)} className="p-3 border-2 border-slate-200 rounded-xl hover:bg-slate-100 transition-colors" title={showToken ? 'Hide token' : 'Show token'}>
                {showToken ? <EyeOff className="w-5 h-5 text-slate-500" /> : <Eye className="w-5 h-5 text-slate-500" />}
              </button>
              <button onClick={handleCopy} className="p-3 border-2 border-slate-200 rounded-xl hover:bg-slate-100 transition-colors" title="Copy token">
                <Copy className="w-5 h-5 text-slate-500" />
              </button>
            </div>
            <p className="text-xs text-slate-500 mt-2">Created: {new Date(token.created_at).toLocaleString()}</p>
          </div>

          <div className="flex items-center gap-4">
            <button onClick={handleRegenerate} disabled={regenerating} className="flex items-center gap-2 px-4 py-2.5 border-2 border-red-200 text-red-600 rounded-xl font-bold hover:bg-red-50 transition-colors disabled:opacity-50">
              {regenerating ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              Regenerate Token
            </button>
            <p className="text-sm text-slate-500">⚠️ Regenerating will invalidate the current token</p>
          </div>

          <div className="p-4 bg-amber-50 border-2 border-amber-200 rounded-xl">
            <h4 className="font-bold text-amber-800 mb-2">Installation Instructions</h4>
            <ol className="text-sm text-amber-700 space-y-2">
              <li>1. Download the TimeTracker agent for your operating system</li>
              <li>2. Run the installer</li>
              <li>3. When prompted, enter this install token</li>
              <li>4. The agent will automatically link to your organization</li>
            </ol>
          </div>
        </div>
      ) : (
        <div className="text-center py-12">
          <Key className="w-12 h-12 mx-auto mb-3 text-slate-300" />
          <p className="font-bold text-slate-700">No install token found</p>
          <button onClick={onRefresh} className="mt-4 px-4 py-2 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90">
            Generate Token
          </button>
        </div>
      )}
    </div>
  );
}