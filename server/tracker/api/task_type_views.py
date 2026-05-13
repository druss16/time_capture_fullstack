"""
DRF views for TaskType management.

ENDPOINTS:
    GET    /api/task-types/                     List all TaskTypes for current org
    POST   /api/task-types/                     Create TaskType
    GET    /api/task-types/{id}/                Retrieve TaskType
    PATCH  /api/task-types/{id}/                Update TaskType
    DELETE /api/task-types/{id}/                Soft-delete (set is_active=False)

    GET    /api/task-type-sets/                 List TaskTypeSets for current org
    POST   /api/task-type-sets/                 Create TaskTypeSet
    GET    /api/task-type-sets/{id}/            Retrieve with members
    PATCH  /api/task-type-sets/{id}/            Update (rename, etc.)
    DELETE /api/task-type-sets/{id}/            Delete (only if not in use)
    POST   /api/task-type-sets/{id}/set-default/   Mark as org default
    POST   /api/task-type-sets/{id}/members/    Add/remove members

    GET    /api/clients/{id}/task-types/        Resolve allowed TaskTypes for client
    PUT    /api/clients/{id}/task-types/        Set client's task type config

    GET    /api/matrix-rules/                   List synced+manual matrix rules
    POST   /api/matrix-rules/                   Create manual matrix rule
    DELETE /api/matrix-rules/{id}/              Delete (only manual rules)

AUTH:
    Standard DRF auth — sessions or auth_token from your existing system.
    All endpoints scoped to the user's active org via OrganizationMembership.
"""

import json
import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from tracker.models import (
    Client,
    OrganizationMembership,
    OrgRoutingRule,
    TaskType,
)
from tracker.models_task_type_sets import (
    ClientTaskType,
    TaskTypeSet,
    TaskTypeSetMember,
)
from tracker.services.task_type_resolver import resolve_allowed_task_types

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

def _get_user_org(request):
    """
    Returns the user's active organization.

    Uses OrganizationMembership to find which org the user belongs to.
    If user belongs to multiple orgs, falls back to the first one
    (production code should look up the org from request.session or a
    request header set by your existing middleware).
    """
    user = request.user
    if not user.is_authenticated:
        return None

    # If your middleware sets request.org or similar, prefer that
    org = getattr(request, 'org', None)
    if org:
        return org

    membership = (
        OrganizationMembership.objects.filter(user=user)
        .select_related('organization')
        .first()
    )
    return membership.organization if membership else None


def _is_admin(request, org):
    """User must be admin/owner of the org for write operations."""
    if not request.user.is_authenticated or org is None:
        return False
    if request.user.is_superuser:
        return True
    return OrganizationMembership.objects.filter(
        user=request.user,
        organization=org,
        role__in=['owner', 'admin'],
    ).exists()


# ============================================================================
# TaskType CRUD
# ============================================================================

class TaskTypeViewSet(viewsets.ViewSet):
    """CRUD for TaskType, scoped to the user's org."""

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        org = _get_user_org(request)
        if not org:
            return Response({'detail': 'No org'}, status=status.HTTP_403_FORBIDDEN)
        qs = TaskType.objects.filter(org=org).order_by('sort_order', 'name')
        data = [self._serialize(tt) for tt in qs]
        return Response(data)

    def retrieve(self, request, pk=None):
        org = _get_user_org(request)
        if not org:
            return Response({'detail': 'No org'}, status=status.HTTP_403_FORBIDDEN)
        tt = get_object_or_404(TaskType, pk=pk, org=org)
        return Response(self._serialize(tt))

    def create(self, request):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        try:
            tt = TaskType.objects.create(
                org=org,
                name=data['name'],
                code=data.get('code', '')[:20],
                is_billable=data.get('is_billable', True),
                default_rate=data.get('default_rate'),
                color=data.get('color', '#3B82F6')[:7],
                icon=data.get('icon', '')[:50],
                sort_order=data.get('sort_order', 0),
                is_active=data.get('is_active', True),
            )
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._serialize(tt), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        tt = get_object_or_404(TaskType, pk=pk, org=org)

        for field in ('name', 'code', 'is_billable', 'default_rate', 'color', 'icon', 'sort_order', 'is_active'):
            if field in request.data:
                setattr(tt, field, request.data[field])
        tt.save()
        return Response(self._serialize(tt))

    def destroy(self, request, pk=None):
        """Soft-delete: set is_active=False. Hard delete only if no blocks reference it."""
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        tt = get_object_or_404(TaskType, pk=pk, org=org)

        # Check for block references
        if tt.blocks.exists():
            tt.is_active = False
            tt.save(update_fields=['is_active'])
            return Response({'detail': 'Marked inactive (blocks still reference this).'},
                            status=status.HTTP_200_OK)
        tt.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _serialize(tt):
        return {
            'id': tt.id,
            'name': tt.name,
            'code': tt.code,
            'is_billable': tt.is_billable,
            'default_rate': str(tt.default_rate) if tt.default_rate is not None else None,
            'color': tt.color,
            'icon': tt.icon,
            'sort_order': tt.sort_order,
            'is_active': tt.is_active,
            'created_at': tt.created_at.isoformat() if tt.created_at else None,
        }


