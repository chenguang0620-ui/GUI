"""工艺/诊断页面：组合独立的反馈设置与运行日志页面。"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QFrame, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from ..event_log import EventLog
from ..job_service import JobService
from ..settings_store import SettingsStore
from .log_page import LogPage
from .settings_page import SettingsPage


class DiagnosticsPage(QWidget):
    def __init__(
        self, job: JobService, store: SettingsStore,
        events: EventLog, action: Callable[[Callable[[], None]], None],
    ):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        tabs = QTabWidget()
        self.settings = SettingsPage(job, store, action)
        self.logs = LogPage(events)
        # 设置项较多，允许该页滚动，避免其最小高度把首页整窗撑大。
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setWidget(self.settings)
        tabs.addTab(settings_scroll, "位置反馈 / 参数")
        tabs.addTab(self.logs, "状态 / 报警日志")
        layout.addWidget(tabs)

    def refresh(self) -> None:
        self.settings.refresh()
        self.logs.refresh()
