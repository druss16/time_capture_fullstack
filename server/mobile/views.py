"""
server/mobile/views.py

Correct model mapping for time_capture_fullstack:
  - Block          (not TimeEntry) — org, user, start, end, minutes, client, notes, category_hours
  - Client         — org FK, is_active, name
  - OrganizationMembership — joins user → organization
  - No Category model — category_hours is a JSONField on Block
  - No is_billable field — approved is the nearest equivalent
"""

import base64
import json
import tempfile
import os
from datetime import datetime

from django.utils import timezone
from django.db.models import Count
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

import openai

from tracker.models import Block, Client, OrganizationMembership, Organization


# ── Helper: resolve the org for the current user ──────────────────────────────

def get_user_org(user):
    """
    OrganizationMembership links user → organization.
    Returns the first org the user belongs to.
    """
    membership = (
        OrganizationMembership.objects
        .select_related('organization')
        .filter(user=user)
        .first()
    )
    return membership.organization if membership else None


def get_common_categories(user, org, limit=8):
    """
    category_hours is a JSONField dict like {"Tax Preparation": 1.5, "Admin": 0.5}.
    Pull the most-used category keys across this user's recent blocks.
    """
    recent_blocks = (
        Block.objects
        .filter(user=user, org=org, is_categorized=True)
        .exclude(category_hours={})
        .order_by('-start')[:200]
        .values_list('category_hours', flat=True)
    )

    counts = {}
    for ch in recent_blocks:
        if isinstance(ch, dict):
            for cat in ch.keys():
                counts[cat] = counts.get(cat, 0) + 1

    sorted_cats = sorted(counts, key=lambda k: counts[k], reverse=True)
    return sorted_cats[:limit]


# ── 1. Start timer ────────────────────────────────────────────────────────────

class MobileStartView(APIView):
    """POST /api/mobile/start/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization found'}, status=400)

        client_id      = request.data.get('client_id')
        start_time_str = request.data.get('start_time')

        try:
            start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
        except (TypeError, ValueError):
            start = timezone.now()

        client = None
        if client_id:
            try:
                client = Client.objects.get(id=client_id, org=org)
            except Client.DoesNotExist:
                pass

        block = Block.objects.create(
            user=request.user,
            org=org,
            client=client,
            start=start,
            end=start,          # placeholder — updated on stop
            minutes=0,
            hostname='mobile',
            device_id='mobile',
            title='Mobile entry',
            categorized_by='manual',
        )

        return Response({
            'entry_id':   block.id,
            'start_time': block.start.isoformat(),
        }, status=status.HTTP_201_CREATED)


# ── 2. Stop timer ─────────────────────────────────────────────────────────────

class MobileStopView(APIView):
    """POST /api/mobile/stop/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org = get_user_org(request.user)
        if not org:
            return Response({'error': 'No organization found'}, status=400)

        entry_id         = request.data.get('entry_id')
        end_time_str     = request.data.get('end_time')
        duration_seconds = int(request.data.get('duration_seconds', 0))
        client_id        = request.data.get('client_id')
        category_name    = request.data.get('category_name', '')
        note             = request.data.get('note', '')
        is_billable      = bool(request.data.get('is_billable', True))

        try:
            block = Block.objects.get(id=entry_id, user=request.user)
        except Block.DoesNotExist:
            # Started offline — create fresh
            block = Block(
                user=request.user,
                org=org,
                hostname='mobile',
                device_id='mobile',
                title='Mobile entry',
                start=timezone.now(),
            )

        try:
            block.end = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
        except (TypeError, ValueError):
            block.end = timezone.now()

        block.minutes        = max(1, round(duration_seconds / 60))
        block.day            = block.start.date()
        block.notes          = note
        block.approved       = is_billable
        block.is_categorized = True
        block.categorized_by = 'manual'
        block.categorized_at = timezone.now()

        if category_name:
            hours = duration_seconds / 3600
            block.category_hours = {category_name: round(hours, 4)}

        if client_id:
            try:
                block.client = Client.objects.get(id=client_id, org=org)
            except Client.DoesNotExist:
                pass

        block.save()

        return Response({
            'id':            block.id,
            'client_name':   block.client.name if block.client else None,
            'category_name': category_name,
            'minutes':       block.minutes,
            'start':         block.start.isoformat(),
            'end':           block.end.isoformat(),
            'notes':         block.notes,
            'approved':      block.approved,
        })


