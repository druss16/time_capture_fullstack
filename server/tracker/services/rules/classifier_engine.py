"""
tracker/services/rules/classifier_engine.py

Backend rule engine for the BlockClassifier.

CALLED FROM
-----------
tracker/services/block_classifier.py at NEW Stage 0c
(between 0b "internal firm work" and Stage 1 "tax software").

WHAT IT DOES
------------
Reads OrgRoutingRule rows where runs_at='classifier' and enabled=True
for the block's org. Evaluates them in priority order. The first matching
terminal rule produces a ClassificationResult (which short-circuits the
rest of the classifier).

Supported actions at this stage:
  - assign_category   — set the block's category
  - mark_non_billable — set is_billable=False
  - flag_for_review   — set needs_review=True + review_reason
                        (also runs at post_save for non-classifier triggers)

USAGE
-----
    from tracker.services.rules.classifier_engine import ClassifierRuleEngine

    engine = ClassifierRuleEngine(org=block.org)
    result = engine.apply(block)
    if result:
        return result   # short-circuit the rest of the classifier
"""

import logging
from typing import Optional

from django.utils import timezone
from django.db.models import F

logger = logging.getLogger(__name__)


class ClassifierRuleEngine:
    """
    Evaluates classifier-stage rules for a single block.
    Stateless — instantiate per block (or per request, with one shared instance).
    """

    def __init__(self, org):
        self.org = org
        self._rules = None  # Lazy-loaded

    def _load_rules(self):
        """Lazy-load the org's classifier-stage rules, sorted by priority."""
        if self._rules is None:
            from tracker.models import OrgRoutingRule
            self._rules = list(
                OrgRoutingRule.objects
                .filter(
                    org=self.org,
                    enabled=True,
                    runs_at='classifier',
                )
                .order_by('-priority', 'id')
            )
        return self._rules

    def apply(self, block) -> Optional['ClassificationResult']:
        """
        Evaluate classifier rules against this block. Returns a
        ClassificationResult if a rule fired terminally, else None.
        """
        rules = self._load_rules()
        if not rules:
            return None

        from tracker.services.rules.matcher import build_context, rule_to_dict, rule_matches

        ctx = build_context(
            title=getattr(block, 'window_title', '') or '',
            exe=self._infer_exe(block),
            file_path=getattr(block, 'file_path', '') or '',
            app_name=getattr(block, 'app_name', '') or '',
            duration_minutes=block.minutes,
            has_attributed_client=bool(block.client_id),
        )

        for rule_obj in rules:
            rule_dict = rule_to_dict(rule_obj)
            if not rule_matches(rule_dict, ctx):
                continue

            result = self._apply_action(rule_obj, rule_dict, block)
            if result is not None:
                self._record_fire(rule_obj, block, ctx, result)
                logger.info(
                    f'[CLASSIFIER-RULES] Rule {rule_obj.id} fired on block {block.id}: '
                    f'{rule_obj.action} → {result.reasoning}'
                )
                return result

        return None

    def _apply_action(self, rule_obj, rule_dict: dict, block):
        """
        Translate a matched rule into a ClassificationResult.
        Returns None for rules that don't produce a terminal classification.
        """
        from tracker.services.block_classifier import ClassificationResult, _build_category_hours

        action = rule_dict.get('action')

        if action == 'assign_category':
            target_cat = rule_dict.get('target_category')
            if not target_cat:
                logger.warning(
                    f'[CLASSIFIER-RULES] Rule {rule_obj.id} action=assign_category but '
                    f'target_category is empty — skipping'
                )
                return None
            return ClassificationResult(
                client_id=block.client_id,
                client_name=block.client.name if block.client else None,
                category=target_cat,
                category_hours=_build_category_hours(target_cat, block),
                confidence_category=0.95,
                overall_confidence=0.95,
                needs_review=False,
                source='org_rule',
                reasoning=f'Org rule #{rule_obj.id}: {rule_obj.match_type}={rule_obj.match_value!r} → {target_cat}',
                matched_signals=[{
                    'type':        'classifier_rule',
                    'rule_id':     rule_obj.id,
                    'match_type':  rule_obj.match_type,
                    'match_value': rule_obj.match_value,
                    'action':      action,
                    'target':      target_cat,
                }],
            )

        if action == 'mark_non_billable':
            # This action doesn't terminate classification — it's a *modifier*.
            # We still want classification to run, but with billable=False.
            # For now, we return None and let the post_save engine handle it
            # via the non_billable rule path. (Alternative: extend
            # ClassificationResult to carry an is_billable override.)
            return None

        if action == 'flag_for_review':
            # Same — flagging is a modifier, not a terminal classification.
            # Handled by PostSaveRuleEngine.
            return None

        # Routing-stage actions (route_to_client, never_switch_away, suppress)
        # should never appear here — they're agent-stage. Defensive log.
        logger.debug(
            f'[CLASSIFIER-RULES] Rule {rule_obj.id} has action={action} — '
            f'not a classifier-stage action, skipping'
        )
        return None

    @staticmethod
    def _infer_exe(block) -> str:
        """
        Try to derive the exe name from app_name or other fields.
        TimeTracker stores the exe as app_name in some cases (e.g. 'Utw25').
        """
        app = getattr(block, 'app_name', '') or ''
        if app and not app.endswith('.exe'):
            # Heuristic: if app_name looks like an exe stem, treat it as such
            return app.lower()
        return app.lower()

    @staticmethod
    def _record_fire(rule_obj, block, context: dict, result):
        """
        Write a RuleFireLog row + bump the rule's fire_count counter.
        """
        try:
            from tracker.models import OrgRoutingRule, RuleFireLog

            RuleFireLog.objects.create(
                rule=rule_obj,
                rule_version=getattr(rule_obj, 'version', 1),
                org=rule_obj.org,
                block=block,
                engine='classifier',
                context={
                    'title':     context.get('title', '')[:200],
                    'exe':       context.get('exe', ''),
                    'file_path': context.get('file_path', '')[:200],
                    'duration':  context.get('duration_minutes'),
                },
                outcome={
                    'action':         rule_obj.action,
                    'category':       result.category,
                    'category_hours': result.category_hours,
                    'reasoning':      result.reasoning[:500],
                },
            )

            OrgRoutingRule.objects.filter(id=rule_obj.id).update(
                fire_count=F('fire_count') + 1,
                last_fired_at=timezone.now(),
            )
        except Exception as e:
            # Audit failures must not break classification
            logger.warning(f'[CLASSIFIER-RULES] Failed to record fire for rule {rule_obj.id}: {e}')