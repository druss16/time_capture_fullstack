// src/components/ClientImportWizard.tsx

import { useState } from 'react';
import {
  Upload,
  Users,
  Briefcase,
  Check,
  ChevronRight,
  ChevronLeft,
  AlertCircle,
  Download,
  Loader2,
  X,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

interface Props {
  onClose: () => void;
  onSuccess: () => void;
  users: Array<{ id: number; email: string; first_name: string; last_name: string; username: string }>;
}

type Step = 'import' | 'visibility' | 'assign' | 'done';

export default function ClientImportWizard({ onClose, onSuccess, users }: Props) {
  const [step, setStep] = useState<Step>('import');
  const [csvContent, setCsvContent] = useState('');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<any>(null);
  const [defaultVisibility, setDefaultVisibility] = useState<'all' | 'assigned'>('all');
  const [assignmentCsv, setAssignmentCsv] = useState('');
  const [assignResult, setAssignResult] = useState<any>(null);

  const downloadClientTemplate = () => {
    const template = 'name,code\nAcme Corporation,ACME\nBigCo Industries,BIGCO\nSmith Family Trust,SMITH';
    const blob = new Blob([template], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'client_import_template.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAssignmentTemplate = () => {
    // Pre-fill with actual user emails and client codes
    const template = 'email,client_code\njohn@yourfirm.com,ACME\njane@yourfirm.com,BIGCO';
    const blob = new Blob([template], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'client_assignments_template.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImportClients = async () => {
    if (!csvContent.trim()) return;
    
    setImporting(true);
    try {
      // Parse CSV and create clients
      const lines = csvContent.trim().split('\n');
      const header = lines[0].toLowerCase();
      const hasHeader = header.includes('name') || header.includes('client');
      
      const dataLines = hasHeader ? lines.slice(1) : lines;
      
      let created = 0;
      let errors: string[] = [];
      
      for (let i = 0; i < dataLines.length; i++) {
        const line = dataLines[i].trim();
        if (!line) continue;
        
        // Simple CSV parsing (handles basic cases)
        const parts = line.split(',').map(p => p.trim().replace(/^["']|["']$/g, ''));
        const name = parts[0];
        const code = parts[1] || name.substring(0, 4).toUpperCase().replace(/\s/g, '');
        
        if (!name) {
          errors.push(`Row ${i + 2}: Missing name`);
          continue;
        }
        
        try {
          await safeFetchJson(`${API_BASE}/settings/clients/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
              name, 
              code,
              visibility: defaultVisibility 
            }),
          });
          created++;
        } catch (err: any) {
          if (err.message?.includes('already exists')) {
            errors.push(`Row ${i + 2}: "${name}" already exists`);
          } else {
            errors.push(`Row ${i + 2}: ${err.message || 'Failed'}`);
          }
        }
      }
      
      setImportResult({ created, errors, total: dataLines.length });
      
      if (created > 0) {
        // Move to next step
        if (defaultVisibility === 'assigned') {
          setStep('assign');
        } else {
          setStep('done');
        }
      }
    } catch (err: any) {
      setImportResult({ error: err.message });
    } finally {
      setImporting(false);
    }
  };

  const handleImportAssignments = async () => {
    if (!assignmentCsv.trim()) {
      setStep('done');
      return;
    }
    
    setImporting(true);
    try {
      const data = await safeFetchJson(`${API_BASE}/settings/client-assignments/import/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_content: assignmentCsv }),
      });
      
      setAssignResult(data);
      setStep('done');
    } catch (err: any) {
      setAssignResult({ error: err.message });
    } finally {
      setImporting(false);
    }
  };

  const getUserDisplayName = (u: any) => {
    const name = `${u.first_name || ''} ${u.last_name || ''}`.trim();
    return name || u.username || u.email;
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-extrabold text-slate-900">Import Clients</h2>
            <p className="text-sm text-slate-500 font-medium">
              {step === 'import' && 'Step 1: Paste your client list'}
              {step === 'visibility' && 'Step 2: Set default visibility'}
              {step === 'assign' && 'Step 3: Assign users to clients'}
              {step === 'done' && 'All done!'}
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Progress */}
        <div className="flex items-center gap-2 mb-6">
          {['import', 'visibility', 'assign', 'done'].map((s, i) => (
            <div key={s} className="flex items-center">
              <div className={cn(
                'w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold',
                step === s ? 'bg-primary text-white' :
                ['import', 'visibility', 'assign', 'done'].indexOf(step) > i 
                  ? 'bg-emerald-500 text-white' 
                  : 'bg-slate-200 text-slate-500'
              )}>
                {['import', 'visibility', 'assign', 'done'].indexOf(step) > i ? (
                  <Check className="w-4 h-4" />
                ) : (
                  i + 1
                )}
              </div>
              {i < 3 && <div className="w-8 h-0.5 bg-slate-200 mx-1" />}
            </div>
          ))}
        </div>

        {/* Step 1: Import Clients */}
        {step === 'import' && (
          <div>
            <div className="mb-4 p-4 bg-slate-50 rounded-xl">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-bold text-slate-700">Expected format:</p>
                <button
                  onClick={downloadClientTemplate}
                  className="text-xs text-primary font-bold hover:underline flex items-center gap-1"
                >
                  <Download className="w-3 h-3" />
                  Download Template
                </button>
              </div>
              <code className="text-xs text-slate-600 bg-slate-200 px-2 py-1 rounded block font-mono">
                name,code<br/>
                Acme Corporation,ACME<br/>
                BigCo Industries,BIGCO
              </code>
              <p className="text-xs text-slate-500 mt-2">
                💡 Tip: Copy directly from Excel — just select name and code columns
              </p>
            </div>

            <textarea
              value={csvContent}
              onChange={(e) => setCsvContent(e.target.value)}
              placeholder="Paste your client list here..."
              rows={10}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
            />

            {importResult?.errors?.length > 0 && (
              <div className="mt-4 p-3 bg-amber-50 border-2 border-amber-200 rounded-xl">
                <p className="text-sm font-bold text-amber-800 mb-1">
                  ✓ Created {importResult.created} clients
                </p>
                <div className="max-h-24 overflow-y-auto">
                  {importResult.errors.slice(0, 5).map((err: string, i: number) => (
                    <p key={i} className="text-xs text-amber-700">{err}</p>
                  ))}
                </div>
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button
                onClick={onClose}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                onClick={() => setStep('visibility')}
                disabled={!csvContent.trim()}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Set Default Visibility */}
        {step === 'visibility' && (
          <div>
            <p className="text-slate-600 font-medium mb-4">
              Who should be able to see these clients by default?
            </p>

            <div className="space-y-3">
              <label 
                className={cn(
                  'block p-4 border-2 rounded-xl cursor-pointer transition-all',
                  defaultVisibility === 'all' 
                    ? 'border-primary bg-primary/5' 
                    : 'border-slate-200 hover:border-slate-300'
                )}
              >
                <input
                  type="radio"
                  name="visibility"
                  value="all"
                  checked={defaultVisibility === 'all'}
                  onChange={() => setDefaultVisibility('all')}
                  className="sr-only"
                />
                <div className="flex items-start gap-3">
                  <div className={cn(
                    'w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5',
                    defaultVisibility === 'all' ? 'border-primary' : 'border-slate-300'
                  )}>
                    {defaultVisibility === 'all' && (
                      <div className="w-2.5 h-2.5 rounded-full bg-primary" />
                    )}
                  </div>
                  <div>
                    <p className="font-bold text-slate-900">👥 All Team Members</p>
                    <p className="text-sm text-slate-500 font-medium">
                      Everyone in your firm can see all clients. Best for small teams (under 20 people).
                    </p>
                  </div>
                </div>
              </label>

              <label 
                className={cn(
                  'block p-4 border-2 rounded-xl cursor-pointer transition-all',
                  defaultVisibility === 'assigned' 
                    ? 'border-primary bg-primary/5' 
                    : 'border-slate-200 hover:border-slate-300'
                )}
              >
                <input
                  type="radio"
                  name="visibility"
                  value="assigned"
                  checked={defaultVisibility === 'assigned'}
                  onChange={() => setDefaultVisibility('assigned')}
                  className="sr-only"
                />
                <div className="flex items-start gap-3">
                  <div className={cn(
                    'w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5',
                    defaultVisibility === 'assigned' ? 'border-primary' : 'border-slate-300'
                  )}>
                    {defaultVisibility === 'assigned' && (
                      <div className="w-2.5 h-2.5 rounded-full bg-primary" />
                    )}
                  </div>
                  <div>
                    <p className="font-bold text-slate-900">🔒 Assigned Users Only</p>
                    <p className="text-sm text-slate-500 font-medium">
                      Only assigned team members can see each client. Best for larger firms or confidential engagements.
                    </p>
                    <p className="text-xs text-amber-600 font-medium mt-1">
                      ⚠️ You'll need to assign users to clients in the next step
                    </p>
                  </div>
                </div>
              </label>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setStep('import')}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 flex items-center justify-center gap-2"
              >
                <ChevronLeft className="w-4 h-4" />
                Back
              </button>
              <button
                onClick={handleImportClients}
                disabled={importing}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25"
              >
                {importing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <>
                    Import Clients
                    <ChevronRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Assign Users (only if visibility = assigned) */}
        {step === 'assign' && (
          <div>
            <div className="mb-4 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
              <p className="font-bold text-emerald-800">
                ✓ Imported {importResult?.created || 0} clients
              </p>
            </div>

            <p className="text-slate-600 font-medium mb-4">
              Now assign team members to clients. You can skip this and do it later in Settings → Client Access.
            </p>

            <div className="mb-4 p-4 bg-slate-50 rounded-xl">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-bold text-slate-700">Assignment format:</p>
                <button
                  onClick={downloadAssignmentTemplate}
                  className="text-xs text-primary font-bold hover:underline flex items-center gap-1"
                >
                  <Download className="w-3 h-3" />
                  Download Template
                </button>
              </div>
              <code className="text-xs text-slate-600 bg-slate-200 px-2 py-1 rounded block font-mono">
                email,client_code<br/>
                john@yourfirm.com,ACME<br/>
                jane@yourfirm.com,BIGCO
              </code>
            </div>

            <textarea
              value={assignmentCsv}
              onChange={(e) => setAssignmentCsv(e.target.value)}
              placeholder="Paste assignments here (or skip this step)..."
              rows={8}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
            />

            {assignResult && (
              <div className={cn(
                'mt-4 p-3 rounded-xl',
                assignResult.error ? 'bg-red-50 border-2 border-red-200' : 'bg-emerald-50 border-2 border-emerald-200'
              )}>
                {assignResult.error ? (
                  <p className="text-sm text-red-700 font-medium">{assignResult.error}</p>
                ) : (
                  <p className="text-sm font-bold text-emerald-800">
                    ✓ Created {assignResult.created} assignments
                    {assignResult.skipped_duplicates > 0 && ` (${assignResult.skipped_duplicates} skipped)`}
                  </p>
                )}
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setStep('done'); }}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100"
              >
                Skip for Now
              </button>
              <button
                onClick={handleImportAssignments}
                disabled={importing || !assignmentCsv.trim()}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25"
              >
                {importing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <>
                    Import Assignments
                    <ChevronRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Done */}
        {step === 'done' && (
          <div className="text-center py-8">
            <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <Check className="w-8 h-8 text-emerald-600" />
            </div>
            <h3 className="text-xl font-extrabold text-slate-900 mb-2">All Done!</h3>
            <p className="text-slate-600 font-medium mb-6">
              {importResult?.created || 0} clients imported
              {assignResult?.created ? ` and ${assignResult.created} assignments created` : ''}.
            </p>
            
            <div className="flex gap-3 justify-center">
              <button
                onClick={() => { onSuccess(); onClose(); }}
                className="px-6 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 shadow-lg shadow-primary/25"
              >
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}