#!/usr/bin/env python
"""
One-time cleanup script to consolidate duplicate uncategorized blocks.

Run this AFTER deploying the fixed compaction.py to clean up existing duplicates.

Usage:
    python manage.py shell < cleanup_duplicate_blocks.py
    
Or in Django shell:
    exec(open('cleanup_duplicate_blocks.py').read())
"""

import os
import sys
import django

# Setup Django if not already
if not django.apps.apps.ready:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from tracker.models import Block, RawEvent, OrganizationMembership

User = get_user_model()

MERGE_GAP_SECONDS = 300  # 5 minutes


def block_signature(block):
    """Create a signature tuple for matching blocks."""
    return (
        (block.app_name or "").lower().strip(),
        (block.bundle_id or "").lower().strip(),
        (block.window_title or "").lower().strip(),
    )


def consolidate_user_blocks(user, days_back=7):
    """Consolidate duplicate uncategorized blocks for a user."""
    
    membership = OrganizationMembership.objects.filter(user=user).first()
    org = membership.organization if membership else None
    
    today = timezone.localdate()
    total_merged = 0
    total_deleted = 0
    
    for i in range(days_back):
        day = today - timedelta(days=i)
        
        # Get all uncategorized blocks for this day
        blocks = list(Block.objects.filter(
            user=user,
            day=day,
            is_categorized=False,
        ).order_by('start'))
        
        if len(blocks) < 2:
            continue
        
        print(f"\n[{day}] Found {len(blocks)} uncategorized blocks")
        
        # Group by signature
        by_sig = {}
        for b in blocks:
            sig = block_signature(b)
            if sig not in by_sig:
                by_sig[sig] = []
            by_sig[sig].append(b)
        
        # Report duplicates
        for sig, sig_blocks in by_sig.items():
            if len(sig_blocks) > 1:
                app_name = sig[0] or "Unknown"
                print(f"  → {len(sig_blocks)} blocks with same signature: {app_name[:40]}")
        
        # Merge duplicates
        blocks_to_delete = []
        
        with transaction.atomic():
            for sig, sig_blocks in by_sig.items():
                if len(sig_blocks) < 2:
                    continue
                
                sig_blocks.sort(key=lambda b: b.start)
                
                i = 0
                while i < len(sig_blocks) - 1:
                    current = sig_blocks[i]
                    next_block = sig_blocks[i + 1]
                    
                    gap_seconds = (next_block.start - current.end).total_seconds()
                    
                    # Merge if gap < 5 minutes OR overlapping
                    if gap_seconds <= MERGE_GAP_SECONDS:
                        try:
                            current_locked = Block.objects.select_for_update().get(id=current.id)
                            next_locked = Block.objects.select_for_update().get(id=next_block.id)
                            
                            if current_locked.is_categorized or next_locked.is_categorized:
                                i += 1
                                continue
                            
                            # Merge
                            new_start = min(current_locked.start, next_locked.start)
                            new_end = max(current_locked.end, next_locked.end)
                            new_minutes = int((new_end - new_start).total_seconds() / 60)
                            
                            current_locked.start = new_start
                            current_locked.end = new_end
                            current_locked.minutes = new_minutes
                            current_locked.save(update_fields=['start', 'end', 'minutes'])
                            
                            # Move events
                            RawEvent.objects.filter(block=next_locked).update(block=current_locked)
                            
                            blocks_to_delete.append(next_locked.id)
                            
                            # Update local refs
                            current.start = new_start
                            current.end = new_end
                            
                            sig_blocks.pop(i + 1)
                            total_merged += 1
                            
                            print(f"    ✅ Merged block {next_locked.id} → {current_locked.id} (now {new_minutes} min)")
                            
                        except Block.DoesNotExist:
                            i += 1
                    else:
                        i += 1
            
            if blocks_to_delete:
                Block.objects.filter(id__in=blocks_to_delete).delete()
                total_deleted += len(blocks_to_delete)
    
    return total_merged, total_deleted


def main():
    print("=" * 60)
    print("DUPLICATE BLOCK CLEANUP")
    print("=" * 60)
    
    # Get username from args or prompt
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter username to clean up (or 'all' for all users): ").strip()
    
    days_back = 7
    if len(sys.argv) > 2:
        days_back = int(sys.argv[2])
    
    if username.lower() == 'all':
        users = User.objects.filter(is_active=True)
        print(f"\nProcessing {users.count()} active users...")
    else:
        try:
            users = [User.objects.get(username=username)]
        except User.DoesNotExist:
            print(f"❌ User not found: {username}")
            return
    
    grand_total_merged = 0
    grand_total_deleted = 0
    
    for user in users:
        print(f"\n{'=' * 40}")
        print(f"User: {user.username}")
        print("=" * 40)
        
        merged, deleted = consolidate_user_blocks(user, days_back)
        grand_total_merged += merged
        grand_total_deleted += deleted
        
        if merged > 0:
            print(f"\n✅ Merged {merged} blocks, deleted {deleted} duplicates")
        else:
            print(f"\n✓ No duplicates found")
    
    print("\n" + "=" * 60)
    print(f"TOTAL: Merged {grand_total_merged} blocks, deleted {grand_total_deleted} duplicates")
    print("=" * 60)


if __name__ == '__main__':
    main()