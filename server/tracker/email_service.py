# tracker/email_service.py
"""
Central email service using SendGrid REST API (raw HTTP, no SDK).
All transactional emails go through here.

Setup:
  1. Set SENDGRID_API_KEY in .env
  2. Set DEFAULT_FROM_EMAIL in settings.py (e.g., "noreply@mavops.ai")
"""

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
# One palette, defined once. Every template used to pass its own gradient, so
# fourteen emails from the same product arrived in fourteen different colour
# schemes. The only thing a caller now chooses is TONE — and only because a
# seat-overage warning and a rejected timesheet genuinely are not the same news
# as an invitation.
INK        = '#131a1e'
INK_SOFT   = '#47555c'
INK_FAINT  = '#7b8a91'
GROUND     = '#f4f5f4'
RULE       = '#e4e6e4'
TEAL       = '#1F7269'
AMBER      = '#a8641f'
RED        = '#b3392f'

TONES = {'brand': TEAL, 'warn': AMBER, 'alert': RED}

FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")


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
    header or a run of whitespace. It is the second thing a person reads and it
    was going to waste on every email we send. The padding run stops the client
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
               preheader=''):
    """The one shell every email uses.

    The signature is unchanged so the existing callers keep working, but the
    first argument is now a TONE ('brand' / 'warn' / 'alert'). A legacy CSS
    gradient string maps onto a tone rather than being honoured, because
    per-email gradients are exactly what made the set look unrelated.

    header_icon is accepted and ignored. An emoji in an H1 dates an email
    instantly, and the title already says the same thing in words.
    """
    accent = _accent_for(tone_or_gradient)
    head = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<title>' + str(header_title) + '</title></head>'
    )
    return (
        head +
        '<body style="margin:0;padding:0;background:' + GROUND +
        ';font-family:' + FONT + ';-webkit-font-smoothing:antialiased;">'
        + _preheader(preheader) +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="background:' + GROUND + ';">'
        '<tr><td align="center" style="padding:32px 16px;">'

        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="max-width:600px;background:#ffffff;border:1px solid '
        + RULE + ';border-radius:14px;overflow:hidden;">'

        # Wordmark bar: a slim band of brand rather than a gradient block with
        # an emoji in it. Gradients render unpredictably across clients, and
        # the emoji carried nothing the title did not already carry.
        '<tr><td style="background:' + TEAL + ';padding:14px 28px;">'
        '<span style="color:#ffffff;font-size:15px;font-weight:700;'
        'letter-spacing:-0.01em;">TimeTracker</span>'
        '<span style="color:rgba(255,255,255,0.72);font-size:12px;">'
        ' by MavOps</span></td></tr>'

        # The only per-email colour, and only where the news genuinely differs.
        '<tr><td style="height:3px;background:' + accent +
        ';font-size:0;line-height:0;">&nbsp;</td></tr>'

        '<tr><td style="padding:30px 28px 8px;">'
        '<h1 style="margin:0;color:' + INK + ';font-size:21px;line-height:1.25;'
        'font-weight:700;letter-spacing:-0.01em;">' + str(header_title) + '</h1>'
        '</td></tr>'

        '<tr><td style="padding:4px 28px 28px;color:' + INK_SOFT +
        ';font-size:15px;line-height:1.55;">' + body_html + '</td></tr>'

        '</table>'

        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' border="0" style="max-width:600px;"><tr>'
        '<td style="padding:16px 28px 0;text-align:center;color:' + INK_FAINT +
        ';font-size:12px;line-height:1.5;">TimeTracker by MavOps &middot; '
        '<a href="mailto:info@mavops.ai" style="color:' + TEAL +
        ';text-decoration:none;">info@mavops.ai</a></td></tr></table>'

        '</td></tr></table></body></html>'
    )


