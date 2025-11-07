from django.urls import path
from . import views

urlpatterns = [
    # -------------------------------
    # Basic / Health
    # -------------------------------
    path("ping/", views.ping, name="ping"),

    # -------------------------------
    # Agent Pairing & Communication
    # -------------------------------
    path("agents/pair/issue/", views.agents_pair_issue, name="agents_pair_issue"),   # web → get pairing code (auth required)
    path("agents/pair/claim/", views.agents_pair_claim, name="agents_pair_claim"),   # agent → redeem code, receive api_key
    path("agents/hello2/", views.agents_hello2, name="agents_hello2"),               # device heartbeat (DeviceKey)
    path("raw-events/", views.raw_events, name="raw_events"),                        # event ingestion (DeviceKey)

    # Optional: browser hint for SPA identity (non-auth)
    path("browser/hello/", views.browser_hello, name="browser_hello"),

    # Device management (web UI)
    path("devices/", views.my_devices, name="my_devices"),
    path("devices/<int:pk>/revoke/", views.revoke_device, name="revoke_device"),

    # Admin / control & identity
    path("agent/control/", views.agent_control, name="agent_control"),
    path("whoami/", views.whoami, name="whoami"),

    # -------------------------------
    # Blocks / Suggestions (Rule-based + AI)
    # -------------------------------
    path("blocks-today/", views.blocks_today, name="blocks_today"),
    path("blocks/suggestions/", views.ai_suggestions_today, name="ai_suggestions_today"),
    path("blocks/suggestions/rule-based/", views.suggestions_today, name="suggestions_today"),
    path("blocks/<int:block_id>/classify/", views.save_block_classification, name="save_block_classification"),
    path("recent-blocks/", views.recent_classified_blocks, name="recent_classified_blocks"),
    path("label-block/", views.label_block, name="label_block"),

    # -------------------------------
    # Timecards
    # -------------------------------
    path("timecards/generate/", views.generate_timecard, name="generate_timecard"),
    path("timecards/", views.list_timecards, name="list_timecards"),
    path("timecards/summary/", views.timecard_summary, name="timecard_summary"),
    path("timecards/summary/day/", views.timecards_summary_day, name="timecards_summary_day"),
    path("timecards/<int:timecard_id>/approve/", views.approve_timecard, name="approve_timecard"),
    path("timecards/<int:timecard_id>/reject/", views.reject_timecard, name="reject_timecard"),

    # -------------------------------
    # Organization / Settings
    # -------------------------------
    path("settings/organization/", views.organization_settings, name="organization_settings"),
    path("settings/entities/", views.known_entities, name="known_entities"),
    path("settings/entities/<int:entity_id>/", views.known_entity_detail, name="known_entity_detail"),
    path("settings/training/", views.save_training_example, name="save_training_example"),

    # -------------------------------
    # Misc / CSRF
    # -------------------------------
    path("get-csrf/", views.get_csrf, name="get_csrf"),
]