# tracker/utils/display_formatter.py
"""
Clean display formatter for time blocks.
Makes real-world messy window titles look as clean as demo data.

BEFORE: "QuickBooks Online - Chart of Accounts - Acme Corp LLC - Google Chrome"
AFTER:  "QuickBooks Online - Acme Corp (Chart of Accounts)"

BEFORE: "Message (HTML) RE: Tax documents needed - Outlook"
AFTER:  "Email - Tax documents needed"
"""

import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List, Tuple


# ============================================================================
# APP NAME CLEANERS - Remove noise from app names
# ============================================================================

APP_NAME_MAP = {
    # Browsers
    'google chrome': 'Chrome',
    'chrome': 'Chrome',
    'mozilla firefox': 'Firefox',
    'firefox': 'Firefox',
    'safari': 'Safari',
    'microsoft edge': 'Edge',
    'edge': 'Edge',
    'brave browser': 'Brave',
    'arc': 'Arc',
    
    # Communication
    'microsoft outlook': 'Outlook',
    'outlook': 'Outlook',
    'mail': 'Mail',
    'gmail': 'Gmail',
    'slack': 'Slack',
    'microsoft teams': 'Teams',
    'teams': 'Teams',
    'zoom.us': 'Zoom',
    'zoom': 'Zoom',
    
    # Productivity
    'microsoft excel': 'Excel',
    'excel': 'Excel',
    'microsoft word': 'Word',
    'word': 'Word',
    'microsoft powerpoint': 'PowerPoint',
    'powerpoint': 'PowerPoint',
    'adobe acrobat reader': 'Acrobat',
    'acrobat reader': 'Acrobat',
    'preview': 'Preview',
    
    # Development
    'visual studio code': 'VS Code',
    'code': 'VS Code',
    'terminal': 'Terminal',
    'iterm2': 'iTerm',
    'iterm': 'iTerm',
    
    # Tax Software
    'ultratax cs': 'UltraTax',
    'ultratax': 'UltraTax',
    'drake tax': 'Drake Tax',
    'lacerte': 'Lacerte',
    'proseries': 'ProSeries',
    
    # Accounting
    'quickbooks': 'QuickBooks',
    'quickbooks online': 'QuickBooks',
    'xero': 'Xero',
    'sage': 'Sage',
}

def clean_app_name(app_name: str) -> str:
    """Clean and standardize app name."""
    if not app_name:
        return ''
    
    app_lower = app_name.lower().strip()
    
    # Check exact and partial matches
    if app_lower in APP_NAME_MAP:
        return APP_NAME_MAP[app_lower]
    
    for key, clean_name in APP_NAME_MAP.items():
        if key in app_lower:
            return clean_name
    
    # Default: Title case, remove common suffixes
    clean = app_name.strip()
    for suffix in ['.app', '.exe', ' - Google Chrome', ' - Mozilla Firefox']:
        if clean.endswith(suffix):
            clean = clean[:-len(suffix)]
    
    return clean.title() if clean else 'Unknown'


# ============================================================================
# WINDOW TITLE CLEANERS - Extract meaningful content
# ============================================================================

# Patterns to remove from window titles
TITLE_NOISE_PATTERNS = [
    r'\s*[-–—]\s*Google Chrome$',
    r'\s*[-–—]\s*Mozilla Firefox$',
    r'\s*[-–—]\s*Safari$',
    r'\s*[-–—]\s*Microsoft Edge$',
    r'\s*[-–—]\s*Brave$',
    r'\s*[-–—]\s*Arc$',
    r'\s*[-–—]\s*Outlook$',
    r'\s*[-–—]\s*Microsoft Outlook$',
    r'^\[.*?\]\s*',  # [EXTERNAL] prefixes
    r'\s*\(\d+\)$',  # (3) unread count suffixes
    r'\s*•\s*\d+$',  # • 5 notification counts
]

# Email patterns
EMAIL_PATTERNS = [
    (r'^(?:RE:|FW:|Fwd:)\s*(.+)', r'Email - \1'),
    (r'^Message \(HTML\)\s*(.+)', r'Email - \1'),
    (r'^Inbox\s*[-–—]\s*(.+)', r'Inbox - \1'),
    (r'^Compose:\s*(.+)', r'Composing - \1'),
]

# Meeting patterns  
MEETING_PATTERNS = [
    (r'^Zoom Meeting.*', 'Zoom Meeting'),
    (r'^(.+)\s*[-–—]\s*Zoom$', r'Zoom - \1'),
    (r'^Microsoft Teams Meeting.*', 'Teams Meeting'),
    (r'^(.+)\s*\|\s*Microsoft Teams$', r'Teams - \1'),
    (r'^Google Meet.*', 'Google Meet'),
]


