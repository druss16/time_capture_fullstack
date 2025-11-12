/**
 * WelcomeSetup.tsx - Welcome screen for onboarding wizard
 */
import React from 'react';

interface WelcomeSetupProps {
  onNext: () => void;
}

export function WelcomeSetup({ onNext }: WelcomeSetupProps) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-blue-100 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full bg-white rounded-2xl shadow-xl p-8 md:p-12">
        {/* Welcome Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-blue-100 mb-4">
            <span className="text-4xl">👋</span>
          </div>
          <h1 className="text-4xl font-bold text-gray-900 mb-4">
            Welcome to MavOps Time Tracking!
          </h1>
          <p className="text-xl text-gray-600">
            Let's get you set up in just a few easy steps
          </p>
        </div>

        {/* What You'll Do */}
        <div className="space-y-4 mb-8">
          <div className="flex items-start gap-4 p-4 bg-blue-50 rounded-lg">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              1
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-1">Import Your Clients</h3>
              <p className="text-gray-600 text-sm">
                Upload a CSV from QuickBooks or enter them manually
              </p>
            </div>
          </div>

          <div className="flex items-start gap-4 p-4 bg-blue-50 rounded-lg">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              2
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-1">Install Mac Agent</h3>
              <p className="text-gray-600 text-sm">
                Download the desktop app to start tracking your time automatically
              </p>
            </div>
          </div>

          <div className="flex items-start gap-4 p-4 bg-blue-50 rounded-lg">
            <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">
              3
            </div>
            <div>
              <h3 className="font-semibold text-gray-900 mb-1">Start Tracking</h3>
              <p className="text-gray-600 text-sm">
                Work as normal and review your auto-generated timecards daily
              </p>
            </div>
          </div>
        </div>

        {/* CTA */}
        <div className="text-center">
          <button
            onClick={onNext}
            className="w-full md:w-auto px-8 py-4 bg-blue-600 text-white rounded-lg font-semibold text-lg hover:bg-blue-700 transition-colors shadow-lg hover:shadow-xl transform hover:-translate-y-0.5 transition-all duration-150"
          >
            Get Started →
          </button>
          <p className="text-sm text-gray-500 mt-4">
            Takes less than 5 minutes
          </p>
        </div>
      </div>
    </div>
  );
}

export default WelcomeSetup;