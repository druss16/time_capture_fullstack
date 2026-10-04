# tracker/email_service.py
"""
Central email service using SendGrid REST API (raw HTTP, no SDK).
All transactional emails go through here.

Setup:
  1. Set SENDGRID_API_KEY in .env
  2. Set DEFAULT_FROM_EMAIL in settings.py (e.g., "noreply@mavops.ai")
"""

import html as html_lib
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# ============================================================================
# CORE SEND FUNCTION (raw HTTP - no SDK needed)
# ============================================================================

def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    plain_content: str = None,
    from_email: str = None,
    from_name: str = "TimeTracker",
    reply_to: str = None,
    categories: list = None,
):
    """
    Send a transactional email via SendGrid REST API.

    Returns:
        True if sent successfully, False otherwise
    """
    import requests as req

    api_key = getattr(settings, 'SENDGRID_API_KEY', None)
    if not api_key:
        logger.error("[EMAIL] SENDGRID_API_KEY not configured")
        return False

    from_email = from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@mavops.ai')
    reply_to = reply_to or getattr(settings, 'DEFAULT_REPLY_TO_EMAIL', 'dan@mavops.ai')
    plain_text = plain_content or _strip_html(html_content)

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email, "name": from_name},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain_text},
            {"type": "text/html", "value": html_content},
        ],
    }

    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    if categories:
        payload["categories"] = categories

    try:
        resp = req.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        logger.info(f"[EMAIL] Sent to {to_email} - status: {resp.status_code} - subject: {subject[:50]}")
        if resp.status_code not in (200, 201, 202):
            logger.error(f"[EMAIL] SendGrid error: {resp.text}")
        return resp.status_code in (200, 201, 202)
    except Exception as e:
        logger.error(f"[EMAIL] Failed to send to {to_email}: {e}")
        return False


def _strip_html(html: str) -> str:
    """Quick and dirty HTML tag stripper for plain text fallback."""
    import re
    text = re.sub(r'<br\s*/?>', '\n', html)
    text = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _fmt_hours(decimal_hours) -> str:
    """
    Convert decimal hours to human-readable string.

    Examples:
        0.6833  → '41min'
        1.5     → '1h 30min'
        2.0     → '2h'
        0.0     → '0min'

    Used everywhere hours are displayed in emails.
    Never pass raw floats or Decimal model values directly into email templates.
    """
    try:
        total_minutes = round(float(decimal_hours) * 60)
    except (TypeError, ValueError):
        return "0min"
    if total_minutes <= 0:
        return "0min"
    h, m = divmod(total_minutes, 60)
    if h and m:
        return f"{h}h {m}min"
    elif h:
        return f"{h}h"
    else:
        return f"{m}min"




# ============================================================================
# SHARED HTML WRAPPER
# ============================================================================

# ── Brand ───────────────────────────────────────────────────────────────────
# The palette is the web app's, not an email-only one: slate-800 top bar with
# the white ring-and-check mark (Navigation.tsx), the app's primary teal
# (--primary: 173 58% 39%), Tailwind slate for text and rules, and the
# "Lightning" card look — 16px radius, hairline slate-200 border, Inter.
# Someone who clicks through from an email should land on a page that looks
# like the email they just read.
#
# A caller chooses only a TONE ('brand' / 'warn' / 'alert'), because a
# seat-overage warning and a rejected timesheet genuinely are not the same
# news as an invitation.
NAV        = '#1e293b'   # slate-800, the app's top bar
INK        = '#0f172a'   # slate-900, headings and figures
INK_SOFT   = '#475569'   # slate-600, body copy
INK_FAINT  = '#64748b'   # slate-500, fine print (slate-400 is too light on white)
GROUND     = '#f9fafb'   # --background: 210 20% 98%
RULE       = '#e2e8f0'   # slate-200
TINT       = '#f7faf9'   # Lightning mint tint (SettingsSection tint)
TEAL       = '#2a9d90'   # --primary: 173 58% 39%
TEAL_INK   = '#1f7a70'   # primary, darkened for small text on white
AMBER      = '#f59e0b'   # --warning
RED        = '#dc2626'

TONES = {'brand': TEAL, 'warn': AMBER, 'alert': RED}

# Panel colours per tone: (background, border, text). Tailwind 50/200/800.
PANELS = {
    'neutral': ('#f8fafc', RULE, INK),
    'brand':   (TINT, '#d5ebe7', INK),
    'warn':    ('#fffbeb', '#fde68a', '#92400e'),
    'alert':   ('#fef2f2', '#fecaca', '#991b1b'),
}

FONT = ("Inter,'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,"
        "'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif")


def _frontend_url():
    return getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')


def _e(value) -> str:
    """Escape a value that came from a person (names, notes, reasons).

    Org names, rejection reasons and suggestion notes are typed by users and
    were interpolated raw, so a stray '<' broke the layout and markup in a
    reason rendered in the recipient's inbox.
    """
    return html_lib.escape('' if value is None else str(value))


def _accent_for(tone_or_gradient):
    """Map a tone name, or a legacy CSS gradient, onto one accent colour."""
    accent = TONES.get(tone_or_gradient)
    if accent is not None:
        return accent
    g = str(tone_or_gradient)
    if 'ef4444' in g or 'dc2626' in g:
        return RED
    if 'F59E0B' in g or 'D97706' in g:
        return AMBER
    return TEAL


