# tracker/views_onboarding.py
"""
Self-Service Onboarding API Endpoints
CSRF exempt for token-based authentication
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model, login
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from datetime import timedelta
from decimal import Decimal
import secrets


from .models import (
    Organization, OrganizationMembership, Client, TaskType, 
    OrgInstallToken, AuthToken, AgentRegistration,
    BillingRate, DEFAULT_CPA_TASK_TYPES
)

User = get_user_model()


# ============================================================================
# STEP 1: Firm Signup
# ============================================================================

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def onboarding_signup(request):
    """
    Create new CPA firm account with owner.
    """
    data = request.data
    
    firm_name = (data.get('firm_name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    owner_name = (data.get('owner_name') or '').strip()
    tz = data.get('timezone', 'America/New_York')
    
    errors = {}
    if not firm_name:
        errors['firm_name'] = 'Firm name is required'
    if not email:
        errors['email'] = 'Email is required'
    elif '@' not in email:
        errors['email'] = 'Invalid email format'
    if not password or len(password) < 8:
        errors['password'] = 'Password must be at least 8 characters'
    
    if errors:
        return Response({'ok': False, 'errors': errors}, status=400)
    
    if User.objects.filter(email=email).exists():
        return Response({
            'ok': False, 
            'errors': {'email': 'An account with this email already exists'}
        }, status=400)
    
    with transaction.atomic():
        # 1. Create Organization
        base_slug = slugify(firm_name)[:40]
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        org = Organization.objects.create(
            name=firm_name,
            slug=slug,
            plan='trial',
            trial_ends_at=timezone.now() + timedelta(days=14),
            timezone=tz,
            billing_rate_default=Decimal('150.00'),
        )
        
        # 2. Create Owner User
        username = email.split('@')[0][:30]
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1
        
        first_name = owner_name.split()[0] if owner_name else ''
        last_name = ' '.join(owner_name.split()[1:]) if owner_name and len(owner_name.split()) > 1 else ''
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        
        # 3. Create Owner Membership
        OrganizationMembership.objects.create(
            user=user,
            organization=org,
            role='owner',
        )
        
        # 4. Seed Default Task Types
        for idx, tt_data in enumerate(DEFAULT_CPA_TASK_TYPES):
            TaskType.objects.create(
                org=org,
                name=tt_data['name'],
                code=tt_data['code'],
                color=tt_data['color'],
                is_billable=tt_data['is_billable'],
                sort_order=idx,
            )
        
        # 5. Create Install Token
        install_token = OrgInstallToken.objects.create(
            org=org,
            created_by=user,
            is_active=True,
        )
        
        # 6. Generate auth token
        auth_token = secrets.token_urlsafe(32)
        AuthToken.objects.create(
            user=user,
            token=auth_token,
            expires_at=timezone.now() + timedelta(days=14),
        )
    
    login(request, user)
    
    return Response({
        'ok': True,
        'token': auth_token,
        'user': {
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'name': f"{first_name} {last_name}".strip(),
        },
        'organization': {
            'id': org.id,
            'name': org.name,
            'slug': org.slug,
            'plan': org.plan,
            'trial_ends_at': org.trial_ends_at.isoformat() if org.trial_ends_at else None,
        },
        'install_token': install_token.token,
        'onboarding_step': 1,
    }, status=201)


# ============================================================================
# ONBOARDING STATUS
# ============================================================================

@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def onboarding_status(request):
    """Get current onboarding progress."""
    user = request.user
    
    membership = OrganizationMembership.objects.filter(user=user).select_related('organization').first()
    if not membership:
        return Response({'error': 'No organization found'}, status=404)
    
    org = membership.organization
    
    steps = {
        'account_created': True,
        'integration_connected': Client.objects.filter(org=org).count() > 0,
        'team_invited': OrganizationMembership.objects.filter(organization=org).count() > 1,
        'rates_configured': BillingRate.objects.filter(org=org).exists() or org.billing_rate_default != Decimal('150.00'),
        'agent_installed': AgentRegistration.objects.filter(org=org, is_active=True).exists(),
    }
    
    completed = sum(1 for v in steps.values() if v)
    total = len(steps)
    
    step_order = ['account_created', 'integration_connected', 'team_invited', 'rates_configured', 'agent_installed']
    current_step = 5
    for i, step in enumerate(step_order):
        if not steps[step]:
            current_step = i + 1
            break
    
    return Response({
        'organization': {
            'id': org.id,
            'name': org.name,
            'plan': org.plan,
            'trial_ends_at': org.trial_ends_at.isoformat() if org.trial_ends_at else None,
        },
        'steps': steps,
        'current_step': current_step,
        'progress': {
            'completed': completed,
            'total': total,
            'percent': int((completed / total) * 100),
        },
        'is_complete': completed == total,
    })


# ============================================================================
# STEP 2: INTEGRATIONS
# ============================================================================

@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integration_list(request):
    """List available integrations."""
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    org = membership.organization
    
    integrations = [
        {
            'id': 'karbon',
            'name': 'Karbon',
            'description': 'Auto-import clients and contacts',
            'icon': 'karbon',
            'connected': False,
            'oauth_url': f'/api/integrations/karbon/connect/?org={org.id}',
        },
        {
            'id': 'quickbooks',
            'name': 'QuickBooks Online',
            'description': 'Auto-import customers as clients',
            'icon': 'quickbooks',
            'connected': False,
            'oauth_url': f'/api/integrations/qbo/connect/?org={org.id}',
        },
        {
            'id': 'taxdome',
            'name': 'TaxDome',
            'description': 'Auto-import accounts as clients',
            'icon': 'taxdome',
            'connected': False,
            'oauth_url': f'/api/integrations/taxdome/connect/?org={org.id}',
        },
    ]
    
    return Response({
        'integrations': integrations,
        'has_clients': Client.objects.filter(org=org).exists(),
        'client_count': Client.objects.filter(org=org, is_active=True).count(),
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def integration_connect(request, provider):
    """Initiate OAuth connection."""
    valid_providers = ['karbon', 'quickbooks', 'taxdome']
    if provider not in valid_providers:
        return Response({'error': f'Unknown provider: {provider}'}, status=400)
    
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    state = secrets.token_urlsafe(32)
    request.session[f'{provider}_oauth_state'] = state
    
    oauth_urls = {
        'karbon': 'https://app.karbonhq.com/oauth/authorize',
        'quickbooks': 'https://appcenter.intuit.com/connect/oauth2',
        'taxdome': 'https://app.taxdome.com/oauth/authorize',
    }
    
    return Response({
        'provider': provider,
        'oauth_url': oauth_urls[provider],
        'state': state,
        'note': 'OAuth integration not yet implemented - use CSV import for now',
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def integration_disconnect(request, provider):
    """Disconnect an integration."""
    return Response({
        'ok': True,
        'provider': provider,
        'message': f'{provider} disconnected',
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def skip_integration(request):
    """Skip integration step."""
    return Response({
        'ok': True,
        'message': 'Integration step skipped.',
        'next_step': 3,
    })


# ============================================================================
# STEP 3: TEAM INVITES
# ============================================================================

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invite_team_bulk(request):
    """Invite multiple team members."""
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return Response({'error': 'Not authorized to invite team members'}, status=403)
    
    org = membership.organization
    invites = request.data.get('invites', [])
    
    if not invites:
        return Response({'error': 'No invites provided'}, status=400)
    
    results = []
    
    for invite_data in invites:
        email = (invite_data.get('email') or '').strip().lower()
        role = invite_data.get('role', 'member')
        name = (invite_data.get('name') or '').strip()
        
        if not email or '@' not in email:
            results.append({'email': email, 'success': False, 'error': 'Invalid email'})
            continue
        
        if role not in ['admin', 'manager', 'member']:
            role = 'member'
        
        if User.objects.filter(email=email).exists():
            existing_user = User.objects.get(email=email)
            if OrganizationMembership.objects.filter(user=existing_user, organization=org).exists():
                results.append({'email': email, 'success': False, 'error': 'Already a team member'})
                continue
        
        try:
            result = _create_and_invite_user(org, email, role, name, request.user)
            results.append(result)
        except Exception as e:
            results.append({'email': email, 'success': False, 'error': str(e)})
    
    success_count = sum(1 for r in results if r.get('success'))
    
    return Response({
        'ok': True,
        'invited': success_count,
        'total': len(invites),
        'results': results,
    })


def _create_and_invite_user(org, email, role, name, invited_by):
    """Create user and send invite email."""
    
    username = email.split('@')[0][:30]
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    
    temp_password = secrets.token_urlsafe(12)
    
    first_name = name.split()[0] if name else ''
    last_name = ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else ''
    
    user = User.objects.create_user(
        username=username,
        email=email,
        password=temp_password,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
    )
    
    OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=role,
        invited_by=invited_by,
    )
    
    install_token = OrgInstallToken.objects.filter(org=org, is_active=True).first()
    
    app_url = getattr(settings, 'APP_URL', 'https://timetracker.mavops.ai')
    agent_download_url = f"{app_url}/download?token={install_token.token}" if install_token else f"{app_url}/download"
    
    email_body = f"""
