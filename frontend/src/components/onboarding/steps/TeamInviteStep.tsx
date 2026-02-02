// src/components/onboarding/steps/TeamInviteStep.tsx

import React, { useState, useRef } from 'react';
import { 
  Users, 
  Plus, 
  Trash2, 
  ArrowRight, 
  Loader2,
  Mail,
  CheckCircle2,
  AlertCircle,
  UserPlus,
  Upload,
  FileSpreadsheet,
  Download,
  Table,
  X
} from 'lucide-react';
import { Organization, inviteTeamMembers } from '../../../services/onboardingApi';

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

interface CSVTeamMember {
  email: string;
  name?: string;
}

// Example CSV data for preview
const EXAMPLE_CSV_DATA = [
  { email: 'john.smith@yourfirm.com', name: 'John Smith' },
  { email: 'sarah.jones@yourfirm.com', name: 'Sarah Jones' },
  { email: 'mike.wilson@yourfirm.com', name: 'Mike Wilson' },
  { email: 'lisa.chen@yourfirm.com', name: 'Lisa Chen' },
];

export default function TeamInviteStep({ organization, onComplete, onSkip }: TeamInviteStepProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  // Manual entry state
  const [emails, setEmails] = useState<string[]>(['']);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<InviteResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  
  // CSV import state
  const [importMode, setImportMode] = useState<'manual' | 'csv'>('manual');
  const [showExample, setShowExample] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<CSVTeamMember[]>([]);
  const [importError, setImportError] = useState<string | null>(null);

  const addEmail = () => {
    setEmails([...emails, '']);
  };

  const removeEmail = (index: number) => {
    if (emails.length > 1) {
      setEmails(emails.filter((_, i) => i !== index));
    }
  };

  const updateEmail = (index: number, value: string) => {
    const newEmails = [...emails];
    newEmails[index] = value;
    setEmails(newEmails);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setImportError(null);
    setCsvFile(file);
    
    // Parse CSV for preview
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      const lines = text.split('\n').filter(line => line.trim());
      
      if (lines.length < 2) {
        setImportError('CSV file must have a header row and at least one data row');
        setCsvFile(null);
        return;
      }
      
      const headers = lines[0].toLowerCase().split(',').map(h => h.trim());
      
      // Flexible column matching
      const emailIdx = headers.findIndex(h => 
        h === 'email' || h === 'email address' || h === 'email_address'
      );
      const nameIdx = headers.findIndex(h => 
        h === 'name' || h === 'full name' || h === 'full_name' || h === 'employee' || h === 'employee name'
      );
      
      if (emailIdx === -1) {
        setImportError('CSV must have an "email" column');
        setCsvFile(null);
        return;
      }
      
      const members: CSVTeamMember[] = [];
      for (let i = 1; i < lines.length; i++) {
        const values = lines[i].split(',').map(v => v.trim().replace(/^["']|["']$/g, ''));
        const email = values[emailIdx];
        if (email && email.includes('@')) {
          members.push({
            email: email,
            name: nameIdx !== -1 ? values[nameIdx] : undefined,
          });
        }
      }
      
      if (members.length === 0) {
        setImportError('No valid email addresses found in CSV');
        setCsvFile(null);
        return;
      }
      
      setCsvPreview(members);
    };
    reader.readAsText(file);
  };

  const handleClearFile = () => {
    setCsvFile(null);
    setCsvPreview([]);
    setImportError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleDownloadTemplate = () => {
    const csvContent = `email,name
john.smith@yourfirm.com,John Smith
sarah.jones@yourfirm.com,Sarah Jones
mike.wilson@yourfirm.com,Mike Wilson
lisa.chen@yourfirm.com,Lisa Chen`;
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'team-import-template.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  };

  const handleInvite = async () => {
    let emailsToInvite: string[] = [];
    
    if (importMode === 'csv' && csvPreview.length > 0) {
      emailsToInvite = csvPreview.map(m => m.email);
    } else {
      emailsToInvite = emails.filter(e => e.trim() && e.includes('@'));
    }
    
    if (emailsToInvite.length === 0) {
      setError('Please enter at least one valid email address');
      return;
    }

    setLoading(true);
    setError(null);
    setResults([]);

    try {
      const response = await inviteTeamMembers(emailsToInvite);
      setResults(response.results || []);
      
      if (response.invited > 0) {
        // Show success briefly then move on
        setTimeout(() => onComplete(), 1500);
      }
    } catch (err: any) {
      setError(err.message || err.error || 'Failed to send invitations');
    } finally {
      setLoading(false);
    }
  };

  const successCount = results.filter(r => r.success).length;
  const failCount = results.filter(r => !r.success).length;

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-teal-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Users className="w-8 h-8 text-teal-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Invite Your Team</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Add team members who will track time in {organization?.name || 'your firm'}
        </p>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-red-700 font-medium">{error}</p>
        </div>
      )}

      {successCount > 0 && (
        <div className="mb-6 p-4 bg-teal-50 border-2 border-teal-200 rounded-xl flex items-start gap-3">
          <CheckCircle2 className="w-5 h-5 text-teal-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-teal-700 font-bold">
              Successfully invited {successCount} team member{successCount > 1 ? 's' : ''}!
            </p>
            {failCount > 0 && (
              <p className="text-teal-600 text-sm font-medium mt-1">
                {failCount} invitation{failCount > 1 ? 's' : ''} failed - check email addresses
              </p>
            )}
          </div>
        </div>
      )}

      {/* Import Mode Toggle */}
      {!csvFile && successCount === 0 && (
        <div className="flex gap-2 mb-6 p-1 bg-slate-100 rounded-xl">
          <button
            onClick={() => setImportMode('manual')}
            className={`flex-1 py-2.5 px-4 rounded-lg font-semibold text-sm transition-all flex items-center justify-center gap-2
              ${importMode === 'manual' 
                ? 'bg-white text-slate-900 shadow-sm' 
                : 'text-slate-500 hover:text-slate-700'}`}
          >
            <Mail className="w-4 h-4" />
            Add Manually
          </button>
          <button
            onClick={() => setImportMode('csv')}
            className={`flex-1 py-2.5 px-4 rounded-lg font-semibold text-sm transition-all flex items-center justify-center gap-2
              ${importMode === 'csv' 
                ? 'bg-white text-slate-900 shadow-sm' 
                : 'text-slate-500 hover:text-slate-700'}`}
          >
            <FileSpreadsheet className="w-4 h-4" />
            Bulk Import CSV
          </button>
        </div>
      )}

      {/* Manual Entry Mode */}
      {importMode === 'manual' && !csvFile && successCount === 0 && (
        <>
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
                    className="w-full pl-10 pr-4 py-3 border-2 border-slate-200 rounded-xl font-medium transition-all focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 focus:outline-none"
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
            className="w-full py-3 border-2 border-dashed border-slate-300 hover:border-teal-400 text-slate-600 hover:text-teal-600 font-semibold rounded-xl transition-all flex items-center justify-center gap-2 mb-6 hover:bg-teal-50"
          >
            <Plus className="w-5 h-5" />
            Add Another Email
          </button>
        </>
      )}

      {/* CSV Import Mode */}
      {importMode === 'csv' && !csvFile && successCount === 0 && (
        <>
          {/* Upload Area */}
          <div className="border-2 border-dashed border-teal-300 bg-teal-50 rounded-xl p-6 mb-4">
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={handleFileSelect}
              className="hidden"
              id="team-csv-upload"
            />
            <label
              htmlFor="team-csv-upload"
              className="cursor-pointer flex flex-col items-center gap-3"
            >
              <div className="w-14 h-14 bg-teal-100 rounded-xl flex items-center justify-center">
                <Upload className="w-7 h-7 text-teal-600" />
              </div>
              <div className="text-center">
                <p className="font-bold text-slate-900">Click to upload CSV</p>
                <p className="text-sm text-slate-600 mt-1 font-medium">
                  or drag and drop your file here
                </p>
              </div>
            </label>
          </div>

          {/* Template Download & Example Toggle */}
          <div className="flex items-center justify-center gap-4 mb-6">
            <button
              onClick={handleDownloadTemplate}
              className="flex items-center gap-2 text-teal-600 hover:text-teal-700 font-semibold text-sm transition-colors"
            >
              <Download className="w-4 h-4" />
              Download Template
            </button>
            <span className="text-slate-300">|</span>
            <button
              onClick={() => setShowExample(!showExample)}
              className="flex items-center gap-2 text-teal-600 hover:text-teal-700 font-semibold text-sm transition-colors"
            >
              <Table className="w-4 h-4" />
              {showExample ? 'Hide Example' : 'View Example Format'}
            </button>
          </div>

          {/* Example Format */}
          {showExample && (
            <div className="border-2 border-slate-200 rounded-xl overflow-hidden mb-6">
              <div className="bg-slate-50 px-4 py-3 border-b-2 border-slate-200">
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className="w-5 h-5 text-slate-500" />
                  <span className="font-bold text-slate-700">Example CSV Format</span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-100">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-bold text-slate-700 border-b-2 border-slate-200">
                        email <span className="text-red-500">*</span>
                      </th>
                      <th className="text-left px-4 py-2.5 font-bold text-slate-700 border-b-2 border-slate-200">
                        name <span className="text-slate-400 font-normal">(optional)</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {EXAMPLE_CSV_DATA.map((row, idx) => (
                      <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                        <td className="px-4 py-2.5 text-slate-900 font-medium">{row.email}</td>
                        <td className="px-4 py-2.5 text-slate-600">{row.name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3 bg-amber-50 border-t-2 border-amber-200">
                <p className="text-sm text-amber-800 font-medium">
                  <strong>Note:</strong> The "email" column is required. Names are optional but helpful for identifying team members.
                </p>
              </div>
            </div>
          )}

          {importError && (
            <div className="mb-6 p-4 bg-red-50 border-2 border-red-200 rounded-xl flex items-center gap-2 text-red-700">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm font-medium">{importError}</span>
            </div>
          )}
        </>
      )}

      {/* CSV Preview */}
      {csvFile && successCount === 0 && (
        <div className="border-2 border-slate-200 rounded-xl overflow-hidden mb-6">
          <div className="bg-slate-50 px-4 py-3 flex items-center justify-between border-b-2 border-slate-200">
            <div className="flex items-center gap-2">
              <FileSpreadsheet className="w-5 h-5 text-teal-600" />
              <span className="font-bold text-slate-900">{csvFile.name}</span>
              <span className="text-sm text-slate-500 font-medium">
                ({csvPreview.length} team member{csvPreview.length !== 1 ? 's' : ''})
              </span>
            </div>
            <button
              onClick={handleClearFile}
              className="p-1.5 hover:bg-slate-200 rounded-lg transition-colors"
            >
              <X className="w-4 h-4 text-slate-500" />
            </button>
          </div>
          
          {/* Preview Table */}
          <div className="max-h-48 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 sticky top-0">
                <tr>
                  <th className="text-left px-4 py-2 font-bold text-slate-700">Email</th>
                  <th className="text-left px-4 py-2 font-bold text-slate-700">Name</th>
                </tr>
              </thead>
              <tbody>
                {csvPreview.map((member, idx) => (
                  <tr key={idx} className="border-t border-slate-100">
                    <td className="px-4 py-2 text-slate-900 font-medium">{member.email}</td>
                    <td className="px-4 py-2 text-slate-500">{member.name || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Info Box */}
      {successCount === 0 && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
          <div className="flex items-start gap-3">
            <UserPlus className="w-5 h-5 text-slate-400 mt-0.5" />
            <div>
              <p className="text-sm text-slate-600 font-medium">
                <strong className="text-slate-800">What happens next?</strong> Each team member will receive an email with login credentials. They can download the desktop app and start tracking time immediately.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      {successCount === 0 && (
        <div className="flex gap-3">
          <button
            onClick={handleInvite}
            disabled={loading || (importMode === 'csv' && !csvFile)}
            className="flex-1 py-3.5 px-4 bg-teal-500 hover:bg-teal-600 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 shadow-lg shadow-teal-500/25"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Sending Invites...
              </>
            ) : (
              <>
                {importMode === 'csv' && csvFile ? (
                  <>Send {csvPreview.length} Invitation{csvPreview.length !== 1 ? 's' : ''}</>
                ) : (
                  <>Send Invitations</>
                )}
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
      )}

      <p className="mt-4 text-center text-sm text-slate-500 font-medium">
        You can always invite more team members later from Settings → Team
      </p>
    </div>
  );
}