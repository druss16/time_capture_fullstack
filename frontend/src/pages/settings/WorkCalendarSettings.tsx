// Work Calendar & Capacity — the utilization denominator. Scheduled hours net
// of holidays, summer Fridays, and PTO. Overrides per-tier Hrs/wk when set.
import { useEffect, useMemo, useState } from 'react';
import { Check, RefreshCw, Plus, Trash2, CalendarDays } from 'lucide-react';
import { safeFetchJson } from '@/lib/api';
import { inputClass, labelClass, primaryBtnClass } from './ui';

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:7123/api';
const API_BASE = RAW_BASE.endsWith('/api') ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, '')}/api`;

const WEEKDAYS = [
  { i: 0, label: 'Mon' }, { i: 1, label: 'Tue' }, { i: 2, label: 'Wed' },
  { i: 3, label: 'Thu' }, { i: 4, label: 'Fri' }, { i: 5, label: 'Sat' }, { i: 6, label: 'Sun' },
];
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

interface Cal {
  configured: boolean;
  hours_per_day: string;
  working_weekdays: number[];
  summer_fridays_off: boolean;
  summer_start_month: number;
  summer_end_month: number;
  avg_pto_days_per_year: string;
  holidays: string[];
  org_capacity_default: string;
}

interface Props { onSuccess: (m: string) => void; onError: (m: string) => void; }

export default function WorkCalendarSettings({ onSuccess, onError }: Props) {
  const [cal, setCal] = useState<Cal | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newHoliday, setNewHoliday] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      setCal(await safeFetchJson<Cal>(`${API_BASE}/settings/work-calendar/`));
    } catch (e: any) {
      onError(e?.message || 'Failed to load work calendar');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const set = <K extends keyof Cal>(k: K, v: Cal[K]) =>
    setCal(c => (c ? { ...c, [k]: v } : c));

  const toggleWeekday = (i: number) =>
    setCal(c => {
      if (!c) return c;
      const has = c.working_weekdays.includes(i);
      const next = has ? c.working_weekdays.filter(x => x !== i) : [...c.working_weekdays, i];
      return { ...c, working_weekdays: next.sort((a, b) => a - b) };
    });

  const addHoliday = () => {
    if (!newHoliday || !/^\d{4}-\d{2}-\d{2}$/.test(newHoliday)) return;
    setCal(c => (c && !c.holidays.includes(newHoliday)
      ? { ...c, holidays: [...c.holidays, newHoliday].sort() } : c));
    setNewHoliday('');
  };
  const removeHoliday = (h: string) =>
    setCal(c => (c ? { ...c, holidays: c.holidays.filter(x => x !== h) } : c));

  // Rough blended weekly capacity preview, so the effect is visible while editing.
  const blendedWeekly = useMemo(() => {
    if (!cal) return null;
    const hpd = parseFloat(cal.hours_per_day) || 0;
    const workdays = cal.working_weekdays.length;               // per week
    let summerFridayWeeks = 0;
    if (cal.summer_fridays_off && cal.working_weekdays.includes(4)) {
      const months = Math.max(0, cal.summer_end_month - cal.summer_start_month + 1);
      summerFridayWeeks = Math.round(months * 4.33);            // ≈ Fridays in the span
    }
    const grossYear = workdays * 52 * hpd;
    const holidayH = cal.holidays.length * hpd;
    const summerH = summerFridayWeeks * hpd;
    const ptoH = (parseFloat(cal.avg_pto_days_per_year) || 0) * hpd;
    const net = Math.max(0, grossYear - holidayH - summerH - ptoH);
    return net / 52;
  }, [cal]);

  if (loading || !cal) return <div className="text-slate-400 text-sm p-4">Loading work calendar…</div>;

  const save = async () => {
    setSaving(true);
    try {
      await safeFetchJson(`${API_BASE}/settings/work-calendar/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          hours_per_day: cal.hours_per_day,
          working_weekdays: cal.working_weekdays,
          summer_fridays_off: cal.summer_fridays_off,
          summer_start_month: cal.summer_start_month,
          summer_end_month: cal.summer_end_month,
          avg_pto_days_per_year: cal.avg_pto_days_per_year,
          holidays: cal.holidays,
        }),
      });
      onSuccess('Work calendar saved');
      await load();
    } catch (e: any) {
      onError(e?.message || 'Failed to save work calendar');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <p className="text-[12px] text-slate-500 leading-snug">
        Drives available <strong>capacity</strong> for utilization — scheduled hours minus holidays,
        summer Fridays, and PTO. <span className="text-slate-400">When set, this overrides the per-tier
        Hrs/wk and the {cal.org_capacity_default} firm default.</span>
      </p>

      {/* Hours/day + avg PTO */}
      <div className="flex flex-wrap gap-4">
        <div>
          <label className={labelClass}>Hours / day</label>
          <input type="number" step="0.5" min="0" max="24" value={cal.hours_per_day}
            onChange={e => set('hours_per_day', e.target.value)}
            className={`${inputClass} w-28`} />
        </div>
        <div>
          <label className={labelClass}>Avg PTO days / year</label>
          <input type="number" step="1" min="0" max="60" value={cal.avg_pto_days_per_year}
            onChange={e => set('avg_pto_days_per_year', e.target.value)}
            className={`${inputClass} w-36`} />
        </div>
        {blendedWeekly != null && (
          <div className="ml-auto self-end text-right">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">Blended capacity</div>
            <div className="text-lg font-bold text-primary tabular-nums">{blendedWeekly.toFixed(1)} h/wk</div>
          </div>
        )}
      </div>

      {/* Working weekdays */}
      <div>
        <label className={labelClass}>Working days</label>
        <div className="flex flex-wrap gap-1.5 mt-1">
          {WEEKDAYS.map(w => {
            const on = cal.working_weekdays.includes(w.i);
            return (
              <button key={w.i} type="button" onClick={() => toggleWeekday(w.i)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                  on ? 'bg-primary/10 border-primary/40 text-primary'
                     : 'bg-white border-border/60 text-slate-500 hover:bg-slate-50'}`}>
                {w.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Summer Fridays */}
      <div>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={cal.summer_fridays_off}
            onChange={e => set('summer_fridays_off', e.target.checked)}
            className="h-4 w-4 accent-primary" />
          <span className="text-sm font-medium text-slate-700">Fridays off during summer</span>
        </label>
        {cal.summer_fridays_off && (
          <div className="flex items-center gap-2 mt-2 pl-6 text-sm text-slate-600">
            <span>From</span>
            <select value={cal.summer_start_month} onChange={e => set('summer_start_month', Number(e.target.value))}
              className={`${inputClass} w-24 py-1.5`}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
            <span>through</span>
            <select value={cal.summer_end_month} onChange={e => set('summer_end_month', Number(e.target.value))}
              className={`${inputClass} w-24 py-1.5`}>
              {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
          </div>
        )}
      </div>

      {/* Holidays */}
      <div>
        <label className={labelClass}>Firm holidays</label>
        <div className="flex items-center gap-2 mt-1">
          <input type="date" value={newHoliday} onChange={e => setNewHoliday(e.target.value)}
            className={`${inputClass} w-44`} />
          <button type="button" onClick={addHoliday}
            className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-primary border border-primary/30 rounded-lg hover:bg-primary/5">
            <Plus className="w-3.5 h-3.5" /> Add
          </button>
        </div>
        {cal.holidays.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {cal.holidays.map(h => (
              <span key={h} className="inline-flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 rounded-lg bg-slate-100 text-xs text-slate-600 tabular-nums">
                <CalendarDays className="w-3 h-3 text-slate-400" />{h}
                <button type="button" onClick={() => removeHoliday(h)} className="text-slate-400 hover:text-rose-500">
                  <Trash2 className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      <button onClick={save} disabled={saving} className={primaryBtnClass}>
        {saving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
        Save Work Calendar
      </button>
    </div>
  );
}
