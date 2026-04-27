"""
tracker/services/rules/llm_explanation.py

LLM #3 — Rule Explanation Service.

PURPOSE
-------
When MavOps (or eventually a customer) asks "why was this block
categorized this way?" — read the RuleFireLog rows for that block,
the rules that almost-fired, and the block's metadata, and produce
a plain-English explanation.

The audit log is the source of truth. The LLM only translates structured
data into prose. It can't make up a story that isn't backed by log data.

WHEN IT RUNS
------------
On-demand when MavOps clicks "Why?" on a block in the dashboard.
Single API call per click.

USAGE
-----
    from tracker.services.rules.llm_explanation import LLMRuleExplanationService

    service = LLMRuleExplanationService()
    explanation = service.explain(block)

    print(explanation['summary'])         # 1-2 sentences
    print(explanation['details'])          # paragraph
    print(explanation['fires'])            # structured data shown alongside
    print(explanation['near_misses'])      # rules that almost fired
"""

import json
import logging
import os
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

OPENAI_MODEL = 'gpt-4o-mini'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'


class LLMRuleExplanationService:
    """Explain why a block ended up the way it did."""

    def __init__(self, api_key: Optional[str] = None, model: str = OPENAI_MODEL):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY', '')
        self.model = model

    def explain(self, block) -> dict:
        """
        Returns:
          {
            'summary': str,           # 1-sentence headline
            'details': str,           # paragraph with context
            'fires': [...],           # raw RuleFireLog rows shown
            'near_misses': [...],     # rules that matched but didn't terminate
          }
        """
        # Pull the structured data first
        fires = self._get_fires(block)
        near_misses = self._get_near_misses(block, fires)
        block_summary = self._summarize_block(block)

        # If LLM isn't configured, return the structured data with a basic summary
        if not self.api_key:
            return {
                'summary': self._fallback_summary(block, fires),
                'details': '',
                'fires': fires,
                'near_misses': near_misses,
            }

        try:
            raw = self._call_openai(
                self._build_system_prompt(),
                self._build_user_prompt(block_summary, fires, near_misses),
            )
            parsed = json.loads(raw)
        except Exception as e:
            logger.exception(f'[LLM-EXPLAIN] Failed: {e}')
            parsed = {'summary': self._fallback_summary(block, fires), 'details': ''}

        return {
            'summary': parsed.get('summary', '') or self._fallback_summary(block, fires),
            'details': parsed.get('details', ''),
            'fires': fires,
            'near_misses': near_misses,
        }

    # -------------------------------------------------------------
    # Data gathering
    # -------------------------------------------------------------

    @staticmethod
    def _get_fires(block) -> list[dict]:
        """All rule fires for this block, ordered by time."""
        try:
            from tracker.models import RuleFireLog
            fires = (
                RuleFireLog.objects
                .filter(block=block)
                .select_related('rule')
                .order_by('fired_at')
            )
            return [{
                'rule_id':     f.rule_id,
                'rule_match':  f'{f.rule.match_type}={f.rule.match_value!r}' if f.rule else '?',
                'rule_action': f.rule.action if f.rule else '?',
                'engine':      f.engine,
                'context':     f.context,
                'outcome':     f.outcome,
                'fired_at':    f.fired_at.isoformat(),
            } for f in fires]
        except Exception as e:
            logger.warning(f'[LLM-EXPLAIN] Failed to fetch fires: {e}')
            return []

    @staticmethod
    def _get_near_misses(block, fires: list) -> list[dict]:
        """
        Rules that COULD have fired but didn't (because a higher-priority
        rule fired first, or because they were just below threshold).

        For now, return the org's other classifier-stage rules that
        match the block's title/exe — these are the "what if" candidates
        the explainer might reference.
        """
        try:
            from tracker.models import OrgRoutingRule
            from tracker.services.rules.matcher import build_context, rule_to_dict, rule_matches

            fired_rule_ids = {f['rule_id'] for f in fires}

            candidates = OrgRoutingRule.objects.filter(
                org=block.org,
                enabled=True,
            ).exclude(id__in=fired_rule_ids).order_by('-priority')[:25]

            ctx = build_context(
                title=getattr(block, 'window_title', '') or '',
                exe=(getattr(block, 'app_name', '') or '').lower(),
                file_path=getattr(block, 'file_path', '') or '',
                duration_minutes=block.minutes,
                has_attributed_client=bool(block.client_id),
            )

            near = []
            for r in candidates:
                if rule_matches(rule_to_dict(r), ctx):
                    near.append({
                        'rule_id':     r.id,
                        'rule_match':  f'{r.match_type}={r.match_value!r}',
                        'rule_action': r.action,
                        'priority':    r.priority,
                        'reason_skipped': 'Lower priority — another rule won',
                    })

            return near[:10]
        except Exception as e:
            logger.warning(f'[LLM-EXPLAIN] Failed to fetch near-misses: {e}')
            return []

    @staticmethod
    def _summarize_block(block) -> dict:
        """Compact summary of the block for the LLM prompt."""
        return {
            'id': block.id,
            'window_title':  (getattr(block, 'window_title', '') or '')[:200],
            'app_name':      getattr(block, 'app_name', '') or '',
            'file_path':     (getattr(block, 'file_path', '') or '')[:200],
            'duration_min':  block.minutes,
            'client':        block.client.name if block.client_id else None,
            'category':      list(block.category_hours.keys())[0] if block.category_hours else None,
            'is_billable':   block.is_billable,
            'needs_review':  block.needs_review,
            'review_reason': block.review_reason or None,
            'categorized_by': block.categorized_by,
        }

    # -------------------------------------------------------------
    # Prompts
    # -------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        return """You are an explanation assistant for TimeTracker. The user is a MavOps admin trying to understand why a specific time block ended up the way it did.

