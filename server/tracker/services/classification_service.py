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
    Stage 1  — Org routing rules (runs_at='classifier')
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

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('timetracker.classification')


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
        # TODO: Implement in Calendar chunk session. Stub for now.
        # self._stage_6_calendar(block, decision)

        # Stage 7 — Mail metadata match
        # TODO: Implement in Mail chunk session. Stub for now.
        # self._stage_7_mail(block, decision)

        # Stage 8 — Recent context (current_client_id, prior block)
        self._stage_8_recent_context(block, decision)

        # Stage 9 — Learned patterns
        self._stage_9_learned_patterns(block, decision)

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

        # Apply suppression by setting state and bailing — don't write category data
        if decision.is_suppressed:
            block.classification_state = 'suppressed'
            block.state_changed_at = timezone.now()
            block.state_changed_by = source
            block.save(update_fields=[
                'classification_state', 'state_changed_at', 'state_changed_by',
            ])
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
                block.client_id = decision.client_id
            if decision.category_hours:
                block.category_hours = decision.category_hours
            elif decision.category:
                # For proposed blocks where category_hours wasn't built, build it
                hours = round((block.minutes or 0) / 60.0, 2) if block.minutes else 0.01
                block.category_hours = {decision.category: hours}
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

        return block

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

        from tracker.models import Client, ClientPattern, OrgRoutingRule

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
                runs_at='classifier',
            )
            .select_related('target_client')
            .order_by('-priority', 'id')
        )

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
        runs_at='classifier' filter in _ensure_context_loaded.
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

        # Individual return — populate taxpayer bucket fields, no client
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

    # -------------------------------------------------------------------------
    # STAGE 3 — Deterministic title / domain / path match
    # -------------------------------------------------------------------------

    def _stage_3_title_match(self, block, decision: ClassificationDecision):
        """
        Score each org client against the block's window title, URL, and file path.
        Emits a Signal for the best match; multiple clients matching at low strength
        produces no signal.

        Three match types in priority order:
          1. URL domain matches client name/alias  → strength 0.92 (strong)
          2. File path contains client name/alias  → strength 0.90 (strong)
          3. Title contains client alias           → strength 0.82 (moderate-high)

        GUARDRAILS to prevent false-matches:
          - Skip aliases that match SHORT_ALIAS_STOPLIST (generic words like
            "Internal", "Tax", "Office") — these match too broadly.
          - For aliases shorter than 8 chars AND containing only one word,
            require word-boundary match (\\bWORD\\b), not substring match.
            This stops "Internal" from matching "Internal Revenue Service".
          - Skip clients whose normalized name is a known meta-client
            (META_CLIENT_NAMES) — these represent firm overhead, not real clients.
        """
        if not self._clients:
            return

        haystack = self._build_haystack(block)
        if not haystack:
            return

        url = (block.url or '').strip().lower()
        file_path = (block.file_path or '').strip().lower()

        best_client = None
        best_strength = 0.0
        best_match_type = ''

        for client in self._clients:
            # Skip meta-clients — these represent internal firm work, not real clients
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
                        # Compare alphanumeric-only versions
                        alias_clean = ''.join(c for c in alias if c.isalnum())
                        domain_clean = ''.join(c for c in domain if c.isalnum())
                        if len(alias_clean) >= 4 and alias_clean in domain_clean:
                            if 0.92 > best_strength:
                                best_client = client
                                best_strength = 0.92
                                best_match_type = 'domain'
                            break

            # Match 2: File path (strong)
            if file_path:
                for alias in all_names:
                    if not self._alias_is_safe(alias):
                        continue
                    if self._alias_matches_safely(alias, file_path):
                        if 0.90 > best_strength:
                            best_client = client
                            best_strength = 0.90
                            best_match_type = 'file_path'
                        break

            # Match 3: Title alias (moderate-high)
            for alias in all_names:
                if not self._alias_is_safe(alias):
                    continue
                if self._alias_matches_safely(alias, haystack):
                    if 0.82 > best_strength:
                        best_client = client
                        best_strength = 0.82
                        best_match_type = 'title_alias'
                    break

        if not best_client or best_strength < 0.65:
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
    def _alias_is_safe(alias: str) -> bool:
        """
        Returns False if the alias is on the stoplist of generic words known
        to produce false matches. Filters out 'Internal', 'Tax', 'Office', etc.
        """
        a = alias.strip().lower()
        if not a or len(a) < 4:
            return False
        if a in SHORT_ALIAS_STOPLIST:
            return False
        return True

    @staticmethod
    def _alias_matches_safely(alias: str, haystack: str) -> bool:
        """
        Match an alias against text safely:
          - Multi-word aliases ("st. theresa catholic church"): substring match OK
          - Single-word aliases >= 8 chars: substring match OK
          - Single-word aliases < 8 chars: require word-boundary match

        This stops "Internal" matching "Internal Revenue Service" while
        allowing "Pinnacle Sealing & Plowing" to match by substring.
        """
        import re

        a = alias.strip().lower()
        words = a.split()

        # Multi-word alias OR long single word — substring match is safe
        if len(words) >= 2 or len(a) >= 8:
            return a in haystack

        # Short single-word alias — require word boundary
        # Use \W (any non-word char) on both sides instead of \b which is locale-sensitive
        pattern = r'(?:^|\W)' + re.escape(a) + r'(?:\W|$)'
        return bool(re.search(pattern, haystack))

    @staticmethod
    def _build_haystack(block) -> str:
        """Combine searchable text fields into one lowercase string."""
        parts = [
            (block.window_title or block.title or ''),
            (block.url or ''),
            (block.file_path or ''),
        ]
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

    def _stage_4_file_path(self, block, decision: ClassificationDecision):
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

        Skipped if:
          - file_path is empty
          - No client matches with sufficient specificity
        """
        file_path = (block.file_path or '').strip()
        if not file_path:
            return

        # Normalize separators for analysis (Windows + Unix paths)
        normalized = file_path.replace('\\', '/').lower()

        # Split into segments, filter empty
        segments = [s for s in normalized.split('/') if s]
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
            # Skip meta-clients (same as Stage 3)
            if client.name.lower().strip() in META_CLIENT_NAMES:
                continue

            name_lower = client.name.lower()
            aliases = [a.lower() for a in (client.aliases or [])] if client.aliases else []
            all_names = [name_lower] + aliases

            for alias in all_names:
                if not self._alias_is_safe(alias):
                    continue

                # Pattern 1: Clean folder segment match (alias IS a path segment)
                # This is the strongest signal — the user is literally inside the
                # client's folder
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
                # If we found a 'Clients/' or 'Customers/' folder above, the
                # NEXT segment should be the client name
                if container_idx >= 0 and container_idx + 1 < len(segments):
                    next_seg = segments[container_idx + 1]
                    # Allow alias-as-prefix match (handles "Wood, Michael" vs "wood-michael")
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
                'file_path':   file_path[:200],  # truncate for storage
            },
        ))

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
        # The agent's selection. Treated as moderate-low (0.55) — never strong.
        # Skip on idle blocks: agent client is not meaningful when user is idle.
        if block.client_id and not is_idle_block:
            client = next((c for c in self._clients if c.id == block.client_id), None)
            if client:
                decision.matched_signals.append(Signal(
                    type='agent_current_client',
                    strength=0.55,
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

    def _stage_9_learned_patterns(self, block, decision: ClassificationDecision):
        """
        Query UserWorkPattern for matches. v1.2.96 hardening:
          - Patterns with total_predictions < 5 produce weak signals (≤0.5)
          - Email-domain patterns require client name in title
          - Confidence weighted by occurrence_count
        """
        from tracker.models import UserWorkPattern

        title = (block.window_title or block.title or '').strip()
        file_path = (block.file_path or '').strip()
        url = (block.url or '').strip()

        # Title prefix patterns
        if title:
            title_lower = title.lower()
            patterns = UserWorkPattern.objects.filter(
                user=self.user,
                org=self.org,
                pattern_type='window_title_prefix',
            ).select_related('client')

            for pattern in patterns:
                if not pattern.client:
                    continue
                key_lower = pattern.pattern_key.lower()

                # v1.2.96 hardening: require non-stop-word match of >= 5 chars
                if len(key_lower) < 5:
                    continue
                if key_lower in STOP_WORDS:
                    continue

                if key_lower in title_lower:
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

        # File path patterns
        if file_path:
            file_path_lower = file_path.lower()
            patterns = UserWorkPattern.objects.filter(
                user=self.user,
                org=self.org,
                pattern_type__in=['file_path', 'client_folder'],
            ).select_related('client')

            for pattern in patterns:
                if not pattern.client:
                    continue
                if pattern.pattern_key.lower() in file_path_lower:
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

        # URL domain patterns
        if url:
            from urllib.parse import urlparse
            try:
                domain = urlparse(url).netloc.lower()
            except Exception:
                domain = ''

            if domain:
                patterns = UserWorkPattern.objects.filter(
                    user=self.user,
                    org=self.org,
                    pattern_type='domain',
                ).select_related('client')

                for pattern in patterns:
                    if not pattern.client:
                        continue
                    if pattern.pattern_key.lower() in domain:
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

    # -------------------------------------------------------------------------
    # STAGE 10 — AI inference (last resort, cost-controlled)
    # -------------------------------------------------------------------------

    def _stage_10_ai_inference(self, block, decision: ClassificationDecision):
        """
        Call OpenAI to classify when stages 0-9 produced no useful signals.

        COST CONTROLS:
          - Only fires when no Signal has strength >= 0.65
          - Only fires when block has duration >= 1 minute (skips transients)
          - Cached per-block-title combo via Django cache (CACHE_TTL)
          - Skips entirely if OPENAI_API_KEY is not set

        Two AI calls per block when triggered:
          1. Client identification (against the org's client list)
          2. Category identification (CPA categories)

        Strength: 0.50-0.85 based on AI's stated confidence. Never auto-commits
        from Stage 10 alone — requires combination with another signal.

        This is a port from block_classifier.py with adaptations:
          - Returns Signal objects instead of ClassificationResult
          - Does not short-circuit; participates in signal aggregation
          - Confidence cap at 0.85 (was 0.88+ in old classifier with current_client boost)
        """
        # Skip if OpenAI not configured
        import os
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return

        # Skip if a moderate+ signal already fired
        max_strength = max(
            (s.strength for s in decision.matched_signals),
            default=0.0,
        )
        if max_strength >= 0.65:
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

        try:
            # ---- AI client identification ----
            client_signal = self._ai_classify_client(block, title)
            if client_signal:
                decision.matched_signals.append(client_signal)

            # ---- AI category identification ----
            # Only call category AI if we got a client (avoids categorizing nothing)
            if client_signal:
                category_signal = self._ai_classify_category(
                    block, title, client_signal.detail.get('client_name')
                )
                if category_signal:
                    decision.matched_signals.append(category_signal)

        except Exception as e:
            logger.warning(f'Stage 10 AI inference failed for block {block.pk}: {e}')

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

            titles_batch = [{
                'title':     title,
                'app_name':  getattr(block, 'app_name', '') or '',
                'file_path': getattr(block, 'file_path', '') or '',
            }]
            clients_payload = [
                {'id': c.id, 'name': c.name, 'aliases': c.aliases or []}
                for c in self._clients
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

        # Cap AI strength at 0.85 — never strong enough to auto-commit alone
        strength = min(0.85, confidence)

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

            self._log_ai_call(
                operation_type='stage_10_category',
                input_data={
                    'title':       title[:200],
                    'block_id':    block.pk,
                    'client_name': client_name,
                },
                output_data={
                    'category':      category,
                    'confidence':    ai_confidence,
                    'is_billable':   billable,
                    'reasoning':     reasoning[:200],
                },
                processing_time_ms=processing_ms,
                success=True,
            )

            if category not in allowed_categories:
                logger.warning(f"AI returned unknown category '{category}' for block {block.pk} — discarding")
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

        See design doc §4.4 for full logic.

        CONTRADICTION DETECTION (added in stages chunk):
        Before auto-committing, check that no moderate-or-better signal disagrees
        with the chosen client. Disagreement → downgrade to 'proposed'. This prevents
        cases like Stage 10 AI saying "ASR" while Stage 8 agent_current_client says
        "All Round Transportation" — both real signals, different clients, must
        not silently commit.
        """
        # Already terminated (suppressed or org rule auto-committed)
        if decision.recommended_state in ('suppressed', 'committed'):
            return decision

        signals = decision.matched_signals
        strong = [s for s in signals if s.is_strong]
        moderate = [s for s in signals if s.is_moderate]

        # Auto-commit: at least one strong signal, no contradictions
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

        # Otherwise propose if we have any signal at all
        if signals:
            self._populate_classification_from_signals(decision, signals)
            decision.recommended_state = 'proposed'
            decision.confidence = max((s.strength for s in signals), default=0.0)
            return decision

        # Nothing — captured
        decision.recommended_state = 'captured'
        decision.confidence = 0.0
        decision.reasoning = decision.reasoning or 'No classification signals matched'
        return decision

    @staticmethod
    def _has_contradicting_signal(signals: list, chosen_client_id: int) -> bool:
        """
        Returns True if any moderate-or-better signal proposes a client_id
        different from chosen_client_id.

        This catches cases like:
          - Stage 8 emits agent_current_client with client_id=A (strength 0.55, weak)
          - Stage 10 emits ai_client with client_id=B (strength 0.75, moderate)
          - Strong signal (ai_category at 0.90) has no client_id
          - Without this check, the chosen client would be B (taken from highest-
            strength signal that has a client). But A also "exists" as a signal.
            That's a contradiction worth flagging.

        We only care about moderate+ signals (strength >= 0.65). Weak signals
        like agent_current_client at 0.55 are too unreliable to count as a
        veto. EXCEPT: if a weak signal at >= 0.50 strength disagrees with a
        moderate-tier choice, we still flag — keeps the safety net for
        agent-vs-AI disagreements specifically.
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
            # A meaningful signal proposes a different client
            if s.strength >= 0.50:
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