"""
Attribute captured work to a matter.

WHY THIS EXISTS
---------------
The classifier resolves a Block to a CLIENT. Legal billing needs a MATTER:
Clio rejects a TimeEntry without one, so client-level attribution cannot push
legal time at all. Before this, 0 of 37,021 blocks had `project` set.

NO VERTICAL BRANCH
------------------
There is deliberately no `if industry == 'legal'` here. This resolver keys off
DATA PRESENCE — an org with ExternalMatterMapping rows gets matter attribution,
an org without them no-ops. A CPA firm simply has no mappings, so nothing runs.
Behaviour follows the data, configuration follows the vertical, and the two
never have to know about each other.

Agencies work the same shape — Client → Project — but keep projects in
TimeTracker rather than a synced system. `services/projects.py` decides which
projects are live (mirrored matters, plus local projects for the verticals
configured to keep them), and everything below works off that one answer. Local
projects have no number, so they add a NAME tier, scoped to the block's client.

TIERS
-----
2. Matter number in the file path, title, or URL. Clio's `display_number`
   ("00123-Smith") is a structured, distinctive token — unlike fuzzy client
   names, which is why this is *more* reliable than client matching, not less.
   Law firms name files by matter relentlessly; iManage, NetDocuments and
   Worldox are all built around it.
3. The client resolves to exactly one open matter. Cheap, and at a small firm
   it covers a lot.

(Tier 1 — reading the matter id straight out of a Clio URL — needs the browser
extension to stop stripping the hash fragment, so it ships separately.)

ABSTAIN WHEN AMBIGUOUS
----------------------
Every tier returns nothing rather than guessing when more than one matter fits.
Mis-attributing a matter does not mislabel a block, it bills the wrong client —
worse in legal than an accounting mis-post. The same discipline that the ATU
alias incident and the Sacred Heart collisions taught: a proposal a human
confirms beats a confident wrong answer.
"""

from celery import shared_task
import logging
import re
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

# Matter numbers shorter than this are too collision-prone to trust in free text.
MIN_NUMBER_TOKEN = 4

# Bare four-digit numbers in this range are almost always years in a filename
# ("Smith 2024 return.pdf"), not matter numbers.
_YEAR_LIKE = re.compile(r'^(19|20)\d{2}$')

_SEPARATORS = re.compile(r'[^a-z0-9]+')

# Matter statuses that can still receive time.
OPEN_STATUSES = {'open', 'pending', ''}


def _normalize(text: str) -> str:
    return _SEPARATORS.sub(' ', (text or '').lower()).strip()


def _tokens(text: str) -> set:
    return {t for t in _normalize(text).split() if t}


def candidate_tokens(display_number: str) -> set:
    """
    Tokens that identify a matter in free text.

    Clio numbers look like "00001-Ridgeline Holdings LLC" — the number AND the
    client name. A filename says "00123 Smith MSJ.docx", so the leading
    identifier has to be usable on its own.

    Rejected as too risky on their own:
      - anything shorter than MIN_NUMBER_TOKEN
      - bare years, which appear in filenames constantly
    """
    out = set()
    normalized = _normalize(display_number)
    if not normalized:
        return out

    parts = normalized.split()
    if not parts:
        return out

    lead = parts[0]
    if len(lead) >= MIN_NUMBER_TOKEN and not _YEAR_LIKE.match(lead):
        out.add(lead)

    # The full number as a contiguous phrase is always safe — it is far too
    # specific to collide.
    if len(parts) > 1:
        out.add(' '.join(parts))

    return out


def build_matter_index(mappings):
    """
    token -> set(project_id). A token claimed by more than one matter is
    dropped: it cannot identify anything, and keeping it would let the most
    recently seen matter win by accident.
    """
    index = defaultdict(set)
    for m in mappings:
        for token in candidate_tokens(m.display_number or ''):
            index[token].add(m.project_id)

    return {token: pids for token, pids in index.items() if len(pids) == 1}


def match_matter_in_text(text: str, index: dict):
    """
    Project id named by `text`, or None.

    Returns None when the text names two different matters — a document that
    mentions both is evidence of neither.
    """
    if not text or not index:
        return None

    normalized = _normalize(text)
    words = set(normalized.split())

    hits = set()
    for token, pids in index.items():
        if ' ' in token:
            if token in normalized:
                hits |= pids
        elif token in words:
            hits |= pids

    if len(hits) == 1:
        return next(iter(hits))
    return None


