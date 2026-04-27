"""
tracker/services/rules/llm_suggestion.py

LLM #1 — Rule Suggestion Service.

PURPOSE
-------
Given a description of a firm (industry, software they use, client list,
billing model, special quirks), use OpenAI to propose a starting set of
rules. Output is constrained to {template_id, params} pairs — the LLM
can ONLY produce rules in shapes the system understands. No hallucinated
behaviors, no free-form expression.

WHEN IT RUNS
------------
Once during onboarding, or when MavOps clicks "Suggest Rules" in the
admin UI. Output is reviewed by MavOps before any rule is created.

NEVER runs at inference time. Suggestions are configuration, not
execution.

USAGE
-----
    from tracker.services.rules.llm_suggestion import LLMRuleSuggestionService

    service = LLMRuleSuggestionService()
    suggestions = service.suggest(
        firm_context={
            'firm_name': 'TL Wall Accounting',
            'industry': 'CPA / Tax',
            'tax_software': ['UltraTax', 'TaxWise'],
            'accounting_software': ['QuickBooks Desktop'],
            'billing_model': 'hourly with fixed-fee tax returns',
            'client_count': 200,
            'folder_convention': r'Z:\Clients\<ClientName>\',
            'notes': 'Wants TaxWise/UltraTax to always be Internal-Tax. '
                     'Flags any block over 4 hours for Wayne to review.',
        },
        org=org,
    )

    for s in suggestions:
        print(s['template_id'], s['params'], s['reasoning'])
"""

import json
import logging
import os
import urllib.request
from typing import Optional

from tracker.services.rules.templates import (
    RULE_TEMPLATES,
    list_templates,
    validate_template_params,
)

logger = logging.getLogger(__name__)

OPENAI_MODEL = 'gpt-4o-mini'
OPENAI_URL = 'https://api.openai.com/v1/chat/completions'


