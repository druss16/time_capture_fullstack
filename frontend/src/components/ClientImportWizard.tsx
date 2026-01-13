// src/components/ClientImportWizard.tsx - Add integration step

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
  Link,
  ExternalLink,
} from 'lucide-react';
import { cn } from '@/lib/design-system';
import { safeFetchJson } from '@/lib/api';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

// Integration logos (you can replace with actual logos)
const INTEGRATIONS = [
  {
    id: 'quickbooks',
    name: 'QuickBooks Online',
    description: 'Import customers from QuickBooks',
    logo: '📗',
    status: 'available' as const,
    color: 'bg-green-50 border-green-200 hover:border-green-400',
  },
  {
    id: 'xero',
    name: 'Xero',
    description: 'Import contacts from Xero',
    logo: '🔵',
    status: 'available' as const,
    color: 'bg-blue-50 border-blue-200 hover:border-blue-400',
  },
  {
    id: 'karbon',
    name: 'Karbon',
    description: 'Import clients from Karbon',
    logo: '🟠',
    status: 'coming_soon' as const,
    color: 'bg-orange-50 border-orange-200',
  },
  {
    id: 'cch',
    name: 'CCH Axcess',
    description: 'Import clients from CCH',
    logo: '🔴',
    status: 'coming_soon' as const,
    color: 'bg-red-50 border-red-200',
  },
  {
    id: 'lacerte',
    name: 'Lacerte / ProConnect',
    description: 'Import from Intuit Tax',
    logo: '💜',
    status: 'coming_soon' as const,
    color: 'bg-purple-50 border-purple-200',
  },
  {
    id: 'thomson',
    name: 'Thomson Reuters',
    description: 'UltraTax CS, Practice CS',
    logo: '🟤',
    status: 'coming_soon' as const,
    color: 'bg-amber-50 border-amber-200',
  },
];

interface Props {
  onClose: () => void;
  onSuccess: () => void;
  users: Array<{ id: number; email: string; first_name: string; last_name: string; username: string }>;
}

type Step = 'method' | 'import' | 'integration' | 'visibility' | 'assign' | 'done';

