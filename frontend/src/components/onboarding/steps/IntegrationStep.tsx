// src/components/onboarding/steps/IntegrationStep.tsx

import React, { useState, useEffect } from 'react';
import { getIntegrations, connectIntegration, skipIntegration, Integration, Organization } from '../../../services/onboardingApi';
import { Link2, CheckCircle, ExternalLink, Loader2, ArrowRight } from 'lucide-react';

interface IntegrationStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
}

export default function IntegrationStep({ organization, onComplete, onSkip }: IntegrationStepProps) {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState<string | null>(null);
  const [hasClients, setHasClients] = useState(false);

  useEffect(() => {
    loadIntegrations();
  }, []);

  const loadIntegrations = async () => {
    try {
      const data = await getIntegrations();
      setIntegrations(data.integrations);
      setHasClients(data.has_clients);
    } catch (err) {
      console.error('Failed to load integrations:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleConnect = async (provider: string) => {
    setConnecting(provider);
    try {
      const data = await connectIntegration(provider);
      
      if (data.oauth_url) {
        alert(`OAuth integration coming soon! For now, you can add clients manually or import via CSV.`);
      }
    } catch (err) {
      console.error('Connection failed:', err);
    } finally {
      setConnecting(null);
    }
  };

  const handleSkip = async () => {
    try {
      await skipIntegration();
      onSkip();
    } catch (err) {
      onSkip();
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
        <h2 className="text-2xl font-bold text-gray-900">Connect Your Practice Management</h2>
        <p className="text-gray-600 mt-2">
          Auto-import clients and contacts from your existing system
        </p>
      </div>

      {/* Integration Options */}
      <div className="space-y-4 mb-8">
        {integrations.map((integration) => (
          <div
            key={integration.id}
            className={`
              border rounded-lg p-4 flex items-center justify-between
              ${integration.connected ? 'border-green-200 bg-green-50' : 'border-gray-200 hover:border-blue-300'}
            `}
          >
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-gray-100 rounded-lg flex items-center justify-center overflow-hidden">
                <span className="text-lg font-bold text-gray-400">
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
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50"
              >
                {connecting === integration.id ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>
                    Connect
                    <ExternalLink className="w-4 h-4" />
                  </>
                )}
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Already Connected Notice */}
      {hasClients && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-lg">
          <div className="flex items-center gap-2 text-green-700">
            <CheckCircle className="w-5 h-5" />
            <span className="font-medium">Clients already imported!</span>
          </div>
          <p className="text-sm text-green-600 mt-1">
            You can continue to the next step.
          </p>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-3">
        {hasClients || integrations.some(i => i.connected) ? (
          <button
            onClick={onComplete}
            className="flex-1 py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            Continue
            <ArrowRight className="w-5 h-5" />
          </button>
        ) : (
          <button
            onClick={handleSkip}
            className="flex-1 py-3 px-4 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors"
          >
            Skip for Now
          </button>
        )}
      </div>

      <p className="text-center text-sm text-gray-500 mt-4">
        You can always connect integrations later from Settings
      </p>
    </div>
  );
}