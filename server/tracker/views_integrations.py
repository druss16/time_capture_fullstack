# tracker/views_integrations.py

import requests
import logging
from datetime import timedelta
from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from urllib.parse import urlencode
from django.http import HttpResponse
from .models import Integration, OrganizationMembership, Client

logger = logging.getLogger(__name__)


def get_user_org(user):
    """Get the user's organization."""
    membership = OrganizationMembership.objects.filter(user=user).select_related('organization').first()
    return membership.organization if membership else None


# ============================================================================
# Token Refresh Helpers
# ============================================================================

def refresh_quickbooks_token(integration):
    """
    Refresh QuickBooks access token if expired or expiring soon.
    Returns True if successful, False if refresh failed.
    """
    # Check if token needs refresh (refresh 5 min before expiry)
    if integration.token_expires_at:
        if integration.token_expires_at > timezone.now() + timedelta(minutes=5):
            return True  # Token still valid
    
    if not integration.refresh_token:
        logger.error(f"No refresh token for QB integration {integration.id}")
        return False
    
    logger.info(f"Refreshing QuickBooks token for org {integration.organization_id}")
    
    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    
    try:
        response = requests.post(
            token_url,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': integration.refresh_token,
            },
            auth=(settings.QUICKBOOKS_CLIENT_ID, settings.QUICKBOOKS_CLIENT_SECRET),
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"QB token refresh failed: {response.status_code} - {response.text}")
            # Mark as disconnected if refresh fails
            integration.is_connected = False
            integration.save(update_fields=['is_connected'])
            return False
        
        tokens = response.json()
        
        integration.access_token = tokens['access_token']
        integration.refresh_token = tokens.get('refresh_token', integration.refresh_token)
        # QB tokens expire in 1 hour (3600 seconds)
        integration.token_expires_at = timezone.now() + timedelta(seconds=tokens.get('expires_in', 3600))
        integration.save(update_fields=['access_token', 'refresh_token', 'token_expires_at'])
        
        logger.info(f"QB token refreshed successfully, expires at {integration.token_expires_at}")
        return True
        
    except requests.RequestException as e:
        logger.error(f"QB token refresh request failed: {e}")
        return False


def refresh_xero_token(integration):
    """
    Refresh Xero access token if expired or expiring soon.
    Returns True if successful, False if refresh failed.
    """
    # Check if token needs refresh (refresh 5 min before expiry)
    if integration.token_expires_at:
        if integration.token_expires_at > timezone.now() + timedelta(minutes=5):
            return True  # Token still valid
    
    if not integration.refresh_token:
        logger.error(f"No refresh token for Xero integration {integration.id}")
        return False
    
    logger.info(f"Refreshing Xero token for org {integration.organization_id}")
    
    token_url = "https://identity.xero.com/connect/token"
    
    try:
        response = requests.post(
            token_url,
            data={
                'grant_type': 'refresh_token',
                'refresh_token': integration.refresh_token,
            },
            auth=(settings.XERO_CLIENT_ID, settings.XERO_CLIENT_SECRET),
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"Xero token refresh failed: {response.status_code} - {response.text}")
            integration.is_connected = False
            integration.save(update_fields=['is_connected'])
            return False
        
        tokens = response.json()
        
        integration.access_token = tokens['access_token']
        integration.refresh_token = tokens.get('refresh_token', integration.refresh_token)
        # Xero tokens expire in 30 minutes (1800 seconds)
        integration.token_expires_at = timezone.now() + timedelta(seconds=tokens.get('expires_in', 1800))
        integration.save(update_fields=['access_token', 'refresh_token', 'token_expires_at'])
        
        logger.info(f"Xero token refreshed successfully, expires at {integration.token_expires_at}")
        return True
        
    except requests.RequestException as e:
        logger.error(f"Xero token refresh request failed: {e}")
        return False


