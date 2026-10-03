"""机床主窗口：参考三栏监控界面，底部固定操作与页面导航。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..domain import MachineMode
from ..alignment_service import AlignmentService
from ..event_log import EventLog
from ..job_service import JobService
from ..manual_service import ManualService
from ..settings_store import SettingsStore
from .diagnostics_page import DiagnosticsPage
from .alignment_page import AlignmentPage
from .manual_page import ManualPage
from .overview_page import OverviewPage
from .program_page import ProgramPage


STYLE = """
QWidget { background:#10181d; color:#dce5e9; font-family:'Microsoft YaHei','Noto Sans CJK SC',sans-serif; font-size:12px; }
QLabel { background:transparent; }
QFrame#panel, QGroupBox { background:#19242b; border:1px solid #394a54; border-radius:4px; }
QGroupBox { margin-top:9px; padding:10px; font-weight:bold; }
QGroupBox::title { subcontrol-origin:margin; left:8px; padding:0 4px; }
QLabel#panelTitle { color:#f3f6f7; font-size:14px; font-weight:bold; }
QLabel#coordinateReadout, QLabel#depthReadout { color:#f5f7f9; font-size:25px; font-weight:bold; }
QLabel#subtle { color:#a1b1ba; font-size:11px; }
QLabel#goodStatus { color:#3dd58a; font-size:19px; font-weight:bold; }
QLabel#brand { color:#ffd22b; font-size:18px; font-weight:bold; }
QLabel#headerStatus { color:#c4d2d8; font-size:11px; }
QPushButton { background:#27353e; border:1px solid #42545e; border-radius:3px; padding:6px 10px; min-height:26px; }
QPushButton:hover { background:#344650; border-color:#768994; }
QPushButton:disabled { color:#75848d; background:#202b31; }
QPushButton#navButton[selected="true"] { background:#ffd22b; color:#171c1f; border-color:#eaba11; font-weight:bold; }
QPushButton#emergency { background:#612e34; border-color:#ab555f; color:#fff; }
QProgressBar { background:#26333c; border:1px solid #42535b; border-radius:2px; min-height:14px; text-align:center; color:#dce5e9; }
QProgressBar::chunk { background:#ffd22b; }
QTabWidget::pane { border:1px solid #394a54; background:#10181d; }
QTabBar::tab { background:#27353e; color:#e0e8ec; padding:7px 16px; border:1px solid #394a54; }
QTabBar::tab:selected { background:#ffd22b; color:#181e22; }
QPlainTextEdit, QDoubleSpinBox, QSpinBox, QComboBox { background:#10191f; border:1px solid #41525b; border-radius:3px; padding:5px; color:#edf3f6; }
QScrollArea { border:0; }
"""


class MainWindow(QMainWindow):
    def __init__(self, job: JobService, store: SettingsStore, events: EventLog, example: Path):
        super().__init__()
        self.job = job
        self.events = events
        self.setWindowTitle("靶宇机械 · 数控穿孔机 · 仿真")
        self.resize(1280, 800)
        self.setStyleSheet(STYLE)

        shell = QWidget()
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(7, 6, 7, 6)
        shell_layout.setSpacing(5)
        header = QHBoxLayout()
        brand = QLabel("◉  靶宇机械 · 数控穿孔机")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch()
        self.header_status = QLabel("自动  |  待机  |  G54  |  模拟模式")
        self.header_status.setObjectName("headerStatus")
        header.addWidget(self.header_status)
        self.emergency_button = QPushButton("仿真急停")
        self.emergency_button.setObjectName("emergency")
        self.emergency_button.clicked.connect(lambda: self.run_action(self.job.emergency_stop))
        header.addWidget(self.emergency_button)
        shell_layout.addLayout(header)

        self.pages = QStackedWidget()
        self.manual_service = ManualService(job)
        self.alignment_service = AlignmentService(job)
        self.overview = OverviewPage(job)
        self.manual = ManualPage(self.manual_service, self.run_action)
        self.alignment = AlignmentPage(self.alignment_service, self.run_action)
        self.program = ProgramPage(job, self.run_action, example)
        self.diagnostics = DiagnosticsPage(job, store, events, self.run_action)
        for page in (self.overview, self.manual, self.alignment, self.program, self.diagnostics):
            self.pages.addWidget(page)
        shell_layout.addWidget(self.pages, 1)

        controls = QHBoxLayout()
        self.start_button = QPushButton("循环启动 / 继续")
        self.pause_button = QPushButton("暂停")
        self.stop_button = QPushButton("停止作业")
        self.single_button = QPushButton("单段：关")
        self.single_button.setCheckable(True)
        self.connection_label = QLabel("仅模拟 · 未连接下位机")
        self.connection_label.setObjectName("subtle")
        for button in (self.start_button, self.pause_button, self.stop_button, self.single_button):
            controls.addWidget(button, 1)
        controls.addWidget(self.connection_label)
        shell_layout.addLayout(controls)

        navigation = QHBoxLayout()
        self.nav_buttons: list[QPushButton] = []
        for index, title in enumerate(("加工总览", "机床手动", "找中 / 补偿", "程序库", "工艺 / 诊断")):
            button = QPushButton(title)
            button.setObjectName("navButton")
            button.clicked.connect(lambda _, page_index=index: self.show_page(page_index))
            navigation.addWidget(button, 1)
            self.nav_buttons.append(button)
        shell_layout.addLayout(navigation)
        self.setCentralWidget(shell)
        self.show_page(0)

        self.start_button.clicked.connect(lambda: self.run_action(self._start_or_resume))
        self.pause_button.clicked.connect(lambda: self.run_action(self.job.request_pause))
        self.stop_button.clicked.connect(lambda: self.run_action(self.job.stop))
        self.single_button.toggled.connect(self._toggle_single_block)
        self.program.validate()
        self._last_tick = time.monotonic()
        self._last_runtime_error: str | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for button_index, button in enumerate(self.nav_buttons):
            button.setProperty("selected", button_index == index)
            button.style().unpolish(button)
            button.style().polish(button)

    def _start_or_resume(self) -> None:
        if self.job.paused:
            self.program.resume()
        else:
            if self.program.is_modified:
                raise RuntimeError("程序已修改，请到程序库重新校验")
            self.job.start()

    def _toggle_single_block(self, checked: bool) -> None:
        self.job.single_block = checked
        self.single_button.setText("单段：开" if checked else "单段：关")
        self.events.add("单段模式已开启" if checked else "单段模式已关闭")

    def run_action(self, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            self.events.add(f"操作失败：{exc}")
            QMessageBox.warning(self, "操作失败", str(exc))
        self.refresh()

    def refresh(self) -> None:
        now = time.monotonic()
        elapsed = min(now - self._last_tick, 0.2)
        self._last_tick = now
        try:
            self.job.tick(elapsed)
        except Exception as exc:
            if str(exc) != self._last_runtime_error:
                self.events.add(f"程序执行失败：{exc}")
                self._last_runtime_error = str(exc)
                QMessageBox.critical(self, "程序执行失败", str(exc))
        status = self.job.last_status
        if status.mode != MachineMode.FAULT:
            self._last_runtime_error = None
        self.overview.refresh(status, program_modified=self.program.is_modified)
        job_active = self.manual_service.job_active
        self.manual.refresh(status, job_active=job_active)
        self.alignment.refresh(status, job_active=job_active)
        self.program.refresh()
        self.diagnostics.refresh()
        self.start_button.setEnabled(
            not self.program.is_modified and (
                self.job.paused or (
                    not self.job.running and not self.job.waiting_xy and not self.job.waiting_hole
                    and status.mode == MachineMode.MANUAL_Z and self.job.program is not None
                )
            )
        )
        self.pause_button.setEnabled(self.job.running and not self.job.pause_requested)
        self.stop_button.setEnabled(self.job.running or self.job.waiting_xy or self.job.waiting_hole or self.job.paused)
        operation = "手动" if self.pages.currentWidget() in (self.manual, self.alignment) and not job_active else "自动"
        self.header_status.setText(
            f"{operation}  |  {status.mode.value.upper()}  |  {self.job.program.hole_count if self.job.program else 0}孔"
            f"  |  G54  |  模拟模式  |  {datetime.now():%m-%d %H:%M:%S}"
        )
