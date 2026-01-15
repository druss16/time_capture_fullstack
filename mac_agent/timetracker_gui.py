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
- Device pairing GUI window
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
        NSScreen, NSVariableStatusItemLength, NSTableView, NSTableColumn,
        NSColor, NSFont
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
# Device Pairing Window
# ------------------------------------------------------------
class PairingWindow(NSWindow):
    """Window for entering pairing code to link device with web app"""

    def initWithCallback_(self, callback):
        width, height = 450, 280
        try:
            screen = NSScreen.mainScreen()
            screen_frame = screen.frame()
            x = (screen_frame.size.width - width) / 2
            y = (screen_frame.size.height - height) / 2
        except Exception:
            x, y = 100, 100

        frame = NSMakeRect(x, y, width, height)

        self = objc.super(PairingWindow, self).initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )
        if self is None:
            return None

        self.callback = callback
        self.pairing_success = False
        self.api_key = None

        self.setTitle_("TimeTracker - Device Pairing")
        self.setLevel_(NSFloatingWindowLevel)

        self._setup_ui()
        return self

    def _setup_ui(self):
        content = self.contentView()

        # Title
        title_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 220, 410, 30))
        title_label.setStringValue_("🔗 Link This Device")
        title_label.setBezeled_(False)
        title_label.setDrawsBackground_(False)
        title_label.setEditable_(False)
        title_label.setSelectable_(False)
        title_label.setFont_(NSFont.boldSystemFontOfSize_(18))
        content.addSubview_(title_label)

        # Instructions
        instructions = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 160, 410, 50))
        instructions.setStringValue_(
            "Enter the pairing code from the TimeTracker web app.\n"
            "You can find this in Settings → Devices → Add Device."
        )
        instructions.setBezeled_(False)
        instructions.setDrawsBackground_(False)
        instructions.setEditable_(False)
        instructions.setSelectable_(False)
        content.addSubview_(instructions)

        # Code label
        code_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 125, 100, 24))
        code_label.setStringValue_("Pairing Code:")
        code_label.setBezeled_(False)
        code_label.setDrawsBackground_(False)
        code_label.setEditable_(False)
        content.addSubview_(code_label)

        # Code input field
        self.code_field = NSTextField.alloc().initWithFrame_(NSMakeRect(125, 125, 200, 24))
        self.code_field.setPlaceholderString_("e.g. ABC123")
        self.code_field.setFont_(NSFont.monospacedSystemFontOfSize_weight_(14, 0.5))
        content.addSubview_(self.code_field)

        # Pair button
        self.pair_btn = NSButton.alloc().initWithFrame_(NSMakeRect(335, 123, 90, 28))
        self.pair_btn.setTitle_("Pair Device")
        self.pair_btn.setBezelStyle_(1)
        self.pair_btn.setTarget_(self)
        self.pair_btn.setAction_("onPair:")
        content.addSubview_(self.pair_btn)

        # Status label
        self.status_label = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 85, 410, 24))
        self.status_label.setStringValue_("")
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        self.status_label.setEditable_(False)
        self.status_label.setSelectable_(False)
        content.addSubview_(self.status_label)

        # Cancel button
        cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, 20, 100, 32))
        cancel_btn.setTitle_("Cancel")
        cancel_btn.setBezelStyle_(1)
        cancel_btn.setTarget_(self)
        cancel_btn.setAction_("onCancel:")
        content.addSubview_(cancel_btn)

        # Continue button (hidden until paired)
        self.continue_btn = NSButton.alloc().initWithFrame_(NSMakeRect(325, 20, 100, 32))
        self.continue_btn.setTitle_("Continue")
        self.continue_btn.setBezelStyle_(1)
        self.continue_btn.setTarget_(self)
        self.continue_btn.setAction_("onContinue:")
        self.continue_btn.setHidden_(True)
        content.addSubview_(self.continue_btn)

    def onPair_(self, _sender):
        code = str(self.code_field.stringValue()).strip().upper()
        if not code:
            self.status_label.setStringValue_("⚠️ Please enter a pairing code")
            self.status_label.setTextColor_(NSColor.systemOrangeColor())
            return

        self.status_label.setStringValue_("⏳ Pairing...")
        self.status_label.setTextColor_(NSColor.systemGrayColor())
        self.pair_btn.setEnabled_(False)

        # Run pairing in background thread
        def _do_pair():
            try:
                if self.callback:
                    result = self.callback(code)
                    self.performSelectorOnMainThread_withObject_waitUntilDone_(
                        "handlePairResult:", result, False
                    )
            except Exception as e:
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "handlePairResult:", {"error": str(e)}, False
                )

        threading.Thread(target=_do_pair, daemon=True).start()

    def handlePairResult_(self, result):
        self.pair_btn.setEnabled_(True)

        if result and result.get("api_key"):
            self.pairing_success = True
            self.api_key = result.get("api_key")
            self.status_label.setStringValue_("✅ Device paired successfully!")
            self.status_label.setTextColor_(NSColor.systemGreenColor())
            self.continue_btn.setHidden_(False)
            self.pair_btn.setHidden_(True)
            
            # Show additional info if available
            username = result.get("username", "")
            org = result.get("org_name", "")
            if username or org:
                info = f"✅ Paired as {username}"
                if org:
                    info += f" ({org})"
                self.status_label.setStringValue_(info)
        else:
            error = result.get("error", "Pairing failed") if result else "Pairing failed"
            self.status_label.setStringValue_(f"❌ {error}")
            self.status_label.setTextColor_(NSColor.systemRedColor())

    def onCancel_(self, _sender):
        self.pairing_success = False
        # Only stop modal if actually running modally
        if NSApp.modalWindow() == self:
            NSApp.stopModal()
        self.orderOut_(None)

    def onContinue_(self, _sender):
        # Only stop modal if actually running modally
        if NSApp.modalWindow() == self:
            NSApp.stopModal()
        self.orderOut_(None)

    def runModal(self) -> Optional[str]:
        """Show window modally and return api_key on success, None on cancel"""
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        NSApp.runModalForWindow_(self)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        
        if self.pairing_success:
            return self.api_key
        return None


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

    def onRefresh_(self, _sender):
        if self.api_callback:
            self.time_data = self.api_callback()
            self.table_view.reloadData()
            total_hours = sum(entry.get("total_hours", 0) for entry in self.time_data)
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
            return f"{entry.get('total_hours', 0):.2f}"
        return ""

    def onClose_(self, _sender):
        self.orderOut_(None)


