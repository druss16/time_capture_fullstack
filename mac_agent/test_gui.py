#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker GUI Test Script
Run this to test the GUI standalone before integrating with main.py
Usage: python3 test_gui.py
"""
import sys
import time
import threading
import signal
try:
    from timetracker_gui import run_gui_app, GUI_AVAILABLE
    from AppKit import NSApp
except Exception as e:
    print(f"❌ Error importing GUI: {e}")
    print("\n💡 Install dependencies:")
    print(" pip3 install --user pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz")
    sys.exit(1)
def test_confirmed(client_id, client_name, prompt_data):
    """Callback when user confirms a client"""
    print(f"✅ TEST: User confirmed '{client_name}' (ID: {client_id})")
    print(f" Confidence: {prompt_data.get('confidence', 0):.2%}")
    print(f" Prompt ID: {prompt_data.get('prompt_id', 'N/A')}")
def test_rejected(prompt_data):
    """Callback when user rejects a client"""
    print(f"❌ TEST: User rejected suggestion")
    print(f" Client: {prompt_data.get('client_name', 'Unknown')}")
    print(f" Confidence: {prompt_data.get('confidence', 0):.2%}")
def test_get_today_time():
    """Mock function to return today's time data"""
    print("📊 TEST: Fetching today's time data...")
    return [
        {"client": "Test Client A", "hours": 3.5},
        {"client": "Test Client B", "hours": 2.25},
        {"client": "Test Client C", "hours": 1.0},
        {"client": "Test Client D", "hours": 0.75},
    ]
def show_test_prompts(menu_bar):
    """Show test prompts after delays"""
    print("\n⏱ Waiting 3 seconds before showing first test prompt...")
    time.sleep(3)
   
    # Test 1: High confidence prompt
    print("\n🔔 TEST 1: Showing high confidence prompt (Acme Corp, 85%)")
    menu_bar.show_client_prompt(
        client_id=1,
        client_name="Acme Corp",
        confidence=0.85,
        prompt_data={
            "prompt_id": "test-001",
            "client_id": 1,
            "client_name": "Acme Corp",
            "confidence": 0.85,
            "hostname": "test-machine",
            "os_user": "test-user",
        }
    )
   
    # Wait for user interaction
    time.sleep(10)
   
    # Test 2: Medium confidence prompt
    print("\n🔔 TEST 2: Showing medium confidence prompt (Beta Industries, 62%)")
    menu_bar.show_client_prompt(
        client_id=2,
        client_name="Beta Industries",
        confidence=0.62,
        prompt_data={
            "prompt_id": "test-002",
            "client_id": 2,
            "client_name": "Beta Industries",
            "confidence": 0.62,
            "hostname": "test-machine",
            "os_user": "test-user",
        }
    )
   
    time.sleep(10)
   
    # Test 3: Lower confidence prompt
    print("\n🔔 TEST 3: Showing lower confidence prompt (Gamma LLC, 48%)")
    menu_bar.show_client_prompt(
        client_id=3,
        client_name="Gamma LLC",
        confidence=0.48,
        prompt_data={
            "prompt_id": "test-003",
            "client_id": 3,
            "client_name": "Gamma LLC",
            "confidence": 0.48,
            "hostname": "test-machine",
            "os_user": "test-user",
        }
    )
def main():
    """Main test function"""
    print("=" * 60)
    print("🧪 TimeTracker GUI Test Script")
    print("=" * 60)
    print()
   
    if not GUI_AVAILABLE:
        print("❌ GUI components not available")
        print("\n💡 Install dependencies:")
        print(" pip3 install --user pyobjc-core pyobjc-framework-Cocoa")
        return 1
   
    print("✅ GUI components available")
    print()
    print("📋 What this test does:")
    print(" 1. Creates menu bar icon (⏱)")
    print(" 2. Shows 3 test prompts at different confidence levels")
    print(" 3. Lets you test all GUI features")
    print()
    print("🎮 Try these features:")
    print(" • Click the menu bar icon (⏱)")
    print(" • Open 'Manage Clients' window")
    print(" • Add/delete test clients")
    print(" • Switch clients via menu")
    print(" • Open 'Today's Time' window")
    print(" • Respond to prompts (Yes/No/Pick Different)")
    print()
    print("⚠️ Note: This is a test. No data is sent to your API.")
    print()
    print("Press Ctrl+C to exit anytime")
    print("=" * 60)
    print()
   
    try:
        # Initialize GUI
        print("🚀 Starting GUI...")
        menu_bar = run_gui_app(
            on_client_confirmed=test_confirmed,
            on_client_rejected=test_rejected,
            get_today_time=test_get_today_time
        )
       
        if not menu_bar:
            print("❌ Failed to initialize menu bar")
            return 1
       
        print("✅ Menu bar initialized")
        print("👀 Look for the timer icon (⏱) in your menu bar!")
        print()
       
        # Start test prompt thread
        test_thread = threading.Thread(
            target=show_test_prompts,
            args=(menu_bar,),
            daemon=True
        )
        test_thread.start()
       
        # Run the GUI event loop (blocks here)
        print("🎬 Running GUI event loop...")
        print(" (GUI is now active - interact with the menu bar)")
        print()

        def signal_handler(sig, frame):
            print("\n🛑 Shutting down GUI...")
            NSApp.terminate_(None)
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        NSApp.run()
       
    except KeyboardInterrupt:
        print("\n\n👋 Test stopped by user (Ctrl+C)")
        print("✅ GUI test complete")
        return 0
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return 1
if __name__ == "__main__":
    sys.exit(main())