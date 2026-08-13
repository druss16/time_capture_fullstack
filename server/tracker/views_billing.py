from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action, permission_classes, parser_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView  # ← ADD THIS LINE
from django.db.models import Sum, F, Q, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import timedelta, date
from decimal import Decimal
from .models import (
    BillingRate, Timesheet, Block, BlockAuditLog,
    Client, TaskType, Organization, OrganizationMembership,
    EmployeeCostRate, Invitation, Invoice, ClientBudget,
    ClientBillingProfile,
)
from .serializers_billing import (
    BillingRateSerializer, TimesheetSummarySerializer, TimesheetDetailSerializer,
    ApprovalQueueItemSerializer, ClientSummarySerializer, BlockAuditLogSerializer,
    InvoiceExportSerializer,
    EmployeeCostRateSerializer,
    ClientBillingProfileSerializer,
)
from functools import wraps  # Add this import

from django.conf import settings
import stripe
from django.utils.timezone import localtime

import csv
import io
from rest_framework.parsers import MultiPartParser, FormParser

stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", None) or ""


EXECUTIVE_PLANS = ['executive']
PROFESSIONAL_PLANS = ['professional', 'executive']  # ← ADD THIS

def get_request_org_override_billing(request):
    from tracker.models import Organization
    override_id = request.GET.get("org_id") or (request.data.get("org_id") if hasattr(request, 'data') else None)
    if override_id and (request.user.is_staff or request.user.is_superuser):
        try:
            return Organization.objects.get(id=int(override_id))
        except (Organization.DoesNotExist, ValueError, TypeError):
            pass
    return get_user_org(request.user)

def get_request_user_override_billing(request):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    override_uid = request.GET.get("user_id")
    if override_uid and (request.user.is_staff or request.user.is_superuser):
        try:
            return User.objects.get(id=int(override_uid))
        except (User.DoesNotExist, ValueError, TypeError):
            pass
    return request.user


class RequireExecutivePlanMixin:
    """Mixin that restricts view to Executive/Enterprise plans"""
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        
        org = get_user_org(request.user)
        if not org:
            return Response({"error": "No organization found"}, status=404)
        
        plan = getattr(org, 'plan', 'professional') or 'professional'
        
        if plan not in EXECUTIVE_PLANS:
            return Response({
                "error": "upgrade_required",
                "message": "This feature requires an Executive or Enterprise plan.",
                "current_plan": plan,
                "upgrade_url": "/account/billing"
            }, status=403)
        
        return super().dispatch(request, *args, **kwargs)

