"""
Verification harness for v1.3.56 classification_service.py fixes.

Run from Django shell after deploying the patch:

    cd /Users/danrussell/Projects/time_capture_fullstack
    python manage.py shell < verify_v1_3_56.py

What it does: constructs 5 synthetic Block instances matching the bug
patterns from TL Wall production, runs classify() through them, and
asserts the new behavior. No database writes — pure in-memory test.

If all 5 pass, the patch is safe to deploy. If any fail, investigate
before pushing.
"""

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch as mock_patch

from tracker.models import Block, Client, Organization, OrganizationMembership
from tracker.services.classification_service import (
    ClassificationService,
    ClassificationDecision,
    Signal,
)
from django.contrib.auth import get_user_model

User = get_user_model()


def _find_test_context():
    """Find any org/user that has clients defined. Don't write anything."""
    org = Organization.objects.filter(industry_type='cpa').first()
    if not org:
        org = Organization.objects.first()
    if not org:
        print("FAIL: no Organization in DB — cannot run verification")
        sys.exit(1)
    membership = OrganizationMembership.objects.filter(organization=org).first()
    if not membership:
        print(f"FAIL: org {org.name} has no members")
        sys.exit(1)
    return org, membership.user


def _build_block(org, user, *, app_name, window_title, client_id=None,
                 file_path='', url='', minutes=5):
    """In-memory Block, never saved. Has a fake pk so logger.info calls work."""
    block = Block(
        org=org,
        user=user,
        app_name=app_name,
        window_title=window_title,
        title=window_title,
        url=url,
        file_path=file_path,
        minutes=minutes,
        client_id=client_id,
        start=datetime.now(timezone.utc),
        end=datetime.now(timezone.utc),
        day=datetime.now(timezone.utc).date(),
        hostname='test',
        device_id=0,
    )
    block.pk = 999999  # so f-string interpolation in logger doesn't error
    return block


def _stub_stage_10(signal_to_inject):
    """Returns a no-op replacement for _stage_10_ai_inference that injects
    a synthetic Signal instead of hitting OpenAI."""
    def stub(self, block, decision):
        if signal_to_inject is not None:
            decision.matched_signals.append(signal_to_inject)
    return stub


