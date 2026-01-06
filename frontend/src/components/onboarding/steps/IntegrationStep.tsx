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
  Link2, 
  CheckCircle, 
  Check,
  Loader2, 
  ArrowRight, 
  Upload,
  FileSpreadsheet,
  AlertCircle,
  X,
  Calendar,
  FileText,
  Mail,
  Clock,
  Users
} from 'lucide-react';

interface IntegrationStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
}

interface CSVClient {
  client: string;
  code?: string;
  project?: string;
}

const AVAILABLE_INTEGRATIONS = [
  {
    id: 'karbon',
    name: 'Karbon',
    description: 'Sync clients and projects from Karbon',
    icon: <FileText className="w-6 h-6" />,
    color: 'bg-purple-100 text-purple-600',
    available: true,
  },
  {
    id: 'outlook',
    name: 'Outlook Calendar',
    description: 'Import calendar events for time tracking',
    icon: <Calendar className="w-6 h-6" />,
    color: 'bg-blue-100 text-blue-600',
    available: true,
  },
  {
    id: 'google',
    name: 'Google Calendar',
    description: 'Import calendar events for time tracking',
    icon: <Calendar className="w-6 h-6" />,
    color: 'bg-red-100 text-red-600',
    available: true,
  },
  {
    id: 'gmail',
    name: 'Gmail',
    description: 'Track time spent on email',
    icon: <Mail className="w-6 h-6" />,
    color: 'bg-red-100 text-red-600',
    available: false,
    comingSoon: true,
  },
];