export default function ClientImportWizard({ onClose, onSuccess, users }: Props) {
  const [step, setStep] = useState<Step>('method');
  const [importMethod, setImportMethod] = useState<'file' | 'integration' | null>(null);
  const [selectedIntegration, setSelectedIntegration] = useState<string | null>(null);
  const [csvContent, setCsvContent] = useState('');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<any>(null);
  const [defaultVisibility, setDefaultVisibility] = useState<'all' | 'assigned'>('all');
  const [assignmentCsv, setAssignmentCsv] = useState('');
  const [assignResult, setAssignResult] = useState<any>(null);
  const [integrationClients, setIntegrationClients] = useState<any[]>([]);
  const [selectedClients, setSelectedClients] = useState<Set<string>>(new Set());
  
  // Drag & drop states
  const [dragActiveClient, setDragActiveClient] = useState(false);
  const [dragActiveAssign, setDragActiveAssign] = useState(false);
  
  // File input refs
  const clientFileInputRef = useRef<HTMLInputElement>(null);
  const assignFileInputRef = useRef<HTMLInputElement>(null);

  // ============================================================================
  // Integration Handlers
  // ============================================================================
  
  const handleConnectIntegration = async (integrationId: string) => {
    setSelectedIntegration(integrationId);
    setImporting(true);
    
    try {
      // Start OAuth flow - this will redirect
      const response = await safeFetchJson<{ auth_url: string }>(
        `${API_BASE}/integrations/${integrationId}/connect/`
      );
      
      if (response.auth_url) {
        // Open OAuth in popup or redirect
        const width = 600;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;
        
        const popup = window.open(
          response.auth_url,
          `Connect to ${integrationId}`,
          `width=${width},height=${height},left=${left},top=${top}`
        );
        
        // Listen for OAuth callback
        const handleMessage = async (event: MessageEvent) => {
          if (event.data?.type === 'oauth_callback' && event.data?.integration === integrationId) {
            window.removeEventListener('message', handleMessage);
            popup?.close();
            
            if (event.data.success) {
              // Fetch clients from the integration
              await fetchIntegrationClients(integrationId);
            } else {
              setImportResult({ error: event.data.error || 'Connection failed' });
              setImporting(false);
            }
          }
        };
        
        window.addEventListener('message', handleMessage);
        
        // Also poll for connection status (backup for popup blockers)
        const pollInterval = setInterval(async () => {
          try {
            const status = await safeFetchJson<{ connected: boolean }>(
              `${API_BASE}/integrations/${integrationId}/status/`
            );
            if (status.connected) {
              clearInterval(pollInterval);
              window.removeEventListener('message', handleMessage);
              await fetchIntegrationClients(integrationId);
            }
          } catch (e) {
            // Ignore polling errors
          }
        }, 2000);
        
        // Stop polling after 5 minutes
        setTimeout(() => clearInterval(pollInterval), 300000);
      }
    } catch (err: any) {
      setImportResult({ error: err.message || 'Failed to connect' });
      setImporting(false);
    }
  };

  const fetchIntegrationClients = async (integrationId: string) => {
    try {
      const response = await safeFetchJson<{ clients: any[] }>(
        `${API_BASE}/integrations/${integrationId}/clients/`
      );
      
      setIntegrationClients(response.clients || []);
      setSelectedClients(new Set(response.clients?.map((c: any) => c.id) || []));
      setStep('integration');
    } catch (err: any) {
      setImportResult({ error: err.message || 'Failed to fetch clients' });
    } finally {
      setImporting(false);
    }
  };

  const handleImportFromIntegration = async () => {
    if (selectedClients.size === 0) return;
    
    setImporting(true);
    setImportResult(null);
    
    try {
      const clientsToImport = integrationClients.filter(c => selectedClients.has(c.id));
      
      let created = 0;
      let skipped = 0;
      let errors: string[] = [];
      
      for (const client of clientsToImport) {
        try {
          await safeFetchJson(`${API_BASE}/settings/clients/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: client.name || client.displayName || client.companyName,
              code: (client.code || client.name?.substring(0, 4) || '').toUpperCase().replace(/\s/g, ''),
              visibility: defaultVisibility,
              external_id: client.id,
              external_source: selectedIntegration,
            }),
          });
          created++;
        } catch (err: any) {
          if (err.message?.includes('already exists')) {
            skipped++;
          } else {
            errors.push(`${client.name}: ${err.message}`);
          }
        }
      }
      
      setImportResult({ created, skipped, errors, total: clientsToImport.length });
      
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
            body: JSON.stringify({ name, code, visibility: defaultVisibility }),
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
        setAssignResult({ error: data.error || `Server error: ${response.status}`, message: data.message });
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
  // Progress calculation
  // ============================================================================
  
  const getStepNumber = (s: Step): number => {
    const steps: Step[] = ['method', 'import', 'integration', 'visibility', 'assign', 'done'];
    // Adjust based on path taken
    if (importMethod === 'file') {
      const fileSteps = ['method', 'import', 'visibility', 'assign', 'done'];
      return fileSteps.indexOf(s) + 1;
    } else {
      const intSteps = ['method', 'integration', 'visibility', 'assign', 'done'];
      return intSteps.indexOf(s) + 1;
    }
  };

  const totalSteps = defaultVisibility === 'assigned' ? 4 : 3;

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
              {step === 'method' && 'Choose how to import your clients'}
              {step === 'import' && 'Upload or paste your client list'}
              {step === 'integration' && `Select clients from ${INTEGRATIONS.find(i => i.id === selectedIntegration)?.name}`}
              {step === 'visibility' && 'Set default visibility'}
              {step === 'assign' && 'Assign users to clients (optional)'}
              {step === 'done' && 'All done!'}
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded-lg transition-colors">
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* ================================================================== */}
        {/* Step: Choose Method                                               */}
        {/* ================================================================== */}
        {step === 'method' && (
          <div>
            <div className="grid md:grid-cols-2 gap-4 mb-6">
              {/* File Upload Option */}
              <button
                onClick={() => { setImportMethod('file'); setStep('import'); }}
                className="p-6 border-2 border-slate-200 rounded-xl hover:border-primary hover:bg-primary/5 transition-all text-left group"
              >
                <FileSpreadsheet className="w-10 h-10 text-slate-400 group-hover:text-primary mb-3" />
                <h3 className="font-bold text-slate-900 mb-1">Upload CSV / Excel</h3>
                <p className="text-sm text-slate-500">
                  Import from a file or paste from Excel
                </p>
              </button>

              {/* Integration Option */}
              <button
                onClick={() => setImportMethod('integration')}
                className="p-6 border-2 border-slate-200 rounded-xl hover:border-primary hover:bg-primary/5 transition-all text-left group"
              >
                <Link className="w-10 h-10 text-slate-400 group-hover:text-primary mb-3" />
                <h3 className="font-bold text-slate-900 mb-1">Connect Integration</h3>
                <p className="text-sm text-slate-500">
                  QuickBooks, Xero, Karbon & more
                </p>
              </button>
            </div>

            {/* Integration List (if selected) */}
            {importMethod === 'integration' && (
              <div className="border-t-2 border-slate-100 pt-6">
                <h3 className="font-bold text-slate-800 mb-4">Choose your platform</h3>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                  {INTEGRATIONS.map(integration => (
                    <button
                      key={integration.id}
                      onClick={() => integration.status === 'available' && handleConnectIntegration(integration.id)}
                      disabled={integration.status === 'coming_soon' || importing}
                      className={cn(
                        'p-4 border-2 rounded-xl text-left transition-all relative',
                        integration.status === 'coming_soon' 
                          ? 'opacity-60 cursor-not-allowed ' + integration.color
                          : integration.color + ' cursor-pointer',
                        importing && selectedIntegration === integration.id && 'ring-2 ring-primary'
                      )}
                    >
                      {integration.status === 'coming_soon' && (
                        <span className="absolute top-2 right-2 text-[10px] bg-slate-200 text-slate-600 px-1.5 py-0.5 rounded-full font-bold">
                          SOON
                        </span>
                      )}
                      <div className="text-2xl mb-2">{integration.logo}</div>
                      <p className="font-bold text-slate-800 text-sm">{integration.name}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{integration.description}</p>
                      
                      {importing && selectedIntegration === integration.id && (
                        <div className="absolute inset-0 bg-white/80 rounded-xl flex items-center justify-center">
                          <Loader2 className="w-6 h-6 text-primary animate-spin" />
                        </div>
                      )}
                    </button>
                  ))}
                </div>
                
                <p className="text-xs text-slate-500 mt-4 text-center">
                  Don't see your platform? <button className="text-primary font-bold hover:underline">Request an integration</button>
                </p>
              </div>
            )}

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
            </div>
          </div>
        )}

        {/* ================================================================== */}
        {/* Step: Integration Client Selection                                */}
        {/* ================================================================== */}
        {step === 'integration' && (
          <div>
            <div className="mb-4 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl flex items-center gap-3">
              <Check className="w-5 h-5 text-emerald-600" />
              <p className="font-bold text-emerald-800">
                Connected to {INTEGRATIONS.find(i => i.id === selectedIntegration)?.name}!
              </p>
            </div>

            <div className="flex items-center justify-between mb-3">
              <p className="font-bold text-slate-800">
                Select clients to import ({selectedClients.size} of {integrationClients.length})
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setSelectedClients(new Set(integrationClients.map(c => c.id)))}
                  className="text-xs text-primary font-bold hover:underline"
                >
                  Select All
                </button>
                <button
                  onClick={() => setSelectedClients(new Set())}
                  className="text-xs text-slate-500 font-bold hover:underline"
                >
                  Clear
                </button>
              </div>
            </div>

            <div className="border-2 border-slate-200 rounded-xl max-h-64 overflow-y-auto">
              {integrationClients.length === 0 ? (
                <div className="p-8 text-center text-slate-500">
                  <p className="font-medium">No clients found</p>
                  <p className="text-sm mt-1">Make sure you have customers in your {INTEGRATIONS.find(i => i.id === selectedIntegration)?.name} account</p>
                </div>
              ) : (
                integrationClients.map(client => (
                  <label
                    key={client.id}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50 cursor-pointer border-b border-slate-100 last:border-0"
                  >
                    <input
                      type="checkbox"
                      checked={selectedClients.has(client.id)}
                      onChange={(e) => {
                        const newSelected = new Set(selectedClients);
                        if (e.target.checked) {
                          newSelected.add(client.id);
                        } else {
                          newSelected.delete(client.id);
                        }
                        setSelectedClients(newSelected);
                      }}
                      className="w-4 h-4 text-primary rounded"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="font-bold text-slate-800 truncate">
                        {client.name || client.displayName || client.companyName}
                      </p>
                      {client.email && (
                        <p className="text-xs text-slate-500 truncate">{client.email}</p>
                      )}
                    </div>
                    {client.balance !== undefined && (
                      <span className="text-xs text-slate-500 font-mono">
                        ${Number(client.balance || 0).toFixed(2)}
                      </span>
                    )}
                  </label>
                ))
              )}
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setStep('method'); setSelectedIntegration(null); }}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 flex items-center justify-center gap-2 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                Back
              </button>
              <button
                onClick={() => setStep('visibility')}
                disabled={selectedClients.size === 0}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25 transition-all"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* ================================================================== */}
        {/* Step: File Import                                                 */}
        {/* ================================================================== */}
        {step === 'import' && (
          <div>
            {/* File Upload Zone */}
            <div
              className={cn(
                'border-2 border-dashed rounded-xl p-8 text-center mb-4 transition-all',
                dragActiveClient ? 'border-primary bg-primary/5' : 'border-slate-300 hover:border-slate-400'
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
              <p className="font-bold text-slate-700 mb-1">Drag & drop CSV file here</p>
              <p className="text-sm text-slate-500 mb-3">
                or{' '}
                <button onClick={() => clientFileInputRef.current?.click()} className="text-primary font-bold hover:underline">
                  browse files
                </button>
              </p>
              <p className="text-xs text-slate-400">Supports .csv and .txt files</p>
            </div>

            {/* Divider */}
            <div className="flex items-center gap-4 mb-4">
              <div className="flex-1 h-px bg-slate-200" />
              <span className="text-sm font-bold text-slate-400">OR</span>
              <div className="flex-1 h-px bg-slate-200" />
            </div>

            {/* Format Example */}
            <div className="mb-4 p-4 bg-slate-50 rounded-xl">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-bold text-slate-700">Paste from Excel</p>
                <button onClick={downloadClientTemplate} className="text-xs text-primary font-bold hover:underline flex items-center gap-1">
                  <Download className="w-3 h-3" />
                  Download Template
                </button>
              </div>
              <code className="text-xs text-slate-600 bg-slate-200 px-2 py-1 rounded block font-mono">
                name,code<br/>Acme Corporation,ACME<br/>BigCo Industries,BIGCO
              </code>
              <p className="text-xs text-slate-500 mt-2">💡 Header row is optional</p>
            </div>

            <textarea
              value={csvContent}
              onChange={(e) => setCsvContent(e.target.value)}
              placeholder="Paste your client list here..."
              rows={6}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
            />

            {csvContent && (
              <div className="mt-2 flex items-center gap-2 text-sm text-emerald-600 font-medium">
                <Check className="w-4 h-4" />
                {csvContent.split('\n').filter(l => l.trim()).length} rows loaded
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => { setStep('method'); setImportMethod(null); }}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 flex items-center justify-center gap-2 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                Back
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
        {/* Step: Visibility                                                  */}
        {/* ================================================================== */}
        {step === 'visibility' && (
          <div>
            <p className="text-slate-600 font-medium mb-4">Who should be able to see these clients by default?</p>

            <div className="space-y-3">
              <label className={cn(
                'block p-4 border-2 rounded-xl cursor-pointer transition-all',
                defaultVisibility === 'all' ? 'border-primary bg-primary/5' : 'border-slate-200 hover:border-slate-300'
              )}>
                <input type="radio" name="visibility" value="all" checked={defaultVisibility === 'all'} onChange={() => setDefaultVisibility('all')} className="sr-only" />
                <div className="flex items-start gap-3">
                  <div className={cn('w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5 flex-shrink-0', defaultVisibility === 'all' ? 'border-primary' : 'border-slate-300')}>
                    {defaultVisibility === 'all' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="font-bold text-slate-900">👥 All Team Members</p>
                    <p className="text-sm text-slate-500 font-medium mt-1">Everyone can see all clients. Best for small teams.</p>
                    <span className="inline-block mt-2 px-2 py-0.5 bg-emerald-100 text-emerald-700 text-xs font-bold rounded-full">Recommended</span>
                  </div>
                </div>
              </label>

              <label className={cn(
                'block p-4 border-2 rounded-xl cursor-pointer transition-all',
                defaultVisibility === 'assigned' ? 'border-primary bg-primary/5' : 'border-slate-200 hover:border-slate-300'
              )}>
                <input type="radio" name="visibility" value="assigned" checked={defaultVisibility === 'assigned'} onChange={() => setDefaultVisibility('assigned')} className="sr-only" />
                <div className="flex items-start gap-3">
                  <div className={cn('w-5 h-5 rounded-full border-2 flex items-center justify-center mt-0.5 flex-shrink-0', defaultVisibility === 'assigned' ? 'border-primary' : 'border-slate-300')}>
                    {defaultVisibility === 'assigned' && <div className="w-2.5 h-2.5 rounded-full bg-primary" />}
                  </div>
                  <div>
                    <p className="font-bold text-slate-900">🔒 Assigned Users Only</p>
                    <p className="text-sm text-slate-500 font-medium mt-1">Only assigned team members can see each client.</p>
                    <p className="text-xs text-amber-600 font-medium mt-2">⚠️ You'll need to assign users in the next step</p>
                  </div>
                </div>
              </label>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setStep(importMethod === 'integration' ? 'integration' : 'import')}
                className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100 flex items-center justify-center gap-2 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                Back
              </button>
              <button
                onClick={importMethod === 'integration' ? handleImportFromIntegration : handleImportClients}
                disabled={importing}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25 transition-all"
              >
                {importing ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />Importing...</>
                ) : (
                  <>Import Clients<ChevronRight className="w-4 h-4" /></>
                )}
              </button>
            </div>
          </div>
        )}

        {/* ================================================================== */}
        {/* Step: Assign Users                                                */}
        {/* ================================================================== */}
        {step === 'assign' && (
          <div>
            <div className="mb-4 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
              <p className="font-bold text-emerald-800 flex items-center gap-2">
                <Check className="w-5 h-5" />
                Imported {importResult?.created || 0} clients
                {importResult?.skipped > 0 && <span className="font-normal text-emerald-600">({importResult.skipped} already existed)</span>}
              </p>
            </div>

            <p className="text-slate-600 font-medium mb-4">
              Assign team members to clients. You can skip this and do it later in <span className="font-bold">Settings → Client Access</span>.
            </p>

            {/* File Upload */}
            <div
              className={cn(
                'border-2 border-dashed rounded-xl p-6 text-center mb-4 transition-all',
                dragActiveAssign ? 'border-primary bg-primary/5' : 'border-slate-300 hover:border-slate-400'
              )}
              onDragEnter={handleDragAssign}
              onDragLeave={handleDragAssign}
              onDragOver={handleDragAssign}
              onDrop={handleDropAssign}
            >
              <input
                ref={assignFileInputRef}
                type="file"
                accept=".csv,.txt"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && handleFileRead(e.target.files[0], setAssignmentCsv, setAssignResult)}
              />
              <FileSpreadsheet className="w-10 h-10 text-slate-400 mx-auto mb-3" />
              <p className="font-bold text-slate-700 mb-1">
                Drop CSV here or <button onClick={() => assignFileInputRef.current?.click()} className="text-primary hover:underline">browse</button>
              </p>
            </div>

            <div className="mb-4 p-4 bg-slate-50 rounded-xl">
              <div className="flex items-center justify-between mb-2">
                <p className="text-sm font-bold text-slate-700">Format:</p>
                <button onClick={downloadAssignmentTemplate} className="text-xs text-primary font-bold hover:underline flex items-center gap-1">
                  <Download className="w-3 h-3" />Template
                </button>
              </div>
              <code className="text-xs text-slate-600 bg-slate-200 px-2 py-1 rounded block font-mono">
                email,client_code<br/>john@firm.com,ACME
              </code>
            </div>

            <textarea
              value={assignmentCsv}
              onChange={(e) => setAssignmentCsv(e.target.value)}
              placeholder="Paste assignments here..."
              rows={5}
              className="w-full border-2 border-slate-200 rounded-xl px-4 py-3 font-mono text-sm focus:border-primary focus:ring-2 focus:ring-primary/20 focus:outline-none"
            />

            {assignResult && (
              <div className={cn('mt-4 p-4 rounded-xl', assignResult.error ? 'bg-red-50 border-2 border-red-200' : 'bg-emerald-50 border-2 border-emerald-200')}>
                {assignResult.error ? (
                  <p className="font-bold text-red-800 flex items-center gap-2"><AlertCircle className="w-4 h-4" />{assignResult.error}</p>
                ) : (
                  <p className="font-bold text-emerald-800">✓ Created {assignResult.created} assignments</p>
                )}
              </div>
            )}

            <div className="flex gap-3 mt-6">
              <button onClick={() => setStep('done')} className="flex-1 px-4 py-3 border-2 border-slate-200 rounded-xl font-bold text-slate-700 hover:bg-slate-100">
                Skip for Now
              </button>
              <button
                onClick={handleImportAssignments}
                disabled={importing || !assignmentCsv.trim()}
                className="flex-1 px-4 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-2 shadow-lg shadow-primary/25"
              >
                {importing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                Import Assignments
              </button>
            </div>
          </div>
        )}

        {/* ================================================================== */}
        {/* Step: Done                                                        */}
        {/* ================================================================== */}
        {step === 'done' && (
          <div className="text-center py-8">
            <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <Check className="w-8 h-8 text-emerald-600" />
            </div>
            <h3 className="text-xl font-extrabold text-slate-900 mb-2">All Done!</h3>
            <p className="text-slate-600 font-medium">
              {importResult?.created || 0} client{(importResult?.created || 0) !== 1 ? 's' : ''} imported
              {assignResult?.created ? ` and ${assignResult.created} assignment${assignResult.created !== 1 ? 's' : ''} created` : ''}.
            </p>
            <button
              onClick={() => { onSuccess(); onClose(); }}
              className="mt-6 px-8 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 shadow-lg shadow-primary/25"
            >
              Done
            </button>
          </div>
        )}
      </div>
    </div>
  );
}