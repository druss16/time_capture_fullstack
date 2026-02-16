// src/pages/account/DownloadPage.tsx
/**
 * Download page for desktop agent installers
 * Uses shared PairDeviceCard component for device pairing
 */

import React, { useState, useEffect } from 'react';
import { Download, Apple, Monitor } from 'lucide-react';
import PairDeviceCard from '@/components/PairDeviceCard';

const DOWNLOAD_URLS = {
  macos: 'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker.pkg',
  windows: 'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker-Windows-Setup.exe',
};

export default function DownloadPage() {
  const [platform, setPlatform] = useState<'macos' | 'windows'>('macos');

  useEffect(() => {
    const userAgent = navigator.userAgent.toLowerCase();
    if (userAgent.includes('win')) {
      setPlatform('windows');
    }
  }, []);

  const handleDownload = (os: 'macos' | 'windows') => {
    window.open(DOWNLOAD_URLS[os], '_blank');
  };

  return (
    <div className="space-y-6">
      {/* Header Card */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 bg-emerald-100 rounded-2xl flex items-center justify-center">
            <Download className="w-7 h-7 text-emerald-600" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">Download Desktop Agent</h2>
            <p className="text-slate-500 font-medium">Install the agent to automatically track your time</p>
          </div>
        </div>

        {/* Download Buttons */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* macOS */}
          <button
            onClick={() => handleDownload('macos')}
            className={`p-5 border-2 rounded-xl transition-all text-left group hover:border-emerald-400 hover:shadow-md
              ${platform === 'macos' ? 'border-emerald-500 bg-emerald-50' : 'border-slate-200 bg-white'}`}
          >
            <div className="flex items-center gap-4 mb-3">
              <div className="w-12 h-12 bg-slate-900 rounded-xl flex items-center justify-center">
                <Apple className="w-7 h-7 text-white" />
              </div>
              <div>
                <p className="font-bold text-slate-900 text-lg">macOS</p>
                <p className="text-sm text-slate-500 font-medium">Intel & Apple Silicon</p>
              </div>
            </div>
            <div className="flex items-center gap-2 text-emerald-600 font-bold group-hover:underline">
              <Download className="w-5 h-5" />
              Download .pkg
            </div>
            {platform === 'macos' && (
              <p className="mt-2 text-xs text-emerald-600 font-medium">✓ Recommended for your system</p>
            )}
          </button>

          {/* Windows */}
          <button
            onClick={() => handleDownload('windows')}
            className={`p-5 border-2 rounded-xl transition-all text-left group hover:border-emerald-400 hover:shadow-md
              ${platform === 'windows' ? 'border-emerald-500 bg-emerald-50' : 'border-slate-200 bg-white'}`}
          >
            <div className="flex items-center gap-4 mb-3">
              <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center">
                <Monitor className="w-7 h-7 text-white" />
              </div>
              <div>
                <p className="font-bold text-slate-900 text-lg">Windows</p>
                <p className="text-sm text-slate-500 font-medium">Windows 10+</p>
              </div>
            </div>
            <div className="flex items-center gap-2 text-emerald-600 font-bold group-hover:underline">
              <Download className="w-5 h-5" />
              Download .exe
            </div>
            {platform === 'windows' && (
              <p className="mt-2 text-xs text-emerald-600 font-medium">✓ Recommended for your system</p>
            )}
          </button>
        </div>
      </div>

      {/* Pair Device Card - shared component */}
      <PairDeviceCard />

      {/* Installation Steps */}
      <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
        <h3 className="text-lg font-bold text-slate-900 mb-4">Installation Steps</h3>
        <div className="space-y-4">
          {[
            { num: 1, title: 'Download the installer', desc: 'Choose macOS or Windows above' },
            { num: 2, title: 'Run the installer', desc: 'Double-click the downloaded file and follow prompts' },
            { num: 3, title: 'Enter pairing code', desc: 'Copy the code above and paste it in the app' },
            { num: 4, title: 'Start tracking', desc: 'The agent runs in the background automatically' },
          ].map((step) => (
            <div key={step.num} className="flex items-start gap-4">
              <div className="w-8 h-8 bg-emerald-100 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
                <span className="text-sm font-bold text-emerald-700">{step.num}</span>
              </div>
              <div>
                <p className="font-bold text-slate-900">{step.title}</p>
                <p className="text-sm text-slate-500 font-medium">{step.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}