def _btn(url, gradient, text):
    """One button style.

    The gradient argument is kept for existing callers and ignored: Outlook
    drops CSS gradients entirely, which was rendering white text on a white
    button. A solid fill in a table cell renders identically everywhere.
    """
    bg = _accent_for(gradient)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:26px 0 10px;"><tr>'
        '<td style="border-radius:10px;background:' + bg + ';">'
        '<a href="' + url + '" style="display:inline-block;padding:13px 26px;'
        'color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;'
        'border-radius:10px;">' + text + '</a>'
        '</td></tr></table>'
    )


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
    login_url = login_url or f"{getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')}/login"
    invite_line = f"{invited_by} has added you" if invited_by else "You've been added"

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {username}!</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            {invite_line} to <strong>{org_name}</strong> on TimeTracker.
        </p>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:16px 0;">
            <p style="margin:0 0 4px;color:#64748b;font-size:13px;">Your account:</p>
            <p style="margin:0;color:#1e293b;font-size:15px;"><strong>Username:</strong> {username}</p>
            <p style="margin:8px 0 0;color:#64748b;font-size:13px;">
                Use your existing TimeTracker password to log in.
            </p>
        </div>
        {_btn(login_url, "#2B9D90 0%,#237F74 100%", "Log In to TimeTracker &rarr;")}
        <p style="color:#94a3b8;font-size:12px;text-align:center;margin-bottom:0;">TimeTracker by MavOps</p>'''

    html = _wrap_html("#2B9D90 0%,#237F74 100%", "🎉", f"You've been added to {org_name}!", body)

    plain = f"""Hi {username}!

{invite_line} to {org_name} on TimeTracker.

Log in at: {login_url}
Username: {username}
Password: Use your existing TimeTracker password

- TimeTracker by MavOps"""

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
    billing_url = f"{getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')}/account/billing"
    over_by = max(0, member_count - seat_count)

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">
            Your team on <strong>{org_name}</strong> has grown past your plan.
        </p>
        <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:16px;margin:16px 0;">
            <p style="margin:0;color:#92400e;font-size:15px;">
                <strong>{member_count} members</strong> on <strong>{seat_count} paid seat{'s' if seat_count != 1 else ''}</strong>
                &mdash; {over_by} over your limit.
            </p>
            <p style="margin:8px 0 0;color:#92400e;font-size:13px;">
                You have <strong>{grace_days} days</strong> to add seats. After that, the
                {over_by} most recently added member{'s' if over_by != 1 else ''} will be paused until you do.
            </p>
        </div>
        {_btn(billing_url, "#2B9D90 0%,#237F74 100%", "Add seats &rarr;")}
        <p style="color:#94a3b8;font-size:12px;text-align:center;margin-bottom:0;">TimeTracker by MavOps</p>'''

    html = _wrap_html("#F59E0B 0%,#D97706 100%", "⚠️", "You're over your seat count", body)

    plain = f"""Your team on {org_name} has grown past your plan.

{member_count} members on {seat_count} paid seats — {over_by} over your limit.

You have {grace_days} days to add seats. After that, the {over_by} most recently
added members will be paused until you do.

Add seats: {billing_url}

- TimeTracker by MavOps"""

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

    Order matters. Set password -> land in the app -> download -> pair. The
    download used to come first, which left people staring at an agent they
    could not sign into yet.
    """
    help_url = f"{getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')}/help"
    who = f"{invited_by} has invited you" if invited_by else "You have been invited"

    plain = f"""{who} to join {org_name} on TimeTracker.

Open this link to choose a password and finish setup:
{invite_url}

It works once and expires in {expires_days} days.

What happens next:
  1. Choose your password (30 seconds)
  2. We walk you through installing the desktop app
  3. Your billable time starts capturing automatically

Questions? {help_url} or reply to this email.

