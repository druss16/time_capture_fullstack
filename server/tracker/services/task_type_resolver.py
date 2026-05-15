"""
TaskType resolution and validation.

Resolves which TaskTypes are allowed for a given (client, user) pair, and
validates that a Block's task_type assignment is legal before committing.

INTEGRATION WITH classification_state
-------------------------------------
The validator is called BEFORE a Block transitions to state='committed'.
It does NOT mutate the Block — the caller is responsible for the state
transition. This keeps the resolver pure and the state machine in one place.

Typical flow:
    block.classification_state == 'proposed'
    user clicks Confirm in UI
    → validate_block_task_type(block, task_type, user)
        returns (True, '') → caller transitions block to 'committed'
        returns (False, reason) → UI shows error, block stays 'proposed'

MATRIX RULES
------------
Matrix rules (which staff can use which TaskType for which Client) are
stored as OrgRoutingRule rows with:
    category   = 'billing'
    runs_at    = 'classifier'  (or 'post_save')
    source     = 'cch_axcess_sync'  (or 'manual')
    match_type = 'task_type_matrix'
    match_value = JSON: {"client_id": 42, "task_type_id": 7, "user_id": 12}
                  (any field can be "*" for wildcard)
    action     = 'mark_non_billable' | 'suppress' | 'flag_for_review'

We add 'task_type_matrix' to MATCH_TYPE_CHOICES for clarity in admin.
"""

import json
import logging
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import Q

