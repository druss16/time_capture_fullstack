from django.urls import path
from . import views

urlpatterns = [
    path("ping/", views.ping),
    path("raw-events/", views.raw_events),              # Agent (with Agent-Key)
    path("ingest-raw-event/", views.ingest_raw_event),  # dev-only open
    path("blocks-today/", views.blocks_today),
    path("suggestions-today/", views.suggestions_today),
    path("label-block/", views.label_block),
]