def _preheader(text: str) -> str:
    """The line an inbox shows beside the subject.

    Left empty, clients scrape it from the markup and show a fragment of the
    header or a run of whitespace. The padding run stops the client
    continuing past our sentence into the header markup.
    """
    if not text:
        return ''
    pad = '&#847;&zwnj;&nbsp;' * 30
    return (
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;'
        'mso-hide:all;">' + text + '</div>'
        '<div style="display:none;max-height:0;overflow:hidden;">' + pad + '</div>'
    )


def _wrap_html(tone_or_gradient, header_icon, header_title, body_html,
               preheader='', subtitle='', footer_note=''):
    """The one shell every email uses.

    The first argument is a TONE ('brand' / 'warn' / 'alert'); a legacy CSS
    gradient string maps onto a tone. header_icon is accepted and ignored —
    the app does not put emoji in headings and neither do we.

    header_title, subtitle and footer_note are trusted HTML: callers escape
    any user-supplied part with _e().
    """
    accent = _accent_for(tone_or_gradient)
    mark = _frontend_url() + '/email-mark-white.png'
    head = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<meta name="supported-color-schemes" content="light">'
        # Apple Mail and iOS honour web fonts; everything else falls back
        # down the FONT stack to the system UI face.
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">'
        # Phones: stat tiles stack and the page gutter tightens. Clients that
        # drop <style> (old Outlook) are desktop, where the tiles fit.
        '<style>@media only screen and (max-width:480px){'
        '.tt-outer{padding:16px 8px!important}'
        '.tt-pad{padding-left:18px!important;padding-right:18px!important}'
        '.tt-stat{display:block!important;width:100%!important;'
        'padding:0 0 8px 0!important}}</style>'
        '<title>' + str(header_title) + '</title></head>'
    )
    sub_html = (
        '<p style="margin:6px 0 0;color:' + INK_FAINT + ';font-size:13px;'
        'line-height:1.45;">' + subtitle + '</p>'
    ) if subtitle else ''
    note_html = ('<br>' + footer_note) if footer_note else ''
    return (
        head +
        '<body style="margin:0;padding:0;background:' + GROUND +
        ';font-family:' + FONT + ';-webkit-font-smoothing:antialiased;">'
        + _preheader(preheader) +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="background:' + GROUND + ';">'
        '<tr><td class="tt-outer" align="center" style="padding:32px 16px;">'

        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="max-width:600px;background:#ffffff;border:1px solid '
        + RULE + ';border-radius:16px;overflow:hidden;">'

        # Top bar: the same slate-800 strip, mark and two-line wordmark the
        # app's navigation shows.
        '<tr><td class="tt-pad" style="background:' + NAV + ';padding:14px 24px;">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td style="vertical-align:middle;padding-right:10px;">'
        '<img src="' + mark + '" width="32" height="32" alt="" '
        'style="display:block;border:0;width:32px;height:32px;"></td>'
        '<td style="vertical-align:middle;font-family:' + FONT + ';">'
        '<div style="color:#ffffff;font-size:15px;font-weight:700;'
        'letter-spacing:-0.01em;line-height:1.1;">TimeTracker</div>'
        '<div style="color:#94a3b8;font-size:11px;line-height:1.3;">by Mavops</div>'
        '</td></tr></table></td></tr>'

        # The only per-email colour, and only where the news genuinely differs.
        '<tr><td style="height:3px;background:' + accent +
        ';font-size:0;line-height:0;">&nbsp;</td></tr>'

        '<tr><td class="tt-pad" style="padding:28px 28px 6px;">'
        '<h1 style="margin:0;color:' + INK + ';font-size:20px;line-height:1.3;'
        'font-weight:700;letter-spacing:-0.01em;">' + str(header_title) + '</h1>'
        + sub_html +
        '</td></tr>'

        '<tr><td class="tt-pad" style="padding:12px 28px 28px;color:' + INK_SOFT +
        ';font-size:15px;line-height:1.6;">' + body_html + '</td></tr>'

        '</table>'

        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="max-width:600px;"><tr>'
        '<td style="padding:16px 28px 0;text-align:center;color:' + INK_FAINT +
        ';font-size:12px;line-height:1.6;">TimeTracker by Mavops &middot; '
        '<a href="mailto:info@mavops.ai" style="color:' + TEAL_INK +
        ';text-decoration:none;">info@mavops.ai</a>' + note_html + '</td></tr></table>'

        '</td></tr></table></body></html>'
    )


def _btn(url, tone, text):
    """The app's primary button: solid fill, 10px radius, semibold.

    A solid fill in a table cell, never a gradient — Outlook drops CSS
    gradients and was rendering white text on a white button.
    """
    bg = _accent_for(tone)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:24px 0 8px;"><tr>'
        '<td style="border-radius:10px;background:' + bg + ';">'
        '<a href="' + url + '" style="display:inline-block;padding:12px 24px;'
        'color:#ffffff;font-family:' + FONT + ';font-size:15px;font-weight:600;'
        'text-decoration:none;border-radius:10px;">' + text + '</a>'
        '</td></tr></table>'
    )


# ── Body building blocks ────────────────────────────────────────────────────
# Every template is assembled from these so a paragraph, a callout or a
# client table looks the same in every email.