You are given:
1. The block's metadata (title, app, duration, client, category)
2. The list of rules that fired on this block (the "fires")
3. The list of rules that matched but didn't fire because higher-priority ones won (the "near misses")

Your job: explain in plain English what happened.

RESPOND IN JSON:
{
  "summary": "One sentence — the headline. E.g. 'Routed to Internal-Tax because rule #47 matched UltraTax.'",
  "details": "A short paragraph (3-5 sentences) walking through the chain. Mention which rules fired, why they matched, and what each did. If there were near-misses, note which would have been chosen instead."
}

RULES:
1. Only state things the data supports. Do not speculate beyond the fires/near-misses provided.
2. Reference rules by their match condition (e.g. "the TaxWise app-family rule") not just by ID.
3. If no rules fired, say so — and explain that classification came from default logic.
4. Be concise. The MavOps admin is debugging, not reading a tutorial."""

    @staticmethod
    def _build_user_prompt(block_summary: dict, fires: list, near_misses: list) -> str:
        return f"""BLOCK:
{json.dumps(block_summary, indent=2)}

RULES THAT FIRED ({len(fires)}):
{json.dumps(fires, indent=2) if fires else '(none — block was classified by default logic, not by org rules)'}

RULES THAT ALMOST FIRED ({len(near_misses)}):
{json.dumps(near_misses, indent=2) if near_misses else '(none)'}

Explain what happened."""

    # -------------------------------------------------------------
    # OpenAI call
    # -------------------------------------------------------------

    def _call_openai(self, system: str, user: str) -> str:
        payload = json.dumps({
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user',   'content': user},
            ],
            'temperature': 0.1,
            'response_format': {'type': 'json_object'},
        }).encode()

        req = urllib.request.Request(
            OPENAI_URL,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        return data['choices'][0]['message']['content']

    @staticmethod
    def _fallback_summary(block, fires: list) -> str:
        """If LLM is unavailable, render a basic summary from the data."""
        if not fires:
            return (
                f'No org rules fired on this block. Classification came from '
                f'default logic ({block.categorized_by or "unknown"}).'
            )
        f = fires[0]
        return (
            f'Rule #{f["rule_id"]} ({f["rule_match"]}) fired in the '
            f'{f["engine"]} engine, action: {f["rule_action"]}.'
        )