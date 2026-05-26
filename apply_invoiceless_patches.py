#!/usr/bin/env python3
"""
apply_invoiceless_patches.py

Drop-in script that applies all four backend patches for invoice-less firm
support. Idempotent — safe to run multiple times; it detects already-applied
patches and skips them.

USAGE (from project root, with Docker):
    docker compose cp apply_invoiceless_patches.py api:/tmp/
    docker compose exec api python /tmp/apply_invoiceless_patches.py
    docker compose restart api

OR from your Mac if you have a Python environment with the same code:
    cd ~/Projects/time_capture_fullstack
    python apply_invoiceless_patches.py

The patches are intentionally simple text replacements with sentinel comments
so they're easy to spot in code review.
"""
import re
import sys
from pathlib import Path


# Find the analytics_v2 package — script may be run from project root or anywhere
def find_analytics_v2_root() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "server" / "tracker" / "analytics_v2",                  # project root
        here / "tracker" / "analytics_v2",                              # inside server/
        Path.cwd() / "server" / "tracker" / "analytics_v2",            # cwd is project root
        Path.cwd() / "tracker" / "analytics_v2",                        # cwd is server/
        Path("/app/tracker/analytics_v2"),                              # inside Docker container
        Path("/app/server/tracker/analytics_v2"),
    ]
    for c in candidates:
        if c.exists() and (c / "permissions.py").exists():
            return c
    raise SystemExit(
        "Couldn't locate tracker/analytics_v2/. Run from project root or set "
        "the working directory so server/tracker/analytics_v2/ is findable."
    )


SENTINEL = "# v2-invoiceless-patch-applied"


def patch_permissions(root: Path) -> bool:
    """Add firm_invoices_here() helper at the end of permissions.py."""
    f = root / "permissions.py"
    src = f.read_text()
    if SENTINEL in src:
        print(f"  skip  {f.name} (already patched)")
        return False
    
    addition = f'''

# {SENTINEL}
def firm_invoices_here(org) -> bool:
    """
    Returns True if this org has ever recorded an Invoice in TimeTracker.
    Used by lenses to detect firms that log time but invoice elsewhere.
    """
    from tracker.models import Invoice
    return Invoice.objects.filter(org=org).exists()
'''
    f.write_text(src.rstrip() + addition)
    print(f"  edit  {f.name} (+firm_invoices_here helper)")
    return True


def patch_query(root: Path) -> bool:
    """Add invoiceless flag to the meta dict in execute_query()."""
    f = root / "query.py"
    src = f.read_text()
    if SENTINEL in src:
        print(f"  skip  {f.name} (already patched)")
        return False
    
    old_meta_block = '        "meta": {\n            "org_id": org.id,'
    if old_meta_block not in src:
        print(f"  WARN  {f.name}: meta block not found in expected form — manual review needed")
        return False
    
    insertion = '''    # v2-invoiceless-patch-applied
    from .permissions import firm_invoices_here
    invoiceless = not firm_invoices_here(org)
    
    '''
    # Insert the calculation just before the return statement
    src_new = src.replace(
        '    return {\n        "view"',
        insertion + 'return {\n        "view"',
    )
    
    # Add the invoiceless field at the end of the meta dict
    src_new = src_new.replace(
        '            "version": "2.0.0-alpha.1",\n        },',
        '            "version": "2.0.0-alpha.2",\n            "invoiceless": invoiceless,\n        },',
    )
    
    if src_new == src:
        print(f"  WARN  {f.name}: replacements didn't match — manual review needed")
        return False
    
    f.write_text(src_new)
    print(f"  edit  {f.name} (+invoiceless flag in meta)")
    return True