export default function IntegrationStep({ organization, onComplete, onSkip }: IntegrationStepProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [hasClients, setHasClients] = useState(false);
  const [clientCount, setClientCount] = useState(0);
  
  // CSV Import state
  const [showCSVImport, setShowCSVImport] = useState(false);
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
      // Use static integrations list as fallback
      setIntegrations([]);
    } finally {
      setLoading(false);
    }
  };

  const handleConnect = async (integrationId: string) => {
    setConnecting(integrationId);
    
    // Redirect to OAuth flow
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
    window.location.href = `${baseUrl}/integrations/${integrationId}/connect/?next=/onboarding`;
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
      const projectIdx = headers.findIndex(h => h === 'project' || h === 'default project' || h === 'default_project');
      
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
            project: projectIdx !== -1 ? values[projectIdx] : undefined,
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

  const connectedIntegrations = integrations.filter(i => i.connected);
  const canContinue = hasClients || connectedIntegrations.length > 0 || importSuccess;

  if (loading) {
    return (
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-emerald-600" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Link2 className="w-8 h-8 text-emerald-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Import Your Clients</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Connect your practice management or import from a spreadsheet
        </p>
      </div>

      {/* Integration Options */}
      <div className="space-y-3 mb-6">
        {AVAILABLE_INTEGRATIONS.map((integration) => {
          const isConnected = connectedIntegrations.some(i => i.id === integration.id || i.provider === integration.id);
          const isConnecting = connecting === integration.id;
          
          return (
            <div
              key={integration.id}
              className={`
                p-4 border-2 rounded-xl transition-all
                ${isConnected ? 'border-emerald-200 bg-emerald-50' : 'border-slate-200 hover:border-slate-300'}
                ${integration.comingSoon ? 'opacity-60' : ''}
              `}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${integration.color}`}>
                    {integration.icon}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-bold text-slate-900">{integration.name}</h3>
                      {integration.comingSoon && (
                        <span className="text-xs bg-slate-200 text-slate-600 px-2 py-0.5 rounded-full font-semibold">
                          Coming Soon
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-slate-500 font-medium">{integration.description}</p>
                  </div>
                </div>

                {isConnected ? (
                  <div className="flex items-center gap-2 text-emerald-600">
                    <Check className="w-5 h-5" />
                    <span className="font-bold">Connected</span>
                  </div>
                ) : integration.available && !integration.comingSoon ? (
                  <button
                    onClick={() => handleConnect(integration.id)}
                    disabled={isConnecting}
                    className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all disabled:opacity-50 shadow-lg shadow-emerald-600/25"
                  >
                    {isConnecting ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      'Connect'
                    )}
                  </button>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {/* CSV Import Section */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-4">
          <div className="flex-1 h-px bg-slate-200"></div>
          <span className="text-sm text-slate-500 font-semibold px-3">OR IMPORT FROM SPREADSHEET</span>
          <div className="flex-1 h-px bg-slate-200"></div>
        </div>

        {!showCSVImport && !csvFile && !importSuccess && (
          <button
            onClick={() => setShowCSVImport(true)}
            className="w-full p-5 border-2 border-dashed border-slate-300 hover:border-emerald-400 text-slate-600 hover:text-emerald-600 hover:bg-emerald-50 rounded-xl transition-all flex items-center justify-center gap-3"
          >
            <FileSpreadsheet className="w-6 h-6" />
            <span className="font-bold">Import Clients from CSV</span>
          </button>
        )}

        {showCSVImport && !csvFile && (
          <div className="border-2 border-dashed border-emerald-300 bg-emerald-50 rounded-xl p-6">
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
              <div className="w-14 h-14 bg-emerald-100 rounded-xl flex items-center justify-center">
                <Upload className="w-7 h-7 text-emerald-600" />
              </div>
              <div className="text-center">
                <p className="font-bold text-slate-900">Click to upload CSV</p>
                <p className="text-sm text-slate-600 mt-1 font-medium">
                  Required column: <code className="bg-emerald-100 px-1.5 py-0.5 rounded text-xs">client</code> or <code className="bg-emerald-100 px-1.5 py-0.5 rounded text-xs">name</code>
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  Optional: code, project
                </p>
              </div>
            </label>
            <button
              onClick={() => setShowCSVImport(false)}
              className="mt-4 text-sm text-slate-500 hover:text-slate-700 w-full text-center font-medium"
            >
              Cancel
            </button>
          </div>
        )}

        {/* CSV Preview */}
        {csvFile && !importSuccess && (
          <div className="border-2 border-slate-200 rounded-xl overflow-hidden">
            <div className="bg-slate-50 px-4 py-3 flex items-center justify-between border-b-2 border-slate-200">
              <div className="flex items-center gap-2">
                <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
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
                    <th className="text-left px-4 py-2 font-bold text-slate-700">Project</th>
                  </tr>
                </thead>
                <tbody>
                  {csvPreview.map((client, idx) => (
                    <tr key={idx} className="border-t border-slate-100">
                      <td className="px-4 py-2 text-slate-900 font-medium">{client.client}</td>
                      <td className="px-4 py-2 text-slate-500">{client.code || '-'}</td>
                      <td className="px-4 py-2 text-slate-500">{client.project || '-'}</td>
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
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-colors flex items-center gap-2 disabled:opacity-50 shadow-lg shadow-emerald-600/25"
              >
                {importing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Importing...
                  </>
                ) : (
                  <>
                    <Upload className="w-4 h-4" />
                    Import Clients
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Import Success */}
        {importSuccess && (
          <div className="border-2 border-emerald-200 bg-emerald-50 rounded-xl p-4 flex items-center gap-3">
            <CheckCircle className="w-6 h-6 text-emerald-600" />
            <div>
              <p className="font-bold text-emerald-800">
                Successfully imported {importedCount} client{importedCount !== 1 ? 's' : ''}!
              </p>
              <p className="text-sm text-emerald-600 font-medium">Continuing to next step...</p>
            </div>
          </div>
        )}
      </div>

      {/* Already Has Clients Notice */}
      {hasClients && !importSuccess && (
        <div className="mb-6 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
          <div className="flex items-center gap-2 text-emerald-700">
            <CheckCircle className="w-5 h-5" />
            <span className="font-bold">
              {clientCount} client{clientCount !== 1 ? 's' : ''} already in system
            </span>
          </div>
          <p className="text-sm text-emerald-600 mt-1 font-medium">
            You can continue or add more clients.
          </p>
        </div>
      )}

      {/* Info Box */}
      <div className="mb-6 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
        <div className="flex items-start gap-3">
          <Clock className="w-5 h-5 text-slate-400 mt-0.5" />
          <div>
            <p className="text-sm text-slate-600 font-medium">
              <strong className="text-slate-800">Don't have a client list?</strong> No problem! You can add clients manually later from Settings, or skip this step entirely.
            </p>
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        {canContinue && !csvFile ? (
          <button
            onClick={onComplete}
            className="flex-1 py-3.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25"
          >
            Continue
            <ArrowRight className="w-5 h-5" />
          </button>
        ) : !csvFile && !importSuccess ? (
          <button
            onClick={handleSkip}
            className="flex-1 py-3.5 px-4 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25"
          >
            Continue Without Clients
            <ArrowRight className="w-5 h-5" />
          </button>
        ) : null}
        
        {canContinue && !csvFile && (
          <button
            onClick={handleSkip}
            className="px-6 py-3.5 border-2 border-slate-200 hover:border-slate-300 text-slate-700 font-bold rounded-xl transition-all hover:bg-slate-50"
          >
            Skip
          </button>
        )}
      </div>

      <p className="text-center text-sm text-slate-500 mt-4 font-medium">
        You can always add more clients later from Settings
      </p>
    </div>
  );
}