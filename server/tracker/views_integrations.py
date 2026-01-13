# tracker/views_integrations.py

import requests
from django.conf import settings
from django.shortcuts import redirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from urllib.parse import urlencode

from .models import Integration, OrganizationMembership


def get_user_org(user):
    membership = OrganizationMembership.objects.filter(user=user).select_related('organization').first()
    return membership.organization if membership else None


# ============================================================================
# QuickBooks Online
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_connect(request):
    """Start QuickBooks OAuth flow."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    # Store state for OAuth callback
    import secrets
    state = secrets.token_urlsafe(32)
    
    # Save state to verify callback
    Integration.objects.update_or_create(
        organization=org,
        provider='quickbooks',
        defaults={'oauth_state': state}
    )
    
    params = {
        'client_id': settings.QUICKBOOKS_CLIENT_ID,
        'response_type': 'code',
        'scope': 'com.intuit.quickbooks.accounting',
        'redirect_uri': settings.QUICKBOOKS_REDIRECT_URI,
        'state': state,
    }
    
    auth_url = f"https://appcenter.intuit.com/connect/oauth2?{urlencode(params)}"
    
    return Response({'auth_url': auth_url})


@api_view(['GET'])
def quickbooks_callback(request):
    """Handle QuickBooks OAuth callback."""
    code = request.GET.get('code')
    state = request.GET.get('state')
    realm_id = request.GET.get('realmId')
    error = request.GET.get('error')
    
    if error:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error={error}")
    
    # Find integration by state
    try:
        integration = Integration.objects.get(oauth_state=state, provider='quickbooks')
    except Integration.DoesNotExist:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=invalid_state")
    
    # Exchange code for tokens
    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    
    response = requests.post(token_url, data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': settings.QUICKBOOKS_REDIRECT_URI,
    }, auth=(settings.QUICKBOOKS_CLIENT_ID, settings.QUICKBOOKS_CLIENT_SECRET))
    
    if response.status_code != 200:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")
    
    tokens = response.json()
    
    # Save tokens
    integration.access_token = tokens['access_token']
    integration.refresh_token = tokens['refresh_token']
    integration.realm_id = realm_id
    integration.is_connected = True
    integration.save()
    
    # Return HTML that posts message to parent window
    return HttpResponse(f"""
        <html>
        <script>
            window.opener.postMessage({{
                type: 'oauth_callback',
                integration: 'quickbooks',
                success: true
            }}, '{settings.FRONTEND_URL}');
            window.close();
        </script>
        </html>
    """)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_status(request):
    """Check QuickBooks connection status."""
    org = get_user_org(request.user)
    if not org:
        return Response({'connected': False})
    
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks')
        return Response({'connected': integration.is_connected})
    except Integration.DoesNotExist:
        return Response({'connected': False})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_clients(request):
    """Fetch customers from QuickBooks."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks', is_connected=True)
    except Integration.DoesNotExist:
        return Response({'error': 'Not connected to QuickBooks'}, status=400)
    
    # Refresh token if needed
    # ... (add token refresh logic)
    
    # Fetch customers from QuickBooks API
    api_url = f"https://quickbooks.api.intuit.com/v3/company/{integration.realm_id}/query"
    
    headers = {
        'Authorization': f'Bearer {integration.access_token}',
        'Accept': 'application/json',
    }
    
    query = "SELECT * FROM Customer WHERE Active = true MAXRESULTS 1000"
    
    response = requests.get(f"{api_url}?query={query}", headers=headers)
    
    if response.status_code != 200:
        return Response({'error': 'Failed to fetch customers'}, status=500)
    
    data = response.json()
    customers = data.get('QueryResponse', {}).get('Customer', [])
    
    clients = [{
        'id': c['Id'],
        'name': c.get('DisplayName') or c.get('CompanyName') or c.get('FullyQualifiedName'),
        'email': c.get('PrimaryEmailAddr', {}).get('Address'),
        'balance': c.get('Balance', 0),
    } for c in customers]
    
    return Response({'clients': clients})


# ============================================================================
# Xero
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xero_connect(request):
    """Start Xero OAuth flow."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    import secrets
    state = secrets.token_urlsafe(32)
    
    Integration.objects.update_or_create(
        organization=org,
        provider='xero',
        defaults={'oauth_state': state}
    )
    
    params = {
        'response_type': 'code',
        'client_id': settings.XERO_CLIENT_ID,
        'redirect_uri': settings.XERO_REDIRECT_URI,
        'scope': 'openid profile email accounting.contacts.read',
        'state': state,
    }
    
    auth_url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params)}"
    
    return Response({'auth_url': auth_url})


# ... Similar callback/status/clients endpoints for Xero