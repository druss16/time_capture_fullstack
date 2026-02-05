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
    pip install windows-toasts

Supports actual action buttons (Yes/No/Switch/Snooze) on Windows 10/11!
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

# Windows notifications using windows-toasts
NOTIF_AVAILABLE = False

try:
    from windows_toasts import (
        Toast, 
        ToastDisplayImage,
        ToastDuration,
        InteractableWindowsToaster,
        ToastActivatedEventArgs,
        ToastButton,
        ToastInputTextBox,
        ToastSelection,
        ToastInputSelectionBox,
    )
    NOTIF_AVAILABLE = True
    print("[NOTIF] windows-toasts library loaded successfully")
except ImportError as e:
    print(f"[NOTIF] Windows toast notifications not available: {e}")
    print("[NOTIF] Install with: pip install windows-toasts")


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


# Action identifiers
ACTION_CONFIRM = "confirm"
ACTION_SWITCH = "switch"
ACTION_SNOOZE = "snooze"
ACTION_DISMISS = "dismiss"

# Store pending notification data for callbacks
_PENDING_NOTIFICATIONS: Dict[str, Dict] = {}


class ClientNotificationManager:
    """
    Comprehensive notification manager for TimeTracker - Windows Version.
    
    Handles all types of client-related notifications with smart throttling
    and user preference respect.
    
    Uses windows-toasts for full action button support on Windows 10/11.
    """
    
    def __init__(self, config: NotificationConfig = None):
        self.config = config or NotificationConfig.load()
        self.state = NotificationState()
        self.toaster = None
        self.ready = False
        self._lock = threading.Lock()
        
        # Callbacks
        self.on_confirm_client: Optional[Callable] = None
        self.on_switch_requested: Optional[Callable] = None
        self.on_snooze: Optional[Callable] = None

        self.api_client = None
        self.agent_config = None
    
    def setup(self) -> bool:
        """Initialize the Windows toast notifier"""
        if not NOTIF_AVAILABLE:
            print("[NOTIF] Windows notifications not available - windows-toasts not installed")
            return False
        
        try:
            # Use InteractableWindowsToaster for button support
            # App name appears in Windows notification settings
            self.toaster = InteractableWindowsToaster("TimeTracker")
            self.ready = True
            print("[NOTIF] ✅ Windows toast notifier initialized successfully")
            return True
        except Exception as e:
            print(f"[NOTIF] ❌ Setup error: {e}")
            import traceback
            traceback.print_exc()
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
        if not self.config.enabled:
            print(f"[NOTIF] Notifications disabled in config")
            return False
        
        if not self.ready:
            print(f"[NOTIF] Toaster not ready")
            return False
        
        if self._is_quiet_hours():
            print(f"[NOTIF] In quiet hours, skipping notification")
            return False
        
        now = time.time()
        elapsed = now - self.state.last_notification_time
        
        if elapsed < self.config.min_seconds_between_notifications:
            print(f"[NOTIF] Throttled - only {elapsed:.0f}s since last notification")
            return False
        
        return True
    
    def _create_activated_callback(self, notif_id: str):
        """Create callback for when notification or button is clicked"""
        def on_activated(event_args: ToastActivatedEventArgs):
            data = _PENDING_NOTIFICATIONS.get(notif_id, {})
            
            # Get the action from arguments (button click) or default to confirm
            action = ACTION_CONFIRM
            if hasattr(event_args, 'arguments') and event_args.arguments:
                action = event_args.arguments
            
            print(f"[NOTIF] Toast activated: action={action}, notif_id={notif_id}")
            
            try:
                if action == ACTION_CONFIRM:
                    if self.on_confirm_client and data.get("client_id"):
                        self.on_confirm_client(
                            data.get("client_id"),
                            data.get("client_name")
                        )
                elif action == ACTION_SWITCH:
                    if self.on_switch_requested:
                        self.on_switch_requested()
                elif action == ACTION_SNOOZE:
                    client_id = data.get("client_id")
                    if client_id:
                        self.state.snooze_client(client_id, 30)
                        if self.on_snooze:
                            self.on_snooze(client_id, 30)
                elif action == "review":
                    # Open browser to timesheet review URL
                    url = data.get("url")
                    if url:
                        import webbrowser
                        print(f"[NOTIF] Opening browser: {url}")
                        webbrowser.open(url)
            except Exception as e:
                print(f"[NOTIF] Callback error: {e}")
                import traceback
                traceback.print_exc()
            
            # Clean up
            _PENDING_NOTIFICATIONS.pop(notif_id, None)
        
        return on_activated
    
    def _create_dismissed_callback(self, notif_id: str):
        """Create callback for when notification is dismissed"""
        def on_dismissed(event_args):
            print(f"[NOTIF] Toast dismissed: notif_id={notif_id}")
            _PENDING_NOTIFICATIONS.pop(notif_id, None)
        
        return on_dismissed
    
    def _create_failed_callback(self, notif_id: str):
        """Create callback for when notification fails"""
        def on_failed(event_args):
            print(f"[NOTIF] Toast failed: notif_id={notif_id}")
            _PENDING_NOTIFICATIONS.pop(notif_id, None)
        
        return on_failed

    def notify_timesheet_review(self, force: bool = False) -> bool:
        """
        Check server for unreviewed timesheet hours and notify if needed.
        Called on agent startup.
        """
        if not self.api_client:
            print("[NOTIF] No API client configured for timesheet review")
            return False
        
        if not self.config.enabled:
            return False
        
        try:
            # Call the server endpoint
            data = self.api_client.get('/agent/startup-notification/')
            
            if not data.get('show_notification'):
                print("[NOTIF] Server says no timesheet review needed")
                return False
            
            title = data.get('title', '⏰ Review Your Timesheet')
            message = data.get('message', 'You have hours to review')
            url = data.get('url', '/daily')
            
            # Build full URL for the callback
            base_url = 'https://timetracker.mavops.ai'
            if self.agent_config:
                base_url = self.agent_config.get('base_url', base_url)
            full_url = f"{base_url}{url}"
            
            # Send Windows toast notification
            result = self._send_notification(
                notif_type=NotificationType.PERIODIC_CHECKIN,
                title=title,
                body=message,
                buttons=[
                    ("Review Now", "review"),
                    ("Later", "dismiss"),
                ],
                data={
                    "url": full_url,  # Store full URL for callback
                    "hours": data.get('hours'),
                    "date": data.get('date'),
                }
            )
            
            if result:
                print(f"[NOTIF] Sent timesheet_review: {title}")
            
            return result
            
        except Exception as e:
            print(f"[NOTIF] Failed to check timesheet review: {e}")
            return False
    
    def _send_notification(
        self,
        notif_type: NotificationType,
        title: str,
        body: str,
        buttons: list = None,
        data: Dict = None,
    ) -> bool:
        """
        Send a Windows toast notification with optional action buttons.
        
        Args:
            notif_type: Type of notification
            title: Notification title (first line, bold)
            body: Notification body text
            buttons: List of (label, action_id) tuples for buttons
            data: Extra data to store for callbacks
        """
        if not self._can_send_notification(notif_type):
            return False
        
        if not self.toaster:
            print("[NOTIF] No toaster available")
            return False
        
        try:
            notif_id = f"tt-{notif_type.value}-{uuid.uuid4().hex[:8]}"
            
            # Store callback data
            _PENDING_NOTIFICATIONS[notif_id] = {
                "type": notif_type,
                "notif_id": notif_id,
                **(data or {})
            }
            
            # Create toast with title and body
            toast = Toast([title, body])
            
            # Set callbacks
            toast.on_activated = self._create_activated_callback(notif_id)
            toast.on_dismissed = self._create_dismissed_callback(notif_id)
            toast.on_failed = self._create_failed_callback(notif_id)
            
            # Add action buttons if provided
            if buttons:
                for label, action_id in buttons:
                    btn = ToastButton(label, action_id)
                    toast.AddAction(btn)
            
            # Show the toast
            print(f"[NOTIF] Showing toast: {title}")
            self.toaster.show_toast(toast)
            
            with self._lock:
                self.state.last_notification_time = time.time()
                self.state.last_notification_type = notif_type
            
            print(f"[NOTIF] ✅ Sent {notif_type.value}: {title}")
            return True
            
        except Exception as e:
            print(f"[NOTIF] ❌ Send error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
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
            body = f"{reason} • {conf_pct}% confident"
        else:
            body = f"Based on your activity • {conf_pct}% confident"
        
        buttons = [
            ("Yes", ACTION_CONFIRM),
            ("Switch Client", ACTION_SWITCH),
            ("Snooze 30m", ACTION_SNOOZE),
        ]
        
        return self._send_notification(
            notif_type=NotificationType.CLIENT_SUGGESTION,
            title=title,
            body=body,
            buttons=buttons,
            data={
                "client_id": client_id,
                "client_name": client_name,
                "confidence": confidence
            }
        )
    
    def notify_duration_reminder(self, force: bool = False) -> bool:
        """
        Send duration reminder if enough time has passed.
        """
        if not self.config.duration_reminder_enabled:
            return False
        
        if not self.state.current_client_id:
            return False
        
        now = time.time()
        working_minutes = (now - self.state.client_start_time) / 60
        since_last = (now - self.state.last_duration_reminder_time) / 60
        
        if not force:
            if working_minutes < self.config.duration_reminder_first_minutes:
                return False
            if since_last < self.config.duration_reminder_interval_minutes:
                return False
        
        # Format duration
        hours = int(working_minutes // 60)
        mins = int(working_minutes % 60)
        
        if hours > 0:
            duration_str = f"{hours}h {mins}m" if mins > 0 else f"{hours} hour{'s' if hours > 1 else ''}"
        else:
            duration_str = f"{mins} minutes"
        
        title = f"Time Check: {self.state.current_client_name}"
        body = f"You've been working on this client for {duration_str}"
        
        buttons = [
            ("Continue", ACTION_CONFIRM),
            ("Switch Client", ACTION_SWITCH),
        ]
        
        result = self._send_notification(
            notif_type=NotificationType.DURATION_REMINDER,
            title=title,
            body=body,
            buttons=buttons,
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
        """
        if not self.config.idle_return_enabled:
            return False
        
        if not self.state.current_client_id:
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
        body = f"You were away {away_text}. Still working on {self.state.current_client_name}?"
        
        buttons = [
            ("Yes", ACTION_CONFIRM),
            ("Switch Client", ACTION_SWITCH),
        ]
        
        return self._send_notification(
            notif_type=NotificationType.IDLE_RETURN,
            title=title,
            body=body,
            buttons=buttons,
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
            body = f"{reason}\nCurrently tracking: {current}"
        else:
            body = f"Your activity suggests a client change\nCurrently: {current}"
        
        buttons = [
            ("Yes, Switch", ACTION_CONFIRM),
            ("Snooze 30m", ACTION_SNOOZE),
        ]
        
        return self._send_notification(
            notif_type=NotificationType.CONTEXT_CHANGE,
            title=title,
            body=body,
            buttons=buttons,
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
        
        buttons = [
            ("Continue", ACTION_CONFIRM),
            ("Switch Client", ACTION_SWITCH),
        ]
        
        result = self._send_notification(
            notif_type=NotificationType.PERIODIC_CHECKIN,
            title=title,
            body=body,
            buttons=buttons,
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
            return False
        
        now = time.time()
        since_last = (now - self.state.last_no_client_reminder_time) / 60
        
        if not force and since_last < self.config.no_client_reminder_after_minutes:
            return False
        
        title = "No Client Selected"
        body = "Select a client to track your time accurately"
        
        buttons = [
            ("Select Client", ACTION_SWITCH),
            ("Snooze 30m", ACTION_SNOOZE),
        ]
        
        result = self._send_notification(
            notif_type=NotificationType.NO_CLIENT_REMINDER,
            title=title,
            body=body,
            buttons=buttons,
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
                import traceback
                traceback.print_exc()
            
            self._stop.wait(timeout=self.poll_interval)


# ============================================================
# INTEGRATION HELPER
# ============================================================

def create_notification_system(
    on_confirm: Callable = None,
    on_switch: Callable = None,
    on_snooze: Callable = None,
    config: NotificationConfig = None,
    api_client = None,           # ADD
    agent_config: dict = None,   # ADD
    on_review: Callable = None,  # ADD
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
    manager.api_client = api_client        # ADD
    manager.agent_config = agent_config    # ADD
    manager.on_review_timesheet = on_review  # ADD
    
    if manager.setup():
        print("[NOTIF] ✅ Windows notification system ready")
    else:
        print("[NOTIF] ⚠️ Windows notification system setup failed")
        print("[NOTIF] To enable notifications, run: pip install windows-toasts")
    
    return manager


# ============================================================
# TEST CODE
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("Testing Windows notification system (windows-toasts)")
    print("=" * 50)
    print(f"NOTIF_AVAILABLE: {NOTIF_AVAILABLE}")
    
    if not NOTIF_AVAILABLE:
        print("\n❌ Install notifications with: pip install windows-toasts")
        exit(1)
    
    def on_confirm(client_id, client_name):
        print(f"✅ CALLBACK: Confirmed client '{client_name}' (ID: {client_id})")
    
    def on_switch():
        print("🔄 CALLBACK: Switch requested - would open client picker")
    
    def on_snooze(client_id, minutes):
        print(f"😴 CALLBACK: Snoozed client {client_id} for {minutes} minutes")
    
    manager = create_notification_system(
        on_confirm=on_confirm,
        on_switch=on_switch,
        on_snooze=on_snooze
    )
    
    if not manager.ready:
        print("❌ Manager not ready!")
        exit(1)
    
    # Set a test client
    manager.set_current_client(1, "Acme Corporation")
    
    print("\n--- Sending test notifications ---")
    print("Click the buttons to test callbacks!\n")
    
    # Test 1: Client suggestion (has Yes/Switch/Snooze buttons)
    print("1. Sending client suggestion notification...")
    print("   → Has buttons: [Yes] [Switch Client] [Snooze 30m]")
    manager.notify_client_suggestion(
        client_id=2,
        client_name="Beta Industries",
        confidence=0.75,
        reason="You opened their QuickBooks file"
    )
    
    time.sleep(4)
    
    # Test 2: Duration reminder (has Continue/Switch buttons)
    print("\n2. Sending duration reminder notification...")
    print("   → Has buttons: [Continue] [Switch Client]")
    manager.notify_duration_reminder(force=True)
    
    time.sleep(4)
    
    # Test 3: Idle return (has Yes/Switch buttons)
    print("\n3. Sending idle return notification...")
    print("   → Has buttons: [Yes] [Switch Client]")
    manager.notify_idle_return(idle_duration_seconds=600)
    
    time.sleep(4)
    
    # Test 4: No client reminder (has Select/Snooze buttons)
    print("\n4. Sending no-client reminder notification...")
    print("   → Has buttons: [Select Client] [Snooze 30m]")
    manager.set_current_client(None, None)
    manager.notify_no_client(force=True)
    
    print("\n" + "=" * 50)
    print("✅ Test notifications sent!")
    print("Check your Windows notification center (Win+N)")
    print("Click the buttons to see callback messages above")
    print("=" * 50)
    print("\nPress Ctrl+C to exit...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDone.")