# A project name shorter than this, once the client's own words are stripped
# out of it, is too generic to read out of free text ("Ads", "SEO" alone).
MIN_NAME_PHRASE = 4


def name_phrase(project_name: str, client_name: str = '') -> str:
    """
    The part of a project's name that identifies it among its client's projects.

    Agencies name projects like "Ford - Spring Launch" or just "Spring Launch".
    The client's words are already settled by the time this runs (the block
    has a client), so they are stripped: "ford spring launch" would otherwise
    never match a file called "Spring Launch storyboard.psd".
    """
    client_words = _tokens(client_name)
    words = [w for w in _normalize(project_name).split() if w not in client_words]
    phrase = ' '.join(words)
    return phrase if len(phrase) >= MIN_NAME_PHRASE and not _YEAR_LIKE.match(phrase) else ''


def build_name_index(options_by_client, client_names) -> dict:
    """
    client_id -> {phrase: project_id} for projects known by NAME — kept in
    TimeTracker, or mirrored from a source that has no numbers (QuickBooks Time).

    Scoped per client on purpose: "Website Refresh" is a project at half the
    agency's clients, and a name is only evidence among the projects of the
    client the block already belongs to. A phrase two of one client's projects
    share identifies neither and is dropped.
    """
    out = {}
    for client_id, options in options_by_client.items():
        seen = defaultdict(set)
        for o in options:
            # Numbered matters (Clio) are matched by number, above. Projects
            # mirrored by name (QuickBooks Time) are matched here like local ones.
            if o.mapped and o.display_number:
                continue
            phrase = name_phrase(o.name, client_names.get(client_id, ''))
            if phrase:
                seen[phrase].add(o.project_id)
        phrases = {ph: next(iter(p)) for ph, p in seen.items() if len(p) == 1}
        if phrases:
            out[client_id] = phrases
    return out


def match_project_name(text: str, phrases: dict):
    """
    Project id whose name appears in `text`, or None.

    Whole words only. When one hit is contained in another ("social" inside
    "social ads") the longer, more specific name wins; any other disagreement
    abstains.
    """
    if not text or not phrases:
        return None
    padded = f' {_normalize(text)} '
    hits = [ph for ph in phrases if f' {ph} ' in padded]
    hits = [h for h in hits if not any(h != o and f' {h} ' in f' {o} ' for o in hits)]
    pids = {phrases[h] for h in hits}
    return next(iter(pids)) if len(pids) == 1 else None


def folder_key(file_path: str) -> str:
    """
    The containing folder of a file, normalized.

    Law firms file by matter — S:\\Clients\\Ridgeline\\Estate Planning\\motion.docx —
    so the folder is the unit that repeats across a matter's documents, while
    the filename changes every time.
    """
    if not file_path:
        return ''
    normalized = str(file_path).replace('\\', '/').rstrip('/')
    if '/' not in normalized:
        return ''
    return _normalize(normalized.rsplit('/', 1)[0])


def build_folder_index(org, since, exclude_block_ids=None) -> dict:
    """
    folder -> project_id, learned from blocks already attributed.

    This is the memory: once a folder resolves to a matter by ANY route —
    the Clio anchor, a matter number, or a person correcting it by hand — every
    later document in that folder follows without inference. Human corrections
    teach it for free, which is why the Timesheet picker is worth more than it
    looks.

    A folder that has pointed at two different matters is dropped. Shared
    folders exist ("Correspondence", "Admin") and guessing between them would
    bill the wrong client.
    """
    from tracker.models import Block

    qs = (
        Block.objects
        .filter(org=org, project__isnull=False, start__gte=since)
        .exclude(file_path='')
        .only('id', 'file_path', 'project_id')
        .order_by('pk')          # keyset paging pages by pk; be explicit
    )
    if exclude_block_ids:
        qs = qs.exclude(id__in=exclude_block_ids)

    # keyset_iter, not .iterator(): server-side cursors do not survive the Neon
    # connection pooler, and this failed with InvalidCursorName on every run.
    # The failure was invisible — full_sync catches attribution errors so a
    # problem here cannot break a sync that worked — so matter attribution
    # silently did nothing at all rather than reporting a fault.
    from tracker.utils.db_iter import keyset_iter

    seen = defaultdict(set)
    for b in keyset_iter(qs, chunk_size=2000):
        key = folder_key(b.file_path)
        if key:
            seen[key].add(b.project_id)

    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def neighbour_matter(block, neighbours_by_user, window_minutes=90):
    """
    The matter both temporal neighbours agree on, or None.

    A lawyer opens a matter in Clio, works in Word for forty minutes, then goes
    back to Clio. That Word time belongs to the matter either side of it — the
    filename never says so. This is the existing Stage Sandwich shape applied to
    matters instead of clients.

    Requires BOTH sides, agreeing, inside the window. One-sided evidence is how
    the block after a lawyer switches matters gets billed to the previous one.
    """
    prior = nxt = None
    for other_start, other_end, project_id in neighbours_by_user:
        if project_id is None:
            continue
        if other_end <= block.start:
            gap = (block.start - other_end).total_seconds() / 60.0
            if gap <= window_minutes and (prior is None or other_end > prior[0]):
                prior = (other_end, project_id)
        elif other_start >= block.end:
            gap = (other_start - block.end).total_seconds() / 60.0
            if gap <= window_minutes and (nxt is None or other_start < nxt[0]):
                nxt = (other_start, project_id)

    if prior and nxt and prior[1] == nxt[1]:
        return prior[1]
    return None


