"""
Regression tests for second_pass WEB AUTO-FILE routing (classify_block).

Covers the "auto-send unrecognized web browsing to No-Client/Non-Billable"
behavior and its guardrails:

  - Signature-less news headlines (no URL) on a browser -> handed to the LLM
    ('llm_web_check'), NOT swept blindly.
  - Known work tools/portals (QBO, Onvio, ADP, Paychex, bank) -> PROTECTED as
    'work tool, needs client' and NEVER auto-non-billable, even when the title
    carries no work keyword.
  - Consumer news outlets / leisure domains -> auto-commit non-billable via the
    heuristic (no LLM needed).
  - Non-browser blocks are never routed through this path.
  - Flag OFF (web_autofile=False) reproduces today's exact behavior.
  - Existing precedence (client-name-in-title, WORKHINT) is preserved.

classify_block is pure (no network); the LLM only runs in run_second_pass. These
tests never call OpenAI — they assert the ROUTING decision.

Run inside the app container:
    python manage.py shell -c "import tracker.second_pass_web_autofile_test"
or standalone where Django is configured:
    python tracker/second_pass_web_autofile_test.py

Exits non-zero if any assertion fails.
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


def blk(title='', url='', app='Msedge'):
    return SimpleNamespace(window_title=title, url=url, app_name=app, user_id=1)


try:
    from tracker.services.second_pass import classify_block, _is_browser, _norm_app
    _ok = True
except Exception as e:  # ModuleNotFoundError / ImproperlyConfigured on bare python
    _ok = False
    _skipped = 1
    print("second_pass web-autofile:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    print("second_pass web-autofile:")
    CF, TI = [], {}  # no client forms, no title index -> isolate the web branches

    def act(block, web=True):
        return classify_block(block, CF, TI, web_autofile=web)[0]

    def reason(block, web=True):
        return classify_block(block, CF, TI, web_autofile=web)[3]

    # --- helpers ---
    check("browser detection: Msedge.Exe", _is_browser('Msedge.Exe'))
    check("browser detection: Chrome", _is_browser('Chrome'))
    check("browser detection: not Excel", not _is_browser('Excel.Exe'))
    check("norm app strips .exe", _norm_app('Msedge.Exe') == 'msedge')

    # --- the exact complaint: bare news headline, no URL, on Edge ---
    trump = blk("Trump is just one slimy move away from plunging us into an ugly conflict",
                url='', app='Msedge')
    check("headline+no-url -> LLM handoff (flag on)", act(trump) == 'llm_web_check')
    check("headline+no-url -> unrecognized nag (flag OFF)",
          act(trump, web=False) == 'propose_needs'
          and 'unrecognized' in reason(trump, web=False))

    # --- work-tool PROTECTION (must never be swept) ---
    onvio = blk("Onvio - Work - Microsoft Edge", url='', app='Msedge')
    check("Onvio (no url) -> protected work tool",
          act(onvio) == 'propose_needs' and 'work tool' in reason(onvio))

    qbo = blk("Home - Personal - Microsoft Edge", url='https://qbo.intuit.com/app/homepage',
              app='Msedge')
    check("QBO url + bland title -> protected work tool",
          act(qbo) == 'propose_needs' and 'work tool' in reason(qbo))

    adp = blk("RUN powered by ADP - Work", url='https://runpayrollmain.adp.com/x', app='Msedge')
    check("ADP payroll -> protected work tool",
          act(adp) == 'propose_needs' and 'work tool' in reason(adp))

    paychex = blk("VIVA - Paychex Employers and 5 more pages - Work", url='', app='Msedge')
    check("Paychex (no url) -> protected work tool",
          act(paychex) == 'propose_needs' and 'work tool' in reason(paychex))

    pinnacle = blk("Pinnacle Employee Services - Page Control - Work", url='', app='Msedge')
    check("Pinnacle payroll -> protected (employee keyword)",
          act(pinnacle) == 'propose_needs' and 'work tool' in reason(pinnacle))

    # --- consumer news / leisure -> auto non-billable via heuristic ---
    foxviewers = blk("Disgusted Fox News viewers shout get him off as Trump repeatedly",
                     url='', app='Msedge')
    check("'Fox News' in title -> auto non-billable (flag on)",
          act(foxviewers) == 'commit_nb')
    check("'Fox News' in title -> NOT auto-committed (flag OFF)",
          act(foxviewers, web=False) != 'commit_nb')

    iheart = blk("Listen to Your Favorite Music, Podcasts, and Radio Stations",
                 url='https://www.iheart.com/', app='Msedge')
    check("iheart -> auto non-billable", act(iheart) == 'commit_nb')

    msnnews = blk("Woman awarded 20k in discrimination case",
                  url='https://www.msn.com/en-us/news/other/thing', app='Msedge')
    check("msn news url -> auto non-billable", act(msnnews) == 'commit_nb')

    # --- deterministic consumer-DOMAIN sweep: works with the flag OFF and with
    #     no OpenAI key/credits (the whole point of the host list) ---
    msn_ent = blk("Fired '60 Minutes' producer ruins MAGA-friendly boss' big day - Work",
                  url='https://www.msn.com/en-us/entertainment/tv/fired-60-minutes', app='Msedge')
    check("msn non-/news/ path -> auto non-billable (flag ON)", act(msn_ent) == 'commit_nb')
    check("msn non-/news/ path -> auto non-billable (flag OFF)",
          act(msn_ent, web=False) == 'commit_nb')

    fox_home = blk("Fox News - Breaking News Updates", url='https://www.foxnews.com/', app='Msedge')
    check("foxnews.com host -> swept with flag OFF", act(fox_home, web=False) == 'commit_nb')

    # HARD hosts outrank WORKHINT: a news story about tax is still news.
    msn_tax = blk("Trump's new tax plan explained", url='https://www.msn.com/en-us/money/taxes/x',
                  app='Msedge')
    check("news headline with WORKHINT word -> still swept",
          act(msn_tax, web=False) == 'commit_nb')

    # SOFT hosts still defer to WORKHINT.
    amz_plain = blk("Amazon.com Order History", url='https://www.amazon.com/gp/history', app='Msedge')
    check("amazon (soft) -> swept when no work keyword", act(amz_plain, web=False) == 'commit_nb')
    amz_work = blk("Order history - invoice for client", url='https://www.amazon.com/gp/history',
                   app='Msedge')
    check("amazon (soft) + WORKHINT -> NOT swept", act(amz_work, web=False) != 'commit_nb')

    # Host match is dotted-suffix, never a loose substring.
    lookalike = blk("Client portal", url='https://notmsn.com/reports', app='Msedge')
    check("'notmsn.com' does not match msn.com", act(lookalike, web=False) != 'commit_nb')
    sub = blk("Story", url='https://edition.cnn.com/2026/story', app='Msedge')
    check("subdomain of a consumer host matches", act(sub, web=False) == 'commit_nb')

    # AI assistants live on a consumer host but are plausibly work -> protected.
    grok = blk("Grok / X and 1 more page - Work", url='https://x.com/i/grok', app='Msedge')
    check("Grok on x.com -> protected work tool, not swept",
          act(grok, web=False) == 'propose_needs' and 'work tool' in reason(grok, web=False))

    # A consumer URL must never beat a work-tool signal (stale captured url).
    stale = blk("QuickBooks Online - Work", url='https://www.msn.com/en-us/news/x', app='Msedge')
    check("work tool title beats consumer url", act(stale, web=False) == 'propose_needs'
          and 'work tool' in reason(stale, web=False))

    # Non-browser app with a consumer url is never swept by this path.
    xl = blk("Book1 - Excel", url='https://www.foxnews.com/', app='Excel.Exe')
    check("non-browser + consumer url -> not swept", act(xl, web=False) != 'commit_nb')

    # --- non-browser residuals are never routed through web autofile ---
    excel = blk("Book1 - Excel", url='', app='Excel.Exe')
    check("non-browser residual -> unrecognized nag, not LLM/sweep",
          act(excel) == 'propose_needs' and 'unrecognized' in reason(excel))

    # --- WORKHINT still protects (browser page mentioning a work keyword) ---
    wh = blk("2025 payroll summary - Work", url='', app='Msedge')
    check("WORKHINT keyword -> looks-like-client-work (not swept)",
          act(wh) == 'propose_needs' and 'client work' in reason(wh))

    # --- a news outlet that is ALSO a work tool must stay protected ---
    # (Thomson Reuters collides with 'reuters'; WORK_TOOL_HINT runs first.)
    tr = blk("Thomson Reuters CoCounsel - Work", url='https://accounting.cocounsel.thomsonreuters.com',
             app='Msedge')
    check("Thomson Reuters CoCounsel -> protected work tool (not news)",
          act(tr) == 'propose_needs' and 'work tool' in reason(tr))

    # --- work-tool guard is browser-scoped: a desktop app with a portal-ish
    #     title should not be pulled into the web path ---
    check("work-tool guard only applies to browsers",
          act(blk("ADP", url='', app='Excel.Exe')) != 'commit_nb')

print()
print(f"second_pass web-autofile: {_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
