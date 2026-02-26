# tracker/email_service.py
"""
Central email service using SendGrid SDK.
All transactional emails go through here.

Setup:
  1. pip install sendgrid (add to requirements.txt)
  2. Set SENDGRID_API_KEY in .env
  3. Set DEFAULT_FROM_EMAIL in settings.py (e.g., "noreply@mavops.ai")
"""

import logging
from django.conf import settings
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, ReplyTo
)

logger = logging.getLogger(__name__)

# ============================================================================
# CORE SEND FUNCTION
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
    Send a transactional email via SendGrid.
    
    Returns:
        True if sent successfully, False otherwise
    """
    api_key = getattr(settings, 'SENDGRID_API_KEY', None)
    if not api_key:
        logger.error("[EMAIL] SENDGRID_API_KEY not configured - email not sent")
        return False

    from_email = from_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@mavops.ai')
    reply_to = reply_to or getattr(settings, 'DEFAULT_REPLY_TO_EMAIL', 'dan@mavops.ai')

    plain_text = plain_content or _strip_html(html_content)

    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        plain_text_content=plain_text,
        html_content=html_content,
    )

    if reply_to:
        message.reply_to = ReplyTo(reply_to)

    if categories:
        for cat in categories:
            message.add_category(cat)

    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info(f"[EMAIL] Sent to {to_email} - status: {response.status_code} - subject: {subject[:50]}")
        return response.status_code in (200, 201, 202)
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


# ============================================================================
# SHARED HTML WRAPPER
# ============================================================================

def _wrap_html(header_gradient, header_icon, header_title, body_html):
    """Wrap body content in standard email template."""
    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:500px;margin:0 auto;padding:20px;">
    <div style="background:linear-gradient(135deg,{header_gradient});padding:24px;border-radius:16px 16px 0 0;text-align:center;">
        <h1 style="margin:0;color:white;font-size:24px;">{header_icon} {header_title}</h1>
    </div>
    <div style="background:white;padding:24px;border-radius:0 0 16px 16px;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);">
        {body_html}
    </div>
</div>
</body></html>'''


def _btn(url, gradient, text):
    """Generate a CTA button."""
    return f'''<div style="text-align:center;margin:24px 0;">
    <a href="{url}" style="display:inline-block;background:linear-gradient(135deg,{gradient});color:white;padding:14px 28px;border-radius:10px;text-decoration:none;font-weight:bold;font-size:16px;">{text}</a>
</div>'''


# ============================================================================
# PRE-BUILT EMAIL TEMPLATES
# ============================================================================

# ---------- 1. Team invitation (simple - used by views.py settings_team_invite) ----------

def send_team_invitation(
    to_email: str,
    org_name: str,
    username: str,
    temp_password: str,
    invited_by: str = None,
    login_url: str = None,
):
    """Send team member invitation email."""
    login_url = login_url or f"{getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')}/login"

    invite_line = f"{invited_by} has invited you" if invited_by else "You've been invited"

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi there!</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            {invite_line} to join <strong>{org_name}</strong> on TimeTracker.
        </p>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:16px 0;">
            <p style="margin:0 0 8px;color:#64748b;font-size:13px;">Your login credentials:</p>
            <p style="margin:0 0 4px;color:#1e293b;font-size:15px;"><strong>Username:</strong> {username}</p>
            <p style="margin:0;color:#1e293b;font-size:15px;"><strong>Temporary Password:</strong> {temp_password}</p>
        </div>
        <p style="color:#94a3b8;font-size:13px;">Please change your password after logging in.</p>
        {_btn(login_url, "#3b82f6 0%,#1d4ed8 100%", "Log In to TimeTracker &rarr;")}
        <p style="color:#94a3b8;font-size:12px;text-align:center;margin-bottom:0;">TimeTracker by MavOps</p>'''

    html = _wrap_html("#3b82f6 0%,#1d4ed8 100%", "🎉", "You're Invited!", body)

    plain = f"""Hi!

{invite_line} to join {org_name} on TimeTracker.

Login at: {login_url}
Username: {username}
Temporary Password: {temp_password}

