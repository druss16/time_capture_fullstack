"""
Why did ?trend=8 come back null? Print the decision points.

    docker compose exec -T api python manage.py shell < debug_trend.py
"""
import json
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from tracker import views_reports as vr
from tracker.views_reports import reports_ai_performance, _ai_perf_for_window
from tracker.views import get_request_org_override, get_user_role

User = get_user_model()

# 1. Who is the staff user, and what org does the request resolve to?
u = User.objects.filter(is_staff=True).first()
print("staff user:", u.username if u else None, "| is_staff:", getattr(u, "is_staff", None))

factory = RequestFactory()
req = factory.get('/api/reports/ai-performance/',
                  {'period': 'week', 'trend': '8', 'org_id': '21'})
req.user = u

# 2. What does org resolution return for this synthetic request?
try:
    org = get_request_org_override(req)
    print("resolved org:", org.id if org else None, "(expected 21)")
except Exception as e:
    print("get_request_org_override raised:", repr(e))
    org = None

# 3. Read the trend param exactly as the view does.
trend_n = req.GET.get("trend")
custom_start = req.GET.get("start")
custom_end = req.GET.get("end")
print("trend param:", trend_n, "| custom_start:", custom_start, "| custom_end:", custom_end)

# 4. Call the real view and dump the WHOLE response, not just trend.
resp = reports_ai_performance(req)
print("\n--- full response keys:", list(resp.data.keys()))
print("range:", resp.data.get("range"))
print("counts:", resp.data.get("counts"))
print("trend is:", "null" if resp.data.get("trend") is None else f"{len(resp.data['trend'])} points")
