"""
MDM / org-token deployment for the Mac agent.

The counterpart to windows_agent/mdm_deploy.py: how a machine IT deployed
gets paired to the right person with nobody clicking anything.

    1. POST /deploy/auto-pair/     hostname or username -> DeviceProvisioningMap
    2. POST /deploy/claim/         existing device -> email -> provisioning map
    3. a one-time picker, then POST /deploy/confirm-user/

Steps 1 and 2 are silent. Only step 3 involves a human, and populating the
provisioning map (manage.py provision_firm) is what avoids it.

WHAT THIS REPLACES. The Mac agent used to post to /agent/register/, which
find-or-creates a user from the OS short name and invents an email like
`dan@yourfirm.local`. That is a different identity namespace from the one
Windows pairs into, so the same person on a Mac and a PC became two users. It
also could not work as written: the view raises TypeError on
`user.groups.add(org)` (Organization is not a Group), and the key it returns
lives in AgentRegistration, which AgentKeyAuthentication never consults.

These three endpoints are shared with the Windows agent and are NOT modified.
auto_pair_device already stores whatever `platform` string it is given and has
no Windows-specific logic beyond a field named windows_username, so the Mac
agent simply sends its own short name in it.

MAC: five deliberate differences from the Windows file.
  * URLs. Windows builds f"{api_base}/api/deploy/...", but api_base already
    ends in /api, so every Windows MDM URL resolves to /api/api/... and 404s.
    This file appends /deploy/... to api_base, which is what the routes
    actually are. See PROVISIONING.md.
  * Identity. Windows reads an AAD UPN from dsregcmd/whoami. A Mac has no
    equivalent, so this asks OpenDirectory (dscl) for the account's real mail
    attribute and falls back to the short name.
  * Hostname. platform.node() can carry a trailing .local on a Mac; the
    provisioning map stores bare, uppercased hostnames.
  * device_id is PASSED IN rather than minted here. The Windows copy keeps its
    own .device_id file, separate from the one its main.py uses, so a Windows
    box can hold two identities. The Mac agent has exactly one.
  * The picker is plain Tk. It must not import the agent's customtkinter shim:
    this runs before the GUI exists.
"""
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request

_TIMEOUT = 15


def _post(url: str, payload: dict) -> dict:
    """POST json, and return the server's dict whatever the status code.

    Every one of these endpoints answers with a JSON body carrying a `status`,
    including on 202 (unprovisioned) and 401/404 (bad token), so the caller
    reads `status` rather than inspecting HTTP codes. A transport failure is
    reported as status "error" with the message, which is what the retry loop
    in do_org_token_claim matches on.
    """
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        try:
            return json.loads(body)
        except Exception:
            if e.code == 202:
                return {"status": "unprovisioned"}
            if e.code in (401, 404):
                return {"status": "invalid_token"}
            return {"status": "error", "message": f"HTTP {e.code}: {body[:200]}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def claim_with_auto_pair(api_base, org_token, hostname, os_username,
                         device_id, app_version="dev") -> dict:
    """Hostname / username match against DeviceProvisioningMap.

    Values are uppercased because provision_firm stores them that way
    (machine_hostname=hostname.upper()) and the server compares exactly.
    """
    return _post(f"{api_base.rstrip('/')}/deploy/auto-pair/", {
        "org_token": org_token,
        "hostname": (hostname or "").upper(),
        "windows_username": (os_username or "").upper(),
        "platform": "macos",
        "app_version": app_version,
        "device_id": device_id,
    })


def claim_with_org_token_legacy(api_base, org_token, hostname, os_username,
                                app_version="dev") -> dict:
    """The four-step ladder: known device, email match, provisioning map, picker.

    Note the field names differ from auto-pair — this endpoint wants
    `os_username` and un-uppercased values. That is the server's contract, not
    an oversight.
    """
    return _post(f"{api_base.rstrip('/')}/deploy/claim/", {
        "org_token": org_token,
        "hostname": hostname,
        "os_username": os_username,
        "platform": platform.platform(),
        "version": app_version,
    })


def confirm_user_selection(api_base, org_token, hostname, user_id,
                           device_id, app_version="dev") -> dict:
    """Bind this device to the user the human picked."""
    return _post(f"{api_base.rstrip('/')}/deploy/confirm-user/", {
        "org_token": org_token,
        "hostname": hostname,
        "user_id": user_id,
        "device_id": device_id,
        "platform": "macos",
        "version": app_version,
    })


