# tracker/services/classify_block.py
from __future__ import annotations

import os, re, json, hashlib, time as _time
from typing import Tuple, Dict, Optional
from datetime import timedelta
from urllib.parse import urlparse

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tracker.utils.monitoring import capture_exception
from ..models import (
    Client, ClientPattern, TaskPattern, ClassificationOverride, Block
)

# --------------------------
# Constants / configuration
# --------------------------

TASK_CATEGORIES = [
    "Email/Communication",
    "Tax Prep",
    "Bookkeeping",
    "Research",
    "Review",
    "File Organization",
    "Data Entry",
    "Meetings/Calls",
    "Planning",
    "Admin/Other",
    "Idle/Uncategorized",
]

IDEMP_TTL = timedelta(minutes=10)   # Skip reclass if hash unchanged recently
NEEDED_CONF = 0.60                  # Below this → consider LLM
MIN_ACCEPT  = 0.55                  # Below this → treat as weak

# Global on/off for LLM via env
CLASSIFY_ALLOW_LLM = os.getenv("CLASSIFY_ALLOW_LLM", "1") == "1"

# App → task hints (lightweight)
APP_TO_TASK = {
    "Terminal": "Build/Dev",
    "Code": "Build/Dev",
    "PyCharm": "Build/Dev",
    "WebStorm": "Build/Dev",
    "VS Code": "Build/Dev",
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
    (re.compile(r"\bstand-?up|retro|sprint|kick[- ]?off|check[ -]?in\b", re.I), "Meetings/Calls"),
    (re.compile(r"\bPR|pull request|review changes\b", re.I),                "Review"),
    (re.compile(r"\bETA|roadmap|scope|deliverable|milestone\b", re.I),      "Planning"),
    (re.compile(r"\binvoice|payable|recon|ledger\b", re.I),                  "Bookkeeping"),
    (re.compile(r"\bexport|csv|sheet|spreadsheet\b", re.I),                  "Data Entry"),
    (re.compile(r"\bdebug|stacktrace|traceback|error\b", re.I),              "Build/Dev"),
    (re.compile(r"\bproposal|quote|contract|SOW\b", re.I),                   "Admin/Other"),
]

# --------------------------
# Small helpers
# --------------------------

def _norm(s: Optional[str]) -> str:
    return (s or "").strip()