class LLMRuleSuggestionService:
    """Generate rule suggestions for a firm via OpenAI."""

    def __init__(self, api_key: Optional[str] = None, model: str = OPENAI_MODEL):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY', '')
        self.model = model

    def suggest(self, firm_context: dict, org=None, max_suggestions: int = 25) -> list[dict]:
        """
        Returns a list of {template_id, params, reasoning, priority} dicts.

        Each suggestion is validated against the template schema before
        returning. Invalid suggestions are dropped (with a log warning),
        not auto-corrected.
        """
        if not self.api_key:
            logger.warning('[LLM-SUGGEST] No OpenAI API key — returning empty suggestions')
            return []

        # Augment firm_context with org-specific data the LLM needs
        if org is not None:
            firm_context = self._augment_with_org_data(firm_context, org)

        prompt_user = self._build_user_prompt(firm_context, max_suggestions)
        prompt_system = self._build_system_prompt()

        try:
            raw = self._call_openai(prompt_system, prompt_user)
            parsed = self._parse_response(raw)
        except Exception as e:
            logger.exception(f'[LLM-SUGGEST] Failed: {e}')
            return []

        # Validate each suggestion against the template schema
        valid = []
        for item in parsed:
            tid = item.get('template_id')
            params = item.get('params', {})

            if tid not in RULE_TEMPLATES:
                logger.warning(f'[LLM-SUGGEST] Unknown template_id: {tid!r} — skipping')
                continue

            ok, err = validate_template_params(tid, params)
            if not ok:
                logger.warning(f'[LLM-SUGGEST] Invalid params for {tid!r}: {err} — skipping')
                continue

            valid.append({
                'template_id': tid,
                'params': params,
                'reasoning': item.get('reasoning', ''),
                'priority': item.get('priority', 100),
                'preview_card': self._render_preview(tid, params, firm_context),
            })

        logger.info(f'[LLM-SUGGEST] Generated {len(valid)} valid suggestions of {len(parsed)} raw')
        return valid[:max_suggestions]

    # -------------------------------------------------------------
    # Org data augmentation
    # -------------------------------------------------------------

    @staticmethod
    def _augment_with_org_data(firm_context: dict, org) -> dict:
        """Add org-specific data the LLM needs to make grounded suggestions."""
        from tracker.models import Client
        from tracker.industry_categories import get_categories_for_industry

        clients = list(
            Client.objects.filter(org=org, is_active=True)
            .values('id', 'name')[:100]
        )

        try:
            categories = get_categories_for_industry(
                getattr(org, 'industry_type', 'general')
            )
        except Exception:
            categories = []

        return {
            **firm_context,
            '_org_clients': clients,
            '_org_categories': categories,
        }

    # -------------------------------------------------------------
    # Prompts
    # -------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        # Build a compact manifest of available templates so the LLM
        # knows exactly what shapes it can emit.
        manifest = []
        for tid, t in RULE_TEMPLATES.items():
            field_specs = [
                f"{f['name']} ({f['type']}, "
                f"{'required' if f.get('required', True) else 'optional'})"
                for f in t['user_fields']
            ]
            manifest.append(
                f"  - {tid}\n"
                f"      label: {t['label']}\n"
                f"      category: {t['category']}\n"
                f"      runs_at: {t['runs_at']}\n"
                f"      what it does: {t['description']}\n"
                f"      example: {t['example']}\n"
                f"      params: {', '.join(field_specs) if field_specs else '(none)'}"
            )
        templates_block = '\n'.join(manifest)

        return f"""You are a rule design assistant for TimeTracker, a time-tracking SaaS for CPA firms.

Your job: given a description of a CPA firm (their software, billing model, client list, and quirks), suggest a starting set of rules that will produce accurate, well-categorized time entries.

You can ONLY suggest rules using one of these templates. Do not invent new templates or fields.

AVAILABLE TEMPLATES:
{templates_block}

OUTPUT FORMAT — you MUST respond with valid JSON in this exact shape:
{{
  "suggestions": [
    {{
      "template_id": "...",
      "params": {{ ... }},
      "reasoning": "Why this rule helps this firm specifically",
      "priority": 100
    }},
    ...
  ]
}}

PRIORITY GUIDELINES:
  500 = hard rule (org-specific, near-certain match like "TaxWise → Internal-Tax")
  300 = baseline (default behavior the firm wants)
  100 = soft (preference, often overridden by other signals)

DESIGN PRINCIPLES:
1. Be specific to THIS firm. Use their actual client names, software, folder paths.
2. Cover the high-frequency cases first (tax software, email apps, common clients).
3. Don't suggest a rule unless the firm context implies they want it.
4. Pair routing rules with categorization rules where appropriate.
5. Suggest 1-3 flagging rules max — over-flagging creates review fatigue.
6. NEVER suggest a rule with empty params or made-up template_ids."""

    @staticmethod
    def _build_user_prompt(firm_context: dict, max_suggestions: int) -> str:
        # Pull out internal fields (prefixed with _) from public ones
        public_ctx = {k: v for k, v in firm_context.items() if not k.startswith('_')}

        clients_summary = ''
        if firm_context.get('_org_clients'):
            sample = firm_context['_org_clients'][:20]
            clients_summary = '\n\nKNOWN CLIENTS IN THIS FIRM (sample):\n' + '\n'.join(
                f'  - id={c["id"]}: {c["name"]}' for c in sample
            )

        categories_summary = ''
        if firm_context.get('_org_categories'):
            categories_summary = (
                '\n\nALLOWED CATEGORIES FOR THIS FIRM:\n  '
                + ', '.join(firm_context['_org_categories'])
            )

        return f"""FIRM CONTEXT:
{json.dumps(public_ctx, indent=2)}
{clients_summary}
{categories_summary}

Suggest up to {max_suggestions} rules tailored to this firm. Respond with the JSON shape specified."""

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
            'temperature': 0.2,
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        return data['choices'][0]['message']['content']

    @staticmethod
    def _parse_response(raw: str) -> list[dict]:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f'[LLM-SUGGEST] Could not parse OpenAI response as JSON: {e}')
            return []

        if isinstance(parsed, dict):
            return parsed.get('suggestions', [])
        if isinstance(parsed, list):
            return parsed
        return []

    @staticmethod
    def _render_preview(template_id: str, params: dict, firm_context: dict) -> str:
        """Render a friendly preview of what the rule would look like as a card."""
        template = RULE_TEMPLATES[template_id]
        # Best-effort: substitute params into card_template
        try:
            # If a target_client_id was given, look up the name for display
            if 'target_client_id' in params and firm_context.get('_org_clients'):
                client_name = next(
                    (c['name'] for c in firm_context['_org_clients']
                     if c['id'] == params['target_client_id']),
                    f"client #{params['target_client_id']}",
                )
                params = {**params, 'target_client_name': client_name}

            # Map user-field names to their target field names
            display_params = {**params}
            for f in template['user_fields']:
                if f['name'] in params:
                    display_params[f['maps_to'].split('.')[-1]] = params[f['name']]

            # Common substitutions
            display_params.setdefault('match_value', params.get('app_family') or params.get('keyword') or params.get('path_fragment', ''))
            display_params.setdefault('target_category', params.get('category', ''))
            display_params.setdefault('threshold_minutes', params.get('min_minutes') or params.get('max_idle_minutes', ''))
            display_params.setdefault('flag_reason', params.get('reason', ''))

            return template['card_template'].format(**display_params)
        except (KeyError, ValueError):
            return f"{template['label']} ({params})"