- The TimeTracker Team"""

    steps = "".join(
        f'<tr><td style="padding:0 0 14px;">'
        f'<span style="display:inline-block;width:22px;color:{TEAL};'
        f'font-weight:700;">{n}.</span>'
        f'<span style="color:{INK};font-weight:600;">{t}</span><br>'
        f'<span style="display:inline-block;width:22px;">&nbsp;</span>'
        f'<span style="color:{INK_FAINT};font-size:14px;">{d}</span>'
        f'</td></tr>'
        for n, t, d in [
            (1, 'Choose your password', 'You pick it &mdash; we never email one.'),
            (2, 'Install the desktop app',
                'We hand you the right download and a code to connect it.'),
            (3, 'Your time starts capturing',
                'It runs quietly in the background and sorts work by client.'),
        ]
    )

    body = (
        f'<p style="margin:0 0 6px;">{who} to join '
        f'<strong style="color:{INK};">{org_name}</strong>.</p>'
        f'<p style="margin:0;">TimeTracker captures your billable time '
        f'automatically, so you never have to remember to log hours. Setup '
        f'takes about two minutes.</p>'
        + _btn(invite_url, 'brand', 'Set your password')
        + f'<p style="margin:0 0 22px;color:{INK_FAINT};font-size:13px;">'
        f'This link works once and expires in {expires_days} days.</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="100%" style="border-top:1px solid {RULE};padding-top:20px;">'
        f'<tr><td style="padding:20px 0 12px;color:{INK};font-weight:600;">'
        f'What happens next</td></tr>{steps}</table>'
        f'<p style="margin:18px 0 0;color:{INK_FAINT};font-size:13px;'
        f'word-break:break-all;">Button not working? Paste this into your '
        f'browser:<br>{invite_url}</p>'
    )

    html = _wrap_html(
        'brand', '', f'Welcome to {org_name}', body,
        preheader='Choose a password and finish setup — takes about two minutes.',
    )

    return send_email(
        to_email=to_email,
        subject=f"You've been invited to join {org_name} on TimeTracker",
        html_content=html,
        plain_content=plain,
        categories=["invitation", "onboarding"],
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

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            Someone asked to reset the password for your <strong>{org_name}</strong> TimeTracker account.
        </p>
        {_btn(reset_url, "#2B9D90 0%,#237F74 100%", "Choose a new password &rarr;")}
        <p style="color:#94a3b8;font-size:13px;text-align:center;margin-top:-8px;">
            Expires in {expires_hours} hours &middot; works once
        </p>
        <p style="color:#64748b;font-size:14px;line-height:1.5;margin-top:24px;">
            If this wasn't you, you can ignore this email — nothing has changed.
        </p>
        <p style="color:#94a3b8;font-size:12px;word-break:break-all;margin-top:16px;">
            Button not working? Paste this into your browser:<br>{reset_url}
        </p>'''

    html = _wrap_html("#2B9D90 0%,#237F74 100%", "\U0001F511", "Reset your password", body)

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
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')
    if not review_url:
        review_url = f'{frontend_url}/daily?date={date_iso}' if date_iso else f'{frontend_url}/daily'

    client_rows = ''.join([
        f'<tr>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e2e8f0;">{name}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:bold;">{_fmt_hours(hrs)}</td>'
        f'</tr>'
        for name, hrs in client_breakdown
    ]) or '<tr><td colspan="2" style="padding:8px 0;color:#94a3b8;">No clients assigned yet</td></tr>'

    unassigned_html = f'''<div style="background:#fef3c7;border:1px solid #fcd34d;padding:12px 16px;border-radius:8px;margin:16px 0;">
        <p style="margin:0;color:#92400e;font-size:14px;">⚠️ <strong>{unassigned_count} block{"s" if unassigned_count != 1 else ""}</strong> need client assignment</p>
    </div>''' if unassigned_count else ''

    if total_hours < 0.1:
        body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <div style="background:#fef3c7;border:1px solid #fcd34d;padding:16px;border-radius:8px;margin:16px 0;">
            <p style="margin:0;color:#92400e;font-size:16px;font-weight:bold;">⚠️ No time was tracked on {date_str}</p>
            <p style="margin:8px 0 0;color:#92400e;font-size:14px;">If you worked yesterday, please check that your desktop agent is running.</p>
        </div>
        {_btn(review_url, "#2B9D90 0%,#237F74 100%", "Review Timesheet &rarr;")}
        <p style="color:#94a3b8;font-size:12px;text-align:center;margin-bottom:0;">
            <a href="{frontend_url}/settings" style="color:#94a3b8;">Manage notification preferences</a>
        </p>'''
        plain = f"""Hi {user_name},

No time was tracked on {date_str}. If you worked yesterday, please check that your desktop agent is running.

Check your timesheet: {review_url}

- TimeTracker"""
    else:
        body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            You tracked <strong style="color:#2B9D90;">{_fmt_hours(total_hours)}</strong> on {date_str} that need review:
        </p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">{client_rows}</table>
        {unassigned_html}
        {_btn(review_url, "#2B9D90 0%,#237F74 100%", "Review Timesheet &rarr;")}
        <p style="color:#94a3b8;font-size:12px;text-align:center;margin-bottom:0;">
            <a href="{frontend_url}/settings" style="color:#94a3b8;">Manage notification preferences</a>
        </p>'''
        plain = f"""Hi {user_name},

You tracked {_fmt_hours(total_hours)} on {date_str} that need review:

{chr(10).join([f'  - {name}: {_fmt_hours(hrs)}' for name, hrs in client_breakdown])}
{"⚠️ " + str(unassigned_count) + " blocks need client assignment." if unassigned_count else ""}

Review your timesheet: {review_url}

