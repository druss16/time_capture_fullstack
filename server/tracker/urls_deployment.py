from django.urls import path
from . import views_deployment, views_autopair

urlpatterns = [
    # Admin endpoints (authenticated)
    path('tokens/', views_deployment.list_deployment_tokens, name='deploy-tokens-list'),
    path('tokens/create/', views_deployment.create_deployment_token, name='deploy-tokens-create'),
    path('tokens/<int:token_id>/revoke/', views_deployment.revoke_deployment_token, name='deploy-tokens-revoke'),
    # Agent endpoints (org_token auth)
    path('claim/', views_deployment.deploy_claim, name='deploy-claim'),
    path('confirm-user/', views_deployment.deploy_confirm_user, name='deploy-confirm-user'),
    # Provisioning monitoring
    path('provisioning/<slug:org_slug>/status/', views_deployment.provisioning_status, name='provisioning-status'),

    path('auto-pair/', views_autopair.auto_pair_device, name='deploy-auto-pair'),

]