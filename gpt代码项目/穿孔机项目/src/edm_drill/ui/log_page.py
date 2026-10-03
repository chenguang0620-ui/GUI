"""运行日志页。"""

from __future__ import annotations

from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from ..event_log import EventLog


class LogPage(QWidget):
    def __init__(self, events: EventLog):
        super().__init__()
        self.events = events
        self.last_version = -1
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)

    def refresh(self) -> None:
        if self.events.version != self.last_version:
            self.text.setPlainText("\n".join(self.events.entries))
            self.text.moveCursor(self.text.textCursor().MoveOperation.End)
            self.last_version = self.events.version
