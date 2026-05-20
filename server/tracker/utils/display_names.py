# tracker/services/display_names.py
"""
Clean up raw app/window data for user-friendly display.

Updated: Now includes "App - Context" formatting and client_name support.
"""
import re
from urllib.parse import urlparse

# =============================================================================
# APP NAME CLEANUP
# =============================================================================
APP_DISPLAY_NAMES = {
    # Browsers
    "google chrome": "Chrome",
    "arc": "Arc Browser",
    "safari": "Safari",
    "firefox": "Firefox",
    "microsoft edge": "Edge",
    "brave browser": "Brave",
    
    # Development
    "code": "VS Code",
    "visual studio code": "VS Code",
    "sublime_text": "Sublime Text",
    "sublime text": "Sublime Text",
    "pycharm": "PyCharm",
    "intellij idea": "IntelliJ",
    "webstorm": "WebStorm",
    "terminal": "Terminal",
    "iterm2": "iTerm",
    "iterm": "iTerm",
    "warp": "Warp Terminal",
    
    # Communication
    "microsoft teams": "Teams",
    "slack": "Slack",
    "zoom.us": "Zoom",
    "zoom": "Zoom",
    "messages": "Messages",
    "facetime": "FaceTime",
    
    # Productivity
    "microsoft excel": "Excel",
    "microsoft word": "Word",
    "microsoft powerpoint": "PowerPoint",
    "microsoft outlook": "Outlook",
    "google docs": "Google Docs",
    "notion": "Notion",
    "finder": "Finder",
    "preview": "Preview",
    
    # Tax/Accounting
    "ultratax cs": "UltraTax",
    "lacerte": "Lacerte",
    "proseries": "ProSeries",
    "quickbooks": "QuickBooks",
    "drake tax": "Drake Tax",
    "xero": "Xero",
    "sage": "Sage",
}

def clean_app_name(app_name: str) -> str:
    """Convert raw app name to user-friendly display name."""
    if not app_name:
        return "Unknown App"
    
    key = app_name.lower().strip()
    
    # Direct match
    if key in APP_DISPLAY_NAMES:
        return APP_DISPLAY_NAMES[key]
    
    # Partial match
    for pattern, display in APP_DISPLAY_NAMES.items():
        if pattern in key:
            return display
    
    # Clean up generic names
    name = app_name.strip()
    
    # Remove .app suffix (macOS)
    name = re.sub(r'\.app$', '', name, flags=re.IGNORECASE)
    
    # Remove common prefixes
    name = re.sub(r'^(Microsoft|Google|Apple)\s+', '', name)
    
    # Title case if all lower
    if name.islower():
        name = name.title()
    
    return name


