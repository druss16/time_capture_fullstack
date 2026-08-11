// src/pages/settings/EconomicsImportModal.tsx
// Owner/admin CSV import for the Economics page. Uploads a team roster
// (email, tier, cost_rate, bill_rate, hours_per_week); the backend parses and
// matches by email, previews the changes (dry run), then applies on confirm.
import { useEffect, useState } from 'react';
import { X, Upload, Download, FileSpreadsheet, Check, RefreshCw, AlertCircle, ArrowLeft, CheckCircle2 } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import type { TeamMember } from './types';
import { primaryBtnClass, secondaryBtnClass } from './ui';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

interface TierPreview { label: string; cost_rate: string | null; bill_rate: string | null; hours_per_week: string | null; action: 'create' | 'update'; }
interface Assignment { email: string; name: string; tier: string; }
interface Unmatched { email: string; tier: string; reason: string; }
interface Preview {
  tiers: TierPreview[];
  assignments: Assignment[];
  unmatched: Unmatched[];
  warnings: string[];
  summary: { tiers: number; people: number; unmatched: number };
  applied?: { tiers: number; assigned: number };
}

interface Props {
  onClose: () => void;
  onImported: () => void;
  users: TeamMember[];
}

interface Tier { id?: number; label: string; cost_rate?: string | null; bill_rate?: string | null; hours_per_week?: string | null; }

const TEMPLATE =
  'email,tier,cost_rate,bill_rate,hours_per_week\n' +
  'jane@yourfirm.com,Partner,200,350,40\n' +
  'bob@yourfirm.com,Manager,130,200,40\n' +
  'sara@yourfirm.com,Staff,75,150,40\n';

