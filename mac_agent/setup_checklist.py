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
    NSApp, NSBackingStoreBuffered, NSBox, NSButton, NSColor, NSFont, NSImage,
    NSImageView, NSMakeRect, NSPanel, NSProgressIndicator, NSScreen,
    NSScrollView, NSTextField, NSView, NSFloatingWindowLevel,
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

try:
    from AppKit import NSWindowStyleMaskFullSizeContentView as _FULL_SIZE
except Exception:  # pragma: no cover
    _FULL_SIZE = 1 << 15

WIDTH = 500
PAD = 24
ROW_MIN_H = 56        # a card row grows with its detail text
HEADER_H = 128        # icon, title, subtitle, progress
FOOTER_H = 64
MIN_H = 380
SCREEN_MARGIN = 120   # never taller than the screen minus this
CLOSE_SNOOZE_S = 3600

# Rows that only wait for the person to open an app are folded into one
# "Asks when you open…" line instead of a row each (a fresh Mac has many).
# System Events is a background helper nobody "opens"; never list it there.
_HIDDEN_WHILE_WAITING = {"com.apple.systemevents"}


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


def _label(text, size=13.0, bold=False, color=None, wrap=False, width=None,
           weight=None, lines=0):
    f = (NSTextField.wrappingLabelWithString_(text) if wrap
         else NSTextField.labelWithString_(text))
    if weight is not None:
        f.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
    else:
        f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color is not None:
        f.setTextColor_(color)
    if width:
        f.setPreferredMaxLayoutWidth_(width)
    if lines:
        f.setMaximumNumberOfLines_(lines)
    return f


# NSFontWeight values (constants are not exported on every PyObjC build).
_MEDIUM, _SEMIBOLD = 0.23, 0.3


def _status(row):
    """(SF Symbol, tint, emoji fallback) for a row's state."""
    if row["ok"] is True:
        return "checkmark.circle.fill", NSColor.systemGreenColor(), "✅"
    if row["ok"] is None:
        return "clock", NSColor.tertiaryLabelColor(), "⏳"
    if row["required"]:
        return "xmark.circle.fill", NSColor.systemRedColor(), "❌"
    return "exclamationmark.circle.fill", NSColor.systemOrangeColor(), "⚠️"


def _icon(symbol, tint, fallback, size=20.0):
    """An SF Symbol (macOS 11+), else the emoji as a label."""
    try:
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, None)
    except Exception:
        img = None
    if img is None:
        return _label(fallback, size - 3)
    try:
        from AppKit import NSImageSymbolConfiguration
        img = img.imageWithSymbolConfiguration_(
            NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, _MEDIUM))
    except Exception:
        pass
    v = NSImageView.imageViewWithImage_(img)
    v.setContentTintColor_(tint)
    return v


def _card(frame):
    """Rounded, bordered panel the rows sit in (System Settings style)."""
    box = NSBox.alloc().initWithFrame_(frame)
    box.setBoxType_(4)              # NSBoxCustom
    box.setTitlePosition_(0)        # NSNoTitle
    box.setCornerRadius_(10.0)
    box.setBorderWidth_(1.0)
    box.setBorderColor_(NSColor.separatorColor())
    box.setFillColor_(NSColor.controlBackgroundColor())
    box.setContentViewMargins_((0, 0))
    return box


def _button(title, action, target, primary=False, small=False):
    b = NSButton.buttonWithTitle_target_action_(title, target, action)
    b.setBezelStyle_(_BEZEL)
    if small:
        b.setControlSize_(1)        # NSControlSizeSmall
        b.setFont_(NSFont.systemFontOfSize_(11.5))
    if primary:
        b.setKeyEquivalent_("\r")  # default button: drawn in the accent colour
    b.sizeToFit()
    return b


def _short(label: str) -> str:
    return label.replace("Automation: ", "").replace(" (recommended)", "")


def _text_h(text, width, size=11.5) -> float:
    """Height a wrapped label needs at this width."""
    f = _label(text, size, wrap=True, width=width)
    return float(f.fittingSize().height)


