#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker Push Notifications Module

Comprehensive notification system for client reminders:
- Duration-based reminders (e.g., "2 hours on Acme Corp")
- Return-from-idle alerts
- Context-switch suggestions
- Periodic check-ins
- Smart notification throttling
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

# macOS notifications
try:
    from Foundation import NSObject, NSLog
    from UserNotifications import (
        UNUserNotificationCenter, UNMutableNotificationContent, 
        UNNotificationRequest, UNNotificationAction, UNNotificationCategory,
        UNNotificationActionOptionForeground, UNTimeIntervalNotificationTrigger
    )
    NOTIF_AVAILABLE = True
except ImportError:
    NOTIF_AVAILABLE = False
    print("[NOTIF] UserNotifications framework not available")


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
            config_path = os.path.expanduser("~/.timetracker/notification_config.json")
        
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
            config_path = os.path.expanduser("~/.timetracker/notification_config.json")
        
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


# Notification category IDs
CATEGORY_CLIENT_SUGGESTION = "TIMETRACKER_CLIENT_SUGGESTION"
CATEGORY_DURATION_REMINDER = "TIMETRACKER_DURATION_REMINDER"
CATEGORY_IDLE_RETURN = "TIMETRACKER_IDLE_RETURN"
CATEGORY_CONTEXT_CHANGE = "TIMETRACKER_CONTEXT_CHANGE"
CATEGORY_CHECKIN = "TIMETRACKER_CHECKIN"
CATEGORY_NO_CLIENT = "TIMETRACKER_NO_CLIENT"

# Action IDs
ACTION_CONFIRM = "ACTION_CONFIRM"
ACTION_SWITCH = "ACTION_SWITCH"
ACTION_SNOOZE = "ACTION_SNOOZE"
ACTION_DISMISS = "ACTION_DISMISS"

# Store pending notification data for callbacks
_PENDING_NOTIFICATIONS: Dict[str, Dict] = {}


class ClientNotificationDelegate(NSObject):
    """Handles notification responses"""
    
    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
        self, center, response, completion
    ):
        try:
            req = response.notification().request()
            req_id = str(req.identifier())
            action_id = str(response.actionIdentifier())
            
            NSLog(f"[NOTIF] Response: req_id={req_id}, action={action_id}")
            
            data = _PENDING_NOTIFICATIONS.pop(req_id, None)
            if not data:
                # Handle startup timesheet review notifications
                if req_id.startswith("timesheet-review-"):
                    import webbrowser
                    from datetime import date, timedelta
                    yesterday = (date.today() - timedelta(days=1)).isoformat()
                    webbrowser.open(f"https://timetracker.mavops.ai/daily?date={yesterday}")
                    NSLog("[NOTIF] Opened timesheet review in browser")
                    if completion:
                        completion()
                    return
                NSLog(f"[NOTIF] No pending data for {req_id}")
                if completion:
                    completion()
                return

            callback = data.get("callback")
            notif_type = data.get("type")
            
            DEFAULT_ACTION = "com.apple.UNNotificationDefaultActionIdentifier"
            DISMISS_ACTION = "com.apple.UNNotificationDismissActionIdentifier"
            
            if action_id == ACTION_CONFIRM or action_id == DEFAULT_ACTION:
                if callback:
                    callback("confirm", data)
            elif action_id == ACTION_SWITCH:
                if callback:
                    callback("switch", data)
            elif action_id == ACTION_SNOOZE:
                if callback:
                    callback("snooze", data)
            elif action_id == DISMISS_ACTION:
                if callback:
                    callback("dismiss", data)
            else:
                NSLog(f"[NOTIF] Unknown action: {action_id}")
            
        except Exception as e:
            NSLog(f"[NOTIF] Delegate error: {e}")
        
        if completion:
            completion()


