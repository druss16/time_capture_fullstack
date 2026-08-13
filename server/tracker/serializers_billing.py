# tracker/serializers_billing.py
# ADD TO YOUR EXISTING SERIALIZERS OR CREATE NEW FILE

from rest_framework import serializers
from decimal import Decimal
from django.contrib.auth import get_user_model
from .models import BillingRate, Timesheet, Block, BlockAuditLog, Client, TaskType, EmployeeCostRate, ClientBillingProfile

User = get_user_model()


class BillingRateSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True)
    client_name = serializers.CharField(source='client.name', read_only=True, allow_null=True)
    task_type_name = serializers.CharField(source='task_type.name', read_only=True, allow_null=True)
    
    class Meta:
        model = BillingRate
        fields = [
            'id', 'user', 'user_name', 'client', 'client_name', 
            'task_type', 'task_type_name', 'rate', 'effective_date', 
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class TimesheetSummarySerializer(serializers.ModelSerializer):
    """Lightweight serializer for timesheet lists"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    week_end = serializers.SerializerMethodField()
    
    class Meta:
        model = Timesheet
        fields = [
            'id', 'user', 'user_name', 'week_start', 'week_end', 'status',
            'total_hours', 'billable_hours', 'non_billable_hours', 'total_amount',
            'submitted_at', 'approved_at'
        ]
    
    def get_week_end(self, obj):
        return obj.get_week_end()


class TimesheetDetailSerializer(serializers.ModelSerializer):
    """Full timesheet with blocks"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True, allow_null=True)
    rejected_by_name = serializers.CharField(source='rejected_by.username', read_only=True, allow_null=True)
    week_end = serializers.SerializerMethodField()
    blocks = serializers.SerializerMethodField()
    daily_breakdown = serializers.SerializerMethodField()
    client_breakdown = serializers.SerializerMethodField()
    
    class Meta:
        model = Timesheet
        fields = [
            'id', 'user', 'user_name', 'week_start', 'week_end', 'status',
            'total_hours', 'billable_hours', 'non_billable_hours', 'total_amount',
            'submitted_at', 'submitted_notes',
            'approved_by', 'approved_by_name', 'approved_at', 'approval_notes',
            'rejected_by', 'rejected_by_name', 'rejected_at', 'rejection_reason',
            'blocks', 'daily_breakdown', 'client_breakdown',
            'created_at', 'updated_at'
        ]
    
    def get_week_end(self, obj):
        return obj.get_week_end()
    
    def get_blocks(self, obj):
        blocks = obj.blocks.select_related('client', 'task_type').order_by('start')
        return TimesheetBlockSerializer(blocks, many=True).data
    
    def get_daily_breakdown(self, obj):
        """Hours per day of the week"""
        from datetime import timedelta
        from django.db.models import Sum, Q
        
        breakdown = {}
        for i in range(7):
            day = obj.week_start + timedelta(days=i)
            day_blocks = obj.blocks.filter(day=day)
            totals = day_blocks.aggregate(
                total=Sum('minutes'),
                billable=Sum('minutes', filter=Q(is_billable=True))
            )
            breakdown[day.strftime('%Y-%m-%d')] = {
                'day_name': day.strftime('%A'),
                'total_hours': round(Decimal(totals['total'] or 0) / 60, 2),
                'billable_hours': round(Decimal(totals['billable'] or 0) / 60, 2),
            }
        return breakdown
    
    def get_client_breakdown(self, obj):
        """Hours and amount per client"""
        from django.db.models import Sum, F, Q
        
        breakdown = obj.blocks.values(
            'client__id', 'client__name'
        ).annotate(
            total_minutes=Sum('minutes'),
            billable_minutes=Sum('minutes', filter=Q(is_billable=True)),
            amount=Sum('billing_amount')
        ).order_by('-total_minutes')
        
        return [
            {
                'client_id': item['client__id'],
                'client_name': item['client__name'] or 'Unassigned',
                'total_hours': round(Decimal(item['total_minutes'] or 0) / 60, 2),
                'billable_hours': round(Decimal(item['billable_minutes'] or 0) / 60, 2),
                'amount': item['amount'] or Decimal('0.00'),
            }
            for item in breakdown
        ]


class TimesheetBlockSerializer(serializers.ModelSerializer):
    """Block within a timesheet context"""
    client_name = serializers.CharField(source='client.name', read_only=True, allow_null=True)
    task_type_name = serializers.CharField(source='task_type.name', read_only=True, allow_null=True)
    hours = serializers.SerializerMethodField()
    invoice_description = serializers.SerializerMethodField()
    
    class Meta:
        model = Block
        fields = [
            'id', 'day', 'start', 'end', 'minutes', 'hours',
            'client', 'client_name', 'task_type', 'task_type_name',
            'app_name', 'window_title', 'notes',
            'is_billable', 'billing_rate', 'billing_amount',
            'description_override', 'invoice_description',
            'is_categorized', 'approved'
        ]
    
    def get_hours(self, obj):
        if obj.minutes:
            return round(Decimal(obj.minutes) / 60, 2)
        return Decimal('0.00')
    
    def get_invoice_description(self, obj):
        """Return override or auto-generated description"""
        if obj.description_override:
            return obj.description_override
        # Auto-generate from context
        parts = []
        if obj.task_type:
            parts.append(obj.task_type.name)
        if obj.app_name:
            parts.append(f"({obj.app_name})")
        if obj.notes:
            parts.append(f"- {obj.notes}")
        return ' '.join(parts) or 'Professional services'


class WeeklyTimesheetViewSerializer(serializers.Serializer):
    """
    Employee-facing weekly view with editable entries.
    Shows hours per client/task per day.
    """
    week_start = serializers.DateField()
    week_end = serializers.DateField()
    status = serializers.CharField()
    
    # Grid data: rows are client+task, columns are days
    entries = serializers.SerializerMethodField()
    
    # Totals
    daily_totals = serializers.DictField()
    client_totals = serializers.DictField()
    grand_total = serializers.DecimalField(max_digits=6, decimal_places=2)
    
    def get_entries(self, obj):
        # This is computed in the view
        return obj.get('entries', [])


class ClientSummarySerializer(serializers.Serializer):
    """Manager/billing view - hours and amounts by client"""
    client_id = serializers.IntegerField()
    client_name = serializers.CharField()
    client_code = serializers.CharField()
    
    total_hours = serializers.DecimalField(max_digits=8, decimal_places=2)
    billable_hours = serializers.DecimalField(max_digits=8, decimal_places=2)
    non_billable_hours = serializers.DecimalField(max_digits=8, decimal_places=2)
    
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    
    # Breakdown by staff
    staff_breakdown = serializers.ListField(child=serializers.DictField())
    
    # Breakdown by task type
    task_breakdown = serializers.ListField(child=serializers.DictField())


class ApprovalQueueItemSerializer(serializers.ModelSerializer):
    """Timesheet in approval queue"""
    user_name = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    week_end = serializers.SerializerMethodField()
    days_pending = serializers.SerializerMethodField()
    
    class Meta:
        model = Timesheet
        fields = [
            'id', 'user', 'user_name', 'user_email',
            'week_start', 'week_end', 'status',
            'total_hours', 'billable_hours', 'total_amount',
            'submitted_at', 'submitted_notes', 'days_pending'
        ]
    
    def get_week_end(self, obj):
        return obj.get_week_end()
    
    def get_days_pending(self, obj):
        if obj.submitted_at:
            from django.utils import timezone
            delta = timezone.now() - obj.submitted_at
            return delta.days
        return 0


class BlockAuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True, allow_null=True)
    
    class Meta:
        model = BlockAuditLog
        fields = [
            'id', 'block', 'action', 'user', 'user_name',
            'field_name', 'old_value', 'new_value',
            'snapshot', 'ip_address', 'notes', 'timestamp'
        ]


