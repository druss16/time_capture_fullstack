"""
Views for managing OrgRoutingRule records.

Scope:
  - MavOps staff (is_staff=True) can edit rules for any org
  - Firm admins (org_admin=True for their org) can edit non-default rules for their own org
  - Regular users: read-only list
"""

import re
import json
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import F
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from tracker.models import OrgRoutingRule, Organization, Client

# -------------------------------------------------------------------
# Permission helper
# -------------------------------------------------------------------

def _can_edit_rules(user, org):
    """MavOps staff OR firm owner/admin of the target org can edit."""
    if user.is_staff:
        return True
    from tracker.models import OrganizationMembership
    return OrganizationMembership.objects.filter(
        user=user,
        organization=org,
        role__in=['owner', 'admin'],
    ).exists()


# -------------------------------------------------------------------
# List + create
# -------------------------------------------------------------------

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def list_create_rules(request, org_id):
    org = get_object_or_404(Organization, id=org_id)

    if request.method == 'GET':
        rules = (
            OrgRoutingRule.objects
            .filter(org=org)
            .select_related('target_client', 'created_by')
            .order_by('-priority', 'id')
        )
        return Response({
            'org_id': org.id,
            'org_name': org.name,
            'rules': [
                {
                    'id': r.id,
                    'match_type': r.match_type,
                    'match_type_display': r.get_match_type_display(),
                    'match_value': r.match_value,
                    'action': r.action,
                    'action_display': r.get_action_display(),
                    'target_client_id': r.target_client_id,
                    'target_client_name': r.target_client.name if r.target_client else None,
                    'priority': r.priority,
                    'enabled': r.enabled,
                    'description': r.description,
                    'is_default': r.is_default,
                    'fire_count': r.fire_count,
                    'last_fired_at': r.last_fired_at.isoformat() if r.last_fired_at else None,
                    'created_by': r.created_by.username if r.created_by else None,
                    'created_at': r.created_at.isoformat(),
                }
                for r in rules
            ],
        })

    # POST — create
    if not _can_edit_rules(request.user, org):
        return Response({'error': 'Permission denied'}, status=403)

    data = request.data
    try:
        target_client = None
        if data.get('target_client_id'):
            target_client = Client.objects.get(id=data['target_client_id'], org=org)

        rule = OrgRoutingRule(
            org=org,
            match_type=data['match_type'],
            match_value=data['match_value'],
            action=data.get('action', 'route_to_client'),
            target_client=target_client,
            priority=int(data.get('priority', 100)),
            enabled=bool(data.get('enabled', True)),
            description=data.get('description', ''),
            is_default=False,
            created_by=request.user,
        )
        rule.full_clean()  # triggers model validation
        rule.save()
        return Response({'ok': True, 'rule_id': rule.id}, status=201)
    except Exception as e:
        return Response({'ok': False, 'error': str(e)}, status=400)


# -------------------------------------------------------------------
# Detail + update + delete
# -------------------------------------------------------------------

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def detail_update_delete_rule(request, org_id, rule_id):
    org = get_object_or_404(Organization, id=org_id)
    rule = get_object_or_404(OrgRoutingRule, id=rule_id, org=org)

    if request.method == 'GET':
        return Response({
            'id': rule.id,
            'match_type': rule.match_type,
            'match_value': rule.match_value,
            'action': rule.action,
            'target_client_id': rule.target_client_id,
            'priority': rule.priority,
            'enabled': rule.enabled,
            'description': rule.description,
            'is_default': rule.is_default,
        })

    if not _can_edit_rules(request.user, org):
        return Response({'error': 'Permission denied'}, status=403)

    if request.method == 'DELETE':
        if rule.is_default:
            return Response({
                'error': 'Default rules cannot be deleted. Disable them instead.'
            }, status=400)
        rule.delete()
        return Response({'ok': True})

    # PATCH
    data = request.data
    try:
        if 'match_type' in data:
            rule.match_type = data['match_type']
        if 'match_value' in data:
            rule.match_value = data['match_value']
        if 'action' in data:
            rule.action = data['action']
        if 'target_client_id' in data:
            if data['target_client_id']:
                rule.target_client = Client.objects.get(
                    id=data['target_client_id'], org=org
                )
            else:
                rule.target_client = None
        if 'priority' in data:
            rule.priority = int(data['priority'])
        if 'enabled' in data:
            rule.enabled = bool(data['enabled'])
        if 'description' in data:
            rule.description = data['description']

        rule.full_clean()
        rule.save()
        return Response({'ok': True})
    except Exception as e:
        return Response({'ok': False, 'error': str(e)}, status=400)


# -------------------------------------------------------------------
# Rule tester — paste a title, see what fires
# -------------------------------------------------------------------

