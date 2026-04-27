"""
tracker/services/rules/templates.py

The 7 starter templates for the rule system.

WHY A PYTHON DICT, NOT A DATABASE TABLE
---------------------------------------
Templates are versioned with the codebase. Adding a template = adding a
key here = next deploy ships it to all orgs. Changing a template's shape
is a code change that's reviewed and tested.

Rule INSTANCES (rows in OrgRoutingRule) are versioned with the database.
Each customer has their own; they evolve independently.

This is the right boundary: structure (templates) is code, content
(rule rows) is data.

USAGE
-----
    from tracker.services.rules.templates import (
        RULE_TEMPLATES,
        get_template,
        build_rule_from_template,
        validate_template_params,
    )

    # Build a rule row from a template selection
    template = get_template('assign_category_by_app_family')
    rule_kwargs = build_rule_from_template(
        template_id='assign_category_by_app_family',
        params={'app_family': 'taxwise', 'category': 'Tax Preparation'},
        org=tl_wall_org,
        priority=300,
    )
    OrgRoutingRule.objects.create(**rule_kwargs)
"""

from typing import Optional


# -----------------------------------------------------------------------------
# Template definitions
# -----------------------------------------------------------------------------

RULE_TEMPLATES = {

    # =============================================================
    # CATEGORIZATION
    # =============================================================

    'assign_category_by_app_family': {
        'label': 'Assign category by app family',
        'emoji': '🏷',
        'category': 'categorization',
        'runs_at': 'classifier',
        'description': 'Windows from a specific app always get this category.',
        'example': 'TaxWise → Tax Preparation',
        'fixed': {
            'match_type': 'exe_family',
            'action':     'assign_category',
        },
        'user_fields': [
            {
                'name': 'app_family',
                'label': 'When the user is in this app',
                'type': 'enum',
                'options_key': 'exe_families',  # populated server-side
                'maps_to': 'match_value',
                'required': True,
            },
            {
                'name': 'category',
                'label': 'Categorize as',
                'type': 'enum',
                'options_key': 'org_categories',
                'maps_to': 'target_category',
                'required': True,
            },
        ],
        'card_template': '{match_value} → {target_category}',
    },

    'assign_category_by_title_keyword': {
        'label': 'Assign category by title keyword',
        'emoji': '🏷',
        'category': 'categorization',
        'runs_at': 'classifier',
        'description': 'Windows whose title contains this keyword get this category.',
        'example': 'Title contains "1040" → Tax Preparation',
        'fixed': {
            'match_type': 'title_contains',
            'action':     'assign_category',
        },
        'user_fields': [
            {
                'name': 'keyword',
                'label': 'When the window title contains',
                'type': 'string',
                'maps_to': 'match_value',
                'required': True,
            },
            {
                'name': 'category',
                'label': 'Categorize as',
                'type': 'enum',
                'options_key': 'org_categories',
                'maps_to': 'target_category',
                'required': True,
            },
        ],
        'card_template': 'Title ~ "{match_value}" → {target_category}',
    },

    # =============================================================
    # ROUTING (existing behavior, now templated)
    # =============================================================

    'route_to_client_by_app_family': {
        'label': 'Route to client by app family',
        'emoji': '➡️',
        'category': 'routing',
        'runs_at': 'agent',
        'description': 'Switch to a specific client when this app is focused.',
        'example': 'TaxWise → Internal - Tax',
        'fixed': {
            'match_type': 'exe_family',
            'action':     'route_to_client',
        },
        'user_fields': [
            {
                'name': 'app_family',
                'label': 'When the user opens this app',
                'type': 'enum',
                'options_key': 'exe_families',
                'maps_to': 'match_value',
                'required': True,
            },
            {
                'name': 'target_client',
                'label': 'Switch to this client',
                'type': 'enum',
                'options_key': 'org_clients',
                'maps_to': 'target_client_id',
                'required': True,
            },
        ],
        'card_template': '{match_value} → {target_client_name}',
    },

    'route_to_client_by_folder_path': {
        'label': 'Route to client by folder path',
        'emoji': '➡️',
        'category': 'routing',
        'runs_at': 'agent',
        'description': 'Switch to a specific client when a file from this folder is open.',
        'example': '/Clients/Varacchi/ → Varacchi',
        'fixed': {
            'match_type': 'file_path_contains',
            'action':     'route_to_client',
        },
        'user_fields': [
            {
                'name': 'path_fragment',
                'label': 'When the file path contains',
                'type': 'string',
                'placeholder': r'\Clients\Varacchi\\',
                'maps_to': 'match_value',
                'required': True,
            },
            {
                'name': 'target_client',
                'label': 'Switch to this client',
                'type': 'enum',
                'options_key': 'org_clients',
                'maps_to': 'target_client_id',
                'required': True,
            },
        ],
        'card_template': 'Path ~ "{match_value}" → {target_client_name}',
    },

    # =============================================================
    # FLAGGING
    # =============================================================

    'flag_long_blocks': {
        'label': 'Flag long blocks for review',
        'emoji': '🚩',
        'category': 'flagging',
        'runs_at': 'post_save',
        'description': 'Set needs_review on any block longer than this duration.',
        'example': 'Blocks > 4h → flag with reason "Partner review required"',
        'fixed': {
            'match_type': 'duration_gt',
            'action':     'flag_for_review',
        },
        'user_fields': [
            {
                'name': 'min_minutes',
                'label': 'Flag blocks longer than (minutes)',
                'type': 'int',
                'maps_to': 'threshold_minutes',
                'required': True,
                'placeholder': '240',
            },
            {
                'name': 'reason',
                'label': 'Reason shown to reviewer',
                'type': 'string',
                'maps_to': 'flag_reason',
                'required': True,
                'placeholder': 'Over 4h — verify duration',
            },
        ],
        'card_template': 'Block > {threshold_minutes}min → flag: "{flag_reason}"',
    },

    # =============================================================
    # BILLING
    # =============================================================

    'mark_non_billable_inside_meeting': {
        'label': 'Mark non-billable inside meetings',
        'emoji': '💰',
        'category': 'billing',
        'runs_at': 'compaction',
        'description': (
            'When a foreground block is 100% inside a meeting window with '
            'an attributed client, mark it non-billable (kept for audit).'
        ),
        'example': '(no parameters — all-or-nothing rule)',
        'fixed': {
            'match_type': 'inside_meeting',
            'action':     'mark_non_billable',
        },
        'user_fields': [],
        'card_template': 'Foreground inside meeting → non-billable',
    },

    'cap_idle_duration': {
        'label': 'Cap idle duration',
        'emoji': '⏱',
        'category': 'billing',
        'runs_at': 'agent',
        'description': 'Close blocks where idle time exceeds this threshold.',
        'example': 'Idle > 20min → close block',
        'fixed': {
            'match_type': 'idle_gt',
            'action':     'cap_duration_at',
        },
        'user_fields': [
            {
                'name': 'max_idle_minutes',
                'label': 'Maximum idle duration (minutes)',
                'type': 'int',
                'maps_to': 'threshold_minutes',
                'required': True,
                'placeholder': '20',
            },
        ],
        'card_template': 'Idle > {threshold_minutes}min → close block',
    },
}


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def get_template(template_id: str) -> Optional[dict]:
    """Look up a template by id. Returns None if not found."""
    return RULE_TEMPLATES.get(template_id)


