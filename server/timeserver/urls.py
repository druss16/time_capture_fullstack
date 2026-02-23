from django.contrib import admin
from django.urls import path, include
from django.views.decorators.csrf import csrf_exempt  # ← Add this
from django.views.generic import TemplateView
from tracker import views as tracker_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("api/", include("tracker.urls")),
    path("export/", include("tracker.export_urls")),
    
    # Auth endpoints - CSRF exempt for cross-origin token auth
    path("api/auth/login/",  csrf_exempt(tracker_views.auth_login),  name="auth_login"),
    path("api/auth/logout/", csrf_exempt(tracker_views.auth_logout), name="auth_logout"),
    path("api/auth/signup/", csrf_exempt(tracker_views.auth_signup), name="auth_signup"),
    
    path("api/whoami/",      tracker_views.whoami,      name="whoami"),
    path('api/onboarding/', include('tracker.urls_onboarding')),
    path('api/billing/', include('tracker.urls_billing')),

    path('eula/', TemplateView.as_view(template_name='legal/eula.html'), name='eula'),
    path('privacy/', TemplateView.as_view(template_name='legal/privacy.html'), name='privacy'),
    path('api/deploy/', include('tracker.urls_deployment')),
]