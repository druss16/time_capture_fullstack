// src/components/AsanaProjectsPanel.tsx
// Link Asana projects to the firm's TimeTracker projects.
//
// Asana never creates projects here — a firm's projects come from QuickBooks
// Time or are kept in TimeTracker — so each Asana project is LINKED to one.
// The sync links those with the same name; this is where an admin links the
// rest (names that differ, or one name several clients share). Only linked
// projects file Asana time. A link made here survives syncs.

import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, FolderKanban, Loader2 } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { SettingsSection, inputClass, secondaryBtnClass } from '@/pages/settings/ui';

interface AsanaProject {
  asana_gid: string;
  asana_name: string;
  archived: boolean;
  project_id: number | null;
  project_name: string | null;
  client_name: string | null;
  link_source: '' | 'name' | 'manual';
}
interface ProjectOption { id: number; name: string; client_name: string }
interface ProjectsResponse { projects: AsanaProject[]; options: ProjectOption[] }

interface Props {
  apiBase: string;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

const AsanaProjectsPanel: React.FC<Props> = ({ apiBase, onSuccess, onError }) => {
  const [data, setData] = useState<ProjectsResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [showLinked, setShowLinked] = useState(false);

  const load = useCallback(() => {
    setLoadError(null);
    safeFetchJson<ProjectsResponse>(`${apiBase}/integrations/asana/projects/`)
      .then(setData)
      .catch((e: any) => setLoadError(e?.message || 'Could not read Asana projects'));
  }, [apiBase]);

  useEffect(() => { load(); }, [load]);

  const link = async (p: AsanaProject, projectId: number | null) => {
    setSaving(p.asana_gid);
    try {
      await safeFetchJson(`${apiBase}/integrations/asana/projects/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asana_gid: p.asana_gid, project_id: projectId }),
      });
      load();
      onSuccess(projectId ? `${p.asana_name} linked` : `${p.asana_name} unlinked`);
    } catch (e: any) {
      onError(e?.message || 'Could not save the link');
    } finally {
      setSaving(null);
    }
  };

  const live = (data?.projects || []).filter((p) => !p.archived);
  const linked = live.filter((p) => p.project_id);
  const unlinked = live.filter((p) => !p.project_id);
  const shown = showLinked ? live : unlinked;

  return (
    <SettingsSection
      className="mt-4"
      icon={<FolderKanban className="w-4 h-4" />}
      title="Asana projects"
      sub="Which TimeTracker project each Asana project is. Projects with the same name link automatically; link the rest here. Time in an unlinked Asana project still asks you."
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
          <Loader2 className="h-4 w-4 animate-spin" /> Reading Asana projects…
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
              {showLinked ? 'Show only not linked' : `Show all ${live.length}`}
            </button>
          </div>

          {live.length === 0 ? (
            <p className="text-sm text-slate-500">No Asana projects yet — the first sync is still running, or the connected account sees none.</p>
          ) : shown.length === 0 ? (
            <p className="text-sm text-slate-500">Every Asana project is linked.</p>
          ) : (
            <div className="divide-y divide-slate-200/70 rounded-xl border border-slate-200/60 bg-white/70">
              {shown.map((p) => (
                <div key={p.asana_gid} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-slate-800">{p.asana_name || p.asana_gid}</div>
                    <div className="truncate text-xs text-slate-500">
                      {p.project_id
                        ? `${p.client_name ? `${p.client_name} · ` : ''}${p.link_source === 'manual' ? 'linked by hand' : 'matched by name'}`
                        : 'not linked'}
                    </div>
                  </div>
                  <select
                    value={p.project_id ?? ''}
                    disabled={saving === p.asana_gid}
                    onChange={(e) => link(p, e.target.value === '' ? null : Number(e.target.value))}
                    className={`${inputClass} w-auto min-w-[16rem] max-w-full`}
                  >
                    <option value="">Not linked</option>
                    {data.options.map((o) => (
                      <option key={o.id} value={o.id}>{o.client_name ? `${o.client_name} — ` : ''}{o.name}</option>
                    ))}
                  </select>
                  {saving === p.asana_gid && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </SettingsSection>
  );
};

export default AsanaProjectsPanel;