def patch_pulse(root: Path) -> bool:
    """Update Pulse lens to swap headline metrics for invoice-less firms."""
    f = root / "lenses" / "pulse.py"
    src = f.read_text()
    if SENTINEL in src:
        print(f"  skip  {f.name} (already patched)")
        return False
    
    # Replace the whole class body — safer than surgical replacements
    new_class = '''@register_lens("pulse")
class PulseLens(Lens):
    """{}
{}
    """
    label = "Pulse"
    
    def assemble(self, org, scope, time, compare=None):
        # v2-invoiceless-patch-applied
        from ..permissions import firm_invoices_here
        invoiceless = not firm_invoices_here(org)
        
        sections: list[Section] = []
        
        # Headline metrics adapt to scope AND invoice presence
        metric_ids = self._headline_metrics_for_scope(scope, invoiceless)
        sections.append(headline_row(metric_ids, org, scope, time, compare,
                                     section_id="headline"))
        
        # Needs attention — pass invoiceless flag down
        insights = generate_pulse_insights(org, scope, time, invoiceless=invoiceless)
        if insights:
            from ..types import Section
            insight_section = Section(
                id="needs_attention",
                type="section",
                title="Needs Attention",
                collapsible=False,
                children=insights,
            )
            sections.append(insight_section)
        
        return sections
    
    def _headline_metrics_for_scope(self, scope: Scope, invoiceless: bool = False) -> list[str]:
        if scope.type == "firm":
            if invoiceless:
                return ["revenue", "billable_hours",
                        "billable_utilization", "wip_total"]
            return ["invoiced_revenue", "realization_dollar",
                    "billable_utilization", "wip_total"]
        if scope.type == "client":
            if invoiceless:
                return ["revenue", "billable_hours",
                        "billable_utilization", "wip_total"]
            return ["invoiced_revenue", "realization_dollar",
                    "billable_hours", "wip_total"]
        if scope.type == "staff":
            return ["billable_hours", "total_hours",
                    "billable_utilization", "effective_rate"]
        return ["revenue", "billable_hours", "billable_utilization"]
'''.format(
        '"""',  # placeholder
        '"""',
    ).replace('"""""""\n"""""""\n    """', '')  # tidy up the placeholder hack
    
    # Find the existing class start and end (next @register_lens or EOF)
    pattern = re.compile(
        r'@register_lens\("pulse"\)\s*\nclass PulseLens\(Lens\):.*?(?=\n@register_lens|\nclass\s|\Z)',
        re.DOTALL,
    )
    if not pattern.search(src):
        print(f"  WARN  {f.name}: PulseLens class not found — manual review needed")
        return False
    
    new_class_clean = '''@register_lens("pulse")
class PulseLens(Lens):
    label = "Pulse"
    
    def assemble(self, org, scope, time, compare=None):
        # v2-invoiceless-patch-applied
        from ..permissions import firm_invoices_here
        invoiceless = not firm_invoices_here(org)
        
        sections: list[Section] = []
        metric_ids = self._headline_metrics_for_scope(scope, invoiceless)
        sections.append(headline_row(metric_ids, org, scope, time, compare,
                                     section_id="headline"))
        
        insights = generate_pulse_insights(org, scope, time, invoiceless=invoiceless)
        if insights:
            from ..types import Section
            insight_section = Section(
                id="needs_attention",
                type="section",
                title="Needs Attention",
                collapsible=False,
                children=insights,
            )
            sections.append(insight_section)
        
        return sections
    
    def _headline_metrics_for_scope(self, scope: Scope, invoiceless: bool = False) -> list[str]:
        if scope.type == "firm":
            if invoiceless:
                return ["revenue", "billable_hours",
                        "billable_utilization", "wip_total"]
            return ["invoiced_revenue", "realization_dollar",
                    "billable_utilization", "wip_total"]
        if scope.type == "client":
            if invoiceless:
                return ["revenue", "billable_hours",
                        "billable_utilization", "wip_total"]
            return ["invoiced_revenue", "realization_dollar",
                    "billable_hours", "wip_total"]
        if scope.type == "staff":
            return ["billable_hours", "total_hours",
                    "billable_utilization", "effective_rate"]
        return ["revenue", "billable_hours", "billable_utilization"]
'''
    
    src_new = pattern.sub(new_class_clean.rstrip(), src)
    f.write_text(src_new)
    print(f"  edit  {f.name} (swap headline metrics for invoice-less firms)")
    return True


