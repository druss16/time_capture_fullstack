# tracker/services/ai_prompts.py
"""
Improved AI prompts for cleaner categorization output.
"""

def build_system_prompt(org_context: str, seasonal_context: str, pattern_context: str) -> str:
    """
    Build the system prompt for AI categorization.
    
    Key improvements:
    1. Asks for user-friendly activity summaries (not raw titles)
    2. Standardized category names
    3. Clear confidence thresholds
    4. Better reasoning format
    """
    
    return f'''You are an intelligent time tracking assistant for professional services firms.

=== YOUR TASK ===
Analyze work activity blocks and categorize them for billing purposes.

=== STANDARD CATEGORIES ===
Use ONLY these category names (exactly as written):
• Development - coding, debugging, code review, DevOps
• Research - web research, documentation reading, AI assistants (Claude, ChatGPT)
• Meetings - video calls, phone calls, in-person meetings
• Communication - email, Slack, Teams chat (not calls)
• Tax Prep - tax software (UltraTax, Lacerte, Drake), IRS forms
• Bookkeeping - QuickBooks, Xero, reconciliations, journal entries
• Admin - proposals, contracts, internal docs, planning
• Design - Figma, Canva, creative work
• Data Entry - spreadsheets, data input
• Idle - screensaver, lock screen, no activity

=== OUTPUT FORMAT ===
For each block, return:
{{
  "client": "Client Name" or null,
  "project": "Project Name" or null,
  "activity": "Brief 3-5 word description of work done",
  "categories": {{"Category": hours}},
  "confidence": 0.0-1.0,
  "needs_review": true/false,
  "reasoning": "Why you categorized it this way (1 sentence)"
}}

=== ACTIVITY DESCRIPTIONS ===
Write activity descriptions as if explaining to a client what you did:
✅ GOOD: "Backend API development", "Client email correspondence", "Tax return review"
❌ BAD: "views.py - Visual Studio Code", "Inbox (3) - Gmail", "localhost:5173"

=== CONFIDENCE GUIDELINES ===
• 0.95+ → Tax software, accounting software, video calls (obvious)
• 0.85-0.94 → Code editors, specific client work, clear patterns
• 0.70-0.84 → Browser research, general admin tasks
• 0.50-0.69 → Ambiguous activity, needs review
• <0.50 → Unknown, definitely needs review

=== CLIENT DETECTION ===
• Look for client names in: file paths, URLs, window titles, project folders
• If a learned pattern matches, trust it (high confidence)
• "Unknown" is better than guessing wrong

=== SPECIAL RULES ===
1. Idle/screensaver → Always category "Idle", never assign to client
2. Multiple activities in one block → Split hours proportionally
3. Internal tools (Slack, email) → Only assign to client if clear context
4. AI tools (Claude, ChatGPT) → Usually "Research" unless context says otherwise

{org_context}

{seasonal_context}

{pattern_context}
'''


def build_user_prompt(blocks: list) -> str:
    """Build the user prompt with block data."""
    
    blocks_json = "[\n"
    for b in blocks:
        blocks_json += f'''  {{
    "id": "{b['id']}",
    "app": "{b.get('app_name', '')}",
    "title": "{b.get('window_title', '') or b.get('title', '')}",
    "url": "{b.get('url', '')}",
    "file_path": "{b.get('file_path', '')}",
    "minutes": {b.get('minutes', 0)},
    "learned_patterns": {b.get('learned_patterns', [])}
  }},
'''
    blocks_json = blocks_json.rstrip(',\n') + "\n]"
    
    return f'''Categorize these {len(blocks)} activity blocks:

{blocks_json}

Return a JSON array with one object per block, in the same order.'''


# =============================================================================
# POST-PROCESSING
# =============================================================================
def clean_ai_response(ai_suggestions: list, blocks: list) -> list:
    """
    Post-process AI suggestions for cleaner display.
    
    - Ensures standard category names
    - Cleans up activity descriptions
    - Adds display-friendly fields
    """
    from tracker.utils.display_names import (
        clean_category, 
        format_duration,
        clean_app_name
    )
    
    cleaned = []
    
    for i, suggestion in enumerate(ai_suggestions):
        block = blocks[i] if i < len(blocks) else {}
        
        # Clean categories
        raw_categories = suggestion.get('categories', {})
        clean_categories = {}
        for cat, hours in raw_categories.items():
            clean_cat = clean_category(cat)
            clean_categories[clean_cat] = round(hours, 2)
        
        # Get primary category (highest hours)
        primary_category = max(clean_categories.keys(), key=lambda k: clean_categories[k]) if clean_categories else "Uncategorized"
        
        # Build activity description
        activity = suggestion.get('activity', '')
        if not activity:
            # Fallback: generate from app/title
            activity = _generate_activity_description(block, primary_category)
        
        # Confidence display
        confidence = suggestion.get('confidence', 0)
        confidence_label = _confidence_label(confidence)
        
        cleaned.append({
            # Core data
            'client': suggestion.get('client'),
            'project': suggestion.get('project'),
            'categories': clean_categories,
            'confidence': confidence,
            'needs_review': suggestion.get('needs_review', confidence < 0.7),
            'reasoning': suggestion.get('reasoning', ''),
            
            # Display-friendly additions
            'activity': activity,
            'primary_category': primary_category,
            'confidence_label': confidence_label,
            'duration': format_duration(block.get('minutes', 0)),
        })
    
    return cleaned


def _generate_activity_description(block: dict, category: str) -> str:
    """Generate activity description from block data if AI didn't provide one."""
    app = block.get('app_name', '')
    title = block.get('window_title', '') or block.get('title', '')
    url = block.get('url', '')
    
    # Category-based defaults
    defaults = {
        'Development': 'Software development',
        'Research': 'Research & documentation',
        'Meetings': 'Video/phone call',
        'Communication': 'Email & messaging',
        'Tax Prep': 'Tax return preparation',
        'Bookkeeping': 'Accounting & bookkeeping',
        'Admin': 'Administrative work',
        'Idle': 'Away from computer',
    }
    
    if category in defaults:
        return defaults[category]
    
    # Try to extract from app
    if 'code' in app.lower() or 'studio' in app.lower():
        return 'Code development'
    if 'chrome' in app.lower() or 'safari' in app.lower():
        if 'claude' in url.lower() or 'chatgpt' in url.lower():
            return 'AI-assisted research'
        return 'Web browsing'
    
    return 'Work activity'


def _confidence_label(confidence: float) -> str:
    """Convert confidence score to user-friendly label."""
    if confidence >= 0.95:
        return "Very High"
    if confidence >= 0.85:
        return "High"
    if confidence >= 0.70:
        return "Medium"
    if confidence >= 0.50:
        return "Low"
    return "Very Low"