def fetch_xero_tenant_id(integration):
    """
    Fetch and store Xero tenant ID after OAuth.
    Must be called after token exchange.
    """
    if integration.tenant_id:
        return True
    
    logger.info(f"Fetching Xero tenant ID for org {integration.organization_id}")
    
    try:
        response = requests.get(
            "https://api.xero.com/connections",
            headers={
                'Authorization': f'Bearer {integration.access_token}',
                'Content-Type': 'application/json',
            },
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch Xero connections: {response.status_code}")
            return False
        
        connections = response.json()
        
        if not connections:
            logger.error("No Xero tenants found for this connection")
            return False
        
        # Use the first tenant (most users have one)
        # For multi-org Xero users, you might want to let them choose
        integration.tenant_id = connections[0]['tenantId']
        integration.save(update_fields=['tenant_id'])
        
        logger.info(f"Stored Xero tenant ID: {integration.tenant_id}")
        return True
        
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Xero tenant: {e}")
        return False


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
    
    import secrets
    state = secrets.token_urlsafe(32)
    
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
    
    try:
        integration = Integration.objects.get(oauth_state=state, provider='quickbooks')
    except Integration.DoesNotExist:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=invalid_state")
    
    # Exchange code for tokens
    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    
    try:
        response = requests.post(
            token_url,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': settings.QUICKBOOKS_REDIRECT_URI,
            },
            auth=(settings.QUICKBOOKS_CLIENT_ID, settings.QUICKBOOKS_CLIENT_SECRET),
            timeout=30
        )
    except requests.RequestException as e:
        logger.error(f"QB token exchange request failed: {e}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")
    
    if response.status_code != 200:
        logger.error(f"QB token exchange failed: {response.status_code} - {response.text}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")
    
    tokens = response.json()
    
    # Save tokens with expiration
    integration.access_token = tokens['access_token']
    integration.refresh_token = tokens['refresh_token']
    integration.realm_id = realm_id
    integration.is_connected = True
    integration.oauth_state = ''  # Clear state after use
    # QB access tokens expire in 1 hour
    integration.token_expires_at = timezone.now() + timedelta(seconds=tokens.get('expires_in', 3600))
    integration.save()
    
    logger.info(f"QuickBooks connected for org {integration.organization_id}, realm {realm_id}")
    
    return HttpResponse(f"""
            <!DOCTYPE html>
            <html>
            <head><title>Connected!</title></head>
            <body>
            <script>
                const message = {{
                    type: 'oauth_callback',
                    integration: 'quickbooks',
                    success: true
                }};
                
                if (window.opener && !window.opener.closed) {{
                    window.opener.postMessage(message, '{settings.FRONTEND_URL}');
                    window.close();
                }} else {{
                    // Fallback: redirect to frontend
                    window.location.href = '{settings.FRONTEND_URL}/settings?qb_connected=true';
                }}
            </script>
            <p>Connected successfully! Redirecting...</p>
            <p>If not redirected, <a href="{settings.FRONTEND_URL}/settings">click here</a>.</p>
            </body>
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
        return Response({
            'connected': integration.is_connected,
            'realm_id': integration.realm_id if integration.is_connected else None,
        })
    except Integration.DoesNotExist:
        return Response({'connected': False})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def quickbooks_disconnect(request):
    """Disconnect QuickBooks integration."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks')
        integration.is_connected = False
        integration.access_token = ''
        integration.refresh_token = ''
        integration.realm_id = ''
        integration.token_expires_at = None
        integration.save()
        return Response({'success': True})
    except Integration.DoesNotExist:
        return Response({'success': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_customers(request):
    """Fetch customers from QuickBooks (preview before import)."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks', is_connected=True)
    except Integration.DoesNotExist:
        return Response({'error': 'Not connected to QuickBooks'}, status=400)
    
    # Refresh token if needed
    if not refresh_quickbooks_token(integration):
        return Response({'error': 'Token refresh failed. Please reconnect QuickBooks.'}, status=401)
    
    # Fetch customers from QuickBooks API
    api_url = f"https://quickbooks.api.intuit.com/v3/company/{integration.realm_id}/query"
    
    headers = {
        'Authorization': f'Bearer {integration.access_token}',
        'Accept': 'application/json',
    }
    
    # Get active customers, ordered by name
    query = "SELECT * FROM Customer WHERE Active = true ORDERBY DisplayName MAXRESULTS 1000"
    
    try:
        response = requests.get(
            api_url,
            params={'query': query},
            headers=headers,
            timeout=30
        )
    except requests.RequestException as e:
        logger.error(f"QB API request failed: {e}")
        return Response({'error': 'Failed to connect to QuickBooks'}, status=500)
    
    if response.status_code == 401:
        # Token might have expired, try refresh
        if refresh_quickbooks_token(integration):
            headers['Authorization'] = f'Bearer {integration.access_token}'
            response = requests.get(api_url, params={'query': query}, headers=headers, timeout=30)
        else:
            return Response({'error': 'Authentication failed. Please reconnect QuickBooks.'}, status=401)
    
    if response.status_code != 200:
        logger.error(f"QB customers fetch failed: {response.status_code} - {response.text}")
        return Response({'error': 'Failed to fetch customers from QuickBooks'}, status=500)
    
    data = response.json()
    customers = data.get('QueryResponse', {}).get('Customer', [])
    
    # Get existing QB IDs to mark already-imported clients
    existing_qb_ids = set(
        Client.objects.filter(org=org, quickbooks_id__isnull=False)
        .values_list('quickbooks_id', flat=True)
    )
    
    clients = [{
        'id': c['Id'],
        'name': c.get('DisplayName') or c.get('CompanyName') or c.get('FullyQualifiedName', 'Unknown'),
        'company_name': c.get('CompanyName', ''),
        'email': c.get('PrimaryEmailAddr', {}).get('Address') if c.get('PrimaryEmailAddr') else '',
        'phone': c.get('PrimaryPhone', {}).get('FreeFormNumber') if c.get('PrimaryPhone') else '',
        'balance': float(c.get('Balance', 0)),
        'already_imported': c['Id'] in existing_qb_ids,
    } for c in customers]
    
    return Response({
        'customers': clients,
        'total': len(clients),
        'already_imported': sum(1 for c in clients if c['already_imported']),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def quickbooks_import(request):
    """Import selected customers from QuickBooks as Clients."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks', is_connected=True)
    except Integration.DoesNotExist:
        return Response({'error': 'Not connected to QuickBooks'}, status=400)
    
    # Get customer IDs to import
    customer_ids = request.data.get('customer_ids', [])
    if not customer_ids:
        return Response({'error': 'No customers selected'}, status=400)
    
    # Refresh token
    if not refresh_quickbooks_token(integration):
        return Response({'error': 'Token refresh failed. Please reconnect QuickBooks.'}, status=401)
    
    # Fetch specific customers from QuickBooks
    api_url = f"https://quickbooks.api.intuit.com/v3/company/{integration.realm_id}/query"
    
    headers = {
        'Authorization': f'Bearer {integration.access_token}',
        'Accept': 'application/json',
    }
    
    # Build query for specific IDs
    id_list = "', '".join(str(id) for id in customer_ids)
    query = f"SELECT * FROM Customer WHERE Id IN ('{id_list}')"
    
    try:
        response = requests.get(api_url, params={'query': query}, headers=headers, timeout=30)
    except requests.RequestException as e:
        logger.error(f"QB API request failed: {e}")
        return Response({'error': 'Failed to connect to QuickBooks'}, status=500)
    
    if response.status_code != 200:
        return Response({'error': 'Failed to fetch customers'}, status=500)
    
    data = response.json()
    customers = data.get('QueryResponse', {}).get('Customer', [])
    
    # Import customers as clients
    imported = []
    skipped = []
    errors = []
    
    for customer in customers:
        qb_id = customer['Id']
        name = customer.get('DisplayName') or customer.get('CompanyName') or customer.get('FullyQualifiedName', 'Unknown')
        
        # Check if already exists
        existing = Client.objects.filter(org=org, quickbooks_id=qb_id).first()
        if existing:
            skipped.append({'id': qb_id, 'name': name, 'reason': 'Already imported'})
            continue
        
        # Also check by name to avoid duplicates
        name_match = Client.objects.filter(org=org, name__iexact=name).first()
        if name_match:
            # Link existing client to QB instead of creating duplicate
            name_match.quickbooks_id = qb_id
            name_match.imported_from = 'quickbooks'
            name_match.save(update_fields=['quickbooks_id', 'imported_from'])
            imported.append({
                'id': name_match.id,
                'name': name,
                'quickbooks_id': qb_id,
                'linked_existing': True,
            })
            continue
        
        try:
            # Create new client
            client = Client.objects.create(
                org=org,
                name=name,
                quickbooks_id=qb_id,
                imported_from='quickbooks',
                is_active=True,
            )
            imported.append({
                'id': client.id,
                'name': client.name,
                'quickbooks_id': qb_id,
                'linked_existing': False,
            })
        except Exception as e:
            logger.error(f"Failed to create client from QB {qb_id}: {e}")
            errors.append({'id': qb_id, 'name': name, 'error': str(e)})
    
    return Response({
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'summary': {
            'imported_count': len(imported),
            'skipped_count': len(skipped),
            'error_count': len(errors),
        }
    })


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
        'scope': 'openid profile email accounting.contacts.read offline_access',  # Added offline_access for refresh tokens
        'state': state,
    }
    
    auth_url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params)}"
    
    return Response({'auth_url': auth_url})


