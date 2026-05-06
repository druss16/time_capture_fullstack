"""
Django view: POST /api/ai/classify-window/

Agents send window titles → backend classifies using OpenAI → caches results.
One API key, server-side, shared across all orgs. Results cached per-org so
repeated titles are instant.

Add to your urls.py:
    path("api/ai/classify-window/", ai_classify_window, name="ai_classify_window"),
    path("api/ai/classify-batch/", ai_classify_batch, name="ai_classify_batch"),
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


# =====================================================================
# Cache helpers
# =====================================================================

def _cache_key(org_id: int, title: str) -> str:
    """Stable cache key: org + normalized title signature."""
    t = title.lower().strip()
    # Normalize dates and long numbers (same as agent-side PatternCache)
    t = re.sub(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b', 'DATE', t)
    t = re.sub(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', 'DATE', t)
    t = re.sub(r'\b\d{5,}\b', 'NNNNN', t)
    t = re.sub(r'\.\w{2,5}$', '.EXT', t)
    sig = hashlib.md5(t.encode()).hexdigest()[:16]
    return f"ai_classify:{org_id}:{sig}"


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
    """Build system + user prompt for OpenAI classification."""
    client_lines = []
    for c in clients[:60]:
        aliases = c.get("aliases") or []
        alias_str = f" (also: {', '.join(aliases[:5])})" if aliases else ""
        client_lines.append(f"  ID {c['id']}: {c['name']}{alias_str}")

    system = f"""You are a client identification engine for a CPA/accounting firm's time tracker.

TASK: Given window titles / file names, determine which CLIENT the user is working on.

KNOWN CLIENTS:
{chr(10).join(client_lines)}

RULES:
1. CPA firms name files like: "ClientName_FormType_Year", "ClientName - 1040 - 2024"
2. Look for client names, abbreviations, nicknames, or aliases in title, file_path, AND url.
3. Common abbreviations: first letters of multi-word names (e.g., "D&F" = "Dauphin & Fantacone")
4. file_path is your STRONGEST signal — if the path contains a client folder, that's almost
   certainly the answer. Use the deepest folder name first.
5. The "current_client" field shows who the user is CURRENTLY tracked as. If the new title
   has weak or no client signal (generic apps like "Outlook", "TimeTracker", "Chrome",
   PowerShell, source code files), prefer returning the current_client at moderate confidence
   (0.50-0.65) — they're still working on the same thing, just switched windows briefly.
6. NEVER return a client just because it matches the current_client — there must be SOME
   signal in title/path/url, OR the title must be generic enough to be a "brief detour"
   (alt-tabbing to a calculator, terminal, or browser with no relevant content).
7. Source code files (.py, .js, .tsx, etc.) and IDE windows (Sublime, VS Code, PyCharm)
   are developer tools — almost never a real client signal. Return null unless path
   contains a client folder name.
8. Email titles ("Inbox - user@firm.com - Outlook") with no client name → null.
9. Confidence: clear match 0.85-0.95. Partial/ambiguous 0.50-0.75. Generic-but-staying-on-
   current 0.50-0.65. NO match → null with confidence 0.0.
10. Generic windows with no client signal AND no current_client → null.

Return ONLY a JSON array, one object per input:
[{{"idx":<int>,"client_id":<int|null>,"client_name":"<str|null>","confidence":<float>,"reasoning":"<brief>"}}]"""

    items = []
    for i, t in enumerate(titles):
        item = {"idx": i, "title": t["title"]}
        if t.get("file_path"):
            item["file_path"] = t["file_path"]
        if t.get("app_name"):
            item["app"] = t["app_name"]
        if t.get("url"):
            item["url"] = t["url"]
        if t.get("current_client_name"):
            item["current_client"] = t["current_client_name"]
        items.append(item)

    user = f"Identify the client for each:\n{json.dumps(items, indent=1)}"
    return system, user


def _call_openai(titles: list, clients: list) -> list:
    """Call OpenAI and return list of results (one per title)."""
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
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    results = json.loads(raw)
    if not isinstance(results, list):
        raise ValueError("Expected JSON array from OpenAI")

    # Index results by idx
    result_map = {}
    for r in results:
        idx = r.get("idx", -1)
        result_map[idx] = r

    # Build ordered output
    output = []
    valid_client_ids = {c["id"] for c in clients}
    for i in range(len(titles)):
        r = result_map.get(i)
        if not r or not r.get("client_id") or r["client_id"] not in valid_client_ids:
            output.append(None)
        else:
            output.append({
                "client_id": int(r["client_id"]),
                "client_name": r.get("client_name") or "",
                "confidence": float(r.get("confidence", 0.0)),
                "reasoning": r.get("reasoning", ""),
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
            "current_client_name": body.get("current_client_name", ""),
        }]
        results = _call_openai(titles_batch, clients)
        result = results[0] if results else None

        if result and result.get("client_id"):
            response_data = {
                "client_id": result["client_id"],
                "client_name": result["client_name"],
                "confidence": result["confidence"],
                "reasoning": result.get("reasoning", ""),
                "cached": False,
            }
            # Cache the result for this org
            cache.set(ck, response_data, timeout=CACHE_TTL)

            # Also store in DB for analytics (optional)
            _log_classification(org, device, title, result)

            logger.info(f"[AI-CLASSIFY] org={org.id}: '{title[:60]}' → "
                        f"{result['client_name']} ({result['confidence']:.0%})")
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