def _directory_email(short_name: str) -> str:
    """The account's real mail address from OpenDirectory, or "".

    This is the Mac's nearest equivalent to the AAD UPN the Windows agent
    reads, and it is what makes /deploy/claim/'s email match able to succeed.
    On a machine bound to a directory this is the person's actual address; on
    an unbound Mac there is usually no mail attribute and this returns "",
    leaving the short name as the only identity — which is exactly when the
    provisioning map matters.
    """
    if not short_name:
        return ""
    try:
        out = subprocess.run(
            ["/usr/bin/dscl", ".", "-read", f"/Users/{short_name}", "mail"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return ""
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", out or "")
    return m.group(0) if m else ""


def mac_hostname() -> str:
    """Bare hostname, without the trailing .local a Mac often reports.

    The provisioning map holds what IT exported from its inventory, which does
    not carry .local; sending it would miss every row.
    """
    node = (platform.node() or "").strip()
    if node.lower().endswith(".local"):
        node = node[: -len(".local")]
    return node


def show_user_picker_gui(members: list):
    """One-time 'who is this Mac?' list. Returns a user_id, or None.

    Deliberately plain Tk. This runs before the agent's GUI exists, and the
    customtkinter shim the menu bar uses is not available this early.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        # Headless or no Tk: fall back to the terminal, and if that is not
        # there either, give up rather than hang a background LaunchAgent.
        return _pick_on_tty(members)

    chosen = {"id": None}
    root = tk.Tk()
    root.title("TimeTracker — who is using this Mac?")
    root.geometry("420x360")
    root.resizable(False, False)

    tk.Label(root, text="Select the person who uses this Mac",
             font=("Helvetica", 14, "bold")).pack(pady=(16, 4))
    tk.Label(root, text="Your administrator deployed TimeTracker here.\n"
                        "This is asked once.",
             justify="center", fg="#555").pack(pady=(0, 10))

    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=16)
    scroll = ttk.Scrollbar(frame)
    scroll.pack(side="right", fill="y")
    listbox = tk.Listbox(frame, yscrollcommand=scroll.set, font=("Helvetica", 12))
    listbox.pack(side="left", fill="both", expand=True)
    scroll.config(command=listbox.yview)

    for m in members:
        label = m.get("display_name") or m.get("name") or m.get("email") or "?"
        email = m.get("email") or ""
        listbox.insert("end", f"{label}  —  {email}" if email else label)
    if members:
        listbox.selection_set(0)

    def confirm():
        sel = listbox.curselection()
        if sel:
            chosen["id"] = members[sel[0]].get("user_id") or members[sel[0]].get("id")
        root.destroy()

    listbox.bind("<Double-Button-1>", lambda _e: confirm())
    tk.Button(root, text="This is me", command=confirm,
              height=2).pack(fill="x", padx=16, pady=(10, 14))

    try:
        root.lift()
        root.attributes("-topmost", True)
        root.mainloop()
    except Exception:
        return None
    return chosen["id"]


def _pick_on_tty(members: list):
    """Terminal fallback for the picker. Returns a user_id, or None."""
    try:
        if not os.isatty(0):
            return None
        print("\nTimeTracker — who is using this Mac?")
        for i, m in enumerate(members, 1):
            print(f"  {i}. {m.get('display_name') or m.get('name') or ''} "
                  f"<{m.get('email') or ''}>")
        raw = input("Number (blank to skip): ").strip()
        if not raw:
            return None
        m = members[int(raw) - 1]
        return m.get("user_id") or m.get("id")
    except Exception:
        return None


def do_org_token_claim(config: dict, save_config_fn, api_base: str,
                       app_version: str, device_id: str, log=print):
    """Pair this Mac using the org token IT deployed. Returns an api_key or None.

    Silent whenever the answer is knowable: a provisioning-map row, a known
    device, or an email the org recognises. A picker only when none of those
    holds, and None if even that is declined — the caller then falls back to
    ordinary interactive pairing, so a failure here is never fatal.
    """
    org_token = (config.get("org_token") or "").strip()
    if not org_token:
        return None

    hostname = mac_hostname()
    short_name = config.get("os_username") or ""
    if not short_name:
        try:
            import getpass
            short_name = getpass.getuser()
        except Exception:
            short_name = ""
    email = _directory_email(short_name)

    log(f"[MDM] Claiming this Mac with the org token")
    log(f"[MDM]   hostname: {hostname}")
    log(f"[MDM]   account : {short_name}{f' <{email}>' if email else ''}")

    def _save(result, how):
        api_key = result.get("api_key")
        if not api_key:
            return None
        config["api_key"] = api_key
        if result.get("device_id"):
            config["server_device_id"] = result["device_id"]
        save_config_fn(config)
        log(f"[MDM] Paired to {result.get('user_email', 'unknown')} ({how})")
        return api_key

    # ── 1. auto-pair, retried: a LaunchAgent can start before the network ──
    result = {}
    for attempt in range(5):
        result = claim_with_auto_pair(api_base, org_token, hostname,
                                      short_name, device_id, app_version)
        msg = result.get("message", "")
        if result.get("status") != "error" or not _looks_like_no_network(msg):
            break
        wait = 5 * (attempt + 1)
        log(f"[MDM] Network not ready, retrying in {wait}s ({attempt + 1}/5)")
        time.sleep(wait)

    status = result.get("status")
    if status in ("paired", "already_paired"):
        key = _save(result, result.get("match_method") or status)
        if key:
            return key
    if status == "invalid_token":
        log("[MDM] Org token was rejected — check the deployed config")
        return None

    # ── 2. the ladder: known device, then email, then provisioning map ──
    log("[MDM] No provisioning-map match — trying the claim ladder")
    result = claim_with_org_token_legacy(api_base, org_token, hostname,
                                         email or short_name, app_version)
    status = result.get("status")
    if status in ("matched", "paired", "already_paired"):
        key = _save(result, status)
        if key:
            return key
    if status == "invalid_token":
        log("[MDM] Org token was rejected — check the deployed config")
        return None

    # ── 3. ask, once ──
    if status == "pick_user":
        members = result.get("members") or []
        log(f"[MDM] Nothing identified this Mac — asking ({len(members)} members)")
        user_id = show_user_picker_gui(members)
        if not user_id:
            log("[MDM] No selection — leaving this Mac unpaired")
            return None
        confirmed = confirm_user_selection(api_base, org_token, hostname,
                                           user_id, device_id, app_version)
        key = _save(confirmed, "picked by the user")
        if key:
            return key
        log(f"[MDM] Confirm failed: {confirmed.get('message', 'no api_key returned')}")
        return None

    log(f"[MDM] Claim did not resolve (status={status!r}) — "
        f"falling back to manual pairing")
    return None


def _looks_like_no_network(message: str) -> bool:
    m = (message or "").lower()
    return any(s in m for s in
               ("getaddrinfo", "name or service not known", "temporary failure",
                "nodename nor servname", "network is unreachable", "timed out"))