# ============================================================================
# TaskTypeSet CRUD
# ============================================================================

class TaskTypeSetViewSet(viewsets.ViewSet):
    """CRUD for TaskTypeSet, with member management."""

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        org = _get_user_org(request)
        if not org:
            return Response({'detail': 'No org'}, status=status.HTTP_403_FORBIDDEN)
        qs = TaskTypeSet.objects.filter(org=org).prefetch_related('members__task_type')
        data = [self._serialize(s) for s in qs]
        return Response(data)

    def retrieve(self, request, pk=None):
        org = _get_user_org(request)
        if not org:
            return Response({'detail': 'No org'}, status=status.HTTP_403_FORBIDDEN)
        ts = get_object_or_404(TaskTypeSet, pk=pk, org=org)
        return Response(self._serialize(ts, include_members=True))

    def create(self, request):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        try:
            with transaction.atomic():
                ts = TaskTypeSet.objects.create(
                    org=org,
                    name=data['name'],
                    description=data.get('description', '')[:255],
                    is_default=data.get('is_default', False),
                    source='manual',
                    created_by=request.user,
                )
                # Optional members on create
                for idx, tt_id in enumerate(data.get('task_type_ids', [])):
                    tt = TaskType.objects.filter(id=tt_id, org=org).first()
                    if tt:
                        TaskTypeSetMember.objects.create(set=ts, task_type=tt, sort_order=idx * 10)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._serialize(ts, include_members=True), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        ts = get_object_or_404(TaskTypeSet, pk=pk, org=org)
        if ts.source == 'cch_axcess_sync':
            return Response(
                {'detail': 'Synced sets are read-only.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        for field in ('name', 'description', 'is_default'):
            if field in request.data:
                setattr(ts, field, request.data[field])
        ts.save()
        return Response(self._serialize(ts, include_members=True))

    def destroy(self, request, pk=None):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        ts = get_object_or_404(TaskTypeSet, pk=pk, org=org)
        if ts.source == 'cch_axcess_sync':
            return Response({'detail': 'Synced sets are read-only.'},
                            status=status.HTTP_403_FORBIDDEN)
        if ts.clients_using_as_default.exists():
            return Response(
                {'detail': 'Cannot delete: clients are using this as their default set.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ts.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        """Mark this set as the org-wide default (auto-clears others)."""
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        ts = get_object_or_404(TaskTypeSet, pk=pk, org=org)
        ts.is_default = True
        ts.save()  # save() enforces uniqueness via the model
        return Response(self._serialize(ts, include_members=True))

    @action(detail=True, methods=['post', 'delete'], url_path='members')
    def members(self, request, pk=None):
        """Add (POST) or remove (DELETE) a member.
        Body: {"task_type_id": 7, "sort_order": 10}
        """
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        ts = get_object_or_404(TaskTypeSet, pk=pk, org=org)
        if ts.source == 'cch_axcess_sync':
            return Response({'detail': 'Synced sets are read-only.'},
                            status=status.HTTP_403_FORBIDDEN)

        tt_id = request.data.get('task_type_id')
        if not tt_id:
            return Response({'detail': 'task_type_id required'}, status=status.HTTP_400_BAD_REQUEST)
        tt = get_object_or_404(TaskType, pk=tt_id, org=org)

        if request.method == 'POST':
            sort_order = request.data.get('sort_order', 0)
            mem, created = TaskTypeSetMember.objects.update_or_create(
                set=ts, task_type=tt,
                defaults={'sort_order': sort_order},
            )
            return Response({'created': created, 'sort_order': mem.sort_order})
        else:
            TaskTypeSetMember.objects.filter(set=ts, task_type=tt).delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _serialize(ts, include_members=False):
        out = {
            'id': ts.id,
            'name': ts.name,
            'description': ts.description,
            'is_default': ts.is_default,
            'source': ts.source,
            'member_count': ts.members.count(),
            'created_at': ts.created_at.isoformat() if ts.created_at else None,
        }
        if include_members:
            members = ts.members.select_related('task_type').order_by('sort_order')
            out['members'] = [{
                'task_type_id': m.task_type_id,
                'code': m.task_type.code,
                'name': m.task_type.name,
                'color': m.task_type.color,
                'is_billable': m.task_type.is_billable,
                'sort_order': m.sort_order,
            } for m in members]
        return out


# ============================================================================
# Per-Client TaskType configuration
# ============================================================================

class ClientTaskTypesView(APIView):
    """
    GET  /api/clients/{client_id}/task-types/
         Returns current config + resolved list of allowed TaskTypes.

    PUT  /api/clients/{client_id}/task-types/
         Set the client's task type configuration. Body shape:
           {
             "mode": "default" | "set" | "custom",
             "default_task_type_set_id": 5,         # if mode='set'
             "overrides": [                          # if mode='custom'
               {"task_type_id": 3, "allowed": true, "override_rate": "150.00"},
               {"task_type_id": 7, "allowed": false}
             ]
           }
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, client_id):
        org = _get_user_org(request)
        client = get_object_or_404(Client, pk=client_id, org=org)

        allowed = resolve_allowed_task_types(client, user=request.user)
        overrides = ClientTaskType.objects.filter(client=client).select_related('task_type')

        if overrides.exists():
            mode = 'custom'
        elif client.default_task_type_set_id:
            mode = 'set'
        else:
            mode = 'default'

        return Response({
            'client_id': client.id,
            'client_name': client.name,
            'mode': mode,
            'default_task_type_set_id': client.default_task_type_set_id,
            'overrides': [
                {
                    'task_type_id': o.task_type_id,
                    'code': o.task_type.code,
                    'name': o.task_type.name,
                    'allowed': o.allowed,
                    'override_rate': str(o.override_rate) if o.override_rate is not None else None,
                    'source': o.source,
                }
                for o in overrides
            ],
            'allowed_task_types': [
                {'id': tt.id, 'code': tt.code, 'name': tt.name, 'color': tt.color}
                for tt in (allowed or [])
            ],
        })

    def put(self, request, client_id):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)

        client = get_object_or_404(Client, pk=client_id, org=org)
        mode = request.data.get('mode', 'default')

        with transaction.atomic():
            if mode == 'default':
                client.default_task_type_set = None
                client.save(update_fields=['default_task_type_set'])
                ClientTaskType.objects.filter(client=client, source='manual').delete()

            elif mode == 'set':
                tts_id = request.data.get('default_task_type_set_id')
                if not tts_id:
                    return Response({'detail': 'default_task_type_set_id required'},
                                    status=status.HTTP_400_BAD_REQUEST)
                tts = get_object_or_404(TaskTypeSet, pk=tts_id, org=org)
                client.default_task_type_set = tts
                client.save(update_fields=['default_task_type_set'])
                ClientTaskType.objects.filter(client=client, source='manual').delete()

            elif mode == 'custom':
                # Replace all manual overrides
                ClientTaskType.objects.filter(client=client, source='manual').delete()
                for override in request.data.get('overrides', []):
                    tt = TaskType.objects.filter(id=override['task_type_id'], org=org).first()
                    if not tt:
                        continue
                    ClientTaskType.objects.create(
                        client=client,
                        task_type=tt,
                        allowed=override.get('allowed', True),
                        override_rate=override.get('override_rate') or None,
                        source='manual',
                        created_by=request.user,
                    )

            else:
                return Response({'detail': f'Unknown mode: {mode}'},
                                status=status.HTTP_400_BAD_REQUEST)

        # Return the new state
        return self.get(request, client_id)


# ============================================================================
# Matrix rules (OrgRoutingRule with match_type='task_type_matrix')
# ============================================================================

class MatrixRuleViewSet(viewsets.ViewSet):
    """
    Read/write matrix rules. Synced rules are read-only; manual rules are
    CRUD'able by admins.
    """

    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        org = _get_user_org(request)
        if not org:
            return Response({'detail': 'No org'}, status=status.HTTP_403_FORBIDDEN)
        qs = OrgRoutingRule.objects.filter(
            org=org,
            match_type='task_type_matrix',
        ).order_by('-priority', 'id')
        return Response([self._serialize(r) for r in qs])

    def create(self, request):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)

        match_value = {
            'client_id': request.data.get('client_id', '*'),
            'task_type_id': request.data.get('task_type_id', '*'),
            'user_id': request.data.get('user_id', '*'),
        }
        try:
            rule = OrgRoutingRule.objects.create(
                org=org,
                match_type='task_type_matrix',
                match_value=json.dumps(match_value),
                action=request.data.get('action', 'suppress'),
                category=request.data.get('category', 'billing'),
                runs_at=request.data.get('runs_at', 'classifier'),
                source='manual',
                priority=int(request.data.get('priority', 100)),
                enabled=True,
                is_default=False,
                description=request.data.get('description', '')[:255],
                flag_reason=request.data.get('flag_reason', '')[:200],
                created_by=request.user,
            )
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._serialize(rule), status=status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        org = _get_user_org(request)
        if not _is_admin(request, org):
            return Response({'detail': 'Admin required'}, status=status.HTTP_403_FORBIDDEN)
        rule = get_object_or_404(
            OrgRoutingRule,
            pk=pk,
            org=org,
            match_type='task_type_matrix',
        )
        if rule.source == 'cch_axcess_sync':
            return Response({'detail': 'Synced rules are read-only.'},
                            status=status.HTTP_403_FORBIDDEN)
        rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _serialize(rule):
        try:
            mv = json.loads(rule.match_value)
        except (json.JSONDecodeError, TypeError):
            mv = {}
        return {
            'id': rule.id,
            'match_value': mv,
            'action': rule.action,
            'category': rule.category,
            'runs_at': rule.runs_at,
            'source': rule.source,
            'priority': rule.priority,
            'enabled': rule.enabled,
            'description': rule.description,
            'flag_reason': rule.flag_reason,
            'fire_count': rule.fire_count,
            'last_fired_at': rule.last_fired_at.isoformat() if rule.last_fired_at else None,
            'is_editable': rule.source == 'manual',
        }