def patch_insights(root: Path) -> bool:
    """Update insights engine: pass invoiceless, skip realization card when set."""
    f = root / "insights" / "engine.py"
    src = f.read_text()
    if SENTINEL in src:
        print(f"  skip  {f.name} (already patched)")
        return False
    
    # 1. Add invoiceless kwarg to generate_pulse_insights signature
    src_new = src.replace(
        "def generate_pulse_insights(\n    org: Organization,\n    scope: Scope,\n    time: TimeRange,\n) -> list[InsightCardPayload]:",
        "def generate_pulse_insights(\n    org: Organization,\n    scope: Scope,\n    time: TimeRange,\n    invoiceless: bool = False,  # v2-invoiceless-patch-applied\n) -> list[InsightCardPayload]:",
    )
    
    # 2. Pass invoiceless through to threshold generator
    src_new = src_new.replace(
        "insights.extend(_generate_threshold_insights(org, scope, time))",
        "insights.extend(_generate_threshold_insights(org, scope, time, invoiceless=invoiceless))",
    )
    
    # 3. Update threshold gen signature
    src_new = src_new.replace(
        "def _generate_threshold_insights(\n    org: Organization, scope: Scope, time: TimeRange\n) -> list[InsightCardPayload]:",
        "def _generate_threshold_insights(\n    org: Organization, scope: Scope, time: TimeRange, invoiceless: bool = False,\n) -> list[InsightCardPayload]:",
    )
    
    # 4. Gate the realization check
    src_new = src_new.replace(
        '    # ── Dollar realization below 85% ──\n    try:\n        rd = get_metric("realization_dollar").safe_compute(org, scope, time)',
        '    # ── Dollar realization below 85% ──\n    # Skip for invoice-less firms (their realization is structurally 0%, not a real problem)\n    if not invoiceless:\n      try:\n        rd = get_metric("realization_dollar").safe_compute(org, scope, time)',
    )
    
    if src_new == src:
        print(f"  WARN  {f.name}: no replacements matched — manual review needed")
        return False
    
    f.write_text(src_new)
    print(f"  edit  {f.name} (skip realization card for invoice-less firms)")
    return True


def patch_realization_lens(root: Path) -> bool:
    """Realization lens returns empty sections for invoice-less firms."""
    f = root / "lenses" / "realization.py"
    src = f.read_text()
    if SENTINEL in src:
        print(f"  skip  {f.name} (already patched)")
        return False
    
    # Insert the early-return block at the start of assemble()
    needle = (
        '    def assemble(self, org, scope, time, compare=None):\n'
        '        sections: list[Section] = []'
    )
    replacement = (
        '    def assemble(self, org, scope, time, compare=None):\n'
        '        # v2-invoiceless-patch-applied\n'
        '        from ..permissions import firm_invoices_here\n'
        '        if not firm_invoices_here(org):\n'
        '            return []  # Frontend renders EmptyStateInvoiceless from meta.invoiceless\n'
        '        \n'
        '        sections: list[Section] = []'
    )
    if needle not in src:
        print(f"  WARN  {f.name}: assemble() not found in expected form — manual review needed")
        return False
    
    f.write_text(src.replace(needle, replacement))
    print(f"  edit  {f.name} (empty sections for invoice-less firms)")
    return True


def main() -> int:
    print("Applying analytics v2 invoice-less patches…")
    root = find_analytics_v2_root()
    print(f"  package: {root}")
    print()
    
    any_changes = False
    any_changes |= patch_permissions(root)
    any_changes |= patch_query(root)
    any_changes |= patch_pulse(root)
    any_changes |= patch_insights(root)
    any_changes |= patch_realization_lens(root)
    
    print()
    if any_changes:
        print("Done. Restart your api container so changes take effect:")
        print("  docker compose restart api")
    else:
        print("Nothing to do — patches already applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
