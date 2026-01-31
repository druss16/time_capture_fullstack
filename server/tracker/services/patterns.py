# tracker/services/patterns.py
"""
Unified pattern matching for auto-categorization.
Consolidates: domain→client, app→task, title hints, and confidence-based matching.
"""
import re

# =============================================================================
# DOMAIN → CLIENT MAPPING (for browser activity)
# =============================================================================
DOMAIN_CLIENT = {
    # Communication
    "mail.google.com": "Email",
    "calendar.google.com": "Calendar",
    "meet.google.com": "Meetings",
    "teams.microsoft.com": "Meetings",
    "slack.com": "Slack",
    "zoom.us": "Meetings",
    
    # Dev Tools
    "github.com": "GitHub",
    "gitlab.com": "GitLab",
    "console.neon.tech": "Neon",
    "dashboard.render.com": "Render",
    "vercel.com": "Vercel",
    
    # AI/Research
    "claude.ai": "Claude",
    "chat.openai.com": "ChatGPT",
    "chatgpt.com": "ChatGPT",
    "stackoverflow.com": "Research",
    
    # Google Workspace
    "docs.google.com": "Google Docs",
    "sheets.google.com": "Google Sheets",
    "drive.google.com": "Google Drive",
    
    # Accounting
    "qbo.intuit.com": "QuickBooks",
    "quickbooks.intuit.com": "QuickBooks",
    "xero.com": "Xero",
    "cchaxcess.com": "CCH Axcess",
    "irs.gov": "IRS",
    
    # Your Projects
    "predictoredge": "PredictorEdge",
    "edgrinvest": "EDGR Invest",
    "edgriq": "EDGRIQ",
    "localhost": "Local Dev",
}

# =============================================================================
# APP → CATEGORY MAPPING
# =============================================================================
APP_CATEGORY = {
    # Development
    "code": "Software Development",
    "vscode": "Software Development",
    "visual studio": "Software Development",
    "sublime": "Software Development",
    "pycharm": "Software Development",
    "intellij": "Software Development",
    "webstorm": "Software Development",
    "xcode": "Software Development",
    "terminal": "Software Development",
    "iterm": "Software Development",
    "warp": "Software Development",
    
    # Communication
    "zoom": "Meetings",
    "teams": "Meetings",
    "meet": "Meetings",
    "webex": "Meetings",
    "slack": "Email/Communication",
    "mail": "Email/Communication",
    "outlook": "Email/Communication",
    
    # Tax Software
    "ultratax": "Tax Preparation",
    "lacerte": "Tax Preparation",
    "proseries": "Tax Preparation",
    "drake": "Tax Preparation",
    "proconnect": "Tax Preparation",
    
    # Accounting
    "quickbooks": "Accounting/Bookkeeping",
    "xero": "Accounting/Bookkeeping",
    
    # Design
    "figma": "Design/Creative",
    "sketch": "Design/Creative",
    "photoshop": "Design/Creative",
    "canva": "Design/Creative",
    
    # Productivity
    "notion": "Administration",
    "word": "Administration",
    "excel": "Data Entry",
    "sheets": "Data Entry",
    "powerpoint": "Administration",
}

# =============================================================================
# TITLE/URL HINTS → CATEGORY (regex patterns)
# =============================================================================
TITLE_HINTS = [
    # Meetings
    (r"stand-?up|retro|sprint|kickoff|check-?in|meeting|call with", "Meetings"),
    
    # Development
    (r"\.py\b|\.js\b|\.tsx?\b|debug|stacktrace|traceback|error|localhost:\d+", "Software Development"),
    (r"\bPR\b|pull request|review changes|merge|commit", "Code Review"),
    
    # Planning
    (r"roadmap|scope|deliverable|milestone|planning|backlog", "Planning"),
    
    # Tax
    (r"\b1040\b|\b1120\b|\b1065\b|\b990\b|tax return|w-2|1099|k-1", "Tax Preparation"),
    
    # Accounting
    (r"invoice|payable|receivable|recon|ledger|journal entry|bank rec", "Accounting/Bookkeeping"),
    
    # Admin
    (r"proposal|quote|contract|SOW|engagement letter", "Administration"),
    
    # Data
    (r"export|csv|spreadsheet|\.xlsx?\b", "Data Entry"),
]

# Compile regex patterns once
TITLE_HINTS_COMPILED = [(re.compile(pat, re.I), cat) for pat, cat in TITLE_HINTS]


# =============================================================================
# MAIN MATCHING FUNCTION
# =============================================================================
def match_activity(app_name=None, url=None, window_title=None, file_path=None):
    """
    Match activity to client and category.
    
    Returns:
        dict: {
            'client': str or None,
            'category': str or None,
            'confidence': float (0.0-1.0),
            'source': str (what matched)
        }
    """
    app = (app_name or "").lower()
    url_lower = (url or "").lower()
    title = (window_title or "").lower()
    path = (file_path or "").lower()
    combined = f"{app} {url_lower} {title} {path}"
    
    result = {'client': None, 'category': None, 'confidence': 0.0, 'source': None}
    
    # 1. Check URL domain (highest confidence for browser work)
    for domain, client in DOMAIN_CLIENT.items():
        if domain in url_lower:
            result['client'] = client
            result['confidence'] = 0.90
            result['source'] = f"domain:{domain}"
            break
    
    # 2. Check app name
    for app_key, category in APP_CATEGORY.items():
        if app_key in app:
            result['category'] = category
            if result['confidence'] < 0.85:
                result['confidence'] = 0.85
            result['source'] = result.get('source') or f"app:{app_key}"
            break
    
    # 3. Check title hints (if no category yet or to boost confidence)
    for pattern, category in TITLE_HINTS_COMPILED:
        if pattern.search(combined):
            if not result['category']:
                result['category'] = category
            result['confidence'] = max(result['confidence'], 0.80)
            result['source'] = result.get('source') or f"title:{pattern.pattern[:20]}"
            break
    
    return result


def get_category_for_block(block):
    """Convenience wrapper for Block objects."""
    return match_activity(
        app_name=getattr(block, 'app_name', None),
        url=getattr(block, 'url', None),
        window_title=getattr(block, 'window_title', None),
        file_path=getattr(block, 'file_path', None),
    )