- TimeTracker"""

    subj = f"⚠️ No time tracked on {date_str}" if total_hours < 0.1 else f"⏰ Review your time for {date_str}"
    html = _wrap_html("#2B9D90 0%,#237F74 100%", "⏰", "Review Your Time", body)

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
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')
    report_url = f'{frontend_url}/billing?week={week_start_iso}' if week_start_iso else f'{frontend_url}/billing'

    client_rows = ''.join([
        f'<tr>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e2e8f0;">{name}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:bold;">{_fmt_hours(hrs)}</td>'
        f'</tr>'
        for name, hrs in client_breakdown[:10]
    ]) or '<tr><td colspan="2" style="padding:8px 0;color:#94a3b8;">No clients tracked this week</td></tr>'

    body = f'''
    <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
    <p style="color:#475569;font-size:16px;line-height:1.5;">
        Here's your weekly summary for <strong>{week_str}</strong>:
    </p>
    <div style="background:#f0fdfa;border:1px solid #99f6e4;padding:16px;border-radius:8px;margin:16px 0;text-align:center;">
        <p style="margin:0;color:#0f766e;font-size:14px;">Total Time</p>
        <p style="margin:4px 0 0;color:#2B9D90;font-size:32px;font-weight:bold;">{_fmt_hours(total_hours)}</p>
    </div>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;">{client_rows}</table>
    {_btn(report_url, "#2B9D90 0%,#237F74 100%", "View Full Report &rarr;")}
    <p style="color:#94a3b8;font-size:12px;text-align:center;margin-bottom:0;">
        <a href="{frontend_url}/settings" style="color:#94a3b8;">Manage notification preferences</a>
    </p>'''

    html = _wrap_html("#2B9D90 0%,#237F74 100%", "📊", "Weekly Summary", body)

    plain = f"""Hi {user_name},

Weekly time summary for {week_str}:

Total: {_fmt_hours(total_hours)}

By Client:
{chr(10).join([f'  - {name}: {_fmt_hours(hrs)}' for name, hrs in client_breakdown[:10]])}

