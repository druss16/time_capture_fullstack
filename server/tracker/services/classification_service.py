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

    def classify(self, block) -> ClassificationDecision:
        """
        Classify a single block. Pure function — does NOT write to the block.

        Returns a ClassificationDecision the caller can choose to apply.

        This is THE one method that runs the full 10-stage pipeline.
        """
        self._ensure_context_loaded()

        decision = ClassificationDecision()

        # Run each stage. Each stage either:
        #   - Adds Signal(s) to decision.matched_signals
        #   - Sets decision.is_suppressed / is_meeting / is_individual_return
        #   - Returns early (Stage 0 suppress, Stage 2 individual return)

        # Stage 0 — Suppress
        if self._stage_0_suppress(block, decision):
            decision.recommended_state = 'suppressed'
            decision.is_suppressed = True
            return decision

        # Stage 1 — Org routing rules (classifier-stage)
        if self._stage_1_org_rules(block, decision):
            # Stage 1 may return early if a 'route_to_client' or 'assign_category' rule fires
            return self._finalize_decision(decision, block)

        # Stage 2 — Tax software extraction
        # TODO: Implement in Stages chunk session. Stub for now.
        # self._stage_2_tax_software(block, decision)

        # Stage 3 — Deterministic title match
        # TODO: Implement in Stages chunk session. Stub for now.
        # self._stage_3_title_match(block, decision)

        # Stage 4 — File path match
        # TODO: Implement in Stages chunk session. Stub for now.
        # self._stage_4_file_path(block, decision)

        # Stage 5 — URL domain match
        # TODO: Implement in Stages chunk session. Stub for now.
        # self._stage_5_url_domain(block, decision)

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

        # Stage 10 — AI inference
        # TODO: Implement in Stages chunk session. Stub for now.
        # self._stage_10_ai_inference(block, decision)

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

        # If committed: also write the live fields (what gets billed)
        if new_state == 'committed':
            if decision.client_id:
                block.client_id = decision.client_id
            if decision.category_hours:
                block.category_hours = decision.category_hours
            block.is_billable = decision.is_billable
            # Backwards compat with existing is_categorized field
            block.is_categorized = True
            if not block.categorized_at:
                block.categorized_at = timezone.now()
            block.categorized_by = self._map_state_to_categorized_by(source)

        # If proposed: leave live fields alone (still no client, no billing)
        # The proposal lives in proposed_* fields; commit converts them to live.

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
        Drop blocks that aren't real activities.

        Returns True if the block is suppressed and the pipeline should stop.

        Suppress conditions:
          - Bare tax software splash with no return open ("UltraTax CS")
          - Generic OS dialogs (Save As, Print, Open, etc.)
          - Empty title with very short duration (likely transient)
          - Any title matching SUPPRESS_PATTERNS below
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
    # DECISION LOGIC — auto-commit vs propose vs capture
    # -------------------------------------------------------------------------

    def _finalize_decision(self, decision: ClassificationDecision, block) -> ClassificationDecision:
        """
        After all stages run, decide the final state and confidence.

        See design doc §4.4 for full logic.
        """
        # Already terminated (suppressed or org rule auto-committed)
        if decision.recommended_state in ('suppressed', 'committed'):
            return decision

        signals = decision.matched_signals
        strong = [s for s in signals if s.is_strong]
        moderate = [s for s in signals if s.is_moderate]

        # Auto-commit: at least one strong signal, no contradictions
        if strong:
            client_ids = {s.proposed_client_id for s in strong if s.proposed_client_id}
            if len(client_ids) <= 1:
                # All strong signals agree (or only one with a client)
                self._populate_classification_from_signals(decision, signals)
                decision.recommended_state = 'committed'
                decision.confidence = max(s.strength for s in strong)
                return decision
            else:
                # Strong signals disagree on client — propose, flag for review
                decision.needs_review = True
                decision.review_reason = (
                    f'Multiple high-confidence client matches: '
                    f'{", ".join(str(cid) for cid in client_ids)}'
                )
                self._populate_classification_from_signals(decision, signals)
                decision.recommended_state = 'proposed'
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