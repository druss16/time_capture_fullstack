"""
MDM / Org Token deployment support for the Windows agent.

Drop this file into the windows_agent/ directory alongside main.py.
Then in main.py, add to the pairing flow (see integration notes at bottom).
"""
import json
import urllib.request
import urllib.error
import platform
import getpass
import threading
import time


def claim_with_org_token(api_base: str, org_token: str, hostname: str, os_username: str,
                          app_version: str = "dev") -> dict:
    """
    Claim a device using an org deployment token.
    Returns dict with status: "matched", "pick_user", or "error"
    """
    url = f"{api_base.rstrip('/')}/deploy/claim/"
    payload = {
        "org_token": org_token,
        "hostname": hostname,
        "os_username": os_username,
        "platform": platform.platform(),
        "version": app_version,
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode('utf-8', errors='ignore')
        except:
            pass
        try:
            return json.loads(body)
        except:
            return {"status": "error", "message": f"HTTP {e.code}: {body[:200]}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def confirm_user_selection(api_base: str, org_token: str, hostname: str,
                            os_username: str, user_id: int,
                            app_version: str = "dev") -> dict:
    """
    Confirm user selection after the picker was shown.
    Returns dict with status: "matched" or "error"
    """
    url = f"{api_base.rstrip('/')}/deploy/confirm-user/"
    payload = {
        "org_token": org_token,
        "hostname": hostname,
        "os_username": os_username,
        "user_id": user_id,
        "platform": platform.platform(),
        "version": app_version,
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode('utf-8', errors='ignore')
        except:
            pass
        try:
            return json.loads(body)
        except:
            return {"status": "error", "message": f"HTTP {e.code}: {body[:200]}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def show_user_picker_gui(members: list) -> int:
    """
    Show a simple Tkinter dialog for the user to select their name.
    Returns the selected user_id, or None if cancelled.

    members = [{"id": 1, "name": "John Smith", "email": "john@..."}, ...]
    """
    selected_id = [None]

    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("TimeTracker — Select Your Name")
        root.geometry("420x500")
        root.resizable(False, False)

        # Center on screen
        root.update_idletasks()
        x = (root.winfo_screenwidth() // 2) - 210
        y = (root.winfo_screenheight() // 2) - 250
        root.geometry(f"+{x}+{y}")

        # Force to front
        root.attributes('-topmost', True)
        root.after(500, lambda: root.attributes('-topmost', False))

        # Header
        header = tk.Label(
            root,
            text="Welcome to TimeTracker",
            font=("Segoe UI", 16, "bold"),
            pady=10
        )
        header.pack()

        subtitle = tk.Label(
            root,
            text="Please select your name to complete setup:",
            font=("Segoe UI", 10),
            pady=5
        )
        subtitle.pack()

        # Listbox with members
        frame = tk.Frame(root)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        listbox = tk.Listbox(
            frame,
            font=("Segoe UI", 11),
            yscrollcommand=scrollbar.set,
            selectmode=tk.SINGLE,
            activestyle='dotbox'
        )
        listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        # Populate list
        for m in members:
            display = m['name']
            if m.get('email'):
                display += f"  ({m['email']})"
            listbox.insert(tk.END, display)

        # Buttons
        btn_frame = tk.Frame(root, pady=10)
        btn_frame.pack()

        def on_confirm():
            sel = listbox.curselection()
            if sel:
                selected_id[0] = members[sel[0]]['id']
                root.destroy()

        def on_cancel():
            root.destroy()

        confirm_btn = tk.Button(
            btn_frame,
            text="Confirm",
            command=on_confirm,
            font=("Segoe UI", 11),
            width=12,
            bg="#2563eb",
            fg="white"
        )
        confirm_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            command=on_cancel,
            font=("Segoe UI", 11),
            width=12
        )
        cancel_btn.pack(side=tk.LEFT, padx=5)

        # Double-click to select
        def on_double_click(event):
            on_confirm()
        listbox.bind('<Double-1>', on_double_click)

        root.mainloop()

    except Exception as e:
        print(f"[MDM] Failed to show user picker: {e}")
        return None

    return selected_id[0]


def do_org_token_claim(config: dict, save_config_fn, api_base: str, app_version: str) -> str:
    """
    Main entry point for org token claim flow.
    Call this from run_agent() when config has 'org_token' but no 'api_key'.

    Returns the API key on success, or None on failure.

    Usage in main.py:
        from mdm_deploy import do_org_token_claim

        org_token = config.get("org_token")
        if org_token and not config.get("api_key"):
            key = do_org_token_claim(config, save_config, API_BASE, APP_VERSION)
            if key:
                API_KEY = key
                # Continue to normal operation
            else:
                # Fall back to manual pairing or exit
    """
    org_token = config.get("org_token", "").strip()
    if not org_token:
        return None

    hostname = platform.node()
    os_username = _get_aad_username()

    print(f"[MDM] Claiming device with org token...")
    print(f"[MDM]   Hostname: {hostname}")
    print(f"[MDM]   Username: {os_username}")

    # Attempt claim with retry for network issues (machine may have just booted)
    result = None
    for attempt in range(5):
        result = claim_with_org_token(api_base, org_token, hostname, os_username, app_version)
        if result.get("status") != "error" or "getaddrinfo" not in result.get("message", ""):
            break
        wait = 5 * (attempt + 1)
        print(f"[MDM] Network not ready, retrying in {wait}s (attempt {attempt + 1}/5)")
        time.sleep(wait)

    if not result:
        print("[MDM] ❌ Failed to claim device — no response")
        return None

    status = result.get("status")

    if status == "matched":
        # Auto-matched by email — save credentials
        api_key = result["api_key"]
        config["api_key"] = api_key
        config["server_device_id"] = result.get("device_id")
        save_config_fn(config)
        user_name = result.get("user_name", "Unknown")
        already = " (already registered)" if result.get("already_registered") else ""
        print(f"[MDM] ✅ Device paired to {user_name}{already}")
        return api_key

    elif status == "pick_user":
        # Need user to select their name
        members = result.get("members", [])
        if not members:
            print("[MDM] ❌ No org members found")
            return None

        print(f"[MDM] Could not auto-match '{os_username}' — showing user picker ({len(members)} members)")
        selected_user_id = show_user_picker_gui(members)

        if not selected_user_id:
            print("[MDM] ❌ User cancelled picker")
            return None

        # Confirm selection
        confirm_result = confirm_user_selection(
            api_base, org_token, hostname, os_username,
            selected_user_id, app_version
        )

        if confirm_result.get("status") == "matched":
            api_key = confirm_result["api_key"]
            config["api_key"] = api_key
            config["server_device_id"] = confirm_result.get("device_id")
            save_config_fn(config)
            user_name = confirm_result.get("user_name", "Unknown")
            print(f"[MDM] ✅ Device paired to {user_name} (manual selection)")
            return api_key
        else:
            print(f"[MDM] ❌ Confirm failed: {confirm_result.get('message', 'Unknown error')}")
            return None

    elif status == "error":
        print(f"[MDM] ❌ Claim error: {result.get('message', 'Unknown error')}")
        return None

    else:
        print(f"[MDM] ❌ Unexpected status: {status}")
        return None


def _get_aad_username() -> str:
    """
    Get the Azure AD UPN (user principal name) on AAD-joined machines.
    Falls back to standard os username if not AAD-joined.

    On AAD-joined machines, the Windows username is typically:
    - AzureAD\\jsmith@cpafirm.com  (displayed form)
    - jsmith@cpafirm.com  (UPN)

    We try multiple methods to get the best match.
    """
    # Method 1: Try dsregcmd to get AAD UPN (most reliable on AAD-joined)
    try:
        import subprocess
        result = subprocess.run(
            ["dsregcmd", "/status"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                # Look for "User UPN" or "UserEmail"
                if "UPN" in line.upper() and ":" in line:
                    upn = line.split(":", 1)[1].strip()
                    if "@" in upn:
                        return upn
    except Exception:
        pass

    # Method 2: Try whoami /upn
    try:
        import subprocess
        result = subprocess.run(
            ["whoami", "/upn"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            upn = result.stdout.strip()
            if "@" in upn:
                return upn
    except Exception:
        pass

    # Method 3: Environment variable (sometimes set on AAD machines)
    import os
    for var in ['USERNAME', 'USER']:
        val = os.environ.get(var, '')
        if '@' in val:
            return val

    # Method 4: Fall back to getpass
    return getpass.getuser()