def attribute_block(block, index, sole_matter_by_client, project_by_external_id=None,
                    folder_index=None, neighbours=None, allow_temporal=False,
                    name_index=None):
    """
    (project_id, tier, reason) for one block, or (None, None, reason).

    Tier order is confidence order:

      0. clio_anchor  — Clio had this matter open. Knowledge, not inference.
      1. folder       — this folder has resolved to exactly one matter before,
                        by any route, including a human correcting it.
      2. number       — a matter number appears in the path, title or URL.
      2b. name        — a project kept in TimeTracker is named in the path,
                        title or URL, among the block's OWN client's projects.
      3. sole_matter  — the client has exactly one open matter. Deterministic:
                        there is nothing here to be wrong about.
      4. temporal     — both neighbours agree. Weakest, because it infers from
                        context rather than content, so it sits last and is
                        opt-in per org.

    An explicit signal outranks an inference, and an inference that cannot be
    wrong outranks one that can.
    """
    anchor = (getattr(block, 'hints', None) or {}).get('clio_matter_id')
    if anchor and project_by_external_id and is_browser_block(block):
        project_id = project_by_external_id.get(str(anchor).strip())
        if project_id:
            return project_id, 'clio_anchor', 'Clio had this matter open'

    if folder_index:
        learned = folder_index.get(folder_key(getattr(block, 'file_path', '') or ''))
        if learned:
            return learned, 'folder', 'this folder has always been this matter'

    for field in ('file_path', 'title', 'window_title', 'url'):
        matched = match_matter_in_text(getattr(block, field, '') or '', index)
        if matched:
            return matched, 'number', f'matter number found in {field}'

    if name_index and block.client_id in name_index:
        phrases = name_index[block.client_id]
        for field in ('file_path', 'window_title', 'title', 'url'):
            matched = match_project_name(getattr(block, field, '') or '', phrases)
            if matched:
                return matched, 'name', f'project name found in {field}'

    if block.client_id:
        sole = sole_matter_by_client.get(block.client_id)
        if sole:
            return sole, 'sole_matter', 'client has exactly one open matter'

    if allow_temporal and neighbours:
        agreed = neighbour_matter(block, neighbours)
        if agreed:
            return agreed, 'temporal', 'bracketed by work on the same matter'

    return None, None, 'no matter identified'


# Apps whose activity the Clio anchor is allowed to speak for.
#
# THE BUG THIS EXISTS TO STOP. The browser extension context rides along on
# events even when the foreground app is NOT the browser — the agent forwards
# the last reported tab — so a block spent in Claude or Terminal carries the
# clio_matter_id of whatever Clio tab was open earlier. The anchor then fired
# on it and claimed the matter.
#
# That was always wrong, but it used to cost only a stray project on an
# unrelated block. Once the anchor began setting the CLIENT too, the same
# stale hint started BILLING unrelated work to a law firm client: 18 blocks
# of "Claude" and "Terminal — python manage.py runserver" booked to Ridgeline
# Holdings, over the top of a classifier that had correctly called them
# no-client and non-billable.
#
# tab_focused_at freshness is not sufficient and never was. It answers "was
# that tab focused recently", not "is the user in the browser NOW" — and
# alt-tabbing to another app leaves the tab timestamp perfectly fresh.
BROWSER_APPS = ('chrome', 'edge', 'firefox', 'safari', 'brave', 'arc',
                'opera', 'vivaldi')


