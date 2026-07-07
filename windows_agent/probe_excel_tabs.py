r"""
probe_excel_tabs.py  —  DIAGNOSTIC ONLY. Not imported by the agent; run by hand.

Purpose: answer the Tier 2 go/no-go. Can we read Excel worksheet TAB NAMES
(the one place an unsaved "Book2" can reveal its client), and which method is
cleanest on this machine?

HOW TO RUN (on the Windows box):
    1. Open Excel with a workbook that has recognizable tab names — ideally an
       unsaved Book2 whose tabs you've named like a real workday
       (e.g. "DivineMercy_JE", "StJames_Payroll", "Sheet3").
    2. Leave Excel open (it does NOT need to be the foreground window).
    3. In a terminal:  python probe_excel_tabs.py
    4. Paste the output back.

It tries TWO read-only methods and prints what each returns:

  [1] UI Automation (uiautomation)  — reads the accessibility tree of the
      ALREADY-RUNNING Excel window, found by its window class 'XLMAIN'. Does
      NOT launch Excel, create a process, or toggle window visibility. This is
      the SAME mechanism the agent already uses for browser URLs, so it's the
      candidate for the real Tier 2 capture. No black-screen risk.

  [2] COM via GetActiveObject       — attaches to the EXISTING Excel instance
      in the Running Object Table. Read-only: it NEVER calls Dispatch() (which
      would launch a new Excel — the usual cause of flashing/black windows) and
      NEVER sets .Visible. Included only for comparison. GetActiveObject can
      fail if Excel is busy/modal — that's expected; it just prints the error.

NEITHER method opens, closes, launches, or changes anything.
"""

import sys


def find_excel_windows():
    """Return HWNDs of top-level Excel frame windows (class 'XLMAIN')."""
    try:
        import win32gui
    except Exception as e:
        print("  (win32gui unavailable: %s)" % e)
        return []
    hwnds = []

    def _cb(h, _):
        try:
            if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "XLMAIN":
                hwnds.append(h)
        except Exception:
            pass
    win32gui.EnumWindows(_cb, None)
    return hwnds


def probe_uia():
    print("\n=== [1] UI Automation (safe: reads existing window, no launch) ===")
    try:
        import uiautomation as auto
    except Exception as e:
        print("  uiautomation not installed (pip install uiautomation):", e)
        return
    hwnds = find_excel_windows()
    if not hwnds:
        print("  No Excel 'XLMAIN' window found — is a workbook open?")
        return
    for hwnd in hwnds:
        try:
            win = auto.ControlFromHandle(hwnd)
            if not win:
                continue
            print(f"  Excel window: {win.Name!r}")
            # Collect every TabItem in the subtree — Excel's sheet tabs are the
            # bottom tab strip. Cast a wide net across Office builds: match by
            # ControlType 'TabItem', or any element whose AutomationId/Name
            # hints at a sheet tab.
            tabs, other_tabish = [], []
            for ctrl, depth in auto.WalkControl(win, includeTop=False, maxDepth=14):
                try:
                    ct = ctrl.ControlTypeName
                    nm = (ctrl.Name or "").strip()
                    aid = (ctrl.AutomationId or "")
                except Exception:
                    continue
                if not nm:
                    continue
                if ct == "TabItemControl":
                    tabs.append(nm)
                elif "tab" in aid.lower() or "sheet" in aid.lower():
                    other_tabish.append(f"[{ct}] {nm!r} (AutomationId={aid!r})")
            if tabs:
                print(f"  >>> SHEET TABS via UIA: {tabs}")
            else:
                print("  No TabItemControl found at depth<=14.")
            if other_tabish:
                print("  other tab-ish elements:")
                for x in other_tabish[:20]:
                    print("     ", x)
        except Exception as e:
            print(f"  UIA probe error on hwnd {hwnd}: {type(e).__name__}: {e}")


def probe_com():
    print("\n=== [2] COM GetActiveObject (read-only; NEVER launches Excel) ===")
    try:
        import win32com.client
        import pythoncom
    except Exception as e:
        print("  pywin32 not installed:", e)
        return
    pythoncom.CoInitialize()
    try:
        # GetActiveObject attaches to an already-running Excel. It does NOT
        # create one (that would be Dispatch()) and does NOT show any window.
        xl = win32com.client.GetActiveObject("Excel.Application")
        wb = xl.ActiveWorkbook
        if wb is None:
            print("  Excel running but no active workbook.")
            return
        print(f"  workbook     : {wb.Name}")
        print(f"  active sheet : {wb.ActiveSheet.Name}")
        print(f"  ALL tabs     : {[ws.Name for ws in wb.Worksheets]}")
    except Exception as e:
        print(f"  COM error (expected if Excel busy/modal/closed): {type(e).__name__}: {e}")
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


if __name__ == "__main__":
    print("Excel sheet-tab probe — open a workbook (ideally an unsaved Book2 with")
    print("client-named tabs) and run this. Neither method launches or changes Excel.")
    probe_uia()
    probe_com()
    print("\nDone. Paste the output back to compare UIA vs COM for Tier 2.")
