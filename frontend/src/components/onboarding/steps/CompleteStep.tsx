// src/components/onboarding/steps/CompleteStep.tsx

import React, { useState, useEffect } from 'react';
import { completeOnboarding, getDownloadInfo, DownloadInfoResponse, Organization } from '../../../services/onboardingApi';
import { 
  CheckCircle, 
  Download, 
  Apple, 
  Monitor,
  Clock,
  Users,
  FileText,
  ArrowRight,
  Loader2,
  ExternalLink,
  Sparkles
} from 'lucide-react';

interface CompleteStepProps {
  organization: Organization | null;
  onComplete: () => void;
}

export default function CompleteStep({ organization, onComplete }: CompleteStepProps) {
  const [downloadInfo, setDownloadInfo] = useState<DownloadInfoResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [downloadData] = await Promise.all([
        getDownloadInfo(),
        completeOnboarding(),
      ]);
      setDownloadInfo(downloadData);
    } catch (err) {
      console.error('Failed to load completion data:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = (os: 'macos' | 'windows') => {
    const url = downloadInfo?.downloads?.[os]?.url;
    if (url) {
      window.open(url, '_blank');
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

  const detectedOS = downloadInfo?.detected_os || 'macos';

  return (
    <div className="space-y-6">
      {/* Success Header */}
      <div className="bg-gradient-to-r from-green-500 to-emerald-600 rounded-xl p-8 text-white text-center">
        <div className="w-20 h-20 bg-white/20 rounded-full flex items-center justify-center mx-auto mb-4">
          <CheckCircle className="w-10 h-10" />
        </div>
        <h2 className="text-2xl font-bold mb-2">You're All Set! 🎉</h2>
        <p className="text-green-100">
          {organization?.name} is ready for automatic time tracking
        </p>
      </div>

      {/* Download Section */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <div className="text-center mb-6">
          <h3 className="text-xl font-bold text-gray-900 mb-2">
            Download the Desktop App
          </h3>
          <p className="text-gray-600">
            The app runs quietly in the background and tracks time automatically
          </p>
        </div>

        {/* OS Download Buttons */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
          {/* macOS */}
          <button
            onClick={() => handleDownload('macos')}
            className={`
              p-4 border-2 rounded-xl flex items-center gap-4 transition-all
              ${detectedOS === 'macos' 
                ? 'border-blue-500 bg-blue-50' 
                : 'border-gray-200 hover:border-gray-300'}
            `}
          >
            <div className="w-12 h-12 bg-gray-100 rounded-xl flex items-center justify-center">
              <Apple className="w-6 h-6 text-gray-700" />
            </div>
            <div className="text-left flex-1">
              <p className="font-medium text-gray-900">macOS</p>
              <p className="text-sm text-gray-500">
                {downloadInfo?.downloads?.macos?.requirements || 'macOS 12+'}
              </p>
            </div>
            <Download className="w-5 h-5 text-blue-600" />
          </button>

          {/* Windows */}
          <button
            onClick={() => handleDownload('windows')}
            className={`
              p-4 border-2 rounded-xl flex items-center gap-4 transition-all
              ${detectedOS === 'windows' 
                ? 'border-blue-500 bg-blue-50' 
                : 'border-gray-200 hover:border-gray-300'}
            `}
          >
            <div className="w-12 h-12 bg-gray-100 rounded-xl flex items-center justify-center">
              <Monitor className="w-6 h-6 text-gray-700" />
            </div>
            <div className="text-left flex-1">
              <p className="font-medium text-gray-900">Windows</p>
              <p className="text-sm text-gray-500">
                {downloadInfo?.downloads?.windows?.requirements || 'Windows 10+'}
              </p>
            </div>
            <Download className="w-5 h-5 text-blue-600" />
          </button>
        </div>

        {/* Installation Steps */}
        <div className="bg-gray-50 rounded-lg p-4">
          <p className="text-sm font-medium text-gray-700 mb-3">
            Quick Setup ({detectedOS === 'macos' ? 'macOS' : 'Windows'}):
          </p>
          <ol className="space-y-2 text-sm text-gray-600">
            {(downloadInfo?.instructions?.[detectedOS] || []).map((step, idx) => (
              <li key={idx} className="flex gap-2">
                <span className="font-medium text-blue-600">{idx + 1}.</span>
                {step}
              </li>
            ))}
          </ol>
        </div>
      </div>

      {/* Quick Tips */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-yellow-500" />
          Quick Tips to Get Started
        </h3>
        
        <div className="space-y-4">
          <div className="flex gap-4">
            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
              <Clock className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <p className="font-medium text-gray-900">Select your client</p>
              <p className="text-sm text-gray-600">
                Click the menu bar icon and select the client you're working on.
                Time is tracked automatically.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0">
              <FileText className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <p className="font-medium text-gray-900">Review your timesheet</p>
              <p className="text-sm text-gray-600">
                Check your weekly timesheet to review and adjust AI-categorized time.
                You'll get a reminder on Fridays.
              </p>
            </div>
          </div>

          <div className="flex gap-4">
            <div className="w-10 h-10 bg-purple-100 rounded-lg flex items-center justify-center flex-shrink-0">
              <Users className="w-5 h-5 text-purple-600" />
            </div>
            <div>
              <p className="font-medium text-gray-900">Get your team onboard</p>
              <p className="text-sm text-gray-600">
                The more people using TimeTracker, the better your firm's utilization
                insights become.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Action Button */}
      <button
        onClick={onComplete}
        className="w-full py-4 px-6 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl transition-colors flex items-center justify-center gap-2 text-lg"
      >
        Go to Dashboard
        <ArrowRight className="w-5 h-5" />
      </button>

      {/* Help Link */}
      <p className="text-center text-sm text-gray-500">
        Need help?{' '}
        <a href="/help" className="text-blue-600 hover:underline inline-flex items-center gap-1">
          View our getting started guide
          <ExternalLink className="w-3 h-3" />
        </a>
      </p>
    </div>
  );
}