// src/components/QbTimePushPanel.tsx
// Send confirmed time to QuickBooks Time as timesheets.
//
// Preview first, always: the preview is the server's real plan (what QuickBooks
// Time already holds is netted out), and nothing is written until the person
// has seen the number. Sending re-plans server-side, so time someone clocked in
// QuickBooks Time between preview and send is netted rather than duplicated.

import React, { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock, Loader2, Send } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import {
  SettingsSection, inputClass, labelClass, primaryBtnClass, secondaryBtnClass,
} from '@/pages/settings/ui';

interface PlanEntry {
  action: 'push' | 'reduce';
  user: string;
  jobcode: string;
  day: string;
  captured_minutes: number;
  already_in_qbt_minutes: number;
  push_minutes: number;
  reduce_minutes?: number;
  parent_jobcode?: boolean;
}

interface Skip {
  reason: string;
  detail: string;
  minutes: number;
}

interface PushError {
  user?: string;
  jobcode: string;
  day: string;
  error: string;
  detail: string;
}

interface PlanResponse {
  dry_run: boolean;
  entries?: PlanEntry[];
  skipped: Skip[];
  totals: { entries: number; minutes: number; hours: number; errors?: number };
  pushed?: { minutes: number }[];
  reduced?: { from_minutes: number; to_minutes: number }[];
  errors?: PushError[];
}

const REASON_LABEL: Record<string, string> = {
  no_client: 'No client',
  jobcode_not_synced: 'Client or project not in QuickBooks Time',
  user_not_mapped: 'Person not found in QuickBooks Time',
  jobcode_inactive: 'Jobcode archived',
  already_in_qbt: 'Already in QuickBooks Time',
  under_increment: 'Under 3 minutes for the day',
};

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

/** Monday–Sunday of the week before this one: the week most firms close out. */
function lastWeek(): [string, string] {
  const now = new Date();
  const monday = new Date(now);
  monday.setDate(now.getDate() - ((now.getDay() + 6) % 7) - 7);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return [iso(monday), iso(sunday)];
}

const hrs = (minutes: number) => `${(minutes / 60).toFixed(2)}h`;

/** Skips grouped by reason — fifty "not synced" rows say one thing. Each
 *  distinct detail is kept, since it names the client or person to fix. */
function groupSkips(skips: Skip[]) {
  const out = new Map<string, { count: number; minutes: number; details: string[] }>();
  for (const s of skips) {
    const g = out.get(s.reason) || { count: 0, minutes: 0, details: [] };
    g.count += 1;
    g.minutes += s.minutes || 0;
    if (s.detail && !g.details.includes(s.detail)) g.details.push(s.detail);
    out.set(s.reason, g);
  }
  return [...out.entries()];
}

type PushTrigger = 'off' | 'approve';

interface Props {
  apiBase: string;
  /** From the integration status; 'off' until an admin turns it on. */
  pushTrigger?: PushTrigger | string | null | undefined;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}

