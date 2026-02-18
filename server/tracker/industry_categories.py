# tracker/industry_categories.py
"""
Industry-specific category configurations for TimeTracker.

SINGLE SOURCE OF TRUTH for:
- Category lists (dropdowns, validation, AI prompts)
- Tool detection patterns (auto-categorization + pre-classification)
- AI prompt generation (system + user prompts)
- Seasonal context
- Task type seeds

UNIVERSAL categories added to ALL industries:
- "Idle" (system-detected inactivity)
- "Personal/Non-Billable" (social media, personal browsing, etc.)
"""

# =============================================================================
# INDUSTRY TYPES
# =============================================================================

INDUSTRY_TYPES = [
    ('cpa', 'CPA / Accounting Firm'),
    ('ai_consulting', 'AI / Technology Consulting'),
    ('marketing', 'Marketing / Creative Agency'),
    ('legal', 'Law Firm'),
    ('general', 'General Professional Services'),
]

INDUSTRY_CHOICES = [(k, v) for k, v in INDUSTRY_TYPES]


# =============================================================================
# UNIVERSAL CATEGORIES (added to every industry)
# =============================================================================

UNIVERSAL_SYSTEM_CATEGORIES = [
    "Idle",
    "Personal/Non-Billable",
]


# =============================================================================
# PERSONAL / NON-WORK DETECTION (universal across all industries)
# =============================================================================

PERSONAL_SITE_DETECTION = {
    "social_media": {
        "keywords": [
            "facebook", "instagram", "tiktok", "snapchat", "pinterest",
            "twitter", "x.com", "threads", "mastodon", "bluesky",
            "linkedin.com/feed", "linkedin.com/messaging",
        ],
        "domains": [
            "facebook.com", "instagram.com", "tiktok.com", "snapchat.com",
            "pinterest.com", "twitter.com", "x.com", "threads.net",
            "mastodon.social", "bsky.app",
        ],
        "category": "Personal/Non-Billable",
        "confidence": 0.92
    },
    "streaming": {
        "keywords": [
            "netflix", "hulu", "disney+", "disneyplus", "amazon prime video",
            "hbo max", "max.com", "peacock", "paramount+", "apple tv+",
            "crunchyroll", "spotify", "pandora", "apple music",
        ],
        "domains": [
            "netflix.com", "hulu.com", "disneyplus.com", "max.com",
            "peacocktv.com", "paramountplus.com", "tv.apple.com",
            "crunchyroll.com", "spotify.com", "pandora.com",
        ],
        "category": "Personal/Non-Billable",
        "confidence": 0.95
    },
    "video_entertainment": {
        "keywords": ["youtube", "twitch", "rumble"],
        "domains": ["youtube.com", "twitch.tv", "rumble.com"],
        "category": "Personal/Non-Billable",
        "confidence": 0.80  # Lower - YouTube can be work-related tutorials
    },
    "news_casual": {
        "keywords": ["reddit", "buzzfeed", "9gag", "imgur"],
        "domains": ["reddit.com", "buzzfeed.com", "9gag.com", "imgur.com"],
        "category": "Personal/Non-Billable",
        "confidence": 0.82  # Lower - Reddit can be work research
    },
    "shopping": {
        "keywords": [
            "amazon.com/gp", "amazon.com/dp", "ebay", "etsy", "walmart",
            "target.com", "bestbuy", "wayfair", "aliexpress",
        ],
        "domains": [
            "amazon.com", "ebay.com", "etsy.com", "walmart.com",
            "target.com", "bestbuy.com", "wayfair.com", "aliexpress.com",
        ],
        "category": "Personal/Non-Billable",
        "confidence": 0.85
    },
    "personal_finance": {
        "keywords": ["mint.com", "venmo", "zelle", "cashapp", "personal banking"],
        "domains": [
            "mint.intuit.com", "venmo.com", "cash.app",
        ],
        "category": "Personal/Non-Billable",
        "confidence": 0.85
    },
    "gaming": {
        "keywords": ["steam", "epic games", "roblox", "minecraft"],
        "domains": ["store.steampowered.com", "epicgames.com", "roblox.com"],
        "category": "Personal/Non-Billable",
        "confidence": 0.95
    },
    "dating": {
        "keywords": ["tinder", "bumble", "hinge", "match.com"],
        "domains": ["tinder.com", "bumble.com", "hinge.co", "match.com"],
        "category": "Personal/Non-Billable",
        "confidence": 0.98
    },
}


# =============================================================================
# CPA / ACCOUNTING FIRM CATEGORIES
# =============================================================================

CPA_CATEGORIES = [
    *UNIVERSAL_SYSTEM_CATEGORIES,
    "Tax Preparation",
    "Tax Planning",
    "Tax Research",
    "Tax Compliance",
    "Accounting/Bookkeeping",
    "Financial Statement Prep",
    "Audit/Assurance",
    "Payroll Services",
    "Advisory/Financial Planning",
    "Valuation/Advisory",
    "Forensic/Fraud Investigation",
    "SEC/Regulatory Compliance",
    "Employee Benefits/ERISA",
    "Real Estate/Property",
    "Nonprofit/Form 990",
    "Healthcare/Medical Practice",
    "Construction/Contractors",
    "Email/Communication",
    "Meetings",
    "Administration",
    "Document Management",
    "Review",
]