from tracker.models import (
    Block,
    Client,
    OrgRoutingRule,
    TaskType,
)
from tracker.models_task_type_sets import (
    CategoryTaskTypeMapping,
    ClientTaskType,
    TaskTypeSet,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ============================================================================
# Resolution — which TaskTypes are allowed for this client/user?
# ============================================================================

def resolve_allowed_task_types(client: Optional[Client], user=None):
    """
    Return the QuerySet of TaskTypes allowed for the given client/user pair.

    RESOLUTION ORDER:
      1. If client is None: return all active TaskTypes for the user's org.
      2. If client has ClientTaskType rows: use them (custom mode).
         - allowed=True rows are included
         - allowed=False rows are explicitly excluded
         - TaskTypes with no row default to "allowed" if also in the
           resolved default set (see step 3).
      3. Else if Client.default_task_type_set is set: use that set's members.
      4. Else if org has a TaskTypeSet with is_default=True: use that set.
      5. Else: all active TaskTypes for the org.

    Returns None to signal "no constraint" (i.e. all org TaskTypes allowed)
    so the caller can short-circuit validation.

    Returns a queryset of TaskType objects otherwise.
    """
    if client is None:
        if user is None:
            return None
        # No client context — return all active types for user's org via their
        # memberships. If user belongs to multiple orgs, caller should pass client.
        return TaskType.objects.filter(is_active=True)

    org = client.org

    # ---- Step 2: explicit per-client overrides (custom mode) ----
    overrides = ClientTaskType.objects.filter(client=client).select_related('task_type')
    if overrides.exists():
        # Custom mode: union of explicitly-allowed rows + any default-set
        # members not explicitly forbidden.
        explicit_allowed_ids = set(
            overrides.filter(allowed=True).values_list('task_type_id', flat=True)
        )
        explicit_forbidden_ids = set(
            overrides.filter(allowed=False).values_list('task_type_id', flat=True)
        )

        # Start from the default-set members
        default_ids = _resolve_default_set_ids(client, org)
        # Union with explicit allows, minus explicit forbids
        final_ids = (default_ids | explicit_allowed_ids) - explicit_forbidden_ids

        return TaskType.objects.filter(
            id__in=final_ids,
            is_active=True,
        ).order_by('sort_order', 'name')

    # ---- Steps 3/4/5: fall back to default-set resolution ----
    default_ids = _resolve_default_set_ids(client, org)
    if default_ids:
        return TaskType.objects.filter(
            id__in=default_ids,
            is_active=True,
        ).order_by('sort_order', 'name')

    # Step 5: no constraint at all — all org TaskTypes
    return TaskType.objects.filter(org=org, is_active=True).order_by('sort_order', 'name')


def _resolve_default_set_ids(client: Client, org) -> set:
    """
    Helper: returns the set of TaskType IDs that come from the resolved
    default set for this client. Returns empty set if no default set found.
    """
    # Client-specific default set wins
    if client.default_task_type_set_id:
        return set(
            client.default_task_type_set.task_types.filter(
                is_active=True,
            ).values_list('id', flat=True)
        )

    # Org-level default set
    org_default = TaskTypeSet.objects.filter(org=org, is_default=True).first()
    if org_default:
        return set(
            org_default.task_types.filter(is_active=True).values_list('id', flat=True)
        )

    return set()


# ============================================================================
# Validation — is this assignment legal?
# ============================================================================

def validate_block_task_type(block: Block, task_type: TaskType, user=None) -> tuple:
    """
    Pre-flight validation before a Block transitions to 'committed' state.

    Does NOT modify the block. Caller is responsible for state transitions.

    Returns:
        (True, '')                      → assignment is valid, proceed
        (False, 'reason string')        → assignment is invalid, abort
    """
    # ---- 1. Basic sanity ----
    if task_type is None:
        return False, 'TaskType is required.'

    if block is None:
        return False, 'Block is required.'

    # ---- 2. Org consistency ----
    if block.org_id != task_type.org_id:
        return False, (
            f"TaskType '{task_type.name}' belongs to a different org "
            f'({task_type.org_id}) than the block ({block.org_id}).'
        )

    # ---- 3. TaskType must be active ----
    if not task_type.is_active:
        return False, f"TaskType '{task_type.code or task_type.name}' is inactive."

    # ---- 4. Client allow-list ----
    if block.client_id:
        allowed = resolve_allowed_task_types(block.client, user=user)
        if allowed is not None:
            allowed_ids = set(allowed.values_list('id', flat=True))
            if task_type.id not in allowed_ids:
                return False, (
                    f"TaskType '{task_type.code or task_type.name}' is not "
                    f"allowed for client '{block.client.name}'. "
                    f'Allowed: {", ".join(sorted(t.code or t.name for t in allowed))}.'
                )

    # ---- 5. Matrix rule check (OrgRoutingRule with match_type='task_type_matrix') ----
    matrix_blocked, matrix_reason = _check_matrix_rules(block, task_type, user)
    if matrix_blocked:
        return False, matrix_reason

    return True, ''


def _check_matrix_rules(block: Block, task_type: TaskType, user) -> tuple:
    """
    Evaluate OrgRoutingRule matrix rules against this (block, task_type, user).

    Matrix rules use:
        match_type  = 'task_type_matrix'
        match_value = JSON string: {"client_id": <int|"*">,
                                    "task_type_id": <int|"*">,
                                    "user_id": <int|"*">}
        action      = 'mark_non_billable' (warn but allow) — returns (False, '') here
                    | 'suppress'          (block) — returns (True, reason)
                    | 'flag_for_review'   (warn but allow) — returns (False, '')

    Only 'suppress' actions BLOCK the commit. Other actions are advisory
    and handled downstream (e.g. mark_non_billable is applied when the block
    is actually saved).

    Returns (blocked: bool, reason: str)
    """
    matrix_rules = OrgRoutingRule.objects.filter(
        org=block.org,
        enabled=True,
        match_type='task_type_matrix',
    ).order_by('-priority', 'id')

    target_user_id = (user.id if user else block.user_id)

    for rule in matrix_rules:
        try:
            match_value = json.loads(rule.match_value)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                'Matrix rule %s has invalid JSON match_value: %r',
                rule.id, rule.match_value,
            )
            continue

        if not _matrix_value_matches(match_value, block, task_type, target_user_id):
            continue

        # Rule fires. Only 'suppress' blocks.
        if rule.action == 'suppress':
            return True, (
                f'Matrix rule blocks this combination: '
                f"client={block.client.name if block.client else 'none'}, "
                f"task_type={task_type.code or task_type.name}, "
                f'staff={target_user_id}. '
                f"Reason: {rule.description or rule.flag_reason or 'rule fired'}."
            )

        # mark_non_billable / flag_for_review are advisory — log but allow
        logger.info(
            'Matrix rule %s fired (advisory) for block %s, task_type %s, user %s',
            rule.id, block.id, task_type.id, target_user_id,
        )

    return False, ''


