from django.contrib import admin
from django.urls import path, include
from django.views.decorators.csrf import csrf_exempt  # ← Add this
from django.views.generic import RedirectView
from django.http import JsonResponse
from tracker import views as tracker_views
from rest_framework.routers import DefaultRouter

def ms_identity_association(request):
    return JsonResponse({
        "associatedApplications": [
            {"applicationId": "1178d566-16f1-4c70-b30a-a046c5879688"},  # TimeTracker Calendar Integration
            {"applicationId": "6424c9a7-83f3-41ee-bd62-8e273a027ce6"},  # TimeTracker Mail
        ]
    })

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

    path("api/support/", include("tracker.support.urls")),

    path(".well-known/microsoft-identity-association.json", ms_identity_association),

    path('eula/', RedirectView.as_view(url='https://timetracker.mavops.ai/eula.html', permanent=False), name='eula'),
    # One privacy policy: the frontend's public/privacy.html. This old template
    # copy had drifted (wrong company, no Google section), so redirect to it.
    path('privacy/', RedirectView.as_view(url='https://timetracker.mavops.ai/privacy.html', permanent=False), name='privacy'),
    path('api/deploy/', include('tracker.urls_deployment')),
    path('api/onboard/', include('tracker.urls_onboarding_console')),  # Onboarding Console (own firewall)
    path('api/mobile/', include('mobile.urls')),  # ← add this
    # path('api/events/', include('django_eventstream.urls'), name='events'),   # disabled until ASGI — SSE kills sync gunicorn workers
]