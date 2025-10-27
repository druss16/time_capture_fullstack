"""
AI-Powered Timecard Service - ADAPTED for Dan's existing models
Integrates with existing Block, Client, Project, Task models
"""
import re
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from urllib.parse import urlparse
import openai
from dataclasses import dataclass, asdict


@dataclass
class ClientActivity:
    """Aggregated activity for a specific client"""
    client_name: str
    total_hours: float
    blocks: List[Dict]
    category_breakdown: Dict[str, float]  # category -> hours
    

@dataclass
class TimecardEntry:
    """Final timecard entry ready for CPA approval"""
    date: str
    client_name: str
    project_name: Optional[str]
    total_hours: float
    category_breakdown: Dict[str, float]  # category -> hours
    activities_summary: List[str]
    needs_review: bool = False
    confidence_score: float = 1.0
    block_ids: List[int] = None  # Link back to source blocks


class ClientExtractor:
    """Extract client names from various sources using AI and pattern matching"""
    
    def __init__(self, openai_api_key: str):
        openai.api_key = openai_api_key
        self.known_clients = {}  # Cache for learned client patterns
        
    def extract_from_url(self, url: str) -> Optional[str]:
        """Extract client name from URL"""
        if not url:
            return None
            
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            
            # Extract company name from domain
            # predictoredge.com -> Predictor Edge
            name = domain.split('.')[0]
            
            # Convert to title case with spaces
            if name:
                words = re.findall('[A-Z][a-z]*|[a-z]+', name.title())
                return ' '.join(words) if words else name.title()
                
        except Exception:
            return None
            
    def extract_from_window_title(self, title: str) -> Optional[str]:
        """Extract client name from window title using patterns"""
        # Common patterns in window titles
        patterns = [
            r'(?:-)?\s*([A-Z][a-zA-Z\s&]+(?:Inc|LLC|Corp|Company|Co|Ltd)?)\s*(?:-|–)',
            r'\(([a-zA-Z0-9-]+\.com)\)',  # (domain.com)
            r'([A-Z][a-zA-Z\s]+)\s*(?:Dashboard|Portal|Admin)',
            r'Project:\s*([A-Z][a-zA-Z\s]+)',
            r'Client:\s*([A-Z][a-zA-Z\s]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                return match.group(1).strip()
                
        return None
        
    async def extract_with_ai(self, block_data: Dict) -> Tuple[str, float]:
        """
        Use OpenAI to intelligently extract client name from a Block
        Returns: (client_name, confidence_score)
        """
        prompt = f"""You are a CPA time tracking assistant. Extract the client/company name from this activity:

Title: {block_data.get('title', '')}
Window Title: {block_data.get('window_title', '')}
URL: {block_data.get('url', 'N/A')}
File Path: {block_data.get('file_path', 'N/A')}

Rules:
1. Extract the most likely client/company name
2. Return "Unknown" if truly unclear
3. For personal tools (Gmail, Slack, etc.), try to infer client from context
4. Return confidence score 0-1

Return JSON: {{"client": "Client Name", "confidence": 0.95}}"""

        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You extract client names from activity data with high accuracy."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=100
            )
            
            result = json.loads(response.choices[0].message.content)
            return result.get('client', 'Unknown'), result.get('confidence', 0.5)
            
        except Exception as e:
            print(f"AI extraction failed: {e}")
            return 'Unknown', 0.0
            
    async def extract_client(self, block_data: Dict) -> Tuple[str, float]:
        """
        Multi-strategy client extraction from Block data
        Returns: (client_name, confidence_score)
        """
        # Strategy 1: Try URL extraction (highest confidence)
        if block_data.get('url'):
            client = self.extract_from_url(block_data['url'])
            if client:
                return client, 0.95
                
        # Strategy 2: Try pattern matching on window title or title
        for title_field in ['window_title', 'title']:
            if block_data.get(title_field):
                client = self.extract_from_window_title(block_data[title_field])
                if client:
                    return client, 0.85
            
        # Strategy 3: Use AI for complex cases
        return await self.extract_with_ai(block_data)


