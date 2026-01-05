# tracker/views_onboarding.py
"""
Self-Service Onboarding API Endpoints

Implements the streamlined 5-step onboarding flow:
1. Admin signs up (firm name, email, password)
2. Connect integration (Karbon/QBO/TaxDome)
3. Invite team (emails with agent download links)
4. Set billing rates (optional)
5. Start tracking

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
from datetime import timedelta
from decimal import Decimal
import uuid
import secrets

from .models import (
    Organization, OrganizationMembership, Client, TaskType, 
    Invitation, OrgInstallToken, DEFAULT_CPA_TASK_TYPES
)

User = get_user_model()


# ============================================================================
# STEP 1: Firm Signup (Enhanced)
# ============================================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def onboarding_signup(request):
    """
    Create new CPA firm account with owner.
    
    POST: {
        "firm_name": "Smith & Associates CPA",
        "email": "john@smithcpa.com",
        "password": "securepass123",
        "owner_name": "John Smith",
        "timezone": "America/New_York"  # optional
    }
    
    Returns:
        - User credentials
        - Organization details
        - Auth token for immediate login
    """
    data = request.data
    
    # Validate required fields
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
    
    # Check if email already exists
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
        
        # 5. Create Install Token for agent deployment
        install_token = OrgInstallToken.objects.create(
            org=org,
            created_by=user,
            is_active=True,
        )
        
        # 6. Generate auth token for immediate login
        from .models import AuthToken
        auth_token = secrets.token_urlsafe(32)
        AuthToken.objects.create(
            user=user,
            token=auth_token,
            expires_at=timezone.now() + timedelta(days=14),
        )
    
    # Log them in
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
        'onboarding_step': 1,  # Just completed step 1
    }, status=201)


# ============================================================================
# ONBOARDING STATUS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def onboarding_status(request):
    """
    Get current onboarding progress for the user's organization.
    
    Returns completion status for each step:
    1. Account created (always true if authenticated)
    2. Integration connected
    3. Team invited (at least 1 other member)
    4. Rates configured
    5. Agent installed (at least 1 device)
    """
    from .models import AgentRegistration, BillingRate
    
    user = request.user
    
    # Get org membership
    membership = OrganizationMembership.objects.filter(user=user).select_related('organization').first()
    if not membership:
        return Response({'error': 'No organization found'}, status=404)
    
    org = membership.organization
    
    # Check each step
    steps = {
        'account_created': True,  # They're authenticated
        'integration_connected': _check_integration_connected(org),
        'team_invited': OrganizationMembership.objects.filter(organization=org).count() > 1,
        'rates_configured': BillingRate.objects.filter(org=org).exists() or org.billing_rate_default != Decimal('150.00'),
        'agent_installed': AgentRegistration.objects.filter(org=org, is_active=True).exists(),
    }
    
    # Calculate overall progress
    completed = sum(1 for v in steps.values() if v)
    total = len(steps)
    
    # Determine current step (first incomplete)
    current_step = 5  # All complete
    step_order = ['account_created', 'integration_connected', 'team_invited', 'rates_configured', 'agent_installed']
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


def _check_integration_connected(org):
    """Check if any integration is connected for this org."""
    # For now, check if org has clients imported (sign of integration)
    # In future, check actual OAuth tokens
    return Client.objects.filter(org=org).count() > 0


# ============================================================================
# STEP 2: INTEGRATIONS
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def integration_list(request):
    """
    List available integrations and their connection status.
    """
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    org = membership.organization
    
    # In production, check actual OAuth tokens
    # For now, return available integrations
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def integration_connect(request, provider):
    """
    Initiate OAuth connection for a provider.
    
    In production, this would redirect to the provider's OAuth flow.
    For now, it's a placeholder that returns the OAuth URL.
    """
    valid_providers = ['karbon', 'quickbooks', 'taxdome']
    if provider not in valid_providers:
        return Response({'error': f'Unknown provider: {provider}'}, status=400)
    
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    # Generate OAuth state token
    state = secrets.token_urlsafe(32)
    
    # Store state for verification (in production, use cache or DB)
    request.session[f'{provider}_oauth_state'] = state
    
    # Build OAuth URL (placeholder - implement actual OAuth in production)
    oauth_urls = {
        'karbon': 'https://app.karbonhq.com/oauth/authorize',
        'quickbooks': 'https://appcenter.intuit.com/connect/oauth2',
        'taxdome': 'https://app.taxdome.com/oauth/authorize',
    }
    
    return Response({
        'provider': provider,
        'oauth_url': oauth_urls[provider],
        'state': state,
        'message': f'Redirect user to OAuth URL to connect {provider}',
        'note': 'OAuth integration not yet implemented - use CSV import for now',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def integration_disconnect(request, provider):
    """Disconnect an integration."""
    # In production, revoke OAuth tokens
    return Response({
        'ok': True,
        'provider': provider,
        'message': f'{provider} disconnected',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def skip_integration(request):
    """
    Skip integration step and continue onboarding.
    User can always connect integrations later.
    """
    return Response({
        'ok': True,
        'message': 'Integration step skipped. You can connect integrations anytime from Settings.',
        'next_step': 3,
    })


# ============================================================================
# STEP 3: TEAM INVITES
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invite_team_bulk(request):
    """
    Invite multiple team members at once.
    
    POST: {
        "invites": [
            {"email": "jane@firm.com", "role": "manager", "name": "Jane Doe"},
            {"email": "bob@firm.com", "role": "member", "name": "Bob Smith"}
        ]
    }
    
    Sends emails with:
    - Login credentials
    - Desktop agent download link
    - Getting started instructions
    """
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
        
        # Check if already a member
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
    """Create user and send invite email with agent download link."""
    
    # Generate credentials
    username = email.split('@')[0][:30]
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    
    temp_password = secrets.token_urlsafe(12)
    
    first_name = name.split()[0] if name else ''
    last_name = ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else ''
    
    # Create user
    user = User.objects.create_user(
        username=username,
        email=email,
        password=temp_password,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
    )
    
    # Create membership
    OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=role,
        invited_by=invited_by,
    )
    
    # Get install token for agent download
    install_token = OrgInstallToken.objects.filter(org=org, is_active=True).first()
    
    # Build email content
    app_url = getattr(settings, 'APP_URL', 'https://timetracker.mavops.ai')
    agent_download_url = f"{app_url}/download?token={install_token.token}" if install_token else f"{app_url}/download"
    
    email_body = f"""
