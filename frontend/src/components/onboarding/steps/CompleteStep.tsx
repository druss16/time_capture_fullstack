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
  Clock,
  ExternalLink
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

export default function CompleteStep({ organization, onComplete }: CompleteStepProps) {
  const [copied, setCopied] = useState(false);
  const [platform, setPlatform] = useState<'macos' | 'windows'>('macos');
  const [installToken, setInstallToken] = useState<string | null>(null);

  useEffect(() => {
    // Detect platform
    const userAgent = navigator.userAgent.toLowerCase();
    if (userAgent.includes('win')) {
      setPlatform('windows');
    }
    
    // Load install token
    loadInstallToken();
  }, []);

  const loadInstallToken = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await fetch(`${baseUrl}/settings/install-token/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      });
      const data = await response.json();
      if (data.token) {
        setInstallToken(data.token);
      }
    } catch (err) {
      console.error('Failed to load install token:', err);
    }
  };

  const handleCopyToken = () => {
    if (installToken) {
      navigator.clipboard.writeText(installToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownload = (os: 'macos' | 'windows') => {
    const url = DOWNLOAD_URLS[os];
    if (url) {
      window.open(url, '_blank');
    } else {
      alert('Windows installer coming soon!');
    }
  };

  // Check if Windows is available
  const windowsAvailable = !!DOWNLOAD_URLS.windows;

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      {/* Success Header */}
      <div className="text-center mb-8">
        <div className="w-20 h-20 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4 relative">
          <CheckCircle2 className="w-10 h-10 text-emerald-600" />
          <Sparkles className="w-6 h-6 text-amber-500 absolute -top-1 -right-1" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">You're All Set! 🎉</h2>
        <p className="text-slate-600 mt-2 font-medium">
          {organization?.name} is ready for automatic time tracking
        </p>
      </div>

      {/* Trial Info */}
      <div className="mb-8 p-4 bg-emerald-50 border-2 border-emerald-200 rounded-xl">
        <div className="flex items-center gap-3">
          <Clock className="w-6 h-6 text-emerald-600" />
          <div>
            <p className="font-bold text-emerald-900">Your 7-day trial has started</p>
            <p className="text-sm text-emerald-700 font-medium">Full access to all features • No credit card required</p>
          </div>
        </div>
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
                ? 'border-emerald-500 bg-emerald-50' 
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
            <div className="flex items-center gap-1 text-emerald-600 font-semibold text-sm group-hover:underline">
              <Download className="w-4 h-4" />
              Download .pkg
            </div>
          </button>

          {/* Windows */}
          <button
            onClick={() => handleDownload('windows')}
            disabled={!windowsAvailable}
            className={`
              p-4 border-2 rounded-xl transition-all text-left group
              ${platform === 'windows' && windowsAvailable
                ? 'border-emerald-500 bg-emerald-50' 
                : 'border-slate-200 hover:border-slate-300'}
              ${!windowsAvailable ? 'opacity-60 cursor-not-allowed' : ''}
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
            <div className="flex items-center gap-1 text-emerald-600 font-semibold text-sm group-hover:underline">
              <Download className="w-4 h-4" />
              {windowsAvailable ? 'Download .exe' : 'Coming Soon'}
            </div>
          </button>
        </div>
      </div>

      {/* Install Token */}
      {installToken && (
        <div className="mb-8 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
          <h4 className="font-bold text-slate-900 mb-2">Organization Install Token</h4>
          <p className="text-sm text-slate-600 font-medium mb-3">
            Use this token during installation to connect your device
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-white border-2 border-slate-200 rounded-lg px-3 py-2 font-mono text-sm text-slate-700 truncate">
              {installToken}
            </code>
            <button
              onClick={handleCopyToken}
              className="p-2.5 border-2 border-slate-200 rounded-lg hover:bg-slate-100 transition-all"
            >
              {copied ? (
                <Check className="w-5 h-5 text-emerald-600" />
              ) : (
                <Copy className="w-5 h-5 text-slate-500" />
              )}
            </button>
          </div>
        </div>
      )}

      {/* Quick Start Steps */}
      <div className="mb-8">
        <h3 className="text-lg font-bold text-slate-900 mb-4">Quick Start</h3>
        <div className="space-y-3">
          {[
            { num: 1, text: 'Download and install the desktop app' },
            { num: 2, text: 'Sign in with your email and password' },
            { num: 3, text: 'The app runs in the background and tracks automatically' },
            { num: 4, text: 'Review and categorize your time in the dashboard' },
          ].map((step) => (
            <div key={step.num} className="flex items-center gap-3">
              <div className="w-8 h-8 bg-emerald-100 rounded-full flex items-center justify-center flex-shrink-0">
                <span className="text-sm font-bold text-emerald-700">{step.num}</span>
              </div>
              <p className="text-slate-700 font-medium">{step.text}</p>
            </div>
          ))}
        </div>
      </div>

      {/* CTA */}
      <button
        onClick={onComplete}
        className="w-full py-4 px-6 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-emerald-600/25"
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
          className="text-emerald-600 hover:text-emerald-700 font-semibold hover:underline inline-flex items-center gap-1"
        >
          View documentation
          <ExternalLink className="w-3 h-3" />
        </a>
      </p>
    </div>
  );
}