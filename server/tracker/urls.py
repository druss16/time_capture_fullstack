# tracker/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from django.views.decorators.csrf import csrf_exempt
from . import views
from . import views_billing, views_settings, views_integrations, views_bulk_assignments, views_sync, views_client_groups, views_notifications, views_deployment, views_ai_classify, views_analytics, views_ai_analysis

# ========================================
# Router for ViewSet-based endpoints
# ========================================
router = DefaultRouter()
router.register(r'task-types', views.TaskTypeViewSet, basename='task-type')
router.register(r'blocks-api', views.BlockCategorizationViewSet, basename='block-api')

# ✅ ADD: Billing ViewSets
router.register(r'billing/rates', views_billing.BillingRateViewSet, basename='billing-rate')
router.register(r'billing/timesheets', views_billing.TimesheetViewSet, basename='timesheet')

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
    path("client/set-current/", csrf_exempt(views.set_current_client), name="set_current_client"),
    path("client/current/", csrf_exempt(views.get_current_client), name="get_current_client"),
    path("clients/list/", views.list_clients, name="list_clients"),
    path("context/guess/", views.context_guess, name="context_guess"),
    path("context/confirm/", views.context_confirm, name="context_confirm"),
    path("context/reject/", views.context_reject, name="context_reject"),

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

    # Dropdown data endpoints
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
    path("blocks/grouped/", views.blocks_grouped, name="blocks_grouped"),

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

    # -------------------------------
    # Settings endpoints
    # -------------------------------
    path("settings/org/", views.settings_org, name="settings_org"),
    # path("settings/ai/", views.org_ai_settings, name="org_ai_settings"),
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
    path('settings/membership/', views.CurrentMembershipView.as_view(), name='current-membership'),

    # Seat management (in settings, but functions live in views_billing)
    path("settings/seats/", views_billing.get_seat_usage, name="seat-usage"),
    path("settings/seats/add/", views_billing.add_seats, name="add-seats"),

    # In urls.py, add:
    path('settings/seats/reduce/', views_billing.reduce_seats, name='reduce-seats'),
    path('settings/plan/change/', views_billing.change_plan, name='change-plan'),

    path('settings/my-clients/', views_settings.get_my_clients, name='my-clients'),
    path('settings/client-assignments/', views_settings.client_assignments_list, name='client-assignments'),
    path('settings/client-assignments/<int:assignment_id>/', views_settings.client_assignment_delete, name='client-assignment-delete'),
    path('settings/client-assignments/bulk/', views_settings.bulk_assign_clients, name='bulk-assign-clients'),
    path('settings/client-assignments/import/', views_settings.import_client_assignments_csv, name='import-client-assignments'),

    path('settings/client-requests/', views_settings.client_requests),
    path('settings/client-requests/<int:request_id>/approve/', views_settings.approve_client_request),

    # ===============================
    # ✅ NEW: BILLING & TIMESHEETS
    # ===============================
    
    # Timesheet Views (employee-facing)
    path("billing/weekly/", views_billing.weekly_timesheet_view, name="weekly-timesheet"),
    
    # Approval Workflow (manager-facing)
    path("billing/approval-queue/", views_billing.approval_queue, name="approval-queue"),
    
    # Client Billing Summary (for invoicing)
    path("billing/client-summary/", views_billing.client_summary_view, name="client-summary"),
    
    # Invoice Export
    path("billing/invoice/<int:client_id>/", views_billing.invoice_export, name="invoice-export"),
    path("billing/mark-invoiced/", views_billing.mark_invoiced, name="mark-invoiced"),
    
    # Block Billing Management
    path("billing/blocks/<int:block_id>/", views_billing.update_block_billing, name="update-block-billing"),
    path("billing/blocks/<int:block_id>/audit/", views_billing.block_audit_history, name="block-audit"),

    # Employee Cost Rates
    path('billing/cost-rates/', views_billing.EmployeeCostRateListView.as_view(), name='cost-rate-list'),
    path('billing/cost-rates/<int:pk>/', views_billing.EmployeeCostRateDetailView.as_view(), name='cost-rate-detail'),

    # Profitability Report
    path('billing/profitability/', views_billing.ProfitabilityReportView.as_view(), name='profitability-report'),

    # Change lines 156-157 to:
    path('billing/rates/', views_billing.billing_rates_list, name='billing-rates-list'),
    path('billing/rates/<int:rate_id>/', views_billing.billing_rates_detail, name='billing-rates-detail'),

    path('billing/timesheets/<int:pk>/submit/', views_billing.TimesheetSubmitView.as_view(), name='timesheet-submit'),
    path('billing/timesheets/<int:pk>/approve/', views_billing.TimesheetApproveView.as_view(), name='timesheet-approve'),
    path('billing/timesheets/<int:pk>/reject/', views_billing.TimesheetRejectView.as_view(), name='timesheet-reject'),
    path('billing/timesheets/<int:pk>/reopen/', views_billing.TimesheetReopenView.as_view(), name='timesheet-reopen'),
    path('billing/timesheets/<int:pk>/lock/', views_billing.TimesheetLockView.as_view()),  # NEW

    # History
    path('billing/timesheet-history/', views_billing.timesheet_history),  # NEW
    
    # Invoice Management
    path('billing/invoices/', views_billing.list_invoices, name='list_invoices'),
    path('billing/invoices/match/', views_billing.match_invoice_client, name='match_invoice_client'),
    
    # Realization Report
    # path('billing/realization/', views_billing.realization_report, name='realization_report'),

    # Client Budgets
    path('billing/budgets/', views_billing.client_budgets_list),
    path('billing/budgets/<int:budget_id>/', views_billing.client_budgets_detail),

    path('billing/clients/update-billed/', views_billing.update_client_billed, name='update-client-billed'),
    path('billing/export/worked-hours/', views_billing.export_worked_hours_csv, name='export-worked-hours'),
    path('billing/realization/', views_billing.realization_with_editable, name='realization-editable'),

    path('billing/invoices/conflicts/', views_integrations.invoice_conflicts_count),
    path('billing/invoices/conflicts/<int:conflict_id>/resolve/', views_integrations.resolve_invoice_conflict),

    path('billing/invoices/quickbooks/', views_billing.quickbooks_invoices, name='qb-invoices-preview'),
    path('billing/invoices/quickbooks/import/', views_billing.quickbooks_import_invoices, name='qb-invoices-import'),

    path('billing/invoices/import-csv/',     views_billing.import_invoices_csv,    name='csv-preview'),
    path('billing/invoices/import-csv/commit/', views_billing.csv_invoice_commit,  name='csv-commit'),
    path('billing/invoices/import-csv/template/', views_billing.csv_invoice_template, name='csv-template'),
    path('billing/invoices/<int:invoice_id>/delete/', views_billing.delete_invoice, name='delete_invoice'),


        

    path('auth/change-password/', views.auth_change_password, name='auth_change_password'),

    # ── Integrations ──
    path('integrations/status/', views_integrations.integrations_status, name='integrations-status'),

    # QuickBooks
    path('integrations/quickbooks/connect/', views_integrations.quickbooks_connect, name='quickbooks-connect'),
    path('integrations/quickbooks/callback/', views_integrations.quickbooks_callback, name='quickbooks-callback'),
    path('integrations/quickbooks/status/', views_integrations.quickbooks_status, name='quickbooks-status'),
    path('integrations/quickbooks/disconnect/', views_integrations.quickbooks_disconnect, name='quickbooks-disconnect'),
    path('integrations/quickbooks/customers/', views_integrations.quickbooks_customers, name='quickbooks-customers'),
    path('integrations/quickbooks/import/', views_integrations.quickbooks_import, name='quickbooks-import'),
    path('integrations/quickbooks/push-time/', views_integrations.quickbooks_push_time, name='quickbooks-push-time'),
    path('integrations/quickbooks/push-status/<str:task_id>/', views_integrations.quickbooks_push_status, name='quickbooks-push-status'),
    path('integrations/quickbooks/invoices/', views_integrations.quickbooks_pull_invoices, name='quickbooks-invoices'),
    path('integrations/qb/webhook/', views_integrations.quickbooks_webhook),

    path('integrations/qb/sync-invoices/', views_integrations.manual_sync_invoices),




    # Xero
    path('integrations/xero/connect/', views_integrations.xero_connect, name='xero-connect'),
    path('integrations/xero/callback/', views_integrations.xero_callback, name='xero-callback'),
    path('integrations/xero/status/', views_integrations.xero_status, name='xero-status'),
    path('integrations/xero/disconnect/', views_integrations.xero_disconnect, name='xero-disconnect'),
    path('integrations/xero/contacts/', views_integrations.xero_contacts, name='xero-contacts'),
    path('integrations/xero/import/', views_integrations.xero_import, name='xero-import'),
    path('integrations/xero/push-time/', views_integrations.xero_push_time, name='xero-push-time'),
    path('integrations/xero/invoices/', views_integrations.xero_pull_invoices, name='xero-invoices'),
    path('clients/bulk-assign/', views_bulk_assignments.bulk_assign_clients, name='bulk-assign-clients'),
    path('clients/bulk-unassign/', views_bulk_assignments.bulk_unassign_clients, name='bulk-unassign-clients'),
    path('clients/copy-assignments/', views_bulk_assignments.copy_assignments, name='copy-assignments'),
    
    # CSV import
    path('clients/assignment-template/', views_bulk_assignments.assignment_csv_template, name='assignment-template'),
    path('clients/import-assignments/', views_bulk_assignments.import_assignments_csv, name='import-assignments'),

    # Quick minimal sync using existing endpoints
    path('sync/status/', views_sync.sync_status, name='sync-status'),
    path('sync/clients/', views_sync.sync_clients, name='sync-clients'),
    path('sync/projects/', views_sync.sync_projects, name='sync-projects'),
    path('sync/task-types/', views_sync.sync_task_types, name='sync-task-types'),
    path('sync/full/', views_sync.sync_full, name='sync-full'),

    path('agent/errors/', views.agent_error_report, name='agent-error-report'),
    path('agent/errors/list/', views.agent_errors_list, name='agent-errors-list'),
    path('agent/errors/summary/', views.agent_errors_summary, name='agent-errors-summary'),
    path('agent/errors/<int:error_id>/', views.agent_error_detail, name='agent-error-detail'),
    path('agent/errors/<int:error_id>/resolve/', views.agent_error_resolve, name='agent-error-resolve'),

    path('categories/', views.get_org_categories, name='get_org_categories'),
    path('industries/', views.get_industry_options, name='get_industry_options'),

    # Client Groups
    path('settings/client-groups/', views_client_groups.client_groups_list, name='client-groups-list'),
    path('settings/client-groups/<int:group_id>/', views_client_groups.client_groups_detail, name='client-groups-detail'),
    
    # Bulk client operations
    path('settings/client-groups/<int:group_id>/add-clients/', views_client_groups.client_groups_add_clients, name='client-groups-add-clients'),
    path('settings/client-groups/<int:group_id>/remove-clients/', views_client_groups.client_groups_remove_clients, name='client-groups-remove-clients'),
    
    # Team assignment (the key feature!)
    path('settings/client-groups/<int:group_id>/assign-team/', views_client_groups.client_groups_assign_team, name='client-groups-assign-team'),
    path('settings/client-groups/<int:group_id>/remove-team/', views_client_groups.client_groups_remove_team, name='client-groups-remove-team'),
    
    # CSV Import
    path('settings/client-groups/import/', views_client_groups.client_groups_import_csv, name='client-groups-import'),
    path('settings/client-groups/template/', views_client_groups.client_groups_template, name='client-groups-template'),
    
    # Utility
    path('settings/clients/ungrouped/', views_client_groups.ungrouped_clients, name='ungrouped-clients'),


    path('timesheet/needs-review/', views_notifications.timesheet_needs_review, name='timesheet-needs-review'),
    path('timesheet/dismiss-reminder/', views_notifications.dismiss_timesheet_reminder, name='dismiss-timesheet-reminder'),
    path('notifications/preferences/', views_notifications.notification_preferences, name='notification-preferences'),
    path('agent/startup-notification/', views_notifications.agent_startup_notification, name='agent-startup-notification'),

    path('timesheet/yesterday-summary/', views.yesterday_summary, name='yesterday-summary'),

    path('agent/version-check/', views.agent_version_check),

    path("user/preferences/", views.user_preferences, name="user_preferences"),

    # AI Classification (backend-powered)
    path('ai/classify-window/', views_ai_classify.ai_classify_window, name='ai-classify-window'),
    path('ai/classify-batch/', views_ai_classify.ai_classify_batch, name='ai-classify-batch'),

    # ===============================
    # ✅ EXECUTIVE ANALYTICS
    # ===============================

    path("analytics/executive/", views_analytics.executive_dashboard, name="analytics-executive"),

    # tracker/urls.py — add this line:
    path("analytics/ai-analysis/", views_ai_analysis.ai_analysis),

    path('blocks/<int:block_id>/dismiss-review/', views.dismiss_block_review),


]