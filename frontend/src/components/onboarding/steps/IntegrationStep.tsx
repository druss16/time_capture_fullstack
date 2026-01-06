// src/components/onboarding/steps/IntegrationStep.tsx

import React, { useState, useEffect } from 'react';
import { 
  Link2, 
  Check, 
  ArrowRight, 
  ExternalLink, 
  Loader2,
  Calendar,
  Mail,
  FileText,
  Clock
} from 'lucide-react';
import { Organization, getIntegrations, Integration } from '../../../services/onboardingApi';

interface IntegrationStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
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
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);

  useEffect(() => {
    loadIntegrations();
  }, []);

  const loadIntegrations = async () => {
    try {
      const data = await getIntegrations();
      setIntegrations(data);
    } catch (err) {
      console.error('Failed to load integrations:', err);
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

  const connectedIds = integrations.filter(i => i.connected).map(i => i.provider);
  const hasAnyConnection = connectedIds.length > 0;

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-slate-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-emerald-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Link2 className="w-8 h-8 text-emerald-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900">Connect Your Tools</h2>
        <p className="text-slate-600 mt-2 font-medium">
          Import clients and sync your calendar for automatic time tracking
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-8 h-8 text-emerald-600 animate-spin" />
        </div>
      ) : (
        <div className="space-y-4 mb-8">
          {AVAILABLE_INTEGRATIONS.map((integration) => {
            const isConnected = connectedIds.includes(integration.id);
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
                  ) : integration.available ? (
                    <button
                      onClick={() => handleConnect(integration.id)}
                      disabled={isConnecting}
                      className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-xl transition-all disabled:opacity-50 shadow-lg shadow-emerald-600/25"
                    >
                      {isConnecting ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <>
                          Connect
                          <ExternalLink className="w-4 h-4" />
                        </>
                      )}
                    </button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Info Box */}
      <div className="mb-8 p-4 bg-slate-50 border-2 border-slate-200 rounded-xl">
        <div className="flex items-start gap-3">
          <Clock className="w-5 h-5 text-slate-400 mt-0.5" />
          <div>
            <p className="text-sm text-slate-600 font-medium">
              <strong className="text-slate-800">Don't see your tool?</strong> No problem! You can always add integrations later from Settings, or use TimeTracker standalone with manual client setup.
            </p>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={onComplete}
          disabled={!hasAnyConnection}
          className={`
            flex-1 py-3.5 px-4 font-bold rounded-xl transition-all flex items-center justify-center gap-2
            ${hasAnyConnection 
              ? 'bg-emerald-600 hover:bg-emerald-700 text-white shadow-lg shadow-emerald-600/25' 
              : 'bg-slate-100 text-slate-400 cursor-not-allowed'}
          `}
        >
          Continue
          <ArrowRight className="w-5 h-5" />
        </button>
        
        <button
          onClick={onSkip}
          className="px-6 py-3.5 border-2 border-slate-200 hover:border-slate-300 text-slate-700 font-bold rounded-xl transition-all hover:bg-slate-50"
        >
          Skip for now
        </button>
      </div>
    </div>
  );
}