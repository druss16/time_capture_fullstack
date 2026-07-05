"""
tracker/services/classification_service.py

The single entry point for ALL block classification.

Replaces the four-path mutation sprawl described in the design doc:
  - pre_classify_obvious_categories (views.py:1479) — DEPRECATED
  - BlockClassifier invocation in ai_suggestions_today (views.py:1732) — DEPRECATED
  - signals.py post_save auto-classify — DEPRECATED
  - ~10 places that mutate block.client directly in views.py — DEPRECATED

In the new world, EVERY classification goes through ClassificationService.
Every endpoint that needs to change a block's client/category calls into
this service. There is exactly one path.

PUBLIC API:
    service = ClassificationService(org=block.org, user=block.user)

    # Pure function — does not write
    decision = service.classify(block)

    # Apply a decision (writes Block, ClassificationAudit)
    block = service.apply(block, decision, source='auto')

    # Commit a Proposed block (Proposed → Committed)
    block = service.commit(block, user=request.user, override={...})

    # Re-run classification on an existing block
    block = service.reclassify(block, force=False)

PIPELINE (see design doc §4 for full details):
    Stage 0  — Suppress generic/dialog windows
    Stage 1  — Org routing rules (runs_at='classifier' or 'both')
    Stage 2  — Tax software extraction (UltraTax/TaxWise)
    Stage 3  — Deterministic title match (alias/code/name)
    Stage 4  — File path match (depth-aware)
    Stage 5  — URL domain match
    Stage 6  — Calendar event overlap
    Stage 7  — Mail metadata match
    Stage 8  — Recent context (current_client_id, prior block)
    Stage 9  — Learned patterns (UserWorkPattern)
    Stage 10 — AI inference (OpenAI batch)

THIS FILE: orchestration + dataclasses + Stage 0/1/8/9 (foundation chunk).
Other stages are stubbed as TODO and will be implemented in subsequent sessions.
"""

from __future__ import annotations
from tracker.services.pattern_learning import LEARNED_PATTERN_BLACKLIST

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any

from django.db import transaction
from django.utils import timezone
import re

logger = logging.getLogger('timetracker.classification')

_PATH_NOISE_SEGMENTS = {
    # Windows system / user paths
    'users', 'documents', 'desktop', 'downloads', 'pictures', 'videos', 'music',
    'appdata', 'local', 'roaming', 'localtemp', 'temp', 'tmp',
    'packages', 'programdata', 'program files', 'program files (x86)',
    'system32', 'syswow64', 'windows', 'winnt', 'inetcache',
    'temporary internet files', 'recent', 'favorites',
    # macOS noise
    'library', 'caches', 'application support', 'applications',
    'preferences', 'containers',
    # Office Protected View / sandbox intermediate folders
    'ac', 'office', 'office15', 'office16',
    # Common cloud sync folder names — too generic to be client signal
    'onedrive', 'dropbox', 'box', 'sync', 'icloud drive', 'icloud',
    'google drive', 'googledrive',
}

def _is_office_protected_view(window_title) -> bool:
    """Return True when the block's window title indicates Office Protected View.
 
    When Excel/Word/PowerPoint open a downloaded file in Protected View, they
    extract it to a randomized temp directory like:
 
      C:\\Users\\<username>\\AppData\\Local\\Packages\\oice_16_*\\AC\\Temp\\CC19E877.xlsx
 
    The filename in that path is a content hash (e.g. CC19E877.xlsx), NOT the
    original filename. The directory structure is also useless for client
    matching — it's a sandbox path, not a folder under "Clients/<name>/".
 
    In Protected View, file_path is meaningless for client attribution. The
    classifier should fall back to the window title (which DOES contain the
    original filename, e.g. "PureADK_Expense_Report_Q1_2026 - Protected View").
    """
    return 'protected view' in (window_title or '').lower()
 
 
def _infer_username_from_path(file_path) -> str:
    """Extract OS username from a path like C:\\Users\\<username>\\... or /Users/<username>/...
 
    Returns the lowercased username, or empty string if not detectable.
 
    Used to strip the user's home folder name from path matching, since every
    path on a machine contains it.
    """
    if not file_path:
        return ''
    normalized = file_path.replace('\\', '/').lower()
    segments = [s for s in normalized.split('/') if s]
    # Windows: C:/Users/<username>/...
    if 'users' in segments:
        idx = segments.index('users')
        if idx + 1 < len(segments):
            return segments[idx + 1]
    # macOS: /Users/<username>/...
    if segments[:1] == ['users'] and len(segments) > 1:
        return segments[1]
    return ''
 
 
def _clean_path_segments(file_path, username='') -> list:
    """Tokenize file_path into matchable segments, dropping system noise.
 
    Drops:
      - Empty / single-char segments
      - Windows/macOS system paths (Users, AppData, Local, Temp, etc.)
      - The OS username (inferred or passed in)
      - Office Protected View randomized directory names (oice_*, temp* longer
        than 10 chars which suggests a UUID/hash)
      - Drive letters (c:, d:)
 
    Returns a list of cleaned segments suitable for client-name matching.
 
    Example:
      Input:  C:\\Users\\mavops\\AppData\\Local\\Packages\\oice_16_x\\AC\\Temp\\CC19E877.xlsx
      Output: ['cc19e877.xlsx']    # everything else stripped as noise
 
    Example:
      Input:  C:\\Users\\mavops\\Documents\\Clients\\PureADK\\report.xlsx
      Output: ['clients', 'pureadk', 'report.xlsx']
              # 'users', 'mavops', 'documents' all stripped
    """
    if not file_path:
        return []
    normalized = file_path.replace('\\', '/').lower()
    raw_segments = [s for s in normalized.split('/') if len(s) > 1]
    username_lower = (username or '').lower()
    cleaned = []
    for seg in raw_segments:
        # Drop drive letters like 'c:' or 'd:'
        if len(seg) == 2 and seg.endswith(':'):
            continue
        # Drop known noise segments
        if seg in _PATH_NOISE_SEGMENTS:
            continue
        # Drop OS username
        if username_lower and seg == username_lower:
            continue
        # Drop Office sandbox / random hash directories
        if seg.startswith('oice_'):
            continue
        if seg.startswith('temp') and len(seg) > 10:
            continue
        cleaned.append(seg)
    return cleaned


# =============================================================================
# DATA CLASSES — the contracts that callers + stages consume
# =============================================================================

@dataclass
class Signal:
    """
    A single piece of evidence produced by a stage.

    A ClassificationDecision is built from a list of Signals. The decision
    logic at the end of the pipeline weighs these signals to determine the
    final state (committed / proposed / captured / suppressed).
    """
    type: str
    """Signal type, one of:
       'org_rule', 'tax_software', 'title_match', 'file_path', 'url_domain',
       'calendar', 'mail', 'agent_current_client', 'prior_block',
       'learned_pattern', 'ai_inference'
    """

    strength: float
    """0.0 - 1.0. How strong this signal is on its own.
       >= 0.85 = strong (one alone can auto-commit)
       0.65 - 0.84 = moderate (two together can auto-commit)
       < 0.65 = weak (corroborating only)
    """

    evidence: str
    """Human-readable, shown in the Daily Review's "Why?" expansion."""

    detail: dict = field(default_factory=dict)
    """Structured data about the match. Keys vary by signal type but commonly:
       {'client_id': int, 'category': str, 'matched_text': str, ...}
    """

    def to_dict(self) -> dict:
        return {
            'type':     self.type,
            'strength': self.strength,
            'evidence': self.evidence,
            'detail':   self.detail,
        }

    @property
    def is_strong(self) -> bool:
        return self.strength >= 0.85

    @property
    def is_moderate(self) -> bool:
        return 0.65 <= self.strength < 0.85

    @property
    def is_weak(self) -> bool:
        return self.strength < 0.65

    @property
    def proposed_client_id(self) -> Optional[int]:
        return self.detail.get('client_id')

    @property
    def proposed_category(self) -> Optional[str]:
        return self.detail.get('category')


@dataclass
class ClassificationDecision:
    """
    The output of ClassificationService.classify(). A pure data structure that
    callers can inspect, override, and apply.

    The recommended_state field is the service's recommendation. Callers may
    apply it directly or override (e.g., admin force-commit).
    """
    # The classification itself
    client_id: Optional[int] = None
    category: Optional[str] = None
    category_hours: dict = field(default_factory=dict)
    is_billable: bool = True

    # Confidence + signals
    confidence: float = 0.0
    matched_signals: List[Signal] = field(default_factory=list)
    reasoning: str = ''
    source: str = 'unknown'  # which stage produced the dominant decision

    # Recommended state
    recommended_state: str = 'captured'  # 'captured' | 'proposed' | 'committed' | 'suppressed'

    # Review hints
    needs_review: bool = False
    review_reason: str = ''

    # Path B / #1b: client IDs that tied in a same-family title collision
    # (Stage 3 deferred to AI). Stage 8 reads this to suppress agent stickiness
    # pointing at a colliding family member, so the AI becomes the sole judge.
    collision_client_ids: set = field(default_factory=set)

    # Special block types
    is_suppressed: bool = False
    is_meeting: bool = False
    is_individual_return: bool = False

    # Tax software extraction (Stage 2)
    taxpayer_name: Optional[str] = None
    taxpayer_id_hash: Optional[str] = None
    tax_return_type: Optional[str] = None

    def signals_dicts(self) -> list:
        """Serialize signals for storage on Block.proposed_signals."""
        return [s.to_dict() for s in self.matched_signals]

    @property
    def has_classification(self) -> bool:
        return bool(self.client_id) or bool(self.category)

    @property
    def strong_signals(self) -> List[Signal]:
        return [s for s in self.matched_signals if s.is_strong]

    @property
    def moderate_signals(self) -> List[Signal]:
        return [s for s in self.matched_signals if s.is_moderate]


# =============================================================================
# THE SERVICE
# =============================================================================

