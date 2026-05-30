"""
Django view: POST /api/ai/classify-window/

Agents send window titles → backend classifies using OpenAI → caches results.
One API key, server-side, shared across all orgs. Results cached per-org so
repeated titles are instant.

Add to your urls.py:
    path("api/ai/classify-window/", ai_classify_window, name="ai_classify_window"),
    path("api/ai/classify-batch/", ai_classify_batch, name="ai_classify_batch"),

PROMPT VERSION HISTORY:
    v1   — original; allowed current_client fallback; produced hallucinations
           when titles were sparse (e.g. AI inventing a plausible-sounding
           client for a fullypromoted.com page).
    v2   — v1.3.58 (2026-05-30): evidence-grounded prompt. AI must quote
           textual evidence from the input or return null. Server-side
           validation that the quote actually appears in the input.
           CACHE_KEY_VERSION bumped to invalidate stale v1 hallucinations.
"""

import json
import hashlib
import logging
import time
import re
from functools import lru_cache

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.core.cache import cache  # Redis/memcached recommended
from .models import OrganizationMembership

logger = logging.getLogger(__name__)

# =====================================================================
# Configuration
# =====================================================================

# Set in settings.py:
#   OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
#   AI_CLASSIFY_MODEL = "gpt-4o-mini"
#   AI_CLASSIFY_CACHE_TTL = 86400 * 7   # 7 days
#   AI_CLASSIFY_RATE_LIMIT = 100         # per org per hour
#   AI_CLASSIFY_ENABLED_PLANS = ["professional", "executive"]  # or None for all

OPENAI_API_KEY = getattr(settings, "OPENAI_API_KEY", "")
AI_MODEL = getattr(settings, "AI_CLASSIFY_MODEL", "gpt-4o-mini")
CACHE_TTL = getattr(settings, "AI_CLASSIFY_CACHE_TTL", 86400 * 7)
RATE_LIMIT_PER_HOUR = getattr(settings, "AI_CLASSIFY_RATE_LIMIT", 100)
ENABLED_PLANS = getattr(settings, "AI_CLASSIFY_ENABLED_PLANS", None)  # None = all plans

# Bump this whenever the prompt or response shape changes — invalidates
# all cached entries from previous prompt versions.
CACHE_KEY_VERSION = "v2"


# =====================================================================
# Cache helpers
# =====================================================================

