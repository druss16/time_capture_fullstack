"""
Test the trend endpoint the RIGHT way — with a real authenticated user, using
DRF's force_authenticate (RequestFactory can't carry auth, which is why the
earlier tests got 403/AnonymousUser).

    docker compose exec -T api python manage.py shell < debug_trend3.py
"""
import json
from rest_framework.test import APIRequestFactory, force_authenticate
from django.contrib.auth import get_user_model
from tracker.views_reports import reports_ai_performance

User = get_user_model()

# Use a staff user so ?org_id=21 impersonation is honored.
u = User.objects.filter(is_staff=True).first()
print("authenticating as:", u.username, "| staff:", u.is_staff)

factory = APIRequestFactory()
req = factory.get('/api/reports/ai-performance/',
                  {'period': 'week', 'trend': '8', 'org_id': '21'})
force_authenticate(req, user=u)        # <-- the missing piece

resp = reports_ai_performance(req)
print("status_code:", resp.status_code)

if resp.status_code != 200:
    print("error detail:", resp.data)
else:
    print("\ncurrent override rate:", resp.data.get("ai_override_rate"), "%")
    print("confirmation rate:", resp.data.get("ai_confirmation_rate"), "%")
    trend = resp.data.get("trend")
    if trend is None:
        print("trend: null (something still gating it)")
    else:
        print(f"\ntrend: {len(trend)} weekly points")
        print(f"  {'week of':<12} {'override%':>10} {'ai_calls':>9}")
        for pt in trend:
            r = pt['ai_override_rate']
            print(f"  {pt['bucket']:<12} {('—' if r is None else r):>10} {pt['ai_decisions']:>9}")