# ── 3. Recent blocks + clients + categories ───────────────────────────────────

class MobileRecentView(APIView):
    """GET /api/mobile/recent/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = get_user_org(request.user)
        if not org:
            return Response({'entries': [], 'clients': [], 'categories': []})

        blocks = (
            Block.objects
            .filter(user=request.user, org=org)
            .select_related('client')
            .order_by('-start')[:10]
        )

        clients = list(
            Client.objects
            .filter(org=org, is_active=True)
            .order_by('name')
            .values('id', 'name')
        )

        raw_cats = get_common_categories(request.user, org)
        categories = [
            {'id': i, 'name': name, 'is_billable_default': True}
            for i, name in enumerate(raw_cats)
        ]

        entries_data = []
        for b in blocks:
            cat_name = (
                list(b.category_hours.keys())[0]
                if isinstance(b.category_hours, dict) and b.category_hours
                else 'Uncategorized'
            )
            entries_data.append({
                'id':               b.id,
                'client_id':        b.client_id,
                'client_name':      b.client.name if b.client else 'Unknown',
                'category_id':      0,
                'category_name':    cat_name,
                'duration_seconds': (b.minutes or 0) * 60,
                'is_billable':      b.approved,
                'note':             b.notes or '',
                'start_time':       b.start.isoformat(),
            })

        return Response({
            'entries':    entries_data,
            'clients':    clients,
            'categories': categories,
        })


# ── 4. AI suggestion ──────────────────────────────────────────────────────────

class MobileAISuggestView(APIView):
    """POST /api/mobile/ai-suggest/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org         = get_user_org(request.user)
        hour        = int(request.data.get('hour', 9))
        day_of_week = int(request.data.get('day_of_week', 1))

        recent = (
            Block.objects
            .filter(user=request.user, is_categorized=True, client__isnull=False)
            .select_related('client')
            .order_by('-start')[:30]
        )

        if not recent:
            return Response({
                'client_id': None, 'client_name': None,
                'category_name': None, 'is_billable': True,
                'confidence': 0, 'reason': '',
            })

        history_lines = []
        for b in recent:
            cat = (
                list(b.category_hours.keys())[0]
                if isinstance(b.category_hours, dict) and b.category_hours
                else 'unknown'
            )
            history_lines.append(
                f"- {b.client.name} | {cat} | dow={b.start.weekday()} hour={b.start.hour}"
            )

        clients    = list(Client.objects.filter(org=org, is_active=True).values('id', 'name')) if org else []
        categories = get_common_categories(request.user, org) if org else []

        prompt = f"""You are a time tracking AI for a CPA firm employee.
Based on their recent history, predict what they are most likely working on RIGHT NOW.

Current context: day_of_week={day_of_week} (0=Mon, 6=Sun), hour={hour}

Recent history (last 30 entries):
{chr(10).join(history_lines)}

Available clients: {', '.join(c['name'] for c in clients)}
Common categories: {', '.join(categories)}

Respond ONLY with valid JSON (no markdown, no code fences):
{{
  "client_name": "exact name from available clients or null",
  "category_name": "category string or null",
  "is_billable": true,
  "confidence": 0.85,
  "reason": "Short one-line reason e.g. You usually track Dauphin on Friday mornings"
}}"""

        try:
            oai  = openai.OpenAI()
            resp = oai.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=200,
                temperature=0.3,
            )
            data = json.loads(resp.choices[0].message.content.strip())
        except Exception:
            return Response({
                'client_id': None, 'client_name': None,
                'category_name': None, 'is_billable': True,
                'confidence': 0, 'reason': '',
            })

        client_match = next((c for c in clients if c['name'] == data.get('client_name')), None)

        return Response({
            'client_id':     client_match['id'] if client_match else None,
            'client_name':   data.get('client_name'),
            'category_name': data.get('category_name'),
            'is_billable':   bool(data.get('is_billable', True)),
            'confidence':    float(data.get('confidence', 0)),
            'reason':        data.get('reason', ''),
        })


