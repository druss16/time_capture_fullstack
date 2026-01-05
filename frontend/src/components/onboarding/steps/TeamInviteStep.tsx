// src/components/onboarding/steps/TeamInviteStep.tsx

import React, { useState } from 'react';
import { inviteTeam, skipTeamInvites, InviteInput, InviteResponse, InviteResult, Organization } from '../../../services/onboardingApi';
import { 
  Users, 
  Mail, 
  Plus, 
  Trash2, 
  CheckCircle, 
  AlertCircle,
  Loader2,
  ArrowRight,
  Copy,
  Check
} from 'lucide-react';

interface Role {
  value: 'admin' | 'manager' | 'member';
  label: string;
  description: string;
}

const ROLES: Role[] = [
  { value: 'admin', label: 'Admin', description: 'Full access, can manage team' },
  { value: 'manager', label: 'Manager', description: 'Approve timesheets, view reports' },
  { value: 'member', label: 'Member', description: 'Track time, submit timesheets' },
];

interface TeamInviteStepProps {
  organization: Organization | null;
  onComplete: () => void;
  onSkip: () => void;
}

export default function TeamInviteStep({ organization, onComplete, onSkip }: TeamInviteStepProps) {
  const [invites, setInvites] = useState<InviteInput[]>([
    { email: '', role: 'member', name: '' }
  ]);
  const [results, setResults] = useState<InviteResponse | { error: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const handleAddRow = () => {
    setInvites([...invites, { email: '', role: 'member', name: '' }]);
  };

  const handleRemoveRow = (idx: number) => {
    setInvites(invites.filter((_, i) => i !== idx));
  };

  const handleChange = (idx: number, field: keyof InviteInput, value: string) => {
    const updated = [...invites];
    if (field === 'role') {
      updated[idx][field] = value as 'admin' | 'manager' | 'member';
    } else {
      updated[idx][field] = value;
    }
    setInvites(updated);
  };

  const handleSubmit = async () => {
    const validInvites = invites.filter(i => i.email.trim());
    
    if (validInvites.length === 0) {
      onSkip();
      return;
    }

    setLoading(true);
    setResults(null);

    try {
      const data = await inviteTeam(validInvites);
      setResults(data);
      
      if (data.invited === data.total) {
        setTimeout(() => {
          onComplete();
        }, 2000);
      }
    } catch (err) {
      const error = err as { message?: string };
      setResults({ error: error.message || 'Failed to send invites' });
    } finally {
      setLoading(false);
    }
  };

  const handleCopyCredentials = (result: InviteResult, idx: number) => {
    const text = `Email: ${result.email}\nPassword: ${result.temp_password}`;
    navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  };

  const handleSkip = async () => {
    try {
      await skipTeamInvites();
    } catch (err) {
      // Continue anyway
    }
    onSkip();
  };

  // Check if results is a success response (has 'ok' property)
  const isSuccessResponse = (r: typeof results): r is InviteResponse => {
    return r !== null && 'ok' in r;
  };

  // Show results screen
  if (results && isSuccessResponse(results)) {
    const successResults = results.results?.filter(r => r.success) || [];
    const failedResults = results.results?.filter(r => !r.success) || [];

    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <CheckCircle className="w-8 h-8 text-green-600" />
          </div>
          <h2 className="text-2xl font-bold text-gray-900">
            {results.invited} Team Member{results.invited !== 1 ? 's' : ''} Invited!
          </h2>
          <p className="text-gray-600 mt-2">
            They'll receive an email with login instructions
          </p>
        </div>

        {/* Success Results */}
        {successResults.length > 0 && (
          <div className="space-y-3 mb-6">
            {successResults.map((result, idx) => (
              <div 
                key={idx}
                className="p-4 bg-green-50 border border-green-200 rounded-lg"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium text-gray-900">{result.email}</p>
                    <p className="text-sm text-gray-500">Role: {result.role}</p>
                  </div>
                  {!result.email_sent && (
                    <div className="text-right">
                      <p className="text-xs text-amber-600 mb-1">Email failed - share manually:</p>
                      <button
                        onClick={() => handleCopyCredentials(result, idx)}
                        className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1"
                      >
                        {copiedIdx === idx ? (
                          <>
                            <Check className="w-4 h-4" />
                            Copied!
                          </>
                        ) : (
                          <>
                            <Copy className="w-4 h-4" />
                            Copy credentials
                          </>
                        )}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Failed Results */}
        {failedResults.length > 0 && (
          <div className="space-y-3 mb-6">
            <p className="text-sm font-medium text-red-600">Failed to invite:</p>
            {failedResults.map((result, idx) => (
              <div 
                key={idx}
                className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between"
              >
                <span className="text-gray-900">{result.email}</span>
                <span className="text-sm text-red-600">{result.error}</span>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={onComplete}
          className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          Continue
          <ArrowRight className="w-5 h-5" />
        </button>
      </div>
    );
  }

  const errorMessage = results && 'error' in results ? results.error : null;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
      <div className="text-center mb-8">
        <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
          <Users className="w-8 h-8 text-blue-600" />
        </div>
        <h2 className="text-2xl font-bold text-gray-900">Invite Your Team</h2>
        <p className="text-gray-600 mt-2">
          They'll get an email with the desktop app download and login credentials
        </p>
      </div>

      {errorMessage && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 mt-0.5" />
          <p className="text-red-700">{errorMessage}</p>
        </div>
      )}

      {/* Invite Rows */}
      <div className="space-y-4 mb-6">
        {invites.map((invite, idx) => (
          <div key={idx} className="flex gap-3 items-start">
            <div className="flex-1">
              <input
                type="email"
                value={invite.email}
                onChange={(e) => handleChange(idx, 'email', e.target.value)}
                placeholder="team@yourfirm.com"
                className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
            <div className="w-32">
              <select
                value={invite.role}
                onChange={(e) => handleChange(idx, 'role', e.target.value)}
                className="w-full px-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
              >
                {ROLES.map(role => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </div>
            {invites.length > 1 && (
              <button
                onClick={() => handleRemoveRow(idx)}
                className="p-2.5 text-gray-400 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-5 h-5" />
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Add More Button */}
      <button
        onClick={handleAddRow}
        className="w-full py-2 border-2 border-dashed border-gray-300 text-gray-500 hover:border-blue-400 hover:text-blue-600 rounded-lg transition-colors flex items-center justify-center gap-2 mb-8"
      >
        <Plus className="w-5 h-5" />
        Add Another
      </button>

      {/* Role Descriptions */}
      <div className="bg-gray-50 rounded-lg p-4 mb-6">
        <p className="text-sm font-medium text-gray-700 mb-2">Role permissions:</p>
        <div className="space-y-1 text-sm text-gray-600">
          {ROLES.map(role => (
            <p key={role.value}>
              <span className="font-medium">{role.label}:</span> {role.description}
            </p>
          ))}
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-3">
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="flex-1 py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {loading ? (
            <>
              <Loader2 className="w-5 h-5 animate-spin" />
              Sending Invites...
            </>
          ) : (
            <>
              <Mail className="w-5 h-5" />
              Send Invites
            </>
          )}
        </button>
        
        <button
          onClick={handleSkip}
          disabled={loading}
          className="py-3 px-4 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-colors"
        >
          Skip for Now
        </button>
      </div>

      <p className="text-center text-sm text-gray-500 mt-4">
        You can invite more team members anytime from Settings
      </p>
    </div>
  );
}