// src/components/onboarding/OnboardingWizard.tsx
/**
 * Self-Service Onboarding Wizard - Teal Theme (matching login page)
 * With clickable step navigation and back button
 * 5-step flow: Account → Clients → Team → Plan → Download
 */

import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { getOnboardingStatus, Organization, OnboardingSteps } from '../../services/onboardingApi';

// Step components
import SignupStep from './steps/SignupStep';
import IntegrationStep from './steps/IntegrationStep';
import TeamInviteStep from './steps/TeamInviteStep';
import PricingStep from './steps/PricingStep';
import CompleteStep from './steps/CompleteStep';

// Icons
import { 
  UserPlus, 
  Link2, 
  Users, 
  CreditCard,
  Download,
  Check,
  ChevronRight,
  ChevronLeft,
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
  { id: 2, name: 'Import Clients', icon: Link2, key: 'integration_connected' },
  { id: 3, name: 'Invite Team', icon: Users, key: 'team_invited' },
  { id: 4, name: 'Choose Plan', icon: CreditCard, key: 'plan_selected' },
  { id: 5, name: 'Start Tracking', icon: Download, key: 'agent_installed' },
];

// Map URL step params to step numbers
const STEP_PARAM_MAP: Record<string, number> = {
  'signup': 1,
  'integration': 2,
  'team': 3,
  'pricing': 4,
  'complete': 5,
};

interface OnboardingWizardProps {
  initialStep?: number;
}

