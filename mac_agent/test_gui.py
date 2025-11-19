#!/usr/bin/env python3
"""Test table view - likely crash point"""

import objc
from AppKit import (
    NSApplication, NSStatusBar, NSMenu, NSMenuItem,
    NSApplicationActivationPolicyAccessory, NSVariableStatusItemLength,
    NSWindow, NSTableView, NSTableColumn, NSScrollView,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
    NSBackingStoreBuffered
)
from Foundation import NSObject, NSMakeRect

class TestWindow(NSWindow):
    def initWithDelegate_(self, delegate):
        frame = NSMakeRect(100, 100, 400, 300)
        self = objc.super(TestWindow, self).initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False
        )
        if self is None:
            return None
        
        self.delegate_obj = delegate
        self.setTitle_("Test Table")
        
        content = self.contentView()
        
        # Create table view
        scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 20, 360, 260))
        scroll_view.setHasVerticalScroller_(True)
        
        self.table_view = NSTableView.alloc().initWithFrame_(scroll_view.bounds())
        
        # ✅ THIS IS THE CRASH POINT - setting Python object as delegate
        self.table_view.setDelegate_(self.delegate_obj)
        self.table_view.setDataSource_(self.delegate_obj)
        
        col1 = NSTableColumn.alloc().initWithIdentifier_("name")
        col1.setTitle_("Name")
        col1.setWidth_(200)
        self.table_view.addTableColumn_(col1)
        
        scroll_view.setDocumentView_(self.table_view)
        content.addSubview_(scroll_view)
        
        print("[TEST] Table window created")
        return self

class TestMenuBar(NSObject):
    def init(self):
        self = objc.super(TestMenuBar, self).init()
        if self is None:
            return None
        
        self.data = ["Item 1", "Item 2", "Item 3"]

        self.windows = []

        
        # Menu bar
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setTitle_("⏱")
        
        self.menu = NSMenu.alloc().init()
        
        show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Show Table", "onShow:", ""
        )
        show_item.setTarget_(self)
        self.menu.addItem_(show_item)
        
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", ""
        )
        self.menu.addItem_(quit_item)
        
        self.status_item.setMenu_(self.menu)
        
        # Create window but don't show yet
        self.window = TestWindow.alloc().initWithDelegate_(self)
        
        print("[TEST] Menu bar created")
        return self
    
    def onShow_(self, sender):
        print("[TEST] Showing window...")
        # Create new window
        window = TestWindow.alloc().initWithDelegate_(self)
        
        # ✅ CRITICAL: Keep reference so it doesn't get garbage collected
        self.windows.append(window)
        
        window.center()
        window.makeKeyAndOrderFront_(None)
    
    # Table view delegate methods
    def numberOfRowsInTableView_(self, table_view):
        return len(self.data)
    
    def tableView_objectValueForTableColumn_row_(self, table_view, table_column, row):
        return self.data[row]

if __name__ == "__main__":
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    
    menu_bar = TestMenuBar.alloc().init()
    
    print("[TEST] Starting event loop...")
    app.run()