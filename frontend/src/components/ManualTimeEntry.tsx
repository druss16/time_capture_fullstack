/**
 * ManualTimeEntry.tsx - Add time entries manually
 * 
 * Allows users to manually log time for:
 * - Client
 * - Category
 * - Date
 * - Duration (hours)
 * - Optional notes
 */

import { useState, useEffect, useCallback } from "react";
import { Plus, Clock, X, Check, Calendar } from "lucide-react";
import { safeFetchJson } from "@/lib/api";

const RAW_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:7123/api";
const API_BASE = RAW_BASE.endsWith("/api") ? RAW_BASE : `${RAW_BASE.replace(/\/+$/, "")}/api`;

type ClientOption = {
  id: number;
  name: string;
};

// Default categories
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
};

export default function ManualTimeEntry({ onSuccess, defaultDate }: ManualTimeEntryProps) {
  const [isOpen, setIsOpen] = useState(false);
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

  // Load clients
  const loadClients = useCallback(async () => {
    try {
      const data = await safeFetchJson<ClientOption[]>(`${API_BASE}/options/clients/`);
      if (data && Array.isArray(data) && data.length > 0) {
        setClients(data);
      }
    } catch (err) {
      console.error('Failed to load clients:', err);
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
          setIsOpen(false);
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

  return (
    <>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(true)}
        className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors font-medium text-sm shadow-sm"
      >
        <Plus className="w-4 h-4" />
        Add Time Manually
      </button>

      {/* Modal */}
      {isOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b">
              <div className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-primary" />
                <h2 className="text-lg font-semibold">Add Time Manually</h2>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="p-4 space-y-4">
              {/* Success Message */}
              {success && (
                <div className="flex items-center gap-2 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700">
                  <Check className="w-5 h-5" />
                  <span className="font-medium">Time entry added successfully!</span>
                </div>
              )}

              {/* Error Message */}
              {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                  {error}
                </div>
              )}

              {/* Client */}
              <div>
                <label className="block text-sm font-medium mb-1.5">
                  Client <span className="text-red-500">*</span>
                </label>
                <select
                  value={form.client_id}
                  onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
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
                <label className="block text-sm font-medium mb-1.5">
                  Category <span className="text-red-500">*</span>
                </label>
                <select
                  value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
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
                <label className="block text-sm font-medium mb-1.5">
                  Date <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <input
                    type="date"
                    value={form.date}
                    onChange={(e) => setForm({ ...form, date: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                    required
                  />
                  <Calendar className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>
              </div>

              {/* Time Duration */}
              <div>
                <label className="block text-sm font-medium mb-1.5">
                  Duration <span className="text-red-500">*</span>
                </label>
                <div className="flex gap-2">
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
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 pr-12 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-gray-500">hrs</span>
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
                        className="w-full border border-gray-300 rounded-lg px-3 py-2 pr-12 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                      />
                      <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-gray-500">min</span>
                    </div>
                  </div>
                </div>

                {/* Quick Time Buttons */}
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {quickTimes.map(qt => (
                    <button
                      key={qt.label}
                      type="button"
                      onClick={() => setQuickTime(qt.hours, qt.minutes)}
                      className="px-2.5 py-1 text-xs font-medium bg-gray-100 hover:bg-gray-200 rounded transition-colors"
                    >
                      {qt.label}
                    </button>
                  ))}
                </div>

                {/* Total Display */}
                {getTotalHours() > 0 && (
                  <p className="text-sm text-primary font-medium mt-2">
                    Total: {getTotalHours().toFixed(2)} hours
                  </p>
                )}
              </div>

              {/* Start Time (Optional) */}
              <div>
                <label className="block text-sm font-medium mb-1.5">
                  Start Time <span className="text-gray-400 text-xs">(optional)</span>
                </label>
                <input
                  type="time"
                  value={form.start_time}
                  onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
                />
              </div>

              {/* Notes */}
              <div>
                <label className="block text-sm font-medium mb-1.5">
                  Notes <span className="text-gray-400 text-xs">(optional)</span>
                </label>
                <textarea
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  placeholder="What did you work on?"
                  rows={2}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary resize-none"
                />
              </div>

              {/* Actions */}
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg font-medium hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || success}
                  className="flex-1 px-4 py-2.5 bg-primary text-white rounded-lg font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
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