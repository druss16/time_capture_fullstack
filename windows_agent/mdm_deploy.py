"""
MDM / Org Token deployment support for the Windows agent.

Supports two flows:
1. Auto-pair via DeviceProvisioningMap (new - hostname matching)
2. Fallback to deploy/claim endpoint (legacy - email matching)

Drop this file into the windows_agent/ directory alongside main.py.
"""
import json
import uuid
import urllib.request
import urllib.error
import platform
import getpass
import time
import os


def claim_with_auto_pair(api_base: str, org_token: str, hostname: str,
                          os_username: str, app_version: str = "dev") -> dict:
    """
    Claim a device using the auto-pair endpoint.
    Matches hostname against DeviceProvisioningMap created during provisioning.
    
    Returns dict with status: "paired", "unprovisioned", or "error"
    """
    url = f"{api_base.rstrip('/')}/devices/auto-pair/"
    
    # Generate or read device_id
    device_id = _get_or_create_device_id()
    
    payload = {
        "org_token": org_token,
        "hostname": hostname.upper(),
        "windows_username": os_username.upper(),
        "platform": "windows",
        "app_version": app_version,
        "device_id": device_id,
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
        
        # 202 = unprovisioned (no match found)
        if e.code == 202:
            try:
                return json.loads(body)
            except:
                return {"status": "unprovisioned", "message": "No provisioning match found"}
        
        # 401 = invalid token
        if e.code == 401:
            try:
                return json.loads(body)
            except:
                return {"status": "error", "message": "Invalid org token"}
        
        try:
            return json.loads(body)
        except:
            return {"status": "error", "message": f"HTTP {e.code}: {body[:200]}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def claim_with_org_token_legacy(api_base: str, org_token: str, hostname: str,
                                 os_username: str, app_version: str = "dev") -> dict:
    """
    Legacy claim endpoint - falls back to email matching and user picker.
    Used when auto-pair doesn't find a hostname match.
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
    Confirm user selection after the picker was shown (legacy flow).
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
    """
    selected_id = [None]

    try:
        import tkinter as tk

        root = tk.Tk()
        root.title("TimeTracker — Select Your Name")
        root.geometry("420x500")
        root.resizable(False, False)

        root.update_idletasks()
        x = (root.winfo_screenwidth() // 2) - 210
        y = (root.winfo_screenheight() // 2) - 250
        root.geometry(f"+{x}+{y}")

        root.attributes('-topmost', True)
        root.after(500, lambda: root.attributes('-topmost', False))

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

        for m in members:
            display = m['name']
            if m.get('email'):
                display += f"  ({m['email']})"
            listbox.insert(tk.END, display)

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

        listbox.bind('<Double-1>', lambda e: on_confirm())

        root.mainloop()

    except Exception as e:
        print(f"[MDM] Failed to show user picker: {e}")
        return None

    return selected_id[0]


def do_org_token_claim(config: dict, save_config_fn, api_base: str, app_version: str) -> str:
    """
    Main entry point for org token claim flow.
    
    Flow:
    1. Try auto-pair (hostname match against DeviceProvisioningMap)
    2. If no match, fall back to legacy deploy/claim (email match + user picker)
    3. If still no match, return None (manual pairing required)
    
    Returns the API key on success, or None on failure.
    """
    org_token = config.get("org_token", "").strip()
    if not org_token:
        return None

    hostname = platform.node()
    os_username = _get_aad_username()

    print(f"[MDM] Claiming device with org token...")
    print(f"[MDM]   Hostname: {hostname}")
    print(f"[MDM]   Username: {os_username}")

    # ── Step 1: Try auto-pair (hostname matching) ──
    print(f"[MDM] Trying auto-pair (hostname match)...")
    result = None
    for attempt in range(5):
        result = claim_with_auto_pair(api_base, org_token, hostname, os_username, app_version)
        if result.get("status") != "error" or "getaddrinfo" not in result.get("message", ""):
            break
        wait = 5 * (attempt + 1)
        print(f"[MDM] Network not ready, retrying in {wait}s (attempt {attempt + 1}/5)")
        time.sleep(wait)

    if not result:
        print("[MDM] ❌ Failed to claim device — no response")
        return None

    status = result.get("status")

    # Auto-pair succeeded
    if status == "paired":
        api_key = result["api_key"]
        config["api_key"] = api_key
        if result.get("device_id"):
            config["server_device_id"] = result["device_id"]
        save_config_fn(config)
        user_email = result.get("user_email", "Unknown")
        match_method = result.get("match_method", "unknown")
        print(f"[MDM] ✅ Auto-paired to {user_email} (matched by {match_method})")
        return api_key

    # Auto-pair: device already paired
    if status == "already_paired":
        api_key = result.get("api_key")
        if api_key:
            config["api_key"] = api_key
            if result.get("device_id"):
                config["server_device_id"] = result["device_id"]
            save_config_fn(config)
            print(f"[MDM] ✅ Device already paired — restored credentials")
            return api_key

    # Auto-pair didn't match — try legacy flow
    if status == "unprovisioned":
        print(f"[MDM] No hostname match in provisioning map — trying legacy claim...")
        return _try_legacy_claim(config, save_config_fn, api_base, org_token,
                                  hostname, os_username, app_version)

    # Invalid token
    if status == "invalid_token":
        print(f"[MDM] ❌ Invalid org token: {org_token}")
        return None

    # Generic error
    if status == "error":
        msg = result.get("message", "Unknown error")
        print(f"[MDM] ❌ Auto-pair error: {msg}")
        # Fall through to legacy
        print(f"[MDM] Falling back to legacy claim...")
        return _try_legacy_claim(config, save_config_fn, api_base, org_token,
                                  hostname, os_username, app_version)

    # Unexpected status
    print(f"[MDM] ⚠️ Unexpected auto-pair status: {status} — trying legacy...")
    return _try_legacy_claim(config, save_config_fn, api_base, org_token,
                              hostname, os_username, app_version)


def _try_legacy_claim(config, save_config_fn, api_base, org_token,
                       hostname, os_username, app_version):
    """
    Legacy claim flow: email matching + user picker GUI.
    Used when auto-pair doesn't find a hostname match.
    """
    result = None
    for attempt in range(3):
        result = claim_with_org_token_legacy(api_base, org_token, hostname,
                                              os_username, app_version)
        if result.get("status") != "error" or "getaddrinfo" not in result.get("message", ""):
            break
        wait = 5 * (attempt + 1)
        print(f"[MDM] Network retry in {wait}s (attempt {attempt + 1}/3)")
        time.sleep(wait)

    if not result:
        print("[MDM] ❌ Legacy claim failed — no response")
        return None

    status = result.get("status")

    if status == "matched":
        api_key = result["api_key"]
        config["api_key"] = api_key
        config["server_device_id"] = result.get("device_id")
        save_config_fn(config)
        user_name = result.get("user_name", "Unknown")
        already = " (already registered)" if result.get("already_registered") else ""
        print(f"[MDM] ✅ Device paired to {user_name}{already} (legacy match)")
        return api_key

    elif status == "pick_user":
        members = result.get("members", [])
        if not members:
            print("[MDM] ❌ No org members found")
            return None

        print(f"[MDM] Showing user picker ({len(members)} members)...")
        selected_user_id = show_user_picker_gui(members)

        if not selected_user_id:
            print("[MDM] ❌ User cancelled picker")
            return None

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
        print(f"[MDM] ❌ Legacy claim error: {result.get('message', 'Unknown error')}")
        return None

    else:
        print(f"[MDM] ❌ Unexpected legacy status: {status}")
        return None


def _get_or_create_device_id() -> str:
    """Get existing device_id or create a new one."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    device_id_file = os.path.join(appdata, "TimeTracker", ".device_id")
    
    try:
        if os.path.exists(device_id_file):
            with open(device_id_file, "r") as f:
                did = f.read().strip()
                if did:
                    return did
    except Exception:
        pass
    
    did = str(uuid.uuid4())
    try:
        os.makedirs(os.path.dirname(device_id_file), exist_ok=True)
        with open(device_id_file, "w") as f:
            f.write(did)
    except Exception:
        pass
    return did


def _get_aad_username() -> str:
    """
    Get the Azure AD UPN on AAD-joined machines.
    Falls back to DOMAIN\\username or plain username.
    """
    # Method 1: Try dsregcmd for AAD UPN
    try:
        import subprocess
        result = subprocess.run(
            ["dsregcmd", "/status"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
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

    # Method 3: DOMAIN\username format (for on-prem AD)
    try:
        domain = os.environ.get('USERDOMAIN', '')
        username = os.environ.get('USERNAME', '')
        if domain and username:
            return f"{domain}\\{username}"
    except Exception:
        pass

    # Method 4: Plain username
    return getpass.getuser()