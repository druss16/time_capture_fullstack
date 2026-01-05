from django.contrib import admin
from django.urls import path, include
from tracker import views as tracker_views


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("api/", include("tracker.urls")),
    path("export/", include("tracker.export_urls")),  # CSV export

        # --------------------------------------------------------------------
    # JSON API endpoints for SPA (frontend)
    # --------------------------------------------------------------------
    path("api/auth/login/",  tracker_views.auth_login,  name="auth_login"),
    path("api/auth/logout/", tracker_views.auth_logout, name="auth_logout"),
    path("api/auth/signup/", tracker_views.auth_signup, name="auth_signup"),
    path("api/whoami/",      tracker_views.whoami,      name="whoami"),
    path('api/onboarding/', include('tracker.urls_onboarding')),
]