@api_view(['GET'])
def xero_callback(request):
    """Handle Xero OAuth callback."""
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')
    
    if error:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error={error}")
    
    try:
        integration = Integration.objects.get(oauth_state=state, provider='xero')
    except Integration.DoesNotExist:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=invalid_state")
    
    # Exchange code for tokens
    token_url = "https://identity.xero.com/connect/token"
    
    try:
        response = requests.post(
            token_url,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': settings.XERO_REDIRECT_URI,
            },
            auth=(settings.XERO_CLIENT_ID, settings.XERO_CLIENT_SECRET),
            timeout=30
        )
    except requests.RequestException as e:
        logger.error(f"Xero token exchange request failed: {e}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")
    
    if response.status_code != 200:
        logger.error(f"Xero token exchange failed: {response.status_code} - {response.text}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")
    
    tokens = response.json()
    
    integration.access_token = tokens['access_token']
    integration.refresh_token = tokens.get('refresh_token', '')
    integration.oauth_state = ''  # Clear state after use
    # Xero tokens expire in 30 minutes
    integration.token_expires_at = timezone.now() + timedelta(seconds=tokens.get('expires_in', 1800))
    integration.save()
    
    # Fetch tenant ID (required for Xero API calls)
    if not fetch_xero_tenant_id(integration):
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=tenant_fetch_failed")
    
    integration.is_connected = True
    integration.save(update_fields=['is_connected'])
    
    logger.info(f"Xero connected for org {integration.organization_id}, tenant {integration.tenant_id}")
    
    return HttpResponse(f"""
            <!DOCTYPE html>
            <html>
            <head><title>Connected!</title></head>
            <body>
            <script>
                const message = {{
                    type: 'oauth_callback',
                    integration: 'xero',
                    success: true
                }};
                
                if (window.opener && !window.opener.closed) {{
                    window.opener.postMessage(message, '{settings.FRONTEND_URL}');
                    window.close();
                }} else {{
                    // Fallback: redirect to frontend
                    window.location.href = '{settings.FRONTEND_URL}/settings?xero_connected=true';
                }}
            </script>
            <p>Connected successfully! Redirecting...</p>
            <p>If not redirected, <a href="{settings.FRONTEND_URL}/settings">click here</a>.</p>
            </body>
            </html>
        """)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xero_status(request):
    """Check Xero connection status."""
    org = get_user_org(request.user)
    if not org:
        return Response({'connected': False})
    
    try:
        integration = Integration.objects.get(organization=org, provider='xero')
        return Response({
            'connected': integration.is_connected,
            'tenant_id': integration.tenant_id if integration.is_connected else None,
        })
    except Integration.DoesNotExist:
        return Response({'connected': False})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def xero_disconnect(request):
    """Disconnect Xero integration."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='xero')
        integration.is_connected = False
        integration.access_token = ''
        integration.refresh_token = ''
        integration.tenant_id = ''
        integration.token_expires_at = None
        integration.save()
        return Response({'success': True})
    except Integration.DoesNotExist:
        return Response({'success': True})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xero_contacts(request):
    """Fetch contacts from Xero (preview before import)."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='xero', is_connected=True)
    except Integration.DoesNotExist:
        return Response({'error': 'Not connected to Xero'}, status=400)
    
    if not integration.tenant_id:
        return Response({'error': 'Xero tenant ID not found. Please reconnect.'}, status=400)
    
    # Refresh token if needed
    if not refresh_xero_token(integration):
        return Response({'error': 'Token refresh failed. Please reconnect Xero.'}, status=401)
    
    # Fetch contacts from Xero API (only customers)
    api_url = "https://api.xero.com/api.xro/2.0/Contacts"
    
    headers = {
        'Authorization': f'Bearer {integration.access_token}',
        'Accept': 'application/json',
        'Xero-tenant-id': integration.tenant_id,
    }
    
    params = {
        'where': 'IsCustomer==true',
        'order': 'Name ASC',
    }
    
    try:
        response = requests.get(api_url, headers=headers, params=params, timeout=30)
    except requests.RequestException as e:
        logger.error(f"Xero API request failed: {e}")
        return Response({'error': 'Failed to connect to Xero'}, status=500)
    
    if response.status_code == 401:
        if refresh_xero_token(integration):
            headers['Authorization'] = f'Bearer {integration.access_token}'
            response = requests.get(api_url, headers=headers, params=params, timeout=30)
        else:
            return Response({'error': 'Authentication failed. Please reconnect Xero.'}, status=401)
    
    if response.status_code != 200:
        logger.error(f"Xero contacts fetch failed: {response.status_code} - {response.text}")
        return Response({'error': 'Failed to fetch contacts from Xero'}, status=500)
    
    data = response.json()
    contacts = data.get('Contacts', [])
    
    # Get existing Xero IDs
    existing_xero_ids = set(
        Client.objects.filter(org=org, xero_id__isnull=False)
        .values_list('xero_id', flat=True)
    )
    
    clients = [{
        'id': c['ContactID'],
        'name': c.get('Name', 'Unknown'),
        'email': c.get('EmailAddress', ''),
        'phone': c.get('Phones', [{}])[0].get('PhoneNumber', '') if c.get('Phones') else '',
        'is_customer': c.get('IsCustomer', False),
        'is_supplier': c.get('IsSupplier', False),
        'already_imported': c['ContactID'] in existing_xero_ids,
    } for c in contacts if c.get('IsCustomer', False)]
    
    return Response({
        'contacts': clients,
        'total': len(clients),
        'already_imported': sum(1 for c in clients if c['already_imported']),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def xero_import(request):
    """Import selected contacts from Xero as Clients."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='xero', is_connected=True)
    except Integration.DoesNotExist:
        return Response({'error': 'Not connected to Xero'}, status=400)
    
    contact_ids = request.data.get('contact_ids', [])
    if not contact_ids:
        return Response({'error': 'No contacts selected'}, status=400)
    
    if not refresh_xero_token(integration):
        return Response({'error': 'Token refresh failed. Please reconnect Xero.'}, status=401)
    
    # Fetch specific contacts
    headers = {
        'Authorization': f'Bearer {integration.access_token}',
        'Accept': 'application/json',
        'Xero-tenant-id': integration.tenant_id,
    }
    
    imported = []
    skipped = []
    errors = []
    
    # Xero doesn't support IN queries easily, so we fetch each contact
    # For large imports, consider fetching all and filtering
    for contact_id in contact_ids:
        api_url = f"https://api.xero.com/api.xro/2.0/Contacts/{contact_id}"
        
        try:
            response = requests.get(api_url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                errors.append({'id': contact_id, 'error': 'Failed to fetch from Xero'})
                continue
            
            data = response.json()
            contacts = data.get('Contacts', [])
            
            if not contacts:
                errors.append({'id': contact_id, 'error': 'Contact not found'})
                continue
            
            contact = contacts[0]
            xero_id = contact['ContactID']
            name = contact.get('Name', 'Unknown')
            
            # Check if already exists
            existing = Client.objects.filter(org=org, xero_id=xero_id).first()
            if existing:
                skipped.append({'id': xero_id, 'name': name, 'reason': 'Already imported'})
                continue
            
            # Check by name
            name_match = Client.objects.filter(org=org, name__iexact=name).first()
            if name_match:
                name_match.xero_id = xero_id
                name_match.imported_from = 'xero'
                name_match.save(update_fields=['xero_id', 'imported_from'])
                imported.append({
                    'id': name_match.id,
                    'name': name,
                    'xero_id': xero_id,
                    'linked_existing': True,
                })
                continue
            
            # Create new client
            client = Client.objects.create(
                org=org,
                name=name,
                xero_id=xero_id,
                imported_from='xero',
                is_active=True,
            )
            imported.append({
                'id': client.id,
                'name': client.name,
                'xero_id': xero_id,
                'linked_existing': False,
            })
            
        except Exception as e:
            logger.error(f"Failed to import Xero contact {contact_id}: {e}")
            errors.append({'id': contact_id, 'error': str(e)})
    
    return Response({
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'summary': {
            'imported_count': len(imported),
            'skipped_count': len(skipped),
            'error_count': len(errors),
        }
    })


# ============================================================================
# Combined Status Endpoint
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integrations_status(request):
    """Get status of all integrations for the org."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    integrations = {}
    
    # QuickBooks
    try:
        qb = Integration.objects.get(organization=org, provider='quickbooks')
        integrations['quickbooks'] = {
            'connected': qb.is_connected,
            'realm_id': qb.realm_id if qb.is_connected else None,
            'last_synced': qb.updated_at.isoformat() if qb.is_connected else None,
        }
    except Integration.DoesNotExist:
        integrations['quickbooks'] = {'connected': False}
    
    # Xero
    try:
        xero = Integration.objects.get(organization=org, provider='xero')
        integrations['xero'] = {
            'connected': xero.is_connected,
            'tenant_id': xero.tenant_id if xero.is_connected else None,
            'last_synced': xero.updated_at.isoformat() if xero.is_connected else None,
        }
    except Integration.DoesNotExist:
        integrations['xero'] = {'connected': False}
    
    # Count imported clients
    client_stats = {
        'from_quickbooks': Client.objects.filter(org=org, imported_from='quickbooks').count(),
        'from_xero': Client.objects.filter(org=org, imported_from='xero').count(),
        'manual': Client.objects.filter(org=org, imported_from='').count(),
    }
    
    return Response({
        'integrations': integrations,
        'client_stats': client_stats,
    })