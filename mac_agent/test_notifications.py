#!/usr/bin/env python3
"""
Test script for TimeTracker notifications.

Run this on your Mac to verify notifications are working:
    python3 test_notifications.py

You should see several test notifications appear in Notification Center.
"""

import time
import sys

def main():
    print("=" * 60)
    print("TimeTracker Notification Test")
    print("=" * 60)
    print()
    
    # Import the notification module
    try:
        from notifications import (
            create_notification_system,
            NotificationConfig
        )
        print("✅ Notification module imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import notifications module: {e}")
        print("\nMake sure notifications.py is in the same directory.")
        sys.exit(1)
    
    # Check macOS notification availability
    try:
        from UserNotifications import UNUserNotificationCenter
        print("✅ macOS UserNotifications framework available")
    except ImportError:
        print("❌ macOS UserNotifications not available")
        print("\nThis requires PyObjC. Install with:")
        print("    pip install pyobjc-framework-UserNotifications")
        sys.exit(1)
    
    # Create configuration
    config = NotificationConfig(
        enabled=True,
        min_seconds_between_notifications=2,  # Short interval for testing
        respect_quiet_hours=False,  # Ignore quiet hours for testing
    )
    
    # Track actions
    actions_received = []
    
    def on_confirm(client_id, client_name):
        print(f"\n📥 CONFIRM received: {client_name} (ID: {client_id})")
        actions_received.append(("confirm", client_id, client_name))
    
    def on_switch():
        print("\n📥 SWITCH requested")
        actions_received.append(("switch", None, None))
    
    def on_snooze(client_id, minutes):
        print(f"\n📥 SNOOZE received: client {client_id} for {minutes} minutes")
        actions_received.append(("snooze", client_id, minutes))
    
    # Create notification manager
    print("\nInitializing notification system...")
    manager = create_notification_system(
        on_confirm=on_confirm,
        on_switch=on_switch,
        on_snooze=on_snooze,
        config=config
    )
    
    if not manager.ready:
        print("❌ Notification system not ready")
        print("\nPossible reasons:")
        print("  • Notifications not authorized for this app")
        print("  • Running in a context without notification permissions")
        print("\nTry running from Terminal.app and allow notifications when prompted.")
        sys.exit(1)
    
    print("✅ Notification system ready")
    print()
    print("-" * 60)
    print("SENDING TEST NOTIFICATIONS")
    print("-" * 60)
    print()
    print("Watch your Notification Center for these notifications.")
    print("You can interact with them to test the action buttons.")
    print()
    
    # Set a test client
    manager.set_current_client(1, "Acme Corporation")
    
    # Test 1: Client suggestion
    print("1️⃣  Sending CLIENT SUGGESTION notification...")
    result = manager.notify_client_suggestion(
        client_id=2,
        client_name="Beta Industries",
        confidence=0.72,
        reason="You opened their QuickBooks file"
    )
    print(f"   {'✅ Sent' if result else '❌ Failed'}")
    time.sleep(3)
    
    # Test 2: Duration reminder
    print("\n2️⃣  Sending DURATION REMINDER notification...")
    result = manager.notify_duration_reminder(force=True)
    print(f"   {'✅ Sent' if result else '❌ Failed'}")
    time.sleep(3)
    
    # Test 3: Idle return
    print("\n3️⃣  Sending IDLE RETURN notification...")
    result = manager.notify_idle_return(idle_duration_seconds=1800)  # 30 min idle
    print(f"   {'✅ Sent' if result else '❌ Failed'}")
    time.sleep(3)
    
    # Test 4: Context change
    print("\n4️⃣  Sending CONTEXT CHANGE notification...")
    result = manager.notify_context_change(
        suggested_client_id=3,
        suggested_client_name="Gamma Holdings",
        confidence=0.68,
        reason="Detected activity in Gamma Holdings folder"
    )
    print(f"   {'✅ Sent' if result else '❌ Failed'}")
    time.sleep(3)
    
    # Test 5: No client reminder
    print("\n5️⃣  Sending NO CLIENT reminder...")
    manager.set_current_client(None, None)  # Clear client
    result = manager.notify_no_client(force=True)
    print(f"   {'✅ Sent' if result else '❌ Failed'}")
    
    print()
    print("-" * 60)
    print("TEST COMPLETE")
    print("-" * 60)
    print()
    print("You should have received 5 notifications.")
    print()
    print("Try clicking the action buttons on the notifications to test:")
    print("  • 'Yes, correct' - Confirms the current/suggested client")
    print("  • 'Switch Client' - Triggers client picker")
    print("  • 'Snooze 30m' - Snoozes suggestions for that client")
    print()
    print("Waiting for notification interactions (30 seconds)...")
    print("Press Ctrl+C to exit early.")
    print()
    
    try:
        for i in range(30):
            time.sleep(1)
            if actions_received:
                break
        
        if actions_received:
            print(f"\n✅ Received {len(actions_received)} action(s):")
            for action, client_id, data in actions_received:
                print(f"   • {action}: client_id={client_id}, data={data}")
        else:
            print("\nNo actions received (notifications may have been dismissed)")
            
    except KeyboardInterrupt:
        print("\n\nTest interrupted.")
    
    print("\n✅ Notification test complete!")


if __name__ == "__main__":
    main()