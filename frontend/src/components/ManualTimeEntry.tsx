// src/components/ManualTimeEntry.tsx

import { useState, useEffect, useCallback } from "react";
import { Plus, Clock, X, Check, Calendar } from "lucide-react";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type ClientOption = {
  id: number;
  name: string;
};

const DEFAULT_CATEGORIES = [
  'Tax Preparation',
  'Audit/Assurance',
  'Bookkeeping',
  'Advisory/Consulting',
  'Research/AI Assistance',
  'Email/Communication',
  'Admin/Internal',
  'Software Development',
  'Meeting/Call',
  'Training',
];

type ManualTimeEntryProps = {
  onSuccess?: () => void;
  defaultDate?: string;
  // NEW: External control props
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
  // Use external control if provided, otherwise internal
  const [internalIsOpen, setInternalIsOpen] = useState(false);
  const isControlled = externalIsOpen !== undefined;
  const isOpen = isControlled ? externalIsOpen : internalIsOpen;
  
  const handleClose = () => {
    if (isControlled && externalOnClose) {
      externalOnClose();
    } else {
      setInternalIsOpen(false);
    }
  };

  const handleOpen = () => {
    if (!isControlled) {
      setInternalIsOpen(true);
    }
  };

  const [clients, setClients] = useState<ClientOption[]>([]);
  const [categories, setCategories] = useState<string[]>(DEFAULT_CATEGORIES);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Form state
  const [form, setForm] = useState({
    client_id: '',
    category: '',
    date: defaultDate || new Date().toISOString().split('T')[0],
    hours: '',
    minutes: '',
    start_time: '09:00',
    notes: '',
  });

  // Update form when preSelectedClientId changes
  useEffect(() => {
    if (preSelectedClientId && isOpen) {
      setForm(prev => ({ ...prev, client_id: preSelectedClientId.toString() }));
    }
  }, [preSelectedClientId, isOpen]);

  // Update date when defaultDate changes
  useEffect(() => {
    if (defaultDate) {
      setForm(prev => ({ ...prev, date: defaultDate }));
    }
  }, [defaultDate]);

  // Load clients
  const loadClients = useCallback(async () => {
    try {
      // Try the my-clients endpoint first (respects visibility)
      const data = await safeFetchJson<ClientOption[]>(`${API_BASE}/settings/my-clients/`);
      if (data && Array.isArray(data) && data.length > 0) {
        setClients(data);
        return;
      }
    } catch {}
    
    // Fallback to other endpoints
    for (const url of [`${API_BASE}/options/clients/`, `${API_BASE}/clients/list/`]) {
      try {
        const data = await safeFetchJson<ClientOption[]>(url);
        if (data && Array.isArray(data) && data.length > 0) {
          setClients(data);
          return;
        }
      } catch {}
    }
  }, []);

  // Load categories
  const loadCategories = useCallback(async () => {
    try {
      const data = await safeFetchJson<{ id: number; name: string }[]>(`${API_BASE}/options/task-types/`);
      if (data && Array.isArray(data) && data.length > 0) {
        setCategories(data.map(t => t.name));
      }
    } catch (err) {
      console.error('Failed to load categories:', err);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadClients();
      loadCategories();
      setError(null);
      setSuccess(false);
    }
  }, [isOpen, loadClients, loadCategories]);

  // Calculate total hours from hours + minutes
  const getTotalHours = () => {
    const h = parseFloat(form.hours) || 0;
    const m = parseFloat(form.minutes) || 0;
    return h + (m / 60);
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);

    const totalHours = getTotalHours();

    if (!form.client_id) {
      setError('Please select a client');
      return;
    }
    if (!form.category) {
      setError('Please select a category');
      return;
    }
    if (totalHours <= 0) {
      setError('Please enter time (hours or minutes)');
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await safeFetchJson(`${API_BASE}/time-entries/manual/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
        
        // Reset form
        setForm({
          client_id: '',
          category: '',
          date: defaultDate || new Date().toISOString().split('T')[0],
          hours: '',
          minutes: '',
          start_time: '09:00',
          notes: '',
        });
        
        // Close after short delay
        setTimeout(() => {
          handleClose();
          setSuccess(false);
          onSuccess?.();
        }, 1500);
      } else {
        throw new Error(response?.error || 'Failed to create time entry');
      }
    } catch (err: any) {
      console.error('Failed to create time entry:', err);
      setError(err?.message || 'Failed to create time entry');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Quick time buttons
  const quickTimes = [
    { label: '15m', hours: 0, minutes: 15 },
    { label: '30m', hours: 0, minutes: 30 },
    { label: '1h', hours: 1, minutes: 0 },
    { label: '1.5h', hours: 1, minutes: 30 },
    { label: '2h', hours: 2, minutes: 0 },
    { label: '4h', hours: 4, minutes: 0 },
  ];

  const setQuickTime = (hours: number, minutes: number) => {
    setForm({ ...form, hours: hours.toString(), minutes: minutes.toString() });
  };

  // Get client name for display
  const selectedClient = clients.find(c => c.id.toString() === form.client_id);

  return (
    <>
      {/* Trigger Button - only show if not externally controlled */}
      {!isControlled && (
        <button
          onClick={handleOpen}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium text-sm shadow-sm"
        >
          <Plus className="w-4 h-4" />
          Add Time Manually
        </button>
      )}

      {/* Modal */}
      {isOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="flex items-center justify-between p-5 border-b border-slate-200">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-primary/10 rounded-xl">
                  <Clock className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h2 className="text-lg font-extrabold text-slate-900">Add Time Manually</h2>
                  {selectedClient && (
                    <p className="text-sm text-primary font-medium">{selectedClient.name}</p>
                  )}
                </div>
              </div>
              <button
                onClick={handleClose}
                className="p-2 hover:bg-slate-100 rounded-xl transition-colors"
              >
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="p-5 space-y-4">
              {/* Success Message */}
              {success && (
                <div className="flex items-center gap-2 p-3 bg-emerald-50 border-2 border-emerald-200 rounded-xl text-emerald-700">
                  <Check className="w-5 h-5" />
                  <span className="font-bold">Time entry added successfully!</span>
                </div>
              )}

              {/* Error Message */}
              {error && (
                <div className="p-3 bg-red-50 border-2 border-red-200 rounded-xl text-red-700 text-sm font-medium">
                  {error}
                </div>
              )}

              {/* Client */}
              <div>
                <label className="block text-sm font-bold text-slate-800 mb-2">
                  Client <span className="text-red-500">*</span>
                </label>
                <select
                  value={form.client_id}
                  onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                  className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all bg-white"
                  required
                >
                  <option value="">Select client...</option>
                  {clients.map(c => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              {/* Category */}
              <div>
                <label className="block text-sm font-bold text-slate-800 mb-2">
                  Category <span className="text-red-500">*</span>
                </label>
                <select
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all bg-white"
                  required
                >
                  <option value="">Select category...</option>
                  {categories.map(cat => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              </div>

              {/* Date */}
              <div>
                <label className="block text-sm font-bold text-slate-800 mb-2">
                  Date <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <input
                    type="date"
                    value={form.date}
                    onChange={(e) => setForm({ ...form, date: e.target.value })}
                    className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                    required
                  />
                </div>
              </div>

              {/* Time Duration */}
              <div>
                <label className="block text-sm font-bold text-slate-800 mb-2">
                  Duration <span className="text-red-500">*</span>
                </label>
                <div className="flex gap-3">
                  <div className="flex-1">
                    <div className="relative">
                      <input
                        type="number"
                        min="0"
                        max="24"
                        step="1"
                        placeholder="0"
                        value={form.hours}
                        onChange={(e) => setForm({ ...form, hours: e.target.value })}
                        className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 pr-12 font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                      />
                      <span className="absolute right-4 top-1/2 -translate-y-1/2 text-sm text-slate-500 font-medium">hrs</span>
                    </div>
                  </div>
                  <div className="flex-1">
                    <div className="relative">
                      <input
                        type="number"
                        min="0"
                        max="59"
                        step="5"
                        placeholder="0"
                        value={form.minutes}
                        onChange={(e) => setForm({ ...form, minutes: e.target.value })}
                        className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 pr-12 font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                      />
                      <span className="absolute right-4 top-1/2 -translate-y-1/2 text-sm text-slate-500 font-medium">min</span>
                    </div>
                  </div>
                </div>

                {/* Quick Time Buttons */}
                <div className="flex flex-wrap gap-2 mt-3">
                  {quickTimes.map(qt => (
                    <button
                      key={qt.label}
                      type="button"
                      onClick={() => setQuickTime(qt.hours, qt.minutes)}
                      className="px-3 py-1.5 text-xs font-bold bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors"
                    >
                      {qt.label}
                    </button>
                  ))}
                </div>

                {/* Total Display */}
                {getTotalHours() > 0 && (
                  <p className="text-sm text-primary font-bold mt-3">
                    Total: {getTotalHours().toFixed(2)} hours
                  </p>
                )}
              </div>

              {/* Start Time (Optional) */}
              <div>
                <label className="block text-sm font-bold text-slate-800 mb-2">
                  Start Time <span className="text-slate-400 text-xs font-medium">(optional)</span>
                </label>
                <input
                  type="time"
                  value={form.start_time}
                  onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                  className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all"
                />
              </div>

              {/* Notes */}
              <div>
                <label className="block text-sm font-bold text-slate-800 mb-2">
                  Notes <span className="text-slate-400 text-xs font-medium">(optional)</span>
                </label>
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  placeholder="What did you work on?"
                  rows={2}
                  className="w-full border-2 border-slate-200 rounded-xl px-4 py-2.5 font-medium focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all resize-none"
                />
              </div>

              {/* Actions */}
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={handleClose}
                  className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || success}
                  className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 transition-all flex items-center justify-center gap-2 shadow-lg shadow-primary/25"
                >
                  {isSubmitting ? (
                    <>
                      <span className="animate-spin">⏳</span>
                      Saving...
                    </>
                  ) : success ? (
                    <>
                      <Check className="w-4 h-4" />
                      Saved!
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      Add Time
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}