# tracker/utils/display_names.py
"""
Clean up raw app/window data for user-friendly display.
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
    
    # Productivity
    "microsoft excel": "Excel",
    "microsoft word": "Word",
    "microsoft powerpoint": "PowerPoint",
    "google docs": "Google Docs",
    "notion": "Notion",
    
    # Tax/Accounting
    "ultratax cs": "UltraTax",
    "lacerte": "Lacerte",
    "proseries": "ProSeries",
    "quickbooks": "QuickBooks",
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
# WINDOW TITLE CLEANUP
# =============================================================================
def clean_window_title(title: str, app_name: str = None) -> str:
    """
    Extract meaningful activity from window title.
    
    Examples:
        "views.py - TimeTracker - Visual Studio Code" → "views.py - TimeTracker"
        "Inbox (3) - dan@mavops.ai - Gmail" → "Email - Gmail"
        "Claude" → "AI Research"
    """
    if not title:
        return ""
    
    title = title.strip()
    
    # Remove app name suffix (common pattern: "content - App Name")
    if app_name:
        app_clean = clean_app_name(app_name)
        # Remove " - App Name" or " — App Name" from end
        title = re.sub(rf'\s*[-—]\s*{re.escape(app_clean)}$', '', title, flags=re.IGNORECASE)
        title = re.sub(rf'\s*[-—]\s*{re.escape(app_name)}$', '', title, flags=re.IGNORECASE)
    
    # Clean up specific patterns
    patterns = [
        # Gmail: "Inbox (3) - email@domain.com - Gmail" → "Email"
        (r'^Inbox\s*\(\d+\).*', 'Email'),
        (r'^.+@.+\s*-\s*Gmail$', 'Email'),
        
        # Zoom: "Zoom Meeting" → "Video Call"
        (r'^Zoom\s*(Meeting|Webinar)?$', 'Video Call'),
        
        # Calendar: "Calendar - Week of Jan 20" → "Calendar"
        (r'^Calendar\s*[-—].*', 'Calendar'),
        
        # VS Code: Remove "● " unsaved indicator
        (r'^●\s*', ''),
        
        # Chrome: Remove "and X more tabs"
        (r'\s*and\s+\d+\s+more\s+tabs?', ''),
    ]
    
    for pattern, replacement in patterns:
        if re.match(pattern, title, re.IGNORECASE):
            title = re.sub(pattern, replacement, title, flags=re.IGNORECASE)
            break
    
    # Truncate if still too long
    if len(title) > 60:
        title = title[:57] + "..."
    
    return title.strip()


# =============================================================================
# URL → ACTIVITY NAME
# =============================================================================
DOMAIN_ACTIVITIES = {
    "claude.ai": "AI Research - Claude",
    "chat.openai.com": "AI Research - ChatGPT",
    "chatgpt.com": "AI Research - ChatGPT",
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "stackoverflow.com": "Stack Overflow",
    "mail.google.com": "Email - Gmail",
    "calendar.google.com": "Google Calendar",
    "docs.google.com": "Google Docs",
    "sheets.google.com": "Google Sheets",
    "drive.google.com": "Google Drive",
    "slack.com": "Slack",
    "notion.so": "Notion",
    "figma.com": "Figma",
    "linkedin.com": "LinkedIn",
    "qbo.intuit.com": "QuickBooks Online",
    "xero.com": "Xero",
    "cchaxcess.com": "CCH Axcess",
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
# CATEGORY DISPLAY NAMES
# =============================================================================
CATEGORY_DISPLAY = {
    # Simplify verbose names
    "Software Development": "Development",
    "Email/Communication": "Communication",
    "Accounting/Bookkeeping": "Bookkeeping",
    "Tax Preparation": "Tax Prep",
    "Research/AI Assistance": "Research",
    "Meetings/Calls": "Meetings",
    "Design/Creative": "Design",
    "Administration": "Admin",
    
    # Keep these as-is
    "Meetings": "Meetings",
    "Development": "Development",
    "Research": "Research",
    "Email": "Email",
}

def clean_category(category: str) -> str:
    """Shorten category name for display."""
    if not category:
        return "Uncategorized"
    return CATEGORY_DISPLAY.get(category, category)


# =============================================================================
# TIME DISPLAY
# =============================================================================
def format_duration(minutes: int) -> str:
    """
    Format minutes as user-friendly duration.
    
    Examples:
        5 → "5 min"
        45 → "45 min"
        60 → "1 hr"
        90 → "1.5 hrs"
        125 → "~2 hrs"
    """
    if not minutes or minutes < 1:
        return "<1 min"
    
    if minutes < 60:
        return f"{minutes} min"
    
    hours = minutes / 60
    
    if hours == int(hours):
        hr_label = "hr" if hours == 1 else "hrs"
        return f"{int(hours)} {hr_label}"
    
    # Round to nearest 0.5
    rounded = round(hours * 2) / 2
    if rounded == int(rounded):
        hr_label = "hr" if rounded == 1 else "hrs"
        return f"{int(rounded)} {hr_label}"
    
    return f"{rounded} hrs"


# =============================================================================
# FULL BLOCK DISPLAY HELPER
# =============================================================================
def format_block_for_display(block_data: dict) -> dict:
    """
    Transform raw block data into user-friendly display format.
    
    Input: Raw block dict with app_name, window_title, url, minutes, etc.
    Output: Clean display dict for frontend
    """
    app = block_data.get('app_name', '')
    title = block_data.get('window_title', '') or block_data.get('title', '')
    url = block_data.get('url', '')
    minutes = block_data.get('minutes', 0)
    category = block_data.get('category', '')
    
    # Build activity description
    activity = ""
    
    # Priority: URL activity > cleaned title > cleaned app
    if url:
        activity = url_to_activity(url)
    
    if not activity and title:
        activity = clean_window_title(title, app)
    
    if not activity:
        activity = clean_app_name(app)
    
    return {
        'activity': activity,
        'app': clean_app_name(app),
        'category': clean_category(category),
        'duration': format_duration(minutes),
        'duration_minutes': minutes,
        # Keep raw data for debugging
        '_raw': {
            'app_name': app,
            'window_title': title,
            'url': url,
        }
    }