def clean_window_title(title: str, app_name: str = '', client_name: str = '') -> str:
    """
    Clean window title to be human-readable.
    
    Args:
        title: Raw window title
        app_name: App name (for context)
        client_name: Client name (to highlight in title)
    
    Returns:
        Clean, readable title like demo data
    """
    if not title:
        return app_name or 'Unknown'
    
    clean = title.strip()
    
    # Remove browser suffixes
    for pattern in TITLE_NOISE_PATTERNS:
        clean = re.sub(pattern, '', clean, flags=re.IGNORECASE)
    
    clean = clean.strip(' -–—|')
    
    # ========================================
    # TAX SOFTWARE - Extract app + client
    # ========================================
    tax_apps = ['ultratax', 'proseries', 'lacerte', 'drake', 'taxact']
    for tax_app in tax_apps:
        if tax_app in clean.lower():
            # Extract: "UltraTax CS - Form 1120S - Client Name"
            # Output: "UltraTax CS - Client Name"
            parts = [p.strip() for p in clean.split(' - ')]
            
            # Find the app name part and client part
            app_part = parts[0] if parts else tax_app.title()
            
            # Look for client name in parts
            client_part = None
            if client_name:
                for p in parts:
                    if client_name.lower() in p.lower():
                        client_part = client_name  # Use clean version
                        break
            
            if client_part:
                return f"{app_part} - {client_part}"
            elif len(parts) > 1:
                # Use second-to-last part (often client)
                return f"{app_part} - {parts[-1][:40]}"
            return app_part
    
    # ========================================
    # ACCOUNTING SOFTWARE - Clean up
    # ========================================
    if 'quickbooks' in clean.lower() or 'qbo' in clean.lower():
        parts = [p.strip() for p in clean.split(' - ')]
        if client_name:
            return f"QuickBooks Online - {client_name}"
        elif len(parts) >= 2:
            # Try to find non-generic part
            for p in parts[1:]:
                if p.lower() not in ('chart of accounts', 'dashboard', 'home'):
                    return f"QuickBooks Online - {p[:40]}"
        return "QuickBooks Online"
    
    # ========================================
    # EMAIL - Clean up aggressively
    # ========================================
    app_lower = (app_name or '').lower()
    is_email = any(x in clean.lower() or x in app_lower for x in ['inbox', 'outlook', 'gmail', 'mail'])
    
    if is_email:
        # Remove email addresses
        clean = re.sub(r'\s*[-–—]\s*\S+@\S+\.\S+', '', clean)
        # Remove unread counts
        clean = re.sub(r'\s*\(\d+\)\s*', ' ', clean)
        # Remove "Gmail" "Outlook" suffixes
        clean = re.sub(r'\s*[-–—]\s*(Gmail|Outlook|Mail)$', '', clean, flags=re.IGNORECASE)
        
        clean = clean.strip(' -–—')
        
        # Handle RE: FW: prefixes
        if re.match(r'^(RE|FW|Fwd):', clean, re.IGNORECASE):
            subject = re.sub(r'^(RE|FW|Fwd):\s*', '', clean, flags=re.IGNORECASE)
            if client_name:
                return f"Email - {client_name} ({subject[:30]})"
            return f"Email - {subject[:40]}"
        
        # Handle "Message (HTML)" Outlook format
        if 'message' in clean.lower():
            clean = re.sub(r'^Message\s*\(HTML\)\s*', '', clean, flags=re.IGNORECASE)
            if client_name:
                return f"Email - {client_name}"
            return f"Email - {clean[:40]}"
        
        # Generic inbox
        if 'inbox' in clean.lower():
            if client_name:
                return f"Inbox - {client_name}"
            return "Inbox"
        
        if client_name:
            return f"Gmail - {client_name}"
        return clean[:50] if clean else "Email"
    
    # ========================================
    # MEETINGS - Simplify
    # ========================================
    if 'zoom' in app_lower or 'teams' in app_lower or 'meet' in app_lower:
        if client_name:
            app_name_clean = 'Zoom' if 'zoom' in app_lower else 'Teams' if 'teams' in app_lower else 'Meeting'
            return f"{app_name_clean} - {client_name}"
        
        for pattern, replacement in MEETING_PATTERNS:
            if re.match(pattern, clean, re.IGNORECASE):
                return re.sub(pattern, replacement, clean, flags=re.IGNORECASE)
        
        return clean[:50]
    
    # ========================================
    # GENERIC CLEANUP
    # ========================================
    # If client name is in title, try to extract meaningful context
    if client_name and client_name.lower() in clean.lower():
        # Keep as-is but truncate
        pass
    elif client_name:
        # Title doesn't have client - check if generic
        generic_words = ['document', 'spreadsheet', 'chart', 'dashboard', 'home', 'untitled']
        if any(g in clean.lower() for g in generic_words):
            clean = f"{clean.split(' - ')[0]} - {client_name}"
    
    # Final truncation
    if len(clean) > 60:
        clean = clean[:57] + '...'
    
    return clean or app_name or 'Unknown'


