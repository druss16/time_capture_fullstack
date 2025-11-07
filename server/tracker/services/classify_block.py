# tracker/services/classify_block.py
from __future__ import annotations

import re, json
from typing import Tuple, Dict, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tracker.utils.monitoring import capture_exception
from ..models import (
    Client, ClientPattern, TaskPattern, ClassificationOverride, Block
)

# Allowed task categories
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
    "Idle/Uncategorized",   # ← add this

]

def _norm(s: Optional[str]) -> str:
    return (s or "").strip()

# -------------------------------
# Rules / Pattern matching (fast)
# -------------------------------
def match_client_patterns(sig: Dict[str, str]) -> Tuple[Optional[str], float, str]:
    hits = []
    text = f"{sig.get('title','')} {sig.get('url','')} {sig.get('file','')}"
    for p in ClientPattern.objects.all():
        try:
            pat = (p.pattern or "").strip()
            if not pat:
                continue
            if p.match_type == "domain" and pat.lower() in text.lower():
                hits.append((p.client_name, p.weight, "domain"))
            elif p.match_type == "path" and pat in (sig.get("file") or ""):
                hits.append((p.client_name, p.weight, "path"))
            elif p.match_type == "keyword" and re.search(pat, text, re.I):
                hits.append((p.client_name, p.weight, "keyword"))
            elif p.match_type == "regex" and re.search(pat, text):
                hits.append((p.client_name, p.weight, "regex"))
        except Exception:
            continue
    if not hits:
        return None, 0.0, "no-pattern"
    best = sorted(hits, key=lambda x: x[1], reverse=True)[0]
    return best[0], min(0.9, 0.4 + 0.1 * best[1]), f"pattern:{best[2]}"

def match_task_patterns(sig: Dict[str, str]) -> Tuple[Optional[str], float, str]:
    hits = []
    text = f"{sig.get('bundle','')} {sig.get('title','')} {sig.get('file','')} {sig.get('url','')}"
    for p in TaskPattern.objects.all():
        try:
            pat = (p.pattern or "").strip()
            if not pat:
                continue
            if p.match_type == "bundle" and pat in (sig.get("bundle") or ""):
                hits.append((p.task_category, p.weight, "bundle"))
            elif p.match_type == "keyword" and re.search(pat, text, re.I):
                hits.append((p.task_category, p.weight, "keyword"))
            elif p.match_type == "regex" and re.search(pat, text):
                hits.append((p.task_category, p.weight, "regex"))
            elif p.match_type == "path_ext" and (sig.get("file") or "").endswith(pat):
                hits.append((p.task_category, p.weight, "path_ext"))
        except Exception:
            continue
    if not hits:
        return None, 0.0, "no-pattern"
    best = sorted(hits, key=lambda x: x[1], reverse=True)[0]
    return best[0], min(0.9, 0.4 + 0.1 * best[1]), f"pattern:{best[2]}"

# ---------------------------------------
# LLM fallback (defensive, no schema arg)
# ---------------------------------------
# tracker/services/classify_block.py

