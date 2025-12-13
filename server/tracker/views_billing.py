from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
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
    EmployeeCostRate,  # ← ADD THIS
)
from .serializers_billing import (
    BillingRateSerializer, TimesheetSummarySerializer, TimesheetDetailSerializer,
    ApprovalQueueItemSerializer, ClientSummarySerializer, BlockAuditLogSerializer,
    InvoiceExportSerializer,
    EmployeeCostRateSerializer,  # ← ADD THIS
)

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

# ===============================
# BILLING RATES VIEWSET
# ===============================

class BillingRateViewSet(viewsets.ModelViewSet):
    """
    CRUD for billing rates.
    Managers/Admins only.
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


# ===============================
# APPROVAL QUEUE
# ===============================

@api_view(['GET'])
def approval_queue(request):
    """
    Get all timesheets pending approval.
    Managers/Admins only.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
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
        
        total_minutes = sum(b.minutes or 0 for b in blocks)
        billable_minutes = sum(b.minutes or 0 for b in blocks if b.is_billable)
        total_amount = sum(float(b.billing_amount or 0) for b in blocks if b.is_billable)
        
        days_pending = 0
        if ts.submitted_at:
            days_pending = (timezone.now() - ts.submitted_at).days
        
        result.append({
            'id': ts.id,
            'user_id': ts.user_id,
            'user_name': f"{ts.user.first_name} {ts.user.last_name}".strip() or ts.user.username,
            'user_email': ts.user.email,
            'week_start': ts.week_start.isoformat(),
            'week_end': (ts.week_start + timedelta(days=6)).isoformat(),
            'status': ts.status,
            'submitted_at': ts.submitted_at.isoformat() if ts.submitted_at else None,
            'days_pending': days_pending,
            'notes': ts.submitted_notes or '',
            'total_hours': round(total_minutes / 60, 2),
            'billable_hours': round(billable_minutes / 60, 2),
            'total_amount': round(total_amount, 2),
            'auto_submitted': ts.auto_submitted,  # ← NEW: Include auto_submitted flag
        })
    
    return Response({
        'count': len(result),
        'timesheets': result
    })


# ===============================
# WEEKLY TIMESHEET VIEW (EMPLOYEE)
# ===============================