# ============================================================================
# URL CLEANERS - Extract meaningful info from URLs
# ============================================================================

URL_DISPLAY_MAP = {
    'mail.google.com': 'Gmail',
    'outlook.office.com': 'Outlook Web',
    'outlook.office365.com': 'Outlook Web',
    'drive.google.com': 'Google Drive',
    'docs.google.com': 'Google Docs',
    'sheets.google.com': 'Google Sheets',
    'meet.google.com': 'Google Meet',
    'zoom.us': 'Zoom',
    'teams.microsoft.com': 'Teams',
    'slack.com': 'Slack',
    'app.slack.com': 'Slack',
    'qbo.intuit.com': 'QuickBooks Online',
    'quickbooks.intuit.com': 'QuickBooks Online',
    'app.xero.com': 'Xero',
    'github.com': 'GitHub',
    'localhost': 'Local Dev',
}


def clean_url_for_display(url: str) -> Optional[str]:
    """Extract meaningful display name from URL."""
    if not url:
        return None
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Check known domains
        for key, display in URL_DISPLAY_MAP.items():
            if key in domain:
                return display
        
        # For unknown domains, return clean domain
        if domain and domain not in ('localhost', '127.0.0.1'):
            # Remove common suffixes
            for suffix in ['.com', '.org', '.net', '.io', '.ai']:
                if domain.endswith(suffix):
                    domain = domain[:-len(suffix)]
                    break
            return domain.title()
        
        return None
    except:
        return None


# ============================================================================
# DURATION FORMATTER
# ============================================================================

def format_duration(minutes: float) -> str:
    """
    Format duration in a clean, readable way.
    
    < 60 min: "45m"
    >= 60 min: "1.5h" or "2h"
    """
    if not minutes or minutes <= 0:
        return "0m"
    
    if minutes < 60:
        return f"{int(round(minutes))}m"
    
    hours = minutes / 60
    if hours == int(hours):
        return f"{int(hours)}h"
    else:
        return f"{hours:.1f}h"


def format_duration_long(minutes: float) -> str:
    """
    Format duration in long form.
    
    "1 hour 30 min" or "45 min"
    """
    if not minutes or minutes <= 0:
        return "0 min"
    
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    
    if hours == 0:
        return f"{mins} min"
    elif mins == 0:
        return f"{hours} hour{'s' if hours > 1 else ''}"
    else:
        return f"{hours}h {mins}m"


# ============================================================================
# CATEGORY DISPLAY
# ============================================================================

CATEGORY_ICONS = {
    'Tax Preparation': '📋',
    'Tax Planning': '📊',
    'Tax Research': '🔍',
    'Bookkeeping': '📒',
    'Accounting/Bookkeeping': '📒',
    'Email/Communication': '✉️',
    'Meetings': '👥',
    'Document Review': '📄',
    'Research': '🔬',
    'Admin/Internal': '⚙️',
    'Administration': '⚙️',
    'Software Development': '💻',
    'Audit/Assurance': '✅',
    'Advisory/Consulting': '💡',
    'Idle': '💤',
}

def get_category_icon(category: str) -> str:
    """Get emoji icon for category."""
    return CATEGORY_ICONS.get(category, '📌')


# ============================================================================
# MAIN FORMATTER - Use this for clean block display
# ============================================================================