# Shared mapping: agent + backend both need to know what exe names
# belong to each "app family."
EXE_FAMILIES = {
    'taxwise':     ['utw', 'taxwise'],
    'ultratax':    ['uts', 'ultratax'],
    'lacerte':     ['lacerte', 'lacertepro'],
    'proseries':   ['proseries', 'ps'],
    'drake':       ['drake'],
    'quickbooks':  ['qbw', 'qb', 'quickbooks'],
    'excel':       ['excel'],
    'word':        ['winword'],
    'powerpoint':  ['powerpnt'],
    'outlook':     ['outlook'],
    'chrome':      ['chrome'],
    'edge':        ['msedge'],
    'firefox':     ['firefox'],
    'teams':       ['teams', 'ms-teams'],
    'slack':       ['slack'],
    'zoom':        ['zoom'],
}


def _match_exe_family(family_key: str, exe_name: str) -> bool:
    """Given 'taxwise' and 'utw25.exe', return True."""
    if not exe_name:
        return False
    prefixes = EXE_FAMILIES.get(family_key.lower(), [family_key.lower()])
    exe_low = exe_name.lower().replace('.exe', '').strip()
    return any(exe_low.startswith(p) for p in prefixes)


def _rule_matches(rule: OrgRoutingRule, title: str, exe: str, file_path: str) -> bool:
    """The single source of truth for whether a rule matches — mirrored in the agent."""
    mv = (rule.match_value or '').lower()
    title_l = (title or '').lower()
    exe_l = (exe or '').lower()
    path_l = (file_path or '').lower()

    if rule.match_type == 'exe':
        return exe_l == mv or exe_l == f"{mv}.exe"

    if rule.match_type == 'exe_family':
        return _match_exe_family(mv, exe_l)

    if rule.match_type == 'title_contains':
        return mv in title_l

    if rule.match_type == 'title_regex':
        try:
            return bool(re.search(rule.match_value, title or '', re.IGNORECASE))
        except re.error:
            return False

    if rule.match_type == 'file_path_contains':
        return mv in path_l

    return False


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_rules(request, org_id):
    """
    Given a sample (title, exe, file_path), return which rules would fire
    and what the final outcome would be. Used by the admin UI simulator.
    """
    org = get_object_or_404(Organization, id=org_id)

    title = request.data.get('title', '')
    exe = request.data.get('exe', '')
    file_path = request.data.get('file_path', '')

    rules = (
        OrgRoutingRule.objects
        .filter(org=org, enabled=True)
        .select_related('target_client')
        .order_by('-priority', 'id')
    )

    matches = []
    winning_rule = None

    for r in rules:
        if _rule_matches(r, title, exe, file_path):
            matches.append({
                'rule_id': r.id,
                'match_type': r.match_type,
                'match_value': r.match_value,
                'action': r.action,
                'target_client_name': r.target_client.name if r.target_client else None,
                'priority': r.priority,
                'description': r.description,
            })
            if winning_rule is None:
                winning_rule = r

    return Response({
        'input': {'title': title, 'exe': exe, 'file_path': file_path},
        'matches': matches,
        'winning_rule_id': winning_rule.id if winning_rule else None,
        'outcome': _describe_outcome(winning_rule),
    })


def _describe_outcome(rule):
    if rule is None:
        return {
            'action': 'fall_through',
            'message': 'No org rule matched. Agent would fall through to default tiers (regex/learned/AI).',
        }
    if rule.action == 'route_to_client':
        return {
            'action': 'route_to_client',
            'target_client_id': rule.target_client_id,
            'target_client_name': rule.target_client.name if rule.target_client else None,
            'message': f'Would switch active client to "{rule.target_client.name}".' if rule.target_client else 'Rule is misconfigured.',
        }
    if rule.action == 'never_switch_away':
        return {
            'action': 'never_switch_away',
            'message': 'Would hold current client — no switch allowed while this window is focused.',
        }
    if rule.action == 'suppress':
        return {
            'action': 'suppress',
            'message': 'Would ignore this window entirely — no event written.',
        }
    return {'action': 'unknown', 'message': 'Unknown action.'}


# -------------------------------------------------------------------
# Agent-telemetry endpoint (same as in sync_additions.py, consolidated)
# -------------------------------------------------------------------

@api_view(['POST'])
def report_routing_rule_fire(request):
    """Agent posts here when a rule fires. Updates counters."""
    rule_id = request.data.get('rule_id')
    if not rule_id:
        return Response({'ok': False, 'error': 'rule_id required'}, status=400)

    try:
        # Adjust this to use your device-key auth
        device_org_id = getattr(request, 'device', None)
        if device_org_id:
            device_org_id = device_org_id.org_id
            OrgRoutingRule.objects.filter(
                id=rule_id, org_id=device_org_id
            ).update(
                fire_count=F('fire_count') + 1,
                last_fired_at=timezone.now(),
            )
        else:
            OrgRoutingRule.objects.filter(id=rule_id).update(
                fire_count=F('fire_count') + 1,
                last_fired_at=timezone.now(),
            )
        return Response({'ok': True})
    except Exception as e:
        return Response({'ok': False, 'error': str(e)}, status=500)