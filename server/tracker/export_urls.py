from django.urls import path
from . import export_views

urlpatterns = [
    path("csv", export_views.export_csv, name="export-csv"),  # /export/csv?from=YYYY-MM-DD&to=YYYY-MM-DD
]