# ------------------------------------------------------------
# Smart Prompt Controller
# ------------------------------------------------------------
class SmartPromptController:
    """
    Decides when to show a smart (AI) client suggestion modal.
    """
    def __init__(self, *, get_ai_guess_cb, get_current_client_cb,
                 show_prompt_cb, on_accept_cb, on_reject_cb,
                 min_confidence=0.70, cooldown_seconds=300):
        self.get_ai_guess_cb = get_ai_guess_cb
        self.get_current_client_cb = get_current_client_cb
        self.show_prompt_cb = show_prompt_cb
        self.on_accept_cb = on_accept_cb
        self.on_reject_cb = on_reject_cb
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

        self.open_windows = []

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

        today_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Today's Time...", "onTodayTime:", ""
        )
        today_item.setTarget_(self)
        self.menu.addItem_(today_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        repair_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Re-pair Device...", "onRepairDevice:", ""
        )
        repair_item.setTarget_(self)
        self.menu.addItem_(repair_item)

        self.menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", ""
        )
        self.menu.addItem_(quit_item)

        self.status_item.setMenu_(self.menu)
        self._update_switch_submenu()

    def _setup_windows(self):
        """Initialize window references to None - create on demand"""
        self.prompt_window = None
        self.client_mgmt_window = None
        self.today_time_window = None
        
        # Smart controller setup
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
        """Show client management - RECREATE every time"""
        window = ClientManagementWindow.alloc().initWithClientManager_callback_(
            self.client_mgr, self._on_clients_changed
        )
        self.open_windows.append(window)
        window.center()
        window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def onTodayTime_(self, _sender):
        window = TodayTimeWindow.alloc().initWithApiCallback_(self._get_today_time)
        self.open_windows.append(window)
        window.center()
        window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        window.onRefresh_(None)

    def onRepairDevice_(self, _sender):
        """Show pairing window to re-pair device (non-modal)"""
        if hasattr(self, 'repair_callback') and self.repair_callback:
            # Create pairing window but don't run modal - just show it
            window = PairingWindow.alloc().initWithCallback_(self.repair_callback)
            self.open_windows.append(window)
            
            # Override the continue button to refresh clients
            original_continue = window.onContinue_
            def on_continue_wrapper(sender):
                original_continue(sender)
                if window.api_key:
                    print(f"[GUI] Device re-paired successfully")
                    if hasattr(self, 'fetch_clients_callback') and self.fetch_clients_callback:
                        self.client_mgr.load(self.fetch_clients_callback)
                        self._update_switch_submenu()
            
            window.center()
            window.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
        else:
            print("[GUI] No repair callback configured")

    def show_client_prompt(self, client_id: int, client_name: str,
                           confidence: float, prompt_data: dict):
        """Show prompt window - RECREATE every time"""
        window = FloatingPromptWindow.alloc().initWithClientManager_state_callback_(
            self.client_mgr, self.state, self._on_prompt_response
        )
        self.open_windows.append(window)
        args = (client_id, client_name, confidence, prompt_data)
        window.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showPromptInternal:", args, True
        )
        NSApp.activateIgnoringOtherApps_(True)
    

    def _on_clients_changed(self):
        self._update_switch_submenu()

    def _on_prompt_response(self, confirmed: bool, client_id: Optional[int],
                            client_name: Optional[str], prompt_data: dict):
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

    def refresh_client_menu(self, clients):
        """Called by sync to update client list"""
        self.client_mgr.clients = clients
        self._update_switch_submenu()


