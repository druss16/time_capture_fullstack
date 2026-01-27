#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Custom Dark Tray Menu - Compact dark themed menu for system tray
"""

import tkinter as tk
from tkinter import font as tkfont

COLORS = {
    "bg": "#1A1A1A",
    "bg_hover": "#2D2D2D",
    "text": "#FFFFFF",
    "text_muted": "#888888",
    "separator": "#333333",
    "primary": "#14B8A6",
}


class DarkTrayMenu:
    """
    Custom dark themed popup menu for system tray.
    Compact and matches the app's dark theme.
    """
    
    def __init__(self):
        self.root = None
        self.menu_window = None
        self.items = []
        self._on_close_callback = None
        
    def set_items(self, items):
        """
        Set menu items.
        
        items: list of dicts with keys:
            - text: str
            - command: callable (None for separator)
            - submenu: list of items (optional)
            - shortcut: str (optional, e.g. "Alt+Ctrl+T")
            - checked: bool (optional, shows bullet)
        """
        self.items = items
    
    def show(self, x, y, on_close=None):
        """Show the menu at screen position (x, y)"""
        self._on_close_callback = on_close
        
        # Create hidden root if needed
        if not self.root:
            self.root = tk.Tk()
            self.root.withdraw()
        
        # Destroy existing menu
        if self.menu_window:
            try:
                self.menu_window.destroy()
            except:
                pass
        
        # Create menu window
        self.menu_window = tk.Toplevel(self.root)
        self.menu_window.overrideredirect(True)
        self.menu_window.attributes('-topmost', True)
        self.menu_window.configure(bg=COLORS["bg"])
        
        # Build menu content
        self._build_menu(self.menu_window, self.items)
        
        # Update to get size
        self.menu_window.update_idletasks()
        
        # Position menu (adjust if near screen edge)
        menu_width = self.menu_window.winfo_reqwidth()
        menu_height = self.menu_window.winfo_reqheight()
        screen_width = self.menu_window.winfo_screenwidth()
        screen_height = self.menu_window.winfo_screenheight()
        
        # Position above the click point (like Windows tray menus)
        final_x = min(x, screen_width - menu_width - 5)
        final_y = y - menu_height - 5
        
        if final_y < 0:
            final_y = y + 5  # Show below if not enough space above
        
        self.menu_window.geometry(f"+{final_x}+{final_y}")
        
        # Close menu when clicking outside
        self.menu_window.bind('<FocusOut>', lambda e: self._close())
        self.menu_window.focus_set()
        
        # Also close on Escape
        self.menu_window.bind('<Escape>', lambda e: self._close())
    
    def _build_menu(self, parent, items, is_submenu=False):
        """Build menu items"""
        frame = tk.Frame(parent, bg=COLORS["bg"], padx=2, pady=2)
        frame.pack(fill="both", expand=True)
        
        # Add subtle border
        if not is_submenu:
            frame.configure(highlightbackground=COLORS["separator"], highlightthickness=1)
        
        for item in items:
            if item.get("separator"):
                # Separator line
                sep = tk.Frame(frame, bg=COLORS["separator"], height=1)
                sep.pack(fill="x", padx=5, pady=3)
            elif item.get("submenu"):
                # Submenu item
                self._create_submenu_item(frame, item)
            else:
                # Regular item
                self._create_menu_item(frame, item)
    
    def _create_menu_item(self, parent, item):
        """Create a single menu item"""
        text = item.get("text", "")
        command = item.get("command")
        shortcut = item.get("shortcut", "")
        checked = item.get("checked", False)
        
        # Container frame
        item_frame = tk.Frame(parent, bg=COLORS["bg"], cursor="hand2")
        item_frame.pack(fill="x")
        
        # Prefix (bullet for checked items)
        prefix = "● " if checked else "  "
        
        # Main label
        label = tk.Label(
            item_frame,
            text=f"{prefix}{text}",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
            anchor="w",
            padx=8,
            pady=4
        )
        label.pack(side="left", fill="x", expand=True)
        
        # Shortcut label (right side)
        if shortcut:
            shortcut_label = tk.Label(
                item_frame,
                text=shortcut,
                bg=COLORS["bg"],
                fg=COLORS["text_muted"],
                font=("Segoe UI", 8),
                anchor="e",
                padx=8,
                pady=4
            )
            shortcut_label.pack(side="right")
            shortcut_label.bind('<Enter>', lambda e, f=item_frame: self._on_hover(f, True))
            shortcut_label.bind('<Leave>', lambda e, f=item_frame: self._on_hover(f, False))
            shortcut_label.bind('<Button-1>', lambda e, cmd=command: self._on_click(cmd))
        
        # Hover effects
        item_frame.bind('<Enter>', lambda e, f=item_frame: self._on_hover(f, True))
        item_frame.bind('<Leave>', lambda e, f=item_frame: self._on_hover(f, False))
        label.bind('<Enter>', lambda e, f=item_frame: self._on_hover(f, True))
        label.bind('<Leave>', lambda e, f=item_frame: self._on_hover(f, False))
        
        # Click handler
        item_frame.bind('<Button-1>', lambda e, cmd=command: self._on_click(cmd))
        label.bind('<Button-1>', lambda e, cmd=command: self._on_click(cmd))
    
    def _create_submenu_item(self, parent, item):
        """Create a submenu item with arrow"""
        text = item.get("text", "")
        submenu_items = item.get("submenu", [])
        
        # Container frame
        item_frame = tk.Frame(parent, bg=COLORS["bg"], cursor="hand2")
        item_frame.pack(fill="x")
        
        # Main label
        label = tk.Label(
            item_frame,
            text=f"  {text}",
            bg=COLORS["bg"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
            anchor="w",
            padx=8,
            pady=4
        )
        label.pack(side="left", fill="x", expand=True)
        
        # Arrow indicator
        arrow = tk.Label(
            item_frame,
            text="›",
            bg=COLORS["bg"],
            fg=COLORS["text_muted"],
            font=("Segoe UI", 10),
            padx=8
        )
        arrow.pack(side="right")
        
        # Submenu window reference
        submenu_window = [None]
        
        def show_submenu(event=None):
            # Close existing submenu
            if submenu_window[0]:
                try:
                    submenu_window[0].destroy()
                except:
                    pass
            
            # Create submenu
            submenu_window[0] = tk.Toplevel(self.menu_window)
            submenu_window[0].overrideredirect(True)
            submenu_window[0].attributes('-topmost', True)
            submenu_window[0].configure(bg=COLORS["bg"])
            
            # Build submenu content
            self._build_menu(submenu_window[0], submenu_items, is_submenu=True)
            
            # Position to the right of parent item
            submenu_window[0].update_idletasks()
            x = self.menu_window.winfo_x() + self.menu_window.winfo_width() - 5
            y = item_frame.winfo_rooty() - 2
            submenu_window[0].geometry(f"+{x}+{y}")
        
        def hide_submenu(event=None):
            if submenu_window[0]:
                try:
                    submenu_window[0].destroy()
                except:
                    pass
                submenu_window[0] = None
        
        # Hover effects
        item_frame.bind('<Enter>', lambda e: (self._on_hover(item_frame, True), show_submenu()))
        item_frame.bind('<Leave>', lambda e: self._on_hover(item_frame, False))
        label.bind('<Enter>', lambda e: (self._on_hover(item_frame, True), show_submenu()))
        arrow.bind('<Enter>', lambda e: (self._on_hover(item_frame, True), show_submenu()))
    
    def _on_hover(self, frame, entering):
        """Handle hover effect"""
        bg = COLORS["bg_hover"] if entering else COLORS["bg"]
        frame.configure(bg=bg)
        for child in frame.winfo_children():
            try:
                child.configure(bg=bg)
            except:
                pass
    
    def _on_click(self, command):
        """Handle menu item click"""
        self._close()
        if command:
            try:
                command()
            except Exception as e:
                print(f"[MENU] Error executing command: {e}")
    
    def _close(self):
        """Close the menu"""
        if self.menu_window:
            try:
                self.menu_window.destroy()
            except:
                pass
            self.menu_window = None
        
        if self._on_close_callback:
            self._on_close_callback()
    
    def destroy(self):
        """Clean up"""
        self._close()
        if self.root:
            try:
                self.root.destroy()
            except:
                pass
            self.root = None


# Test
if __name__ == "__main__":
    menu = DarkTrayMenu()
    
    menu.set_items([
        {"text": "Search Clients...", "shortcut": "Alt+Ctrl+T", "command": lambda: print("Search!")},
        {"text": "Switch Client", "submenu": [
            {"text": "Clear Client", "command": lambda: print("Clear")},
            {"separator": True},
            {"text": "MAVOPS", "checked": True, "command": lambda: print("MAVOPS")},
            {"text": "Acme Corp", "command": lambda: print("Acme")},
        ]},
        {"text": "Today's Time...", "command": lambda: print("Today")},
        {"separator": True},
        {"text": "Show Client Widget", "command": lambda: print("Widget")},
        {"separator": True},
        {"text": "Quit", "command": lambda: menu.destroy()},
    ])
    
    # Show at mouse position
    root = tk.Tk()
    root.withdraw()
    
    def show_menu():
        x = root.winfo_pointerx()
        y = root.winfo_pointery()
        menu.show(x, y)
    
    # Show after a short delay
    root.after(100, show_menu)
    root.mainloop()