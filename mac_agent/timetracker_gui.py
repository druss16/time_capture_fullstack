#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker macOS Menu Bar GUI
Features:
- Menu bar icon with tracking status
- Floating window for client prompts (near menu bar)
- Manual client management (add/edit/delete)
- Switch clients manually
- View today's tracked time by client
- Smart (AI) modal that suggests switching clients
"""
import os
import json
import threading
import time as _time
from datetime import datetime
from typing import Optional, List, Dict, Callable

try:
    import objc
    from Foundation import (
        NSObject, NSTimer, NSMakeRect, NSMakeSize
    )
    from AppKit import (
        NSApplication, NSApp, NSStatusBar, NSMenu, NSMenuItem,
        NSWindow, NSTextField, NSButton, NSPopUpButton, NSScrollView,
        NSFloatingWindowLevel, NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
        NSWindowStyleMaskResizable, NSBackingStoreBuffered,
        NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular,
        NSScreen, NSVariableStatusItemLength, NSTableView, NSTableColumn
    )
    GUI_AVAILABLE = True
except Exception as e:
    print(f"GUI not available: {e}")
    GUI_AVAILABLE = False


# ------------------------------------------------------------
# Config paths
# ------------------------------------------------------------
CLIENTS_FILE = os.path.expanduser("~/.timetracker/clients.json")
GUI_STATE_FILE = os.path.expanduser("~/.timetracker/gui_state.json")


# ------------------------------------------------------------
# Client Manager
# ------------------------------------------------------------
class ClientManager:
    """Manages the list of clients (stored locally)"""

    def __init__(self):
        self.clients: List[Dict] = []
        self.load()

    def load(self, fetch_callback=None):
        """Load clients from backend if available, otherwise use local cache"""
        
        # Try to fetch from backend first
        if fetch_callback:
            try:
                backend_clients = fetch_callback()
                if backend_clients and isinstance(backend_clients, list):
                    self.clients = backend_clients
                    self.save()  # Cache them locally
                    print(f"[GUI] Loaded {len(self.clients)} clients from backend")
                    return
            except Exception as e:
                print(f"[GUI] Failed to fetch clients from backend: {e}")
        
        # Fall back to local cache
        if os.path.exists(CLIENTS_FILE):
            try:
                with open(CLIENTS_FILE, 'r') as f:
                    self.clients = json.load(f)
                    print(f"[GUI] Loaded {len(self.clients)} clients from cache")
            except Exception as e:
                print(f"[GUI] Failed to load clients: {e}")
                self.clients = []
        else:
            # Empty list if nothing else works
            self.clients = []


    def save(self):
        try:
            os.makedirs(os.path.dirname(CLIENTS_FILE), exist_ok=True)
            with open(CLIENTS_FILE, 'w') as f:
                json.dump(self.clients, f, indent=2)
        except Exception as e:
            print(f"[GUI] Failed to save clients: {e}")

    def get_all(self) -> List[Dict]:
        return self.clients

    def get_by_id(self, client_id: int) -> Optional[Dict]:
        for c in self.clients:
            if c.get("id") == client_id:
                return c
        return None

    def get_by_name(self, name: str) -> Optional[Dict]:
        name_lower = name.lower()
        for c in self.clients:
            if c.get("name", "").lower() == name_lower:
                return c
        return None

    def add(self, name: str, code: str = "") -> Dict:
        max_id = max([c.get("id", 0) for c in self.clients], default=0)
        new_client = {
            "id": max_id + 1,
            "name": name.strip(),
            "code": (code or name[:4]).strip().upper()
        }
        self.clients.append(new_client)
        self.save()
        return new_client

    def update(self, client_id: int, name: str, code: str):
        for c in self.clients:
            if c.get("id") == client_id:
                c["name"] = name.strip()
                c["code"] = code.strip().upper()
                self.save()
                return True
        return False

    def delete(self, client_id: int):
        self.clients = [c for c in self.clients if c.get("id") != client_id]
        self.save()


# ------------------------------------------------------------
# GUI State
# ------------------------------------------------------------
class GUIState:
    """Manages GUI state (current client, etc.)"""

    def __init__(self):
        self.current_client_id: Optional[int] = None
        self.current_client_name: str = "No Client"
        self.load()

    def load(self):
        if os.path.exists(GUI_STATE_FILE):
            try:
                with open(GUI_STATE_FILE, 'r') as f:
                    data = json.load(f)
                    self.current_client_id = data.get("current_client_id")
                    self.current_client_name = data.get("current_client_name", "No Client")
            except Exception:
                pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(GUI_STATE_FILE), exist_ok=True)
            with open(GUI_STATE_FILE, 'w') as f:
                json.dump({
                    "current_client_id": self.current_client_id,
                    "current_client_name": self.current_client_name,
                }, f, indent=2)
        except Exception as e:
            print(f"[GUI] Failed to save state: {e}")

    def set_client(self, client_id: Optional[int], client_name: str):
        self.current_client_id = client_id
        self.current_client_name = client_name
        self.save()


# ------------------------------------------------------------
# Floating Prompt Window (AI modal)
# ------------------------------------------------------------
class FloatingPromptWindow(NSWindow):
    """Floating window for client prompts that appears near menu bar"""

    def initWithClientManager_state_callback_(self, client_mgr, state, callback):
        width, height = 400, 200
        try:
            screen = NSScreen.mainScreen()
            screen_frame = screen.visibleFrame()
            x = screen_frame.origin.x + screen_frame.size.width - width - 20
            y = screen_frame.origin.y + screen_frame.size.height - height - 10
        except Exception:
            screen = NSScreen.mainScreen()
            screen_frame = screen.frame()
            x = (screen_frame.size.width - width) / 2
            y = (screen_frame.size.height - height) / 2

        frame = NSMakeRect(x, y, width, height)

        self = objc.super(FloatingPromptWindow, self).initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )
        if self is None:
            return None

        self.client_mgr = client_mgr
        self.state = state
        self.callback = callback
        self.prompt_data = None

        self.setTitle_("Time Tracker")
        self.setLevel_(NSFloatingWindowLevel)
        self.setMovableByWindowBackground_(True)

        self._setup_ui()
        return self

    def _setup_ui(self):
        content = self.contentView()

        self.question_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 140, 360, 24))
        self.question_label.setStringValue_("Are you working on this client?")
        self.question_label.setBezeled_(False)
        self.question_label.setDrawsBackground_(False)
        self.question_label.setEditable_(False)
        self.question_label.setSelectable_(False)
        content.addSubview_(self.question_label)

        self.guess_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 110, 360, 24))
        self.guess_label.setStringValue_("Client Name (85%)")
        self.guess_label.setBezeled_(False)
        self.guess_label.setDrawsBackground_(False)
        self.guess_label.setEditable_(False)
        self.guess_label.setSelectable_(False)
        content.addSubview_(self.guess_label)

        self.yes_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, 70, 100, 32))
        self.yes_btn.setTitle_("✓ Yes")
        self.yes_btn.setBezelStyle_(1)
        self.yes_btn.setTarget_(self)
        self.yes_btn.setAction_("onYes:")
        content.addSubview_(self.yes_btn)

        self.no_btn = NSButton.alloc().initWithFrame_(NSMakeRect(130, 70, 100, 32))
        self.no_btn.setTitle_("✗ No")
        self.no_btn.setBezelStyle_(1)
        self.no_btn.setTarget_(self)
        self.no_btn.setAction_("onNo:")
        content.addSubview_(self.no_btn)

        or_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 45, 360, 16))
        or_label.setStringValue_("Or select a different client:")
        or_label.setBezeled_(False)
        or_label.setDrawsBackground_(False)
        or_label.setEditable_(False)
        or_label.setSelectable_(False)
        content.addSubview_(or_label)

        self.client_dropdown = NSPopUpButton.alloc().initWithFrame_(NSMakeRect(20, 10, 260, 28))
        self._update_dropdown()
        content.addSubview_(self.client_dropdown)

        self.select_btn = NSButton.alloc().initWithFrame_(NSMakeRect(290, 10, 90, 28))
        self.select_btn.setTitle_("Select")
        self.select_btn.setBezelStyle_(1)
        self.select_btn.setTarget_(self)
        self.select_btn.setAction_("onSelect:")
        content.addSubview_(self.select_btn)

    def _update_dropdown(self):
        self.client_dropdown.removeAllItems()
        for client in self.client_mgr.get_all():
            self.client_dropdown.addItemWithTitle_(client["name"])

    # IMPORTANT: selector name matches performSelector call
    def showPromptInternal_(self, args):
        client_id, client_name, confidence, prompt_data = args
        self.prompt_data = prompt_data
        self.guess_label.setStringValue_(f"{client_name} ({int(confidence * 100)}% confidence)")
        self._update_dropdown()
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        NSApp.runModalForWindow_(self)

    # Button handlers
    def onYes_(self, _sender):
        if self.prompt_data and self.callback:
            self.callback(True, self.prompt_data.get("client_id"), self.prompt_data.get("client_name"), self.prompt_data)
        NSApp.stopModal()
        self.orderOut_(None)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    def onNo_(self, _sender):
        if self.prompt_data and self.callback:
            self.callback(False, None, None, self.prompt_data)
        NSApp.stopModal()
        self.orderOut_(None)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    def onSelect_(self, _sender):
        selected_title = self.client_dropdown.titleOfSelectedItem()
        client = self.client_mgr.get_by_name(selected_title)
        if client and self.callback:
            self.callback(True, client["id"], client["name"], self.prompt_data)
        NSApp.stopModal()
        self.orderOut_(None)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


# ------------------------------------------------------------
# Client Management Window
# ------------------------------------------------------------
class ClientManagementWindow(NSWindow):
    """Window for managing clients (add/edit/delete)"""

    def initWithClientManager_callback_(self, client_mgr, callback):
        frame = NSMakeRect(100, 100, 500, 400)
        self = objc.super(ClientManagementWindow, self).initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered,
            False
        )
        if self is None:
            return None

        self.client_mgr = client_mgr
        self.callback = callback
        self.clients_data = []

        self.setTitle_("Manage Clients")
        self.setMinSize_(NSMakeSize(500, 400))

        self._setup_ui()
        self._refresh_table()
        return self

    def _setup_ui(self):
        content = self.contentView()

        scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 100, 460, 280))
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setAutohidesScrollers_(True)
        scroll_view.setBorderType_(1)

        self.table_view = NSTableView.alloc().initWithFrame_(scroll_view.bounds())
        self.table_view.setDelegate_(self)
        self.table_view.setDataSource_(self)

        col1 = NSTableColumn.alloc().initWithIdentifier_("name")
        col1.setTitle_("Client Name")
        col1.setWidth_(250)
        self.table_view.addTableColumn_(col1)

        col2 = NSTableColumn.alloc().initWithIdentifier_("code")
        col2.setTitle_("Code")
        col2.setWidth_(100)
        self.table_view.addTableColumn_(col2)

        scroll_view.setDocumentView_(self.table_view)
        content.addSubview_(scroll_view)

        add_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 65, 100, 20))
        add_label.setStringValue_("New Client:")
        add_label.setBezeled_(False)
        add_label.setDrawsBackground_(False)
        add_label.setEditable_(False)
        content.addSubview_(add_label)

        self.name_field = NSTextField.alloc().initWithFrame_(NSMakeRect(120, 65, 200, 24))
        self.name_field.setPlaceholderString_("Client Name")
        content.addSubview_(self.name_field)

        self.code_field = NSTextField.alloc().initWithFrame_(NSMakeRect(330, 65, 80, 24))
        self.code_field.setPlaceholderString_("Code")
        content.addSubview_(self.code_field)

        add_btn = NSButton.alloc().initWithFrame_(NSMakeRect(420, 65, 60, 24))
        add_btn.setTitle_("Add")
        add_btn.setBezelStyle_(1)
        add_btn.setTarget_(self)
        add_btn.setAction_("onAdd:")
        content.addSubview_(add_btn)

        delete_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, 20, 100, 32))
        delete_btn.setTitle_("Delete Selected")
        delete_btn.setBezelStyle_(1)
        delete_btn.setTarget_(self)
        delete_btn.setAction_("onDelete:")
        content.addSubview_(delete_btn)

        close_btn = NSButton.alloc().initWithFrame_(NSMakeRect(380, 20, 100, 32))
        close_btn.setTitle_("Close")
        close_btn.setBezelStyle_(1)
        close_btn.setTarget_(self)
        close_btn.setAction_("onClose:")
        content.addSubview_(close_btn)

    def _refresh_table(self):
        self.clients_data = self.client_mgr.get_all()
        if hasattr(self, 'table_view'):
            self.table_view.reloadData()

    # DataSource
    def numberOfRowsInTableView_(self, _table_view):
        return len(self.clients_data)

    def tableView_objectValueForTableColumn_row_(self, _table_view, table_column, row):
        client = self.clients_data[row]
        identifier = table_column.identifier()
        return client.get(identifier, "")

    # Actions
    def onAdd_(self, _sender):
        name = str(self.name_field.stringValue()).strip()
        code = str(self.code_field.stringValue()).strip()
        if not name:
            return
        self.client_mgr.add(name, code)
        self._refresh_table()
        self.name_field.setStringValue_("")
        self.code_field.setStringValue_("")
        if self.callback:
            self.callback()

    def onDelete_(self, _sender):
        row = self.table_view.selectedRow()
        if 0 <= row < len(self.clients_data):
            client = self.clients_data[row]
            self.client_mgr.delete(client["id"])
            self._refresh_table()
            if self.callback:
                self.callback()

    def onClose_(self, _sender):
        self.orderOut_(None)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


# ------------------------------------------------------------
# Today Time Window
# ------------------------------------------------------------
class TodayTimeWindow(NSWindow):
    """Window showing today's tracked time by client"""

    def initWithApiCallback_(self, api_callback):
        frame = NSMakeRect(100, 100, 500, 400)
        self = objc.super(TodayTimeWindow, self).initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered,
            False
        )
        if self is None:
            return None

        self.api_callback = api_callback
        self.time_data = []

        self.setTitle_("Today's Time Tracking")
        self.setMinSize_(NSMakeSize(500, 400))

        self._setup_ui()
        return self

    def _setup_ui(self):
        content = self.contentView()

        self.date_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 360, 460, 24))
        self.date_label.setStringValue_(datetime.now().strftime("%A, %B %d, %Y"))
        self.date_label.setBezeled_(False)
        self.date_label.setDrawsBackground_(False)
        self.date_label.setEditable_(False)
        content.addSubview_(self.date_label)

        scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 80, 460, 270))
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setAutohidesScrollers_(True)
        scroll_view.setBorderType_(1)

        self.table_view = NSTableView.alloc().initWithFrame_(scroll_view.bounds())
        self.table_view.setDelegate_(self)
        self.table_view.setDataSource_(self)

        col1 = NSTableColumn.alloc().initWithIdentifier_("client")
        col1.setTitle_("Client")
        col1.setWidth_(300)
        self.table_view.addTableColumn_(col1)

        col2 = NSTableColumn.alloc().initWithIdentifier_("time")
        col2.setTitle_("Time (hours)")
        col2.setWidth_(150)
        self.table_view.addTableColumn_(col2)

        scroll_view.setDocumentView_(self.table_view)
        content.addSubview_(scroll_view)

        self.total_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 50, 460, 20))
        self.total_label.setStringValue_("Total: 0.0 hours")
        self.total_label.setBezeled_(False)
        self.total_label.setDrawsBackground_(False)
        self.total_label.setEditable_(False)
        content.addSubview_(self.total_label)

        refresh_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, 10, 100, 32))
        refresh_btn.setTitle_("Refresh")
        refresh_btn.setBezelStyle_(1)
        refresh_btn.setTarget_(self)
        refresh_btn.setAction_("onRefresh:")
        content.addSubview_(refresh_btn)

        close_btn = NSButton.alloc().initWithFrame_(NSMakeRect(380, 10, 100, 32))
        close_btn.setTitle_("Close")
        close_btn.setBezelStyle_(1)
        close_btn.setTarget_(self)
        close_btn.setAction_("onClose:")
        content.addSubview_(close_btn)

    def show_and_refresh(self):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.onRefresh_(None)

    def onRefresh_(self, _sender):
        if self.api_callback:
            self.time_data = self.api_callback()
            self.table_view.reloadData()
            total_hours = sum(entry.get("hours", 0) for entry in self.time_data)
            self.total_label.setStringValue_(f"Total: {total_hours:.1f} hours")

    # DataSource
    def numberOfRowsInTableView_(self, _table_view):
        return len(self.time_data)

    def tableView_objectValueForTableColumn_row_(self, _table_view, table_column, row):
        entry = self.time_data[row]
        identifier = table_column.identifier()
        if identifier == "client":
            return entry.get("client", "Unknown")
        elif identifier == "time":
            return f"{entry.get('hours', 0):.2f}"
        return ""

    def onClose_(self, _sender):
        self.orderOut_(None)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)