export default function EconomicsImportModal({ onClose, onImported, users }: Props) {
  const [step, setStep]       = useState<'upload' | 'preview' | 'done'>('upload');
  const [csvText, setCsvText] = useState('');
  const [fileName, setFileName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [tiers, setTiers]     = useState<Tier[]>([]);
  const [teamCsv, setTeamCsv] = useState('');

  // Pull existing tiers + roster so we can show valid tier names and offer a
  // template pre-filled with the real team.
  useEffect(() => {
    safeFetchJson<{ tiers?: Tier[]; members?: { id: number; cost_tier_id: number | null }[] }>(
      `${API_BASE}/settings/cost-rates/`,
    ).then(d => {
      const tierList = d.tiers || [];
      setTiers(tierList);
      const tierById: Record<number, Tier> = {};
      tierList.forEach(t => { if (t.id != null) tierById[t.id] = t; });
      const emailById: Record<number, string> = {};
      users.forEach(u => { if (u.email) emailById[u.id] = u.email; });
      const lines = (d.members || [])
        .filter(m => emailById[m.id])
        .map(m => {
          const t = m.cost_tier_id != null ? tierById[m.cost_tier_id] : undefined;
          return [emailById[m.id], t?.label || '', t?.cost_rate ?? '', t?.bill_rate ?? '', t?.hours_per_week ?? ''].join(',');
        });
      if (lines.length) setTeamCsv('email,tier,cost_rate,bill_rate,hours_per_week\n' + lines.join('\n') + '\n');
    }).catch(() => {});
  }, [users]);

  const download = (content: string, name: string) => {
    const blob = new Blob([content], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };
  const downloadTemplate = () => (teamCsv
    ? download(teamCsv, 'my-team.csv')
    : download(TEMPLATE, 'economics-roster-template.csv'));

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFileName(f.name);
    setCsvText(await f.text());
    setError(null);
  };

  const post = async (dryRun: boolean): Promise<Preview> =>
    safeFetchJson<Preview>(`${API_BASE}/settings/economics/import/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv_content: csvText, dry_run: dryRun }),
    });

  const runPreview = async () => {
    if (!csvText.trim()) { setError('Add a CSV file or paste rows first.'); return; }
    setLoading(true); setError(null);
    try {
      setPreview(await post(true));
      setStep('preview');
    } catch (e: any) {
      setError(e?.message || 'Could not read that CSV');
    } finally { setLoading(false); }
  };

  const runApply = async () => {
    setLoading(true); setError(null);
    try {
      setPreview(await post(false));
      setStep('done');
      onImported();
    } catch (e: any) {
      setError(e?.message || 'Import failed');
    } finally { setLoading(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" style={{ fontFamily: '"Inter", sans-serif' }}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200/70">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 bg-primary/10 rounded-xl flex items-center justify-center">
              <Upload className="w-4 h-4 text-primary" />
            </div>
            <div>
              <h2 className="text-[15px] font-bold text-slate-900">Import team roster</h2>
              <p className="text-[12px] text-slate-400">Populate tiers & assignments from a CSV.</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-4 h-4 text-slate-500" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
              <span className="text-[13px] text-red-700">{error}</span>
            </div>
          )}

          {/* ── Upload ── */}
          {step === 'upload' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/70 bg-slate-50/60 p-3.5">
                <div className="flex items-start gap-2.5 min-w-0">
                  <FileSpreadsheet className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" />
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-slate-800">
                      {teamCsv ? 'Start from your team' : 'Need the format?'}
                    </p>
                    <p className="text-[12px] text-slate-400">Columns: email · tier · cost_rate · bill_rate · hours_per_week</p>
                  </div>
                </div>
                <button onClick={downloadTemplate} className={`${secondaryBtnClass} shrink-0`}>
                  <Download className="w-3.5 h-3.5" /> {teamCsv ? 'Download my team' : 'Template'}
                </button>
              </div>

              {tiers.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[12px] text-slate-400">Use these tier names:</span>
                  {tiers.map(t => (
                    <span key={t.label} className="text-[11px] font-semibold text-primary bg-primary/8 border border-primary/20 rounded-full px-2 py-0.5">
                      {t.label}
                    </span>
                  ))}
                </div>
              )}

              <label className="block cursor-pointer rounded-2xl border-2 border-dashed border-slate-200 hover:border-primary/40 transition-colors p-8 text-center">
                <input type="file" accept=".csv,text/csv" onChange={onFile} className="hidden" />
                <Upload className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                <p className="text-[13px] font-semibold text-slate-700">{fileName || 'Choose a CSV file'}</p>
                <p className="text-[12px] text-slate-400 mt-0.5">or paste rows below</p>
              </label>

              <textarea
                value={csvText}
                onChange={e => { setCsvText(e.target.value); setFileName(''); }}
                placeholder="email,tier,cost_rate,bill_rate,hours_per_week&#10;jane@yourfirm.com,Partner,200,350,40"
                rows={5}
                className="w-full px-3 py-2 border border-border/60 rounded-lg text-[13px] font-mono text-slate-800 focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none bg-white resize-y"
              />

              <p className="text-[12px] text-slate-400 leading-snug">
                People are matched by email. Tiers are created from the tier names/rates in the file. Nothing
                is saved until you review the preview on the next step.
              </p>
            </div>
          )}

          {/* ── Preview ── */}
          {step === 'preview' && preview && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <Stat n={preview.summary.tiers} label="Tiers" />
                <Stat n={preview.summary.people} label="People assigned" />
                <Stat n={preview.summary.unmatched} label="Unmatched" warn={preview.summary.unmatched > 0} />
              </div>

              {preview.tiers.length > 0 && (
                <Block title="Tiers">
                  {preview.tiers.map((t, i) => (
                    <Row key={i}>
                      <span className="font-semibold text-slate-800">{t.label}</span>
                      <span className="text-slate-400">
                        cost {t.cost_rate ? `$${t.cost_rate}` : '—'} · bill {t.bill_rate ? `$${t.bill_rate}` : '—'} · {t.hours_per_week || '—'} hrs
                      </span>
                      <Tag kind={t.action === 'create' ? 'good' : 'neutral'}>{t.action}</Tag>
                    </Row>
                  ))}
                </Block>
              )}

              {preview.assignments.length > 0 && (
                <Block title={`Assignments (${preview.assignments.length})`}>
                  {preview.assignments.map((a, i) => (
                    <Row key={i}>
                      <span className="font-medium text-slate-800">{a.name}</span>
                      <span className="text-slate-400">{a.email}</span>
                      <Tag kind="good">→ {a.tier}</Tag>
                    </Row>
                  ))}
                </Block>
              )}

              {preview.unmatched.length > 0 && (
                <Block title={`Unmatched — will be skipped (${preview.unmatched.length})`}>
                  {preview.unmatched.map((u, i) => (
                    <Row key={i}>
                      <span className="font-medium text-slate-700">{u.email}</span>
                      <span className="text-slate-400">{u.reason}</span>
                    </Row>
                  ))}
                </Block>
              )}

              {preview.warnings.length > 0 && (
                <Block title="Notes">
                  {preview.warnings.map((w, i) => (
                    <p key={i} className="px-3 py-1.5 text-[12px] text-amber-700">{w}</p>
                  ))}
                </Block>
              )}
            </div>
          )}

          {/* ── Done ── */}
          {step === 'done' && preview?.applied && (
            <div className="text-center py-8">
              <div className="w-14 h-14 rounded-full bg-emerald-100 flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="w-7 h-7 text-emerald-600" />
              </div>
              <h3 className="text-[16px] font-bold text-slate-900">Import complete</h3>
              <p className="text-[13px] text-slate-500 mt-1">
                {preview.applied.tiers} tier{preview.applied.tiers === 1 ? '' : 's'} and{' '}
                {preview.applied.assigned} assignment{preview.applied.assigned === 1 ? '' : 's'} saved.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-t border-slate-200/70 bg-slate-50/50">
          {step === 'upload' && (
            <>
              <button onClick={onClose} className={secondaryBtnClass}>Cancel</button>
              <button onClick={runPreview} disabled={loading || !csvText.trim()} className={primaryBtnClass}>
                {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <ArrowLeft className="w-3.5 h-3.5 rotate-180" />}
                Preview
              </button>
            </>
          )}
          {step === 'preview' && (
            <>
              <button onClick={() => setStep('upload')} className={secondaryBtnClass}>
                <ArrowLeft className="w-3.5 h-3.5" /> Back
              </button>
              <button onClick={runApply} disabled={loading || (preview?.summary.tiers === 0 && preview?.summary.people === 0)} className={primaryBtnClass}>
                {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                Import {preview?.summary.people ?? 0} people
              </button>
            </>
          )}
          {step === 'done' && (
            <button onClick={onClose} className={`${primaryBtnClass} ml-auto`}>Done</button>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ n, label, warn }: { n: number; label: string; warn?: boolean }) {
  return (
    <div className={`rounded-xl border p-3 text-center ${warn ? 'border-amber-200 bg-amber-50/60' : 'border-slate-200/70 bg-slate-50/60'}`}>
      <p className={`text-2xl font-extrabold ${warn ? 'text-amber-600' : 'text-slate-800'}`}>{n}</p>
      <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{label}</p>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200/70 overflow-hidden">
      <p className="px-3 py-1.5 bg-slate-50/80 text-[11px] font-bold uppercase tracking-widest text-slate-400">{title}</p>
      <div className="divide-y divide-slate-100 max-h-44 overflow-y-auto">{children}</div>
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center gap-2 px-3 py-1.5 text-[12.5px] [&>*:nth-child(2)]:ml-auto">{children}</div>;
}

function Tag({ kind, children }: { kind: 'good' | 'neutral'; children: React.ReactNode }) {
  const cls = kind === 'good'
    ? 'bg-primary/8 text-primary border-primary/20'
    : 'bg-slate-100 text-slate-500 border-slate-200';
  return <span className={`shrink-0 text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full border ${cls}`}>{children}</span>;
}
