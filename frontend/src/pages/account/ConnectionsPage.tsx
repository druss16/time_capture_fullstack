/**
 * ConnectionsPage.tsx
 *
 * Account → Connections page. Hosts per-user OAuth integrations.
 * Each tab handles its own status, OAuth flow, and rendering;
 * this page just stacks them with a shared page header.
 */

import CalendarConnectionTab from '@/components/CalendarConnectionTab';
import MailConnectionTab from '@/components/MailConnectionTab';

export default function ConnectionsPage() {
  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Connections</h1>
        <p className="text-sm text-slate-500 mt-1">
          Connect external services so TimeTracker can attribute time to clients more accurately.
        </p>
      </div>

      <CalendarConnectionTab />

      <div className="border-t border-slate-200" />

      <MailConnectionTab />
    </div>
  );
}