Hi {first_name or 'there'}!

You've been invited to join {org.name} on TimeTracker.

GET STARTED:

1. Download the Desktop App:
   {agent_download_url}
   
2. Sign in with these credentials:
   Email: {email}
   Password: {temp_password}
   
3. That's it! The app runs in the background and tracks your time automatically.

Need help? Visit {app_url}/help

- The TimeTracker Team
"""

    email_sent = False
    try:
        send_mail(
            subject=f"You're invited to {org.name} on TimeTracker",
            message=email_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@mavops.ai'),
            recipient_list=[email],
            fail_silently=False,
        )
        email_sent = True
    except Exception:
        pass
    
    return {
        'email': email,
        'success': True,
        'user_id': user.id,
        'username': username,
        'temp_password': temp_password,
        'email_sent': email_sent,
        'role': role,
    }


@csrf_exempt
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def team_status(request):
    """Get current team members."""
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    org = membership.organization
    
    members = OrganizationMembership.objects.filter(
        organization=org
    ).select_related('user').order_by('-role', 'user__first_name')
    
    return Response({
        'count': members.count(),
        'members': [{
            'id': m.user.id,
            'email': m.user.email,
            'name': f"{m.user.first_name} {m.user.last_name}".strip() or m.user.username,
            'role': m.role,
            'is_you': m.user == request.user,
        } for m in members],
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def skip_team_invites(request):
    """Skip team invite step."""
    return Response({
        'ok': True,
        'message': 'Team invites skipped.',
        'next_step': 4,
    })


# ============================================================================
# STEP 4: BILLING RATES
# ============================================================================

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_default_rate(request):
    """Set the organization's default billing rate."""
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership or membership.role not in ['owner', 'admin']:
        return Response({'error': 'Not authorized'}, status=403)
    
    org = membership.organization
    
    rate = request.data.get('rate')
    if rate is None:
        return Response({'error': 'Rate is required'}, status=400)
    
    try:
        rate = Decimal(str(rate))
        if rate < 0:
            raise ValueError()
    except:
        return Response({'error': 'Invalid rate'}, status=400)
    
    org.billing_rate_default = rate
    org.save(update_fields=['billing_rate_default'])
    
    return Response({
        'ok': True,
        'rate': str(rate),
        'message': f'Default billing rate set to ${rate}/hour',
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def skip_rates(request):
    """Skip rate configuration."""
    return Response({
        'ok': True,
        'message': 'Rate configuration skipped.',
        'next_step': 5,
    })


# ============================================================================
# STEP 5: COMPLETE ONBOARDING
# ============================================================================

@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_onboarding(request):
    """Mark onboarding as complete."""
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    install_token = OrgInstallToken.objects.filter(
        org=membership.organization, 
        is_active=True
    ).first()
    
    return Response({
        'ok': True,
        'message': 'Onboarding complete!',
        'next_steps': [
            'Download the desktop app to start automatic time tracking',
            'Select your client from the menu bar when working',
            'Review your timesheet at the end of each week',
        ],
        'install_token': install_token.token if install_token else None,
        'download_url': '/download',
    })


# ============================================================================
# AGENT DOWNLOAD
# ============================================================================

@csrf_exempt
@api_view(['GET'])
@permission_classes([AllowAny])
def agent_download_info(request):
    """Get agent download URLs."""
    ua = request.META.get('HTTP_USER_AGENT', '').lower()
    detected_os = 'unknown'
    if 'mac' in ua or 'darwin' in ua:
        detected_os = 'macos'
    elif 'windows' in ua or 'win' in ua:
        detected_os = 'windows'
    
    app_url = getattr(settings, 'APP_URL', 'https://timetracker.mavops.ai')
    
    return Response({
        'detected_os': detected_os,
        'downloads': {
            'macos': {
                'url': f'{app_url}/downloads/TimeTracker-mac.dmg',
                'name': 'TimeTracker for Mac',
                'size': '45 MB',
                'requirements': 'macOS 12 or later',
            },
            'windows': {
                'url': f'{app_url}/downloads/TimeTracker-win.exe',
                'name': 'TimeTracker for Windows',
                'size': '52 MB',
                'requirements': 'Windows 10 or later',
            },
        },
        'instructions': {
            'macos': [
                'Download and open the .dmg file',
                'Drag TimeTracker to Applications',
                'Open TimeTracker and grant Accessibility permission when prompted',
                'Sign in with your email and password',
            ],
            'windows': [
                'Download and run the installer',
                'Follow the installation wizard',
                'TimeTracker will start automatically',
                'Sign in with your email and password',
            ],
        },
    })