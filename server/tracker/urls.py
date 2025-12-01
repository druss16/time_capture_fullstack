# tracker/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ========================================
# Router for ViewSet-based endpoints
# ========================================
router = DefaultRouter()
router.register(r'task-types', views.TaskTypeViewSet, basename='task-type')
router.register(r'blocks-api', views.BlockCategorizationViewSet, basename='block-api')  # Renamed to avoid conflict

urlpatterns = [
    # -------------------------------
    # Basic / Health
    # -------------------------------
    path("ping/", views.ping, name="ping"),

    # -------------------------------
    # Agent Pairing & Communication
    # -------------------------------
    path("agents/pair/issue/", views.agents_pair_issue, name="agents_pair_issue"),
    path("agents/pair/claim/", views.agents_pair_claim, name="agents_pair_claim"),
    path("agents/hello2/", views.agents_hello2, name="agents_hello2"),
    path("raw-events/", views.raw_events, name="raw_events"),

    # -------------------------------
    # Client Selection (Agent)
    # -------------------------------
    path("client/set-current", views.set_current_client, name="set_current_client"),
    path("client/current", views.get_current_client, name="get_current_client"),
    path("clients/list", views.list_clients, name="list_clients"),
    path("context/guess", views.context_guess, name="context_guess"),
    path("context/confirm", views.context_confirm, name="context_confirm"),
    path("context/reject", views.context_reject, name="context_reject"),

    # -------------------------------
    # Manual Categorization (Legacy)
    # -------------------------------
    path("categorization/data/", views.get_categorization_data, name='categorization-data'),
    path("categorization/save/", views.save_categorization, name='categorization-save'),
    path("categorization/bulk/", views.bulk_categorize, name='categorization-bulk'),
    path("categorization/stats/", views.category_stats, name='categorization-stats'),



    # -------------------------------
    # Multi-tenant / org management
    # -------------------------------
    path("firm-signup/", views.firm_signup, name="firm_signup"),
    path("invite/", views.invite_team_member, name="invite_team_member"),
    path("invite/<str:token>/accept/", views.accept_invitation, name="accept_invitation"),

    # -------------------------------
    # Client & Project Management
    # -------------------------------
    path("clients/", views.create_client, name="create_client"),
    path("import-clients-csv/", views.import_clients_csv, name="import_clients_csv"),

    path("clients/<int:client_id>/", views.delete_client, name="delete_client"),

    
    # ✅ NEW: Dropdown data endpoints
    path("options/clients/", views.client_options, name="client_options"),
    path("options/projects/", views.project_options, name="project_options"),
    path("options/projects/<int:client_id>/", views.project_options_by_client, name="project_options_by_client"),
    path("options/task-types/", views.task_type_options, name="task_type_options"),


    path("projects/", views.list_projects, name="list_projects"),
    path("projects/create/", views.create_project, name="create_project"),
    path("projects/<int:project_id>/", views.update_project, name="update_project"),
    path("projects/<int:project_id>/delete/", views.delete_project, name="delete_project"),

    # -------------------------------
    # User Profile & Onboarding
    # -------------------------------
    path("profile/", views.user_profile, name="user_profile"),
    path("onboarding/complete", views.complete_onboarding, name="complete_onboarding"),

    # -------------------------------
    # Dashboard / Summary
    # -------------------------------
    path("today-time/", views.today_time, name="today_time"),

    path("blocks/<int:block_id>/recategorize/", views.recategorize_block, name="recategorize_block"),

    path("time-entries/manual/", views.create_manual_time_entry, name="create_manual_time_entry"),

    path("agent/register/", views.register_agent, name="register_agent"),

    # -------------------------------
    # Device Management
    # -------------------------------
    path("devices/", views.my_devices, name="my_devices"),
    path("devices/<int:pk>/revoke/", views.revoke_device, name="revoke_device"),

    # -------------------------------
    # Admin / Control
    # -------------------------------
    path("agent/control/", views.agent_control, name="agent_control"),
    path("whoami/", views.whoami, name="whoami"),

    # -------------------------------
    # Blocks (Legacy endpoints)
    # -------------------------------
    path("blocks-today/", views.blocks_today, name="blocks_today"),
    path("blocks/suggestions/", views.ai_suggestions_today, name="ai_suggestions_today"),
    path("blocks/<int:block_id>/classify/", views.save_block_classification, name="save_block_classification"),
    path("recent-blocks/", views.recent_classified_blocks, name="recent_classified_blocks"),
    path("label-block/", views.label_block, name="label_block"),
    path("blocks/<int:block_id>/delete/", views.delete_block, name="delete_block"),
    
    # ✅ NEW: Grouped blocks view (for hybrid UI)
    path("blocks/grouped/", views.blocks_grouped, name="blocks_grouped"),

    path("blocks/<int:block_id>/recategorize/", views.recategorize_block, name="recategorize_block"),

    # -------------------------------
    # Timecards
    # -------------------------------
    path("timecards/summary/day/", views.timecards_summary_day, name="timecards_summary_day"),

    # -------------------------------
    # Organization Settings
    # -------------------------------
    path("settings/organization/", views.organization_settings, name="organization_settings"),
    path("settings/entities/", views.known_entities, name="known_entities"),
    path("settings/entities/<int:entity_id>/", views.known_entity_detail, name="known_entity_detail"),
    path("settings/training/", views.save_training_example, name="save_training_example"),

    # -------------------------------
    # CSRF
    # -------------------------------
    path("get-csrf/", views.get_csrf, name="get_csrf"),

    # Settings endpoints
    path("settings/org/", views.settings_org, name="settings_org"),
    path("settings/team/", views.settings_team_list, name="settings_team_list"),
    path("settings/team/invite/", views.settings_team_invite, name="settings_team_invite"),
    path("settings/team/<int:user_id>/", views.settings_team_remove, name="settings_team_remove"),
    path("settings/clients/", views.settings_clients, name="settings_clients"),
    path("settings/clients/<int:client_id>/", views.settings_client_detail, name="settings_client_detail"),
    path("settings/devices/", views.settings_devices, name="settings_devices"),
    path("settings/devices/<int:device_id>/deactivate/", views.settings_device_deactivate, name="settings_device_deactivate"),
    path("settings/install-token/", views.settings_install_token, name="settings_install_token"),
    path("settings/install-token/regenerate/", views.settings_install_token_regenerate, name="settings_install_token_regenerate"),

    path("settings/team/<int:user_id>/promote/", views.settings_team_promote),
    path("settings/team/<int:user_id>/demote/", views.settings_team_demote),
    path("settings/team/<int:user_id>/set-manager/", views.settings_team_set_manager),
    
    # -------------------------------
    # Router URLs (ViewSets)
    # -------------------------------
    path("", include(router.urls)),
]