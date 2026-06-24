"""
Show the actual error the view returned (detail + status), and run the inner
helper directly with a traceback so we see the real exception line.

    docker compose exec -T api python manage.py shell < debug_trend2.py
"""
import traceback
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from tracker.views_reports import (
    reports_ai_performance, _ai_perf_for_window,
    _resolve_period_window, _day_bounds_utc, _resolve_scope,
)
from tracker.views import get_request_org_override

User = get_user_model()
u = User.objects.filter(is_staff=True).first()
req = RequestFactory().get('/api/reports/ai-performance/',
                           {'period': 'week', 'trend': '8', 'org_id': '21'})
req.user = u

# 1. The actual error envelope + HTTP status.
resp = reports_ai_performance(req)
print("status_code:", resp.status_code)
print("detail:", resp.data.get("detail"))

# 2. Reproduce the inner call with a real traceback so we see WHICH line.
print("\n--- direct helper call with traceback ---")
try:
    org = get_request_org_override(req)
    can_see_all, forced_user_id = _resolve_scope(req, org)
    start_date, end_date = _resolve_period_window("week", __import__("django.utils.timezone", fromlist=["localdate"]).localdate())
    start_utc, end_utc = _day_bounds_utc(start_date, end_date)
    pt = _ai_perf_for_window(org, start_utc, end_utc, can_see_all, forced_user_id)
    print("inner helper OK:", {k: pt[k] for k in ("ai_override_rate", "ai_decisions")})
except Exception:
    traceback.print_exc()