Please change your password after logging in.

- TimeTracker by MavOps"""

    return send_email(
        to_email=to_email,
        subject=f"You're invited to {org_name} on TimeTracker",
        html_content=html,
        plain_content=plain,
        categories=["invitation", "onboarding"],
    )


# ---------- 2. Onboarding invitation (rich - used by views_onboarding.py) ----------

def send_onboarding_invitation(
    to_email: str,
    org_name: str,
    temp_password: str,
    invited_by: str = None,
):
    """Send rich onboarding invitation with download links."""
    app_url = getattr(settings, 'APP_URL', 'https://timetracker.mavops.ai')
    help_url = f"{app_url}/help"
    mac_url = 'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker.pkg'
    win_url = 'https://github.com/druss16/timetracker-releases/releases/latest/download/TimeTracker-Windows-Setup.exe'
    invite_line = f"{invited_by} has invited" if invited_by else "You've been invited"

    plain = f"""Welcome to TimeTracker!

{invite_line} you to join {org_name} on TimeTracker.

GET STARTED IN 2 MINUTES

1. DOWNLOAD THE APP
   Mac: {mac_url}
   Windows: {win_url}

2. SIGN IN
   Email: {to_email}
   Password: {temp_password}

3. YOU'RE DONE! The app captures your billable time automatically.

Questions? Visit {help_url} or reply to this email.

