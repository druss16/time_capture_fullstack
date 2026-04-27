"""
server/tracker/views_rule_templates.py

API endpoints for the template-based rule system + LLM services.
Mount these in your URL config (see urls_patch.py).

ENDPOINTS
---------
GET    /api/mavops/rule-templates/
       List all templates + dropdown options for the picker UI.

POST   /api/mavops/orgs/<org_id>/rules/from-template/
       Create a rule from a (template_id, params) pair.

POST   /api/mavops/orgs/<org_id>/rules/suggest/
       LLM #1 — suggest rules from firm context.

POST   /api/mavops/orgs/<org_id>/rules/parse/
       LLM #2 — parse natural language into a (template_id, params) pair.

GET    /api/mavops/blocks/<block_id>/explain/
       LLM #3 — explain why a block was categorized this way.

ALL ENDPOINTS REQUIRE: is_staff (MavOps internal only for v1).
"""

import logging

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication
from tracker.models import Organization, Client, Block, OrgRoutingRule
from tracker.views_mavops import IsStaff
from tracker.services.rules.templates import (
    RULE_TEMPLATES,
    list_templates,
    get_template,
    build_rule_from_template,
    validate_template_params,
)
from tracker.services.rules.matcher import EXE_FAMILIES

logger = logging.getLogger(__name__)


# ============================================================================
# GET /api/mavops/rule-templates/
# ============================================================================

@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def list_rule_templates(request):
    """
    Return all templates plus the dropdown options the picker UI needs.

    Query params:
      org_id (optional) — if given, also returns the org's clients
                          and categories for grouped picker rendering.
    """
    org_id = request.GET.get('org_id')
    org = None
    org_clients = []
    org_categories = []

    if org_id:
        try:
            org = Organization.objects.get(id=org_id)
            org_clients = list(
                Client.objects.filter(org=org, is_active=True)
                .values('id', 'name')
                .order_by('name')
            )
            try:
                from tracker.industry_categories import get_categories_for_industry
                org_categories = get_categories_for_industry(
                    getattr(org, 'industry_type', 'general')
                )
            except Exception:
                org_categories = []
        except Organization.DoesNotExist:
            return Response({'error': 'Org not found'}, status=404)

    return Response({
        'templates': list_templates(),
        'options': {
            'exe_families':   sorted(EXE_FAMILIES.keys()),
            'org_clients':    org_clients,
            'org_categories': org_categories,
        },
        'org': {'id': org.id, 'name': org.name} if org else None,
    })


# ============================================================================
# POST /api/mavops/orgs/<org_id>/rules/from-template/
# ============================================================================

@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def create_rule_from_template(request, org_id):
    """
    Create one rule from a (template_id, params) pair.

    Body:
      {
        "template_id": "assign_category_by_app_family",
        "params": {"app_family": "taxwise", "category": "Tax Preparation"},
        "priority": 300,
        "enabled": true,
        "description": "TL Wall: TaxWise → Tax Prep"
      }
    """
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Org not found'}, status=404)

    data = request.data
    template_id = data.get('template_id')
    params = data.get('params', {})

    if not template_id:
        return Response({'error': 'template_id required'}, status=400)

    try:
        kwargs = build_rule_from_template(
            template_id=template_id,
            params=params,
            org=org,
            priority=int(data.get('priority', 100)),
            enabled=bool(data.get('enabled', True)),
            description=data.get('description', ''),
            created_by=request.user,
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=400)

    # If target_client_id is in kwargs, validate it belongs to this org
    target_client_id = kwargs.get('target_client_id')
    if target_client_id:
        if not Client.objects.filter(id=target_client_id, org=org).exists():
            return Response(
                {'error': f'target_client_id {target_client_id} not in this org'},
                status=400,
            )

    rule = OrgRoutingRule.objects.create(**kwargs)
    return Response({'ok': True, 'rule_id': rule.id})