# =============================================================================
# CONTEXT EXTRACTION - Extract meaningful info from window titles
# =============================================================================
def extract_context_from_title(window_title: str, app_name: str = '', url: str = '', client_name: str = '') -> str:
    """
    Extract the meaningful context from a window title.
    
    Returns JUST the context part (not the app name).
    
    Examples:
        "Aurelia Beauty - Dashboard - Google Chrome" → "Aurelia Beauty"
        "druss16/timetracker: PR #45 - GitHub - Google Chrome" → "timetracker - Pull requests"
        "dan@mac:~/Projects$ npm run dev" → "npm run dev"
        "BookingPage.tsx - aurelia-site - Visual Studio Code" → "BookingPage.tsx (aurelia-site)"
        "Inbox (5) - dan@company.com - Gmail" → "Inbox"
    """
    if not window_title:
        return ''
    
    title = window_title.strip()
    
    # Remove browser/app suffixes
    suffixes_to_remove = [
        ' - Google Chrome', ' - Chrome', ' - Mozilla Firefox', ' - Firefox',
        ' - Safari', ' - Microsoft Edge', ' - Edge', ' - Brave', ' - Arc',
        ' — Mozilla Firefox', ' — Google Chrome',
        ' - Visual Studio Code', ' - VS Code', ' - Code',
        ' - Outlook', ' - Microsoft Outlook',
    ]
    for suffix in suffixes_to_remove:
        if title.endswith(suffix):
            title = title[:-len(suffix)]
    
    title = title.strip(' -\u2013\u2014|')
    
    app_lower = (app_name or '').lower()
    
    # ========================================
    # TERMINAL - Extract command
    # ========================================
    if 'terminal' in app_lower or 'iterm' in app_lower or 'warp' in app_lower:
        if '$' in title:
            cmd = title.split('$')[-1].strip()
            if cmd:
                return cmd[:50]
        if '\u2014' in title:
            parts = title.split('\u2014')
            if len(parts) >= 2:
                return parts[1].strip()[:50]
        # Strip user@host:path prefix
        if ':' in title and ('~' in title or '/' in title):
            path_part = title.split(':')[-1].strip()
            return path_part[:50]
        return title[:50]
    
    # ========================================
    # VS CODE / Sublime - Extract file + project
    # ========================================
    if any(x in app_lower for x in ['code', 'visual studio', 'sublime']):
        # Remove unsaved indicator
        title = re.sub(r'^\u25cf\s*', '', title)
        
        parts = [p.strip() for p in title.split(' - ')]
        if len(parts) >= 2:
            filename = parts[0]
            project = parts[1] if len(parts) > 1 else ''
            if project and project.lower() not in filename.lower():
                return f"{filename} ({project})"
            return filename
        return title[:50]
    
    # ========================================
    # GITHUB - Extract repo + context
    # ========================================
    if 'github' in title.lower():
        parts = title.split(' - ')
        for i, part in enumerate(parts):
            if '/' in part and ':' in part:
                repo = part.split('/')[1].split(':')[0]
                context = parts[i+1].strip() if i+1 < len(parts) else ''
                if context:
                    return f"{repo} - {context}"
                return repo
        return title.replace('GitHub', '').strip(' -\u2013')[:50]
    
    # ========================================
    # LOCALHOST/DEV - Extract port + context
    # ========================================
    if 'localhost' in title.lower() or '127.0.0.1' in title.lower():
        port_match = re.search(r'localhost:(\d+)', title, re.IGNORECASE)
        if port_match:
            port = port_match.group(0)
            before = title.split(port)[0].strip(' -\u2013|')
            if before and len(before) < 30:
                return f"{port} ({before})"
            return port
        return title[:50]
    
    # ========================================
    # EMAIL - Clean up
    # ========================================
    if any(x in title.lower() for x in ['inbox', 'outlook', 'gmail']) or any(x in app_lower for x in ['outlook', 'mail', 'gmail']):
        # Remove email addresses
        title = re.sub(r'\s*[-\u2013\u2014]\s*\S+@\S+\.\S+', '', title)
        # Remove unread counts
        title = re.sub(r'\s*\(\d+\)\s*', ' ', title)
        # Remove "Gmail" "Outlook" suffixes
        title = re.sub(r'\s*[-\u2013\u2014]\s*(Gmail|Outlook|Mail)$', '', title, flags=re.IGNORECASE)
        # Handle RE: FW: prefixes
        title = re.sub(r'^(RE|FW|Fwd):\s*', '', title, flags=re.IGNORECASE)
        # Handle "Message (HTML)" Outlook format
        title = re.sub(r'^Message\s*\(HTML\)\s*', '', title, flags=re.IGNORECASE)
        
        title = title.strip(' -\u2013\u2014')
        
        if not title or title.lower() in ('inbox', 'mail', 'email'):
            return 'Inbox'
        return title[:50]
    
    # ========================================
    # TAX SOFTWARE - Extract app + client from title
    # ========================================
    tax_apps = ['ultratax', 'proseries', 'lacerte', 'drake', 'taxact', 'cch']
    for tax_app in tax_apps:
        if tax_app in title.lower():
            parts = [p.strip() for p in title.split(' - ')]
            # Use last meaningful part (often the open return/client)
            if len(parts) > 1:
                return parts[-1][:40]
            return title[:50]
        

    # ========================================
    # QUICKBOOKS - Extract company + current screen
    # Format: "{Company Name} - QuickBooks <edition> - [{Current Screen}]"
    # ========================================
    if 'quickbooks' in title.lower() or 'qbo' in title.lower():
        company = ''
        screen = ''
        
        # Extract bracketed screen, e.g. "[Reconcile - Mass Stipend Account 3345]"
        bracket_match = re.search(r'\[([^\]]+)\]', title)
        if bracket_match:
            screen = bracket_match.group(1).strip()
            # Often "Reconcile - Mass Stipend Account 3345" — take the first part as the action
            if ' - ' in screen:
                screen = screen.split(' - ')[0].strip()
        
        # Extract company name (everything before " - QuickBooks")
        qb_split = re.split(r'\s*-\s*QuickBooks', title, maxsplit=1, flags=re.IGNORECASE)
        if qb_split and qb_split[0].strip():
            company = qb_split[0].strip()
        
        if company and screen:
            return f"{company[:40]} - {screen[:25]}"
        if company:
            return company[:50]
        if screen:
            return screen[:50]
        # No usable info from title — fall through to generic at bottom
    
    # ========================================
    # MEETINGS - Simplify
    # ========================================
    if any(x in app_lower for x in ['zoom', 'teams', 'facetime', 'meet']):
        # Remove "Zoom Meeting" prefix
        title = re.sub(r'^(Zoom|Teams)\s*(Meeting|Call)\s*[-\u2013\u2014]?\s*', '', title, flags=re.IGNORECASE)
        return title[:50] if title else 'Call'
    
    # ========================================
    # GENERIC - Take meaningful parts
    # ========================================
    parts = [p.strip() for p in re.split(r'\s*[-\u2013\u2014|]\s*', title)]
    
    # Filter out very generic parts
    generic = ['home', 'new tab', 'untitled', 'document']
    meaningful_parts = [p for p in parts if p.lower() not in generic and len(p) > 2]
    
    if meaningful_parts:
        if len(meaningful_parts) >= 2 and len(meaningful_parts[0]) + len(meaningful_parts[1]) < 50:
            return f"{meaningful_parts[0]} - {meaningful_parts[1]}"
        return meaningful_parts[0][:50]
    
    return title[:50] if title else ''