- The TimeTracker Team"""

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;">
<tr><td align="center" style="padding:40px 20px;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.05);">
    <tr><td style="background:linear-gradient(135deg,#14b8a6 0%,#0d9488 100%);padding:40px 40px 30px;text-align:center;">
        <div style="width:60px;height:60px;background:rgba(255,255,255,0.2);border-radius:16px;margin:0 auto 20px;line-height:60px;"><span style="font-size:28px;">⏱️</span></div>
        <h1 style="margin:0;color:#fff;font-size:28px;font-weight:700;">Welcome to TimeTracker!</h1>
        <p style="margin:12px 0 0;color:rgba(255,255,255,0.9);font-size:16px;">{f"{invited_by} has invited you to join" if invited_by else "You've been invited to join"}</p>
        <p style="margin:4px 0 0;color:#fff;font-size:20px;font-weight:600;">{org_name}</p>
    </td></tr>
    <tr><td style="padding:40px;">
        <p style="margin:0 0 30px;color:#475569;font-size:16px;line-height:1.6;">TimeTracker automatically captures your billable time so you never forget to log hours again. Get started in just 2 minutes.</p>
        <!-- Step 1 -->
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:24px;"><tr>
            <td width="44" valign="top"><div style="width:36px;height:36px;background:#ccfbf1;border-radius:50%;text-align:center;line-height:36px;color:#0d9488;font-weight:700;font-size:16px;">1</div></td>
            <td valign="top" style="padding-left:12px;">
                <h3 style="margin:0 0 12px;color:#1e293b;font-size:16px;font-weight:600;">Download the Desktop App</h3>
                <table role="presentation" cellspacing="0" cellpadding="0"><tr>
                    <td style="padding-right:12px;padding-bottom:8px;"><a href="{mac_url}" style="display:inline-block;background:#1e293b;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;font-size:14px;">🍎 Download for Mac</a></td>
                    <td style="padding-bottom:8px;"><a href="{win_url}" style="display:inline-block;background:#0078d4;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;font-size:14px;">⊞ Download for Windows</a></td>
                </tr></table>
            </td>
        </tr></table>
        <!-- Step 2 -->
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:24px;"><tr>
            <td width="44" valign="top"><div style="width:36px;height:36px;background:#ccfbf1;border-radius:50%;text-align:center;line-height:36px;color:#0d9488;font-weight:700;font-size:16px;">2</div></td>
            <td valign="top" style="padding-left:12px;">
                <h3 style="margin:0 0 12px;color:#1e293b;font-size:16px;font-weight:600;">Sign in with these credentials</h3>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;"><tr><td style="padding:16px;">
                    <p style="margin:0 0 8px;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Email</p>
                    <p style="margin:0 0 16px;color:#1e293b;font-size:15px;font-weight:500;font-family:monospace;">{to_email}</p>
                    <p style="margin:0 0 8px;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;font-weight:600;">Temporary Password</p>
                    <p style="margin:0;color:#1e293b;font-size:15px;font-weight:500;font-family:monospace;">{temp_password}</p>
                </td></tr></table>
            </td>
        </tr></table>
        <!-- Step 3 -->
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:32px;"><tr>
            <td width="44" valign="top"><div style="width:36px;height:36px;background:#ccfbf1;border-radius:50%;text-align:center;line-height:36px;color:#0d9488;font-weight:700;font-size:16px;">3</div></td>
            <td valign="top" style="padding-left:12px;">
                <h3 style="margin:0 0 8px;color:#1e293b;font-size:16px;font-weight:600;">You're done! 🎉</h3>
                <p style="margin:0;color:#475569;font-size:14px;line-height:1.5;">The app runs quietly in the background and captures your billable time automatically.</p>
            </td>
        </tr></table>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:32px 0;">
        <h3 style="margin:0 0 16px;color:#1e293b;font-size:16px;font-weight:600;">What happens next?</h3>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
            <tr><td style="padding:8px 0;color:#475569;font-size:14px;"><span style="color:#14b8a6;margin-right:8px;">✓</span> Your time is automatically categorized by client and task</td></tr>
            <tr><td style="padding:8px 0;color:#475569;font-size:14px;"><span style="color:#14b8a6;margin-right:8px;">✓</span> Review and submit your timesheet each week</td></tr>
            <tr><td style="padding:8px 0;color:#475569;font-size:14px;"><span style="color:#14b8a6;margin-right:8px;">✓</span> No more forgetting to log hours!</td></tr>
        </table>
    </td></tr>
    <tr><td style="background:#f8fafc;padding:24px 40px;border-top:1px solid #e2e8f0;">
        <p style="margin:0;color:#64748b;font-size:14px;text-align:center;">Questions? <a href="{help_url}" style="color:#14b8a6;text-decoration:none;font-weight:500;">Visit our Help Center</a> or reply to this email.</p>
    </td></tr>
</table>
<p style="margin:24px 0 0;color:#94a3b8;font-size:12px;text-align:center;">&copy; 2026 TimeTracker by MavOps</p>
</td></tr></table>
</body></html>'''

    return send_email(
        to_email=to_email,
        subject=f"You've been invited to join {org_name} on TimeTracker",
        html_content=html,
        plain_content=plain,
        categories=["invitation", "onboarding"],
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
):
    """
    Send daily timesheet review reminder.
    Used by: tasks.py send_daily_timesheet_reminders_task
             views_notifications.py send_daily_timesheet_reminders
    """
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')
    review_url = review_url or f'{frontend_url}/timesheet'

    client_rows = ''.join([
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #e2e8f0;">{name}</td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:bold;">{hrs:.1f}h</td></tr>'
        for name, hrs in client_breakdown
    ]) or '<tr><td colspan="2" style="padding:8px 0;color:#94a3b8;">No clients assigned yet</td></tr>'

    unassigned_html = f'''<div style="background:#fef3c7;border:1px solid #fcd34d;padding:12px 16px;border-radius:8px;margin:16px 0;">
        <p style="margin:0;color:#92400e;font-size:14px;">⚠️ <strong>{unassigned_count} block{"s" if unassigned_count != 1 else ""}</strong> need client assignment</p>
    </div>''' if unassigned_count else ''

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            You tracked <strong style="color:#ea580c;">{total_hours:.1f} hours</strong> on {date_str} that need review:
        </p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;">{client_rows}</table>
        {unassigned_html}
        {_btn(review_url, "#f59e0b 0%,#ea580c 100%", "Review Timesheet &rarr;")}
        <p style="color:#94a3b8;font-size:12px;text-align:center;margin-bottom:0;">
            <a href="{frontend_url}/settings" style="color:#94a3b8;">Manage notification preferences</a>
        </p>'''

    html = _wrap_html("#f59e0b 0%,#ea580c 100%", "⏰", "Review Your Time", body)

    plain = f"""Hi {user_name},

