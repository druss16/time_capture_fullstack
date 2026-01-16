# tracker/urls_billing.py
"""
URL routes for Stripe billing integration.
Add to main urls.py: path('api/billing/', include('tracker.urls_billing')),
"""

from django.urls import path
from . import views_billing

urlpatterns = [
    # Checkout
    path('create-checkout-session/', views_billing.create_checkout_session, name='create_checkout_session'),
    path('portal/', views_billing.create_billing_portal_session, name='billing_portal'),
    
    # Status
    path('subscription/', views_billing.get_subscription_status, name='subscription_status'),
    
    # Webhook (Stripe calls this)
    path('webhook/', views_billing.stripe_webhook, name='stripe_webhook'),
]