# ===============================
# INVOICE/EXPORT SERIALIZERS
# ===============================

class InvoiceLineItemSerializer(serializers.Serializer):
    """Single line item for invoice export"""
    date = serializers.DateField()
    description = serializers.CharField()
    hours = serializers.DecimalField(max_digits=6, decimal_places=2)
    rate = serializers.DecimalField(max_digits=10, decimal_places=2)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    staff_initials = serializers.CharField()
    task_type = serializers.CharField(allow_null=True)


class InvoiceExportSerializer(serializers.Serializer):
    """Full invoice export data"""
    client_id = serializers.IntegerField()
    client_name = serializers.CharField()
    client_code = serializers.CharField()
    
    invoice_date = serializers.DateField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    
    line_items = InvoiceLineItemSerializer(many=True)
    
    subtotal_hours = serializers.DecimalField(max_digits=8, decimal_places=2)
    subtotal_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    
    # Optional: tax, discounts, etc.
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0'))
    tax_amount = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class EmployeeCostRateSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    
    class Meta:
        model = EmployeeCostRate
        fields = [
            'id', 'user', 'user_name', 'cost_rate',
            'effective_date', 'end_date', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_user_name(self, obj):
        if obj.user:
            name = f"{obj.user.first_name} {obj.user.last_name}".strip()
            return name or obj.user.username
        return None
    
    def create(self, validated_data):
        # Auto-set organization from request
        request = self.context.get('request')
        if request and hasattr(request, 'membership'):
            validated_data['organization'] = request.membership.organization
        return super().create(validated_data)


class ClientBillingProfileSerializer(serializers.ModelSerializer):
    """Per-client billing arrangement. Read-only helpers surface the client name,
    the QB customer fallback, and human labels so the settings modal can render
    without extra round-trips."""
    client_name = serializers.CharField(source='client.name', read_only=True)
    fallback_customer_id = serializers.CharField(source='client.quickbooks_id', read_only=True, allow_null=True)
    billing_type_display = serializers.CharField(source='get_billing_type_display', read_only=True)
    billing_system_display = serializers.CharField(source='get_billing_system_display', read_only=True)

    class Meta:
        model = ClientBillingProfile
        fields = [
            'id', 'client', 'client_name',
            'billing_type', 'billing_type_display',
            'flat_amount', 'flat_period',
            'billing_system', 'billing_system_display',
            'external_customer_id', 'external_customer_name', 'default_item_name',
            'counts_billable_utilization',
            'fallback_customer_id', 'notes', 'updated_at',
        ]
        read_only_fields = [
            'id', 'client', 'client_name', 'fallback_customer_id',
            'billing_type_display', 'billing_system_display', 'updated_at',
        ]
