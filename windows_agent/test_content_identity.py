"""
test_content_identity.py — run the extractor against REAL titles from the
2026-06-29 org-21 audit. No Windows, no DB. Just: does it tag work correctly
and leave personal as '' (so downstream marks it personal)?

Run:  python3 test_content_identity.py
"""

from content_identity import content_identity as ci

# (title, url, expected_identity_or_marker)
#   expected '' means "no work identity -> downstream classifies (usually personal)"
#   expected startswith marker means "must produce a work identity of this kind"
CASES = [
    # ---- QBO: customer detail carries the client (STRONGEST win) ----
    ("Customer - UPSTATE CEREBRAL PALSY, INC. and 1 more page - Work - Microsoft\u200b Edge",
     "https://qbo.intuit.com/app/customerdetail", "qbo:customer=upstate cerebral palsy, inc."),
    ("Customers & leads - Customer Hub and 1 more page - Work - Microsoft\u200b Edge",
     "https://qbo.intuit.com/app/customers", "qbo:section="),
    ("Profit and Loss and 1 more page - Work - Microsoft\u200b Edge",
     "https://qbo.intuit.com/app/report/builder", "qbo:section="),
    ("Balance Sheet and 1 more page - Work - Microsoft\u200b Edge",
     "https://qbo.intuit.com/app/report/builder", "qbo:section="),
    ("Bank Deposit and 1 more page - Work - Microsoft\u200b Edge",
     "https://qbo.intuit.com/app/deposit", "qbo:section="),

    # ---- Paychex: stable company id in parens ----
    ("TL Wall Tax And Accounting Corp (70189236), Dashboard and 2 more pages - Work - Microsoft\u200b Edge",
     "https://myapps.paychex.com/landing_remote/login.do", "paychex:company=70189236"),
    ("All Around Auto Repair and Sales Corp INC (70247783), Dashboard - Work - Microsoft\u200b Edge",
     "https://myapps.paychex.com/landing_remote/login.do", "paychex:company=70247783"),
    ("Tung D Nguyen DDS PC (14097382), Dashboard - Work - Microsoft\u200b Edge",
     "https://myapps.paychex.com/landing_remote/login.do", "paychex:company=14097382"),

    # ---- Pinnacle / PrismHR: section-level (honest partial — groups the app) ----
    ("Pinnacle Employee Services - Payroll Allocation Report and 2 more pages - Work - Microsoft\u200b Edge",
     "https://pin.prismhr.com/pin/dbnet.aspx", "pinnacle:report=payroll allocation report"),
    ("Pinnacle Employee Services - Home and 2 more pages - Work - Microsoft\u200b Edge",
     "https://pin.prismhr.com/pin/dbnet.aspx", "pinnacle:report=home"),

    # ---- Scanner batches + church/bank PDFs: basename is the identity ----
    ("SKMBT_42325092414300.pdf - Work - Microsoft\u200b Edge", "", "file=skmbt_42325092414300"),
    ("SKMBT_42326051311590.pdf and 14 more pages - Work - Microsoft\u200b Edge", "", "file=skmbt_42326051311590"),
    ("6-26-2026 SH Parish check requests bills and docs to be recorded.pdf - Work - Microsoft\u200b Edge",
     "", "file=6-26-2026 sh parish check requests bills and docs to be recorded.pdf"),
    ("St Francis Xavier SDIF MAY25.pdf and 4 more pages - Work - Microsoft\u200b Edge",
     "", "file=st francis xavier sdif may25.pdf"),
    ("*St Marys Bville Seneca Savings Bank Statements 5.31.26.pdf and 2 more pages - Work - Microsoft\u200b Edge",
     "", "file=st marys bville seneca savings bank statements 5.31.26.pdf"),
    ("CCF06232026_0001.pdf - Work - Microsoft\u200b Edge", "", "file=ccf06232026_0001.pdf"),
    ("VGG - July Health Bill (003).pdf and 2 more pages - Work - Microsoft\u200b Edge",
     "", "file=vgg - july health bill.pdf"),

    # ---- Known work hosts ----
    ("Onvio and 3 more pages - Work - Microsoft\u200b Edge", "", "web:onvio"),
    ("Onvio - Work - Microsoft\u200b Edge", "", "web:onvio"),
    ("Site Index Search | Internal Revenue Service and 1 more page - Work - Microsoft\u200b Edge",
     "https://www.irs.gov/site-index-search", "web:irs.gov/"),
    ("Simplify Your Davis-Bacon Certified Payroll Reporting | U.S. Department of Labor and 1 more page - Work - Microsoft\u200b Edge",
     "https://www.dol.gov/agencies/whd/forms/wh347-web", "web:dol.gov/"),
    ("Statements and Notices | M&T Bank and 1 more page - Work - Microsoft\u200b Edge",
     "https://onlinebanking.mtb.com/Statements/Statement", "web:onlinebanking.mtb.com/"),

    # ---- PERSONAL: must produce NO work identity ('') so downstream tags personal ----
    ("MSN | Personalized News, Top Headlines, Live Updates and more - Work - Microsoft\u200b Edge", "", ""),
    ("Fox News apologizes after Kevin O\u2019Leary\u2019s claims about data center - Work - Microsoft\u200b Edge", "", ""),
    ("Trump throws absolute fit at Maggie Haberman, then misspells his own insults and 1 more page - Work - Microsoft\u200b Edge", "", ""),
    ("7 rumors about Trump falling asleep, examined - Work - Microsoft\u200b Edge", "", ""),
    ("Breitbart News Network and 3 more pages - Work - Microsoft\u200b Edge", "https://www.breitbart.com", ""),
    ("Applebee's\u00ae Menu - Pasta and 3 more pages - Work - Microsoft\u200b Edge",
     "https://www.applebees.com/en/menu/pasta", ""),
    ("Monkey GO Happy NEW Stages - 0407- Play Free Educational Kids Online Games",
     "https://monkeyhappy.com/0407.html", ""),
    ("Without Trying - song and lyrics by Forrest Rose | Spotify",
     "https://open.spotify.com/track/6SZNGiE3qIcl0qvbexV", ""),
    ("Escape Rooms in Syracuse NY | All In Adventures and 5 more pages - Work - Microsoft\u200b Edge", "", ""),
    ("New tab - Work - Microsoft\u200b Edge", "", ""),
    ("New tab and 2 more pages - Work - Microsoft\u200b Edge", "", ""),
    ("Google - Work - Microsoft\u200b Edge", "", ""),

    # ---- TRICKY: billable research via search engine — currently '' (downstream
    #      must treat irs/dol/ssa SEARCHES as work via content_classifier, NOT here).
    #      These are here to DOCUMENT the boundary, expected '' at identity layer. ----
    ("in ultra tax how do i reprot a large dump truck - Search - Work - Microsoft\u200b Edge",
     "https://www.bing.com/search", ""),
    ("does contributing to IRA lower taxable income - Search - Work - Microsoft\u200b Edge",
     "https://www.bing.com/search", ""),
]


def run():
    passed = failed = 0
    fails = []
    for title, url, expected in CASES:
        got = ci(title, url)
        if expected == "":
            ok = (got == "")
        elif expected.endswith("=") or expected.endswith("/"):  # prefix-only check
            ok = got.startswith(expected)
        else:
            ok = (got == expected)
        if ok:
            passed += 1
        else:
            failed += 1
            fails.append((title[:60], url[:40], expected, got))

    print(f"\n{'='*70}")
    print(f"RESULT: {passed} passed, {failed} failed  (of {len(CASES)})")
    print('='*70)
    if fails:
        print("\nFAILURES (expected -> got):")
        for t, u, exp, got in fails:
            print(f"  title : {t!r}")
            print(f"  url   : {u!r}")
            print(f"  expect: {exp!r}")
            print(f"  got   : {got!r}\n")
    else:
        print("\nAll cases pass. Work identities extracted, personal left blank.")
    return failed == 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)