CPA_TOOL_DETECTION = {
    "ultratax": {
        "keywords": ["ultratax", "cch axcess", "proseries", "drake", "lacerte", "atx"],
        "domains": ["cchaxcess.com", "cchtaxoffice.com", "proseries.com"],
        "category": "Tax Preparation",
        "confidence": 0.95
    },
    "quickbooks": {
        "keywords": ["quickbooks", "qbo", "quickbooks online"],
        "domains": ["quickbooks.intuit.com", "qbo.intuit.com", "app.quickbooks.com"],
        "category": "Accounting/Bookkeeping",
        "confidence": 0.93
    },
    "xero": {
        "keywords": ["xero"],
        "domains": ["xero.com", "go.xero.com"],
        "category": "Accounting/Bookkeeping",
        "confidence": 0.93
    },
    "sage": {
        "keywords": ["sage", "sage intacct"],
        "domains": ["sage.com", "intacct.com"],
        "category": "Accounting/Bookkeeping",
        "confidence": 0.90
    },
    "irs": {
        "keywords": ["irs.gov", "internal revenue"],
        "domains": ["irs.gov"],
        "category": "Tax Research",
        "confidence": 0.93
    },
    "tax_research": {
        "keywords": [
            "checkpoint", "thomsonreuters", "tax notes", "taxnotes",
            "bna", "bloomberg tax", "tax foundation",
        ],
        "domains": [
            "checkpoint.riag.com", "taxnotes.com", "bloombergtax.com",
        ],
        "category": "Tax Research",
        "confidence": 0.92
    },
    "payroll": {
        "keywords": ["adp", "gusto", "paychex", "paylocity"],
        "domains": ["adp.com", "gusto.com", "paychex.com", "paylocity.com"],
        "category": "Payroll Services",
        "confidence": 0.90
    },
    "document_mgmt": {
        "keywords": [
            "sharefile", "citrix sharefile", "smartvault", "canopy",
            "suralink", "liscio",
        ],
        "domains": [
            "sharefile.com", "smartvault.com", "canopytax.com",
            "suralink.com", "liscio.me",
        ],
        "category": "Document Management",
        "confidence": 0.85
    },
    "karbon": {
        "keywords": ["karbon", "karbonhq"],
        "domains": ["karbonhq.com"],
        "category": "Administration",
        "confidence": 0.85
    },
}

CPA_TASK_TYPES = [
    {"name": "Tax Preparation", "code": "TAX", "color": "#2563eb", "is_billable": True},
    {"name": "Tax Planning", "code": "PLAN", "color": "#7c3aed", "is_billable": True},
    {"name": "Accounting/Bookkeeping", "code": "ACCT", "color": "#059669", "is_billable": True},
    {"name": "Audit/Assurance", "code": "AUDIT", "color": "#dc2626", "is_billable": True},
    {"name": "Advisory", "code": "ADV", "color": "#ea580c", "is_billable": True},
    {"name": "Email/Communication", "code": "EMAIL", "color": "#6b7280", "is_billable": False},
    {"name": "Meetings", "code": "MTG", "color": "#0891b2", "is_billable": True},
    {"name": "Administration", "code": "ADMIN", "color": "#9ca3af", "is_billable": False},
    {"name": "Personal/Non-Billable", "code": "PERS", "color": "#d1d5db", "is_billable": False},
]


# =============================================================================
# AI / TECHNOLOGY CONSULTING CATEGORIES
# =============================================================================

AI_CONSULTING_CATEGORIES = [
    *UNIVERSAL_SYSTEM_CATEGORIES,

    # --- Core development ---
    "Software Development",
    "Code Review",
    "Architecture/Design",
    "Testing/QA",
    "Debugging",
    "DevOps/Deployment",
    "Infrastructure",
    "Database Work",
    "API Development",

    # --- AI/ML specific ---
    "Model Development",
    "Prompt Engineering",
    "Data Preparation",
    "Model Training",
    "Model Evaluation",
    "AI Research",

    # --- Research & documentation ---
    "Research/AI Assistance",
    "Documentation",
    "Technical Writing",
    "Learning/Upskilling",

    # Client marketing services
    "Marketing/Advertising",
    "SEO/Analytics",
    "Social Media Management",
    "Email Marketing",
    "Website/Web Development",
    "Content Creation",
    "Graphic Design",

    # --- Client-facing ---
    "Client Discovery",
    "Requirements Gathering",
    "Technical Consulting",
    "Training/Workshop",
    "Presentations/Proposals",

    # --- Internal/admin ---
    "Project Management",
    "Email/Communication",
    "Meetings",
    "Administration",
    "Sales/Business Dev",
]

# =============================================================================
# INTERNAL CLIENT CATEGORIES (same for all industries)
# =============================================================================

INTERNAL_CATEGORIES = [
    *UNIVERSAL_SYSTEM_CATEGORIES,
    "Administration",
    "Team Meetings",
    "Training/Professional Development",
    "Business Development/Sales",
    "Hiring/HR",
    "Company Planning",
    "Internal Projects",
    "Marketing (Own Firm)",
    "IT/Tech Support",
    "Finance/Accounting (Own Firm)",
    "PTO/Time Off",
    "Email/Communication",
]

# =============================================================================
# AI CONSULTING TOOL DETECTION
# =============================================================================

