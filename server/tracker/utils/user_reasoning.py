"""
Translate engineer-speak AI/classifier reasoning into plain language
for end-user display.

The raw `ai_disagreement_reasoning` field in Block contains the
classifier's internal evidence trail — things like:
  "Client 'X' matched via title_alias; Agent had 'Y' selected when
   this activity was captured; Learned title pattern 'desktop' (seen
   1x, 0/0 correct)"

That's invaluable for debugging in MavOpsAdmin but confusing for
end users. This module produces a short, plain-English version
suitable for the disagreement banner ("Show details" expansion still
shows the raw evidence panel).

Strategy: pattern-match on common reasoning fragments rather than
re-running classification. Keeps this file independent of the
classifier internals; if the classifier changes its phrasing, this
file degrades gracefully to "Suggested based on activity content."
"""

import re
from typing import Optional, Dict, Any


def humanize_reasoning(
    raw_reasoning: str,
    suggested_client_name: Optional[str] = None,
    block: Optional[Any] = None,
) -> str:
    """
    Translate raw classifier reasoning into user-facing text.

    Args:
      raw_reasoning: The engineer-speak string from ai_disagreement_reasoning
      suggested_client_name: The client the AI is proposing (for context)
      block: Optional Block object — used for event count if available

    Returns:
      A short, plain-English explanation suitable for the banner UI.

    Falls back to a generic message if the input can't be parsed.
    """
    if not raw_reasoning:
        return "Suggested based on activity content"

    raw = raw_reasoning.strip()

    # Try to extract the most user-relevant signal. Process in priority
    # order — strongest signal first. Stop at the first match.

    # Pattern 1: explicit title match
    # "Client 'X' matched via title_alias" or "matched via title_alias"
    title_match = re.search(
        r"matched via title_alias|title.*?(?:contains|mentions|references)",
        raw, re.IGNORECASE,
    )
    if title_match and suggested_client_name:
        return f'Activity title references "{suggested_client_name}"'

    # Pattern 2: file path match
    file_match = re.search(
        r"matched via (?:file_path|file_name|filename)",
        raw, re.IGNORECASE,
    )
    if file_match and suggested_client_name:
        return f'You opened a file related to "{suggested_client_name}"'

    # Pattern 3: URL / browser match
    url_match = re.search(
        r"matched via (?:url|url_host|domain)",
        raw, re.IGNORECASE,
    )
    if url_match and suggested_client_name:
        return f'You visited a web page for "{suggested_client_name}"'

    # Pattern 4: email / mail sender match
    mail_match = re.search(
        r"matched via mail|email from|mail signal",
        raw, re.IGNORECASE,
    )
    if mail_match and suggested_client_name:
        return f'You read email from "{suggested_client_name}"'

    # Pattern 5: calendar / meeting match
    cal_match = re.search(
        r"matched via calendar|calendar event|meeting with",
        raw, re.IGNORECASE,
    )
    if cal_match and suggested_client_name:
        return f'You had a meeting with "{suggested_client_name}"'

    # Pattern 6: AI / OpenAI classification (Stage 10)
    ai_match = re.search(
        r"AI (?:classified|determined|identified)|GPT|OpenAI|Stage 10",
        raw, re.IGNORECASE,
    )
    if ai_match and suggested_client_name:
        return f'AI matched this activity to "{suggested_client_name}"'

    # Pattern 7: learned rule
    learned_match = re.search(
        r"learned (?:rule|pattern|title)",
        raw, re.IGNORECASE,
    )
    if learned_match and suggested_client_name:
        return f'Past similar activity was attributed to "{suggested_client_name}"'

    # Fallback: generic message — we don't expose the engineer-speak,
    # but we still give the user enough to act on.
    if suggested_client_name:
        return f'Suggested attribution: "{suggested_client_name}"'
    return "Suggested based on activity content"


def humanize_for_api(block) -> str:
    """
    Convenience wrapper for API serializers — takes a Block, returns
    the human-readable reasoning. Pass this into API responses where
    the raw reasoning field is currently being exposed.
    """
    raw = getattr(block, 'ai_disagreement_reasoning', '') or ''
    name = None
    if getattr(block, 'ai_proposed_client_id', None):
        try:
            name = block.ai_proposed_client.name
        except Exception:
            pass
    return humanize_reasoning(raw, suggested_client_name=name, block=block)