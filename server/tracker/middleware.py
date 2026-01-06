# tracker/middleware.py
"""
Middleware for subscription/trial checks.
"""

from django.http import JsonResponse
from django.utils import timezone
from django.conf import settings

from .models import OrganizationMembership


# Paths that don't require subscription
EXEMPT_PATHS = [
    '/api/auth/',
    '/api/onboarding/',
    '/api/billing/',
    '/api/whoami/',
    '/admin/',
    '/accounts/',
    '/static/',
]


class SubscriptionMiddleware:
    """
    Check if user's organization has an active subscription or trial.
    Returns 402 Payment Required if trial expired and no subscription.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Skip check for exempt paths
        if any(request.path.startswith(path) for path in EXEMPT_PATHS):
            return self.get_response(request)
        
        # Skip for non-authenticated users (they'll hit 401 elsewhere)
        if not request.user.is_authenticated:
            return self.get_response(request)
        
        # Skip for superusers/staff
        if request.user.is_superuser or request.user.is_staff:
            return self.get_response(request)
        
        # Check subscription status
        membership = OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
        
        if not membership:
            return self.get_response(request)
        
        org = membership.organization
        
        # Check if subscription is active
        if org.plan in ['starter', 'professional', 'enterprise']:
            # Has active paid plan
            return self.get_response(request)
        
        # Check trial status
        if org.trial_ends_at:
            if org.trial_ends_at > timezone.now():
                # Trial still active
                return self.get_response(request)
            else:
                # Trial expired
                return JsonResponse({
                    'error': 'subscription_required',
                    'message': 'Your trial has expired. Please subscribe to continue.',
                    'trial_ended_at': org.trial_ends_at.isoformat(),
                    'billing_url': '/billing',
                }, status=402)
        
        # No trial and no subscription
        return JsonResponse({
            'error': 'subscription_required',
            'message': 'A subscription is required to access this feature.',
            'billing_url': '/billing',
        }, status=402)