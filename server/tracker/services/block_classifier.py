# tracker/services/block_classifier.py
"""
BlockClassifier — orchestrates the 5-stage classification pipeline for TimeTracker.

PIPELINE ORDER (stops at first confident match):
  Stage 0: Suppress       — generic dialogs / internal firm work (no AI, no client)
  Stage 1: Tax software   — UltraTax/TaxWise open return extraction (SSN hashed+discarded)
  Stage 2: Deterministic  — exact alias/domain/path rules, no AI
  Stage 3: Learned patterns — UserWorkPattern with recency/occurrence weighting
  Stage 4: AI client match  — OpenAI classify-batch (client only)
  Stage 5: AI category match — OpenAI category prompt (once client is known)

THRESHOLDS (CPA billing-safe):
  >= 0.88 → auto-save, lock block
  0.70–0.87 → save with needs_review=True
  < 0.70 → return as suggestion only, do not save

CURRENT CLIENT PRIOR:
  If a current client is set, it gets +0.12 confidence boost on every stage.
  Email/meeting/browser apps boost to +0.18.
  AI override of current client requires it to beat current client by >= 0.15.

TAXPAYER BUCKETS:
  Individual tax returns (1040, etc.) are bucketed by taxpayer name + SSN hash.
  SSNs are extracted positionally from UltraTax titles and immediately hashed —
  the raw SSN never leaves tracker/utils/tax_software.py.
  Business returns (1065, 1120S) attempt a client record match first.

USAGE (in ai_suggestions_today view):
    from tracker.services.block_classifier import BlockClassifier

    classifier = BlockClassifier(org=org, user=user_obj)
    result = classifier.classify_block(block)

    if result.should_auto_save:
        classifier.apply_result(block, result)
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
# Configuration
# ---------------------------------------------------------------------------

AUTO_SAVE_THRESHOLD       = 0.88
REVIEW_THRESHOLD          = 0.70
MIN_SUGGESTION_THRESHOLD  = 0.50
CURRENT_CLIENT_BOOST      = 0.12
CURRENT_CLIENT_COMMS_BOOST = 0.18
CURRENT_CLIENT_OVERRIDE_MARGIN = 0.15

COMMS_APPS = {
    'outlook', 'mail', 'gmail', 'thunderbird',
    'microsoft teams', 'teams', 'slack',
    'zoom', 'google meet', 'webex',
    'quickbooks', 'qbo', 'xero', 'karbon',
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    # Client (None for individual tax returns)
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    confidence_client: float = 0.0

    # Category
    category: Optional[str] = None
    category_hours: dict = field(default_factory=dict)
    confidence_category: float = 0.0

    # Taxpayer bucket fields (individual returns only)
    taxpayer_name: Optional[str] = None
    taxpayer_id_hash: Optional[str] = None
    tax_return_type: Optional[str] = None

    # Meta
    overall_confidence: float = 0.0
    needs_review: bool = True
    source: str = "none"
    matched_signals: list = field(default_factory=list)
    reasoning: str = ""

    # Audit helpers
    current_client_was_applied: bool = False
    ai_was_called: bool = False

    @property
    def should_auto_save(self) -> bool:
        return (
            self.overall_confidence >= AUTO_SAVE_THRESHOLD
            and bool(self.category_hours)
        )

    @property
    def should_save_with_review(self) -> bool:
        return (
            REVIEW_THRESHOLD <= self.overall_confidence < AUTO_SAVE_THRESHOLD
            and bool(self.category_hours)
        )

    @property
    def is_suppressed(self) -> bool:
        return self.source == "suppressed"

    @property
    def is_individual_return(self) -> bool:
        return bool(self.taxpayer_name and not self.client_id)


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class BlockClassifier:
    """
    Orchestrates the 5-stage classification pipeline for a single block.
    Instantiate once per request (caches org clients + current client).
    """

    def __init__(self, org, user):
        self.org = org
        self.user = user
        self._org_clients = None
        self._current_client = None
        self._current_client_loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_block(self, block) -> ClassificationResult:
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
        Handles both client blocks and individual-return (taxpayer bucket) blocks.
        SAFETY: re-checks is_categorized inside select_for_update.
        """
        from django.db import transaction
        from tracker.models import Block, Client
        from tracker.services.pattern_learning import PatternLearningService

        # Suppressed blocks are not saved at all
        if result.is_suppressed:
            return False

        try:
            with transaction.atomic():
                fresh = Block.objects.select_for_update().get(id=block.id)

                if fresh.is_categorized:
                    logger.info(f"[CLASSIFIER] Block {block.id} already locked — skipping apply")
                    return False

                # --- Apply client (business blocks only) ---
                if result.client_id and result.client_id != getattr(fresh.client, 'id', None):
                    try:
                        client_obj = Client.objects.get(
                            id=result.client_id, org=self.org, is_active=True
                        )
                        fresh.client = client_obj
                    except Client.DoesNotExist:
                        logger.warning(
                            f"[CLASSIFIER] Client {result.client_id} not found — skipping"
                        )

                # --- Apply taxpayer bucket (individual return blocks) ---
                if result.taxpayer_name and result.taxpayer_id_hash:
                    fresh.taxpayer_name     = result.taxpayer_name
                    fresh.taxpayer_id_hash  = result.taxpayer_id_hash
                    fresh.tax_return_type   = result.tax_return_type

                    # get_or_create the TaxpayerBucket record
                    try:
                        from tracker.models import TaxpayerBucket
                        bucket, created = TaxpayerBucket.objects.get_or_create(
                            org=self.org,
                            taxpayer_id_hash=result.taxpayer_id_hash,
                            defaults={
                                "display_name": result.taxpayer_name,
                                "software": getattr(result, '_software', ''),
                            },
                        )
                        # Update return_types_seen (informational)
                        if result.tax_return_type and result.tax_return_type not in bucket.return_types_seen:
                            bucket.return_types_seen = bucket.return_types_seen + [result.tax_return_type]
                            bucket.save(update_fields=["return_types_seen", "last_seen"])

                        # Handle display_name disambiguation (same name, different hash)
                        _ensure_unique_display_name(bucket, self.org)

                        fresh.taxpayer_bucket = bucket
                    except Exception as e:
                        logger.warning(f"[CLASSIFIER] TaxpayerBucket upsert failed (non-fatal): {e}")

                # --- Apply categories ---
                if result.category_hours:
                    clean = {}
                    for k, v in result.category_hours.items():
                        try:
                            clean[str(k)] = float(v)
                        except (ValueError, TypeError):
                            pass

                    if clean:
                        fresh.category_hours    = clean
                        fresh.ai_category       = list(clean.keys())[0]
                        fresh.ai_confidence     = result.overall_confidence
                        fresh.ai_processed_at   = timezone.now()
                        fresh.categorized_by    = result.source

                        if result.should_auto_save:
                            fresh.is_categorized  = True
                            fresh.categorized_at  = timezone.now()

                        fresh.save()

                        # Write audit row
                        try:
                            from tracker.models import ClassificationAudit
                            ClassificationAudit.objects.create(
                                block=fresh,
                                source=result.source,
                                client_after=fresh.client,
                                category_after=list(result.category_hours.keys())[0],
                                confidence_client=result.confidence_client,
                                confidence_category=result.confidence_category,
                                overall_confidence=result.overall_confidence,
                                matched_signals=result.matched_signals,
                            )
                        except Exception as e:
                            logger.warning(f"[CLASSIFIER] Audit log failed (non-fatal): {e}")

                        # Update in-memory reference
                        block.client            = fresh.client
                        block.category_hours    = fresh.category_hours
                        block.is_categorized    = fresh.is_categorized
                        block.taxpayer_name     = fresh.taxpayer_name
                        block.taxpayer_id_hash  = fresh.taxpayer_id_hash

                        # Pattern learning (only for confirmed client blocks)
                        if result.should_auto_save and self.user and result.client_id:
                            try:
                                PatternLearningService.learn_from_block(fresh, self.user)
                            except Exception as e:
                                logger.warning(f"[CLASSIFIER] Pattern learning failed: {e}")

                        logger.info(
                            f"[CLASSIFIER] ✅ Applied block {block.id} → "
                            f"{result.client_name or result.taxpayer_name or 'no client'} | "
                            f"{list(clean.keys())} ({result.overall_confidence:.2f}) "
                            f"[{result.source}] locked={fresh.is_categorized}"
                        )
                        return True

        except Exception as e:
            logger.exception(f"[CLASSIFIER] Failed to apply result for block {block.id}: {e}")

        return False

    # ------------------------------------------------------------------
    # Pipeline orchestration
    # ------------------------------------------------------------------

    def _run_pipeline(self, block) -> ClassificationResult:
        title = getattr(block, 'window_title', '') or ''

        # ── Stage 0a: Suppress generic dialogs ─────────────────────────
        from tracker.utils.tax_software import is_generic_tax_dialog, is_internal_firm_work
        if is_generic_tax_dialog(title):
            logger.debug(f"[CLASSIFIER] Block {block.id} SUPPRESSED (generic dialog)")
            return ClassificationResult(
                source="suppressed",
                reasoning=f"Generic tax/app dialog suppressed: '{title[:80]}'",
            )

        # ── Stage 0b: Internal firm work shortcut ───────────────────────
        internal_cat = is_internal_firm_work(title)
        if internal_cat:
            logger.debug(f"[CLASSIFIER] Block {block.id} → INTERNAL ({internal_cat})")
            return ClassificationResult(
                client_id=None,
                client_name=None,
                category=internal_cat,
                category_hours=_build_category_hours(internal_cat, block),
                confidence_category=0.90,
                overall_confidence=0.90,
                needs_review=False,
                source="deterministic",
                reasoning=f"Internal firm work: {internal_cat}",
            )

        # ── Stage 1: Tax software extraction ───────────────────────────
        from tracker.utils.tax_software import extract_tax_context
        tax_ctx = extract_tax_context(title)
        if tax_ctx:
            result = self._stage_tax_software(block, tax_ctx)
            if result:
                logger.debug(
                    f"[CLASSIFIER] Block {block.id} resolved by TAX_SOFTWARE "
                    f"({tax_ctx.taxpayer_name}, {tax_ctx.return_type})"
                )
                return result

        current_client = self._get_current_client()

        # ── Stage 2: Deterministic ──────────────────────────────────────
        result = self._stage_deterministic(block, current_client)
        if result and result.overall_confidence >= REVIEW_THRESHOLD:
            logger.debug(
                f"[CLASSIFIER] Block {block.id} resolved by DETERMINISTIC "
                f"({result.overall_confidence:.2f})"
            )
            return result

        # ── Stage 3: Learned patterns ───────────────────────────────────
        pattern_result = self._stage_learned_patterns(block, current_client)
        if pattern_result and pattern_result.overall_confidence >= REVIEW_THRESHOLD:
            logger.debug(
                f"[CLASSIFIER] Block {block.id} resolved by PATTERNS "
                f"({pattern_result.overall_confidence:.2f})"
            )
            return pattern_result

        best_so_far = _pick_best(result, pattern_result)

        # ── Stage 4: AI client match ────────────────────────────────────
        ai_client_result = self._stage_ai_client(block, current_client)
        merged = self._merge_with_prior(ai_client_result, best_so_far, current_client)

        # ── Stage 5: AI category match ──────────────────────────────────
        final = self._stage_ai_category(block, merged)

        logger.debug(
            f"[CLASSIFIER] Block {block.id} resolved by AI "
            f"({final.overall_confidence:.2f}, needs_review={final.needs_review})"
        )
        return final

    # ------------------------------------------------------------------
    # Stage 1 — Tax software open return
    # ------------------------------------------------------------------

    def _stage_tax_software(self, block, tax_ctx) -> Optional[ClassificationResult]:
        """
        Handle a block where a tax software title revealed an open return.

        Business returns (1065, 1120S): attempt client record match first.
        Individual returns (1040, etc.): bucket by taxpayer name, no client.

        Category is always "Tax Preparation" — if UltraTax has a return open,
        that's what the user is doing.
        """
        category_hours = _build_category_hours(tax_ctx.category, block)

        if tax_ctx.is_business_return:
            # Try to match entity name against client records
            client = self._match_name_to_client(tax_ctx.taxpayer_name)
            if client:
                current_client = self._get_current_client()
                boosted, was_applied = _apply_current_client_boost(
                    0.87, client.id, current_client, block
                )
                return ClassificationResult(
                    client_id=client.id,
                    client_name=client.name,
                    confidence_client=boosted,
                    category=tax_ctx.category,
                    category_hours=category_hours,
                    confidence_category=0.95,
                    overall_confidence=_harmonic_mean(boosted, 0.95),
                    needs_review=(boosted < AUTO_SAVE_THRESHOLD),
                    source="tax_software",
                    matched_signals=[{
                        "type": "tax_software",
                        "software": tax_ctx.software,
                        "return_type": tax_ctx.return_type,
                        "taxpayer": tax_ctx.taxpayer_name,
                        "client": client.name,
                    }],
                    reasoning=(
                        f"{tax_ctx.software} {tax_ctx.return_type}: "
                        f"'{tax_ctx.taxpayer_name}' matched client '{client.name}'"
                    ),
                    current_client_was_applied=was_applied,
                )
            # Business return but no client match — fall through to individual bucket

        # Individual return (or unmatched business return) → taxpayer bucket
        result = ClassificationResult(
            client_id=None,
            client_name=None,
            confidence_client=0.0,
            category=tax_ctx.category,
            category_hours=category_hours,
            confidence_category=0.97,
            # High overall confidence — tax software + open return = certain activity
            overall_confidence=0.93,
            needs_review=False,
            source="tax_software",
            matched_signals=[{
                "type": "tax_software",
                "software": tax_ctx.software,
                "return_type": tax_ctx.return_type,
                "taxpayer": tax_ctx.taxpayer_name,
            }],
            reasoning=(
                f"{tax_ctx.software} {tax_ctx.return_type}: "
                f"individual return '{tax_ctx.taxpayer_name}'"
            ),
            taxpayer_name=tax_ctx.taxpayer_name,
            taxpayer_id_hash=tax_ctx.taxpayer_id_hash,
            tax_return_type=tax_ctx.return_type,
        )
        # Stash software name for TaxpayerBucket record
        result._software = tax_ctx.software
        return result

    def _match_name_to_client(self, taxpayer_name: str) -> Optional[object]:
        """
        Try to match a taxpayer/entity name from tax software against org clients.
        Used for business returns (1065, 1120S) only.
        Matches last name / first significant word against client name + aliases.
        """
        if not taxpayer_name:
            return None

        # Normalize: "Everson Corp, LLC" → ["everson", "corp", "llc"]
        name_lower = taxpayer_name.lower()
        # Last name before comma, or first word
        first_token = name_lower.split(',')[0].strip().split()[0] if name_lower else ''

        if len(first_token) < 4:
            return None

        for client in self._get_org_clients():
            all_names = [client.name.lower()] + [
                a.lower() for a in (client.aliases or [])
            ]
            for name in all_names:
                if first_token in name.split() or first_token in name:
                    return client
        return None

    # ------------------------------------------------------------------
    # Stage 2 — Deterministic matching (unchanged from original)
    # ------------------------------------------------------------------

    def _stage_deterministic(self, block, current_client) -> Optional[ClassificationResult]:
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

        boosted, was_applied = _apply_current_client_boost(
            best_confidence, best_client.id, current_client, block
        )

        return ClassificationResult(
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

    # ------------------------------------------------------------------
    # Stage 3 — Learned patterns (unchanged from original)
    # ------------------------------------------------------------------

    def _stage_learned_patterns(self, block, current_client) -> Optional[ClassificationResult]:
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

        top_client_name, top_category, top_conf = patterns[0]

        if top_conf < MIN_SUGGESTION_THRESHOLD:
            return None

        client_id = self._resolve_client_id(top_client_name)

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
            matched_signals=[{
                "type": "learned_pattern",
                "client": top_client_name,
                "category": top_category,
            }],
            reasoning=f"Learned pattern: {top_client_name} / {top_category} ({top_conf:.2f})",
            current_client_was_applied=was_applied,
        )

    # ------------------------------------------------------------------
    # Stage 4 — AI client identification (unchanged from original)
    # ------------------------------------------------------------------

    def _stage_ai_client(self, block, current_client) -> Optional[ClassificationResult]:
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
                client_id  = cached.get('client_id')
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

                client_id   = r.get('client_id')
                client_name = r.get('client_name') or ''
                confidence  = float(r.get('confidence', 0.0))

                if client_id:
                    from tracker.views_ai_classify import CACHE_TTL
                    cache.set(cache_key, {
                        'client_id': client_id,
                        'client_name': client_name,
                        'confidence': confidence,
                    }, timeout=CACHE_TTL)

            if not client_id or confidence < MIN_SUGGESTION_THRESHOLD:
                return None

            boosted, was_applied = _apply_current_client_boost(
                confidence, client_id, current_client, block
            )

            if (current_client
                    and current_client.id != client_id
                    and not was_applied):
                current_conf = _base_current_client_confidence(block) + CURRENT_CLIENT_BOOST
                if boosted - current_conf < CURRENT_CLIENT_OVERRIDE_MARGIN:
                    logger.debug(
                        f"[CLASSIFIER] AI client override blocked: "
                        f"{client_name} ({boosted:.2f}) vs current "
                        f"{current_client.name} ({current_conf:.2f})"
                    )
                    client_id   = current_client.id
                    client_name = current_client.name
                    boosted     = current_conf
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
    # Stage 5 — AI category (unchanged from original)
    # ------------------------------------------------------------------

    def _stage_ai_category(self, block, client_result: Optional[ClassificationResult]) -> ClassificationResult:
        if client_result is None:
            return ClassificationResult(source="none", reasoning="No client identified")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return client_result

        if client_result.confidence_client < MIN_SUGGESTION_THRESHOLD:
            return client_result

        try:
            import urllib.request

            industry_type = getattr(self.org, 'industry_type', 'general') or 'general'
            allowed_categories = _get_allowed_categories(industry_type)

            system       = _build_category_system_prompt(allowed_categories)
            user_content = _build_category_user_prompt(block, client_result.client_name)

            payload = json.dumps({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_content},
                ],
                "temperature": 0.1,
                "max_tokens": 300,
            }).encode()

            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            raw = (data["choices"][0]["message"]["content"] or "").strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            parsed = json.loads(raw)

            category     = parsed.get("category", "")
            cat_confidence = float(parsed.get("confidence", 0.0))
            billable     = parsed.get("billable", True)
            reasoning    = parsed.get("reasoning", "")

            if category not in allowed_categories:
                logger.warning(
                    f"[CLASSIFIER] AI returned unknown category '{category}' — discarding"
                )
                return client_result

            overall        = _harmonic_mean(client_result.confidence_client, cat_confidence)
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
                matched_signals=client_result.matched_signals + [{
                    "type": "ai_category",
                    "category": category,
                    "billable": billable,
                }],
                reasoning=(
                    f"{client_result.reasoning} | "
                    f"Category: {category} ({cat_confidence:.2f}) — {reasoning}"
                ),
                current_client_was_applied=client_result.current_client_was_applied,
                ai_was_called=True,
            )

        except Exception as e:
            logger.warning(f"[CLASSIFIER] AI category stage failed: {e}")
            return client_result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_current_client(self):
        if not self._current_client_loaded:
            from tracker.utils.blocks import get_current_client_for_user
            self._current_client = (
                get_current_client_for_user(self.user) if self.user else None
            )
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
        if ai_result is None:
            return prior
        if prior is None:
            return ai_result
        if ai_result.confidence_client >= prior.confidence_client:
            return ai_result
        return prior