# ------------------------------------------------------------
# Smart Prompt Controller
# ------------------------------------------------------------
class SmartPromptController:
    """
    Decides when to show a smart (AI) client suggestion modal.
    - Uses a callback to fetch an AI guess for the current context.
    - Applies a confidence threshold and cooldown so we don't nag.
    - Skips if suggestion matches current client.
    """
    def __init__(self, *, get_ai_guess_cb, get_current_client_cb,
                 show_prompt_cb, on_accept_cb, on_reject_cb,
                 min_confidence=0.70, cooldown_seconds=300):
        self.get_ai_guess_cb = get_ai_guess_cb               # () -> dict|None
        self.get_current_client_cb = get_current_client_cb   # () -> (id,name)
        self.show_prompt_cb = show_prompt_cb                 # (id,name,conf,meta) -> None
        self.on_accept_cb = on_accept_cb                     # (id,name,meta) -> None
        self.on_reject_cb = on_reject_cb                     # (meta) -> None
        self.min_confidence = float(min_confidence)
        self.cooldown_seconds = int(cooldown_seconds)

        self._last_prompt_ts = 0.0
        self._pending = False

    def maybe_prompt(self):
        now = _time.time()
        if self._pending:
            return
        if now - self._last_prompt_ts < self.cooldown_seconds:
            return

        guess = self.get_ai_guess_cb() if self.get_ai_guess_cb else None
        if not guess:
            return

        cid = guess.get("client_id")
        cname = guess.get("client_name")
        conf = float(guess.get("confidence", 0.0))
        if not cid or not cname or conf < self.min_confidence:
            return

        cur_id, _cur_name = self.get_current_client_cb()
        if cur_id == cid:
            return

        self._pending = True
        meta = {k: v for k, v in guess.items()}

        def _wrap_accept(client_id, client_name, prompt_data):
            self.on_accept_cb(client_id, client_name, prompt_data)
            self._pending = False
            self._last_prompt_ts = _time.time()

        def _wrap_reject(prompt_data):
            self.on_reject_cb(prompt_data)
            self._pending = False
            self._last_prompt_ts = _time.time()

        # Temporarily intercept callbacks
        self._orig_accept = self.on_accept_cb
        self._orig_reject = self.on_reject_cb
        self.on_accept_cb = _wrap_accept
        self.on_reject_cb = _wrap_reject

        try:
            self.show_prompt_cb(cid, cname, conf, meta)
        finally:
            self.on_accept_cb = self._orig_accept
            self.on_reject_cb = self._orig_reject