Hi {first_name or 'there'}!

You've been invited to join {org.name} on TimeTracker.

🚀 GET STARTED IN 2 MINUTES:

1️⃣ Download the Desktop App:
   {agent_download_url}
   
2️⃣ Sign in with these credentials:
   Email: {email}
   Password: {temp_password}
   
3️⃣ That's it! The app runs in the background and tracks your time automatically.

💡 QUICK TIPS:
• Select your current client from the menu bar icon
• Review your timesheet weekly (you'll get a reminder)
• Time is categorized automatically by AI

Need help? Reply to this email or visit {app_url}/help

Welcome aboard! 🎉

- The TimeTracker Team
"""

    # Send email
    email_sent = False
    try:
        send_mail(
            subject=f"You're invited to {org.name} on TimeTracker",
            message=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        email_sent = True
    except Exception as e:
        pass  # Don't fail the invite if email fails
    
    return {
        'email': email,
        'success': True,
        'user_id': user.id,
        'username': username,
        'temp_password': temp_password,  # Return for display in case email fails
        'email_sent': email_sent,
        'role': role,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def team_status(request):
    """Get current team members for onboarding display."""
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def skip_team_invites(request):
    """Skip team invite step - can invite later."""
    return Response({
        'ok': True,
        'message': 'Team invites skipped. You can invite team members anytime from Settings.',
        'next_step': 4,
    })


# ============================================================================
# STEP 4: BILLING RATES
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_default_rate(request):
    """
    Set the organization's default billing rate.
    
    POST: {"rate": 175.00}
    """
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def skip_rates(request):
    """Skip rate configuration - uses default $150/hour."""
    return Response({
        'ok': True,
        'message': 'Rate configuration skipped. Default rate is $150/hour. You can configure rates in Settings.',
        'next_step': 5,
    })


# ============================================================================
# STEP 5: COMPLETE ONBOARDING
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def complete_onboarding(request):
    """
    Mark onboarding as complete.
    User is ready to start tracking time.
    """
    membership = OrganizationMembership.objects.filter(user=request.user).first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    # Get install token for agent download
    install_token = OrgInstallToken.objects.filter(
        org=membership.organization, 
        is_active=True
    ).first()
    
    return Response({
        'ok': True,
        'message': 'Onboarding complete! You\'re ready to start tracking time.',
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

@api_view(['GET'])
@permission_classes([AllowAny])
def agent_download_info(request):
    """
    Get agent download URLs.
    Works with or without authentication.
    """
    import platform
    
    # Detect platform from User-Agent
    ua = request.META.get('HTTP_USER_AGENT', '').lower()
    detected_os = 'unknown'
    if 'mac' in ua or 'darwin' in ua:
        detected_os = 'macos'
    elif 'windows' in ua or 'win' in ua:
        detected_os = 'windows'
    
    # In production, these would be actual download URLs
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