View full report: {report_url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"📊 Weekly Summary: {_fmt_hours(total_hours)} ({week_str})",
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
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    auto_warn_html = '''<div style="background:#fef3c7;border:1px solid #fcd34d;padding:12px 16px;border-radius:8px;margin:16px 0;">
        <p style="margin:0;color:#92400e;font-size:14px;">⚠️ If not submitted by end of day, it will be <strong>auto-submitted Tuesday 9am</strong>.</p>
    </div>''' if auto_submit_enabled else ''

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            Your timesheet for <strong>{week_start_str} - {week_end_str}</strong> hasn't been submitted yet.
        </p>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:16px 0;">
            <p style="margin:0;color:#1e293b;font-size:15px;">📊 <strong>{_fmt_hours(total_hours)}</strong> tracked &middot; {block_count} time blocks</p>
        </div>
        {auto_warn_html}
        {_btn(frontend_url + "/timesheet?tab=timesheet" + (f"&week={week_start_iso}" if week_start_iso else ""), "#2B9D90 0%,#237F74 100%", "Review &amp; Submit &rarr;")}'''

    html = _wrap_html("#2B9D90 0%,#237F74 100%", "⏰", "Submit Your Timesheet", body)

    plain = f"""Hi {user_name},

Your timesheet for {week_start_str} - {week_end_str} has not been submitted yet.

Summary:
- {_fmt_hours(total_hours)} tracked
- {block_count} time blocks

Please review and submit by end of day today.
{"It will be auto-submitted Tuesday 9am if not submitted." if auto_submit_enabled else ""}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"⏰ Timesheet Reminder: Week of {week_start_str}",
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
    """Notify user their timesheet was auto-submitted on Tuesday."""
    try:
        total_amount_fmt = f"{float(total_amount):,.2f}"
    except (TypeError, ValueError):
        total_amount_fmt = "0.00"
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            Your timesheet for <strong>{week_start_str} - {week_end_str}</strong> was automatically submitted.
        </p>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:16px 0;">
            <p style="margin:0 0 4px;color:#1e293b;font-size:15px;">Total time: <strong>{_fmt_hours(total_hours)}</strong></p>
            <p style="margin:0 0 4px;color:#1e293b;font-size:15px;">Billable time: <strong>{_fmt_hours(billable_hours)}</strong></p>
            <p style="margin:0;color:#1e293b;font-size:15px;">Amount: <strong>${total_amount_fmt}</strong></p>
        </div>
        <p style="color:#64748b;font-size:14px;">Your manager will review shortly. Need changes? Ask your manager to send it back.</p>
        {_btn(frontend_url + "/timesheet", "#2B9D90 0%,#237F74 100%", "View Timesheet &rarr;")}'''

    html = _wrap_html("#2B9D90 0%,#237F74 100%", "✅", "Timesheet Auto-Submitted", body)

    plain = f"""Hi {user_name},

Your timesheet for {week_start_str} - {week_end_str} was automatically submitted.

Total time: {_fmt_hours(total_hours)}
Billable time: {_fmt_hours(billable_hours)}
Amount: ${total_amount_fmt}

Your manager will review and approve it shortly.

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"✅ Timesheet Auto-Submitted: Week of {week_start_str}",
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
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    rows_html = ''.join([
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;font-size:14px;">{line.strip().lstrip("• ")}</td></tr>'
        for line in summary_lines
    ])

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {manager_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            <strong>{timesheet_count} timesheets</strong> are pending approval for the week of <strong>{week_start_str}</strong> ({_fmt_hours(total_hours)} total).
        </p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;background:#f8fafc;border-radius:8px;">{rows_html}</table>
        {_btn(frontend_url + "/timesheet?tab=approvals", "#2B9D90 0%,#237F74 100%", "Review Timesheets &rarr;")}'''

    html = _wrap_html("#2B9D90 0%,#237F74 100%", "📋", "Approvals Pending", body)

    plain = f"""Hi {manager_name},

{timesheet_count} timesheets pending approval for week of {week_start_str} ({_fmt_hours(total_hours)} total):

{chr(10).join(summary_lines)}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"📋 {timesheet_count} Timesheets Pending Approval - Week of {week_start_str}",
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

    return send_email(
        to_email="dan@mavops.ai",
        subject=f"[TimeTracker] Critical Agent Error: {error_type}",
        html_content=f"<pre>{plain}</pre>",
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
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            Your timesheet for <strong>{week_str}</strong> ({_fmt_hours(total_hours)}) has been approved by {approved_by}.
        </p>
        {_btn(frontend_url + "/timesheet", "#2B9D90 0%,#237F74 100%", "View Timesheet &rarr;")}'''

    html = _wrap_html("#2B9D90 0%,#237F74 100%", "✅", "Timesheet Approved", body)

    return send_email(
        to_email=to_email,
        subject=f"✅ Timesheet approved for {week_str}",
        html_content=html,
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
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')
    reason_html = f'<p style="color:#92400e;font-size:14px;background:#fef3c7;padding:12px;border-radius:8px;">Reason: {reason}</p>' if reason else ''

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            Your timesheet for <strong>{week_str}</strong> was sent back by {rejected_by}.
        </p>
        {reason_html}
        {_btn(frontend_url + "/timesheet", "#ef4444 0%,#dc2626 100%", "Revise Timesheet &rarr;")}'''

    html = _wrap_html("#ef4444 0%,#dc2626 100%", "⚠️", "Timesheet Needs Revision", body)

    return send_email(
        to_email=to_email,
        subject=f"⚠️ Timesheet needs revision for {week_str}",
        html_content=html,
        categories=["timesheet_rejected"],
    )

# ============================================================================
# RULE SUGGESTION NOTIFICATION
# ============================================================================
# Append this function to tracker/email_service.py.

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
    Notify MavOps that a firm user flagged an uncategorized activity as a
    candidate for a routing/categorization rule. Best-effort — callers wrap
    this in try/except so a failed email never blocks the suggestion saving.
    """
    hours = round((minutes or 0) / 60, 1)
    note_html = (
        f'<p style="margin:12px 0;padding:10px;background:#f8fafc;border-left:3px solid #8b5cf6;">'
        f'<strong>Note from submitter:</strong><br>{note}</p>'
        if note else ""
    )
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:520px;">
      <h2 style="color:#7c3aed;margin-bottom:4px;">New rule suggestion</h2>
      <p style="color:#64748b;margin-top:0;">From <strong>{submitted_by}</strong> at <strong>{org_name}</strong></p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr><td style="padding:6px 0;color:#64748b;">Activity</td><td style="padding:6px 0;font-weight:600;">{label}</td></tr>
        <tr><td style="padding:6px 0;color:#64748b;">Uncategorized time</td><td style="padding:6px 0;">{hours}h ({minutes} min)</td></tr>
        <tr><td style="padding:6px 0;color:#64748b;">Blocks</td><td style="padding:6px 0;">{block_count}</td></tr>
        <tr><td style="padding:6px 0;color:#64748b;">Employees affected</td><td style="padding:6px 0;">{user_count}</td></tr>
      </table>
      {note_html}
      <p style="color:#94a3b8;font-size:12px;margin-top:16px;">
        Review in MavOps Admin → Rule Suggestions{f' (#{suggestion_id})' if suggestion_id else ''}.
      </p>
    </div>
    """
    return send_email(
        to_email=getattr(settings, "SUGGESTIONS_NOTIFY_EMAIL", "support@mavops.ai"),
        subject=f"Rule suggestion from {org_name}: {label}",
        html_content=html,
        from_name="TimeTracker",
        categories=["rule_suggestion"],
    )