# =============================================================================
# WINDOW TITLE CLEANUP (legacy - still used by some code)
# =============================================================================
def clean_window_title(title: str, app_name: str = None) -> str:
    """
    Extract meaningful activity from window title.
    Legacy wrapper around extract_context_from_title.
    """
    if not title:
        return ""
    
    context = extract_context_from_title(title, app_name or '')
    if context:
        return context
    
    # Fallback: truncate
    return title[:57] + "..." if len(title) > 60 else title


# =============================================================================
# URL -> ACTIVITY NAME
# =============================================================================
DOMAIN_ACTIVITIES = {
    "claude.ai": "AI Research - Claude",
    "chat.openai.com": "AI Research - ChatGPT",
    "chatgpt.com": "AI Research - ChatGPT",
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "stackoverflow.com": "Stack Overflow",
    "mail.google.com": "Gmail",
    "calendar.google.com": "Google Calendar",
    "docs.google.com": "Google Docs",
    "sheets.google.com": "Google Sheets",
    "drive.google.com": "Google Drive",
    "meet.google.com": "Google Meet",
    "slack.com": "Slack",
    "app.slack.com": "Slack",
    "notion.so": "Notion",
    "figma.com": "Figma",
    "linkedin.com": "LinkedIn",
    "qbo.intuit.com": "QuickBooks Online",
    "quickbooks.intuit.com": "QuickBooks Online",
    "app.xero.com": "Xero",
    "xero.com": "Xero",
    "cchaxcess.com": "CCH Axcess",
    "teams.microsoft.com": "Teams",
    "outlook.office.com": "Outlook Web",
    "outlook.office365.com": "Outlook Web",
}

def url_to_activity(url: str) -> str:
    """Convert URL to user-friendly activity name."""
    if not url:
        return ""
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www.
        domain = re.sub(r'^www\.', '', domain)
        
        # Check known domains
        for pattern, activity in DOMAIN_ACTIVITIES.items():
            if pattern in domain:
                return activity
        
        # localhost = Development
        if 'localhost' in domain or '127.0.0.1' in domain:
            port = parsed.port
            if port:
                return f"Local Dev (:{port})"
            return "Local Development"
        
        # Return cleaned domain
        return domain.split('.')[0].title()
        
    except Exception:
        return ""


# =============================================================================
# CATEGORY DISPLAY
# =============================================================================
CATEGORY_DISPLAY = {
    "Software Development": "Development",
    "Email/Communication": "Communication",
    "Accounting/Bookkeeping": "Bookkeeping",
    "Tax Preparation": "Tax Prep",
    "Research/AI Assistance": "Research",
    "Meetings/Calls": "Meetings",
    "Design/Creative": "Design",
    "Administration": "Admin",
    "Meetings": "Meetings",
    "Development": "Development",
    "Research": "Research",
    "Email": "Email",
}

