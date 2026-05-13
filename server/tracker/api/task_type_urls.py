"""
URL routing for TaskType management endpoints (Sets, per-client overrides,
matrix rules).

NAMESPACING:
  Your existing tracker/urls.py already exposes /api/task-types/ via
  views.TaskTypeViewSet (legacy TaskType CRUD). To avoid colliding, the
  new endpoints live under /api/task-management/ instead.

  Existing (untouched):
    /api/task-types/              ← legacy views.TaskTypeViewSet
    /api/options/task-types/      ← dropdown helper

  New (added by this file):
    /api/task-management/task-types/                   CRUD on TaskType (NEW)
    /api/task-management/task-type-sets/               TaskTypeSet CRUD
    /api/task-management/task-type-sets/{id}/members/  Add/remove set members
    /api/task-management/matrix-rules/                 Matrix rule CRUD
    /api/task-management/clients/{id}/task-types/      Per-client config

  ⚠️  About the new TaskTypeViewSet collision:
      My TaskTypeViewSet (in tracker.api.task_type_views) and the existing
      views.TaskTypeViewSet both do CRUD on the same TaskType model. The new
      one is org-scoped via OrganizationMembership and supports soft-delete;
      the existing one is whatever your codebase has had since day one.
      They coexist at different URLs:
        /api/task-types/                  → legacy
        /api/task-management/task-types/  → new
      You can pick which one your frontend uses. Once you've migrated the
      frontend to the new one (and confirmed it covers all use cases),
      delete the legacy entry from tracker/urls.py (line 13) and unregister
      views.TaskTypeViewSet.

ADDING TO YOUR MAIN URLS:
  In tracker/urls.py, REPLACE the line that says:
      path('api/', include('tracker.api.task_type_urls')),
  WITH:
      path('task-management/', include('tracker.api.task_type_urls')),

  Why the change: tracker/urls.py is itself mounted at /api/ by
  server/urls.py (via `path("api/", include("tracker.urls"))`). So using
  path('task-management/', ...) makes the full URL /api/task-management/.
  The earlier 'api/' prefix would have given /api/api/task-management/
  which is wrong.
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from tracker.api.task_type_views import (
    ClientTaskTypesView,
    MatrixRuleViewSet,
    TaskTypeSetViewSet,
    TaskTypeViewSet,
)

router = DefaultRouter()
# Note: basenames suffixed with '-v2' to avoid colliding with the legacy
# 'task-type' basename registered in tracker/urls.py. DRF requires
# basenames to be globally unique within a project.
router.register(r'task-types',     TaskTypeViewSet,     basename='task-type-v2')
router.register(r'task-type-sets', TaskTypeSetViewSet,  basename='task-type-set')
router.register(r'matrix-rules',   MatrixRuleViewSet,   basename='matrix-rule')

urlpatterns = router.urls + [
    path(
        'clients/<int:client_id>/task-types/',
        ClientTaskTypesView.as_view(),
        name='client-task-types-v2',
    ),
]