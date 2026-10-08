"""
Asana OAuth + sync endpoints: connect, callback, sync, disconnect, and the
project links (list, link one by hand).

Same shape as QuickBooks Time's (integrations/qb_time/views.py): one app for
every firm, one Integration row per firm, owners and admins only, and a first
sync started the moment the grant lands.
"""
import logging
import secrets
import threading

from django.conf import settings
from django.db import connection
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from tracker.integrations.asana.client import (
    AsanaError, apply_tokens, authorize_url, exchange_code, is_configured,
)
from tracker.integrations.clio.views import _require_admin
from tracker.models import Integration, Project
from tracker.views_integrations import _oauth_success_response, error_response, get_integration

logger = logging.getLogger(__name__)


def _fail(reason):
    return redirect(f"{settings.FRONTEND_URL}/settings?tab=integrations&integration_error={reason}")


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def asana_connect(request):
    org, denied = _require_admin(request, 'connect Asana')
    if denied:
        return denied
    if not is_configured():
        return error_response('Asana is not configured on this server.', 503, 'not_configured')
    state = secrets.token_urlsafe(32)
    Integration.objects.update_or_create(
        organization=org, provider='asana', defaults={'oauth_state': state})
    return Response({'auth_url': authorize_url(state)})


@api_view(['GET'])
@permission_classes([AllowAny])
def asana_callback(request):
    """Exchange the code for tokens. Reached by redirect, with no session."""
    code, state, error = request.GET.get('code'), request.GET.get('state'), request.GET.get('error')
    if error:
        return _fail(error)
    if not code or not state:
        return _fail('missing_code')
    try:
        integration = Integration.objects.get(oauth_state=state, provider='asana')
    except Integration.DoesNotExist:
        return _fail('invalid_state')
    try:
        tokens = exchange_code(code)
    except Exception as e:
        logger.error('Asana token exchange failed: %s', e)
        return _fail('token_exchange_failed')

    apply_tokens(integration, tokens)
    # The workspace is chosen on the first sync; a reconnect may be a
    # different account, so it is chosen again.
    integration.tenant_id = ''
    integration.oauth_state = ''
    integration.is_connected = True
    integration.last_sync_status = 'pending'
    integration.last_sync_error = ''
    integration.save()
    _start_sync(integration.id, full=True)
    return _oauth_success_response('asana')


def _start_sync(integration_id: int, *, full: bool) -> None:
    """In a thread: Celery is eager in production, so .delay() would hold the
    request open for the whole first import."""
    def run():
        from tracker.integrations.asana.sync import run_sync
        try:
            run_sync(integration_id, full=full)
        except Exception:
            logger.exception('Background Asana sync failed for integration %s', integration_id)
        finally:
            connection.close()
    threading.Thread(target=run, name=f'asana-sync-{integration_id}', daemon=True).start()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def asana_sync(request):
    org, denied = _require_admin(request, 'run an Asana sync')
    if denied:
        return denied
    integration, err = get_integration(org, 'asana')
    if err:
        return err
    _start_sync(integration.id, full=True)
    return Response({'started': True,
                     'message': 'Asana sync started. The counts update here when it finishes.'},
                    status=202)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def asana_disconnect(request):
    """Drop the grant locally. Links and activity already read stay."""
    org, denied = _require_admin(request, 'disconnect Asana')
    if denied:
        return denied
    integration = Integration.objects.filter(organization=org, provider='asana').first()
    if integration:
        integration.is_connected = False
        integration.access_token = ''
        integration.refresh_token = ''
        integration.token_expires_at = None
        integration.oauth_state = ''
        integration.save()
    return Response({'success': True})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def asana_projects(request):
    """
    GET  — every Asana project and the TimeTracker project it is linked to.
    POST {"asana_gid": "...", "project_id": 12 | null} — link (or unlink) one
         by hand. A hand-made link survives every later sync.

    Matching by name links most of a firm's projects; the rest are names that
    differ between the two systems, or one name that several clients share.
    """
    from tracker.models_asana import AsanaProjectLink

    org, denied = _require_admin(request, 'link Asana projects')
    if denied:
        return denied
    integration, err = get_integration(org, 'asana', connected_only=False)
    if err:
        return err

    if request.method == 'POST':
        gid = str(request.data.get('asana_gid') or '').strip()
        project_id = request.data.get('project_id')
        link = AsanaProjectLink.objects.filter(integration=integration, asana_gid=gid).first()
        if link is None:
            return error_response('Unknown Asana project.', 404)
        if project_id in (None, '', 0):
            link.project, link.link_source = None, 'manual'
        else:
            project = Project.objects.filter(org=org, id=project_id).first()
            if project is None:
                return error_response('Project not found for this firm.', 404)
            link.project, link.link_source = project, 'manual'
        link.save(update_fields=['project', 'link_source', 'updated_at'])
        return Response({'asana_gid': gid, 'project_id': link.project_id})

    rows = [{
        'asana_gid': link.asana_gid,
        'asana_name': link.asana_name,
        'archived': link.archived,
        'project_id': link.project_id,
        'project_name': link.project.name if link.project else None,
        'client_name': link.project.client.name if link.project and link.project.client else None,
        'link_source': link.link_source,
    } for link in AsanaProjectLink.objects.filter(integration=integration)
        .select_related('project__client').order_by('archived', 'asana_name')]
    # What an unlinked one can be linked to: the firm's live projects.
    options = [{'id': p.id, 'name': p.name, 'client_name': p.client.name if p.client else ''}
               for p in Project.objects.filter(org=org, is_active=True).select_related('client')
               .order_by('client__name', 'name')]
    return Response({'projects': rows, 'options': options})


def asana_status(integration) -> dict:
    """The card's numbers — see integrations_status."""
    from datetime import timedelta
    from django.utils import timezone
    from tracker.models_asana import AsanaActivity, AsanaProjectLink
    from tracker.models_task_type_sets import ExternalStaffMapping
    try:
        live = AsanaProjectLink.objects.filter(integration=integration, archived=False)
        return {
            'projects': live.count(),
            'projects_linked': live.filter(project__isnull=False).count(),
            'people_linked': ExternalStaffMapping.objects.filter(integration=integration).count(),
            'activity_7d': AsanaActivity.objects.filter(
                integration=integration, at__gte=timezone.now() - timedelta(days=7)).count(),
        }
    except Exception:       # tables not migrated yet — the card shows no counts
        return {}


__all__ = ['asana_connect', 'asana_callback', 'asana_sync', 'asana_disconnect',
           'asana_projects', 'asana_status', 'AsanaError']
