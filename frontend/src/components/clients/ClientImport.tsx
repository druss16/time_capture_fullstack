/**
 * ClientImport.tsx - CSV Import for clients
 * Updated to match design system
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '@/lib/api';
import { 
  Upload, 
  Download, 
  FileSpreadsheet, 
  CheckCircle2, 
  AlertCircle, 
  ArrowLeft,
  X 
} from 'lucide-react';
import { cn } from '@/lib/design-system';

export function ClientImport() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async () => {
    if (!file) return;
    
    setUploading(true);
    setError(null);
    setResult(null);
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const response = await fetch(`${API_BASE}/import-clients-csv/`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.error || 'Upload failed');
      }
      
      setResult(data);
      setFile(null);
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    setFile(selectedFile);
    setError(null);
    setResult(null);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-2xl mx-auto p-6">
        {/* Back Button */}
        <button
          onClick={() => navigate('/clients')}
          className="flex items-center gap-2 text-slate-600 hover:text-slate-900 font-semibold mb-6 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Clients
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-12 h-12 rounded-xl bg-primary flex items-center justify-center shadow-lg shadow-primary/25">
            <Upload className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">Import Clients</h1>
            <p className="text-slate-600 font-medium">Upload a CSV file to import multiple clients</p>
          </div>
        </div>

        {/* Main Card */}
        <div className="bg-white rounded-2xl border-2 border-slate-200 shadow-sm overflow-hidden">
          {/* Download Template */}
          <div className="px-6 py-4 border-b-2 border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-extrabold text-slate-900">Step 1: Get the Template</h2>
                <p className="text-sm text-slate-600 font-medium">Download and fill in your client data</p>
              </div>
              <a 
                href="/client-template.csv" 
                download
                className="flex items-center gap-2 px-4 py-2.5 bg-primary text-white rounded-xl font-bold text-sm hover:opacity-90 shadow-lg shadow-primary/25 transition-all"
              >
                <Download className="w-4 h-4" />
                Download Template
              </a>
            </div>
          </div>

          {/* Upload Section */}
          <div className="p-6">
            <h2 className="text-lg font-extrabold text-slate-900 mb-4">Step 2: Upload Your File</h2>
            
            {/* File Drop Zone */}
            <label 
              className={cn(
                "flex flex-col items-center justify-center p-8 border-2 border-dashed rounded-xl cursor-pointer transition-all",
                file 
                  ? "border-primary bg-primary/5" 
                  : "border-slate-300 bg-slate-50 hover:border-slate-400 hover:bg-slate-100"
              )}
            >
              <input
                type="file"
                accept=".csv"
                onChange={handleFileChange}
                className="hidden"
              />
              
              {file ? (
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-3">
                    <FileSpreadsheet className="w-6 h-6 text-primary" />
                  </div>
                  <p className="font-bold text-slate-900">{file.name}</p>
                  <p className="text-sm text-slate-500 font-medium mt-1">
                    {(file.size / 1024).toFixed(1)} KB
                  </p>
                  <button
                    type="button"
                    onClick={(e) => { e.preventDefault(); setFile(null); }}
                    className="mt-3 text-sm text-red-600 font-semibold hover:underline"
                  >
                    Remove file
                  </button>
                </div>
              ) : (
                <div className="text-center">
                  <div className="w-12 h-12 rounded-full bg-slate-200 flex items-center justify-center mx-auto mb-3">
                    <Upload className="w-6 h-6 text-slate-500" />
                  </div>
                  <p className="font-bold text-slate-700">Click to select a CSV file</p>
                  <p className="text-sm text-slate-500 font-medium mt-1">or drag and drop</p>
                </div>
              )}
            </label>

            {/* Upload Button */}
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="w-full mt-4 flex items-center justify-center gap-2 px-5 py-3 bg-primary text-white rounded-xl font-bold hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary/25 transition-all"
            >
              {uploading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" />
                  Upload & Import
                </>
              )}
            </button>
          </div>

          {/* Results */}
          {(result || error) && (
            <div className="px-6 pb-6">
              {result && (
                <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-4 flex items-start gap-3">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-bold text-emerald-800">Import Successful!</p>
                    <p className="text-sm text-emerald-700 font-medium mt-1">
                      Imported {result.clients} client{result.clients !== 1 ? 's' : ''}
                      {result.projects > 0 && ` and ${result.projects} project${result.projects !== 1 ? 's' : ''}`}
                    </p>
                  </div>
                </div>
              )}
              
              {error && (
                <div className="bg-red-50 border-2 border-red-200 rounded-xl p-4 flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="font-bold text-red-800">Import Failed</p>
                    <p className="text-sm text-red-700 font-medium mt-1">{error}</p>
                  </div>
                  <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Tips */}
        <div className="mt-6 p-4 bg-blue-50 border-2 border-blue-200 rounded-2xl">
          <h3 className="font-bold text-blue-900 mb-3">💡 CSV Format Tips</h3>
          <ul className="text-sm text-blue-800 font-medium space-y-2">
            <li>• First row should be headers: <code className="bg-blue-100 px-1 rounded">name,code</code></li>
            <li>• Client name is required, code is optional</li>
            <li>• Duplicates will be skipped automatically</li>
            <li>• Save your Excel file as CSV before uploading</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

export default ClientImport;