class ClassificationService:
    """
    Orchestrates the 10-stage classification pipeline and owns all block
    classification mutations.
    """

    def __init__(self, org, user):
        """
        Args:
            org: Organization instance (the block's org)
            user: User instance (the block's user)
        """
        self.org = org
        self.user = user
        self._context_loaded = False

        # Lazy-loaded context — populated on first classify() call
        self._clients: Optional[List] = None
        self._client_patterns: Optional[List] = None
        self._classifier_rules: Optional[List] = None
        self._calendar_events_cache: Dict[str, List] = {}  # keyed by date string
        self._mail_signals_cache: Dict[str, List] = {}

        # Sensitivity from org settings (drives auto-commit thresholds)
        self.sensitivity = getattr(org, 'ai_sensitivity', 50)

        self._sandwich_enabled = getattr(org, 'sandwich_correlation_enabled', False)


    # -------------------------------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------------------------------

    def classify(self, block, skip_ai: bool = False) -> ClassificationDecision:
        """
        Classify a single block. Pure function — does NOT write to the block.

        Returns a ClassificationDecision the caller can choose to apply.

        Args:
            block: Block instance to classify
            skip_ai: When True, skips Stage 10 (AI inference). Used by compaction
                     for low-latency synchronous classification. The signal
                     handler will later enqueue Stage 10 via Celery for any
                     block that ends in 'captured' state.

        This is THE one method that runs the full 10-stage pipeline.
        """
        self._ensure_context_loaded()

        decision = ClassificationDecision()

        # Run each stage. Each stage either:
        #   - Adds Signal(s) to decision.matched_signals
        #   - Sets decision.is_suppressed / is_meeting / is_individual_return
        #   - Returns early (Stage 0 suppress, Stage 2 individual return)

        # Stage 0 — Suppress / internal-work shortcut
        # Stage 0 sets decision.source to 'suppress' or 'internal_work' if it
        # short-circuits. Don't overwrite recommended_state — Stage 0 set it.
        if self._stage_0_suppress(block, decision):
            if decision.source == 'suppress':
                decision.recommended_state = 'suppressed'
                decision.is_suppressed = True
                return decision
            # Internal work — Stage 0 already set recommended_state='committed',
            # category, category_hours, etc. Run finalize to populate proposed_*.
            return self._finalize_decision(decision, block)

        # Stage 2 — Tax software extraction (RUNS BEFORE Stage 1)
        # If a tax software window has an open return, the specific taxpayer
        # extraction is more valuable than any org-level "default tax software
        # routing" rule. Specificity wins. Stage 1 still runs as fallback when
        # no return was detected (e.g. UltraTax open with just a dialog).
        if self._stage_2_tax_software(block, decision):
            return self._finalize_decision(decision, block)

        # Stage 1 — Org routing rules (classifier-stage)
        # Runs AFTER Stage 2 so that specific taxpayer extraction takes priority
        # over generic "exe_family=ultratax → route to Internal-Tax" rules.
        # When Stage 2 didn't detect a return, Stage 1 provides the firm-default.
        if self._stage_1_org_rules(block, decision):
            # Stage 1 may return early if a 'route_to_client' or 'assign_category' rule fires
            return self._finalize_decision(decision, block)

        # Stage 3 — Deterministic title match (alias / domain / file path)
        # Adds a Signal but does not short-circuit — let other stages also weigh in.
        self._stage_3_title_match(block, decision)

        # Stage 4 — File path match (deeper than Stage 3)
        # Stage 3 already does basic file_path containment. Stage 4 looks at the
        # path STRUCTURE — folder segments, depth — to find stronger signals.
        self._stage_4_file_path(block, decision)

        # Stage 5 — URL domain match
        # SKIPPED in foundation: Stage 3 already handles URL domain matching.
        # Stage 5 was originally planned for Client.email_domain matching but
        # that requires schema changes deferred to Phase 2.

        # Stage 6 — Calendar event overlap
        # Reads CalendarEvent records pre-matched during sync.
        # Behind feature flag (org.calendar_classification_enabled).
        self._stage_6_calendar(block, decision)

        # Stage 7 — Mail metadata match
        self._stage_7_mail(block, decision)

        # Stage 8 — Recent context (current_client_id, prior block)
        self._stage_8_recent_context(block, decision)

        # Stage 9 — Learned patterns
        self._stage_9_learned_patterns(block, decision)

        # Stage 9.5 — Bracket attribution (same-day temporal context)
        # Fires only when no earlier stage produced a moderate-or-better
        # client signal. Catches "context work" like bank portals and brief
        # Excel scratch that are bracketed by attributed work for one client.
        # Strength 0.65 — strong enough to override stale agent signals,
        # weak enough to defer to direct title evidence.
        self._stage_9_5_bracket_attribution(block, decision)

        # Stage 9.6 — Deterministic tool→category from industry config.
        # Backstops Stage 10 so routine tool work (QuickBooks→Bookkeeping,
        # Figma→Design) is categorized without an LLM call.
        self._stage_9_6_tool_category(block, decision)

        # Stage 10 — AI inference (last resort, only when nothing else fired)
        # Calls OpenAI to classify when stages 0-9 produced no signals.
        # Cost-controlled: only invoked if no Signal has strength >= 0.65.
        # Skipped when caller passes skip_ai=True (e.g., compaction hot path).
        if not skip_ai:
            self._stage_10_ai_inference(block, decision)

        return self._finalize_decision(decision, block)

    @transaction.atomic
    def apply(self, block, decision: ClassificationDecision, source: str = 'classifier'):
        """
        Apply a classification decision to a block.

        Writes Block fields, creates ClassificationAudit row, updates state.
        This is the ONLY place that mutates block.client, block.category_hours,
        and block.classification_state.

        Args:
            block: Block instance to update
            decision: ClassificationDecision from classify()
            source: One of the state_changed_by choices

        Returns:
            Updated block.
        """
        from tracker.models import Client, ClassificationAudit

        old_client_id = block.client_id
        old_category = self._extract_dominant_category(block)
        old_state = block.classification_state

        # v1.3.55: Captured state with no recommended client means we explicitly
        # rejected attribution (weak signals only, no real evidence). Clear any
        # stale agent-set client_id so the block appears as Unassigned in
        # Daily Review. Without this, blocks where the user drifted from real
        # client work into news/research keep the agent's stale client pick.
        if decision.recommended_state == 'captured' and decision.client_id is None:
            block.client_id = None
            block.classification_state = 'captured'
            block.state_changed_at = timezone.now()
            block.state_changed_by = source
            block.proposed_signals = decision.signals_dicts()
            block.proposed_reasoning = decision.reasoning or ''
            block.proposed_client_id = None
            block.proposed_category = decision.category or ''   
            block.proposed_confidence = decision.confidence
            block.proposed_at = timezone.now()
            block.is_categorized = False
            block.is_billable = decision.is_billable            
            block.category_hours = {}
            block.save(force_classifier=True)
            self._write_audit(
                block=block, decision=decision,
                client_before_id=old_client_id, client_after_id=None,
                category_before=old_category, category_after='',
                source=source,
            )
            return block

        # Always populate the proposed_* fields (audit trail of what classifier said)
        block.proposed_client_id = decision.client_id
        block.proposed_category = decision.category or ''
        block.proposed_confidence = decision.confidence
        block.proposed_at = timezone.now()
        block.proposed_signals = decision.signals_dicts()
        block.proposed_reasoning = decision.reasoning

        # Update state per the decision's recommendation
        new_state = decision.recommended_state
        block.classification_state = new_state
        block.state_changed_at = timezone.now()
        block.state_changed_by = source

        # If committed OR proposed: write the live fields so the block shows up
        # in dashboards. classification_state distinguishes whether it's been
        # confirmed or is awaiting user review.
        if new_state in ('committed', 'proposed'):
            if decision.client_id:
                # v1.3.41: Respect agent attribution. If the block already has
                # a client (set by compaction from RawEvent.current_client_id),
                # the classifier should SUGGEST not overwrite. Stage 10 already
                # handles this for AI signals; mirror that for deterministic
                # stages by recording disagreement and leaving block.client_id.
                if old_client_id and old_client_id != decision.client_id:
                    # Agent already attributed. Don't overwrite — surface as disagreement.
                    block.ai_disagrees_with_agent = True
                    block.ai_proposed_client_id = decision.client_id
                    block.ai_proposed_confidence = decision.confidence or 0.0
                    block.ai_disagreement_reasoning = (decision.reasoning or '')[:500]
                    logger.info(
                        f"[CLASSIFY-DISAGREE] Block {block.pk}: agent={old_client_id} "
                        f"vs classifier={decision.client_id} at {decision.confidence:.2f} — "
                        f"keeping agent's pick"
                    )
                    # Don't write block.client_id — keep agent's choice
                else:
                    block.client_id = decision.client_id
            else:
                # v1.3.61: decision says no client — clear agent's stale attribution.
                # The classifier (FIX 7 in _finalize_decision, or any other path)
                # determined no signal attests to the existing client_id. Drop it.
                # Without this, phantom client_ids from agent stickiness survive
                # into committed state — see Terri's KeyBank → BH Enterprises case.
                if old_client_id:
                    logger.info(
                        f"[APPLY] Block {block.pk}: classifier cleared agent's "
                        f"stale client_id={old_client_id} (no signal attested)"
                    )
                    block.client_id = None
            
            # Ensure category_hours is populated with a real category. The
            # dashboard's today_time filters out 'Idle' and 'Uncategorized'
            # (they EXCLUDE_FROM_TOTALS), so blocks with those category names
            # become invisible. For proposed/committed blocks WITH a client,
            # pick a fallback category based on the org's industry and the
            # classifier's billability judgment.
            #
            # Previously this hardcoded 'General' regardless, which:
            #   (a) wrote a category name that wasn't in any industry's
            #       allowed list (phantom bucket on the dashboard)
            #   (b) silently overrode the AI's is_billable=False signal when
            #       it picked 'Idle' — filter dropped 'Idle' → fallback wrote
            #       billable 'General'. Identical news-browsing activity
            #       ended up in different buckets across clients depending
            #       purely on whether the AI happened to pick 'Idle' vs
            #       'Personal/Non-Billable' for the category.
            hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.01
            EXCLUDE_CATEGORIES = {'idle', 'uncategorized'}

            industry = getattr(self.org, 'industry_type', None) or 'general'
            billable_fb, non_billable_fb = FALLBACK_CATEGORIES.get(
                industry, FALLBACK_CATEGORIES_DEFAULT
            )
            fallback_category = non_billable_fb if not decision.is_billable else billable_fb

            if decision.category_hours:
                cleaned = {k: v for k, v in decision.category_hours.items()
                           if k.lower() not in EXCLUDE_CATEGORIES}
                if cleaned:
                    block.category_hours = cleaned
                else:
                    block.category_hours = {fallback_category: hours}
            elif decision.category and decision.category.lower() not in EXCLUDE_CATEGORIES:
                block.category_hours = {decision.category: hours}
            else:
                # Classifier had a client but no usable category. Respect the
                # AI's billability judgment via the industry-aware fallback so
                # the block appears in dashboards without misrepresenting
                # whether it's billable.
                block.category_hours = {fallback_category: hours}

            # Plan B: resolve the dominant category to this firm's TaskType
            # (Layer 1 -> Layer 2 bridge). Sets block.task_type if a
            # CategoryTaskTypeMapping exists for this org; leaves it unset
            # otherwise (None is a valid, expected outcome).
            try:
                from tracker.services.task_type_resolver import (
                    resolve_task_type_for_category,
                )
                dominant_category = self._extract_dominant_category(block)
                if dominant_category:
                    resolved_tt = resolve_task_type_for_category(
                        block.org, dominant_category
                    )
                    if resolved_tt is not None:
                        block.task_type = resolved_tt
            except Exception as e:
                # Never let task_type resolution break classification.
                logger.warning(
                    '[TASK-TYPE-RESOLVE] Block %s: failed to resolve '
                    'task_type for category — %s', block.pk, e,
                )

            block.is_billable = decision.is_billable
            # Backwards compat with existing is_categorized field
            block.is_categorized = True
            if not block.categorized_at:
                block.categorized_at = timezone.now()
            block.categorized_by = self._map_state_to_categorized_by(source)

        # The 'proposed' state is preserved in classification_state, even though
        # is_categorized=True. Frontend uses classification_state OR the
        # needs_review flag from suggestions endpoint to render differently.

        # Save with force_classifier=True to bypass the legacy protection check
        block.save(force_classifier=True)

        # Write audit trail
        self._write_audit(
            block=block, decision=decision,
            client_before_id=old_client_id,
            client_after_id=block.client_id,
            category_before=old_category,
            category_after=self._extract_dominant_category(block),
            source=source,
        )

        # Mail vs. attribution disagreement (Fix B from Stage 7 v2).
        # Stage 7 stashes the mail-proposed client on decision.detail; if the
        # final attribution differs, flag it so Daily Review surfaces a
        # confirmation prompt to the user.
        mail_detail = (getattr(decision, 'detail', {}) or {})
        mail_proposed_id = mail_detail.get('mail_proposed_client_id')
        if mail_proposed_id:
            final_client_id = block.client_id
            if final_client_id and final_client_id != mail_proposed_id:
                # Disagreement — flag it. We update via .update() to skip the
                # post_save signal, then mirror to the in-memory instance.
                from tracker.models import Block
                reasoning = (
                    f"Email metadata suggests '{mail_detail.get('mail_proposed_client_name', '?')}' "
                    f"but block was attributed to a different client. "
                    f"Mail evidence: {mail_detail.get('mail_proposed_evidence', '')[:300]}"
                )
                Block.objects.filter(pk=block.pk).update(
                    mail_disagrees_with_agent=True,
                    mail_proposed_client_id=mail_proposed_id,
                    mail_proposed_confidence=mail_detail.get('mail_proposed_confidence', 0.0),
                    mail_disagreement_reasoning=reasoning[:500],
                )
                block.mail_disagrees_with_agent = True
                block.mail_proposed_client_id = mail_proposed_id
                block.mail_proposed_confidence = mail_detail.get('mail_proposed_confidence', 0.0)
                block.mail_disagreement_reasoning = reasoning[:500]
 
                logger.info(
                    f"[STAGE-7-DISAGREE] Block {block.pk}: attributed={final_client_id} "
                    f"vs mail-proposed={mail_proposed_id} "
                    f"(conf {mail_detail.get('mail_proposed_confidence', 0.0):.2f})"
                )
            else:
                # Agreement (or final has no client) — clear any stale flag
                # from a prior classification run.
                if getattr(block, 'mail_disagrees_with_agent', False):
                    from tracker.models import Block
                    Block.objects.filter(pk=block.pk).update(
                        mail_disagrees_with_agent=False,
                        mail_proposed_client_id=None,
                        mail_proposed_confidence=None,
                        mail_disagreement_reasoning='',
                    )
                    block.mail_disagrees_with_agent = False
                    block.mail_proposed_client_id = None
                    block.mail_proposed_confidence = None
                    block.mail_disagreement_reasoning = ''


        # ─────────────────────────────────────────────────────────────────────
        # FIX D (v1.3.42): Calendar vs. attribution disagreement
        # ─────────────────────────────────────────────────────────────────────
        # Mirrors the Stage 7 mail reconciliation above. When Stage 6 stashed
        # a calendar-proposed client and the final attribution disagrees,
        # flag for Daily Review.
        #
        # Two sources of disagreement, distinguished by state_changed_by:
        #
        #   'classifier'  — agent/classifier picked X, calendar says Y.
        #                   Banner: "Calendar shows '<event>' during this block —
        #                            reassign from X to Y?"
        #
        #   'manual'      — user manually picked X (state_changed_by in
        #                   {'user','user_edit','correction'}), calendar says Y.
        #                   Banner: "You picked X, but this overlaps '<event>'.
        #                            Keep X or reassign?"
        #
        # We never overwrite the attribution — we only flag. The user decides
        # in Daily Review, same as mail.
        #
        # We also write the meeting flag here. Stage 6 set decision.is_meeting,
        # and Block.is_meeting is the persisted field that
        # _filter_foreground_inside_meetings reads downstream in compaction.
        cal_detail = (getattr(decision, 'detail', {}) or {})
        cal_proposed_id = cal_detail.get('calendar_proposed_client_id')

        # Apply the meeting flag whenever Stage 6 raised it. Done independently
        # of disagreement so calendar-flagged meetings work even when the user
        # and calendar agree on the client.
        if decision.is_meeting and not block.is_meeting:
            block.is_meeting = True
            # Save will happen below in the disagreement branch, or here if
            # there's no disagreement processing to follow.
            try:
                from tracker.models import Block
                Block.objects.filter(pk=block.pk).update(is_meeting=True)
            except Exception as e:
                logger.warning(
                    f"[STAGE-6-MEETING] Failed to persist is_meeting=True "
                    f"for block {block.pk}: {e}"
                )

        if cal_proposed_id:
            final_client_id = block.client_id

            # Determine source for banner copy. state_changed_by was set
            # earlier in this apply() call from the `source` argument.
            if source in ('user', 'user_edit', 'correction'):
                disagreement_source = 'manual'
            else:
                disagreement_source = 'classifier'

            if final_client_id and final_client_id != cal_proposed_id:
                # Disagreement — flag it
                event_title = cal_detail.get('calendar_event_title', '?')
                proposed_name = cal_detail.get('calendar_proposed_client_name', '?')

                if disagreement_source == 'manual':
                    reasoning = (
                        f"You picked a different client, but this block overlaps "
                        f"the calendar event '{event_title[:80]}' which is "
                        f"associated with '{proposed_name}'. "
                        f"Calendar evidence: {cal_detail.get('calendar_proposed_evidence', '')[:200]}"
                    )
                else:
                    reasoning = (
                        f"Calendar shows '{event_title[:80]}' during this block, "
                        f"associated with '{proposed_name}', but the block was "
                        f"attributed to a different client. "
                        f"Calendar evidence: {cal_detail.get('calendar_proposed_evidence', '')[:200]}"
                    )

                from tracker.models import Block
                Block.objects.filter(pk=block.pk).update(
                    calendar_disagrees_with_agent=True,
                    calendar_proposed_client_id=cal_proposed_id,
                    calendar_proposed_confidence=cal_detail.get('calendar_proposed_confidence', 0.0),
                    calendar_disagreement_reasoning=reasoning[:500],
                    calendar_disagreement_source=disagreement_source,
                )
                # Mirror to in-memory instance so subsequent block.save()
                # calls (e.g. propagation) don't clobber the flag.
                block.calendar_disagrees_with_agent = True
                block.calendar_proposed_client_id = cal_proposed_id
                block.calendar_proposed_confidence = cal_detail.get('calendar_proposed_confidence', 0.0)
                block.calendar_disagreement_reasoning = reasoning[:500]
                block.calendar_disagreement_source = disagreement_source

                logger.info(
                    f"[STAGE-6-DISAGREE] Block {block.pk}: "
                    f"attributed={final_client_id} vs calendar-proposed={cal_proposed_id} "
                    f"source={disagreement_source} "
                    f"(conf {cal_detail.get('calendar_proposed_confidence', 0.0):.2f})"
                )
            else:
                # Agreement (or no final client) — clear any stale flag from
                # an earlier classification run that since got resolved.
                if getattr(block, 'calendar_disagrees_with_agent', False):
                    from tracker.models import Block
                    Block.objects.filter(pk=block.pk).update(
                        calendar_disagrees_with_agent=False,
                        calendar_proposed_client_id=None,
                        calendar_proposed_confidence=None,
                        calendar_disagreement_reasoning='',
                        calendar_disagreement_source='',
                    )
                    block.calendar_disagrees_with_agent = False
                    block.calendar_proposed_client_id = None
                    block.calendar_proposed_confidence = None
                    block.calendar_disagreement_reasoning = ''
                    block.calendar_disagreement_source = ''


        # ─────────────────────────────────────────────────────────────────
        # FIX C (v1.2.97): Mail-derived client propagation
        # ─────────────────────────────────────────────────────────────────
        # When Stage 7 commits a block with a mail-derived client at high
        # confidence, propagate that to the user's CurrentClient record so
        # subsequent blocks (Excel, browser, etc.) inherit the new client
        # instead of the stale agent selection.
        #
        # Without this, the inheritance bug just shifts one block forward:
        #   QuickBooks (Client A) → Outlook (correctly attributed to B via mail)
        #   → Excel (still wrongly attributed to A because agent never updated)
        #
        # Conditions to propagate:
        #   1. This block was mail-driven (mail_proposed_id present)
        #   2. The block actually committed to the mail-proposed client (no
        #      disagreement, no override)
        #   3. The decision came from Stage 7 with confidence >= 0.85 (strong)
        #   4. The user's CurrentClient hasn't been manually updated very
        #      recently (don't clobber a user who just switched)
        self._propagate_mail_client_if_applicable(block, decision)

        return block

    def _propagate_mail_client_if_applicable(self, block, decision: ClassificationDecision):
        """
        See FIX C above. Updates CurrentClient if and only if:
          - Block committed (not proposed)
          - Stage 7 mail signal at strength >= 0.85 was the dominant signal
          - User hasn't manually switched in the last 5 minutes
          - The mail-proposed client matches the block's final client

        Logged extensively because this is a billing-affecting silent change.
        """
        # Guard 1: must be committed
        if decision.recommended_state != 'committed':
            return

        # Guard 2: dominant signal must be mail at strong threshold
        mail_signals = [
            s for s in decision.matched_signals
            if s.type == 'mail' and s.strength >= 0.85
        ]
        if not mail_signals:
            return

        # The mail signal must propose the SAME client the block was committed to
        mail_client_id = mail_signals[0].proposed_client_id
        if not mail_client_id or mail_client_id != block.client_id:
            return

        # Guard 3: don't clobber recent manual user activity. We use 5min as the
        # window — long enough that we won't fight the user, short enough that
        # mail-driven inheritance still wins for legitimate context switches.
        from tracker.models import CurrentClient
        from datetime import timedelta

        try:
            cc = CurrentClient.objects.filter(user=self.user).first()
            old_id = None  # set below if we update an existing record

            if cc:
                # If the current selection is already this client, nothing to do
                if cc.client_id == mail_client_id:
                    return

                # If the user updated CurrentClient very recently, respect that
                now = timezone.now()
                if cc.updated_at and (now - cc.updated_at) < timedelta(minutes=5):
                    logger.info(
                        f"[STAGE-7-PROPAGATE] Skipping propagation — user updated "
                        f"CurrentClient {(now - cc.updated_at).total_seconds():.0f}s ago "
                        f"(too recent to override)"
                    )
                    return

                old_id = cc.client_id
                cc.client_id = mail_client_id
                cc.started_at = timezone.now()
                cc.save(update_fields=['client_id', 'started_at', 'updated_at'])

                logger.info(
                    f"[STAGE-7-PROPAGATE] ✅ Updated CurrentClient for user "
                    f"{self.user.id}: {old_id} → {mail_client_id} "
                    f"(mail-driven, block {block.pk}, conf {mail_signals[0].strength:.2f})"
                )
            else:
                # First-ever CurrentClient row for this user
                CurrentClient.objects.create(
                    user=self.user,
                    device_id=block.device_id or 0,
                    client_id=mail_client_id,
                    started_at=timezone.now(),
                )
                logger.info(
                    f"[STAGE-7-PROPAGATE] ✅ Created CurrentClient for user "
                    f"{self.user.id}: client {mail_client_id} (mail-driven)"
                )

            # Audit log entry — fires for both update + create paths
            try:
                from tracker.models import AIProcessingLog
                AIProcessingLog.objects.create(
                    org=self.org,
                    user=self.user,
                    operation_type='stage_7_mail_propagation',
                    input_data={
                        'block_id': block.pk,
                        'mail_client_id': mail_client_id,
                        'mail_confidence': mail_signals[0].strength,
                        'mail_evidence': mail_signals[0].evidence[:300],
                    },
                    output_data={
                        'old_current_client_id': old_id,
                        'new_current_client_id': mail_client_id,
                        'propagation_source': 'stage_7_mail',
                    },
                    processing_time_ms=0,
                    success=True,
                )
            except Exception:
                pass  # never break on logging

        except Exception as e:
            # Never let propagation failure break classification
            logger.warning(
                f"[STAGE-7-PROPAGATE] Failed for block {block.pk}: {e}",
                exc_info=True
            )

    @transaction.atomic
    def commit(self, block, user, override: Optional[dict] = None):
        """
        Transition a Proposed block to Committed.

        Args:
            block: Block in 'proposed' or 'captured' state
            user: The user committing (request.user)
            override: Optional dict to override proposed values:
                      {'client_id': int, 'category': str, 'category_hours': dict,
                       'is_billable': bool}

        Returns:
            Updated block.
        """
        from tracker.models import ClassificationAudit

        if block.classification_state == 'committed':
            raise ValueError(f'Block {block.pk} is already committed')
        if block.classification_state == 'suppressed':
            raise ValueError(f'Block {block.pk} is suppressed; cannot commit')

        old_client_id = block.client_id
        old_category = self._extract_dominant_category(block)

        override = override or {}

        # Determine final values: override > proposed > existing
        final_client_id = override.get('client_id', block.proposed_client_id)
        final_category = override.get('category', block.proposed_category) or ''
        final_category_hours = override.get('category_hours')
        if not final_category_hours and final_category:
            # Build category_hours dict from category + duration
            hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.0
            final_category_hours = {final_category: hours}

        is_billable = override.get('is_billable', block.is_billable)

        # Apply the commit
        block.client_id = final_client_id
        block.category_hours = final_category_hours or {}
        block.is_billable = is_billable
        block.classification_state = 'committed'
        block.state_changed_at = timezone.now()
        block.state_changed_by = 'user_edit' if override else 'user'
        block.is_categorized = True
        if not block.categorized_at:
            block.categorized_at = timezone.now()
        block.categorized_by = 'manual' if override else 'correction'

        block.save(force_classifier=True)

        # Audit log
        ClassificationAudit.objects.create(
            block=block,
            source='manual',
            client_before_id=old_client_id,
            client_after_id=final_client_id,
            category_before=old_category,
            category_after=final_category,
            confidence_client=1.0,  # User commit = full confidence
            confidence_category=1.0,
            overall_confidence=1.0,
            matched_signals=[{
                'type':     'user_commit',
                'strength': 1.0,
                'evidence': f'User {user.username} committed' + (' with override' if override else ''),
                'detail':   override or {},
            }],
            corrected_by_user=bool(override),
        )

        return block

    @transaction.atomic
    def recommit(self, block, user, override: dict, audit_detail: dict = None):
        """
        Record a user's manual client/category correction on a block — even
        if it's already committed. This is THE single path every correction
        endpoint must call so that a ClassificationAudit row (source='manual',
        corrected_by_user=True) is always written. That audit row is the
        ground-truth label the precision report reads.

        Unlike commit(), this does NOT raise on already-committed blocks —
        correcting a wrong attribution on a committed block is the common case.

        Args:
            block: Block being corrected (any state)
            user:  request.user performing the correction
            override: {'client_id': int|None, 'category': str,
                       'category_hours': dict, 'is_billable': bool} —
                      any subset; absent keys keep the block's current value.

        Returns:
            Updated block.
        """
        from tracker.models import ClassificationAudit

        old_client_id = block.client_id
        old_category = self._extract_dominant_category(block)

        # Resolve final values: override wins, else keep what's on the block.
        if 'client_id' in override:
            final_client_id = override['client_id']
        else:
            final_client_id = block.client_id

        final_category = override.get('category', old_category) or ''
        final_category_hours = override.get('category_hours')
        if not final_category_hours and final_category:
            hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.0
            final_category_hours = {final_category: hours}

        is_billable = override.get('is_billable', block.is_billable)

        block.client_id = final_client_id
        if final_category_hours is not None:
            block.category_hours = final_category_hours
        block.is_billable = is_billable
        block.classification_state = 'committed'
        block.state_changed_at = timezone.now()
        block.state_changed_by = 'correction'
        block.is_categorized = True
        if not block.categorized_at:
            block.categorized_at = timezone.now()
        block.categorized_by = 'correction'

        # A manual correction is authoritative — clear stale disagreement
        # flags so resolved banners don't keep reappearing in Daily Review.
        for f in ('ai_disagrees_with_agent', 'mail_disagrees_with_agent',
                  'calendar_disagrees_with_agent'):
            if hasattr(block, f):
                setattr(block, f, False)

        block.save(force_classifier=True)

        ClassificationAudit.objects.create(
            block=block,
            source='manual',
            client_before_id=old_client_id,
            client_after_id=final_client_id,
            category_before=old_category,
            category_after=final_category,
            confidence_client=1.0,
            confidence_category=1.0,
            overall_confidence=1.0,
            matched_signals=[{
                'type': 'user_correction',
                'strength': 1.0,
                'evidence': f'User {getattr(user, "username", "?")} corrected client/category',
                'detail': {**{k: v for k, v in override.items()}, **(audit_detail or {})},
            }],
            corrected_by_user=True,
        )

        return block

    @transaction.atomic
    def reclassify(self, block, force: bool = False):
        """
        Re-run classification on an existing block.

        Args:
            block: Block to reclassify
            force: If True, allow reclassification of Committed blocks (admin only)

        Returns:
            Updated block.
        """
        if block.classification_state == 'committed' and not force:
            raise ValueError(
                f'Block {block.pk} is committed. Use force=True to reclassify '
                '(admin operation only).'
            )

        decision = self.classify(block)
        return self.apply(block, decision, source='classifier')

    # -------------------------------------------------------------------------
    # CONTEXT LOADING
    # -------------------------------------------------------------------------

    def _ensure_context_loaded(self):
        """
        Lazy-load all the org-wide data the stages need. Done once per service
        instance to amortize across many classify() calls.
        """
        if self._context_loaded:
            return

        from tracker.models import Client, ClientPattern, OrgRoutingRule, UserWorkPattern

        self._clients = list(
            Client.objects.filter(org=self.org, is_active=True)
            .only('id', 'name', 'code', 'aliases')
        )

        self._client_patterns = list(
            ClientPattern.objects.filter(org=self.org)
            .only('id', 'client_name', 'match_type', 'pattern', 'weight')
            .order_by('-weight')
        )

        self._classifier_rules = list(
            OrgRoutingRule.objects.filter(
                org=self.org,
                enabled=True,
                runs_at__in=['classifier', 'both'],
            )
            .select_related('target_client')
            .order_by('-priority', 'id')
        )

        # ✅ STAGE 9: Load learned patterns once, grouped by type
        # This eliminates 141+ DB queries (47 blocks × 3 pattern queries per block)
        self._learned_patterns_by_type = {
            'window_title_prefix': list(
                UserWorkPattern.objects.filter(
                    user=self.user,
                    org=self.org,
                    pattern_type='window_title_prefix',
                )[:500].select_related('client')
            ),
            'file_path': list(
                UserWorkPattern.objects.filter(
                    user=self.user,
                    org=self.org,
                    pattern_type__in=['file_path', 'client_folder'],
                )[:500].select_related('client')
            ),
            'domain': list(
                UserWorkPattern.objects.filter(
                    user=self.user,
                    org=self.org,
                    pattern_type='domain',
                )[:500].select_related('client')
            ),
        }

        self._context_loaded = True

    # -------------------------------------------------------------------------
    # STAGE 0 — Suppress
    # -------------------------------------------------------------------------

    def _stage_0_suppress(self, block, decision: ClassificationDecision) -> bool:
        """
        Drop blocks that aren't real activities, or shortcut to internal-firm-work.

        Returns True if the block is suppressed/handled and the pipeline should stop.

        Suppress conditions:
          - Bare tax software splash with no return open ("UltraTax CS")
          - Generic OS dialogs (Save As, Print, Open, etc.)
          - Generic tax software dialogs (CFlYoutFrame, Statements from B&D, etc.)
          - Empty title with very short duration (likely transient)
          - Any title matching SUPPRESS_PATTERNS below

        Shortcut conditions (also stop pipeline):
          - Internal firm work (timesheet, payroll) → assign Billing/Admin category
        """
        title = (block.window_title or block.title or '').strip()
        title_lower = title.lower()
        app_name = (block.app_name or '').lower()
        duration_min = block.minutes or 0

        # Empty title + short duration = transient nothing
        if not title and duration_min < 1:
            decision.matched_signals.append(Signal(
                type='suppress',
                strength=1.0,
                evidence='Empty title with duration < 1 minute',
                detail={'reason': 'empty_short'},
            ))
            decision.reasoning = 'Suppressed: empty title with negligible duration'
            decision.source = 'suppress'
            return True

        # Pattern-based suppression
        for pattern in SUPPRESS_PATTERNS:
            if pattern in title_lower:
                decision.matched_signals.append(Signal(
                    type='suppress',
                    strength=1.0,
                    evidence=f"Title matches suppress pattern '{pattern}'",
                    detail={'reason': 'pattern_match', 'pattern': pattern},
                ))
                decision.reasoning = f"Suppressed: title matches generic dialog pattern '{pattern}'"
                decision.source = 'suppress'
                return True

        # Bare tax software splash (just the app name, no return loaded)
        for splash in BARE_TAX_SOFTWARE_TITLES:
            if title_lower == splash:
                decision.matched_signals.append(Signal(
                    type='suppress',
                    strength=1.0,
                    evidence=f"Bare tax software splash screen '{title}'",
                    detail={'reason': 'tax_software_splash'},
                ))
                decision.reasoning = f"Suppressed: bare tax software splash '{title}' (no return open)"
                decision.source = 'suppress'
                return True

        # Generic tax software dialogs (Save As, Statements from B&D, Online Status, etc.)
        # Lives in tracker/utils/tax_software.py with the SSN extraction logic
        try:
            from tracker.utils.tax_software import is_generic_tax_dialog, is_internal_firm_work
        except ImportError:
            # Module not available — skip these checks
            return False

        if is_generic_tax_dialog(title):
            decision.matched_signals.append(Signal(
                type='suppress',
                strength=1.0,
                evidence=f"Generic tax software dialog: '{title[:60]}'",
                detail={'reason': 'generic_tax_dialog'},
            ))
            decision.reasoning = f"Suppressed: generic tax software dialog '{title[:60]}'"
            decision.source = 'suppress'
            return True

        # Internal firm work — timesheet, payroll, etc. Not suppressed; categorized.
        # Assign Billing/Admin category, no client. Stop pipeline.
        internal_cat = is_internal_firm_work(title)
        if internal_cat:
            # GUARD: if a known client's name appears in the block text, this is
            # CLIENT work that happens to look administrative (e.g. running
            # payroll inside a client's QuickBooks file). Stand down and let
            # the client-attribution stages (rules, patterns, AI) handle it.
            self._ensure_context_loaded()
            _hay = " ".join([
                title or '',
                getattr(block, 'window_title', '') or '',
                getattr(block, 'file_path', '') or '',
            ]).lower()
            # Detect a client with the SAME matcher Stage 3 uses — not a naive
            # full-name substring. The old substring check missed short/reordered
            # forms: a QB window "Sacred Heart Basilica - ... - [Enter Payroll
            # Information]" never contains the literal registered name "Basilica
            # of The Sacred Heart of Jesus", so the guard failed and "payroll"
            # mislabelled real client payroll work as internal (No Client).
            _client_hit = None
            for _c in self._clients:
                if _c.name.lower().strip() in META_CLIENT_NAMES:
                    continue
                _names = [_c.name] + list(getattr(_c, 'aliases', None) or [])
                for _n in _names:
                    _al = (_n or '').lower()
                    if _al and self._alias_is_safe(_al) and self._alias_matches_safely(_al, _hay):
                        _client_hit = _c
                        break
                if _client_hit:
                    break
            if _client_hit:
                decision.matched_signals.append(Signal(
                    type='internal_work_deferred',
                    strength=0.0,
                    evidence=(
                        f"Internal-work pattern matched but client "
                        f"'{_client_hit.name}' appears in title — deferring "
                        f"to client attribution stages"
                    ),
                    detail={'deferred_client_id': _client_hit.id,
                            'internal_category': internal_cat},
                ))
                return False   # not handled — later stages attribute the client

            hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.0
            decision.category = internal_cat
            decision.category_hours = {internal_cat: hours}
            decision.is_billable = False  # Internal work is non-billable by default
            decision.confidence = 0.90
            decision.source = 'internal_work'
            decision.reasoning = f"Internal firm work: {internal_cat}"
            decision.recommended_state = 'committed'  # Internal work is unambiguous
            decision.matched_signals.append(Signal(
                type='internal_work',
                strength=0.90,
                evidence=f"Internal firm work pattern matched in title: '{title[:60]}'",
                detail={'category': internal_cat, 'is_billable': False},
            ))
            return True

        return False

    # -------------------------------------------------------------------------
    # STAGE 1 — Org routing rules (classifier-stage)
    # -------------------------------------------------------------------------

    def _stage_1_org_rules(self, block, decision: ClassificationDecision) -> bool:
        """
        Apply org-specific classifier-stage routing rules.

        Returns True if a terminal rule fired (rule short-circuits remaining stages).

        Uses the existing dormant ClassifierRuleEngine. Rules are loaded with
        runs_at__in=['classifier', 'both'] filter in _ensure_context_loaded.
        """
        if not self._classifier_rules:
            return False

        try:
            from tracker.services.rules.matcher import build_context, rule_to_dict, rule_matches
        except ImportError:
            logger.warning('matcher module not available — skipping Stage 1')
            return False

        ctx = build_context(
            title=getattr(block, 'window_title', '') or '',
            exe=self._infer_exe(block),
            file_path=getattr(block, 'file_path', '') or '',
            app_name=getattr(block, 'app_name', '') or '',
            duration_minutes=block.minutes,
            has_attributed_client=bool(block.client_id),
            is_inside_meeting=getattr(block, 'is_meeting', False),
        )

        for rule_obj in self._classifier_rules:
            rule_dict = rule_to_dict(rule_obj)
            if not rule_matches(rule_dict, ctx):
                continue

            # Rule matched — apply its action
            terminated = self._apply_rule_action(rule_obj, rule_dict, block, decision)
            if terminated:
                self._record_rule_fire(rule_obj, block, ctx, decision)
                return True

        return False

    def _apply_rule_action(self, rule_obj, rule_dict: dict, block, decision: ClassificationDecision) -> bool:
        """
        Translate a matched rule into a Signal and possibly a terminal decision.
        Returns True if the rule terminates classification (route_to_client / assign_category).
        """
        action = rule_dict.get('action')

        if action == 'route_to_client':
            client = rule_obj.target_client
            if not client:
                logger.warning(f'Rule {rule_obj.id} action=route_to_client but no target_client')
                return False
            decision.client_id = client.id
            decision.confidence = 0.95
            decision.source = 'org_rule'
            decision.reasoning = (
                f"Org rule #{rule_obj.id} ({rule_obj.match_type}={rule_obj.match_value!r}) "
                f"→ route to {client.name}"
            )
            decision.matched_signals.append(Signal(
                type='org_rule',
                strength=0.95,
                evidence=decision.reasoning,
                detail={
                    'rule_id':    rule_obj.id,
                    'action':     action,
                    'client_id':  client.id,
                    'client_name': client.name,
                },
            ))
            decision.recommended_state = 'committed'  # Org rules are firm-managed = trusted
            return True

        if action == 'assign_category':
            target_cat = rule_dict.get('target_category')
            if not target_cat:
                logger.warning(f'Rule {rule_obj.id} action=assign_category but no target_category')
                return False
            decision.category = target_cat
            hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.0
            decision.category_hours = {target_cat: hours}
            decision.confidence = 0.95
            decision.source = 'org_rule'
            decision.reasoning = (
                f"Org rule #{rule_obj.id} ({rule_obj.match_type}={rule_obj.match_value!r}) "
                f"→ assign category '{target_cat}'"
            )
            decision.matched_signals.append(Signal(
                type='org_rule',
                strength=0.95,
                evidence=decision.reasoning,
                detail={
                    'rule_id':  rule_obj.id,
                    'action':   action,
                    'category': target_cat,
                },
            ))
            decision.recommended_state = 'committed'
            return True

        if action == 'suppress':
            decision.is_suppressed = True
            decision.recommended_state = 'suppressed'
            decision.source = 'org_rule_suppress'
            decision.reasoning = (
                f"Org rule #{rule_obj.id} suppressed this block"
            )
            decision.matched_signals.append(Signal(
                type='org_rule',
                strength=1.0,
                evidence=decision.reasoning,
                detail={'rule_id': rule_obj.id, 'action': action},
            ))
            return True

        if action == 'mark_non_billable':
            decision.is_billable = False
            decision.matched_signals.append(Signal(
                type='org_rule',
                strength=0.7,  # Modifier, not terminal — moderate signal
                evidence=f"Org rule #{rule_obj.id} marked non-billable",
                detail={'rule_id': rule_obj.id, 'action': action},
            ))
            return False  # Not terminal — continue to other stages

        if action == 'flag_for_review':
            decision.needs_review = True
            decision.review_reason = rule_dict.get('flag_reason', '') or f"Flagged by rule #{rule_obj.id}"
            decision.matched_signals.append(Signal(
                type='org_rule',
                strength=0.5,
                evidence=f"Org rule #{rule_obj.id} flagged for review: {decision.review_reason}",
                detail={'rule_id': rule_obj.id, 'action': action, 'reason': decision.review_reason},
            ))
            return False  # Not terminal

        if action == 'propose_only':
            # Provides a strong signal but explicitly does NOT auto-commit
            client = rule_obj.target_client
            if client:
                decision.client_id = client.id
                decision.confidence = 0.85
                decision.source = 'org_rule_propose'
                decision.reasoning = f"Org rule #{rule_obj.id} proposes {client.name} (review required)"
                decision.matched_signals.append(Signal(
                    type='org_rule',
                    strength=0.85,
                    evidence=decision.reasoning,
                    detail={'rule_id': rule_obj.id, 'action': action, 'client_id': client.id},
                ))
                decision.recommended_state = 'proposed'
                return True

        # Routing-stage actions (never_switch_away) shouldn't be in classifier-stage rules
        logger.debug(f'Stage 1: rule {rule_obj.id} has action={action} — not handled at classifier stage')
        return False

    @staticmethod
    def _infer_exe(block) -> str:
        """Best-effort exe name from block.app_name."""
        app = (getattr(block, 'app_name', '') or '').lower()
        return app

    @staticmethod
    def _record_rule_fire(rule_obj, block, ctx: dict, decision: ClassificationDecision):
        """Write a RuleFireLog row + bump the rule's fire_count."""
        try:
            from django.db.models import F
            from tracker.models import OrgRoutingRule, RuleFireLog

            RuleFireLog.objects.create(
                rule=rule_obj,
                rule_version=getattr(rule_obj, 'version', 1),
                org=rule_obj.org,
                block=block,
                engine='classifier',
                context={
                    'title':     ctx.get('title', '')[:200],
                    'exe':       ctx.get('exe', ''),
                    'file_path': ctx.get('file_path', '')[:200],
                    'duration':  ctx.get('duration_minutes'),
                },
                outcome={
                    'action':    rule_obj.action,
                    'client_id': decision.client_id,
                    'category':  decision.category,
                    'reasoning': decision.reasoning[:500],
                },
            )

            OrgRoutingRule.objects.filter(id=rule_obj.id).update(
                fire_count=F('fire_count') + 1,
                last_fired_at=timezone.now(),
            )
        except Exception as e:
            logger.warning(f'Failed to record rule fire for rule {rule_obj.id}: {e}')

    # -------------------------------------------------------------------------
    # STAGE 2 — Tax software extraction (UltraTax, TaxWise, Lacerte, ProSeries)
    # -------------------------------------------------------------------------

    def _stage_2_tax_software(self, block, decision: ClassificationDecision) -> bool:
        """
        Detect when the user has a return open in tax software and extract the
        taxpayer / return type. Strong signal — auto-commits to committed state.

        Behavior:
          - Individual returns (1040, 1041, etc.): no client, but populate taxpayer
            bucket fields (name, hash, type) for dashboard analytics.
          - Business returns (1065, 1120, 1120S, 990): try to match entity name
            against org clients. If matched, attribute to client. If unmatched,
            treat as individual-return (taxpayer bucket).

        Returns True if Stage 2 fired a strong signal and pipeline should stop.
        """
        try:
            from tracker.utils.tax_software import extract_tax_context
        except ImportError:
            return False

        title = (block.window_title or block.title or '').strip()
        if not title:
            return False

        tax_ctx = extract_tax_context(title)
        if not tax_ctx:
            return False

        category = tax_ctx.category  # always "Tax Preparation"
        hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.0
        category_hours = {category: hours}

        # Business return — try to match entity name to a client record
        if tax_ctx.is_business_return:
            client = self._match_taxpayer_to_client(tax_ctx.taxpayer_name)
            if client:
                decision.client_id = client.id
                decision.category = category
                decision.category_hours = category_hours
                decision.confidence = 0.92  # Strong but not absolute (name match heuristic)
                decision.source = 'tax_software'
                decision.reasoning = (
                    f"{tax_ctx.software} {tax_ctx.return_type} return open: "
                    f"'{tax_ctx.taxpayer_name}' matched client '{client.name}'"
                )
                decision.matched_signals.append(Signal(
                    type='tax_software',
                    strength=0.92,
                    evidence=decision.reasoning,
                    detail={
                        'software':         tax_ctx.software,
                        'return_type':      tax_ctx.return_type,
                        'taxpayer':         tax_ctx.taxpayer_name,
                        'taxpayer_id_hash': tax_ctx.taxpayer_id_hash,
                        'client_id':        client.id,
                        'client_name':      client.name,
                        'category':         category,
                    },
                ))
                decision.recommended_state = 'committed'
                return True
            # Business return but no client match — fall through to individual bucket

        # Individual return — populate taxpayer bucket fields.
        # Per org config: optionally route to firm's Internal-Tax client
        # so the time is automatically billable. Default behavior is to
        # leave client_id=None and let the user route manually via the
        # Daily Review queue.
        if getattr(self.org, 'route_individual_returns_to_internal_tax', False):
            decision.client_id = self._get_internal_tax_client_id()
        else:
            decision.client_id = None
        decision.category = category
        decision.category_hours = category_hours
        decision.confidence = 0.95  # Very strong — tax software + open return = certain
        decision.source = 'tax_software'
        decision.reasoning = (
            f"{tax_ctx.software} {tax_ctx.return_type} return open: "
            f"individual return for '{tax_ctx.taxpayer_name}'"
        )
        decision.is_individual_return = True
        decision.taxpayer_name = tax_ctx.taxpayer_name
        decision.taxpayer_id_hash = tax_ctx.taxpayer_id_hash
        decision.tax_return_type = tax_ctx.return_type
        decision.matched_signals.append(Signal(
            type='tax_software',
            strength=0.95,
            evidence=decision.reasoning,
            detail={
                'software':         tax_ctx.software,
                'return_type':      tax_ctx.return_type,
                'taxpayer':         tax_ctx.taxpayer_name,
                'taxpayer_id_hash': tax_ctx.taxpayer_id_hash,
                'category':         category,
            },
        ))
        decision.recommended_state = 'committed'
        return True

    def _match_taxpayer_to_client(self, taxpayer_name: str):
        """
        Try to match a taxpayer/entity name from tax software against org clients.
        Used for business returns (1065, 1120, 1120S, 990) only.

        GUARDRAILS:
          - Skips meta-clients (Internal, Internal - Tax, etc.)
          - Skips short aliases on the stoplist (Tax, Office, Internal, etc.)
          - Requires first_token >= 5 chars OR an exact word match in client name

        Returns Client object or None.
        """
        if not taxpayer_name:
            return None

        # Normalize: take the first significant word
        # "Everson Corp, LLC" → "everson"
        # "Smith, John" → "smith"
        name_lower = taxpayer_name.lower()
        first_part = name_lower.split(',')[0].strip()
        first_token = first_part.split()[0] if first_part else ''

        if len(first_token) < 4:
            return None

        # Don't match against generic words
        if first_token in SHORT_ALIAS_STOPLIST:
            return None
        if first_token in ('the', 'and', 'inc', 'llc', 'corp', 'ltd'):
            return None

        for client in self._clients:
            # Skip meta-clients
            if client.name.lower().strip() in META_CLIENT_NAMES:
                continue

            client_name_lower = client.name.lower()
            client_aliases = [a.lower() for a in (client.aliases or [])] if client.aliases else []
            all_names = [client_name_lower] + client_aliases

            for name in all_names:
                # Match if first_token appears as a complete word in client name
                if first_token in name.split():
                    return client
                # Substring match only allowed for tokens >= 5 chars
                if len(first_token) >= 5 and first_token in name:
                    return client

        return None

    def _get_internal_tax_client_id(self):
        """Find this org's 'Internal - Tax' client ID. Cached per-service.
        
        Used by Stage 2 to route individual tax returns when the org has
        enabled route_individual_returns_to_internal_tax. Returns None
        if no Internal-Tax client exists for this org (caller falls back
        to leaving client_id=None — same as the feature-off path).
        """
        if hasattr(self, '_internal_tax_client_id'):
            return self._internal_tax_client_id
        internal_tax = next(
            (c for c in self._clients if c.name.lower().strip() == 'internal - tax'),
            None
        )
        self._internal_tax_client_id = internal_tax.id if internal_tax else None
        return self._internal_tax_client_id

    # -------------------------------------------------------------------------
    # STAGE 3 — Deterministic title / domain / path match
    # -------------------------------------------------------------------------

    def _stage_3_title_match(self, block, decision: 'ClassificationDecision'):
        """
        Match block content (window title, URL, file path) against client names
        and aliases. The strongest match wins.
 
        Signal order (best wins):
          1. URL domain (0.92) — strongest, hard to fake
          2. File path (0.90) — strong unless Office Protected View
          3. Title alias (0.82) — moderate-high
 
        v1.3.41 changes:
          - Skip file_path matching when window indicates Office Protected View
            (path is a sandbox temp dir, not real client folder)
          - Strip OS user home, AppData, Temp, etc. from file_path before
            matching to avoid coincidental matches on system folders
          - When file_path is fully noise after cleaning, skip the file_path
            stage and let the title stage decide
 
        Meta-clients (firm overhead) are skipped entirely.
        """
        if not self._clients:
            return
 
        haystack = self._build_haystack(block)
        if not haystack:
            return
 
        url = (block.url or '').strip().lower()
        file_path_raw = (block.file_path or '').strip()
 
        # v1.3.41: clean file_path before matching
        is_protected_view = _is_office_protected_view(block.window_title)
        if file_path_raw and not is_protected_view:
            username = _infer_username_from_path(file_path_raw)
            cleaned_segments = _clean_path_segments(file_path_raw, username)
            # Rebuild as a space-joined searchable string for substring matching
            file_path_searchable = ' '.join(cleaned_segments)
        else:
            file_path_searchable = ''
 
        best_client = None
        best_strength = 0.0
        best_match_type = ''

        # Path B collision tracking: record every client that matches via the
        # TITLE-ALIAS path and its score. After the loop, if 2+ distinct clients
        # tie at the top title-alias score, the deterministic matcher cannot
        # disambiguate a same-family collision (e.g. "Sacred Heart Basilica"
        # matches Cicero/Basilica/NY-Mills/Rome all on shared "sacred heart").
        # In that case we DEFER to AI (Stage 10), which reads the distinguishing
        # token. URL/file_path matches are specific and excluded from this.
        _title_alias_hits = []  # list of (client_id, strength, spec) — title matches
        _file_path_hits = []    # same shape — file-path matches (collision-checked too)
 
        for client in self._clients:
            # Skip meta-clients
            if client.name.lower().strip() in META_CLIENT_NAMES:
                continue
 
            name_lower = client.name.lower()
            aliases = [a.lower() for a in (client.aliases or [])] if client.aliases else []
            all_names = [name_lower] + aliases
 
            # Match 1: URL domain (strongest)
            if url:
                domain = self._extract_domain(url)
                if domain:
                    for alias in all_names:
                        if not self._alias_is_safe(alias):
                            continue
                        alias_clean = ''.join(c for c in alias if c.isalnum())
                        domain_clean = ''.join(c for c in domain if c.isalnum())
                        if len(alias_clean) >= 4 and alias_clean in domain_clean:
                            # v1.3.24: Use specificity score as tiebreaker.
                            # Domain is the strongest signal type — base
                            # strength 0.92 stays, but among multiple
                            # matching clients, prefer the one whose alias
                            # tokens most completely match.
                            spec = self._alias_match_score(alias, domain_clean)
                            this_strength = 0.92 + (spec - 0.5) * 0.02  # tiny nudge
                            if this_strength > best_strength:
                                best_client = client
                                best_strength = this_strength
                                best_match_type = 'domain'
                            break

            # Match 2: File path (strong) — only if not Protected View and has signal
            if file_path_searchable:
                for alias in all_names:
                    if not self._alias_is_safe(alias):
                        continue
                    if self._alias_matches_safely(alias, file_path_searchable):
                        spec = self._alias_match_score(alias, file_path_searchable)
                        this_strength = 0.90 + (spec - 0.5) * 0.02
                        # Record for the same-family collision check below. A
                        # folder named for a client *family* (e.g. "Sacred Heart
                        # Bascilica") matches every sibling on the shared tokens
                        # at an identical score, exactly like an ambiguous title
                        # — so file paths must defer to AI too, not silently
                        # commit an arbitrary iteration-order winner.
                        _file_path_hits.append((client.id, this_strength, spec))
                        if this_strength > best_strength:
                            best_client = client
                            best_strength = this_strength
                            best_match_type = 'file_path'
                        break

            # Match 3: Title alias (moderate-high)
            for alias in all_names:
                if not self._alias_is_safe(alias):
                    continue
                if self._alias_matches_safely(alias, haystack):
                    spec = self._alias_match_score(alias, haystack)
                    this_strength = 0.82 + (spec - 0.5) * 0.02
                    # Store (id, strength, spec): strength drives the existing
                    # collision margin (Basilica-safe); raw spec drives the
                    # high-confidence shortcut below (St Matthew rescue).
                    _title_alias_hits.append((client.id, this_strength, spec))
                    if this_strength > best_strength:
                        best_client = client
                        best_strength = this_strength
                        best_match_type = 'title_alias'
                    break
 
        if not best_client or best_strength < 0.65:
            return
 
        # Path B (collision deferral): if the winning match is a TITLE-ALIAS or
        # FILE-PATH match AND 2+ distinct clients tied at the top score for that
        # signal, the deterministic matcher is guessing among a same-name family
        # (e.g. "Sacred Heart Basilica" matches Cicero/Basilica/NY-Mills/Rome all
        # on the shared "sacred heart" tokens, every one scoring spec=0.0).
        # Picking by iteration order silently mis-attributes. Defer to AI (Stage
        # 10), which reads the distinguishing token ("Basilica" -> 175). Emit NO
        # title signal so the AI client signal becomes dominant. The keystone
        # SAFETY CAP ensures the resulting lone-AI pick PROPOSES (not commits)
        # without corroboration.
        #
        # File paths were ORIGINALLY excluded here on the assumption they are
        # always specific. That broke on shared-family folders: a file stored at
        # "...\Client File Notes\Sacred Heart Bascilica\..." matched all four
        # Sacred Heart siblings at an identical 0.89 and committed Cicero (block
        # 48006, billable) with NO deferral. A folder named for the family is as
        # ambiguous as a title, so the same collision logic now covers it. A
        # path that names ONE client (".../Clients/Acme Corp/...") still yields a
        # single hit, no tie, and commits exactly as before — no regression.
        # URL matches remain specific and are still excluded.
        _active_hits = (
            _title_alias_hits if best_match_type == 'title_alias'
            else _file_path_hits if best_match_type == 'file_path'
            else []
        )
        if best_match_type in ('title_alias', 'file_path') and _active_hits:
            # High-confidence shortcut (St Matthew rescue): if exactly ONE
            # client FULLY owns the title (raw spec >= 0.9) and no other client
            # comes close (next spec <= top - 0.1), it's a clear winner, NOT a
            # family collision. Take it directly so we don't defer a confident
            # match to an AI that may whiff (block 46203 "St Matthew East
            # Syracuse" -> 412 at spec 1.0, rest at 0.0 -> previously deferred
            # then landed None, losing 75 billable minutes). Basilica is
            # unaffected: its clients top out at spec ~0.33, never reaching 0.9.
            _spec_sorted = sorted((sp for _, _, sp in _active_hits), reverse=True)
            _clear_winner = (
                len(_spec_sorted) >= 1
                and _spec_sorted[0] >= 0.9
                and (len(_spec_sorted) == 1 or _spec_sorted[1] <= _spec_sorted[0] - 0.1)
            )
            _top = max(strg for _, strg, _ in _active_hits)
            # Near-tie margin on compressed STRENGTH (0.81-0.83 band). The
            # compression is load-bearing: it squashes a partial match (Cicero
            # spec 0.333 -> strength 0.817) and a non-match (spec 0.0 -> 0.810)
            # close enough to tie, which is what lets a same-family collision
            # fire when the CORRECT client (Basilica, spec 0.0) scores LOWER than
            # an incidental partial match (Cicero). Do NOT switch to raw spec —
            # Basilica's correct answer is at the bottom, not the top.
            _COLLISION_MARGIN = 0.05
            _tied = {cid for cid, strg, _ in _active_hits if (_top - strg) < _COLLISION_MARGIN}
            if len(_tied) >= 2 and not _clear_winner:
                # DISTINGUISHING-TOKEN TIEBREAK. The whole-name gate flattens
                # every sibling to spec 0.0, so "Sacred Heart Basilica" ties
                # Cicero/Basilica/NY-Mills/Rome — even though the text usually
                # carries the deciding word ("basilica", "rome", "boonville").
                # Before giving up to the AI, pick the one client whose UNIQUE
                # token is present. For file paths the FILE NAME is the stronger
                # signal, so we check it before the folders; for titles the whole
                # title is both. This resolves the clear cases deterministically
                # (no AI cost, no confirmation, no mis-attribution) and defers
                # ONLY genuine ambiguity — e.g. "St Patricks Jordan.xlsx" (church
                # vs cemetery, no deciding word) or text naming two siblings.
                _winner_id = None
                if best_match_type == 'file_path':
                    _basename = re.split(r'[\\/]', (file_path_raw or '').strip())[-1]
                    _winner_id = self._disambiguate_collision(
                        _tied, _basename, file_path_searchable, self._clients
                    )
                elif best_match_type == 'title_alias':
                    _winner_id = self._disambiguate_collision(
                        _tied, haystack, haystack, self._clients
                    )
                if _winner_id is not None:
                    _wc = next((c for c in self._clients if c.id == _winner_id), None)
                    if _wc is not None:
                        _ws = next((strg for cid, strg, _ in _active_hits
                                    if cid == _winner_id), best_strength)
                        logger.info(
                            f"[STAGE-3-COLLISION] {best_match_type} tie among "
                            f"{sorted(_tied)} broken to {_winner_id} ({_wc.name!r}) "
                            f"via distinguishing token"
                        )
                        decision.matched_signals.append(Signal(
                            type=f'title_match_{best_match_type}',
                            strength=_ws,
                            evidence=(f"Client '{_wc.name}' matched via "
                                      f"{best_match_type} (distinguishing-token tiebreak)"),
                            detail={
                                'client_id':   _winner_id,
                                'client_name': _wc.name,
                                'match_type':  best_match_type,
                            },
                        ))
                        return
                decision.collision_client_ids = set(_tied)
                # ROOT FIX: the agent's stuck client_id, if it's one of these
                # ambiguous family members, is an unreliable guess. Clear it
                # in-memory NOW so NO downstream guard — Stage 8 stickiness,
                # Stage 10 validation-mode, or the apply() disagreement check
                # (which would otherwise "keep agent's pick" and revert the AI's
                # correct disambiguation) — ever sees a conflicting agent client
                # to protect. The AI becomes the sole judge; keystone caps it to
                # proposed. This is purer than gating each guard separately.
                if block.client_id in _tied:
                    logger.info(
                        f"[STAGE-3-COLLISION] clearing stale agent client "
                        f"{block.client_id} (a colliding family member) so AI decides"
                    )
                    block.client_id = None
                logger.info(
                    f"[STAGE-3-COLLISION] {len(_tied)} clients tie for title "
                    f"{haystack[:45]!r} (score {_top:.2f}) -- deferring to AI"
                )
                return

        decision.matched_signals.append(Signal(
            type=f'title_match_{best_match_type}',
            strength=best_strength,
            evidence=f"Client '{best_client.name}' matched via {best_match_type}",
            detail={
                'client_id':   best_client.id,
                'client_name': best_client.name,
                'match_type':  best_match_type,
            },
        ))

    @staticmethod
    def _disambiguate_collision(tied_ids, primary_text, full_text, clients):
        """
        Break a same-family tie (title OR file path) using a DISTINGUISHING token.

        Several sibling clients can tie on shared tokens — e.g. all four
        "Sacred Heart" parishes match "Sacred Heart Basilica ..." at an identical
        score because the whole-name gate zeros everyone to spec 0.0. But the
        text the user has open usually names the right one ("...Basilica...",
        "...NY Mills...", "...Rome...", "...Boonville...").

        Strategy: among the tied clients, find tokens that are UNIQUE to a
        single client (shared tokens like "sacred"/"heart" can't distinguish)
        and look for them in `primary_text` first (the file NAME, or the title),
        then `full_text` (the whole path; same as primary for titles). Return the
        lone client whose unique token is present. Return None when undecidable:
        no unique token anywhere (e.g. "St Patricks Jordan.xlsx" — church vs
        cemetery), or two+ clients each have one (text naming multiple siblings).
        The caller then defers to AI.

        Exact-token matching only (with the same stemming/normalization as the
        matcher) — deliberately conservative, so a tie is broken only on a real
        verbatim distinguishing word, never a fuzzy coincidence.
        """
        import re
        from collections import Counter

        def _norm(s):
            s = (s or '').lower()
            s = re.sub(r'\bst\.?\s|\bst\.(?=[a-z])', 'saint ', s)
            s = re.sub(r'\bmt\.?\s', 'mount ', s)
            s = re.sub(r'\bft\.?\s', 'fort ', s)
            s = s.replace("'", "").replace("’", "")
            s = re.sub(r'\b(\w{4,})s\b', r'\1', s)
            # NB: split underscores too, so "Summary_StMary_2026" tokenizes
            s = re.sub(r'[._,()&/\\|:;!?"*–—\-\[\]{}]+', ' ', s)
            return re.sub(r'\s+', ' ', s).strip()

        by_id = {c.id: c for c in clients if c.id in tied_ids}
        if len(by_id) < 2:
            return None

        # Distinctive tokens per tied client (name + aliases): real words that
        # aren't stop-words, legal suffixes, or domain-common ("church", etc).
        dtok = {}
        for cid, c in by_id.items():
            toks = set()
            for nm in [c.name] + list(c.aliases or []):
                for t in _norm(nm).split():
                    if (len(t) >= 4
                            and t not in ALIAS_STOP_WORDS
                            and t not in ALIAS_GENERIC_SUFFIXES
                            and t not in DOMAIN_COMMON_WORDS):
                        toks.add(t)
            dtok[cid] = toks

        # Keep only tokens unique to ONE tied client — shared ones can't decide.
        counts = Counter(t for toks in dtok.values() for t in toks)
        for cid in dtok:
            dtok[cid] = {t for t in dtok[cid] if counts[t] == 1}

        # Primary text first (file name / the title), then the broader text.
        for text in (primary_text, full_text):
            text_toks = set(_norm(text).split())
            winners = [cid for cid in by_id if dtok[cid] & text_toks]
            if len(winners) == 1:
                return winners[0]
            if len(winners) >= 2:
                return None  # names two+ siblings — genuinely ambiguous
        return None  # no distinguishing token present anywhere

    @staticmethod
    def _alias_is_safe(alias: str) -> bool:
        a = alias.strip().lower()
        if not a or len(a) < 4:
            return False
        if a in SHORT_ALIAS_STOPLIST:
            return False
        import re
        normalized = re.sub(r'[^a-z\s]', ' ', a)
        tokens = [t for t in normalized.split() if t]
        distinctive = [
            t for t in tokens
            if len(t) >= 4
            and t not in ALIAS_STOP_WORDS
            and t not in ALIAS_GENERIC_SUFFIXES
        ]
        if len(tokens) > 1 and len(distinctive) <= 1:
            # Multi-word alias whose only distinctive token is in the
            # SINGLE_TOKEN_ALIAS_BLOCKLIST is rejected outright. These are
            # tokens that should NEVER be a sole basis for matching anything
            # ("services", "company", "inc"...).
            if distinctive and distinctive[0] in SINGLE_TOKEN_ALIAS_BLOCKLIST:
                return False
            # v1.3.64: Removed the DOMAIN_COMMON_WORDS check that previously
            # lived here. It was both REDUNDANT and OVERLY AGGRESSIVE:
            #
            #   REDUNDANT — _alias_matches_safely already enforces this
            #   in its token-based fallback path (require >=1 non-domain-
            #   common distinctive match for multi-token aliases).
            #
            #   OVERLY AGGRESSIVE — pre-rejected legitimate verbatim phrases.
            #   The verbatim substring match in _alias_matches_safely
            #   (Step 2) is inherently safe — the full phrase "The New
            #   School" won't appear in "Microsoft School Edition", so
            #   verbatim matches via this path are high-quality.
            #
            # Architecturally: safety should be a property of MATCHES
            # (alias + haystack pairs), not of aliases in isolation.
            # _alias_is_safe shouldn't be making safety decisions at all —
            # it should only do basic structural sanity checks. Future
            # cleanup: consider deleting this function entirely and folding
            # the SHORT_ALIAS_STOPLIST + SINGLE_TOKEN_ALIAS_BLOCKLIST checks
            # into _alias_matches_safely.
        return True

    @staticmethod
    def _normalize_name(s: str) -> str:
        """
        Canonical name normalization — the SINGLE source of truth for both the
        client matcher (_alias_matches_safely) and the specificity scorer
        (_alias_match_score). Applied identically to client names and block text.

        Consolidated from two identical nested copies whose drift caused the
        "St.James" (no space) vs "St. James" mismatch. Keep this as the one place
        this logic lives — future stages (ClientNameResolver) route through it.

          - expand St./Mt./Ft. abbreviations, WITH or WITHOUT a trailing space
            ("St.James" and "St. James" both -> "saint james"); the period is
            required in the no-space branch so "start"/"stone" are untouched
          - strip apostrophes ("Mary's" == "Marys")
          - stem possessive 's on 4+ char words ("theresas" -> "theresa")
          - split punctuation/&/hyphens/brackets so distinctive tokens are reachable
          - collapse whitespace
        """
        import re
        s = s.lower()
        s = re.sub(r'\bst\.?\s|\bst\.(?=[a-z])', 'saint ', s)
        s = re.sub(r'\bmt\.?\s', 'mount ', s)
        s = re.sub(r'\bft\.?\s', 'fort ', s)
        s = s.replace("'", "").replace("’", "")
        s = re.sub(r'\b(\w{4,})s\b', r'\1', s)
        s = re.sub(r'[.,()&/\\|:;!?"*–—\-\[\]{}]+', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    @staticmethod
    def _alias_match_score(alias: str, haystack: str) -> float:
        """
        v1.3.48: Position- and contiguity-aware specificity score.

        Returns 0.0 if alias doesn't match haystack (via _alias_matches_safely).
        Returns a score in (0, 1] otherwise, weighted by:

          1. Contiguous match position (front-of-haystack > later > in-bracket)
          2. Distinctive token coverage (fallback for non-contiguous matches)

        The score is used by Stage 3 to break ties when multiple clients
        match the same haystack. Higher score = more specific identification.

        Score tiers:
          1.00 - Alias appears contiguously at position 0 (after normalization)
          0.95 - Alias appears contiguously early in pre-bracket region (<10 chars in)
          0.85 - Alias appears contiguously somewhere in pre-bracket region
          0.40 - Alias matches ONLY inside a QB screen bracket
          (0, 0.5] - Token-based fallback (current v1.3.24 behavior)

        Rationale: When a QB title like
            "St Marys Cemetery (Secondary) - QuickBooks ... - [Vendor Center: Cacciatore Cemetery Services]"
        matches BOTH "St Marys Cemetery" (alias on client 125, contiguous at
        position 0) AND "266 Services LLC" (matched on single shared token
        "services" inside the vendor bracket), the front-contiguous match
        must crush the token-bracket match. Previously both scored 1.0 via
        1/1 distinctive tokens, leaving Stage 3 to pick by iteration order.
        """
        import re
        if not ClassificationService._alias_matches_safely(alias, haystack):
            return 0.0

        def _normalize(s: str) -> str:
            return ClassificationService._normalize_name(s)

        alias_n = _normalize(alias)
        haystack_n = _normalize(haystack)

        if not alias_n or not haystack_n:
            return 0.5

        # v1.3.48 - Find bracket boundary (e.g. "QuickBooks ... - [Vendor Center: ...]")
        # Bracket may be normalized away — we need to find it in the RAW
        # haystack and project the split into the normalized one.
        raw_bracket_pos = haystack.find(' - [')
        if raw_bracket_pos > 0:
            # Apply same normalization to the pre-bracket portion to find
            # its position in normalized space
            raw_pre = haystack[:raw_bracket_pos]
            pre_bracket = _normalize(raw_pre)
            # Everything after pre_bracket in haystack_n is "in_bracket"
            in_bracket = haystack_n[len(pre_bracket):].strip()
        else:
            pre_bracket = haystack_n
            in_bracket = ''

        # v1.3.48 Tier 1: Contiguous match in pre-bracket region.
        # This is the dominant signal — a client name appearing as a
        # contiguous phrase at or near the start of the title is the
        # strongest evidence we can get.
        alias_pos = pre_bracket.find(alias_n)
        if alias_pos == 0:
            return 1.0
        if 0 < alias_pos < 10:
            return 0.95
        if alias_pos > 0:
            return 0.85

        # v1.3.48 Tier 2: Alias matches ONLY inside the bracket.
        # QB vendor-center brackets contain vendor/customer names that are
        # NOT the client whose file the user is working on. Drop the score.
        if in_bracket and alias_n in in_bracket:
            return 0.40

        # v1.3.75: WHOLE-NAME SIMILARITY GATE for the token-coverage fallback.
        # Token-coverage lets a client match on scattered shared words even
        # when the overall names are nothing alike — e.g. "CNY Coin & Silver"
        # matching "All Around Auto Repair and Sales Corp" on generic tokens.
        # Require the alias to genuinely RESEMBLE the title (as a whole or as
        # its leading chunk) before any scatter-match score is allowed.
        # Proven: "All Round Repair"≈"All Around Auto Repair" = 0.90 (keep),
        # "CNY Coin & Silver" = 0.39 (reject). Contiguous Tiers 1/2 above are
        # unaffected — they're already high-similarity by definition.
        from difflib import SequenceMatcher
        _WHOLE_NAME_GATE = 0.70
        _whole = SequenceMatcher(None, alias_n, pre_bracket).ratio()
        # Also test the leading chunk of the title (length of alias + slack),
        # so trailing window chrome ("- Work - Microsoft Edge") doesn't dilute
        # an otherwise-strong leading-name match.
        _lead_chunk = pre_bracket[:len(alias_n) + 5]
        _lead = SequenceMatcher(None, alias_n, _lead_chunk).ratio()
        _name_sim = max(_whole, _lead)
        if _name_sim < _WHOLE_NAME_GATE:
            return 0.0

        # Tier 3 (existing v1.3.24 behavior): Token-coverage fallback.
        # For aliases whose words appear scattered through the haystack
        # rather than contiguously. Capped at 0.5 so non-contiguous
        # matches always lose to contiguous ones above.
        alias_tokens = [
            t for t in alias_n.split()
            if len(t) >= 4
            and t not in ALIAS_STOP_WORDS
            and t not in ALIAS_GENERIC_SUFFIXES
        ]
        distinctive_alias = [t for t in alias_tokens if t not in DOMAIN_COMMON_WORDS]
        if not distinctive_alias:
            return 0.5

        haystack_tokens = haystack_n.split()
        haystack_set = set(haystack_tokens)

        # v1.3.48: Weight pre-bracket token matches at full value,
        # in-bracket matches at 0.3x.
        pre_bracket_tokens = set(pre_bracket.split())
        in_bracket_tokens = set(in_bracket.split()) if in_bracket else set()

        matched_score = 0.0
        for ct in distinctive_alias:
            # Direct token match
            if ct in pre_bracket_tokens:
                matched_score += 1.0
                continue
            if ct in in_bracket_tokens:
                matched_score += 0.3
                continue
            # v1.3.53: Fuzzy 5+ char prefix match (tightened from 4).
            # 4 was too loose: "complete" matched "complex" (both share
            # "comp"), causing client name false matches against common
            # English words in haystack. 5+ chars rejects this while
            # preserving legitimate near-matches like "cemete"/"cemetery"
            # (6 char shared prefix). Possessive variants ("mary"/"marys")
            # are already handled by _normalize's stem-trailing-s logic.
            for ht in pre_bracket_tokens:
                if len(ht) < 6 or ht in DOMAIN_COMMON_WORDS:
                    continue
                cp = 0
                for x, y in zip(ct, ht):
                    if x != y:
                        break
                    cp += 1
                if cp >= 6 and cp >= 0.7 * min(len(ct), len(ht)):
                    matched_score += 1.0
                    break

        coverage = matched_score / len(distinctive_alias)
        # Cap at 0.5 so non-contiguous matches lose to contiguous ones
        return min(0.5, coverage * 0.5)

    @staticmethod
    def _alias_matches_safely(alias: str, haystack: str) -> bool:
        """
        Match an alias against text using token-based matching with
        CPA-friendly normalization.

        v1.3.22: Replaces brittle substring matching that failed on
        apostrophe/possessive/extra-word variants. For example,
        previously "St. Theresa's Church" required the literal string
        "st. theresa's church" to appear contiguously in the haystack,
        which never happens in real titles like
        "St. Theresa Catholic Church - QuickBooks...".

        Strategy (mirrors agent's LearnedRules._title_contains_client):
          1. Normalize both strings (St. → Saint, strip apostrophes,
             stem possessive 's, split hyphens, strip punctuation)
          2. Direct substring match still preferred (cheap, exact)
          3. Token-based fallback with fuzzy-prefix matching
          4. For multi-token aliases: require >=2 token matches AND
             >=1 distinctive (non-domain-common) match
          5. Single-token aliases: require 1 match, reject if the
             token itself is domain-common

        Other safety: stops "Internal" matching "Internal Revenue
        Service" via word-boundary requirement; stops "St. Patrick"
        matching "St. Theresa" via distinctive-token requirement.
        """
        import re

        a = alias.strip().lower()
        if not a or not haystack:
            return False

        def _normalize(s: str) -> str:
            return ClassificationService._normalize_name(s)

        alias_n = _normalize(a)
        haystack_n = _normalize(haystack)

        # v1.3.23: Generic-haystack early reject. If the title is entirely
        # generic app/file vocabulary (no client-specific tokens), refuse
        # to fire any strong match. Catches "client tracking file 2025 -
        # Excel", "CS Connect Background Services", etc.
        haystack_token_set_early = set(haystack_n.split())
        haystack_distinctive = [
            t for t in haystack_token_set_early
            if len(t) >= 4 and t not in GENERIC_HAYSTACK_WORDS
        ]
        if not haystack_distinctive:
            return False

        # Direct substring hit — easiest case, preserves prior behavior
        # for aliases that already matched exactly.
        if alias_n and alias_n in haystack_n:
            return True

        # Token-based fallback
        alias_tokens = [
            t for t in alias_n.split()
            if len(t) >= 4
            and t not in ALIAS_STOP_WORDS
            and t not in ALIAS_GENERIC_SUFFIXES
        ]

        if not alias_tokens:
            # Alias is entirely stop words / suffixes / too short — already
            # failed substring check above, so reject.
            return False

        haystack_tokens = haystack_n.split()
        haystack_token_set = set(haystack_tokens)

        # Count total matches with fuzzy-prefix support
        def _token_matches(at, htoks, hset, allow_domain_common_fuzzy=True):
            """Direct match, or 4+ char shared prefix with a haystack token."""
            if at in hset:
                return True
            for ht in htoks:
                if len(ht) < 6:
                    continue
                if not allow_domain_common_fuzzy and ht in DOMAIN_COMMON_WORDS:
                    continue
                # v1.3.74: Tightened fuzzy-prefix from 5 to 6 chars AND require
                # the shared prefix to cover >=70% of the shorter token. 5 chars
                # let "transaction" match "transfiguration" (5 shared: t-r-a-n-s),
                # billing a personal "Syracuse Mets Transaction" email to
                # Transfiguration Church. 70% coverage rejects that (5/11 = 45%)
                # while keeping real near-matches like "cemete"/"cemetery" (6/8 = 75%).
                cp = 0
                for x, y in zip(at, ht):
                    if x != y:
                        break
                    cp += 1
                if cp >= 6 and cp >= 0.7 * min(len(at), len(ht)):
                    return True
            return False

        total_matches = sum(
            1 for at in alias_tokens
            if _token_matches(at, haystack_tokens, haystack_token_set, True)
        )


        # NEW CODE:
        if len(alias_tokens) == 1:
            sole_token = alias_tokens[0]
            if sole_token in DOMAIN_COMMON_WORDS:
                return False
            if sole_token in SINGLE_TOKEN_ALIAS_BLOCKLIST:
                return False
            # CRITICAL: If the ORIGINAL alias was multi-word but stop-word
            # filtering reduced it to a single token, treat the alias as
            # requiring contiguous match. The direct substring check at the
            # top of this function already covers that case — by the time we
            # reach here, the contiguous check failed, so reject.
            #
            # This prevents "ASR Systems Group" from matching every title
            # containing "Systems", and "H & B Marketing" from matching every
            # title containing "Market" (via fuzzy prefix).
            original_word_count = len([w for w in alias_n.split() if w])
            if original_word_count > 1:
                return False
            # True single-word original alias (e.g. user explicitly set
            # alias="Smithco" for a client named "Smith Corporation").
            # That's intentional and we trust it. But still require an
            # exact token match — no fuzzy prefix for single-word aliases.
            return sole_token in haystack_token_set

        # Multi-token alias: 2+ total matches AND >=1 distinctive match
        if total_matches < 2:
            return False

        distinctive_alias_tokens = [
            t for t in alias_tokens if t not in DOMAIN_COMMON_WORDS
        ]
        if not distinctive_alias_tokens:
            return False

        distinctive_matches = sum(
            1 for at in distinctive_alias_tokens
            if _token_matches(at, haystack_tokens, haystack_token_set, False)
        )

        if distinctive_matches < 1:
            return False

        # v1.3.54: PROXIMITY CHECK. For multi-token aliases, the matched
        # tokens must appear close together in the haystack. Without this,
        # unrelated content with coincidental word collisions matches —
        # e.g. "Salt City Harvest Farm" matches a haystack containing
        # "salt additives" (token 30) AND "city water" (token 60) even
        # though the user was researching two unrelated topics.
        #
        # Rule: at least 2 of the alias's distinctive tokens must appear
        # within MAX_PROXIMITY_TOKENS of each other in the haystack. This
        # enforces "these words appeared as a phrase or near-phrase,"
        # not "these words happened to appear somewhere in this long
        # document."
        MAX_PROXIMITY_TOKENS = 2

        # Find positions of each distinctive alias token in the haystack
        positions_by_token = {}
        for at in distinctive_alias_tokens:
            positions = []
            for i, ht in enumerate(haystack_tokens):
                if ht == at:
                    positions.append(i)
                    continue
                # Fuzzy prefix (v1.3.74: 6+ char shared AND >=70% of shorter token)
                if len(ht) < 6 or ht in DOMAIN_COMMON_WORDS:
                    continue
                cp = 0
                for x, y in zip(at, ht):
                    if x != y:
                        break
                    cp += 1
                if cp >= 6 and cp >= 0.7 * min(len(at), len(ht)):
                    positions.append(i)
            if positions:
                positions_by_token[at] = positions

        # Need at least 2 distinct tokens with positions
        if len(positions_by_token) < 2:
            # Only 1 distinctive token matched — fall back to strict requirement:
            # require the FULL alias to appear contiguously (already failed at
            # substring check at top of function, so reject).
            return False

        # Check if any pair of distinctive tokens is within MAX_PROXIMITY_TOKENS
        # of each other in the haystack.
        all_positions = sorted(
            (pos, tok)
            for tok, positions in positions_by_token.items()
            for pos in positions
        )

        close_pair_found = False
        for i in range(len(all_positions) - 1):
            pos_a, tok_a = all_positions[i]
            for j in range(i + 1, len(all_positions)):
                pos_b, tok_b = all_positions[j]
                if pos_b - pos_a > MAX_PROXIMITY_TOKENS:
                    break  # sorted; further pairs are even farther
                if tok_a != tok_b:
                    # Two DIFFERENT distinctive tokens within proximity window
                    close_pair_found = True
                    break
            if close_pair_found:
                break

        if not close_pair_found:
            return False

        # v1.3.23: Entity-class exclusion check. If the title and the
        # client name contain words from opposed classes (e.g. title
        # says "Church", client name says "Cemetery"), reject the match.
        # Same parish often has church + cemetery + fund as DIFFERENT
        # accounting clients — matching one to the other is always wrong.
        for class_group in EXCLUSIVE_ENTITY_CLASSES:
            alias_classes = class_group & set(alias_tokens)
            haystack_classes = class_group & haystack_token_set
            # If both sides have an entity class word from this group,
            # they must agree (be the same word). If they disagree,
            # reject.
            if alias_classes and haystack_classes:
                if not (alias_classes & haystack_classes):
                    return False

        return True


    @staticmethod
    def _strip_qb_screen_bracket(title: str) -> str:
        """
        v1.3.55: Strip QuickBooks Desktop screen bracket from a title.

        QB titles have structure:
          "{company_file} - QuickBooks Accountant Desktop Plus 2024 - [{screen}]"

        The bracket changes as the user navigates QB screens (Home, Vendor
        Center, Customer Center: <name>, Write Checks, etc.) and contains
        vendor/customer names that hijack client attribution.

        For client identification, ONLY the company file name (pre-bracket)
        matters. Strip everything from ' - [' onward.

        Mirrors agent's _strip_qb_screen_bracket in ai_client_switcher.py.
        Returns title unchanged if not a QB window.
        """
        if not title:
            return title
        title_lower = title.lower()
        if 'quickbooks' not in title_lower and 'qbw' not in title_lower:
            return title
        bracket_pos = title.rfind(' - [')
        if bracket_pos > 0:
            return title[:bracket_pos]
        return title

    @staticmethod
    def _build_haystack(block) -> str:
        """Combine searchable text fields into one lowercase string.

        File path is cleaned via _clean_path_segments to strip OS user home,
        AppData, Temp, Protected View randomized dirs, etc. Otherwise the
        Windows username (e.g. C:\\Users\\mavops\\) would produce false matches
        against clients whose name happens to equal the OS username.

        v1.3.51: Aggregate distinct titles from ALL raw events in the block.
        v1.3.55: Strip QuickBooks screen brackets from EVERY title before
        adding to the haystack. The bracket contains vendor/customer names
        that hijack attribution when the user navigates QB Customer Center.
        Mirrors the agent's _strip_qb_screen_bracket logic.
        """
        primary_title = ClassificationService._strip_qb_screen_bracket(
            block.window_title or block.title or ''
        )
        parts = [
            primary_title,
            (block.url or ''),
        ]

        if block.file_path:
            username = _infer_username_from_path(block.file_path)
            cleaned_segments = _clean_path_segments(block.file_path, username)
            if cleaned_segments:
                parts.append(' '.join(cleaned_segments))

        try:
            from tracker.models import RawEvent
            event_titles = list(
                RawEvent.objects
                .filter(block=block)
                .exclude(window_title__exact='')
                .exclude(window_title__isnull=True)
                .values_list('window_title', flat=True)
                .distinct()
            )
            block_title_lower = (primary_title or '').lower()
            for t in event_titles:
                if not t:
                    continue
                # v1.3.55: strip QB bracket from each event title too
                stripped = ClassificationService._strip_qb_screen_bracket(t)
                if stripped and stripped.lower() != block_title_lower:
                    parts.append(stripped)
        except Exception:
            pass

        return ' '.join(p for p in parts if p).lower()

    @staticmethod
    def _extract_domain(url: str) -> str:
        """
        Extract the registered domain from a URL.
        'https://app.smithco.com/dashboard' → 'smithco.com'
        Returns empty string on parse failure.
        """
        if not url:
            return ''
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url if '://' in url else f'http://{url}')
            host = parsed.hostname or ''
            # Strip 'www.' prefix
            if host.startswith('www.'):
                host = host[4:]
            return host.lower()
        except Exception:
            return ''

    # -------------------------------------------------------------------------
    # STAGE 4 — File path structure analysis
    # -------------------------------------------------------------------------

    def _stage_4_file_path(self, block, decision: 'ClassificationDecision'):
        """
        Analyze file_path STRUCTURE for client signals beyond simple containment
        (which Stage 3 already does).
 
        Patterns to detect:
          1. Client name as a clean folder segment (highest signal)
             Example: '/Clients/Wood, Michael/2024/return.pdf' → 'Wood, Michael'
          2. Client name in a 'Clients' or 'Customers' container folder
             Example: 'C:/Customers/Acme Corp/Q4/file.xlsx' → 'Acme Corp'
          3. UNC paths with client folder structure
             Example: '\\\\server\\Shared\\Acme Corp\\file.pdf' → 'Acme Corp'
 
        Strength: 0.90 for clean folder segment match, 0.85 for container-folder match.
 
        v1.3.41 changes:
          - Skip entirely when window indicates Office Protected View
          - Strip OS user home, AppData, Temp, etc. before segment analysis
          - Drop randomized Office sandbox folder names (oice_*, temp UUIDs)
 
        Skipped if:
          - file_path is empty
          - Office Protected View detected
          - No client matches with sufficient specificity after cleaning
        """
        file_path = (block.file_path or '').strip()
        if not file_path:
            return
 
        # v1.3.41: skip Protected View entirely — path is a sandbox temp dir
        if _is_office_protected_view(block.window_title):
            return
 
        # v1.3.41: clean segments before matching
        username = _infer_username_from_path(file_path)
        segments = _clean_path_segments(file_path, username)
        if not segments:
            return
 
        # Look for "Clients" / "Customers" container — client name should follow
        CONTAINER_NAMES = {'clients', 'customers', 'firms', 'accounts'}
        container_idx = -1
        for i, seg in enumerate(segments):
            if seg in CONTAINER_NAMES:
                container_idx = i
                break
 
        best_client = None
        best_strength = 0.0
        best_evidence = ''
 
        for client in self._clients:
            if client.name.lower().strip() in META_CLIENT_NAMES:
                continue
 
            name_lower = client.name.lower()
            aliases = [a.lower() for a in (client.aliases or [])] if client.aliases else []
            all_names = [name_lower] + aliases
 
            for alias in all_names:
                if not self._alias_is_safe(alias):
                    continue
 
                # Pattern 1: Clean folder segment match
                if alias in segments:
                    if 0.90 > best_strength:
                        best_client = client
                        best_strength = 0.90
                        best_evidence = (
                            f"File path contains client folder '{alias}' "
                            f"(segment match in '{file_path}')"
                        )
                    break
 
                # Pattern 2: Container-relative match
                if container_idx >= 0 and container_idx + 1 < len(segments):
                    next_seg = segments[container_idx + 1]
                    if alias in next_seg or next_seg.startswith(alias):
                        if 0.85 > best_strength:
                            best_client = client
                            best_strength = 0.85
                            best_evidence = (
                                f"File path contains client folder '{next_seg}' "
                                f"under '{segments[container_idx]}/' container"
                            )
                        break
 
        if not best_client:
            return
 
        decision.matched_signals.append(Signal(
            type='file_path_structure',
            strength=best_strength,
            evidence=best_evidence,
            detail={
                'client_id':   best_client.id,
                'client_name': best_client.name,
                'file_path':   file_path[:200],
            },
        ))


    # -------------------------------------------------------------------------
    # STAGE 6 — CALENDAR EVENT OVERLAP (v1.3.42)
    # -------------------------------------------------------------------------
    #
    # v1.3.42 additions over the prior implementation:
    #
    #   (a) Flips decision.is_meeting = True when overlap >= 70% AND match
    #       confidence >= 0.80 AND block duration >= 3 minutes. Calendar wins
    #       over audio/camera detector (calendar is intent, audio/camera was
    #       always an inference — listen-only calls, phone dial-ins, and
    #       browser meetings the detector misses all get caught).
    #
    #   (b) Stashes calendar-proposed client on decision.detail so apply() can
    #       perform mail-style reconciliation and set the disagreement flag.
    #       Mirrors the Stage 7 mail pattern exactly.
    #
    # Ghost-meeting risk (calendar says meeting but user actually skipped it
    # and worked on something else): mitigated by the existing contradicting-
    # signal check in _finalize_decision. A strong Stage 3 title_match for a
    # different client will force the block to 'proposed' for human review
    # rather than auto-committing as a Bowers meeting block.

    def _stage_6_calendar(self, block, decision: ClassificationDecision):
        """
        Use overlapping CalendarEvent records as a classification signal and
        (new in v1.3.42) as a meeting source.

        Calendar events are pre-matched to clients during sync via
        tracker.calendar_matching.find_best_match. This stage reads the pre-
        computed extracted_client / extraction_confidence — zero network calls
        in the hot path.

        Behavior:
          - Find CalendarEvents for self.user that overlap [block.start, block.end]
          - Filter to events with extracted_client and extraction_confidence >= 0.70
          - Pick the event with greatest overlap
          - Emit a Signal proportional to overlap percentage and match confidence
          - If overlap >= 70% AND match_conf >= 0.80 AND block.minutes >= 3:
              * Set decision.is_meeting = True
              * Existing _filter_foreground_inside_meetings then handles
                supersede semantics for foreground apps inside the meeting
          - Always stash calendar-proposed client on decision.detail for
            apply()-time disagreement reconciliation (see FIX D in apply())

        Signal strength is downgraded from raw match confidence:
          - direct rule match (0.95) → signal 0.80 (strong, near-auto-commit)
          - fuzzy title match (0.80) → signal 0.65 (moderate)
          - fuzzy alias (0.75)       → signal 0.55 (weak corroborator)
        Strength is further modulated by overlap percentage and capped at 0.85
        so calendar alone never auto-commits without corroboration.
        """
        from tracker.models import CalendarEvent

        # Feature flag — org must opt in. Currently mavops only.
        if not getattr(self.org, 'calendar_classification_enabled', False):
            return

        if not block.start or not block.end:
            return

        block_seconds = (block.end - block.start).total_seconds()
        if block_seconds <= 0:
            return

        # Cache events per (user, date) so back-to-back classify() calls
        # don't re-query.
        cache_key = f"{self.user.id}:{block.start.date().isoformat()}"
        if cache_key not in self._calendar_events_cache:
            day_start = block.start.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            self._calendar_events_cache[cache_key] = list(
                CalendarEvent.objects.filter(
                    user=self.user,
                    extracted_client__isnull=False,
                    extraction_confidence__gte=0.70,
                    start__lt=day_end,
                    end__gt=day_start,
                ).select_related('extracted_client').order_by('start')
            )

        candidates = self._calendar_events_cache[cache_key]
        if not candidates:
            return

        # Find the event with greatest temporal overlap with this block
        best_event = None
        best_overlap_seconds = 0.0

        for evt in candidates:
            overlap_start = max(evt.start, block.start)
            overlap_end = min(evt.end, block.end)
            overlap = (overlap_end - overlap_start).total_seconds()
            if overlap <= 0:
                continue
            if overlap > best_overlap_seconds:
                best_event = evt
                best_overlap_seconds = overlap

        if not best_event or best_overlap_seconds <= 0:
            return

        overlap_pct = best_overlap_seconds / block_seconds

        # Stage 6 attribution threshold — at least 30% of block coincides
        if overlap_pct < 0.30:
            return

        # Map raw match confidence to signal strength
        match_conf = best_event.extraction_confidence or 0.0
        if match_conf >= 0.95:
            base_strength = 0.80   # direct rule (OrgCalendarRule)
        elif match_conf >= 0.80:
            base_strength = 0.65   # fuzzy title
        elif match_conf >= 0.70:
            base_strength = 0.55   # fuzzy alias
        else:
            return

        # Modulate by overlap (30% → 0.85x of base, 100% → 1.0x)
        overlap_modifier = 0.85 + (0.15 * overlap_pct)
        strength = round(base_strength * overlap_modifier, 2)
        strength = min(strength, 0.85)  # cap — never auto-commits alone

        client = best_event.extracted_client
        evidence = (
            f"Calendar: '{best_event.title[:60]}' "
            f"({int(overlap_pct * 100)}% overlap)"
        )

        decision.matched_signals.append(Signal(
            type='calendar',
            strength=strength,
            evidence=evidence,
            detail={
                'client_id':        client.id,
                'client_name':      client.name,
                'event_id':         best_event.id,
                'event_title':      best_event.title,
                'overlap_pct':      round(overlap_pct, 2),
                'match_method':     'calendar_overlap',
                'match_confidence': match_conf,
            },
        ))

        # ─── v1.3.42 (a): meeting flag from calendar ──────────────────────────
        # Require all three conditions to avoid false-positive meeting flags:
        #   - High overlap so we're confident the block IS the meeting
        #   - Strong match confidence (direct rule or strong fuzzy)
        #   - Non-transient block (>= 3 min) so we don't flag drive-bys
        is_meeting_candidate = (
            overlap_pct >= 0.70
            and match_conf >= 0.80
            and (block.minutes or 0) >= 3
        )
        if is_meeting_candidate:
            decision.is_meeting = True
            logger.info(
                f"[STAGE-6-MEETING] Block {getattr(block, 'pk', None)} flagged is_meeting=True "
                f"via calendar: event '{best_event.title[:60]}' "
                f"overlap={overlap_pct:.0%} match_conf={match_conf:.2f}"
            )

        # ─── v1.3.42 (b): stash for apply()-time disagreement reconciliation ─
        # apply() compares this to the final block.client_id after all stages
        # and writes calendar_disagrees_with_agent if they disagree. Mirrors
        # the Stage 7 mail pattern.
        decision.detail = getattr(decision, 'detail', {}) or {}
        decision.detail['calendar_proposed_client_id'] = client.id
        decision.detail['calendar_proposed_client_name'] = client.name
        decision.detail['calendar_proposed_confidence'] = strength
        decision.detail['calendar_proposed_evidence'] = evidence
        decision.detail['calendar_event_title'] = best_event.title


    # -------------------------------------------------------------------------
    # STAGE 7 — Mail metadata match (v2 — with Outlook boost + disagreement)
    # -------------------------------------------------------------------------
    #
    # Replaces the v1 _stage_7_mail. Two new behaviors:
    #
    # FIX A — Outlook strength boost:
    #   When the block's app is Outlook (or window title looks email-like),
    #   the user is *in their email client*, so MailSignal evidence is
    #   authoritative — not corroborating. Strength is boosted so Stage 7
    #   outranks Stage 8 (agent_current_client at 0.55) and breaks the
    #   inheritance bug where Outlook activity gets bucketed into whatever
    #   client the agent had selected before alt-tabbing.
    #
    #     Outlook block + domain match only      → strength 0.70 (was 0.45)
    #     Outlook block + subject_extract present → strength 0.85 (was 0.65)
    #     Non-Outlook block (any other app)      → unchanged from v1
    #
    # FIX B — Mail-vs-attribution disagreement detection:
    #   Even when Stage 7 doesn't dominate the decision, if mail signals
    #   point to a different client than the block ends up attributed to,
    #   we set block.mail_disagrees_with_agent = True and surface in Daily
    #   Review. Mirrors the existing ai_disagrees_with_agent pattern.
    #
    #   We don't OVERWRITE the attribution — we just flag for review. The
    #   user decides. If we silently overwrote, we'd just trade one
    #   inheritance bug for another.

    def _stage_7_mail(self, block, decision: 'ClassificationDecision'):
        """
        Use MailSignal records around the block's time as a classification signal.

        See module-level docstring above for behavior changes vs. v1.
        """
        from tracker.models import MailSignal

        # Honor org-level kill switch
        if getattr(self.org, 'disable_mail_integration', False):
            return

        if not block.start:
            return

        # Cache per (user, date) — same pattern as Stage 6 calendar
        cache_key = f"{self.user.id}:{block.start.date().isoformat()}"
        if cache_key not in self._mail_signals_cache:
            day_start = block.start.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            self._mail_signals_cache[cache_key] = list(
                MailSignal.objects
                .filter(
                    user=self.user,
                    extracted_client__isnull=False,
                    occurred_at__gte=day_start - timedelta(hours=4),
                    occurred_at__lt=day_end + timedelta(hours=1),
                )
                .select_related('extracted_client')
                .order_by('occurred_at')
            )

        candidates = self._mail_signals_cache[cache_key]
        if not candidates:
            return

        # Window: 2 hours before block start through 30 min after
        window_start = block.start - timedelta(hours=2)
        window_end = block.start + timedelta(minutes=30)

        # Group signals by client, track best one (subject_extract > domain only)
        from collections import defaultdict
        per_client = defaultdict(lambda: {
            'signals': [],
            'has_subject_extract': False,
            'best_signal': None,
            'count': 0,
        })

        for sig in candidates:
            if not (window_start <= sig.occurred_at <= window_end):
                continue
            cid = sig.extracted_client_id
            entry = per_client[cid]
            entry['signals'].append(sig)
            entry['count'] += 1
            if sig.subject_extract:
                entry['has_subject_extract'] = True
                entry['best_signal'] = sig
            elif entry['best_signal'] is None:
                entry['best_signal'] = sig

        if not per_client:
            return

        # Pick the client with the most signals; tie-break by has_subject_extract
        best_cid, best_entry = max(
            per_client.items(),
            key=lambda kv: (kv[1]['count'], kv[1]['has_subject_extract']),
        )

        best_signal = best_entry['best_signal']
        if not best_signal:
            return

        client = best_signal.extracted_client

        # ─── FIX A: Outlook boost ─────────────────────────────────────────────
        is_outlook_block = self._is_outlook_or_email_block(block)

        if best_entry['has_subject_extract']:
            strength = 0.85 if is_outlook_block else 0.65
        else:
            strength = 0.70 if is_outlook_block else 0.45

        # Multi-signal corroboration (3+ signals from same client = stronger)
        # Cap higher in Outlook context to make it dominant.
        if best_entry['count'] >= 3:
            cap = 0.90 if is_outlook_block else 0.70
            strength = min(strength + 0.05, cap)

        # Direction-aware evidence string
        direction_label = 'received from' if best_signal.direction == 'in' else 'sent to'

        outlook_marker = ' [Outlook block — authoritative]' if is_outlook_block else ''
        evidence = (
            f"Mail: {best_entry['count']} signal(s) "
            f"{direction_label} {best_signal.other_party_domain} → "
            f"{client.name}"
            f"{outlook_marker}"
        )
        if best_signal.subject_extract:
            evidence += f" — subject: '{best_signal.subject_extract[:50]}'"

        decision.matched_signals.append(Signal(
            type='mail',
            strength=strength,
            evidence=evidence,
            detail={
                'client_id':           client.id,
                'client_name':         client.name,
                'signal_count':        best_entry['count'],
                'has_subject_extract': best_entry['has_subject_extract'],
                'other_party_domain':  best_signal.other_party_domain,
                'direction':           best_signal.direction,
                'window_minutes':      150,
                'is_outlook_block':    is_outlook_block,
                'subject_extract':     best_signal.subject_extract or '',
            },
        ))

        # ─── FIX B: Mail-vs-attribution disagreement detection ─────────────────
        # Stash the mail-proposed client/conf on the decision so apply()
        # can write it to the Block AFTER the final attribution is settled.
        # We don't know yet whether mail will end up agreeing or disagreeing;
        # _finalize_decision determines that based on the full signal set.
        decision.detail = getattr(decision, 'detail', {}) or {}
        decision.detail['mail_proposed_client_id'] = client.id
        decision.detail['mail_proposed_client_name'] = client.name
        decision.detail['mail_proposed_confidence'] = strength
        decision.detail['mail_proposed_evidence'] = evidence

    @staticmethod
    def _is_outlook_or_email_block(block) -> bool:
            """
            Returns True when the block represents the user actively in their
            email client. Used by Stage 7 to boost mail signal strength.

            Detection order (most reliable first):
              1. app_name contains 'outlook' (Mac/full process names)
              2. app_name is 'olk' (Windows agent abbreviates to 'Olk')
              3. window_title contains email-client markers — handles webmail
                 AND the abbreviated case where app_name is 'Olk' but the
                 window title still ends in 'Outlook'
            """
            app = (getattr(block, 'app_name', '') or '').lower()
            if 'outlook' in app or app == 'olk':
                return True

            # Title-based detection — catches abbreviated app names AND
            # webmail in browser tabs
            title = (getattr(block, 'window_title', '') or getattr(block, 'title', '') or '').lower()
            EMAIL_TITLE_MARKERS = (
                ' - outlook',           # NEW: Windows window titles end in "- Outlook"
                'outlook.exe',
                ' - inbox',
                'message (html)',
                'message (plain text)',
                'mail.google.com',      # Gmail in browser
                'outlook.office.com',   # OWA
                'outlook.live.com',
            )
            return any(marker in title for marker in EMAIL_TITLE_MARKERS)

    def _try_emit_inference_signal(self, block, decision: ClassificationDecision) -> bool:
        """
        v1.4.0: Read the agent's structured inference output (RawEvent.inference)
        and emit an 'agent_inference' signal if confidence is above the floor.

        Strategy: scan all RawEvents in this block, use the highest-confidence
        inference among them (per design decision 3b — better accuracy at the
        cost of a small extra scan).

        Returns True if a signal was emitted; the caller should then skip the
        legacy agent_current_client emission to avoid double-counting (since
        the inference signal already incorporates the same underlying agent
        observation, plus richer evidence).
        """
        from tracker.models import RawEvent

        raw_events = RawEvent.objects.filter(block=block)
        if not raw_events.exists():
            return False

        best_inference = None
        best_confidence = 0.0
        best_event_id = None
        for ev in raw_events:
            inf = ev.inference
            if not inf:
                continue
            cid = inf.get('client_id')
            if not cid:
                continue
            conf = inf.get('confidence', 0.0) or 0.0
            if conf > best_confidence:
                best_confidence = conf
                best_inference = inf
                best_event_id = ev.id

        if not best_inference or best_confidence < 0.4:
            return False

        cid = best_inference['client_id']
        client = next((c for c in self._clients if c.id == cid), None)
        if not client:
            logger.warning(
                f"[STAGE-8-INF] Block {getattr(block, 'pk', '?')}: "
                f"inference points to unknown client_id={cid}, skipping"
            )
            return False

        evidence_sources = [
            e.get('source', '?') for e in best_inference.get('evidence', [])
        ]

        # v1.4.1 FORWARD-FILL GUARD.
        # An agent inference sourced from a CARRIED signal — a QB company file
        # still open from prior work, or plain agent stickiness — is the
        # dominant mis-attribution mode (the St. John / Sacred Heart reconcile
        # family). Two defenses:
        #   (a) if such an inference names client Y but an AUTHORITATIVE Stage 3
        #       signal (title_alias/file_path/domain) already named a DIFFERENT
        #       client X, the window literally shows X — cap the inference below
        #       the propose gate so it can't outrank or corroborate around X;
        #   (b) on a browser block with no independent corroboration, suppress
        #       the carry-prone inference entirely (alt-tab-to-news leak).
        # Inferences derived from THIS block's own text (title_alias/file_path
        # sources) are NOT carry-prone and are left untouched.
        STICKINESS_INFERENCE_SOURCES = {
            'qb_company_file', 'agent_current_client', 'prior_block',
            'stickiness', 'cached_client',
        }
        source_is_carry_prone = any(
            src in STICKINESS_INFERENCE_SOURCES for src in evidence_sources
        )

        # (b) browser forward-fill: carry-prone + browser + no corroboration → drop.
        _app_lower = (block.app_name or '').lower()
        _BROWSER_APPS = {'msedge', 'chrome', 'firefox', 'brave',
                         'safari', 'opera', 'iexplore'}
        if _app_lower in _BROWSER_APPS and source_is_carry_prone:
            _CORROBORATING = {
                'title_match_title_alias', 'title_match_file_path',
                'title_match_domain', 'file_path_structure', 'calendar',
                'mail', 'learned_pattern', 'org_rule', 'tax_software',
            }
            _has_corr = any(
                s.detail and s.detail.get('client_id') == cid
                and s.type in _CORROBORATING
                for s in decision.matched_signals
            )
            if not _has_corr:
                logger.info(
                    f"[STAGE-8-INF] Block {getattr(block, 'pk', '?')}: "
                    f"suppressing carry-prone agent_inference on browser block "
                    f"({_app_lower}) — no corroboration for client_id={cid} "
                    f"(sources={evidence_sources})"
                )
                return False

        # (a) competing authoritative Stage 3 signal naming a DIFFERENT client.
        _AUTHORITATIVE = {
            'title_match_title_alias', 'title_match_file_path', 'title_match_domain',
        }
        _competing = next(
            (s for s in decision.matched_signals
             if s.type in _AUTHORITATIVE and s.detail
             and s.detail.get('client_id')
             and s.detail.get('client_id') != cid),
            None,
        )
        forward_fill_suspect = source_is_carry_prone and _competing is not None

        # Map agent confidence to classifier signal strength.
        # Agent's confidence already factors in evidence quality + decay, so
        # we trust it more than the flat-0.45 legacy signal.
        if best_confidence >= 0.85:
            signal_strength = 0.85   # strong
        elif best_confidence >= 0.70:
            signal_strength = 0.75   # moderate-strong
        elif best_confidence >= 0.60:
            signal_strength = 0.65   # moderate
        else:
            signal_strength = 0.45   # weak

        if forward_fill_suspect:
            # Cap below the Stage 3 title floor (0.82) AND the propose gate
            # (0.65) so a stale QB-file inference can neither win against nor
            # corroborate around the authoritative title naming client X.
            _capped = min(signal_strength, 0.45)
            logger.info(
                f"[STAGE-8-INF] Block {getattr(block, 'pk', '?')}: forward-fill "
                f"suspect — inference client={client.name} "
                f"(sources={evidence_sources}) conflicts with authoritative "
                f"Stage 3 client_id={_competing.detail.get('client_id')}; "
                f"capping {signal_strength}->{_capped}, marking stickiness"
            )
            signal_strength = _capped

        decision.matched_signals.append(Signal(
            type='agent_inference',
            strength=signal_strength,
            evidence=(
                f"Agent inferred '{client.name}' with confidence "
                f"{best_confidence:.2f} from {evidence_sources}"
            ),
            detail={
                'client_id': client.id,
                'client_name': client.name,
                'inference_confidence': best_confidence,
                'inference_evidence_sources': evidence_sources,
                'source_event_id': best_event_id,
                # v1.4.1: carry-prone inferences count as stickiness (not
                # independent attestation) for FIX 7 / Mets guard.
                'is_stickiness_inference': source_is_carry_prone,
                'forward_fill_capped': forward_fill_suspect,
            },
        ))

        logger.info(
            f"[STAGE-8-INF] Block {getattr(block, 'pk', '?')}: "
            f"agent_inference signal emitted client={client.name} "
            f"confidence={best_confidence:.2f} strength={signal_strength} "
            f"evidence={evidence_sources}"
        )

        return True

    # -------------------------------------------------------------------------
    # STAGE 8 — Recent context (current_client_id, prior block)
    # -------------------------------------------------------------------------

    def _stage_8_recent_context(self, block, decision: ClassificationDecision):
        """
        Use agent's current_client_id and the previous block as weak-to-moderate
        signals.

        Hardened (v2 of foundation chunk):
          1. Idle blocks (the user wasn't working on anything) DO NOT receive
             prior_block signals. By definition the user wasn't on a client.
          2. prior_block reads ONLY from blocks where state_changed_by indicates
             human confirmation ('user' or 'correction'). Auto-classified prior
             blocks are not authoritative — using them propagates errors.
          3. prior_block strength reduced to weak (0.40-0.45) so it cannot tip
             a decision on its own. It only meaningfully contributes when it
             agrees with another signal (e.g. agent_current_client).

        The agent's current_client_id is treated as a MODERATE-LOW signal (0.55).
        It surfaces the agent's belief but cannot commit a block by itself. This
        is the architectural fix for the inheritance bug.
        """
        from tracker.models import Block

        # v1.4.0: New confidence-graded inference path. If the block's
        # RawEvents have structured inference data (post-v1.4.0 agents),
        # emit a single 'agent_inference' signal at strength derived from
        # the agent's reported confidence. Legacy agent_current_client
        # emission is skipped to avoid double-counting.
        # Path B / #1b: if Stage 3 deferred a same-family collision and the
        # agent's client is one of the colliding family members, the agent's
        # stickiness is an equally-unreliable family guess (e.g. agent stuck on
        # Sacred Heart-Cicero 360 for a "Sacred Heart Basilica" block). Suppress
        # BOTH agent signals (inference + current_client) so Stage 10's AI --
        # which reads the distinguishing token -- becomes the sole client judge.
        # Keystone then caps the lone-AI pick to 'proposed'. Without this, the
        # stale agent client forces Stage 10 into validation mode and the AI's
        # correct pick is never added as a signal (-> block lands None).
        agent_client_in_collision = (
            block.client_id is not None
            and block.client_id in getattr(decision, 'collision_client_ids', set())
        )
        if agent_client_in_collision:
            logger.info(
                f"[STAGE-8-COLLISION-SKIP] Block {getattr(block,'pk','?')}: agent "
                f"client {block.client_id} is a deferred collision member -- "
                f"suppressing agent signals, letting AI decide"
            )
            inference_signal_fired = False
        else:
            inference_signal_fired = self._try_emit_inference_signal(block, decision)

        # Determine if this is an "idle" block — these should not receive
        # prior_block signals because the user wasn't working on anything.
        title_lower = (block.window_title or block.title or '').strip().lower()
        app_lower = (block.app_name or '').strip().lower()
        is_idle_block = (
            title_lower == 'idle/uncategorized'
            or title_lower == 'idle'
            or app_lower == 'idle'
            # "Program Manager" and "New notification" are Windows shell windows,
            # never representative of actual work
            or title_lower == 'program manager'
            or title_lower == 'new notification'
        )

        # Signal A: current_client_id from the agent.
        # The agent's selection. Treated as moderate-low (0.45) — never strong.
        # Skip on idle blocks: agent client is not meaningful when user is idle.
        # v1.4.0: Skip if inference signal already fired — avoids double-counting
        # the same underlying agent observation.
        if block.client_id and not is_idle_block and not inference_signal_fired and not agent_client_in_collision:
            # v1.3.56: Browser blocks are the inheritance-bug magnet.
            # The agent's client sticks across alt-tabs to news, music,
            # personal browsing. Without independent corroboration from
            # another stage, the agent's selection alone must not
            # propose a client for a browser block.
            #
            # Non-browser apps (QuickBooks, Excel, UltraTax, Outlook)
            # keep their existing behavior: the user actively opened
            # that app, so the agent's client is meaningful.
            app_lower = (block.app_name or '').lower()
            BROWSER_APPS = {
                'msedge', 'chrome', 'firefox', 'brave',
                'safari', 'opera', 'iexplore',
            }
            is_browser_block = app_lower in BROWSER_APPS

            if is_browser_block:
                # Look for any signal (already on decision from earlier
                # stages) that independently points to the same client.
                # We accept Stage 3 (title/domain/path), Stage 4 (file
                # path structure), Stage 6 (calendar), Stage 7 (mail),
                # or Stage 9 (learned). We REJECT prior_block (just
                # another form of stickiness) and ai_category (category
                # only, no client signal).
                CORROBORATING_TYPES = {
                    'title_match_title_alias',
                    'title_match_file_path',
                    'title_match_domain',
                    'file_path_structure',
                    'calendar',
                    'mail',
                    'learned_pattern',
                    'org_rule',
                    'tax_software',
                }
                has_corroboration = any(
                    s.proposed_client_id == block.client_id
                    and s.type in CORROBORATING_TYPES
                    for s in decision.matched_signals
                )

                if not has_corroboration:
                    logger.info(
                        f"[STAGE-8] Block {getattr(block, 'pk', '?')}: "
                        f"suppressing agent_current_client signal — "
                        f"browser block ({app_lower}) with no independent "
                        f"corroboration for client_id={block.client_id}"
                    )
                    # Skip emitting the signal entirely. Block will fall
                    # through to Captured or get classified by another
                    # signal type that doesn't depend on agent stickiness.
                else:
                    client = next((c for c in self._clients if c.id == block.client_id), None)
                    if client:
                        decision.matched_signals.append(Signal(
                            type='agent_current_client',
                            strength=0.45,
                            evidence=f"Agent had '{client.name}' selected when this activity was captured (corroborated by independent signal)",
                            detail={
                                'client_id':   client.id,
                                'client_name': client.name,
                                'corroborated': True,
                            },
                        ))
            else:
                # Non-browser app — agent stickiness is meaningful
                client = next((c for c in self._clients if c.id == block.client_id), None)
                if client:
                    decision.matched_signals.append(Signal(
                        type='agent_current_client',
                        strength=0.45,
                        evidence=f"Agent had '{client.name}' selected when this activity was captured",
                        detail={
                            'client_id':   client.id,
                            'client_name': client.name,
                        },
                    ))

        # Signal B: previous HUMAN-CONFIRMED block's client.
        # Skip on idle blocks: idle is its own answer, do not chain client from
        # prior context. Skip if no prior human-confirmed block exists.
        if is_idle_block or not block.start:
            return

        prior = (
            Block.objects
            .filter(
                user=self.user,
                classification_state='committed',
                state_changed_by__in=('user', 'correction'),
                end__lte=block.start,
            )
            .exclude(client_id__isnull=True)
            .order_by('-end')
            .first()
        )
        if not (prior and prior.client_id):
            return

        gap_minutes = (block.start - prior.end).total_seconds() / 60.0
        if gap_minutes >= 30:
            return

        # Weak signal, capped well below the moderate threshold so it cannot
        # tip a decision on its own. It contributes via signal combination
        # when it agrees with another signal (e.g. agent_current_client).
        if gap_minutes < 5:
            strength = 0.45
        elif gap_minutes < 15:
            strength = 0.40
        else:
            strength = 0.35

        client = next((c for c in self._clients if c.id == prior.client_id), None)
        if not client:
            return

        decision.matched_signals.append(Signal(
            type='prior_block',
            strength=strength,
            evidence=(
                f"Previous user-confirmed block ({int(gap_minutes)}min ago) "
                f"was attributed to {client.name}"
            ),
            detail={
                'client_id':     client.id,
                'client_name':   client.name,
                'gap_minutes':   round(gap_minutes, 1),
                'prior_block_id': prior.id,
            },
        ))

    # -------------------------------------------------------------------------
    # STAGE 9 — Learned patterns (UserWorkPattern)
    # -------------------------------------------------------------------------

    def _learned_pattern_overruled_by_collision(self, client_id, pattern_key, decision):
        """
        True when a learned-pattern signal for `client_id` must be SUPPRESSED
        because Stage 3 deferred a same-family collision and this pattern can't
        distinguish the client from its tied siblings.

        Stage 8 and Stage 10 already skip a collision-member client; Stage 9 did
        not — so a learned FAMILY-LEVEL pattern (e.g. "sacred heart" -> Cicero)
        could silently override the "don't guess among siblings" deferral and
        re-commit the very mistake the deferral exists to prevent.

        We suppress ONLY non-distinguishing patterns: if the pattern key contains
        a token UNIQUE to this client among the colliding siblings — e.g.
        "cemetery" for a cemetery vs its church, or "boonville" for the Boonville
        parish — the pattern IS real evidence and is kept. Note: unlike the
        tiebreak, entity words (church/cemetery/...) are NOT excluded here, so a
        legitimately specific pattern keyed on them survives.
        """
        collision = getattr(decision, 'collision_client_ids', None) or set()
        if client_id not in collision:
            return False
        import re
        sib = {c.id: c for c in self._clients if c.id in collision}
        if len(sib) < 2:
            return False

        def _toks(c):
            out = set()
            for nm in [c.name] + list(c.aliases or []):
                for t in re.sub(r'[^a-z0-9]+', ' ', (nm or '').lower()).split():
                    if len(t) >= 4 and t not in ALIAS_STOP_WORDS:
                        out.add(t)
            return out

        mine = _toks(sib[client_id])
        others = set()
        for cid, c in sib.items():
            if cid != client_id:
                others |= _toks(c)
        exclusive = mine - others
        key = (pattern_key or '').lower()
        # Keep if a UNIQUE token of this client appears in the key (distinguishes);
        # otherwise it's a family-level guess during a deferral -> suppress.
        return not any(t in key for t in exclusive)

    def _stage_9_learned_patterns(self, block, decision: ClassificationDecision):
        """
        Query UserWorkPattern for matches. v1.2.96 hardening + v1.3.70 optimization:
          - Patterns pre-loaded in _ensure_context_loaded (single DB call per type)
          - Patterns with total_predictions < 5 produce weak signals (≤0.5)
          - Email-domain patterns require client name in title
          - Confidence weighted by occurrence_count
        """
        title = (block.window_title or block.title or '').strip()
        file_path = (block.file_path or '').strip()
        url = (block.url or '').strip()

        # Title prefix patterns — use pre-loaded list
        if title:
            title_lower = title.lower()
            patterns = self._learned_patterns_by_type.get('window_title_prefix', [])

            for pattern in patterns:
                if not pattern.client:
                    continue
                key_lower = pattern.pattern_key.lower()

                # v1.2.96 hardening: require non-stop-word match of >= 5 chars
                if len(key_lower) < 5:
                    continue
                if key_lower in STOP_WORDS:
                    continue

                # v1.6.0 hardening: refuse signals from statistically
                # unreliable patterns. Three filters:
                #  - occurrence_count < 3 → too few samples to be evidence
                #  - total_predictions > 0 AND correct_predictions == 0 →
                #    empirically wrong, never confirmed correct
                #  - blacklisted generic key ("desktop", "outlook") →
                #    matches thousands of unrelated titles, pure noise
                if pattern.occurrence_count < 3:
                    continue
                if pattern.total_predictions > 0 and pattern.correct_predictions == 0:
                    continue
                if key_lower in LEARNED_PATTERN_BLACKLIST:
                    continue

                if key_lower in title_lower:
                    if self._learned_pattern_overruled_by_collision(
                            pattern.client.id, pattern.pattern_key, decision):
                        continue
                    strength = self._learned_pattern_strength(pattern)
                    decision.matched_signals.append(Signal(
                        type='learned_pattern',
                        strength=strength,
                        evidence=(
                            f"Learned title pattern '{pattern.pattern_key}' "
                            f"(seen {pattern.occurrence_count}x, "
                            f"{pattern.correct_predictions}/{pattern.total_predictions} correct)"
                        ),
                        detail={
                            'pattern_id':   pattern.id,
                            'pattern_type': pattern.pattern_type,
                            'pattern_key':  pattern.pattern_key,
                            'client_id':    pattern.client.id,
                            'client_name':  pattern.client.name,
                            'category':     pattern.category,
                        },
                    ))

        # File path patterns — use pre-loaded list
        if file_path:
            file_path_lower = file_path.lower()
            patterns = self._learned_patterns_by_type.get('file_path', [])

            for pattern in patterns:
                if not pattern.client:
                    continue
                key_lower = pattern.pattern_key.lower()
                # v1.6.0 hardening: same quality gate as title-prefix patterns
                if pattern.occurrence_count < 3:
                    continue
                if pattern.total_predictions > 0 and pattern.correct_predictions == 0:
                    continue
                if key_lower in LEARNED_PATTERN_BLACKLIST:
                    continue
                if key_lower in file_path_lower:
                    if self._learned_pattern_overruled_by_collision(
                            pattern.client.id, pattern.pattern_key, decision):
                        continue
                    strength = self._learned_pattern_strength(pattern)
                    decision.matched_signals.append(Signal(
                        type='learned_pattern',
                        strength=strength,
                        evidence=(
                            f"Learned file path pattern '{pattern.pattern_key}' → {pattern.client.name}"
                        ),
                        detail={
                            'pattern_id':  pattern.id,
                            'client_id':   pattern.client.id,
                            'client_name': pattern.client.name,
                        },
                    ))

        # URL domain patterns — use pre-loaded list
        if url:
            from urllib.parse import urlparse
            try:
                domain = urlparse(url).netloc.lower()
            except Exception:
                domain = ''

            if domain:
                patterns = self._learned_patterns_by_type.get('domain', [])

                for pattern in patterns:
                    if not pattern.client:
                        continue
                    if pattern.pattern_key.lower() in domain:
                        if self._learned_pattern_overruled_by_collision(
                                pattern.client.id, pattern.pattern_key, decision):
                            continue
                        strength = self._learned_pattern_strength(pattern)
                        decision.matched_signals.append(Signal(
                            type='learned_pattern',
                            strength=strength,
                            evidence=f"Learned domain pattern '{pattern.pattern_key}' → {pattern.client.name}",
                            detail={
                                'pattern_id':  pattern.id,
                                'client_id':   pattern.client.id,
                                'client_name': pattern.client.name,
                            },
                        ))


    def _stage_9_5_bracket_attribution(self, block, decision: ClassificationDecision):
        """
        Stage 9.5 — Same-day temporal bracket attribution (in-memory version).
        Uses cached block list instead of DB queries to avoid 600+ queries per request.
        """
        from datetime import timedelta

        # Guard 1: Don't fire if a real signal already proposes a client
        for sig in decision.matched_signals:
            if sig.proposed_client_id and sig.strength >= 0.65:
                return

        if not block.start or not block.end or not hasattr(self, '_daily_blocks_cache'):
            return

        # Use pre-loaded blocks instead of querying
        all_blocks = self._daily_blocks_cache
        TWO_SIDED_WINDOW = timedelta(minutes=30)
        ONE_SIDED_WINDOW = timedelta(minutes=15)
        EXCLUDE_SOURCES = {'bracket_attribution', 'bracket'}

        def find_prev(window):
            """Find preceding block within window."""
            for b in reversed(all_blocks):
                if b.id == block.id or not b.client_id:
                    continue
                if b.end > block.start:
                    continue  # hasn't ended yet
                if b.end < block.start - window:
                    break  # too far back
                if b.client.name == 'Internal - Tax':
                    continue
                if b.state_changed_by in EXCLUDE_SOURCES:
                    continue
                return b
            return None

        def find_next(window):
            """Find following block within window."""
            for b in all_blocks:
                if b.id == block.id or not b.client_id:
                    continue
                if b.start < block.end:
                    continue  # already started
                if b.start > block.end + window:
                    break  # too far ahead
                if b.client.name == 'Internal - Tax':
                    continue
                if b.state_changed_by in EXCLUDE_SOURCES:
                    continue
                return b
            return None

        # Mode 1: Two-sided bracket
        prev_wide = find_prev(TWO_SIDED_WINDOW)
        next_wide = find_next(TWO_SIDED_WINDOW)

        if prev_wide and next_wide and prev_wide.client_id == next_wide.client_id:
            client = next((c for c in self._clients if c.id == prev_wide.client_id), None)
            if client:
                gap_before_min = int((block.start - prev_wide.end).total_seconds() // 60)
                gap_after_min = int((next_wide.start - block.end).total_seconds() // 60)
                decision.matched_signals.append(Signal(
                    type='bracket_attribution',
                    strength=0.55,
                    evidence=f"Adjacent blocks: {client.name} ({gap_before_min}min before, {gap_after_min}min after)",
                    detail={
                        'client_id': client.id,
                        'client_name': client.name,
                        'mode': 'two_sided',
                    },
                ))
                return

        if prev_wide and next_wide and prev_wide.client_id != next_wide.client_id:
            return  # Disagreement, don't guess

        # Mode 2: One-sided bracket
        prev_tight = find_prev(ONE_SIDED_WINDOW)
        next_tight = find_next(ONE_SIDED_WINDOW)

        candidate = None
        if prev_tight and next_tight and prev_tight.client_id == next_tight.client_id:
            candidate = prev_tight
        elif prev_tight and not next_tight:
            candidate = prev_tight
        elif next_tight and not prev_tight:
            candidate = next_tight

        if candidate and candidate.client_id:
            client = next((c for c in self._clients if c.id == candidate.client_id), None)
            if client:
                decision.matched_signals.append(Signal(
                    type='bracket_attribution',
                    strength=0.55,
                    evidence=f"Bracket context: {client.name}",
                    detail={
                        'client_id': client.id,
                        'client_name': client.name,
                        'mode': 'one_sided',
                    },
                ))
                return

        # Mode 3: Overlap (blocks starting during this block)
        overlapping = [
            b for b in all_blocks
            if b.id != block.id
            and b.start > block.start
            and b.start < block.end
            and b.client_id
            and b.client.name != 'Internal - Tax'
            and b.state_changed_by not in EXCLUDE_SOURCES
        ]

        if overlapping:
            client_ids = set(b.client_id for b in overlapping)
            if len(client_ids) == 1:
                client_id = client_ids.pop()
                client = next((c for c in self._clients if c.id == client_id), None)
                if client:
                    decision.matched_signals.append(Signal(
                        type='bracket_attribution',
                        strength=0.55,
                        evidence=f"Overlap: {client.name} work during this block",
                        detail={
                            'client_id': client.id,
                            'client_name': client.name,
                            'mode': 'overlap',
                        },
                    ))

    def _stage_9_6_tool_category(self, block, decision: ClassificationDecision):
        """
        Stage 9.6 — Deterministic tool→category from the industry config.

        Reads get_combined_tool_detection(industry) (the single source of
        truth in industry_categories.py) and matches the block's app/title/url
        against known tool patterns. Emits a CATEGORY-ONLY signal — never a
        client. This is the "common sense" layer: QuickBooks is bookkeeping,
        Figma is design, VS Code is development. Facts about the tool, not
        inferences, so they shouldn't depend on an LLM round-trip.

        Fires only when no earlier stage produced a category signal, so it
        backstops Stage 10 without overriding anything that already decided.
        Strength caps below the tool's own confidence so a real AI category
        (Stage 10) or an org rule still wins when present.
        """
        # Don't override a category another stage already proposed
        if decision.category or any(s.proposed_category for s in decision.matched_signals):
            return

        try:
            from tracker.industry_categories import get_combined_tool_detection
        except ImportError:
            return

        industry = getattr(self.org, 'industry_type', None) or 'general'
        tool_map = get_combined_tool_detection(industry)
        if not tool_map:
            return

        # Build the same haystack the client stages use (QB bracket stripped,
        # path noise cleaned, all distinct event titles aggregated).
        haystack = self._build_haystack(block)
        app_lower = (block.app_name or '').lower()
        url_lower = (block.url or '').strip().lower()
        domain = self._extract_domain(url_lower)

        best_category = None
        best_confidence = 0.0
        best_tool = ''

        for tool_name, spec in tool_map.items():
            category = spec.get('category')
            conf = spec.get('confidence', 0.0)
            if not category or conf <= best_confidence:
                continue

            matched = False

            # Domain match (strongest, most specific)
            for d in spec.get('domains', []):
                if d and domain and (domain == d or domain.endswith('.' + d) or d in domain):
                    matched = True
                    break

            # Keyword match against app name + haystack
            if not matched:
                for kw in spec.get('keywords', []):
                    if not kw:
                        continue
                    k = kw.lower()
                    if k in app_lower or k in haystack:
                        matched = True
                        break

            if matched:
                best_category = category
                best_confidence = conf
                best_tool = tool_name

        if not best_category:
            return

        # Cap so a genuine Stage 10 AI category or an org rule still outranks
        # this. Tool detection is a strong backstop, not the final word.
        strength = min(0.80, best_confidence)

        decision.matched_signals.append(Signal(
            type='tool_category',
            strength=strength,
            evidence=(
                f"Tool '{best_tool}' detected ({app_lower or domain or 'title'}) "
                f"→ category '{best_category}' (industry={industry})"
            ),
            detail={
                'category':   best_category,
                'tool':       best_tool,
                'confidence': best_confidence,
                'industry':   industry,
            },
        ))

    # -------------------------------------------------------------------------
    # STAGE 10 — AI inference (last resort, cost-controlled)
    # -------------------------------------------------------------------------

    @staticmethod
    def _learned_pattern_strength(pattern) -> float:
        """
        Compute signal strength from a UserWorkPattern with v1.2.96 hardening.

        Rules:
          - Patterns with < 5 predictions are weak (max 0.50) regardless of confidence
          - Patterns with high occurrence_count (>= 50) get a small boost
          - Confidence score is weighted by sqrt of total_predictions to favor proven patterns
        """
        # Hardening: insufficient data = weak signal
        if pattern.total_predictions < 5:
            return min(0.50, pattern.confidence_score * 0.6)

        # Use confidence_score as base, capped at 0.80 (learned patterns NEVER strong-signal)
        base = min(0.80, pattern.confidence_score)

        # Occurrence boost: patterns seen many times are more trustworthy
        if pattern.occurrence_count >= 50:
            base = min(0.80, base + 0.05)

        return round(base, 3)


    def _stage_10_ai_inference(self, block, decision: ClassificationDecision):
        """
        Call OpenAI to classify with full block context (titles, paths, URLs,
        duration). Two distinct flows depending on whether the agent already
        assigned a client:

        FLOW A — Block has NO agent client (block.client_id is None):
          Call AI for client identification. AI client signal can be:
            - Strong (>=0.85)  → strong signal, may auto-commit via _finalize
            - Moderate (0.65-0.84) → propose for user review
            - Weak (<0.65) → ignored
          Then call AI for category if we got a client.

        FLOW B — Block HAS agent-assigned client (block.client_id is set):
          Skip AI client classification UNLESS we want to validate. We DO want
          to validate, because the agent's deterministic ladder can be wrong
          (regex matched on a coincidental substring). So:
            - Call AI client and compare to agent's
            - If AI agrees → no signal added (block stays as agent set it)
            - If AI disagrees with confidence >= 0.85 → log to AIProcessingLog
              for review, set block.ai_disagrees_with_agent=True, block stays
              as agent set it. User sees flag in web app daily review.
            - If AI disagrees with confidence < 0.85 → ignored (too uncertain)
          Then call AI for category regardless.

        ALWAYS for either flow:
          AI category signal capped at 0.85 strength so it can auto-commit
          when combined with the client signal (agent or AI).

        COST CONTROLS:
          - Only fires when no Signal has strength >= 0.65 OR block has client
          - Only fires when block has duration >= 1 minute (skips transients)
          - Cached per-block-title via Django cache (CACHE_TTL)
          - Skips entirely if OPENAI_API_KEY is not set
        """
        # Skip if OpenAI not configured
        import os
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return

        # Skip transient blocks (< 1 minute)
        if (block.minutes or 0) < 1:
            return

        # Skip if no clients to match against
        if not self._clients:
            return

        title = (block.window_title or block.title or '').strip()
        if not title:
            return

        # Cost gate: skip ONLY if a strong-enough CLIENT signal already exists
        # AND there's no agent client to validate. Gate on client-signal
        # strength, NOT max signal strength: a strong CATEGORY-only signal
        # (e.g. Outlook -> tool_category 0.80) must NOT suppress AI *client*
        # identification. Category (Email) and client (which client's email)
        # are orthogonal — an Outlook block legitimately has a category but
        # still needs AI to find the client. Without this, every email/Outlook
        # block with a client name silently landed in No Client.
        # Lone-AI picks are capped to 'proposed' downstream (see _finalize
        # SAFETY CAP), so opening this gate for email is safe.
        client_strength = max(
            (s.strength for s in decision.matched_signals if s.proposed_client_id),
            default=0.0,
        )
        # Path B / #1b: if the agent's client is a deferred collision member,
        # treat it as NO agent client so Stage 10 runs in FREE mode (FLOW A) and
        # ADDS the AI's pick as a client signal — instead of validation mode,
        # which only records a disagreement and never adds the AI client (the
        # block would then clear to None). The stale agent family-guess must not
        # force validation here; the AI is the intended judge of the collision.
        _agent_in_collision = (
            block.client_id is not None
            and block.client_id in getattr(decision, 'collision_client_ids', set())
        )
        has_agent_client = bool(block.client_id) and not _agent_in_collision

        if not has_agent_client and client_strength >= 0.65:
            # A strong CLIENT signal already exists and there's no agent client
            # to validate — Stage 10 wouldn't add value. Skip to save tokens.
            return

        try:
            # ---- AI client identification ----
            client_signal = self._ai_classify_client(block, title)

            if has_agent_client:
                # Validation flow — compare AI to agent
                self._handle_ai_agent_comparison(block, client_signal, decision)
                # In validation flow we ALWAYS use the agent's client for
                # category context — never the AI's, because the agent's
                # client is what's actually attached to the block.
                client_name_for_category = (
                    block.client.name if block.client else ''
                )
            else:
                # Free-form classification flow
                if client_signal:
                    decision.matched_signals.append(client_signal)
                client_name_for_category = (
                    client_signal.detail.get('client_name')
                    if client_signal else ''
                )

            # ---- AI category identification ----
            # Always classify category if we have any client context
            if client_name_for_category:
                category_signal = self._ai_classify_category(
                    block, title, client_name_for_category
                )
                if category_signal:
                    decision.matched_signals.append(category_signal)
                    # The AI's billability call is authoritative when AI is the
                    # category source. The signal carries detail['is_billable']
                    # but decision.is_billable defaults to True — propagate
                    # explicitly or the judgment gets lost downstream (e.g.
                    # apply() writes is_billable=True over an AI is_billable=False).
                    ai_is_billable = category_signal.detail.get('is_billable')
                    if ai_is_billable is not None:
                        decision.is_billable = bool(ai_is_billable)

        except Exception as e:
            logger.warning(f'Stage 10 AI inference failed for block {block.pk}: {e}')

    def _handle_ai_agent_comparison(self, block, ai_signal, decision):
        """
        When the agent already assigned a client and Stage 10 ran AI to
        validate, compare the two and either:
          - Agree → no-op (block stays as agent set it, no new signal)
          - Disagree at >= 0.85 confidence → log disagreement, mark block,
            but do NOT change the block's client. User reviews in web app.
          - Disagree at < 0.85 → ignore (AI not confident enough to flag)
        """
        if not ai_signal:
            return

        ai_client_id = ai_signal.detail.get('client_id')
        ai_client_name = ai_signal.detail.get('client_name', '')
        ai_confidence = ai_signal.detail.get('ai_confidence', 0.0)
        agent_client_id = block.client_id

        if not ai_client_id:
            return

        if ai_client_id == agent_client_id:
            # AI confirms agent's choice. Nice, but no signal needed —
            # the agent's deterministic decision already stands. Save the
            # confirmation to AIProcessingLog for analytics if desired.
            self._log_ai_call(
                operation_type='stage_10_validation_agree',
                input_data={
                    'block_id': block.pk,
                    'client_id': agent_client_id,
                    'title': (block.window_title or '')[:200],
                },
                output_data={
                    'ai_client_id': ai_client_id,
                    'ai_confidence': ai_confidence,
                    'verdict': 'agree',
                },
                processing_time_ms=0,
                success=True,
            )
            return

        # AI disagrees. Only flag if AI is confident.
        if ai_confidence < 0.85:
            # AI's disagreement is too uncertain to surface. Log it
            # silently for analytics but don't bug the user.
            self._log_ai_call(
                operation_type='stage_10_validation_uncertain',
                input_data={
                    'block_id': block.pk,
                    'agent_client_id': agent_client_id,
                    'title': (block.window_title or '')[:200],
                },
                output_data={
                    'ai_client_id': ai_client_id,
                    'ai_client_name': ai_client_name,
                    'ai_confidence': ai_confidence,
                    'verdict': 'low_confidence_disagreement',
                },
                processing_time_ms=0,
                success=True,
            )
            return

        # AI confidently disagrees. Surface in web app.
        self._log_ai_call(
            operation_type='stage_10_validation_disagree',
            input_data={
                'block_id': block.pk,
                'agent_client_id': agent_client_id,
                'agent_client_name': block.client.name if block.client else '',
                'title': (block.window_title or '')[:200],
            },
            output_data={
                'ai_client_id': ai_client_id,
                'ai_client_name': ai_client_name,
                'ai_confidence': ai_confidence,
                'verdict': 'confident_disagreement',
            },
            processing_time_ms=0,
            success=True,
        )

        # Mark block. We update the in-memory instance AND the DB row.
        # 
        # Why both:
        # - DB update (.update()) skips post_save signal so we don't infinite-loop
        # - In-memory update prevents apply()'s subsequent block.save() from
        #   overwriting ai_disagrees_with_agent=False (the field default) on top
        #   of our True. This was a real bug pre-fix: log entry written but flag
        #   never persisted because save() clobbered the update.
        from tracker.models import Block
        Block.objects.filter(pk=block.pk).update(
            ai_disagrees_with_agent=True,
            ai_proposed_client_id=ai_client_id,
            ai_proposed_confidence=ai_confidence,
            ai_disagreement_reasoning=ai_signal.evidence[:500],
        )
        # Also set on in-memory instance so apply()'s save() preserves these
        block.ai_disagrees_with_agent = True
        block.ai_proposed_client_id = ai_client_id
        block.ai_proposed_confidence = ai_confidence
        block.ai_disagreement_reasoning = ai_signal.evidence[:500]

        logger.info(
            f"[STAGE-10-DISAGREE] Block {block.pk}: agent={block.client_id}"
            f"({block.client.name if block.client else '?'}) vs "
            f"AI={ai_client_id}({ai_client_name}) at {ai_confidence:.2f}"
        )

    @staticmethod
    def _prefilter_clients_for_ai(title, clients, max_candidates=25):
        """
        Shrink the client list to a rarity-ranked shortlist BEFORE the AI call.

        gpt-4o-mini degrades to near-random with 300+ clients in one prompt
        (observed: "St Ant-St Agnes" -> "The Artist Bullpen"). Given a short,
        relevant list it reasons correctly ("St Agnes -> St. Anthony & St. Agnes").

        Tokens are weighted by inverse document frequency so a rare, identifying
        token outranks common ones ("saint", "church"). Distinctive matches
        surface to the top of the cap.

        SAFETY: only changes which candidates the AI SEES, never what gets
        attributed -- the AI still chooses and the _finalize verification gate
        still requires textual/corroborating evidence. An over-inclusive filter
        is safe; dropping the right client is the only real failure, so we fall
        back to the FULL list when nothing scores.
        """
        import re, math
        from collections import Counter

        def _toks(x):
            x = (x or '').lower()
            x = re.sub(r'\bst\.?\s|\bst\.(?=[a-z])', 'saint ', x)
            x = re.sub(r'\bmt\.?\s', 'mount ', x)
            x = re.sub(r"['\u2019]", '', x)
            x = re.sub(r'[^a-z0-9]+', ' ', x)
            return {t for t in x.split() if len(t) >= 3}

        title_tokens = _toks(title)
        if not title_tokens:
            return clients[:max_candidates] if len(clients) > max_candidates else clients

        df = Counter()
        ctok = {}
        for c in clients:
            nt = _toks(c.name)
            for a in (c.aliases or []):
                nt |= _toks(a)
            ctok[id(c)] = nt
            for t in nt:
                df[t] += 1
        N = len(clients)

        def _idf(t):
            return math.log((N + 1) / (df.get(t, 0) + 1)) + 0.1

        scored = []
        for c in clients:
            nt = ctok[id(c)]
            if not nt:
                continue
            sc = 0.0
            shared = title_tokens & nt
            for t in shared:
                sc += _idf(t) * 3
            if not shared:
                for x in title_tokens:
                    for y in nt:
                        if len(x) >= 3 and (y.startswith(x) or x.startswith(y)):
                            sc += _idf(x)
                            break
            if sc > 0:
                scored.append((sc, c))

        if not scored:
            return clients
        scored.sort(key=lambda z: z[0], reverse=True)
        return [c for _, c in scored[:max_candidates]]

    def _ai_classify_client(self, block, title):
        """
        Call OpenAI to identify the client. Returns Signal or None.
        Uses module-level cache shared with views_ai_classify.

        Logs each non-cached API call to AIProcessingLog for cost visibility.
        """
        try:
            from tracker.views_ai_classify import _call_openai, _cache_key, CACHE_TTL
            from django.core.cache import cache
        except ImportError:
            logger.warning('views_ai_classify not available — skipping AI client stage')
            return None

        # Check cache first
        cache_key = _cache_key(self.org.id, title)
        cached = cache.get(cache_key)
        was_cached = cached is not None

        if cached:
            client_id = cached.get('client_id')
            client_name = cached.get('client_name') or ''
            confidence = float(cached.get('confidence', 0.0))
        else:
            # Call OpenAI
            import time
            t_start = time.monotonic()

            # v1.3.52: Pull distinct event titles from this block for richer
            # context. Single window_title is one snapshot; the AI now sees
            # all titles in the block and reasons over the full activity.
            try:
                from tracker.models import RawEvent
                additional_titles = list(
                    RawEvent.objects
                    .filter(block=block)
                    .exclude(window_title__exact='')
                    .exclude(window_title__isnull=True)
                    .values_list('window_title', flat=True)
                    .distinct()
                )
                # Exclude the primary title (don't duplicate it) and cap at 10
                # to keep prompt size reasonable
                additional_titles = [
                    t for t in additional_titles if t != title
                ][:10]
            except Exception:
                additional_titles = []

            titles_batch = [{
                'title':     title,
                'app_name':  getattr(block, 'app_name', '') or '',
                'file_path': getattr(block, 'file_path', '') or '',
                'additional_titles': additional_titles,
            }]
            # Pre-filter to a rarity-ranked shortlist so the model isn't
            # drowning in 300+ clients (observed: full list -> garbage pick;
            # shortlist -> correct). Built from primary + additional titles.
            _filter_text = ' '.join([title] + list(additional_titles or []))
            _ai_clients = self._prefilter_clients_for_ai(_filter_text, self._clients)
            clients_payload = [
                {'id': c.id, 'name': c.name, 'aliases': c.aliases or []}
                for c in _ai_clients
            ]

            try:
                results = _call_openai(titles_batch, clients_payload)
                processing_ms = int((time.monotonic() - t_start) * 1000)
            except Exception as e:
                processing_ms = int((time.monotonic() - t_start) * 1000)
                self._log_ai_call(
                    operation_type='stage_10_client',
                    input_data={'title': title[:200], 'block_id': block.pk},
                    output_data={'error': str(e)[:500]},
                    processing_time_ms=processing_ms,
                    success=False,
                    error_message=str(e)[:500],
                )
                raise

            r = results[0] if results else None
            if not r:
                self._log_ai_call(
                    operation_type='stage_10_client',
                    input_data={'title': title[:200], 'block_id': block.pk},
                    output_data={'note': 'no result returned'},
                    processing_time_ms=processing_ms,
                    success=True,
                )
                return None

            client_id = r.get('client_id')
            client_name = r.get('client_name') or ''
            confidence = float(r.get('confidence', 0.0))

            self._log_ai_call(
                operation_type='stage_10_client',
                input_data={'title': title[:200], 'block_id': block.pk},
                output_data={
                    'client_id':   client_id,
                    'client_name': client_name,
                    'confidence':  confidence,
                },
                processing_time_ms=processing_ms,
                success=True,
            )

            if client_id:
                cache.set(cache_key, {
                    'client_id':   client_id,
                    'client_name': client_name,
                    'confidence':  confidence,
                }, timeout=CACHE_TTL)

        if not client_id or confidence < 0.5:
            return None

        # Strength is the raw AI confidence, capped at 0.95 to leave room
        # for category signal combination via noisy-OR. AI client at 0.95
        # paired with AI category at 0.85 gives combined ~0.99, plenty
        # to auto-commit via _finalize_decision's strong-signal path.
        # 
        # When this block has an agent-assigned client, this strength is
        # never added to decision.matched_signals — _handle_ai_agent_comparison
        # uses the raw confidence for disagreement logic instead.
        strength = min(0.95, confidence)

        return Signal(
            type='ai_client',
            strength=strength,
            evidence=f"AI classified as '{client_name}' (confidence {confidence:.2f})",
            detail={
                'client_id':       client_id,
                'client_name':     client_name,
                'ai_confidence':   confidence,
                'cached':          was_cached,
            },
        )

    def _ai_classify_category(self, block, title, client_name):
        """
        Call OpenAI to identify the activity category (Tax Prep, Bookkeeping, etc.)
        Returns Signal or None. Reuses module-level helpers from block_classifier.py.

        Logs each API call to AIProcessingLog for cost visibility.
        """
        try:
            from tracker.industry_categories import (
                _get_allowed_categories,
                _build_category_system_prompt,
                _build_category_user_prompt,
            )
        except ImportError:
            logger.warning('block_classifier helpers not available — skipping AI category stage')
            return None

        import json
        import os
        import re
        import time
        import urllib.request

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return None

        t_start = time.monotonic()

        try:
            industry_type = getattr(self.org, 'industry_type', 'general') or 'general'
            allowed_categories = _get_allowed_categories(industry_type)
            system_prompt = _build_category_system_prompt(allowed_categories)
            user_prompt = _build_category_user_prompt(block, client_name)

            payload = json.dumps({
                'model': 'gpt-4o-mini',
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user',   'content': user_prompt},
                ],
                'temperature': 0.1,
                'max_tokens': 300,
            }).encode()

            req = urllib.request.Request(
                'https://api.openai.com/v1/chat/completions',
                data=payload,
                headers={
                    'Content-Type':  'application/json',
                    'Authorization': f'Bearer {api_key}',
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            processing_ms = int((time.monotonic() - t_start) * 1000)

            raw = (data['choices'][0]['message']['content'] or '').strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            parsed = json.loads(raw)

            category = parsed.get('category', '')
            ai_confidence = float(parsed.get('confidence', 0.0))
            billable = parsed.get('billable', True)
            reasoning = parsed.get('reasoning', '')

            # v1.3.72: Repair near-miss category strings instead of discarding.
            # The model frequently returns valid-but-non-exact names
            # ("Bookkeeping" for "Accounting/Bookkeeping", "Email" for
            # "Email/Communication"). The hard `not in allowed_categories`
            # discard nuked these → no category signal → block fell through to
            # the FIX 6b "General Client Work" fallback. validate_and_fix_ai_response
            # is the same safety net the batch path already uses: exact match →
            # KNOWN_FIXES alias → difflib fuzzy (>0.75). Only a truly
            # unrecognizable string falls through to the discard below.
            original_category = category
            if category not in allowed_categories:
                try:
                    from tracker.industry_categories import validate_and_fix_ai_response
                    fixed = validate_and_fix_ai_response(
                        [{'categories': {category: 1.0}, 'confidence': ai_confidence}],
                        industry_type,
                    )
                    repaired = next(iter(fixed[0].get('categories', {})), category)
                    if repaired in allowed_categories:
                        logger.info(
                            f"[STAGE-10-CAT] Block {block.pk}: repaired category "
                            f"'{original_category}' → '{repaired}'"
                        )
                        category = repaired
                except Exception as e:
                    logger.warning(
                        f"[STAGE-10-CAT] Block {block.pk}: category repair failed "
                        f"for '{original_category}' — {e}"
                    )

            self._log_ai_call(
                operation_type='stage_10_category',
                input_data={
                    'title':       title[:200],
                    'block_id':    block.pk,
                    'client_name': client_name,
                },
                output_data={
                    'category':          category,
                    'original_category': original_category,
                    'confidence':        ai_confidence,
                    'is_billable':       billable,
                    'reasoning':         reasoning[:200],
                },
                processing_time_ms=processing_ms,
                success=True,
            )

            # Still unrecognizable after repair — genuinely garbage, discard.
            if category not in allowed_categories:
                logger.warning(
                    f"AI returned unknown category '{original_category}' for "
                    f"block {block.pk} — unrepairable, discarding"
                )
                return None

            if ai_confidence < 0.5:
                return None

            # Cap AI strength at 0.85
            strength = min(0.85, ai_confidence)

            return Signal(
                type='ai_category',
                strength=strength,
                evidence=f"AI category: '{category}' (confidence {ai_confidence:.2f}) — {reasoning[:80]}",
                detail={
                    'category':       category,
                    'is_billable':    billable,
                    'ai_confidence':  ai_confidence,
                    'ai_reasoning':   reasoning[:200],
                },
            )

        except Exception as e:
            processing_ms = int((time.monotonic() - t_start) * 1000)
            self._log_ai_call(
                operation_type='stage_10_category',
                input_data={'title': title[:200], 'block_id': block.pk, 'client_name': client_name},
                output_data={'error': str(e)[:500]},
                processing_time_ms=processing_ms,
                success=False,
                error_message=str(e)[:500],
            )
            logger.warning(f'AI category classification failed for block {block.pk}: {e}')
            return None

    def _log_ai_call(
        self,
        operation_type: str,
        input_data: dict,
        output_data: dict,
        processing_time_ms: int,
        success: bool,
        error_message: str = '',
    ):
        """
        Persist an AI API call to AIProcessingLog for cost visibility.
        Wraps in try/except so logging failures never break classification.
        """
        try:
            from tracker.models import AIProcessingLog
            AIProcessingLog.objects.create(
                org=self.org,
                user=self.user,
                operation_type=operation_type,
                input_data=input_data,
                output_data=output_data,
                model_used='gpt-4o-mini',
                tokens_used=0,  # OpenAI response includes usage but we'd need to plumb it through
                processing_time_ms=processing_time_ms,
                success=success,
                error_message=error_message,
            )
        except Exception as e:
            logger.warning(f'Failed to log AI call to AIProcessingLog: {e}')

    # -------------------------------------------------------------------------
    # DECISION LOGIC — auto-commit vs propose vs capture
    # -------------------------------------------------------------------------

    def _finalize_decision(self, decision: ClassificationDecision, block) -> ClassificationDecision:
        """
        After all stages run, decide the final state and confidence.
        ...

        DEDUPLICATION:
        Before computing the strong/moderate split, we collapse multiple
        learned-pattern signals proposing the SAME client into a single signal.
        Reason: learned patterns are derived from the same UserWorkPattern table,
        so 3 patterns matching the same block (title prefix + domain + file path)
        are correlated, not independent. The noisy-OR formula assumes independence,
        so 3 correlated weak signals would falsely combine to a strong one.

        We keep the highest-strength learned signal per client_id and discard
        the rest. Other signal types (org_rule, mail, etc.) are not deduplicated —
        each represents independent evidence.
        """
        # Already terminated (suppressed or org rule auto-committed)
        if decision.recommended_state in ('suppressed', 'committed'):
            return decision

        signals = self._dedupe_correlated_signals(decision.matched_signals)
        decision.matched_signals = signals  # update so downstream sees deduped list

        # v1.3.57 FIX 4: Verify ai_client signals against evidence.
        # AI inference can confidently hallucinate a client when there's
        # no visible client identity in the input (e.g. proposing
        # "S&A Creative" for a fullypromoted.com email page). We require
        # either:
        #   1) The proposed client's name appears in the block's
        #      title/url/path (textual evidence), OR
        #   2) Independent corroboration from a non-AI signal type
        # If neither holds, drop the ai_client signal.
        AI_CLIENT_CORROBORATING_TYPES = {
            'title_match_title_alias', 'title_match_file_path',
            'title_match_domain', 'file_path_structure',
            'calendar', 'mail', 'learned_pattern',
            'org_rule', 'tax_software',
        }
        verified_signals = []
        for sig in signals:
            if sig.type == 'ai_client' and sig.proposed_client_id is not None:
                proposed_id = sig.proposed_client_id
                client_obj = next(
                    (c for c in self._clients if c.id == proposed_id), None
                )
                # Check 1: client name appears in block input
                haystack = ' '.join([
                    getattr(block, 'window_title', '') or '',
                    getattr(block, 'url', '') or '',
                    getattr(block, 'file_path', '') or '',
                ]).lower()
                # UNIVERSAL GUARD: in a browser / consumed-content block, a client
                # word in the page (a news headline, weather page, search result)
                # is NOT evidence of client work — it's what the user is READING.
                # "Basilica" in QuickBooks means doing that client's books;
                # "Oswego"/"Syracuse" in a Yelp/weather tab means nothing (same
                # word rarity, opposite meaning — so this can't be a frequency
                # gate, it must be context). So the WEAK single-token evidence
                # paths below are disabled for browser blocks; they then need the
                # FULL client name in the input, or an independent non-AI work
                # signal (file/domain/deterministic match). Generalizes the
                # Stage-8 browser-corroboration guard to the AI client — kills
                # "Syracuse Weather -> Syracuse Fitness" and the whole class.
                _app = (getattr(block, 'app_name', '') or '').lower().replace('.exe', '').strip()
                _is_browser = _app in {'msedge', 'chrome', 'firefox', 'brave',
                                       'safari', 'opera', 'iexplore', 'arc'}
                # But a DOCUMENT open in the browser (a client's PDF/Excel) IS a
                # work surface — CPAs view client files in Edge. Only a genuine
                # WEB PAGE (news/weather/search, no document) is consumed content.
                _looks_like_document = bool(re.search(
                    r'\.(pdf|xlsx?|xlsm|xlsb|docx?|csv|pptx?|txt)\b', haystack))
                _consumed_content = _is_browser and not _looks_like_document
                has_textual_evidence = False
                if client_obj:
                    name_lower = client_obj.name.lower()
                    # Strip corporate suffix
                    stripped = re.sub(
                        r'[,\s]+(inc|llc|corp|pc|pllc|plc|ltd|co|'
                        r'incorporated|corporation|company|limited)\.?$',
                        '', name_lower,
                    ).strip(' .,')
                    # Try full stripped name as substring (trusted anywhere)
                    if stripped and len(stripped) >= 4 and stripped in haystack:
                        has_textual_evidence = True
                    elif not _consumed_content:
                        # Weak: first distinctive word (>=5 chars). Work surface
                        # only — a lone word in a browsed page isn't client work.
                        words = re.findall(
                            r'\b[a-z][a-z0-9\-&]{4,}\b',
                            stripped or name_lower,
                        )
                        if words and re.search(
                            r'\b' + re.escape(words[0]) + r'\b', haystack
                        ):
                            has_textual_evidence = True
                    # Distinctive-token path: client shares a rare, non-generic
                    # token with the input (e.g. "agnes" for an abbreviated
                    # "St Ant-St Agnes" title). Mirrors the views_ai_classify
                    # gate. Proven safe via shadow: 110 passes on "agnes",
                    # Artist Bullpen + generic-only "church" collisions reject.
                    if not has_textual_evidence and client_obj and not _consumed_content:
                        _GEN = {
                            'saint','church','cemetery','parish','catholic',
                            'school','fund','foundation','center','centre',
                            'company','corp','inc','llc','ltd','group',
                            'services','service','the','and','of','st',
                            'associates','partners','holdings','enterprises',
                            'community','ministry','chapel',
                        }
                        _hn = re.sub(r'\bst\.?\s|\bst\.(?=[a-z])', 'saint ', name_lower)
                        _hn = re.sub(r"['\u2019]", '', _hn)
                        _hn = re.sub(r'[^a-z0-9]+', ' ', _hn)
                        _hh = re.sub(r'\bst\.?\s|\bst\.(?=[a-z])', 'saint ', haystack)
                        _hh = re.sub(r"['\u2019]", '', _hh)
                        _hh = re.sub(r'[^a-z0-9]+', ' ', _hh)
                        _htoks = {t for t in _hh.split() if len(t) >= 4}
                        for _tok in _hn.split():
                            if len(_tok) >= 4 and _tok not in _GEN and _tok in _htoks:
                                has_textual_evidence = True
                                break
                # Check 2: independent corroboration from non-AI signal
                has_corroboration = any(
                    other is not sig
                    and other.type in AI_CLIENT_CORROBORATING_TYPES
                    and other.proposed_client_id == proposed_id
                    for other in signals
                )
                if not has_textual_evidence and not has_corroboration:
                    logger.info(
                        f"[FINALIZE] Block {getattr(block, 'pk', '?')}: "
                        f"dropping unverifiable ai_client signal proposing "
                        f"client_id={proposed_id} "
                        f"({client_obj.name if client_obj else 'unknown'}) — "
                        f"name not in input, no corroborating signal"
                    )
                    continue  # drop this signal
            verified_signals.append(sig)
        signals = verified_signals
        decision.matched_signals = signals  # update again after FIX 4

        # v1.3.56 FIX 2: Filter the strong/moderate sets to signals that
        # actually propose a CLIENT.
        def _has_client_proposal(s):
            return s.proposed_client_id is not None

        strong = [s for s in signals if s.is_strong and _has_client_proposal(s)]
        moderate = [s for s in signals if s.is_moderate and _has_client_proposal(s)]

        # v1.3.56 FIX 3: AI non-billable verdict clears stale client
        # attribution. When AI says "this isn't billable client work"
        # with high confidence, and the only client-proposing signals
        # are stickiness signals from the agent's prior selection, drop
        # the attribution. Block becomes Captured with no client —
        # surfaces in Daily Review as Uncategorized rather than wrongly
        # billable to a stale client.
        ai_nonbillable_strong = next(
            (s for s in signals
             if s.type == 'ai_category'
             and s.strength >= 0.80
             and s.detail.get('is_billable') is False),
            None,
        )
        if ai_nonbillable_strong:
            # Check if ALL client-proposing signals are stickiness-only
            client_signals = [s for s in signals if _has_client_proposal(s)]
            STICKINESS_TYPES = {'agent_current_client', 'prior_block'}
            stickiness_only = (
                len(client_signals) > 0
                and all(s.type in STICKINESS_TYPES for s in client_signals)
            )
            if stickiness_only:
                logger.info(
                    f"[FINALIZE] Block {getattr(block, 'pk', '?')}: "
                    f"AI judged non-billable @ {ai_nonbillable_strong.strength:.2f} "
                    f"with no independent client evidence — clearing stale "
                    f"agent attribution. AI reasoning: "
                    f"{ai_nonbillable_strong.detail.get('ai_reasoning', '')[:120]}"
                )
                decision.client_id = None
                decision.is_billable = False
                decision.recommended_state = 'captured'
                decision.confidence = ai_nonbillable_strong.strength
                decision.reasoning = (
                    f"AI judged non-billable "
                    f"({ai_nonbillable_strong.detail.get('ai_reasoning', '')[:200]}). "
                    f"No independent client evidence beyond agent stickiness — "
                    f"cleared attribution and routed to Daily Review."
                )
                return decision

        # Auto-commit: at least one strong signal (with a client proposal), no contradictions
        if strong:
            # Strong signals' proposed clients must agree with each other
            strong_client_ids = {s.proposed_client_id for s in strong if s.proposed_client_id}

            if len(strong_client_ids) > 1:
                # Strong signals disagree among themselves — propose, flag for review
                decision.needs_review = True
                decision.review_reason = (
                    f'Multiple high-confidence client matches: '
                    f'{", ".join(str(cid) for cid in strong_client_ids)}'
                )
                self._populate_classification_from_signals(decision, signals)
                decision.recommended_state = 'proposed'
                decision.confidence = max(s.strength for s in strong)
                return decision

            # Strong signals agree (or only category-only strong signals).
            # Now check: does any MODERATE signal contradict the dominant client?
            self._populate_classification_from_signals(decision, signals)
            chosen_client_id = decision.client_id

            if chosen_client_id and self._has_contradicting_signal(signals, chosen_client_id):
                # A moderate signal proposes a different client than the chosen one.
                # Don't auto-commit — let a human resolve.
                decision.needs_review = True
                decision.review_reason = (
                    f'Stage signals disagree on client (chosen={chosen_client_id}); '
                    f'requires human review'
                )
                decision.recommended_state = 'proposed'
                decision.confidence = max(s.strength for s in strong)
                return decision

            # SAFETY CAP (keystone): never auto-commit a LONE AI client
            # identification. An ai_client signal alone -- with no deterministic,
            # agent, mail, or rule signal corroborating the SAME client -- is a
            # guess from a title that can be confidently wrong in ways the
            # verification gate cannot catch (proven: "Mark Utica" -> "Mark
            # Clary" on a shared first name, 0.85). Such picks must be PROPOSED
            # for one-click human review, never auto-billed. Corroborated AI
            # and all deterministic/agent paths still auto-commit unchanged.
            if chosen_client_id:
                non_ai_corroborates = any(
                    s.proposed_client_id == chosen_client_id
                    and not s.type.startswith('ai')
                    for s in signals
                )
                strong_is_ai_only = all(s.type.startswith('ai') for s in strong)
                if strong_is_ai_only and not non_ai_corroborates:
                    decision.needs_review = True
                    decision.review_reason = (
                        'Lone AI client identification -- proposing for review '
                        '(not auto-committed without corroboration)'
                    )
                    decision.recommended_state = 'proposed'
                    decision.confidence = max(s.strength for s in strong)
                    logger.info(
                        f"[FINALIZE] Block {getattr(block, 'pk', '?')}: lone "
                        f"ai_client proposing client {chosen_client_id} -- capped "
                        f"to PROPOSED (no non-AI corroboration)"
                    )
                    return decision

            decision.recommended_state = 'committed'
            decision.confidence = max(s.strength for s in strong)
            return decision

        # Auto-commit: 2+ moderate signals all agree
        if len(moderate) >= 2:
            client_ids = {s.proposed_client_id for s in moderate if s.proposed_client_id}
            if len(client_ids) == 1:
                # Compute combined confidence (independent-evidence model)
                combined = self._combine_confidences([s.strength for s in moderate])
                if combined >= 0.85:
                    self._populate_classification_from_signals(decision, signals)
                    decision.recommended_state = 'committed'
                    decision.confidence = combined
                    return decision

        # Stage Sandwich — temporal fallback attribution.
        # Runs only when no real evidence produced a client. Slots between
        # the moderate>=2 auto-commit check and FIX 6's non-billable default,
        # enforcing precedence: real evidence > sandwich > safe default.
        if decision.client_id is None and self._sandwich_enabled:
            from tracker.services.sandwich_correlation import find_sandwich_attribution
            sandwich_sig = find_sandwich_attribution(block, self.user, self.org)
            if sandwich_sig and sandwich_sig.strength >= 0.65:
                decision.matched_signals.append(sandwich_sig)
                # Sandwich client is authoritative — set directly rather than
                # routing through the strength-sort, which is fragile.
                decision.client_id = sandwich_sig.proposed_client_id
                decision.category = sandwich_sig.proposed_category or decision.category
                decision.source = 'sandwich_correlation'
                decision.reasoning = sandwich_sig.evidence
                decision.recommended_state = 'proposed'   # never auto-commit a sandwich
                decision.confidence = sandwich_sig.strength
                decision.is_billable = sandwich_sig.detail.get('is_billable', True)
                return decision
            # else fall through to FIX 6 as today

        # v1.3.61 FIX 7: reject client_id when only agent stickiness attests to it.
        #
        # The agent attaches a "current client" to every captured event based on
        # the user's most recent client work. When the user context-switches
        # (e.g., briefly browses bank statements between client work blocks),
        # the agent's stickiness leaks the previous client_id onto the new event.
        #
        # If the only signal proposing this client_id is `agent_current_client`
        # (no alias match, no learned pattern, no AI client identification, no
        # corroboration), the stickiness is unverified. Clear it and let FIX 6
        # default the block to non-billable.
        #
        # Also clear any orphan `ai_category` signal — that category was predicated
        # on the now-rejected client, so its category prediction is invalid.
        if decision.client_id is not None:
            attesting_signals = [
                s for s in decision.matched_signals
                if s.detail and s.detail.get('client_id') == decision.client_id
            ]
            non_stickiness_attestation = [
                s for s in attesting_signals
                if s.type != 'agent_current_client'
                and not (s.type == 'agent_inference'
                         and s.detail and s.detail.get('is_stickiness_inference'))
            ]
            stickiness_corroborated = any(
                (s.type == 'agent_current_client' and s.detail.get('corroborated'))
                or (s.type == 'agent_inference' and s.detail.get('corroborated'))
                for s in attesting_signals
            )

            if not non_stickiness_attestation and not stickiness_corroborated:
                logger.info(
                    f"[FINALIZE] Block {getattr(block, 'pk', '?')}: "
                    f"FIX 7 clearing unattested client_id={decision.client_id} "
                    f"(agent stickiness only, no corroboration)"
                )
                cleared_client_id = decision.client_id
                decision.client_id = None

                # Drop AI category — it was predicated on the now-cleared client.
                ai_cat_signals = [s for s in decision.matched_signals if s.type == 'ai_category']
                if ai_cat_signals:
                    decision.is_billable = True  # reset so FIX 6 logic fires correctly
                    decision.matched_signals = [
                        s for s in decision.matched_signals if s.type != 'ai_category'
                    ]

                # tool_category SURVIVES a client clear: it's a fact about the
                # tool (QuickBooks is bookkeeping) independent of which client
                # the work was for. Re-seed decision.category from it whenever
                # one is present — runs regardless of whether an ai_category
                # was dropped above, because the QB case often has NO
                # ai_category (Stage 9.6 supplied the category and Stage 10
                # skipped). Without this outside the if, the re-seed silently
                # never fired for the exact blocks it was meant to protect.
                surviving_tool_cat = next(
                    (s for s in decision.matched_signals if s.type == 'tool_category'),
                    None,
                )
                if surviving_tool_cat:
                    decision.category = surviving_tool_cat.proposed_category
                elif ai_cat_signals:
                    # AI category was dropped and there's no tool_category to
                    # fall back on — clear the orphaned category.
                    decision.category = None

                decision.matched_signals.append(Signal(
                    type='fix7_stickiness_rejected',
                    strength=0.0,
                    evidence=f'Rejected unattested client_id={cleared_client_id} (agent stickiness without corroboration)',
                    detail={'rejected_client_id': cleared_client_id},
                ))

        # v1.3.61: FIX 6 must not fire when a client WAS identified via signals.
        # decision.client_id isn't populated until _populate_classification_from_signals
        # (which runs BELOW this point), so a client arriving from alias/title
        # signals is invisible here — check the signals directly.
        has_client_signal = any(
            getattr(s, 'proposed_client_id', None) for s in signals
        )

        if decision.client_id is None and not has_client_signal and decision.is_billable:
            has_ai_category = any(
                s.type == 'ai_category' for s in decision.matched_signals
            )
            if not has_ai_category:
                logger.info(
                    f"[FINALIZE] Block {getattr(block, 'pk', '?')}: "
                    f"defaulting is_billable=False (no client, no AI category)"
                )
                decision.is_billable = False

                # Detect unambiguous overhead (inbox, login, new tab, etc.).
                # For those, AUTO-COMMIT the non-billable default instead of
                # leaving a weak proposal in the pile (strength 0.50 → proposed).
                _title_l = (getattr(block, 'window_title', '') or '').lower()
                _app_l = (getattr(block, 'app_name', '') or '').lower()
                _is_overhead = (
                    any(sub in _title_l for sub in AUTO_NONBILLABLE_TITLE_SUBSTRINGS)
                    or _app_l in AUTO_NONBILLABLE_APPS
                )

                # v1.3.60: also propose a category so the UI can pre-fill
                industry = getattr(self.org, 'industry_type', None) or 'general'
                _, non_billable_fb = FALLBACK_CATEGORIES.get(
                    industry, FALLBACK_CATEGORIES_DEFAULT
                )
                if not decision.category:
                    decision.category = non_billable_fb
                if _is_overhead:
                    # Strong strength → auto-commits as non-billable. User can
                    # still override in Daily Review if a given inbox session
                    # was actually billable correspondence.
                    decision.recommended_state = 'committed'
                    decision.matched_signals.append(Signal(
                        type='overhead_auto_nonbillable',
                        strength=0.90,
                        evidence=f'Unambiguous overhead → auto non-billable ({non_billable_fb})',
                        detail={'category': non_billable_fb, 'is_billable': False},
                    ))
                else:
                    decision.matched_signals.append(Signal(
                        type='fix6_default',
                        strength=0.50,
                        evidence=f'No client identified; defaulting to {non_billable_fb}',
                        detail={'category': non_billable_fb, 'is_billable': False},
                    ))
        elif has_client_signal and not decision.category and not any(
            s.proposed_category for s in signals
        ):
            # v1.3.61: client identified but no category signal — prefill the
            # org's BILLABLE fallback ("General Client Work" for CPA), not
            # Personal. Weak strength → surfaces as suggestion, not auto-commit.
            industry = getattr(self.org, 'industry_type', None) or 'general'
            billable_fb, _ = FALLBACK_CATEGORIES.get(
                industry, FALLBACK_CATEGORIES_DEFAULT
            )
            decision.category = billable_fb
            decision.matched_signals.append(Signal(
                type='fix6b_client_default',
                strength=0.50,
                evidence=f'Client identified via signals; defaulting category to {billable_fb}',
                detail={'category': billable_fb, 'is_billable': True},
            ))

        # Otherwise propose if we have any MODERATE-or-better signal.
        # Weak-only signals (< 0.65) — typically just agent_current_client
        # with no corroboration — don't justify proposing a client. The
        # block goes to captured for user review instead.
        moderate_or_better = [s for s in signals if s.strength >= 0.65]
        if moderate_or_better:
            self._populate_classification_from_signals(decision, signals)

            # v1.3.75: A moderate-or-better signal can carry a CATEGORY without
            # proposing a CLIENT (e.g. tool_category "Outlook → Email" at 0.80).
            # In that case _populate may have pulled the client_id from a WEAK
            # signal (agent_current_client at 0.45) — exactly the stale
            # stickiness FIX 7 is meant to reject. Guard it here: if the only
            # signal attesting to the chosen client is uncorroborated agent
            # stickiness, clear the client (keep the category). This is the
            # Mets bug: a personal email kept Transfiguration because the agent
            # had it selected, and tool_category(0.80) tripped this branch while
            # the only client evidence was agent stickiness(0.45).
            if decision.client_id is not None:
                attesting = [
                    s for s in decision.matched_signals
                    if s.detail and s.detail.get('client_id') == decision.client_id
                ]
                non_stickiness = [
                    s for s in attesting
                    if s.type != 'agent_current_client'
                    and not (s.type == 'agent_inference'
                             and s.detail and s.detail.get('is_stickiness_inference'))
                ]
                stickiness_corroborated = any(
                    (s.type == 'agent_current_client' and s.detail.get('corroborated'))
                    or (s.type == 'agent_inference' and s.detail.get('corroborated'))
                    for s in attesting
                )
                if not non_stickiness and not stickiness_corroborated:
                    logger.info(
                        f"[FINALIZE] Block {getattr(block, 'pk', '?')}: "
                        f"clearing client_id={decision.client_id} proposed only via "
                        f"weak agent stickiness while a clientless moderate signal "
                        f"(e.g. tool_category) tripped the propose branch"
                    )
                    decision.client_id = None
                    decision.is_billable = False

            # Don't downgrade an overhead auto-commit back to 'proposed'.
            if not any(s.type == 'overhead_auto_nonbillable' for s in decision.matched_signals):
                decision.recommended_state = 'proposed'
            decision.confidence = max(s.strength for s in moderate_or_better)
            return decision

        # Only weak signals exist — capture without attribution
        if signals:
            decision.recommended_state = 'captured'
            decision.confidence = max(s.strength for s in signals)

        return decision

    @staticmethod
    def _has_contradicting_signal(signals: list, chosen_client_id: int) -> bool:
        """
        Returns True if any MODERATE-or-better signal proposes a different client.

        Threshold = 0.65 (the moderate floor). Weak signals (e.g. agent_current_client
        at 0.55) cannot veto a strong-signal auto-commit. They surface as proposed
        state only when no strong signal exists.

        This catches cases like:
          - Stage 7 emits mail at 0.85 for Client B (strong)
          - Stage 8 emits agent_current_client at 0.55 for Client A (weak)
          - Pre-fix: Client A vetoed Client B → block went to 'proposed'
          - Post-fix: Client A is below threshold → mail commits to Client B

        What we still flag:
          - Stage 8 ai_client at 0.75 disagreeing with chosen client
          - Stage 7 mail at 0.65 disagreeing with chosen client
          - Two strong signals with different client_ids (handled separately
            in _finalize_decision before this is called)
        """
        if not chosen_client_id:
            return False

        for s in signals:
            # Skip signals without a client proposal
            if not s.proposed_client_id:
                continue
            # Skip the chosen client (no contradiction)
            if s.proposed_client_id == chosen_client_id:
                continue
            # A moderate-or-better signal proposes a different client
            if s.strength >= 0.65:
                return True

        return False

    @staticmethod
    def _populate_classification_from_signals(decision: ClassificationDecision, signals: list):
        """
        Pick the dominant client/category from the highest-strength signal that has them.
        Builds reasoning string.
        """
        # Sort by strength desc to pick the best signal as the primary
        sorted_sigs = sorted(signals, key=lambda s: s.strength, reverse=True)

        # Find first signal that proposes a client
        if not decision.client_id:
            for s in sorted_sigs:
                if s.proposed_client_id:
                    decision.client_id = s.proposed_client_id
                    if not decision.source or decision.source == 'unknown':
                        decision.source = s.type
                    break

        # Find first signal that proposes a category
        if not decision.category:
            for s in sorted_sigs:
                if s.proposed_category:
                    decision.category = s.proposed_category
                    break

        # Build reasoning string from top 3 signals
        top_signals = sorted_sigs[:3]
        if top_signals and not decision.reasoning:
            decision.reasoning = '; '.join(s.evidence for s in top_signals)

    @staticmethod
    def _combine_confidences(strengths: list) -> float:
        """
        Combine multiple independent signal strengths using a noisy-OR style:
          combined = 1 - prod(1 - s_i)
        This gives more weight to multiple-source agreement than averaging would.
        """
        if not strengths:
            return 0.0
        prob_all_wrong = 1.0
        for s in strengths:
            prob_all_wrong *= (1.0 - s)
        return round(1.0 - prob_all_wrong, 3)

    @staticmethod
    def _dedupe_correlated_signals(signals: list) -> list:
        """
        Collapse correlated signals down to one per (signal_type, client_id) tuple,
        keeping the highest-strength member of each group.

        Currently applies to:
          - learned_pattern (multiple patterns from UserWorkPattern → same client)

        Does NOT apply to:
          - org_rule, mail, calendar, agent_current_client, ai_client, ai_category,
            title_match_*, file_path_structure, tax_software
            (these come from independent sources — keep all)

        Rationale: noisy-OR confidence combination assumes independence. Correlated
        signals (multiple matches from the same DB table for the same user/client)
        would falsely combine to high confidence. Treating them as one signal
        preserves the independence assumption.
        """
        CORRELATED_TYPES = {'learned_pattern'}

        # Bucket signals by whether they need dedup
        independent = []
        needs_dedup = {}  # (type, client_id) → highest-strength Signal

        for s in signals:
            if s.type not in CORRELATED_TYPES:
                independent.append(s)
                continue

            cid = s.proposed_client_id
            if not cid:
                # No client to dedup against — keep as independent
                independent.append(s)
                continue

            key = (s.type, cid)
            existing = needs_dedup.get(key)
            if existing is None or s.strength > existing.strength:
                needs_dedup[key] = s

        return independent + list(needs_dedup.values())

    # -------------------------------------------------------------------------
    # AUDIT + UTILITY
    # -------------------------------------------------------------------------

    def _write_audit(self, block, decision: ClassificationDecision,
                     client_before_id: Optional[int], client_after_id: Optional[int],
                     category_before: str, category_after: str,
                     source: str):
        """Write a ClassificationAudit row for this decision."""
        try:
            from tracker.models import ClassificationAudit

            audit_source = self._map_state_to_audit_source(source, decision)

            ClassificationAudit.objects.create(
                block=block,
                source=audit_source,
                client_before_id=client_before_id,
                client_after_id=client_after_id,
                category_before=category_before,
                category_after=category_after,
                confidence_client=decision.confidence if decision.client_id else 0.0,
                confidence_category=decision.confidence if decision.category else 0.0,
                overall_confidence=decision.confidence,
                matched_signals=decision.signals_dicts(),
                corrected_by_user=False,
            )
        except Exception as e:
            logger.warning(f'Failed to write ClassificationAudit for block {block.pk}: {e}')

    @staticmethod
    def _extract_dominant_category(block) -> str:
        """Pull the largest-hours category out of category_hours, or empty string."""
        if not block.category_hours:
            return ''
        return max(block.category_hours.items(), key=lambda x: x[1])[0]

    @staticmethod
    def _map_state_to_categorized_by(source: str) -> str:
        """Map our state_changed_by to the legacy categorized_by enum."""
        return {
            'classifier':      'ai',
            'user':            'manual',
            'user_edit':       'correction',
            'admin_bulk':      'import',
            'auto_commit_eod': 'ai',
            'rule':            'pattern',
            'correction':      'correction',
        }.get(source, 'ai')

    @staticmethod
    def _map_state_to_audit_source(source: str, decision: ClassificationDecision) -> str:
        """Map our state_changed_by to the ClassificationAudit.SOURCE_CHOICES enum."""
        if source in ('user', 'user_edit', 'correction'):
            return 'manual'
        if decision.source == 'org_rule' or decision.source.startswith('org_rule'):
            return 'deterministic'
        if any(s.type in ('title_match', 'tax_software', 'file_path', 'org_rule') for s in decision.matched_signals):
            return 'deterministic'
        if any(s.type == 'learned_pattern' for s in decision.matched_signals):
            return 'pattern'
        if any(s.type == 'ai_inference' for s in decision.matched_signals):
            return 'ai'
        return 'pattern'  # fallback


# =============================================================================
# CONSTANTS — kept at the bottom for readability
# =============================================================================

# Per-industry fallback categories for the rare case where the classifier
# produced a client but no usable category (or only an Idle-bucket category
# which gets filtered out so the block doesn't disappear from the dashboard).
#
# Keys are Organization.industry_type values. Values are
# (billable_fallback, non_billable_fallback). Both names must exist in the
# industry's allowed category list (see industry_categories.py).
FALLBACK_CATEGORIES = {
    'cpa': ('General Client Work', 'Personal/Non-Billable'),
    'general': ('Project Work', 'Personal/Non-Billable'),
    'ai_consulting': ('Project Work', 'Personal/Non-Billable'),
}
# Used when industry_type isn't in the map above
FALLBACK_CATEGORIES_DEFAULT = ('Project Work', 'Personal/Non-Billable')

# Patterns that, if found in window title (case-insensitive substring), suppress the block.
# These are generic OS dialogs and transient windows that shouldn't count as work.
SUPPRESS_PATTERNS = [
    'save as',
    'open file',
    'open as',
    'print preview',
    'print...',
    'page setup',
    'preferences',
    'settings',
    'about',
    'help',
    'task manager',
    'cflyoutframe',
    'input screen ctrl+i',
    'select item',
    'browse for folder',
    'choose folder',
    'sign in to your account',
    'sharing link validation',
    'working...',
    'redirecting',
    'authenticating',
]

# Bare tax software splash titles (exact match required, lowercase)
BARE_TAX_SOFTWARE_TITLES = [
    'ultratax cs',
    'ultratax',
    'taxwise',
    'lacerte tax',
    'lacerte',
    'proseries',
    'drake tax',
    'drake',
]

# Stop words (don't learn these as patterns)
STOP_WORDS = {
    'the', 'and', 'for', 'with', 'this', 'that', 'from', 'have',
    'inbox', 'outlook', 'email', 'mail', 'word', 'excel', 'powerpoint',
    'document', 'file', 'folder', 'window', 'tab',
}

# Signatures that are ALWAYS firm overhead → non-billable, safe to AUTO-COMMIT
# (not just propose). These are unambiguous: an email inbox, a login screen, a
# blank new browser tab is never billable client work for anyone. Matching here
# lets FIX 6 commit the non-billable default instead of leaving it as a proposal
# that the user has to confirm — clearing the overhead pile with zero touch.
# Non-billable is the safe direction (a wrongly-non-billable block is visible
# and re-billable in Daily Review; it can never mis-charge a client).
AUTO_NONBILLABLE_TITLE_SUBSTRINGS = (
    'inbox',
    'new tab',
    'sign in', 'sign-in', 'log in', 'login',
    'enter your phone',
    'creative cloud desktop',
    'payroll subscription',
    # v1.3.76: QB/tax/OS navigation & dialog chrome that names no client.
    # SAFE because _is_overhead only fires when block already has NO client
    # and NO AI category (see _finalize_decision ~line 4265) — real billable
    # reconciliation/payroll work has a client and never reaches here.
    'begin reconciliation',
    'select reconciliation',
    'reconciliation report',
    'print preview',
    'print checks',
    'printer setup',
    'preview paycheck',
    'special paycheck situation',
    'preparer options',
    'past transactions',
    'recycle bin',
    'this pc',
    'quick access',
    'control panel',
    'task manager',
)
AUTO_NONBILLABLE_APPS = (
    'olk',
)


# Short single-word aliases that produce too many false matches.
# Stage 3 skips these entirely. Stage 2 _match_taxpayer_to_client also skips.
# All entries should be lowercase.
SHORT_ALIAS_STOPLIST = {
    'internal',     # "Internal Revenue Service"
    'tax',          # appears in too many titles
    'office',       # "Office 365", "office hours"
    'admin',        # "administrator login"
    'home',         # "home page"
    'main',         # "main menu"
    'login',        # "login.gov"
    'work',         # "Microsoft Edge - Work"
    'auth',         # "auth.example.com"
    'support',      # "support ticket"
    'service',      # "Internal Revenue Service"
    'client',       # "client tracking file"
    'user',         # "user profile"
    'data',         # "data analysis"
    'team',         # "Microsoft Teams"
    'view',         # too generic
    'page',         # "1 more page"
    'list',         # "client list"
    'group',        # "group settings"
    'account',      # "account management"
    'system',       # "system settings"
    'general',      # too generic
    'web',          # "web browser"
    'site',         # "site settings"
    'app',          # too short anyway
    'apps',
    'all',
    'new',
    'edit',
    'open',
    'save',
    'help',
}

# v1.3.23: Mutually exclusive entity classes. If the title contains
# one of these AND the client name contains the OTHER one from the same
# group, the match is rejected. Prevents "St. Mary's Church" titles
# matching "St. Mary's Cemetery" client and similar mixups.
#
# Each set is a group of mutually exclusive types — a real-world entity
# is one of them, never multiple. A parish might have BOTH a church and
# a cemetery as separate accounting entities (separate clients), so
# matching one to the other is always wrong.
EXCLUSIVE_ENTITY_CLASSES = [
    # Religious entity types
    {'church', 'cemetery', 'fund', 'foundation', 'school'},
    # Business entity types
    {'inc', 'llc', 'cemetery', 'fund'},
]

DOMAIN_COMMON_WORDS = {
    # Religious
    'saint', 'church', 'catholic', 'parish', 'diocese', 'cemetery',
    'school', 'foundation', 'community', 'ministry', 'mission',
    'chapel', 'temple', 'synagogue', 'mosque', 'baptist', 'methodist',
    'presbyterian', 'episcopal',
    # Generic facility / location descriptors
    'center', 'centre', 'house', 'place', 'office', 'building',
    'practice', 'clinic', 'medical', 'dental', 'family', 'general',
    # v1.3.51: Business-type descriptors. Appear in many client names
    # AND in unrelated content (government agency names like "Internal
    # Revenue Service", news article titles, dialog screens).
    'service', 'services', 'company', 'enterprises', 'group',
    'associates', 'partners', 'solutions', 'holdings', 'consulting',
    'inc', 'llc', 'corp', 'ltd',
    # v1.3.53: Common-English qualifier adjectives that appear in real
    # client names AND in everyday writing. "Complete" was matching
    # "complex" via 4-char fuzzy prefix and causing "CNY Complete
    # Contracting LLC" to false-match an IRS tax-research haystack
    # containing "complex tax topics". Same risk applies to other
    # qualifier words — they don't uniquely identify a client.
    'complete', 'comprehensive', 'professional', 'premium', 'standard',
    'national', 'regional', 'local', 'global', 'advanced', 'integrated',
    'unified', 'universal', 'modern', 'classic', 'essential', 'onedrive', 
    'sharepoint', 'sharing', 'validation', 'signin',
}

# v1.3.23: Reject matches where the haystack has no specific content.
# "client tracking file 2025 - Excel" has zero distinctive tokens after
# removing generic words, so it shouldn't fire a strong match against
# anything. Extends DOMAIN_COMMON_WORDS with generic app / OS / file
# vocabulary that appears in titles without indicating a client.
GENERIC_HAYSTACK_WORDS = DOMAIN_COMMON_WORDS | {
    'client', 'file', 'tracking', 'information', 'compatibility',
    'mode', 'excel', 'outlook', 'word', 'processing', 'managing',
    'background', 'services', 'connect', 'system', 'login',
    'document', 'untitled', 'work',
}

# Words that should never single-token-match an alias, even if they
# survive the stop-word filter. These are common English terms that
# appear in unrelated content all the time (news, search results,
# product descriptions, etc).
#
# This blocklist is the safety net for the more important fix above
# (rejecting single-token-survival from multi-word aliases). Even if
# someone explicitly sets a one-word alias from this list, we refuse
# to use it for matching.
SINGLE_TOKEN_ALIAS_BLOCKLIST = {
    # Business descriptors
    'systems', 'system', 'group', 'solutions', 'services', 'service',
    'company', 'companies', 'corporation', 'corp', 'enterprises',
    'enterprise', 'holdings', 'partners', 'consulting', 'management',
    'industries', 'international', 'global', 'national', 'regional',
    'associates', 'agency', 'firm', 'office', 'studio', 'studios',
    'works', 'team',
    # Industry verticals
    'marketing', 'media', 'communications', 'news', 'finance',
    'financial', 'capital', 'investments', 'investment', 'properties',
    'property', 'realty', 'real', 'estate', 'design', 'designs',
    'technology', 'technologies', 'software', 'digital', 'creative',
    # Generic descriptors that pair with everything
    'auto', 'home', 'water', 'energy', 'health', 'medical', 'dental',
    'legal', 'tax', 'accounting', 'audit', 'insurance', 'banking',
    # Quality / size adjectives
    'best', 'first', 'premier', 'select', 'standard', 'professional',
    'modern', 'classic', 'new', 'old', 'big', 'small', 'main',
    'central', 'general', 'family', 'community',
}

# Stop words for tokenization (mirrors agent's _STOP_WORDS).
ALIAS_STOP_WORDS = {
    "and", "the", "for", "inc", "llc", "ltd", "corp", "co", "group",
    "tax", "firm", "cpas", "cpa", "associates", "partners", "services",
}

# Generic legal-entity suffixes (mirrors agent's _GENERIC_SUFFIXES).
ALIAS_GENERIC_SUFFIXES = {
    'inc', 'llc', 'ltd', 'corp', 'co', 'company', 'group',
    'associates', 'partners', 'services', 'holdings', 'trust',
    'llp', 'pllc', 'pc',
}


# Client names that represent internal firm overhead, not real clients.
# Stage 2 (taxpayer matching) and Stage 3 (alias matching) skip these.
# All entries should be lowercase, normalized (whitespace stripped).
META_CLIENT_NAMES = {
    'internal',
    'internal - tax',
    'internal tax',
    'internal-tax',
    'admin',
    'administration',
    'office',
    'firm',
    'firm work',
    'overhead',
    'general',
    'misc',
    'miscellaneous',
}