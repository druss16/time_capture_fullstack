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
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from datetime import timedelta
from decimal import Decimal
import secrets


from .models import (
    Organization, OrganizationMembership, Client, TaskType, 
    OrgInstallToken, AuthToken, AgentRegistration, Invitation,
    BillingRate, DEFAULT_CPA_TASK_TYPES
)

User = get_user_model()


# ============================================================================
# STEP 1: Firm Signup
# ============================================================================

# ============================================================================
# UPDATED onboarding_signup - Replace in views_onboarding.py
# ============================================================================

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def onboarding_signup(request):
    """
    Create new firm account with owner.
    NOW ACCEPTS industry_type and seeds appropriate task types!
    """
    from tracker.industry_categories import INDUSTRY_CHOICES, get_task_types_for_industry
    
    data = request.data
    
    firm_name = (data.get('firm_name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    owner_name = (data.get('owner_name') or '').strip()
    tz = data.get('timezone', 'America/New_York')
    industry_type = data.get('industry_type', 'general')  # ✅ NEW
    
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
    
    # ✅ Validate industry type
    valid_industries = [choice[0] for choice in INDUSTRY_CHOICES]
    if industry_type not in valid_industries:
        industry_type = 'general'
    
    if User.objects.filter(email=email).exists():
        return Response({
            'ok': False, 
            'errors': {'email': 'An account with this email already exists'}
        }, status=400)
    
    with transaction.atomic():
        # 1. Create Organization WITH industry_type
        base_slug = slugify(firm_name)[:40]
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        org = Organization.objects.create(
            name=firm_name,
            slug=slug,
            industry_type=industry_type,  # ✅ SET INDUSTRY TYPE
            plan='professional',
            trial_ends_at=timezone.now() + timedelta(days=30),
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
        
        # 4. ✅ Seed Task Types BASED ON INDUSTRY (not hardcoded CPA!)
        task_types = get_task_types_for_industry(industry_type)
        for idx, tt_data in enumerate(task_types):
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
            'industry_type': org.industry_type,  # ✅ Return industry type
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


def _issue_invite(org, user, role, invited_by):
    """Mint a single-use invite link for `user` and email it.

    The link IS the credential, so nothing recoverable is ever put in the
    message body. Invitation carries its own 7-day expiry and accepted_at, so
    a forwarded email cannot be replayed after the member has used it.

    Returns (invite_url, email_sent).
    """
    invite = Invitation.create_invite(org, user.email, role, invited_by)
    base = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai').rstrip('/')
    invite_url = f"{base}/invite/{invite.token}"

    inviter_name = None
    if invited_by:
        inviter_name = invited_by.get_full_name().strip() or invited_by.email

    from tracker.email_service import send_onboarding_invitation
    email_sent = False
    try:
        email_sent = send_onboarding_invitation(
            to_email=user.email,
            org_name=org.name,
            invite_url=invite_url,
            invited_by=inviter_name,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"[INVITE] Failed to send onboarding email to {user.email}: {e}"
        )

    return invite_url, email_sent


def _create_and_invite_user(org, email, role, name, invited_by):
    """Create the member's account and email them a link to set a password.

    The account is created up front (not at accept time) so the seat is
    reserved and the person shows in the team list immediately. It is created
    WITHOUT a password: there is nothing to leak, and nothing to sign in with
    until they have been through the invite link.
    """

    username = email.split('@')[0][:30]
    base_username = username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1

    first_name = name.split()[0] if name else ''
    last_name = ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else ''

    user = User.objects.create_user(
        username=username,
        email=email,
        password=None,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
    )
    user.set_unusable_password()
    user.save(update_fields=['password'])

    OrganizationMembership.objects.create(
        user=user,
        organization=org,
        role=role,
        invited_by=invited_by,
    )

    invite_url, email_sent = _issue_invite(org, user, role, invited_by)

    return {
        'email': email,
        'success': True,
        'user_id': user.id,
        'username': username,
        'invite_url': invite_url,
        'email_sent': email_sent,
        'role': role,
    }


# ── Replace team_invite_view in tracker/views_onboarding.py ──────────────────
#
# All imports already exist at the top of views_onboarding.py:
#   - secrets, User, OrganizationMembership
#   - send_onboarding_invitation (from tracker.email_service)
#   - _create_and_invite_user (defined earlier in this file)
#
# send_team_invitation is a lighter email (no password reset messaging)
# already defined in email_service.py
# ─────────────────────────────────────────────────────────────────────────────

# ── Replace team_invite_view in tracker/views_onboarding.py ──────────────────
#
# All imports already exist at the top of views_onboarding.py:
#   - secrets, User, OrganizationMembership
#   - send_onboarding_invitation (from tracker.email_service)
#   - _create_and_invite_user (defined earlier in this file)
#
# send_team_invitation is a lighter email (no password reset messaging)
# already defined in email_service.py
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def team_invite_view(request):
    """
    Single-member invite from the Settings > Team tab.

    Handles three cases:
      1. User exists + belongs to another org  → add to this org, NO password reset
      2. User exists + no org (orphaned)        → reset password, add to org, send onboarding email
      3. Brand new user                         → create, add to org, send onboarding email

    Always errors if user is already a member of THIS org.
    """
    from tracker.email_service import send_onboarding_invitation, send_added_to_org

    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()

    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)

    org = membership.organization
    email = request.data.get('email', '').strip().lower()

    if not email:
        return Response({'error': 'Email is required'}, status=400)

    # ── Seat check ────────────────────────────────────────────────────────────
    seat_count = org.seat_count or 0
    member_count = OrganizationMembership.objects.filter(organization=org).count()
    if seat_count > 0 and member_count >= seat_count:
        return Response({
            'upgrade_required': True,
            'seat_count': seat_count,
            'current_members': member_count,
            'message': 'No seats available. Add more seats to invite more members.',
        }, status=400)

    # ── Already a member of THIS org ──────────────────────────────────────────
    if OrganizationMembership.objects.filter(
        user__email=email, organization=org
    ).exists():
        return Response(
            {'error': f'{email} is already a member of this organization.'},
            status=400,
        )

    inviter = request.user.get_full_name().strip() or request.user.username

    existing = User.objects.filter(email=email).first()

    if existing:
        # Check if they belong to any OTHER org
        other_membership = OrganizationMembership.objects.filter(
            user=existing
        ).exclude(organization=org).first()

        if other_membership:
            # ── Case 1: User belongs to another org ──────────────────────────
            # Do NOT reset their password — they need it for their other org.
            # Just add them to this org and notify them.
            OrganizationMembership.objects.get_or_create(
                user=existing,
                organization=org,
                defaults={'role': 'member', 'invited_by': request.user},
            )

            email_sent = False
            try:
                email_sent = send_added_to_org(
                    to_email=email,
                    org_name=org.name,
                    username=existing.username,
                    invited_by=inviter,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    f"[INVITE] Failed to send join notification to {email}: {e}"
                )

            return Response({
                'username': existing.username,
                'email_sent': email_sent,
                'resent': False,
                'added_existing_user': True,
                'note': 'User added from another org. Password unchanged.',
            })

        else:
            # ── Case 2: User exists in DB but has no org (orphaned account) ──
            # Nobody is relying on the old password, so retire it and let them
            # set a fresh one through the invite link like any new member.
            existing.set_unusable_password()
            existing.save(update_fields=['password'])

            OrganizationMembership.objects.get_or_create(
                user=existing,
                organization=org,
                defaults={'role': 'member', 'invited_by': request.user},
            )

            invite_url, email_sent = _issue_invite(
                org, existing, 'member', request.user,
            )

            return Response({
                'username': existing.username,
                'invite_url': invite_url,
                'email_sent': email_sent,
                'resent': True,
            })

    # ── Case 3: Brand new user ────────────────────────────────────────────────
    result = _create_and_invite_user(
        org=org,
        email=email,
        role='member',
        name='',
        invited_by=request.user,
    )
    return Response(result, status=201)
    
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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def team_activation(request):
    """GET /api/settings/team/activation/ — who is actually up and running.

    White-glove rollout lives or dies on knowing which member is stuck and
    where, so this reports the four things that have to be true in order, from
    real signals rather than a checkbox someone ticked:

        invited -> password set -> device paired -> time flowing

    A member who never opened the invite and a member whose agent died look
    identical on the team list. They should not look identical here.
    """
    from django.db.models import Count, Max, Min
    from .models import Block, AgentDevice

    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    if membership.role not in ('owner', 'admin', 'manager'):
        return Response({'error': 'Permission denied'}, status=403)

    org = membership.organization
    members = list(
        OrganizationMembership.objects.filter(organization=org)
        .select_related('user')
        .order_by('user__first_name', 'user__username')
    )
    user_ids = [m.user_id for m in members]

    # Three grouped queries rather than three per member — a 60-person firm
    # would otherwise be ~180 round trips to render one page.
    devices = {
        r['user_id']: r for r in AgentDevice.objects
        .filter(user_id__in=user_ids)
        .values('user_id')
        .annotate(count=Count('id'), last_seen=Max('last_seen_at'))
    }
    blocks = {
        r['user_id']: r for r in Block.objects
        .filter(user_id__in=user_ids, org=org)
        .values('user_id')
        .annotate(count=Count('id'), first=Min('start'), last=Max('start'))
    }
    invites = {}
    for inv in Invitation.objects.filter(organization=org).order_by('created_at'):
        invites[inv.email.lower()] = inv

    cutoff = timezone.now() - timedelta(days=7)
    rows = []
    for m in members:
        u = m.user
        dev = devices.get(u.id) or {}
        blk = blocks.get(u.id) or {}
        inv = invites.get((u.email or '').lower())

        has_password = u.has_usable_password()
        # Having a password proves nothing on its own: every account created
        # under the old temp-password flow has one whether or not the person
        # ever opened the email. Reaching the second rung means signing IN.
        signed_in = u.last_login is not None
        device_count = dev.get('count') or 0
        device_last_seen = dev.get('last_seen')
        block_count = blk.get('count') or 0
        last_block = blk.get('last')

        # Furthest rung reached, not the first one failed.
        if last_block and last_block >= cutoff:
            stage = 'time_flowing'
        elif device_count:
            stage = 'device_paired'
        elif signed_in:
            stage = 'password_set'
        else:
            stage = 'invited'

        if signed_in:
            invite_state = 'active'
        elif inv and not inv.accepted_at and inv.expires_at > timezone.now():
            invite_state = 'invite_pending'
        elif inv and not inv.accepted_at:
            invite_state = 'invite_expired'
        else:
            invite_state = 'never_signed_in'

        # A fresh invite only helps someone who has never got in. For anyone
        # who has, resending would revoke a password they are using — that is
        # a password reset, a different thing, and not offered here.
        can_resend_invite = not signed_in

        rows.append({
            'user_id': u.id,
            'name': f"{u.first_name} {u.last_name}".strip() or u.username,
            'email': u.email,
            'role': m.role,
            'is_you': u.id == request.user.id,
            'stage': stage,
            'invite_state': invite_state,
            'invite_sent_at': inv.created_at.isoformat() if inv else None,
            'invite_expires_at': inv.expires_at.isoformat() if inv and not inv.accepted_at else None,
            'has_password': has_password,
            'signed_in': signed_in,
            'can_resend_invite': can_resend_invite,
            'last_login': u.last_login.isoformat() if u.last_login else None,
            'device_count': device_count,
            'device_last_seen': device_last_seen.isoformat() if device_last_seen else None,
            'block_count': block_count,
            'last_block_at': last_block.isoformat() if last_block else None,
        })

    order = ['invited', 'password_set', 'device_paired', 'time_flowing']
    counts = {s: sum(1 for r in rows if r['stage'] == s) for s in order}

    return Response({
        'org_name': org.name,
        'total': len(rows),
        'ready': counts['time_flowing'],
        'counts': counts,
        # Stuck first — this page exists to surface those.
        'members': sorted(rows, key=lambda r: (order.index(r['stage']), r['name'])),
    })


@csrf_exempt
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def resend_invite(request, user_id):
    """POST /api/settings/team/<user_id>/resend-invite/ — mint a fresh link.

    Invites expire, and the common white-glove case is a member who let one
    lapse. Re-inviting through the normal path would collide with the account
    that already exists, so resending is its own action.
    """
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()
    if not membership or membership.role not in ('owner', 'admin'):
        return Response({'error': 'Permission denied'}, status=403)

    org = membership.organization
    target = OrganizationMembership.objects.filter(
        organization=org, user_id=user_id,
    ).select_related('user').first()
    if not target:
        return Response({'error': 'Not a member of this organization'}, status=404)

    if target.user.last_login is not None:
        return Response(
            {'error': 'This member has already signed in. Send them a password reset instead.'},
            status=400,
        )

    # They have never been in, so nothing depends on whatever password they
    # were issued. Retiring it here is the point as much as a side effect: it
    # is how a password that went out in a plaintext email stops working.
    if target.user.has_usable_password():
        target.user.set_unusable_password()
        target.user.save(update_fields=['password'])

    # Retire any live invite so only the newest link works.
    Invitation.objects.filter(
        organization=org, email=target.user.email, accepted_at__isnull=True,
    ).update(expires_at=timezone.now())

    invite_url, email_sent = _issue_invite(org, target.user, target.role, request.user)
    return Response({
        'ok': True,
        'email': target.user.email,
        'invite_url': invite_url,
        'email_sent': email_sent,
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