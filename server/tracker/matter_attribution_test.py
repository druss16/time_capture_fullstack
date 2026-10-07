"""
Tests for matter attribution — deciding which matter captured work belongs to.

This is billing-critical in a way client attribution is not. Sending an hour to
the wrong matter bills the wrong client, and in a regulated profession that is
worse than an accounting mis-post. Every case below is really asking the same
question: does this abstain when it should?

The specific hazards, all learned the hard way on the client side:
  - a token shared by two matters must identify NEITHER (Sacred Heart)
  - a short or year-like number must never match on its own ("Smith 2024.pdf"
    is a tax year, not matter 2024)
  - text naming two matters is evidence of neither

Needs Django importable; if unavailable, cases are SKIPPED.

    python manage.py shell -c "import tracker.matter_attribution_test"
"""
import os
import sys

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


try:
    from tracker.services.matter_attribution import (
        candidate_tokens, build_matter_index, match_matter_in_text, attribute_block,
        folder_key, neighbour_matter,
        name_phrase, name_words, build_name_index, match_project_name,
        match_project_name_partial, named_part_of_path,
    )
    from tracker.services.projects import ProjectOption
    from datetime import datetime, timedelta
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("Matter attribution:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


class _M:
    def __init__(self, project_id, display_number, status='open'):
        self.project_id = project_id
        self.display_number = display_number
        self.external_status = status


class _B:
    def __init__(self, file_path='', title='', window_title='', url='',
                 client_id=None, hints=None):
        self.file_path, self.title = file_path, title
        self.window_title, self.url, self.client_id = window_title, url, client_id
        self.hints = hints or {}
        # The Clio anchor only speaks for browser activity (is_browser_block);
        # these fixtures model a Clio tab, so they are browser blocks.
        self.app_name = 'Google Chrome'
        self.start = self.end = None


if _ok:
    print("Matter attribution — tokens drawn from a Clio matter number:")
    t = candidate_tokens('00123-Smith')
    check("leading number is usable alone", '00123' in t)
    check("full number kept as a phrase", '00123 smith' in t)
    check("bare year rejected — 'Smith 2024.pdf' is a tax year",
          candidate_tokens('2024-Smith') == {'2024 smith'})
    check("short number rejected on its own",
          all(len(x) >= 4 or ' ' in x for x in candidate_tokens('12-Smith')))
    check("empty number yields nothing", candidate_tokens('') == set())

    print("Matter attribution — a token two matters share identifies neither:")
    idx = build_matter_index([_M(1, '00123-Smith'), _M(2, '00123-Jones')])
    check("shared leading number dropped", '00123' not in idx)
    check("but each full number survives", '00123 smith' in idx and '00123 jones' in idx)

    idx2 = build_matter_index([_M(1, '00123-Smith'), _M(2, '00456-Jones')])
    check("distinct numbers both usable", idx2.get('00123') == {1} and idx2.get('00456') == {2})

    print("Matter attribution — matching real filenames:")
    check("matches a matter number in a filename",
          match_matter_in_text(r'S:\Clients\Smith\00123 Estate\motion.docx', idx2) == 1)
    check("matches inside a Word window title",
          match_matter_in_text('00456 Jones - Response.docx - Word', idx2) == 2)
    check("no number, no match",
          match_matter_in_text('random notes.docx', idx2) is None)
    check("ABSTAINS when two matters are named",
          match_matter_in_text('00123 and 00456 comparison.xlsx', idx2) is None)
    check("does not match a number embedded in a longer one",
          match_matter_in_text('invoice 004561234.pdf', idx2) is None)
    check("empty text is safe", match_matter_in_text('', idx2) is None)
    check("empty index is safe", match_matter_in_text('00123 Estate.docx', {}) is None)

    print("Matter attribution — a year in a filename must not win:")
    year_idx = build_matter_index([_M(9, '2024-Smith')])
    check("'Smith 2024 return.pdf' does not match matter 2024-Smith",
          match_matter_in_text('Smith 2024 return.pdf', year_idx) is None)
    check("but the full number still matches",
          match_matter_in_text('2024-Smith engagement.docx', year_idx) == 9)

    print("Matter attribution — tier order and the sole-matter fallback:")
    sole = {77: 5}
    check("explicit number beats the sole-matter inference",
          attribute_block(_B(file_path='00123 Estate.docx', client_id=77), idx2, sole)[:2] == (1, 'number'))
    check("falls back to the client's only matter",
          attribute_block(_B(title='notes.docx', client_id=77), idx2, sole)[:2] == (5, 'sole_matter'))
    check("client with several matters abstains",
          attribute_block(_B(title='notes.docx', client_id=88), idx2, sole)[0] is None)
    check("no client and no number abstains",
          attribute_block(_B(title='notes.docx'), idx2, sole)[0] is None)
    check("url is searched too",
          attribute_block(_B(url='https://portal/00456/doc', client_id=None), idx2, sole)[:2] == (2, 'number'))

    print("Matter attribution — the Clio anchor outranks every heuristic:")
    anchors = {'1925394507': 63, '1925394508': 64}
    check("anchor alone attributes",
          attribute_block(_B(hints={'clio_matter_id': '1925394507'}), idx2, sole, anchors)[:2]
          == (63, 'clio_anchor'))
    check("anchor BEATS a conflicting matter number in the filename",
          attribute_block(_B(file_path='00123 Estate.docx',
                             hints={'clio_matter_id': '1925394508'}), idx2, sole, anchors)[0] == 64)
    check("anchor beats the sole-matter inference",
          attribute_block(_B(title='notes.docx', client_id=77,
                             hints={'clio_matter_id': '1925394507'}), idx2, sole, anchors)[0] == 63)
    check("unknown matter id falls through, never invents a project",
          attribute_block(_B(file_path='00123 Estate.docx',
                             hints={'clio_matter_id': '999999'}), idx2, sole, anchors)[:2]
          == (1, 'number'))
    check("no anchor map (org never synced Clio) is safe",
          attribute_block(_B(hints={'clio_matter_id': '1925394507'}), idx2, sole, None)[0] is None)
    check("blank hints are safe", attribute_block(_B(hints={}), idx2, sole, anchors)[0] is None)
    check("numeric-typed id still matches its string key",
          attribute_block(_B(hints={'clio_matter_id': 1925394507}), idx2, sole, anchors)[0] == 63)

    print("Matter attribution — folders are the unit that repeats:")
    check("windows path -> folder",
          folder_key(r'S:\Clients\Ridgeline\Estate Planning\motion.docx')
          == folder_key('S:/Clients/Ridgeline/Estate Planning/x.docx'))
    check("filename is excluded from the key",
          'motion' not in folder_key(r'S:\Clients\Ridgeline\Estate\motion.docx'))
    check("bare filename has no folder", folder_key('motion.docx') == '')
    check("empty path is safe", folder_key('') == '')

    # Compaction keys a project firm's document blocks on folder_key, so it must
    # split exactly where a project can change — and nowhere else.
    fall = folder_key('/Users/danrussell/Desktop/Adidas/Fall Launch/Adidas_test.psd')
    winter = folder_key('/Users/danrussell/Desktop/Adidas/Winter Sprint/Adidas_test_deux.psd')
    check("two project folders of one client are two keys (Dan's Adidas test)",
          fall and winter and fall != winter)
    check("two files in one project folder share a key",
          fall == folder_key('/Users/danrussell/Desktop/Adidas/Fall Launch/other.ai'))
    mtc_root = '/Users/a/Library/CloudStorage/Dropbox-MoreThanCars/Team/Client-Work_2026/0074_Easterns-Auto-Group'
    deliv = f'{mtc_root}/0074_2026-08_Easterns-Auto_Konetiq-Launch-Ads'
    check("MTC: a deliverable's Exports/ stays in the deliverable's key",
          folder_key(f'{deliv}/hero.psd') == folder_key(f'{deliv}/Exports/banner.png'))
    check("MTC: two deliverables of one client are two keys",
          folder_key(f'{deliv}/hero.psd')
          != folder_key(f'{mtc_root}/0074_2026-09_Easterns-Auto_Collision-Flyer/a.psd'))
    check("MTC: the same deliverable on two machines is one key",
          folder_key(f'{deliv}/hero.psd') == folder_key(
              'C:/Users/bob/Dropbox (More Than Cars)/Team/Client-Work_2026/0074_Easterns-Auto-Group/'
              '0074_2026-08_Easterns-Auto_Konetiq-Launch-Ads/hero.psd'))

    folders = {folder_key('S:/Clients/Ridgeline/Estate Planning/a.docx'): 64}
    check("a learned folder attributes a new file in it",
          attribute_block(_B(file_path='S:/Clients/Ridgeline/Estate Planning/brand-new.docx'),
                          idx2, sole, None, folder_index=folders)[:2] == (64, 'folder'))
    check("learned folder beats a matter number in the filename",
          attribute_block(_B(file_path='S:/Clients/Ridgeline/Estate Planning/00123 x.docx'),
                          idx2, sole, None, folder_index=folders)[0] == 64)
    check("the Clio anchor still outranks a learned folder",
          attribute_block(_B(file_path='S:/Clients/Ridgeline/Estate Planning/a.docx',
                             hints={'clio_matter_id': '1925394507'}),
                          idx2, sole, {'1925394507': 63}, folder_index=folders)[0] == 63)

    print("Matter attribution — temporal propagation needs both sides to agree:")
    base = datetime(2026, 8, 20, 10, 0)

    def blk(start_min, end_min):
        b = _B(title='untitled.docx')
        b.start = base + timedelta(minutes=start_min)
        b.end = base + timedelta(minutes=end_min)
        return b

    both_agree = [(base, base + timedelta(minutes=10), 64),
                  (base + timedelta(minutes=60), base + timedelta(minutes=70), 64)]
    check("both neighbours agree -> propagate",
          neighbour_matter(blk(20, 50), both_agree) == 64)

    disagree = [(base, base + timedelta(minutes=10), 64),
                (base + timedelta(minutes=60), base + timedelta(minutes=70), 65)]
    check("neighbours DISAGREE -> abstain", neighbour_matter(blk(20, 50), disagree) is None)

    one_side = [(base, base + timedelta(minutes=10), 64)]
    check("one-sided evidence -> abstain (this is the matter-switch case)",
          neighbour_matter(blk(20, 50), one_side) is None)

    far = [(base, base + timedelta(minutes=10), 64),
           (base + timedelta(minutes=600), base + timedelta(minutes=610), 64)]
    check("agreeing but hours away -> abstain", neighbour_matter(blk(20, 50), far) is None)

    check("temporal is off unless the org opted in",
          attribute_block(blk(20, 50), idx2, sole, None,
                          neighbours=both_agree, allow_temporal=False)[0] is None)
    check("temporal fires when opted in",
          attribute_block(blk(20, 50), idx2, sole, None,
                          neighbours=both_agree, allow_temporal=True)[:2] == (64, 'temporal'))
    check("temporal sits BELOW the sole-matter inference",
          attribute_block(_B(title='x.docx', client_id=77), idx2, sole, None,
                          neighbours=both_agree, allow_temporal=True)[:2] == (5, 'sole_matter'))

if _ok:
    print("Agency projects — a name is evidence only among the block's own client's projects:")
    check("client words stripped from the project name",
          name_phrase('Ford - Spring Launch', 'Ford') == 'spring launch')
    check("a name that is only the client's words identifies nothing",
          name_phrase('Ford', 'Ford') == '')
    check("too-short remainder rejected", name_phrase('Ford SEO', 'Ford') == '')
    check("bare year rejected", name_phrase('2026', 'Ford') == '')

    def _opt(pid, cid, name, mapped=False, number=''):
        return ProjectOption(project_id=pid, client_id=cid, name=name, mapped=mapped,
                             display_number=number)

    opts = {
        10: [_opt(101, 10, 'Ford - Spring Launch'), _opt(102, 10, 'Social'),
             _opt(103, 10, 'Social Ads'), _opt(104, 10, '00999-Mirrored', mapped=True, number='00999'),
             _opt(105, 10, 'Dealer Event', mapped=True)],
        20: [_opt(201, 20, 'Spring Launch')],
    }
    nidx = build_name_index(opts, {10: 'Ford', 20: 'Chevy'})
    check("numbered matters are not name-indexed (they match by number)",
          all(pid != 104 for pid in nidx[10].values()))
    check("a mirror known only by name (QuickBooks Time) IS name-indexed",
          nidx[10].get('dealer event') == 105)
    check("same name at two clients stays per-client",
          nidx[10]['spring launch'] == 101 and nidx[20]['spring launch'] == 201)
    check("file named for the project matches",
          match_project_name('Dropbox/Ford/Spring Launch storyboard v3.psd', nidx[10]) == 101)
    check("partial word does not match ('springfield launcher')",
          match_project_name('springfield launcher.ai', nidx[10]) is None)
    check("longer name wins when one contains the other",
          match_project_name('Social Ads - October report', nidx[10]) == 103)
    check("two unrelated project names -> abstain",
          match_project_name('Spring Launch vs Social recap', nidx[10]) is None)

    check("name tier fires for the block's client",
          attribute_block(_B(file_path='/Ford/Spring Launch/brief.docx', client_id=10),
                          {}, {}, None, name_index=nidx)[:2] == (101, 'name'))
    check("name tier ignores another client's project with the same name",
          attribute_block(_B(title='Spring Launch brief', client_id=30),
                          {}, {}, None, name_index=nidx)[0] is None)
    check("name beats the sole-project inference",
          attribute_block(_B(title='Spring Launch', client_id=20), {}, {20: 999}, None,
                          name_index=nidx)[:2] == (201, 'name'))

    print("Project names however the firm spells them:")
    for label, text in (
        ("CamelCase", 'Dropbox/Ford/SpringLaunch_storyboard_v3.psd'),
        ("underscores", '/x/2026_Spring_Launch/hero.psd'),
        ("hyphens and caps", '/x/FORD-SPRING-LAUNCH-hero.ai'),
        ("run together, all caps", '/x/SPRINGLAUNCH/hero.psd'),
        ("words in another order", '/x/Launch - Spring/hero.psd'),
        ("words in different folders", '/x/Spring/Launch Assets/hero.psd'),
        ("version and year noise", '/x/v3_SpringLaunch_2026_final.psd'),
    ):
        check(f"{label}: {text}", match_project_name(text, nidx[10]) == 101)
    check("plural folder, singular project",
          match_project_name('/x/Dealer_Events/a.psd', nidx[10]) == 105)
    check("still whole words: 'springfield launcher' is not 'spring launch'",
          match_project_name('/x/SpringfieldLauncher/a.psd', nidx[10]) is None)
    check("a one-word name never matches out of order pieces",
          match_project_name('/x/so cial.psd', {'social': 1}) is None)

    print("Most of a project name (name_partial):")
    mtc_opts = {7: [_opt(71, 7, 'Easterns KONETIQ Campaigns', mapped=True),
                    _opt(72, 7, 'Konetiq Launch Ads', mapped=True),
                    _opt(73, 7, 'Monthly New Car Specials', mapped=True)]}
    midx = build_name_index(mtc_opts, {7: 'Easterns Automotive Group'})
    check("client words stripped, CamelCase split",
          midx[7].get('konetiq campaigns') == 71)
    check("two of three words incl. a distinctive one",
          match_project_name_partial('0074_2026-09_Easterns-Auto_Konetiq-Launch_Sept/hero.psd',
                                     midx[7]) == 72)
    check("only the shared word ('konetiq') -> abstain",
          match_project_name_partial('0074_Konetiq_Sept/hero.psd', midx[7]) is None)
    check("one word of a long name is not 'most of it'",
          match_project_name_partial('0074_Specials_Recap/x.psd', midx[7]) is None)
    check("abbreviated decorated name",
          match_project_name_partial('/x/New-Car-Special_OCT/x.psd', midx[7]) == 73)
    check("exact tier still wins first",
          attribute_block(_B(file_path='/d/0074_Konetiq-Launch-Ads/c.psd', client_id=7),
                          {}, {}, None, name_index=midx)[:2] == (72, 'name'))
    check("partial tier fires below the exact one",
          attribute_block(_B(file_path='/d/0074_Konetiq-Launch_Sept/c.psd', client_id=7),
                          {}, {}, None, name_index=midx)[:2] == (72, 'name_partial'))
    check("partial abstains, sole-project is not consulted for a multi-project client",
          attribute_block(_B(file_path='/d/0074_Konetiq_Sept/c.psd', client_id=7),
                          {}, {}, None, name_index=midx)[0] is None)

    print("Q1 2026 Production vs. a Google Doc's URL (Tom Gill, 2026-10-07):")
    tg = {9: [_opt(91, 9, 'Tom Gill Buick/GMC Q1 2026 Production', mapped=True),
              _opt(92, 9, 'TGBGMC Website Reskin', mapped=True),
              _opt(93, 9, 'TGBGMC Monthly Donut Videos', mapped=True)]}
    tidx = build_name_index(tg, {9: 'Tom Gill Buick GMC'})
    check("'Q1' stays one word", name_words('Q1 2026 Production') == ['q1', 'production'])
    check("words after two letters still split", name_words('Month2026') == ['month'])
    check("client abbreviation stripped from the project name",
          tidx[9].get('website reskin') == 92 and tidx[9].get('monthly donut videos') == 93)
    check("Q1 project keyed on 'q1 production'", tidx[9].get('q1 production') == 91)
    doc = _B(title='Chrome', window_title='Tom Gill October Offers for Creative - Google Docs',
             url='https://docs.google.com/document/d/1xQ7bW9q_1Tz3kLm0Pq1aR/edit?tab=t.0',
             client_id=9)
    check("a doc's URL ID does not half-name Q1 Production",
          attribute_block(doc, {}, {}, None, name_index=tidx)[0] is None)
    check("fragments never count toward a partial",
          match_project_name_partial('q 1 x', {'q1 production': 91, 'q 1 production': 91}) is None)
    check("a title that says Q1 Production still matches",
          attribute_block(_B(window_title='Tom Gill Q1 Production shot list - Google Docs', client_id=9),
                          {}, {}, None, name_index=tidx)[:2] == (91, 'name'))
    check("a title that says Website Reskin matches in full now",
          attribute_block(_B(window_title='Tom Gill Website Reskin wireframes', client_id=9),
                          {}, {}, None, name_index=tidx)[:2] == (92, 'name'))

    print("The sync root's words never count toward a name:")
    check("Dropbox (More Than Cars) does not half-name 'New Car Specials'",
          match_project_name_partial(
              named_part_of_path('/Users/a/Dropbox (More Than Cars)/0074_New_Hire/x.psd'),
              midx[7]) is None)
    check("Mac CloudStorage root dropped too",
          named_part_of_path('/Users/a/Library/CloudStorage/Dropbox-MoreThanCars/A/b.psd') == 'A/b.psd')
    check("Windows home + Dropbox root dropped, file name kept",
          named_part_of_path('C:\\Users\\bob\\Dropbox (MTC)\\A\\b.psd') == 'A/b.psd')
    check("no sync root: home dropped only",
          named_part_of_path('/Users/dan/Desktop/Adidas/Fall Launch/a.psd')
          == 'Desktop/Adidas/Fall Launch/a.psd')
    check("Dan's Adidas test: Fall Launch from the folder",
          match_project_name(named_part_of_path('/Users/danrussell/Desktop/Adidas/Fall Launch/Adidas_test.psd'),
                             build_name_index({5: [_opt(51, 5, 'Fall Launch', mapped=True),
                                                   _opt(52, 5, 'Holiday Promo', mapped=True)]},
                                              {5: 'Adidas'})[5]) == 51)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
