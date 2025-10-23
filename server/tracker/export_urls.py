from django.urls import path
from .export_views import export_blocks_today_csv

urlpatterns = [
    path("blocks-today.csv", export_blocks_today_csv),
]
