from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("tracker/", include("tracker.urls")),   # all tracker endpoints live here
    path("export/", include("tracker.export_urls")),  # CSV export, keep clean
]