@api_view(['GET'])
def weekly_timesheet_view(request):
    """
    Employee-facing weekly timesheet grid.
    Shows hours per client/task per day.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
    # Get week
    week_start_param = request.query_params.get('week_start')
    if week_start_param:
        try:
            week_start = date.fromisoformat(week_start_param)
        except ValueError:
            return Response({'error': 'Invalid date format'}, status=400)
    else:
        week_start = get_monday(timezone.now().date())
    
    week_start = get_monday(week_start)
    week_end = week_start + timedelta(days=6)
    
    # Get or create timesheet
    timesheet, _ = Timesheet.get_or_create_for_date(org, request.user, week_start)
    
    # Get blocks for this week
    blocks = Block.objects.filter(
        org=org,
        user=request.user,
        day__gte=week_start,
        day__lte=week_end
    ).select_related('client', 'task_type')
    
    # Build grid: group by client+task_type, then by day
    grid = {}
    for block in blocks:
        key = (block.client_id, block.task_type_id)
        if key not in grid:
            grid[key] = {
                'client_id': block.client_id,
                'client_name': block.client.name if block.client else 'Unassigned',
                'task_type_id': block.task_type_id,
                'task_type_name': block.task_type.name if block.task_type else 'General',
                'is_billable': block.is_billable,
                'days': {(week_start + timedelta(days=i)).isoformat(): Decimal('0') for i in range(7)},
                'total': Decimal('0'),
            }
        
        day_key = block.day.isoformat()
        hours = Decimal(block.minutes or 0) / 60
        grid[key]['days'][day_key] += hours
        grid[key]['total'] += hours
    
    # Calculate daily totals
    daily_totals = {(week_start + timedelta(days=i)).isoformat(): Decimal('0') for i in range(7)}
    for row in grid.values():
        for day, hours in row['days'].items():
            daily_totals[day] += hours
    
    return Response({
        'week_start': week_start.isoformat(),
        'week_end': week_end.isoformat(),
        'timesheet_id': timesheet.id,
        'status': timesheet.status,
        'auto_submitted': timesheet.auto_submitted,  # ← NEW
        'submitted_at': timesheet.submitted_at.isoformat() if timesheet.submitted_at else None,  # ← NEW
        'rejection_reason': timesheet.rejection_reason or '',  # ← NEW
        'entries': list(grid.values()),
        'daily_totals': daily_totals,
        'grand_total': sum(daily_totals.values()),
        'billable_total': sum(r['total'] for r in grid.values() if r['is_billable']),
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
    org = get_user_org(request.user)
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
    
    if not block_ids:
        return Response({'error': 'block_ids required'}, status=400)
    
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

class EmployeeCostRateListView(APIView):
    """
    GET: List all employee cost rates for org
    POST: Create new cost rate
    """
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        """Get user's organization membership"""
        return OrganizationMembership.objects.filter(
            user=request.user
        ).select_related('organization').first()
    
    def get(self, request):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        rates = EmployeeCostRate.objects.filter(
            organization=membership.organization
        ).select_related('user')
        serializer = EmployeeCostRateSerializer(rates, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        if membership.role not in ['owner', 'admin']:
            return Response({'error': 'Permission denied'}, status=403)
        
        # Add organization to data
        data = request.data.copy()
        data['organization'] = membership.organization.id
        
        serializer = EmployeeCostRateSerializer(data=data)
        if serializer.is_valid():
            serializer.save(organization=membership.organization)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class EmployeeCostRateDetailView(APIView):
    """
    GET: Get single cost rate
    DELETE: Remove cost rate
    """
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        """Get user's organization membership"""
        return OrganizationMembership.objects.filter(
            user=request.user,
        ).select_related('organization').first()
    
    def get_object(self, pk, org):
        return get_object_or_404(EmployeeCostRate, pk=pk, organization=org)
    
    def get(self, request, pk):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        rate = self.get_object(pk, membership.organization)
        serializer = EmployeeCostRateSerializer(rate)
        return Response(serializer.data)
    
    def delete(self, request, pk):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        if membership.role not in ['owner', 'admin']:
            return Response({'error': 'Permission denied'}, status=403)
        
        rate = self.get_object(pk, membership.organization)
        rate.delete()
        return Response(status=204)


class ProfitabilityReportView(APIView):
    """
    GET: Calculate profit margins by client
    
    Query params:
    - start_date: YYYY-MM-DD
    - end_date: YYYY-MM-DD
    - only_approved: true/false
    """
    permission_classes = [IsAuthenticated]
    
    def get_membership(self, request):
        """Get user's organization membership"""
        return OrganizationMembership.objects.filter(
            user=request.user,
        ).select_related('organization').first()
    
    def get(self, request):
        membership = self.get_membership(request)
        if not membership:
            return Response({'error': 'No organization membership'}, status=403)
        
        org = membership.organization
        
        # Only managers/admins/owners can view profitability
        if membership.role not in ['owner', 'admin', 'manager']:
            return Response({'error': 'Permission denied'}, status=403)
        
        # Parse date range
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        only_approved = request.query_params.get('only_approved', 'true').lower() == 'true'
        
        if not start_date or not end_date:
            return Response({'error': 'start_date and end_date required'}, status=400)
        
        # Build query
        blocks = Block.objects.filter(
            organization=org,
            start_time__date__gte=start_date,
            start_time__date__lte=end_date,
            is_billable=True,
        )
        
        if only_approved:
            # Filter for approved timesheets OR blocks with no timesheet (legacy data)
            blocks = blocks.filter(
                Q(timesheet__status__in=['approved', 'locked']) | 
                Q(timesheet__isnull=True)
            )
        
        # Get all cost rates for the org (most recent per user)
        cost_rates = {}
        for rate in EmployeeCostRate.objects.filter(
            organization=org,
            effective_date__lte=end_date
        ).select_related('user').order_by('user_id', '-effective_date'):
            # Only keep first (most recent) rate per user
            if rate.user_id not in cost_rates:
                cost_rates[rate.user_id] = rate.cost_rate
        
        # Default cost rate if not set
        default_cost_rate = Decimal('50.00')
        
        # Aggregate by client, then by user
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
            
            # Calculate hours from minutes or duration
            if hasattr(block, 'minutes') and block.minutes:
                hours = Decimal(str(block.minutes)) / Decimal('60')
            elif hasattr(block, 'duration') and block.duration:
                hours = Decimal(str(block.duration)) / Decimal('60')
            else:
                # Calculate from start/end time
                if block.end_time and block.start_time:
                    delta = block.end_time - block.start_time
                    hours = Decimal(str(delta.total_seconds())) / Decimal('3600')
                else:
                    hours = Decimal('0')
            
            billing_rate = Decimal(str(block.billing_rate)) if block.billing_rate else Decimal('0')
            cost_rate = cost_rates.get(user_id, default_cost_rate)
            
            revenue = hours * billing_rate
            cost = hours * cost_rate
            
            # Initialize client if needed
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
            
            # Initialize staff if needed
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
            
            # Accumulate
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
        
        # Format response
        clients_list = []
        for client_id, client in clients_data.items():
            gross_margin = client['total_revenue'] - client['total_cost']
            margin_percent = (
                float(gross_margin / client['total_revenue'] * 100)
                if client['total_revenue'] > 0 else 0
            )
            
            # Format staff details
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
        
        # Sort by revenue descending
        clients_list.sort(key=lambda x: x['total_revenue'], reverse=True)
        
        # Calculate total margin
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
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
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
        
        # =====================================================
        # OPTION A: Can only submit AFTER the week has ended
        # =====================================================
        today = timezone.now().date()
        week_end = timesheet.week_start + timedelta(days=6)  # Sunday
        
        if today <= week_end:
            days_remaining = (week_end - today).days + 1
            return Response({
                'error': f'Cannot submit timesheet until after the week ends.',
                'detail': f'This timesheet covers {timesheet.week_start.isoformat()} to {week_end.isoformat()}. '
                          f'You can submit starting {(week_end + timedelta(days=1)).isoformat()} (Monday).',
                'week_start': timesheet.week_start.isoformat(),
                'week_end': week_end.isoformat(),
                'days_remaining': days_remaining,
                'can_submit_on': (week_end + timedelta(days=1)).isoformat(),
            }, status=400)
        
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


@api_view(['GET'])
def timesheet_history(request):
    """
    Get all approved/invoiced/locked timesheets.
    Managers see all, members see only their own.
    """
    org = get_user_org(request.user)
    if not org:
        return Response({'error': 'No organization'}, status=400)
    
    membership = OrganizationMembership.objects.filter(
        user=request.user, organization=org
    ).first()
    
    if not membership:
        return Response({'error': 'No membership'}, status=403)
    
    # Base query - approved and locked timesheets
    timesheets = Timesheet.objects.filter(
        org=org,
        status__in=['approved', 'locked']
    ).select_related('user', 'approved_by').order_by('-week_start')
    
    # Non-managers only see their own
    if membership.role == 'member':
        timesheets = timesheets.filter(user=request.user)
    
    # Optional filters
    user_id = request.query_params.get('user_id')
    if user_id:
        timesheets = timesheets.filter(user_id=user_id)
    
    status = request.query_params.get('status')
    if status:
        timesheets = timesheets.filter(status=status)
    
    # Date range filter
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    if start_date:
        timesheets = timesheets.filter(week_start__gte=start_date)
    if end_date:
        timesheets = timesheets.filter(week_start__lte=end_date)
    
    result = []
    for ts in timesheets:
        result.append({
            'id': ts.id,
            'user_id': ts.user_id,
            'user_name': f"{ts.user.first_name} {ts.user.last_name}".strip() or ts.user.username,
            'user_email': ts.user.email,
            'week_start': ts.week_start.isoformat(),
            'week_end': ts.get_week_end().isoformat(),
            'status': ts.status,
            'total_hours': float(ts.total_hours),
            'billable_hours': float(ts.billable_hours),
            'non_billable_hours': float(ts.non_billable_hours),
            'total_amount': float(ts.total_amount),
            'submitted_at': ts.submitted_at.isoformat() if ts.submitted_at else None,
            'approved_at': ts.approved_at.isoformat() if ts.approved_at else None,
            'approved_by': ts.approved_by.username if ts.approved_by else None,
            'auto_submitted': ts.auto_submitted,  # ← NEW: Include auto_submitted flag
        })
    
    return Response({
        'count': len(result),
        'timesheets': result,
    })