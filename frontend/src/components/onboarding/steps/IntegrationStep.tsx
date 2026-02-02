// src/components/onboarding/steps/IntegrationStep.tsx

import React, { useState, useEffect, useRef } from 'react';
import { 
  getIntegrations, 
  skipIntegration, 
  importClientsCSV,
  Integration, 
  Organization 
} from '../../../services/onboardingApi';
import { 
  Users, 
  CheckCircle, 
  Check,
  Loader2, 
  ArrowRight, 
  Upload,
  FileSpreadsheet,
  AlertCircle,
  X,
  Clock,
  Download,
  Table
} from 'lucide-react';

interface IntegrationStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
}

interface CSVClient {
  client: string;
  code?: string;
}

// Coming soon integrations
const COMING_SOON_INTEGRATIONS = [
  {
    id: 'quickbooks',
    name: 'QuickBooks',
    description: 'Import clients from QuickBooks Online',
    logo: '📗',
    color: 'bg-green-100',
  },
  {
    id: 'xero',
    name: 'Xero',
    description: 'Import clients from Xero',
    logo: '📘',
    color: 'bg-blue-100',
  },
];

// Example CSV data for preview
const EXAMPLE_CSV_DATA = [
  { client: 'Acme Corporation', code: 'ACME' },
  { client: 'Smith Family Trust', code: 'SMITH-T' },
  { client: 'Johnson & Partners', code: 'JOHN-P' },
  { client: 'Green Energy LLC', code: 'GREEN' },
];