class ActivityClassifier:
    """Classify activities into billable categories"""
    
    # Map common app names to categories
    CATEGORY_MAP = {
        # Development
        'Visual Studio Code': 'Development',
        'PyCharm': 'Development',
        'Cursor': 'Development',
        'Terminal': 'Development',
        'iTerm': 'Development',
        'Xcode': 'Development',
        
        # Communication
        'Gmail': 'Email & Communication',
        'Outlook': 'Email & Communication',
        'Mail': 'Email & Communication',
        'Slack': 'Email & Communication',
        'Zoom': 'Meetings',
        'Google Meet': 'Meetings',
        'Microsoft Teams': 'Meetings',
        
        # Documentation
        'Google Docs': 'Documentation',
        'Microsoft Word': 'Documentation',
        'Pages': 'Documentation',
        'Notion': 'Documentation',
        
        # Spreadsheets & Analysis
        'Excel': 'Analysis & Reporting',
        'Google Sheets': 'Analysis & Reporting',
        'Numbers': 'Analysis & Reporting',
        
        # Research
        'Chrome': 'Research',
        'Safari': 'Research',
        'Firefox': 'Research',
        
        # AI Tools
        'Claude': 'AI-Assisted Work',
        'ChatGPT': 'AI-Assisted Work',
    }
    
    def classify_from_title(self, title: str) -> Optional[str]:
        """Try to classify from title content"""
        title_lower = title.lower()
        
        # Common patterns
        if any(x in title_lower for x in ['email', 'gmail', 'inbox', 'message']):
            return 'Email & Communication'
        if any(x in title_lower for x in ['.py', '.js', '.java', 'code', 'github']):
            return 'Development'
        if any(x in title_lower for x in ['doc', 'document', 'report']):
            return 'Documentation'
        if any(x in title_lower for x in ['sheet', 'excel', 'csv']):
            return 'Analysis & Reporting'
        if any(x in title_lower for x in ['meeting', 'zoom', 'call']):
            return 'Meetings'
            
        return None
    
    def classify(self, block_data: Dict) -> str:
        """
        Classify block into billable category
        Uses title as primary signal since we don't have app_name in Block
        """
        title = block_data.get('title', '') or block_data.get('window_title', '')
        
        # Try direct title-based classification first
        category = self.classify_from_title(title)
        if category:
            return category
        
        # Try URL-based classification
        url = block_data.get('url', '')
        if url:
            if any(x in url.lower() for x in ['github.com', 'gitlab.com']):
                return 'Development'
            if any(x in url.lower() for x in ['docs.google.com', 'office.com']):
                return 'Documentation'
            if 'mail.google.com' in url.lower():
                return 'Email & Communication'
        
        # Try file path based classification
        file_path = block_data.get('file_path', '')
        if file_path:
            ext = file_path.split('.')[-1].lower() if '.' in file_path else ''
            if ext in ['py', 'js', 'java', 'cpp', 'rb', 'go']:
                return 'Development'
            if ext in ['doc', 'docx', 'txt', 'md']:
                return 'Documentation'
            if ext in ['xls', 'xlsx', 'csv']:
                return 'Analysis & Reporting'
        
        # Fallback
        return 'Other'


class TimeAggregator:
    """Aggregate blocks by client and category"""
    
    def __init__(self):
        self.client_extractor = None
        self.classifier = ActivityClassifier()
        
    async def aggregate_by_client(self, blocks: List[Dict],
                                  client_extractor: ClientExtractor,
                                  existing_clients: Dict[str, str] = None) -> List[ClientActivity]:
        """
        Aggregate all blocks by client
        blocks: List of dicts with Block data (id, start, end, title, url, etc.)
        existing_clients: Dict mapping block_id -> client_name (from existing assignments)
        """
        self.client_extractor = client_extractor
        existing_clients = existing_clients or {}
        
        # Group by client
        client_data = defaultdict(lambda: {
            'total_seconds': 0,
            'blocks': [],
            'categories': defaultdict(int),
            'block_ids': []
        })
        
        for block in blocks:
            # Use existing client assignment if available
            if block['id'] in existing_clients:
                client_name = existing_clients[block['id']]
                confidence = 1.0
            else:
                # Extract client name using AI
                client_name, confidence = await client_extractor.extract_client(block)
            
            # Classify activity
            category = self.classifier.classify(block)
            
            # Calculate duration
            duration_seconds = block.get('minutes', 0) * 60
            
            # Aggregate
            client_data[client_name]['total_seconds'] += duration_seconds
            client_data[client_name]['blocks'].append({
                'id': block['id'],
                'start': block['start'],
                'end': block['end'],
                'title': block['title'],
                'window_title': block.get('window_title', ''),
                'url': block.get('url', ''),
                'category': category,
                'duration_seconds': duration_seconds,
                'confidence': confidence
            })
            client_data[client_name]['categories'][category] += duration_seconds
            client_data[client_name]['block_ids'].append(block['id'])
            
        # Convert to ClientActivity objects
        result = []
        for client_name, data in client_data.items():
            category_breakdown = {
                cat: seconds / 3600  # Convert to hours
                for cat, seconds in data['categories'].items()
            }
            
            result.append(ClientActivity(
                client_name=client_name,
                total_hours=data['total_seconds'] / 3600,
                blocks=data['blocks'],
                category_breakdown=category_breakdown
            ))
            
        # Sort by total hours (descending)
        result.sort(key=lambda x: x.total_hours, reverse=True)
        return result


