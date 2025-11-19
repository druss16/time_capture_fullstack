// frontend/src/components/OnboardingWizard.tsx
import { useState } from 'react';

export function OnboardingWizard() {
  const [step, setStep] = useState(1);

  return (
    <div className="max-w-2xl mx-auto p-8">
      {step === 1 && (
        <div>
          <h1>Welcome to MavOps Time Tracking! 👋</h1>
          <p>Let's set up your clients in 3 easy steps...</p>
          <button onClick={() => setStep(2)}>Get Started →</button>
        </div>
      )}

      {step === 2 && (
        <div>
          <h2>Step 1: Import Your Clients</h2>
          <p>Choose how you want to add your clients:</p>
          
          <div className="grid grid-cols-2 gap-4">
            {/* Option A: Upload CSV */}
            <button 
              onClick={() => setStep(3)}
              className="p-6 border rounded hover:bg-blue-50"
            >
              📄 Upload CSV<br/>
              <small>From QuickBooks or Excel</small>
            </button>

            {/* Option B: Manual Entry */}
            <button 
              onClick={() => setStep(4)}
              className="p-6 border rounded hover:bg-blue-50"
            >
              ✍️ Enter Manually<br/>
              <small>Add one at a time</small>
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <ClientImport />
      )}

      {step === 4 && (
        <ManualClientEntry />
      )}
    </div>
  );
}