# ── 5. Voice parse ────────────────────────────────────────────────────────────

class MobileVoiceParseView(APIView):
    """POST /api/mobile/voice-parse/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org       = get_user_org(request.user)
        audio_b64 = request.data.get('audio_base64', '')
        mime_type = request.data.get('mime_type', 'audio/m4a')

        clients    = list(Client.objects.filter(org=org, is_active=True).values('id', 'name')) if org else []
        categories = get_common_categories(request.user, org) if org else []

        try:
            audio_bytes = base64.b64decode(audio_b64)
            suffix = '.m4a' if 'm4a' in mime_type or 'mp4' in mime_type else '.wav'

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name

            oai = openai.OpenAI()

            with open(tmp_path, 'rb') as af:
                transcript = oai.audio.transcriptions.create(
                    model='whisper-1', file=af
                ).text
            os.unlink(tmp_path)

            parse_prompt = f"""Extract time entry details from this voice memo.
Transcript: "{transcript}"
Available clients: {', '.join(c['name'] for c in clients)}
Common categories: {', '.join(categories)}
Respond ONLY with valid JSON (no markdown):
{{"client_name":"best match or null","category_name":"best match or null","note":"extra context","is_billable":true}}"""

            parsed = json.loads(
                oai.chat.completions.create(
                    model='gpt-4o',
                    messages=[{'role': 'user', 'content': parse_prompt}],
                    max_tokens=200,
                    temperature=0.1,
                ).choices[0].message.content.strip()
            )

        except Exception as e:
            return Response({'error': str(e)}, status=400)

        client_match = next((c for c in clients if c['name'] == parsed.get('client_name')), None)

        return Response({
            'transcript':    transcript,
            'client_id':     client_match['id'] if client_match else None,
            'client_name':   parsed.get('client_name'),
            'category_name': parsed.get('category_name'),
            'note':          parsed.get('note', ''),
            'is_billable':   bool(parsed.get('is_billable', True)),
        })


# ── 6. Calendar suggest ───────────────────────────────────────────────────────

class MobileCalendarSuggestView(APIView):
    """POST /api/mobile/calendar-suggest/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        org          = get_user_org(request.user)
        event_titles = request.data.get('event_titles', [])
        if not event_titles:
            return Response([])

        clients = list(
            Client.objects.filter(org=org, is_active=True).values('id', 'name')
        ) if org else []

        prompt = f"""Match each calendar event title to the most likely client.
Available clients: {', '.join(c['name'] for c in clients)}
Events:
{chr(10).join(f'- "{t}"' for t in event_titles)}
Respond ONLY with a valid JSON array (no markdown):
[{{"event_title":"...","client_name":"exact client name or null"}}]"""

        try:
            oai     = openai.OpenAI()
            results = json.loads(
                oai.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[{'role': 'user', 'content': prompt}],
                    max_tokens=300,
                    temperature=0.1,
                ).choices[0].message.content.strip()
            )
        except Exception:
            return Response([
                {'event_title': t, 'client_id': None, 'client_name': None}
                for t in event_titles
            ])

        return Response([
            {
                'event_title': r.get('event_title'),
                'client_id':   next((c['id'] for c in clients if c['name'] == r.get('client_name')), None),
                'client_name': r.get('client_name'),
            }
            for r in results
        ])