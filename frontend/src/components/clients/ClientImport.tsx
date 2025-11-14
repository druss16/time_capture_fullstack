// frontend/src/components/ClientImport.tsx

import { useState } from 'react';
import { uploadClientCSV } from '../api/clients';
import { API_BASE } from '@/lib/api';
import { postJson } from '@/lib/csrf';

export function ClientImport() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);


  const handleUpload = async () => {
    if (!file) return;
    
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const response = await fetch('/api/import-clients-csv/', {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
      
      const data = await response.json();
      setResult(data);
      alert(`✅ Imported ${data.clients} clients!`);
    } catch (error) {
      alert('❌ Upload failed');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="p-6">
      <h2>Import Clients from CSV</h2>
      
      {/* Download template */}
      <div className="mb-4">
        <a 
          href="/client-template.csv" 
          download
          className="text-blue-600 underline"
        >
          📥 Download CSV Template
        </a>
      </div>

      {/* Upload */}
      <input
        type="file"
        accept=".csv"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
      />
      
      <button
        onClick={handleUpload}
        disabled={!file || uploading}
        className="ml-4 px-4 py-2 bg-blue-600 text-white rounded"
      >
        {uploading ? 'Uploading...' : 'Upload Clients'}
      </button>

      {result && (
        <div className="mt-4 p-4 bg-green-50 rounded">
          ✅ Success! Imported {result.clients} clients and {result.projects} projects
        </div>
      )}
    </div>
  );
}