def is_browser_block(block) -> bool:
    """True when this block activity actually happened in a browser."""
    app = (getattr(block, 'app_name', '') or '').lower()
    return any(name in app for name in BROWSER_APPS)


# categorized_by values that mean A PERSON chose the client. A clio_anchor hit
# may correct a machine guess; it may never overrule somebody's decision.
HUMAN_SET_CLIENT = ('manual', 'correction')


def may_correct_client(categorized_by) -> bool:
    """
    True when a tier-0 anchor is allowed to rewrite this block's client.

    Named and separate so the rule can be read and tested on its own. It is
    one line, and it is the line that decides whether the system is permitted
    to overrule a person — which is the sort of thing that should not be an
    inline condition inside a loop.

    Everything that is not an explicit human choice is a machine guess, and an
    anchor is a better machine answer than the guess it replaces. Unknown or
    future values therefore default to correctable; a new automated source
    should not silently become immune to correction by virtue of being new.
    """
    return (categorized_by or '') not in HUMAN_SET_CLIENT


def _build_convention_index(org, options_by_client):
    """The naming-convention lookup for this firm (clients, codes, live projects)."""
    from tracker.models import Client
    from tracker.models_task_type_sets import ExternalClientMapping
    from tracker.services.naming_convention import build_index
    clients = Client.objects.filter(org=org, is_active=True).values_list('id', 'name', 'code', 'aliases')
    extra = (ExternalClientMapping.objects
             .filter(integration__organization=org).exclude(external_code='')
             .values_list('client_id', 'external_code'))
    projects = [(o.project_id, o.client_id, o.name)
                for opts in options_by_client.values() for o in opts]
    return build_index(clients, extra, projects)