You tracked {total_hours:.1f} hours on {date_str} that need review:

{chr(10).join([f'  - {name}: {hrs:.1f}h' for name, hrs in client_breakdown])}
{"⚠️ " + str(unassigned_count) + " blocks need client assignment." if unassigned_count else ""}

Review your timesheet: {review_url}

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"⏰ Review your time for {date_str}",
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
):
    """
    Send weekly time summary email.
    Used by: tasks.py send_weekly_summary_task
             views_notifications.py send_weekly_summary
    """
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')
    client_lines = '\n'.join([f'  - {name}: {hrs:.1f}h' for name, hrs in client_breakdown[:10]])

    plain = f"""Hi {user_name},

Weekly time summary for {week_str}:

Total: {total_hours:.1f} hours

By Client:
{client_lines}

View detailed report: {frontend_url}/reports

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"📊 Weekly Summary: {total_hours:.1f} hours ({week_str})",
        html_content=f"<pre>{plain}</pre>",
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
):
    """
    Monday reminder to submit last week's timesheet.
    Used by: tasks.py send_timesheet_reminders
    """
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            Your timesheet for <strong>{week_start_str} - {week_end_str}</strong> hasn't been submitted yet.
        </p>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:16px 0;">
            <p style="margin:0;color:#1e293b;font-size:15px;">📊 <strong>{total_hours} hours</strong> tracked &middot; {block_count} time blocks</p>
        </div>
        <div style="background:#fef3c7;border:1px solid #fcd34d;padding:12px 16px;border-radius:8px;margin:16px 0;">
            <p style="margin:0;color:#92400e;font-size:14px;">⚠️ If not submitted by end of day, it will be <strong>auto-submitted Tuesday 9am</strong>.</p>
        </div>
        {_btn(frontend_url + "/timesheet", "#8b5cf6 0%,#7c3aed 100%", "Review &amp; Submit &rarr;")}'''

    html = _wrap_html("#8b5cf6 0%,#7c3aed 100%", "⏰", "Submit Your Timesheet", body)

    plain = f"""Hi {user_name},

Your timesheet for {week_start_str} - {week_end_str} has not been submitted yet.

Summary:
- {total_hours} hours tracked
- {block_count} time blocks

