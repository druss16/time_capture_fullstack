# tracker/views_integrations.py
#
# Integration endpoints for QuickBooks Online & Xero
# Supports: OAuth connect/disconnect, client import,
#           time entry PUSH (to billing), invoice PULL (for profitability)
#
# v2 CHANGELOG:
# - Added retry logic on token refresh (retry once before disconnecting)
# - Fixed Xero N+1 import (batch fetch + client-side filter)
# - Added generic API call helpers with auto-refresh
# - Added PUSH endpoints: push approved time entries to QBO/Xero
# - Added PULL endpoints: pull invoices from QBO/Xero for profitability
# - Consistent error response format with error codes
# - Better logging throughout

import requests
import logging
from collections import defaultdict
from datetime import timedelta, date, datetime
from decimal import Decimal
from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from urllib.parse import urlencode
from django.http import HttpResponse
from .models import (
    Integration,
    OrganizationMembership,
    Client,
    Block,
    BillingRate,
    InvoiceConflict,
)

logger = logging.getLogger(__name__)

QB_API_BASE = settings.QUICKBOOKS_API_BASE


# ============================================================================
# Shared Helpers
# ============================================================================

def get_user_org(user):
    """Get the user's organization."""
    membership = OrganizationMembership.objects.filter(
        user=user
    ).select_related('organization').first()
    return membership.organization if membership else None


def error_response(message, status=400, code=None):
    """Consistent error response format."""
    payload = {'error': message}
    if code:
        payload['error_code'] = code
    return Response(payload, status=status)


def get_integration(org, provider, connected_only=True):
    """
    Get integration for org+provider.
    Returns (integration, error_response) tuple.
    """
    if not org:
        return None, error_response('No organization found', 404, 'no_org')

    try:
        filters = {'organization': org, 'provider': provider}
        if connected_only:
            filters['is_connected'] = True
        integration = Integration.objects.get(**filters)
        return integration, None
    except Integration.DoesNotExist:
        if connected_only:
            return None, error_response(
                f'Not connected to {provider.replace("_", " ").title()}. '
                f'Please connect first in Settings.',
                400, 'not_connected'
            )
        return None, None

def run_post_import_alias_derivation(org, min_confidence: float = 0.8):
    """
    Best-effort: derive client aliases for an org after a client import, then
    prune known-junk tokens. Never raises — logs and swallows all errors so a
    derivation problem cannot break the import that just succeeded.
    """
    try:
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("derive_aliases", org_id=org.id,
                     min_confidence=min_confidence, stdout=out)
        call_command("prune_junk_aliases", org_id=org.id, stdout=out)
        logger.info("Post-import alias derivation complete for org %s:\n%s",
                    org.id, out.getvalue())
        return {"ok": True, "log": out.getvalue()}
    except Exception as e:
        logger.warning("Post-import alias derivation failed for org %s: %s",
                       getattr(org, "id", "?"), e, exc_info=True)
        return None


