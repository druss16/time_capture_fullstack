# tracker/services/pattern_learning.py
"""
Pattern Learning Service - Learns from user behavior to improve AI classification.

KEY IMPROVEMENTS OVER PREVIOUS VERSION:
1. Fixed org fallback (uses OrganizationMembership, not groups)
2. Negative learning - correcting a pattern downgrades the old one
3. Smarter time patterns - only learns specific recurring slots, not vague "morning"
4. Faster confidence growth (+0.05 per occurrence instead of +0.02)
5. Lower threshold for AI prompt inclusion (occurrence_count >= 2 instead of 3)
6. Domain patterns extracted more aggressively from URLs
7. Client name detection in window titles
"""

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import re
from django.db.models import Q, Count, Avg
from django.utils import timezone

import logging
logger = logging.getLogger(__name__)


class PatternLearningService:
    """
    Learns patterns from user behavior to improve AI classification.
    
    Pattern types (by reliability):
      - domain:     URL domain → client/category  (highest signal)
      - app:        App name → category            (high signal)
      - file_path:  Folder path → client/category  (high signal)
      - client_folder: "Clients/X" in path → client (high signal)
      - window_title_prefix: First segment of title  (medium signal)
      - time_slot:  Specific day+hour combos        (medium signal, needs repetition)
      - app_sequence: App switching patterns         (lower signal)
    """

    # =========================================================================
    # CONFIGURATION
    # =========================================================================
    
    # How much to boost confidence per repeated occurrence
    CONFIDENCE_BOOST = 0.05
    
    # How much to penalize when user corrects a pattern
    CONFIDENCE_PENALTY = 0.15
    
    # Max confidence score
    MAX_CONFIDENCE = 0.98
    
    # Min confidence to return as suggestion
    MIN_SUGGESTION_CONFIDENCE = 0.50
    
    # Min confidence to include in AI prompt context
    MIN_PROMPT_CONFIDENCE = 0.65
    
    # Min occurrences before including in AI prompt
    MIN_PROMPT_OCCURRENCES = 2
    
    # Patterns decay after this many days without being seen
    DECAY_DAYS = 60

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _get_org(block, user):
        """Get org from block or user membership. Never falls back to groups."""
        org = getattr(block, 'org', None)
        if org:
            return org
        
        try:
            from tracker.models import OrganizationMembership
            membership = OrganizationMembership.objects.filter(user=user).first()
            if membership:
                return membership.organization
        except Exception as e:
            logger.warning(f"[PATTERN] Failed to get org: {e}")
        
        return None

    @staticmethod
    def _get_category_from_block(block) -> str:
        """Extract the primary category name from a block."""
        cat_hours = getattr(block, 'category_hours', None)
        if cat_hours and isinstance(cat_hours, dict) and cat_hours:
            return list(cat_hours.keys())[0]
        return ''

    @staticmethod
    def _extract_domain(url: str) -> Optional[str]:
        """Extract clean domain from URL."""
        if not url:
            return None
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = (parsed.netloc or '').lower()
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain if domain and len(domain) > 3 else None
        except Exception:
            return None

    # =========================================================================
    # PATTERN EXTRACTION
    # =========================================================================

    @staticmethod
    def extract_app_patterns(block) -> List[Dict]:
        """
        Extract patterns from app name, URL domain, and window title.
        These are the highest-signal patterns.
        """
        patterns = []
        
        app_name = (getattr(block, 'app_name', None) or '').strip()
        url = (getattr(block, 'url', None) or '').strip()
        window_title = (getattr(block, 'window_title', None) or '').strip()
        
        # Pattern 1: App name (reliable for desktop apps)
        if app_name:
            app_lower = app_name.lower()
            # Skip generic/idle apps
            skip_apps = {'idle', 'unknown', '', 'loginwindow', 'screensaver', 'finder', 'dock'}
            if app_lower not in skip_apps:
                patterns.append({
                    'type': 'app',
                    'key': app_lower,
                    'confidence': 0.85
                })
        
        # Pattern 2: URL domain (very high signal for browser work)
        domain = PatternLearningService._extract_domain(url)
        if domain:
            # Skip generic domains that don't indicate specific work
            skip_domains = {
                'google.com', 'bing.com', 'duckduckgo.com',
                'youtube.com', 'reddit.com', 'twitter.com', 'x.com',
                'facebook.com', 'instagram.com', 'linkedin.com',
                'newtab', 'about:blank',
            }
            if domain not in skip_domains:
                patterns.append({
                    'type': 'domain',
                    'key': domain,
                    'confidence': 0.92
                })
        
        # Pattern 3: Window title prefix (for desktop apps with context)
        # e.g., "views.py - TimeTracker - Visual Studio Code" → "views.py"
        if window_title and ' - ' in window_title:
            # Use first meaningful segment
            parts = window_title.split(' - ')
            first_part = parts[0].strip()
            
            # Skip very short/generic prefixes
            skip_prefixes = {'new tab', 'untitled', 'open', '', 'home', 'dashboard'}
            if first_part.lower() not in skip_prefixes and 2 < len(first_part) < 60:
                patterns.append({
                    'type': 'window_title_prefix',
                    'key': first_part.lower(),
                    'confidence': 0.75
                })
        
        return patterns

    @staticmethod
    def extract_file_patterns(block) -> List[Dict]:
        """
        Extract patterns from file paths.
        
        Examples:
        - /Users/dan/Clients/Acme/2024/Tax/ → client_folder: Acme
        - ~/projects/timetracker/views.py → file_path: projects/timetracker
        """
        patterns = []
        file_path = getattr(block, 'file_path', None) or ''
        
        if not file_path:
            return patterns
        
        path_lower = file_path.lower()
        path_parts = [p for p in file_path.split('/') if p and p != '~']
        
        # Pattern 1: Client name in folder structure
        # Look for common patterns: "Clients/X", "Projects/X", etc.
        client_markers = {'clients', 'client', 'projects', 'engagements', 'matters'}
        for i, part in enumerate(path_parts):
            if part.lower() in client_markers and i + 1 < len(path_parts):
                potential_client = path_parts[i + 1]
                # Skip year-only folders and very short names
                if len(potential_client) > 2 and not potential_client.isdigit():
                    patterns.append({
                        'type': 'client_folder',
                        'key': f"{part.lower()}/{potential_client.lower()}",
                        'client_hint': potential_client,
                        'confidence': 0.88
                    })
                break  # Only use first match
        
        # Pattern 2: Parent folder path (excluding filename and home dir)
        # This catches repo roots, project folders, etc.
        if len(path_parts) > 2:
            # Skip user home prefix (Users/dan, home/user, etc.)
            start_idx = 0
            home_markers = {'users', 'home', 'documents', 'desktop', 'downloads'}
            for i, part in enumerate(path_parts[:3]):
                if part.lower() in home_markers:
                    start_idx = i + 1
                    # Skip one more if it's the username
                    if i + 1 < len(path_parts):
                        start_idx = i + 2
                    break
            
            # Take meaningful folder path (2-3 levels deep from project root)
            meaningful_parts = path_parts[start_idx:-1]  # Exclude filename
            if meaningful_parts:
                folder_key = '/'.join(meaningful_parts[:3]).lower()
                if len(folder_key) > 3:
                    patterns.append({
                        'type': 'file_path',
                        'key': folder_key,
                        'confidence': 0.90
                    })
        
        # Pattern 3: Category hints from folder names
        category_keywords = {
            'Tax Preparation': ['tax', 'returns', '1040', '1120', '1065', 'forms', 'efile'],
            'Accounting/Bookkeeping': ['bookkeeping', 'accounting', 'quickbooks', 'reconciliation', 'gl', 'ledger'],
            'Audit/Assurance': ['audit', 'assurance', 'review', 'compilation'],
            'Software Development': ['src', 'source', 'components', 'backend', 'frontend', 'api'],
            'Documentation': ['docs', 'documentation', 'wiki', 'readme'],
        }
        
        for category, keywords in category_keywords.items():
            if any(kw in path_lower for kw in keywords):
                patterns.append({
                    'type': 'category_folder',
                    'key': f"cat:{category.lower().replace('/', '_')}",
                    'category_hint': category,
                    'confidence': 0.78
                })
                break  # Only first match
        
        return patterns

    @staticmethod
    def extract_time_patterns(block) -> List[Dict]:
        """
        Extract SPECIFIC time slot patterns only.
        
        Instead of vague "morning" patterns, learns specific day+hour combos:
        - "monday_09" = Mondays at 9am → usually team meeting
        - "friday_16" = Fridays at 4pm → usually partner review
        
        These only become useful after repeated occurrences (3+).
        """
        patterns = []
        start = getattr(block, 'start', None)
        
        if not start:
            return patterns
        
        # Only learn specific day+hour combos (much more useful than vague time-of-day)
        weekday = start.strftime('%A').lower()
        hour = start.hour
        
        patterns.append({
            'type': 'time_slot',
            'key': f"{weekday}_{hour:02d}",
            'metadata': {'day': weekday, 'hour': hour},
            'confidence': 0.55  # Start low - needs repetition to matter
        })
        
        return patterns

    @staticmethod
    def extract_app_sequence_patterns(blocks: List) -> List[Dict]:
        """
        Extract patterns from 2-app switching sequences.
        Only tracks pairs, not triples (simpler and more reliable).
        """
        patterns = []
        
        if len(blocks) < 2:
            return patterns
        
        recent = blocks[-5:]
        apps = []
        for b in recent:
            app = (getattr(b, 'app_name', None) or '').lower().strip()
            if app and app not in ('idle', 'unknown', ''):
                # Deduplicate consecutive same-app entries
                if not apps or apps[-1] != app:
                    apps.append(app)
        
        # 2-app sequences only
        for i in range(len(apps) - 1):
            seq_key = f"{apps[i]}→{apps[i+1]}"
            patterns.append({
                'type': 'app_sequence',
                'key': seq_key,
                'metadata': {'from': apps[i], 'to': apps[i+1]},
                'confidence': 0.65
            })
        
        return patterns

    # =========================================================================
    # LEARN FROM USER ACTIONS
    # =========================================================================

    @staticmethod
    def learn_from_block(block, user):
        """
        Extract and store all patterns from a confirmed/categorized block.
        Called when user manually categorizes or confirms AI suggestion.
        
        KEY BEHAVIORS:
        - Creates new patterns on first occurrence
        - Boosts confidence on repeat occurrences (same client/category)
        - PENALIZES confidence if user corrected to different client/category
        - Updates client/category to match the correction
        """
        from tracker.models import UserWorkPattern
        
        if not block.client and not PatternLearningService._get_category_from_block(block):
            return  # Nothing to learn from
        
        org = PatternLearningService._get_org(block, user)
        category = PatternLearningService._get_category_from_block(block)
        
        # Extract all patterns from this block
        all_patterns = []
        # Only learn window_title_prefix and domain patterns — app names and time slots
        # are generic across all clients and cause false positives (Dewitt/Moose bug)
        app_patterns = PatternLearningService.extract_app_patterns(block)
        all_patterns.extend([p for p in app_patterns if p['type'] in ('window_title_prefix', 'domain')])
        all_patterns.extend(PatternLearningService.extract_file_patterns(block))
        # ← REMOVED: extract_time_patterns — time slots are never client-specific
        
        stored_count = 0
        corrected_count = 0
        
        for pattern_data in all_patterns:
            try:
                pattern, created = UserWorkPattern.objects.get_or_create(
                    user=user,
                    org=org,
                    pattern_type=pattern_data['type'],
                    pattern_key=pattern_data['key'],
                    defaults={
                        'client': block.client,
                        'category': category,
                        'confidence_score': pattern_data.get('confidence', 0.50),
                        'metadata': pattern_data.get('metadata', {}),
                    }
                )
                
                if created:
                    stored_count += 1
                    logger.debug(f"[PATTERN] New: {pattern_data['type']}:{pattern_data['key']} → {block.client}")
                else:
                    # Existing pattern - check if user is confirming or correcting
                    pattern.occurrence_count += 1
                    pattern.last_seen = timezone.now()
                    
                    same_client = (
                        (pattern.client_id == getattr(block.client, 'id', None)) or
                        (pattern.client is None and block.client is None)
                    )
                    same_category = (pattern.category == category) if category else True
                    
                    if same_client and same_category:
                        # CONFIRMING existing pattern → boost confidence
                        pattern.confidence_score = min(
                            PatternLearningService.MAX_CONFIDENCE,
                            pattern.confidence_score + PatternLearningService.CONFIDENCE_BOOST
                        )
                    else:
                        # CORRECTING → penalize old pattern, update to new values
                        old_client = pattern.client.name if pattern.client else 'None'
                        new_client = block.client.name if block.client else 'None'
                        
                        pattern.confidence_score = max(
                            0.30,
                            pattern.confidence_score - PatternLearningService.CONFIDENCE_PENALTY
                        )
                        pattern.client = block.client
                        pattern.category = category
                        
                        # Reset occurrence count on correction (it's now a "new" pattern)
                        pattern.occurrence_count = 1
                        
                        corrected_count += 1
                        logger.info(
                            f"[PATTERN] Corrected: {pattern_data['type']}:{pattern_data['key']} "
                            f"({old_client} → {new_client})"
                        )
                    
                    pattern.save()
                    stored_count += 1
                    
            except Exception as e:
                logger.warning(f"[PATTERN] Failed to save {pattern_data['type']}:{pattern_data['key']}: {e}")
        
        if stored_count:
            logger.info(
                f"[PATTERN] Learned {stored_count} patterns from block {block.id} "
                f"({corrected_count} corrections)"
            )

    # =========================================================================
    # RETRIEVE PATTERNS FOR A BLOCK
    # =========================================================================

    @staticmethod
    def get_patterns_for_block(block, user) -> List[Tuple[str, str, float]]:
        """
        Retrieve learned patterns that match this block.
        
        Returns: [(client_name, category, confidence), ...] sorted by confidence desc
        """
        from tracker.models import UserWorkPattern
        
        if not user:
            return []
        
        suggestions = []
        
        # Extract patterns from current block
        all_patterns = []
        all_patterns.extend(PatternLearningService.extract_app_patterns(block))
        all_patterns.extend(PatternLearningService.extract_file_patterns(block))
        all_patterns.extend(PatternLearningService.extract_time_patterns(block))
        
        # Collect all pattern keys to query in ONE database call
        pattern_keys = []
        pattern_map = {}  # key → extraction confidence
        
        for p in all_patterns:
            lookup_key = (p['type'], p['key'])
            pattern_keys.append(lookup_key)
            pattern_map[lookup_key] = p.get('confidence', 0.70)
        
        if not pattern_keys:
            return []
        
        # Build Q filter for batch lookup
        q_filter = Q()
        for ptype, pkey in pattern_keys:
            q_filter |= Q(pattern_type=ptype, pattern_key=pkey)
        
        # Single query for all matching patterns
        matches = UserWorkPattern.objects.filter(
            q_filter,
            user=user,
            confidence_score__gte=PatternLearningService.MIN_SUGGESTION_CONFIDENCE,
        ).select_related('client')
        
        # Skip stale patterns
        decay_cutoff = timezone.now() - timedelta(days=PatternLearningService.DECAY_DAYS)
        
        for match in matches:
            # Skip patterns not seen recently
            if match.last_seen and match.last_seen < decay_cutoff:
                continue
            
            client_name = match.client.name if match.client else None
            category = match.category or None
            
            if not client_name and not category:
                continue
            
            # Combined confidence: learned × extraction strength
            extraction_confidence = pattern_map.get(
                (match.pattern_type, match.pattern_key), 0.70
            )
            combined = match.confidence_score * extraction_confidence
            
            # Boost patterns with many occurrences
            if match.occurrence_count >= 5:
                combined = min(0.98, combined + 0.05)
            elif match.occurrence_count >= 3:
                combined = min(0.95, combined + 0.02)
            
            suggestions.append((client_name, category, combined))
        
        # Deduplicate: if same client+category appears multiple times, keep highest
        seen = {}
        for client_name, category, confidence in suggestions:
            key = (client_name, category)
            if key not in seen or confidence > seen[key]:
                seen[key] = confidence
        
        deduped = [(k[0], k[1], v) for k, v in seen.items()]
        deduped.sort(key=lambda x: x[2], reverse=True)
        
        return deduped[:5]

    # =========================================================================
    # BUILD CONTEXT FOR AI PROMPT
    # =========================================================================

    @staticmethod
    def build_pattern_context(user, org) -> str:
        """
        Build a text summary of learned patterns to include in AI prompt.
        Only includes patterns with enough repetition to be meaningful.
        """
        from tracker.models import UserWorkPattern
        
        if not user:
            return ""
        
        # Only patterns with real signal
        decay_cutoff = timezone.now() - timedelta(days=PatternLearningService.DECAY_DAYS)
        
        top_patterns = UserWorkPattern.objects.filter(
            user=user,
            confidence_score__gte=PatternLearningService.MIN_PROMPT_CONFIDENCE,
            occurrence_count__gte=PatternLearningService.MIN_PROMPT_OCCURRENCES,
            last_seen__gte=decay_cutoff,
        ).select_related('client').order_by('-confidence_score', '-occurrence_count')[:25]
        
        if not top_patterns.exists():
            return ""
        
        # Group by type
        by_type = defaultdict(list)
        for p in top_patterns:
            by_type[p.pattern_type].append(p)
        
        sections = []
        
        # Domain patterns (highest value for AI)
        if 'domain' in by_type:
            lines = ["**LEARNED URL PATTERNS** (from this user's confirmed categorizations):"]
            for p in by_type['domain'][:8]:
                client_name = p.client.name if p.client else "?"
                cat = f", Category: {p.category}" if p.category else ""
                lines.append(
                    f"  - {p.pattern_key} → Client: {client_name}{cat} "
                    f"(confirmed {p.occurrence_count}x, {int(p.confidence_score*100)}%)"
                )
            sections.append('\n'.join(lines))
        
        # App patterns
        if 'app' in by_type:
            lines = ["**LEARNED APP PATTERNS**:"]
            for p in by_type['app'][:6]:
                client_name = p.client.name if p.client else "?"
                cat = p.category or "?"
                lines.append(
                    f"  - App '{p.pattern_key}' → {client_name} / {cat} "
                    f"({p.occurrence_count}x)"
                )
            sections.append('\n'.join(lines))
        
        # File path patterns
        file_types = ['file_path', 'client_folder', 'category_folder']
        file_patterns = []
        for ft in file_types:
            file_patterns.extend(by_type.get(ft, []))
        
        if file_patterns:
            lines = ["**LEARNED FILE PATTERNS** (user's folder organization):"]
            for p in file_patterns[:5]:
                client_name = p.client.name if p.client else "?"
                lines.append(
                    f"  - Path '{p.pattern_key}' → Client: {client_name} "
                    f"({p.occurrence_count}x)"
                )
            sections.append('\n'.join(lines))
        
        # Time slot patterns (only if very consistent)
        if 'time_slot' in by_type:
            strong_time = [p for p in by_type['time_slot'] if p.occurrence_count >= 3]
            if strong_time:
                lines = ["**LEARNED SCHEDULE PATTERNS** (recurring time slots):"]
                for p in strong_time[:4]:
                    meta = p.metadata or {}
                    day = meta.get('day', '?').title()
                    hour = meta.get('hour', '?')
                    client_name = p.client.name if p.client else p.category or "?"
                    lines.append(
                        f"  - {day} at {hour}:00 → Usually: {client_name} "
                        f"({p.occurrence_count}x)"
                    )
                sections.append('\n'.join(lines))
        
        if sections:
            return "\n=== LEARNED USER PATTERNS ===\n" + '\n\n'.join(sections)
        
        return ""

    # =========================================================================
    # MAINTENANCE
    # =========================================================================

    @staticmethod
    def cleanup_stale_patterns(user=None, days: int = None) -> Dict[str, int]:
        """
        Remove patterns that haven't been seen recently or have very low confidence.
        Run periodically (e.g., weekly via Celery).
        """
        from tracker.models import UserWorkPattern
        
        days = days or PatternLearningService.DECAY_DAYS
        cutoff = timezone.now() - timedelta(days=days)
        
        qs = UserWorkPattern.objects.filter(
            Q(last_seen__lt=cutoff) | Q(confidence_score__lt=0.35)
        )
        
        if user:
            qs = qs.filter(user=user)
        
        count = qs.count()
        qs.delete()
        
        logger.info(f"[PATTERN] Cleaned up {count} stale patterns")
        return {'deleted': count}

    @staticmethod
    def get_pattern_stats(user) -> Dict:
        """Get summary stats for debugging/admin."""
        from tracker.models import UserWorkPattern
        
        if not user:
            return {}
        
        patterns = UserWorkPattern.objects.filter(user=user)
        
        by_type = patterns.values('pattern_type').annotate(
            count=Count('id'),
            avg_confidence=Avg('confidence_score'),
        )
        
        return {
            'total': patterns.count(),
            'high_confidence': patterns.filter(confidence_score__gte=0.80).count(),
            'by_type': {
                item['pattern_type']: {
                    'count': item['count'],
                    'avg_confidence': round(float(item['avg_confidence'] or 0), 2),
                }
                for item in by_type
            }
        }