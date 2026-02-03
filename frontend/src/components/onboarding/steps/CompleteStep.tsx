// src/components/onboarding/steps/CompleteStep.tsx

import React, { useState, useEffect } from 'react';
import { 
  Download, 
  CheckCircle2, 
  Apple, 
  Monitor,
  Copy,
  Check,
  ArrowRight,
  Sparkles,
  ExternalLink,
  Smartphone,
  RefreshCw
} from 'lucide-react';
import { Organization } from '../../../services/onboardingApi';

interface CompleteStepProps {
  organization: Organization | null;
  onComplete: () => void;
}

const DOWNLOAD_URLS = {
  macos: 'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker.pkg',
  windows: 'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker-Windows-Setup.exe',
};

const RAW = (import.meta.env.VITE_API_BASE_URL || "http://localhost:7123").replace(/\/+$/, "");
const API_BASE = RAW.endsWith("/api") ? RAW : `${RAW}/api`;

export default function CompleteStep({ organization, onComplete }: CompleteStepProps) {
  const [copied, setCopied] = useState(false);
  const [platform, setPlatform] = useState<'macos' | 'windows'>('macos');
  
  // Pairing code state
  const [pairingCode, setPairingCode] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<Date | null>(null);
  const [timeLeft, setTimeLeft] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Detect platform
    const userAgent = navigator.userAgent.toLowerCase();
    if (userAgent.includes('win')) {
      setPlatform('windows');
    }
  }, []);

  // Countdown timer for pairing code
  useEffect(() => {
    const timer = setInterval(() => {
      if (!expiresAt) {
        setTimeLeft(0);
        return;
      }
      setTimeLeft(Math.max(0, Math.floor((expiresAt.getTime() - Date.now()) / 1000)));
    }, 500);
    return () => clearInterval(timer);
  }, [expiresAt]);

  const generatePairingCode = async () => {
    setError(null);
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/agents/pair/issue/`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ttl_seconds: 600 }),
      });
      
      if (!response.ok) {
        throw new Error('Failed to generate pairing code');
      }
      
      const data = await response.json();
      if (!data?.code) {
        throw new Error('Failed to issue code');
      }
      
      setPairingCode(data.code);
      setExpiresAt(new Date(data.expires_at));
    } catch (err: any) {
      setError(err.message || 'Error generating pairing code');
    } finally {
      setLoading(false);
    }
  };

  const handleCopyCode = () => {
    if (pairingCode) {
      navigator.clipboard.writeText(pairingCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const isExpired = !!expiresAt && Date.now() > expiresAt.getTime();

  const handleDownload = (os: 'macos' | 'windows') => {
    const url = DOWNLOAD_URLS[os];
    if (url) {
      window.open(url, '_blank');
    }
  };

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      {/* Success Header */}
      <div className="text-center mb-8">
        <div className="w-20 h-20 bg-teal-100 rounded-full flex items-center justify-center mx-auto mb-4 relative">
          <CheckCircle2 className="w-10 h-10 text-teal-600" />
          <Sparkles className="w-6 h-6 text-amber-500 absolute -top-1 -right-1" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">You're All Set! 🎉</h2>
        <p className="text-slate-600 mt-2 font-medium">
          {organization?.name} is ready for automatic time tracking
        </p>
      </div>

      {/* Download Section */}
      <div className="mb-8">
        <h3 className="text-lg font-bold text-slate-900 mb-4">Download Desktop App</h3>
        
        <div className="grid grid-cols-2 gap-4">
          {/* macOS */}
          <button
            onClick={() => handleDownload('macos')}
            className={`
              p-4 border-2 rounded-xl transition-all text-left group
              ${platform === 'macos' 
                ? 'border-teal-500 bg-teal-50' 
                : 'border-slate-200 hover:border-slate-300'}
            `}
          >
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 bg-slate-900 rounded-xl flex items-center justify-center">
                <Apple className="w-6 h-6 text-white" />
              </div>
              <div>
                <p className="font-bold text-slate-900">macOS</p>
                <p className="text-xs text-slate-500 font-medium">Intel & Apple Silicon</p>
              </div>
            </div>
            <div className="flex items-center gap-1 text-teal-600 font-semibold text-sm group-hover:underline">
              <Download className="w-4 h-4" />
              Download .pkg
            </div>
          </button>

          {/* Windows */}
          <button
            onClick={() => handleDownload('windows')}
            className={`
              p-4 border-2 rounded-xl transition-all text-left group
              ${platform === 'windows'
                ? 'border-teal-500 bg-teal-50' 
                : 'border-slate-200 hover:border-slate-300'}
            `}
          >
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center">
                <Monitor className="w-6 h-6 text-white" />
              </div>
              <div>
                <p className="font-bold text-slate-900">Windows</p>
                <p className="text-xs text-slate-500 font-medium">Windows 10+</p>
              </div>
            </div>
            <div className="flex items-center gap-1 text-teal-600 font-semibold text-sm group-hover:underline">
              <Download className="w-4 h-4" />
              Download .exe
            </div>
          </button>
        </div>
      </div>

      {/* Pairing Code Section */}
      <div className="mb-8 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
        <div className="flex items-center gap-2 mb-2">
          <Smartphone className="w-5 h-5 text-teal-600" />
          <h4 className="font-bold text-slate-900">Pairing Code</h4>
        </div>
        <p className="text-sm text-slate-600 font-medium mb-3">
          Enter this code in the desktop app to pair your device
        </p>
        
        {error && (
          <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm font-medium">
            {error}
          </div>
        )}
        
        {pairingCode && !isExpired ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-white border-2 border-slate-200 rounded-lg px-3 py-2.5 font-mono text-2xl text-slate-800 tracking-widest text-center font-bold">
                {pairingCode}
              </code>
              <button
                onClick={handleCopyCode}
                className="p-2.5 border-2 border-slate-200 rounded-lg hover:bg-slate-100 transition-all"
                title="Copy to clipboard"
              >
                {copied ? (
                  <Check className="w-5 h-5 text-teal-600" />
                ) : (
                  <Copy className="w-5 h-5 text-slate-500" />
                )}
              </button>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-slate-500 font-medium">
                Expires in <span className="font-bold text-slate-700">{timeLeft}s</span>
              </span>
              <button
                onClick={generatePairingCode}
                disabled={loading}
                className="text-sm text-teal-600 hover:text-teal-700 font-semibold flex items-center gap-1"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                Regenerate
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={generatePairingCode}
            disabled={loading}
            className="w-full py-2.5 px-4 bg-teal-500 hover:bg-teal-600 text-white font-semibold rounded-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {loading ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Generating...
              </>
            ) : isExpired ? (
              <>
                <RefreshCw className="w-4 h-4" />
                Code Expired - Generate New
              </>
            ) : (
              <>
                <Smartphone className="w-4 h-4" />
                Generate Pairing Code
              </>
            )}
          </button>
        )}
      </div>

      {/* Quick Start Steps */}
      <div className="mb-8">
        <h3 className="text-lg font-bold text-slate-900 mb-4">Quick Start</h3>
        <div className="space-y-3">
          {[
            { num: 1, text: 'Download and install the desktop app' },
            { num: 2, text: 'Generate a pairing code and enter it in the app' },
            { num: 3, text: 'The app runs in the background and tracks automatically' },
            { num: 4, text: 'Review and categorize your time in the dashboard' },
          ].map((step) => (
            <div key={step.num} className="flex items-center gap-3">
              <div className="w-8 h-8 bg-teal-100 rounded-full flex items-center justify-center flex-shrink-0">
                <span className="text-sm font-bold text-teal-700">{step.num}</span>
              </div>
              <p className="text-slate-700 font-medium">{step.text}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <button
        onClick={onComplete}
        className="w-full py-4 px-6 bg-teal-500 hover:bg-teal-600 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-teal-500/25"
      >
        Go to Dashboard
        <ArrowRight className="w-5 h-5" />
      </button>

      {/* Help Link */}
      <p className="mt-4 text-center text-sm text-slate-500 font-medium">
        Need help?{' '}
        <a 
          href="https://timetracker.mavops.ai/help" 
          target="_blank" 
          rel="noopener noreferrer"
          className="text-teal-600 hover:text-teal-700 font-semibold hover:underline inline-flex items-center gap-1"
        >
          View documentation
          <ExternalLink className="w-3 h-3" />
        </a>
      </p>
    </div>
  );
}