# ---------------------------------------------------------------------------
# TaxpayerBucket display name disambiguation
# ---------------------------------------------------------------------------

def _ensure_unique_display_name(bucket, org):
    """
    If two TaxpayerBuckets in the same org share a display_name but have
    different hashes (e.g. Wood, Michael Sr. vs Jr.), append (1), (2) etc.
    Called after get_or_create — only updates if a collision is detected.
    """
    from tracker.models import TaxpayerBucket
    duplicates = (
        TaxpayerBucket.objects
        .filter(org=org, display_name=bucket.display_name)
        .exclude(taxpayer_id_hash=bucket.taxpayer_id_hash)
    )
    if not duplicates.exists():
        return  # No collision — nothing to do

    # Number all buckets with this display_name in order of first_seen
    all_same = list(
        TaxpayerBucket.objects
        .filter(org=org, display_name__startswith=bucket.display_name.split(' (')[0])
        .order_by('first_seen')
    )
    # Strip any existing numbering
    base_name = bucket.display_name.split(' (')[0].strip()
    for i, b in enumerate(all_same, start=1):
        new_name = f"{base_name} ({i})"
        if b.display_name != new_name:
            TaxpayerBucket.objects.filter(pk=b.pk).update(display_name=new_name)


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions)
# ---------------------------------------------------------------------------

