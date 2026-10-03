"""/api/onboard/ — the Onboarding Console. See views_onboarding_console.py."""
from django.urls import path

from tracker import views_onboarding_console as v

urlpatterns = [
    path('me/', v.console_me, name='onboard-me'),
    path('projects/', v.projects, name='onboard-projects'),
    path('orgs/adoptable/', v.adoptable_orgs, name='onboard-adoptable-orgs'),
    path('projects/<int:pk>/', v.project_detail, name='onboard-project'),
    path('projects/<int:pk>/steps/<str:step_key>/', v.mark_step, name='onboard-step'),
    path('projects/<int:pk>/verify/', v.verify, name='onboard-verify'),
    path('projects/<int:pk>/audit/', v.audit_log, name='onboard-audit'),
    path('projects/<int:pk>/import/', v.run_import, name='onboard-import'),
    path('projects/<int:pk>/intake-csv/<str:kind>/', v.intake_csv, name='onboard-intake-csv'),
    path('projects/<int:pk>/mappings/', v.mappings, name='onboard-mappings'),
    path('projects/<int:pk>/mappings/suggest/', v.suggest_mappings, name='onboard-mappings-suggest'),
    path('projects/<int:pk>/invites/', v.invites, name='onboard-invites'),
    path('projects/<int:pk>/token/', v.token, name='onboard-token'),
    path('projects/<int:pk>/pairing/', v.pairing, name='onboard-pairing'),
    path('projects/<int:pk>/aliases/', v.aliases, name='onboard-aliases'),
    path('projects/<int:pk>/clio-trigger/', v.clio_trigger, name='onboard-clio-trigger'),
    path('projects/<int:pk>/stripe/', v.stripe_setup, name='onboard-stripe'),
    path('projects/<int:pk>/deploy-kit/', v.deploy_kit, name='onboard-deploy-kit'),
    path('projects/<int:pk>/go-live/', v.go_live, name='onboard-go-live'),
    path('projects/<int:pk>/delete/', v.delete_project, name='onboard-delete'),
    path('projects/<int:pk>/intake/', v.intake_link, name='onboard-intake-link'),
    path('projects/<int:pk>/intake/reopen/', v.intake_reopen, name='onboard-intake-reopen'),
    # The firm's side: no login, the token in the path is the whole credential.
    path('intake/<str:raw>/', v.PublicIntake.as_view(), name='onboard-public-intake'),
]
