"""
The one server-side list of video-meeting platforms.

Why one list: meeting detection used to live in five places with five different
vocabularies (views_block_evidence._MEETING_APPS, utils/blocks
COMMUNICATION_APPS, display_formatter._MEETING_PLATFORMS, compaction's
NEVER_IDLE_DOMAINS, views.infer_task_for_block). None of them knew about
telehealth, so an 82-minute Kareo telehealth call in Chrome (block 79634,
"Telehealth - Camera and microphone recording - Google Chrome") was captured
but never treated as a meeting: the "why" panel never looked at the calendar
and said "No added context to go on".

The desktop agents carry their own copies (mac_agent/meeting_detector.py,
windows_agent/meeting_detector.py, mac_agent/main.py MEETING_DOMAINS). They
cannot import this module, so keep them in step by hand — and remember an
agent change only reaches machines with an agent release.

Three kinds of evidence, strongest first:

  * URL host — exact domain or a subdomain of one in MEETING_DOMAINS.
  * App name — a native conferencing app (Teams, Zoom, Webex …).
  * Title words — "Telehealth", "Video visit", "Huddle", "Zoom Meeting".
    Title words are only trusted on a browser or a conferencing app, because
    a document called "huddle notes.docx" is not a meeting.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

# Host (or parent domain) → platform label. Subdomains match: "us02web.zoom.us"
# matches "zoom.us"; "telehealth.kareo.com" is listed exactly because the rest
# of kareo.com is the practice-management app, not a call.
MEETING_DOMAINS: dict[str, str] = {
    'zoom.us': 'Zoom',
    'zoom.com': 'Zoom',
    'zoomgov.com': 'Zoom',
    'teams.microsoft.com': 'Teams',
    'teams.live.com': 'Teams',
    'meet.google.com': 'Google Meet',
    'webex.com': 'Webex',
    'gotomeeting.com': 'GoTo Meeting',
    'meet.goto.com': 'GoTo Meeting',
    'app.goto.com': 'GoTo Meeting',
    'bluejeans.com': 'BlueJeans',
    'v.ringcentral.com': 'RingCentral Video',
    'meetings.ringcentral.com': 'RingCentral Video',
    'whereby.com': 'Whereby',
    'around.co': 'Around',
    'app.chime.aws': 'Amazon Chime',
    'chime.aws': 'Amazon Chime',
    'meet.jit.si': 'Jitsi',
    '8x8.vc': 'Jitsi',
    # Telehealth
    'doxy.me': 'Doxy.me',
    'telehealth.kareo.com': 'Kareo Telehealth',
    'video.simplepractice.com': 'SimplePractice',
    'vsee.com': 'VSee',
    'vsee.me': 'VSee',
    'teladoc.com': 'Teladoc',
    'teladochealth.com': 'Teladoc',
}

# Native conferencing apps, matched as a substring of the lower-cased app name.
# Order matters: the first hit names the platform.
MEETING_APPS: tuple[tuple[str, str], ...] = (
    ('teams', 'Teams'),
    ('zoom', 'Zoom'),
    ('webex', 'Webex'),
    ('gotomeeting', 'GoTo Meeting'),
    ('goto meeting', 'GoTo Meeting'),
    ('bluejeans', 'BlueJeans'),
    ('ringcentral', 'RingCentral Video'),
    ('vsee', 'VSee'),
    ('amazon chime', 'Amazon Chime'),
    ('chime', 'Amazon Chime'),
    ('around', 'Around'),
    ('google meet', 'Google Meet'),
)

# Title phrases that say "this window is a call" (lower-case, word-bounded).
MEETING_TITLE_PHRASES: tuple[tuple[str, str], ...] = (
    ('telehealth', 'Telehealth'),
    ('tele-health', 'Telehealth'),
    ('video visit', 'Video visit'),
    ('virtual visit', 'Video visit'),
    ('doxy.me', 'Doxy.me'),
    ('simplepractice', 'SimplePractice'),
    ('teladoc', 'Teladoc'),
    ('vsee', 'VSee'),
    ('whereby', 'Whereby'),
    ('jitsi', 'Jitsi'),
    ('meet.jit.si', 'Jitsi'),
    ('bluejeans', 'BlueJeans'),
    ('gotomeeting', 'GoTo Meeting'),
    ('goto meeting', 'GoTo Meeting'),
    ('ringcentral video', 'RingCentral Video'),
    ('amazon chime', 'Amazon Chime'),
    ('huddle', 'Huddle'),
    ('zoom meeting', 'Zoom'),
    ('zoom webinar', 'Zoom'),
    ('teams meeting', 'Teams'),
    ('webex meeting', 'Webex'),
    ('google meet', 'Google Meet'),
    ('meet.google.com', 'Google Meet'),
)

BROWSER_APP_HINTS = (
    'chrome', 'msedge', 'edge', 'firefox', 'safari', 'brave', 'opera',
    'vivaldi', 'arc.exe', 'thebrowser',
)
# Apps whose own windows can host a call without a meeting-shaped app name
# (a Slack huddle runs inside slack.exe).
CALL_CAPABLE_APP_HINTS = ('slack', 'discord', 'skype', 'facetime')

_PHRASE_RES = tuple(
    (re.compile(r'(?<![a-z0-9])' + re.escape(p) + r'(?![a-z0-9])'), label)
    for p, label in MEETING_TITLE_PHRASES
)


def host_of(url: str) -> str:
    u = (url or '').strip().lower()
    if not u:
        return ''
    if '://' not in u:
        u = 'https://' + u
    try:
        return (urlparse(u).hostname or '').lower()
    except Exception:
        return ''


def platform_for_host(host: str) -> Optional[str]:
    h = (host or '').lower().strip('.')
    if h.startswith('www.'):
        h = h[4:]
    for domain, label in MEETING_DOMAINS.items():
        if h == domain or h.endswith('.' + domain):
            return label
    return None


def platform_for_url(url: str) -> Optional[str]:
    return platform_for_host(host_of(url))


def _is_browser_or_call_app(app: str) -> bool:
    a = (app or '').lower()
    return any(b in a for b in BROWSER_APP_HINTS + CALL_CAPABLE_APP_HINTS)


def platform_for_title(title: str) -> Optional[str]:
    t = (title or '').lower()
    if not t:
        return None
    for rx, label in _PHRASE_RES:
        if rx.search(t):
            return label
    return None


def platform_for_app(app_name: str) -> Optional[str]:
    a = (app_name or '').lower()
    if not a:
        return None
    for key, label in MEETING_APPS:
        if key in a:
            return label
    return None


def detect_meeting_platform(app_name: str = '', window_title: str = '',
                            url: str = '') -> Optional[str]:
    """Platform label when the block/window is a video call, else None.

    Native conferencing apps only count when the agent's meeting detector
    bracketed the block (its app name then says "meeting") or the title says
    it is a meeting: a Teams CHAT window is ordinary work.
    """
    app = (app_name or '').lower()
    title = (window_title or '').lower()

    by_url = platform_for_url(url)
    if by_url:
        return by_url

    # The agent's meeting detector writes app names like "Teams Meeting".
    if 'meeting' in app:
        return platform_for_app(app) or platform_for_title(title) or 'Meeting'

    native = platform_for_app(app)
    if native and 'meeting' in title:
        return native

    if _is_browser_or_call_app(app) or native:
        by_title = platform_for_title(title)
        if by_title:
            return by_title
        # A browser tab title can carry the host ("meet.google.com is sharing").
        for domain, label in MEETING_DOMAINS.items():
            if domain in title:
                return label
    return None


def is_meeting_activity(app_name: str = '', window_title: str = '', url: str = '') -> bool:
    return detect_meeting_platform(app_name, window_title, url) is not None