def require_professional_plan(view_func):
    """Decorator that restricts endpoint to Professional/Enterprise plans"""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        org = get_user_org(request.user)
        if not org:
            return Response({"error": "No organization found"}, status=404)
        
        plan = getattr(org, 'plan', 'none') or 'none'

        
        if plan not in PROFESSIONAL_PLANS:
            return Response({
                "error": "upgrade_required",
                "message": "This feature requires a Professional or Enterprise plan.",
                "current_plan": plan,
                "upgrade_url": "/account/billing"
            }, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapped

def get_user_org(user):
    """Get the user's Organization from OrganizationMembership."""
    try:
        membership = OrganizationMembership.objects.filter(user=user).first()
        if membership:
            return membership.organization
        return None
    except Exception as e:
        print(f"Error in get_user_org: {e}")
        return None

def get_monday(d):
    """Get Monday of the week containing date d"""
    return d - timedelta(days=d.weekday())


def get_membership(self, request):
    return OrganizationMembership.objects.filter(
        user=request.user
    ).select_related('organization').first()

def safe_date(d):
    """Safely convert date to ISO string"""
    if not d:
        return None
    return d.isoformat() if hasattr(d, 'isoformat') else d


class ClientBillingProfileView(APIView):
    """
    Per-client billing profile — owner/admin only (managers approve; owners bill).

    GET  billing/clients/<client_id>/billing-profile/
      Returns the saved profile, or unsaved defaults if none exists yet, plus
      two read-only aids: `effective_hourly_rate` (resolved from BillingRate:
      client-level → org default) and the QB customer fallback so the modal can
      prefill without extra round-trips.
    PUT  billing/clients/<client_id>/billing-profile/
      Upserts the profile (partial). Stamps updated_by.

    Hourly RATES are intentionally not written here — they stay in BillingRate so
    there's one source of truth; the modal shows the effective rate read-only and
    points to the Billing Rates screen to change it.
    """
    permission_classes = [IsAuthenticated]

    def _guard(self, request, client_id):
        org = get_request_org_override_billing(request)
        if not org:
            return None, None, Response({'error': 'No organization'}, status=400)
        is_staff = request.user.is_staff or request.user.is_superuser
        if not is_staff:
            m = OrganizationMembership.objects.filter(
                user=request.user, organization=org
            ).first()
            if not m or m.role not in ['owner', 'admin']:
                return None, None, Response(
                    {'error': 'Only an owner or admin can manage billing profiles.'},
                    status=403,
                )
        client = Client.objects.filter(id=client_id, org=org).first()
        if not client:
            return None, None, Response({'error': 'Client not found'}, status=404)
        return org, client, None

    def _effective_hourly_rate(self, org, client):
        """Client-level BillingRate (no task_type/user) → org default. Task-level
        overrides still apply per-line at export time; this is the headline rate."""
        r = (BillingRate.objects
             .filter(org=org, client=client, task_type__isnull=True, user__isnull=True)
             .order_by('-effective_date')
             .first())
        if r:
            return r.rate
        return org.billing_rate_default

    def _payload(self, org, client, profile):
        if profile is not None:
            data = ClientBillingProfileSerializer(profile).data
        else:
            data = ClientBillingProfileSerializer(
                ClientBillingProfile(client=client, org=org)
            ).data
        rate = self._effective_hourly_rate(org, client)
        data['effective_hourly_rate'] = str(rate) if rate is not None else None
        return data

    def get(self, request, client_id):
        org, client, err = self._guard(request, client_id)
        if err:
            return err
        profile = ClientBillingProfile.objects.filter(client=client).first()
        return Response(self._payload(org, client, profile))

    def put(self, request, client_id):
        org, client, err = self._guard(request, client_id)
        if err:
            return err
        profile, _created = ClientBillingProfile.objects.get_or_create(
            client=client, defaults={'org': org}
        )
        serializer = ClientBillingProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(org=org, updated_by=request.user)
        return Response(self._payload(org, client, profile))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_billing_profiles(request):
    """
    All active clients + their billing profile in ONE call (for the Economics
    flat-fee section). Avoids the N+1 of fetching each client's profile
    separately. Read-only; org-scoped.

    GET billing/clients/billing-profiles/
      → [ { client_id, name, billing_type, flat_amount, flat_period }, ... ]
    """
    org = get_request_org_override_billing(request)
    if not org:
        return Response({'error': 'No organization'}, status=400)

    clients = Client.objects.filter(org=org, is_active=True).order_by('name')
    profiles = {p.client_id: p for p in ClientBillingProfile.objects.filter(client__org=org)}
    out = []
    for c in clients:
        p = profiles.get(c.id)
        out.append({
            'client_id': c.id,
            'name': c.name,
            'billing_type': p.billing_type if p else 'hourly',
            'flat_amount': str(p.flat_amount) if (p and p.flat_amount is not None) else None,
            'flat_period': (p.flat_period if p else '') or '',
        })
    return Response(out)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_set_billing_profile(request):
    """
    Apply billing-profile fields to many clients at once (owner/admin only).
    Only the fields present in the payload are changed on each client's profile
    (upserting a profile if none exists) — so you can e.g. set billing_system on
    30 clients without touching their billing_type. Per-client details (exact
    flat amount, customer mapping) are still tuned in the single-client modal.

    POST billing/clients/bulk-billing-profile/
      { "client_ids": [1,2,3],
        "billing_type": "hourly",           # optional
        "billing_system": "qb_desktop",     # optional
        "flat_amount": "1200.00",           # optional
        "flat_period": "monthly",           # optional
        "default_item_name": "Bookkeeping"  # optional
      }
    """
    org = get_request_org_override_billing(request)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    if not (request.user.is_staff or request.user.is_superuser):
        m = OrganizationMembership.objects.filter(user=request.user, organization=org).first()
        if not m or m.role not in ['owner', 'admin']:
            return Response({'error': 'Only an owner or admin can manage billing profiles.'}, status=403)

    client_ids = request.data.get('client_ids') or []
    if not isinstance(client_ids, list) or not client_ids:
        return Response({'error': 'client_ids is required'}, status=400)

    # Validate any provided choice fields against the model's choices.
    valid_types = {c[0] for c in ClientBillingProfile.BILLING_TYPE_CHOICES}
    valid_systems = {c[0] for c in ClientBillingProfile.BILLING_SYSTEM_CHOICES}
    valid_periods = {c[0] for c in ClientBillingProfile.FLAT_PERIOD_CHOICES} | {''}

    updates = {}
    if 'billing_type' in request.data:
        v = request.data['billing_type']
        if v not in valid_types:
            return Response({'error': f'Invalid billing_type: {v}'}, status=400)
        updates['billing_type'] = v
    if 'billing_system' in request.data:
        v = request.data['billing_system']
        if v not in valid_systems:
            return Response({'error': f'Invalid billing_system: {v}'}, status=400)
        updates['billing_system'] = v
    if 'flat_period' in request.data:
        v = request.data['flat_period'] or ''
        if v not in valid_periods:
            return Response({'error': f'Invalid flat_period: {v}'}, status=400)
        updates['flat_period'] = v
    if 'flat_amount' in request.data:
        raw = request.data['flat_amount']
        if raw in (None, ''):
            updates['flat_amount'] = None
        else:
            try:
                updates['flat_amount'] = Decimal(str(raw))
            except (ValueError, TypeError, ArithmeticError):
                return Response({'error': f'Invalid flat_amount: {raw}'}, status=400)
    if 'default_item_name' in request.data:
        updates['default_item_name'] = str(request.data['default_item_name'])[:255]

    if not updates:
        return Response({'error': 'No billing fields provided to apply'}, status=400)

    clients = Client.objects.filter(org=org, id__in=client_ids)
    count = 0
    for client in clients:
        profile, _ = ClientBillingProfile.objects.get_or_create(client=client, defaults={'org': org})
        for k, v in updates.items():
            setattr(profile, k, v)
        profile.org = org
        profile.updated_by = request.user
        profile.save()
        count += 1

    return Response({'updated': count, 'fields': list(updates.keys())})


# ===============================
# BILLING RATES VIEWSET (Professional Plan Only)
# ===============================
class BillingRateViewSet(RequireExecutivePlanMixin, viewsets.ModelViewSet):
    """
    CRUD for billing rates.
    Managers/Admins only.
    RESTRICTED TO: Professional and Enterprise plans.
    """
    serializer_class = BillingRateSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        org = get_user_org(self.request.user)
        if not org:
            return BillingRate.objects.none()
        return BillingRate.objects.filter(org=org).select_related('user', 'client', 'task_type')
    
    def perform_create(self, serializer):
        org = get_user_org(self.request.user)
        serializer.save(org=org)
    
    @action(detail=False, methods=['get'])
    def for_user(self, request):
        """Get all rates for a specific user"""
        user_id = request.query_params.get('user_id')
        if not user_id:
            return Response({'error': 'user_id required'}, status=400)
        
        rates = self.get_queryset().filter(user_id=user_id)
        return Response(BillingRateSerializer(rates, many=True).data)



# ===============================
# TIMESHEET VIEWSET
# ===============================

class TimesheetViewSet(viewsets.ModelViewSet):
    """
    Timesheet management.
    - Employees see their own timesheets
    - Managers see all timesheets in org
    """
    permission_classes = [IsAuthenticated]
    
    def get_serializer_class(self):
        if self.action == 'list':
            return TimesheetSummarySerializer
        return TimesheetDetailSerializer
    
    def get_queryset(self):
        org = get_user_org(self.request.user)
        if not org:
            return Timesheet.objects.none()
        
        membership = OrganizationMembership.objects.filter(
            user=self.request.user, organization=org
        ).first()
        
        qs = Timesheet.objects.filter(org=org).select_related('user', 'approved_by', 'rejected_by')
        
        # Non-managers only see their own
        if membership and membership.role in ('member',):
            qs = qs.filter(user=self.request.user)
        
        return qs.order_by('-week_start')
    
    def perform_create(self, serializer):
        org = get_user_org(self.request.user)
        serializer.save(org=org, user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def current_week(self, request):
        """Get or create timesheet for current week"""
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization'}, status=400)
        
        today = timezone.now().date()
        timesheet, created = Timesheet.get_or_create_for_date(org, request.user, today)
        
        return Response(TimesheetDetailSerializer(timesheet).data)
    
    @action(detail=False, methods=['get'])
    def for_week(self, request):
        """Get timesheet for a specific week"""
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization'}, status=400)
        
        week_start = request.query_params.get('week_start')
        if not week_start:
            return Response({'error': 'week_start required (YYYY-MM-DD)'}, status=400)
        
        try:
            week_start = date.fromisoformat(week_start)
        except ValueError:
            return Response({'error': 'Invalid date format'}, status=400)
        
        # Ensure it's a Monday
        week_start = get_monday(week_start)
        
        timesheet, created = Timesheet.get_or_create_for_date(org, request.user, week_start)
        return Response(TimesheetDetailSerializer(timesheet).data)
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit timesheet for approval"""
        timesheet = self.get_object()
        
        if timesheet.user != request.user:
            return Response({'error': 'Can only submit your own timesheet'}, status=403)
        
        try:
            notes = request.data.get('notes', '')
            timesheet.submit(notes=notes)
            return Response(TimesheetDetailSerializer(timesheet).data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a submitted timesheet (managers only)"""
        timesheet = self.get_object()
        
        # Check if user is manager/admin
        org = get_user_org(request.user)
        membership = OrganizationMembership.objects.filter(
            user=request.user, organization=org
        ).first()
        
        if not membership or membership.role not in ('owner', 'admin', 'manager'):
            return Response({'error': 'Insufficient permissions'}, status=403)
        
        try:
            notes = request.data.get('notes', '')
            timesheet.approve(approved_by=request.user, notes=notes)
            return Response(TimesheetDetailSerializer(timesheet).data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a submitted timesheet (managers only)"""
        timesheet = self.get_object()
        
        org = get_user_org(request.user)
        membership = OrganizationMembership.objects.filter(
            user=request.user, organization=org
        ).first()
        
        if not membership or membership.role not in ('owner', 'admin', 'manager'):
            return Response({'error': 'Insufficient permissions'}, status=403)
        
        try:
            reason = request.data.get('reason', '')
            if not reason:
                return Response({'error': 'Rejection reason required'}, status=400)
            timesheet.reject(rejected_by=request.user, reason=reason)
            return Response(TimesheetDetailSerializer(timesheet).data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
    
    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        """Reopen a rejected timesheet"""
        timesheet = self.get_object()
        
        if timesheet.user != request.user:
            return Response({'error': 'Can only reopen your own timesheet'}, status=403)
        
        try:
            timesheet.reopen()
            return Response(TimesheetDetailSerializer(timesheet).data)
        except ValueError as e:
            return Response({'error': str(e)}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def timesheet_detail_view(request, pk):
    """
    Full timesheet detail for manager drawer review.
    GET /api/billing/timesheets/<pk>/detail/
    Returns: entries grid + daily block timeline.
    """
    import datetime as dt_module
    from datetime import timezone as dt_timezone
    from django.utils.timezone import localtime
    from tracker.models import RawEvent  # adjust if your app is named differently
 
    org = get_request_org_override_billing(request)
    if not org:
        return Response({'error': 'No organization'}, status=400)

    if request.user.is_staff or request.user.is_superuser:
        is_manager = True
    else:
        membership = OrganizationMembership.objects.filter(
            user=request.user, organization=org
        ).first()
        if not membership:
            return Response({'error': 'No membership'}, status=403)
        is_manager = membership.role in ('owner', 'admin', 'manager')
 
    try:
        if is_manager:
            timesheet = Timesheet.objects.select_related('user').get(pk=pk, org=org)
        else:
            timesheet = Timesheet.objects.select_related('user').get(
                pk=pk, org=org, user=request.user
            )
    except Timesheet.DoesNotExist:
        return Response({'error': 'Not found.'}, status=404)
 
    ts_user    = timesheet.user
    week_start = timesheet.week_start
    week_end   = week_start + timedelta(days=6)
    day_strings = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]
 
    tz = timezone.get_current_timezone()
    start_utc = timezone.make_aware(
        dt_module.datetime.combine(week_start, dt_module.time.min), tz
    ).astimezone(dt_timezone.utc)
    end_utc = timezone.make_aware(
        dt_module.datetime.combine(week_end, dt_module.time.max), tz
    ).astimezone(dt_timezone.utc)
 
    # ── Entries grid (same event-based logic as weekly_timesheet_view) ────────
 
    events = list(RawEvent.objects.filter(
        user=ts_user,
        start_ts__gte=start_utc,
        start_ts__lt=end_utc,
    ).select_related('block', 'block__client', 'block__task_type').order_by('start_ts'))
 
    deleted_block_ids = set(
        Block.objects.filter(user=ts_user, deleted_at__isnull=False)
        .values_list('id', flat=True)
    )
 
    grid = {}
    IDLE_CAP = 180  # 3-min cap, matches weekly_timesheet_view
 
    for i, event in enumerate(events):
        if i + 1 < len(events):
            gap = (events[i + 1].start_ts - event.start_ts).total_seconds()
            duration_min = min(gap, IDLE_CAP) / 60.0
        else:
            duration_min = 3.0
 
        block = event.block
        if block and block.id in deleted_block_ids:
            block = None
 
        if block and block.client_id:
            client_id      = block.client_id
            client_name    = block.client.name if block.client else 'Unassigned'
            task_type_id   = block.task_type_id
            task_type_name = block.task_type.name if block.task_type else 'General'
            is_billable    = block.is_billable
        else:
            client_id = None; client_name = 'Unassigned'
            task_type_id = None; task_type_name = 'General'; is_billable = False
 
        day_str = localtime(event.start_ts).date().isoformat()
        if day_str not in day_strings:
            continue
 
        key = (client_id, task_type_id)
        if key not in grid:
            grid[key] = {
                'client_id': client_id, 'client_name': client_name,
                'task_type_id': task_type_id, 'task_type_name': task_type_name,
                'is_billable': is_billable,
                'day_minutes': {d: 0.0 for d in day_strings},
            }
        grid[key]['day_minutes'][day_str] += duration_min
 
    # Mobile blocks
    for block in Block.objects.filter(
        user=ts_user, org=org, hostname='mobile',
        start__gte=start_utc, start__lte=end_utc,
        is_categorized=True, client__isnull=False, deleted_at__isnull=True,
    ).select_related('client', 'task_type'):
        day_str = localtime(block.start).date().isoformat()
        if day_str not in day_strings:
            continue
        key = (block.client_id, block.task_type_id)
        if key not in grid:
            grid[key] = {
                'client_id': block.client_id,
                'client_name': block.client.name,
                'task_type_id': block.task_type_id,
                'task_type_name': block.task_type.name if block.task_type else 'General',
                'is_billable': block.is_billable,
                'day_minutes': {d: 0.0 for d in day_strings},
            }
        grid[key]['day_minutes'][day_str] += float(block.minutes or 0)
 
    entries = []
    daily_totals   = {d: 0.0 for d in day_strings}
    grand_total    = 0.0
    billable_total = 0.0
 
    for data in grid.values():
        day_hours  = {}
        row_minutes = 0.0
        for d in day_strings:
            m = data['day_minutes'][d]
            day_hours[d] = round(m / 60, 2)
            daily_totals[d] += m
            row_minutes += m
        row_total = round(row_minutes / 60, 2)
        grand_total += row_total
        if data['is_billable']:
            billable_total += row_total
        entries.append({
            'client_id':      data['client_id'],
            'client_name':    data['client_name'],
            'task_type_id':   data['task_type_id'],
            'task_type_name': data['task_type_name'],
            'is_billable':    data['is_billable'],
            'days':           day_hours,
            'total':          row_total,
        })
 
    entries.sort(key=lambda e: (not e['is_billable'], e['client_name'] or ''))
    daily_totals_hours = {d: round(m / 60, 2) for d, m in daily_totals.items()}
 
    # ── Block-level timeline ──────────────────────────────────────────────────
 
    blocks_qs = Block.objects.filter(
        user=ts_user,
        org=org,
        start__gte=start_utc,
        start__lte=end_utc,
        deleted_at__isnull=True,
    ).select_related('client', 'task_type').order_by('start')
 
    days_map = {d: [] for d in day_strings}
 
    for block in blocks_qs:
        if not block.start:
            continue
        day_str = localtime(block.start).date().isoformat()
        if day_str not in days_map:
            continue
 
        duration_minutes = 0
        if block.end and block.end > block.start:
            duration_minutes = int((block.end - block.start).total_seconds() // 60)
        elif block.minutes:
            duration_minutes = int(block.minutes)
 
        # Try ClassificationAudit for AI confidence — graceful fallback
        classification_source = None
        ai_confidence = None
        try:
            from tracker.models import ClassificationAudit
            audit = ClassificationAudit.objects.filter(
                block=block
            ).order_by('-created_at').first()
            if audit:
                classification_source = getattr(audit, 'source', None)
                raw_conf = getattr(audit, 'confidence', None)
                ai_confidence = float(raw_conf) if raw_conf is not None else None
        except Exception:
            pass
 
        days_map[day_str].append({
            'id':                    block.id,
            'started_at':            block.start.isoformat(),
            'ended_at':              block.end.isoformat() if block.end else None,
            'duration_minutes':      duration_minutes,
            'client_name':           block.client.name if block.client else None,
            'task_type_name':        block.task_type.name if block.task_type else None,
            'is_billable':           block.is_billable,
            'window_title':          getattr(block, 'window_title', None),
            'application':           getattr(block, 'application', None),
            'classification_source': classification_source,
            'ai_confidence':         ai_confidence,
            'taxpayer_name':         getattr(block, 'taxpayer_name', None),
        })
 
    days_list = [
        {
            'date':          d,
            'blocks':        days_map[d],
            'total_minutes': sum(b['duration_minutes'] for b in days_map[d]),
        }
        for d in day_strings
    ]
 
    return Response({
        'timesheet_id':    timesheet.id,
        'user_name':       f"{ts_user.first_name} {ts_user.last_name}".strip() or ts_user.username,
        'user_email':      ts_user.email,
        'week_start':      week_start.isoformat(),
        'week_end':        week_end.isoformat(),
        'status':          timesheet.status,
        'auto_submitted':  getattr(timesheet, 'auto_submitted', False),
        'submitted_at':    timesheet.submitted_at.isoformat() if timesheet.submitted_at else None,
        'submitted_notes': timesheet.submitted_notes or '',
        'rejection_reason': getattr(timesheet, 'rejection_reason', None) or '',
        'entries':         entries,
        'daily_totals':    daily_totals_hours,
        'grand_total':     round(grand_total, 2),
        'billable_total':  round(billable_total, 2),
        'days':            days_list,
    })
 

# ===============================
# APPROVAL QUEUE
# ===============================
@api_view(['GET'])
def approval_queue(request):
    org = get_request_org_override_billing(request)
    if not org:
        return Response({'error': 'No organization'}, status=400)

    # Staff bypass — no membership check needed
    if not (request.user.is_staff or request.user.is_superuser):
        membership = OrganizationMembership.objects.filter(
            user=request.user, organization=org
        ).first()
        if not membership or membership.role not in ('owner', 'admin', 'manager'):
            return Response({'error': 'Insufficient permissions'}, status=403)

    timesheets = Timesheet.objects.filter(
        org=org,
        status='submitted'
    ).select_related('user').order_by('submitted_at')

    result = []
    for ts in timesheets:
        blocks = Block.objects.filter(timesheet=ts)
        total_minutes    = sum(b.minutes or 0 for b in blocks)
        billable_minutes = sum(b.minutes or 0 for b in blocks if b.is_billable)
        total_amount     = sum(float(b.billing_amount or 0) for b in blocks if b.is_billable)
        days_pending = (timezone.now() - ts.submitted_at).days if ts.submitted_at else 0

        result.append({
            'id':             ts.id,
            'user_id':        ts.user_id,
            'user_name':      f"{ts.user.first_name} {ts.user.last_name}".strip() or ts.user.username,
            'user_email':     ts.user.email,
            'week_start':     ts.week_start.isoformat(),
            'week_end':       (ts.week_start + timedelta(days=6)).isoformat(),
            'status':         ts.status,
            'submitted_at':   ts.submitted_at.isoformat() if ts.submitted_at else None,
            'days_pending':   days_pending,
            'notes':          ts.submitted_notes or '',
            'total_hours':    round(total_minutes / 60, 2),
            'billable_hours': round(billable_minutes / 60, 2),
            'total_amount':   round(total_amount, 2),
            'auto_submitted': ts.auto_submitted,
        })

    return Response({'count': len(result), 'timesheets': result})


# ===============================
# WEEKLY TIMESHEET VIEW (EMPLOYEE)
# ===============================

# ── views_billing.py patch ────────────────────────────────────────────────────
#
# PROBLEM: weekly_timesheet_view sums block.minutes directly, causing
#          double-counting when blocks overlap (same clock time, different apps).
#
# FIX: Use union of time spans per client/task, same as today_time does.
#
# REPLACE your existing weekly_timesheet_view with this version:
# ─────────────────────────────────────────────────────────────────────────────

from datetime import timedelta, date
from decimal import Decimal
from collections import defaultdict


# ── CORRECTED weekly_timesheet_view ─────────────────────────────────────────
#
# The previous version had a units bug: _union_hours returns fractional hours
# correctly, but block.start/end timezone handling caused span inflation.
#
# This version uses a simpler, proven approach:
# - Use block.minutes (already compacted correctly by the agent)
# - Apply union logic on the TIME SPANS to avoid double-counting
# - Fall back to block.minutes sum if no start/end available
#
# REPLACE weekly_timesheet_view in views_billing.py with this:
# ─────────────────────────────────────────────────────────────────────────────

from collections import defaultdict
from decimal import Decimal
from datetime import timedelta, date
import datetime as dt_module
from django.utils.timezone import make_aware


def _union_minutes_from_blocks(block_list):
    """
    Given a list of Block objects, return the union of their time spans in MINUTES.
    Handles overlapping blocks by merging spans — no double-counting.
    Falls back to summing block.minutes if start/end not available.
    """
    spans = []
    for b in block_list:
        if b.start and b.end and b.end > b.start:
            spans.append((b.start, b.end))

    if not spans:
        # Fallback: sum minutes directly (may double-count but better than nothing)
        return sum(b.minutes or 0 for b in block_list)

    # Sort and merge overlapping spans
    spans.sort(key=lambda x: x[0])
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    total_seconds = sum((e - s).total_seconds() for s, e in merged)
    return round(total_seconds / 60, 2)  # Return MINUTES


# ── weekly_timesheet_view — event-based, matches today_time exactly ──────────
#
# Uses the same RAW EVENT logic as today_time:
# - Duration = time to next event, capped at 3 minutes
# - Client/category from the event's linked block
# - Aggregated by (client_id, task_type_id) per day
#
# Replace weekly_timesheet_view in views_billing.py with this:
# ─────────────────────────────────────────────────────────────────────────────

from django.utils.timezone import localtime, make_aware
import datetime as dt_module
from collections import defaultdict
from datetime import timezone as dt_timezone


IDLE_CAP_SECONDS = 180  # 3 min cap — matches today_time and agent


def _get_event_minutes_for_week(user, week_start, week_end):
    """
    Run today_time's event-based attribution across an entire week.
    Returns: dict of {(client_id, client_name, task_type_id, task_type_name, is_billable, day_str): minutes}
    """
    from tracker.models import RawEvent

    tz = timezone.get_current_timezone()
    start_local = timezone.make_aware(
        dt_module.datetime.combine(week_start, dt_module.time.min), tz
    )
    end_local = timezone.make_aware(
        dt_module.datetime.combine(week_end, dt_module.time.max), tz
    )
    start_utc = start_local.astimezone(dt_timezone.utc)
    end_utc   = end_local.astimezone(dt_timezone.utc)

    # Fetch all events for the week in one query
    events = list(RawEvent.objects.filter(
        user=user,
        start_ts__gte=start_utc,
        start_ts__lt=end_utc,
    ).select_related(
        'block', 'block__client', 'block__task_type'
    ).order_by('start_ts'))

    # Deleted block IDs
    deleted_block_ids = set(
        Block.objects.filter(user=user, deleted_at__isnull=False)
        .values_list('id', flat=True)
    )

    # Accumulate minutes per (client_id, task_type_id, day_str)
    # key: (client_id, client_name, task_type_id, task_type_name, is_billable, day_str)
    minute_map = defaultdict(float)

    for i, event in enumerate(events):
        # Duration capped at 3 min
        if i + 1 < len(events):
            gap = (events[i + 1].start_ts - event.start_ts).total_seconds()
            duration_min = min(gap, IDLE_CAP_SECONDS) / 60.0
        else:
            duration_min = 3.0

        block = event.block
        if block and block.id in deleted_block_ids:
            block = None

        if block and block.client_id:
            client_id   = block.client_id
            client_name = block.client.name if block.client else 'Unassigned'
            task_type_id   = block.task_type_id
            task_type_name = block.task_type.name if block.task_type else 'General'
            is_billable = block.is_billable
        else:
            client_id      = None
            client_name    = 'Unassigned'
            task_type_id   = None
            task_type_name = 'General'
            is_billable    = False

        day_str = localtime(event.start_ts).date().isoformat()

        key = (client_id, client_name, task_type_id, task_type_name, is_billable, day_str)
        minute_map[key] += duration_min

    return minute_map


# ── weekly_timesheet_view — event-based, matches today_time exactly ──────────
# Replace weekly_timesheet_view in views_billing.py with this entire function.
# Also ensure this import is at top of views_billing.py:
#   from django.utils.timezone import localtime
# ─────────────────────────────────────────────────────────────────────────────

import datetime as dt_module
from datetime import timezone as dt_timezone
from django.utils.timezone import localtime

IDLE_CAP_SECONDS = 180  # 3-min cap, matches today_time and agent


@api_view(['GET'])
def weekly_timesheet_view(request):
    """
    Event-based weekly timesheet. Matches Daily Review exactly.
    Mobile blocks merged separately (same as today_time Step 5).
    """
    org = get_request_org_override_billing(request)
    user = get_request_user_override_billing(request)

    if not org:
        return Response({'error': 'No organization'}, status=400)

    week_start_param = request.query_params.get('week_start')
    if week_start_param:
        try:
            week_start = date.fromisoformat(week_start_param)
        except ValueError:
            return Response({'error': 'Invalid date format'}, status=400)
    else:
        week_start = get_monday(timezone.now().date())

    week_start = get_monday(week_start)
    week_end   = week_start + timedelta(days=6)
    day_strings = [(week_start + timedelta(days=i)).isoformat() for i in range(7)]

    timesheet, _ = Timesheet.get_or_create_for_date(org, user, week_start)

    tz = timezone.get_current_timezone()
    start_local = timezone.make_aware(dt_module.datetime.combine(week_start, dt_module.time.min), tz)
    end_local   = timezone.make_aware(dt_module.datetime.combine(week_end, dt_module.time.max), tz)
    start_utc   = start_local.astimezone(dt_timezone.utc)
    end_utc     = end_local.astimezone(dt_timezone.utc)

    # ── Raw events for the week ───────────────────────────────────────────────
    from tracker.models import RawEvent
    events = list(RawEvent.objects.filter(
        user=user,
        start_ts__gte=start_utc,
        start_ts__lt=end_utc,
    ).select_related('block', 'block__client', 'block__task_type').order_by('start_ts'))

    deleted_block_ids = set(
        Block.objects.filter(user=user, deleted_at__isnull=False)
        .values_list('id', flat=True)
    )

    grid = {}
    day_first_ts = {}   # day_str -> earliest event epoch (presence envelope start)
    day_last_ts  = {}   # day_str -> latest event epoch (presence envelope end)

    # ── Event-based attribution (3-min cap) ───────────────────────────────────
    for i, event in enumerate(events):
        if i + 1 < len(events):
            gap = (events[i + 1].start_ts - event.start_ts).total_seconds()
            duration_min = min(gap, IDLE_CAP_SECONDS) / 60.0
        else:
            duration_min = 3.0

        block = event.block
        if block and block.id in deleted_block_ids:
            block = None

        if block and block.client_id:
            client_id      = block.client_id
            client_name    = block.client.name if block.client else 'Unassigned'
            task_type_id   = block.task_type_id
            task_type_name = block.task_type.name if block.task_type else 'General'
            is_billable    = block.is_billable
        else:
            client_id = None; client_name = 'Unassigned'
            task_type_id = None; task_type_name = 'General'; is_billable = False

        day_str = localtime(event.start_ts).date().isoformat()
        if day_str not in day_strings:
            continue

        # Presence envelope: first→last event timestamp per day (wall-clock span).
        # Active minutes (below) already cap idle gaps at 3 min; the gap between
        # this span and the summed active time is the day's Idle/Away.
        ev_ts = event.start_ts.timestamp()
        if day_str not in day_first_ts or ev_ts < day_first_ts[day_str]:
            day_first_ts[day_str] = ev_ts
        if day_str not in day_last_ts or ev_ts > day_last_ts[day_str]:
            day_last_ts[day_str] = ev_ts

        key = (client_id, task_type_id)
        if key not in grid:
            grid[key] = {
                'client_id': client_id, 'client_name': client_name,
                'task_type_id': task_type_id, 'task_type_name': task_type_name,
                'is_billable': is_billable,
                'day_minutes': {d: 0.0 for d in day_strings},
            }
        grid[key]['day_minutes'][day_str] += duration_min

    # ── Mobile blocks (no raw events) ────────────────────────────────────────
    for block in Block.objects.filter(
        user=user, org=org, hostname='mobile',
        start__gte=start_utc, start__lte=end_utc,
        is_categorized=True, client__isnull=False, deleted_at__isnull=True,
    ).select_related('client', 'task_type'):
        day_str = localtime(block.start).date().isoformat()
        if day_str not in day_strings:
            continue
        key = (block.client_id, block.task_type_id)
        minutes = float(block.minutes or 0)
        if key not in grid:
            grid[key] = {
                'client_id': block.client_id,
                'client_name': block.client.name,
                'task_type_id': block.task_type_id,
                'task_type_name': block.task_type.name if block.task_type else 'General',
                'is_billable': block.is_billable,
                'day_minutes': {d: 0.0 for d in day_strings},
            }
        grid[key]['day_minutes'][day_str] += minutes

    # ── Build response ────────────────────────────────────────────────────────
    grid_entries = []
    for data in grid.values():
        day_hours = {}
        row_minutes = 0.0
        for day_str in day_strings:
            m = data['day_minutes'][day_str]
            day_hours[day_str] = round(m / 60, 2)
            row_minutes += m
        grid_entries.append({
            'client_id': data['client_id'], 'client_name': data['client_name'],
            'task_type_id': data['task_type_id'], 'task_type_name': data['task_type_name'],
            'is_billable': data['is_billable'],
            'days': day_hours, 'total': round(row_minutes / 60, 2),
        })

    grid_entries.sort(key=lambda e: (not e['is_billable'], e['client_name'] or ''))

    daily_totals = {d: 0.0 for d in day_strings}
    for data in grid.values():
        for d, m in data['day_minutes'].items():
            daily_totals[d] += m

    daily_totals_hours = {d: round(m / 60, 2) for d, m in daily_totals.items()}
    grand_total    = round(sum(daily_totals_hours.values()), 2)
    billable_total = round(sum(e['total'] for e in grid_entries if e['is_billable']), 2)

    # ── Presence envelope + Idle/Away ─────────────────────────────────────────
    # Present = wall-clock span from first to last activity that day (attendance).
    # Active  = daily_totals (summed active minutes, idle gaps capped at 3 min).
    # Idle/Away = the difference: lunch, breaks, meetings away from the keyboard.
    # Present is NOT summed Mon→Fri as one span; each day's envelope is measured
    # then summed, so a normal 8h day reads as ~8h present / ~5-7h active.
    daily_presence = {}
    daily_idle     = {}
    for d in day_strings:
        if d in day_first_ts:
            present_min = max(0.0, (day_last_ts[d] - day_first_ts[d]) / 60.0)
        else:
            present_min = 0.0
        active_min = daily_totals[d]            # minutes
        idle_min   = max(0.0, present_min - active_min)
        daily_presence[d] = round(present_min / 60.0, 2)
        daily_idle[d]     = round(idle_min / 60.0, 2)

    present_total = round(sum(daily_presence.values()), 2)
    idle_total    = round(sum(daily_idle.values()), 2)

    return Response({
        'week_start': week_start.isoformat(), 'week_end': week_end.isoformat(),
        'timesheet_id': timesheet.id, 'status': timesheet.status,
        'auto_submitted': timesheet.auto_submitted,
        'submitted_at': timesheet.submitted_at.isoformat() if timesheet.submitted_at else None,
        'rejection_reason': timesheet.rejection_reason or '',
        'entries': grid_entries, 'daily_totals': daily_totals_hours,
        'grand_total': grand_total, 'billable_total': billable_total,
        'daily_presence': daily_presence, 'daily_idle': daily_idle,
        'present_total': present_total, 'idle_total': idle_total,
    })
# ===============================
# CLIENT SUMMARY VIEW (MANAGER/BILLING)
# ===============================

@api_view(['GET'])
def client_summary_view(request):
    """
    Manager/billing view - hours and amounts by client.
    Used for invoicing.
    """
    org = get_request_org_override_billing(request)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
    # Date range
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    
    if not start_date or not end_date:
        # Default to current month
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    else:
        start_date = date.fromisoformat(start_date)
        end_date = date.fromisoformat(end_date)
    
    # Filter options
    client_id = request.query_params.get('client_id')
    user_id = request.query_params.get('user_id')
    only_approved = request.query_params.get('only_approved', 'true').lower() == 'true'
    only_billable = request.query_params.get('only_billable', 'false').lower() == 'true'
    
    # Base query
    blocks = Block.objects.filter(
        org=org,
        day__gte=start_date,
        day__lte=end_date,
    ).select_related('client', 'user', 'task_type')
    
    if client_id:
        blocks = blocks.filter(client_id=client_id)
    if user_id:
        blocks = blocks.filter(user_id=user_id)
    if only_approved:
        blocks = blocks.filter(approved=True)
    if only_billable:
        blocks = blocks.filter(is_billable=True)
    
    # Aggregate by client
    client_data = blocks.values('client_id', 'client__name', 'client__code').annotate(
        total_minutes=Sum('minutes'),
        billable_minutes=Sum('minutes', filter=Q(is_billable=True)),
        total_amount=Coalesce(Sum('billing_amount'), Decimal('0')),
    ).order_by('client__name')
    
    results = []
    for item in client_data:
        # Get staff breakdown
        staff = blocks.filter(client_id=item['client_id']).values(
            'user_id', 'user__username'
        ).annotate(
            hours=Sum('minutes'),
            amount=Sum('billing_amount'),
        ).order_by('user__username')
        
        # Get task breakdown
        tasks = blocks.filter(client_id=item['client_id']).values(
            'task_type_id', 'task_type__name'
        ).annotate(
            hours=Sum('minutes'),
            amount=Sum('billing_amount'),
        ).order_by('task_type__name')
        
        results.append({
            'client_id': item['client_id'],
            'client_name': item['client__name'] or 'Unassigned',
            'client_code': item['client__code'] or '',
            'total_hours': round(Decimal(item['total_minutes'] or 0) / 60, 2),
            'billable_hours': round(Decimal(item['billable_minutes'] or 0) / 60, 2),
            'non_billable_hours': round(Decimal((item['total_minutes'] or 0) - (item['billable_minutes'] or 0)) / 60, 2),
            'total_amount': item['total_amount'],
            'staff_breakdown': [
                {
                    'user_id': s['user_id'],
                    'username': s['user__username'],
                    'hours': round(Decimal(s['hours'] or 0) / 60, 2),
                    'amount': s['amount'] or Decimal('0'),
                }
                for s in staff
            ],
            'task_breakdown': [
                {
                    'task_type_id': t['task_type_id'],
                    'task_type': t['task_type__name'] or 'General',
                    'hours': round(Decimal(t['hours'] or 0) / 60, 2),
                    'amount': t['amount'] or Decimal('0'),
                }
                for t in tasks
            ],
        })
    
    return Response({
        'period_start': start_date.isoformat(),
        'period_end': end_date.isoformat(),
        'clients': results,
        'totals': {
            'total_hours': sum(r['total_hours'] for r in results),
            'billable_hours': sum(r['billable_hours'] for r in results),
            'total_amount': sum(r['total_amount'] for r in results),
        }
    })


# ===============================
# INVOICE EXPORT
# ===============================

@api_view(['GET'])
def invoice_export(request, client_id):
    """
    Generate invoice data for a client.
    Returns JSON that can be used to create PDF or send to QuickBooks.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
    client = get_object_or_404(Client, id=client_id, org=org)
    
    # Date range
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    
    if not start_date or not end_date:
        return Response({'error': 'start_date and end_date required'}, status=400)
    
    start_date = date.fromisoformat(start_date)
    end_date = date.fromisoformat(end_date)
    
    # Get approved, billable, non-invoiced blocks
    blocks = Block.objects.filter(
        org=org,
        client=client,
        day__gte=start_date,
        day__lte=end_date,
        approved=True,
        is_billable=True,
        invoiced=False,
    ).select_related('user', 'task_type').order_by('day', 'start')
    
    # Generate line items
    line_items = []
    for block in blocks:
        hours = Decimal(block.minutes or 0) / 60
        rate = block.billing_rate or org.billing_rate_default
        amount = hours * rate
        
        # Get initials
        user = block.user
        initials = ''.join(n[0].upper() for n in user.get_full_name().split() if n) or user.username[:2].upper()
        
        # Description
        description = block.description_override
        if not description:
            parts = []
            if block.task_type:
                parts.append(block.task_type.name)
            if block.notes:
                parts.append(block.notes)
            if not parts:
                parts.append('Professional services')
            description = ' - '.join(parts)
        
        line_items.append({
            'block_id': block.id,
            'date': block.day.isoformat(),
            'description': description,
            'hours': round(hours, 2),
            'rate': rate,
            'amount': round(amount, 2),
            'staff_initials': initials,
            'task_type': block.task_type.name if block.task_type else None,
        })
    
    # Calculate totals
    subtotal_hours = sum(item['hours'] for item in line_items)
    subtotal_amount = sum(item['amount'] for item in line_items)
    
    # Tax (if applicable - would come from client or org settings)
    tax_rate = Decimal('0')  # TODO: Get from client settings
    tax_amount = subtotal_amount * tax_rate
    total_amount = subtotal_amount + tax_amount
    
    return Response({
        'client_id': client.id,
        'client_name': client.name,
        'client_code': client.code,
        
        'invoice_date': timezone.now().date().isoformat(),
        'period_start': start_date.isoformat(),
        'period_end': end_date.isoformat(),
        
        'line_items': line_items,
        
        'subtotal_hours': round(subtotal_hours, 2),
        'subtotal_amount': round(subtotal_amount, 2),
        
        'tax_rate': tax_rate,
        'tax_amount': round(tax_amount, 2),
        'total_amount': round(total_amount, 2),
        
        'block_ids': [item['block_id'] for item in line_items],
    })


@api_view(['POST'])
def mark_invoiced(request):
    """
    Mark blocks as invoiced after invoice is created.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
    block_ids = request.data.get('block_ids', [])
    invoice_reference = request.data.get('invoice_reference', '')
    override = request.data.get('override_mismatches', False)

    if not block_ids:
        return Response({'error': 'block_ids required'}, status=400)

    # Pre-invoice mismatch gate (non-blocking review). Unless the caller has
    # acknowledged with override_mismatches=true, refuse to bill blocks whose
    # window title names a different client than they're booked to. Same
    # detector as the nightly scan.
    # v1.4.1: DETECTION-ONLY until the billing UI handles the 409 review prompt.
    # Log mismatches and record them, but DO NOT block the invoice — the
    # frontend has no handler yet, so a hard 409 would dead-end billing. Flip
    # back to blocking (restore the 409 return) once the UI is built.
    if not override:
        from tracker.services.mismatch_scan import check_invoice_mismatches
        mismatches = check_invoice_mismatches(org, block_ids)
        if mismatches:
            import logging
            logging.getLogger(__name__).warning(
                f"[MARK-INVOICED] {len(mismatches)} mismatch(es) on invoice for "
                f"org {org.id}, blocks {[m['block_id'] for m in mismatches]} — "
                f"logged, NOT blocked (UI handler pending)"
            )

    updated = Block.objects.filter(
        id__in=block_ids,
        org=org,
        approved=True,
        invoiced=False,
    ).update(
        invoiced=True,
        invoiced_at=timezone.now(),
        invoice_reference=invoice_reference,
    )

    # If billed over an acknowledged mismatch, record it on the flags for audit.
    if override:
        from tracker.models import MismatchFlag
        MismatchFlag.objects.filter(
            block_id__in=block_ids,
            org=org,
            resolved_at__isnull=True,
        ).update(
            resolved_at=timezone.now(),
            resolved_reason='invoiced_anyway',
        )

    return Response({
        'updated': updated,
        'block_ids': block_ids,
        'invoice_reference': invoice_reference,
    })


# ===============================
# AUDIT LOG
# ===============================

@api_view(['GET'])
def block_audit_history(request, block_id):
    """Get audit history for a specific block"""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
    block = get_object_or_404(Block, id=block_id, org=org)
    logs = block.audit_logs.all().select_related('user')
    
    return Response(BlockAuditLogSerializer(logs, many=True).data)


# ===============================
# BLOCK BILLING UPDATES
# ===============================

@api_view(['PATCH'])
def update_block_billing(request, block_id):
    """
    Update billing-related fields on a block.
    - is_billable
    - billing_rate
    - description_override
    - client
    - task_type
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
    block = get_object_or_404(Block, id=block_id, org=org)
    
    # Check permissions
    if block.approved or block.invoiced:
        return Response({'error': 'Cannot modify approved/invoiced blocks'}, status=400)
    
    # Track changes for audit
    changes = {}
    
    if 'is_billable' in request.data:
        old_val = block.is_billable
        block.is_billable = request.data['is_billable']
        if old_val != block.is_billable:
            changes['is_billable'] = (old_val, block.is_billable)
    
    if 'billing_rate' in request.data:
        old_val = block.billing_rate
        block.billing_rate = Decimal(str(request.data['billing_rate']))
        if old_val != block.billing_rate:
            changes['billing_rate'] = (str(old_val), str(block.billing_rate))
    
    if 'description_override' in request.data:
        old_val = block.description_override
        block.description_override = request.data['description_override']
        if old_val != block.description_override:
            changes['description_override'] = (old_val, block.description_override)
    
    if 'client_id' in request.data:
        old_val = block.client_id
        block.client_id = request.data['client_id']
        if old_val != block.client_id:
            changes['client'] = (old_val, block.client_id)
    
    if 'task_type_id' in request.data:
        old_val = block.task_type_id
        block.task_type_id = request.data['task_type_id']
        if old_val != block.task_type_id:
            changes['task_type'] = (old_val, block.task_type_id)
    
    # Recalculate billing amount
    if block.is_billable and block.billing_rate and block.minutes:
        block.billing_amount = (Decimal(block.minutes) / 60) * block.billing_rate
    else:
        block.billing_amount = Decimal('0')
    
    block.save(force_update=True)  # Skip protected check for billing fields
    
    # Create audit log
    for field, (old, new) in changes.items():
        BlockAuditLog.objects.create(
            block=block,
            action='update',
            user=request.user,
            field_name=field,
            old_value=str(old) if old is not None else '',
            new_value=str(new) if new is not None else '',
        )
    
    return Response({
        'id': block.id,
        'is_billable': block.is_billable,
        'billing_rate': str(block.billing_rate) if block.billing_rate else None,
        'billing_amount': str(block.billing_amount) if block.billing_amount else None,
        'description_override': block.description_override,
    })


from decimal import Decimal
from django.db.models import Sum, F, Q
from django.db.models.functions import Coalesce

# ============================================================================
# REPLACE the EmployeeCostRate views in views_billing.py with these:
# ============================================================================

# Replace EmployeeCostRateListView in views_billing.py with this:

from django.db import IntegrityError

from django.db import IntegrityError

# Replace EmployeeCostRateListView and EmployeeCostRateDetailView in views_billing.py with this:
# Note: The model field is `cost_rate` (not hourly_cost)

from django.db import IntegrityError

# ===============================
# EMPLOYEE COST RATES (Professional Plan Only)
# ===============================
class EmployeeCostRateListView(RequireExecutivePlanMixin, APIView):
    """
    GET: List all employee cost rates for the org
    POST: Create a new cost rate (or return conflict if duplicate)
    RESTRICTED TO: Professional and Enterprise plans.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization found'}, status=404)
        
        rates = EmployeeCostRate.objects.filter(organization=org).select_related('user')
        
        result = []
        for rate in rates:
            result.append({
                'id': rate.id,
                'user': rate.user.id,
                'user_name': rate.user.username,
                'user_email': rate.user.email or '',
                'cost_rate': str(rate.cost_rate),
                'effective_date': safe_date(rate.effective_date),
            })
        
        return Response(result)
    
    def post(self, request):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization found'}, status=404)
        
        user_id = request.data.get('user')
        cost_rate = request.data.get('cost_rate')
        effective_date = request.data.get('effective_date')
        
        if not user_id:
            return Response({'error': 'User is required'}, status=400)
        if not cost_rate:
            return Response({'error': 'Cost rate is required'}, status=400)
        
        # Check if a rate already exists for this user + date
        existing = EmployeeCostRate.objects.filter(
            organization=org,
            user_id=user_id,
            effective_date=effective_date
        ).first()
        
        if existing:
            return Response({
                'error': 'duplicate',
                'message': f'A cost rate already exists for this employee on {effective_date}',
                'existing_rate': {
                    'id': existing.id,
                    'cost_rate': str(existing.cost_rate),
                    'effective_date': safe_date(existing.effective_date),
                },
                'hint': 'Use PATCH /api/billing/cost-rates/{id}/ to update, or choose a different effective date'
            }, status=409)
        
        try:
            rate = EmployeeCostRate.objects.create(
                organization=org,
                user_id=user_id,
                cost_rate=Decimal(str(cost_rate)),
                effective_date=effective_date or None,
            )
            
            return Response({
                'id': rate.id,
                'user': rate.user.id,
                'user_name': rate.user.username,
                'cost_rate': str(rate.cost_rate),
                'effective_date': safe_date(rate.effective_date),
            }, status=201)
            
        except IntegrityError:
            return Response({
                'error': 'duplicate',
                'message': 'A cost rate already exists for this employee on this date',
            }, status=409)

class EmployeeCostRateDetailView(RequireExecutivePlanMixin, APIView):
    """
    GET: Get a specific cost rate
    PUT/PATCH: Update a cost rate
    DELETE: Delete a cost rate
    RESTRICTED TO: Professional and Enterprise plans.
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, pk, org):
        try:
            return EmployeeCostRate.objects.get(id=pk, organization=org)
        except EmployeeCostRate.DoesNotExist:
            return None
    
    def get(self, request, pk):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization found'}, status=404)
        
        rate = self.get_object(pk, org)
        if not rate:
            return Response({'error': 'Cost rate not found'}, status=404)
        
        return Response({
            'id': rate.id,
            'user': rate.user.id,
            'user_name': rate.user.username,
            'cost_rate': str(rate.cost_rate),
            'effective_date': safe_date(rate.effective_date),
        })
    
    def put(self, request, pk):
        return self.patch(request, pk)
    
    def patch(self, request, pk):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization found'}, status=404)
        
        rate = self.get_object(pk, org)
        if not rate:
            return Response({'error': 'Cost rate not found'}, status=404)
        
        cost_rate = request.data.get('cost_rate') or request.data.get('hourly_cost')
        if cost_rate:
            rate.cost_rate = Decimal(str(cost_rate))
        if 'effective_date' in request.data:
            rate.effective_date = request.data['effective_date']
        
        try:
            rate.save()
        except IntegrityError:
            return Response({
                'error': 'duplicate',
                'message': 'A cost rate already exists for this employee on this date',
            }, status=409)
        
        return Response({
            'id': rate.id,
            'user': rate.user.id,
            'user_name': rate.user.username,
            'cost_rate': str(rate.cost_rate),
            'effective_date': safe_date(rate.effective_date),
        })
    
    def delete(self, request, pk):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization found'}, status=404)
        
        rate = self.get_object(pk, org)
        if not rate:
            return Response({'error': 'Cost rate not found'}, status=404)
        
        rate_id = rate.id
        rate.delete()
        
        return Response({
            'success': True,
            'message': f'Cost rate {rate_id} deleted',
        })


## ===============================
# PROFITABILITY REPORT (Professional Plan Only)
# ===============================
class ProfitabilityReportView(RequireExecutivePlanMixin, APIView):
    """
    GET: Calculate profit margins by client
    
    Query params:
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - only_approved: true/false
    
    RESTRICTED TO: Professional and Enterprise plans.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization'}, status=400)
        
        # Check permission
        membership = OrganizationMembership.objects.filter(
            user=request.user, organization=org
        ).first()
        
        if not membership or membership.role not in ['owner', 'admin', 'manager']:
            return Response({'error': 'Permission denied'}, status=403)
        
        # Parse date range
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        only_approved = request.query_params.get('only_approved', 'true').lower() == 'true'
        
        if not start_date or not end_date:
            return Response({'error': 'start_date and end_date required'}, status=400)
        
        blocks = Block.objects.filter(
            org=org,
            day__gte=start_date,
            day__lte=end_date,
            is_billable=True,
        )
        
        if only_approved:
            blocks = blocks.filter(
                Q(timesheet__status__in=['approved', 'locked']) | 
                Q(timesheet__isnull=True)
            )
        
        # Get all cost rates for the org (most recent per user)
        cost_rates = {}
        try:
            for rate in EmployeeCostRate.objects.filter(
                organization=org,
                effective_date__lte=end_date
            ).select_related('user').order_by('user_id', '-effective_date'):
                if rate.user_id not in cost_rates:
                    cost_rates[rate.user_id] = rate.cost_rate
        except Exception:
            pass
        
        default_cost_rate = Decimal('50.00')
        
        clients_data = {}
        totals = {
            'total_hours': Decimal('0'),
            'billable_hours': Decimal('0'),
            'total_revenue': Decimal('0'),
            'total_cost': Decimal('0'),
        }
        
        for block in blocks.select_related('client', 'user'):
            client_id = block.client_id or 0
            client_name = block.client.name if block.client else 'No Client'
            client_code = getattr(block.client, 'code', '') if block.client else ''
            
            user_id = block.user_id
            user_name = f"{block.user.first_name} {block.user.last_name}".strip() or block.user.username
            
            if block.minutes:
                hours = Decimal(str(block.minutes)) / Decimal('60')
            else:
                hours = Decimal('0')
            
            billing_rate = Decimal(str(block.billing_rate)) if block.billing_rate else Decimal('0')
            cost_rate = cost_rates.get(user_id, default_cost_rate)
            
            revenue = hours * billing_rate
            cost = hours * cost_rate
            
            if client_id not in clients_data:
                clients_data[client_id] = {
                    'client_id': client_id,
                    'client_name': client_name,
                    'client_code': client_code,
                    'total_hours': Decimal('0'),
                    'billable_hours': Decimal('0'),
                    'total_revenue': Decimal('0'),
                    'total_cost': Decimal('0'),
                    'staff': {}
                }
            
            if user_id not in clients_data[client_id]['staff']:
                clients_data[client_id]['staff'][user_id] = {
                    'user_id': user_id,
                    'user_name': user_name,
                    'hours': Decimal('0'),
                    'billing_rate': float(billing_rate),
                    'cost_rate': float(cost_rate),
                    'revenue': Decimal('0'),
                    'cost': Decimal('0'),
                }
            
            clients_data[client_id]['total_hours'] += hours
            clients_data[client_id]['billable_hours'] += hours
            clients_data[client_id]['total_revenue'] += revenue
            clients_data[client_id]['total_cost'] += cost
            
            clients_data[client_id]['staff'][user_id]['hours'] += hours
            clients_data[client_id]['staff'][user_id]['revenue'] += revenue
            clients_data[client_id]['staff'][user_id]['cost'] += cost
            
            totals['total_hours'] += hours
            totals['billable_hours'] += hours
            totals['total_revenue'] += revenue
            totals['total_cost'] += cost
        
        clients_list = []
        for client_id, client in clients_data.items():
            gross_margin = client['total_revenue'] - client['total_cost']
            margin_percent = (
                float(gross_margin / client['total_revenue'] * 100)
                if client['total_revenue'] > 0 else 0
            )
            
            staff_details = []
            for user_id, staff in client['staff'].items():
                staff_margin = staff['revenue'] - staff['cost']
                staff_margin_pct = (
                    float(staff_margin / staff['revenue'] * 100)
                    if staff['revenue'] > 0 else 0
                )
                staff_details.append({
                    'user_id': user_id,
                    'user_name': staff['user_name'],
                    'hours': float(staff['hours']),
                    'billing_rate': staff['billing_rate'],
                    'cost_rate': staff['cost_rate'],
                    'revenue': float(staff['revenue']),
                    'cost': float(staff['cost']),
                    'margin': float(staff_margin),
                    'margin_percent': float(staff_margin_pct),
                })
            
            clients_list.append({
                'client_id': client_id,
                'client_name': client['client_name'],
                'client_code': client['client_code'],
                'total_hours': float(client['total_hours']),
                'billable_hours': float(client['billable_hours']),
                'total_revenue': float(client['total_revenue']),
                'total_cost': float(client['total_cost']),
                'gross_margin': float(gross_margin),
                'margin_percent': margin_percent,
                'staff_details': staff_details,
            })
        
        clients_list.sort(key=lambda x: x['total_revenue'], reverse=True)
        
        total_margin = totals['total_revenue'] - totals['total_cost']
        total_margin_pct = (
            float(total_margin / totals['total_revenue'] * 100)
            if totals['total_revenue'] > 0 else 0
        )
        
        return Response({
            'period_start': start_date,
            'period_end': end_date,
            'clients': clients_list,
            'totals': {
                'total_hours': float(totals['total_hours']),
                'billable_hours': float(totals['billable_hours']),
                'total_revenue': float(totals['total_revenue']),
                'total_cost': float(totals['total_cost']),
                'gross_margin': float(total_margin),
                'margin_percent': total_margin_pct,
            }
        })

# ============================================================================
# CORRECTED VIEWS - Replace these in views_billing.py
# Your models use: 'org' (not 'organization'), 'submitted_notes' (not 'notes')
# ============================================================================

"""
Updated TimesheetSubmitView with Option A validation:
- Users can only submit a timesheet AFTER the week has ended
- Prevents the "where does Saturday go?" problem
"""

from datetime import date, timedelta
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone


class TimesheetSubmitView(APIView):
    """POST /api/billing/timesheets/<id>/submit/"""
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        return OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
    
    def post(self, request, pk):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        timesheet = get_object_or_404(
            Timesheet,
            pk=pk,
            org=membership.organization,
            user=request.user
        )
        
        # Submission is allowed on any day of the week (the UI shows a confirm
        # dialog with an "early submit" heads-up). Previously gated to after the
        # week ended (OPTION A) — removed per product request.
        week_end = timesheet.week_start + timedelta(days=6)  # Sunday

        # Allow both draft AND rejected status
        if timesheet.status not in ['draft', 'rejected']:
            return Response({
                'error': f'Cannot submit timesheet with status "{timesheet.status}".'
            }, status=400)
        
        # Link blocks to timesheet BEFORE submitting
        blocks_updated = Block.objects.filter(
            user=request.user,
            org=membership.organization,
            start__date__gte=timesheet.week_start,
            start__date__lte=week_end,
        ).update(timesheet=timesheet)
        
        # If reopening from rejected, reset to draft first
        if timesheet.status == 'rejected':
            timesheet.status = 'draft'
            timesheet.rejection_reason = ''
            timesheet.rejected_at = None
            timesheet.rejected_by = None
            timesheet.save()
        
        # Use model method - this recalculates totals and sets status
        notes = request.data.get('notes', '')
        timesheet.submit(notes=notes)
        
        return Response({
            'id': timesheet.id,
            'status': timesheet.status,
            'blocks_linked': blocks_updated,
            'total_hours': float(timesheet.total_hours),
            'billable_hours': float(timesheet.billable_hours),
            'total_amount': float(timesheet.total_amount),
            'submitted_at': timesheet.submitted_at.isoformat() if timesheet.submitted_at else None,
        })


class TimesheetApproveView(APIView):
    """POST /api/billing/timesheets/<id>/approve/"""
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        return OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
    
    def post(self, request, pk):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        if membership.role not in ['owner', 'admin', 'manager']:
            return Response({'error': 'Permission denied'}, status=403)
        
        timesheet = get_object_or_404(
            Timesheet,
            pk=pk,
            org=membership.organization
        )
        
        if timesheet.status != 'submitted':
            return Response({
                'error': f'Cannot approve timesheet with status "{timesheet.status}".'
            }, status=400)
        
        # Use model method - this marks blocks as approved and updates status
        notes = request.data.get('notes', '')
        timesheet.approve(approved_by=request.user, notes=notes)
        
        return Response({
            'id': timesheet.id,
            'status': timesheet.status,
            'approved_at': timesheet.approved_at.isoformat(),
            'approved_by': request.user.username,
            'total_hours': float(timesheet.total_hours),
            'billable_hours': float(timesheet.billable_hours),
            'total_amount': float(timesheet.total_amount),
        })


class TimesheetRejectView(APIView):
    """POST /api/billing/timesheets/<id>/reject/"""
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        return OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
    
    def post(self, request, pk):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        if membership.role not in ['owner', 'admin', 'manager']:
            return Response({'error': 'Permission denied'}, status=403)
        
        timesheet = get_object_or_404(
            Timesheet,
            pk=pk,
            org=membership.organization
        )
        
        if timesheet.status != 'submitted':
            return Response({
                'error': f'Cannot reject timesheet with status "{timesheet.status}".'
            }, status=400)
        
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'error': 'Rejection reason is required'}, status=400)
        
        # Use model method
        timesheet.reject(rejected_by=request.user, reason=reason)
        
        # Unlink blocks so they can be edited
        Block.objects.filter(timesheet=timesheet).update(timesheet=None)
        
        return Response({
            'id': timesheet.id,
            'status': timesheet.status,
            'rejection_reason': timesheet.rejection_reason,
            'rejected_by': request.user.username,
        })


class TimesheetReopenView(APIView):
    """POST /api/billing/timesheets/<id>/reopen/"""
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        return OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
    
    def post(self, request, pk):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        timesheet = get_object_or_404(
            Timesheet,
            pk=pk,
            org=membership.organization,
            user=request.user
        )
        
        if timesheet.status != 'rejected':
            return Response({
                'error': f'Cannot reopen timesheet with status "{timesheet.status}".'
            }, status=400)
        
        # Use model method
        timesheet.reopen()
        
        return Response({
            'id': timesheet.id,
            'status': timesheet.status,
        })


class TimesheetLockView(APIView):
    """POST /api/billing/timesheets/<id>/lock/ - Lock after invoicing"""
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        return OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
    
    def post(self, request, pk):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        if membership.role not in ['owner', 'admin']:
            return Response({'error': 'Permission denied'}, status=403)
        
        timesheet = get_object_or_404(
            Timesheet,
            pk=pk,
            org=membership.organization
        )
        
        if timesheet.status != 'approved':
            return Response({
                'error': f'Cannot lock timesheet with status "{timesheet.status}". Must be approved first.'
            }, status=400)
        
        # Use model method - this locks blocks too
        timesheet.lock()
        
        return Response({
            'id': timesheet.id,
            'status': timesheet.status,
        })


from datetime import date, datetime
 
 
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def timesheet_history(request):
    # ── Admin impersonation override ──
    override_id = request.GET.get("org_id")
    if override_id and (request.user.is_staff or request.user.is_superuser):
        try:
            org = Organization.objects.get(id=int(override_id))
        except (Organization.DoesNotExist, ValueError):
            return Response({"error": "Org not found"}, status=404)
    else:
        membership = OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
        if not membership:
            return Response({"error": "No organization found"}, status=404)
        org = membership.organization
 
    # ── Date range filter ─────────────────────────────────────────────────────
    start_date_str = request.GET.get('start_date')
    end_date_str   = request.GET.get('end_date')
 
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
    except ValueError:
        start_date = None
 
    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        end_date = None
 
    # ── Base queryset — approved timesheets for this org ──────────────────────
    qs = Timesheet.objects.filter(
        org=org,
        status__in=['approved', 'locked'],
    ).select_related('user', 'approved_by').order_by('-week_start')
 
    # Apply date filters — filter on week_start so a timesheet shows up
    # whenever its week starts within the selected range.
    if start_date:
        qs = qs.filter(week_start__gte=start_date)
    if end_date:
        qs = qs.filter(week_start__lte=end_date)
 
    # ── Serialize ─────────────────────────────────────────────────────────────
    timesheets = []
    for ts in qs:
        timesheets.append({
            'id':                    ts.id,
            'user_id':               ts.user.id,
            'user_username':         ts.user.username,
            'user_email':            ts.user.email,
            'user_first_name':       ts.user.first_name,
            'user_last_name':        ts.user.last_name,
            'week_start':            str(ts.week_start),
            'week_end':              str(ts.week_start + timedelta(days=6)),
            'status':                ts.status,
            'total_hours':           float(ts.total_hours or 0),
            'billable_hours':        float(ts.billable_hours or 0),
            'total_amount':          str(ts.total_amount or '0.00'),
            'auto_submitted':        ts.auto_submitted,
            'submitted_at':          ts.submitted_at.isoformat() if ts.submitted_at else None,
            'approved_at':           ts.approved_at.isoformat() if ts.approved_at else None,
            'approved_by_id':        ts.approved_by_id,
            'approved_by_username':  ts.approved_by.username if ts.approved_by else None,
        })
 
    # ── Summary — computed over the FILTERED set ──────────────────────────────
    total_hours    = sum(t['total_hours']    for t in timesheets)
    billable_hours = sum(t['billable_hours'] for t in timesheets)
    total_amount   = sum(float(t['total_amount']) for t in timesheets)
 
    return Response({
        'timesheets': timesheets,
        'summary': {
            'total_timesheets':    len(timesheets),
            'total_hours':         total_hours,
            'billable_hours':      billable_hours,
            'total_amount':        f'{total_amount:.2f}',
            'auto_submitted_count': sum(1 for t in timesheets if t['auto_submitted']),
        },
        # Echo back the active date range so the frontend can verify
        'date_range': {
            'start': str(start_date) if start_date else None,
            'end':   str(end_date)   if end_date   else None,
        },
    })


# Add these to tracker/views_billing.py

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def billing_rates_list(request):
    """
    GET: List all billing rates for the org
    POST: Create a new billing rate
    """
    from decimal import Decimal
    from tracker.models import BillingRate, Client
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    if request.method == 'GET':
        rates = BillingRate.objects.filter(org=org).select_related('user', 'client')
        result = []
        for rate in rates:
            result.append({
                'id': rate.id,
                'user': rate.user_id,
                'user_name': f"{rate.user.first_name} {rate.user.last_name}".strip() or rate.user.username if rate.user else None,
                'client': rate.client_id,
                'client_name': rate.client.name if rate.client else None,
                'rate': str(rate.rate),
                'effective_date': rate.effective_date.isoformat() if hasattr(rate, 'effective_date') and rate.effective_date else None,
                'end_date': rate.end_date.isoformat() if hasattr(rate, 'end_date') and rate.end_date else None,
            })
        return Response(result)
    
    elif request.method == 'POST':
        data = request.data
        
        # Get user if specified
        user = None
        if data.get('user_id'):
            user = User.objects.filter(id=data['user_id']).first()
        
        # Get client if specified
        client = None
        if data.get('client_id'):
            client = Client.objects.filter(id=data['client_id'], org=org).first()
        
        # Create the rate
        rate = BillingRate.objects.create(
            org=org,
            user=user,
            client=client,
            rate=Decimal(str(data.get('rate', '150.00'))),
            effective_date=data.get('effective_date'),
        )
        
        return Response({
            'id': rate.id,
            'user': rate.user_id,
            'user_name': f"{rate.user.first_name} {rate.user.last_name}".strip() or rate.user.username if rate.user else None,
            'client': rate.client_id,
            'client_name': rate.client.name if rate.client else None,
            'rate': str(rate.rate),
            'effective_date': safe_date(rate.effective_date),

        }, status=201)


# REPLACE billing_rates_detail in views_billing.py with this fixed version:
# The BillingRate model uses 'rate' not 'hourly_rate'

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def billing_rates_detail(request, rate_id):
    """Get, update, or delete a specific billing rate"""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization found'}, status=404)
    
    # Get the rate (must belong to this org)
    try:
        rate = BillingRate.objects.get(id=rate_id, org=org)
    except BillingRate.DoesNotExist:
        return Response({'error': 'Billing rate not found'}, status=404)
    
    if request.method == 'GET':
        return Response({
            'id': rate.id,
            'user': rate.user.id if rate.user else None,
            'user_name': rate.user.username if rate.user else None,
            'client': rate.client.id if rate.client else None,
            'client_name': rate.client.name if rate.client else None,
            'rate': str(rate.rate),  # FIX: was 'hourly_rate'
            'effective_date': safe_date(rate.effective_date),
        })
    
    elif request.method in ['PUT', 'PATCH']:
        # Update rate - accept both 'rate' and 'hourly_rate' for compatibility
        new_rate = request.data.get('rate') or request.data.get('hourly_rate')
        if new_rate:
            rate.rate = Decimal(str(new_rate))  # FIX: was rate.hourly_rate
        if 'effective_date' in request.data:
            rate.effective_date = request.data['effective_date']
        if 'user' in request.data:
            rate.user_id = request.data['user'] or None
        if 'client' in request.data:
            rate.client_id = request.data['client'] or None
        
        rate.save()
        
        return Response({
            'id': rate.id,
            'user': rate.user.id if rate.user else None,
            'user_name': rate.user.username if rate.user else None,
            'client': rate.client.id if rate.client else None,
            'client_name': rate.client.name if rate.client else None,
            'rate': str(rate.rate),  # FIX: was 'hourly_rate'
            'effective_date': safe_date(rate.effective_date),
        })
    
    elif request.method == 'DELETE':
        rate_id = rate.id
        rate.delete()
        return Response({
            'success': True,
            'message': f'Billing rate {rate_id} deleted',
        })


# tracker/views_billing.py
"""
Stripe billing integration for TimeTracker.
Handles checkout sessions, webhooks, and subscription management.
"""

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import timedelta

from rest_framework import status

from .models import Organization, OrganizationMembership

STRIPE_PRICES = {
    "professional_monthly": getattr(settings, "STRIPE_PRICE_PROFESSIONAL_MONTHLY", None),
    "professional_yearly": getattr(settings, "STRIPE_PRICE_PROFESSIONAL_YEARLY", None),
    "executive_monthly": getattr(settings, "STRIPE_PRICE_EXECUTIVE_MONTHLY", None),
    "executive_yearly": getattr(settings, "STRIPE_PRICE_EXECUTIVE_YEARLY", None),
}

# ============================================================================
# CHECKOUT SESSION
# ============================================================================

# Replace the create_checkout_session function in views_billing.py with this:

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_checkout_session(request):
    """Only org OWNER can create checkout session."""
    membership = OrganizationMembership.objects.filter(
        user=request.user
    ).select_related("organization").first()
    
    if not membership:
        return Response({"error": "No organization found"}, status=400)
    
    # ✅ Only owner can manage billing
    if membership.role != 'owner':
        return Response({
            "error": "Only the organization owner can manage billing"
        }, status=403)
    
    org = membership.organization
    
    plan = (request.data.get("plan") or "professional").strip().lower()
    interval = (request.data.get("interval") or "monthly").strip().lower()
    quantity = max(1, int(request.data.get("quantity") or 1))  # Minimum 1 seat
    
    if plan not in ("professional", "executive"):
        return Response({"error": "Invalid plan"}, status=400)
    if interval not in ("monthly", "yearly"):
        return Response({"error": "Invalid interval"}, status=400)
    
    key = f"{plan}_{interval}"
    price_id = STRIPE_PRICES.get(key)
    
    if not price_id:
        return Response({"error": f"Stripe price not configured for {key}"}, status=500)
    
    # Create/get Stripe customer for ORG
    if not org.stripe_customer_id:
        customer = stripe.Customer.create(
            email=request.user.email,
            name=org.name,
            metadata={
                "organization_id": str(org.id),
                "organization_slug": org.slug,
            },
        )
        org.stripe_customer_id = customer.id
        org.save(update_fields=["stripe_customer_id"])
    
    success_url = request.data.get("success_url") or f"{settings.FRONTEND_URL}/account/billing?success=true"
    cancel_url = request.data.get("cancel_url") or f"{settings.FRONTEND_URL}/account/billing"
    
    session = stripe.checkout.Session.create(
        customer=org.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": quantity}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        metadata={
            "organization_id": str(org.id),
            "plan": plan,
            "seats": str(quantity),
        },
        subscription_data={
            "metadata": {
                "organization_id": str(org.id),
                "plan": plan,
            }
        },
    )
    
    return Response({"checkout_url": session.url, "session_id": session.id})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_billing_portal_session(request):
    """
    Create a Stripe Customer Portal session for managing subscription.
    Allows customers to update payment method, view invoices, cancel, etc.
    """
    try:
        membership = OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
        
        if not membership:
            return Response({'error': 'No organization found'}, status=400)
        
        org = membership.organization
        
        if not org.stripe_customer_id:
            return Response({'error': 'No billing account found'}, status=400)
        
        return_url = request.data.get('return_url', f"{settings.FRONTEND_URL}/settings")
        
        session = stripe.billing_portal.Session.create(
            customer=org.stripe_customer_id,
            return_url=return_url,
        )
        
        return Response({
            'portal_url': session.url,
        })
        
    except stripe.error.StripeError as e:
        return Response({'error': str(e)}, status=400)


# ============================================================================
# SUBSCRIPTION STATUS
# ============================================================================

# In views_billing.py, update get_subscription_status

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_subscription_status(request):
    """Get current subscription status for the organization."""
    try:
        membership = OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
        
        if not membership:
            return Response({'error': 'No organization found'}, status=400)
        
        org = membership.organization
        
        # Check trial status
        now = timezone.now()
        trial_active = org.trial_ends_at and org.trial_ends_at > now
        trial_days_left = 0
        if trial_active:
            trial_days_left = (org.trial_ends_at - now).days
        
        # Get Stripe subscription if exists
        subscription_data = None
        if org.stripe_customer_id:
            subscriptions = stripe.Subscription.list(
                customer=org.stripe_customer_id,
                status='active',
                limit=1,
            )
            
            if subscriptions.data:
                sub = subscriptions.data[0]
                item = sub['items']['data'][0] if sub['items']['data'] else None
                
                # Get the billing interval from the price
                interval = 'month'
                if item and item.get('price'):
                    interval = item['price'].get('recurring', {}).get('interval', 'month')
                
                subscription_data = {
                    'id': sub.id,
                    'status': sub.status,
                    'current_period_end': sub.current_period_end,
                    'cancel_at_period_end': sub.cancel_at_period_end,
                    'plan': item['price']['nickname'] if item else None,
                    'quantity': item['quantity'] if item else 1,
                    'interval': interval,  # 'month' or 'year'
                }
        
        return Response({
            'organization': {
                'id': org.id,
                'name': org.name,
                'plan': org.plan,
                'seat_count': org.seat_count, 
            },
            'trial': {
                'active': trial_active,
                'ends_at': org.trial_ends_at.isoformat() if org.trial_ends_at else None,
                'days_left': trial_days_left,
            },
            'subscription': subscription_data,
            'has_payment_method': bool(org.stripe_customer_id and subscription_data),
            'is_owner': membership.role == 'owner',
        })
        
    except stripe.error.StripeError as e:
        return Response({'error': str(e)}, status=400)


# ============================================================================
# WEBHOOK HANDLER
# ============================================================================

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def stripe_webhook(request):
    """
    Handle Stripe webhook events.
    
    Events handled:
    - checkout.session.completed: Subscription started
    - customer.subscription.updated: Plan changed
    - customer.subscription.deleted: Subscription cancelled
    - invoice.payment_failed: Payment failed
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)
    
    event_type = event['type']
    data = event['data']['object']
    
    # Handle specific events
    if event_type == 'checkout.session.completed':
        handle_checkout_completed(data)
    
    elif event_type == 'customer.subscription.updated':
        handle_subscription_updated(data)
    
    elif event_type == 'customer.subscription.deleted':
        handle_subscription_deleted(data)
    
    elif event_type == 'invoice.payment_failed':
        handle_payment_failed(data)
    
    return HttpResponse(status=200)


def handle_checkout_completed(session):
    """Handle successful checkout - activate subscription with seat count."""
    org_id = session.get('metadata', {}).get('organization_id')
    
    if not org_id:
        customer_id = session.get('customer')
        try:
            org = Organization.objects.get(stripe_customer_id=customer_id)
            org_id = org.id
        except Organization.DoesNotExist:
            print(f"[Stripe] Could not find org for checkout session {session['id']}")
            return
    
    try:
        org = Organization.objects.get(id=org_id)
        
        subscription_id = session.get('subscription')
        if subscription_id:
            subscription = stripe.Subscription.retrieve(subscription_id)
            
            # Get price and quantity
            item = subscription['items']['data'][0] if subscription['items']['data'] else None
            if item:
                price_id = item['price']['id']
                quantity = item['quantity']  # ✅ Get seat count
                
                # Map price to plan
                if price_id in [STRIPE_PRICES.get('executive_monthly'), STRIPE_PRICES.get('executive_yearly')]:
                    plan = 'executive'
                else:
                    plan = 'professional'
                
                # ✅ Save subscription ID, plan, AND seat count
                org.stripe_subscription_id = subscription_id
                org.plan = plan
                org.seat_count = quantity
                org.trial_ends_at = None
                org.save(update_fields=['stripe_subscription_id', 'plan', 'seat_count', 'trial_ends_at'])
                
                print(f"[Stripe] Activated {plan} plan for {org.name} with {quantity} seats")
        
    except Organization.DoesNotExist:
        print(f"[Stripe] Organization {org_id} not found")


def handle_subscription_updated(subscription):
    """Handle subscription changes (upgrades, downgrades, seat changes)."""
    customer_id = subscription.get('customer')
    
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        
        if subscription['status'] in ['active', 'trialing']:
            item = subscription['items']['data'][0] if subscription['items']['data'] else None
            
            if item:
                price_id = item['price']['id']
                quantity = item['quantity']
                
                if price_id in [STRIPE_PRICES.get('executive_monthly'), STRIPE_PRICES.get('executive_yearly')]:
                    plan = 'executive'
                else:
                    plan = 'professional'
                
                org.plan = plan
                org.stripe_subscription_id = subscription['id']
                
                # Only update seat_count if Stripe quantity is higher,
                # or if org has no seats yet. This prevents plan switches
                # from resetting seats to 1.
                if quantity > org.seat_count or org.seat_count == 0:
                    org.seat_count = quantity
                
                # Clear grace deadline if payment recovered
                if org.payment_grace_deadline:
                    org.payment_grace_deadline = None
                    org.save(update_fields=['plan', 'seat_count', 'stripe_subscription_id', 'payment_grace_deadline'])
                    print(f"[Stripe] Payment recovered for {org.name}, grace period cleared")
                else:
                    org.save(update_fields=['plan', 'seat_count', 'stripe_subscription_id'])
                
                print(f"[Stripe] Updated {org.name}: {plan} plan, {org.seat_count} seats (Stripe qty: {quantity})")
        
        # Handle past_due — start 15-day grace period
        elif subscription['status'] == 'past_due':
            if not org.payment_grace_deadline:
                from django.utils import timezone
                from datetime import timedelta
                org.payment_grace_deadline = timezone.now() + timedelta(days=15)
                org.save(update_fields=['payment_grace_deadline'])
                print(f"[Stripe] Payment past due for {org.name}, grace deadline: {org.payment_grace_deadline}")
        
    except Organization.DoesNotExist:
        print(f"[Stripe] Organization not found for customer {customer_id}")


def handle_subscription_deleted(subscription):
    """Handle subscription cancellation."""
    from tracker.models import AgentDevice, OrganizationMembership
    
    customer_id = subscription.get('customer')
    
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        org.plan = 'none'
        org.seat_count = 0
        org.stripe_subscription_id = None
        org.save(update_fields=['plan', 'seat_count', 'stripe_subscription_id'])
        
        # Deactivate all org devices
        org_user_ids = OrganizationMembership.objects.filter(
            organization=org
        ).values_list('user_id', flat=True)
        
        deactivated = AgentDevice.objects.filter(
            user_id__in=org_user_ids, is_active=True
        ).update(is_active=False)
        
        print(f"[Stripe] Subscription cancelled for {org.name}, deactivated {deactivated} devices")
        
    except Organization.DoesNotExist:
        print(f"[Stripe] Organization not found for customer {customer_id}")


def handle_payment_failed(invoice):
    """Handle failed payment - notify org admin."""
    customer_id = invoice.get('customer')
    
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        
        # TODO: Send email notification about failed payment
        # TODO: Maybe create a PaymentFailure record
        
        print(f"[Stripe] Payment failed for {org.name}")
        
    except Organization.DoesNotExist:
        print(f"[Stripe] Organization not found for customer {customer_id}")


# ============================================================================
# PLAN SELECTION (for trial users)
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def select_plan(request):
    """
    Select a plan during onboarding (before payment).
    Stores the intended plan for when they convert from trial.
    """
    try:
        membership = OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
        
        if not membership:
            return Response({'error': 'No organization found'}, status=400)
        
        org = membership.organization
        
        plan = request.data.get('plan', 'professional')
        seats = request.data.get('seats', 1)
        
        # Store intended plan (will apply after trial or payment)
        # For now, just validate and acknowledge
        if plan not in ['professional', 'executive']:
            return Response({'error': 'Invalid plan'}, status=400)
        
        # You could store this in a separate field like `intended_plan`
        # For simplicity, we'll just return success
        
        return Response({
            'ok': True,
            'plan': plan,
            'seats': seats,
            'message': f'Selected {plan} plan with {seats} seat(s). Your 7-day trial has started.',
        })
        
    except Exception as e:
        return Response({'error': str(e)}, status=500)

# ============================================================================
# ADD SEATS
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_seats(request):
    """Add more seats to existing subscription. Owner only."""
    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role='owner'
    ).select_related('organization').first()
    
    if not membership:
        return Response({'error': 'Only organization owner can add seats'}, status=403)
    
    org = membership.organization
    
    if not org.stripe_subscription_id:
        return Response({'error': 'No active subscription. Please subscribe first.'}, status=400)
    
    additional_seats = max(1, int(request.data.get('seats', 1)))
    new_quantity = org.seat_count + additional_seats
    
    try:
        # Get current subscription
        subscription = stripe.Subscription.retrieve(org.stripe_subscription_id)
        
        # Update quantity
        stripe.Subscription.modify(
            org.stripe_subscription_id,
            items=[{
                'id': subscription['items']['data'][0]['id'],
                'quantity': new_quantity,
            }],
            proration_behavior='create_prorations',  # Charge prorated amount immediately
        )
        
        # Update local record (webhook will also update, but this gives immediate feedback)
        org.seat_count = new_quantity
        org.save(update_fields=['seat_count'])
        
        return Response({
            'success': True,
            'previous_seats': org.seat_count - additional_seats,
            'added_seats': additional_seats,
            'new_seat_count': new_quantity,
            'message': f'Successfully added {additional_seats} seat(s). New total: {new_quantity}'
        })
        
    except stripe.error.StripeError as e:
        return Response({'error': str(e)}, status=400)


