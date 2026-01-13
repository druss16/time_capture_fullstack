// src/components/ClientImportWizard.tsx

import { useState, useRef } from 'react';
import {
  Upload,
  Check,
  ChevronRight,
  ChevronLeft,
  AlertCircle,
  Download,
  Loader2,
  X,
  FileSpreadsheet,
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
  
  // Drag & drop states
  const [dragActiveClient, setDragActiveClient] = useState(false);
  const [dragActiveAssign, setDragActiveAssign] = useState(false);
  
  // File input refs
  const clientFileInputRef = useRef<HTMLInputElement>(null);
  const assignFileInputRef = useRef<HTMLInputElement>(null);

  // ============================================================================
  // Template Downloads
  // ============================================================================
  
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
    // Build template with actual user emails if available
    let template = 'email,client_code\n';
    if (users.length > 0) {
      const sampleEmail = users[0].email || 'user@yourfirm.com';
      template += `${sampleEmail},ACME\n${sampleEmail},BIGCO`;
    } else {
      template += 'john@yourfirm.com,ACME\njane@yourfirm.com,BIGCO';
    }
    
    const blob = new Blob([template], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'client_assignments_template.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  // ============================================================================
  // File Handling
  // ============================================================================
  
  const handleFileRead = (file: File, setContent: (content: string) => void, setError?: (err: any) => void) => {
    if (!file) return;
    
    const validTypes = ['.csv', '.txt', 'text/csv', 'text/plain', 'application/vnd.ms-excel'];
    const isValid = validTypes.some(type => 
      file.name.toLowerCase().endsWith(type) || file.type.includes(type.replace('.', ''))
    );
    
    if (!isValid && setError) {
      setError({ error: 'Please upload a CSV or text file' });
      return;
    }
    
    const reader = new FileReader();
    reader.onload = (e) => {
      const content = e.target?.result as string;
      setContent(content);
    };
    reader.onerror = () => {
      if (setError) setError({ error: 'Failed to read file' });
    };
    reader.readAsText(file);
  };

  const handleDragClient = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActiveClient(true);
    } else if (e.type === 'dragleave') {
      setDragActiveClient(false);
    }
  };

  const handleDropClient = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActiveClient(false);
    if (e.dataTransfer.files?.[0]) {
      handleFileRead(e.dataTransfer.files[0], setCsvContent);
    }
  };

  const handleDragAssign = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActiveAssign(true);
    } else if (e.type === 'dragleave') {
      setDragActiveAssign(false);
    }
  };

  const handleDropAssign = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActiveAssign(false);
    if (e.dataTransfer.files?.[0]) {
      handleFileRead(e.dataTransfer.files[0], setAssignmentCsv, setAssignResult);
    }
  };

  // ============================================================================
  // Import Handlers
  // ============================================================================
  
  const handleImportClients = async () => {
    if (!csvContent.trim()) return;
    
    setImporting(true);
    setImportResult(null);
    
    try {
      const lines = csvContent.trim().split('\n');
      const firstLine = lines[0].toLowerCase();
      const knownHeaders = ['name', 'client', 'code', 'client_name', 'client_code'];
      const hasHeader = knownHeaders.some(h => firstLine.includes(h));
      
      const dataLines = hasHeader ? lines.slice(1) : lines;
      
      let created = 0;
      let skipped = 0;
      let errors: string[] = [];
      
      for (let i = 0; i < dataLines.length; i++) {
        const line = dataLines[i].trim();
        if (!line) continue;
        
        // Parse CSV line (handles basic cases and quoted values)
        const parts = line.match(/(?:^|,)("(?:[^"]*(?:""[^"]*)*)"|[^,]*)/g)?.map(p => 
          p.replace(/^,/, '').replace(/^"|"$/g, '').replace(/""/g, '"').trim()
        ) || line.split(',').map(p => p.trim());
        
        const name = parts[0];
        const code = parts[1] || name?.substring(0, 4).toUpperCase().replace(/\s/g, '');
        
        if (!name) {
          errors.push(`Row ${i + (hasHeader ? 2 : 1)}: Missing name`);
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
          if (err.message?.includes('already exists') || err.message?.includes('duplicate')) {
            skipped++;
          } else {
            errors.push(`Row ${i + (hasHeader ? 2 : 1)}: ${err.message || 'Failed'}`);
          }
        }
      }
      
      setImportResult({ created, skipped, errors, total: dataLines.length });
      
      if (created > 0 || skipped > 0) {
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
    setAssignResult(null);
    
    try {
      const response = await fetch(`${API_BASE}/settings/client-assignments/import/`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('auth_token')}`,
        },
        body: JSON.stringify({ csv_content: assignmentCsv }),
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        setAssignResult({ 
          error: data.error || `Server error: ${response.status}`,
          message: data.message,
        });
        return;
      }
      
      setAssignResult(data);
      
      if (data.created > 0 || data.skipped_duplicates >= 0) {
        setStep('done');
      }
    } catch (err: any) {
      setAssignResult({ error: err.message || 'Network error' });
    } finally {
      setImporting(false);
    }
  };

  // ============================================================================
  // Render
  // ============================================================================
  
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-extrabold text-slate-900">Import Clients</h2>
            <p className="text-sm text-slate-500 font-medium">
              {step === 'import' && 'Step 1: Upload or paste your client list'}
              {step === 'visibility' && 'Step 2: Set default visibility'}
              {step === 'assign' && 'Step 3: Assign users to clients (optional)'}
              {step === 'done' && 'All done!'}
            </p>
          </div>
          <button 
            onClick={onClose} 
            className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Progress Steps */}
        <div className="flex items-center gap-2 mb-6">
          {(['import', 'visibility', 'assign', 'done'] as Step[]).map((s, i) => {
            const stepIndex = ['import', 'visibility', 'assign', 'done'].indexOf(step);
            const isComplete = stepIndex > i;
            const isCurrent = step === s;
            
            return (
              <div key={s} className="flex items-center">
                <div className={cn(
                  'w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-colors',
                  isCurrent ? 'bg-primary text-white' :
                  isComplete ? 'bg-emerald-500 text-white' : 
                  'bg-slate-200 text-slate-500'
                )}>
                  {isComplete ? <Check className="w-4 h-4" /> : i + 1}
                </div>
                {i < 3 && (
                  <div className={cn(
                    'w-8 h-0.5 mx-1',
                    isComplete ? 'bg-emerald-500' : 'bg-slate-200'
                  )} />
                )}
              </div>
            );
          })}
        </div>

        {/* ================================================================== */}
        {/* Step 1: Import Clients                                            */}
        {/* ================================================================== */}
        {step === 'import' && (
          <div>
            {/* File Upload Zone */}
            <div
              className={cn(
                'border-2 border-dashed rounded-xl p-8 text-center mb-4 transition-all',
                dragActiveClient 
                  ? 'border-primary bg-primary/5' 
                  : 'border-slate-300 hover:border-slate-400'
              )}
              onDragEnter={handleDragClient}
              onDragLeave={handleDragClient}
              onDragOver={handleDragClient}
              onDrop={handleDropClient}
            >
              <input
                ref={clientFileInputRef}
                type="file"
                accept=".csv,.txt,text/csv,text/plain"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files?.[0]) {
                    handleFileRead(e.target.files[0], setCsvContent);
                  }
                }}
              />
              
              <FileSpreadsheet className="w-12 h-12 text-slate-400 mx-auto mb-3" />
              <p className="font-bold text-slate-700 mb-1">
                Drag & drop CSV file here
              </p>
              <p className="text-sm text-slate-500 mb-3">
                or{' '}
                <button
                  onClick={() => clientFileInputRef.current?.click()}
                  className="text-primary font-bold hover:underline"
                >
                  browse files
                </button>
              </p>
              <p className="text-xs text-slate-400">
                Supports .csv and .txt files
              </p>
            </div>

            {/* Divider */}
            <div className="flex items-center gap-4 mb-4">
              <div className="flex-1 h-px bg-slate-200" />
              <span className="text-sm font-bold text-slate-400">OR</span>
              <div className="flex-1 h-px bg-slate-200" />
            </div>

            {/* Format Example & Template */}
            <div className="mb-4 p-4 bg-slate-50 rounded-xl">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-bold text-slate-700">Paste from Excel</p>
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
                💡 Header row is optional. Just copy your client names from Excel!
              </p>
            </div>

            {/* Paste Area */}
            <textarea
              value={csvContent}
              onChange={(e) => setCsvContent(e.target.value)}
              placeholder="Paste your client list here..."
              rows={8}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
            />

            {/* Show file loaded indicator */}
            {csvContent && (
              <div className="mt-2 flex items-center gap-2 text-sm text-emerald-600 font-medium">
                <Check className="w-4 h-4" />
                {csvContent.split('\n').filter(l => l.trim()).length} rows loaded
              </div>
            )}

            {/* Error display */}
            {importResult?.error && (
              <div className="mt-4 p-3 bg-red-50 border-2 border-red-200 rounded-xl">
                <p className="text-sm text-red-700 font-medium flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" />
                  {importResult.error}
                </p>
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button
                onClick={onClose}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => setStep('visibility')}
                disabled={!csvContent.trim()}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25 transition-all"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* ================================================================== */}
        {/* Step 2: Set Default Visibility                                    */}
        {/* ================================================================== */}
        {step === 'visibility' && (
          <div>
            <p className="text-slate-600 font-medium mb-4">
              Who should be able to see these clients by default?
            </p>

            <div className="space-y-3">
              {/* All Team Members Option */}
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
                    'w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5 flex-shrink-0',
                    defaultVisibility === 'all' ? 'border-primary' : 'border-slate-300'
                  )}>
                    {defaultVisibility === 'all' && (
                      <div className="w-2.5 h-2.5 rounded-full bg-primary" />
                    )}
                  </div>
                  <div>
                    <p className="font-bold text-slate-900">👥 All Team Members</p>
                    <p className="text-sm text-slate-500 font-medium mt-1">
                      Everyone in your firm can see all clients. Best for small teams.
                    </p>
                    <span className="inline-block mt-2 px-2 py-0.5 bg-emerald-100 text-emerald-700 text-xs font-bold rounded-full">
                      Recommended for most firms
                    </span>
                  </div>
                </div>
              </label>

              {/* Assigned Only Option */}
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
                    'w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5 flex-shrink-0',
                    defaultVisibility === 'assigned' ? 'border-primary' : 'border-slate-300'
                  )}>
                    {defaultVisibility === 'assigned' && (
                      <div className="w-2.5 h-2.5 rounded-full bg-primary" />
                    )}
                  </div>
                  <div>
                    <p className="font-bold text-slate-900">🔒 Assigned Users Only</p>
                    <p className="text-sm text-slate-500 font-medium mt-1">
                      Only assigned team members can see each client. Best for larger firms or confidential engagements.
                    </p>
                    <p className="text-xs text-amber-600 font-medium mt-2">
                      ⚠️ You'll need to assign users to clients in the next step
                    </p>
                  </div>
                </div>
              </label>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setStep('import')}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 flex items-center justify-center gap-2 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                Back
              </button>
              <button
                onClick={handleImportClients}
                disabled={importing}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25 transition-all"
              >
                {importing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Importing...
                  </>
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

        {/* ================================================================== */}
        {/* Step 3: Assign Users (only if visibility = assigned)              */}
        {/* ================================================================== */}
        {step === 'assign' && (
          <div>
            {/* Success Banner */}
            <div className="mb-4 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
              <p className="font-bold text-emerald-800 flex items-center gap-2">
                <Check className="w-5 h-5" />
                Imported {importResult?.created || 0} clients
                {importResult?.skipped > 0 && (
                  <span className="font-normal text-emerald-600">
                    ({importResult.skipped} already existed)
                  </span>
                )}
              </p>
            </div>

            <p className="text-slate-600 font-medium mb-4">
              Now assign team members to clients. You can skip this and do it later in{' '}
              <span className="font-bold">Settings → Client Access</span>.
            </p>

            {/* File Upload Zone */}
            <div
              className={cn(
                'border-2 border-dashed rounded-xl p-6 text-center mb-4 transition-all',
                dragActiveAssign 
                  ? 'border-primary bg-primary/5' 
                  : 'border-slate-300 hover:border-slate-400'
              )}
              onDragEnter={handleDragAssign}
              onDragLeave={handleDragAssign}
              onDragOver={handleDragAssign}
              onDrop={handleDropAssign}
            >
              <input
                ref={assignFileInputRef}
                type="file"
                accept=".csv,.txt,text/csv,text/plain"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files?.[0]) {
                    handleFileRead(e.target.files[0], setAssignmentCsv, setAssignResult);
                  }
                }}
              />
              
              <FileSpreadsheet className="w-10 h-10 text-slate-400 mx-auto mb-3" />
              <p className="font-bold text-slate-700 mb-1">
                Drop CSV file here or{' '}
                <button
                  onClick={() => assignFileInputRef.current?.click()}
                  className="text-primary hover:underline"
                >
                  browse
                </button>
              </p>
              <p className="text-sm text-slate-500">
                or paste content below
              </p>
            </div>

            {/* Format Example & Template */}
            <div className="mb-4 p-4 bg-slate-50 rounded-xl">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-bold text-slate-700">Expected format:</p>
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
              <p className="text-xs text-slate-500 mt-2">
                💡 Header row is optional. We'll auto-detect the format.
              </p>
            </div>

            {/* Paste Area */}
            <textarea
              value={assignmentCsv}
              onChange={(e) => setAssignmentCsv(e.target.value)}
              placeholder="Paste assignments here (or skip this step)..."
              rows={6}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
            />

            {/* Show rows loaded */}
            {assignmentCsv && (
              <div className="mt-2 flex items-center gap-2 text-sm text-emerald-600 font-medium">
                <Check className="w-4 h-4" />
                {assignmentCsv.split('\n').filter(l => l.trim()).length} rows loaded
              </div>
            )}

            {/* Results / Errors */}
            {assignResult && (
              <div className={cn(
                'mt-4 p-4 rounded-xl',
                assignResult.error 
                  ? 'bg-red-50 border-2 border-red-200' 
                  : 'bg-emerald-50 border-2 border-emerald-200'
              )}>
                {assignResult.error ? (
                  <div>
                    <p className="font-bold text-red-800 flex items-center gap-2">
                      <AlertCircle className="w-4 h-4" />
                      {assignResult.error}
                    </p>
                    {assignResult.message && (
                      <p className="text-sm text-red-700 mt-1">{assignResult.message}</p>
                    )}
                  </div>
                ) : (
                  <div>
                    <p className="font-bold text-emerald-800">
                      ✓ Created {assignResult.created} assignment(s)
                      {assignResult.skipped_duplicates > 0 && (
                        <span className="font-normal text-emerald-600">
                          {' '}({assignResult.skipped_duplicates} already existed)
                        </span>
                      )}
                    </p>
                    {assignResult.errors?.length > 0 && (
                      <div className="mt-2 max-h-24 overflow-y-auto">
                        {assignResult.errors.map((err: string, i: number) => (
                          <p key={i} className="text-xs text-amber-700">{err}</p>
                        ))}
                        {assignResult.total_errors > assignResult.errors.length && (
                          <p className="text-xs text-amber-700 font-bold">
                            ... and {assignResult.total_errors - assignResult.errors.length} more
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setStep('done')}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 transition-colors"
              >
                Skip for Now
              </button>
              <button
                onClick={handleImportAssignments}
                disabled={importing || !assignmentCsv.trim()}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25 transition-all"
              >
                {importing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Importing...
                  </>
                ) : (
                  <>
                    <Upload className="w-4 h-4" />
                    Import Assignments
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* ================================================================== */}
        {/* Step 4: Done                                                      */}
        {/* ================================================================== */}
        {step === 'done' && (
          <div className="text-center py-8">
            <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <Check className="w-8 h-8 text-emerald-600" />
            </div>
            <h3 className="text-xl font-extrabold text-slate-900 mb-2">All Done!</h3>
            <p className="text-slate-600 font-medium mb-2">
              {importResult?.created || 0} client{(importResult?.created || 0) !== 1 ? 's' : ''} imported
              {assignResult?.created ? ` and ${assignResult.created} assignment${assignResult.created !== 1 ? 's' : ''} created` : ''}.
            </p>
            {importResult?.skipped > 0 && (
              <p className="text-sm text-slate-500 mb-4">
                ({importResult.skipped} client{importResult.skipped !== 1 ? 's' : ''} already existed)
              </p>
            )}
            
            <div className="flex gap-3 justify-center mt-6">
              <button
                onClick={() => { onSuccess(); onClose(); }}
                className="px-8 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
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