# tracker/industry_categories.py
"""
Industry-specific category configurations for TimeTracker.

Each industry has:
- CATEGORIES: List of category names for dropdowns/UI
- TOOL_DETECTION: Pattern matching for auto-categorization
- TASK_TYPES: Default TaskType seeds for new orgs
- SEASONAL_CONTEXT: Industry-specific seasonal patterns
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
# CPA / ACCOUNTING FIRM CATEGORIES
# =============================================================================

CPA_CATEGORIES = [
    # System
    "Idle",
    
    # Core Tax Services
    "Tax Preparation",
    "Tax Planning",
    "Tax Research",
    "Tax Compliance",
    
    # Accounting Services
    "Accounting/Bookkeeping",
    "Financial Statement Prep",
    "Audit/Assurance",
    "Payroll Services",
    
    # Advisory Services
    "Advisory/Financial Planning",
    "Valuation/Advisory",
    "Forensic/Fraud Investigation",
    
    # Compliance & Regulatory
    "SEC/Regulatory Compliance",
    "Employee Benefits/ERISA",
    
    # Specialized Industry
    "Real Estate/Property",
    "Nonprofit/Form 990",
    "Healthcare/Medical Practice",
    "Construction/Contractors",
    
    # Administrative
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
    "irs": {
        "keywords": ["irs.gov", "internal revenue"],
        "domains": ["irs.gov"],
        "category": "Tax Research",
        "confidence": 0.93
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
]


# =============================================================================
# AI / TECHNOLOGY CONSULTING CATEGORIES
# =============================================================================

AI_CONSULTING_CATEGORIES = [
    # System
    "Idle",
    
    # Core Development
    "Software Development",
    "Code Review",
    "Architecture/Design",
    "Testing/QA",
    "Debugging",
    
    # AI/ML Specific
    "Model Development",
    "Prompt Engineering",
    "Data Preparation",
    "Model Training",
    "Model Evaluation",
    "AI Research",
    
    # Infrastructure
    "DevOps/Deployment",
    "Infrastructure",
    "Database Work",
    "API Development",
    
    # Client Work
    "Client Discovery",
    "Requirements Gathering",
    "Technical Consulting",
    "Training/Workshop",
    "Documentation",
    
    # Research & Learning
    "Research/AI Assistance",
    "Learning/Upskilling",
    "Technical Writing",
    
    # Administrative
    "Email/Communication",
    "Meetings",
    "Project Management",
    "Administration",
    "Sales/Business Dev",
]

AI_CONSULTING_TOOL_DETECTION = {
    "vscode": {
        "keywords": ["visual studio code", "vscode", "vs code", "code - ", ".py - ", ".js - ", ".tsx - "],
        "domains": [],
        "category": "Software Development",
        "confidence": 0.95
    },
    "terminal": {
        "keywords": ["terminal", "iterm", "iterm2", "docker compose", "python manage.py", "npm run", "git "],
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
        "keywords": ["localhost", "127.0.0.1", ":3000", ":8000", ":5173"],
        "domains": ["localhost", "127.0.0.1"],
        "category": "Software Development",
        "confidence": 0.88
    },
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
        "domains": ["colab.research.google.com", "jupyter.org"],
        "category": "Model Development",
        "confidence": 0.90
    },
    "huggingface": {
        "keywords": ["huggingface", "transformers", "datasets"],
        "domains": ["huggingface.co"],
        "category": "AI Research",
        "confidence": 0.88
    },
    "deployment": {
        "keywords": ["render.com", "vercel", "heroku", "aws", "docker", "kubernetes"],
        "domains": ["render.com", "vercel.com", "console.aws.amazon.com"],
        "category": "DevOps/Deployment",
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
]


# =============================================================================
# MARKETING / CREATIVE AGENCY CATEGORIES
# =============================================================================

MARKETING_CATEGORIES = [
    # System
    "Idle",
    
    # Strategy & Planning
    "Strategy/Planning",
    "Campaign Planning",
    "Market Research",
    "Competitive Analysis",
    "Client Discovery",
    
    # Content Creation
    "Content Writing",
    "Copywriting",
    "Blog/Article Writing",
    "Social Media Content",
    "Video Scripting",
    
    # Design & Creative
    "Graphic Design",
    "Video Production",
    "Video Editing",
    "Photography",
    "Brand Development",
    "UI/UX Design",
    
    # Digital Marketing
    "SEO/SEM",
    "Paid Advertising",
    "Email Marketing",
    "Social Media Management",
    "Analytics/Reporting",
    
    # Web & Tech
    "Web Development",
    "Website Updates",
    "Landing Pages",
    "CMS Management",
    
    # Client Management
    "Client Meetings",
    "Presentations",
    "Proposals/Pitches",
    "Account Management",
    
    # Administrative
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
]


# =============================================================================
# LEGAL FIRM CATEGORIES
# =============================================================================

LEGAL_CATEGORIES = [
    # System
    "Idle",
    
    # Core Legal Work
    "Legal Research",
    "Document Drafting",
    "Contract Review",
    "Brief Writing",
    "Case Preparation",
    
    # Litigation
    "Litigation",
    "Discovery",
    "Depositions",
    "Court Appearances",
    "Trial Preparation",
    
    # Client Work
    "Client Consultation",
    "Client Communication",
    "Negotiations",
    
    # Transactional
    "Due Diligence",
    "Closing",
    "Regulatory Filing",
    
    # Administrative
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
}

LEGAL_TASK_TYPES = [
    {"name": "Legal Research", "code": "RES", "color": "#2563eb", "is_billable": True},
    {"name": "Document Drafting", "code": "DRAFT", "color": "#7c3aed", "is_billable": True},
    {"name": "Litigation", "code": "LIT", "color": "#dc2626", "is_billable": True},
    {"name": "Client Consultation", "code": "CONSULT", "color": "#059669", "is_billable": True},
    {"name": "Meetings", "code": "MTG", "color": "#0891b2", "is_billable": True},
    {"name": "Email/Communication", "code": "EMAIL", "color": "#6b7280", "is_billable": False},
    {"name": "Administration", "code": "ADMIN", "color": "#9ca3af", "is_billable": False},
]


# =============================================================================
# GENERAL PROFESSIONAL SERVICES (FALLBACK)
# =============================================================================

GENERAL_CATEGORIES = [
    # System
    "Idle",
    
    # Core Work
    "Project Work",
    "Client Work",
    "Research",
    "Documentation",
    "Review",
    
    # Communication
    "Email/Communication",
    "Meetings",
    "Calls",
    
    # Administrative
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
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_categories_for_industry(industry_type: str) -> list:
    """Get category list for a specific industry type."""
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


def get_seasonal_context_for_industry(industry_type: str) -> str:
    """Get seasonal context hints for AI classification."""
    from datetime import datetime
    now = datetime.now()
    month = now.month
    
    if industry_type == 'cpa':
        # CPA has very specific seasons
        if month in (1, 2, 3) or (month == 4 and now.day <= 15):
            return """
