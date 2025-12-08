from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, F, Q, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import timedelta, date
from decimal import Decimal

from .models import (
    BillingRate, Timesheet, Block, BlockAuditLog, 
    Client, TaskType, Organization, OrganizationMembership
)
from .serializers_billing import (
    BillingRateSerializer, TimesheetSummarySerializer, TimesheetDetailSerializer,
    ApprovalQueueItemSerializer, ClientSummarySerializer, BlockAuditLogSerializer,
    InvoiceExportSerializer
)


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
    
    return Response({
        'count': timesheets.count(),
        'timesheets': ApprovalQueueItemSerializer(timesheets, many=True).data
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