def _cache_key(org_id: int, title: str) -> str:
    """Stable cache key: org + normalized title signature + prompt version."""
    t = title.lower().strip()
    # Normalize dates and long numbers (same as agent-side PatternCache)
    t = re.sub(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b', 'DATE', t)
    t = re.sub(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', 'DATE', t)
    t = re.sub(r'\b\d{5,}\b', 'NNNNN', t)
    t = re.sub(r'\.\w{2,5}$', '.EXT', t)
    sig = hashlib.md5(t.encode()).hexdigest()[:16]
    return f"ai_classify:{CACHE_KEY_VERSION}:{org_id}:{sig}"


def _rate_limit_key(org_id: int) -> str:
    hour = int(time.time() // 3600)
    return f"ai_classify_rate:{org_id}:{hour}"


def _check_rate_limit(org_id: int) -> bool:
    """Returns True if under rate limit."""
    key = _rate_limit_key(org_id)
    current = cache.get(key, 0)
    if current >= RATE_LIMIT_PER_HOUR:
        return False
    cache.set(key, current + 1, timeout=3600)
    return True


# =====================================================================
# OpenAI call (server-side)
# =====================================================================

def _build_prompt(titles: list, clients: list) -> tuple:
    """
    Build evidence-grounded system + user prompt for OpenAI classification.

    The AI must quote textual evidence from the input or return null.
    Returns (system_prompt, user_prompt) tuple.
    """
    # Build client list
    client_lines = []
    for c in clients[:60]:
        aliases = c.get("aliases") or []
        alias_str = ', '.join(str(a) for a in aliases[:5]) if aliases else '(none)'
        client_lines.append(
            f"  - {c['id']} | \"{c['name']}\" | aliases: {alias_str}"
        )

    system = (
        "You are a client identification engine for a CPA/accounting firm's "
        "time tracker. For each activity, identify the client ONLY if there "
        "is textual evidence in the input.\n\n"
        "KNOWN CLIENTS for this firm (id | name | aliases):\n"
        + '\n'.join(client_lines)
        + "\n\n"
        "STRICT RULES:\n"
        "1. You may return a client_id ONLY if the client's name, an alias, "
        "a domain, or a clearly recognizable identifier appears LITERALLY "
        "in the activity's title, file_path, app_name, url, or "
        "additional_titles.\n"
        "2. You MUST provide `evidence_quote`: the exact substring of the "
        "input that identifies the client. Case-insensitive match is fine, "
        "but the substring must be present.\n"
        "3. If no client identifier appears in the input, return "
        "`client_id: null`. THIS IS THE CORRECT AND PREFERRED ANSWER when "
        "there is no evidence. Do NOT guess.\n"
        "4. CPA firms often name files with client identifiers like "
        "\"ClientName_FormType_Year\" or \"ClientName - 1040 - 2024\". "
        "Look in title and file_path. file_path is your STRONGEST signal — "
        "if the path contains a client folder, that's almost certainly "
        "the answer.\n"
        "5. Minor spelling/punctuation differences are OK (e.g. "
        "\"St.Anthony\" vs \"St. Anthony\") — match the client and use "
        "the substring as it appears in the input as evidence_quote.\n"
        "6. Common abbreviations as aliases are OK (e.g. \"D&F\" → "
        "\"Dauphin & Fantacone\"). The alias must still appear in the "
        "input, and evidence_quote must be the exact substring found.\n"
        "7. Do NOT pick a client based on:\n"
        "   - Activity type alone (e.g. \"this looks like banking work\")\n"
        "   - User history, common patterns, or which clients are similar\n"
        "   - Plausibility without textual evidence in this input\n"
        "8. Source code files (.py, .js, .tsx, etc.) and IDE windows "
        "(Sublime, VS Code, PyCharm) are developer tools — return null "
        "unless the file_path contains a client folder name.\n"
        "9. Email titles (\"Inbox - user@firm.com - Outlook\") with no "
        "client name → null.\n"
        "10. The `additional_titles` field lists OTHER window titles from "
        "the same activity block. Use them as supporting evidence: if the "
        "primary title is generic but additional_titles all reference the "
        "same client, match that client (evidence_quote should be from "
        "one of the additional_titles).\n"
        "11. Confidence reflects ONLY the strength of textual evidence:\n"
        "    - Clear match in title or file_path: 0.85-0.95\n"
        "    - Match in additional_titles only: 0.70-0.85\n"
        "    - Ambiguous or partial match: 0.50-0.70\n"
        "    - No quotable evidence: 0.0 with client_id=null\n\n"
        "Return a JSON object with this exact shape:\n"
        '{\n'
        '  "results": [\n'
        '    {\n'
        '      "idx": <int matching input index>,\n'
        '      "client_id": <int from KNOWN CLIENTS list, or null>,\n'
        '      "client_name": "<name or empty string>",\n'
        '      "evidence_quote": "<exact substring of input, or empty>",\n'
        '      "confidence": <float 0.0 to 1.0>,\n'
        '      "reasoning": "<brief explanation, including why null if null>"\n'
        '    }\n'
        '  ]\n'
        '}\n'
    )

    # Build activity items
    items = []
    for i, t in enumerate(titles):
        item = {"idx": i, "title": t.get("title", "")}
        if t.get("file_path"):
            item["file_path"] = t["file_path"]
        if t.get("app_name"):
            item["app"] = t["app_name"]
        if t.get("url"):
            item["url"] = t["url"]
        # v1.3.52: multi-title context. additional_titles is a list of
        # distinct window titles from the same block's raw events.
        if t.get("additional_titles"):
            item["additional_titles"] = t["additional_titles"]
        items.append(item)

    user = (
        "Identify the client for each activity. Remember: if you cannot "
        "quote evidence from the input that identifies the client, return "
        "client_id=null. Returning null when uncertain is the CORRECT answer.\n\n"
        f"{json.dumps(items, indent=1)}"
    )

    return system, user


def _call_openai(titles: list, clients: list) -> list:
    """
    Call OpenAI with evidence-grounded prompt and validate every response
    against the actual input. Returns list of results (one per title),
    None where validation fails.
    """
    import urllib.request

    system, user = _build_prompt(titles, clients)

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {OPENAI_API_KEY}")
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read())

    raw = (data["choices"][0]["message"]["content"] or "").strip()
    # JSON mode shouldn't wrap in markdown but defensive parse
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    parsed = json.loads(raw)

    # Extract results list. JSON mode requires an object so we wrap in
    # {"results": [...]}. Accept either shape for safety.
    if isinstance(parsed, list):
        results = parsed
    elif isinstance(parsed, dict):
        results = (
            parsed.get("results")
            or parsed.get("classifications")
            or parsed.get("activities")
            or []
        )
    else:
        raise ValueError(f"Expected JSON object or array, got {type(parsed)}")

    if not isinstance(results, list):
        raise ValueError("Expected `results` field to be a list")

    # Index by idx
    result_map = {}
    for r in results:
        idx = r.get("idx", -1)
        result_map[idx] = r

    output = []
    valid_client_ids = {c["id"] for c in clients}

    for i in range(len(titles)):
        r = result_map.get(i)
        if not r:
            output.append(None)
            continue

        client_id = r.get("client_id")
        if not client_id:
            # AI returned null — accept as-is (this is the preferred answer
            # when no evidence is found)
            output.append(None)
            continue

        # Validation 1: client_id must be in firm's list
        try:
            client_id = int(client_id)
        except (TypeError, ValueError):
            logger.info(
                f"[AI-VALIDATE] dropping non-int client_id={client_id!r}"
            )
            output.append(None)
            continue
        if client_id not in valid_client_ids:
            logger.info(
                f"[AI-VALIDATE] dropping client_id={client_id} — "
                f"not in firm's client list"
            )
            output.append(None)
            continue

        # Validation 2: evidence_quote must be present and non-empty
        evidence_quote = (r.get("evidence_quote") or "").strip()
        if not evidence_quote:
            logger.info(
                f"[AI-VALIDATE] dropping client_id={client_id} for title "
                f"{(titles[i].get('title') or '')[:60]!r} — "
                f"no evidence_quote (likely hallucination)"
            )
            output.append(None)
            continue

        # Validation 3: evidence_quote must appear in the actual input
        t = titles[i]
        haystack_parts = [
            t.get("title", "") or "",
            t.get("file_path", "") or "",
            t.get("app_name", "") or "",
            t.get("url", "") or "",
        ]
        haystack_parts.extend(t.get("additional_titles", []) or [])
        haystack = " ".join(haystack_parts).lower()

        if evidence_quote.lower() not in haystack:
            logger.info(
                f"[AI-VALIDATE] dropping client_id={client_id} — "
                f"evidence_quote {evidence_quote!r} not found in input "
                f"(hallucinated quote)"
            )
            output.append(None)
            continue

        # All validations passed
        output.append({
            "client_id": client_id,
            "client_name": r.get("client_name") or "",
            "confidence": float(r.get("confidence", 0.0)),
            "reasoning": r.get("reasoning", ""),
            "evidence_quote": evidence_quote,
        })

    return output


# =====================================================================
# Auth helper — reuse your existing device auth
# =====================================================================

def _get_device_and_org(request):
    from .models import AgentDevice

    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth.startswith("DeviceKey "):
        return None, None, None

    key = auth.replace("DeviceKey ", "").strip()
    try:
        device = AgentDevice.objects.select_related("user").get(
            api_key=key, is_active=True
        )
        membership = OrganizationMembership.objects.filter(user=device.user).first()
        org = membership.organization if membership else None
        return device, device.user, org
    except AgentDevice.DoesNotExist:
        return None, None, None


def _get_org_clients(org):
    """Get active clients for this org. Adjust to your Client model."""
    from .models import Client  # Adjust import path

    clients = Client.objects.filter(
        org=org, is_active=True
    ).values("id", "name", "aliases")

    return [
        {
            "id": c["id"],
            "name": c["name"],
            "aliases": c.get("aliases") or [],
        }
        for c in clients
    ]


# =====================================================================
# Views
# =====================================================================

@csrf_exempt
@require_POST
def ai_classify_window(request):
    """
    Single title classification.

    POST /api/ai/classify-window/
    {
        "title": "D&F 1040 2024.pdf",
        "app_name": "Adobe Acrobat",
        "file_path": "/docs/D&F_1040.pdf"
    }
    → {"client_id": 5, "client_name": "Dauphin & Fantacone", "confidence": 0.92, "cached": false}

    NOTE: v1.3.58 — the `current_client_name` field, if sent by the agent,
    is accepted for backward compatibility but no longer passed to the AI.
    Agent stickiness is handled by Stage 8 signals in classification_service,
    not by the AI prompt.
    """
    device, user, org = _get_device_and_org(request)
    if not org:
        return JsonResponse({"error": "unauthorized"}, status=401)

    # Plan gating
    if ENABLED_PLANS:
        plan = getattr(org, "plan", "free")
        if plan not in ENABLED_PLANS:
            return JsonResponse({"error": "ai_classification_not_available",
                                 "message": "Upgrade to Professional or Executive for AI classification"},
                                status=403)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    title = (body.get("title") or "").strip()
    if not title:
        return JsonResponse({"error": "title_required"}, status=400)

    # Check cache first
    ck = _cache_key(org.id, title)
    cached_result = cache.get(ck)
    if cached_result is not None:
        cached_result["cached"] = True
        logger.info(f"[AI-CLASSIFY] Cache hit for org={org.id}: {title[:60]} → {cached_result.get('client_name')}")
        return JsonResponse(cached_result)

    # Rate limit
    if not _check_rate_limit(org.id):
        return JsonResponse({"error": "rate_limit_exceeded",
                             "message": f"Max {RATE_LIMIT_PER_HOUR} AI classifications per hour"},
                            status=429)

    if not OPENAI_API_KEY:
        return JsonResponse({"error": "ai_not_configured"}, status=503)

    # Get org's clients
    clients = _get_org_clients(org)
    if not clients:
        return JsonResponse({"client_id": None, "client_name": None,
                             "confidence": 0, "cached": False})

    # Call OpenAI
    try:
        titles_batch = [{
            "title": title,
            "app_name": body.get("app_name", ""),
            "file_path": body.get("file_path", ""),
            "url": body.get("url", ""),
            # NOTE: current_client_name intentionally not passed to AI in v1.3.58.
            # Agent stickiness is handled by Stage 8 signals, not by the AI prompt.
        }]
        results = _call_openai(titles_batch, clients)
        result = results[0] if results else None

        if result and result.get("client_id"):
            response_data = {
                "client_id": result["client_id"],
                "client_name": result["client_name"],
                "confidence": result["confidence"],
                "reasoning": result.get("reasoning", ""),
                "evidence_quote": result.get("evidence_quote", ""),
                "cached": False,
            }
            # Cache the result for this org
            cache.set(ck, response_data, timeout=CACHE_TTL)

            # Also store in DB for analytics (optional)
            _log_classification(org, device, title, result)

            logger.info(f"[AI-CLASSIFY] org={org.id}: '{title[:60]}' → "
                        f"{result['client_name']} ({result['confidence']:.0%}) "
                        f"evidence={result.get('evidence_quote', '')[:40]!r}")
        else:
            response_data = {
                "client_id": None,
                "client_name": None,
                "confidence": 0,
                "cached": False,
            }
            # Cache the "no match" too to avoid repeat calls
            cache.set(ck, response_data, timeout=CACHE_TTL // 4)

        return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"[AI-CLASSIFY] Error for org={org.id}: {e}")
        return JsonResponse({"error": "classification_failed"}, status=500)


@csrf_exempt
@require_POST
def ai_classify_batch(request):
    """
    Batch classification (up to 10 titles at once).

    POST /api/ai/classify-batch/
    {
        "titles": [
            {"title": "D&F 1040 2024.pdf", "app_name": "Acrobat"},
            {"title": "Beck CPA financials.xlsx", "app_name": "Excel"}
        ]
    }
    → {"results": [{...}, {...}]}
    """
    device, user, org = _get_device_and_org(request)
    if not org:
        return JsonResponse({"error": "unauthorized"}, status=401)

    if ENABLED_PLANS:
        plan = getattr(org, "plan", "free")
        if plan not in ENABLED_PLANS:
            return JsonResponse({"error": "ai_classification_not_available"}, status=403)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "invalid_json"}, status=400)

    titles_input = body.get("titles") or []
    if not titles_input or len(titles_input) > 10:
        return JsonResponse({"error": "titles_required_max_10"}, status=400)

    clients = _get_org_clients(org)
    if not clients:
        return JsonResponse({"results": [None] * len(titles_input)})

    # Check cache for each title, only send uncached to OpenAI
    results = [None] * len(titles_input)
    uncached_indices = []
    uncached_titles = []

    for i, t in enumerate(titles_input):
        title = (t.get("title") or "").strip()
        if not title:
            continue
        ck = _cache_key(org.id, title)
        cached = cache.get(ck)
        if cached is not None:
            cached["cached"] = True
            results[i] = cached
        else:
            uncached_indices.append(i)
            uncached_titles.append(t)

    # Call OpenAI for uncached titles
    if uncached_titles:
        if not _check_rate_limit(org.id):
            return JsonResponse({"error": "rate_limit_exceeded"}, status=429)

        if not OPENAI_API_KEY:
            return JsonResponse({"error": "ai_not_configured"}, status=503)

        try:
            ai_results = _call_openai(uncached_titles, clients)

            for j, ai_result in enumerate(ai_results):
                orig_idx = uncached_indices[j]
                title = (uncached_titles[j].get("title") or "").strip()
                ck = _cache_key(org.id, title)

                if ai_result and ai_result.get("client_id"):
                    response_data = {
                        "client_id": ai_result["client_id"],
                        "client_name": ai_result["client_name"],
                        "confidence": ai_result["confidence"],
                        "reasoning": ai_result.get("reasoning", ""),
                        "evidence_quote": ai_result.get("evidence_quote", ""),
                        "cached": False,
                    }
                    cache.set(ck, response_data, timeout=CACHE_TTL)
                    _log_classification(org, device, title, ai_result)
                else:
                    response_data = {
                        "client_id": None,
                        "client_name": None,
                        "confidence": 0,
                        "cached": False,
                    }
                    cache.set(ck, response_data, timeout=CACHE_TTL // 4)

                results[orig_idx] = response_data

        except Exception as e:
            logger.error(f"[AI-CLASSIFY] Batch error for org={org.id}: {e}")
            # Return partial results (cached ones) + nulls for failed
            pass

    cache_hits = sum(1 for r in results if r and r.get("cached"))
    logger.info(f"[AI-CLASSIFY] Batch org={org.id}: {len(titles_input)} titles, "
                f"{cache_hits} cached, {len(uncached_titles)} sent to AI")

    return JsonResponse({"results": results})


# =====================================================================
# Analytics logging (optional — tracks usage for billing/insights)
# =====================================================================

def _log_classification(org, device, title, result):
    """
    Store classification result for analytics.
    Create this model or skip if you don't need analytics yet.
    """
    try:
        from .models import AIClassificationLog  # Optional model

        AIClassificationLog.objects.create(
            org=org,
            device=device,
            title=title[:500],
            client_id=result.get("client_id"),
            client_name=result.get("client_name", "")[:200],
            confidence=result.get("confidence", 0),
            reasoning=result.get("reasoning", "")[:500],
        )
    except Exception:
        pass  # Model doesn't exist yet — that's fine