CATEGORY_ICONS = {
    'Tax Preparation': '\U0001f4cb',
    'Tax Planning': '\U0001f4ca',
    'Tax Research': '\U0001f50d',
    'Bookkeeping': '\U0001f4d2',
    'Accounting/Bookkeeping': '\U0001f4d2',
    'Email/Communication': '\u2709\ufe0f',
    'Email': '\u2709\ufe0f',
    'Communication': '\u2709\ufe0f',
    'Meetings': '\U0001f465',
    'Meetings/Calls': '\U0001f465',
    'Document Review': '\U0001f4c4',
    'Research': '\U0001f52c',
    'Research/AI Assistance': '\U0001f52c',
    'Admin/Internal': '\u2699\ufe0f',
    'Administration': '\u2699\ufe0f',
    'Software Development': '\U0001f4bb',
    'Development': '\U0001f4bb',
    'Advisory/Consulting': '\U0001f4a1',
    'Audit/Assurance': '\u2705',
    'Design/Creative': '\U0001f3a8',
    'Idle': '\U0001f4a4',
    'Uncategorized': '\U0001f4cc',
}

def clean_category(category: str) -> str:
    """Shorten category name for display."""
    if not category:
        return "Uncategorized"
    return CATEGORY_DISPLAY.get(category, category)

def get_category_icon(category: str) -> str:
    """Get emoji icon for category."""
    if not category:
        return '\U0001f4cc'
    return CATEGORY_ICONS.get(category, '\U0001f4cc')


# =============================================================================
# TIME DISPLAY
# =============================================================================
def format_duration(minutes) -> str:
    """
    Format minutes as user-friendly duration.
    
    Accepts int or float.
    
    Examples:
        5  -> "5m"
        45 -> "45m"
        60 -> "1h"
        90 -> "1.5h"
    """
    if not minutes or float(minutes) < 0.5:
        return "0m"
    
    minutes = float(minutes)
    
    if minutes < 60:
        return f"{int(round(minutes))}m"
    
    hours = minutes / 60
    if hours == int(hours):
        return f"{int(hours)}h"
    else:
        return f"{hours:.1f}h"


def format_duration_long(minutes) -> str:
    """
    Format duration in long form.
    "1 hr 30 min" or "45 min"
    """
    if not minutes or float(minutes) < 1:
        return "<1 min"
    
    minutes = float(minutes)
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    
    if hours == 0:
        return f"{mins} min"
    
    hr_label = "hr" if hours == 1 else "hrs"
    if mins == 0:
        return f"{hours} {hr_label}"
    
    return f"{hours} {hr_label} {mins} min"


# =============================================================================
# FULL BLOCK DISPLAY HELPER
# =============================================================================
def format_block_for_display(block_data: dict, client_name: str = '') -> dict:
    """
    Transform raw block data into user-friendly "App - Context" display format.
    
    Input: Raw block dict with app_name, window_title, url, minutes, etc.
    Output: Clean display dict for frontend
    
    Examples:
        "Google Chrome" + "views.py - TimeTracker - Google Chrome"
            -> {"title": "Chrome - views.py (TimeTracker)", "app": "Chrome", ...}
        
        "Terminal" + "dan@mac:~/Projects$ npm run dev"
            -> {"title": "Terminal - npm run dev", "app": "Terminal", ...}
        
        "Google Chrome" + "localhost:5173 - Vite + React - Google Chrome"
            -> {"title": "Chrome - localhost:5173 (Aurelia)", "app": "Chrome", ...}
    """
    app = block_data.get('app_name', '') or ''
    title = block_data.get('window_title', '') or block_data.get('title', '') or ''
    url = block_data.get('url', '') or ''
    minutes = block_data.get('minutes', 0) or 0
    category = block_data.get('category', '') or ''
    
    # Clean app name
    clean_app = clean_app_name(app)
    
    # Extract context from window title
    context = extract_context_from_title(title, app, url, client_name)
    
    # If no context from title, try URL
    if not context and url:
        context = url_to_activity(url)
    
    # Build display title in "App - Context" format
    if clean_app and context:
        # Don't duplicate if context already contains app name
        if clean_app.lower() in context.lower():
            display_title = context
        else:
            display_title = f"{clean_app} - {context}"
    elif context:
        display_title = context
    elif clean_app and clean_app != "Unknown App":
        display_title = clean_app
    else:
        display_title = 'Activity'
    
    # Add client context if missing and would be helpful
    if client_name and client_name.lower() not in display_title.lower():
        generic_apps = ['chrome', 'firefox', 'safari', 'edge', 'arc browser', 'brave']
        if clean_app.lower() in generic_apps and len(display_title) < 40:
            display_title = f"{display_title} ({client_name})"
    
    return {
        'title': display_title,
        'app': clean_app,
        'duration': format_duration(minutes),
        'duration_long': format_duration_long(minutes),
        'minutes': round(float(minutes), 1) if minutes else 0,
        'category': clean_category(category),
        'category_icon': get_category_icon(category),
        # Legacy field (backward compatibility)
        'activity': display_title,
    }