def _safe_openai_classify(prompt: str, *, timeout_s: float = 8.0, max_retries: int = 2) -> dict:
    """
    Minimal, defensive OpenAI call with strict timeouts + tiny retries.
    Keeps output small to avoid long generations (and timeouts).
    """
    try:
        import time as _time
        import httpx
        from openai import OpenAI

        # Allow env to override without code changes
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
            # httpx.Timeout(total) is NOT supported; set per-phase to avoid hangs
            timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=timeout_s, pool=5.0),
            # We manage our own retry loop; disable SDK retries
            max_retries=0,
        )

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = client.responses.create(
                    model="gpt-4.1-mini",     # small/fast model; keep it here
                    input=prompt,
                    temperature=0,
                    # keep outputs compact so responses return quickly
                    max_output_tokens=200,
                )

                # Prefer output_text, then manual extraction
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
                        start, end = text.find("{"), text.rfind("}")
                        if start != -1 and end != -1 and end > start:
                            data = json.loads(text[start:end+1])
                    except Exception:
                        data = {}

                client_name = _norm(data.get("client_name"))
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
                # Retry only on network/timeout-ish failures
                etxt = str(e)
                retryable = (
                    isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout)) or
                    "ReadTimeout" in etxt or "ConnectTimeout" in etxt or "WriteTimeout" in etxt or
                    "Timed out" in etxt
                )
                if attempt < max_retries and retryable:
                    _time.sleep(0.25 * (2 ** attempt))  # tiny exponential backoff
                    continue
                # Fallthrough → break and default
                break

        # If we’re here, the call failed; record & return a safe default
        capture_exception(last_err)
        return {
            "client_name": None,
            "task_category": "Admin/Other",
            "client_conf": 0.0,
            "task_conf": 0.0,
            "explanation": "LLM call/parse failed or timed out",
        }

    except Exception as e:
        capture_exception(e)
        return {
            "client_name": None,
            "task_category": "Admin/Other",
            "client_conf": 0.0,
            "task_conf": 0.0,
            "explanation": "LLM setup error",
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

# --------------------------
# Main entry: classify block
# --------------------------
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
        "ctx": getattr(block, "hints", {}) or {},
        "hostname": getattr(block, "hostname", "") or "",
    }

    # --- IDLE FAST PATH ---
    # Your agent emits Idle rows with bundle_id="__idle__" and title="Uncategorized - Idle".
    if (getattr(block, "bundle_id", "") == "__idle__"
        or getattr(block, "app_name", "") == "Idle"
        or getattr(block, "window_title", "") == "Uncategorized - Idle"):
        block.ai_extracted_client = None
        block.ai_category = "Uncategorized - Idle"
        block.ai_confidence = 1.0
        block.ai_processed_at = timezone.now()
        # Do NOT attach a client; this is intentionally uncategorized/idle
        block.save(update_fields=[
            "ai_extracted_client",
            "ai_category",
            "ai_confidence",
            "ai_processed_at",
        ])
        return block

    # 1) Patterns
    client_guess, c_score, c_src = match_client_patterns(sig)
    task_guess, t_score, t_src = match_task_patterns(sig)
    explanation = f"{c_src} | {t_src}".strip(" |")

    # 2) LLM fallback
    if (c_score < 0.6 or not client_guess) or (t_score < 0.6 or not task_guess):
        known = list(Client.objects.filter(org=block.org, is_active=True).values_list("name", flat=True))
        print(f"[classify] calling LLM for Block {block.pk} (hash={getattr(block, 'ai_hash', '')})")
        llm = ask_llm_for_classification(sig, known_clients=known)
        client_guess = client_guess or _norm(llm.get("client_name"))
        task_guess = task_guess or _norm(llm.get("task_category"))
        c_score = max(c_score, float(llm.get("client_conf", 0) or 0))
        t_score = max(t_score, float(llm.get("task_conf", 0) or 0))
        if llm.get("explanation"):
            explanation = (explanation + " | " + llm["explanation"]).strip(" |")

    # 3) Human override
    ov = ClassificationOverride.objects.filter(raw_event_id=getattr(block, "id")).first()
    if ov:
        if _norm(ov.client_name):
            client_guess = _norm(ov.client_name)
        if _norm(ov.task_category):
            task_guess = _norm(ov.task_category)
        explanation = (explanation + " | human override").strip(" |")

    # 4) Normalize category
    if task_guess not in TASK_CATEGORIES:
        low = (task_guess or "").lower()
        best = next((c for c in TASK_CATEGORIES if c.lower() in low or low in c.lower()), None)
        task_guess = best or "Admin/Other"

    # 5) Persist
    block.ai_extracted_client = (client_guess or "").strip() or None
    block.ai_category = task_guess
    block.ai_confidence = float(f"{(float(c_score) + float(t_score)) / 2:.3f}")
    block.ai_processed_at = timezone.now()

    resolved = _resolve_client(block.org, client_guess)
    if resolved:
        block.client = resolved

    block.save(update_fields=[
        "ai_extracted_client",
        "ai_category",
        "ai_confidence",
        "ai_processed_at",
        "client",
    ])
    return block