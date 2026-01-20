#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker Push Notifications Module - WINDOWS VERSION

Comprehensive notification system for client reminders:
- Duration-based reminders (e.g., "2 hours on Acme Corp")
- Return-from-idle alerts
- Context-switch suggestions
- Periodic check-ins
- Smart notification throttling

Requirements:
    pip install win10toast-click

Note: Windows toast notifications have limited interactivity compared to macOS.
Clicking the notification triggers the primary action (confirm/switch).
"""

import os
import json
import time
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Callable, Any
from dataclasses import dataclass, field
from enum import Enum

# Windows notifications
NOTIF_AVAILABLE = False
ToastNotifier = None

try:
    from win10toast_click import ToastNotifier as _ToastNotifier
    ToastNotifier = _ToastNotifier
    NOTIF_AVAILABLE = True
    print("[NOTIF] win10toast-click available")
except ImportError:
    try:
        # Fallback to regular win10toast (no click support)
        from win10toast import ToastNotifier as _ToastNotifier
        ToastNotifier = _ToastNotifier
        NOTIF_AVAILABLE = True
        print("[NOTIF] win10toast available (no click callbacks)")
    except ImportError:
        print("[NOTIF] Windows toast notifications not available")
        print("[NOTIF] Install with: pip install win10toast-click")


class NotificationType(Enum):
    """Types of notifications we send"""
    CLIENT_SUGGESTION = "client_suggestion"      # AI thinks you're working on X
    DURATION_REMINDER = "duration_reminder"      # You've been on X for N hours
    IDLE_RETURN = "idle_return"                  # Welcome back, still on X?
    CONTEXT_CHANGE = "context_change"            # Activity changed, switch client?
    PERIODIC_CHECKIN = "periodic_checkin"        # Quick reminder of current client
    NO_CLIENT_REMINDER = "no_client_reminder"    # You haven't selected a client


@dataclass
class NotificationConfig:
    """Configuration for notification behavior"""
    # Master switch
    enabled: bool = True
    
    # Duration reminders (in minutes)
    duration_reminder_enabled: bool = True
    duration_reminder_interval_minutes: int = 60  # Remind every hour
    duration_reminder_first_minutes: int = 30     # First reminder after 30 min
    
    # Idle return
    idle_return_enabled: bool = True
    idle_threshold_seconds: int = 300  # 5 minutes idle
    
    # Context change detection
    context_change_enabled: bool = True
    context_confidence_threshold: float = 0.6  # Min confidence to suggest
    
    # Periodic check-ins
    periodic_checkin_enabled: bool = False  # Off by default (can be noisy)
    periodic_checkin_interval_minutes: int = 120  # Every 2 hours
    
    # No client reminder
    no_client_reminder_enabled: bool = True
    no_client_reminder_after_minutes: int = 15  # Remind after 15 min with no client
    
    # Throttling
    min_seconds_between_notifications: int = 60  # Don't spam
    quiet_hours_start: int = 22  # 10 PM
    quiet_hours_end: int = 7     # 7 AM
    respect_quiet_hours: bool = True
    
    # Windows-specific
    notification_duration_seconds: int = 10  # How long toast stays visible
    
    @classmethod
    def load(cls, config_path: str = None) -> 'NotificationConfig':
        """Load config from file or return defaults"""
        if config_path is None:
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            config_path = os.path.join(appdata, "TimeTracker", "notification_config.json")
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    data = json.load(f)
                    return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
            except Exception as e:
                print(f"[NOTIF] Failed to load config: {e}")
        
        return cls()
    
    def save(self, config_path: str = None):
        """Save config to file"""
        if config_path is None:
            appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
            config_path = os.path.join(appdata, "TimeTracker", "notification_config.json")
        
        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(self.__dict__, f, indent=2)
        except Exception as e:
            print(f"[NOTIF] Failed to save config: {e}")


@dataclass
class NotificationState:
    """Tracks notification state to prevent spam"""
    last_notification_time: float = 0
    last_notification_type: Optional[NotificationType] = None
    last_duration_reminder_time: float = 0
    last_periodic_checkin_time: float = 0
    last_no_client_reminder_time: float = 0
    client_start_time: float = field(default_factory=time.time)
    current_client_id: Optional[int] = None
    current_client_name: Optional[str] = None
    was_idle: bool = False
    idle_start_time: float = 0
    
    # Track dismissed/snoozed suggestions
    snoozed_clients: Dict[int, float] = field(default_factory=dict)  # client_id -> snooze_until
    
    def snooze_client(self, client_id: int, minutes: int = 30):
        """Snooze suggestions for a specific client"""
        self.snoozed_clients[client_id] = time.time() + (minutes * 60)
    
    def is_snoozed(self, client_id: int) -> bool:
        """Check if client suggestions are snoozed"""
        until = self.snoozed_clients.get(client_id, 0)
        return time.time() < until
    
    def set_client(self, client_id: Optional[int], client_name: Optional[str]):
        """Update current client and reset timers"""
        if client_id != self.current_client_id:
            self.current_client_id = client_id
            self.current_client_name = client_name
            self.client_start_time = time.time()
            self.last_duration_reminder_time = time.time()


# Store pending notification callbacks
_PENDING_CALLBACKS: Dict[str, Dict] = {}


class ClientNotificationManager:
    """
    Comprehensive notification manager for TimeTracker - Windows Version.
    
    Handles all types of client-related notifications with smart throttling
    and user preference respect.
    
    Note: Windows toast notifications have limited interactivity.
    Clicking the toast triggers the primary callback action.
    """
    
    def __init__(self, config: NotificationConfig = None):
        self.config = config or NotificationConfig.load()
        self.state = NotificationState()
        self.toaster = None
        self.ready = False
        self._lock = threading.Lock()
        self._icon_path = self._get_icon_path()
        
        # Callbacks
        self.on_confirm_client: Optional[Callable] = None
        self.on_switch_requested: Optional[Callable] = None
        self.on_snooze: Optional[Callable] = None
    
    def _get_icon_path(self) -> Optional[str]:
        """Get path to notification icon"""
        # Check common locations for icon
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "icon.ico"),
            os.path.join(os.path.dirname(__file__), "assets", "icon.ico"),
            os.path.join(os.environ.get("APPDATA", ""), "TimeTracker", "icon.ico"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def setup(self) -> bool:
        """Initialize the Windows toast notifier"""
        if not NOTIF_AVAILABLE or ToastNotifier is None:
            print("[NOTIF] Windows notifications not available")
            return False
        
        try:
            self.toaster = ToastNotifier()
            self.ready = True
            print("[NOTIF] Windows toast notifier ready")
            return True
        except Exception as e:
            print(f"[NOTIF] Setup error: {e}")
            return False
    
    def _is_quiet_hours(self) -> bool:
        """Check if we're in quiet hours"""
        if not self.config.respect_quiet_hours:
            return False
        
        hour = datetime.now().hour
        start = self.config.quiet_hours_start
        end = self.config.quiet_hours_end
        
        if start > end:  # Wraps midnight (e.g., 22-7)
            return hour >= start or hour < end
        else:
            return start <= hour < end
    
    def _can_send_notification(self, notif_type: NotificationType) -> bool:
        """Check if we can send a notification (throttling, quiet hours, etc.)"""
        if not self.config.enabled or not self.ready:
            return False
        
        if self._is_quiet_hours():
            return False
        
        now = time.time()
        elapsed = now - self.state.last_notification_time
        
        if elapsed < self.config.min_seconds_between_notifications:
            return False
        
        return True
    
    def _send_notification(
        self,
        notif_type: NotificationType,
        title: str,
        body: str,
        data: Dict = None,
        callback: Callable = None,
        threaded: bool = True
    ) -> bool:
        """
        Send a Windows toast notification.
        
        Args:
            notif_type: Type of notification
            title: Notification title
            body: Notification body text
            data: Extra data to pass to callback
            callback: Function to call when notification is clicked
            threaded: Run in background thread (recommended)
        """
        if not self._can_send_notification(notif_type):
            return False
        
        if not self.toaster:
            return False
        
        try:
            notif_id = f"timetracker-{notif_type.value}-{uuid.uuid4().hex[:8]}"
            
            # Store callback data
            callback_data = {
                "type": notif_type,
                "callback": callback or self._default_callback,
                "notif_id": notif_id,
                **(data or {})
            }
            _PENDING_CALLBACKS[notif_id] = callback_data
            
            # Create click callback wrapper
            def on_click():
                cb_data = _PENDING_CALLBACKS.pop(notif_id, None)
                if cb_data and cb_data.get("callback"):
                    try:
                        cb_data["callback"]("click", cb_data)
                    except Exception as e:
                        print(f"[NOTIF] Callback error: {e}")
            
            # Send the toast
            # Note: win10toast-click uses callback parameter for click handling
            try:
                self.toaster.show_toast(
                    title=title,
                    msg=body,
                    icon_path=self._icon_path,
                    duration=self.config.notification_duration_seconds,
                    threaded=threaded,
                    callback_on_click=on_click
                )
            except TypeError:
                # Fallback for regular win10toast (no callback support)
                self.toaster.show_toast(
                    title=title,
                    msg=body,
                    icon_path=self._icon_path,
                    duration=self.config.notification_duration_seconds,
                    threaded=threaded
                )
            
            with self._lock:
                self.state.last_notification_time = time.time()
                self.state.last_notification_type = notif_type
            
            print(f"[NOTIF] Sent {notif_type.value}: {title}")
            return True
            
        except Exception as e:
            print(f"[NOTIF] Send error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _default_callback(self, action: str, data: Dict):
        """Default notification response handler"""
        print(f"[NOTIF] Action: {action}, data keys: {list(data.keys())}")
        
        notif_type = data.get("type")
        
        # Handle click based on notification type
        if notif_type == NotificationType.CLIENT_SUGGESTION:
            # Click = confirm the suggestion
            if self.on_confirm_client:
                self.on_confirm_client(
                    data.get("client_id"),
                    data.get("client_name")
                )
        
        elif notif_type == NotificationType.NO_CLIENT_REMINDER:
            # Click = open client picker
            if self.on_switch_requested:
                self.on_switch_requested()
        
        elif notif_type in (NotificationType.IDLE_RETURN, NotificationType.DURATION_REMINDER):
            # Click = confirm continuing with current client
            if self.on_confirm_client:
                self.on_confirm_client(
                    data.get("client_id"),
                    data.get("client_name")
                )
        
        elif notif_type == NotificationType.CONTEXT_CHANGE:
            # Click = switch to suggested client
            if self.on_confirm_client:
                self.on_confirm_client(
                    data.get("client_id"),
                    data.get("client_name")
                )
    
    # ============================================================
    # PUBLIC NOTIFICATION METHODS
    # ============================================================
    
    def notify_client_suggestion(
        self,
        client_id: int,
        client_name: str,
        confidence: float,
        reason: str = None
    ) -> bool:
        """
        Notify user of AI client suggestion.
        
        Args:
            client_id: Suggested client ID
            client_name: Suggested client name
            confidence: AI confidence (0-1)
            reason: Optional reason for suggestion
        """
        if self.state.is_snoozed(client_id):
            return False
        
        if self.state.current_client_id == client_id:
            return False
        
        conf_pct = int(confidence * 100)
        
        title = f"Working on {client_name}?"
        
        if reason:
            body = f"{reason}\nConfidence: {conf_pct}% • Click to confirm"
        else:
            body = f"Based on your activity • {conf_pct}% confident\nClick to confirm"
        
        return self._send_notification(
            notif_type=NotificationType.CLIENT_SUGGESTION,
            title=title,
            body=body,
            data={
                "client_id": client_id,
                "client_name": client_name,
                "confidence": confidence
            }
        )
    
    def notify_duration_reminder(self, force: bool = False) -> bool:
        """
        Send duration reminder if enough time has passed.
        
        Args:
            force: Send even if interval hasn't elapsed
        """
        if not self.config.duration_reminder_enabled:
            return False
        
        if not self.state.current_client_id:
            return False
        
        now = time.time()
        working_minutes = (now - self.state.client_start_time) / 60
        since_last = (now - self.state.last_duration_reminder_time) / 60
        
        # Check if we should send
        if not force:
            if working_minutes < self.config.duration_reminder_first_minutes:
                return False
            if since_last < self.config.duration_reminder_interval_minutes:
                return False
        
        # Format duration nicely
        hours = int(working_minutes // 60)
        mins = int(working_minutes % 60)
        
        if hours > 0:
            duration_str = f"{hours}h {mins}m" if mins > 0 else f"{hours} hour{'s' if hours > 1 else ''}"
        else:
            duration_str = f"{mins} minutes"
        
        title = f"Time Check: {self.state.current_client_name}"
        body = f"You've been working on this client for {duration_str}\nClick to continue tracking"
        
        result = self._send_notification(
            notif_type=NotificationType.DURATION_REMINDER,
            title=title,
            body=body,
            data={
                "client_id": self.state.current_client_id,
                "client_name": self.state.current_client_name,
                "duration_minutes": working_minutes
            }
        )
        
        if result:
            self.state.last_duration_reminder_time = now
        
        return result
    
    def notify_idle_return(self, idle_duration_seconds: float) -> bool:
        """
        Notify user when returning from idle.
        
        Args:
            idle_duration_seconds: How long they were idle
        """
        if not self.config.idle_return_enabled:
            return False
        
        if not self.state.current_client_id:
            # No client set - remind them to select one
            return self.notify_no_client()
        
        idle_mins = int(idle_duration_seconds / 60)
        
        if idle_mins < 5:
            away_text = "briefly"
        elif idle_mins < 30:
            away_text = f"for {idle_mins} minutes"
        elif idle_mins < 60:
            away_text = f"for about {idle_mins} minutes"
        else:
            hours = idle_mins // 60
            away_text = f"for {hours}+ hour{'s' if hours > 1 else ''}"
        
        title = "Welcome back!"
        body = f"You were away {away_text}\nStill working on {self.state.current_client_name}?\nClick to confirm"
        
        return self._send_notification(
            notif_type=NotificationType.IDLE_RETURN,
            title=title,
            body=body,
            data={
                "client_id": self.state.current_client_id,
                "client_name": self.state.current_client_name,
                "idle_seconds": idle_duration_seconds
            }
        )
    
    def notify_context_change(
        self,
        suggested_client_id: int,
        suggested_client_name: str,
        confidence: float,
        reason: str = None
    ) -> bool:
        """
        Notify when activity suggests a different client.
        
        Args:
            suggested_client_id: New suggested client
            suggested_client_name: New suggested client name
            confidence: Confidence in suggestion
            reason: Why we think they switched
        """
        if not self.config.context_change_enabled:
            return False
        
        if confidence < self.config.context_confidence_threshold:
            return False
        
        if self.state.is_snoozed(suggested_client_id):
            return False
        
        if suggested_client_id == self.state.current_client_id:
            return False
        
        current = self.state.current_client_name or "No client"
        
        title = f"Switch to {suggested_client_name}?"
        
        if reason:
            body = f"{reason}\nCurrently tracking: {current}\nClick to switch"
        else:
            body = f"Your activity suggests a client change\nCurrently tracking: {current}\nClick to switch"
        
        return self._send_notification(
            notif_type=NotificationType.CONTEXT_CHANGE,
            title=title,
            body=body,
            data={
                "client_id": suggested_client_id,
                "client_name": suggested_client_name,
                "previous_client_id": self.state.current_client_id,
                "confidence": confidence
            }
        )
    
    def notify_periodic_checkin(self, force: bool = False) -> bool:
        """
        Send periodic check-in notification.
        """
        if not self.config.periodic_checkin_enabled and not force:
            return False
        
        now = time.time()
        since_last = (now - self.state.last_periodic_checkin_time) / 60
        
        if not force and since_last < self.config.periodic_checkin_interval_minutes:
            return False
        
        if not self.state.current_client_id:
            return self.notify_no_client()
        
        working_mins = int((now - self.state.client_start_time) / 60)
        
        title = "TimeTracker"
        body = f"Currently tracking: {self.state.current_client_name}\n{working_mins} min on this client"
        
        result = self._send_notification(
            notif_type=NotificationType.PERIODIC_CHECKIN,
            title=title,
            body=body,
            data={
                "client_id": self.state.current_client_id,
                "client_name": self.state.current_client_name
            }
        )
        
        if result:
            self.state.last_periodic_checkin_time = now
        
        return result
    
    def notify_no_client(self, force: bool = False) -> bool:
        """
        Remind user to select a client.
        """
        if not self.config.no_client_reminder_enabled and not force:
            return False
        
        if self.state.current_client_id:
            return False  # They have a client
        
        now = time.time()
        since_last = (now - self.state.last_no_client_reminder_time) / 60
        
        # Don't spam - only remind every N minutes
        if not force and since_last < self.config.no_client_reminder_after_minutes:
            return False
        
        title = "No Client Selected"
        body = "Select a client to track your time accurately\nClick to open client picker"
        
        result = self._send_notification(
            notif_type=NotificationType.NO_CLIENT_REMINDER,
            title=title,
            body=body,
            data={}
        )
        
        if result:
            self.state.last_no_client_reminder_time = now
        
        return result
    
    # ============================================================
    # STATE MANAGEMENT
    # ============================================================
    
    def set_current_client(self, client_id: Optional[int], client_name: Optional[str]):
        """Update the current client being tracked"""
        with self._lock:
            self.state.set_client(client_id, client_name)
    
    def on_idle_start(self):
        """Called when user goes idle"""
        with self._lock:
            self.state.was_idle = True
            self.state.idle_start_time = time.time()
    
    def on_idle_end(self) -> bool:
        """
        Called when user returns from idle.
        Returns True if notification was sent.
        """
        with self._lock:
            if not self.state.was_idle:
                return False
            
            idle_duration = time.time() - self.state.idle_start_time
            self.state.was_idle = False
            
            if idle_duration >= self.config.idle_threshold_seconds:
                return self.notify_idle_return(idle_duration)
        
        return False
    
    def check_duration_reminder(self) -> bool:
        """Check and send duration reminder if needed"""
        return self.notify_duration_reminder()
    
    def check_periodic_checkin(self) -> bool:
        """Check and send periodic check-in if needed"""
        return self.notify_periodic_checkin()
    
    def check_no_client_reminder(self) -> bool:
        """Check and send no-client reminder if needed"""
        return self.notify_no_client()


# ============================================================
# BACKGROUND NOTIFICATION WORKER
# ============================================================

class NotificationWorker:
    """
    Background worker that monitors state and sends notifications.
    
    Run this in a separate thread to handle all notification logic.
    """
    
    def __init__(
        self,
        notification_manager: ClientNotificationManager,
        get_current_client: Callable[[], Dict],
        get_ai_suggestion: Callable[[], Optional[Dict]] = None,
        poll_interval: int = 30
    ):
        self.notif = notification_manager
        self.get_current_client = get_current_client
        self.get_ai_suggestion = get_ai_suggestion
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread = None
    
    def start(self):
        """Start the notification worker"""
        if self._thread and self._thread.is_alive():
            return
        
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("[NOTIF] Worker started")
    
    def stop(self):
        """Stop the notification worker"""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        print("[NOTIF] Worker stopped")
    
    def _run(self):
        """Main worker loop"""
        while not self._stop.is_set():
            try:
                # Sync current client state
                current = self.get_current_client()
                if current:
                    self.notif.set_current_client(
                        current.get("client_id"),
                        current.get("client_name")
                    )
                
                # Check duration reminders
                self.notif.check_duration_reminder()
                
                # Check periodic check-ins
                self.notif.check_periodic_checkin()
                
                # Check no-client reminder
                self.notif.check_no_client_reminder()
                
                # Check AI suggestions (if available)
                if self.get_ai_suggestion:
                    suggestion = self.get_ai_suggestion()
                    if suggestion:
                        self.notif.notify_client_suggestion(
                            client_id=suggestion.get("client_id"),
                            client_name=suggestion.get("client_name"),
                            confidence=suggestion.get("confidence", 0),
                            reason=suggestion.get("reason")
                        )
                
            except Exception as e:
                print(f"[NOTIF] Worker error: {e}")
            
            self._stop.wait(timeout=self.poll_interval)


# ============================================================
# INTEGRATION HELPER
# ============================================================

def create_notification_system(
    on_confirm: Callable = None,
    on_switch: Callable = None,
    on_snooze: Callable = None,
    config: NotificationConfig = None
) -> ClientNotificationManager:
    """
    Create and setup the notification system.
    
    Args:
        on_confirm: Called when user confirms current client (client_id, client_name)
        on_switch: Called when user wants to switch client (no args)
        on_snooze: Called when user snoozes a suggestion (client_id, minutes)
        config: Optional custom configuration
    
    Returns:
        Configured ClientNotificationManager
    """
    manager = ClientNotificationManager(config)
    manager.on_confirm_client = on_confirm
    manager.on_switch_requested = on_switch
    manager.on_snooze = on_snooze
    
    if manager.setup():
        print("[NOTIF] ✅ Windows notification system ready")
    else:
        print("[NOTIF] ⚠️ Windows notification system setup failed")
    
    return manager


# ============================================================
# TEST CODE
# ============================================================

if __name__ == "__main__":
    print("Testing Windows notification system...")
    print(f"NOTIF_AVAILABLE: {NOTIF_AVAILABLE}")
    
    if not NOTIF_AVAILABLE:
        print("\nInstall notifications with: pip install win10toast-click")
        exit(1)
    
    def on_confirm(client_id, client_name):
        print(f"✅ Confirmed: {client_name} (ID: {client_id})")
    
    def on_switch():
        print("🔄 Switch requested - would open client picker")
    
    def on_snooze(client_id, minutes):
        print(f"😴 Snoozed client {client_id} for {minutes} minutes")
    
    manager = create_notification_system(
        on_confirm=on_confirm,
        on_switch=on_switch,
        on_snooze=on_snooze
    )
    
    if not manager.ready:
        print("Manager not ready!")
        exit(1)
    
    # Set a test client
    manager.set_current_client(1, "Acme Corporation")
    
    print("\n--- Sending test notifications ---")
    print("(Click on them to test callbacks)\n")
    
    # Test 1: Client suggestion
    print("1. Sending client suggestion...")
    manager.notify_client_suggestion(
        client_id=2,
        client_name="Beta Industries",
        confidence=0.75,
        reason="You opened their QuickBooks file"
    )
    
    time.sleep(3)
    
    # Test 2: Duration reminder
    print("2. Sending duration reminder...")
    manager.notify_duration_reminder(force=True)
    
    time.sleep(3)
    
    # Test 3: Idle return
    print("3. Sending idle return notification...")
    manager.notify_idle_return(idle_duration_seconds=600)
    
    time.sleep(3)
    
    # Test 4: No client reminder
    print("4. Sending no-client reminder...")
    manager.set_current_client(None, None)  # Clear client first
    manager.notify_no_client(force=True)
    
    print("\n✅ Test notifications sent!")
    print("Check your Windows notification center.")
    print("Click notifications to test callbacks.")
    print("\nPress Ctrl+C to exit...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDone.")