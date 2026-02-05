#!/usr/bin/env python3
"""Standalone client picker - runs completely isolated from main process"""
import os
import sys
import json

# Suppress warnings
os.environ['TK_SILENCE_DEPRECATION'] = '1'

def run_picker(clients_json: str, usage_json: str):
    """Run the picker and print result to stdout"""
    import customtkinter as ctk
    
    clients = json.loads(clients_json) if clients_json else []
    usage_data = json.loads(usage_json) if usage_json else {}
    usage_data = {int(k): v for k, v in usage_data.items()}
    
    selected = {"id": None, "name": None}
    confirmed = {"value": False}
    
    # Colors
    colors = {
        "primary": "#14B8A6",
        "bg_window": "#1C1C1C",
        "bg_card": "#2A2A2A",
        "bg_card_hover": "#333333",
        "text_primary": "#FFFFFF",
        "text_accent": "#14B8A6",
        "text_muted": "#555555",
    }
    
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("Select Client")
    root.geometry("380x500")
    root.configure(fg_color=colors["bg_window"])
    root.attributes('-topmost', True)
    
    # Center
    root.withdraw()
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 190
    y = (root.winfo_screenheight() // 2) - 250
    root.geometry(f"+{x}+{y}")
    root.deiconify()
    root.lift()
    root.focus_force()
    
    def do_confirm():
        confirmed["value"] = True
        root.quit()
    
    def do_cancel():
        root.quit()
    
    def do_clear():
        selected["id"] = 0
        selected["name"] = "No Client"
        confirmed["value"] = True
        root.quit()
    
    # Container
    container = ctk.CTkFrame(root, fg_color="transparent")
    container.pack(fill="both", expand=True, padx=16, pady=12)
    
    # Search
    search_var = ctk.StringVar()
    search_entry = ctk.CTkEntry(container, textvariable=search_var,
                                placeholder_text="Type to filter...",
                                fg_color=colors["bg_card"],
                                height=36, corner_radius=8)
    search_entry.pack(fill="x", pady=(0, 12))
    
    # Scrollable list
    scroll_frame = ctk.CTkScrollableFrame(container, fg_color="transparent")
    scroll_frame.pack(fill="both", expand=True, pady=(0, 12))
    
    row_widgets = []
    
    def select_row(cid, cname):
        selected["id"] = cid
        selected["name"] = cname
        for row, rid, rn in row_widgets:
            row.configure(fg_color=colors["primary"] if rid == cid else colors["bg_card"])
    
    def build_list(query=""):
        nonlocal row_widgets
        row_widgets = []
        for w in scroll_frame.winfo_children():
            w.destroy()
        
        query_lower = query.lower().strip()
        filtered = [c for c in clients if query_lower in c.get("name", "").lower()] if query_lower else clients
        filtered = sorted(filtered, key=lambda c: usage_data.get(c.get("id", 0), 0), reverse=True)
        
        for client in filtered[:20]:
            cid = client.get("id")
            cname = client.get("name", "Unknown")
            
            card = ctk.CTkFrame(scroll_frame, fg_color=colors["bg_card"], corner_radius=10)
            card.pack(fill="x", pady=3, padx=2)
            row_widgets.append((card, cid, cname))
            
            content = ctk.CTkFrame(card, fg_color="transparent")
            content.pack(fill="x", padx=14, pady=12)
            
            label = ctk.CTkLabel(content, text=cname, text_color=colors["text_primary"])
            label.pack(side="left")
            
            for widget in [card, content, label]:
                widget.bind("<Button-1>", lambda e, c=cid, n=cname: select_row(c, n))
                widget.bind("<Double-Button-1>", lambda e, c=cid, n=cname: [select_row(c, n), do_confirm()])
    
    search_var.trace_add("write", lambda *a: build_list(search_var.get()))
    
    # Buttons
    btn_frame = ctk.CTkFrame(container, fg_color="transparent")
    btn_frame.pack(fill="x")
    
    ctk.CTkButton(btn_frame, text="Clear", command=do_clear, fg_color="transparent", width=60).pack(side="left")
    ctk.CTkButton(btn_frame, text="Cancel", command=do_cancel, fg_color=colors["bg_card"], width=80).pack(side="right")
    ctk.CTkButton(btn_frame, text="OK", command=do_confirm, fg_color=colors["primary"], width=80).pack(side="right", padx=(0, 8))
    
    build_list("")
    search_entry.focus_set()
    
    root.bind("<Return>", lambda e: do_confirm() if selected["id"] is not None else None)
    root.bind("<Escape>", lambda e: do_cancel())
    
    root.mainloop()
    root.destroy()
    
    # Output result as JSON to stdout
    if confirmed["value"] and (selected["id"] is not None or selected["name"] == "No Client"):
        print(json.dumps({"id": selected["id"], "name": selected["name"]}))
    else:
        print(json.dumps({"id": None, "name": None}))


if __name__ == "__main__":
    clients_json = sys.argv[1] if len(sys.argv) > 1 else "[]"
    usage_json = sys.argv[2] if len(sys.argv) > 2 else "{}"
    run_picker(clients_json, usage_json)