# ------------------------------------------------------------
# Menu Bar Controller
# ------------------------------------------------------------
class TimeTrackerMenuBar(NSObject):
    """Main menu bar controller"""

    def init(self):
        self = objc.super(TimeTrackerMenuBar, self).init()
        if self is None:
            return None

        self.client_mgr = ClientManager()
        self.state = GUIState()

        # External callbacks (set by run_gui_app)
        self.on_client_confirmed_callback = None
        self.on_client_rejected_callback = None
        self.get_today_time_callback = None
        self.get_ai_guess_callback = None

        self._setup_menu_bar()
        self._setup_windows()

        # Update menu every 2s
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, self, "updateMenu:", None, True
        )
        # AI tick every 15s
        self.smart_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            15.0, self, "smartTick:", None, True
        )

        return self

    def _setup_menu_bar(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("⏱")

        self.menu = NSMenu.alloc().init()

        self.current_client_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f"Client: {self.state.current_client_name}", None, ""
        )
        self.current_client_item.setEnabled_(False)
        self.menu.addItem_(self.current_client_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        switch_menu = NSMenu.alloc().init()
        self.switch_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Switch Client", None, ""
        )
        self.switch_menu_item.setSubmenu_(switch_menu)
        self.menu.addItem_(self.switch_menu_item)
        self.switch_submenu = switch_menu

        self.menu.addItem_(NSMenuItem.separatorItem())

        manage_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Manage Clients...", "onManageClients:", ""
        )
        manage_item.setTarget_(self)
        self.menu.addItem_(manage_item)

        today_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Today's Time...", "onTodayTime:", ""
        )
        today_item.setTarget_(self)
        self.menu.addItem_(today_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", ""
        )
        self.menu.addItem_(quit_item)

        self.status_item.setMenu_(self.menu)
        self._update_switch_submenu()

    def _setup_windows(self):
        self.prompt_window = FloatingPromptWindow.alloc().initWithClientManager_state_callback_(
            self.client_mgr, self.state, self._on_prompt_response
        )
        self.client_mgmt_window = ClientManagementWindow.alloc().initWithClientManager_callback_(
            self.client_mgr, self._on_clients_changed
        )
        self.today_time_window = TodayTimeWindow.alloc().initWithApiCallback_(
            self._get_today_time
        )

        def _get_ai_guess():
            if hasattr(self, "get_ai_guess_callback") and self.get_ai_guess_callback:
                try:
                    return self.get_ai_guess_callback()
                except Exception as e:
                    print(f"[AI] get_ai_guess_callback error: {e}")
                    return None
            return None

        def _get_current_client():
            return (self.state.current_client_id, self.state.current_client_name)

        self._smart = SmartPromptController(
            get_ai_guess_cb=_get_ai_guess,
            get_current_client_cb=_get_current_client,
            show_prompt_cb=self.show_client_prompt,
            on_accept_cb=lambda cid, cname, meta: self._on_prompt_response(True, cid, cname, meta),
            on_reject_cb=lambda meta: self._on_prompt_response(False, None, None, meta),
            min_confidence=0.75,
            cooldown_seconds=5 * 60
        )

    # --- tickers / actions / helpers ---
    def smartTick_(self, _timer):
        try:
            self._smart.maybe_prompt()
        except Exception as e:
            print(f"[AI] smartTick error: {e}")

    def _update_switch_submenu(self):
        self.switch_submenu.removeAllItems()

        clear_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Clear Client", "onSwitchClient:", ""
        )
        clear_item.setTarget_(self)
        clear_item.setTag_(0)
        self.switch_submenu.addItem_(clear_item)
        self.switch_submenu.addItem_(NSMenuItem.separatorItem())

        for client in self.client_mgr.get_all():
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                client["name"], "onSwitchClient:", ""
            )
            item.setTarget_(self)
            item.setTag_(client["id"])
            self.switch_submenu.addItem_(item)

    def updateMenu_(self, _timer):
        self.current_client_item.setTitle_(f"Client: {self.state.current_client_name}")

    def onSwitchClient_(self, sender):
        client_id = sender.tag()
        if client_id == 0:
            self.state.set_client(None, "No Client")
            print(f"[GUI] Client cleared locally")
            # Sync to backend
            if self.set_current_client_callback:
                try:
                    self.set_current_client_callback(0)
                    print(f"[GUI] Client cleared on backend")
                except Exception as e:
                    print(f"[GUI] Failed to clear client on backend: {e}")
        else:
            client = self.client_mgr.get_by_id(client_id)
            if client:
                self.state.set_client(client["id"], client["name"])
                print(f"[GUI] Switched to client: {client['name']}")
                # Sync to backend
                if self.set_current_client_callback:
                    try:
                        success = self.set_current_client_callback(client_id)
                        if success:
                            print(f"[GUI] Client synced to backend ✅")
                        else:
                            print(f"[GUI] Failed to sync client to backend")
                    except Exception as e:
                        print(f"[GUI] Error syncing to backend: {e}")
        self.updateMenu_(None)

    def onManageClients_(self, _sender):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self.client_mgmt_window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def onTodayTime_(self, _sender):
        self.today_time_window.show_and_refresh()

    def _on_clients_changed(self):
        self._update_switch_submenu()
        if self.prompt_window.isVisible():
            self.prompt_window._update_dropdown()

    def _on_prompt_response(self, confirmed: bool, client_id: Optional[int],
                            client_name: Optional[str], prompt_data: dict):
        print(f"[DEBUG] _on_prompt_response: confirmed={confirmed}, id={client_id}, name={client_name}")
        if confirmed and client_id and client_name:
            self.state.set_client(client_id, client_name)
            print(f"[GUI] Client confirmed: {client_name}")
            if self.on_client_confirmed_callback:
                self.on_client_confirmed_callback(client_id, client_name, prompt_data)
        else:
            print(f"[GUI] Client rejected")
            if self.on_client_rejected_callback:
                self.on_client_rejected_callback(prompt_data)

    def _get_today_time(self) -> List[Dict]:
        if self.get_today_time_callback:
            return self.get_today_time_callback()
        return []

    def show_client_prompt(self, client_id: int, client_name: str,
                           confidence: float, prompt_data: dict):
        args = (client_id, client_name, confidence, prompt_data)
        self.prompt_window.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showPromptInternal:", args, True
        )


