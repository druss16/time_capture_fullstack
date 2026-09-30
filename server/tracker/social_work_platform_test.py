"""
Tests for treating social / ad platforms as a workplace.

WHY THESE EXIST
---------------
Every personal sweep keyed on a consumer parent domain, so the business
consoles on its subdomains went with it: business.facebook.com (Meta Ads
Manager) and studio.youtube.com were committed Personal/Non-Billable in EVERY
org, by second-pass, as 'correction' — which nothing ever revisits. For a
marketing agency the consumer platforms themselves are where client work
happens, and the firm bills hourly, so each sweep was lost revenue.

Two rules, both configuration in industry_categories.py:
  * PLATFORM_CONSOLE_HOSTS are work in every vertical.
  * INDUSTRY_SOCIAL_WORK['marketing'] hosts are never auto-filed personal for
    that vertical; they go to review and categorise as Social Media Management.
Every other vertical must behave exactly as before on the consumer sites.

    python manage.py shell -c "import tracker.social_work_platform_test"
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


from tracker.industry_categories import (  # noqa: E402  (pure module)
    MARKETING_CATEGORIES, PERSONAL_SITE_DETECTION, get_combined_tool_detection,
    get_personal_site_detection, is_work_platform_host,
)

print("Social/ad platforms as a workplace:")

# ── Config ────────────────────────────────────────────────────────────────
check("Ads Manager is a work platform in every vertical",
      all(is_work_platform_host('business.facebook.com', i) for i in ('cpa', 'legal', None)))
check("YouTube Studio is a work platform in every vertical",
      is_work_platform_host('studio.youtube.com', 'cpa'))
check("facebook.com is work for marketing", is_work_platform_host('facebook.com', 'marketing'))
check("facebook.com is NOT work for a CPA firm", not is_work_platform_host('facebook.com', 'cpa'))
check("a look-alike host is not a console",
      not is_work_platform_host('business.facebook.com.evil.example', 'cpa'))

check("non-marketing personal map is untouched (same object)",
      get_personal_site_detection('cpa') is PERSONAL_SITE_DETECTION)
mk = get_personal_site_detection('marketing')
mk_tokens = {t for g in mk.values() for t in g['keywords'] + g['domains']}
check("marketing personal map drops the social domains and brand words",
      not ({'facebook.com', 'facebook', 'instagram', 'youtube.com', 'youtube',
            'twitter', 'x.com', 'threads', 'tiktok'} & mk_tokens))
check("marketing personal map keeps everything else (netflix, espn, reddit)",
      {'netflix.com', 'espn.com', 'reddit.com'} <= mk_tokens)
check("filtering does not mutate the shared map",
      'facebook.com' in PERSONAL_SITE_DETECTION['social_media']['domains'])

combined = get_combined_tool_detection('marketing')
check("marketing gets a social work entry whose category is a marketing category",
      combined.get('social_platforms_work', {}).get('category') in MARKETING_CATEGORIES)
check("CPA gets no social work entry", 'social_platforms_work' not in get_combined_tool_detection('cpa'))
check("'later' is no longer a bare keyword anywhere",
      all('later' not in s.get('keywords', [])
          for i in ('marketing', 'ai_consulting') for s in get_combined_tool_detection(i).values()))


# ── Django-backed: the sweeps themselves ──────────────────────────────────
try:
    from tracker.services.second_pass import classify_block
    from tracker.utils.content_classifier import classify_event_content
    from tracker.services.classification_service import (
        ClassificationService, ClassificationDecision,
    )
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


def _blk(url, title='', app='Google Chrome'):
    return SimpleNamespace(window_title=title, url=url, app_name=app, user_id=1,
                           title=title, file_path='')


def _sp(url, title, industry):
    return classify_block(_blk(url, title), [], {}, web_autofile=False,
                          industry_type=industry)[0]


def _stage96(url, title, industry):
    svc = ClassificationService.__new__(ClassificationService)
    svc.org = SimpleNamespace(industry_type=industry)
    svc._build_haystack = lambda block: f"{title} {url}".lower()
    decision = ClassificationDecision()
    svc._stage_9_6_tool_category(_blk(url, title), decision)
    sigs = [s for s in decision.matched_signals if s.type == 'tool_category']
    return sigs[0].detail['category'] if sigs else None


if _ok:
    ADS = 'https://adsmanager.facebook.com/adsmanager/manage/campaigns'
    SUITE = 'https://business.facebook.com/latest/home'
    IG = 'https://www.instagram.com/acmemotors/'

    # second pass
    check("second-pass: Ads Manager is NOT swept for a CPA firm",
          _sp(ADS, 'Ads Manager - Manage ads - Campaigns', 'cpa') == 'propose_needs')
    check("second-pass: Meta Business Suite is NOT swept for marketing",
          _sp(SUITE, 'Meta Business Suite', 'marketing') == 'propose_needs')
    check("second-pass: instagram.com goes to review for marketing",
          _sp(IG, 'Acme Motors (@acmemotors) • Instagram photos and videos', 'marketing') == 'propose_needs')
    check("second-pass: instagram.com is still swept for a CPA firm",
          _sp(IG, 'Acme Motors (@acmemotors) • Instagram photos and videos', 'cpa') == 'commit_nb')
    check("second-pass: a URL-less 'Facebook' title is not personal for marketing",
          _sp('', 'Acme Motors | Facebook', 'marketing') != 'commit_nb')
    check("second-pass: a URL-less 'Facebook' title is still personal for CPA",
          _sp('', 'Acme Motors | Facebook', 'cpa') == 'commit_nb')
    check("second-pass: netflix is still swept for marketing",
          _sp('https://www.netflix.com/browse', 'Netflix', 'marketing') == 'commit_nb')

    # compaction content bucket
    ev = lambda url, title='': SimpleNamespace(window_title=title, url=url, app_name='chrome',
                                              content_identity='')
    check("compaction: Ads Manager is 'work' for a CPA firm",
          classify_event_content(ev(ADS), 'cpa') == 'work')
    check("compaction: instagram.com is not 'personal' for marketing",
          classify_event_content(ev(IG), 'marketing') != 'personal')
    check("compaction: instagram.com stays 'personal' for a CPA firm",
          classify_event_content(ev(IG), 'cpa') == 'personal')
    check("compaction: no industry keeps the old behaviour",
          classify_event_content(ev(IG)) == 'personal')

    # Stage 9.6 tool category
    check("Stage 9.6: Ads Manager is Paid Advertising for marketing",
          _stage96(ADS, 'Ads Manager', 'marketing') == 'Paid Advertising')
    check("Stage 9.6: Ads Manager is not Personal for a CPA firm",
          _stage96(ADS, 'Ads Manager - Facebook', 'cpa') != 'Personal/Non-Billable')
    check("Stage 9.6: instagram.com is Social Media Management for marketing",
          _stage96(IG, 'Acme Motors • Instagram', 'marketing') == 'Social Media Management')
    check("Stage 9.6: instagram.com is still Personal for a CPA firm",
          _stage96(IG, 'Acme Motors • Instagram', 'cpa') == 'Personal/Non-Billable')
    check("Stage 9.6: 'Facebook ad copy - Google Docs' is not Personal for marketing",
          _stage96('https://docs.google.com/document/d/abc', 'Facebook ad copy - Google Docs',
                   'marketing') != 'Personal/Non-Billable')
    check("Stage 9.6: youtube.com is not Personal for marketing",
          _stage96('https://www.youtube.com/watch?v=x', 'Acme spot - YouTube',
                   'marketing') != 'Personal/Non-Billable')

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