def _p(html, *, last=False):
    return ('<p style="margin:0 0 ' + ('0' if last else '12px') + ';">'
            + html + '</p>')


def _strong(html):
    return '<strong style="color:' + INK + ';font-weight:600;">' + html + '</strong>'


def _fine(html, *, top=12):
    return ('<p style="margin:' + str(top) + 'px 0 0;color:' + INK_FAINT +
            ';font-size:13px;line-height:1.5;">' + html + '</p>')


def _panel(html, tone='neutral'):
    """A callout card — the app's rounded, hairline-bordered section."""
    bg, border, color = PANELS.get(tone, PANELS['neutral'])
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="margin:16px 0;"><tr>'
        '<td style="background:' + bg + ';border:1px solid ' + border +
        ';border-radius:12px;padding:14px 16px;color:' + color +
        ';font-size:14px;line-height:1.55;">' + html + '</td></tr></table>'
    )


def _label(text):
    """The app's small uppercase field label."""
    return ('<div style="color:' + INK_FAINT + ';font-size:11px;font-weight:600;'
            'text-transform:uppercase;letter-spacing:0.06em;">' + text + '</div>')


def _stats(items):
    """A row of stat tiles: [(label, value), ...] — the Lightning KPI look."""
    width = str(int(100 / max(1, len(items))))
    cells = ''.join(
        '<td class="tt-stat" width="' + width + '%" style="vertical-align:top;padding:' + ('0 0 0 8px' if i else '0') + ';">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        '<tr><td style="background:' + TINT + ';border:1px solid #d5ebe7;'
        'border-radius:12px;padding:14px 16px;">'
        + _label(label) +
        '<div style="margin-top:4px;color:' + INK + ';font-size:22px;font-weight:700;'
        'letter-spacing:-0.01em;line-height:1.2;">' + value + '</div>'
        '</td></tr></table></td>'
        for i, (label, value) in enumerate(items)
    )
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
            ' border="0" style="margin:16px 0;"><tr>' + cells + '</tr></table>')


def _rows(rows, *, heading=None, empty='', total=None):
    """A two-column breakdown (client → hours) in a bordered card.

    rows are (left_html, right_html) pairs, already escaped by the caller.
    """
    head = ''
    if heading:
        head = (
            '<tr><td style="padding:10px 16px;border-bottom:1px solid ' + RULE + ';">'
            + _label(heading[0]) + '</td>'
            '<td style="padding:10px 16px;border-bottom:1px solid ' + RULE +
            ';text-align:right;">' + _label(heading[1]) + '</td></tr>'
        )
    body = ''.join(
        '<tr><td style="padding:10px 16px;border-bottom:1px solid ' + RULE +
        ';color:' + INK + ';font-size:14px;">' + left + '</td>'
        '<td style="padding:10px 16px;border-bottom:1px solid ' + RULE +
        ';color:' + INK + ';font-size:14px;font-weight:600;text-align:right;'
        'white-space:nowrap;">' + right + '</td></tr>'
        for left, right in rows
    )
    if not rows and empty:
        body = ('<tr><td colspan="2" style="padding:14px 16px;color:' + INK_FAINT +
                ';font-size:14px;">' + empty + '</td></tr>')
    foot = ''
    if total is not None:
        foot = (
            '<tr><td style="padding:12px 16px;background:' + TINT + ';color:' + INK +
            ';font-size:14px;font-weight:700;">Total</td>'
            '<td style="padding:12px 16px;background:' + TINT + ';color:' + TEAL_INK +
            ';font-size:14px;font-weight:700;text-align:right;white-space:nowrap;">'
            + total + '</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="margin:16px 0;border:1px solid ' + RULE +
        ';border-radius:12px;border-collapse:separate;overflow:hidden;">'
        + head + body + foot + '</table>'
    )


def _fallback_link(url):
    return _fine('Button not working? Paste this into your browser:<br>'
                 '<span style="word-break:break-all;color:' + TEAL_INK + ';">'
                 + url + '</span>', top=18)


def _prefs_note():
    return ('<a href="' + _frontend_url() + '/settings" style="color:' + INK_FAINT +
            ';text-decoration:underline;">Manage email preferences</a>')


# ============================================================================
# PRE-BUILT EMAIL TEMPLATES
# ============================================================================

# ---------- 1. Added to an existing org ----------
# send_team_invitation was removed here: it was the last emailer that put a
# temporary password in a message body, and nothing called it any more. New
# members get a single-use setup link instead (send_onboarding_invitation).

