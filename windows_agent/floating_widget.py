#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Floating Client Widget - Always visible current client indicator

Features:
- Small floating window showing current client
- Draggable to any position
- Collapsible to just an icon
- Click to open client picker
- Remembers position between sessions
"""

import os
import json
import threading
import time as _time

try:
    import customtkinter as ctk
    WIDGET_AVAILABLE = True
except ImportError:
    WIDGET_AVAILABLE = False

# Colors matching the app theme
COLORS = {
    "primary": "#14B8A6",
    "primary_dark": "#0D9488",
    "bg_dark": "#1A1A1A",
    "bg_card": "#252525",
    "text": "#FFFFFF",
    "text_muted": "#888888",
    "no_client": "#EF4444",  # Red for no client
}

WIDGET_STATE_FILE = os.path.expanduser("~/.timetracker/widget_state.json")


class FloatingClientWidget:
    """
    Floating always-on-top widget showing current client.
    
    Expanded view:
    ┌─────────────────────────┐
    │ ⏱ Acme Corp      ─  ✕ │
    └─────────────────────────┘
    
    Collapsed view:
    ┌────┐
    │ ⏱ │
    └────┘
    """
    
    def __init__(self, on_click_callback=None, get_client_callback=None):
        """
        Args:
            on_click_callback: Called when user clicks to switch client
            get_client_callback: Returns {"client_id": int, "client_name": str}
        """
        self.on_click = on_click_callback
        self.get_client = get_client_callback
        
        self.root = None
        self.is_collapsed = False
        self.is_visible = True
        self.is_dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        
        self.current_client_name = "No Client"
        self.current_client_id = None
        
        # Load saved state
        self._load_state()
        
    def _load_state(self):
        """Load widget position and collapse state"""
        self.saved_x = None
        self.saved_y = None
        self.is_collapsed = False
        self.is_visible = True
        
        if os.path.exists(WIDGET_STATE_FILE):
            try:
                with open(WIDGET_STATE_FILE, 'r') as f:
                    state = json.load(f)
                    self.saved_x = state.get('x')
                    self.saved_y = state.get('y')
                    self.is_collapsed = state.get('collapsed', False)
                    self.is_visible = state.get('visible', True)
            except Exception:
                pass
    
    def _save_state(self):
        """Save widget position and collapse state"""
        try:
            os.makedirs(os.path.dirname(WIDGET_STATE_FILE), exist_ok=True)
            state = {
                'x': self.root.winfo_x() if self.root else self.saved_x,
                'y': self.root.winfo_y() if self.root else self.saved_y,
                'collapsed': self.is_collapsed,
                'visible': self.is_visible,
            }
            with open(WIDGET_STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[WIDGET] Failed to save state: {e}")
    
    def create(self, parent_root=None):
        if not WIDGET_AVAILABLE:
            print("[WIDGET] customtkinter not available")
            return None
        
        # REMOVED the is_visible early return — always allow creation
        # The user can re-hide it if they want
        
        self.is_visible = True  # Reset on create
        ctk.set_appearance_mode("dark")
        
        # Use provided root or create new one
        if parent_root:
            self.root = ctk.CTkToplevel(parent_root)
        else:
            # Create standalone - must be called from main thread
            self.root = ctk.CTk()
        
        self.root.title("TimeTracker")
        self.root.overrideredirect(True)  # Remove window decorations
        self.root.attributes('-topmost', True)  # Always on top
        
        try:
            self.root.attributes('-alpha', 0.95)  # Slightly transparent
        except:
            pass
        
        # Set initial size based on collapsed state
        if self.is_collapsed:
            self.root.geometry("45x35")
        else:
            self.root.geometry("220x50")
        
        # Position window
        if self.saved_x is not None and self.saved_y is not None:
            self.root.geometry(f"+{self.saved_x}+{self.saved_y}")
        else:
            # Default to top-right corner
            self.root.update_idletasks()
            screen_w = self.root.winfo_screenwidth()
            self.root.geometry(f"+{screen_w - 240}+10")
        
        self._build_ui()
        self._start_update_loop()
        
        return self.root
    
    def run(self):
        """Run the widget mainloop (call from main thread)"""
        if self.root:
            self.root.mainloop()
    
    def _build_ui(self):
        """Build the widget UI"""
        # Main container with rounded corners effect
        self.container = ctk.CTkFrame(
            self.root,
            fg_color=COLORS["bg_dark"],
            corner_radius=8,
            border_width=1,
            border_color=COLORS["primary"]
        )
        self.container.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Make it draggable
        self.container.bind("<Button-1>", self._start_drag)
        self.container.bind("<B1-Motion>", self._do_drag)
        self.container.bind("<ButtonRelease-1>", self._stop_drag)
        
        # Inner content frame
        self.content = ctk.CTkFrame(self.container, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=5, pady=3)
        
        # Left side - icon and client info
        left_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        left_frame.pack(side="left", fill="both", expand=True)
        left_frame.bind("<Button-1>", self._start_drag)
        left_frame.bind("<B1-Motion>", self._do_drag)
        
        # Top row - icon and client name
        top_row = ctk.CTkFrame(left_frame, fg_color="transparent")
        top_row.pack(fill="x")
        top_row.bind("<Button-1>", self._start_drag)
        top_row.bind("<B1-Motion>", self._do_drag)
        
        # Icon (always visible)
        self.icon_label = ctk.CTkLabel(
            top_row,
            text="⏱",
            font=ctk.CTkFont(size=14),
            text_color=COLORS["primary"],
            cursor="hand2"  # Show hand cursor since clicking expands
        )
        self.icon_label.pack(side="left")
        self.icon_label.bind("<Button-1>", self._on_icon_click)
        self.icon_label.bind("<B1-Motion>", self._do_drag)
        
        # Client name
        self.client_label = ctk.CTkLabel(
            top_row,
            text=self.current_client_name,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text"],
            anchor="w"
        )
        if not self.is_collapsed:
            self.client_label.pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.client_label.bind("<Button-1>", self._start_drag)
        self.client_label.bind("<B1-Motion>", self._do_drag)
        
        # Hotkey hint (shown below client name when expanded)
        self.hint_label = ctk.CTkLabel(
            left_frame,
            text="Alt+Ctrl+T to switch",
            font=ctk.CTkFont(size=9),
            text_color=COLORS["text_muted"],
            anchor="w"
        )
        if not self.is_collapsed:
            self.hint_label.pack(fill="x", padx=(19, 0))  # Align with client name
        self.hint_label.bind("<Button-1>", self._start_drag)
        self.hint_label.bind("<B1-Motion>", self._do_drag)
        
        # Buttons frame (hidden when collapsed)
        self.buttons_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        if not self.is_collapsed:
            self.buttons_frame.pack(side="right")
        
        # Collapse button
        self.collapse_btn = ctk.CTkButton(
            self.buttons_frame,
            text="─",
            width=20,
            height=20,
            corner_radius=3,
            fg_color="transparent",
            hover_color=COLORS["bg_card"],
            text_color=COLORS["text_muted"],
            command=self._toggle_collapse
        )
        self.collapse_btn.pack(side="left", padx=1)
        
        # Close button
        self.close_btn = ctk.CTkButton(
            self.buttons_frame,
            text="✕",
            width=20,
            height=20,
            corner_radius=3,
            fg_color="transparent",
            hover_color="#EF4444",
            text_color=COLORS["text_muted"],
            command=self._hide
        )
        self.close_btn.pack(side="left", padx=1)
        
        # Update initial appearance
        self._update_appearance()
    
    def _start_drag(self, event):
        """Start dragging the widget"""
        self.is_dragging = True
        self.drag_start_x = event.x
        self.drag_start_y = event.y
    
    def _do_drag(self, event):
        """Handle dragging"""
        if self.is_dragging:
            x = self.root.winfo_x() + event.x - self.drag_start_x
            y = self.root.winfo_y() + event.y - self.drag_start_y
            self.root.geometry(f"+{x}+{y}")
    
    def _stop_drag(self, event):
        """Stop dragging and save position"""
        self.is_dragging = False
        self._save_state()
    
    def _on_icon_click(self, event):
        """Handle click on icon - expand if collapsed"""
        if self.is_collapsed:
            self._toggle_collapse()
        # If not collapsed, do nothing (just drag)
    
    def _on_client_click(self, event):
        """Handle click on client name - open picker"""
        if not self.is_dragging and self.on_click:
            self.on_click()
    
    def _toggle_collapse(self):
        """Toggle between expanded and collapsed view"""
        self.is_collapsed = not self.is_collapsed
        
        if self.is_collapsed:
            # Collapse - hide client name, hint, and buttons
            self.client_label.pack_forget()
            self.hint_label.pack_forget()
            self.buttons_frame.pack_forget()
            self.root.geometry("45x35")
        else:
            # Expand - show everything
            self.client_label.pack(side="left", fill="x", expand=True, padx=(5, 0))
            self.hint_label.pack(fill="x", padx=(19, 0))
            self.buttons_frame.pack(side="right")
            self.root.geometry("220x50")
        
        self._save_state()
    
    def _hide(self):
        """Hide the widget (can be shown again from tray)"""
        self.is_visible = False
        self._save_state()
        if self.root:
            self.root.withdraw()  # Hide, don't destroy
    
    def show(self):
        """Show the widget if hidden"""
        self.is_visible = True
        self._save_state()
        if self.root:
            self.root.deiconify()
            self.root.attributes('-topmost', True)
            self.root.lift()
        else:
            # Widget was destroyed, recreate it
            self.create()
            if self.root:
                self.root.mainloop()
    
    def update_client(self, client_id, client_name):
        """Update the displayed client"""
        self.current_client_id = client_id
        self.current_client_name = client_name or "No Client"
        self._update_appearance()
    
    def _update_appearance(self):
        """Update colors based on client state"""
        if not self.root or not self.root.winfo_exists():
            return
        
        try:
            # Update client label text
            display_name = self.current_client_name
            if len(display_name) > 18:
                display_name = display_name[:16] + "..."
            self.client_label.configure(text=display_name)
            
            # Change colors based on whether client is selected
            if self.current_client_id:
                # Has client - green/teal theme
                self.container.configure(border_color=COLORS["primary"])
                self.icon_label.configure(text_color=COLORS["primary"])
                self.client_label.configure(text_color=COLORS["text"])
            else:
                # No client - red warning
                self.container.configure(border_color=COLORS["no_client"])
                self.icon_label.configure(text_color=COLORS["no_client"])
                self.client_label.configure(text_color=COLORS["no_client"])
        except Exception:
            pass
    
    def _start_update_loop(self):
        """Start background loop to poll for client updates"""
        self._update_running = True
        
        def update_loop():
            while self._update_running:
                try:
                    if self.get_client:
                        client_info = self.get_client()
                        if client_info:
                            new_id = client_info.get("client_id")
                            new_name = client_info.get("client_name") or "No Client"
                            
                            if new_id != self.current_client_id or new_name != self.current_client_name:
                                self.current_client_id = new_id
                                self.current_client_name = new_name
                                
                                # Schedule UI update on main thread (don't touch tkinter here)
                                try:
                                    if self.root:
                                        self.root.after(0, self._update_appearance)
                                except Exception:
                                    pass
                except Exception as e:
                    print(f"[WIDGET] Update error: {e}")
                
                _time.sleep(2)
        
        thread = threading.Thread(target=update_loop, daemon=True)
        thread.start()

    def destroy(self):
        """Clean up the widget"""
        self._update_running = False  # Stop the loop first
        self._save_state()
        if self.root:
            try:
                self.root.destroy()
            except:
                pass
            self.root = None


# ============================================================
# Integration helper for TimeTrackerSystemTray
# ============================================================
def create_floating_widget(tray_controller):
    """
    Create and attach a floating widget to the system tray controller.
    
    Args:
        tray_controller: TimeTrackerSystemTray instance
    
    Returns:
        FloatingClientWidget instance
    """
    if not WIDGET_AVAILABLE:
        print("[WIDGET] Cannot create widget - customtkinter not available")
        return None
    
    def on_click():
        """Open client picker when widget is clicked"""
        if hasattr(tray_controller, '_show_client_picker'):
            tray_controller._show_client_picker()
    
    def get_client():
        """Get current client from tray state"""
        if hasattr(tray_controller, 'state'):
            return {
                "client_id": tray_controller.state.current_client_id,
                "client_name": tray_controller.state.current_client_name
            }
        return {"client_id": None, "client_name": "No Client"}
    
    widget = FloatingClientWidget(
        on_click_callback=on_click,
        get_client_callback=get_client
    )
    
    return widget


if __name__ == "__main__":
    # Test the widget standalone
    import customtkinter as ctk
    
    test_client = {"id": 1, "name": "Test Client Inc"}
    
    def on_click():
        print("Widget clicked!")
    
    def get_client():
        return {"client_id": test_client["id"], "client_name": test_client["name"]}
    
    widget = FloatingClientWidget(
        on_click_callback=on_click,
        get_client_callback=get_client
    )
    widget.create()
    
    # Test updating client after 3 seconds
    def test_no_client():
        test_client["id"] = None
        test_client["name"] = "No Client"
    
    def test_new_client():
        test_client["id"] = 2
        test_client["name"] = "Another Client Corp"
    
    if widget.root:
        widget.root.after(3000, test_no_client)
        widget.root.after(6000, test_new_client)
        widget.run()