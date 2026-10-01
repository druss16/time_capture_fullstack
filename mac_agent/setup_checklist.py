"""The "Finish setting up TimeTracker" window.

macOS's own permission prompts are one-shot and easy to miss: a dismissed
Automation prompt is never shown again, and the Accessibility prompt is one
click from gone. This window is TimeTracker's own, so it can keep asking:

* one row per permission with a live ✅ / ❌, re-checked every 3s while open,
  so a switch flipped in System Settings shows up without a restart;
* a Fix button per ❌ row: Accessibility and Automation open the exact pane
  of System Settings; an app never asked gets "Ask", which triggers macOS's
  prompt right now while the window says "Click OK on the popup";
* it stays up until every REQUIRED row is ✅, or the person picks "Remind me
  later" (back in 4 hours). Closing it with the red button is a 1-hour
  snooze, not a dismissal.

Native AppKit in the agent's own process (rumps already runs the NSApp), so
it shares the menu bar's main thread. Rows come from
permissions.PermissionMonitor.rows(); nothing here decides policy.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Callable, Optional

import objc
from AppKit import (
    NSApp, NSBackingStoreBuffered, NSButton, NSColor, NSFont, NSMakeRect,
    NSPanel, NSTextField, NSView, NSFloatingWindowLevel,
)
from Foundation import NSObject, NSTimer

try:  # constants moved names across macOS SDKs
    from AppKit import (NSWindowStyleMaskTitled as _TITLED,
                        NSWindowStyleMaskClosable as _CLOSABLE)
except Exception:  # pragma: no cover
    _TITLED, _CLOSABLE = 1, 2

try:
    from AppKit import NSBezelStyleRounded as _BEZEL
except Exception:  # pragma: no cover
    _BEZEL = 1

WIDTH = 600
ROW_H = 62
PAD = 20
CLOSE_SNOOZE_S = 3600


# ---------------------------------------------------------------------------
# Main-thread hand-off. The permission monitor ticks on a background thread;
# AppKit may only be touched on the main thread.
# ---------------------------------------------------------------------------
class _MainThreadCaller(NSObject):
    def init(self):
        self = objc.super(_MainThreadCaller, self).init()
        if self is None:
            return None
        self._q = deque()
        self._lock = threading.Lock()
        return self

    @objc.python_method
    def submit(self, fn):
        with self._lock:
            self._q.append(fn)
        self.performSelectorOnMainThread_withObject_waitUntilDone_("drain:", None, False)

    def drain_(self, _):
        while True:
            with self._lock:
                if not self._q:
                    return
                fn = self._q.popleft()
            try:
                fn()
            except Exception as e:
                print(f"[SETUP] main-thread call failed: {e}")


_caller = None


def call_on_main(fn: Callable[[], None]) -> None:
    global _caller
    if _caller is None:
        _caller = _MainThreadCaller.alloc().init()
    _caller.submit(fn)


class _Flipped(NSView):
    """Top-down coordinates, so rows are laid out like a list."""

    def isFlipped(self):
        return True


def _label(text, size=13.0, bold=False, color=None, wrap=False, width=None):
    f = (NSTextField.wrappingLabelWithString_(text) if wrap
         else NSTextField.labelWithString_(text))
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color is not None:
        f.setTextColor_(color)
    if width:
        f.setPreferredMaxLayoutWidth_(width)
    return f


def _glyph(row) -> str:
    if row["ok"] is True:
        return "✅"
    if row["ok"] is None:
        return "⏳"
    return "❌" if row["required"] else "⚠️"


class _Controller(NSObject):
    """Target for the buttons, the refresh timer and the window delegate."""

    def initWithChecklist_(self, checklist):
        self = objc.super(_Controller, self).init()
        if self is None:
            return None
        self.checklist = checklist
        return self

    def fix_(self, sender):
        self.checklist._on_fix(int(sender.tag()))

    def askAll_(self, sender):
        self.checklist._on_ask_all()

    def later_(self, sender):
        self.checklist._on_later()

    def done_(self, sender):
        self.checklist._on_done()

    def tick_(self, timer):
        self.checklist._on_tick()

    def windowShouldClose_(self, sender):
        self.checklist._on_close_button()
        return True


class SetupChecklist:
    """One window per process; show() brings it back if already open."""

    def __init__(self, monitor, on_change: Optional[Callable[[], None]] = None,
                 live: bool = True):
        self.mon = monitor
        self.on_change = on_change or (lambda: None)
        self.live = live
        self.window = None
        self.ctrl = _Controller.alloc().initWithChecklist_(self)
        self._timer = None
        self._rows = []
        self._sig = None
        self._busy: Optional[str] = None   # a Fix/Ask in flight

    # -- public ------------------------------------------------------------
    def is_open(self) -> bool:
        return self.window is not None and bool(self.window.isVisible())

    def show(self) -> None:
        if self.window is None:
            self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, WIDTH, 400), _TITLED | _CLOSABLE,
                NSBackingStoreBuffered, False)
            self.window.setTitle_("TimeTracker setup")
            self.window.setDelegate_(self.ctrl)
            self.window.setReleasedWhenClosed_(False)
            self.window.setHidesOnDeactivate_(False)
            self.window.setLevel_(NSFloatingWindowLevel)
        self._sig = None
        self.render()
        self.window.center()
        try:
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass
        self.window.makeKeyAndOrderFront_(None)
        if self.live and self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                3.0, self.ctrl, "tick:", None, True)

    def close(self) -> None:
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        if self.window is not None:
            self.window.orderOut_(None)

    # -- rendering ---------------------------------------------------------
    def render(self) -> None:
        rows = self.mon.rows()
        asking = self.mon.asking or self._busy
        sig = (tuple((r["key"], r["ok"], r["status"], r["detail"], r["fix"]) for r in rows),
               asking, tuple(self.mon.missing_required()))
        if sig == self._sig:
            return
        self._sig = sig
        self._rows = rows
        missing = self.mon.missing_required()

        required = [r for r in rows if r["required"]]
        other = [r for r in rows if not r["required"]]
        height = PAD + 70 + (28 if asking else 0) \
            + (24 + ROW_H * len(required) if required else 0) \
            + (24 + ROW_H * len(other) if other else 0) + 70
        view = _Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, height))
        gray = NSColor.secondaryLabelColor()
        y = PAD

        head = _label("Finish setting up TimeTracker" if missing
                      else "TimeTracker is set up", 18.0, bold=True)
        head.setFrame_(NSMakeRect(PAD, y, WIDTH - 2 * PAD, 26))
        view.addSubview_(head)
        y += 30
        sub_text = (f"{len(missing)} required permission{'s' if len(missing) != 1 else ''} "
                    "missing. Until they are on, some of your work is captured without the "
                    "page or file name." if missing else
                    "Everything required is on. Rows marked ⚠️ are optional extras.")
        sub = _label(sub_text, 12.0, color=gray, wrap=True, width=WIDTH - 2 * PAD)
        sub.setFrame_(NSMakeRect(PAD, y, WIDTH - 2 * PAD, 34))
        view.addSubview_(sub)
        y += 40

        if asking:
            note = _label(f"👉 Click OK on the popup that just appeared ({asking}).",
                          13.0, bold=True, color=NSColor.systemBlueColor())
            note.setFrame_(NSMakeRect(PAD, y, WIDTH - 2 * PAD, 20))
            view.addSubview_(note)
            y += 28

        def section(title, items, y):
            if not items:
                return y
            h = _label(title.upper(), 10.5, bold=True, color=gray)
            h.setFrame_(NSMakeRect(PAD, y, WIDTH - 2 * PAD, 16))
            view.addSubview_(h)
            y += 24
            for r in items:
                idx = rows.index(r)
                g = _label(_glyph(r), 16.0)
                g.setFrame_(NSMakeRect(PAD, y + 2, 26, 22))
                view.addSubview_(g)
                t = _label(r["label"], 13.0, bold=True)
                t.setFrame_(NSMakeRect(PAD + 32, y, WIDTH - 2 * PAD - 32 - 90, 18))
                view.addSubview_(t)
                d = _label(r["detail"], 11.5, color=gray, wrap=True,
                           width=WIDTH - 2 * PAD - 32 - 90)
                d.setFrame_(NSMakeRect(PAD + 32, y + 19, WIDTH - 2 * PAD - 32 - 90, 34))
                view.addSubview_(d)
                if r["fix"]:
                    b = NSButton.alloc().initWithFrame_(NSMakeRect(WIDTH - PAD - 80, y + 2, 80, 28))
                    b.setTitle_(r["fix"])
                    b.setBezelStyle_(_BEZEL)
                    b.setTag_(idx)
                    b.setTarget_(self.ctrl)
                    b.setAction_("fix:")
                    b.setEnabled_(not asking)
                    view.addSubview_(b)
                y += ROW_H
            return y

        y = section("Required", required, y)
        y = section("Recommended & optional", other, y)

        y += 14
        pending = [r for r in rows if r["fix"] == "Ask"]
        if pending:
            ask = NSButton.alloc().initWithFrame_(NSMakeRect(PAD, y, 150, 30))
            ask.setTitle_("Ask for all now")
            ask.setBezelStyle_(_BEZEL)
            ask.setTarget_(self.ctrl)
            ask.setAction_("askAll:")
            ask.setEnabled_(not asking)
            view.addSubview_(ask)
        if missing:
            later = NSButton.alloc().initWithFrame_(NSMakeRect(WIDTH - PAD - 150, y, 150, 30))
            later.setTitle_("Remind me later")
            later.setBezelStyle_(_BEZEL)
            later.setTarget_(self.ctrl)
            later.setAction_("later:")
            view.addSubview_(later)
        else:
            done = NSButton.alloc().initWithFrame_(NSMakeRect(WIDTH - PAD - 100, y, 100, 30))
            done.setTitle_("Done")
            done.setBezelStyle_(_BEZEL)
            done.setKeyEquivalent_("\r")
            done.setTarget_(self.ctrl)
            done.setAction_("done:")
            view.addSubview_(done)

        if self.window is not None:
            self.window.setContentSize_((WIDTH, height))
            self.window.setContentView_(view)
        self.view = view

    # -- actions -----------------------------------------------------------
    def _in_background(self, label: str, fn) -> None:
        if self._busy:
            return
        self._busy = label

        def run():
            try:
                fn()
            finally:
                self._busy = None
                try:
                    self.mon.refresh()
                except Exception:
                    pass
                call_on_main(self._after_change)

        threading.Thread(target=run, daemon=True, name="SetupFix").start()
        self.render()

    def _after_change(self) -> None:
        self.render()
        self.on_change()

    def _on_fix(self, idx: int) -> None:
        if not 0 <= idx < len(self._rows):
            return
        row = self._rows[idx]
        self._in_background(row["label"].replace("Automation: ", ""),
                            lambda: self.mon.fix(row["key"]))

    def _on_ask_all(self) -> None:
        self._in_background("one app at a time", self.mon.ask_all_pending)

    def _on_later(self) -> None:
        self.mon.remind_later()
        self.close()

    def _on_done(self) -> None:
        self.mon.clear_snooze()
        self.close()

    def _on_close_button(self) -> None:
        if self.mon.needs_attention():
            self.mon.remind_later(CLOSE_SNOOZE_S)
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None

    def _on_tick(self) -> None:
        """While open: re-check (cheap local calls) and redraw on change.
        A grant made in System Settings flips its row within ~3s."""
        if self._busy:
            self.render()
            return
        try:
            changed = self.mon.refresh()
        except Exception:
            changed = False
        self.render()
        if changed:
            self.on_change()
