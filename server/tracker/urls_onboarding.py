from django.urls import path
from . import views_onboarding

urlpatterns = [
    # Step 1: Signup
    path('signup/', views_onboarding.onboarding_signup, name='onboarding_signup'),
    
    # Onboarding status
    path('status/', views_onboarding.onboarding_status, name='onboarding_status'),
    
    # Step 2: Integrations
    path('integrations/', views_onboarding.integration_list, name='integration_list'),
    path('integrations/<str:provider>/connect/', views_onboarding.integration_connect, name='integration_connect'),
    path('integrations/<str:provider>/disconnect/', views_onboarding.integration_disconnect, name='integration_disconnect'),
    path('integrations/skip/', views_onboarding.skip_integration, name='skip_integration'),
    
    # Step 3: Team invites
    path('team/invite/', views_onboarding.invite_team_bulk, name='invite_team_bulk'),
    path('team/status/', views_onboarding.team_status, name='team_status'),
    path('team/skip/', views_onboarding.skip_team_invites, name='skip_team_invites'),
    
    # Step 4: Billing rates
    path('rates/default/', views_onboarding.set_default_rate, name='set_default_rate'),
    path('rates/skip/', views_onboarding.skip_rates, name='skip_rates'),
    
    # Step 5: Complete
    path('complete/', views_onboarding.complete_onboarding, name='complete_onboarding'),
    
    # Agent download
    path('download/', views_onboarding.agent_download_info, name='agent_download_info'),
]