# Add these to views_billing.py

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reduce_seats(request):
    """Remove seats from existing subscription. Owner only."""
    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role='owner'
    ).select_related('organization').first()
    
    if not membership:
        return Response({'error': 'Only organization owner can manage seats'}, status=403)
    
    org = membership.organization
    
    if not org.stripe_subscription_id:
        return Response({'error': 'No active subscription'}, status=400)
    
    new_quantity = max(1, int(request.data.get('seats', 1)))  # Minimum 1 seat
    
    # Check current usage
    current_members = OrganizationMembership.objects.filter(organization=org).count()
    pending_invites = Invitation.objects.filter(
        organization=org,
        accepted_at__isnull=True,
        expires_at__gt=timezone.now()
    ).count()
    
    total_allocated = current_members + pending_invites
    
    if new_quantity < total_allocated:
        return Response({
            'error': 'Cannot reduce below current usage',
            'current_members': current_members,
            'pending_invites': pending_invites,
            'total_allocated': total_allocated,
            'requested_seats': new_quantity,
            'message': f'You have {total_allocated} seats in use. Remove {total_allocated - new_quantity} member(s) or cancel pending invites first.'
        }, status=400)
    
    try:
        subscription = stripe.Subscription.retrieve(org.stripe_subscription_id)
        
        stripe.Subscription.modify(
            org.stripe_subscription_id,
            items=[{
                'id': subscription['items']['data'][0]['id'],
                'quantity': new_quantity,
            }],
            proration_behavior='create_prorations',  # Credit for unused time
        )
        
        previous_seats = org.seat_count
        org.seat_count = new_quantity
        org.save(update_fields=['seat_count'])
        
        return Response({
            'success': True,
            'previous_seats': previous_seats,
            'new_seat_count': new_quantity,
            'seats_removed': previous_seats - new_quantity,
            'message': f'Reduced to {new_quantity} seat(s). You\'ll receive a prorated credit.'
        })
        
    except stripe.error.StripeError as e:
        return Response({'error': str(e)}, status=400)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_plan(request):
    """Switch between Professional and Executive plans. Owner only."""
    membership = OrganizationMembership.objects.filter(
        user=request.user,
        role='owner'
    ).select_related('organization').first()
    
    if not membership:
        return Response({'error': 'Only organization owner can change plan'}, status=403)
    
    org = membership.organization
    
    if not org.stripe_subscription_id:
        return Response({'error': 'No active subscription'}, status=400)
    
    new_plan = request.data.get('plan', '').lower()
    if new_plan not in ('professional', 'executive'):
        return Response({'error': 'Invalid plan. Choose "professional" or "executive"'}, status=400)
    
    if new_plan == org.plan:
        return Response({'error': f'Already on {new_plan} plan'}, status=400)
    
    # Determine billing interval from current subscription
    try:
        subscription = stripe.Subscription.retrieve(org.stripe_subscription_id)
        current_price_id = subscription['items']['data'][0]['price']['id']
        
        # Figure out if monthly or yearly
        if current_price_id in [STRIPE_PRICES.get('professional_yearly'), STRIPE_PRICES.get('executive_yearly')]:
            interval = 'yearly'
        else:
            interval = 'monthly'
        
        new_price_id = STRIPE_PRICES.get(f'{new_plan}_{interval}')
        
        if not new_price_id:
            return Response({'error': f'Price not configured for {new_plan}_{interval}'}, status=500)
        
        # Update subscription with new price, keep same quantity
        stripe.Subscription.modify(
            org.stripe_subscription_id,
            items=[{
                'id': subscription['items']['data'][0]['id'],
                'price': new_price_id,
            }],
            proration_behavior='create_prorations',
        )
        
        previous_plan = org.plan
        org.plan = new_plan
        org.save(update_fields=['plan'])
        
        action = 'Upgraded' if new_plan == 'executive' else 'Downgraded'
        
        return Response({
            'success': True,
            'previous_plan': previous_plan,
            'new_plan': new_plan,
            'interval': interval,
            'message': f'{action} to {new_plan.title()} plan. Changes effective immediately.'
        })
        
    except stripe.error.StripeError as e:
        return Response({'error': str(e)}, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_seat_usage(request):
    """Get current seat usage for the org."""
    membership = request.user.memberships.select_related('organization').first()
    
    if not membership:
        return Response({'error': 'No organization'}, status=404)
    
    org = membership.organization
    
    current_members = OrganizationMembership.objects.filter(
        organization=org
    ).count()
    
    pending_invites = Invitation.objects.filter(
        organization=org,
        accepted_at__isnull=True,  # ✅ Correct - invitation not yet accepted
        expires_at__gt=timezone.now()
    ).count()
    
    return Response({
        'seat_count': org.seat_count,
        'members': current_members,
        'pending_invites': pending_invites,
        'total_allocated': current_members + pending_invites,
        'seats_available': max(0, org.seat_count - current_members - pending_invites),
        'can_invite': (current_members + pending_invites) < org.seat_count,
        'plan': org.plan,
    })


# ============================================================================
# REPLACE import_invoices_csv in views_billing.py with this version
# Fixes: UTF-8 BOM handling from Excel exports
# ============================================================================

# ============================================================================
# CSV INVOICE IMPORT — Preview + Commit (two-step)
# ============================================================================

def _parse_csv_file(csv_file):
    """
    Parse uploaded CSV file. Returns (reader, column_map, error_response).
    Handles UTF-8 BOM, flexible column aliases, required column validation.
    """
    raw_content = csv_file.read()
    try:
        decoded_file = raw_content.decode('utf-8-sig')
    except UnicodeDecodeError:
        decoded_file = raw_content.decode('latin-1')

    reader = csv.DictReader(io.StringIO(decoded_file))

    if reader.fieldnames:
        reader.fieldnames = [
            h.lower().strip().replace(' ', '_').replace('\ufeff', '')
            for h in reader.fieldnames
        ]

    fieldnames_set = set(reader.fieldnames or [])

    COLUMN_ALIASES = {
        'client_code':    ['client_code', 'clientcode', 'client', 'code',
                           'customer_code', 'customercode', 'customer'],
        'invoice_number': ['invoice_number', 'invoicenumber', 'invoice_no',
                           'invoiceno', 'invoice', 'inv_number', 'inv_no', 'number', 'doc_number'],
        'invoice_date':   ['invoice_date', 'invoicedate', 'date', 'inv_date',
                           'invdate', 'txndate'],
        'amount':         ['amount', 'total', 'invoice_amount', 'invoiceamount',
                           'total_amount', 'totalamount', 'value', 'totalamt'],
        'hours_billed':   ['hours_billed', 'hoursbilled', 'hours', 'billed_hours',
                           'billedhours', 'qty', 'quantity'],
        'status':         ['status', 'invoice_status', 'payment_status'],
    }

    column_map = {}
    for standard_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in fieldnames_set:
                column_map[standard_name] = alias
                break

    required = ['client_code', 'invoice_number', 'invoice_date', 'amount']
    missing = [col for col in required if col not in column_map]

    if missing:
        return None, None, {
            'error': f'Missing required columns: {", ".join(missing)}',
            'found_columns': list(reader.fieldnames or []),
            'required_columns': required,
            'hint': 'CSV must have: client_code (or customer), invoice_number (or invoice_no), invoice_date (or date), amount (or total)',
        }

    return reader, column_map, None


def _parse_row(row, column_map, row_num):
    """
    Parse a single CSV row. Returns (parsed_dict, error_str).
    """
    from datetime import datetime as dt

    client_code    = (row.get(column_map['client_code']) or '').strip().upper()
    invoice_number = (row.get(column_map['invoice_number']) or '').strip()
    date_str       = (row.get(column_map['invoice_date']) or '').strip()
    amount_str     = (row.get(column_map['amount']) or '').strip()
    hours_str      = (row.get(column_map.get('hours_billed', '__missing__')) or '').strip()
    status_str     = (row.get(column_map.get('status', '__missing__')) or '').strip().lower()

    if not all([client_code, invoice_number, date_str, amount_str]):
        return None, 'Missing required field'

    DATE_FORMATS = [
        '%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y',
        '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d',
        '%m/%d/%y', '%d/%m/%y',
    ]
    invoice_date = None
    for fmt in DATE_FORMATS:
        try:
            invoice_date = dt.strptime(date_str, fmt).date()
            break
        except ValueError:
            continue
    if not invoice_date:
        return None, f'Invalid date format: {date_str}'

    try:
        amount = Decimal(amount_str.replace('$', '').replace(',', '')
                                   .replace('£', '').replace('€', '').strip())
    except Exception:
        return None, f'Invalid amount: {amount_str}'

    hours_billed = None
    if hours_str:
        try:
            hours_billed = Decimal(hours_str.replace(',', '').strip())
        except Exception:
            pass  # Optional field — don't fail

    # Normalize status
    status_map = {
        'paid': 'paid', 'open': 'sent', 'sent': 'sent',
        'draft': 'draft', 'voided': 'voided', 'void': 'voided',
        'overdue': 'overdue',
    }
    status = status_map.get(status_str, 'sent')

    return {
        'client_code':    client_code,
        'invoice_number': invoice_number,
        'invoice_date':   invoice_date,
        'amount':         amount,
        'hours_billed':   hours_billed,
        'status':         status,
    }, None


MATCH_THRESHOLD = 82  # rapidfuzz score 0–100


def _match_client(client_code, clients_by_code, clients_by_name):
    """
    Two-tier client matching:
    1. Exact code match (fast path)
    2. Fuzzy name/code match via rapidfuzz (fallback)

    Returns (client_or_None, match_score, suggestions_list, needs_review_bool)
    """
    from rapidfuzz import fuzz, process

    # Tier 1: exact code match
    exact = clients_by_code.get(client_code)
    if exact:
        return exact, 100, [], False

    # Tier 2: fuzzy match against all client names and codes
    all_labels = list(clients_by_name.keys())  # "NAME (CODE)" strings
    if not all_labels:
        return None, 0, [], True

    results = process.extract(
        client_code,
        all_labels,
        scorer=fuzz.token_sort_ratio,
        limit=3,
    )

    suggestions = [
        {
            'client_id':   clients_by_name[label].id,
            'client_name': clients_by_name[label].name,
            'client_code': clients_by_name[label].code or '',
            'score':       round(score),
        }
        for label, score, _ in results
        if score >= 50  # Show anything semi-plausible as a suggestion
    ]

    best_label, best_score, _ = results[0] if results else (None, 0, None)

    if best_score >= MATCH_THRESHOLD and best_label:
        best_client = clients_by_name[best_label]
        return best_client, round(best_score), suggestions, False

    return None, round(best_score) if results else 0, suggestions, True


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
@require_professional_plan
def import_invoices_csv(request):
    """
    PREVIEW step — parse CSV, fuzzy-match clients, return rows for review.
    No DB writes. Frontend shows this before calling csv_invoice_commit.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)

    csv_file = request.FILES.get('file')
    if not csv_file:
        return Response({'error': 'No file uploaded'}, status=400)
    if not csv_file.name.lower().endswith('.csv'):
        return Response({'error': 'File must be a CSV'}, status=400)

    try:
        reader, column_map, err = _parse_csv_file(csv_file)
        if err:
            return Response(err, status=400)

        # Build lookup tables
        all_clients = list(Client.objects.filter(org=org))
        clients_by_code = {
            c.code.upper(): c for c in all_clients if c.code
        }
        # "NAME (CODE)" label for fuzzy matching
        clients_by_name = {
            f"{c.name} ({c.code or ''})".strip(): c for c in all_clients
        }

        existing_invoice_numbers = set(
            Invoice.objects.filter(org=org)
            .values_list('invoice_number', flat=True)
        )

        rows = []
        parse_errors = []

        for row_num, row in enumerate(reader, start=2):
            parsed, err = _parse_row(row, column_map, row_num)
            if err:
                parse_errors.append({'row': row_num, 'error': err})
                continue

            client, score, suggestions, needs_review = _match_client(
                parsed['client_code'], clients_by_code, clients_by_name
            )

            is_duplicate = parsed['invoice_number'] in existing_invoice_numbers

            rows.append({
                'row':            row_num,
                'invoice_number': parsed['invoice_number'],
                'invoice_date':   parsed['invoice_date'].isoformat(),
                'amount':         float(parsed['amount']),
                'hours_billed':   float(parsed['hours_billed']) if parsed['hours_billed'] else None,
                'status':         parsed['status'],
                # Client matching
                'client_code':     parsed['client_code'],
                'client_id':       client.id if client else None,
                'client_name':     client.name if client else None,
                'match_score':     score,
                'needs_review':    needs_review,
                'suggestions':     suggestions,
                # Flags
                'is_duplicate':    is_duplicate,
                'will_import':     not is_duplicate and not needs_review,
            })

        matched      = sum(1 for r in rows if r['client_id'] and not r['needs_review'])
        unmatched    = sum(1 for r in rows if r['needs_review'])
        duplicates   = sum(1 for r in rows if r['is_duplicate'])
        will_import  = sum(1 for r in rows if r['will_import'])

        return Response({
            'preview': True,
            'rows': rows,
            'parse_errors': parse_errors,
            'summary': {
                'total_rows':   len(rows),
                'will_import':  will_import,
                'matched':      matched,
                'unmatched':    unmatched,
                'duplicates':   duplicates,
                'parse_errors': len(parse_errors),
            },
        })

    except Exception as e:
        import traceback
        return Response({
            'error': f'Failed to process CSV: {str(e)}',
            'detail': traceback.format_exc()[:500],
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def csv_invoice_commit(request):
    """
    COMMIT step — write confirmed rows to Invoice model.

    Body: {
        "rows": [
            {
                "invoice_number": "INV-001",
                "invoice_date":   "2026-02-01",
                "amount":         1500.00,
                "hours_billed":   10.0,         // optional
                "status":         "paid",        // optional, default "sent"
                "client_code":    "SMITH",
                "client_id":      42,            // null if still unmatched
            },
            ...
        ]
    }

    Rows with client_id=null are saved with client=null (unmatched queue).
    Duplicate invoice_numbers are skipped.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)

    rows = request.data.get('rows', [])
    if not rows:
        return Response({'error': 'No rows provided'}, status=400)

    # Re-fetch existing invoice numbers to guard against concurrent uploads
    existing_numbers = set(
        Invoice.objects.filter(org=org).values_list('invoice_number', flat=True)
    )

    # Pre-fetch clients once
    clients_by_id = {
        c.id: c for c in Client.objects.filter(org=org)
    }

    imported, skipped, errors = [], [], []

    from django.db import transaction
    with transaction.atomic():
        for row in rows:
            inv_num = (row.get('invoice_number') or '').strip()
            if not inv_num:
                errors.append({'invoice_number': inv_num, 'error': 'Missing invoice_number'})
                continue

            if inv_num in existing_numbers:
                skipped.append({'invoice_number': inv_num, 'reason': 'Duplicate'})
                continue

            try:
                inv_date = row['invoice_date']  # Already ISO string from preview
                amount   = Decimal(str(row['amount']))
                hours    = Decimal(str(row['hours_billed'])) if row.get('hours_billed') else None
                status   = row.get('status', 'sent')
                client_id = row.get('client_id')
                client    = clients_by_id.get(client_id) if client_id else None

                invoice = Invoice.objects.create(
                    org=org,
                    client=client,
                    invoice_number=inv_num,
                    invoice_date=inv_date,
                    amount=amount,
                    hours_billed=hours,
                    status=status,
                    client_code=row.get('client_code', ''),
                    source='csv',
                    created_by=request.user,
                )

                existing_numbers.add(inv_num)  # Prevent dupes within this batch

                imported.append({
                    'id':             invoice.id,
                    'invoice_number': inv_num,
                    'client_name':    client.name if client else None,
                    'amount':         float(amount),
                })

            except Exception as e:
                errors.append({'invoice_number': inv_num, 'error': str(e)})

    return Response({
        'success': True,
        'summary': {
            'imported':  len(imported),
            'skipped':   len(skipped),
            'errors':    len(errors),
            'unmatched': sum(1 for r in imported if not Invoice.objects.filter(
                id=r['id']).values_list('client_id', flat=True).first()),
        },
        'imported': imported,
        'skipped':  skipped,
        'errors':   errors,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def csv_invoice_template(request):
    """
    Download a pre-filled CSV template with the org's active client codes.
    Makes it easy for firms to fill in their invoice data correctly.
    """
    from django.http import HttpResponse

    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)

    clients = Client.objects.filter(org=org, is_active=True).order_by('name')

    lines = [
        '# TimeTracker Invoice Import Template',
        '# Required columns: client_code, invoice_number, invoice_date, amount',
        '# Optional columns: hours_billed, status (paid/sent/draft/voided)',
        '#',
        'client_code,invoice_number,invoice_date,amount,hours_billed,status',
    ]

    # Pre-populate one example row per client
    from django.utils import timezone as tz
    today = tz.now().date()
    for client in clients:
        code = client.code or client.name.upper()[:8].replace(' ', '')
        lines.append(f'{code},INV-XXXX,{today.isoformat()},0.00,,sent')

    content = '\n'.join(lines)
    response = HttpResponse(content, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="invoice_import_template_{org.slug}.csv"'
    return response

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def list_invoices(request):
    from .models import Invoice

    # ── Admin impersonation override ──
    override_id = request.GET.get("org_id")
    if override_id and (request.user.is_staff or request.user.is_superuser):
        try:
            org = Organization.objects.get(id=int(override_id))
        except (Organization.DoesNotExist, ValueError):
            return Response({"error": "Org not found"}, status=404)
    else:
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization'}, status=404)

    start_date = request.GET.get('start_date')
    end_date   = request.GET.get('end_date')
    client_id  = request.GET.get('client_id')

    invoices = Invoice.objects.filter(org=org).select_related('client')

    if start_date: invoices = invoices.filter(invoice_date__gte=start_date)
    if end_date:   invoices = invoices.filter(invoice_date__lte=end_date)
    if client_id:  invoices = invoices.filter(client_id=client_id)

    data = [{
        'id':             inv.id,
        'invoice_number': inv.invoice_number,
        'invoice_date':   inv.invoice_date.isoformat(),
        'amount':         float(inv.amount),
        'hours_billed':   float(inv.hours_billed) if inv.hours_billed else None,
        'client_id':      inv.client_id,
        'client_name':    inv.client.name if inv.client else inv.client_code,
        'client_code':    inv.client_code,
        'source':         inv.source,
        'status':         inv.status or 'sent',
        'matched':        inv.client is not None,
    } for inv in invoices.order_by('-invoice_date', '-id')[:500]]

    return Response({'invoices': data, 'total': invoices.count()})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def match_invoice_client(request):
    """Manually match an unmatched invoice to a client."""
    from .models import Invoice
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    invoice_id = request.data.get('invoice_id')
    client_id = request.data.get('client_id')
    
    if not invoice_id or not client_id:
        return Response({'error': 'invoice_id and client_id required'}, status=400)
    
    try:
        invoice = Invoice.objects.get(id=invoice_id, org=org)
        client = Client.objects.get(id=client_id, org=org)
        
        invoice.client = client
        invoice.save(update_fields=['client'])
        
        return Response({
            'success': True,
            'invoice_number': invoice.invoice_number,
            'client_name': client.name,
        })
    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=404)
    except Client.DoesNotExist:
        return Response({'error': 'Client not found'}, status=404)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def delete_invoice(request, invoice_id):
    """Delete an invoice."""
    from .models import Invoice
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        invoice = Invoice.objects.get(id=invoice_id, org=org)
        inv_number = invoice.invoice_number
        invoice.delete()
        return Response({'success': True, 'deleted': inv_number})
    except Invoice.DoesNotExist:
        return Response({'error': 'Invoice not found'}, status=404)


# ============================================================================
# REALIZATION REPORT
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def realization_report(request):
    """
    Calculate realization: Billed (Budget) vs Worked (Actual)
    
    Realization = Billed Hours / Worked Hours × 100
    
    - >100% = Efficient (worked fewer hours than billed)
    - 100% = Break even
    - <100% = Over budget (worked more hours than billed)
    """
    from .models import Invoice
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if not start_date or not end_date:
        return Response({'error': 'start_date and end_date required'}, status=400)
    
    # Get invoiced totals by client
    invoiced = Invoice.objects.filter(
        org=org,
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
        client__isnull=False,
    ).values('client_id', 'client__name', 'client__code').annotate(
        billed_hours=Coalesce(Sum('hours_billed'), Decimal('0'), output_field=DecimalField()),
        billed_amount=Coalesce(Sum('amount'), Decimal('0'), output_field=DecimalField()),
    )
    
    invoiced_by_client = {
        row['client_id']: {
            'client_id': row['client_id'],
            'client_name': row['client__name'],
            'client_code': row['client__code'] or '',
            'billed_hours': float(row['billed_hours']),
            'billed_amount': float(row['billed_amount']),
        }
        for row in invoiced
    }
    
    # Get worked hours by client (billable time blocks)
    # Using Block model with 'day' field based on your existing code
    worked = Block.objects.filter(
        org=org,
        day__gte=start_date,
        day__lte=end_date,
        client__isnull=False,
        is_billable=True,
    ).values('client_id', 'client__name', 'client__code').annotate(
        worked_minutes=Coalesce(Sum('minutes'), 0),
    )
    
    worked_by_client = {
        row['client_id']: {
            'client_id': row['client_id'],
            'client_name': row['client__name'],
            'client_code': row['client__code'] or '',
            'worked_hours': float(row['worked_minutes'] or 0) / 60,
        }
        for row in worked
    }
    
    # Merge data
    all_client_ids = set(invoiced_by_client.keys()) | set(worked_by_client.keys())
    
    clients = []
    totals = {
        'billed_hours': 0,
        'billed_amount': 0,
        'worked_hours': 0,
    }
    
    for client_id in all_client_ids:
        inv_data = invoiced_by_client.get(client_id, {})
        work_data = worked_by_client.get(client_id, {})
        
        billed_hours = inv_data.get('billed_hours', 0)
        billed_amount = inv_data.get('billed_amount', 0)
        worked_hours = work_data.get('worked_hours', 0)
        
        # Calculate realization
        if worked_hours > 0 and billed_hours > 0:
            realization = (billed_hours / worked_hours) * 100
        elif worked_hours == 0 and billed_hours > 0:
            realization = 100
        elif worked_hours > 0 and billed_hours == 0:
            realization = 0
        else:
            realization = None
        
        variance_hours = billed_hours - worked_hours if billed_hours and worked_hours else None
        
        client_name = inv_data.get('client_name') or work_data.get('client_name', 'Unknown')
        client_code = inv_data.get('client_code') or work_data.get('client_code', '')
        
        # Status
        if realization is None:
            status = 'no_data'
        elif realization >= 125:
            status = 'excellent'
        elif realization >= 100:
            status = 'good'
        elif realization >= 85:
            status = 'warning'
        else:
            status = 'critical'
        
        clients.append({
            'client_id': client_id,
            'client_name': client_name,
            'client_code': client_code,
            'billed_hours': round(billed_hours, 2),
            'billed_amount': round(billed_amount, 2),
            'worked_hours': round(worked_hours, 2),
            'variance_hours': round(variance_hours, 2) if variance_hours is not None else None,
            'realization': round(realization, 1) if realization is not None else None,
            'status': status,
        })
        
        totals['billed_hours'] += billed_hours
        totals['billed_amount'] += billed_amount
        totals['worked_hours'] += worked_hours
    
    # Sort by realization (lowest first)
    clients.sort(key=lambda x: (x['realization'] or 0, x['client_name']))
    
    # Total realization
    if totals['worked_hours'] > 0 and totals['billed_hours'] > 0:
        totals['realization'] = round((totals['billed_hours'] / totals['worked_hours']) * 100, 1)
    else:
        totals['realization'] = None
    
    totals['variance_hours'] = round(totals['billed_hours'] - totals['worked_hours'], 2)
    
    if totals['realization'] is None:
        totals['status'] = 'no_data'
    elif totals['realization'] >= 125:
        totals['status'] = 'excellent'
    elif totals['realization'] >= 100:
        totals['status'] = 'good'
    elif totals['realization'] >= 85:
        totals['status'] = 'warning'
    else:
        totals['status'] = 'critical'
    
    return Response({
        'period_start': start_date,
        'period_end': end_date,
        'clients': clients,
        'totals': totals,
    })


# ============================================================================
# QuickBooks Invoice Sync (if connected)
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def quickbooks_invoices(request):
    """Fetch invoices from QuickBooks for preview."""
    from .models import Integration, Invoice
    from .views_integrations import refresh_quickbooks_token, QB_API_BASE
    import requests
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks', is_connected=True)
    except Integration.DoesNotExist:
        return Response({'error': 'Not connected to QuickBooks'}, status=400)
    
    if not refresh_quickbooks_token(integration):
        return Response({'error': 'Token refresh failed. Please reconnect.'}, status=401)
    
    start_date = request.GET.get('start_date', '2024-01-01')
    end_date = request.GET.get('end_date')
    
    conditions = [f"TxnDate >= '{start_date}'"]
    if end_date:
        conditions.append(f"TxnDate <= '{end_date}'")
    
    query = f"SELECT * FROM Invoice WHERE {' AND '.join(conditions)} ORDERBY TxnDate DESC MAXRESULTS 500"
    
    api_url = f"{QB_API_BASE}/v3/company/{integration.realm_id}/query"
    
    try:
        response = requests.get(
            api_url,
            params={'query': query},
            headers={
                'Authorization': f'Bearer {integration.access_token}',
                'Accept': 'application/json',
            },
            timeout=30
        )
    except requests.RequestException as e:
        return Response({'error': f'Failed to connect: {e}'}, status=500)
    
    if response.status_code != 200:
        return Response({'error': 'Failed to fetch invoices'}, status=500)
    
    data = response.json()
    qb_invoices = data.get('QueryResponse', {}).get('Invoice', [])
    
    existing_ids = set(
        Invoice.objects.filter(org=org, source='quickbooks', external_id__isnull=False)
        .values_list('external_id', flat=True)
    )
    
    clients_by_qb_id = {
        c.quickbooks_id: c for c in Client.objects.filter(org=org, quickbooks_id__isnull=False)
    }
    
    invoices = []
    for inv in qb_invoices:
        qb_customer_id = str(inv.get('CustomerRef', {}).get('value', ''))
        client = clients_by_qb_id.get(qb_customer_id)
        
        # Extract hours from line items
        hours = 0
        for line in inv.get('Line', []):
            if line.get('DetailType') == 'SalesItemLineDetail':
                qty = line.get('SalesItemLineDetail', {}).get('Qty', 0)
                if 0.25 <= qty <= 500:
                    hours += qty
        
        invoices.append({
            'id': inv['Id'],
            'doc_number': inv.get('DocNumber', ''),
            'date': inv.get('TxnDate', ''),
            'customer_name': inv.get('CustomerRef', {}).get('name', 'Unknown'),
            'customer_id': qb_customer_id,
            'amount': float(inv.get('TotalAmt', 0)),
            'hours': hours if hours > 0 else None,
            'status': 'Paid' if inv.get('Balance', 0) == 0 else 'Open',
            'already_imported': inv['Id'] in existing_ids,
            'client_matched': client is not None,
            'client_name': client.name if client else None,
        })
    
    return Response({
        'invoices': invoices,
        'total': len(invoices),
        'already_imported': sum(1 for i in invoices if i['already_imported']),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def quickbooks_import_invoices(request):
    """Import selected invoices from QuickBooks."""
    from .models import Integration, Invoice
    from .views_integrations import refresh_quickbooks_token, QB_API_BASE
    import requests
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        integration = Integration.objects.get(organization=org, provider='quickbooks', is_connected=True)
    except Integration.DoesNotExist:
        return Response({'error': 'Not connected to QuickBooks'}, status=400)
    
    invoice_ids = request.data.get('invoice_ids', [])
    if not invoice_ids:
        return Response({'error': 'No invoices selected'}, status=400)
    
    if not refresh_quickbooks_token(integration):
        return Response({'error': 'Token refresh failed'}, status=401)
    
    clients_by_qb_id = {
        c.quickbooks_id: c for c in Client.objects.filter(org=org, quickbooks_id__isnull=False)
    }
    
    imported = []
    skipped = []
    errors = []
    
    for inv_id in invoice_ids:
        api_url = f"{QB_API_BASE}/v3/company/{integration.realm_id}/invoice/{inv_id}"
        
        try:
            response = requests.get(
                api_url,
                headers={
                    'Authorization': f'Bearer {integration.access_token}',
                    'Accept': 'application/json',
                },
                timeout=30
            )
            
            if response.status_code != 200:
                errors.append({'id': inv_id, 'error': 'Failed to fetch'})
                continue
            
            inv = response.json().get('Invoice', {})
            
            if Invoice.objects.filter(org=org, external_id=inv_id, source='quickbooks').exists():
                skipped.append({'id': inv_id, 'reason': 'Already imported'})
                continue
            
            qb_customer_id = str(inv.get('CustomerRef', {}).get('value', ''))
            client = clients_by_qb_id.get(qb_customer_id)
            
            hours = 0
            for line in inv.get('Line', []):
                if line.get('DetailType') == 'SalesItemLineDetail':
                    qty = line.get('SalesItemLineDetail', {}).get('Qty', 0)
                    if 0.25 <= qty <= 500:
                        hours += qty
            
            invoice = Invoice.objects.create(
                org=org,
                client=client,
                invoice_number=inv.get('DocNumber', f"QB-{inv_id}"),
                invoice_date=inv.get('TxnDate'),
                amount=Decimal(str(inv.get('TotalAmt', 0))),
                hours_billed=Decimal(str(hours)) if hours > 0 else None,
                client_code=client.code if client else '',
                client_name=inv.get('CustomerRef', {}).get('name', ''),
                source='quickbooks',
                external_id=inv_id,
                created_by=request.user,
            )
            
            imported.append({
                'id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'amount': float(invoice.amount),
            })
            
        except Exception as e:
            errors.append({'id': inv_id, 'error': str(e)})
    
    return Response({
        'imported': imported,
        'skipped': skipped,
        'errors': errors,
        'summary': {
            'imported': len(imported),
            'skipped': len(skipped),
            'errors': len(errors),
        }
    })


# ============================================================================
# CLIENT BUDGETS CRUD
# ============================================================================

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def client_budgets_list(request):
    """GET: List all client budgets / POST: Create new budget"""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    if request.method == 'GET':
        budgets = ClientBudget.objects.filter(org=org).select_related('client')
        
        client_id = request.GET.get('client_id')
        if client_id:
            budgets = budgets.filter(client_id=client_id)
        
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        if start_date and end_date:
            budgets = budgets.filter(period_start__lte=end_date, period_end__gte=start_date)
        
        data = [{
            'id': b.id,
            'client_id': b.client_id,
            'client_name': b.client.name,
            'client_code': b.client.code or '',
            'period_start': b.period_start.isoformat(),
            'period_end': b.period_end.isoformat(),
            'budget_hours': float(b.budget_hours),
            'budget_amount': float(b.budget_amount) if b.budget_amount else None,
            'description': b.description,
        } for b in budgets.order_by('-period_start')]
        
        return Response({'budgets': data, 'total': len(data)})
    
    elif request.method == 'POST':
        client_id = request.data.get('client_id')
        period_start = request.data.get('period_start')
        period_end = request.data.get('period_end')
        budget_hours = request.data.get('budget_hours')
        
        if not all([client_id, period_start, period_end, budget_hours]):
            return Response({'error': 'client_id, period_start, period_end, budget_hours required'}, status=400)
        
        try:
            client = Client.objects.get(id=client_id, org=org)
        except Client.DoesNotExist:
            return Response({'error': 'Client not found'}, status=404)
        
        budget = ClientBudget.objects.create(
            org=org,
            client=client,
            period_start=period_start,
            period_end=period_end,
            budget_hours=Decimal(str(budget_hours)),
            budget_amount=Decimal(str(request.data['budget_amount'])) if request.data.get('budget_amount') else None,
            description=request.data.get('description', ''),
        )
        
        return Response({
            'id': budget.id,
            'client_id': budget.client_id,
            'client_name': client.name,
            'period_start': budget.period_start.isoformat(),
            'period_end': budget.period_end.isoformat(),
            'budget_hours': float(budget.budget_hours),
            'budget_amount': float(budget.budget_amount) if budget.budget_amount else None,
            'description': budget.description,
        }, status=201)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def client_budgets_detail(request, budget_id):
    """Get, update, or delete a specific client budget."""
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    try:
        budget = ClientBudget.objects.select_related('client').get(id=budget_id, org=org)
    except ClientBudget.DoesNotExist:
        return Response({'error': 'Budget not found'}, status=404)
    
    if request.method == 'GET':
        return Response({
            'id': budget.id,
            'client_id': budget.client_id,
            'client_name': budget.client.name,
            'client_code': budget.client.code or '',
            'period_start': budget.period_start.isoformat(),
            'period_end': budget.period_end.isoformat(),
            'budget_hours': float(budget.budget_hours),
            'budget_amount': float(budget.budget_amount) if budget.budget_amount else None,
            'description': budget.description,
        })
    
    elif request.method in ['PUT', 'PATCH']:
        if 'period_start' in request.data:
            budget.period_start = request.data['period_start']
        if 'period_end' in request.data:
            budget.period_end = request.data['period_end']
        if 'budget_hours' in request.data:
            budget.budget_hours = Decimal(str(request.data['budget_hours']))
        if 'budget_amount' in request.data:
            budget.budget_amount = Decimal(str(request.data['budget_amount'])) if request.data['budget_amount'] else None
        if 'description' in request.data:
            budget.description = request.data['description']
        
        budget.save()
        
        return Response({
            'id': budget.id,
            'client_id': budget.client_id,
            'client_name': budget.client.name,
            'period_start': budget.period_start.isoformat(),
            'period_end': budget.period_end.isoformat(),
            'budget_hours': float(budget.budget_hours),
            'budget_amount': float(budget.budget_amount) if budget.budget_amount else None,
            'description': budget.description,
        })
    
    elif request.method == 'DELETE':
        budget.delete()
        return Response({'success': True, 'deleted': budget_id})


# ============================================================================
# ADD TO views_billing.py - Manual Billing Input & Export Endpoints
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def update_client_billed(request):
    """
    Manually update billed hours/amount for a client in a period.
    Creates or updates an Invoice record with source='manual'.
    
    POST body: {
        "client_id": 123,
        "period_start": "2026-02-01",
        "period_end": "2026-02-28",
        "billed_hours": 15.0,
        "billed_amount": 2000.00
    }
    """
    from .models import Invoice, Client
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    client_id = request.data.get('client_id')
    period_start = request.data.get('period_start')
    period_end = request.data.get('period_end')
    billed_hours = request.data.get('billed_hours')
    billed_amount = request.data.get('billed_amount')
    
    if not client_id:
        return Response({'error': 'client_id required'}, status=400)
    
    try:
        client = Client.objects.get(id=client_id, org=org)
    except Client.DoesNotExist:
        return Response({'error': 'Client not found'}, status=404)
    
    # Generate a unique invoice number for manual entries
    invoice_number = f"MANUAL-{client.code or client_id}-{period_start}-{period_end}"
    
    # Try to find existing manual invoice for this client+period
    invoice, created = Invoice.objects.update_or_create(
        org=org,
        client=client,
        invoice_number=invoice_number,
        defaults={
            'invoice_date': period_end,  # Use period end as invoice date
            'hours_billed': Decimal(str(billed_hours)) if billed_hours else None,
            'amount': Decimal(str(billed_amount)) if billed_amount else Decimal('0'),
            'client_code': client.code or '',
            'source': 'manual',
            'created_by': request.user,
        }
    )
    
    return Response({
        'success': True,
        'created': created,
        'invoice_id': invoice.id,
        'client_id': client.id,
        'client_name': client.name,
        'billed_hours': float(invoice.hours_billed) if invoice.hours_billed else None,
        'billed_amount': float(invoice.amount),
        'message': f'{"Created" if created else "Updated"} billing for {client.name}',
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@require_professional_plan  
def export_worked_hours_csv(request):
    """
    Export worked hours by client as CSV.
    Can be imported into QuickBooks/Xero for invoicing.
    
    Query params:
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - format: 'detailed' or 'summary' (default: summary)
    """
    from django.http import HttpResponse
    
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    export_format = request.GET.get('format', 'summary')
    
    if not start_date or not end_date:
        return Response({'error': 'start_date and end_date required'}, status=400)
    
    # Get worked hours
    blocks = Block.objects.filter(
        org=org,
        day__gte=start_date,
        day__lte=end_date,
        is_billable=True,
        client__isnull=False,
    ).select_related('client', 'user', 'task_type')
    
    if export_format == 'detailed':
        # Detailed: one row per time block
        lines = ['date,client_code,client_name,employee,task,hours,billing_rate,amount,description']
        
        for block in blocks.order_by('day', 'client__name', 'user__username'):
            hours = Decimal(str(block.minutes or 0)) / Decimal('60')
            rate = block.billing_rate or Decimal('0')
            amount = hours * rate
            
            employee_name = f"{block.user.first_name} {block.user.last_name}".strip() or block.user.username
            task_name = block.task_type.name if block.task_type else 'General'
            description = (block.description_override or block.notes or '').replace('"', "'").replace('\n', ' ')
            
            lines.append(
                f'{block.day.isoformat()},'
                f'{block.client.code or ""},'
                f'"{block.client.name}",'
                f'"{employee_name}",'
                f'"{task_name}",'
                f'{hours:.2f},'
                f'{rate:.2f},'
                f'{amount:.2f},'
                f'"{description}"'
            )
    else:
        # Summary: one row per client
        from django.db.models import Sum
        from django.db.models.functions import Coalesce
        
        client_totals = blocks.values(
            'client_id', 'client__code', 'client__name'
        ).annotate(
            total_minutes=Coalesce(Sum('minutes'), 0),
            total_amount=Coalesce(Sum('billing_amount'), Decimal('0')),
        ).order_by('client__name')
        
        lines = ['client_code,client_name,hours,amount,period_start,period_end']
        
        for row in client_totals:
            hours = Decimal(str(row['total_minutes'] or 0)) / Decimal('60')
            lines.append(
                f'{row["client__code"] or ""},'
                f'"{row["client__name"]}",'
                f'{hours:.2f},'
                f'{row["total_amount"]:.2f},'
                f'{start_date},'
                f'{end_date}'
            )
    
    content = '\n'.join(lines)
    
    filename = f'worked_hours_{start_date}_to_{end_date}_{export_format}.csv'
    response = HttpResponse(content, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@require_professional_plan
def realization_with_editable(request):
    """
    Same as realization_report but includes editable flag and manual invoice IDs.
    This allows the frontend to show which values can be edited inline.
    """
    from .models import Invoice
    
    org = get_request_org_override_billing(request)
    if not org:
        return Response({'error': 'No organization'}, status=404)
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if not start_date or not end_date:
        return Response({'error': 'start_date and end_date required'}, status=400)
    
    # Get invoiced totals by client
    invoiced = Invoice.objects.filter(
        org=org,
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
        client__isnull=False,
    ).values('client_id', 'client__name', 'client__code').annotate(
        billed_hours=Coalesce(Sum('hours_billed'), Decimal('0'), output_field=DecimalField()),
        billed_amount=Coalesce(Sum('amount'), Decimal('0'), output_field=DecimalField()),
    )
    
    invoiced_by_client = {
        row['client_id']: {
            'client_id': row['client_id'],
            'client_name': row['client__name'],
            'client_code': row['client__code'] or '',
            'billed_hours': float(row['billed_hours']),
            'billed_amount': float(row['billed_amount']),
        }
        for row in invoiced
    }
    
    # Get manual invoice IDs for each client (for editing)
    manual_invoices = Invoice.objects.filter(
        org=org,
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
        source='manual',
        client__isnull=False,
    ).values('client_id', 'id', 'hours_billed', 'amount')
    
    manual_by_client = {
        row['client_id']: {
            'invoice_id': row['id'],
            'hours': float(row['hours_billed']) if row['hours_billed'] else None,
            'amount': float(row['amount']),
        }
        for row in manual_invoices
    }
    
    # Get worked hours by client
    worked = Block.objects.filter(
        org=org,
        day__gte=start_date,
        day__lte=end_date,
        client__isnull=False,
        is_billable=True,
    ).values('client_id', 'client__name', 'client__code').annotate(
        worked_minutes=Coalesce(Sum('minutes'), 0),
    )
    
    worked_by_client = {
        row['client_id']: {
            'client_id': row['client_id'],
            'client_name': row['client__name'],
            'client_code': row['client__code'] or '',
            'worked_hours': float(row['worked_minutes'] or 0) / 60,
        }
        for row in worked
    }
    
    # Merge data
    all_client_ids = set(invoiced_by_client.keys()) | set(worked_by_client.keys())
    
    clients = []
    totals = {
        'billed_hours': 0,
        'billed_amount': 0,
        'worked_hours': 0,
    }
    
    for client_id in all_client_ids:
        inv_data = invoiced_by_client.get(client_id, {})
        work_data = worked_by_client.get(client_id, {})
        manual_data = manual_by_client.get(client_id)
        
        billed_hours = inv_data.get('billed_hours', 0)
        billed_amount = inv_data.get('billed_amount', 0)
        worked_hours = work_data.get('worked_hours', 0)
        
        # Calculate realization
        if worked_hours > 0 and billed_hours > 0:
            realization = (billed_hours / worked_hours) * 100
        elif worked_hours == 0 and billed_hours > 0:
            realization = 100
        elif worked_hours > 0 and billed_hours == 0:
            realization = 0
        else:
            realization = None
        
        variance_hours = billed_hours - worked_hours if billed_hours and worked_hours else None
        
        client_name = inv_data.get('client_name') or work_data.get('client_name', 'Unknown')
        client_code = inv_data.get('client_code') or work_data.get('client_code', '')
        
        # Status
        if realization is None:
            status = 'no_data'
        elif realization >= 125:
            status = 'excellent'
        elif realization >= 100:
            status = 'good'
        elif realization >= 85:
            status = 'warning'
        else:
            status = 'critical'
        
        clients.append({
            'client_id': client_id,
            'client_name': client_name,
            'client_code': client_code,
            'billed_hours': round(billed_hours, 2),
            'billed_amount': round(billed_amount, 2),
            'worked_hours': round(worked_hours, 2),
            'variance_hours': round(variance_hours, 2) if variance_hours is not None else None,
            'realization': round(realization, 1) if realization is not None else None,
            'status': status,
            # Editable info
            'manual_invoice_id': manual_data['invoice_id'] if manual_data else None,
            'is_editable': True,  # All rows can have manual override
        })
        
        totals['billed_hours'] += billed_hours
        totals['billed_amount'] += billed_amount
        totals['worked_hours'] += worked_hours
    
    # Sort by client name
    clients.sort(key=lambda x: x['client_name'].lower())
    
    # Total realization
    if totals['worked_hours'] > 0 and totals['billed_hours'] > 0:
        totals['realization'] = round((totals['billed_hours'] / totals['worked_hours']) * 100, 1)
    else:
        totals['realization'] = None
    
    totals['variance_hours'] = round(totals['billed_hours'] - totals['worked_hours'], 2)
    
    if totals['realization'] is None:
        totals['status'] = 'no_data'
    elif totals['realization'] >= 125:
        totals['status'] = 'excellent'
    elif totals['realization'] >= 100:
        totals['status'] = 'good'
    elif totals['realization'] >= 85:
        totals['status'] = 'warning'
    else:
        totals['status'] = 'critical'
    
    return Response({
        'period_start': start_date,
        'period_end': end_date,
        'clients': clients,
        'totals': totals,
    })


# ============================================================================
# ADD THESE URLS to urls.py
# ============================================================================
"""
path('billing/clients/update-billed/', update_client_billed, name='update-client-billed'),
path('billing/export/worked-hours/', export_worked_hours_csv, name='export-worked-hours'),
path('billing/realization/', realization_with_editable, name='realization-editable'),
"""# ============================================================================
# BILLING CSV EXPORT (Plan B downstream beneficiary)
# ============================================================================
#
# Single endpoint that produces a clean, CCH-import-shaped CSV of all billable
# work in a date range. Designed for the firm's bookkeeper to download and
# import into CCH Axcess Practice (or QuickBooks, Karbon, etc.).
#
# Endpoint: GET /api/billing/export-csv/
#
# Query params:
#   start_date  YYYY-MM-DD  required
#   end_date    YYYY-MM-DD  required
#   user        username or 'me'         optional (limits to one user)
#   level       'daily' or 'block'       default 'daily' (per-day-per-client-per-task)
#   format      'generic' or 'cch_axcess'  default 'generic'
#   include     'committed', 'proposed', or 'all'  default 'committed'
#
# Permissions:
#   - ?user=me           → any authenticated user can export their own
#   - no user param      → owner/admin/manager only (org-wide)
#   - ?user=<username>   → owner/admin/manager only
#
# Column shape (generic format):
#   date, staff, staff_code, client, client_code, task_type, task_type_code,
#   hours, billable, description, blocks
#
# - date         YYYY-MM-DD (block.day or block.start.date())
# - staff        user's display name or username
# - staff_code   username (no separate staff_code field today)
# - client       Client.name or 'Unassigned'
# - client_code  Client.code or '' (CCH calls this 'client code')
# - task_type    TaskType.name or '(unmapped)' when null
# - task_type_code   TaskType.code or '(unmapped)' (CCH calls this 'service code')
# - hours        decimal, 2 places
# - billable     'Y' or 'N' (from TaskType.is_billable; falls back to block.is_billable)
# - description  comma-joined sample of block window titles (or 'Professional services')
# - blocks       pipe-separated block IDs (audit trail)
#
# Streams response — works for orgs with thousands of rows in a single call.
# ============================================================================

from django.http import StreamingHttpResponse
from collections import defaultdict


class _Echo:
    """Minimal file-like object that csv.writer can write to for streaming."""
    def write(self, value):
        return value


def _can_export_org_wide(request, org):
    """Owner/admin/manager only. Staff bypass for impersonation."""
    if request.user.is_staff or request.user.is_superuser:
        return True
    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    return bool(membership and membership.role in ('owner', 'admin', 'manager'))


def _resolve_export_target_user(request, org):
    """
    Returns (target_user, is_self_export, error_response).
    target_user=None means "all users in the org" (org-wide export).
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    raw = (request.GET.get('user') or '').strip()

    if not raw:
        # Org-wide export — requires manager+ role
        if not _can_export_org_wide(request, org):
            return None, False, Response(
                {'error': 'Org-wide export requires owner, admin, or manager role. '
                          'Use ?user=me to export only your own time.'},
                status=403,
            )
        return None, False, None

    if raw.lower() == 'me':
        # Self-export — any authenticated user can do this
        return request.user, True, None

    # Specific user requested — requires manager+ role
    if not _can_export_org_wide(request, org):
        return None, False, Response(
            {'error': 'Exporting another user\'s time requires owner, admin, or '
                      'manager role.'},
            status=403,
        )

    # Resolve username → user, but only if they belong to this org
    target = User.objects.filter(username=raw).first()
    if not target:
        return None, False, Response(
            {'error': f'User "{raw}" not found.'}, status=404,
        )

    in_org = OrganizationMembership.objects.filter(
        user=target, organization=org
    ).exists()
    if not in_org and not (request.user.is_staff or request.user.is_superuser):
        return None, False, Response(
            {'error': f'User "{raw}" is not in this organization.'}, status=404,
        )

    return target, False, None


def _allowed_block_states(include_param):
    """
    Map the ?include= flag to a list of classification_state values that
    are billing-relevant. Never includes 'captured' or 'suppressed' — those
    are not user-confirmed time and have no business in billing exports.
    """
    include = (include_param or 'committed').strip().lower()
    if include == 'committed':
        return ['committed']
    elif include == 'proposed':
        return ['committed', 'proposed']
    elif include == 'all':
        # Still excludes captured/suppressed for safety
        return ['committed', 'proposed']
    else:
        # Unknown value → default to safest (committed only)
        return ['committed']


def _block_description(block, max_titles=3):
    """
    Build the description column. Prefers description_override → notes →
    a sample of window titles → fallback. Truncated and quote-safe.
    """
    text = (block.description_override or block.notes or '').strip()
    if text:
        return text[:200].replace('"', "'").replace('\n', ' ')

    # Fallback: sample window titles from this block's raw events
    titles = []
    try:
        from tracker.models import RawEvent
        sample = (RawEvent.objects.filter(block=block)
                  .exclude(window_title__isnull=True)
                  .exclude(window_title__exact='')
                  .values_list('window_title', flat=True)
                  .distinct()[:max_titles])
        titles = [t for t in sample if t]
    except Exception:
        pass

    if titles:
        return ', '.join(titles)[:200].replace('"', "'").replace('\n', ' ')

    return 'Professional services'


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_billing_csv(request):
    """
    Stream a CCH-import-shaped billing CSV. See the long docblock above for
    full query-param documentation and column shape.
    """
    # ── Resolve org (with admin impersonation support) ────────────────────
    org = get_request_org_override_billing(request)
    if not org:
        return Response({'error': 'No organization'}, status=400)

    # ── Parse + validate date range ───────────────────────────────────────
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    if not start_date_str or not end_date_str:
        return Response(
            {'error': 'start_date and end_date are required (YYYY-MM-DD)'},
            status=400,
        )
    try:
        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)
    except ValueError:
        return Response(
            {'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=400,
        )
    if start_date > end_date:
        return Response(
            {'error': 'start_date must be on or before end_date'}, status=400,
        )

    # ── Resolve target user (with permission checks) ──────────────────────
    target_user, is_self, err = _resolve_export_target_user(request, org)
    if err:
        return err

    # ── Read flags ────────────────────────────────────────────────────────
    level = (request.GET.get('level') or 'daily').strip().lower()
    if level not in ('daily', 'block'):
        level = 'daily'

    fmt = (request.GET.get('format') or 'generic').strip().lower()
    if fmt not in ('generic', 'cch_axcess'):
        fmt = 'generic'
    # cch_axcess is currently identical to generic — placeholder until Bowers
    # gets the spec from Wolters Kluwer. Reserved so future change is just
    # a column remap, not a new endpoint.

    allowed_states = _allowed_block_states(request.GET.get('include'))

    # ── Query blocks ──────────────────────────────────────────────────────
    blocks_qs = Block.objects.filter(
        org=org,
        day__gte=start_date,
        day__lte=end_date,
        deleted_at__isnull=True,
        classification_state__in=allowed_states,
    ).select_related('user', 'client', 'task_type')

    if target_user:
        blocks_qs = blocks_qs.filter(user=target_user)

    blocks_qs = blocks_qs.order_by('day', 'user__username', 'client__name', 'start')

    # ── Build CSV rows ────────────────────────────────────────────────────
    columns = [
        'date', 'staff', 'staff_code', 'client', 'client_code',
        'task_type', 'task_type_code', 'hours', 'billable',
        'description', 'blocks',
    ]

    def aggregate_daily(blocks):
        """
        Group by (day, user_id, client_id, task_type_id). Sum hours. Merge
        descriptions and block IDs.
        """
        groups = {}
        for b in blocks:
            key = (
                b.day,
                b.user_id,
                b.client_id or 0,
                b.task_type_id or 0,
            )
            if key not in groups:
                groups[key] = {
                    'day': b.day,
                    'user': b.user,
                    'client': b.client,
                    'task_type': b.task_type,
                    'minutes': 0,
                    'is_billable': False,
                    'descriptions': [],
                    'block_ids': [],
                }
            grp = groups[key]
            grp['minutes'] += int(b.minutes or 0)
            # OR the billable flag — if ANY block in the group is billable,
            # the aggregated row is billable. (TaskType.is_billable is the
            # source of truth; block.is_billable is a per-block override.)
            tt_billable = b.task_type.is_billable if b.task_type else b.is_billable
            grp['is_billable'] = grp['is_billable'] or bool(tt_billable)
            grp['block_ids'].append(b.id)
            desc = _block_description(b)
            if desc and desc not in grp['descriptions']:
                grp['descriptions'].append(desc)
        return groups

    def row_for_block(b):
        """Per-block row (level=block mode)."""
        user = b.user
        staff_name = (f'{user.first_name} {user.last_name}'.strip()
                      or user.username)
        client_name = b.client.name if b.client else 'Unassigned'
        client_code = (b.client.code if b.client else '') or ''
        if b.task_type:
            tt_name = b.task_type.name
            tt_code = b.task_type.code or '(unmapped)'
            billable = 'Y' if b.task_type.is_billable else 'N'
        else:
            tt_name = '(unmapped)'
            tt_code = '(unmapped)'
            billable = 'Y' if b.is_billable else 'N'
        hours = round(Decimal(b.minutes or 0) / Decimal('60'), 2)
        return [
            b.day.isoformat() if b.day else '',
            staff_name,
            user.username,
            client_name,
            client_code,
            tt_name,
            tt_code,
            f'{hours}',
            billable,
            _block_description(b),
            str(b.id),
        ]

    def row_for_group(grp):
        """Aggregated daily row (level=daily mode, default)."""
        user = grp['user']
        staff_name = (f'{user.first_name} {user.last_name}'.strip()
                      or user.username)
        client = grp['client']
        tt = grp['task_type']
        if tt:
            tt_name = tt.name
            tt_code = tt.code or '(unmapped)'
        else:
            tt_name = '(unmapped)'
            tt_code = '(unmapped)'
        hours = round(Decimal(grp['minutes']) / Decimal('60'), 2)
        return [
            grp['day'].isoformat() if grp['day'] else '',
            staff_name,
            user.username,
            client.name if client else 'Unassigned',
            (client.code if client else '') or '',
            tt_name,
            tt_code,
            f'{hours}',
            'Y' if grp['is_billable'] else 'N',
            ' | '.join(grp['descriptions'])[:300] or 'Professional services',
            '|'.join(str(bid) for bid in grp['block_ids']),
        ]

    # ── Stream the CSV response ───────────────────────────────────────────
    pseudo_buffer = _Echo()
    writer = csv.writer(pseudo_buffer, quoting=csv.QUOTE_MINIMAL)

    def row_iter():
        # Header
        yield writer.writerow(columns)

        # Materialize blocks once. For huge orgs this would need true chunking;
        # we're optimizing for Bowers-scale (~10K rows/month) where the whole
        # set fits comfortably in memory.
        blocks = list(blocks_qs)

        if level == 'block':
            for b in blocks:
                yield writer.writerow(row_for_block(b))
        else:
            groups = aggregate_daily(blocks)
            # Sort: day, then staff, then client, then task_type
            sorted_keys = sorted(
                groups.keys(),
                key=lambda k: (
                    k[0] or date.min,
                    (groups[k]['user'].username or ''),
                    (groups[k]['client'].name if groups[k]['client'] else 'ZZZ'),
                    (groups[k]['task_type'].code if groups[k]['task_type'] else 'ZZZ'),
                ),
            )
            for k in sorted_keys:
                yield writer.writerow(row_for_group(groups[k]))

    # Build filename
    scope = (target_user.username if target_user
             else (org.slug if org.slug else 'org'))
    filename = (f'billing_export_{scope}_'
                f'{start_date.isoformat()}_to_{end_date.isoformat()}_'
                f'{level}.csv')

    response = StreamingHttpResponse(row_iter(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
