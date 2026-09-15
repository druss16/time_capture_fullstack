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

## Building

`build_and_release.sh` is what ships. It does NOT use a spec file — it runs

    pyinstaller --onefile --name TimeTrackerAgent --clean --noconfirm main.py

and relies entirely on PyInstaller's import analysis, which does find every
module this agent imports, including the ones reached from inside functions.
`TimeTracker.spec` and `TimeTrackerAgent.spec` exist and are kept correct,
but only the Makefile's `pyi` target uses one.

What analysis cannot do is install a dependency nobody declared.
`requirements.txt` did not describe the environment the shipping build
actually needs, and a clean build from it produced a binary that died on
launch:

  * `certifi` — imported at module scope in `main.py`, unguarded, to point
    `SSL_CERT_FILE` before any HTTPS call. Missing it is fatal at import.
  * `customtkinter` — its import in `timetracker_gui.py` is wrapped in
    `try/except ImportError`, which looks optional, but four classes below
    subclass `ctk.*` at module scope. Missing it raised `NameError: name
    'ctk' is not defined` while the module was still importing. The shipped
    1.7.22 bundles customtkinter 6.0.0, so the real build machine always had
    it; the file simply never said so. There is now a shim so the module
    degrades instead of exploding, and the dependency is declared.
  * `pynput` — genuinely optional (the ⌃⌥T hotkey), but intended.
  * `psutil` — both Mac meeting probes are gated on it.

Two modules show up in PyInstaller's warn file as missing, and both are
correct: `qb_company_tracker` (Windows-only, and every collector in
`collect_all_evidence` is individually exception-wrapped, so it degrades to
producing no evidence) and `mac_agent` (an import fallback that cannot resolve
inside a bundle and never needs to). A third, `pdf_identity`, is dormant on
both platforms — nothing imports it — so a spec-less build leaves it out;
`TimeTracker.spec` forces it in for parity with the Windows agent.

After a build, check that list is still only those:

    grep '^missing module named' build/TimeTracker*/warn-TimeTracker*.txt

## Testing a build end to end

`test_event_contract.py` checks the payload shape without a server. To check
the whole chain, run the built app against a stub backend that replays
`tracker/views.raw_events`' validation — an event that stub accepts is one
production accepts.

Two things make the difference between a test that proves something and one
that quietly proves nothing:

**Run the `.app`, never the bare binary.** The notification manager calls
`+[UNUserNotificationCenter currentNotificationCenter]`, which throws
`NSInternalInconsistencyException` ("bundleProxyForCurrentProcess is nil")
when the process has no bundle. That is an Objective-C exception — no Python
`try/except` catches it, and the process aborts with SIGABRT partway through
startup, right after the first sync. Production is
`/Applications/TimeTracker.app`, so it never sees this; a `--onefile` binary
run from `dist/` dies every time. Note that `build_and_release.sh` installs
the bare binary to `/usr/local/bin/TimeTrackerAgent`, which would hit the
same wall — the working install on this machine is the `.app`.

**A fresh build holds no permissions.** It is a new code signature, so TCC
treats it as a different application: no Accessibility, which means
`get_window_title_via_ax` returns nothing and EVERY window title arrives
empty. Detection still works (NSWorkspace/System Events name the app) and so
does everything that reads a path over AppleScript, but anything that
depends on the title reads as a total failure when it is really a missing
permission. Grant Accessibility to the test build, or verify title-dependent
behavior with the module-level tests instead.

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