# ============================================================================
# POST /api/mavops/orgs/<org_id>/rules/from-template/bulk/
# ============================================================================

@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def bulk_create_rules_from_templates(request, org_id):
    """
    Create multiple rules at once. Used by the LLM Suggest workflow
    where MavOps approves N suggestions in one click.

    Body:
      {
        "suggestions": [
          {"template_id": "...", "params": {...}, "priority": 300},
          ...
        ]
      }
    """
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Org not found'}, status=404)

    suggestions = request.data.get('suggestions', [])
    if not isinstance(suggestions, list) or not suggestions:
        return Response({'error': 'suggestions must be a non-empty list'}, status=400)

    created = []
    failed = []
    for s in suggestions:
        try:
            kwargs = build_rule_from_template(
                template_id=s['template_id'],
                params=s.get('params', {}),
                org=org,
                priority=int(s.get('priority', 100)),
                enabled=bool(s.get('enabled', True)),
                description=s.get('description', ''),
                created_by=request.user,
            )
            rule = OrgRoutingRule.objects.create(**kwargs)
            created.append({'rule_id': rule.id, 'template_id': s['template_id']})
        except Exception as e:
            failed.append({'template_id': s.get('template_id'), 'error': str(e)})

    return Response({
        'ok': True,
        'created_count': len(created),
        'failed_count': len(failed),
        'created': created,
        'failed': failed,
    })


# ============================================================================
# POST /api/mavops/orgs/<org_id>/rules/suggest/   (LLM #1)
# ============================================================================

@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def suggest_rules(request, org_id):
    """
    LLM #1 — given firm context, suggest rules.

    Body:
      {
        "firm_context": {
          "firm_name": "...",
          "industry": "CPA / Tax",
          "tax_software": ["UltraTax", "TaxWise"],
          "billing_model": "...",
          "notes": "..."
        },
        "max_suggestions": 25
      }

    Returns suggestions for review — does NOT create rules. Use the
    bulk-create endpoint to persist after MavOps approves.
    """
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Org not found'}, status=404)

    firm_context = request.data.get('firm_context', {})
    max_suggestions = int(request.data.get('max_suggestions', 25))

    from tracker.services.rules.llm_suggestion import LLMRuleSuggestionService
    service = LLMRuleSuggestionService()
    suggestions = service.suggest(
        firm_context=firm_context,
        org=org,
        max_suggestions=max_suggestions,
    )

    return Response({
        'org': {'id': org.id, 'name': org.name},
        'suggestions': suggestions,
        'count': len(suggestions),
    })


# ============================================================================
# POST /api/mavops/orgs/<org_id>/rules/parse/   (LLM #2)
# ============================================================================

@api_view(['POST'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def parse_rule(request, org_id):
    """
    LLM #2 — parse natural language into a {template_id, params} pair.

    Body:
      {
        "text": "Flag any block over 4 hours for partner review"
      }

    Returns a pre-fillable template form. Does NOT create the rule.
    """
    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        return Response({'error': 'Org not found'}, status=404)

    text = (request.data.get('text') or '').strip()
    if not text:
        return Response({'error': 'text required'}, status=400)

    from tracker.services.rules.llm_parser import LLMRuleParserService
    service = LLMRuleParserService()
    result = service.parse(text=text, org=org)

    return Response(result)


# ============================================================================
# GET /api/mavops/blocks/<block_id>/explain/   (LLM #3)
# ============================================================================

@api_view(['GET'])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated, IsStaff])
def explain_block(request, block_id):
    """
    LLM #3 — explain why a block was categorized the way it was.
    """
    try:
        block = Block.objects.select_related('client', 'org').get(id=block_id)
    except Block.DoesNotExist:
        return Response({'error': 'Block not found'}, status=404)

    from tracker.services.rules.llm_explanation import LLMRuleExplanationService
    service = LLMRuleExplanationService()
    explanation = service.explain(block)

    return Response(explanation)