def send_added_to_org(
    to_email: str,
    org_name: str,
    username: str,
    invited_by: str = None,
    login_url: str = None,
):
    """
    Notify an existing TimeTracker user they've been added to a new organization.
    Does NOT include a password — they already have one.
    """
    login_url = login_url or f"{_frontend_url()}/login"
    invite_line = f"{invited_by} has added you" if invited_by else "You've been added"

    body = (
        _p(f'Hi {_e(username)},')
        + _p(f'{_e(invite_line)} to {_strong(_e(org_name))} on TimeTracker.', last=True)
        + _panel(
            _label('Your account')
            + f'<div style="margin-top:4px;">Username: {_strong(_e(username))}</div>'
            + f'<div style="margin-top:6px;color:{INK_FAINT};font-size:13px;">'
              'Sign in with the password you already use for TimeTracker.</div>'
        )
        + _btn(login_url, 'brand', 'Sign in to TimeTracker')
    )

    html = _wrap_html(
        'brand', '', f"You've been added to {_e(org_name)}", body,
        preheader=f'{_e(org_name)} is now in your TimeTracker account.',
    )

    plain = f"""Hi {username},

{invite_line} to {org_name} on TimeTracker.

Sign in at: {login_url}
Username: {username}
Password: the one you already use for TimeTracker

- TimeTracker by Mavops"""

    return send_email(
        to_email=to_email,
        subject=f"You've been added to {org_name} on TimeTracker",
        html_content=html,
        plain_content=plain,
        categories=["invitation", "org_added"],
    )


def send_seat_overage_notice(
    to_email: str,
    org_name: str,
    member_count: int,
    seat_count: int,
    grace_days: int = 15,
):
    """
    Warn an org owner/admin that they have more members than paid seats,
    with a grace window before the extra users are paused.
    """
    billing_url = f"{_frontend_url()}/account/billing"
    over_by = max(0, member_count - seat_count)
    seats_word = 'seat' if seat_count == 1 else 'seats'
    members_word = 'member' if over_by == 1 else 'members'

    body = (
        _p(f'Your team on {_strong(_e(org_name))} has grown past your plan.', last=True)
        + _stats([
            ('Members', str(member_count)),
            (f'Paid {seats_word}', str(seat_count)),
            ('Over by', str(over_by)),
        ])
        + _panel(
            f'You have <strong>{grace_days} days</strong> to add seats. After that, '
            f'the {over_by} most recently added {members_word} will be paused until you do.',
            'warn',
        )
        + _btn(billing_url, 'brand', 'Add seats')
    )

    html = _wrap_html(
        'warn', '', "You're over your seat count", body,
        preheader=f'{member_count} members on {seat_count} paid {seats_word} — '
                  f'{grace_days} days to add seats.',
    )

    plain = f"""Your team on {org_name} has grown past your plan.

{member_count} members on {seat_count} paid {seats_word} — {over_by} over your limit.

You have {grace_days} days to add seats. After that, the {over_by} most recently
added {members_word} will be paused until you do.

Add seats: {billing_url}

- TimeTracker by Mavops"""

    return send_email(
        to_email=to_email,
        subject=f"Action needed: {org_name} is over its seat count",
        html_content=html,
        plain_content=plain,
        categories=["billing", "seat_overage"],
    )


# ---------- 2. Onboarding invitation ----------

def send_onboarding_invitation(
    to_email: str,
    org_name: str,
    invite_url: str,
    invited_by: str = None,
    expires_days: int = 7,
):
    """Invite a new member with a one-time link to choose their own password.

    The link is the whole credential: no password is ever put in an email, and
    the invite is single-use and expires, so a forwarded or archived message
    cannot be replayed into an account.

    The desktop app is already on the person's computer — the firm's IT
    deploys it — so the email never asks them to download or install
    anything. Choosing a password is the only step left for them.
    """
    help_url = f"{_frontend_url()}/help"
    who = f"{invited_by} has invited you" if invited_by else "You have been invited"

    plain = f"""{who} to join {org_name} on TimeTracker.

Open this link to choose a password and finish setup:
{invite_url}

It works once and expires in {expires_days} days.

What happens next:
  1. Choose your password (30 seconds)
  2. The desktop app is already on your computer — nothing to install
  3. Your billable time starts capturing automatically

Questions? {help_url} or reply to this email.

- The TimeTracker Team"""

    steps = "".join(
        f'<tr><td style="padding:0 0 14px;vertical-align:top;width:34px;">'
        f'<div style="width:24px;height:24px;border-radius:12px;background:{TINT};'
        f'border:1px solid #d5ebe7;color:{TEAL_INK};font-size:12px;font-weight:700;'
        f'text-align:center;line-height:24px;">{n}</div></td>'
        f'<td style="padding:0 0 14px;vertical-align:top;">'
        f'<div style="color:{INK};font-weight:600;font-size:14px;">{t}</div>'
        f'<div style="color:{INK_FAINT};font-size:13px;">{d}</div>'
        f'</td></tr>'
        for n, t, d in [
            (1, 'Choose your password', 'You pick it &mdash; we never email one.'),
            (2, 'The desktop app is already installed',
                'Your firm put it on your computer, so there is nothing to download.'),
            (3, 'Your time starts capturing',
                'It runs quietly in the background and sorts work by client.'),
        ]
    )

    body = (
        _p(f'{_e(who)} to join {_strong(_e(org_name))}.')
        + _p('TimeTracker captures your billable time automatically, so you never '
             'have to remember to log hours. All you need to do is choose a password.', last=True)
        + _btn(invite_url, 'brand', 'Set your password')
        + _fine(f'This link works once and expires in {expires_days} days.', top=0)
        + f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
          f'width="100%" style="margin-top:22px;border-top:1px solid {RULE};">'
          f'<tr><td colspan="2" style="padding:20px 0 12px;">{_label("What happens next")}'
          f'</td></tr>{steps}</table>'
        + _fallback_link(invite_url)
    )

    html = _wrap_html(
        'brand', '', f'Welcome to {_e(org_name)}', body,
        preheader='Choose a password and you are done. The desktop app is already installed.',
    )

    return send_email(
        to_email=to_email,
        subject=f"You've been invited to join {org_name} on TimeTracker",
        html_content=html,
        plain_content=plain,
        categories=["invitation", "onboarding"],
    )


