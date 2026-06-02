"""
Confidence-graded client inference for the TimeTracker agent.

Public API:
    Evidence              — a single observation pointing to a client
    InferenceResult       — the engine's output (client_id + confidence + evidence)
    WindowContext         — input snapshot of the current window
    SCHEMA_VERSION        — version tag for the serialized format

    current_strength(evidence)        — current evidence strength after decay
    apply_decay_to_inference(result)  — recompute a stored result's confidence

    infer_client(ctx, clients, ...)   — main entry point: collect + compute
    compute_inference(evidence_list)  — lower-level: just compute from evidence
    collect_all_evidence(...)         — lower-level: just collect, no scoring

Usage:
    from windows_agent.inference import WindowContext, infer_client

    ctx = WindowContext(
        title="Holly Corbett, Inc - QuickBooks Accountant Desktop",
        app_name="QuickBooks",
        exe_name="qbw.exe",
        file_path=None,
    )
    result = infer_client(
        ctx,
        clients=client_list,
        learned_rules=rules,
        firm_name_patterns=["T.L. Wall Accounting", "TL Wall"],
        internal_client_id=42,
    )

    # result.client_id, result.confidence, result.evidence, ...
    # result.is_high_confidence, result.is_stale, result.disagreement, ...
"""

from .evidence import (
    Evidence,
    InferenceResult,
    WindowContext,
    SCHEMA_VERSION,
)

from .decay import (
    current_strength,
    is_expired,
    apply_decay_to_inference,
)

from .engine import (
    infer_client,
    compute_inference,
)

from .collectors import (
    collect_all_evidence,
    # Tier 1
    collect_tax_software_evidence,
    collect_qb_company_file_evidence,
    collect_file_path_evidence,
    collect_title_alias_evidence,
    collect_manual_override_evidence,
    # Tier 2
    collect_calendar_evidence,
    collect_url_domain_evidence,
    collect_email_thread_evidence,
    collect_continuity_evidence,
    # Tier 3
    collect_learned_pattern_evidence,
    # Tier 4
    collect_idle_evidence,
    collect_generic_browser_evidence,
    collect_personal_app_evidence,
    collect_firm_name_evidence,
)

__all__ = [
    # Schemas
    'Evidence',
    'InferenceResult',
    'WindowContext',
    'SCHEMA_VERSION',
    # Decay
    'current_strength',
    'is_expired',
    'apply_decay_to_inference',
    # Engine
    'infer_client',
    'compute_inference',
    # Collectors
    'collect_all_evidence',
    'collect_tax_software_evidence',
    'collect_qb_company_file_evidence',
    'collect_file_path_evidence',
    'collect_title_alias_evidence',
    'collect_manual_override_evidence',
    'collect_calendar_evidence',
    'collect_url_domain_evidence',
    'collect_email_thread_evidence',
    'collect_continuity_evidence',
    'collect_learned_pattern_evidence',
    'collect_idle_evidence',
    'collect_generic_browser_evidence',
    'collect_personal_app_evidence',
    'collect_firm_name_evidence',
]
