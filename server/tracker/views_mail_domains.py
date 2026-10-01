"""
Settings → Email domains: map a counterparty email domain to a client.

All logic lives in tracker/services/mail_domains.py (shared with the
`mail_domains` management command); these views are org resolution,
permission and JSON shape only.

PERMISSION: owners and admins of the org, for READ as well as write.
  * It is org-wide configuration that changes how every member's mail and
    meetings are attributed — the same owner/admin line the Integrations and
    task-type settings tabs draw.
  * The observed list is an aggregate of who the WHOLE firm corresponds with,
    across every connected mailbox and calendar. Managers may see a domain on
    a block they review, but a firm-wide roll-up of counterparties is more than
    any one review needs, and a read-only view would serve no task a manager
    has. So managers are not given it.
  * Deliberately NOT tracker.views.IsOrgAdmin, which resolves to
    owner/admin/**manager** (the same trap tracker/cost_visibility.py records).
  * Superusers (MavOps operators) pass; is_staff alone does not. MavOps "View
    as" swaps request.user, so an operator viewing as an owner is an owner.
"""
from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import OrganizationMembership
from tracker.services import mail_domains as svc

MANAGE_ROLES = ('owner', 'admin')


def can_manage_email_domains(user, org) -> bool:
    if user is None or not getattr(user, 'is_authenticated', False) or org is None:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return OrganizationMembership.objects.filter(
        user=user, organization=org, role__in=MANAGE_ROLES,
    ).exists()


def _org_or_error(request):
    """(org, None) or (None, Response)."""
    from tracker.views import get_request_org_override
    org = get_request_org_override(request)
    if not org:
        return None, Response({'error': 'No organization'}, status=404)
    if not can_manage_email_domains(request.user, org):
        return None, Response(
            {'error': 'Only firm owners and admins can manage email domains.'}, status=403)
    return org, None


def _error(e: svc.DomainError) -> Response:
    status = {'duplicate': 409, 'not_found': 404}.get(e.code, 400)
    return Response({'error': str(e), 'code': e.code}, status=status)


def _mapping_json(rule, counts=None) -> dict:
    domain = svc._rule_domain(rule)
    c = (counts or {}).get(domain, {})
    return {
        'id': rule.id,
        'domain': domain,
        'client_id': rule.target_client_id,
        'client_name': rule.target_client.name if rule.target_client else None,
        'is_active': rule.is_active,
        'created_at': rule.created_at.isoformat() if rule.created_at else None,
        'messages': c.get('messages', 0),
        'messages_attributed': c.get('messages_attributed', 0),
    }


def _write_response(org, change: svc.MappingChange, status=200) -> Response:
    svc.queue_rematch(org, change)
    body = {'domain': change.domain, 'rematch_queued': True}
    if change.rule is not None:
        rule = svc.get_mapping(org, change.rule.id)
        body['mapping'] = _mapping_json(rule, svc.mapping_counts(org, [change.domain]))
    return Response(body, status=status)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def email_domains(request):
    """GET: current mappings. POST {domain, client_id}: map a domain."""
    org, err = _org_or_error(request)
    if err:
        return err

    if request.method == 'GET':
        rules = svc.list_mappings(org)
        counts = svc.mapping_counts(org, [svc._rule_domain(r) for r in rules])
        return Response({
            'mappings': [_mapping_json(r, counts) for r in rules],
            'own_domains': sorted(svc.org_own_domains(org)),
            'covers_subdomains': False,
        })

    try:
        change = svc.create_mapping(org, request.data.get('domain', ''),
                                    request.data.get('client_id'))
    except svc.DomainError as e:
        return _error(e)
    return _write_response(org, change, status=201)


@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def email_domain_detail(request, rule_id: int):
    """PATCH {client_id}: re-point a mapping. DELETE: remove it."""
    org, err = _org_or_error(request)
    if err:
        return err
    try:
        if request.method == 'DELETE':
            change = svc.delete_mapping(org, rule_id)
        else:
            change = svc.update_mapping(org, rule_id, request.data.get('client_id'))
    except svc.DomainError as e:
        return _error(e)
    return _write_response(org, change)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def email_domains_bulk(request):
    """POST {mappings: [{domain, client_id}, ...]} — accept several suggestions.

    Each item succeeds or fails on its own; the response lists both.
    """
    org, err = _org_or_error(request)
    if err:
        return err
    items = request.data.get('mappings') or []
    if not isinstance(items, list) or len(items) > 200:
        return Response({'error': 'Send a list of at most 200 mappings.'}, status=400)
    created, failed = [], []
    for item in items:
        item = item if isinstance(item, dict) else {}
        try:
            change = svc.create_mapping(org, item.get('domain', ''), item.get('client_id'))
        except svc.DomainError as e:
            failed.append({'domain': item.get('domain', ''), 'error': str(e), 'code': e.code})
            continue
        svc.queue_rematch(org, change)
        created.append(_mapping_json(svc.get_mapping(org, change.rule.id)))
    return Response({'created': created, 'failed': failed, 'rematch_queued': bool(created)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_domains_observed(request):
    """Domains seen in mail/calendar but not mapped, with a suggested client."""
    org, err = _org_or_error(request)
    if err:
        return err
    try:
        days = max(1, min(int(request.GET.get('days', svc.DEFAULT_WINDOW_DAYS)), 365))
    except (TypeError, ValueError):
        days = svc.DEFAULT_WINDOW_DAYS
    return Response({
        'window_days': days,
        'observed': svc.observed_domains(org, days),
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def email_domains_ignored(request):
    """GET: ignored domains. POST {domain}: hide a domain from the observed list."""
    org, err = _org_or_error(request)
    if err:
        return err
    if request.method == 'GET':
        return Response({'ignored': [
            {'id': i.id, 'domain': i.domain,
             'created_at': i.created_at.isoformat() if i.created_at else None}
            for i in svc.ignored_domains(org)
        ]})
    try:
        obj = svc.ignore_domain(org, request.data.get('domain', ''), user=request.user)
    except svc.DomainError as e:
        return _error(e)
    except Exception:
        # Table missing: the migration has not been applied yet.
        return Response({'error': 'Ignoring domains is not available yet.'}, status=503)
    return Response({'id': obj.id, 'domain': obj.domain}, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def email_domains_ignored_bulk(request):
    """POST {domains: [...]} — ignore several at once ("Ignore all automated").

    Each domain succeeds or fails on its own; the response lists both.
    """
    org, err = _org_or_error(request)
    if err:
        return err
    domains = request.data.get('domains') or []
    if not isinstance(domains, list) or len(domains) > 500:
        return Response({'error': 'Send a list of at most 500 domains.'}, status=400)
    try:
        done, failed = svc.ignore_domains(org, domains, user=request.user)
    except Exception:
        # Table missing: the migration has not been applied yet.
        return Response({'error': 'Ignoring domains is not available yet.'}, status=503)
    return Response({
        'ignored': [{'id': i.id, 'domain': i.domain} for i in done],
        'failed': failed,
    })


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def email_domain_ignored_detail(request, ignore_id: int):
    org, err = _org_or_error(request)
    if err:
        return err
    if not svc.unignore_domain(org, ignore_id):
        return Response({'error': 'Not found'}, status=404)
    return Response(status=204)