Please review and submit by end of day today.
If not submitted, it will be auto-submitted Tuesday 9am.

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
    """
    Notify user their timesheet was auto-submitted.
    Used by: tasks.py auto_submit_timesheets
    """
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            Your timesheet for <strong>{week_start_str} - {week_end_str}</strong> was automatically submitted.
        </p>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin:16px 0;">
            <p style="margin:0 0 4px;color:#1e293b;font-size:15px;">Total hours: <strong>{total_hours}</strong></p>
            <p style="margin:0 0 4px;color:#1e293b;font-size:15px;">Billable hours: <strong>{billable_hours}</strong></p>
            <p style="margin:0;color:#1e293b;font-size:15px;">Amount: <strong>${total_amount}</strong></p>
        </div>
        <p style="color:#64748b;font-size:14px;">Your manager will review shortly. Need changes? Ask your manager to send it back.</p>
        {_btn(frontend_url + "/timesheet", "#06b6d4 0%,#0891b2 100%", "View Timesheet &rarr;")}'''

    html = _wrap_html("#06b6d4 0%,#0891b2 100%", "✅", "Timesheet Auto-Submitted", body)

    plain = f"""Hi {user_name},

Your timesheet for {week_start_str} - {week_end_str} was automatically submitted.

Total hours: {total_hours}
Billable hours: {billable_hours}
Amount: ${total_amount}

Your manager will review and approve it shortly.

- TimeTracker"""

    return send_email(
        to_email=to_email,
        subject=f"✅ Timesheet Auto-Submitted: Week of {week_start_str}",
        html_content=html,
        plain_content=plain,
        categories=["auto_submit", "weekly"],
    )


# ---------- 7. Approval/rejection notification ----------

def send_approval_notification(
    to_email: str,
    user_name: str,
    period_str: str,
    status: str,
    total_hours: float = 0,
    reviewer_notes: str = "",
):
    """
    Send approved/rejected notification.
    Used by: tasks.py send_approval_notification_task
    """
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    if status == 'approved':
        body = f'''
            <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
            <p style="color:#475569;font-size:16px;line-height:1.5;">
                Your timesheet for <strong>{period_str}</strong> ({total_hours:.1f} hours) has been approved.
            </p>
            {_btn(frontend_url + "/timesheet", "#10b981 0%,#059669 100%", "View Timesheet &rarr;")}'''
        html = _wrap_html("#10b981 0%,#059669 100%", "✅", "Timesheet Approved", body)
        subject = f"✅ Timesheet Approved: {period_str}"
        plain = f"Hi {user_name},\n\nYour timesheet for {period_str} ({total_hours:.1f} hours) has been approved.\n\n- TimeTracker"
    else:
        feedback = f"\nFeedback: {reviewer_notes}" if reviewer_notes else "\nPlease review and resubmit."
        reason_html = f'<div style="background:#fef3c7;border:1px solid #fcd34d;padding:12px 16px;border-radius:8px;margin:16px 0;"><p style="margin:0;color:#92400e;font-size:14px;">Feedback: {reviewer_notes}</p></div>' if reviewer_notes else ''
        body = f'''
            <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {user_name},</p>
            <p style="color:#475569;font-size:16px;line-height:1.5;">Your timesheet for <strong>{period_str}</strong> needs revision.</p>
            {reason_html}
            {_btn(frontend_url + "/timesheet", "#ef4444 0%,#dc2626 100%", "Revise Timesheet &rarr;")}'''
        html = _wrap_html("#ef4444 0%,#dc2626 100%", "⚠️", "Timesheet Needs Revision", body)
        subject = f"❌ Timesheet Needs Revision: {period_str}"
        plain = f"Hi {user_name},\n\nYour timesheet for {period_str} needs revision.{feedback}\n\nEdit: {frontend_url}/timesheet\n\n- TimeTracker"

    return send_email(
        to_email=to_email,
        subject=subject,
        html_content=html,
        plain_content=plain,
        categories=["approval_notification", status],
    )


# ---------- 8. Manager pending approvals ----------

def send_manager_pending_approvals(
    to_email: str,
    manager_name: str,
    week_start_str: str,
    timesheet_count: int,
    total_hours: float,
    summary_lines: list,
):
    """
    Notify managers of pending approvals.
    Used by: tasks.py notify_managers_pending_approvals
    """
    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai')

    rows_html = ''.join([
        f'<tr><td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;font-size:14px;">{line.strip().lstrip("• ")}</td></tr>'
        for line in summary_lines
    ])

    body = f'''
        <p style="color:#475569;font-size:16px;line-height:1.5;margin-top:0;">Hi {manager_name},</p>
        <p style="color:#475569;font-size:16px;line-height:1.5;">
            <strong>{timesheet_count} timesheets</strong> are pending approval for the week of <strong>{week_start_str}</strong> ({total_hours:.1f} total hours).
        </p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0;background:#f8fafc;border-radius:8px;">{rows_html}</table>
        {_btn(frontend_url + "/approvals", "#6366f1 0%,#4f46e5 100%", "Review Timesheets &rarr;")}'''

    html = _wrap_html("#6366f1 0%,#4f46e5 100%", "📋", "Approvals Pending", body)

    plain = f"""Hi {manager_name},

{timesheet_count} timesheets pending approval for week of {week_start_str} ({total_hours:.1f} total hours):

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
            Your timesheet for <strong>{week_str}</strong> ({total_hours:.1f} hours) has been approved by {approved_by}.
        </p>
        {_btn(frontend_url + "/timesheet", "#10b981 0%,#059669 100%", "View Timesheet &rarr;")}'''

    html = _wrap_html("#10b981 0%,#059669 100%", "✅", "Timesheet Approved", body)

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