def attribute_matters_for_org(org, *, days=30, dry_run=False, limit=None) -> dict:
    """
    Fill Block.project for recent blocks that have none.

    No-ops for a firm with no live projects: one that neither syncs a practice
    management system nor keeps its own projects (services/projects.py).
    """
    from tracker.models import Block, Client
    from tracker.models_task_type_sets import ExternalMatterMapping
    from tracker.services.projects import selectable_projects

    mappings = list(
        ExternalMatterMapping.objects
        .filter(integration__organization=org)
        .select_related('project')
    )
    options_by_client = selectable_projects(org)
    stats = {
        'org_id': org.id, 'matters': len(mappings),
        'projects': sum(len(v) for v in options_by_client.values()),
        'scanned': 0,
        'by_clio_anchor': 0, 'by_folder': 0, 'by_number': 0, 'by_name': 0,
        'by_sole_matter': 0, 'by_temporal': 0,
        'unmatched': 0, 'off_client': 0, 'client_corrected': 0, 'dry_run': dry_run,
    }
    if not mappings and not options_by_client:
        return stats

    index = build_matter_index(mappings)
    project_by_external_id = {str(m.external_id): m.project_id for m in mappings}
    client_by_project_id = {m.project_id: m.project.client_id for m in mappings}
    live_project_client = {
        o.project_id: o.client_id
        for opts in options_by_client.values() for o in opts
    }
    client_by_project_id.update(live_project_client)
    client_names = dict(
        Client.objects.filter(id__in=list(options_by_client)).values_list('id', 'name')
    )
    name_index = build_name_index(options_by_client, client_names)

    since = timezone.now() - timedelta(days=days)

    # Learned folders reach further back than the blocks being attributed: a
    # folder settled months ago should still teach today's work.
    folder_index = build_folder_index(org, timezone.now() - timedelta(days=max(days, 180)))

    # Temporal inference is opt-in per org, reusing the flag that already gates
    # Stage Sandwich for clients — the same trade, and the same firms who want it.
    # Firms that keep their own projects get it regardless: every hour belongs to
    # a project there, and the Slack/email between two files of the same project
    # is that project. It still only fills a block whose client already agrees.
    from tracker.services.projects import org_tracks_local_projects
    tracks_local = org_tracks_local_projects(org)
    allow_temporal = bool(getattr(org, 'sandwich_correlation_enabled', False)) or tracks_local
    convention = _build_convention_index(org, options_by_client) if tracks_local else None
    neighbours_by_user = defaultdict(list)
    if allow_temporal:
        for user_id, b_start, b_end, project_id in (
            Block.objects
            .filter(org=org, project__isnull=False, start__gte=since)
            .values_list('user_id', 'start', 'end', 'project_id')
        ):
            neighbours_by_user[user_id].append((b_start, b_end, project_id))

    # Only live projects can absorb new time — open matters, active local ones.
    sole_matter_by_client = {
        cid: opts[0].project_id for cid, opts in options_by_client.items() if len(opts) == 1
    }

    qs = (
        Block.objects
        .filter(org=org, project__isnull=True, start__gte=since)
        .exclude(classification_state='suppressed')
        # Every field the loop reads must be here: a deferred field costs one
        # query PER BLOCK on access. categorized_by (may_correct_client) and
        # app_name (is_browser_block) were missing — see deferred-field N+1.
        .only('id', 'user_id', 'client_id', 'file_path', 'title',
              'window_title', 'url', 'hints', 'start', 'end',
              'categorized_by', 'app_name')
        .order_by('-start')
    )
    if limit:
        qs = qs[:limit]

    updates = defaultdict(list)
    client_fixes = defaultdict(list)
    stats['by_convention'] = 0
    stats['by_current_project'] = 0
    # Ticker "Switch Project" picks: user -> (project, client, from, until).
    picks = {}
    try:
        from tracker.models import CurrentProject
        from tracker.services.projects import CURRENT_PROJECT_TTL_HOURS
        for cp in CurrentProject.objects.filter(project__org=org, project__is_active=True) \
                .select_related('project'):
            picks[cp.user_id] = (cp.project_id, cp.project.client_id, cp.started_at,
                                 cp.started_at + timedelta(hours=CURRENT_PROJECT_TTL_HOURS))
    except Exception as e:      # table not migrated yet — the tier is simply absent
        logger.warning('current-project picks unavailable: %s', e)
    for block in qs:
        stats['scanned'] += 1

        # The firm's own naming convention names client AND project outright
        # (services/naming_convention.py). Knowledge, not inference: it may set
        # a missing client or correct a machine-guessed one, like a Clio anchor.
        if convention:
            from tracker.services.naming_convention import resolve_text
            hit = resolve_text([('file_path', block.file_path), ('window_title', block.window_title),
                                ('title', block.title)], convention)
            if hit:
                want_client, conv_project, _field = hit
                if block.client_id != want_client:
                    if block.client_id and not may_correct_client(block.categorized_by):
                        stats['off_client'] += 1
                        continue
                    client_fixes[want_client].append(block.id)
                if conv_project:
                    updates[conv_project].append(block.id)
                    stats['by_convention'] += 1
                    continue
                # Client only: let the other tiers find the project, now
                # scoped to the client the file named.
                block.client_id = want_client

        # What the person said they are on, for their same-client work while
        # the pick is fresh. Below the convention (a named file is specific),
        # above every inference (a statement beats a guess).
        pick = picks.get(block.user_id)
        if pick and block.client_id == pick[1] and pick[2] <= block.start <= pick[3]:
            updates[pick[0]].append(block.id)
            stats['by_current_project'] += 1
            continue

        project_id, tier, _reason = attribute_block(
            block, index, sole_matter_by_client, project_by_external_id,
            folder_index=folder_index,
            neighbours=neighbours_by_user.get(block.user_id),
            allow_temporal=allow_temporal,
            name_index=name_index,
        )
        if not project_id:
            stats['unmatched'] += 1
            continue

        # An inference may choose a project, never a client. A learned folder
        # or a neighbour can point at another client's project (shared drives,
        # back-to-back work for two clients), and writing it would leave the
        # block saying one client while its project says another — the same
        # contradiction set_block_matter refuses by hand. Only tier 0 knows the
        # client outright; it is handled below.
        if tier != 'clio_anchor':
            want = live_project_client.get(project_id)
            if want is None or (block.client_id and block.client_id != want):
                stats['off_client'] += 1
                continue
            # A neighbour may carry a project across a gap only within the
            # client the block already has — a YouTube tab between two Acme
            # files must not become Acme work.
            if tier == 'temporal' and block.client_id != want:
                stats['off_client'] += 1
                continue
        stats[f'by_{tier}'] += 1
        updates[project_id].append(block.id)

        # A clio_anchor hit knows the MATTER, and a matter has exactly one
        # client — so it knows the client too. Previously only project was
        # written, which left blocks internally contradictory: matter
        # "00001-Ridgeline Holdings LLC" sitting on client "MAVOPS", because
        # the classifier had guessed the client from a window title while the
        # anchor knew the answer outright.
        #
        # ONLY tier 0. The tiers below are inferences about which matter a
        # piece of work belongs to; letting a guessed matter rewrite a client
        # would turn a matter-level mistake into a billing-level one. Tier 0
        # is described in attribute_block as "knowledge, not inference", and
        # that is exactly the bar for overwriting an existing client.
        if tier != 'clio_anchor':
            continue
        want_client = client_by_project_id.get(project_id)
        if not want_client or block.client_id == want_client:
            continue
        # Never overwrite a person. 'manual' and 'correction' mean somebody
        # decided this; 'ai'/'pattern'/None mean the machine guessed, and the
        # anchor is a better machine answer than the guess it replaces.
        if not may_correct_client(block.categorized_by):
            continue
        client_fixes[want_client].append(block.id)

    if not dry_run:
        for project_id, block_ids in updates.items():
            Block.objects.filter(id__in=block_ids).update(project_id=project_id)
        for client_id, block_ids in client_fixes.items():
            # .update() deliberately, matching the project write above: it
            # bypasses Block.save()'s guard on categorised blocks, which is
            # the sanctioned path for a system correction of a machine guess.
            Block.objects.filter(id__in=block_ids).update(client_id=client_id)
    stats['client_corrected'] = sum(len(v) for v in client_fixes.values())

    logger.info('Matter attribution for org %s: %s', org.id, stats)
    return stats


