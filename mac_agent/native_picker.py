#!/usr/bin/env python3
"""
Native macOS Client Picker using AppKit
- Proper trackpad scrolling
- Native look and feel
"""

import objc
from AppKit import (
    NSApplication, NSApp, NSWindow, NSPanel,
    NSView, NSTextField, NSScrollView, NSTableView,
    NSTableColumn, NSButton, NSFont, NSColor,
    NSBackingStoreBuffered, NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
    NSWindowStyleMaskUtilityWindow, NSBorderlessWindowMask,
    NSTableViewSelectionHighlightStyleRegular,
    NSBezelStyleRounded, NSTextFieldCell,
    NSLayoutConstraint, NSStackView,
    NSUserInterfaceLayoutOrientationVertical,
    NSUserInterfaceLayoutOrientationHorizontal,
    NSLayoutAttributeTop, NSLayoutAttributeBottom,
    NSLayoutAttributeLeading, NSLayoutAttributeTrailing,
    NSLayoutAttributeWidth, NSLayoutAttributeHeight,
    NSLayoutRelationEqual, NSViewWidthSizable, NSViewHeightSizable,
    NSTableViewStylePlain, NSLineBreakByTruncatingTail,
)
from Foundation import NSObject, NSRect, NSPoint, NSSize, NSMakeRect, NSIndexSet
import threading


class ClientPickerDelegate(NSObject):
    """Delegate for table view and window"""
    
    def initWithClients_callback_(self, clients, callback):
        self = objc.super(ClientPickerDelegate, self).init()
        if self is None:
            return None
        self.clients = clients
        self.filtered_clients = list(clients)
        self.callback = callback
        self.selected_client = None
        self.window = None
        self.table_view = None
        self.search_field = None
        return self
    
    # NSTableViewDataSource methods
    def numberOfRowsInTableView_(self, table_view):
        return len(self.filtered_clients)
    
    def tableView_objectValueForTableColumn_row_(self, table_view, column, row):
        if row < 0 or row >= len(self.filtered_clients):
            return ""
        client = self.filtered_clients[row]
        col_id = column.identifier()
        if col_id == "name":
            return client.get("name", "Unknown")
        elif col_id == "code":
            return client.get("code", "")
        return ""
    
    # NSTableViewDelegate methods
    def tableViewSelectionDidChange_(self, notification):
        table = notification.object()
        row = table.selectedRow()
        if row >= 0 and row < len(self.filtered_clients):
            self.selected_client = self.filtered_clients[row]
    
    def tableView_shouldSelectRow_(self, table_view, row):
        return True
    
    # Double-click handler
    def tableViewDoubleClick_(self, sender):
        row = sender.clickedRow()
        if row >= 0 and row < len(self.filtered_clients):
            self.selected_client = self.filtered_clients[row]
            self.confirmSelection_(None)
    
    # Search field action
    def searchFieldChanged_(self, sender):
        query = sender.stringValue().lower().strip()
        if query:
            self.filtered_clients = [
                c for c in self.clients
                if query in c.get("name", "").lower() or query in c.get("code", "").lower()
            ]
        else:
            self.filtered_clients = list(self.clients)
        self.table_view.reloadData()
    
    # Button actions
    def confirmSelection_(self, sender):
        if self.selected_client and self.callback:
            self.callback(self.selected_client.get("id"), self.selected_client.get("name"))
        self.window.close()
        NSApp.stopModal()
    
    def cancelSelection_(self, sender):
        self.selected_client = None
        self.window.close()
        NSApp.stopModal()
    
    def clearSelection_(self, sender):
        if self.callback:
            self.callback(0, "No Client")
        self.window.close()
        NSApp.stopModal()
    
    # Window delegate
    def windowWillClose_(self, notification):
        NSApp.stopModal()


