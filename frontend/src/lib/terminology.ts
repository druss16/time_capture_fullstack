// Vertical terminology.
//
// The same record is called different things by different professions: a law
// firm's Matter is a CPA firm's Engagement is an agency's Campaign. Only the
// word differs — the data, the queries and the billing are identical.
//
// The server resolves this per-org (tracker/industry_categories.py) and ships
// it on whoami, which every page already loads. Read it here rather than
// hardcoding a profession's vocabulary into a component.
//
// This is the only sanctioned way a vertical changes the product. If you find
// yourself writing `if (industry === 'legal')` around behaviour rather than
// wording, the app has started forking by accident.

import { useEffect, useState } from 'react';
import { fetchWhoAmI } from '@/lib/whoami';

export interface Terms {
  client: string;
  clients: string;
  project: string;
  projects: string;
  engagement: string;
  engagements: string;
  task_type: string;
  task_types: string;
  timesheet: string;
  billable_work: string;
}

/** Neutral wording, used until whoami resolves and for orgs with no vertical. */
export const DEFAULT_TERMS: Terms = {
  client: 'Client',
  clients: 'Clients',
  project: 'Project',
  projects: 'Projects',
  engagement: 'Engagement',
  engagements: 'Engagements',
  task_type: 'Task Type',
  task_types: 'Task Types',
  timesheet: 'Timesheet',
  billable_work: 'Billable Work',
};

let cached: Terms | null = null;

/**
 * This org's word for each concept.
 *
 * Returns DEFAULT_TERMS synchronously on first render, then re-renders once
 * whoami resolves. whoami is itself cached, so this costs one fetch per session
 * no matter how many components call it — and a failure degrades to neutral
 * wording rather than a blank label.
 */
export function useTerminology(): Terms {
  const [terms, setTerms] = useState<Terms>(cached ?? DEFAULT_TERMS);

  useEffect(() => {
    if (cached) return;
    let alive = true;
    fetchWhoAmI()
      .then((me) => {
        const t = me?.terminology;
        if (!alive || !t || typeof t !== 'object') return;
        cached = { ...DEFAULT_TERMS, ...(t as Partial<Terms>) };
        setTerms(cached);
      })
      .catch(() => {/* neutral wording is a fine fallback */});
    return () => { alive = false; };
  }, []);

  return terms;
}

/** Reset between impersonation switches, where the vertical can change. */
export function clearTerminologyCache(): void {
  cached = null;
}
