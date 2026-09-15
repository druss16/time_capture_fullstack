# Mac agent ↔ Windows agent parity

The two agents share the code that decides *which client a piece of work
belongs to*. That code must reach the same verdict on both platforms, or the
same firm gets different answers depending on whose desk the work happened
at. This file records what is shared, what is deliberately different, and
what has no Mac counterpart at all.

Keep it current. When you change one agent, this is the list that tells you
whether the other one needs the same change.

## Shared verbatim

These files are ports and should stay byte-identical apart from the marked
platform sections. Diff them before changing either copy.

| File | Notes |
|---|---|
| `ai_client_switcher.py` | Five `MAC:`-marked differences, listed in its header |
| `inference/` | Evidence collectors, engine, decay — pure Python |
| `inference_cache.py` | |
| `routing_rules.py` | Tier -1 org rules |
| `tax_software_constants.py` | Mirrors `tracker/utils/tax_software.py` on the server |
| `content_identity.py` | Mirrors `tracker/utils/content_identity.py` |
| `pdf_identity.py` | |
| `widget_state_tracker.py` | Also a dependency of `inference/collectors.py` |
| `tracking_health.py` | Progress heartbeat + idle classification |
| `meeting_detector.py` | Written cross-platform; picks `MacMeetingProbe` here |

## Same job, different implementation

| Concern | Windows | Mac |
|---|---|---|
| Folder signal | `explorer_watcher.py` (UI Automation on the address bar) | `finder_watcher.py` (AppleScript on Finder's front window) |
| App identity | `.exe` name | bundle identifier, in the parameter still called `exe_name` |
| Document + URL reads | UI Automation | AppleScript, per app — see `_DOC_PATH_SCRIPTS` and `_CHROMIUM_APPS` in `main.py` |
| Notifications | win10toast / PowerShell toast / Tk | `UNUserNotificationCenter` |
| Tray / menu | `pystray` + `floating_widget.py` | `rumps` menu bar |
| Watchdog | `tt_watchdog.py`, `watchdog.py`, Scheduled Tasks | `mac_watchdog.py`, launchd |
| Install | Inno Setup, MSI, GPO | `.pkg`, `.dmg`, `setup.sh` |

## No Mac counterpart, on purpose

**`qb_company_tracker.py`** — reads which QuickBooks Desktop company file is
open, via the shell's file-dialog MRU in the registry and process handles.
QuickBooks Desktop is a Windows product; there is nothing here to read.

**`floating_widget.py`, `client_picker.py`, `custom_tray_menu.py`** — the
always-on-top ticker window. The Mac agent lives in the menu bar instead.
The *behaviour* attached to the ticker did port: the vendor hands-off gate
(`_show_client_widget` / `set_client_widget_enabled`) hides the manual
client controls while leaving automatic attribution running.

**`ensure_extension.py`** — silently force-installs the URL Reporter
extension by writing an `ExtensionInstallForcelist` policy under HKCU, which
Chrome and Edge both honour per-user on Windows. There is no per-user
equivalent on macOS: Chrome reads policy through the managed-preferences
domain and ignores values that are not *forced*, so it takes a configuration
profile installed by an admin or MDM. The extension itself is
cross-platform and works here once installed — it posts to the same
`http://127.0.0.1:7321/context` bus, whose handler is identical in both
agents. It also matters less here, because the Mac agent reads browser URLs
directly over AppleScript rather than scraping the address bar.

**`mdm_deploy.py`, `startup_task.py`, `register_watchdog_task.ps1`,
`installer.iss`, `build.bat`, `msi/`** — Windows deployment.

**`no_flash_check.py`, `probe_excel_tabs.py`** — one-off COM diagnostics.

**`morning_review.py`** — present in `windows_agent/` but imported by
nothing there. Dead on both sides; porting it would only spread it.

## Things that bite

- **`TimeTracker.spec` does not discover modules for you.** Anything new
  needs an entry in *both* `datas` and `hiddenimports`. Every import added
  by the port is guarded by `try/except`, so a module missing from the
  bundle does not crash the agent — the feature is simply, silently gone.

- **The server requires `start_ts` and `end_ts`** on every raw event and
  returns 400 otherwise, with no compatibility path. `test_event_contract.py`
  replays that validation against a payload built by the real `write_event`;
  run it before shipping.

- **`exe_name` carries a bundle identifier here.** Anything matching against
  it needs both vocabularies — see `_exe_family_matches` and
  `_MAC_BUNDLE_FAMILIES` in `ai_client_switcher.py`.

## Running the tests

```bash
cd mac_agent
python3 test_event_contract.py        # server contract + interval chunking
python3 test_client_matchers_fuzz.py  # matcher never raises on hostile names
```

Both stub the macOS frameworks, so they run anywhere.