export default function IntegrationStep({ organization, onComplete, onSkip }: IntegrationStepProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasClients, setHasClients] = useState(false);
  const [clientCount, setClientCount] = useState(0);
  
  // CSV Import state
  const [showExample, setShowExample] = useState(false);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<CSVClient[]>([]);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importSuccess, setImportSuccess] = useState(false);
  const [importedCount, setImportedCount] = useState(0);

  useEffect(() => {
    loadIntegrations();
  }, []);

  const loadIntegrations = async () => {
    try {
      const data = await getIntegrations();
      // Handle both array and object response formats
      if (Array.isArray(data)) {
        setIntegrations(data);
      } else {
        setIntegrations(data.integrations || []);
        setHasClients(data.has_clients || false);
        setClientCount(data.client_count || 0);
      }
    } catch (err) {
      console.error('Failed to load integrations:', err);
      setIntegrations([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSkip = async () => {
    try {
      await skipIntegration();
    } catch (err) {
      // Continue anyway
    }
    onSkip();
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
      const clientIdx = headers.findIndex(h => 
        h === 'client' || h === 'name' || h === 'client name' || h === 'client_name' || h === 'company'
      );
      const codeIdx = headers.findIndex(h => h === 'code' || h === 'client code' || h === 'client_code');
      
      if (clientIdx === -1) {
        setImportError('CSV must have a "client" or "name" column');
        setCsvFile(null);
        return;
      }
      
      const clients: CSVClient[] = [];
      for (let i = 1; i < Math.min(lines.length, 6); i++) { // Preview first 5
        const values = lines[i].split(',').map(v => v.trim().replace(/^["']|["']$/g, ''));
        if (values[clientIdx]) {
          clients.push({
            client: values[clientIdx],
            code: codeIdx !== -1 ? values[codeIdx] : undefined,
          });
        }
      }
      
      setCsvPreview(clients);
    };
    reader.readAsText(file);
  };

  const handleImportCSV = async () => {
    if (!csvFile) return;
    
    setImporting(true);
    setImportError(null);
    
    try {
      const data = await importClientsCSV(csvFile);
      
      setImportSuccess(true);
      setImportedCount(data.clients || 0);
      setHasClients(true);
      setClientCount(prev => prev + (data.clients || 0));
      
      // Auto-continue after success
      setTimeout(() => {
        onComplete();
      }, 1500);
      
    } catch (err: any) {
      setImportError(
        err.file?.[0] || 
        err.error || 
        err.message || 
        'Failed to import clients'
      );
    } finally {
      setImporting(false);
    }
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
    const csvContent = `client,code
Acme Corporation,ACME
Smith Family Trust,SMITH-T
Johnson & Partners,JOHN-P
Green Energy LLC,GREEN`;
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'client-import-template.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  };

  const canContinue = hasClients || importSuccess;

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-teal-500" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-teal-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Users className="w-8 h-8 text-teal-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Import Your Clients</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Upload a CSV file with your client list to get started
        </p>
      </div>

      {/* CSV Import Section - Primary */}
      <div className="mb-6">
        {!csvFile && !importSuccess && (
          <>
            {/* Upload Area */}
            <div className="border-2 border-dashed border-teal-300 bg-teal-50 rounded-xl p-6 mb-4">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv"
                onChange={handleFileSelect}
                className="hidden"
                id="csv-upload"
              />
              <label
                htmlFor="csv-upload"
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
            <div className="flex items-center justify-center gap-4 mb-4">
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
              <div className="border-2 border-slate-200 rounded-xl overflow-hidden mb-4">
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
                          client <span className="text-red-500">*</span>
                        </th>
                        <th className="text-left px-4 py-2.5 font-bold text-slate-700 border-b-2 border-slate-200">
                          code <span className="text-slate-400 font-normal">(optional)</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {EXAMPLE_CSV_DATA.map((row, idx) => (
                        <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                          <td className="px-4 py-2.5 text-slate-900 font-medium">{row.client}</td>
                          <td className="px-4 py-2.5 text-slate-600 font-mono text-xs">{row.code}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-4 py-3 bg-amber-50 border-t-2 border-amber-200">
                  <p className="text-sm text-amber-800 font-medium">
                    <strong>Note:</strong> The "client" column is required. Column headers are flexible — 
                    we also accept "name", "company", "client_name", etc.
                  </p>
                </div>
              </div>
            )}
          </>
        )}

        {/* CSV Preview */}
        {csvFile && !importSuccess && (
          <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
            <div className="bg-slate-50 px-4 py-3 flex items-center justify-between border-b-2 border-slate-200">
              <div className="flex items-center gap-2">
                <FileSpreadsheet className="w-5 h-5 text-teal-600" />
                <span className="font-bold text-slate-900">{csvFile.name}</span>
                <span className="text-sm text-slate-500 font-medium">
                  ({csvPreview.length}+ clients)
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
                    <th className="text-left px-4 py-2 font-bold text-slate-700">Client Name</th>
                    <th className="text-left px-4 py-2 font-bold text-slate-700">Code</th>
                  </tr>
                </thead>
                <tbody>
                  {csvPreview.map((client, idx) => (
                    <tr key={idx} className="border-t border-slate-100">
                      <td className="px-4 py-2 text-slate-900 font-medium">{client.client}</td>
                      <td className="px-4 py-2 text-slate-500 font-mono text-xs">{client.code || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            {importError && (
              <div className="px-4 py-3 bg-red-50 border-t-2 border-red-200 flex items-center gap-2 text-red-700">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span className="text-sm font-medium">{importError}</span>
              </div>
            )}
            
            <div className="px-4 py-3 bg-slate-50 border-t-2 border-slate-200 flex justify-end gap-3">
              <button
                onClick={handleClearFile}
                disabled={importing}
                className="px-4 py-2 text-slate-600 hover:text-slate-800 font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleImportCSV}
                disabled={importing}
                className="px-4 py-2 bg-teal-500 hover:bg-teal-600 text-white font-bold rounded-xl transition-colors flex items-center gap-2 disabled:opacity-50 shadow-lg shadow-teal-500/25"
              >
                {importing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Importing...
                  </>
                ) : (
                  <>
                    <Upload className="w-4 h-4" />
                    Import {csvPreview.length}+ Clients
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Import Success */}
        {importSuccess && (
          <div className="border-2 border-teal-200 bg-teal-50 rounded-xl p-4 flex items-center gap-3">
            <CheckCircle className="w-6 h-6 text-teal-600" />
            <div>
              <p className="font-bold text-teal-800">
                Successfully imported {importedCount} client{importedCount !== 1 ? 's' : ''}!
              </p>
              <p className="text-sm text-teal-600 font-medium">Continuing to next step...</p>
            </div>
          </div>
        )}
      </div>

      {/* Coming Soon Integrations */}
      {!csvFile && !importSuccess && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="flex-1 h-px bg-slate-200"></div>
            <span className="text-sm text-slate-400 font-semibold px-3">COMING SOON</span>
            <div className="flex-1 h-px bg-slate-200"></div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {COMING_SOON_INTEGRATIONS.map((integration) => (
              <div
                key={integration.id}
                className="p-4 border-2 border-slate-200 rounded-xl opacity-50 cursor-not-allowed"
              >
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 ${integration.color} rounded-xl flex items-center justify-center text-xl`}>
                    {integration.logo}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-bold text-slate-700">{integration.name}</h3>
                    </div>
                    <p className="text-xs text-slate-400 font-medium">{integration.description}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Already Has Clients Notice */}
      {hasClients && !importSuccess && !csvFile && (
        <div className="mb-6 p-4 bg-teal-50 border-2 border-teal-200 rounded-xl">
          <div className="flex items-center gap-2 text-teal-700">
            <CheckCircle className="w-5 h-5" />
            <span className="font-bold">
              {clientCount} client{clientCount !== 1 ? 's' : ''} already in system
            </span>
          </div>
          <p className="text-sm text-teal-600 mt-1 font-medium">
            You can continue or add more clients.
          </p>
        </div>
      )}

      {/* Info Box */}
      {!csvFile && !importSuccess && (
        <div className="mb-6 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
          <div className="flex items-start gap-3">
            <Clock className="w-5 h-5 text-slate-400 mt-0.5" />
            <div>
              <p className="text-sm text-slate-600 font-medium">
                <strong className="text-slate-800">Don't have a client list ready?</strong> No problem! 
                You can add clients manually later from Settings, or skip this step entirely.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      {!csvFile && !importSuccess && (
        <div className="flex gap-3">
          {canContinue ? (
            <button
              onClick={onComplete}
              className="flex-1 py-3.5 px-4 bg-teal-500 hover:bg-teal-600 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-teal-500/25"
            >
              Continue
              <ArrowRight className="w-5 h-5" />
            </button>
          ) : (
            <button
              onClick={handleSkip}
              className="flex-1 py-3.5 px-4 bg-teal-500 hover:bg-teal-600 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-teal-500/25"
            >
              Continue Without Clients
              <ArrowRight className="w-5 h-5" />
            </button>
          )}
          
          {canContinue && (
            <button
              onClick={handleSkip}
              className="px-6 py-3.5 border-2 border-slate-200 hover:border-slate-300 text-slate-700 font-bold rounded-xl transition-all hover:bg-slate-50"
            >
              Skip
            </button>
          )}
        </div>
      )}

      <p className="text-center text-sm text-slate-500 mt-4 font-medium">
        You can always add more clients later from Settings
      </p>
    </div>
  );
}