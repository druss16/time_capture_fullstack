"""
tracker/services/rules/llm_parser.py

LLM #2 — Natural Language Rule Parser.

PURPOSE
-------
Convert a plain-English rule description into a {template_id, params} pair.
Used in the admin UI as a power-user shortcut: type the rule, see the form
pre-filled, confirm and save.

Constrained output: the LLM can only produce rules in known template shapes.
If the user describes something that doesn't map to any template, return
an empty result with an explanation (so the UI can say "I can't express
this — try one of these templates instead").

WHEN IT RUNS
------------
On-demand from the admin UI when MavOps clicks "Parse rule" with a text
input. Single API call, single parse. Output is reviewed before being
persisted.

USAGE
-----
    from tracker.services.rules.llm_parser import LLMRuleParserService

    service = LLMRuleParserService()
    result = service.parse(
        text='Flag any block over 4 hours and mark it as needs partner review',
        org=org,
    )

    if result['matched']:
        # Pre-fill the template form
        template_id = result['template_id']  # 'flag_long_blocks'
        params = result['params']            # {'min_minutes': 240, 'reason': '...'}
    else:
        # Show the user what we couldn't parse
        explanation = result['explanation']
        suggestions = result['suggested_templates']
"""

import json
import logging
import os
import urllib.request
from typing import Optional

from tracker.services.rules.templates import (
    RULE_TEMPLATES,
    validate_template_params,
)

logger = logging.getLogger(__name__)

OPENAI_MODEL = 'gpt-4o-mini'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'


class LLMRuleParserService:
    """Parse natural language into a rule template + params."""

    def __init__(self, api_key: Optional[str] = None, model: str = OPENAI_MODEL):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY', '')
        self.model = model

    def parse(self, text: str, org=None) -> dict:
        """
        Returns:
          {
            'matched': True,
            'template_id': '...',
            'params': {...},
            'confidence': 0.0-1.0,
            'reasoning': 'why this template matches',
          }

        OR (if no template fits):
          {
            'matched': False,
            'explanation': 'why it didn't match',
            'suggested_templates': ['template_id', ...],   # nearest matches
          }
        """
        if not self.api_key:
            return {'matched': False, 'explanation': 'OpenAI not configured', 'suggested_templates': []}

        if not (text or '').strip():
            return {'matched': False, 'explanation': 'Empty input', 'suggested_templates': []}

        # Augment with org data so the LLM knows actual client/category names
        org_context = self._build_org_context(org)

        try:
            raw = self._call_openai(
                self._build_system_prompt(),
                self._build_user_prompt(text, org_context),
            )
            parsed = json.loads(raw)
        except Exception as e:
            logger.exception(f'[LLM-PARSE] Failed: {e}')
            return {'matched': False, 'explanation': f'Parse failed: {e}', 'suggested_templates': []}

        # Sanity-check the result
        if not parsed.get('matched'):
            return {
                'matched': False,
                'explanation': parsed.get('explanation', 'No matching template.'),
                'suggested_templates': parsed.get('suggested_templates', []),
            }

        tid = parsed.get('template_id')
        params = parsed.get('params', {})

        if tid not in RULE_TEMPLATES:
            return {
                'matched': False,
                'explanation': f'LLM proposed unknown template: {tid!r}',
                'suggested_templates': list(RULE_TEMPLATES.keys()),
            }

        ok, err = validate_template_params(tid, params)
        if not ok:
            return {
                'matched': False,
                'explanation': f'LLM proposed {tid!r} but params invalid: {err}',
                'suggested_templates': [tid],
            }

        return {
            'matched': True,
            'template_id': tid,
            'params': params,
            'confidence': float(parsed.get('confidence', 0.7)),
            'reasoning': parsed.get('reasoning', ''),
        }

    # -------------------------------------------------------------
    # Org context
    # -------------------------------------------------------------

    @staticmethod
    def _build_org_context(org) -> dict:
        if org is None:
            return {}
        from tracker.models import Client
        from tracker.industry_categories import get_categories_for_industry

        clients = list(
            Client.objects.filter(org=org, is_active=True)
            .values('id', 'name')[:50]
        )
        try:
            categories = get_categories_for_industry(
                getattr(org, 'industry_type', 'general')
            )
        except Exception:
            categories = []

        return {
            'org_name':   getattr(org, 'name', ''),
            'clients':    clients,
            'categories': categories,
        }

    # -------------------------------------------------------------
    # Prompts
    # -------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        manifest = []
        for tid, t in RULE_TEMPLATES.items():
            field_specs = [
                f"{f['name']} ({f['type']})"
                for f in t['user_fields']
            ]
            manifest.append(
                f"  - {tid}: {t['description']}\n"
                f"      params: {', '.join(field_specs) if field_specs else '(none)'}\n"
                f"      example: {t['example']}"
            )
        templates_block = '\n'.join(manifest)

        return f"""You are a rule parser for TimeTracker, a time-tracking SaaS for CPA firms.

The user will describe a rule in plain English. Your job: map it to ONE of the known templates below, OR explain why it doesn't fit any of them.

AVAILABLE TEMPLATES:
{templates_block}

RESPONSE FORMAT — respond with valid JSON in ONE of these two shapes:

If a template fits:
{{
  "matched": true,
  "template_id": "...",
  "params": {{ ... }},
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of why this template matches"
}}

If nothing fits:
{{
  "matched": false,
  "explanation": "Why no template fits, in 1-2 sentences",
  "suggested_templates": ["closest_template_id_1", "closest_template_id_2"]
}}

RULES:
1. Only emit template_ids that appear in the list above. NEVER invent one.
2. All required params for the chosen template MUST be present.
3. If the user says "always" or "every time," that's a high-priority rule (300+).
4. If the user names a specific client, look it up in the org context provided.
5. If the user names a category, use one from the categories list.
6. If you're under 0.6 confident, set "matched": false and explain.
7. NEVER ask follow-up questions. Either parse or explain why you can't."""

    @staticmethod
    def _build_user_prompt(text: str, org_context: dict) -> str:
        ctx_block = ''
        if org_context:
            ctx_block = '\n\nORG CONTEXT (for resolving names):\n' + json.dumps(org_context, indent=2)
        return f"USER RULE DESCRIPTION:\n{text}{ctx_block}"

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
            'temperature': 0.0,
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