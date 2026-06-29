"""
Support URL routes.

Include from tracker's main urls.py:
    path("api/support/", include("tracker.support.urls")),
"""
from django.urls import path
from . import views

urlpatterns = [
    path("chat/", views.support_chat),
    path("conversations/", views.list_conversations),
    path("conversations/<int:pk>/", views.get_conversation),
    path("ticket/", views.create_ticket),
]