def send_intake_link(to_email: str, firm_name: str, intake_url: str,
                     contact_name: str = None, expires_on: str = None):
    """Ask a new firm to fill in its onboarding intake.

    The link is single-use per firm and needs no login, so it says plainly
    that it should not be forwarded outside the firm.
    """
    hello = f"Hi {contact_name}," if contact_name else "Hi,"
    until = f" It stays open until {expires_on}." if expires_on else ""
    plain = f"""{hello}

To get {firm_name} set up on TimeTracker, we need a few details from you:
your team, the services you bill for, and who we should work with.
It takes about 20 minutes and saves as you go, so several people can fill it in.

Open the form:
{intake_url}

No login is needed. Please keep the link within {firm_name}.{until}

Questions? Just reply to this email.

- Dan Russell, Mavops"""

    body = (
        _p(_e(hello))
        + _p(f'To get {_strong(_e(firm_name))} set up on TimeTracker, we need a few '
             f'details from you: your team, the services you bill for, and who we '
             f'should work with.')
        + _p('It takes about 20 minutes and saves as you go, so several people can '
             'fill it in.', last=True)
        + _btn(intake_url, 'brand', 'Open the setup form')
        + _fine(f'No login is needed. Please keep the link within '
                f'{_e(firm_name)}.{_e(until)}', top=0)
        + _fallback_link(intake_url)
    )
    html = _wrap_html('brand', '', f'Getting {_e(firm_name)} set up', body,
                      preheader='A short form so we can set up TimeTracker for your firm.')
    return send_email(
        to_email=to_email,
        subject=f"Getting {firm_name} set up on TimeTracker",
        html_content=html,
        plain_content=plain,
        categories=["onboarding", "intake"],
    )


# ---------- 2b. Password reset ----------

def send_password_reset(
    to_email: str,
    user_name: str,
    reset_url: str,
    org_name: str = "TimeTracker",
    expires_hours: int = 72,
):
    """Send a password reset link.

    Deliberately says nothing about the account beyond the firm name: reset
    mail reaches whoever controls the mailbox, which is not always the person
    it was meant for.
    """
    plain = f"""Hi {user_name},

Someone asked to reset the password for your {org_name} TimeTracker account.

Choose a new one here:
{reset_url}

This link expires in {expires_hours} hours and can only be used once.

If this wasn't you, ignore this email — nothing has changed.

- The TimeTracker Team"""

    body = (
        _p(f'Hi {_e(user_name)},')
        + _p(f'Someone asked to reset the password for your '
             f'{_strong(_e(org_name))} TimeTracker account.', last=True)
        + _btn(reset_url, 'brand', 'Choose a new password')
        + _fine(f'Expires in {expires_hours} hours &middot; works once', top=0)
        + _panel("If this wasn't you, you can ignore this email &mdash; nothing has changed.")
        + _fallback_link(reset_url)
    )

    html = _wrap_html('brand', '', 'Reset your password', body,
                      preheader=f'This link expires in {expires_hours} hours.')

    return send_email(
        to_email=to_email,
        subject="Reset your TimeTracker password",
        html_content=html,
        plain_content=plain,
        categories=["password_reset"],
    )


# ---------- 3. Daily timesheet review reminder ----------

def send_timesheet_reminder(
    to_email: str,
    user_name: str,
    date_str: str,
    total_hours: float,
    client_breakdown: list,
    unassigned_count: int = 0,
    review_url: str = None,
    date_iso: str = None,
):
    """Send daily timesheet review reminder."""
    frontend_url = _frontend_url()
    if not review_url:
        review_url = f'{frontend_url}/daily?date={date_iso}' if date_iso else f'{frontend_url}/daily'

    blocks_word = 'block needs' if unassigned_count == 1 else 'blocks need'

    # No "nothing captured" email. A day with no time is usually a day off,
    # and a daily nag reaches everyone who is on vacation.
    if total_hours < 0.1:
        logger.info(f"[EMAIL] Daily reminder skipped for {to_email}: no time captured")
        return False

    tone = 'brand'
    title = 'Review your time'
    rows = [(_e(name), _fmt_hours(hrs)) for name, hrs in client_breakdown]
    unassigned_html = _panel(
        f'<strong>{unassigned_count} {blocks_word}</strong> a client before '
        'you can submit.', 'warn',
    ) if unassigned_count else ''
    body = (
        _p(f'Hi {_e(user_name)},')
        + _p(f'You captured {_strong(_fmt_hours(total_hours))} on {_e(date_str)}. '
             'Give it a quick look before it goes on your timesheet.', last=True)
        + _rows(rows, heading=('Client', 'Time'),
                empty='No clients assigned yet',
                total=_fmt_hours(total_hours))
        + unassigned_html
        + _btn(review_url, 'brand', 'Open Daily Review')
    )
    unassigned_line = (f"\n{unassigned_count} {blocks_word} a client before you can submit.\n"
                       if unassigned_count else "")
    plain = f"""Hi {user_name},

You captured {_fmt_hours(total_hours)} on {date_str}:

{chr(10).join([f'  - {name}: {_fmt_hours(hrs)}' for name, hrs in client_breakdown])}
{unassigned_line}
Open Daily Review: {review_url}

- TimeTracker"""
    subj = f"Review your time for {date_str}"
    pre = f'{_fmt_hours(total_hours)} captured' + (
        f' · {unassigned_count} {blocks_word} a client' if unassigned_count else '')

    html = _wrap_html(tone, '', title, body, preheader=pre,
                      subtitle=_e(date_str), footer_note=_prefs_note())

    return send_email(
        to_email=to_email,
        subject=subj,
        html_content=html,
        plain_content=plain,
        categories=["timesheet_reminder", "daily"],
    )