AI_CONSULTING_TOOL_DETECTION = {

    # ── Development tools ──────────────────────────────────────────────────
    "vscode": {
        "keywords": [
            "visual studio code", "vscode", "vs code",
            "code - ", ".py - ", ".js - ", ".tsx - ", ".jsx - ",
            "tasks.py", "views.py", "models.py", "settings.py",
            "index.tsx", "app.tsx",
        ],
        "domains": [],
        "category": "Software Development",
        "confidence": 0.95
    },
    "terminal": {
        "keywords": [
            "terminal", "iterm", "iterm2", "warp",
            "docker compose", "python manage.py", "npm run", "git ", "celery -A",
        ],
        "domains": [],
        "category": "Software Development",
        "confidence": 0.90
    },
    "github": {
        "keywords": ["github", "pull request", "commit", "repository"],
        "domains": ["github.com", "gitlab.com", "bitbucket.org"],
        "category": "Software Development",
        "confidence": 0.92
    },
    "localhost": {
        "keywords": ["localhost", "127.0.0.1", ":3000", ":8000", ":5173", ":7123"],
        "domains": ["localhost", "127.0.0.1"],
        "category": "Software Development",
        "confidence": 0.88
    },
    "deployment": {
        "keywords": ["render.com", "vercel", "heroku", "docker", "kubernetes", "neon.tech"],
        "domains": ["render.com", "dashboard.render.com", "vercel.com", "console.neon.tech"],
        "category": "DevOps/Deployment",
        "confidence": 0.90
    },

    # ── AI / Research tools ────────────────────────────────────────────────
    "claude": {
        "keywords": ["claude", "claude.ai", "anthropic"],
        "domains": ["claude.ai"],
        "category": "Research/AI Assistance",
        "confidence": 0.92
    },
    "chatgpt": {
        "keywords": ["chatgpt", "openai", "gpt-4"],
        "domains": ["chat.openai.com", "chatgpt.com"],
        "category": "Research/AI Assistance",
        "confidence": 0.92
    },
    "jupyter": {
        "keywords": ["jupyter", "notebook", "colab"],
        "domains": ["colab.research.google.com"],
        "category": "Model Development",
        "confidence": 0.90
    },
    "huggingface": {
        "keywords": ["huggingface", "transformers"],
        "domains": ["huggingface.co"],
        "category": "AI Research",
        "confidence": 0.88
    },

    # ── Marketing / Advertising tools ──────────────────────────────────────
    "google_ads": {
        "keywords": [
            "google ads", "adwords", "ads.google.com",
            "campaign manager", "ad campaign", "ad group",
            "google ads - ", "- google ads",
        ],
        "domains": ["ads.google.com"],
        "category": "Marketing/Advertising",
        "confidence": 0.95
    },
    "meta_ads": {
        "keywords": [
            "facebook ads", "meta ads", "ads manager",
            "adsmanager.facebook", "meta business",
        ],
        "domains": ["business.facebook.com", "adsmanager.facebook.com"],
        "category": "Marketing/Advertising",
        "confidence": 0.94
    },
    "google_analytics": {
        "keywords": ["google analytics", "ga4", "analytics.google"],
        "domains": ["analytics.google.com"],
        "category": "SEO/Analytics",
        "confidence": 0.90
    },
    "search_console": {
        "keywords": ["search console", "google search console"],
        "domains": ["search.google.com/search-console"],
        "category": "SEO/Analytics",
        "confidence": 0.90
    },
    "semrush": {
        "keywords": ["semrush", "ahrefs", "moz"],
        "domains": ["semrush.com", "ahrefs.com"],
        "category": "SEO/Analytics",
        "confidence": 0.90
    },
    "mailchimp": {
        "keywords": ["mailchimp", "klaviyo", "constant contact", "campaign monitor"],
        "domains": ["mailchimp.com", "klaviyo.com"],
        "category": "Email Marketing",
        "confidence": 0.92
    },
    "canva": {
        "keywords": ["canva"],
        "domains": ["canva.com"],
        "category": "Graphic Design",
        "confidence": 0.90
    },
    "figma": {
        "keywords": ["figma"],
        "domains": ["figma.com"],
        "category": "Graphic Design",
        "confidence": 0.93
    },
    "wordpress": {
        "keywords": ["wordpress", "wp-admin", "elementor", "wix", "squarespace"],
        "domains": ["wordpress.com", "wix.com", "squarespace.com"],
        "category": "Website/Web Development",
        "confidence": 0.88
    },
    "hubspot": {
        "keywords": ["hubspot"],
        "domains": ["app.hubspot.com"],
        "category": "Marketing/Advertising",
        "confidence": 0.85
    },
    "hootsuite": {
        "keywords": ["hootsuite", "buffer", "sprout social", "later"],
        "domains": ["hootsuite.com", "buffer.com", "sproutsocial.com"],
        "category": "Social Media Management",
        "confidence": 0.90
    },
}


AI_CONSULTING_TASK_TYPES = [
    {"name": "Software Development", "code": "DEV", "color": "#2563eb", "is_billable": True},
    {"name": "Model Development", "code": "ML", "color": "#7c3aed", "is_billable": True},
    {"name": "Prompt Engineering", "code": "PROMPT", "color": "#db2777", "is_billable": True},
    {"name": "Technical Consulting", "code": "CONSULT", "color": "#059669", "is_billable": True},
    {"name": "Research", "code": "RES", "color": "#ea580c", "is_billable": True},
    {"name": "DevOps/Deployment", "code": "DEVOPS", "color": "#0891b2", "is_billable": True},
    {"name": "Meetings", "code": "MTG", "color": "#6366f1", "is_billable": True},
    {"name": "Email/Communication", "code": "EMAIL", "color": "#6b7280", "is_billable": False},
    {"name": "Administration", "code": "ADMIN", "color": "#9ca3af", "is_billable": False},
    {"name": "Personal/Non-Billable", "code": "PERS", "color": "#d1d5db", "is_billable": False},
]


# =============================================================================
# MARKETING / CREATIVE AGENCY CATEGORIES
# =============================================================================

MARKETING_CATEGORIES = [
    *UNIVERSAL_SYSTEM_CATEGORIES,
    "Strategy/Planning",
    "Campaign Planning",
    "Market Research",
    "Competitive Analysis",
    "Client Discovery",
    "Content Writing",
    "Copywriting",
    "Blog/Article Writing",
    "Social Media Content",
    "Video Scripting",
    "Graphic Design",
    "Video Production",
    "Video Editing",
    "Photography",
    "Brand Development",
    "UI/UX Design",
    "SEO/SEM",
    "Paid Advertising",
    "Email Marketing",
    "Social Media Management",
    "Analytics/Reporting",
    "Web Development",
    "Website Updates",
    "Landing Pages",
    "CMS Management",
    "Client Meetings",
    "Presentations",
    "Proposals/Pitches",
    "Account Management",
    "Email/Communication",
    "Meetings",
    "Project Management",
    "Administration",
    "Billing/Invoicing",
]