# ------------------------------------------------------------
# GUI Pairing Function (called from main.py)
# ------------------------------------------------------------
def show_pairing_window(pair_callback: Callable) -> Optional[str]:
    """
    Show the pairing window and return the api_key on success.
    
    Args:
        pair_callback: Function that takes (code) and returns 
                      {"api_key": str, "username": str, "org_name": str} on success
                      or {"error": str} on failure
    
    Returns:
        api_key string on success, None on cancel/failure
    """
    if not GUI_AVAILABLE:
        print("[GUI] GUI not available for pairing window")
        return None
    
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    
    window = PairingWindow.alloc().initWithCallback_(pair_callback)
    return window.runModal()


# ------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------
def run_gui_app(on_client_confirmed: Callable,
                on_client_rejected: Callable,
                get_today_time: Callable,
                get_ai_guess: Callable = None,
                fetch_clients: Callable = None,
                set_current_client: Callable = None,
                get_current_client: Callable = None,
                repair_callback: Callable = None,
                cpa_tools_data: dict = None,
                sync=None):  # Keep param for backwards compat
    """
    Initialize and run the GUI menu bar app.
    """
    if not GUI_AVAILABLE:
        print("[GUI] GUI components not available")
        return None

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    menu_bar = TimeTrackerMenuBar.alloc().init()
    menu_bar.on_client_confirmed_callback = on_client_confirmed
    menu_bar.on_client_rejected_callback = on_client_rejected
    menu_bar.get_today_time_callback = get_today_time
    menu_bar.get_ai_guess_callback = get_ai_guess
    
    # Backend sync callbacks
    menu_bar.fetch_clients_callback = fetch_clients
    menu_bar.set_current_client_callback = set_current_client
    menu_bar.get_current_client_callback = get_current_client
    menu_bar.repair_callback = repair_callback

    if sync:
        print(f"[GUI DEBUG] Setting gui_menu_bar on sync id={id(sync)}")
        sync.gui_menu_bar = menu_bar
        print(f"[GUI] Registered with sync")

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
            {"client": "Acme Corp", "total_hours": 3.5},
            {"client": "Beta Industries", "total_hours": 2.0},
            {"client": "Gamma LLC", "total_hours": 1.25},
        ]

    def test_ai_guess():
        if random.random() < 0.40:
            return {
                "client_id": 2,
                "client_name": "Beta Industries",
                "confidence": 0.84,
                "reason": "Window matched 'beta-invoice.xlsx'",
            }
        return None

    def test_pair(code):
        print(f"Test pairing with code: {code}")
        time.sleep(1)  # Simulate network
        if code == "TEST123":
            return {"api_key": "test-key-123", "username": "testuser", "org_name": "Test Org"}
        else:
            return {"error": "Invalid pairing code"}

    # Test pairing window
    print("Testing pairing window...")
    result = show_pairing_window(test_pair)
    print(f"Pairing result: {result}")

    if result:
        menu_bar = run_gui_app(test_confirmed, test_rejected, test_get_today, get_ai_guess=test_ai_guess)

        if menu_bar:
            def show_test_prompt():
                time.sleep(3)
                menu_bar.show_client_prompt(
                    1, "Acme Corp", 0.85,
                    {"client_id": 1, "client_name": "Acme Corp", "confidence": 0.85, "reason": "manual test"}
                )
            threading.Thread(target=show_test_prompt, daemon=True).start()

            NSApp.run()