def extract_context_from_title(window_title: str, app_name: str = '', url: str = '', client_name: str = '') -> str:
    """
    Extract the meaningful context from a window title.
    
    Examples:
        "Aurelia Beauty - Dashboard - Google Chrome" → "Aurelia Dashboard"
        "druss16/timetracker: PR #45 - GitHub" → "GitHub - timetracker PR #45"
        "dan@mac:~/Projects$ npm run dev" → "npm run dev"
        "tasks.py - timetracker - Visual Studio Code" → "tasks.py (timetracker)"
    """
    import re as regex  # Local import to avoid scope issues
    
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
    
    title = title.strip(' -–—|')
    
    # ========================================
    # TERMINAL - Extract command
    # ========================================
    if 'terminal' in app_name.lower() or 'iterm' in app_name.lower():
        # "dan@mac:~/Projects/timetracker$ npm run dev" → "npm run dev"
        if '$' in title:
            cmd = title.split('$')[-1].strip()
            if cmd:
                return cmd[:50]
        if '—' in title:
            # "timetracker — npm run dev — 80×24"
            parts = title.split('—')
            if len(parts) >= 2:
                return parts[1].strip()[:50]
        return title[:50]
    
    # ========================================
    # VS CODE - Extract file + project
    # ========================================
    if 'code' in app_name.lower() or 'visual studio' in app_name.lower():
        # "tasks.py - timetracker - Visual Studio Code" → "tasks.py (timetracker)"
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
        # "druss16/timetracker: Time tracking - Pull requests" → "timetracker - Pull requests"
        parts = title.split(' - ')
        # Find repo name
        for i, part in enumerate(parts):
            if '/' in part and ':' in part:
                # "druss16/timetracker: description"
                repo = part.split('/')[1].split(':')[0]
                context = parts[i+1] if i+1 < len(parts) else ''
                if context:
                    return f"{repo} - {context}"
                return repo
        # Fallback
        return title.replace('GitHub', '').strip(' -–')[:50]
    
    # ========================================
    # LOCALHOST/DEV - Extract port + context
    # ========================================
    if 'localhost' in title.lower() or '127.0.0.1' in title.lower():
        # "TimeTracker - localhost:5173" → "localhost:5173"
        port_match = regex.search(r'localhost:(\d+)', title, regex.IGNORECASE)
        if port_match:
            port = port_match.group(0)
            # Get any title before it
            before = title.split(port)[0].strip(' -–|')
            if before and len(before) < 30:
                return f"{port} ({before})"
            return port
        return title[:50]
    
    # ========================================
    # EMAIL - Extract subject
    # ========================================
    if any(x in title.lower() for x in ['inbox', 'mail', 'outlook', 'gmail']):
        # Remove email addresses
        title = regex.sub(r'\s*[-–—]\s*\S+@\S+\.\S+', '', title)
        title = regex.sub(r'\s*\(\d+\)\s*', ' ', title)  # Remove (5) counts
        title = regex.sub(r'^(RE|FW|Fwd):\s*', '', title, flags=regex.IGNORECASE)
        return title.strip()[:50]
    
    # ========================================
    # GENERIC - Take first meaningful part
    # ========================================
    parts = [p.strip() for p in regex.split(r'\s*[-–—|]\s*', title)]
    
    # Filter out generic parts
    generic = ['home', 'dashboard', 'new tab', 'untitled', 'document']
    meaningful_parts = [p for p in parts if p.lower() not in generic and len(p) > 2]
    
    if meaningful_parts:
        # Take first 1-2 parts
        if len(meaningful_parts) >= 2 and len(meaningful_parts[0]) + len(meaningful_parts[1]) < 50:
            return f"{meaningful_parts[0]} - {meaningful_parts[1]}"
        return meaningful_parts[0][:50]
    
    return title[:50] if title else ''


def format_block_for_display(block: Dict[str, Any], client_name: str = '') -> Dict[str, Any]:
    """
    Format a block for clean UI display.
    
    OUTPUT FORMAT: "App - Context"
    
    Examples:
        "Chrome - Aurelia Dashboard"
        "VS Code - tasks.py (timetracker)"  
        "Terminal - npm run dev"
        "Zoom - Client Meeting"
    
    Args:
        block: Block data dict with keys like app_name, window_title, url, minutes, category
        client_name: Optional client name for context
    
    Returns:
        Dict with clean display values
    """
    app_name = block.get('app_name', '')
    window_title = block.get('window_title', '')
    url = block.get('url', '')
    minutes = block.get('minutes', 0) or 0
    category = block.get('category') or block.get('ai_category', '')
    
    # Clean app name
    clean_app = clean_app_name(app_name)
    
    # Extract context from window title
    context = extract_context_from_title(window_title, app_name, url, client_name)
    
    # If no context from title, try URL
    if not context and url:
        context = clean_url_for_display(url) or ''
    
    # Build display title in "App - Context" format
    if clean_app and context:
        # Don't duplicate if context already contains app name
        if clean_app.lower() in context.lower():
            display_title = context
        else:
            display_title = f"{clean_app} - {context}"
    elif context:
        display_title = context
    elif clean_app:
        display_title = clean_app
    else:
        display_title = 'Activity'
    
    # Add client context if missing and would be helpful
    if client_name and client_name.lower() not in display_title.lower():
        # Only add for generic activities
        generic_apps = ['chrome', 'firefox', 'safari', 'edge']
        if clean_app.lower() in generic_apps and len(display_title) < 40:
            display_title = f"{display_title} ({client_name})"
    
    return {
        'title': display_title,
        'app': clean_app,
        'duration': format_duration(minutes),
        'duration_long': format_duration_long(minutes),
        'minutes': round(minutes, 1),
        'category': category,
        'category_icon': get_category_icon(category),
    }