# ============================================================================
# Scheduled entry point
# ============================================================================

@shared_task(name='tracker.attribute_matters_recent')
def attribute_matters_recent(days: int = 2) -> dict:
    """
    Attribute recently-compacted blocks to matters/projects, for every firm
    that syncs a practice management system or keeps its own projects.

    WHY THIS EXISTS SEPARATELY FROM THE POST-SYNC RUN
    -------------------------------------------------
    Attribution used to run in exactly one place: at the end of a Clio sync.
    So a block's matter was decided on the SYNC's cadence, not the block's —
    work captured at 19:17 waited for the 20:20 sweep, even though the matter
    id was known at the moment of capture and was already sitting in
    block.hints.

    That made the feature impossible to evaluate by looking at it. A block
    with a perfectly good anchor and no project is indistinguishable from a
    broken tier, and the only way to tell was to know the sync schedule.

    NARROW ON PURPOSE. `days=2` rather than the post-sync run's 30: this fires
    every few minutes, and re-scanning a month of blocks each time would be
    wasted work on a table that is large for exactly the firms that can least
    afford it. The 30-day pass after each sync stays as the backstop that
    catches anything this window missed.
    """
    from tracker.models import Organization
    from tracker.models_task_type_sets import ExternalMatterMapping

    from tracker.industry_categories import INDUSTRY_LOCAL_PROJECTS

    org_ids = set(
        ExternalMatterMapping.objects
        .values_list('integration__organization_id', flat=True)
        .distinct()
    )
    # Firms that keep their own projects have no sync to trigger a run, so
    # this sweep is the only thing that ever attributes their time.
    org_ids |= set(
        Organization.objects
        .filter(industry_type__in=INDUSTRY_LOCAL_PROJECTS)
        .values_list('id', flat=True)
    )
    totals = {'orgs': 0, 'scanned': 0, 'attributed': 0, 'client_corrected': 0}
    for org in Organization.objects.filter(id__in=list(org_ids)):
        try:
            s = attribute_matters_for_org(org, days=days)
        except Exception as e:
            logger.warning('Matter attribution failed for org %s: %s',
                           org.id, e, exc_info=True)
            continue
        totals['orgs'] += 1
        totals['scanned'] += s.get('scanned', 0)
        totals['attributed'] += sum(
            v for k, v in s.items() if k.startswith('by_') and isinstance(v, int)
        )
        totals['client_corrected'] += s.get('client_corrected', 0)

    logger.info('Matter attribution sweep: %s', totals)
    return totals