def _build_haystack(block) -> str:
    return " ".join([
        getattr(block, 'window_title', '') or '',
        getattr(block, 'title', '') or '',
        getattr(block, 'url', '') or '',
        getattr(block, 'file_path', '') or '',
    ]).lower()


def _score_client_deterministic(client, haystack: str, block) -> tuple[float, str]:
    from tracker.services.pattern_learning import PatternLearningService

    name_lower = client.name.lower()
    aliases    = [a.lower() for a in (client.aliases or [])] if client.aliases else []
    all_names  = [name_lower] + aliases

    domain = PatternLearningService._extract_domain(
        getattr(block, 'url', '') or ''
    )
    if domain:
        for alias in all_names:
            if len(alias) > 3 and alias.replace(' ', '') in domain.replace('-', '').replace('.', ''):
                return 0.92, "domain"

    file_path = (getattr(block, 'file_path', '') or '').lower()
    if file_path:
        for alias in all_names:
            if len(alias) > 3 and alias in file_path:
                return 0.90, "client_folder"

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
    if not current_client or current_client.id != client_id:
        return confidence, False

    app_lower = (getattr(block, 'app_name', '') or '').lower()
    is_comms  = any(app in app_lower for app in COMMS_APPS)
    boost     = CURRENT_CLIENT_COMMS_BOOST if is_comms else CURRENT_CLIENT_BOOST

    return min(0.98, confidence + boost), True