def _row_h(detail, text_w) -> float:
    return max(ROW_MIN_H, 12 + 18 + 3 + _text_h(detail, text_w) + 12)


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
                NSMakeRect(0, 0, WIDTH, MIN_H), _TITLED | _CLOSABLE | _FULL_SIZE,
                NSBackingStoreBuffered, False)
            self.window.setTitle_("TimeTracker setup")
            self.window.setTitlebarAppearsTransparent_(True)
            self.window.setTitleVisibility_(1)      # NSWindowTitleHidden
            self.window.setMovableByWindowBackground_(True)
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

        # Rows that only wait for an app to be opened fold into one line.
        waiting = [r for r in rows if r["ok"] is None and not r["fix"]]
        shown = [r for r in rows if r not in waiting]
        required = [r for r in shown if r["required"]]
        other = [r for r in shown if not r["required"]]
        later_apps = [_short(r["label"]) for r in waiting
                      if r["key"] not in _HIDDEN_WHILE_WAITING]

        inner = WIDTH - 2 * PAD
        gray = NSColor.secondaryLabelColor()

        # ---- scrolling body: banner + cards ---------------------------------
        def text_w(r):
            return inner - 48 - (92 if r["fix"] else 16)
        heights = {id(r): _row_h(r["detail"], text_w(r)) for r in shown}
        later_text = ", ".join(later_apps)
        later_h = _row_h(later_text, inner - 64) if later_apps else 0

        def card_h(items):
            return sum(heights[id(r)] for r in items)
        body_h = 8
        if asking:
            body_h += 52
        for items in (required, other):
            if items:
                body_h += 26 + card_h(items) + 20
        if later_apps:
            body_h += 26 + later_h + 20
        body = _Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, body_h))
        y = 8

        if asking:
            banner = _card(NSMakeRect(PAD, y, inner, 40))
            banner.setFillColor_(NSColor.systemBlueColor().colorWithAlphaComponent_(0.12))
            banner.setBorderColor_(NSColor.systemBlueColor().colorWithAlphaComponent_(0.35))
            body.addSubview_(banner)
            ic = _icon("hand.point.up.left.fill", NSColor.systemBlueColor(), "👉", 15.0)
            ic.setFrame_(NSMakeRect(PAD + 12, y + 10, 20, 20))
            body.addSubview_(ic)
            note = _label(f"Click OK on the popup that just appeared ({asking}).", 13.0,
                          weight=_MEDIUM, color=NSColor.systemBlueColor())
            note.setFrame_(NSMakeRect(PAD + 40, y + 11, inner - 52, 18))
            body.addSubview_(note)
            y += 52

        def section(title, items, y):
            if not items:
                return y
            h = _label(title, 12.0, weight=_SEMIBOLD, color=gray)
            h.setFrame_(NSMakeRect(PAD + 4, y, inner, 16))
            body.addSubview_(h)
            y += 26
            card = _card(NSMakeRect(PAD, y, inner, card_h(items)))
            body.addSubview_(card)
            ry = y
            for i, r in enumerate(items):
                rh = heights[id(r)]
                if i:
                    sep = NSBox.alloc().initWithFrame_(NSMakeRect(PAD + 48, ry, inner - 48, 1))
                    sep.setBoxType_(2)      # NSBoxSeparator
                    body.addSubview_(sep)
                symbol, tint, fallback = _status(r)
                ic = _icon(symbol, tint, fallback)
                ic.setFrame_(NSMakeRect(PAD + 14, ry + (rh - 22) / 2, 22, 22))
                body.addSubview_(ic)
                tw = text_w(r)
                t = _label(_short(r["label"]), 13.0, weight=_MEDIUM)
                t.setFrame_(NSMakeRect(PAD + 48, ry + 12, tw, 18))
                body.addSubview_(t)
                d = _label(r["detail"], 11.5, color=gray, wrap=True, width=tw)
                d.setFrame_(NSMakeRect(PAD + 48, ry + 33, tw, rh - 33 - 10))
                body.addSubview_(d)
                if r["fix"]:
                    b = _button(r["fix"], "fix:", self.ctrl, small=True)
                    b.setTag_(rows.index(r))
                    b.setEnabled_(not asking)
                    bw = max(64.0, b.frame().size.width + 8)
                    b.setFrame_(NSMakeRect(PAD + inner - bw - 12, ry + (rh - 24) / 2, bw, 24))
                    body.addSubview_(b)
                ry += rh
            return y + card_h(items) + 20

        y = section("Required", required, y)
        y = section("Recommended", other, y)
        if later_apps:
            h = _label("Later", 12.0, weight=_SEMIBOLD, color=gray)
            h.setFrame_(NSMakeRect(PAD + 4, y, inner, 16))
            body.addSubview_(h)
            y += 26
            body.addSubview_(_card(NSMakeRect(PAD, y, inner, later_h)))
            ic = _icon("clock", NSColor.tertiaryLabelColor(), "⏳")
            ic.setFrame_(NSMakeRect(PAD + 14, y + (later_h - 22) / 2, 22, 22))
            body.addSubview_(ic)
            t = _label("Asks the first time you open them", 13.0, weight=_MEDIUM)
            t.setFrame_(NSMakeRect(PAD + 48, y + 12, inner - 64, 18))
            body.addSubview_(t)
            d = _label(later_text, 11.5, color=gray, wrap=True, width=inner - 64)
            d.setFrame_(NSMakeRect(PAD + 48, y + 33, inner - 64, later_h - 33 - 10))
            body.addSubview_(d)

        # ---- window: fixed header + scrolling body + fixed footer -----------
        max_h = MIN_H
        try:
            screen = (self.window.screen() if self.window is not None else None) \
                or NSScreen.mainScreen()
            max_h = max(MIN_H, screen.visibleFrame().size.height - SCREEN_MARGIN)
        except Exception:
            max_h = 640
        height = min(HEADER_H + body_h + FOOTER_H, max_h)
        scroll_h = height - HEADER_H - FOOTER_H

        view = _Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, height))
        view.setWantsLayer_(True)

        try:
            app_icon = NSImageView.imageViewWithImage_(NSApp.applicationIconImage())
            app_icon.setFrame_(NSMakeRect(PAD, 34, 44, 44))
            view.addSubview_(app_icon)
            tx = PAD + 56
        except Exception:
            tx = PAD
        head = _label("Finish setting up TimeTracker" if missing
                      else "TimeTracker is set up", 20.0, weight=_SEMIBOLD)
        head.setFrame_(NSMakeRect(tx, 34, WIDTH - tx - PAD, 26))
        view.addSubview_(head)
        req_all = [r for r in rows if r["required"]]
        done_n = sum(1 for r in req_all if r["ok"] is True)
        sub_text = (f"{done_n} of {len(req_all)} required done. Until the rest are on, "
                    "some work is captured without the page or file name." if missing else
                    "Everything required is on. You can close this window.")
        sub = _label(sub_text, 12.0, color=gray, wrap=True, width=WIDTH - tx - PAD, lines=2)
        sub.setFrame_(NSMakeRect(tx, 62, WIDTH - tx - PAD, 32))
        view.addSubview_(sub)
        if req_all:
            bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(PAD, 102, WIDTH - 2 * PAD, 8))
            bar.setStyle_(0)                 # bar
            bar.setIndeterminate_(False)
            bar.setControlSize_(1)
            bar.setMinValue_(0)
            bar.setMaxValue_(len(req_all))
            bar.setDoubleValue_(done_n)
            view.addSubview_(bar)

        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, HEADER_H, WIDTH, scroll_h))
        scroll.setHasVerticalScroller_(body_h > scroll_h)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setBorderType_(0)
        scroll.setDocumentView_(body)
        view.addSubview_(scroll)

        line = NSBox.alloc().initWithFrame_(NSMakeRect(0, height - FOOTER_H, WIDTH, 1))
        line.setBoxType_(2)
        view.addSubview_(line)
        by = height - FOOTER_H + (FOOTER_H - 28) / 2
        pending = [r for r in rows if r["fix"] == "Ask"]
        right = WIDTH - PAD
        if missing:
            primary = bool(pending)
            if pending:
                ask = _button("Ask for all now", "askAll:", self.ctrl, primary=True)
                ask.setEnabled_(not asking)
                w = ask.frame().size.width + 16
                ask.setFrame_(NSMakeRect(right - w, by, w, 28))
                view.addSubview_(ask)
                right -= w + 10
            later = _button("Remind me later", "later:", self.ctrl, primary=not primary)
            w = later.frame().size.width + 16
            later.setFrame_(NSMakeRect(right - w, by, w, 28))
            view.addSubview_(later)
        else:
            done = _button("Done", "done:", self.ctrl, primary=True)
            w = max(80.0, done.frame().size.width + 16)
            done.setFrame_(NSMakeRect(right - w, by, w, 28))
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