def run_tests():
    org, user = _find_test_context()
    print(f"\n=== TimeTracker classification v1.3.56 verification ===")
    print(f"Org: {org.name} | User: {user.username}\n")

    results = []

    # =========================================================================
    # TEST 1 — FIX 1: Browser block with stale agent client, no corroboration,
    # NO ai_category at all. Should suppress agent signal and end in Captured
    # with no client.
    # =========================================================================
    print("TEST 1: Browser block, stale agent client, no corroboration, no AI")
    svc = ClassificationService(org=org, user=user)
    # Pick any active client for the org as the stale "agent selection"
    svc._ensure_context_loaded()
    test_client = svc._clients[0] if svc._clients else None
    if not svc._clients:
        svc._ensure_context_loaded()
    if not svc._clients:
        print("  SKIP: no active clients in org")
        results.append(('test_1', 'SKIPPED'))
    else:
        stale_client = svc._clients[0]
        block = _build_block(
            org, user,
            app_name='Msedge',
            window_title='Listen to Your Favorite Music, Podcasts, and Radio Stations for Free! - Work - Microsoft Edge',
            client_id=stale_client.id,
        )
        # Stub out Stage 10 so we don't hit OpenAI
        with mock_patch.object(ClassificationService, '_stage_10_ai_inference', _stub_stage_10(None)):
            decision = svc.classify(block, skip_ai=True)

        agent_signals = [s for s in decision.matched_signals if s.type == 'agent_current_client']
        ok = (
            len(agent_signals) == 0
            and decision.client_id is None
            and decision.recommended_state == 'captured'
        )
        print(f"  agent_signals_emitted: {len(agent_signals)} (want 0)")
        print(f"  decision.client_id: {decision.client_id} (want None)")
        print(f"  decision.state: {decision.recommended_state} (want captured)")
        print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
        results.append(('test_1', 'PASS' if ok else 'FAIL'))

    # =========================================================================
    # TEST 2 — FIX 2: Browser block with ai_category (strong, billable) and
    # agent_current_client. Without FIX 2, ai_category would be "strong" and
    # the block would auto-commit to the agent's client. With FIX 2, it
    # should not.
    # =========================================================================
    print("TEST 2: Browser block, agent + ai_category(billable) only")
    svc = ClassificationService(org=org, user=user)
    svc._ensure_context_loaded()
    if svc._clients:
        stale_client = svc._clients[0]
        block = _build_block(
            org, user,
            app_name='Msedge',
            window_title='Some Random Website - Work - Microsoft Edge',
            client_id=stale_client.id,
        )
        # Inject a strong AI category signal (no client proposal)
        ai_cat_signal = Signal(
            type='ai_category',
            strength=0.85,
            evidence='AI category: General Client Work',
            detail={'category': 'General Client Work', 'is_billable': True},
        )
        with mock_patch.object(ClassificationService, '_stage_10_ai_inference', _stub_stage_10(ai_cat_signal)):
            decision = svc.classify(block, skip_ai=False)

        # Block should not be auto-committed to stale_client just because
        # ai_category fired
        ok = decision.recommended_state != 'committed' or decision.client_id != stale_client.id
        print(f"  decision.state: {decision.recommended_state}")
        print(f"  decision.client_id: {decision.client_id} (want != {stale_client.id})")
        print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
        results.append(('test_2', 'PASS' if ok else 'FAIL'))

    # =========================================================================
    # TEST 3 — FIX 3: Any app, ai_category says non-billable @ 0.85,
    # only stickiness signals propose a client. Should clear attribution.
    # =========================================================================
    print("TEST 3: AI non-billable verdict + only stickiness signals → clear")
    svc = ClassificationService(org=org, user=user)
    svc._ensure_context_loaded()
    if svc._clients:
        stale_client = svc._clients[0]
        # Use a NON-browser app so FIX 1 doesn't suppress the signal — we
        # want to test FIX 3 specifically
        block = _build_block(
            org, user,
            app_name='Qbw.Exe',
            window_title='Some QB Screen - QuickBooks',
            client_id=stale_client.id,
            minutes=3,  # > 1 min so AI fires
        )
        # Inject a strong AI category signal saying non-billable
        ai_nonbillable = Signal(
            type='ai_category',
            strength=0.85,
            evidence='AI category: Idle',
            detail={
                'category': 'Idle',
                'is_billable': False,
                'ai_reasoning': 'Activity does not match client work patterns',
            },
        )
        with mock_patch.object(ClassificationService, '_stage_10_ai_inference', _stub_stage_10(ai_nonbillable)):
            decision = svc.classify(block, skip_ai=False)

        ok = (
            decision.client_id is None
            and decision.recommended_state == 'captured'
            and decision.is_billable is False
        )
        print(f"  decision.client_id: {decision.client_id} (want None)")
        print(f"  decision.state: {decision.recommended_state} (want captured)")
        print(f"  decision.is_billable: {decision.is_billable} (want False)")
        print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
        results.append(('test_3', 'PASS' if ok else 'FAIL'))

    # =========================================================================
    # TEST 4 — REGRESSION: NON-browser block with stale agent client should
    # still emit agent_current_client signal (FIX 1 is browser-specific).
    # =========================================================================
    print("TEST 4: Non-browser block, agent signal NOT suppressed (regression)")
    svc = ClassificationService(org=org, user=user)
    svc._ensure_context_loaded()
    if svc._clients:
        stale_client = svc._clients[0]
        block = _build_block(
            org, user,
            app_name='Excel',
            window_title='somefile.xlsx - Excel',
            client_id=stale_client.id,
        )
        with mock_patch.object(ClassificationService, '_stage_10_ai_inference', _stub_stage_10(None)):
            decision = svc.classify(block, skip_ai=True)

        agent_signals = [s for s in decision.matched_signals if s.type == 'agent_current_client']
        ok = len(agent_signals) == 1
        print(f"  agent_signals_emitted: {len(agent_signals)} (want 1)")
        print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
        results.append(('test_4', 'PASS' if ok else 'FAIL'))

    # =========================================================================
    # TEST 5 — REGRESSION: Browser block WITH Stage 3 corroboration should
    # still emit agent signal AND commit to that client.
    # =========================================================================
    print("TEST 5: Browser block with Stage 3 alias hit on same client (regression)")
    svc = ClassificationService(org=org, user=user)
    svc._ensure_context_loaded()
    if svc._clients:
        # Find a client whose name appears clearly in a fake URL we control
        target = None
        for c in svc._clients:
            # Look for clients with a distinctive multi-word name we can craft a hit for
            name_lower = c.name.lower()
            tokens = [t for t in name_lower.split() if len(t) >= 5]
            if len(tokens) >= 2:
                target = c
                break
        if not target:
            print("  SKIP: no client with sufficiently distinctive name")
            results.append(('test_5', 'SKIPPED'))
        else:
            distinctive = ' '.join([t for t in target.name.lower().split() if len(t) >= 5][:2])
            block = _build_block(
                org, user,
                app_name='Msedge',
                window_title=f'{target.name} dashboard - Work - Microsoft Edge',
                client_id=target.id,
            )
            with mock_patch.object(ClassificationService, '_stage_10_ai_inference', _stub_stage_10(None)):
                decision = svc.classify(block, skip_ai=True)

            agent_signals = [s for s in decision.matched_signals if s.type == 'agent_current_client']
            stage3_signals = [s for s in decision.matched_signals
                              if s.type.startswith('title_match_') and s.proposed_client_id == target.id]
            ok = len(stage3_signals) >= 1 and len(agent_signals) >= 1
            print(f"  stage3_signals: {len(stage3_signals)} (want >=1)")
            print(f"  agent_signals: {len(agent_signals)} (want >=1 because corroborated)")
            print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
            results.append(('test_5', 'PASS' if ok else 'FAIL'))

    # =========================================================================
    print("=" * 60)
    passed = sum(1 for _, r in results if r == 'PASS')
    failed = sum(1 for _, r in results if r == 'FAIL')
    skipped = sum(1 for _, r in results if r == 'SKIPPED')
    for name, result in results:
        print(f"  {name}: {result}")
    print(f"\nTotals: {passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        print("\n⚠️  FAILURES PRESENT — do not deploy until investigated")
        sys.exit(1)
    else:
        print("\n✅ All tests passed. Safe to deploy v1.3.56.\n")


run_tests()