**SEASON: TAX SEASON (Jan-Apr 15)**
Peak tax preparation time. Most work will be:
- Individual tax returns (1040)
- Business returns (1120, 1065, 1120S)
- Extensions and compliance
- Default to 'Tax Preparation' if context unclear
"""
        elif month in (9, 10):
            return """
**SEASON: EXTENSION SEASON (Sep-Oct)**
Extended return deadlines. Expect:
- Extended individual returns due 10/15
- Partnership/S-Corp extensions due 9/15
"""
        else:
            return """
**SEASON: OFF-SEASON**
Mix of advisory, bookkeeping, and planning work.
"""
    
    elif industry_type == 'marketing':
        if month in (10, 11, 12):
            return """
**SEASON: Q4 HOLIDAY RUSH**
Peak marketing season. Heavy:
- Holiday campaigns
- Year-end promotions
- Budget planning for next year
"""
        elif month in (1, 2):
            return """
**SEASON: NEW YEAR PLANNING**
Strategy and planning period:
- Annual strategy development
- Campaign planning
- Budget allocation
"""
        else:
            return """
**SEASON: REGULAR OPERATIONS**
Standard campaign and content work.
"""
    
    elif industry_type == 'ai_consulting':
        return """
**CONTEXT: AI/TECH CONSULTING**
Focus on:
- Development sprints and milestones
- Client deliverables
- Research and prototyping
"""
    
    else:
        return """
**CONTEXT: PROFESSIONAL SERVICES**
Standard client work and operations.
"""


def build_ai_prompt_for_industry(industry_type: str) -> str:
    """Build industry-specific AI classification prompt."""
    categories = get_categories_for_industry(industry_type)
    seasonal = get_seasonal_context_for_industry(industry_type)
    
    industry_descriptions = {
        'cpa': "CPA/Accounting firm",
        'ai_consulting': "AI/Technology consulting firm",
        'marketing': "Marketing/Creative agency",
        'legal': "Law firm",
        'general': "Professional services firm",
    }
    
    industry_desc = industry_descriptions.get(industry_type, "Professional services firm")
    
    # Build category list for prompt
    category_list = "\n".join([f"- {cat}" for cat in categories if cat != "Idle"])
    
    return f"""You are an expert time-tracking classifier for a {industry_desc}.
Your goal is to accurately categorize every billable minute into the correct client and category.

=== AVAILABLE CATEGORIES (use these EXACT names) ===
{category_list}

=== CLASSIFICATION RULES ===
1. Be Specific: Use the most specific category that applies
2. Confidence Scoring: >= 0.90 obvious tools, >= 0.80 clear patterns, >= 0.70 reasonable inference
3. Client Identification: Check window titles, URLs, file paths for client names
4. Time Allocation: Split time proportionally if multiple activities

{seasonal}

=== RESPONSE FORMAT ===
Return ONLY a JSON array with one object per block:
{{
  "client": "Client Name" | null,
  "project": "Project Name" | null,
  "categories": {{"Category Name": 1.5}},
  "confidence": 0.92,
  "needs_review": false,
  "reasoning": "Brief explanation"
}}
"""


# =============================================================================
# COMBINED TOOL DETECTION (for pre-classification)
# =============================================================================

def get_combined_tool_detection(industry_type: str) -> dict:
    """
    Get tool detection combining industry-specific + universal patterns.
    Universal patterns (Zoom, Gmail, etc.) are always included.
    """
    # Start with universal patterns
    combined = {
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
    }
    
    # Add industry-specific patterns (they override universal if same key)
    industry_patterns = get_tool_detection_for_industry(industry_type)
    combined.update(industry_patterns)
    
    return combined