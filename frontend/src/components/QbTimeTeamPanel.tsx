// src/components/QbTimeTeamPanel.tsx
// Link QuickBooks Time users to the firm's TimeTracker people.
//
// The sync links people by email (or by a full name only one person has).
// Someone whose QuickBooks Time email is not their work address stays
// unlinked, and their time is skipped when it is sent to QuickBooks Time.
// This is where an admin links them by hand; a link made here survives syncs.

import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Loader2, Users } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { SettingsSection, inputClass, secondaryBtnClass } from '@/pages/settings/ui';

interface Person { id: number; name: string; email: string }
interface QbtUser {
  external_id: string;
  name: string;
  email: string;
  active: boolean;
  linked_user: Person | null;
}
interface StaffResponse { users: QbtUser[]; people: Person[] }

interface Props {
  apiBase: string;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

const QbTimeTeamPanel: React.FC<Props> = ({ apiBase, onSuccess, onError }) => {
  const [data, setData] = useState<StaffResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [showLinked, setShowLinked] = useState(false);

  const load = useCallback(() => {
    setLoadError(null);
    safeFetchJson<StaffResponse>(`${apiBase}/integrations/qb_time/staff/`)
      .then(setData)
      .catch((e: any) => setLoadError(e?.message || 'Could not read QuickBooks Time users'));
  }, [apiBase]);

  useEffect(() => { load(); }, [load]);

  const link = async (u: QbtUser, userId: number | null) => {
    setSaving(u.external_id);
    try {
      const res = await safeFetchJson<{ user: Person | null }>(`${apiBase}/integrations/qb_time/staff/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ external_id: u.external_id, user_id: userId, external_name: u.name }),
      });
      // A person links to one QuickBooks Time user, so a move can unlink
      // another row: reload rather than patch one row.
      load();
      onSuccess(res?.user ? `${u.name} linked to ${res.user.name}` : `${u.name} unlinked`);
    } catch (e: any) {
      onError(e?.message || 'Could not save the link');
    } finally {
      setSaving(null);
    }
  };

  const users = data?.users || [];
  const unlinked = users.filter((u) => !u.linked_user && u.active);
  const linked = users.filter((u) => u.linked_user);
  const shown = showLinked ? users : users.filter((u) => !u.linked_user && u.active);

  return (
    <SettingsSection
      className="mt-4"
      icon={<Users className="w-4 h-4" />}
      title="Team"
      sub="Who each QuickBooks Time user is in TimeTracker. People are linked by email automatically; link anyone whose QuickBooks Time email is different. Unlinked people's time is not sent."
    >
      {loadError && (
        <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1">{loadError}</span>
          <button className={secondaryBtnClass} onClick={load}>Try again</button>
        </div>
      )}

      {!data && !loadError && (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" /> Reading QuickBooks Time users…
        </div>
      )}

      {data && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
            <span className="inline-flex items-center gap-1.5 text-emerald-700">
              <CheckCircle2 className="h-4 w-4" /> {linked.length} linked
            </span>
            {unlinked.length > 0 && (
              <span className="inline-flex items-center gap-1.5 font-semibold text-amber-700">
                <AlertCircle className="h-4 w-4" /> {unlinked.length} not linked
              </span>
            )}
            <span className="flex-1" />
            <button className="text-xs font-medium text-slate-500 hover:text-slate-800 hover:underline"
                    onClick={() => setShowLinked((v) => !v)}>
              {showLinked ? 'Show only not linked' : `Show all ${users.length}`}
            </button>
          </div>

          {shown.length === 0 ? (
            <p className="text-sm text-slate-500">Everyone in QuickBooks Time is linked.</p>
          ) : (
            <div className="divide-y divide-slate-200/70 rounded-xl border border-slate-200/60 bg-white/70">
              {shown.map((u) => (
                <div key={u.external_id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-slate-800">
                      {u.name}{!u.active && <span className="ml-2 text-xs font-normal text-slate-400">inactive</span>}
                    </div>
                    <div className="truncate text-xs text-slate-500">{u.email || 'no email in QuickBooks Time'}</div>
                  </div>
                  <select
                    value={u.linked_user?.id ?? ''}
                    disabled={saving === u.external_id}
                    onChange={(e) => link(u, e.target.value === '' ? null : Number(e.target.value))}
                    className={`${inputClass} w-auto min-w-[14rem]`}
                  >
                    <option value="">Not linked</option>
                    {data.people.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}{p.email ? ` — ${p.email}` : ''}</option>
                    ))}
                  </select>
                  {saving === u.external_id && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </SettingsSection>
  );
};

export default QbTimeTeamPanel;