class ClientNotificationManager:
    """
    Comprehensive notification manager for TimeTracker.
    
    Handles all types of client-related notifications with smart throttling
    and user preference respect.
    """
    
    def __init__(self, config: NotificationConfig = None):
        self.config = config or NotificationConfig.load()
        self.state = NotificationState()
        self.center = None
        self.delegate = None
        self.ready = False
        self._lock = threading.Lock()
        self._init_time = time.time()  # ADD THIS LINE

        
        # Callbacks
        self.on_confirm_client: Optional[Callable] = None
        self.on_switch_requested: Optional[Callable] = None
        self.on_snooze: Optional[Callable] = None
    
    def setup(self) -> bool:
        """Initialize notification center and register categories"""
        if not NOTIF_AVAILABLE:
            print("[NOTIF] macOS notifications not available")
            return False
        
        try:
            self.center = UNUserNotificationCenter.currentNotificationCenter()
            
            # Create delegate
            if not self.delegate:
                self.delegate = ClientNotificationDelegate.alloc().init()
                self.center.setDelegate_(self.delegate)
            
            # Register notification categories with actions
            categories = set()
            
            # Client suggestion category (Yes/No/Snooze)
            confirm_action = UNNotificationAction.actionWithIdentifier_title_options_(
                ACTION_CONFIRM, "Yes, correct", UNNotificationActionOptionForeground
            )
            switch_action = UNNotificationAction.actionWithIdentifier_title_options_(
                ACTION_SWITCH, "Switch Client", UNNotificationActionOptionForeground
            )
            snooze_action = UNNotificationAction.actionWithIdentifier_title_options_(
                ACTION_SNOOZE, "Snooze 30m", 0
            )
            
            suggestion_cat = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                CATEGORY_CLIENT_SUGGESTION, 
                [confirm_action, switch_action, snooze_action], 
                [], 0
            )
            categories.add(suggestion_cat)
            
            # Duration reminder (Continue/Switch)
            continue_action = UNNotificationAction.actionWithIdentifier_title_options_(
                ACTION_CONFIRM, "Continue", 0
            )
            duration_cat = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                CATEGORY_DURATION_REMINDER,
                [continue_action, switch_action],
                [], 0
            )
            categories.add(duration_cat)
            
            # Idle return (Yes/Switch)
            idle_cat = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                CATEGORY_IDLE_RETURN,
                [confirm_action, switch_action],
                [], 0
            )
            categories.add(idle_cat)
            
            # Context change (Switch/Dismiss)
            context_cat = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                CATEGORY_CONTEXT_CHANGE,
                [switch_action, snooze_action],
                [], 0
            )
            categories.add(context_cat)
            
            # Simple check-in (just acknowledge)
            checkin_cat = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                CATEGORY_CHECKIN,
                [continue_action, switch_action],
                [], 0
            )
            categories.add(checkin_cat)
            
            # No client reminder (Select Client action)
            select_action = UNNotificationAction.actionWithIdentifier_title_options_(
                ACTION_SWITCH, "Select Client", UNNotificationActionOptionForeground
            )
            no_client_cat = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                CATEGORY_NO_CLIENT,
                [select_action, snooze_action],
                [], 0
            )
            categories.add(no_client_cat)
            
            self.center.setNotificationCategories_(categories)
            
            # Request authorization
            evt = threading.Event()
            
            def on_auth(granted, error):
                self.ready = bool(granted)
                if error:
                    print(f"[NOTIF] Auth error: {error}")
                evt.set()
            
            # Request alert + sound
            self.center.requestAuthorizationWithOptions_completionHandler_(
                (1 << 0) | (1 << 1) | (1 << 2),  # badge, sound, alert
                on_auth
            )
            
            evt.wait(timeout=5)
            print(f"[NOTIF] Setup complete, ready={self.ready}")
            return self.ready
            
        except Exception as e:
            print(f"[NOTIF] Setup error: {e}")
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
        subtitle: str = None,
        category_id: str = None,
        data: Dict = None,
        callback: Callable = None,
        delay_seconds: float = 0
    ) -> bool:
        """Send a notification"""
        if not self._can_send_notification(notif_type):
            return False
        
        try:
            req_id = f"timetracker-{notif_type.value}-{uuid.uuid4().hex[:8]}"
            
            # Store callback data
            _PENDING_NOTIFICATIONS[req_id] = {
                "type": notif_type,
                "callback": callback or self._default_callback,
                **(data or {})
            }
            
            content = UNMutableNotificationContent.alloc().init()
            content.setTitle_(title)
            content.setBody_(body)
            if subtitle:
                content.setSubtitle_(subtitle)
            if category_id:
                content.setCategoryIdentifier_(category_id)
            
            # Optional: Add sound
            # content.setSound_(UNNotificationSound.defaultSound())
            
            trigger = None
            if delay_seconds > 0:
                trigger = UNTimeIntervalNotificationTrigger.triggerWithTimeInterval_repeats_(
                    delay_seconds, False
                )
            
            request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                req_id, content, trigger
            )
            
            def on_complete(error):
                if error:
                    print(f"[NOTIF] ❌ Delivery FAILED: {error}")
                else:
                    print(f"[NOTIF] ✅ Delivered to macOS: {req_id}")

            self.center.addNotificationRequest_withCompletionHandler_(request, on_complete)
            
            with self._lock:
                self.state.last_notification_time = time.time()
                self.state.last_notification_type = notif_type
            
            print(f"[NOTIF] Sent {notif_type.value}: {title}")
            return True
            
        except Exception as e:
            print(f"[NOTIF] Send error: {e}")
            return False

    def notify_timesheet_review(self, force: bool = False) -> bool:
        """
        Check server for unreviewed timesheet hours and notify if needed.
        Called on agent startup.
        """
        if not getattr(self, 'api_client', None):
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
            subtitle = data.get('subtitle')
            url = data.get('url', '/daily')
            
            # Build full URL for the callback
            base_url = 'https://timetracker.mavops.ai'
            if getattr(self, 'agent_config', None):
                base_url = self.agent_config.get('base_url', base_url)
            full_url = f"{base_url}{url}"
            
            # Send macOS notification
            result = self._send_notification(
                notif_type=NotificationType.PERIODIC_CHECKIN,
                title=title,
                body=message,
                subtitle=subtitle,
                category_id=CATEGORY_CHECKIN,
                data={
                    "url": full_url,
                    "hours": data.get('hours'),
                    "date": data.get('date'),
                    "action": "review_timesheet",
                }
            )
            
            if result:
                print(f"[NOTIF] Sent timesheet_review: {title}")
            
            return result
            
        except Exception as e:
            print(f"[NOTIF] Failed to check timesheet review: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _default_callback(self, action: str, data: Dict):
        """Default notification response handler"""
        print(f"[NOTIF] Action: {action}, data: {data}")
        
        if action == "confirm":
            if self.on_confirm_client:
                self.on_confirm_client(
                    data.get("client_id"),
                    data.get("client_name")
                )
        elif action == "switch":
            if self.on_switch_requested:
                self.on_switch_requested()
        elif action == "snooze":
            client_id = data.get("client_id")
            if client_id and self.on_snooze:
                self.on_snooze(client_id, 30)  # 30 minute snooze
            if client_id:
                self.state.snooze_client(client_id, 30)
    
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
        
        if reason:
            body = f"{reason}\nConfidence: {conf_pct}%"
        else:
            body = f"Based on your activity • {conf_pct}% confident"
        
        return self._send_notification(
            notif_type=NotificationType.CLIENT_SUGGESTION,
            title="Working on this client?",
            subtitle=client_name,
            body=body,
            category_id=CATEGORY_CLIENT_SUGGESTION,
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
        
        result = self._send_notification(
            notif_type=NotificationType.DURATION_REMINDER,
            title="Time Check",
            subtitle=self.state.current_client_name,
            body=f"You've been working on this client for {duration_str}",
            category_id=CATEGORY_DURATION_REMINDER,
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
            body = "You were away briefly"
        elif idle_mins < 30:
            body = f"You were away for {idle_mins} minutes"
        elif idle_mins < 60:
            body = f"You were away for about {idle_mins} minutes"
        else:
            hours = idle_mins // 60
            body = f"You were away for {hours}+ hour{'s' if hours > 1 else ''}"
        
        return self._send_notification(
            notif_type=NotificationType.IDLE_RETURN,
            title="Welcome back!",
            subtitle=f"Still working on {self.state.current_client_name}?",
            body=body,
            category_id=CATEGORY_IDLE_RETURN,
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
            reason: Why we think they switched (e.g., "Opened QuickBooks for Acme")
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
        
        body = reason or f"Your activity suggests you may have switched from {current}"
        
        return self._send_notification(
            notif_type=NotificationType.CONTEXT_CHANGE,
            title="Client Changed?",
            subtitle=f"Switch to {suggested_client_name}?",
            body=body,
            category_id=CATEGORY_CONTEXT_CHANGE,
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
        
        result = self._send_notification(
            notif_type=NotificationType.PERIODIC_CHECKIN,
            title="TimeTracker",
            subtitle=self.state.current_client_name,
            body=f"Currently tracking • {working_mins} min today",
            category_id=CATEGORY_CHECKIN,
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
        
        # STARTUP GRACE PERIOD: Don't send within first 10 seconds
        # This allows time for client state to be restored from backend
        if hasattr(self, '_init_time'):
            if now - self._init_time < 10:
                return False
        
        result = self._send_notification(
            notif_type=NotificationType.NO_CLIENT_REMINDER,
            title="No Client Selected",
            body="Select a client to track your time accurately",
            category_id=CATEGORY_NO_CLIENT,
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
    config: NotificationConfig = None,
    api_client = None,           # ADD
    agent_config: dict = None,   # ADD
    on_review: Callable = None,  # ADD
) -> ClientNotificationManager:
    """
    Create and setup the notification system.
    
    Args:
        on_confirm: Called when user confirms current client
        on_switch: Called when user wants to switch client
        on_snooze: Called when user snoozes a suggestion
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
        print("[NOTIF] Notification system ready")
    else:
        print("[NOTIF] Notification system setup failed")
    
    return manager


if __name__ == "__main__":
    # Test the notification system
    print("Testing notification system...")
    
    def on_confirm(client_id, client_name):
        print(f"Confirmed: {client_name} (ID: {client_id})")
    
    def on_switch():
        print("Switch requested")
    
    def on_snooze(client_id, minutes):
        print(f"Snoozed client {client_id} for {minutes} minutes")
    
    manager = create_notification_system(
        on_confirm=on_confirm,
        on_switch=on_switch,
        on_snooze=on_snooze
    )
    
    # Set a test client
    manager.set_current_client(1, "Acme Corporation")
    
    # Test notifications
    print("\nSending test notifications...")
    
    manager.notify_client_suggestion(
        client_id=2,
        client_name="Beta Industries",
        confidence=0.75,
        reason="You opened their QuickBooks file"
    )
    
    time.sleep(2)
    
    manager.notify_duration_reminder(force=True)
    
    time.sleep(2)
    
    manager.notify_idle_return(idle_duration_seconds=600)
    
    print("\nNotifications sent. Check your notification center.")
    print("Press Ctrl+C to exit...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDone.")