def show_native_picker(clients: list, callback) -> None:
    """
    Show native macOS client picker.
    
    Args:
        clients: List of client dicts with 'id', 'name', 'code'
        callback: Function to call with (client_id, client_name) on selection
    """
    
    # Ensure we're on main thread
    if not NSThread.isMainThread():
        from PyObjCTools import AppHelper
        AppHelper.callAfter(lambda: show_native_picker(clients, callback))
        return
    
    # Create delegate
    delegate = ClientPickerDelegate.alloc().initWithClients_callback_(clients, callback)
    
    # Window dimensions
    width = 400
    height = 500
    
    # Get screen center
    screen = NSScreen.mainScreen()
    screen_rect = screen.visibleFrame()
    x = screen_rect.origin.x + (screen_rect.size.width - width) / 2
    y = screen_rect.origin.y + (screen_rect.size.height - height) / 2
    
    # Create window
    rect = NSMakeRect(x, y, width, height)
    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable
    window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, style, NSBackingStoreBuffered, False
    )
    window.setTitle_("Select Client")
    window.setDelegate_(delegate)
    window.setMinSize_(NSSize(300, 400))
    delegate.window = window
    
    # Dark appearance
    window.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(0.15, 0.15, 0.17, 1.0))
    
    content = window.contentView()
    content.setWantsLayer_(True)
    
    # Search field at top
    search_field = NSTextField.alloc().initWithFrame_(NSMakeRect(20, height - 50, width - 40, 28))
    search_field.setPlaceholderString_("Search clients...")
    search_field.setTarget_(delegate)
    search_field.setAction_(objc.selector(delegate.searchFieldChanged_, signature=b'v@:@'))
    search_field.setFocusRingType_(1)  # None
    content.addSubview_(search_field)
    delegate.search_field = search_field
    
    # Scroll view with table
    scroll_rect = NSMakeRect(20, 60, width - 40, height - 130)
    scroll_view = NSScrollView.alloc().initWithFrame_(scroll_rect)
    scroll_view.setHasVerticalScroller_(True)
    scroll_view.setHasHorizontalScroller_(False)
    scroll_view.setBorderType_(0)  # No border
    scroll_view.setAutohidesScrollers_(True)
    
    # Table view
    table_rect = NSMakeRect(0, 0, scroll_rect.size.width, scroll_rect.size.height)
    table_view = NSTableView.alloc().initWithFrame_(table_rect)
    table_view.setDataSource_(delegate)
    table_view.setDelegate_(delegate)
    table_view.setRowHeight_(36)
    table_view.setGridStyleMask_(0)  # No grid
    table_view.setSelectionHighlightStyle_(NSTableViewSelectionHighlightStyleRegular)
    table_view.setBackgroundColor_(NSColor.clearColor())
    table_view.setDoubleAction_(objc.selector(delegate.tableViewDoubleClick_, signature=b'v@:@'))
    table_view.setTarget_(delegate)
    delegate.table_view = table_view
    
    # Name column
    name_col = NSTableColumn.alloc().initWithIdentifier_("name")
    name_col.setTitle_("Client")
    name_col.setWidth_(scroll_rect.size.width - 80)
    name_col.setMinWidth_(150)
    table_view.addTableColumn_(name_col)
    
    # Code column
    code_col = NSTableColumn.alloc().initWithIdentifier_("code")
    code_col.setTitle_("Code")
    code_col.setWidth_(60)
    code_col.setMinWidth_(40)
    table_view.addTableColumn_(code_col)
    
    # Hide header
    table_view.setHeaderView_(None)
    
    scroll_view.setDocumentView_(table_view)
    content.addSubview_(scroll_view)
    
    # Buttons at bottom
    btn_y = 15
    btn_height = 32
    
    # Cancel button
    cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, btn_y, 80, btn_height))
    cancel_btn.setTitle_("Cancel")
    cancel_btn.setBezelStyle_(NSBezelStyleRounded)
    cancel_btn.setTarget_(delegate)
    cancel_btn.setAction_(objc.selector(delegate.cancelSelection_, signature=b'v@:@'))
    content.addSubview_(cancel_btn)
    
    # Clear button
    clear_btn = NSButton.alloc().initWithFrame_(NSMakeRect(110, btn_y, 100, btn_height))
    clear_btn.setTitle_("Clear Client")
    clear_btn.setBezelStyle_(NSBezelStyleRounded)
    clear_btn.setTarget_(delegate)
    clear_btn.setAction_(objc.selector(delegate.clearSelection_, signature=b'v@:@'))
    content.addSubview_(clear_btn)
    
    # OK button
    ok_btn = NSButton.alloc().initWithFrame_(NSMakeRect(width - 100, btn_y, 80, btn_height))
    ok_btn.setTitle_("OK")
    ok_btn.setBezelStyle_(NSBezelStyleRounded)
    ok_btn.setTarget_(delegate)
    ok_btn.setAction_(objc.selector(delegate.confirmSelection_, signature=b'v@:@'))
    ok_btn.setKeyEquivalent_("\r")  # Enter key
    content.addSubview_(ok_btn)
    
    # Show window
    window.makeKeyAndOrderFront_(None)
    window.makeFirstResponder_(search_field)
    
    # Run modal
    NSApp.runModalForWindow_(window)


# Test
if __name__ == "__main__":
    from AppKit import NSScreen, NSThread
    
    # Ensure NSApp exists
    app = NSApplication.sharedApplication()
    
    # Test clients
    test_clients = [
        {"id": 1, "name": "Acme Corporation", "code": "ACME"},
        {"id": 2, "name": "Beta Industries", "code": "BETA"},
        {"id": 3, "name": "Charlie's Widgets", "code": "CHAR"},
        {"id": 4, "name": "Delta Services", "code": "DELT"},
        {"id": 5, "name": "Echo Partners", "code": "ECHO"},
        {"id": 6, "name": "Foxtrot LLC", "code": "FOXT"},
        {"id": 7, "name": "Golf Enterprises", "code": "GOLF"},
        {"id": 8, "name": "Hotel Group", "code": "HOTL"},
        {"id": 9, "name": "India Tech", "code": "INDI"},
        {"id": 10, "name": "Juliet Consulting", "code": "JULI"},
        {"id": 11, "name": "Kilo Manufacturing", "code": "KILO"},
        {"id": 12, "name": "Lima Financial", "code": "LIMA"},
        {"id": 13, "name": "Mike & Associates", "code": "MIKE"},
        {"id": 14, "name": "November Corp", "code": "NOVR"},
        {"id": 15, "name": "Oscar Holdings", "code": "OSCR"},
    ]
    
    def on_select(client_id, client_name):
        print(f"Selected: {client_name} (ID: {client_id})")
    
    print("Opening native picker...")
    show_native_picker(test_clients, on_select)
    print("Done!")