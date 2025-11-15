# tracker/services/pattern_learning.py

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import re
from django.db.models import Q, Count, Avg
from django.utils import timezone
from tracker.models import Block, UserWorkPattern, Client
import logging

logger = logging.getLogger(__name__)


class PatternLearningService:
    """
    Learns patterns from user behavior to improve AI classification.
    """
    
    @staticmethod
    def extract_file_patterns(block) -> List[Dict]:
        """
        Extract meaningful patterns from file paths.
        
        Examples:
        - /Users/dan/Documents/Clients/Acme/2024/Tax/ → Client: Acme, Category: Tax Preparation
        - ~/Desktop/QuickBooks Backups/Smith LLC/ → Client: Smith LLC, Category: Accounting
        """
        patterns = []
        file_path = getattr(block, 'file_path', None) or ''
        
        if not file_path:
            return patterns
        
        # Normalize path
        path_lower = file_path.lower()
        path_parts = [p for p in file_path.split('/') if p]
        
        # Pattern 1: Client name in path (look for "Clients" folder)
        if 'clients' in path_lower or 'client' in path_lower:
            try:
                clients_idx = next(i for i, p in enumerate(path_parts) if 'client' in p.lower())
                if clients_idx + 1 < len(path_parts):
                    potential_client = path_parts[clients_idx + 1]
                    patterns.append({
                        'type': 'client_folder',
                        'key': f"clients/{potential_client.lower()}",
                        'client_hint': potential_client,
                        'confidence': 0.85
                    })
            except StopIteration:
                pass
        
        # Pattern 2: Tax-related folders
        tax_keywords = ['tax', 'returns', '1040', '1120', '1065', 'forms']
        if any(kw in path_lower for kw in tax_keywords):
            patterns.append({
                'type': 'category_folder',
                'key': 'tax_folder',
                'category_hint': 'Tax Preparation',
                'confidence': 0.80
            })
        
        # Pattern 3: Accounting folders
        acct_keywords = ['bookkeeping', 'accounting', 'quickbooks', 'reconciliation', 'gl']
        if any(kw in path_lower for kw in acct_keywords):
            patterns.append({
                'type': 'category_folder',
                'key': 'accounting_folder',
                'category_hint': 'Accounting/Bookkeeping',
                'confidence': 0.80
            })
        
        # Pattern 4: Year-based organization (common in CPA firms)
        year_match = re.search(r'/(202[0-9]|201[0-9])/', file_path)
        if year_match:
            year = year_match.group(1)
            patterns.append({
                'type': 'year_folder',
                'key': f'year_{year}',
                'metadata': {'year': year},
                'confidence': 0.60
            })
        
        # Pattern 5: Full path signature (exact match)
        # Use parent folder path (excluding filename)
        if len(path_parts) > 1:
            folder_path = '/'.join(path_parts[:-1])
            patterns.append({
                'type': 'file_path',
                'key': folder_path.lower(),
                'confidence': 0.90
            })
        
        return patterns
    
    @staticmethod
    def extract_time_patterns(block) -> List[Dict]:
        """
        Extract time-of-day and day-of-week patterns.
        
        Examples:
        - Mondays 9-11am = Team meetings
        - Fridays 3-5pm = Partner review
        - Tuesdays/Thursdays = Client X work
        """
        patterns = []
        start = getattr(block, 'start', None)
        
        if not start:
            return patterns
        
        # Time of day
        hour = start.hour
        
        # Morning (6am-12pm)
        if 6 <= hour < 12:
            patterns.append({
                'type': 'time_of_day',
                'key': 'morning',
                'metadata': {'hour_range': [6, 12]},
                'confidence': 0.60
            })
        # Afternoon (12pm-5pm)
        elif 12 <= hour < 17:
            patterns.append({
                'type': 'time_of_day',
                'key': 'afternoon',
                'metadata': {'hour_range': [12, 17]},
                'confidence': 0.60
            })
        # Evening (5pm+)
        elif 17 <= hour < 23:
            patterns.append({
                'type': 'time_of_day',
                'key': 'evening',
                'metadata': {'hour_range': [17, 23]},
                'confidence': 0.60
            })
        
        # Specific hour blocks (for very consistent patterns)
        patterns.append({
            'type': 'time_of_day',
            'key': f'hour_{hour}',
            'metadata': {'specific_hour': hour},
            'confidence': 0.70
        })
        
        # Day of week
        weekday = start.strftime('%A').lower()  # monday, tuesday, etc.
        patterns.append({
            'type': 'day_of_week',
            'key': weekday,
            'metadata': {'day': weekday},
            'confidence': 0.65
        })
        
        return patterns
    
    @staticmethod
    def extract_app_sequence_patterns(blocks: List) -> List[Dict]:
        """
        Extract patterns from application switching sequences.
        
        Examples:
        - Outlook → Excel → QuickBooks = Reconciliation workflow
        - Zoom → Chrome (email) = Post-meeting follow-up
        - UltraTax → Chrome (IRS.gov) = Tax research during prep
        """
        patterns = []
        
        if len(blocks) < 2:
            return patterns
        
        # Look at last 5 blocks to find sequences
        recent = blocks[-5:]
        app_sequence = []
        
        for b in recent:
            app = getattr(b, 'app_name', None)
            if app:
                app_sequence.append(app)
        
        # 2-app sequences
        if len(app_sequence) >= 2:
            for i in range(len(app_sequence) - 1):
                seq_key = f"{app_sequence[i]}→{app_sequence[i+1]}"
                patterns.append({
                    'type': 'app_sequence',
                    'key': seq_key.lower(),
                    'metadata': {'apps': [app_sequence[i], app_sequence[i+1]]},
                    'confidence': 0.70
                })
        
        # 3-app sequences (stronger signal)
        if len(app_sequence) >= 3:
            for i in range(len(app_sequence) - 2):
                seq_key = f"{app_sequence[i]}→{app_sequence[i+1]}→{app_sequence[i+2]}"
                patterns.append({
                    'type': 'app_sequence',
                    'key': seq_key.lower(),
                    'metadata': {'apps': app_sequence[i:i+3]},
                    'confidence': 0.80
                })
        
        return patterns
    
    @staticmethod
    def learn_from_block(block, user):
        """
        Extract and store all patterns from a confirmed/categorized block.
        Called when user confirms AI suggestion or manually categorizes.
        """
        if not block.client and not getattr(block, 'category_hours', None):
            return  # Nothing to learn from
        
        org = getattr(block, 'org', None) or user.groups.first()
        
        # Extract all patterns
        all_patterns = []
        all_patterns.extend(PatternLearningService.extract_file_patterns(block))
        all_patterns.extend(PatternLearningService.extract_time_patterns(block))
        
        # Store patterns
        for pattern_data in all_patterns:
            try:
                pattern, created = UserWorkPattern.objects.get_or_create(
                    user=user,
                    org=org,
                    pattern_type=pattern_data['type'],
                    pattern_key=pattern_data['key'],
                    defaults={
                        'client': block.client,
                        'category': list((getattr(block, 'category_hours', None) or {}).keys())[0] if getattr(block, 'category_hours', None) else '',
                        'confidence_score': pattern_data.get('confidence', 0.5),
                        'metadata': pattern_data.get('metadata', {}),
                    }
                )
                
                if not created:
                    # Update existing pattern
                    pattern.occurrence_count += 1
                    pattern.last_seen = timezone.now()
                    
                    # If pattern still points to same client/category, boost confidence
                    if pattern.client == block.client:
                        pattern.confidence_score = min(0.98, pattern.confidence_score + 0.02)
                    
                    pattern.save()
                    
                logger.debug(f"[PATTERN] Learned: {pattern_data['type']} → {pattern_data['key']}")
                
            except Exception as e:
                logger.warning(f"[PATTERN] Failed to save pattern: {e}")
    
    @staticmethod
    def get_patterns_for_block(block, user) -> List[Tuple[str, str, float]]:
        """
        Retrieve learned patterns that match this block.
        Returns: [(client_name, category, confidence), ...]
        """
        if not user:
            return []
        
        suggestions = []
        
        # Extract patterns from current block
        file_patterns = PatternLearningService.extract_file_patterns(block)
        time_patterns = PatternLearningService.extract_time_patterns(block)
        
        all_patterns = file_patterns + time_patterns
        
        # Look up each pattern in database
        for pattern_data in all_patterns:
            try:
                matches = UserWorkPattern.objects.filter(
                    user=user,
                    pattern_type=pattern_data['type'],
                    pattern_key=pattern_data['key'],
                    confidence_score__gte=0.60  # Only use confident patterns
                ).select_related('client')
                
                for match in matches:
                    client_name = match.client.name if match.client else None
                    category = match.category or None
                    
                    # Combined confidence: learned confidence × pattern strength
                    combined_confidence = match.confidence_score * pattern_data.get('confidence', 0.7)
                    
                    if client_name or category:
                        suggestions.append((client_name, category, combined_confidence))
                        
            except Exception as e:
                logger.warning(f"[PATTERN] Lookup error: {e}")
        
        # Return top 3 by confidence
        suggestions.sort(key=lambda x: x[2], reverse=True)
        return suggestions[:3]
    
    @staticmethod
    def build_pattern_context(user, org) -> str:
        """
        Build a text summary of learned patterns to include in AI prompt.
        Makes the AI aware of user's specific work habits.
        """
        if not user:
            return ""
        
        # Get top patterns by confidence
        top_patterns = UserWorkPattern.objects.filter(
            user=user,
            org=org,
            confidence_score__gte=0.70,
            occurrence_count__gte=3  # Must have seen it at least 3 times
        ).order_by('-confidence_score')[:20]
        
        if not top_patterns.exists():
            return ""
        
        sections = []
        
        # Group by type
        by_type = defaultdict(list)
        for p in top_patterns:
            by_type[p.pattern_type].append(p)
        
        # File path patterns
        if 'file_path' in by_type or 'client_folder' in by_type:
            file_patterns = by_type.get('file_path', []) + by_type.get('client_folder', [])
            if file_patterns:
                lines = ["\n**LEARNED FILE PATTERNS** (this user's folder organization):"]
                for p in file_patterns[:5]:
                    client_name = p.client.name if p.client else "?"
                    lines.append(f"  - Path contains '{p.pattern_key}' → Client: {client_name} ({int(p.confidence_score*100)}% confidence)")
                sections.append('\n'.join(lines))
        
        # Time patterns
        if 'time_of_day' in by_type or 'day_of_week' in by_type:
            time_patterns = by_type.get('time_of_day', []) + by_type.get('day_of_week', [])
            if time_patterns:
                lines = ["\n**LEARNED SCHEDULE PATTERNS** (this user's typical schedule):"]
                for p in time_patterns[:5]:
                    client_name = p.client.name if p.client else p.category or "?"
                    lines.append(f"  - {p.pattern_key.title()} → Usually: {client_name}")
                sections.append('\n'.join(lines))
        
        # App sequences
        if 'app_sequence' in by_type:
            lines = ["\n**LEARNED WORKFLOW PATTERNS** (how this user works):"]
            for p in by_type['app_sequence'][:3]:
                category = p.category or "work"
                lines.append(f"  - App sequence '{p.pattern_key}' → Usually: {category}")
            sections.append('\n'.join(lines))
        
        if sections:
            return '\n'.join(sections)
        
        return ""