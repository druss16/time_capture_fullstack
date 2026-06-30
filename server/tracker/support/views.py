"""
Support API views.

Wire into tracker's main urls.py:
    path("api/support/", include("tracker.support.urls")),
(routes live in tracker/support/urls.py)

Auth + org resolution match the rest of TimeTracker: DRF auth populates
request.user, and the active org is resolved via OrganizationMembership.
If you already have a helper/middleware that puts the org on the request,
replace _resolve_org() with that.
"""
import os
import requests

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from tracker.models import (
    Organization, OrganizationMembership,
    SupportConversation, SupportMessage, SupportTicket,
)
from .embeddings import retrieve


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# ── Cost / quality knobs ──────────────────────────────────────────────────────
# Flip this ONE line to A/B quality vs. cost:
#   "claude-haiku-4-5"   → ~5-10x cheaper, great for grounded Q&A (default)
#   "claude-sonnet-4-6"  → smoother writing on complex questions, pricier
SUPPORT_CHAT_MODEL = "claude-haiku-4-5"

# Support answers should be short. Capping output tokens caps the priciest
# part of each call (output costs more than input) and keeps replies tight.
SUPPORT_MAX_TOKENS = 600

# How many KB chunks to retrieve. Fewer = cheaper input + tighter answers.
SUPPORT_RETRIEVAL_K = 3

# Prompt caching: the instruction block below is identical on every call, so
# we mark it cache-eligible. Anthropic then doesn't re-bill those tokens on
# repeat calls within the cache window — meaningful savings at volume.
ANTHROPIC_VERSION = "2023-06-01"
# ──────────────────────────────────────────────────────────────────────────────

# Split the system prompt into a STABLE part (cacheable) and a DYNAMIC part
# (the retrieved docs, which change per question and can't be cached).
SYSTEM_INSTRUCTIONS = """You are the in-app support assistant for TimeTracker, \
an AI time-capture and billing product for CPA firms.

Answer the user's question using ONLY the documentation provided. \
Be concise, friendly, and concrete. Use the product's own terms (Daily Review, \
Billing, Reports, Analytics, Settings, agent, classification). Prefer short \
numbered steps for "how do I" questions.

If the documentation does not contain the answer, do NOT guess. Instead say \
you're not certain and that you can open an email ticket to the team. End \
that reply with the exact token [[ESCALATE]] on its own line so the app can \
offer the handoff."""


def _resolve_org(request) -> Organization:
    """
    Resolve the active org for this user. Mirrors how the rest of the app
    derives org from membership. If the user belongs to multiple orgs and
    you track an active one (impersonation / header / session), prefer that.
    """
    membership = (
        OrganizationMembership.objects
        .filter(user=request.user)
        .select_related('organization')
        .first()
    )
    if not membership:
        return None
    return membership.organization


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def support_chat(request):
    """
    Body: { "conversation_id": int|null, "message": str }
    Returns the assistant reply + conversation id.
    """
    org = _resolve_org(request)
    if org is None:
        return JsonResponse({"error": "No organization for user."}, status=403)

    user_msg = request.data["message"].strip()
    conv_id = request.data.get("conversation_id")

    if conv_id:
        conv = SupportConversation.objects.get(
            id=conv_id, user=request.user, org=org,
        )
    else:
        conv = SupportConversation.objects.create(
            user=request.user, org=org, title=user_msg[:60],
        )

    SupportMessage.objects.create(conversation=conv, role="user", content=user_msg)

    # Retrieve grounding chunks (org-scoped + global).
    docs = retrieve(user_msg, org_id=org.id, k=SUPPORT_RETRIEVAL_K)
    context = "\n\n---\n\n".join(
        f"[{d.title} | {d.source}]\n{d.content}" for d in docs
    ) or "(no documentation found)"

    history = [
        {"role": m.role, "content": m.content}
        for m in conv.messages.order_by("created_at")
    ]

    # System prompt as a list of blocks so we can cache the stable instructions
    # while letting the per-question documentation vary. Only the first block
    # carries cache_control; the docs block is fresh each time.
    system_blocks = [
        {
            "type": "text",
            "text": SYSTEM_INSTRUCTIONS,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"DOCUMENTATION:\n{context}",
        },
    ]

    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": SUPPORT_CHAT_MODEL,
            "max_tokens": SUPPORT_MAX_TOKENS,
            "system": system_blocks,
            "messages": history,
        },
        timeout=60,
    )
    resp.raise_for_status()
    reply = "".join(
        b["text"] for b in resp.json()["content"] if b["type"] == "text"
    )

    escalated = "[[ESCALATE]]" in reply
    reply = reply.replace("[[ESCALATE]]", "").strip()

    SupportMessage.objects.create(
        conversation=conv, role="assistant", content=reply,
        cited_doc_ids=[d.id for d in docs],
        was_grounded=not escalated,
    )

    return JsonResponse({
        "conversation_id": conv.id,
        "reply": reply,
        "escalate": escalated,
        "sources": [{"title": d.title, "source": d.source} for d in docs],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_conversations(request):
    convs = SupportConversation.objects.filter(user=request.user)
    return JsonResponse({"conversations": [
        {"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat()}
        for c in convs
    ]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_conversation(request, pk):
    conv = SupportConversation.objects.get(id=pk, user=request.user)
    return JsonResponse({
        "id": conv.id,
        "title": conv.title,
        "messages": [
            {"role": m.role, "content": m.content,
             "created_at": m.created_at.isoformat()}
            for m in conv.messages.order_by("created_at")
        ],
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_ticket(request):
    """
    Body: { "subject": str, "body": str, "conversation_id": int|null }
    Persists the ticket AND emails the team via your existing mail path.
    """
    org = _resolve_org(request)
    if org is None:
        return JsonResponse({"error": "No organization for user."}, status=403)

    conv_id = request.data.get("conversation_id")
    conv = (SupportConversation.objects.filter(
                id=conv_id, user=request.user, org=org).first()
            if conv_id else None)

    ticket = SupportTicket.objects.create(
        user=request.user, org=org,
        subject=request.data["subject"],
        body=request.data["body"],
        conversation=conv,
    )

    # Reuse your existing Celery/Graph/SMTP mail path here.
    from django.core.mail import send_mail
    send_mail(
        subject=f"[TimeTracker support #{ticket.id}] {ticket.subject}",
        message=(
            f"From: {request.user.email} (org: {org.name}, id {org.id})\n\n"
            f"{ticket.body}\n\n"
            f"--- ticket #{ticket.id} ---"
        ),
        from_email="support@mavops.ai",
        recipient_list=["support@mavops.ai"],
        fail_silently=False,
    )

    return JsonResponse({"ticket_id": ticket.id, "status": ticket.status})