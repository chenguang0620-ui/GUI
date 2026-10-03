"""程序页：打开、编辑、校验、预览和调度单孔作业。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QSplitter, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from ..job_service import JobService


class ProgramPage(QWidget):
    def __init__(self, job: JobService, action: Callable[[Callable[[], None]], None], example: Path):
        super().__init__()
        self.job = job
        self.action = action
        self.loaded_source: str | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("程序使用 G21 / G90 / G54、G0 XY 和 M200 P… D…；M200 由上位机解释。"))
        buttons = QHBoxLayout()
        self.open_button = QPushButton("打开 .ngc")
        self.validate_button = QPushButton("校验并加载")
        self.start_button = QPushButton("开始")
        self.resume_button = QPushButton("继续")
        self.stop_button = QPushButton("停止")
        for button in (
            self.open_button, self.validate_button, self.start_button,
            self.resume_button, self.stop_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("在这里输入或打开 G 代码")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.preview)
        layout.addWidget(splitter)
        self.editor.setPlainText(example.read_text(encoding="utf-8"))
        self.open_button.clicked.connect(self.open_file)
        self.validate_button.clicked.connect(lambda: self.action(self.validate))
        self.start_button.clicked.connect(lambda: self.action(self.start))
        self.resume_button.clicked.connect(lambda: self.action(self.resume))
        self.stop_button.clicked.connect(lambda: self.action(self.job.stop))
        self.editor.textChanged.connect(self._mark_modified)

    def open_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "打开 G 代码", "", "G 代码 (*.ngc *.nc *.tap);;所有文件 (*)")
        if filename:
            self.action(lambda: self.editor.setPlainText(Path(filename).read_text(encoding="utf-8")))

    def validate(self) -> None:
        source = self.editor.toPlainText()
        program = self.job.load(source)
        self.loaded_source = source
        lines = [f"校验通过：{program.hole_count} 个孔，{len(program.steps)} 条执行指令", ""]
        x = y = 0.0
        for step in program.steps:
            if step.kind == "move_xy":
                x, y = step.x_mm or 0.0, step.y_mm or 0.0
            elif step.kind == "hole":
                lines.append(f"第 {step.line} 行 | X{x:.3f} Y{y:.3f} | P{step.recipe_id} D{step.depth_mm:.3f}")
        self.preview.setPlainText("\n".join(lines))

    def start(self) -> None:
        if self.loaded_source != self.editor.toPlainText():
            raise RuntimeError("程序已修改，请重新校验并加载")
        self.job.start()

    @property
    def is_modified(self) -> bool:
        """编辑器与已经校验的作业不一致时，需要重新校验。"""
        return self.loaded_source != self.editor.toPlainText()

    def resume(self) -> None:
        if self.is_modified:
            raise RuntimeError("程序已修改，请停止作业后重新校验")
        self.job.resume()

    def _mark_modified(self) -> None:
        if self.loaded_source is not None and self.loaded_source != self.editor.toPlainText():
            self.preview.setPlainText("程序已修改，请重新校验并加载。")

    def refresh(self) -> None:
        busy = self.job.running or self.job.waiting_hole or self.job.waiting_xy or self.job.paused
        self.editor.setReadOnly(busy)
        self.open_button.setEnabled(not busy)
        self.validate_button.setEnabled(not busy)
        self.start_button.setEnabled(not busy and not self.is_modified and self.job.program is not None)
        self.resume_button.setEnabled(self.job.paused and not self.is_modified)
        self.stop_button.setEnabled(busy or self.job.paused)