# ---------- 4. Weekly summary ----------

def send_weekly_summary_email(
    to_email: str,
    user_name: str,
    week_str: str,
    total_hours: float,
    client_breakdown: list,
    week_start_iso: str = None,
):
    """Send weekly time summary email."""
    frontend_url = _frontend_url()
    report_url = f'{frontend_url}/billing?week={week_start_iso}' if week_start_iso else f'{frontend_url}/billing'

    top = client_breakdown[:10]
    rows = [(_e(name), _fmt_hours(hrs)) for name, hrs in top]
    more = len(client_breakdown) - len(top)

    body = (
        _p(f'Hi {_e(user_name)},')
        + _p(f'Here is where your time went for {_strong(_e(week_str))}.', last=True)
        + _stats([('Total time', _fmt_hours(total_hours)),
                  ('Clients', str(len(client_breakdown)))])
        + _rows(rows, heading=('Client', 'Time'), empty='No clients this week')
        + (_fine(f'Plus {more} more in the full report.', top=0) if more > 0 else '')
        + _btn(report_url, 'brand', 'View full report')
    )

    html = _wrap_html('brand', '', 'Your week in review', body,
                      subtitle=_e(week_str),
                      preheader=f'{_fmt_hours(total_hours)} across '
                                f'{len(client_breakdown)} clients.',
                      footer_note=_prefs_note())

    plain = f"""Hi {user_name},

Your week in review — {week_str}

Total: {_fmt_hours(total_hours)}

By client:
{chr(10).join([f'  - {name}: {_fmt_hours(hrs)}' for name, hrs in top])}

View full report: {report_url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"Your week: {_fmt_hours(total_hours)} ({week_str})",
        html_content=html,
        plain_content=plain,
        categories=["weekly_summary"],
    )


# ---------- 5. Monday submission reminder ----------

def send_submission_reminder(
    to_email: str,
    user_name: str,
    week_start_str: str,
    week_end_str: str,
    total_hours: float,
    block_count: int,
    week_start_iso: str = None,
    auto_submit_enabled: bool = False,
):
    """Monday reminder to submit last week's timesheet."""
    url = (_frontend_url() + "/timesheet?tab=timesheet"
           + (f"&week={week_start_iso}" if week_start_iso else ""))

    auto_warn_html = _panel(
        'If it isn\'t submitted by the end of today, it will be '
        '<strong>auto-submitted Tuesday at 9am</strong>.', 'warn',
    ) if auto_submit_enabled else ''

    body = (
        _p(f'Hi {_e(user_name)},')
        + _p(f'Your timesheet for {_strong(_e(week_start_str) + " &ndash; " + _e(week_end_str))} '
             "hasn't been submitted yet.", last=True)
        + _stats([('Time captured', _fmt_hours(total_hours)),
                  ('Time blocks', str(block_count))])
        + auto_warn_html
        + _btn(url, 'brand', 'Review &amp; submit')
    )

    html = _wrap_html('brand', '', 'Submit your timesheet', body,
                      subtitle=f'Week of {_e(week_start_str)}',
                      preheader=f'{_fmt_hours(total_hours)} waiting to be submitted.')

    plain = f"""Hi {user_name},

Your timesheet for {week_start_str} - {week_end_str} has not been submitted yet.

Summary:
- {_fmt_hours(total_hours)} captured
- {block_count} time blocks

Please review and submit by end of day today.
{"It will be auto-submitted Tuesday 9am if not submitted." if auto_submit_enabled else ""}

Review & submit: {url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"Timesheet reminder: week of {week_start_str}",
        html_content=html,
        plain_content=plain,
        categories=["submission_reminder", "weekly"],
    )


# ---------- 6. Auto-submit notification ----------

def send_auto_submit_notification(
    to_email: str,
    user_name: str,
    week_start_str: str,
    week_end_str: str,
    total_hours,
    billable_hours,
    total_amount,
):
    """Notify user their timesheet was auto-submitted on Tuesday.

    total_amount is accepted for existing callers and not shown. Firms bill
    from Clio / Karbon / their own system, not from TimeTracker, so a dollar
    figure here reads as an invoice the person never sent.
    """
    url = _frontend_url() + "/timesheet"

    body = (
        _p(f'Hi {_e(user_name)},')
        + _p(f'Your timesheet for {_strong(_e(week_start_str) + " &ndash; " + _e(week_end_str))} '
             'was submitted automatically.', last=True)
        + _stats([('Total', _fmt_hours(total_hours)),
                  ('Billable', _fmt_hours(billable_hours))])
        + _p('Your manager will review it shortly. Need a change? Ask them to send '
             'it back to you.', last=True)
        + _btn(url, 'brand', 'View timesheet')
    )

    html = _wrap_html('brand', '', 'Timesheet auto-submitted', body,
                      subtitle=f'Week of {_e(week_start_str)}',
                      preheader='Your manager will review it shortly.')

    plain = f"""Hi {user_name},

