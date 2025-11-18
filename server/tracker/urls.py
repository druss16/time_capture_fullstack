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

        # === ADD THESE 6 NEW ROUTES HERE ===
    path("client/set-current", views.set_current_client, name="set_current_client"),
    path("client/current", views.get_current_client, name="get_current_client"),
    path("clients/list", views.list_clients, name="list_clients"),
    path("context/guess", views.context_guess, name="context_guess"),
    path("context/confirm", views.context_confirm, name="context_confirm"),
    path("context/reject", views.context_reject, name="context_reject"),
    # path('bulk-assign/', views.dbulk_assign_current_client, name='bulk_assign_current_client'),

    # Manual categorization endpoints
    path("categorization/data/", views.get_categorization_data, name='categorization-data'),
    path("categorization/save/", views.save_categorization, name='categorization-save'),
    path("categorization/bulk/", views.bulk_categorize, name='categorization-bulk'),
    path("categorization/stats/", views.category_stats, name='categorization-stats'),
 

    # === END NEW ROUTES ===

    # 👇 ADD THESE NEW ROUTES:
    path("clients/", views.create_client, name="create_client"),  # POST to create client
    path("import-clients-csv/", views.import_clients_csv, name="import_clients_csv"),  # POST to import CSV
    path("profile/", views.user_profile, name="user_profile"),  # GET user profile
    path("onboarding/complete", views.complete_onboarding, name="complete_onboarding"),  # POST to complete onboarding

    path("today-time/", views.today_time, name="today_time"),


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
    path("blocks/<int:block_id>/classify/", views.save_block_classification, name="save_block_classification"),
    path("recent-blocks/", views.recent_classified_blocks, name="recent_classified_blocks"),
    path("label-block/", views.label_block, name="label_block"),

    # -------------------------------
    # Timecards
    # -------------------------------
    path("timecards/summary/day/", views.timecards_summary_day, name="timecards_summary_day"),


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