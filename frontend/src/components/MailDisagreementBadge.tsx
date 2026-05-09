/**
 * MailDisagreementBadge.tsx
 *
 * Small inline component shown next to a block in Daily Review when
 * Stage 7 mail signals point to a different client than the block was
 * attributed to. Lets the user accept the mail-proposed client, dismiss
 * the suggestion, or view the reasoning.
 *
 * Save at: Frontend/src/components/MailDisagreementBadge.tsx
 *
 * Then in your Daily Review block list, render it conditionally:
 *
 *   {block.mail_disagrees_with_agent && (
 *     <MailDisagreementBadge
 *       block={block}
 *       onAccept={() => handleReassign(block.id, block.mail_proposed_client_id)}
 *       onDismiss={() => handleDismiss(block.id)}
 *     />
 *   )}
 */

import { useState } from 'react';
import { Mail, AlertTriangle, Check, X } from 'lucide-react';

interface BlockWithMailDisagreement {
  id: number;
  client_name?: string | null;
  mail_disagrees_with_agent: boolean;
  mail_proposed_client_id: number | null;
  mail_proposed_client_name: string;
  mail_proposed_confidence: number | null;
  mail_disagreement_reasoning: string;
}

interface Props {
  block: BlockWithMailDisagreement;
  onAccept: () => void | Promise<void>;
  onDismiss: () => void | Promise<void>;
}

export default function MailDisagreementBadge({ block, onAccept, onDismiss }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [working, setWorking] = useState<'accept' | 'dismiss' | null>(null);

  const handleAccept = async () => {
    setWorking('accept');
    try {
      await onAccept();
    } finally {
      setWorking(null);
    }
  };

  const handleDismiss = async () => {
    setWorking('dismiss');
    try {
      await onDismiss();
    } finally {
      setWorking(null);
    }
  };

  const confPct = block.mail_proposed_confidence
    ? Math.round(block.mail_proposed_confidence * 100)
    : 0;

  return (
    <div className="mt-2 border border-amber-200 bg-amber-50/60 rounded-lg p-3 text-sm">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-start gap-2 w-full text-left"
      >
        <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-amber-900">
            Email suggests a different client
          </div>
          <div className="text-xs text-amber-800 mt-0.5">
            Attributed to{' '}
            <span className="font-semibold">{block.client_name || '(none)'}</span>,
            but email metadata points to{' '}
            <span className="font-semibold">{block.mail_proposed_client_name}</span>
            {confPct > 0 && (
              <span className="ml-1 text-amber-700">({confPct}% confidence)</span>
            )}
          </div>
        </div>
      </button>

      {expanded && (
        <div className="mt-2 pt-2 border-t border-amber-200/70 text-xs text-amber-900 space-y-2">
          <div className="flex items-start gap-1.5">
            <Mail className="w-3 h-3 mt-0.5 shrink-0" />
            <span className="leading-relaxed">{block.mail_disagreement_reasoning}</span>
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              onClick={handleAccept}
              disabled={working !== null}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold bg-amber-600 hover:bg-amber-700 text-white rounded-md disabled:opacity-50 transition-colors"
            >
              <Check className="w-3 h-3" />
              {working === 'accept' ? 'Reassigning…' : `Reassign to ${block.mail_proposed_client_name}`}
            </button>
            <button
              type="button"
              onClick={handleDismiss}
              disabled={working !== null}
              className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100 rounded-md disabled:opacity-50 transition-colors"
            >
              <X className="w-3 h-3" />
              {working === 'dismiss' ? 'Dismissing…' : 'Dismiss'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}