def _compute_ai_hash(sig: dict) -> str:
    blob = json.dumps(sig, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

def _domain(url: str) -> str:
    try:
        u = urlparse(url or "")
        # hostname is empty for things like chrome://new-tab-page
        return (u.hostname or "").lower()
    except Exception:
        return ""

def _is_idleish(sig: dict, blk: Block) -> bool:
    title  = _norm(sig.get("title")).lower()
    bundle = _norm(sig.get("bundle")).lower()
    app    = _norm(sig.get("app_name")).lower()
    url    = _norm(sig.get("url"))
    scheme = ""
    try:
        scheme = urlparse(url).scheme.lower()
    except Exception:
        pass

    return (
        bundle == "__idle__"
        or app == "idle"
        or title in {"uncategorized - idle", "idle/uncategorized", "idle", "uncategorized", "newtab", "new tab"}
        or scheme in {"chrome", "edge", "about"}  # new tab/special pages
        or getattr(blk, "window_title", "") == "Uncategorized - Idle"
    )

def _maybe_set(obj, field: str, value):
    if hasattr(obj, field):
        setattr(obj, field, value)

# --------------------------
# TTL cached pattern loaders
# --------------------------

_CACHE_SECS = 60
def _ttl_cache(seconds: int):
    def decorator(fn):
        cache = {"t": 0, "v": None}
        def wrapper(*args, **kwargs):
            now = _time.time()
            if now - cache["t"] > seconds or cache["v"] is None:
                cache["v"] = fn(*args, **kwargs)
                cache["t"] = now
            return cache["v"]
        return wrapper
    return decorator

@_ttl_cache(_CACHE_SECS)
def _load_client_patterns() -> list[ClientPattern]:
    return list(ClientPattern.objects.all())

@_ttl_cache(_CACHE_SECS)
def _load_task_patterns() -> list[TaskPattern]:
    return list(TaskPattern.objects.all())

# -------------------------------
# Rules / Pattern matching (fast)
# -------------------------------

def match_client_patterns(sig: Dict[str, str]) -> Tuple[Optional[str], float, str]:
    text = f"{sig.get('title','')} {sig.get('url','')} {sig.get('file','')}"
    host = _domain(sig.get("url") or "")
    hits = []

    # Exact domain wins
    if host:
        for p in _load_client_patterns():
            pat = (p.pattern or "").strip().lower()
            if pat and p.match_type == "domain" and host == pat:
                return p.client_name, 0.95, f"domain:{host}"

    # Softer matches
    for p in _load_client_patterns():
        try:
            pat = (p.pattern or "").strip()
            if not pat:
                continue
            mt = p.match_type
            if mt == "domain" and pat.lower() in host:
                hits.append((p.client_name, p.weight, "domain"))
            elif mt == "path" and pat in (sig.get("file") or ""):
                hits.append((p.client_name, p.weight, "path"))
            elif mt == "keyword" and re.search(pat, text, re.I):
                hits.append((p.client_name, p.weight, "keyword"))
            elif mt == "regex" and re.search(pat, text):
                hits.append((p.client_name, p.weight, "regex"))
        except Exception:
            continue

    if not hits:
        return None, 0.0, "no-pattern"
    best = max(hits, key=lambda x: x[1])
    return best[0], min(0.9, 0.4 + 0.1 * best[1]), f"pattern:{best[2]}"

def match_task_patterns(sig: Dict[str, str]) -> Tuple[Optional[str], float, str]:
    host = _domain(sig.get("url") or "")
    app  = _norm(sig.get("app_name"))
    ttl  = _norm(sig.get("title"))

    # App-driven
    if app in APP_TO_TASK and APP_TO_TASK[app]:
        return APP_TO_TASK[app], 0.9, f"app:{app}"

    # Title-driven
    for rx, task in TITLE_HINTS_TO_TASK:
        if rx.search(ttl):
            return task, 0.85, f"title:{task}"

    # Meeting URLs
    if host in {"meet.google.com", "teams.microsoft.com", "zoom.us"}:
        return "Meetings/Calls", 0.85, "meeting-url"

    # Common dev/research hosts
    if host == "github.com":
        return "Build/Dev", 0.8, "github"
    if host == "docs.google.com":
        return "Research", 0.7, "docs"

    # DB patterns
    text = f"{sig.get('bundle','')} {sig.get('title','')} {sig.get('file','')} {sig.get('url','')}"
    hits = []
    for p in _load_task_patterns():
        try:
            pat = (p.pattern or "").strip()
            if not pat:
                continue
            mt = p.match_type
            if mt == "bundle" and pat in (sig.get("bundle") or ""):
                hits.append((p.task_category, p.weight, "bundle"))
            elif mt == "keyword" and re.search(pat, text, re.I):
                hits.append((p.task_category, p.weight, "keyword"))
            elif mt == "regex" and re.search(pat, text):
                hits.append((p.task_category, p.weight, "regex"))
            elif mt == "path_ext" and (sig.get("file") or "").endswith(pat):
                hits.append((p.task_category, p.weight, "path_ext"))
        except Exception:
            continue

    if not hits:
        return None, 0.0, "no-pattern"
    best = max(hits, key=lambda x: x[1])
    return best[0], min(0.9, 0.4 + 0.1 * best[1]), f"pattern:{best[2]}"

# ---------------------------------------
# LLM fallback (defensive, low-latency)
# ---------------------------------------

def _safe_openai_classify(prompt: str, *, timeout_s: float = 8.0, max_retries: int = 2) -> dict:
    try:
        from openai import OpenAI

        # env overrides
        try:
            timeout_s = float(getattr(settings, "OPENAI_TIMEOUT_SEC", None) or os.getenv("OPENAI_TIMEOUT_SEC") or timeout_s)
        except Exception:
            pass
        try:
            max_retries = int(getattr(settings, "OPENAI_MAX_RETRIES", None) or os.getenv("OPENAI_MAX_RETRIES") or max_retries)
        except Exception:
            pass

        client = OpenAI(
            api_key=getattr(settings, "OPENAI_API_KEY", None),
            timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=timeout_s, pool=5.0),
            max_retries=0,  # we control retries
        )

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = client.responses.create(
                    model="gpt-4.1-mini",
                    input=prompt,
                    temperature=0,
                    max_output_tokens=200,
                )
                text = getattr(resp, "output_text", None)
                if not text:
                    parts = []
                    for item in getattr(resp, "output", []) or []:
                        for c in getattr(item, "content", []) or []:
                            v = getattr(getattr(c, "text", None), "value", None)
                            if v:
                                parts.append(v)
                    text = "\n".join(parts).strip()

                data = {}
                try:
                    data = json.loads(text)
                except Exception:
                    try:
                        s, e = text.find("{"), text.rfind("}")
                        if s != -1 and e != -1 and e > s:
                            data = json.loads(text[s:e+1])
                    except Exception:
                        data = {}

                client_name   = _norm(data.get("client_name"))
                task_category = _norm(data.get("task_category"))
                if task_category not in TASK_CATEGORIES:
                    low = (task_category or "").lower()
                    best = next((c for c in TASK_CATEGORIES if c.lower() in low or low in c.lower()), None)
                    task_category = best or "Admin/Other"

                return {
                    "client_name": client_name or None,
                    "task_category": task_category,
                    "client_conf": float(data.get("client_conf", 0) or 0),
                    "task_conf": float(data.get("task_conf", 0) or 0),
                    "explanation": _norm(data.get("explanation")),
                }
            except Exception as e:
                last_err = e
                etxt = str(e)
                retryable = (
                    isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout))
                    or "Timeout" in etxt or "Timed out" in etxt
                )
                if attempt < max_retries and retryable:
                    _time.sleep(0.25 * (2 ** attempt))
                    continue
                break

        capture_exception(last_err)
        return {"client_name": None, "task_category": "Admin/Other", "client_conf": 0.0, "task_conf": 0.0, "explanation": "LLM call/parse failed"}
    except Exception as e:
        capture_exception(e)
        return {"client_name": None, "task_category": "Admin/Other", "client_conf": 0.0, "task_conf": 0.0, "explanation": "LLM setup error"}