def _oauth_success_response(provider):
    """Standard OAuth success HTML with postMessage to parent window."""
    frontend_url = settings.FRONTEND_URL
    return HttpResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>Connected!</title></head>
        <body>
        <script>
            const message = {{
                type: 'oauth_callback',
                integration: '{provider}',
                success: true
            }};
            if (window.opener && !window.opener.closed) {{
                window.opener.postMessage(message, '{frontend_url}');
                window.close();
            }} else {{
                window.location.href = '{frontend_url}/settings?{provider}_connected=true';
            }}
        </script>
        <p>Connected successfully! Redirecting...</p>
        <p>If not redirected, <a href="{frontend_url}/settings">click here</a>.</p>
        </body>
        </html>
    """)


# ============================================================================
# Token Refresh (generic with single retry)
# ============================================================================

def _do_token_refresh(integration, token_url, auth_tuple, default_expiry):
    """
    Generic token refresh with single retry before disconnecting.
    Returns True if token is valid/refreshed, False if failed.
    """
    # Check if token still valid (5 min buffer)
    if integration.token_expires_at:
        if integration.token_expires_at > timezone.now() + timedelta(minutes=5):
            return True

    if not integration.refresh_token:
        logger.error(
            f"No refresh token for {integration.provider} "
            f"integration {integration.id}"
        )
        return False

    logger.info(
        f"Refreshing {integration.provider} token "
        f"for org {integration.organization_id}"
    )

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                token_url,
                data={
                    'grant_type': 'refresh_token',
                    'refresh_token': integration.refresh_token,
                },
                auth=auth_tuple,
                timeout=30,
            )

            if response.status_code == 200:
                tokens = response.json()
                integration.access_token = tokens['access_token']
                integration.refresh_token = tokens.get(
                    'refresh_token', integration.refresh_token
                )
                integration.token_expires_at = timezone.now() + timedelta(
                    seconds=tokens.get('expires_in', default_expiry)
                )
                integration.save(update_fields=[
                    'access_token', 'refresh_token', 'token_expires_at'
                ])
                logger.info(
                    f"{integration.provider} token refreshed OK "
                    f"(attempt {attempt})"
                )
                return True

            logger.warning(
                f"{integration.provider} refresh attempt {attempt}: "
                f"{response.status_code}"
            )
            # Don't retry on non-rate-limit 4xx
            if 400 <= response.status_code < 500 and response.status_code != 429:
                break

        except requests.RequestException as e:
            logger.warning(
                f"{integration.provider} refresh attempt {attempt}: {e}"
            )

    # All attempts failed
    logger.error(f"{integration.provider} token refresh failed — disconnecting")
    integration.is_connected = False
    integration.save(update_fields=['is_connected'])
    return False


def refresh_quickbooks_token(integration):
    return _do_token_refresh(
        integration,
        "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        (settings.QUICKBOOKS_CLIENT_ID, settings.QUICKBOOKS_CLIENT_SECRET),
        3600,
    )


def refresh_xero_token(integration):
    return _do_token_refresh(
        integration,
        "https://identity.xero.com/connect/token",
        (settings.XERO_CLIENT_ID, settings.XERO_CLIENT_SECRET),
        1800,
    )


# ============================================================================
# Authenticated API Call Helpers
# ============================================================================

def _api_call(integration, method, url, headers, refresh_fn, **kwargs):
    """
    Generic authenticated API call with auto-refresh on 401.
    Returns (response_json, error_response).
    """
    if not refresh_fn(integration):
        return None, error_response(
            f'{integration.provider.title()} auth failed. Please reconnect.',
            401, 'auth_failed'
        )

    headers['Authorization'] = f'Bearer {integration.access_token}'

    try:
        resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    except requests.RequestException as e:
        logger.error(f"{integration.provider} API error: {e}")
        return None, error_response(
            f'Failed to connect to {integration.provider.title()}', 500
        )

    # Retry once on 401
    if resp.status_code == 401:
        if refresh_fn(integration):
            headers['Authorization'] = f'Bearer {integration.access_token}'
            try:
                resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
            except requests.RequestException:
                return None, error_response('Connection failed after retry', 500)

    if resp.status_code not in (200, 201):
        logger.error(f"{integration.provider} API {resp.status_code}: {resp.text[:300]}")
        return None, error_response(
            f'{integration.provider.title()} API error ({resp.status_code})', 500
        )

    return resp.json(), None


def qb_api_call(integration, method, endpoint, **kwargs):
    """QuickBooks authenticated API call."""
    url = f"{QB_API_BASE}/v3/company/{integration.realm_id}{endpoint}"
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    return _api_call(integration, method, url, headers, refresh_quickbooks_token, **kwargs)


def xero_api_call(integration, method, endpoint, **kwargs):
    """Xero authenticated API call."""
    url = f"https://api.xero.com/api.xro/2.0{endpoint}"
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Xero-tenant-id': integration.tenant_id,
    }
    return _api_call(integration, method, url, headers, refresh_xero_token, **kwargs)


def fetch_xero_tenant_id(integration):
    """Fetch and store Xero tenant ID after OAuth."""
    if integration.tenant_id:
        return True
    try:
        resp = requests.get(
            "https://api.xero.com/connections",
            headers={
                'Authorization': f'Bearer {integration.access_token}',
                'Content-Type': 'application/json',
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Xero connections fetch failed: {resp.status_code}")
            return False
        connections = resp.json()
        if not connections:
            logger.error("No Xero tenants found")
            return False
        integration.tenant_id = connections[0]['tenantId']
        integration.save(update_fields=['tenant_id'])
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Xero tenant: {e}")
        return False


# ============================================================================
# QuickBooks OAuth
# ============================================================================

@api_view(['GET'])
@permission_classes([AllowAny])
def quickbooks_connect(request):
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization', 404)

    membership = request.user.memberships.filter(organization=org).first()
    if not membership or membership.role not in ('owner', 'admin'):
        return error_response('Only owners and admins can manage integrations', 403)

    import secrets
    state = secrets.token_urlsafe(32)
    Integration.objects.update_or_create(
        organization=org, provider='quickbooks',
        defaults={'oauth_state': state},
    )
    params = {
        'client_id': settings.QUICKBOOKS_CLIENT_ID,
        'response_type': 'code',
        'scope': 'com.intuit.quickbooks.accounting',
        'redirect_uri': settings.QUICKBOOKS_REDIRECT_URI,
        'state': state,
        'prompt': 'select_account',  # ← add this

    }
    auth_url = f"https://appcenter.intuit.com/connect/oauth2?{urlencode(params)}"
    return Response({'auth_url': auth_url})


@api_view(['GET'])
@permission_classes([AllowAny])  # ← add this
def quickbooks_callback(request):
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

    try:
        resp = requests.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': settings.QUICKBOOKS_REDIRECT_URI,
            },
            auth=(settings.QUICKBOOKS_CLIENT_ID, settings.QUICKBOOKS_CLIENT_SECRET),
            timeout=30,
        )
    except requests.RequestException as e:
        logger.error(f"QB token exchange failed: {e}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")

    if resp.status_code != 200:
        logger.error(f"QB token exchange {resp.status_code}: {resp.text}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")

    tokens = resp.json()
    integration.access_token = tokens['access_token']
    integration.refresh_token = tokens['refresh_token']
    integration.realm_id = realm_id
    integration.is_connected = True
    integration.oauth_state = ''
    integration.token_expires_at = timezone.now() + timedelta(seconds=tokens.get('expires_in', 3600))
    integration.save()
    logger.info(f"QuickBooks connected for org {integration.organization_id}")

    # Kick off a one-shot historical backfill so realization/leakage/margin have
    # data immediately instead of waiting for the 4-hourly rolling reconcile.
    try:
        from tracker.tasks import backfill_qb_invoices
        backfill_qb_invoices.delay(integration.organization_id, 365)
    except Exception as e:
        logger.warning(f"QB backfill enqueue failed for org {integration.organization_id}: {e}")

    return _oauth_success_response('quickbooks')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_status(request):
    org = get_user_org(request.user)
    integration, _ = get_integration(org, 'quickbooks', connected_only=False)
    if not integration:
        return Response({'connected': False})
    return Response({
        'connected': integration.is_connected,
        'realm_id': integration.realm_id if integration.is_connected else None,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def quickbooks_disconnect(request):
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization', 404)
    membership = request.user.memberships.filter(organization=org).first()
    if not membership or membership.role not in ('owner', 'admin'):
        return error_response('Only owners and admins can manage integrations', 403)
    try:
        i = Integration.objects.get(organization=org, provider='quickbooks')
        i.is_connected = False
        i.access_token = ''
        i.refresh_token = ''
        i.realm_id = ''
        i.token_expires_at = None
        i.save()
    except Integration.DoesNotExist:
        pass
    return Response({'success': True})


# ============================================================================
# QuickBooks: Client Import (PULL clients)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_customers(request):
    """Fetch customers from QuickBooks (preview before import)."""
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'quickbooks')
    if err:
        return err

    query = "SELECT * FROM Customer WHERE Active = true ORDERBY DisplayName MAXRESULTS 1000"
    data, err = qb_api_call(integration, 'GET', '/query', params={'query': query})
    if err:
        return err

    customers = data.get('QueryResponse', {}).get('Customer', [])
    existing_qb_ids = set(
        Client.objects.filter(
            org=org, 
            quickbooks_id__isnull=False,
            quickbooks_realm_id=integration.realm_id
        ).values_list('quickbooks_id', flat=True)
    )

    clients = [{
        'id': c['Id'],
        'name': c.get('DisplayName') or c.get('CompanyName') or c.get('FullyQualifiedName', 'Unknown'),
        'company_name': c.get('CompanyName', ''),
        'email': c.get('PrimaryEmailAddr', {}).get('Address', '') if c.get('PrimaryEmailAddr') else '',
        'phone': c.get('PrimaryPhone', {}).get('FreeFormNumber', '') if c.get('PrimaryPhone') else '',
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
    integration, err = get_integration(org, 'quickbooks')
    if err:
        return err

    customer_ids = request.data.get('customer_ids', [])
    if not customer_ids:
        return error_response('No customers selected')

    id_list = "', '".join(str(cid) for cid in customer_ids)
    query = f"SELECT * FROM Customer WHERE Id IN ('{id_list}')"
    data, err = qb_api_call(integration, 'GET', '/query', params={'query': query})
    if err:
        return err

    customers = data.get('QueryResponse', {}).get('Customer', [])
    imported, skipped, errors = [], [], []

    for customer in customers:
        qb_id = customer['Id']
        name = customer.get('DisplayName') or customer.get('CompanyName') or 'Unknown'

        if Client.objects.filter(org=org, quickbooks_id=qb_id).exists():
            skipped.append({'id': qb_id, 'name': name, 'reason': 'Already imported'})
            continue

        name_match = Client.objects.filter(org=org, name__iexact=name).first()
        if name_match:
            name_match.quickbooks_id = qb_id
            name_match.quickbooks_realm_id = integration.realm_id
            name_match.imported_from = 'quickbooks'
            update_fields = ['quickbooks_id', 'quickbooks_realm_id', 'imported_from']
            email = customer.get('PrimaryEmailAddr', {}).get('Address', '') if customer.get('PrimaryEmailAddr') else ''
            if email and not name_match.email:
                name_match.email = email
                update_fields.append('email')
            name_match.save(update_fields=update_fields)
            imported.append({'id': name_match.id, 'name': name, 'quickbooks_id': qb_id, 'linked_existing': True})
            continue

        try:
            client = Client.objects.create(
                org=org, name=name, quickbooks_id=qb_id,
                quickbooks_realm_id=integration.realm_id,
                imported_from='quickbooks', is_active=True,
                email=(customer.get('PrimaryEmailAddr', {}).get('Address', '') if customer.get('PrimaryEmailAddr') else ''),
            )
            imported.append({'id': client.id, 'name': name, 'quickbooks_id': qb_id, 'linked_existing': False})
        except Exception as e:
            logger.error(f"Failed to create client from QB {qb_id}: {e}")
            errors.append({'id': qb_id, 'name': name, 'error': str(e)})

    # Auto-derive aliases for newly imported clients (best-effort, never breaks import)
    if imported:
        run_post_import_alias_derivation(org)

    return Response({
        'imported': imported, 'skipped': skipped, 'errors': errors,
        'summary': {
            'imported_count': len(imported),
            'skipped_count': len(skipped),
            'error_count': len(errors),
        },
    })


# ============================================================================
# QuickBooks: PUSH Time Entries
# ============================================================================

# ============================================================================
# REPLACE quickbooks_push_time in views_integrations.py
# AND ADD quickbooks_push_status below it
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def quickbooks_push_time(request):
    """
    Push categorized time entries to QuickBooks as TimeActivity records.
    - dry_run=True: returns preview synchronously
    - dry_run=False: kicks off Celery background task, returns task_id
    """
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'quickbooks')
    if err:
        return err

    start_date = request.data.get('start_date')
    end_date = request.data.get('end_date')
    client_ids = request.data.get('client_ids', [])
    dry_run = request.data.get('dry_run', False)

    if not start_date or not end_date:
        return error_response('start_date and end_date are required')

    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return error_response('Invalid date format. Use YYYY-MM-DD')

    if (end_dt - start_dt).days > 366:
        return error_response('Date range cannot exceed 1 year')

    # Build UTC range for the date span
    tz = timezone.get_current_timezone()
    start_aware = timezone.make_aware(datetime.combine(start_dt, datetime.min.time()), tz)
    end_aware = timezone.make_aware(datetime.combine(end_dt + timedelta(days=1), datetime.min.time()), tz)

    # Get categorized blocks that have QB-linked clients and haven't been pushed yet
    blocks_qs = Block.objects.filter(
        org=org,
        is_categorized=True,
        start__gte=start_aware,
        start__lt=end_aware,
        client__isnull=False,
        client__quickbooks_id__isnull=False,
    ).exclude(
        client__quickbooks_id=''
    ).select_related('client', 'user')

    # Exclude already-pushed blocks
    blocks_qs = blocks_qs.filter(
        Q(qb_time_activity_id__isnull=True) | Q(qb_time_activity_id='')
    )

    if client_ids:
        blocks_qs = blocks_qs.filter(client_id__in=client_ids)

    blocks = list(blocks_qs.order_by('start'))

    if not blocks:
        return Response({
            'message': 'No unpushed categorized time entries found for this period',
            'entries': [],
            'summary': {'total_entries': 0, 'total_hours': 0},
        })

    # Pre-cache user → QBO employee mappings for preview
    user_ids = set(b.user_id for b in blocks)
    memberships = {
        m.user_id: m.quickbooks_employee_id
        for m in OrganizationMembership.objects.filter(
            organization=org, user_id__in=user_ids
        )
        if m.quickbooks_employee_id
    }

    # Build preview entries (used for both dry_run and push response)
    entries = []
    for block in blocks:
        total_minutes = block.minutes or 0
        if total_minutes <= 0 and block.end and block.start:
            total_minutes = int((block.end - block.start).total_seconds() / 60)
        if total_minutes <= 0:
            continue

        cats = block.category_hours or {}
        cat_names = ', '.join(cats.keys()) if cats else 'General'

        entries.append({
            'block_id': block.id,
            'client': block.client.name,
            'client_id': block.client_id,
            'date': timezone.localtime(block.start).strftime('%Y-%m-%d'),
            'hours': round(total_minutes / 60, 2),
            'category': cat_names,
            'notes': block.notes or '',
        })

    # --- DRY RUN ---
    if dry_run:
        return Response({
            'dry_run': True,
            'entries': entries,
            'summary': {
                'total_entries': len(entries),
                'total_hours': round(sum(e['hours'] for e in entries), 2),
                'clients': list(set(e['client'] for e in entries)),
            },
        })

    # --- PUSH (background task) ---
    from tracker.tasks import push_time_to_quickbooks

    task = push_time_to_quickbooks.delay(
        org.id,
        request.user.id,
        start_date,
        end_date,
        client_ids or None,
    )

    return Response({
        'status': 'started',
        'task_id': task.id,
        'total_entries': len(entries),
        'total_hours': round(sum(e['hours'] for e in entries), 2),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_push_status(request, task_id):
    from celery.result import AsyncResult

    result = AsyncResult(task_id)

    if result.state == 'PROGRESS':
        info = result.info if isinstance(result.info, dict) else {}
        return Response({
            'status': 'processing',
            **info,
        })
    elif result.state == 'SUCCESS':
        return Response(result.result)
    elif result.state == 'FAILURE':
        return Response({
            'status': 'error',
            'error': str(result.info),
        }, status=500)
    else:
        return Response({
            'status': 'pending',
            'current': 0,
            'total': 0,
        })

# ============================================================================
# QuickBooks: PULL Invoices (for profitability)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def quickbooks_pull_invoices(request):
    """
    Pull invoice data from QuickBooks for profitability comparison.

    Query params: start_date, end_date (YYYY-MM-DD, required), client_id (optional)

    Returns billed revenue by client for:
    - Tracked hours × rate = expected revenue
    - QBO invoiced = actual billed
    - Delta = realization rate
    """
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'quickbooks')
    if err:
        return err

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date or not end_date:
        return error_response('start_date and end_date are required')

    query = (
        f"SELECT * FROM Invoice WHERE TxnDate >= '{start_date}' "
        f"AND TxnDate <= '{end_date}'"
    )

    client_id = request.GET.get('client_id')
    if client_id:
        try:
            client = Client.objects.get(id=client_id, org=org)
            if client.quickbooks_id:
                query += f" AND CustomerRef = '{client.quickbooks_id}'"
        except Client.DoesNotExist:
            pass

    query += " ORDERBY TxnDate MAXRESULTS 1000"
    data, err = qb_api_call(integration, 'GET', '/query', params={'query': query})
    if err:
        return err

    invoices = data.get('QueryResponse', {}).get('Invoice', [])

    # Aggregate by customer
    by_customer = {}
    for inv in invoices:
        cust = inv.get('CustomerRef', {})
        cid = cust.get('value', 'unknown')
        if cid not in by_customer:
            by_customer[cid] = {
                'qb_customer_id': cid,
                'customer_name': cust.get('name', 'Unknown'),
                'invoice_count': 0,
                'total_billed': 0.0,
                'total_paid': 0.0,
                'total_balance': 0.0,
                'invoices': [],
            }
        total = float(inv.get('TotalAmt', 0))
        balance = float(inv.get('Balance', 0))
        by_customer[cid]['invoice_count'] += 1
        by_customer[cid]['total_billed'] += total
        by_customer[cid]['total_paid'] += total - balance
        by_customer[cid]['total_balance'] += balance
        by_customer[cid]['invoices'].append({
            'id': inv.get('Id'),
            'doc_number': inv.get('DocNumber', ''),
            'date': inv.get('TxnDate', ''),
            'due_date': inv.get('DueDate', ''),
            'total': total,
            'balance': balance,
            'status': 'Paid' if balance == 0 else 'Open',
        })

    # Match QBO customers → TimeTracker clients
    qb_map = {c.quickbooks_id: c for c in Client.objects.filter(org=org, quickbooks_id__isnull=False)}
    results = []
    for cid, d in by_customer.items():
        tt = qb_map.get(cid)
        results.append({
            **d,
            'timetracker_client_id': tt.id if tt else None,
            'timetracker_client_name': tt.name if tt else None,
            'matched': tt is not None,
            'total_billed': round(d['total_billed'], 2),
            'total_paid': round(d['total_paid'], 2),
            'total_balance': round(d['total_balance'], 2),
        })

    # ── Save pulled invoices to local Invoice model ──
    from .models import Invoice as InvoiceModel

    saved_count = 0
    for cust_data in results:
        # Only save for matched clients
        if not cust_data.get('matched') or not cust_data.get('timetracker_client_id'):
            continue

        for inv in cust_data.get('invoices', []):
            qb_invoice_id = str(inv.get('id', ''))
            doc_number = inv.get('doc_number', '') or f"QBO-{qb_invoice_id}"
            inv_date = inv.get('date', end_date)
            total = Decimal(str(inv.get('total', 0)))

            try:
                # REMOVE the estimated_hours calculation entirely
                # REPLACE with:
                InvoiceModel.objects.update_or_create(
                    org=org,
                    invoice_number=doc_number,
                    defaults={
                        'client_id': cust_data['timetracker_client_id'],
                        'client_name': cust_data.get('customer_name', ''),
                        'invoice_date': inv_date,
                        'amount': total,
                        'hours_billed': None,   # Real hours come from time blocks, not reverse math
                        'source': 'quickbooks',
                        'external_id': qb_invoice_id,
                        'status': 'paid' if inv.get('balance', 1) == 0 else 'sent',
                        'created_by': request.user,
                    }
                )
                saved_count += 1
            except Exception as e:
                logger.warning(f"Failed to save QBO invoice {doc_number}: {e}")

    logger.info(f"Saved {saved_count} QBO invoices for org {org.id}")

    results.sort(key=lambda x: x['total_billed'], reverse=True)

    integration.last_synced_at = timezone.now()
    integration.save(update_fields=['last_synced_at'])

    return Response({
        'period': {'start': start_date, 'end': end_date},
        'customers': results,
        'totals': {
            'total_billed': round(sum(r['total_billed'] for r in results), 2),
            'total_paid': round(sum(r['total_paid'] for r in results), 2),
            'total_balance': round(sum(r['total_balance'] for r in results), 2),
            'invoice_count': sum(r['invoice_count'] for r in results),
        },
    })



# ============================================================================
# Xero OAuth
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xero_connect(request):
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization', 404)

    import secrets
    state = secrets.token_urlsafe(32)
    Integration.objects.update_or_create(
        organization=org, provider='xero',
        defaults={'oauth_state': state},
    )
    params = {
        'response_type': 'code',
        'client_id': settings.XERO_CLIENT_ID,
        'redirect_uri': settings.XERO_REDIRECT_URI,
        'scope': (
            'openid profile email '
            'accounting.contacts.read accounting.transactions.read '
            'accounting.settings.read offline_access'
        ),
        'state': state,
    }
    auth_url = f"https://login.xero.com/identity/connect/authorize?{urlencode(params)}"
    return Response({'auth_url': auth_url})


@api_view(['GET'])
def xero_callback(request):
    code = request.GET.get('code')
    state = request.GET.get('state')
    error = request.GET.get('error')

    if error:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error={error}")

    try:
        integration = Integration.objects.get(oauth_state=state, provider='xero')
    except Integration.DoesNotExist:
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=invalid_state")

    try:
        resp = requests.post(
            "https://identity.xero.com/connect/token",
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': settings.XERO_REDIRECT_URI,
            },
            auth=(settings.XERO_CLIENT_ID, settings.XERO_CLIENT_SECRET),
            timeout=30,
        )
    except requests.RequestException as e:
        logger.error(f"Xero token exchange failed: {e}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")

    if resp.status_code != 200:
        logger.error(f"Xero token exchange {resp.status_code}: {resp.text}")
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=token_exchange_failed")

    tokens = resp.json()
    integration.access_token = tokens['access_token']
    integration.refresh_token = tokens.get('refresh_token', '')
    integration.oauth_state = ''
    integration.token_expires_at = timezone.now() + timedelta(seconds=tokens.get('expires_in', 1800))
    integration.save()

    if not fetch_xero_tenant_id(integration):
        return redirect(f"{settings.FRONTEND_URL}/settings?integration_error=tenant_fetch_failed")

    integration.is_connected = True
    integration.save(update_fields=['is_connected'])
    logger.info(f"Xero connected for org {integration.organization_id}")
    return _oauth_success_response('xero')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xero_status(request):
    org = get_user_org(request.user)
    integration, _ = get_integration(org, 'xero', connected_only=False)
    if not integration:
        return Response({'connected': False})
    return Response({
        'connected': integration.is_connected,
        'tenant_id': integration.tenant_id if integration.is_connected else None,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def xero_disconnect(request):
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization', 404)
    try:
        i = Integration.objects.get(organization=org, provider='xero')
        i.is_connected = False
        i.access_token = ''
        i.refresh_token = ''
        i.tenant_id = ''
        i.token_expires_at = None
        i.save()
    except Integration.DoesNotExist:
        pass
    return Response({'success': True})


# ============================================================================
# Xero: Client Import — FIXED (batch fetch, no N+1)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xero_contacts(request):
    """Fetch contacts from Xero — single API call, no N+1."""
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'xero')
    if err:
        return err
    if not integration.tenant_id:
        return error_response('Xero tenant ID missing. Please reconnect.', 400)

    data, err = xero_api_call(
        integration, 'GET', '/Contacts',
        params={'where': 'IsCustomer==true', 'order': 'Name ASC'},
    )
    if err:
        return err

    contacts = data.get('Contacts', [])
    existing_xero_ids = set(
        Client.objects.filter(
            org=org,
            xero_id__isnull=False,
            xero_tenant_id=integration.tenant_id
        ).values_list('xero_id', flat=True)
    )

    clients = [{
        'id': c['ContactID'],
        'name': c.get('Name', 'Unknown'),
        'email': c.get('EmailAddress', ''),
        'phone': c.get('Phones', [{}])[0].get('PhoneNumber', '') if c.get('Phones') else '',
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
    """Import contacts from Xero — batch fetch, filter client-side."""
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'xero')
    if err:
        return err

    contact_ids = request.data.get('contact_ids', [])
    if not contact_ids:
        return error_response('No contacts selected')

    # Single fetch for all contacts
    data, err = xero_api_call(
        integration, 'GET', '/Contacts',
        params={'where': 'IsCustomer==true'},
    )
    if err:
        return err

    lookup = {c['ContactID']: c for c in data.get('Contacts', [])}
    imported, skipped, errors = [], [], []

    for cid in contact_ids:
        contact = lookup.get(cid)
        if not contact:
            errors.append({'id': cid, 'error': 'Not found in Xero'})
            continue

        xero_id = contact['ContactID']
        name = contact.get('Name', 'Unknown')

        if Client.objects.filter(org=org, xero_id=xero_id).exists():
            skipped.append({'id': xero_id, 'name': name, 'reason': 'Already imported'})
            continue

        name_match = Client.objects.filter(org=org, name__iexact=name).first()
        if name_match:
            name_match.xero_id = xero_id
            name_match.xero_tenant_id = integration.tenant_id
            name_match.imported_from = 'xero'
            update_fields = ['xero_id', 'xero_tenant_id', 'imported_from']
            email = contact.get('EmailAddress', '') or ''
            if email and not name_match.email:
                name_match.email = email
                update_fields.append('email')
            name_match.save(update_fields=update_fields)
            imported.append({'id': name_match.id, 'name': name, 'xero_id': xero_id, 'linked_existing': True})
            continue

        try:
            client = Client.objects.create(
                org=org, name=name, xero_id=xero_id,
                xero_tenant_id=integration.tenant_id,
                imported_from='xero', is_active=True,
                email=(contact.get('EmailAddress', '') or ''),
            )
            imported.append({'id': client.id, 'name': name, 'xero_id': xero_id, 'linked_existing': False})
        except Exception as e:
            errors.append({'id': cid, 'error': str(e)})

    # Auto-derive aliases for newly imported clients (best-effort, never breaks import)
    if imported:
        run_post_import_alias_derivation(org)

    return Response({
        'imported': imported, 'skipped': skipped, 'errors': errors,
        'summary': {
            'imported_count': len(imported),
            'skipped_count': len(skipped),
            'error_count': len(errors),
        },
    })


# ============================================================================
# Xero: PUSH Time as Draft Invoices
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def xero_push_time(request):
    """
    Push categorized time to Xero as DRAFT invoices.
    One invoice per client, line items grouped by category.

    Body: {
        "start_date": "2026-02-10",
        "end_date": "2026-02-14",
        "client_ids": [],       // optional
        "dry_run": false
    }

    NOTE: You need `xero_invoice_id` CharField on Block model.
    """
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'xero')
    if err:
        return err

    start_date = request.data.get('start_date')
    end_date = request.data.get('end_date')
    client_ids = request.data.get('client_ids', [])
    dry_run = request.data.get('dry_run', False)

    if not start_date or not end_date:
        return error_response('start_date and end_date are required')

    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return error_response('Invalid date format')

    tz = timezone.get_current_timezone()
    start_aware = timezone.make_aware(datetime.combine(start_dt, datetime.min.time()), tz)
    end_aware = timezone.make_aware(datetime.combine(end_dt + timedelta(days=1), datetime.min.time()), tz)

    blocks_qs = Block.objects.filter(
        org=org,
        is_categorized=True,
        start__gte=start_aware,
        start__lt=end_aware,
        client__isnull=False,
        client__xero_id__isnull=False,
    ).select_related('client', 'user')

    if hasattr(Block, 'xero_invoice_id'):
        blocks_qs = blocks_qs.filter(
            Q(xero_invoice_id__isnull=True) | Q(xero_invoice_id='')
        )

    if client_ids:
        blocks_qs = blocks_qs.filter(client_id__in=client_ids)

    blocks = list(blocks_qs.order_by('client__name', 'start'))

    if not blocks:
        return Response({
            'message': 'No unpushed time entries found',
            'invoices': [],
            'summary': {'total_invoices': 0, 'total_hours': 0, 'total_amount': 0},
        })

    # Group by client → category
    client_groups = defaultdict(list)
    for b in blocks:
        client_groups[b.client_id].append(b)

    invoices_preview = []
    for cid, cblocks in client_groups.items():
        client = cblocks[0].client

        # Get billing rate
        billing_rate = Decimal('150.00')
        try:
            rate_obj = BillingRate.objects.filter(org=org, client=client).first()
            if rate_obj:
                billing_rate = rate_obj.rate
            elif hasattr(org, 'billing_rate_default') and org.billing_rate_default:
                billing_rate = org.billing_rate_default
        except Exception:
            pass

        # Aggregate by category
        cat_totals = defaultdict(lambda: {'minutes': 0, 'block_ids': []})
        for b in cblocks:
            cats = b.category_hours or {}
            primary = list(cats.keys())[0] if cats else 'General'
            cat_totals[primary]['minutes'] += b.minutes or 0
            cat_totals[primary]['block_ids'].append(b.id)

        line_items = []
        total_hours = Decimal('0')
        all_block_ids = []

        for cat, cdata in cat_totals.items():
            hours = Decimal(str(round(cdata['minutes'] / 60.0, 2)))
            total_hours += hours
            all_block_ids.extend(cdata['block_ids'])
            line_items.append({
                'Description': f"{cat} — {start_date} to {end_date} ({hours}h @ ${billing_rate}/hr)",
                'Quantity': str(hours),
                'UnitAmount': str(billing_rate),
                'AccountCode': '200',
                'TaxType': 'NONE',
            })

        payload = {
            'Type': 'ACCREC',
            'Contact': {'ContactID': client.xero_id},
            'Date': end_date,
            'DueDate': (end_dt + timedelta(days=30)).strftime('%Y-%m-%d'),
            'LineAmountTypes': 'Exclusive',
            'Status': 'DRAFT',
            'Reference': f"TimeTracker {start_date} to {end_date}",
            'LineItems': line_items,
        }

        invoices_preview.append({
            'client_id': cid,
            'client_name': client.name,
            'total_hours': float(total_hours),
            'total_amount': float(total_hours * billing_rate),
            'block_ids': all_block_ids,
            'payload': payload,
        })

    if dry_run:
        return Response({
            'dry_run': True,
            'invoices': [{
                'client': inv['client_name'],
                'hours': inv['total_hours'],
                'amount': inv['total_amount'],
                'blocks': len(inv['block_ids']),
            } for inv in invoices_preview],
            'summary': {
                'total_invoices': len(invoices_preview),
                'total_hours': round(sum(i['total_hours'] for i in invoices_preview), 2),
                'total_amount': round(sum(i['total_amount'] for i in invoices_preview), 2),
            },
        })

    # Push
    pushed, push_errors = [], []
    for inv in invoices_preview:
        data, err = xero_api_call(integration, 'POST', '/Invoices', json=inv['payload'])
        if err:
            push_errors.append({'client': inv['client_name'], 'error': 'API call failed'})
            continue

        xero_inv = data.get('Invoices', [{}])[0]
        xero_inv_id = xero_inv.get('InvoiceID', '')

        if xero_inv_id and hasattr(Block, 'xero_invoice_id'):
            Block.objects.filter(id__in=inv['block_ids']).update(xero_invoice_id=xero_inv_id)

        pushed.append({
            'client': inv['client_name'],
            'hours': inv['total_hours'],
            'amount': inv['total_amount'],
            'xero_invoice_id': xero_inv_id,
            'xero_invoice_number': xero_inv.get('InvoiceNumber', ''),
        })

    return Response({
        'pushed': pushed,
        'errors': push_errors,
        'summary': {
            'invoices_created': len(pushed),
            'error_count': len(push_errors),
            'total_hours': round(sum(p['hours'] for p in pushed), 2),
            'total_amount': round(sum(p['amount'] for p in pushed), 2),
        },
    })


# ============================================================================
# Xero: PULL Invoices
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def xero_pull_invoices(request):
    """Pull invoices from Xero for profitability comparison."""
    org = get_user_org(request.user)
    integration, err = get_integration(org, 'xero')
    if err:
        return err

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if not start_date or not end_date:
        return error_response('start_date and end_date are required')

    # Xero date filter format
    where = (
        f'Date >= DateTime({start_date.replace("-", ",")}) '
        f'&& Date <= DateTime({end_date.replace("-", ",")})'
    )
    client_id = request.GET.get('client_id')
    if client_id:
        try:
            c = Client.objects.get(id=client_id, org=org)
            if c.xero_id:
                where += f' && Contact.ContactID==Guid("{c.xero_id}")'
        except Client.DoesNotExist:
            pass

    data, err = xero_api_call(
        integration, 'GET', '/Invoices',
        params={'where': where, 'order': 'Date ASC'},
    )
    if err:
        return err

    invoices = [i for i in data.get('Invoices', []) if i.get('Type') == 'ACCREC']
    by_contact = {}
    for inv in invoices:
        contact = inv.get('Contact', {})
        cid = contact.get('ContactID', 'unknown')
        if cid not in by_contact:
            by_contact[cid] = {
                'xero_contact_id': cid,
                'contact_name': contact.get('Name', 'Unknown'),
                'invoice_count': 0, 'total_billed': 0.0,
                'total_paid': 0.0, 'total_due': 0.0, 'invoices': [],
            }
        total = float(inv.get('Total', 0))
        due = float(inv.get('AmountDue', 0))
        by_contact[cid]['invoice_count'] += 1
        by_contact[cid]['total_billed'] += total
        by_contact[cid]['total_paid'] += total - due
        by_contact[cid]['total_due'] += due
        by_contact[cid]['invoices'].append({
            'id': inv.get('InvoiceID'), 'number': inv.get('InvoiceNumber', ''),
            'date': inv.get('Date', ''), 'total': total, 'amount_due': due,
            'status': inv.get('Status', ''),
        })

    xero_map = {c.xero_id: c for c in Client.objects.filter(org=org, xero_id__isnull=False)}
    results = []
    for cid, d in by_contact.items():
        tt = xero_map.get(cid)
        results.append({
            **d,
            'timetracker_client_id': tt.id if tt else None,
            'timetracker_client_name': tt.name if tt else None,
            'matched': tt is not None,
            'total_billed': round(d['total_billed'], 2),
            'total_paid': round(d['total_paid'], 2),
            'total_due': round(d['total_due'], 2),
        })
    results.sort(key=lambda x: x['total_billed'], reverse=True)

    return Response({
        'period': {'start': start_date, 'end': end_date},
        'contacts': results,
        'totals': {
            'total_billed': round(sum(r['total_billed'] for r in results), 2),
            'total_paid': round(sum(r['total_paid'] for r in results), 2),
            'total_due': round(sum(r['total_due'] for r in results), 2),
            'invoice_count': sum(r['invoice_count'] for r in results),
        },
    })


# ============================================================================
# Combined Status
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integrations_status(request):
    """All integration statuses + client import counts."""
    org = get_user_org(request.user)
    if not org:
        return error_response('No organization found', 404)

    integrations = {}
    for provider in ('quickbooks', 'xero'):
        try:
            i = Integration.objects.get(organization=org, provider=provider)
            integrations[provider] = {
                'connected': i.is_connected,
                'last_synced': i.updated_at.isoformat() if i.is_connected else None,
            }
            if provider == 'quickbooks':
                integrations[provider]['realm_id'] = i.realm_id if i.is_connected else None
            elif provider == 'xero':
                integrations[provider]['tenant_id'] = i.tenant_id if i.is_connected else None
        except Integration.DoesNotExist:
            integrations[provider] = {'connected': False}

    client_stats = {
        'from_quickbooks': Client.objects.filter(org=org, imported_from='quickbooks').count(),
        'from_xero': Client.objects.filter(org=org, imported_from='xero').count(),
        'manual': Client.objects.filter(org=org).filter(
            Q(imported_from='') | Q(imported_from__isnull=True)
        ).count(),
    }

    return Response({'integrations': integrations, 'client_stats': client_stats})


import hmac, hashlib, base64, json
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse

# ============================================================================
# QuickBooks Webhook (add to urls.py: path('integrations/qb/webhook/', quickbooks_webhook))
# ============================================================================

@csrf_exempt
def quickbooks_webhook(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    signature = request.headers.get('intuit-signature', '')
    payload = request.body

    try:
        expected = base64.b64encode(
            hmac.new(
                settings.QB_WEBHOOK_VERIFIER_TOKEN.encode(),
                payload,
                hashlib.sha256
            ).digest()
        ).decode()
    except Exception as e:
        logger.error(f"QB webhook signature error: {e}")
        return HttpResponse(status=401)

    if not hmac.compare_digest(expected, signature):
        logger.warning("QB webhook: invalid signature")
        return HttpResponse(status=401)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    from tracker.tasks import sync_single_qb_invoice

    # ── CloudEvents format (new) ──
    from tracker.tasks import sync_single_qb_invoice

    # Normalize to always be a list regardless of format
    if isinstance(data, dict) and 'eventNotifications' in data:
        # ── Legacy format ──
        for notification in data.get('eventNotifications', []):
            realm_id = notification.get('realmId')
            for entity in notification.get('dataChangeEvent', {}).get('entities', []):
                if entity.get('name') == 'Invoice' and entity.get('id'):
                    sync_single_qb_invoice.delay(realm_id, entity['id'], entity.get('operation', 'Update'))
                    logger.info(f"QB webhook (legacy): queued Invoice {entity['id']}")

    else:
        # ── CloudEvents format — normalize single object or array into a list ──
        events = data if isinstance(data, list) else [data]

        for event in events:
            realm_id = event.get('intuitaccountid')
            entity_id = event.get('intuitentityid')
            event_type = event.get('type', '')

            if not realm_id or not entity_id or not event_type:
                continue

            parts = event_type.split('.')  # 'qbo.invoice.created.v1'
            if len(parts) < 3:
                continue

            entity_name = parts[1].capitalize()  # 'invoice' → 'Invoice'
            operation = parts[2].capitalize()    # 'created' → 'Created'

            op_map = {'Created': 'Create', 'Updated': 'Update', 'Deleted': 'Delete', 'Voided': 'Void', 'Merged': 'Merge'}
            operation = op_map.get(operation, operation)

            if entity_name == 'Invoice':
                sync_single_qb_invoice.delay(realm_id, entity_id, operation)
                logger.info(f"QB webhook (CloudEvents): queued Invoice {entity_id} ({operation})")

    return HttpResponse(status=200)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def invoice_conflicts_count(request):
    org = get_user_org(request.user)
    from .models import InvoiceConflict
    count = InvoiceConflict.objects.filter(org=org, resolved=False).count()
    return Response({'count': count})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resolve_invoice_conflict(request, conflict_id):
    """Accept source amount or keep TimeTracker amount."""
    org = get_user_org(request.user)
    resolution = request.data.get('resolution')  # 'accept_source' or 'keep_tt'

    if resolution not in ('accept_source', 'keep_tt'):
        return error_response('Invalid resolution')

    try:
        conflict = InvoiceConflict.objects.get(id=conflict_id, org=org, resolved=False)
    except InvoiceConflict.DoesNotExist:
        return error_response('Conflict not found', 404)

    if resolution == 'accept_source':
        conflict.invoice.amount = conflict.source_amount
        conflict.invoice.save(update_fields=['amount'])

    conflict.resolved = True
    conflict.resolved_at = timezone.now()
    conflict.resolved_by = request.user
    conflict.resolution = resolution
    conflict.save()

    return Response({'success': True, 'final_amount': str(conflict.invoice.amount)})


# views_integrations.py
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def manual_sync_invoices(request):
    from tracker.tasks import reconcile_qb_invoices
    reconcile_qb_invoices.delay()
    return Response({'status': 'sync started'})