const QbTimePushPanel: React.FC<Props> = ({ apiBase, pushTrigger, onSuccess, onError }) => {
  const [trigger, setTrigger] = useState<PushTrigger>(pushTrigger === 'approve' ? 'approve' : 'off');
  const [savingTrigger, setSavingTrigger] = useState(false);
  useEffect(() => { setTrigger(pushTrigger === 'approve' ? 'approve' : 'off'); }, [pushTrigger]);

  const changeTrigger = async (value: PushTrigger) => {
    const before = trigger;
    setTrigger(value);
    setSavingTrigger(true);
    try {
      await safeFetchJson(`${apiBase}/integrations/qb_time/push-trigger/`, {
        method: 'POST',
        body: JSON.stringify({ push_trigger: value }),
      });
      onSuccess(value === 'approve'
        ? 'Approved timesheets will now be sent to QuickBooks Time.'
        : 'QuickBooks Time will only receive time you send from here.');
    } catch (err: any) {
      setTrigger(before);
      onError(err?.message || 'Could not change when time is sent to QuickBooks Time');
    } finally {
      setSavingTrigger(false);
    }
  };

  const [[start, end], setRange] = useState<[string, string]>(lastWeek);
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [result, setResult] = useState<PlanResponse | null>(null);
  const [busy, setBusy] = useState<'preview' | 'send' | null>(null);

  const call = (dry_run: boolean) =>
    safeFetchJson<PlanResponse>(`${apiBase}/integrations/qb_time/push/`, {
      method: 'POST',
      body: JSON.stringify({ start_date: start, end_date: end, dry_run }),
    });

  const preview = async () => {
    setBusy('preview');
    setResult(null);
    try {
      setPlan(await call(true));
    } catch (err: any) {
      setPlan(null);
      onError(err?.message || 'Could not preview the QuickBooks Time push');
    } finally {
      setBusy(null);
    }
  };

  const send = async () => {
    setBusy('send');
    try {
      const res = await call(false);
      setResult(res);
      setPlan(null);
      const errs = res.errors?.length || 0;
      if (errs) onError(`Sent ${res.totals.hours}h to QuickBooks Time; ${errs} timesheet${errs === 1 ? '' : 's'} failed.`);
      else onSuccess(`Sent ${res.totals.hours}h to QuickBooks Time.`);
    } catch (err: any) {
      onError(err?.message || 'QuickBooks Time push failed');
    } finally {
      setBusy(null);
    }
  };

  const entries = plan?.entries || [];
  const pushes = entries.filter(e => e.action === 'push');
  const reductions = entries.filter(e => e.action === 'reduce');
  const parentCount = pushes.filter(e => e.parent_jobcode).length;

  return (
    <SettingsSection
      className="mt-4"
      icon={<Send className="w-4 h-4" />}
      title="Send time to QuickBooks Time"
      sub="Confirmed time becomes one timesheet per person, jobcode and day, rounded to the nearest 6 minutes. Hours already in QuickBooks Time are subtracted and later time grows the same row, so sending twice never doubles anything."
    >
      {/* Off by default: the firm connected QuickBooks Time to read projects,
          and should see a preview land correctly before approvals start writing. */}
      <div className="mb-4 rounded-xl border border-slate-200/60 bg-white/70 p-3">
        <label className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
          <span className="font-semibold text-slate-600">Send approved timesheets</span>
          <select
            value={trigger}
            disabled={savingTrigger}
            onChange={(e) => changeTrigger(e.target.value as PushTrigger)}
            className={`${inputClass} w-auto`}
          >
            <option value="off">only when sent from here</option>
            <option value="approve">automatically, when a timesheet is approved</option>
          </select>
        </label>
        <p className="mt-2 text-xs text-slate-500">
          {trigger === 'approve'
            ? 'Each approved week goes to QuickBooks Time on its own, for that person and week only. Preview a week below first to check it lands where you expect.'
            : 'Nothing is written to QuickBooks Time unless you send it below. Turn this on once a preview looks right.'}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className={labelClass} htmlFor="qbt-push-start">From</label>
          <input id="qbt-push-start" type="date" className={inputClass} value={start}
                 onChange={e => { setRange([e.target.value, end]); setPlan(null); }} />
        </div>
        <div>
          <label className={labelClass} htmlFor="qbt-push-end">To</label>
          <input id="qbt-push-end" type="date" className={inputClass} value={end}
                 onChange={e => { setRange([start, e.target.value]); setPlan(null); }} />
        </div>
        <button type="button" className={secondaryBtnClass} onClick={preview} disabled={!!busy}>
          {busy === 'preview' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Clock className="w-4 h-4" />}
          Preview
        </button>
      </div>

      {plan && (
        <div className="mt-4 space-y-3">
          {pushes.length === 0 && reductions.length === 0 ? (
            <p className="text-sm text-slate-600">Nothing to send for these dates.</p>
          ) : (
            <>
              <p className="text-sm text-slate-800">
                <span className="font-bold">{pushes.length} timesheet{pushes.length === 1 ? '' : 's'}</span>
                {' '}totalling <span className="font-bold">{hrs(plan.totals.minutes)}</span>
                {reductions.length > 0 && (
                  // Not only refiled time: rounding and trimmed captures reduce too.
                  <> and <span className="font-bold">{reductions.length} correction{reductions.length === 1 ? '' : 's'}</span>,
                  cutting back time we sent earlier that TimeTracker no longer has there</>
                )}.
              </p>
              <div className="max-h-64 overflow-auto rounded-lg border border-slate-200">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-slate-500 sticky top-0">
                    <tr>
                      <th className="text-left px-3 py-2 font-semibold">Day</th>
                      <th className="text-left px-3 py-2 font-semibold">Person</th>
                      <th className="text-left px-3 py-2 font-semibold">Jobcode</th>
                      <th className="text-right px-3 py-2 font-semibold">Captured</th>
                      <th className="text-right px-3 py-2 font-semibold">Already there</th>
                      <th className="text-right px-3 py-2 font-semibold">Send</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((e, i) => (
                      <tr key={i} className="border-t border-slate-100">
                        <td className="px-3 py-1.5 whitespace-nowrap">{e.day}</td>
                        <td className="px-3 py-1.5">{e.user}</td>
                        <td className="px-3 py-1.5">
                          {e.jobcode}
                          {e.parent_jobcode && <span className="ml-1 text-amber-600" title="This jobcode has sub-jobcodes">*</span>}
                        </td>
                        <td className="px-3 py-1.5 text-right">{hrs(e.captured_minutes)}</td>
                        <td className="px-3 py-1.5 text-right">{hrs(e.already_in_qbt_minutes)}</td>
                        <td className="px-3 py-1.5 text-right font-semibold">
                          {e.action === 'reduce'
                            ? <span className="text-amber-700">−{hrs(e.reduce_minutes || 0)}</span>
                            : hrs(e.push_minutes)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {parentCount > 0 && (
                <p className="text-xs text-amber-700">
                  * {parentCount} timesheet{parentCount === 1 ? ' goes' : 's go'} to a client-level jobcode that has
                  projects under it. QuickBooks Time may refuse those; filing the time to a project avoids it.
                </p>
              )}
            </>
          )}

          {plan.skipped.length > 0 && (
            <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
              <p className="text-xs font-bold text-slate-700 mb-1">Not sent</p>
              <ul className="space-y-1">
                {groupSkips(plan.skipped).map(([reason, g]) => (
                  <li key={reason} className="text-xs text-slate-600">
                    <span className="font-semibold">{REASON_LABEL[reason] || reason}</span>
                    {' '}— {g.count} item{g.count === 1 ? '' : 's'}, {hrs(g.minutes)}.
                    {reason !== 'already_in_qbt' && (
                      <ul className="ml-3 mt-0.5 list-disc list-inside text-slate-500">
                        {g.details.slice(0, 5).map(d => <li key={d}>{d}</li>)}
                        {g.details.length > 5 && <li>and {g.details.length - 5} more</li>}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {(pushes.length > 0 || reductions.length > 0) && (
            <button type="button" className={primaryBtnClass} onClick={send} disabled={!!busy}>
              {busy === 'send' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              {/* Say everything the click writes — corrections cut real rows too. */}
              {(() => {
                const fixes = reductions.length
                  ? `${reductions.length} correction${reductions.length === 1 ? '' : 's'}`
                  : '';
                if (!pushes.length) return `Apply ${fixes} in QuickBooks Time`;
                const send = `Send ${hrs(plan.totals.minutes)}`;
                return fixes ? `${send} and ${fixes} to QuickBooks Time` : `${send} to QuickBooks Time`;
              })()}
            </button>
          )}
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-2">
          <p className="text-sm text-emerald-800 flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4" />
            Sent {result.totals.entries} timesheet{result.totals.entries === 1 ? '' : 's'} ({hrs(result.totals.minutes)})
            {(result.reduced?.length || 0) > 0 && `, corrected ${result.reduced!.length}`}.
          </p>
          {(result.errors?.length || 0) > 0 && (
            <div className="rounded-lg bg-red-50 border border-red-200 p-3">
              <p className="text-xs font-bold text-red-800 mb-1 flex items-center gap-1.5">
                <AlertCircle className="w-4 h-4" /> QuickBooks Time refused {result.errors!.length}
              </p>
              <ul className="space-y-0.5">
                {result.errors!.map((e, i) => (
                  <li key={i} className="text-xs text-red-700">
                    {e.day} · {e.user} · {e.jobcode}: {e.detail}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </SettingsSection>
  );
};

export default QbTimePushPanel;