Your timesheet for {week_start_str} - {week_end_str} was automatically submitted.

Total time: {_fmt_hours(total_hours)}
Billable time: {_fmt_hours(billable_hours)}

Your manager will review and approve it shortly.

View timesheet: {url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"Timesheet auto-submitted: week of {week_start_str}",
        html_content=html,
        plain_content=plain,
        categories=["auto_submit", "weekly"],
    )


# ---------- 7. (removed) ----------
# send_approval_notification had no callers: the approve/reject pair below
# replaced it, and the task that used to call it targeted a model that does
# not exist. Deleted rather than left as a template nobody renders.

# ---------- 8. Manager pending approvals ----------

def send_manager_pending_approvals(
    to_email: str,
    manager_name: str,
    week_start_str: str,
    timesheet_count: int,
    total_hours: float,
    summary_lines: list,
):
    """Notify managers of pending approvals."""
    url = _frontend_url() + "/timesheet?tab=approvals"
    sheets_word = 'timesheet is' if timesheet_count == 1 else 'timesheets are'

    lines_html = ''.join(
        f'<tr><td style="padding:10px 16px;border-bottom:1px solid {RULE};'
        f'color:{INK};font-size:14px;">{_e(line.strip().lstrip("• "))}</td></tr>'
        for line in summary_lines
    )

    body = (
        _p(f'Hi {_e(manager_name)},')
        + _p(f'{_strong(f"{timesheet_count} {sheets_word}")} waiting for your approval '
             f'for the week of {_strong(_e(week_start_str))}.', last=True)
        + _stats([('Timesheets', str(timesheet_count)),
                  ('Total time', _fmt_hours(total_hours))])
        + (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
           f'border="0" style="margin:16px 0;border:1px solid {RULE};border-radius:12px;'
           f'border-collapse:separate;overflow:hidden;">{lines_html}</table>'
           if lines_html else '')
        + _btn(url, 'brand', 'Review timesheets')
    )

    html = _wrap_html('brand', '', 'Approvals waiting', body,
                      subtitle=f'Week of {_e(week_start_str)}',
                      preheader=f'{timesheet_count} {sheets_word} waiting for you.')

    plain = f"""Hi {manager_name},

{timesheet_count} timesheets pending approval for week of {week_start_str} ({_fmt_hours(total_hours)} total):

{chr(10).join(summary_lines)}

Review timesheets: {url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"{timesheet_count} timesheet{'s' if timesheet_count != 1 else ''} "
                f"waiting for approval — week of {week_start_str}",
        html_content=html,
        plain_content=plain,
        categories=["manager_approval", "weekly"],
    )


# ---------- 9. Critical error alert ----------

def send_critical_error_alert(
    error_type: str,
    username: str,
    hostname: str,
    device_id: str,
    app_version: str,
    error_message: str,
    error_id: int,
):
    """Send critical agent error alert to admin."""
    admin_url = f"https://timetracker-api-k375.onrender.com/admin/tracker/agenterror/{error_id}/"

    plain = f"""Critical error from agent:

User: {username}
Host: {hostname}
Device: {device_id}
Version: {app_version}

Error: {error_message}

View details: {admin_url}"""

    body = (
        _rows([
            ('User', _e(username)),
            ('Host', _e(hostname)),
            ('Device', _e(device_id)),
            ('Version', _e(app_version)),
        ])
        + _label('Error')
        + f'<pre style="margin:6px 0 0;padding:12px 14px;background:#f8fafc;'
          f'border:1px solid {RULE};border-radius:10px;color:{INK};font-size:12px;'
          f'line-height:1.5;white-space:pre-wrap;word-break:break-word;'
          f'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;">'
          f'{_e(error_message)}</pre>'
        + _btn(admin_url, 'alert', 'Open in admin')
    )
    html = _wrap_html('alert', '', f'Critical agent error: {_e(error_type)}', body,
                      preheader=f'{_e(username)} on {_e(hostname)}')

    return send_email(
        to_email="dan@mavops.ai",
        subject=f"[TimeTracker] Critical Agent Error: {error_type}",
        html_content=html,
        plain_content=plain,
        categories=["error_alert", "critical"],
    )


# ---------- 10. Timesheet approved (standalone) ----------

def send_timesheet_approved(
    to_email: str,
    user_name: str,
    week_str: str,
    total_hours: float,
    approved_by: str,
):
    """Notify employee their timesheet was approved."""
    url = _frontend_url() + "/timesheet"

    body = (
        _p(f'Hi {_e(user_name)},')
        + _p(f'Your timesheet for {_strong(_e(week_str))} '
             f'({_fmt_hours(total_hours)}) was approved by {_e(approved_by)}. '
             'Nothing else to do.', last=True)
        + _btn(url, 'brand', 'View timesheet')
    )

    html = _wrap_html('brand', '', 'Timesheet approved', body,
                      subtitle=_e(week_str),
                      preheader=f'Approved by {_e(approved_by)}.')

    plain = f"""Hi {user_name},

