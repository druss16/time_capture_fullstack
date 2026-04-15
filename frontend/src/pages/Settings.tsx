/**
 * Settings.tsx — Org Admin Settings Page
 * Lean shell — all tab content lives in ./settings/ subdirectory
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Building2, Users, Briefcase, Monitor, Key,
  DollarSign, Lock, Shield, Sparkles,
  CheckCircle2, AlertCircle, RefreshCw,
  Folder, Link2,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

// Tab components
import OrganizationTab      from '@/pages/settings/OrganizationTab';
import TeamTab              from '@/pages/settings/TeamTab';
import ClientsTab           from '@/pages/settings/ClientsTab';
import BillingRatesTab      from '@/pages/settings/BillingRatesTab';
import EmployeeCostRatesTab from '@/pages/settings/EmployeeCostRatesTab';
import DevicesTab           from '@/pages/settings/DevicesTab';
import TokenTab             from '@/pages/settings/TokenTab';
import ClientAssignmentManager from '@/components/ClientAssignmentManager';
import ClientGroupManager      from '@/components/ClientGroupManager';
import IntegrationsTab         from '@/components/IntegrationsTab';
import DeploymentTab           from '@/components/DeploymentTab';

// Types
import {
  PROFESSIONAL_PLANS, EXECUTIVE_PLANS,
} from '@/pages/settings/types';
import type {
  PlanType, RoleType, Tab, TabConfig,
  OrgInfo, TeamMember, Client, Device,
  InstallToken, BillingRate, EmployeeCostRate,
} from '@/pages/settings/types';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;


// ── Upgrade prompt ────────────────────────────────────────────────────────────

function UpgradePrompt({ featureName }: { featureName: string }) {
  return (
    <div className="flex items-center justify-center min-h-[400px]">
      <div className="text-center p-10 bg-white rounded-2xl border border-border/60 shadow-sm max-w-md">
        <div className="w-14 h-14 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-5">
          <Lock className="w-7 h-7 text-slate-300" />
        </div>
        <h3 className="text-lg font-bold text-slate-900 mb-2">{featureName}</h3>
        <p className="text-slate-500 text-sm leading-relaxed mb-6">
          This feature is available on the{' '}
          <span className="font-semibold text-primary">Executive</span> plan.
        </p>
        <a
          href="/account/billing"
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-white text-sm font-semibold rounded-lg hover:opacity-90 transition-all"
        >
          <Sparkles className="w-4 h-4" />
          Upgrade to Executive
        </a>
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  const [activeTab, setActiveTab] = useState<Tab>(() => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    const valid: Tab[] = ['organization','team','clients','assignments','groups','integrations','billing','costs','devices','token','deployment'];
    return valid.includes(tab as Tab) ? (tab as Tab) : 'organization';
  });

  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [orgInfo,           setOrgInfo]           = useState<OrgInfo | null>(null);
  const [orgPlan,           setOrgPlan]           = useState<PlanType>('professional');
  const [teamMembers,       setTeamMembers]       = useState<TeamMember[]>([]);
  const [clients,           setClients]           = useState<Client[]>([]);
  const [devices,           setDevices]           = useState<Device[]>([]);
  const [installToken,      setInstallToken]      = useState<InstallToken | null>(null);
  const [billingRates,      setBillingRates]      = useState<BillingRate[]>([]);
  const [employeeCostRates, setEmployeeCostRates] = useState<EmployeeCostRate[]>([]);
  const [currentUserId,     setCurrentUserId]     = useState<number | null>(null);
  const [currentUserRole,   setCurrentUserRole]   = useState<string>('member');

  const showSuccess = (msg: string) => { setSuccess(msg); setTimeout(() => setSuccess(null), 3000); };
  const showError   = (msg: string) => { setError(msg);   setTimeout(() => setError(null), 5000); };

  // Load user info once
  useEffect(() => {
    safeFetchJson<any>(`${API_BASE}/whoami/`)
      .then(d => { setCurrentUserId(d.user_id); setCurrentUserRole(d.role || 'member'); })
      .catch(() => {});
  }, []);

  // Load org plan once
  useEffect(() => {
    if (localStorage.getItem("impersonating_org_id")) {
      setOrgPlan('executive');
      return;
    }
    safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`)
      .then(org => { setOrgInfo(org); setOrgPlan(org.plan || 'professional'); })
      .catch(() => {});
  }, []);

  const loadTabData = useCallback(async (tab: Tab) => {
    setLoading(true);
    setError(null);
    try {
      switch (tab) {
        case 'organization': {
          const org = await safeFetchJson<OrgInfo>(`${API_BASE}/settings/org/`);
          setOrgInfo(org); setOrgPlan(org.plan || 'professional');
          break;
        }
        case 'team': {
          const team = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`);
          setTeamMembers(team || []);
          if (currentUserId) {
            const me = team.find((m: TeamMember) => m.id === currentUserId);
            if (me) setCurrentUserRole(me.role);
          }
          break;
        }
        case 'clients':
        case 'assignments':
        case 'groups': {
          const [cl, tm] = await Promise.all([
            safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
            safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
          ]);
          setClients(cl || []); setTeamMembers(tm || []);
          break;
        }
        case 'billing': {
          if (EXECUTIVE_PLANS.includes(orgPlan)) {
            const rates = await safeFetchJson<BillingRate[]>(`${API_BASE}/billing/rates/`);
            setBillingRates(rates || []);
            const [cl, tm] = await Promise.all([
              safeFetchJson<Client[]>(`${API_BASE}/settings/clients/`).catch(() => []),
              safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []),
            ]);
            setClients(cl || []); setTeamMembers(tm || []);
          }
          break;
        }
        case 'costs': {
          if (EXECUTIVE_PLANS.includes(orgPlan)) {
            const cr = await safeFetchJson<EmployeeCostRate[]>(`${API_BASE}/billing/cost-rates/`).catch(() => []);
            setEmployeeCostRates(cr || []);
            const tm = await safeFetchJson<TeamMember[]>(`${API_BASE}/settings/team/`).catch(() => []);
            setTeamMembers(tm || []);
          }
          break;
        }
        case 'devices': {
          const dl = await safeFetchJson<Device[]>(`${API_BASE}/settings/devices/`);
          setDevices(dl || []);
          break;
        }
        case 'token': {
          const t = await safeFetchJson<InstallToken>(`${API_BASE}/settings/install-token/`);
          setInstallToken(t);
          break;
        }
        default: break;
      }
    } catch (err: any) {
      showError(err?.message || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [currentUserId, orgPlan]);

  useEffect(() => { loadTabData(activeTab); }, [activeTab, loadTabData]);

  const tabs: TabConfig[] = [
    { id: 'organization', label: 'Organization',  icon: <Building2 className="w-4 h-4" /> },
    { id: 'team',         label: 'Team Members',  icon: <Users className="w-4 h-4" /> },
    { id: 'clients',      label: 'Clients',       icon: <Briefcase className="w-4 h-4" /> },
    { id: 'assignments',  label: 'Client Access', icon: <Shield className="w-4 h-4" />, requiredRole: ['owner','admin','manager'] },
    { id: 'groups',       label: 'Client Groups', icon: <Folder className="w-4 h-4" />, requiredRole: ['owner','admin','manager'] },
    { id: 'integrations', label: 'Integrations',  icon: <Link2 className="w-4 h-4" />, requiredRole: ['owner','admin'] },
    { id: 'billing',      label: 'Billing Rates', icon: <DollarSign className="w-4 h-4" />, requiredPlan: EXECUTIVE_PLANS },
    { id: 'costs',        label: 'Employee Costs',icon: <Users className="w-4 h-4" />,     requiredPlan: EXECUTIVE_PLANS },
    { id: 'devices',      label: 'Devices',       icon: <Monitor className="w-4 h-4" /> },
    { id: 'deployment',   label: 'MDM Deploy',    icon: <Monitor className="w-4 h-4" />, requiredRole: ['owner','admin'] },
  ];

  const isTabLocked = (tab: TabConfig) => {
    if (!tab.requiredPlan) return false;
    return !tab.requiredPlan.includes(orgPlan);
  };

  const getLockedFeatureName = (tabId: Tab) => {
    switch (tabId) {
      case 'billing': return 'Billing Rates';
      case 'costs':   return 'Employee Cost Rates';
      default:        return 'This Feature';
    }
  };

  const activeTabConfig = tabs.find(t => t.id === activeTab);
  const isLocked = activeTabConfig ? isTabLocked(activeTabConfig) : false;

  return (
    <div className="min-h-[calc(100vh-56px)] bg-background flex">

      {/* Toasts */}
      {success && (
        <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-xl flex items-center gap-2 bg-emerald-500 text-white font-semibold animate-in slide-in-from-right">
          <CheckCircle2 className="w-4 h-4" />
          <span className="text-sm">{success}</span>
        </div>
      )}
      {error && (
        <div className="fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-xl flex items-center gap-2 bg-red-500 text-white font-semibold animate-in slide-in-from-right">
          <AlertCircle className="w-4 h-4" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* ── Sidebar ── */}
      <aside className="w-56 bg-white border-r border-border/50 flex-shrink-0 flex flex-col">
        <div className="px-5 py-4 border-b border-border/40">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-0.5">Settings</p>
          <p className="text-base font-extrabold text-slate-900 tracking-tight">Manage your organization</p>
        </div>

        <nav className="flex-1 py-3 px-2 space-y-0.5">
          {tabs.map(tab => {
            const locked  = isTabLocked(tab);
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 group relative',
                  locked
                    ? 'text-slate-300 cursor-not-allowed'
                    : isActive
                      ? 'bg-primary/8 text-primary font-semibold'
                      : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'
                )}
              >
                {isActive && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-primary rounded-r-full" />
                )}
                <span className={cn(
                  'w-4 h-4 shrink-0 transition-colors',
                  locked ? 'text-slate-200' : isActive ? 'text-primary' : 'text-slate-400 group-hover:text-slate-600'
                )}>
                  {tab.icon}
                </span>
                <span className="flex-1 text-left truncate">{tab.label}</span>
                {locked && <Lock className="w-3 h-3 text-slate-200 shrink-0" />}
              </button>
            );
          })}
        </nav>

        {/* Plan badge */}
        <div className="px-4 py-3 border-t border-border/40">
          <div className={cn(
            'text-xs font-semibold px-2.5 py-1.5 rounded-lg text-center',
            orgPlan === 'executive' ? 'bg-primary/8 text-primary' : 'bg-amber-50 text-amber-600'
          )}>
            {orgPlan === 'executive' ? '💎 Executive' : '⭐ Professional'}
          </div>
          {orgPlan === 'professional' && (
            <a href="/account/billing" className="block text-center text-[11px] text-slate-400 hover:text-primary mt-1.5 transition-colors">
              Upgrade for more features →
            </a>
          )}
        </div>
      </aside>

      {/* ── Main content ── */}
      <main className="flex-1 pt-2 px-6 pb-6 bg-slate-50 overflow-auto min-w-0">
        <div className="bg-white rounded-xl border border-border/60 p-6">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="w-5 h-5 text-primary animate-spin" />
            </div>
          ) : isLocked ? (
            <UpgradePrompt featureName={getLockedFeatureName(activeTab)} />
          ) : (
            <>
              {activeTab === 'organization' && (
                <OrganizationTab
                  orgInfo={orgInfo} orgPlan={orgPlan}
                  onUpdate={updated => { setOrgInfo(updated); setOrgPlan(updated.plan || 'professional'); }}
                  onSuccess={showSuccess} onError={showError}
                  currentUserRole={currentUserRole}
                />
              )}
              {activeTab === 'team' && (
                <TeamTab
                  members={teamMembers} currentUserId={currentUserId}
                  currentUserRole={currentUserRole}
                  onRefresh={() => loadTabData('team')}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'clients' && (
                <ClientsTab
                  clients={clients} currentUserRole={currentUserRole as RoleType}
                  users={teamMembers}
                  onRefresh={() => loadTabData('clients')}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'assignments' && (
                <ClientAssignmentManager
                  users={teamMembers} clients={clients}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'groups' && (
                <ClientGroupManager
                  users={teamMembers} clients={clients}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'integrations' && (
                <IntegrationsTab onSuccess={showSuccess} onError={showError} />
              )}
              {activeTab === 'billing' && (
                <BillingRatesTab
                  rates={billingRates} users={teamMembers} clients={clients}
                  orgDefaultRate={orgInfo?.billing_rate_default || '150.00'}
                  onRefresh={() => loadTabData('billing')}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'costs' && (
                <EmployeeCostRatesTab
                  rates={employeeCostRates} users={teamMembers}
                  onRefresh={() => loadTabData('costs')}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'devices' && (
                <DevicesTab
                  devices={devices}
                  onRefresh={() => loadTabData('devices')}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'token' && (
                <TokenTab
                  token={installToken}
                  onRefresh={() => loadTabData('token')}
                  onSuccess={showSuccess} onError={showError}
                />
              )}
              {activeTab === 'deployment' && (
                <DeploymentTab apiBase={API_BASE} />
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}