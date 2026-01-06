// src/components/onboarding/steps/TeamInviteStep.tsx

import React, { useState } from 'react';
import { 
  Users, 
  Plus, 
  Trash2, 
  ArrowRight, 
  Loader2,
  Mail,
  CheckCircle2,
  AlertCircle,
  Upload
} from 'lucide-react';
import { Organization, inviteTeamMembers, importClientsCSV } from '../../../services/onboardingApi';

interface TeamInviteStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
}

interface InviteResult {
  email: string;
  success: boolean;
  error?: string;
}

export default function TeamInviteStep({ organization, onComplete, onSkip }: TeamInviteStepProps) {
  const [emails, setEmails] = useState<string[]>(['']);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<InviteResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  
  // CSV Import
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ clients: number; skipped: number } | null>(null);

  const addEmail = () => {
    setEmails([...emails, '']);
  };

  const removeEmail = (index: number) => {
    setEmails(emails.filter((_, i) => i !== index));
  };

  const updateEmail = (index: number, value: string) => {
    const newEmails = [...emails];
    newEmails[index] = value;
    setEmails(newEmails);
  };

  const handleInvite = async () => {
    const validEmails = emails.filter(e => e.trim() && e.includes('@'));
    
    if (validEmails.length === 0) {
      setError('Please enter at least one valid email address');
      return;
    }

    setLoading(true);
    setError(null);
    setResults([]);

    try {
      const response = await inviteTeamMembers(validEmails);
      setResults(response.results || []);
      
      if (response.invited > 0) {
        setTimeout(() => onComplete(), 1500);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to send invitations');
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setImporting(true);
    setImportResult(null);

    try {
      const result = await importClientsCSV(file);
      setImportResult({ clients: result.clients, skipped: result.skipped });
    } catch (err: any) {
      setError(err.message || 'Failed to import CSV');
    } finally {
      setImporting(false);
    }
  };

  const successCount = results.filter(r => r.success).length;

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Users className="w-8 h-8 text-emerald-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Invite Your Team</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Add team members who will track time
        </p>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
          <p className="text-red-700 font-medium">{error}</p>
        </div>
      )}

      {successCount > 0 && (
        <div className="mb-6 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-emerald-500 mt-0.5" />
          <p className="text-emerald-700 font-medium">
            Successfully invited {successCount} team member{successCount > 1 ? 's' : ''}!
          </p>
        </div>
      )}

      {/* Email Inputs */}
      <div className="space-y-3 mb-6">
        {emails.map((email, index) => (
          <div key={index} className="flex gap-2">
            <div className="flex-1 relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400" />
              <input
                type="email"
                value={email}
                onChange={(e) => updateEmail(index, e.target.value)}
                placeholder="colleague@yourfirm.com"
                className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 focus:outline-none"
              />
            </div>
            {emails.length > 1 && (
              <button
                onClick={() => removeEmail(index)}
                className="p-3 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-xl transition-all"
              >
                <Trash2 className="w-5 h-5" />
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Add More Button */}
      <button
        onClick={addEmail}
        className="w-full py-3 border-2 border-dashed border-slate-300 hover:border-emerald-400 text-slate-600 hover:text-emerald-600 font-semibold rounded-xl transition-all flex items-center justify-center gap-2 mb-6 hover:bg-emerald-50"
      >
        <Plus className="w-5 h-5" />
        Add Another Email
      </button>

      {/* CSV Import Section */}
      <div className="mb-8 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
        <h3 className="font-bold text-slate-900 mb-2">Import Clients from CSV</h3>
        <p className="text-sm text-slate-600 font-medium mb-3">
          Upload a CSV with columns: name, code, project (optional)
        </p>
        
        <label className="flex items-center justify-center gap-2 px-4 py-3 border-2 border-slate-300 hover:border-emerald-400 rounded-xl cursor-pointer transition-all hover:bg-emerald-50 group">
          {importing ? (
            <Loader2 className="w-5 h-5 animate-spin text-emerald-600" />
          ) : (
            <Upload className="w-5 h-5 text-slate-500 group-hover:text-emerald-600" />
          )}
          <span className="font-semibold text-slate-700 group-hover:text-emerald-700">
            {importing ? 'Importing...' : 'Upload CSV'}
          </span>
          <input
            type="file"
            accept=".csv"
            onChange={handleFileUpload}
            className="hidden"
          />
        </label>
        
        {importResult && (
          <p className="mt-3 text-sm text-emerald-700 font-medium">
            ✓ Imported {importResult.clients} clients ({importResult.skipped} skipped)
          </p>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={handleInvite}
          disabled={loading}
          className="flex-1 py-3.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 shadow-lg shadow-emerald-600/25"
        >
          {loading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Sending Invites...
            </>
          ) : (
            <>
              Send Invitations
              <ArrowRight className="w-5 h-5" />
            </>
          )}
        </button>
        
        <button
          onClick={onSkip}
          className="px-6 py-3.5 border-2 border-slate-200 hover:border-slate-300 text-slate-700 font-bold rounded-xl transition-all hover:bg-slate-50"
        >
          Skip for now
        </button>
      </div>

      <p className="mt-4 text-center text-sm text-slate-500 font-medium">
        You can always invite more team members later from Settings
      </p>
    </div>
  );
}