MARKETING_TOOL_DETECTION = {
    "figma": {
        "keywords": ["figma"],
        "domains": ["figma.com"],
        "category": "Graphic Design",
        "confidence": 0.93
    },
    "canva": {
        "keywords": ["canva"],
        "domains": ["canva.com"],
        "category": "Graphic Design",
        "confidence": 0.90
    },
    "adobe": {
        "keywords": ["photoshop", "illustrator", "premiere", "after effects", "indesign"],
        "domains": ["adobe.com", "creativecloud.adobe.com"],
        "category": "Graphic Design",
        "confidence": 0.92
    },
    "google_ads": {
        "keywords": ["google ads", "adwords"],
        "domains": ["ads.google.com"],
        "category": "Paid Advertising",
        "confidence": 0.93
    },
    "meta_ads": {
        "keywords": ["facebook ads", "meta ads", "instagram ads"],
        "domains": ["business.facebook.com", "adsmanager.facebook.com"],
        "category": "Paid Advertising",
        "confidence": 0.93
    },
    "analytics": {
        "keywords": ["google analytics", "ga4"],
        "domains": ["analytics.google.com"],
        "category": "Analytics/Reporting",
        "confidence": 0.90
    },
    "mailchimp": {
        "keywords": ["mailchimp", "campaign monitor", "klaviyo", "constant contact"],
        "domains": ["mailchimp.com", "klaviyo.com"],
        "category": "Email Marketing",
        "confidence": 0.92
    },
    "social": {
        "keywords": ["hootsuite", "buffer", "sprout social", "later"],
        "domains": ["hootsuite.com", "buffer.com", "sproutsocial.com"],
        "category": "Social Media Management",
        "confidence": 0.90
    },
    "wordpress": {
        "keywords": ["wordpress", "wp-admin", "elementor", "wix", "squarespace"],
        "domains": ["wordpress.com", "wix.com", "squarespace.com"],
        "category": "Website Updates",
        "confidence": 0.88
    },
    "semrush": {
        "keywords": ["semrush", "ahrefs", "moz", "screaming frog"],
        "domains": ["semrush.com", "ahrefs.com", "moz.com"],
        "category": "SEO/SEM",
        "confidence": 0.90
    },
    "hubspot": {
        "keywords": ["hubspot"],
        "domains": ["hubspot.com", "app.hubspot.com"],
        "category": "Account Management",
        "confidence": 0.85
    },
}

MARKETING_TASK_TYPES = [
    {"name": "Strategy/Planning", "code": "STRAT", "color": "#7c3aed", "is_billable": True},
    {"name": "Content Writing", "code": "CONTENT", "color": "#2563eb", "is_billable": True},
    {"name": "Graphic Design", "code": "DESIGN", "color": "#db2777", "is_billable": True},
    {"name": "Video Production", "code": "VIDEO", "color": "#ea580c", "is_billable": True},
    {"name": "Paid Advertising", "code": "ADS", "color": "#059669", "is_billable": True},
    {"name": "SEO/SEM", "code": "SEO", "color": "#0891b2", "is_billable": True},
    {"name": "Social Media", "code": "SOCIAL", "color": "#6366f1", "is_billable": True},
    {"name": "Client Meetings", "code": "MTG", "color": "#f59e0b", "is_billable": True},
    {"name": "Email/Communication", "code": "EMAIL", "color": "#6b7280", "is_billable": False},
    {"name": "Administration", "code": "ADMIN", "color": "#9ca3af", "is_billable": False},
    {"name": "Personal/Non-Billable", "code": "PERS", "color": "#d1d5db", "is_billable": False},
]


# =============================================================================
# LEGAL FIRM CATEGORIES
# =============================================================================

LEGAL_CATEGORIES = [
    *UNIVERSAL_SYSTEM_CATEGORIES,
    "Legal Research",
    "Document Drafting",
    "Contract Review",
    "Brief Writing",
    "Case Preparation",
    "Litigation",
    "Discovery",
    "Depositions",
    "Court Appearances",
    "Trial Preparation",
    "Client Consultation",
    "Client Communication",
    "Negotiations",
    "Due Diligence",
    "Closing",
    "Regulatory Filing",
    "Email/Communication",
    "Meetings",
    "Administration",
    "Billing",
    "CLE/Training",
]

LEGAL_TOOL_DETECTION = {
    "westlaw": {
        "keywords": ["westlaw", "thomson reuters"],
        "domains": ["westlaw.com", "1.next.westlaw.com"],
        "category": "Legal Research",
        "confidence": 0.95
    },
    "lexis": {
        "keywords": ["lexis", "lexisnexis"],
        "domains": ["lexis.com", "lexisnexis.com"],
        "category": "Legal Research",
        "confidence": 0.95
    },
    "clio": {
        "keywords": ["clio"],
        "domains": ["clio.com", "app.clio.com"],
        "category": "Administration",
        "confidence": 0.85
    },
    "fastcase": {
        "keywords": ["fastcase", "vlex"],
        "domains": ["fastcase.com", "vlex.com"],
        "category": "Legal Research",
        "confidence": 0.92
    },
}

LEGAL_TASK_TYPES = [
    {"name": "Legal Research", "code": "RES", "color": "#2563eb", "is_billable": True},
    {"name": "Document Drafting", "code": "DRAFT", "color": "#7c3aed", "is_billable": True},
    {"name": "Litigation", "code": "LIT", "color": "#dc2626", "is_billable": True},
    {"name": "Client Consultation", "code": "CONSULT", "color": "#059669", "is_billable": True},
    {"name": "Meetings", "code": "MTG", "color": "#0891b2", "is_billable": True},
    {"name": "Email/Communication", "code": "EMAIL", "color": "#6b7280", "is_billable": False},
    {"name": "Administration", "code": "ADMIN", "color": "#9ca3af", "is_billable": False},
    {"name": "Personal/Non-Billable", "code": "PERS", "color": "#d1d5db", "is_billable": False},
]


# =============================================================================
# GENERAL PROFESSIONAL SERVICES (FALLBACK)
# =============================================================================

GENERAL_CATEGORIES = [
    *UNIVERSAL_SYSTEM_CATEGORIES,
    "Project Work",
    "Client Work",
    "Research",
    "Documentation",
    "Review",
    "Email/Communication",
    "Meetings",
    "Calls",
    "Administration",
    "Planning",
    "Travel",
]

