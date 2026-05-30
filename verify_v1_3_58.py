"""
Verify v1.3.58 evidence-grounded AI prompt.

This sends the EXACT inputs that historically caused hallucinations
in TL Wall production to the NEW prompt and confirms the AI now
returns client_id=null instead of fabricating an answer.

Run via Docker:
    docker compose exec -T api python manage.py shell < verify_v1_3_58.py

⚠️  This makes REAL OpenAI API calls (3 of them). Set OPENAI_API_KEY in
   your local .env. Cost should be <$0.01 total.
"""

import os
import sys

from tracker.views_ai_classify import _call_openai

if not os.getenv('OPENAI_API_KEY'):
    print("SKIP: OPENAI_API_KEY not set in this environment")
    sys.exit(0)

# Decoy client list — includes the clients that historically got hallucinated
# (S&A Creative, 100 Maconi Ave) so the AI has the opportunity to pick them.
clients = [
    {'id': 100, 'name': 'Pinnacle Sealing & Plowing', 'aliases': ['pinnacle']},
    {'id': 102, 'name': 'S&A Creative Designs LLC', 'aliases': ['s&a', 'sacreative']},
    {'id': 144, 'name': '100 Maconi Ave, LLC', 'aliases': ['maconi']},
    {'id': 151, 'name': 'Account Temps', 'aliases': ['account temps']},
    {'id': 451, 'name': 'Internal - Tax', 'aliases': []},
]

results = []

# ── TEST 1 — Reproduces block 39976 (was hallucinated to S&A Creative) ──
print("\n=== TEST 1: fullypromoted.com file-share page (block 39976 repro) ===")
print("Historical behavior: AI proposed S&A Creative Designs at 0.85")
print("Expected new behavior: client_id=null (no client name in input)")
test_1 = [{
    'title': 'Edit Incoming File "Files from Angela Seymour angela.seymour@fullypromoted.com" - TL Wall Accounting',
    'file_path': '',
    'app_name': 'Msedge',
    'additional_titles': [],
}]
try:
    out_1 = _call_openai(test_1, clients)
    print(f"Result: {out_1}")
    ok_1 = out_1[0] is None
except Exception as e:
    print(f"ERROR: {e}")
    ok_1 = False
print(f"RESULT: {'PASS' if ok_1 else 'FAIL'}")
results.append(('test_1_fullypromoted', ok_1))

# ── TEST 2 — Reproduces block 39909 (music site, was hallucinated to Account Temps) ──
print("\n=== TEST 2: music streaming site (block 39909 repro) ===")
print("Expected new behavior: client_id=null (no client name in input)")
test_2 = [{
    'title': 'Listen to Your Favorite Music, Podcasts, and Radio Stations for Free! - Work - Microsoft Edge',
    'file_path': '',
    'app_name': 'Msedge',
    'additional_titles': [],
}]
try:
    out_2 = _call_openai(test_2, clients)
    print(f"Result: {out_2}")
    ok_2 = out_2[0] is None
except Exception as e:
    print(f"ERROR: {e}")
    ok_2 = False
print(f"RESULT: {'PASS' if ok_2 else 'FAIL'}")
results.append(('test_2_music_site', ok_2))

# ── TEST 3 — Reproduces block 36725 (Chase secure URL) ──
print("\n=== TEST 3: Chase secure URL with no client identifier (block 36725 repro) ===")
print("Expected new behavior: client_id=null")
test_3 = [{
    'title': 'secure.chase.com/svc/rr/documents/secure/idal/v5/pdfdoc/star/list?docKey=832c8ba8',
    'file_path': '',
    'app_name': 'Msedge',
    'additional_titles': [],
}]
try:
    out_3 = _call_openai(test_3, clients)
    print(f"Result: {out_3}")
    ok_3 = out_3[0] is None
except Exception as e:
    print(f"ERROR: {e}")
    ok_3 = False
print(f"RESULT: {'PASS' if ok_3 else 'FAIL'}")
results.append(('test_3_chase_url', ok_3))

# ── TEST 4 — Legitimate match — title contains client name verbatim ──
print("\n=== TEST 4: REGRESSION — legitimate Pinnacle match ===")
print("Expected: client_id=100 (Pinnacle), with evidence_quote containing 'Pinnacle'")
test_4 = [{
    'title': 'Pinnacle Sealing - Bank Reconciliation - QuickBooks',
    'file_path': '',
    'app_name': 'Qbw',
    'additional_titles': [],
}]
try:
    out_4 = _call_openai(test_4, clients)
    print(f"Result: {out_4}")
    ok_4 = (
        out_4[0] is not None
        and out_4[0].get('client_id') == 100
        and 'pinnacle' in (out_4[0].get('evidence_quote', '') or '').lower()
    )
except Exception as e:
    print(f"ERROR: {e}")
    ok_4 = False
print(f"RESULT: {'PASS' if ok_4 else 'FAIL'}")
results.append(('test_4_legitimate_match', ok_4))

# ── Summary ──
print("\n" + "=" * 60)
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
for name, ok in results:
    print(f"  {name}: {'PASS' if ok else 'FAIL'}")
print(f"\nTotals: {passed} passed, {failed} failed")
if failed:
    print("\n⚠️  Failures — investigate before deploying. The AI may need a stronger prompt nudge.")
    sys.exit(1)
print("\n✅ Source-level hallucination fix verified. Safe to deploy v1.3.58.")