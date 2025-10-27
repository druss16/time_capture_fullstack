# fix_zero_duration_blocks.py
# Run this in Django shell to fix existing blocks with 0 minutes

from tracker.models import Block
from datetime import timedelta, date

# Configuration
MIN_BLOCK_DURATION = 6  # minutes
BLOCK_GRANULARITY = 6   # round to 6-min increments

def _round_up_minutes(n: int, granularity: int) -> int:
    """Round up to nearest granularity"""
    return n if n % granularity == 0 else n + (granularity - (n % granularity))

def fix_zero_duration_blocks():
    """Fix all blocks with 0 minutes duration"""
    
    # Get all blocks with 0 minutes
    zero_blocks = Block.objects.filter(minutes=0)
    count = zero_blocks.count()
    
    if count == 0:
        print("✅ No zero-duration blocks found!")
        return
    
    print(f"🔧 Fixing {count} zero-duration blocks...")
    
    fixed = 0
    for block in zero_blocks:
        # Calculate actual duration
        if block.start and block.end:
            actual_duration = int((block.end - block.start).total_seconds() // 60)
        else:
            actual_duration = 0
        
        # Apply minimum duration
        dur = max(MIN_BLOCK_DURATION, _round_up_minutes(actual_duration, BLOCK_GRANULARITY))
        
        # Update block
        block.minutes = dur
        
        # Extend end time if needed
        if actual_duration < dur:
            block.end = block.start + timedelta(minutes=dur)
        
        block.save()
        fixed += 1
        
        if fixed % 10 == 0:
            print(f"  Fixed {fixed}/{count} blocks...")
    
    print(f"✅ Fixed {fixed} blocks!")
    print(f"   All blocks now have minimum {MIN_BLOCK_DURATION} minutes duration")
    
    # Show summary
    remaining = Block.objects.filter(minutes=0).count()
    if remaining > 0:
        print(f"⚠️  Warning: {remaining} blocks still have 0 minutes")
    else:
        print("✅ All blocks now have valid durations!")

# Run it
if __name__ == "__main__":
    fix_zero_duration_blocks()


# ====================
# HOW TO RUN THIS:
# ====================
# 
# Option 1: Django shell
# -----------------------
# docker exec -it time_api python manage.py shell
# >>> exec(open('fix_zero_duration_blocks.py').read())
#
# Option 2: Direct execution
# --------------------------
# docker exec -it time_api python manage.py shell < fix_zero_duration_blocks.py
#
# Option 3: Copy-paste into shell
# --------------------------------
# docker exec -it time_api python manage.py shell
# >>> from tracker.models import Block
# >>> from datetime import timedelta
# >>> for block in Block.objects.filter(minutes=0):
# ...     block.minutes = 6
# ...     block.end = block.start + timedelta(minutes=6)
# ...     block.save()
# >>> print("Done!")