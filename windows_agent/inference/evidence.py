"""
Evidence schemas for the inference engine.

These are pure data structures. No logic. The inference engine consumes
Evidence objects and produces InferenceResult objects.

Versioning: any change to these dataclasses requires a schema version bump
because they're serialized into RawEvent.inference and stored long-term.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

SCHEMA_VERSION = "1.0"


# =============================================================================
# Evidence — a single piece of information suggesting which client is active
# =============================================================================

@dataclass
class Evidence:
    """
    A single observation that points to (or against) a specific client.

    Each evidence source produces zero or more Evidence objects per
    window-change event. The inference engine combines them into a single
    InferenceResult.
    """

    source: str
    """
    The detector that produced this evidence. One of:
      - 'tax_software_taxpayer'        (Tier 1, 0.95)
      - 'qb_company_file'              (Tier 1, 0.95)
      - 'file_path_client_folder'      (Tier 1, 0.90)
      - 'title_alias_match'            (Tier 1, 0.85)
      - 'manual_user_override'         (Tier 1, 0.85)
      - 'calendar_event_tag'           (Tier 2, 0.75)
      - 'url_domain_match'             (Tier 2, 0.65)
      - 'email_thread_match'           (Tier 2, 0.60)
      - 'recent_window_continuity'     (Tier 2, 0.40)
      - 'learned_pattern'              (Tier 3, 0.30)

    Anti-evidence sources (negative effect on confidence):
      - 'os_idle'                      (Tier 4, forces 0.0)
      - 'generic_browser_tab'          (Tier 4, caps at 0.5)
      - 'personal_app_foreground'      (Tier 4, caps at 0.3)
      - 'firm_name_in_title'           (Tier 4, routes to Internal)
    """

    client_id: Optional[int]
    """
    The client this evidence points to. None for anti-evidence that doesn't
    name a specific client (e.g., 'os_idle' applies to all candidates).
    """

    strength: float
    """
    0.0 to 1.0 — the evidence's max contribution to confidence when fresh.
    Decays linearly over freshness_window_seconds to 0.0.
    """

    detected_at: datetime
    """
    Timezone-aware datetime when this evidence was observed. Required for
    decay calculation.
    """

    freshness_window_seconds: int = 900  # 15 minutes default
    """
    How long this evidence remains valid before decaying to zero. Most
    evidence uses the default 15-min linear decay. Some sources (e.g., a
    calendar event that's currently active) may extend this.
    """

    detail: Dict[str, Any] = field(default_factory=dict)
    """
    Structured data about the match. Keys vary by source. Examples:
      tax_software_taxpayer: {'taxpayer_name': str, 'return_type': str}
      qb_company_file: {'file_name': str}
      file_path_client_folder: {'folder_segment': str, 'depth': int}
      title_alias_match: {'matched_alias': str, 'position_in_title': int}
      manual_user_override: {'set_by': 'user', 'previous_client_id': int}
    """

    # ----- Convenience properties -----

    @property
    def is_anti_evidence(self) -> bool:
        """
        Anti-evidence reduces/caps confidence. Identified by source name AND
        no specific client_id. Some anti-evidence sources can also produce
        positive votes — e.g., firm_name_in_title routes positively to
        Internal while also blocking other client attribution.
        """
        if self.client_id is not None:
            return False
        return self.source in (
            'os_idle',
            'generic_browser_tab',
            'personal_app_foreground',
            'firm_name_in_title',
        )

    @property
    def tier(self) -> int:
        if self.source in ('tax_software_taxpayer', 'qb_company_file',
                           'file_path_client_folder', 'title_alias_match',
                           'manual_user_override'):
            return 1
        if self.source in ('calendar_event_tag', 'url_domain_match',
                           'email_thread_match', 'recent_window_continuity'):
            return 2
        if self.source == 'learned_pattern':
            return 3
        if self.is_anti_evidence:
            return 4
        return 0  # unknown

    def to_dict(self) -> dict:
        d = asdict(self)
        d['detected_at'] = self.detected_at.isoformat()
        return d


# =============================================================================
# InferenceResult — the engine's output, stamped on RawEvent.inference
# =============================================================================

@dataclass
class InferenceResult:
    """
    The output of one inference evaluation. Stamped on RawEvent.inference
    and used by the tray UI and the server-side classifier.

    Properties:
      - client_id is None when confidence < 0.4 (below floor)
      - confidence is the agent's belief in client_id, post-decay
      - last_affirming_signal_at is the most recent detected_at among
        contributing evidence; the decay clock runs from this timestamp
      - disagreement is True when multiple clients tied within 0.1
      - candidates lists tied clients (only populated when disagreement)
    """

    client_id: Optional[int]
    confidence: float
    last_affirming_signal_at: Optional[datetime]
    evidence: List[Evidence] = field(default_factory=list)
    decay_function: str = "linear_15min"
    disagreement: bool = False
    candidates: Optional[List[Dict[str, Any]]] = None
    schema_version: str = SCHEMA_VERSION
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def has_client(self) -> bool:
        return self.client_id is not None

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.85

    @property
    def is_moderate_confidence(self) -> bool:
        return 0.6 <= self.confidence < 0.85

    @property
    def is_low_confidence(self) -> bool:
        return 0.4 <= self.confidence < 0.6

    @property
    def is_stale(self) -> bool:
        """True if confidence has decayed below the action floor."""
        return self.confidence < 0.4

    def to_dict(self) -> dict:
        return {
            'client_id': self.client_id,
            'confidence': self.confidence,
            'last_affirming_signal_at': (
                self.last_affirming_signal_at.isoformat()
                if self.last_affirming_signal_at else None
            ),
            'evidence': [e.to_dict() for e in self.evidence],
            'decay_function': self.decay_function,
            'disagreement': self.disagreement,
            'candidates': self.candidates,
            'schema_version': self.schema_version,
            'computed_at': self.computed_at.isoformat(),
        }


# =============================================================================
# WindowContext — input to the inference engine
# =============================================================================

@dataclass
class WindowContext:
    """
    Snapshot of the user's current window/activity at the moment of a
    window-change event. Passed to evidence collectors.
    """

    title: str
    app_name: str
    exe_name: str
    bundle_id: Optional[str] = None
    file_path: Optional[str] = None
    url: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Optional context that may be available
    recent_windows: List[Dict[str, Any]] = field(default_factory=list)
    """Last N window contexts (most recent first). Used by recent_window_continuity."""

    active_calendar_event: Optional[Dict[str, Any]] = None
    """Currently-active calendar event if calendar integration is connected."""

    active_email_thread: Optional[Dict[str, Any]] = None
    """Currently-focused email thread if Outlook integration available."""

    manual_override: Optional[Dict[str, Any]] = None
    """
    Active manual override from the user, if any. Shape:
      {'client_id': int, 'set_at': datetime, 'set_by': 'user'}
    """
