# tracker/services/block_classifier.py
"""
BlockClassifier — orchestrates the 4-stage classification pipeline for TimeTracker.

PIPELINE ORDER (stops at first confident match):
  Stage 1: Deterministic  — exact alias/domain/path rules, no AI
  Stage 2: Learned patterns — UserWorkPattern with recency/occurrence weighting
  Stage 3: AI client match  — OpenAI classify-batch (client only)
  Stage 4: AI category match — OpenAI category prompt (once client is known)

THRESHOLDS (CPA billing-safe):
  >= 0.88 → auto-save, lock block
  0.70–0.87 → save with needs_review=True
  < 0.70 → return as suggestion only, do not save

CURRENT CLIENT PRIOR:
  If a current client is set, it gets +0.12 confidence boost on every stage.
  Email/meeting/browser apps boost to +0.18.
  AI override of current client requires it to beat current client by >= 0.15.

USAGE (in ai_suggestions_today view):
    from tracker.services.block_classifier import BlockClassifier

    classifier = BlockClassifier(org=org, user=user_obj)
    result = classifier.classify_block(block)
    # result is a ClassificationResult dataclass

    if result.should_auto_save:
        classifier.apply_result(block, result)   # saves + locks + learns
    else:
        # return as suggestion to frontend
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration — tweak without touching logic
# ---------------------------------------------------------------------------

# Auto-save threshold — locks the block permanently
AUTO_SAVE_THRESHOLD = 0.88

# Save-with-review threshold — saves but flags for user review
REVIEW_THRESHOLD = 0.70

# Minimum confidence to return as a suggestion at all
MIN_SUGGESTION_THRESHOLD = 0.50

# How much current-client boosts confidence on every signal
CURRENT_CLIENT_BOOST = 0.12

# Extra boost for comms/email apps where context is client-session heavy
CURRENT_CLIENT_COMMS_BOOST = 0.18

# AI override must beat current client by at least this margin
CURRENT_CLIENT_OVERRIDE_MARGIN = 0.15

# Apps that get the higher current-client boost
COMMS_APPS = {
    'outlook', 'mail', 'gmail', 'thunderbird',
    'microsoft teams', 'teams', 'slack',
    'zoom', 'google meet', 'webex',
    'quickbooks', 'qbo', 'xero', 'karbon',
}


# ---------------------------------------------------------------------------
# Result dataclass — single shape no matter which stage produced it
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    # Client
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    confidence_client: float = 0.0

    # Category
    category: Optional[str] = None
    category_hours: dict = field(default_factory=dict)
    confidence_category: float = 0.0

    # Meta
    overall_confidence: float = 0.0
    needs_review: bool = True
    source: str = "none"           # deterministic | pattern | ai | manual
    matched_signals: list = field(default_factory=list)
    reasoning: str = ""

    # Audit helpers
    current_client_was_applied: bool = False
    ai_was_called: bool = False

    @property
    def should_auto_save(self) -> bool:
        """Lock the block permanently — only if both confidence AND category present."""
        return (
            self.overall_confidence >= AUTO_SAVE_THRESHOLD
            and bool(self.category_hours)
        )

    @property
    def should_save_with_review(self) -> bool:
        """Save but mark needs_review — user sees it highlighted."""
        return (
            REVIEW_THRESHOLD <= self.overall_confidence < AUTO_SAVE_THRESHOLD
            and bool(self.category_hours)
        )


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class BlockClassifier:
    """
    Orchestrates the 4-stage classification pipeline for a single block.

    Instantiate once per request (it caches org clients + current client).
    """

    def __init__(self, org, user):
        self.org = org
        self.user = user
        self._org_clients = None        # lazy-loaded
        self._current_client = None     # lazy-loaded
        self._current_client_loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_block(self, block) -> ClassificationResult:
        """
        Run all 4 stages in order. Returns as soon as a stage is confident enough.
        Always returns a ClassificationResult (never raises).
        """
        try:
            return self._run_pipeline(block)
        except Exception as e:
            logger.exception(f"[CLASSIFIER] Unexpected error for block {block.id}: {e}")
            return ClassificationResult(
                source="error",
                reasoning=f"Classification error: {str(e)[:120]}",
            )

    def apply_result(self, block, result: ClassificationResult):
        """
        Persist a ClassificationResult to the block and trigger pattern learning.
        Only call this after confirming result.should_auto_save or should_save_with_review.
        SAFETY: re-checks is_categorized inside a select_for_update.
        """
        from django.db import transaction
        from tracker.models import Block, Client
        from tracker.services.pattern_learning import PatternLearningService

        try:
            with transaction.atomic():
                fresh = Block.objects.select_for_update().get(id=block.id)

                if fresh.is_categorized:
                    logger.info(f"[CLASSIFIER] Block {block.id} already locked — skipping apply")
                    return False

                # Apply client if known and different from current
                if result.client_id and result.client_id != getattr(fresh.client, 'id', None):
                    try:
                        client_obj = Client.objects.get(id=result.client_id, org=self.org, is_active=True)
                        fresh.client = client_obj
                    except Client.DoesNotExist:
                        logger.warning(f"[CLASSIFIER] Client {result.client_id} not found — skipping client update")

                # Apply categories
                if result.category_hours:
                    clean = {}
                    for k, v in result.category_hours.items():
                        try:
                            clean[str(k)] = float(v)
                        except (ValueError, TypeError):
                            pass

                    if clean:
                        fresh.category_hours = clean
                        fresh.ai_category = list(clean.keys())[0]
                        fresh.ai_confidence = result.overall_confidence
                        fresh.ai_processed_at = timezone.now()
                        fresh.categorized_by = result.source

                        if result.should_auto_save:
                            fresh.is_categorized = True
                            fresh.categorized_at = timezone.now()

                        fresh.save()

                        # Write audit row — tracks every save for correction analytics
                        try:
                            from tracker.models import ClassificationAudit
                            ClassificationAudit.objects.create(
                                block=fresh,
                                source=result.source,
                                client_after=fresh.client,
                                category_after=list(result.category_hours.keys())[0] if result.category_hours else '',
                                confidence_client=result.confidence_client,
                                confidence_category=result.confidence_category,
                                overall_confidence=result.overall_confidence,
                                matched_signals=result.matched_signals,
                            )
                        except Exception as e:
                            logger.warning(f"[CLASSIFIER] Audit log failed (non-fatal): {e}")

                        # Update in-memory reference for caller
                        block.client = fresh.client
                        block.category_hours = fresh.category_hours
                        block.is_categorized = fresh.is_categorized

                        # Trigger pattern learning from confirmed block
                        if result.should_auto_save and self.user:
                            try:
                                PatternLearningService.learn_from_block(fresh, self.user)
                            except Exception as e:
                                logger.warning(f"[CLASSIFIER] Pattern learning failed: {e}")

                        logger.info(
                            f"[CLASSIFIER] ✅ Applied block {block.id} → "
                            f"{result.client_name or 'no client'} | "
                            f"{list(clean.keys())} ({result.overall_confidence:.2f}) "
                            f"[{result.source}] locked={fresh.is_categorized}"
                        )
                        return True

        except Exception as e:
            logger.exception(f"[CLASSIFIER] Failed to apply result for block {block.id}: {e}")

        return False

    # ------------------------------------------------------------------
    # Stage orchestration
    # ------------------------------------------------------------------

    def _run_pipeline(self, block) -> ClassificationResult:
        current_client = self._get_current_client()

        # ── Stage 1: Deterministic ──────────────────────────────────────
        result = self._stage_deterministic(block, current_client)
        if result and result.overall_confidence >= REVIEW_THRESHOLD:
            logger.debug(f"[CLASSIFIER] Block {block.id} resolved by DETERMINISTIC ({result.overall_confidence:.2f})")
            return result

        # ── Stage 2: Learned patterns ───────────────────────────────────
        pattern_result = self._stage_learned_patterns(block, current_client)
        if pattern_result and pattern_result.overall_confidence >= REVIEW_THRESHOLD:
            logger.debug(f"[CLASSIFIER] Block {block.id} resolved by PATTERNS ({pattern_result.overall_confidence:.2f})")
            return pattern_result

        # Keep best partial result so far as a fallback
        best_so_far = _pick_best(result, pattern_result)

        # ── Stage 3: AI client match ────────────────────────────────────
        ai_client_result = self._stage_ai_client(block, current_client)

        # Merge AI client confidence with any existing pattern hints
        merged_client_result = self._merge_with_prior(ai_client_result, best_so_far, current_client)

        # ── Stage 4: AI category match ──────────────────────────────────
        final = self._stage_ai_category(block, merged_client_result)

        logger.debug(
            f"[CLASSIFIER] Block {block.id} resolved by AI "
            f"({final.overall_confidence:.2f}, needs_review={final.needs_review})"
        )
        return final

    # ------------------------------------------------------------------
    # Stage 1 — Deterministic matching
    # ------------------------------------------------------------------

    def _stage_deterministic(self, block, current_client) -> Optional[ClassificationResult]:
        """
        Check exact client alias/domain/path matches.
        Returns None if no strong match found.
        """
        from tracker.models import Client

        org_clients = self._get_org_clients()
        if not org_clients:
            return None

        haystack = _build_haystack(block)
        best_client = None
        best_confidence = 0.0
        best_signal = ""

        for client in org_clients:
            conf, signal = _score_client_deterministic(client, haystack, block)
            if conf > best_confidence:
                best_confidence = conf
                best_client = client
                best_signal = signal

        if not best_client or best_confidence < MIN_SUGGESTION_THRESHOLD:
            return None

        # Apply current-client boost
        boosted, was_applied = _apply_current_client_boost(
            best_confidence, best_client.id, current_client, block
        )

        # Build result without category (Stage 4 handles that)
        result = ClassificationResult(
            client_id=best_client.id,
            client_name=best_client.name,
            confidence_client=boosted,
            overall_confidence=boosted,
            needs_review=(boosted < AUTO_SAVE_THRESHOLD),
            source="deterministic",
            matched_signals=[{"type": best_signal, "client": best_client.name}],
            reasoning=f"Deterministic match via {best_signal}",
            current_client_was_applied=was_applied,
        )
        return result

    # ------------------------------------------------------------------
    # Stage 2 — Learned patterns
    # ------------------------------------------------------------------

    def _stage_learned_patterns(self, block, current_client) -> Optional[ClassificationResult]:
        """
        Query UserWorkPattern for this block. Returns best match or None.
        """
        from tracker.services.pattern_learning import PatternLearningService

        if not self.user:
            return None

        try:
            patterns = PatternLearningService.get_patterns_for_block(block, self.user)
        except Exception as e:
            logger.warning(f"[CLASSIFIER] Pattern lookup failed: {e}")
            return None

        if not patterns:
            return None

        # patterns = [(client_name, category, confidence), ...]
        top_client_name, top_category, top_conf = patterns[0]

        if top_conf < MIN_SUGGESTION_THRESHOLD:
            return None

        # Resolve client ID
        client_id = self._resolve_client_id(top_client_name)

        # Apply current-client boost
        if client_id:
            boosted, was_applied = _apply_current_client_boost(
                top_conf, client_id, current_client, block
            )
        else:
            boosted, was_applied = top_conf, False

        category_hours = _build_category_hours(top_category, block)

        return ClassificationResult(
            client_id=client_id,
            client_name=top_client_name,
            confidence_client=boosted,
            category=top_category,
            category_hours=category_hours,
            confidence_category=top_conf,
            overall_confidence=boosted,
            needs_review=(boosted < AUTO_SAVE_THRESHOLD),
            source="pattern",
            matched_signals=[{"type": "learned_pattern", "client": top_client_name, "category": top_category}],
            reasoning=f"Learned pattern: {top_client_name} / {top_category} ({top_conf:.2f})",
            current_client_was_applied=was_applied,
        )

    # ------------------------------------------------------------------
    # Stage 3 — AI client identification
    # ------------------------------------------------------------------

    def _stage_ai_client(self, block, current_client) -> Optional[ClassificationResult]:
        """
        Call the existing ai_classify_batch logic (client identification only).
        Returns None on failure.
        """
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None

        org_clients = self._get_org_clients()
        if not org_clients:
            return None

        try:
            from tracker.views_ai_classify import _call_openai, _cache_key
            from django.core.cache import cache

            title = getattr(block, 'window_title', '') or getattr(block, 'title', '') or ''
            cache_key = _cache_key(self.org.id, title)
            cached = cache.get(cache_key)

            if cached:
                client_id = cached.get('client_id')
                client_name = cached.get('client_name') or ''
                confidence = float(cached.get('confidence', 0.0))
            else:
                titles_batch = [{
                    "title": title,
                    "app_name": getattr(block, 'app_name', '') or '',
                    "file_path": getattr(block, 'file_path', '') or '',
                }]
                clients_payload = [
                    {"id": c.id, "name": c.name, "aliases": c.aliases or []}
                    for c in org_clients
                ]
                results = _call_openai(titles_batch, clients_payload)
                r = results[0] if results else None
                if not r:
                    return None

                client_id = r.get('client_id')
                client_name = r.get('client_name') or ''
                confidence = float(r.get('confidence', 0.0))

                # Cache it
                if client_id:
                    from tracker.views_ai_classify import CACHE_TTL
                    cache.set(cache_key, {
                        'client_id': client_id,
                        'client_name': client_name,
                        'confidence': confidence,
                    }, timeout=CACHE_TTL)

            if not client_id or confidence < MIN_SUGGESTION_THRESHOLD:
                return None

            # Apply current-client boost + override guard
            boosted, was_applied = _apply_current_client_boost(
                confidence, client_id, current_client, block
            )

            # If AI wants to override current client, enforce minimum margin
            if (current_client
                    and current_client.id != client_id
                    and not was_applied):
                current_conf = _base_current_client_confidence(block) + CURRENT_CLIENT_BOOST
                if boosted - current_conf < CURRENT_CLIENT_OVERRIDE_MARGIN:
                    # Not confident enough to override — revert to current client
                    logger.debug(
                        f"[CLASSIFIER] AI client override blocked: "
                        f"{client_name} ({boosted:.2f}) vs current {current_client.name} ({current_conf:.2f})"
                    )
                    client_id = current_client.id
                    client_name = current_client.name
                    boosted = current_conf
                    was_applied = True

            return ClassificationResult(
                client_id=client_id,
                client_name=client_name,
                confidence_client=boosted,
                overall_confidence=boosted,
                needs_review=(boosted < AUTO_SAVE_THRESHOLD),
                source="ai",
                matched_signals=[{"type": "ai_client", "client": client_name}],
                reasoning=f"AI client match: {client_name} ({boosted:.2f})",
                current_client_was_applied=was_applied,
                ai_was_called=True,
            )

        except Exception as e:
            logger.warning(f"[CLASSIFIER] AI client stage failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Stage 4 — AI category classification
    # ------------------------------------------------------------------

    def _stage_ai_category(self, block, client_result: Optional[ClassificationResult]) -> ClassificationResult:
        """
        Classify category using a focused prompt. Requires client to be known.
        Falls back to client_result if category call fails.
        """
        if client_result is None:
            return ClassificationResult(source="none", reasoning="No client identified")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return client_result

        # Don't make a category AI call if client confidence is already too low
        if client_result.confidence_client < MIN_SUGGESTION_THRESHOLD:
            return client_result

        try:
            import urllib.request

            industry_type = getattr(self.org, 'industry_type', 'general') or 'general'
            allowed_categories = _get_allowed_categories(industry_type)

            system = _build_category_system_prompt(allowed_categories)
            user_content = _build_category_user_prompt(block, client_result.client_name)

            payload = json.dumps({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.1,
                "max_tokens": 300,
            }).encode()

            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            raw = (data["choices"][0]["message"]["content"] or "").strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            parsed = json.loads(raw)

            category = parsed.get("category", "")
            cat_confidence = float(parsed.get("confidence", 0.0))
            billable = parsed.get("billable", True)
            reasoning = parsed.get("reasoning", "")

            # Validate category is in allowed set
            if category not in allowed_categories:
                logger.warning(f"[CLASSIFIER] AI returned unknown category '{category}' — discarding")
                return client_result

            # Overall confidence = harmonic mean of client + category confidence
            overall = _harmonic_mean(client_result.confidence_client, cat_confidence)

            category_hours = _build_category_hours(category, block)

            return ClassificationResult(
                client_id=client_result.client_id,
                client_name=client_result.client_name,
                confidence_client=client_result.confidence_client,
                category=category,
                category_hours=category_hours,
                confidence_category=cat_confidence,
                overall_confidence=overall,
                needs_review=(overall < AUTO_SAVE_THRESHOLD),
                source=client_result.source,
                matched_signals=client_result.matched_signals + [
                    {"type": "ai_category", "category": category, "billable": billable}
                ],
                reasoning=f"{client_result.reasoning} | Category: {category} ({cat_confidence:.2f}) — {reasoning}",
                current_client_was_applied=client_result.current_client_was_applied,
                ai_was_called=True,
            )

        except Exception as e:
            logger.warning(f"[CLASSIFIER] AI category stage failed: {e}")
            return client_result  # Return client result without category rather than nothing

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_current_client(self):
        if not self._current_client_loaded:
            from tracker.utils.blocks import get_current_client_for_user
            self._current_client = get_current_client_for_user(self.user) if self.user else None
            self._current_client_loaded = True
        return self._current_client

    def _get_org_clients(self):
        if self._org_clients is None:
            from tracker.models import Client
            self._org_clients = list(
                Client.objects.filter(org=self.org, is_active=True)
                .only('id', 'name', 'aliases')
            )
        return self._org_clients

    def _resolve_client_id(self, client_name: str) -> Optional[int]:
        if not client_name:
            return None
        for c in self._get_org_clients():
            if c.name.lower() == client_name.lower():
                return c.id
        return None

    def _merge_with_prior(
        self,
        ai_result: Optional[ClassificationResult],
        prior: Optional[ClassificationResult],
        current_client,
    ) -> Optional[ClassificationResult]:
        """
        Merge AI client result with any prior partial result.
        AI result wins if it's more confident, otherwise keep prior.
        """
        if ai_result is None:
            return prior
        if prior is None:
            return ai_result
        if ai_result.confidence_client >= prior.confidence_client:
            return ai_result
        return prior


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions — easy to unit test)
# ---------------------------------------------------------------------------

def _build_haystack(block) -> str:
    return " ".join([
        getattr(block, 'window_title', '') or '',
        getattr(block, 'title', '') or '',
        getattr(block, 'url', '') or '',
        getattr(block, 'file_path', '') or '',
    ]).lower()


def _score_client_deterministic(client, haystack: str, block) -> tuple[float, str]:
    """
    Return (confidence, signal_type) for the best deterministic match.
    Signal priority: domain > client_folder > file_path > alias > name
    """
    from tracker.services.pattern_learning import PatternLearningService

    name_lower = client.name.lower()
    aliases = [a.lower() for a in (client.aliases or [])] if client.aliases else []
    all_names = [name_lower] + aliases

    # Domain match (highest signal)
    domain = PatternLearningService._extract_domain(
        getattr(block, 'url', '') or ''
    )
    if domain:
        for alias in all_names:
            # e.g. "dauphin" in "dauphin-cpa.com"
            if len(alias) > 3 and alias.replace(' ', '') in domain.replace('-', '').replace('.', ''):
                return 0.92, "domain"

    # Client folder match
    file_path = (getattr(block, 'file_path', '') or '').lower()
    if file_path:
        for alias in all_names:
            if len(alias) > 3 and alias in file_path:
                return 0.90, "client_folder"

    # Window title / file name match (exact name or alias)
    for alias in all_names:
        if len(alias) > 3 and alias in haystack:
            return 0.82, "alias_title"

    return 0.0, ""


def _apply_current_client_boost(
    confidence: float,
    client_id: int,
    current_client,
    block,
) -> tuple[float, bool]:
    """
    Returns (boosted_confidence, was_applied).
    Boost is only applied when the match IS the current client.
    """
    if not current_client or current_client.id != client_id:
        return confidence, False

    app_lower = (getattr(block, 'app_name', '') or '').lower()
    is_comms = any(app in app_lower for app in COMMS_APPS)
    boost = CURRENT_CLIENT_COMMS_BOOST if is_comms else CURRENT_CLIENT_BOOST

    boosted = min(0.98, confidence + boost)
    return boosted, True


def _base_current_client_confidence(block) -> float:
    """
    Estimate the implicit confidence the current client has just from being set.
    Used when comparing AI override vs current client.
    """
    app_lower = (getattr(block, 'app_name', '') or '').lower()
    is_comms = any(app in app_lower for app in COMMS_APPS)
    return 0.72 if is_comms else 0.65


def _pick_best(
    a: Optional[ClassificationResult],
    b: Optional[ClassificationResult],
) -> Optional[ClassificationResult]:
    if a is None:
        return b
    if b is None:
        return a
    return a if a.overall_confidence >= b.overall_confidence else b


def _harmonic_mean(a: float, b: float) -> float:
    if a + b == 0:
        return 0.0
    return round(2 * a * b / (a + b), 4)


def _build_category_hours(category: Optional[str], block) -> dict:
    """Convert a category name + block duration into category_hours dict."""
    if not category:
        return {}
    minutes = 0
    try:
        if block.end and block.start:
            from datetime import timezone as dt_tz
            start = block.start
            end = block.end
            minutes = int((end - start).total_seconds() / 60)
    except Exception:
        pass
    hours = round(minutes / 60, 2) if minutes else 0.0
    return {category: hours}


def _get_allowed_categories(industry_type: str) -> list[str]:
    """
    Return the fixed category enum for this industry.
    Extend as needed; CPA is the primary target.
    """
    cpa_categories = [
        "Tax Preparation",
        "Tax Review",
        "Tax Research",
        "Bookkeeping",
        "Reconciliation",
        "Audit Fieldwork",
        "Audit Review",
        "Client Email / Communication",
        "Client Meeting",
        "Internal Meeting",
        "Billing / Admin",
        "Practice Development",
        "Training",
        "IT / Setup",
        "Uncategorized",
    ]
    # Future: add other industry taxonomies here
    return cpa_categories


def _build_category_system_prompt(allowed_categories: list[str]) -> str:
    cat_list = "\n".join(f"  - {c}" for c in allowed_categories)
    return f"""You are a CPA firm time-entry categorization engine.

