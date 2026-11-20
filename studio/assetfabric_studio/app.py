"""AssetFabric Studio — minimal PySide6 shell (real, offscreen-tested).

Surfaces today: **Status** (forge status), **Mirror** (newest frame a paired phone pushed — still or decoded video),
**Console** (a text input that remote Studio input lands in; it never executes commands). Remote input from a paired phone
(MirrorWeave C9, `drive_studio` capability) arrives as validated events in the LoomLink state dir's Studio spool;
`StudioInputBridge` turns each into a real Qt key / mouse / wheel event on this window.
Everything user-visible comes from locale keys (`studio.*`). SPEC surfaces not built yet (SwatchStudio, sandbox, character
creator, MCP/ACP host) are listed in TODO.md, not mocked here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import (QApplication, QLabel, QLineEdit, QMainWindow, QPlainTextEdit, QTabWidget, QVBoxLayout,
                               QWidget)

from forge.i18n import t
from forge.mirrorweave import StudioInputSpool, decode_latest, load_persisted, validate_studio_event

SPECIAL = {"space": (Qt.Key_Space, " "), "enter": (Qt.Key_Return, "\r"), "backspace": (Qt.Key_Backspace, "\b"),
           "tab": (Qt.Key_Tab, "\t"), "escape": (Qt.Key_Escape, ""), "left": (Qt.Key_Left, ""), "right": (Qt.Key_Right, ""),
           "up": (Qt.Key_Up, ""), "down": (Qt.Key_Down, ""), "slash": (Qt.Key_Slash, "/"), "minus": (Qt.Key_Minus, "-"),
           "period": (Qt.Key_Period, "."), "comma": (Qt.Key_Comma, ",")}


def qt_key(name: str, shift: bool = False) -> tuple[int, str]:
    if name in SPECIAL:
        return SPECIAL[name]
    if len(name) == 1 and name.isalpha():
        return int(Qt.Key_A) + ord(name) - ord("a"), (name.upper() if shift else name)
    if len(name) == 1 and name.isdigit():
        return int(Qt.Key_0) + int(name), name
    raise ValueError(name)


class StudioWindow(QMainWindow):
    def __init__(self, state_dir: Path | None = None, root: Path | None = None) -> None:
        super().__init__()
        self.state_dir, self.root = state_dir, root
        self.setWindowTitle(t("studio.title", root))
        self.tabs = QTabWidget()
        self.status_view = QPlainTextEdit()
        self.status_view.setReadOnly(True)
        self.mirror_label = QLabel(t("studio.mirror.empty", root))
        self.mirror_label.setAlignment(Qt.AlignCenter)
        self.console = QLineEdit()
        self.console.setPlaceholderText(t("studio.console.placeholder", root))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        con = QWidget()
        lay = QVBoxLayout(con)
        lay.addWidget(self.console)
        lay.addWidget(self.log)
        self.tabs.addTab(self.status_view, t("studio.tab.status", root))
        self.tabs.addTab(self.mirror_label, t("studio.tab.mirror", root))
        self.tabs.addTab(con, t("studio.tab.console", root))
        self.setCentralWidget(self.tabs)
        self.console.returnPressed.connect(self._submit)
        self.resize(960, 600)

    def _submit(self) -> None:
        # Typed text is echoed to the log only. Studio does not run shell or forge commands from this box (yet).
        self.log.appendPlainText(self.console.text())
        self.console.clear()

    def refresh_status(self) -> dict[str, Any]:
        from forge.status import collect_status

        st = collect_status(self.root)
        self.status_view.setPlainText(json.dumps({k: st[k] for k in ("healthy", "version", "milestone")}, indent=2))
        return st

    def refresh_mirror(self, stream: str = "screen") -> bool:
        if not self.state_dir:
            return False
        mroot = self.state_dir / "mirror"
        png = decode_latest(mroot, stream)
        if png is None:
            got = load_persisted(mroot, stream)
            png = got[1] if got and got[0].get("codec") in ("png", "jpeg", "webp") else None
        if png is None:
            return False
        img = QImage.fromData(png)
        self.mirror_label.setPixmap(QPixmap.fromImage(img))
        return not img.isNull()


class StudioInputBridge:
    """Polls the Studio spool and delivers each new event as a real Qt event. Re-validates every event (the spool is a file)."""

    def __init__(self, win: StudioWindow, spool: StudioInputSpool) -> None:
        self.win, self.spool, self.after = win, spool, -1
        self.delivered = 0

    def poll(self) -> int:
        n = 0
        for row in self.spool.read(self.after):
            self.after = row["seq"]
            try:
                ev = validate_studio_event(row["event"])
            except (ValueError, PermissionError):
                continue
            self.deliver(ev)
            n += 1
        self.delivered += n
        return n

    def _target(self, x: float, y: float) -> tuple[QWidget, QPointF]:
        w = self.win.centralWidget()
        gp = w.mapToGlobal(QPoint(int(x * max(1, w.width() - 1)), int(y * max(1, w.height() - 1))))
        child = QApplication.widgetAt(gp) or w.childAt(w.mapFromGlobal(gp)) or w
        return child, QPointF(child.mapFromGlobal(gp))

    def deliver(self, ev: dict[str, Any]) -> None:
        app = QApplication.instance()
        if ev["type"] == "key":
            key, text = qt_key(ev["key"], ev.get("shift", False))
            mods = Qt.ShiftModifier if ev.get("shift") else Qt.NoModifier
            target = app.focusWidget() or self.win
            for typ in (QEvent.KeyPress, QEvent.KeyRelease):
                app.sendEvent(target, QKeyEvent(typ, key, mods, text))
        elif ev["type"] == "pointer":
            target, pos = self._target(ev["x"], ev["y"])
            btn = Qt.LeftButton if ev["button"] == "left" else Qt.RightButton
            seq = {"move": [(QEvent.MouseMove, Qt.NoButton)], "down": [(QEvent.MouseButtonPress, btn)],
                   "up": [(QEvent.MouseButtonRelease, btn)],
                   "click": [(QEvent.MouseButtonPress, btn), (QEvent.MouseButtonRelease, btn)]}[ev["action"]]
            gpos = QPointF(target.mapToGlobal(pos.toPoint()))
            for typ, b in seq:
                buttons = b if typ == QEvent.MouseButtonPress else Qt.NoButton
                app.sendEvent(target, QMouseEvent(typ, pos, gpos, b, buttons, Qt.NoModifier))
            if ev["action"] in ("down", "click") and target.focusPolicy() != Qt.NoFocus:
                target.setFocus(Qt.MouseFocusReason)
        elif ev["type"] == "scroll":
            target, pos = self._target(0.5, 0.5)
            app.sendEvent(target, QWheelEvent(pos, QPointF(target.mapToGlobal(pos.toPoint())), QPoint(0, 0),
                                              QPoint(0, 120 * ev["dy"]), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))


def run(state_dir: Path | None = None, root: Path | None = None, poll_ms: int = 100) -> int:
    app = QApplication.instance() or QApplication([])
    win = StudioWindow(state_dir, root)
    win.refresh_status()
    win.show()
    if state_dir:
        bridge = StudioInputBridge(win, StudioInputSpool(state_dir / "mirror" / "studio_input.jsonl"))
        timer = QTimer(win)
        timer.timeout.connect(lambda: (bridge.poll(), win.refresh_mirror()))
        timer.start(poll_ms)
    return app.exec()
