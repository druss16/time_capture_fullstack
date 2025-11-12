# tracker/services/patterns.py
import re

DOMAIN_TO_CLIENT = {
  # core work tools
  "mail.google.com": "Email",
  "calendar.google.com": "Calendar",
  "meet.google.com": "Google Meet",
  "teams.microsoft.com": "Microsoft Teams",
  "slack.com": "Slack",
  "karbonhq.com": "KarbonHQ",
  "github.com": "GitHub",
  "docs.google.com": "Google Docs",
  "sheets.google.com": "Google Sheets",
  "console.neon.tech": "Neon",
  "platform.openai.com": "OpenAI",
  "chat.openai.com": "ChatGPT.com",
  "claude.ai": "Claude.ai",

  # your projects / clients
  "predictoredge": "PredictorEdge",
  "edgrinvest": "EDGR Invest",
  "edgriq": "EDGRIQ",
  "localhost:5173": "Local Dev",
  "localhost:7123": "Local API",
}

APP_TO_TASK = {
  "Terminal": "Build/Dev",
  "Code": "Build/Dev",
  "PyCharm": "Build/Dev",
  "WebStorm": "Build/Dev",
  "VS Code": "Build/Dev",
  "Google Chrome": None,     # infer from URL/title
  "Arc": None,
  "Safari": None,
  "Mail": "Email/Communication",
  "Gmail": "Email/Communication",
  "Calendar": "Meetings/Calls",
  "Google Meet": "Meetings/Calls",
  "Microsoft Teams": "Meetings/Calls",
  "Slack": "Email/Communication",
  "Notion": "Planning",
  "Sheets": "Data Entry",
}

TITLE_HINTS_TO_TASK = [
  (re.compile(r"\bstand-?up|retro|sprint|kickoff|check[ -]?in\b", re.I), "Meetings/Calls"),
  (re.compile(r"\bPR|pull request|review changes\b", re.I), "Review"),
  (re.compile(r"\bETA|roadmap|scope|deliverable|milestone\b", re.I), "Planning"),
  (re.compile(r"\binvoice|payable|recon|ledger\b", re.I), "Bookkeeping"),
  (re.compile(r"\bexport|csv|sheet|spreadsheet\b", re.I), "Data Entry"),
  (re.compile(r"\bdebug|stacktrace|traceback|error\b", re.I), "Build/Dev"),
  (re.compile(r"\bloom|proposal|quote|contract|SOW\b", re.I), "Admin/Other"),
]