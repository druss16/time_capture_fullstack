// src/pages/account/DownloadPage.tsx
// Desktop agent download + device pairing — restyled to match design system

import React, { useState, useEffect } from 'react';
import { Download, Apple, Monitor, CheckCircle2 } from 'lucide-react';
import PairDeviceCard from '@/components/PairDeviceCard';
import { cn } from '@/lib/design-system';

const DOWNLOAD_URLS = {
  macos:   'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker.pkg',
  windows: 'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker-Windows-Setup.exe',
};

export default function DownloadPage() {
  const [platform, setPlatform] = useState<'macos' | 'windows'>('macos');

  useEffect(() => {
    if (navigator.userAgent.toLowerCase().includes('win')) setPlatform('windows');
  }, []);

  const handleDownload = (os: 'macos' | 'windows') => window.open(DOWNLOAD_URLS[os], '_blank');

  const STEPS = [
    { num: 1, title: 'Download the installer',  desc: 'Choose macOS or Windows above' },
    { num: 2, title: 'Run the installer',        desc: 'Double-click the downloaded file and follow prompts' },
    { num: 3, title: 'Enter pairing code',       desc: 'Copy the code below and paste it in the app' },
    { num: 4, title: 'Start tracking',           desc: 'The agent runs in the background automatically' },
  ];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-white rounded-xl border border-border/60 px-6 py-5 flex items-center gap-4">
        <div className="w-10 h-10 bg-primary/10 rounded-xl flex items-center justify-center shrink-0">
          <Download className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-slate-800">Download Desktop Agent</h2>
          <p className="text-xs text-slate-400 mt-0.5">Install the agent to automatically track your time</p>
        </div>
      </div>

      {/* Download buttons */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden">
        <div className="px-6 py-4 border-b border-border/50">
          <h3 className="text-sm font-extrabold text-slate-700">Choose your platform</h3>
        </div>
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* macOS */}
          <button onClick={() => handleDownload('macos')}
            className={cn(
              'p-4 border rounded-xl transition-all text-left group hover:shadow-sm',
              platform === 'macos' ? 'border-primary/30 bg-primary/5' : 'border-border/60 hover:border-primary/30 hover:bg-slate-50'
            )}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-slate-900 rounded-lg flex items-center justify-center shrink-0">
                <Apple className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="font-bold text-slate-800 text-sm">macOS</p>
                <p className="text-xs text-slate-400">Intel & Apple Silicon</p>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                <Download className="w-3.5 h-3.5" /> Download .pkg
              </span>
              {platform === 'macos' && (
                <span className="flex items-center gap-1 text-[10px] font-semibold text-emerald-600">
                  <CheckCircle2 className="w-3 h-3" /> Recommended
                </span>
              )}
            </div>
          </button>

          {/* Windows */}
          <button onClick={() => handleDownload('windows')}
            className={cn(
              'p-4 border rounded-xl transition-all text-left group hover:shadow-sm',
              platform === 'windows' ? 'border-primary/30 bg-primary/5' : 'border-border/60 hover:border-primary/30 hover:bg-slate-50'
            )}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center shrink-0">
                <Monitor className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="font-bold text-slate-800 text-sm">Windows</p>
                <p className="text-xs text-slate-400">Windows 10+</p>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-primary">
                <Download className="w-3.5 h-3.5" /> Download .exe
              </span>
              {platform === 'windows' && (
                <span className="flex items-center gap-1 text-[10px] font-semibold text-emerald-600">
                  <CheckCircle2 className="w-3 h-3" /> Recommended
                </span>
              )}
            </div>
          </button>
        </div>
      </div>

      {/* Pair device — shared component */}
      <PairDeviceCard />

      {/* Installation steps */}
      <div className="bg-white rounded-xl border border-border/60 overflow-hidden">
        <div className="px-6 py-4 border-b border-border/50">
          <h3 className="text-sm font-extrabold text-slate-700">Installation Steps</h3>
        </div>
        <div className="px-6 py-5 space-y-4">
          {STEPS.map((step, idx) => (
            <div key={step.num} className="flex items-start gap-4">
              <div className="w-7 h-7 bg-primary/10 rounded-full flex items-center justify-center shrink-0 mt-0.5">
                <span className="text-xs font-bold text-primary">{step.num}</span>
              </div>
              <div className={cn('flex-1 pb-4', idx < STEPS.length - 1 && 'border-b border-border/30')}>
                <p className="text-sm font-semibold text-slate-700">{step.title}</p>
                <p className="text-xs text-slate-400 mt-0.5">{step.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}