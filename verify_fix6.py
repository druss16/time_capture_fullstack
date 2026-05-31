"""
Verify FIX 6 — default is_billable=False when no client + no AI category.

Run via Docker:
    docker compose exec -T api python manage.py shell < verify_fix6.py

Tests:
  1. Block ends with no client + no AI category → is_billable=False
  2. Block ends with no client + AI category billable=True → is_billable preserved
  3. Block ends WITH client + no AI category → is_billable=True (unaffected)
  4. Block ends with no client + AI category billable=False → is_billable=False
"""

import sys
from datetime import datetime, timezone
from unittest.mock import patch as mock_patch

from tracker.models import Block, Organization, OrganizationMembership
from tracker.services.classification_service import (
    ClassificationService,
    Signal,
)


def _ctx():
    org = (Organization.objects.filter(industry_type='cpa').first()
           or Organization.objects.first())
    membership = OrganizationMembership.objects.filter(organization=org).first()
    return org, membership.user


def _build(org, user, *, app_name, window_title, client_id=None, minutes=5):
    b = Block(
        org=org, user=user, app_name=app_name,
        window_title=window_title, title=window_title,
        url='', file_path='', minutes=minutes, client_id=client_id,
        start=datetime.now(timezone.utc), end=datetime.now(timezone.utc),
        day=datetime.now(timezone.utc).date(),
        hostname='test', device_id=0,
    )
    b.pk = 777777
    return b


def _stub(signals):
    def stub(self, block, decision):
        for s in signals:
            decision.matched_signals.append(s)
    return stub


def run():
    org, user = _ctx()
    svc = ClassificationService(org=org, user=user)
    svc._ensure_context_loaded()
    if not svc._clients:
        print("FAIL: no active clients")
        sys.exit(1)

    target = svc._clients[0]
    results = []

    # ── TEST 1: no client, no AI category → is_billable should default to False ──
    print("TEST 1: no client + no AI category → is_billable=False")
    block = _build(org, user, app_name='Msedge',
                   window_title='Random News Headline - Microsoft Edge')
    with mock_patch.object(ClassificationService, '_stage_10_ai_inference', _stub([])):
        d = svc.classify(block, skip_ai=True)
    ok = d.client_id is None and d.is_billable is False
    print(f"  client_id={d.client_id} (want None)")
    print(f"  is_billable={d.is_billable} (want False)")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
    results.append(('test_1', ok))

    # ── TEST 2: no client + AI category billable=True → is_billable preserved ──
    print("TEST 2: no client + AI category(billable=True) → is_billable=True")
    block = _build(org, user, app_name='Msedge',
                   window_title='Some random page - Microsoft Edge')
    ai_billable = Signal(
        type='ai_category', strength=0.85,
        evidence='AI category: Document Management',
        detail={'category': 'Document Management', 'is_billable': True},
    )
    with mock_patch.object(ClassificationService, '_stage_10_ai_inference',
                            _stub([ai_billable])):
        d = svc.classify(block, skip_ai=False)
    # AI category was billable=True → FIX 6 shouldn't fire → is_billable stays True
    ok = d.is_billable is True
    print(f"  is_billable={d.is_billable} (want True — preserved)")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
    results.append(('test_2', ok))

    # ── TEST 3: WITH client + no AI category → unaffected ──
    print("TEST 3: with client + no AI category → is_billable stays True")
    # Use non-browser app so agent signal isn't suppressed by FIX 1
    block = _build(org, user, app_name='Qbw.Exe',
                   window_title='QuickBooks - Working',
                   client_id=target.id)
    with mock_patch.object(ClassificationService, '_stage_10_ai_inference', _stub([])):
        d = svc.classify(block, skip_ai=True)
    ok = d.is_billable is True
    print(f"  client_id={d.client_id} (want {target.id})")
    print(f"  is_billable={d.is_billable} (want True — has client)")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
    results.append(('test_3', ok))

    # ── TEST 4: no client + AI says non-billable → is_billable=False ──
    print("TEST 4: no client + AI category(billable=False) → is_billable=False")
    block = _build(org, user, app_name='Msedge',
                   window_title='Fox News Breaking Headlines - Microsoft Edge')
    ai_nonbillable = Signal(
        type='ai_category', strength=0.85,
        evidence='AI category: Personal/Non-Billable',
        detail={'category': 'Personal/Non-Billable', 'is_billable': False},
    )
    with mock_patch.object(ClassificationService, '_stage_10_ai_inference',
                            _stub([ai_nonbillable])):
        d = svc.classify(block, skip_ai=False)
    ok = d.is_billable is False
    print(f"  is_billable={d.is_billable} (want False)")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
    results.append(('test_4', ok))

    # Summary
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    print(f"\n{passed}/{len(results)} passed")
    if passed < len(results):
        print("\n⚠️  Failures — investigate before deploy")
        sys.exit(1)
    print("\n✅ FIX 6 verified. Safe to deploy.")


run()