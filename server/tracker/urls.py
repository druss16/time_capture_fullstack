from django.urls import path
from . import views

urlpatterns = [
    # agent ingest (API key–protected)
    path("raw-events/", views.raw_events, name="raw-events"),

    # blocks/suggestions for the web app (auth required)
    path("blocks/today/", views.blocks_today, name="blocks-today"),            # optional helper you already have
    path("suggestions/today/", views.suggestions_today, name="suggestions"),   # top-3 suggestions per block
    path("blocks/label/", views.label_block, name="label-block"),              # apply client/project/task (+ optional rule)
]
