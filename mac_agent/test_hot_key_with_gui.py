#!/usr/bin/env python3
"""
Test hotkey in a rumps-like environment.
This mimics how main.py runs with a menu bar app.
"""

import rumps
import threading
from AppKit import NSEvent
from PyObjCTools import AppHelper

# Mask constants
NSKeyDownMask = 1 << 10
NSControlKeyMask = 1 << 18  
NSAlternateKeyMask = 1 << 19
KEY_T = 17

class TestMenuBarApp(rumps.App):
    def __init__(self):
        super().__init__("🕐 Test", quit_button=None)
        self.menu = [
            rumps.MenuItem("Open Picker (or press ⌃⌥T)", callback=self.on_picker),
            None,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]
        
        # Setup hotkey monitors
        self._setup_hotkey()
    
    def _setup_hotkey(self):
        """Setup both global and local hotkey monitors."""
        
        def handle_hotkey(event):
            try:
                keycode = event.keyCode()
                flags = event.modifierFlags()
                
                ctrl = (flags & NSControlKeyMask) != 0
                option = (flags & NSAlternateKeyMask) != 0
                
                if keycode == KEY_T and ctrl and option:
                    print("[HOTKEY] ⌃⌥T detected!")
                    # Must use callAfter to safely call from event handler
                    AppHelper.callAfter(self.on_picker, None)
                    return None  # Consume event
                    
            except Exception as e:
                print(f"[HOTKEY] Error: {e}")
            return event
        
        # Global = other apps focused
        self._global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, handle_hotkey
        )
        
        # Local = this app focused
        self._local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSKeyDownMask, handle_hotkey
        )
        
        if self._global_monitor:
            print("[HOTKEY] ✅ Global monitor active")
        else:
            print("[HOTKEY] ❌ Global monitor failed - check Accessibility permissions")
            
        if self._local_monitor:
            print("[HOTKEY] ✅ Local monitor active")
        else:
            print("[HOTKEY] ❌ Local monitor failed")
    
    def on_picker(self, sender):
        """Called when hotkey pressed or menu clicked."""
        print("\n" + "=" * 40)
        print("🎯 PICKER OPENED!")
        print("=" * 40 + "\n")
        
        # Show a notification as visual feedback
        rumps.notification(
            title="TimeTracker",
            subtitle="Hotkey worked!",
            message="Ctrl+Option+T triggered successfully"
        )


if __name__ == "__main__":
    print("=" * 50)
    print("HOTKEY TEST WITH MENU BAR APP")
    print("=" * 50)
    print()
    print("Press Ctrl+Option+T anywhere to test.")
    print("You should see 'PICKER OPENED!' in the console.")
    print()
    print("Click the 🕐 menu bar icon to quit.")
    print()
    
    app = TestMenuBarApp()
    app.run()