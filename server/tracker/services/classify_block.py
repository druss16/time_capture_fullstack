# tracker/services/classify_block.py
import re, json
from typing import Tuple, Dict, Optional

from django.conf import settings
from django.db import transaction

from ..models import (
    Client, ClientPattern, TaskPattern, ClassificationOverride, Block
)

# If you prefer, move this into settings and import from there.
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
]

def _norm(s: Optional[str]) -> str:
    return (s or "").strip()

def match_client_patterns(sig: Dict[str, str]) -> Tuple[Optional[str], float, str]:
    hits = []
    text = f"{sig.get('title','')} {sig.get('url','')} {sig.get('file','')}"
    for p in ClientPattern.objects.all():
        try:
            if p.match_type == "domain" and p.pattern and p.pattern.lower() in text.lower():
                hits.append((p.client_name, p.weight, "domain"))
            elif p.match_type == "path" and p.pattern and p.pattern in (sig.get("file") or ""):
                hits.append((p.client_name, p.weight, "path"))
            elif p.match_type == "keyword" and p.pattern and re.search(p.pattern, text, re.I):
                hits.append((p.client_name, p.weight, "keyword"))
            elif p.match_type == "regex" and p.pattern and re.search(p.pattern, text):
                hits.append((p.client_name, p.weight, "regex"))
        except Exception:
            continue
    if not hits:
        return None, 0.0, "no-pattern"
    best = sorted(hits, key=lambda x: x[1], reverse=True)[0]
    # heuristic confidence
    return best[0], min(0.9, 0.4 + 0.1 * best[1]), f"pattern:{best[2]}"

def match_task_patterns(sig: Dict[str, str]) -> Tuple[Optional[str], float, str]:
    hits = []
    text = f"{sig.get('bundle','')} {sig.get('title','')} {sig.get('file','')} {sig.get('url','')}"
    for p in TaskPattern.objects.all():
        try:
            if p.match_type == "bundle" and p.pattern and p.pattern in (sig.get("bundle") or ""):
                hits.append((p.task_category, p.weight, "bundle"))
            elif p.match_type == "keyword" and p.pattern and re.search(p.pattern, text, re.I):
                hits.append((p.task_category, p.weight, "keyword"))
            elif p.match_type == "regex" and p.pattern and re.search(p.pattern, text):
                hits.append((p.task_category, p.weight, "regex"))
            elif p.match_type == "path_ext" and p.pattern and (sig.get("file") or "").endswith(p.pattern):
                hits.append((p.task_category, p.weight, "path_ext"))
        except Exception:
            continue
    if not hits:
        return None, 0.0, "no-pattern"
    best = sorted(hits, key=lambda x: x[1], reverse=True)[0]
    return best[0], min(0.9, 0.4 + 0.1 * best[1]), f"pattern:{best[2]}"

def _safe_openai_classify(prompt: str) -> dict:
    """
    Minimal, defensive OpenAI call. Replace with your preferred client.
    Ensure OPENAI_API_KEY is set in settings or env.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=getattr(settings, "OPENAI_API_KEY", None))
        resp = client.responses.create(model="gpt-4.1-mini", input=prompt, temperature=0)
        text = (getattr(resp, "output_text", None) or "").strip()
        data = json.loads(text)
        return {
            "client_name": _norm(data.get("client_name")),
            "task_category": _norm(data.get("task_category")),
            "client_conf": float(data.get("client_conf", 0) or 0),
            "task_conf": float(data.get("task_conf", 0) or 0),
            "explanation": _norm(data.get("explanation")),
        }
    except Exception:
        return {
            "client_name": None,
            "task_category": None,
            "client_conf": 0.0,
            "task_conf": 0.0,
            "explanation": "LLM parse or call failed",
        }

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

@transaction.atomic
def classify_block(block: Block) -> Block:
    """
    Classify a Block in-place:
      - Fill ai_extracted_client, ai_category, ai_confidence, ai_processed_at
      - Optionally set block.client FK if an org-matching Client exists
      - Apply overrides if present
    """
    sig = {
        "bundle": getattr(block, "bundle_id", "") or "",
        "title": getattr(block, "window_title", "") or "",
        "url": getattr(block, "url", "") or "",
        "file": getattr(block, "file_path", "") or "",
        "ctx": getattr(block, "hints", {}) or {},  # use your 'hints' JSON as context
    }

    # 1) Rules / patterns first
    client_guess, c_score, c_src = match_client_patterns(sig)
    task_guess, t_score, t_src = match_task_patterns(sig)
    explanation = f"{c_src} | {t_src}".strip(" |")

    # 2) If low confidence, ask LLM
    if (c_score < 0.6 or not client_guess) or (t_score < 0.6 or not task_guess):
        known = list(Client.objects.filter(org=block.org, is_active=True).values_list("name", flat=True))
        llm = ask_llm_for_classification(sig, known_clients=known)
        client_guess = client_guess or _norm(llm.get("client_name"))
        task_guess = task_guess or _norm(llm.get("task_category"))
        # combine a simple confidence
        c_score = max(c_score, float(llm.get("client_conf", 0) or 0))
        t_score = max(t_score, float(llm.get("task_conf", 0) or 0))
        if llm.get("explanation"):
            explanation = (explanation + " | " + llm["explanation"]).strip(" |")

    # 3) Human override wins (by raw_event_id if that’s your mapping)
    ov = ClassificationOverride.objects.filter(raw_event_id=getattr(block, "id")).first()
    if ov:
        if _norm(ov.client_name):
            client_guess = _norm(ov.client_name)
        if _norm(ov.task_category):
            task_guess = _norm(ov.task_category)
        explanation = (explanation + " | human override").strip(" |")

    # 4) Normalize task category to allowed set
    if task_guess not in TASK_CATEGORIES:
        # try a rough match
        low = (task_guess or "").lower()
        best = next((c for c in TASK_CATEGORIES if c.lower() in low or low in c.lower()), None)
        task_guess = best or "Uncategorized"

    # 5) Save on Block
    block.ai_extracted_client = client_guess or "Unknown"
    block.ai_category = task_guess
    block.ai_confidence = float(f"{(c_score + t_score) / 2:.3f}")
    from django.utils import timezone
    block.ai_processed_at = timezone.now()

    # Optional: attach FK if client exists in org
    resolved = _resolve_client(block.org, client_guess)
    if resolved:
        block.client = resolved

    block.save(update_fields=[
        "ai_extracted_client", "ai_category", "ai_confidence",
        "ai_processed_at", "client"
    ])
    return block