def list_templates() -> list:
    """Return all templates as a list (for the picker UI)."""
    return [
        {'id': tid, **tdef}
        for tid, tdef in RULE_TEMPLATES.items()
    ]


def list_templates_by_category(category: str) -> list:
    """Return only templates in a given category."""
    return [t for t in list_templates() if t['category'] == category]


def validate_template_params(template_id: str, params: dict) -> tuple[bool, str]:
    """
    Validate that params satisfy all required fields of the template.
    Returns (is_valid, error_message). error_message is '' on success.
    """
    template = get_template(template_id)
    if template is None:
        return False, f'Unknown template_id: {template_id!r}'

    for field in template['user_fields']:
        if field.get('required', True) and field['name'] not in params:
            return False, f'Missing required field: {field["name"]!r}'
        value = params.get(field['name'])
        if field.get('required', True) and (value is None or value == ''):
            return False, f'Required field {field["name"]!r} cannot be empty'

    return True, ''


def build_rule_from_template(
    template_id: str,
    params: dict,
    org,
    priority: int = 100,
    enabled: bool = True,
    description: str = '',
    created_by=None,
) -> dict:
    """
    Convert a (template_id, params) pair into kwargs ready for
    OrgRoutingRule.objects.create(**kwargs).

    Raises ValueError if validation fails.
    """
    is_valid, err = validate_template_params(template_id, params)
    if not is_valid:
        raise ValueError(err)

    template = get_template(template_id)

    # Start with the template's fixed fields
    kwargs = {
        'org': org,
        'priority': priority,
        'enabled': enabled,
        'description': description or f"Created from template: {template['label']}",
        'created_by': created_by,
        'category': template['category'],
        'runs_at': template['runs_at'],
        **template['fixed'],
    }

    # Apply user-supplied params via their maps_to
    for field in template['user_fields']:
        value = params.get(field['name'])
        kwargs[field['maps_to']] = value

    return kwargs