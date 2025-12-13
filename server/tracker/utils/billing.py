# tracker/utils/billing.py
"""
Billing rate utilities for TimeTracker.
Apply rates when blocks are created or assigned to clients.
"""

from decimal import Decimal
from typing import Optional


def apply_billing_rate(block, org=None) -> Decimal:
    """
    Apply the appropriate billing rate to a block.
    
    Priority:
    1. User + Client specific rate (BillingRate)
    2. Client specific rate (BillingRate)
    3. User specific rate (BillingRate)
    4. Org default rate (Organization.billing_rate_default)
    5. Fallback default ($150)
    
    Args:
        block: Block instance (must have user, client, org)
        org: Organization (optional, will use block.org if not provided)
    
    Returns:
        The billing rate applied (Decimal)
    
    Side effects:
        Sets block.billing_rate and block.billing_amount
    """
    from tracker.models import BillingRate
    
    # Skip non-billable blocks
    if not getattr(block, 'is_billable', True):
        block.billing_rate = None
        block.billing_amount = Decimal('0')
        return Decimal('0')
    
    # Get org
    if not org:
        org = getattr(block, 'org', None)
    
    if not org:
        # Fallback default
        rate = Decimal('150.00')
        block.billing_rate = rate
        _calculate_amount(block, rate)
        return rate
    
    rate = None
    
    # 1. User + Client specific rate
    if block.user_id and block.client_id:
        rate_obj = BillingRate.objects.filter(
            org=org,
            user_id=block.user_id,
            client_id=block.client_id
        ).first()
        if rate_obj:
            rate = rate_obj.rate
    
    # 2. Client specific rate
    if not rate and block.client_id:
        rate_obj = BillingRate.objects.filter(
            org=org,
            client_id=block.client_id,
            user__isnull=True
        ).first()
        if rate_obj:
            rate = rate_obj.rate
    
    # 3. User specific rate
    if not rate and block.user_id:
        rate_obj = BillingRate.objects.filter(
            org=org,
            user_id=block.user_id,
            client__isnull=True
        ).first()
        if rate_obj:
            rate = rate_obj.rate
    
    # 4. Org default
    if not rate:
        rate = getattr(org, 'billing_rate_default', None)
    
    # 5. Fallback
    if not rate:
        rate = Decimal('150.00')
    
    # Apply to block
    block.billing_rate = rate
    _calculate_amount(block, rate)
    
    return rate


def _calculate_amount(block, rate: Decimal):
    """Calculate billing_amount from minutes and rate."""
    minutes = getattr(block, 'minutes', None)
    if minutes and rate:
        hours = Decimal(str(minutes)) / Decimal('60')
        block.billing_amount = hours * rate
    else:
        block.billing_amount = Decimal('0')


def apply_billing_rate_on_save(sender, instance, **kwargs):
    """
    Signal handler to apply billing rate before saving a block.
    
    Only applies rate if:
    1. Block is billable
    2. Block has a client assigned
    3. Block doesn't already have a rate set (or rate is zero/None)
    """
    # Only apply if block is billable
    if not getattr(instance, 'is_billable', True):
        return
    
    # Only apply if block has a client (client work is billable)
    if not instance.client_id:
        return
    
    # Only apply if rate not already set
    if instance.billing_rate and instance.billing_rate > 0:
        return
    
    apply_billing_rate(instance)