GENERAL_TOOL_DETECTION = {
    "zoom": {
        "keywords": ["zoom", "zoom meeting"],
        "domains": ["zoom.us"],
        "category": "Meetings",
        "confidence": 0.95
    },
    "teams": {
        "keywords": ["microsoft teams", "teams"],
        "domains": ["teams.microsoft.com"],
        "category": "Meetings",
        "confidence": 0.95
    },
    "gmail": {
        "keywords": ["gmail", "inbox"],
        "domains": ["mail.google.com"],
        "category": "Email/Communication",
        "confidence": 0.92
    },
    "outlook": {
        "keywords": ["outlook"],
        "domains": ["outlook.office.com"],
        "category": "Email/Communication",
        "confidence": 0.92
    },
}

GENERAL_TASK_TYPES = [
    {"name": "Project Work", "code": "PROJ", "color": "#2563eb", "is_billable": True},
    {"name": "Client Work", "code": "CLIENT", "color": "#7c3aed", "is_billable": True},
    {"name": "Meetings", "code": "MTG", "color": "#0891b2", "is_billable": True},
    {"name": "Email/Communication", "code": "EMAIL", "color": "#6b7280", "is_billable": False},
    {"name": "Administration", "code": "ADMIN", "color": "#9ca3af", "is_billable": False},
    {"name": "Personal/Non-Billable", "code": "PERS", "color": "#d1d5db", "is_billable": False},
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_categories_for_industry(industry_type: str, client_code: str = None) -> list:
    """Get category list. Returns internal categories if client is Internal."""
    if client_code == 'INTERNAL':
        return INTERNAL_CATEGORIES

    mapping = {
        'cpa': CPA_CATEGORIES,
        'ai_consulting': AI_CONSULTING_CATEGORIES,
        'marketing': MARKETING_CATEGORIES,
        'legal': LEGAL_CATEGORIES,
        'general': GENERAL_CATEGORIES,
    }
    return mapping.get(industry_type, GENERAL_CATEGORIES)


def get_tool_detection_for_industry(industry_type: str) -> dict:
    """Get tool detection patterns for a specific industry type."""
    mapping = {
        'cpa': CPA_TOOL_DETECTION,
        'ai_consulting': AI_CONSULTING_TOOL_DETECTION,
        'marketing': MARKETING_TOOL_DETECTION,
        'legal': LEGAL_TOOL_DETECTION,
        'general': GENERAL_TOOL_DETECTION,
    }
    return mapping.get(industry_type, GENERAL_TOOL_DETECTION)


def get_task_types_for_industry(industry_type: str) -> list:
    """Get default TaskType configurations for a specific industry type."""
    mapping = {
        'cpa': CPA_TASK_TYPES,
        'ai_consulting': AI_CONSULTING_TASK_TYPES,
        'marketing': MARKETING_TASK_TYPES,
        'legal': LEGAL_TASK_TYPES,
        'general': GENERAL_TASK_TYPES,
    }
    return mapping.get(industry_type, GENERAL_TASK_TYPES)


# =============================================================================
# SEASONAL CONTEXT — SINGLE SOURCE OF TRUTH
# =============================================================================

def get_seasonal_context_for_industry(industry_type: str) -> str:
    """
    Get seasonal context hints for AI classification.
    This is the ONLY seasonal context function — the duplicate in views.py
    should be removed.
    """
    from datetime import datetime
    now = datetime.now()
    month = now.month
    day = now.day

    if industry_type == 'cpa':
        if month == 1:
            return (
                "**SEASON: EARLY TAX SEASON (January)**\n"
                "Tax season starting. Organizing documents, early returns (1040),\n"
                "business returns with fiscal year-ends. Default ambiguous work to\n"
                "'Tax Preparation' (confidence 0.75)."
            )
        elif month == 2:
            return (
                "**SEASON: MID TAX SEASON (February)**\n"
                "Heavy individual tax prep. Partnership (1065) and S-Corp (1120S)\n"
                "returns due 3/15. Default ambiguous work to 'Tax Preparation'."
            )
        elif month == 3:
            return (
                "**SEASON: PEAK TAX SEASON (March)**\n"
                "Maximum volume. Partnership/S-Corp deadline 3/15. Extensions starting.\n"
                "Default to 'Tax Preparation' for almost anything ambiguous."
            )
        elif month == 4 and day <= 15:
            return (
                "**SEASON: TAX SEASON FINALE (April 1-15)**\n"
                "Final push to 4/15. Individual (1040) and C-Corp (1120) due.\n"
                "Extensions filed. Default to 'Tax Preparation' or 'Review'."
            )
        elif month == 4 and day > 15:
            return (
                "**SEASON: POST-TAX RECOVERY (Late April)**\n"
                "Recovery period. Catching up on correspondence, filing extensions,\n"
                "administration, planning."
            )
        elif month in (5, 6, 7, 8):
            return (
                "**SEASON: OFF-SEASON (May-Aug)**\n"
                "Advisory, bookkeeping catch-up, audit work, tax planning,\n"
                "training/CPE, practice management."
            )
        elif month == 9 or (month == 10 and day <= 15):
            return (
                "**SEASON: EXTENSION SEASON (Sep-Oct 15)**\n"
                "Extended return deadlines. Individual extensions due 10/15,\n"
                "partnership/S-Corp extensions due 9/15. Prefer 'Tax Compliance'."
            )
        elif month in (11, 12):
            return (
                "**SEASON: YEAR-END PLANNING (Nov-Dec)**\n"
                "Year-end tax planning, estimated payments, financial statement\n"
                "prep, advisory services."
            )
        return "**SEASON: REGULAR**\nMix of tax, accounting, advisory."

    elif industry_type == 'marketing':
        if month in (10, 11, 12):
            return (
                "**SEASON: Q4 HOLIDAY RUSH**\n"
                "Peak marketing. Holiday campaigns, year-end promotions, next-year budgeting."
            )
        elif month in (1, 2):
            return (
                "**SEASON: NEW YEAR PLANNING**\n"
                "Strategy development, campaign planning, budget allocation."
            )
        return "**SEASON: REGULAR OPERATIONS**\nStandard campaign and content work."

    elif industry_type == 'legal':
        return (
            "**CONTEXT: LAW FIRM**\n"
            "Almost all client work is billable. Only mark Personal/Non-Billable\n"
            "for clearly personal browsing."
        )

    elif industry_type == 'ai_consulting':
        return (
            "**CONTEXT: AI/TECH CONSULTING**\n"
            "Development sprints, client deliverables, research, prototyping.\n"
            "Also delivers marketing/web services to clients."
        )

    return "**CONTEXT: PROFESSIONAL SERVICES**\nStandard client work and operations."


# =============================================================================
# AI PROMPT GENERATION — SINGLE SOURCE OF TRUTH
# =============================================================================

def build_ai_prompt_for_industry(industry_type: str) -> str:
    """
    Build the SYSTEM PROMPT for AI classification.

    This is the ONLY prompt builder that defines categories and rules.
    The user prompt (build_classification_user_prompt) just sends block data.
    """
    categories = get_categories_for_industry(industry_type)
    seasonal = get_seasonal_context_for_industry(industry_type)

    industry_descriptions = {
        'cpa': "CPA/Accounting firm",
        'ai_consulting': "AI/Technology consulting firm that also provides marketing, advertising, and web services to clients",
        'marketing': "Marketing/Creative agency",
        'legal': "Law firm",
        'general': "Professional services firm",
    }

    industry_desc = industry_descriptions.get(industry_type, "Professional services firm")
    category_list = "\n".join([f"  - {cat}" for cat in categories if cat != "Idle"])

    extra_rules = _get_extra_rules(industry_type)
    common_mistakes = _get_common_mistakes(industry_type)
    internal_client_rules = _get_internal_client_rules()

    return f"""You are an expert time-tracking classifier for a {industry_desc}.
Your goal is to accurately categorize every billable minute into the correct client and category.

=== AVAILABLE CATEGORIES ===
You MUST use one of these EXACT names. Any other name is an error.
{category_list}
  - Idle

=== STRICT OUTPUT CONTRACT ===
1. The "categories" field MUST contain keys that EXACTLY match a name from the list above.
2. Do NOT invent new categories like "Tax Prep/Research" or "Email".
   Use the exact name: "Tax Preparation", "Email/Communication", etc.
3. If unsure between two categories, pick the more specific one.
4. Values are hours as decimals (e.g., 0.25 = 15 minutes).

=== CONFIDENCE SCORING ===
  0.95+ → Dedicated tool detected (UltraTax=Tax Prep, Figma=Graphic Design)
  0.85-0.94 → Clear app + context match (VS Code + .py file = Development)
  0.70-0.84 → Reasonable inference (browser on client portal)
  0.50-0.69 → Ambiguous, set needs_review: true
  <0.50 → Unknown, set needs_review: true, consider null client

=== CLIENT IDENTIFICATION ===
1. Check window titles for client names — often in parentheses or after "-"
2. Check URLs for client-specific domains or subdomains
3. Check file paths for client folder names (e.g., /Clients/Aurelia/)
4. If multiple clients appear in one block, assign to the DOMINANT one
5. If no client can be identified, set client: null (not "Unknown")

=== READING WINDOW TITLES ===
Window titles often follow: "App - Context (ClientName)"
  "Chrome - Ads (Dauphin & Fantacone)" → Marketing/Advertising, client=Dauphin & Fantacone
  "Chrome - Admin (Aurelia)" → Administration, client=Aurelia
  "VS Code - views.py (timetracker)" → Software Development, client from project context
  "Chrome - Newtab" → Transition, infer from surrounding blocks, confidence 0.50

=== CONTEXT FROM SURROUNDING BLOCKS ===
Blocks are ordered chronologically. Use neighboring blocks for clues:
  - If blocks 3-7 are all on the same client portal, a brief Chrome tab in the
    middle is probably still that client's work.
  - If a user switches from UltraTax to Chrome (IRS.gov) back to UltraTax,
    the Chrome block is likely "Tax Research" for the same client.
  - Brief idle gaps (<5 min) between same-client blocks don't mean a context switch.

=== UNIVERSAL RULES ===
1. Idle/screensaver/lock screen → category "Idle", client null, confidence 0.99
2. Social media, streaming, shopping, gaming, dating → "Personal/Non-Billable", client null
3. YouTube/Reddit at lower confidence (0.80) — could be work research
4. Email/Slack without clear client context → "Email/Communication", client null
5. Zoom/Meet/Teams → "Meetings", try to identify client from meeting title

{internal_client_rules}

{extra_rules}

{common_mistakes}

{seasonal}

=== RESPONSE FORMAT ===
Return ONLY a valid JSON array. No markdown fences. No explanation outside JSON.
One object per block, in the SAME ORDER as the input:
[
  {{
    "client": "Client Name" | null,
    "project": "Project Name" | null,
    "categories": {{"Exact Category Name": 0.25}},
    "confidence": 0.92,
    "needs_review": false,
    "reasoning": "One sentence explaining why"
  }}
]
"""


def build_classification_user_prompt(blocks: list, org_context: str = "") -> str:
    """
    Build the USER PROMPT for AI classification.

    This ONLY sends block data. It does NOT define categories or rules
    (those are in the system prompt from build_ai_prompt_for_industry).

    REPLACES the old build_classification_prompt() in views.py.
    """
    import json

    # Clean org context (optional — appended if present)
    context_section = ""
    if org_context:
        context_section = f"\n=== ORGANIZATION CONTEXT ===\n{org_context}\n"

    # Format blocks as clean JSON for the model
    blocks_json = json.dumps(blocks, indent=2, default=str)

    return f"""{context_section}
=== BLOCKS TO CLASSIFY ({len(blocks)} total) ===
{blocks_json}

Classify each block. Return ONLY a JSON array with {len(blocks)} objects, same order as input.
Use ONLY the category names from the system prompt. No markdown."""


def _get_internal_client_rules() -> str:
    """Rules for handling internal/firm work vs. client work."""
    internal_cats = "\n".join([f"    - {c}" for c in INTERNAL_CATEGORIES if c not in UNIVERSAL_SYSTEM_CATEGORIES])

    return f"""
=== INTERNAL vs. CLIENT WORK ===
If a block is clearly internal firm work (not for any client), set client to "Internal".
Internal work uses these categories:
{internal_cats}

Signals that work is internal:
  - Company's own website, own marketing, own social media
  - HR, hiring, team meetings without client context
  - Internal tools development (e.g., building the firm's own systems)
  - Training, CPE, professional development
  - Practice management software (Karbon, Canopy, etc.)
"""


def _get_common_mistakes(industry_type: str) -> str:
    """Negative examples — things the AI commonly gets wrong."""

    universal = """
=== COMMON MISTAKES TO AVOID ===
❌ Do NOT invent category names. "Tax Prep" is wrong — use "Tax Preparation".
❌ Do NOT use "Email" alone — use "Email/Communication".
❌ Do NOT classify Zoom as "Email/Communication" — it's "Meetings".
❌ Do NOT assign a client to Idle blocks.
❌ Do NOT assign a client to Personal/Non-Billable blocks.
❌ Do NOT classify generic browsing (Google search) as "Research" at high confidence.
   Use 0.60 and needs_review: true unless the search is clearly work-related.
❌ Do NOT split a block into multiple categories unless there is clear evidence
   of multiple activities (e.g., block has both meeting and email events).
"""

    if industry_type == 'cpa':
        return universal + """
❌ QuickBooks is NOT "Tax Preparation" — it's "Accounting/Bookkeeping".
❌ IRS.gov is NOT "Tax Preparation" — it's "Tax Research".
❌ Google Docs during tax season is NOT automatically "Tax Preparation".
   Look at the document title for context.
❌ Karbon/Canopy are practice management → "Administration", not tax.
❌ Do NOT default everything to "Tax Preparation" even in tax season —
   only use it when there's actual tax software or tax document context.
"""

    elif industry_type == 'ai_consulting':
        return universal + """
❌ WordPress/Wix for a CLIENT is "Website/Web Development", not "Software Development".
❌ localhost / :5173 / :8000 is INTERNAL "Software Development", not client work
   (unless the project folder path names a client).
❌ Google Ads Manager is "Marketing/Advertising", not "Administration".
❌ Claude.ai / ChatGPT is "Research/AI Assistance", not "Software Development"
   (even if you're researching code — it's still research).
❌ Figma for a client deliverable is "Graphic Design", not "Software Development".
"""

    elif industry_type == 'marketing':
        return universal + """
❌ Work on the AGENCY'S own marketing is "Administration" or "Sales/Business Dev",
   not a client category like "Paid Advertising".
❌ Reviewing analytics for a client is "Analytics/Reporting", not "Paid Advertising".
❌ Creating ad copy is "Content Writing" or "Copywriting", not "Paid Advertising".
❌ Managing live campaigns in Ads Manager IS "Paid Advertising".
"""

    elif industry_type == 'legal':
        return universal + """
❌ Clio/MyCase are practice management → "Administration", not "Legal Research".
❌ Reading a PDF is NOT always "Legal Research" — could be "Contract Review"
   or "Case Preparation" depending on context.
❌ Almost all legal work is billable. Only mark "Personal/Non-Billable" for
   clearly personal sites.
"""

    return universal


def _get_extra_rules(industry_type: str) -> str:
    """Return industry-specific classification rules to inject into the prompt."""

    if industry_type == 'ai_consulting':
        return """
=== AI/TECH CONSULTING SPECIFIC RULES ===

RULE 1 — WORK FOR A CLIENT ≠ SOFTWARE DEVELOPMENT
  This firm builds software internally AND delivers marketing/web services to clients.
  Classify by WHAT is being done, not which app is open:

  Marketing/Advertising → Google Ads, Meta Ads, AdWords, campaign manager, HubSpot
  SEO/Analytics → Google Analytics (GA4), Search Console, SEMrush, Ahrefs
  Website/Web Development → CLIENT's website (WordPress, Wix, Squarespace, Webflow)
  Social Media Management → Hootsuite, Buffer, or posting for a client
  Email Marketing → Mailchimp, Klaviyo campaigns for a client
  Software Development → VS Code, Terminal, localhost, GitHub, Docker (INTERNAL tools)
  Research/AI Assistance → Claude.ai, ChatGPT, Stack Overflow, docs

RULE 2 — PORT NUMBERS = INTERNAL DEV
  localhost, 127.0.0.1, :5173, :8000, :3000 → always "Software Development"
  UNLESS the browser tab title clearly shows a client name.
"""

    elif industry_type == 'cpa':
        return """
=== CPA FIRM SPECIFIC RULES ===

RULE 1 — TAX SOFTWARE IS DEFINITIVE
  UltraTax, Lacerte, Drake, ProSeries, CCH Axcess, ATX → "Tax Preparation" (0.95)
  QuickBooks, Xero, Sage, NetSuite → "Accounting/Bookkeeping" (0.93)
  IRS.gov, Checkpoint, Bloomberg Tax → "Tax Research" (0.93)
  ADP, Gusto, Paychex → "Payroll Services" (0.90)
  ShareFile, SmartVault, Suralink → "Document Management" (0.85)
  Karbon, Canopy → "Administration" (0.85)

RULE 2 — BROWSER WORK IS ALMOST NEVER "SOFTWARE DEVELOPMENT"
  CPAs don't write code. Browser activity is research, portal access,
  document review, or communication. Use URL/title to determine which.

RULE 3 — WINDOW TITLE CLIENT EXTRACTION
  CPA software often shows: "ClientLastName, ClientFirstName - Form 1040"
  Extract the client name from before the dash.
  Tax organizers show: "2024 Tax Organizer - Smith, John" → client is "Smith, John"
"""

    elif industry_type == 'marketing':
        return """
=== MARKETING AGENCY SPECIFIC RULES ===

RULE 1 — PRODUCTION vs MANAGEMENT
  Creating ads/content → "Content Writing" or "Graphic Design"
  Managing/optimizing live campaigns → "Paid Advertising"
  Reviewing performance data → "Analytics/Reporting"

RULE 2 — CLIENT vs INTERNAL
  Work on a CLIENT's marketing → specific service category
  Work on the AGENCY'S own marketing → "Administration" or not billable

RULE 3 — TOOL → CATEGORY MAPPING
  Figma, Canva, Adobe → Graphic Design or Video Production
  Google Ads, Meta Ads Manager → Paid Advertising
  Google Analytics, SEMrush → Analytics/Reporting
  Mailchimp, Klaviyo → Email Marketing
  Hootsuite, Buffer → Social Media Management
  WordPress, Webflow → Website Updates
"""

    elif industry_type == 'legal':
        return """
=== LAW FIRM SPECIFIC RULES ===

RULE 1 — RESEARCH TOOLS ARE DEFINITIVE
  Westlaw, LexisNexis, Fastcase → "Legal Research" (0.95)
  Clio, MyCase → "Administration" (0.85)

RULE 2 — DOCUMENT CONTEXT MATTERS
  Word/Google Docs → Check title: "Brief" → "Brief Writing",
  "Contract" → "Contract Review", "Motion" → "Litigation"
  PDF review → Could be Contract Review, Case Preparation, or Discovery

RULE 3 — BILLING
  Almost all legal work is billable. Default to billable unless
  clearly personal browsing.
"""

    return ""


# =============================================================================
# COMBINED TOOL DETECTION (for pre-classification / compaction)
# =============================================================================

def get_combined_tool_detection(industry_type: str) -> dict:
    """
    Build tool detection combining:
    1. Personal/non-work site detection (lowest priority)
    2. Universal work patterns (Zoom, Gmail, Google Ads, etc.)
    3. Industry-specific patterns (highest priority - overrides above)
    """
    combined = dict(PERSONAL_SITE_DETECTION)

    # Universal communication tools
    combined.update({
        "zoom": {
            "keywords": ["zoom", "zoom meeting"],
            "domains": ["zoom.us"],
            "category": "Meetings",
            "confidence": 0.95
        },
        "teams": {
            "keywords": ["microsoft teams", "teams meeting"],
            "domains": ["teams.microsoft.com"],
            "category": "Meetings",
            "confidence": 0.95
        },
        "meet": {
            "keywords": ["google meet"],
            "domains": ["meet.google.com"],
            "category": "Meetings",
            "confidence": 0.95
        },
        "gmail": {
            "keywords": ["gmail", "google mail", "inbox"],
            "domains": ["mail.google.com"],
            "category": "Email/Communication",
            "confidence": 0.92
        },
        "outlook": {
            "keywords": ["outlook", "office 365 mail"],
            "domains": ["outlook.office.com", "outlook.live.com"],
            "category": "Email/Communication",
            "confidence": 0.92
        },
        "slack": {
            "keywords": ["slack"],
            "domains": ["slack.com", "app.slack.com"],
            "category": "Email/Communication",
            "confidence": 0.90
        },
    })

    # Universal advertising platforms (all industries)
    combined.update({
        "google_ads_universal": {
            "keywords": [
                "google ads", "adwords", "ads.google.com",
                "- google ads", "google ads -",
                "campaign manager", "ad campaign", "ad group",
                "performance max", "pmax", "smart campaign",
            ],
            "domains": ["ads.google.com"],
            "category": "Marketing/Advertising",
            "confidence": 0.95
        },
        "meta_ads_universal": {
            "keywords": [
                "facebook ads", "meta ads", "ads manager",
                "adsmanager.facebook", "meta business suite",
            ],
            "domains": ["business.facebook.com", "adsmanager.facebook.com"],
            "category": "Marketing/Advertising",
            "confidence": 0.94
        },
        "google_analytics_universal": {
            "keywords": ["google analytics", "ga4", "analytics.google"],
            "domains": ["analytics.google.com"],
            "category": "SEO/Analytics",
            "confidence": 0.90
        },
    })

    # Universal document tools
    combined.update({
        "google_docs": {
            "keywords": ["google docs", "docs.google.com"],
            "domains": ["docs.google.com"],
            "category": "Document Management",
            "confidence": 0.70  # Low — needs title context to determine actual category
        },
        "google_sheets": {
            "keywords": ["google sheets", "sheets.google.com"],
            "domains": ["sheets.google.com"],
            "category": "Administration",
            "confidence": 0.70
        },
        "microsoft_word": {
            "keywords": ["microsoft word", "word - "],
            "domains": [],
            "category": "Document Management",
            "confidence": 0.70
        },
        "microsoft_excel": {
            "keywords": ["microsoft excel", "excel - "],
            "domains": [],
            "category": "Administration",
            "confidence": 0.70
        },
    })

    # Industry-specific patterns (highest priority — override everything above)
    industry_patterns = get_tool_detection_for_industry(industry_type)
    combined.update(industry_patterns)

    return combined


# =============================================================================
# INTERNAL CLIENT HELPER
# =============================================================================

def ensure_internal_client(org):
    """
    Ensure an 'Internal' client exists for the given org.
    Called on org creation and can be called idempotently.
    Returns the Internal client instance.
    """
    from tracker.models import Client

    client, created = Client.objects.get_or_create(
        org=org,
        code='INTERNAL',
        defaults={
            'name': 'Internal',
            'is_active': True,
        }
    )

    if created:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[INTERNAL] Created 'Internal' client for org: {org.name}")

    return client