class TimecardGenerator:
    """Generate CPA-ready timecards from Blocks"""
    
    def __init__(self, openai_api_key: str):
        self.client_extractor = ClientExtractor(openai_api_key)
        self.aggregator = TimeAggregator()
        
    async def generate_timecard(self, blocks: List[Dict],
                               date: str,
                               existing_assignments: Dict[int, Dict] = None) -> List[TimecardEntry]:
        """
        Generate a complete timecard for a specific date
        
        blocks: List of Block data dicts
        date: Date string (YYYY-MM-DD)
        existing_assignments: Dict mapping block_id -> {'client': name, 'project': name, 'task': name}
        """
        # Extract existing client assignments
        existing_clients = {}
        if existing_assignments:
            for block_id, assignment in existing_assignments.items():
                if assignment.get('client'):
                    existing_clients[block_id] = assignment['client']
        
        # Aggregate by client
        client_activities = await self.aggregator.aggregate_by_client(
            blocks, self.client_extractor, existing_clients
        )
        
        # Generate timecard entries
        timecard = []
        for client_activity in client_activities:
            # Calculate average confidence
            confidences = [b['confidence'] for b in client_activity.blocks]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            # Generate activity summary using AI
            summary = await self._generate_activity_summary(client_activity)
            
            # Determine if needs review
            needs_review = (
                avg_confidence < 0.7 or 
                client_activity.client_name == 'Unknown' or
                client_activity.total_hours < 0.1  # Less than 6 minutes
            )
            
            # Extract block IDs
            block_ids = [b['id'] for b in client_activity.blocks]
            
            entry = TimecardEntry(
                date=date,
                client_name=client_activity.client_name,
                project_name=None,  # Could extract from blocks if assigned
                total_hours=round(client_activity.total_hours, 2),
                category_breakdown={
                    k: round(v, 2) 
                    for k, v in client_activity.category_breakdown.items()
                },
                activities_summary=summary,
                needs_review=needs_review,
                confidence_score=round(avg_confidence, 2),
                block_ids=block_ids
            )
            
            timecard.append(entry)
            
        return timecard
        
    async def _generate_activity_summary(self, client_activity: ClientActivity) -> List[str]:
        """Use AI to generate human-readable activity summaries"""
        # Group blocks by category
        by_category = defaultdict(list)
        for block in client_activity.blocks:
            by_category[block['category']].append(block)
            
        summaries = []
        for category, blocks in by_category.items():
            hours = sum(b['duration_seconds'] for b in blocks) / 3600
            
            # Sample titles for context
            samples = [b['title'] for b in blocks[:3]]
            
            prompt = f"""Summarize this work activity in 1 short phrase (max 8 words):

Category: {category}
Duration: {hours:.1f} hours
Sample activities: {samples}

Example good summaries:
- "Client onboarding documentation"
- "Tax return preparation and review"
- "Financial statement analysis"
- "Email correspondence with client"

Return only the summary phrase, nothing else."""

            try:
                response = await openai.ChatCompletion.acreate(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=20
                )
                
                summary = response.choices[0].message.content.strip()
                summaries.append(f"{summary} ({hours:.1f}h)")
                
            except Exception:
                # Fallback to simple summary
                summaries.append(f"{category} ({hours:.1f}h)")
                
        return summaries
        
    def format_timecard_for_display(self, timecard: List[TimecardEntry]) -> str:
        """Format timecard for human-readable display"""
        output = []
        output.append("=" * 80)
        output.append(f"DAILY TIMECARD - {timecard[0].date if timecard else 'N/A'}")
        output.append("=" * 80)
        output.append("")
        
        total_hours = 0
        for entry in timecard:
            flag = " ⚠️  NEEDS REVIEW" if entry.needs_review else ""
            output.append(f"CLIENT: {entry.client_name}{flag}")
            if entry.project_name:
                output.append(f"PROJECT: {entry.project_name}")
            output.append(f"Total Time: {entry.total_hours:.2f} hours")
            output.append(f"Confidence: {entry.confidence_score * 100:.0f}%")
            output.append(f"Block IDs: {', '.join(map(str, entry.block_ids or []))}")
            output.append("")
            
            output.append("Activities:")
            for summary in entry.activities_summary:
                output.append(f"  • {summary}")
            output.append("")
            
            output.append("Category Breakdown:")
            for category, hours in entry.category_breakdown.items():
                output.append(f"  • {category}: {hours:.2f}h")
            
            output.append("-" * 80)
            output.append("")
            
            total_hours += entry.total_hours
            
        output.append(f"TOTAL BILLABLE TIME: {total_hours:.2f} hours")
        output.append("=" * 80)
        
        return "\n".join(output)