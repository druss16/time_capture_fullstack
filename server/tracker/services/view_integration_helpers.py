"""
View integration helpers for the TaskType matrix validator.

Your existing commit paths in views.py write `category_hours` (a dict of
{category_name: hours}) and don't set `block.task_type` directly. This helper
bridges that gap: it tries to map the category string to a TaskType for the
org, and if successful, runs the matrix validator.

USAGE PATTERNS
==============

Pattern A — block already has a task_type set explicitly:
    Use commit_block_with_task_type() from task_type_resolver.py directly.

Pattern B — block has category_hours but no task_type:
    Call validate_category_assignment(block, category_string, user)
    Returns (ok, reason, resolved_task_type_or_None).
    If ok is False, return 400 with reason.
    If ok is True and resolved_task_type is not None, set block.task_type
    to that resolved TaskType for matrix audit purposes.

Pattern C — bulk path with no task_type at all:
    Call validate_category_assignment() per block; collect failures into
    a results['errors'] list and skip those blocks.
"""

import logging
from typing import Optional, Tuple

from tracker.models import Block, Client, TaskType
from tracker.services.task_type_resolver import validate_block_task_type

logger = logging.getLogger(__name__)


def resolve_category_to_task_type(org, category_string: str) -> Optional[TaskType]:
    """
    Map a category string (e.g. "Tax Preparation", "Audit") to a TaskType
    for the given org.

    Strategy:
      1. Exact case-insensitive name match
      2. Exact case-insensitive code match
      3. Substring match on the category string

    Returns the TaskType or None if no match (which means the validator
    can't enforce the matrix for this block — it'll be allowed through).
    """
    if not category_string:
        return None

    cat_lower = category_string.lower().strip()

    # 1. Exact name match
    tt = TaskType.objects.filter(
        org=org, is_active=True, name__iexact=cat_lower,
    ).first()
    if tt:
        return tt

    # 2. Exact code match
    tt = TaskType.objects.filter(
        org=org, is_active=True, code__iexact=cat_lower,
    ).first()
    if tt:
        return tt

    # 3. Substring (e.g. "tax preparation" → matches name="Tax Preparation - 1040")
    tt = TaskType.objects.filter(
        org=org, is_active=True, name__icontains=cat_lower,
    ).first()
    if tt:
        return tt

    return None


def validate_category_assignment(
    block: Block,
    category_string: str,
    user=None,
) -> Tuple[bool, str, Optional[TaskType]]:
    """
    Validate that this category assignment is legal for the block's
    client, by resolving the category to a TaskType and running the matrix.

    Returns:
        (True, '', task_type) if valid, or no matching TaskType exists
        (False, 'reason', task_type) if matrix rule blocks the assignment

    If no matching TaskType is found, returns (True, '', None) — the
    validator can't enforce what it can't resolve. This is the "permissive"
    behavior; flip the DEFAULT_STRICT flag below to make this stricter.
    """
    DEFAULT_STRICT = False  # Flip to True to require all categories map to a TaskType

    org = block.org
    tt = resolve_category_to_task_type(org, category_string)

    if tt is None:
        if DEFAULT_STRICT:
            return False, (
                f"Category '{category_string}' does not map to any TaskType "
                f'in your firm. Add a matching TaskType in Settings → Task Types.'
            ), None
        # Permissive: allow without matrix enforcement
        logger.info(
            'No TaskType found for category "%s" (org %s); allowing without matrix check',
            category_string, org.id,
        )
        return True, '', None

    ok, reason = validate_block_task_type(block, tt, user=user)
    if not ok:
        return False, reason, tt

    return True, '', tt


def apply_resolved_task_type(block: Block, task_type: Optional[TaskType]):
    """
    If the category was successfully resolved to a TaskType, set it on
    the block so downstream code (billing, audit) has the link.

    Does NOT save — caller is responsible.
    """
    if task_type is not None:
        block.task_type = task_type
        # Don't overwrite billing_rate here — the existing view code may
        # have its own rate logic. Only the explicit commit_block_with_task_type
        # path manages billing_rate.