def _matrix_value_matches(match_value: dict, block: Block, task_type: TaskType, user_id) -> bool:
    """
    Check if a matrix rule's match_value JSON matches the given combination.

    Each field can be a specific ID or "*" for wildcard. Missing fields
    are treated as "*".
    """
    rule_client = match_value.get('client_id', '*')
    rule_tt = match_value.get('task_type_id', '*')
    rule_user = match_value.get('user_id', '*')

    if rule_client != '*' and rule_client != block.client_id:
        return False
    if rule_tt != '*' and rule_tt != task_type.id:
        return False
    if rule_user != '*' and rule_user != user_id:
        return False
    return True


# ============================================================================
# Convenience: commit helper that wraps validation + state transition
# ============================================================================

def commit_block_with_task_type(block: Block, task_type: TaskType, user, source: str = 'user') -> tuple:
    """
    Convenience helper: validate, then transition block to 'committed' state
    with proper audit fields set.

    This is what your views should call when a user confirms a block.

    Args:
        block: Block instance (will be modified and saved)
        task_type: TaskType to assign
        user: User performing the action (for audit trail)
        source: state_changed_by value
                ('user', 'user_edit', 'admin_bulk', 'classifier', etc.)

    Returns:
        (True, '')                → block committed, saved
        (False, 'reason')         → validation failed, block NOT modified

    Caller is expected to wrap this in a try/except for any IntegrityError
    from the save itself.
    """
    from django.utils import timezone

    ok, reason = validate_block_task_type(block, task_type, user=user)
    if not ok:
        return False, reason

    block.task_type = task_type

    # Apply billing rate from override or TaskType default
    if block.client_id:
        override = ClientTaskType.objects.filter(
            client=block.client,
            task_type=task_type,
        ).first()
        if override and override.override_rate is not None:
            block.billing_rate = override.override_rate
        elif task_type.default_rate is not None:
            block.billing_rate = task_type.default_rate

    block.is_billable = task_type.is_billable

    # Transition state
    block.classification_state = 'committed'
    block.state_changed_at = timezone.now()
    block.state_changed_by = source

    # Legacy flags for backwards compatibility with old views
    block.is_categorized = True
    if not block.categorized_at:
        block.categorized_at = timezone.now()
    block.categorized_by = 'manual' if source in ('user', 'user_edit') else 'ai'

    # force_classifier=True lets us update committed blocks if user changes
    # their mind via the disagreement-resolution flow.
    block.save(force_classifier=True)

    return True, ''

# ============================================================================
# Category -> TaskType resolution (Layer 1 -> Layer 2 bridge)
# ============================================================================

def resolve_task_type_for_category(org, category_str):
    """
    Map a canonical classifier category string to this org's TaskType.

    Reads the per-firm CategoryTaskTypeMapping table. This is the bridge
    from Layer 1 (the classifier's universal category vocabulary) to
    Layer 2 (this firm's TaskType records).

    Called from ClassificationService.apply() to set Block.task_type, and
    by the billing export.

    Args:
        org: Organization instance (or org_id-bearing object)
        category_str: a canonical category string, e.g. "Tax Preparation"

    Returns:
        TaskType instance if a mapping exists, else None.
        None is a valid, expected result — the caller leaves
        Block.task_type unset (the block shows as uncategorized until a
        mapping is added or a user assigns one manually).
    """
    if not org or not category_str:
        return None

    category_str = category_str.strip()
    if not category_str:
        return None

    mapping = (
        CategoryTaskTypeMapping.objects
        .filter(org=org, category__iexact=category_str)
        .select_related('task_type')
        .first()
    )
    if mapping is None:
        return None

    return mapping.task_type