export function OnboardingWizard({ initialStep = 1 }: OnboardingWizardProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [currentStep, setCurrentStep] = useState(initialStep);
  const [highestStepReached, setHighestStepReached] = useState(initialStep);
  const [status, setStatus] = useState<{ steps: OnboardingSteps; is_complete: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [organization, setOrganization] = useState<Organization | null>(null);

  // Check if user is logged in (has completed step 1)
  const isLoggedIn = !!localStorage.getItem('auth_token');

  useEffect(() => {
    // Check for step override from URL (e.g., after Stripe cancel or success)
    const stepParam = searchParams.get('step');
    const sessionId = searchParams.get('session_id');
    
    // If returning from Stripe checkout with session_id = success
    if (sessionId) {
      setCurrentStep(5);
      setHighestStepReached(5);
      setLoading(false);
      
      if (isLoggedIn) {
        loadOrganizationOnly();
      }
      return;
    }
    
    // Handle explicit step parameter (e.g., ?step=pricing from Stripe cancel)
    if (stepParam && STEP_PARAM_MAP[stepParam]) {
      const targetStep = STEP_PARAM_MAP[stepParam];
      
      // Load org data but override the step
      if (isLoggedIn) {
        loadStatusWithStepOverride(targetStep);
      } else {
        setCurrentStep(targetStep);
        setHighestStepReached(targetStep);
        setLoading(false);
      }
      return;
    }
    
    // Normal flow - load status from server
    if (isLoggedIn) {
      loadStatus();
    } else {
      setLoading(false);
    }
  }, [searchParams]);

  const loadOrganizationOnly = async () => {
    try {
      const data = await getOnboardingStatus();
      setOrganization(data.organization);
    } catch (err) {
      console.error('Failed to load organization:', err);
    }
  };

  const loadStatusWithStepOverride = async (overrideStep: number) => {
    try {
      const data = await getOnboardingStatus();
      setStatus({ steps: data.steps, is_complete: data.is_complete });
      setOrganization(data.organization);
      
      if (data.is_complete) {
        navigate('/daily');
        return;
      }
      
      // Use the override step, but track highest reached from server
      const serverStep = data.current_step || 2;
      setCurrentStep(overrideStep);
      setHighestStepReached(Math.max(serverStep, overrideStep));
    } catch (err) {
      setCurrentStep(overrideStep);
      setHighestStepReached(overrideStep);
    } finally {
      setLoading(false);
    }
  };

  const loadStatus = async () => {
    try {
      const data = await getOnboardingStatus();
      setStatus({ steps: data.steps, is_complete: data.is_complete });
      setOrganization(data.organization);
      
      if (data.is_complete) {
        navigate('/daily');
        return;
      }
      
      // Set current step from server, but allow navigation back
      const serverStep = data.current_step || 2;
      setCurrentStep(serverStep);
      setHighestStepReached(serverStep);
    } catch (err) {
      // If API fails, clear potentially stale token and start fresh at step 1
      localStorage.removeItem('auth_token');
      setCurrentStep(1);
      setHighestStepReached(1);
    } finally {
      setLoading(false);
    }
  };

  const handleStepComplete = (stepNum: number, data?: { organization?: Organization }) => {
    if (data?.organization) {
      setOrganization(data.organization);
    }
    
    if (stepNum < 5) {
      const nextStep = stepNum + 1;
      setCurrentStep(nextStep);
      setHighestStepReached(Math.max(highestStepReached, nextStep));
    } else {
      navigate('/daily');
    }
  };

  const handleSkip = (stepNum: number) => {
    if (stepNum < 5) {
      const nextStep = stepNum + 1;
      setCurrentStep(nextStep);
      setHighestStepReached(Math.max(highestStepReached, nextStep));
    }
  };

  // Navigate to a specific step
  const goToStep = (stepId: number) => {
    // Can't go back to step 1 after signup
    if (stepId === 1 && isLoggedIn) return;
    
    // Can go to any step up to highest reached
    if (stepId >= 1 && stepId <= highestStepReached) {
      setCurrentStep(stepId);
    }
  };

  // Go back one step
  const handleBack = () => {
    const minStep = isLoggedIn ? 2 : 1;
    if (currentStep > minStep) {
      setCurrentStep(currentStep - 1);
    }
  };

  // Can we go back?
  const canGoBack = isLoggedIn ? currentStep > 2 : currentStep > 1;
  
  // Can this step be clicked?
  const canClickStep = (stepId: number) => {
    // Can't click step 1 if logged in
    if (stepId === 1 && isLoggedIn) return false;
    // Can click any step we've reached
    return stepId <= highestStepReached;
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-teal-500" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Header */}
      <header className="bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-5xl mx-auto px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-teal-500 rounded-xl flex items-center justify-center shadow-lg shadow-teal-500/25">
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

      {/* Progress Steps - Clickable */}
      <div className="bg-white border-b border-slate-200 py-4">
        <div className="max-w-5xl mx-auto px-4">
          <nav aria-label="Progress">
            <ol className="flex items-center justify-between">
              {STEPS.map((step, idx) => {
                const StepIcon = step.icon;
                const isComplete = currentStep > step.id;
                const isCurrent = currentStep === step.id;
                const isClickable = canClickStep(step.id);
                
                return (
                  <li key={step.id} className="flex items-center">
                    <button
                      type="button"
                      onClick={() => goToStep(step.id)}
                      disabled={!isClickable}
                      className={`
                        flex items-center gap-2 px-3 py-2 rounded-xl transition-all
                        ${isCurrent ? 'bg-teal-50 text-teal-700' : ''}
                        ${isComplete && !isCurrent ? 'text-teal-600' : ''}
                        ${!isComplete && !isCurrent ? 'text-slate-400' : ''}
                        ${isClickable && !isCurrent ? 'cursor-pointer hover:bg-slate-100 hover:text-teal-600' : ''}
                        ${!isClickable ? 'cursor-not-allowed opacity-60' : ''}
                      `}
                      title={isClickable ? `Go to ${step.name}` : (step.id === 1 && isLoggedIn ? 'Account already created' : 'Complete previous steps first')}
                    >
                      <div className={`
                        w-8 h-8 rounded-full flex items-center justify-center transition-all
                        ${isComplete ? 'bg-teal-100 text-teal-600' : ''}
                        ${isCurrent ? 'bg-teal-100 text-teal-600 ring-2 ring-teal-500 ring-offset-2' : ''}
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
                    </button>
                    
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
        {/* Back Button */}
        {canGoBack && (
          <button
            type="button"
            onClick={handleBack}
            className="mb-4 flex items-center gap-2 text-slate-600 hover:text-teal-600 font-medium transition-colors group"
          >
            <ChevronLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
            Back to {STEPS[currentStep - 2]?.name}
          </button>
        )}

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
          />
        )}
        
        {currentStep === 5 && (
          <CompleteStep 
            organization={organization}
            onComplete={() => handleStepComplete(5)} 
          />
        )}
      </main>
    </div>
  );
}

export default OnboardingWizard;