from django.urls import path
from . import views

urlpatterns = [
    # -------------------------------
    # Basic + ingestion endpoints
    # -------------------------------
    path("ping/", views.ping),
    path("raw-events/", views.raw_events),              # For authenticated agent posts
    path("ingest-raw-event/", views.ingest_raw_event),  # Dev/open ingestion
    path("blocks-today/", views.blocks_today),

    # -------------------------------
    # Suggestions (Rule-based + AI)
    # -------------------------------
    path("suggestions-today/", views.suggestions_today),        # old rule-based
    path("ai-suggestions-today/", views.ai_suggestions_today),  # new LLM-based
    path("blocks/suggestions/", views.ai_suggestions_today, name="ai_suggestions_today"),  # main unified route
    path("blocks/suggestions/rule-based/", views.suggestions_today, name="suggestions_today"),
    path("blocks/<int:block_id>/classify/", views.save_block_classification, name="save_block_classification"),

    # -------------------------------
    # Timecard Management
    # -------------------------------
    path("timecards/generate/", views.generate_timecard),
    path("timecards/", views.list_timecards, name="list_timecards"),
    path("timecards/summary/", views.timecard_summary, name="timecard_summary"),
    path("timecards/<int:timecard_id>/approve/", views.approve_timecard, name="approve_timecard"),
    path("timecards/<int:timecard_id>/reject/", views.reject_timecard, name="reject_timecard"),

    # -------------------------------
    # Organization Settings
    # -------------------------------
    path("settings/organization/", views.organization_settings, name="organization_settings"),
    path("settings/entities/", views.known_entities, name="known_entities"),
    path("settings/entities/<int:entity_id>/", views.known_entity_detail, name="known_entity_detail"),
    path("settings/training/", views.save_training_example, name="save_training_example"),
]