def format_blocks_grouped(blocks: List[Dict], include_samples: bool = True) -> List[Dict]:
    """
    Group blocks by client → category and format for display.
    
    This produces output like the demo:
    - Client name with total
    - Categories with counts
    - Sample activities with durations
    
    Args:
        blocks: List of block dicts with client, category, minutes, etc.
        include_samples: Whether to include sample activity titles
    
    Returns:
        List of client groups with nested categories
    """
    from collections import defaultdict
    
    # Group: client → category → blocks
    grouped = defaultdict(lambda: defaultdict(list))
    
    for block in blocks:
        client = block.get('client_name') or block.get('client') or 'Unassigned'
        
        # Get category from category_hours or ai_category
        category = None
        if block.get('category_hours'):
            cats = block['category_hours']
            if isinstance(cats, dict) and cats:
                category = list(cats.keys())[0]
        if not category:
            category = block.get('ai_category') or block.get('category') or 'Uncategorized'
        
        grouped[client][category].append(block)
    
    # Build clean output
    result = []
    
    for client, categories in sorted(grouped.items()):
        client_total_minutes = 0
        category_list = []
        
        for category, cat_blocks in sorted(categories.items()):
            cat_minutes = sum(b.get('minutes', 0) or 0 for b in cat_blocks)
            client_total_minutes += cat_minutes
            
            # Format sample activities
            samples = []
            if include_samples:
                # Sort by duration, take top 5
                sorted_blocks = sorted(cat_blocks, key=lambda b: b.get('minutes', 0) or 0, reverse=True)
                for b in sorted_blocks[:5]:
                    formatted = format_block_for_display(b, client)
                    samples.append(f"{formatted['title']} ({formatted['duration']})")
            
            category_list.append({
                'name': category,
                'icon': get_category_icon(category),
                'block_count': len(cat_blocks),
                'minutes': round(cat_minutes, 1),
                'hours': round(cat_minutes / 60, 2),
                'duration': format_duration(cat_minutes),
                'samples': samples,
            })
        
        result.append({
            'client': client,
            'category_count': len(category_list),
            'total_minutes': round(client_total_minutes, 1),
            'total_hours': round(client_total_minutes / 60, 2),
            'duration': format_duration(client_total_minutes),
            'categories': category_list,
        })
    
    # Sort by total time descending
    result.sort(key=lambda x: x['total_minutes'], reverse=True)
    
    return result


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == '__main__':
    # Test with messy real-world data
    test_blocks = [
        {
            'app_name': 'Google Chrome',
            'window_title': 'QuickBooks Online - Chart of Accounts - Acme Corp LLC - Google Chrome',
            'url': 'https://qbo.intuit.com/app/chartofaccounts',
            'minutes': 45,
            'client_name': 'Acme Corp',
            'category_hours': {'Bookkeeping': 0.75},
        },
        {
            'app_name': 'Microsoft Outlook',
            'window_title': 'Message (HTML) RE: Tax documents needed for 2024 return - John Smith',
            'url': '',
            'minutes': 12,
            'client_name': 'Smith Family',
            'category_hours': {'Email/Communication': 0.2},
        },
        {
            'app_name': 'zoom.us',
            'window_title': 'Zoom Meeting - Tax Review with Johnson Holdings',
            'url': '',
            'minutes': 30,
            'client_name': 'Johnson Holdings',
            'category_hours': {'Meetings': 0.5},
        },
    ]
    
    print("=" * 60)
    print("INDIVIDUAL BLOCK FORMATTING")
    print("=" * 60)
    
    for block in test_blocks:
        formatted = format_block_for_display(block, block.get('client_name', ''))
        print(f"\nRAW: {block['window_title'][:50]}...")
        print(f"CLEAN: {formatted['title']} ({formatted['duration']})")
    
    print("\n" + "=" * 60)
    print("GROUPED OUTPUT (like demo)")
    print("=" * 60)
    
    grouped = format_blocks_grouped(test_blocks)
    for client_group in grouped:
        print(f"\n{client_group['client']} - {client_group['category_count']} categories")
        print(f"  Total: {client_group['duration']}")
        for cat in client_group['categories']:
            print(f"  {cat['icon']} {cat['name']} ({cat['block_count']})")
            print(f"     {cat['duration']}")
            for sample in cat['samples']:
                print(f"     • {sample}")