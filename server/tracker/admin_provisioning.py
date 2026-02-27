"""
tracker/admin_provisioning.py

Admin registration for provisioning models.
Import in your admin.py:
    from tracker.admin_provisioning import *
"""

from django.contrib import admin
from tracker.models_provisioning import OnboardingBatch, DeviceProvisioningMap


class DeviceProvisioningMapInline(admin.TabularInline):
    model = DeviceProvisioningMap
    extra = 0
    readonly_fields = ('status', 'paired_device', 'paired_user', 'paired_at', 'match_method')
    fields = (
        'machine_hostname', 'windows_username', 'email', 'display_name',
        'role', 'billing_rate', 'status', 'match_method', 'paired_at',
    )


@admin.register(OnboardingBatch)
class OnboardingBatchAdmin(admin.ModelAdmin):
    list_display = (
        'organization', 'status', 'total_users', 'total_devices',
        'devices_paired', 'pair_percentage', 'created_at',
    )
    list_filter = ('status', 'organization')
    readonly_fields = (
        'total_users', 'total_devices', 'total_clients',
        'devices_paired', 'created_at', 'updated_at', 'completed_at',
    )
    inlines = [DeviceProvisioningMapInline]
    
    def pair_percentage(self, obj):
        return f'{obj.pair_percentage}%'
    pair_percentage.short_description = 'Paired %'


@admin.register(DeviceProvisioningMap)
class DeviceProvisioningMapAdmin(admin.ModelAdmin):
    list_display = (
        'machine_hostname', 'email', 'display_name', 'role',
        'status', 'match_method', 'paired_at', 'organization',
    )
    list_filter = ('status', 'organization', 'role')
    search_fields = ('machine_hostname', 'windows_username', 'email', 'display_name')
    readonly_fields = ('paired_device', 'paired_user', 'paired_at', 'match_method', 'error_message')
    
    fieldsets = (
        ('Device Matching', {
            'fields': ('organization', 'batch', 'machine_hostname', 'windows_username')
        }),
        ('Target User', {
            'fields': ('email', 'display_name', 'role', 'billing_rate', 'cost_rate')
        }),
        ('Pairing Result', {
            'fields': ('status', 'paired_device', 'paired_user', 'paired_at', 'match_method', 'error_message')
        }),
    )