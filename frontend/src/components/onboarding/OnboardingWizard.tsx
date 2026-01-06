// src/components/onboarding/OnboardingWizard.tsx
/**
 * Self-Service Onboarding Wizard - Green Theme
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getOnboardingStatus, Organization, OnboardingSteps } from '../../services/onboardingApi';

// Step components
import SignupStep from './steps/SignupStep';
import IntegrationStep from './steps/IntegrationStep';
import TeamInviteStep from './steps/TeamInviteStep';
import PricingStep from './steps/PricingStep';
import BillingRatesStep from './steps/BillingRatesStep';
import CompleteStep from './steps/CompleteStep';

// Icons
import { 
  UserPlus, 
  Link2, 
  Users, 
  CreditCard,
  DollarSign, 
  Download,
  Check,
  ChevronRight,
  Clock,
  LucideIcon
} from 'lucide-react';

interface Step {
  id: number;
  name: string;
  icon: LucideIcon;
  key: keyof OnboardingSteps | 'plan_selected';
}

const STEPS: Step[] = [
  { id: 1, name: 'Create Account', icon: UserPlus, key: 'account_created' },
  { id: 2, name: 'Connect Integration', icon: Link2, key: 'integration_connected' },
  { id: 3, name: 'Invite Team', icon: Users, key: 'team_invited' },
  { id: 4, name: 'Choose Plan', icon: CreditCard, key: 'plan_selected' },
  { id: 5, name: 'Set Rates', icon: DollarSign, key: 'rates_configured' },
  { id: 6, name: 'Start Tracking', icon: Download, key: 'agent_installed' },
];

interface OnboardingWizardProps {
  initialStep?: number;
}

export function OnboardingWizard({ initialStep = 1 }: OnboardingWizardProps) {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(initialStep);
  const [status, setStatus] = useState<{ steps: OnboardingSteps; is_complete: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [organization, setOrganization] = useState<Organization | null>(null);

  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    if (token && currentStep > 1) {
      loadStatus();
    } else {
      setLoading(false);
    }
  }, []);

  const loadStatus = async () => {
    try {
      const data = await getOnboardingStatus();
      setStatus({ steps: data.steps, is_complete: data.is_complete });
      setOrganization(data.organization);
      
      if (data.is_complete) {
        navigate('/daily');
        return;
      }
      
      setCurrentStep(data.current_step);
    } catch (err) {
      setCurrentStep(1);
    } finally {
      setLoading(false);
    }
  };

  const handleStepComplete = (stepNum: number, data?: { organization?: Organization }) => {
    if (data?.organization) {
      setOrganization(data.organization);
    }
    
    if (stepNum < 6) {
      setCurrentStep(stepNum + 1);
    } else {
      navigate('/daily');
    }
  };

  const handleSkip = (stepNum: number) => {
    if (stepNum < 6) {
      setCurrentStep(stepNum + 1);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-600" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-5xl mx-auto px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-emerald-600 rounded-xl flex items-center justify-center shadow-lg shadow-emerald-600/25">
              <Clock className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">TimeTracker</h1>
              {organization && (
                <p className="text-sm text-slate-500 font-medium">{organization.name}</p>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Progress Steps */}
      <div className="bg-white border-b border-slate-200 py-4">
        <div className="max-w-5xl mx-auto px-4">
          <nav aria-label="Progress">
            <ol className="flex items-center justify-between">
              {STEPS.map((step, idx) => {
                const StepIcon = step.icon;
                const isComplete = (status?.steps?.[step.key as keyof OnboardingSteps]) || currentStep > step.id;
                const isCurrent = currentStep === step.id;
                
                return (
                  <li key={step.id} className="flex items-center">
                    <div className={`
                      flex items-center gap-2 px-3 py-2 rounded-xl transition-all
                      ${isCurrent ? 'bg-emerald-50 text-emerald-700' : ''}
                      ${isComplete && !isCurrent ? 'text-emerald-600' : ''}
                      ${!isComplete && !isCurrent ? 'text-slate-400' : ''}
                    `}>
                      <div className={`
                        w-8 h-8 rounded-full flex items-center justify-center transition-all
                        ${isComplete ? 'bg-emerald-100 text-emerald-600' : ''}
                        ${isCurrent ? 'bg-emerald-100 text-emerald-600 ring-2 ring-emerald-600 ring-offset-2' : ''}
                        ${!isComplete && !isCurrent ? 'bg-slate-100 text-slate-400' : ''}
                      `}>
                        {isComplete ? (
                          <Check className="w-4 h-4" />
                        ) : (
                          <StepIcon className="w-4 h-4" />
                        )}
                      </div>
                      <span className="hidden sm:block text-sm font-semibold">
                        {step.name}
                      </span>
                    </div>
                    
                    {idx < STEPS.length - 1 && (
                      <ChevronRight className="w-5 h-5 text-slate-300 mx-2" />
                    )}
                  </li>
                );
              })}
            </ol>
          </nav>
        </div>
      </div>

      {/* Step Content */}
      <main className="max-w-2xl mx-auto px-4 py-8">
        {currentStep === 1 && (
          <SignupStep 
            onComplete={(data) => handleStepComplete(1, data)} 
          />
        )}
        
        {currentStep === 2 && (
          <IntegrationStep 
            organization={organization}
            onComplete={() => handleStepComplete(2)} 
            onSkip={() => handleSkip(2)}
          />
        )}
        
        {currentStep === 3 && (
          <TeamInviteStep 
            organization={organization}
            onComplete={() => handleStepComplete(3)} 
            onSkip={() => handleSkip(3)}
          />
        )}
        
        {currentStep === 4 && (
          <PricingStep 
            organizationId={organization?.id || 0}
            onComplete={() => handleStepComplete(4)}
            onStartTrial={() => handleStepComplete(4)}
          />
        )}
        
        {currentStep === 5 && (
          <BillingRatesStep 
            organization={organization}
            onComplete={() => handleStepComplete(5)} 
            onSkip={() => handleSkip(5)}
          />
        )}
        
        {currentStep === 6 && (
          <CompleteStep 
            organization={organization}
            onComplete={() => handleStepComplete(6)} 
          />
        )}
      </main>
    </div>
  );
}

export default OnboardingWizard;