TASK: Given a window title, app, file path, and client context, return the single best category.

ALLOWED CATEGORIES (use ONLY these exact strings):
{cat_list}

RULES:
1. Return ONLY a JSON object — no markdown, no preamble.
2. Pick the single most accurate category from the list above.
3. If the activity is clearly billable client work, billable = true.
4. Confidence: 0.90+ = very clear signal, 0.75–0.89 = reasonable match, <0.75 = ambiguous.
5. Never invent a category not in the list.

Response format:
{{"category": "Tax Preparation", "confidence": 0.91, "billable": true, "reasoning": "1040 PDF"}}"""


def _build_category_user_prompt(block, client_name: Optional[str]) -> str:
    title = getattr(block, 'window_title', '') or getattr(block, 'title', '') or ''
    app = getattr(block, 'app_name', '') or ''
    file_path = getattr(block, 'file_path', '') or ''
    url = getattr(block, 'url', '') or ''
    minutes = 0
    try:
        if block.end and block.start:
            minutes = int((block.end - block.start).total_seconds() / 60)
    except Exception:
        pass

    parts = [f"Client: {client_name or 'Unknown'}"]
    if title:
        parts.append(f"Window: {title[:160]}")
    if app:
        parts.append(f"App: {app[:80]}")
    if file_path:
        parts.append(f"File path: {file_path[:140]}")
    if url:
        parts.append(f"URL: {url[:140]}")
    if minutes:
        parts.append(f"Duration: {minutes} min")

    return "\n".join(parts)