# ------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------
def run_gui_app(on_client_confirmed: Callable,
                on_client_rejected: Callable,
                get_today_time: Callable,
                get_ai_guess: Callable = None,
                # NEW: Backend sync callbacks
                fetch_clients: Callable = None,
                set_current_client: Callable = None,
                get_current_client: Callable = None):
    """
    MODIFIED: Now accepts backend sync callbacks
    """
    if not GUI_AVAILABLE:
        print("[GUI] GUI components not available")
        return None

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    menu_bar = TimeTrackerMenuBar.alloc().init()
    menu_bar.on_client_confirmed_callback = on_client_confirmed
    menu_bar.on_client_rejected_callback = on_client_rejected
    menu_bar.get_today_time_callback = get_today_time
    menu_bar.get_ai_guess_callback = get_ai_guess
    
    # NEW: Set backend sync callbacks
    menu_bar.fetch_clients_callback = fetch_clients
    menu_bar.set_current_client_callback = set_current_client
    menu_bar.get_current_client_callback = get_current_client


    # ✅ ADD THESE 3 LINES:
    if fetch_clients:
        menu_bar.client_mgr.load(fetch_clients)
        menu_bar._update_switch_submenu()

    return menu_bar


# ------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------
if __name__ == "__main__":
    import random
    import time

    def test_confirmed(client_id, client_name, prompt_data):
        print(f"Test: Confirmed {client_name} (id={client_id}) reason={prompt_data.get('reason')}")

    def test_rejected(prompt_data):
        print("Test: Rejected", prompt_data)

    def test_get_today():
        return [
            {"client": "Acme Corp", "hours": 3.5},
            {"client": "Beta Industries", "hours": 2.0},
            {"client": "Gamma LLC", "hours": 1.25},
        ]

    # Simple AI stub (suggests Beta sometimes)
    def test_ai_guess():
        if random.random() < 0.40:
            return {
                "client_id": 2,
                "client_name": "Beta Industries",
                "confidence": 0.84,
                "reason": "Window matched 'beta-invoice.xlsx'",
            }
        return None

    menu_bar = run_gui_app(test_confirmed, test_rejected, test_get_today, get_ai_guess=test_ai_guess)

    if menu_bar:
        # Manual test prompt after 3s
        def show_test_prompt():
            time.sleep(3)
            menu_bar.show_client_prompt(
                1, "Acme Corp", 0.85,
                {"client_id": 1, "client_name": "Acme Corp", "confidence": 0.85, "reason": "manual test"}
            )
        threading.Thread(target=show_test_prompt, daemon=True).start()

        NSApp.run()