Your timesheet for {week_str} ({_fmt_hours(total_hours)}) was approved by {approved_by}.

View timesheet: {url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"Timesheet approved for {week_str}",
        html_content=html,
        plain_content=plain,
        categories=["timesheet_approved"],
    )


# ---------- 11. Timesheet rejected (standalone) ----------

def send_timesheet_rejected(
    to_email: str,
    user_name: str,
    week_str: str,
    rejected_by: str,
    reason: str = "",
):
    """Notify employee their timesheet was rejected."""
    url = _frontend_url() + "/timesheet"
    reason_html = _panel(
        _label('Reason') + f'<div style="margin-top:4px;">{_e(reason)}</div>', 'warn',
    ) if reason else ''

    body = (
        _p(f'Hi {_e(user_name)},')
        + _p(f'Your timesheet for {_strong(_e(week_str))} was sent back by '
             f'{_e(rejected_by)}. Make the changes and submit it again.', last=True)
        + reason_html
        + _btn(url, 'brand', 'Revise timesheet')
    )

    html = _wrap_html('alert', '', 'Timesheet needs changes', body,
                      subtitle=_e(week_str),
                      preheader=f'Sent back by {_e(rejected_by)}.')

    plain = f"""Hi {user_name},

Your timesheet for {week_str} was sent back by {rejected_by}.
{f"{chr(10)}Reason: {reason}{chr(10)}" if reason else ""}
Revise timesheet: {url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"Timesheet needs changes for {week_str}",
        html_content=html,
        plain_content=plain,
        categories=["timesheet_rejected"],
    )


# ============================================================================
# RULE SUGGESTION NOTIFICATION
# ============================================================================

def send_rule_suggestion_notification(
    *,
    org_name: str,
    submitted_by: str,
    label: str,
    minutes: int,
    block_count: int,
    user_count: int,
    note: str = "",
    suggestion_id: int = None,
):
    """
    Notify Mavops that a firm user flagged an uncategorized activity as a
    candidate for a routing/categorization rule. Best-effort — callers wrap
    this in try/except so a failed email never blocks the suggestion saving.
    """
    hours = round((minutes or 0) / 60, 1)
    ref = f' (#{suggestion_id})' if suggestion_id else ''

    body = (
        _p(f'From {_strong(_e(submitted_by))} at {_strong(_e(org_name))}.', last=True)
        + _rows([
            ('Activity', _e(label)),
            ('Uncategorized time', f'{hours}h ({minutes} min)'),
            ('Blocks', str(block_count)),
            ('Employees affected', str(user_count)),
        ])
        + (_panel(_label('Note from submitter')
                  + f'<div style="margin-top:4px;">{_e(note)}</div>', 'brand')
           if note else '')
        + _fine(f'Review in Mavops Admin &rarr; Rule Suggestions{ref}.')
    )
    html = _wrap_html('brand', '', 'New rule suggestion', body,
                      preheader=f'{_e(label)} — {_e(org_name)}')

    plain = f"""New rule suggestion from {submitted_by} at {org_name}

Activity: {label}
Uncategorized time: {hours}h ({minutes} min)
Blocks: {block_count}
Employees affected: {user_count}
{f"{chr(10)}Note: {note}{chr(10)}" if note else ""}
Review in Mavops Admin → Rule Suggestions{ref}."""

    return send_email(
        to_email=getattr(settings, "SUGGESTIONS_NOTIFY_EMAIL", "support@mavops.ai"),
        subject=f"Rule suggestion from {org_name}: {label}",
        html_content=html,
        plain_content=plain,
        from_name="TimeTracker",
        categories=["rule_suggestion"],
    )


# ============================================================================
# SUPPORT TICKET
# ============================================================================

def send_support_ticket(*, ticket_id: int, subject: str, body: str,
                        user_email: str, org_name: str, org_id: int):
    """Forward an in-app support ticket to the support inbox.

    Replies go straight to the person who filed it.
    """
    plain = (
        f"From: {user_email} (org: {org_name}, id {org_id})\n\n"
        f"{body}\n\n"
        f"--- ticket #{ticket_id} ---"
    )
    html_body = (
        _rows([('From', _e(user_email)),
               ('Firm', f'{_e(org_name)} <span style="color:{INK_FAINT};'
                        f'font-weight:400;">(id {org_id})</span>')])
        + _label('Message')
        + f'<div style="margin-top:6px;padding:14px 16px;background:#f8fafc;'
          f'border:1px solid {RULE};border-radius:12px;color:{INK};font-size:14px;'
          f'line-height:1.6;white-space:pre-wrap;">{_e(body)}</div>'
        + _fine('Reply to this email to answer them directly.')
    )
    html = _wrap_html('brand', '', f'Support ticket #{ticket_id}', html_body,
                      subtitle=_e(subject), preheader=f'{_e(user_email)}: {_e(subject)}')
    return send_email(
        to_email="support@mavops.ai",
        subject=f"[TimeTracker support #{ticket_id}] {subject}",
        html_content=html,
        plain_content=plain,
        from_name="TimeTracker Support",
        reply_to=user_email or None,
        categories=["support_ticket"],
    )