def _base_current_client_confidence(block) -> float:
    app_lower = (getattr(block, 'app_name', '') or '').lower()
    is_comms  = any(app in app_lower for app in COMMS_APPS)
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
    if not category:
        return {}
    minutes = 0
    try:
        if block.end and block.start:
            minutes = int((block.end - block.start).total_seconds() / 60)
    except Exception:
        pass
    hours = round(minutes / 60, 2) if minutes else 0.0
    return {category: hours}


def _get_allowed_categories(industry_type: str) -> list[str]:
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
    title     = getattr(block, 'window_title', '') or getattr(block, 'title', '') or ''
    app       = getattr(block, 'app_name', '') or ''
    file_path = getattr(block, 'file_path', '') or ''
    url       = getattr(block, 'url', '') or ''
    minutes   = 0
    try:
        if block.end and block.start:
            minutes = int((block.end - block.start).total_seconds() / 60)
    except Exception:
        pass

    parts = [f"Client: {client_name or 'Unknown'}"]
    if title:     parts.append(f"Window: {title[:160]}")
    if app:       parts.append(f"App: {app[:80]}")
    if file_path: parts.append(f"File path: {file_path[:140]}")
    if url:       parts.append(f"URL: {url[:140]}")
    if minutes:   parts.append(f"Duration: {minutes} min")

    return "\n".join(parts)