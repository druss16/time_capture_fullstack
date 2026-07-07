r"""
no_flash_check.py  —  Tier 2 safety check. Run BEFORE tagging an agent release.

Purpose: prove the Tier 2 Excel read cannot flash / pop up windows. It makes the
exact read-only COM call the agent uses (GetActiveObject — attaches to a running
Excel, never launches one), 40 times in a row, so any window flash would be
obvious.

HOW TO RUN (on the Windows box), same as the probe:
    1. Open Excel with any workbook (ideally an unsaved Book2).
    2. In a terminal:
           cd windows_agent
           python no_flash_check.py
    3. WATCH THE SCREEN while it runs (~12 seconds). It should print sheet names
       and NOTHING should flash, pop up, or steal focus.

If you see zero flashing -> safe to tag the release.
If you EVER see a flash/new window -> stop, tell Claude, we switch to UIA.
"""
import time

try:
    import win32com.client
    import pythoncom
except Exception as e:
    print("pywin32 not installed (pip install pywin32):", e)
    raise SystemExit(1)

print("Running 40 read-only Excel reads. Watch for ANY window flash...\n")
for i in range(40):
    pythoncom.CoInitialize()
    try:
        xl = win32com.client.GetActiveObject("Excel.Application")  # attach; never launches
        wb = xl.ActiveWorkbook
        name = wb.ActiveSheet.Name if wb else "(no workbook)"
        print(f"  {i:>2}: active sheet = {name!r}")
    except Exception as e:
        # Expected if Excel is busy/modal/closed — a miss, NOT a flash.
        print(f"  {i:>2}: (no read: {type(e).__name__})")
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    time.sleep(0.3)

print("\nDONE. Did any Excel window flash, pop up, or steal focus? Should be ZERO.")
