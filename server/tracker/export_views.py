from __future__ import annotations
import csv, io
from django.utils import timezone
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated

from django.conf import settings
from .models import Block

USE_AUTH = bool(getattr(settings, "USE_AUTH", False))
PermUI = IsAuthenticated if USE_AUTH else AllowAny

@api_view(["GET"])
@permission_classes([PermUI])
def export_blocks_today_csv(_request):
    today = timezone.localdate()
    qs = Block.objects.filter(start__date=today).order_by("start")

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["start","end","minutes","title","url","file_path","client","project","task","notes"])

    for b in qs:
        minutes = int((b.end - b.start).total_seconds() / 60)
        w.writerow([
            b.start.isoformat(),
            b.end.isoformat(),
            minutes,
            (b.title or "").replace("\n", " ").strip(),
            b.url or "",
            b.file_path or "",
            getattr(b.client, "name", "") or "",
            getattr(b.project, "name", "") or "",
            getattr(b.task, "name", "") or "",
            (getattr(b, "notes", "") or "").replace("\n", " ").strip(),
        ])

    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="blocks_today.csv"'
    return resp
