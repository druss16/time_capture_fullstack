// src/components/ManualTimeEntry.tsx

import { useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { Plus, Clock, X, Check } from "lucide-react";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type ClientOption = { id: number; name: string };

const DEFAULT_CATEGORIES = [
  "Tax Preparation",
  "Audit/Assurance",
  "Bookkeeping",
  "Advisory/Consulting",
  "Research/AI Assistance",
  "Email/Communication",
  "Admin/Internal",
  "Software Development",
  "Meeting/Call",
  "Training",
];

type ManualTimeEntryProps = {
  onSuccess?: () => void;
  defaultDate?: string;
  isOpen?: boolean;
  onClose?: () => void;
  preSelectedClientId?: number | null;
};

export default function ManualTimeEntry({
  onSuccess,
  defaultDate,
  isOpen: externalIsOpen,
  onClose: externalOnClose,
  preSelectedClientId,
}: ManualTimeEntryProps) {
  const [internalIsOpen, setInternalIsOpen] = useState(false);
  const isControlled = externalIsOpen !== undefined;
  const isOpen = isControlled ? externalIsOpen : internalIsOpen;

  const handleClose = () => {
    if (isControlled && externalOnClose) externalOnClose();
    else setInternalIsOpen(false);
  };

  const [clients, setClients] = useState<ClientOption[]>([]);
  const [categories, setCategories] = useState<string[]>(DEFAULT_CATEGORIES);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [form, setForm] = useState({
    client_id: "",
    category: "",
    date: defaultDate || new Date().toISOString().split("T")[0],
    hours: "",
    minutes: "",
    start_time: "09:00",
    notes: "",
  });

  useEffect(() => {
    if (preSelectedClientId && isOpen)
      setForm((prev) => ({ ...prev, client_id: preSelectedClientId.toString() }));
  }, [preSelectedClientId, isOpen]);

  useEffect(() => {
    if (defaultDate) setForm((prev) => ({ ...prev, date: defaultDate }));
  }, [defaultDate]);

  const loadClients = useCallback(async () => {
    try {
      const data = await safeFetchJson<ClientOption[]>(`${API_BASE}/settings/my-clients/`);
      if (data?.length) { setClients(data); return; }
    } catch {}
    for (const url of [`${API_BASE}/options/clients/`, `${API_BASE}/clients/list/`]) {
      try {
        const data = await safeFetchJson<ClientOption[]>(url);
        if (data?.length) { setClients(data); return; }
      } catch {}
    }
  }, []);

  const loadCategories = useCallback(async () => {
    try {
      const data = await safeFetchJson<{ id: number; name: string }[]>(`${API_BASE}/options/task-types/`);
      if (data?.length) setCategories(data.map((t) => t.name));
    } catch {}
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadClients();
      loadCategories();
      setError(null);
      setSuccess(false);
    }
  }, [isOpen, loadClients, loadCategories]);

  const getTotalHours = () => (parseFloat(form.hours) || 0) + (parseFloat(form.minutes) || 0) / 60;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const totalHours = getTotalHours();
    if (!form.client_id) { setError("Please select a client"); return; }
    if (!form.category) { setError("Please select a category"); return; }
    if (totalHours <= 0) { setError("Please enter time (hours or minutes)"); return; }

    setIsSubmitting(true);
    try {
      const response = await safeFetchJson(`${API_BASE}/time-entries/manual/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: parseInt(form.client_id),
          category: form.category,
          date: form.date,
          hours: totalHours,
          start_time: form.start_time,
          notes: form.notes,
        }),
      });
      if (response?.success) {
        setSuccess(true);
        setForm({
          client_id: "",
          category: "",
          date: defaultDate || new Date().toISOString().split("T")[0],
          hours: "",
          minutes: "",
          start_time: "09:00",
          notes: "",
        });
        setTimeout(() => { handleClose(); setSuccess(false); onSuccess?.(); }, 1500);
      } else {
        throw new Error(response?.error || "Failed to create time entry");
      }
    } catch (err: any) {
      setError(err?.message || "Failed to create time entry");
    } finally {
      setIsSubmitting(false);
    }
  };

  const quickTimes = [
    { label: "15m", hours: 0, minutes: 15 },
    { label: "30m", hours: 0, minutes: 30 },
    { label: "1h", hours: 1, minutes: 0 },
    { label: "1.5h", hours: 1, minutes: 30 },
    { label: "2h", hours: 2, minutes: 0 },
    { label: "4h", hours: 4, minutes: 0 },
  ];

  const selectedClient = clients.find((c) => c.id.toString() === form.client_id);

  return (
    <>
      {/* Trigger — only when uncontrolled */}
      {!isControlled && (
        <button
          onClick={() => setInternalIsOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors font-semibold text-sm shadow-sm"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Time
        </button>
      )}

      {/* ── Modal (portalled to body to escape all stacking contexts) ──────── */}
      {isOpen && createPortal(
        <div
          className="fixed inset-0 z-[9999] bg-black/40 backdrop-blur-[2px] overflow-y-auto"
          onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
        >
          {/*
            Key fix: instead of flex centering (which clips on short viewports),
            we use a block container with auto margins and top padding.
            This lets the modal start near the top and the page scroll behind it.
          */}
          <div className="min-h-full flex items-start justify-center p-4 sm:pt-10">
            <div className="w-full max-w-md bg-white rounded-2xl shadow-2xl my-auto">

              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-primary/10 rounded-xl">
                    <Clock className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <h2 className="text-base font-extrabold text-slate-900 leading-none">
                      Add Time Manually
                    </h2>
                    {selectedClient && (
                      <p className="text-xs text-primary font-semibold mt-0.5">{selectedClient.name}</p>
                    )}
                  </div>
                </div>
                <button
                  onClick={handleClose}
                  className="p-1.5 hover:bg-slate-100 rounded-lg transition-colors text-slate-400 hover:text-slate-700"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Form */}
              <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">

                {success && (
                  <div className="flex items-center gap-2 px-3 py-2.5 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-700 text-sm font-semibold">
                    <Check className="w-4 h-4 shrink-0" />
                    Time entry added!
                  </div>
                )}
                {error && (
                  <div className="px-3 py-2.5 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm font-medium">
                    {error}
                  </div>
                )}

                {/* Client */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Client <span className="text-red-400">*</span>
                  </label>
                  <select
                    value={form.client_id}
                    onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                    className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm font-medium bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                    required
                  >
                    <option value="">Select client…</option>
                    {clients.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>

                {/* Category */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Category <span className="text-red-400">*</span>
                  </label>
                  <select
                    value={form.category}
                    onChange={(e) => setForm({ ...form, category: e.target.value })}
                    className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm font-medium bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                    required
                  >
                    <option value="">Select category…</option>
                    {categories.map((cat) => (
                      <option key={cat} value={cat}>{cat}</option>
                    ))}
                  </select>
                </div>

                {/* Date */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Date <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="date"
                    value={form.date}
                    onChange={(e) => setForm({ ...form, date: e.target.value })}
                    className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                    required
                  />
                </div>

                {/* Duration */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Duration <span className="text-red-400">*</span>
                  </label>
                  <div className="flex gap-2">
                    <div className="relative flex-1">
                      <input
                        type="number"
                        min="0"
                        max="24"
                        step="1"
                        placeholder="0"
                        value={form.hours}
                        onChange={(e) => setForm({ ...form, hours: e.target.value })}
                        className="w-full border border-slate-200 rounded-xl px-3 py-2.5 pr-10 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 font-semibold pointer-events-none">hrs</span>
                    </div>
                    <div className="relative flex-1">
                      <input
                        type="number"
                        min="0"
                        max="59"
                        step="5"
                        placeholder="0"
                        value={form.minutes}
                        onChange={(e) => setForm({ ...form, minutes: e.target.value })}
                        className="w-full border border-slate-200 rounded-xl px-3 py-2.5 pr-10 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 font-semibold pointer-events-none">min</span>
                    </div>
                  </div>

                  {/* Quick picks */}
                  <div className="flex flex-wrap gap-1.5 pt-1">
                    {quickTimes.map((qt) => (
                      <button
                        key={qt.label}
                        type="button"
                        onClick={() => setForm({ ...form, hours: qt.hours.toString(), minutes: qt.minutes.toString() })}
                        className="px-2.5 py-1 text-xs font-bold bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg transition-colors"
                      >
                        {qt.label}
                      </button>
                    ))}
                  </div>

                  {getTotalHours() > 0 && (
                    <p className="text-xs text-primary font-bold">
                      = {getTotalHours().toFixed(2)} hours total
                    </p>
                  )}
                </div>

                {/* Start Time */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Start Time{" "}
                    <span className="normal-case font-medium text-slate-400">(optional)</span>
                  </label>
                  <input
                    type="time"
                    value={form.start_time}
                    onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                    className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                  />
                </div>

                {/* Notes */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-500 uppercase tracking-wide">
                    Notes{" "}
                    <span className="normal-case font-medium text-slate-400">(optional)</span>
                  </label>
                  <textarea
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    placeholder="What did you work on?"
                    rows={2}
                    className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all resize-none"
                  />
                </div>

                {/* Actions */}
                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    onClick={handleClose}
                    className="flex-1 px-4 py-2.5 border border-slate-200 rounded-xl text-sm font-bold text-slate-600 hover:bg-slate-50 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting || success}
                    className="flex-1 px-4 py-2.5 bg-primary text-white rounded-xl text-sm font-bold hover:opacity-90 disabled:opacity-50 transition-all flex items-center justify-center gap-2 shadow-md shadow-primary/20"
                  >
                    {isSubmitting ? (
                      <span className="flex items-center gap-2">
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Saving…
                      </span>
                    ) : success ? (
                      <span className="flex items-center gap-2">
                        <Check className="w-3.5 h-3.5" />
                        Saved!
                      </span>
                    ) : (
                      <span className="flex items-center gap-2">
                        <Plus className="w-3.5 h-3.5" />
                        Add Time
                      </span>
                    )}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}