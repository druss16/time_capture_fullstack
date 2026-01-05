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
  Loader2, 
  ArrowRight, 
  Upload,
  FileSpreadsheet,
  AlertCircle,
  X
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
      setIntegrations(data.integrations);
      setHasClients(data.has_clients);
      setClientCount(data.client_count);
    } catch (err) {
      console.error('Failed to load integrations:', err);
      // Set default integrations if endpoint fails
      setIntegrations([
        { id: 'karbon', name: 'Karbon', description: 'Auto-import clients and contacts', icon: 'karbon', connected: false, oauth_url: '' },
        { id: 'quickbooks', name: 'QuickBooks Online', description: 'Auto-import customers as clients', icon: 'quickbooks', connected: false, oauth_url: '' },
        { id: 'taxdome', name: 'TaxDome', description: 'Auto-import accounts as clients', icon: 'taxdome', connected: false, oauth_url: '' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleConnect = async (provider: string) => {
    setConnecting(provider);
    try {
      alert(`${provider} integration coming soon! For now, use CSV import below.`);
    } finally {
      setConnecting(null);
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
      
      // Match your existing endpoint's expected columns
      const clientIdx = headers.findIndex(h => h === 'client' || h === 'name' || h === 'client name' || h === 'company');
      const codeIdx = headers.findIndex(h => h === 'code' || h === 'client code');
      const projectIdx = headers.findIndex(h => h === 'project' || h === 'default project');
      
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
      // Use the API service which calls your existing endpoint
      const data = await importClientsCSV(csvFile);
      
      setImportSuccess(true);
      setImportedCount(data.clients || 0);
      setHasClients(true);
      setClientCount(prev => prev + (data.clients || 0));
      
      // Auto-continue after success
      setTimeout(() => {
        onComplete();
      }, 1500);
      
    } catch (err) {
      const error = err as { error?: string; message?: string; file?: string[] };
      setImportError(
        error.file?.[0] || 
        error.error || 
        error.message || 
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

  if (loading) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-purple-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <Link2 className="w-8 h-8 text-purple-600" />
        </div>
        <h2 className="text-2xl font-bold text-gray-900">Import Your Clients</h2>
        <p className="text-gray-600 mt-2">
          Connect your practice management or import from a spreadsheet
        </p>
      </div>

      {/* Integration Options */}
      <div className="space-y-3 mb-6">
        {integrations.map((integration) => (
          <div
            key={integration.id}
            className={`
              border rounded-lg p-4 flex items-center justify-between
              ${integration.connected ? 'border-green-200 bg-green-50' : 'border-gray-200'}
            `}
          >
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-gray-100 rounded-lg flex items-center justify-center">
                <span className="text-sm font-bold text-gray-400">
                  {integration.name[0]}
                </span>
              </div>
              <div>
                <h3 className="font-medium text-gray-900">{integration.name}</h3>
                <p className="text-sm text-gray-500">{integration.description}</p>
              </div>
            </div>

            {integration.connected ? (
              <div className="flex items-center gap-2 text-green-600">
                <CheckCircle className="w-5 h-5" />
                <span className="text-sm font-medium">Connected</span>
              </div>
            ) : (
              <button
                onClick={() => handleConnect(integration.id)}
                disabled={connecting === integration.id}
                className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-500 text-sm rounded-lg transition-colors"
              >
                Coming Soon
              </button>
            )}
          </div>
        ))}
      </div>

      {/* CSV Import Section */}
      <div className="border-t border-gray-200 pt-6">
        <p className="text-sm font-medium text-gray-700 mb-4">Or import clients from a spreadsheet:</p>

        {!showCSVImport && !csvFile && !importSuccess && (
          <button
            onClick={() => setShowCSVImport(true)}
            className="w-full py-4 border-2 border-dashed border-gray-300 text-gray-600 hover:border-blue-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors flex items-center justify-center gap-3"
          >
            <FileSpreadsheet className="w-6 h-6" />
            <span className="font-medium">Import from CSV</span>
          </button>
        )}

        {showCSVImport && !csvFile && (
          <div className="border-2 border-dashed border-blue-300 bg-blue-50 rounded-lg p-6">
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
              <Upload className="w-10 h-10 text-blue-500" />
              <div className="text-center">
                <p className="font-medium text-gray-900">Click to upload CSV</p>
                <p className="text-sm text-gray-500 mt-1">
                  Required column: "client" (client name)
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  Optional: code, project, active
                </p>
              </div>
            </label>
            <button
              onClick={() => setShowCSVImport(false)}
              className="mt-4 text-sm text-gray-500 hover:text-gray-700 w-full text-center"
            >
              Cancel
            </button>
          </div>
        )}

        {/* CSV Preview */}
        {csvFile && !importSuccess && (
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="bg-gray-50 px-4 py-3 flex items-center justify-between border-b">
              <div className="flex items-center gap-2">
                <FileSpreadsheet className="w-5 h-5 text-green-600" />
                <span className="font-medium text-gray-900">{csvFile.name}</span>
                <span className="text-sm text-gray-500">
                  ({csvPreview.length}+ clients)
                </span>
              </div>
              <button
                onClick={handleClearFile}
                className="p-1 hover:bg-gray-200 rounded"
              >
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>
            
            {/* Preview Table */}
            <div className="max-h-48 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium text-gray-600">Client Name</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600">Code</th>
                    <th className="text-left px-4 py-2 font-medium text-gray-600">Project</th>
                  </tr>
                </thead>
                <tbody>
                  {csvPreview.map((client, idx) => (
                    <tr key={idx} className="border-t border-gray-100">
                      <td className="px-4 py-2 text-gray-900">{client.client}</td>
                      <td className="px-4 py-2 text-gray-500">{client.code || '-'}</td>
                      <td className="px-4 py-2 text-gray-500">{client.project || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            {importError && (
              <div className="px-4 py-3 bg-red-50 border-t border-red-200 flex items-center gap-2 text-red-700">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span className="text-sm">{importError}</span>
              </div>
            )}
            
            <div className="px-4 py-3 bg-gray-50 border-t flex justify-end gap-3">
              <button
                onClick={handleClearFile}
                disabled={importing}
                className="px-4 py-2 text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleImportCSV}
                disabled={importing}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50"
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
          <div className="border border-green-200 bg-green-50 rounded-lg p-4 flex items-center gap-3">
            <CheckCircle className="w-6 h-6 text-green-600" />
            <div>
              <p className="font-medium text-green-800">
                Successfully imported {importedCount} client{importedCount !== 1 ? 's' : ''}!
              </p>
              <p className="text-sm text-green-600">Continuing to next step...</p>
            </div>
          </div>
        )}
      </div>

      {/* Already Has Clients Notice */}
      {hasClients && !importSuccess && (
        <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center gap-2 text-green-700">
            <CheckCircle className="w-5 h-5" />
            <span className="font-medium">
              {clientCount} client{clientCount !== 1 ? 's' : ''} already in system
            </span>
          </div>
          <p className="text-sm text-green-600 mt-1">
            You can continue or add more clients.
          </p>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-3 mt-6">
        {(hasClients || integrations.some(i => i.connected)) && !csvFile ? (
          <button
            onClick={onComplete}
            className="flex-1 py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            Continue
            <ArrowRight className="w-5 h-5" />
          </button>
        ) : !csvFile && !importSuccess ? (
          <button
            onClick={handleSkip}
            className="flex-1 py-3 px-4 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors"
          >
            Skip for Now
          </button>
        ) : null}
      </div>

      <p className="text-center text-sm text-gray-500 mt-4">
        You can always add more clients later from Settings
      </p>
    </div>
  );
}