def ask_llm_for_classification(sig: Dict[str, str], known_clients=None) -> Dict[str, str]:
    prompt = f"""
You are a classifier for CPA time tracking. Return STRICT JSON with keys:
client_name, task_category, client_conf, task_conf, explanation.
task_category must be one of: {', '.join(TASK_CATEGORIES)}.

INPUT:
bundle: {sig.get('bundle')}
title: {sig.get('title')}
url: {sig.get('url')}
file: {sig.get('file')}
ctx: {json.dumps(sig.get('ctx') or {})}
known_clients: {json.dumps(known_clients or [])}
"""
    return _safe_openai_classify(prompt)

def _resolve_client(org, client_name: Optional[str]) -> Optional[Client]:
    name = _norm(client_name)
    if not name or not org:
        return None
    try:
        return Client.objects.get(org=org, name=name)
    except Client.DoesNotExist:
        return None

# --------------------------
# Main entry
# --------------------------

@transaction.atomic
def classify_block(block: Block, *, allow_llm: bool = True) -> Block:
    """
    Classify CATEGORY only - never override client if already set!
    """
    sig = {
        "bundle":     getattr(block, "bundle_id", "") or "",
        "title":      getattr(block, "window_title", "") or getattr(block, "title", "") or "",
        "url":        getattr(block, "url", "") or "",
        "file":       getattr(block, "file_path", "") or "",
        "ctx":        getattr(block, "hints", {}) or {},
        "hostname":   getattr(block, "hostname", "") or "",
        "app_name":   getattr(block, "app_name", "") or "",
    }

    # Idempotency
    new_hash = _compute_ai_hash(sig)
    blk = Block.objects.select_for_update().get(pk=block.pk)
    if getattr(blk, "ai_hash", None) == new_hash and getattr(blk, "ai_processed_at", None):
        if timezone.now() - blk.ai_processed_at <= IDEMP_TTL:
            return blk
    if getattr(blk, "ai_hash", None) != new_hash:
        blk.ai_hash = new_hash
        blk.save(update_fields=["ai_hash"])

    # Idle / New Tab fast path
    if _is_idleish(sig, blk):
        blk.ai_extracted_client = None
        blk.ai_category = "Uncategorized - Idle"
        blk.ai_confidence = 1.0
        blk.ai_processed_at = timezone.now()
        _maybe_set(blk, "ai_explanation", "idle fast-path")
        # ← NEW: Clear client for idle blocks
        blk.client = None
        blk.save(update_fields=[
            "ai_extracted_client", "ai_category", "ai_confidence", "ai_processed_at", "client",
            *(["ai_explanation"] if hasattr(blk, "ai_explanation") else [])
        ])
        return blk

    # ========================================
    # NEW: Only classify CATEGORY, not client!
    # ========================================
    
    # Only get task/category, NOT client
    task_guess, t_score, t_src = match_task_patterns(sig)
    explanation = t_src

    # LLM for category only if needed
    needs_llm = t_score < NEEDED_CONF or not task_guess
    if CLASSIFY_ALLOW_LLM and allow_llm and needs_llm:
        known = list(Client.objects.filter(org=blk.org, is_active=True).values_list("name", flat=True))
        llm = ask_llm_for_classification(sig, known_clients=known)

        if not task_guess or llm.get("task_conf", 0) > t_score:
            task_guess = _norm(llm.get("task_category")) or task_guess
            t_score = max(t_score, float(llm.get("task_conf", 0) or 0))
        if llm.get("explanation"):
            explanation = (explanation + " | " + llm["explanation"]).strip(" |")

    # Human override for category only
    ov = ClassificationOverride.objects.filter(raw_event_id=blk.id).first()
    if ov:
        if _norm(ov.task_category):
            task_guess = _norm(ov.task_category)
        explanation = (explanation + " | human override").strip(" |")

    # Normalize category
    if task_guess not in TASK_CATEGORIES:
        low = (task_guess or "").lower()
        best = next((c for c in TASK_CATEGORIES if c.lower() in low or low in c.lower()), None)
        task_guess = best or "Admin/Other"

    # Persist CATEGORY only - DO NOT touch client!
    blk.ai_extracted_client = None  # No longer needed
    blk.ai_category = task_guess
    blk.ai_confidence = float(f"{t_score:.3f}")
    blk.ai_processed_at = timezone.now()
    _maybe_set(blk, "ai_explanation", explanation[:1000])

    # ← REMOVED: No longer override client!
    # The client was already set when Block was created from RawEvent

    fields = ["ai_extracted_client", "ai_category", "ai_confidence", "ai_processed_at"]
    if hasattr(blk, "ai_explanation"):
        fields.append("ai_explanation")
    blk.save(update_fields=fields)
    return blk