"""加工总览：三栏机床面板、孔位路径、进度和设备状态。"""

from __future__ import annotations

import math

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout, QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from ..domain import MachineMode, MachineStatus
from ..job_service import JobService
from .hole_map import HoleMap


def _panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(10, 9, 10, 9)
    layout.setSpacing(6)
    label = QLabel(title)
    label.setObjectName("panelTitle")
    layout.addWidget(label)
    return frame, layout


class OverviewPage(QWidget):
    def __init__(self, job: JobService):
        super().__init__()
        self.job = job
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 5, 6, 5)
        root.setSpacing(5)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        coords, box = _panel("坐标 / mm")
        self.coords = QLabel("X +0.000\nY +0.000\nZ +0.000")
        self.coords.setObjectName("coordinateReadout")
        box.addWidget(self.coords)
        self.coordinate_hint = QLabel("当前工作坐标 · G54")
        self.coordinate_hint.setObjectName("subtle")
        box.addWidget(self.coordinate_hint)
        left_layout.addWidget(coords)

        speed, box = _panel("速度与功率 · 模拟")
        self.speed_bars = []
        for axis in "XYZ":
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{axis} 轴速度"))
            value = QLabel("0%")
            row.addStretch()
            row.addWidget(value)
            box.addLayout(row)
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setRange(0, 100)
            box.addWidget(bar)
            self.speed_bars.append((bar, value))
        box.addWidget(QLabel("放电设定功率 · 待接入配方"))
        self.power_bar = QProgressBar()
        self.power_bar.setRange(0, 100)
        self.power_bar.setValue(0)
        box.addWidget(self.power_bar)
        left_layout.addWidget(speed)

        equipment, box = _panel("设备状态")
        self.equipment = QFormLayout()
        self.xy_state = QLabel("模拟待机")
        self.pulse_state = QLabel("关闭")
        self.flush_state = QLabel("未接入")
        self.rotate_state = QLabel("未接入")
        for name, value in (
            ("XY", self.xy_state), ("放电", self.pulse_state),
            ("冲液", self.flush_state), ("电极旋转", self.rotate_state),
        ):
            self.equipment.addRow(name, value)
        box.addLayout(self.equipment)
        left_layout.addWidget(equipment)
        left_layout.addStretch()
        left_scroll.setWidget(left)
        root.addWidget(left_scroll, 24)

        center, box = _panel("孔位与加工路径")
        self.map_summary = QLabel("孔位：等待加载程序")
        self.map_summary.setObjectName("subtle")
        box.addWidget(self.map_summary)
        self.map_tabs = QTabWidget()
        self.hole_map = HoleMap()
        self.program_text = QPlainTextEdit()
        self.program_text.setReadOnly(True)
        self.map_tabs.addTab(self.hole_map, "孔位图")
        self.map_tabs.addTab(self.program_text, "程序文本")
        box.addWidget(self.map_tabs, 1)
        self.current_hole_label = QLabel("当前孔：—")
        box.addWidget(self.current_hole_label)
        self.selected_label = QLabel("点击孔查看坐标；滚轮缩放，拖动平移")
        self.selected_label.setObjectName("subtle")
        box.addWidget(self.selected_label)
        reset_button = QPushButton("复位视图")
        reset_button.clicked.connect(self.hole_map.reset_view)
        box.addWidget(reset_button)
        self.recipe_label = QLabel("工艺：演示配方 · 实际脉冲参数未接入")
        self.recipe_label.setObjectName("subtle")
        box.addWidget(self.recipe_label)
        self.program_label = QLabel("当前模拟作业  |  未加载")
        self.program_label.setObjectName("subtle")
        box.addWidget(self.program_label)
        self.total_progress = QProgressBar()
        box.addWidget(self.total_progress)
        root.addWidget(center, 50)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        depth, box = _panel("当前孔加工深度")
        self.depth_value = QLabel("0.000 mm")
        self.depth_value.setObjectName("depthReadout")
        box.addWidget(self.depth_value)
        self.depth_target = QLabel("目标：—")
        self.depth_target.setObjectName("subtle")
        box.addWidget(self.depth_target)
        self.depth_progress = QProgressBar()
        box.addWidget(self.depth_progress)
        right_layout.addWidget(depth)

        machining, box = _panel("加工状态")
        self.mode_label = QLabel("待机 · 模拟")
        self.mode_label.setObjectName("goodStatus")
        box.addWidget(self.mode_label)
        detail = QFormLayout()
        self.gap_voltage = QLabel("—")
        self.current = QLabel("—")
        self.recipe = QLabel("—")
        for name, value in (("间隙电压", self.gap_voltage), ("加工电流", self.current), ("作业配方", self.recipe)):
            detail.addRow(name, value)
        box.addLayout(detail)
        right_layout.addWidget(machining)

        timing, box = _panel("加工时间")
        self.elapsed = QLabel("已加工：00:00")
        box.addWidget(self.elapsed)
        box.addWidget(QLabel("预计剩余：—（未标定）"))
        note = QLabel("仅模拟时间，不能用于生产估算")
        note.setObjectName("subtle")
        box.addWidget(note)
        right_layout.addWidget(timing)

        alarms, box = _panel("状态 / 报警消息")
        self.message = QLabel("模拟模式 · 未连接硬件")
        self.message.setWordWrap(True)
        box.addWidget(self.message)
        right_layout.addWidget(alarms)
        right_layout.addStretch()
        right_scroll.setWidget(right)
        root.addWidget(right_scroll, 26)

        self.hole_map.selected.connect(self._select_hole)

    def _select_hole(self, number: int) -> None:
        hole = self.hole_map.holes[number - 1]
        self.selected_label.setText(
            f"H{number:03d}  |  X {hole.x_mm:+.3f}  Y {hole.y_mm:+.3f}  |  P{hole.recipe_id} D{hole.depth_mm:.3f}"
        )

    def refresh(self, status: MachineStatus, *, program_modified: bool = False) -> None:
        program = self.job.program
        selected_before = self.hole_map.selected_number
        self.hole_map.set_program(program)
        if selected_before is not None and self.hole_map.selected_number is None:
            self.selected_label.setText("点击孔查看坐标；滚轮缩放，拖动平移")
        self.hole_map.set_progress(self.job.holes_completed_in_job, self.job.current_hole_number)
        source = program.source if program else "未加载程序"
        if self.program_text.toPlainText() != source:
            self.program_text.setPlainText(source)
        # 失联后坐标未知，不把无效值显示成误导性的 0.000。
        def coordinate(value: float) -> str:
            return f"{value:+.3f}" if math.isfinite(value) else "—"

        self.coords.setText(
            f"X {coordinate(status.x_mm)}\nY {coordinate(status.y_mm)}\nZ {coordinate(status.z_mm)}"
        )
        self.xy_state.setText(
            "XY 定位中" if not status.xy_stationary else
            "未回零" if not status.xy_homed else "模拟待机"
        )
        self.pulse_state.setText("开启 · 仿真" if status.pulse_enabled else "关闭")
        capability = getattr(self.job.controller, "supports_manual_output", None)
        self.flush_state.setText(
            ("开启" if status.flush_enabled else "关闭")
            if callable(capability) and capability("flush") else "未接入"
        )
        self.rotate_state.setText(
            ("开启" if status.rotation_enabled else "关闭")
            if callable(capability) and capability("rotation") else "未接入"
        )
        self.mode_label.setText(
            "故障 · 模拟" if status.mode == MachineMode.FAULT else
            "穿孔中 · 模拟" if status.mode == MachineMode.EDM_Z else
            "退刀中 · 模拟" if status.mode == MachineMode.RETRACT else
            "XY 定位中 · 模拟" if self.job.waiting_xy else
            "暂停 · 模拟" if self.job.paused else "待机 · 模拟"
        )
        if program:
            self.map_summary.setText(f"孔位：{program.hole_count} 个  |  已完成：{self.job.holes_completed_in_job} 个")
            current = self.job.current_hole_number
            if current is not None:
                self.current_hole_label.setText(f"当前孔：H{current:03d} · 加工中")
            elif self.job.waiting_xy:
                self.current_hole_label.setText(f"当前孔：定位至 H{self.job.holes_completed_in_job + 1:03d}")
            elif self.job.holes_completed_in_job == program.hole_count:
                self.current_hole_label.setText("当前孔：全部完成")
            else:
                self.current_hole_label.setText(f"下一孔：H{self.job.holes_completed_in_job + 1:03d}")
        else:
            self.map_summary.setText("孔位：等待加载程序")
            self.current_hole_label.setText("当前孔：—")
        self.recipe.setText(f"P{status.active_recipe}" if status.active_recipe else "—")
        target = self.job.current_hole_target_mm
        depth = max(0.0, -status.z_mm) if target else 0.0
        self.depth_value.setText(f"{depth:.3f} mm")
        self.depth_target.setText(f"目标：{target:.3f} mm" if target else "目标：—")
        self.depth_progress.setValue(round(depth / target * 100) if target else 0)
        self.total_progress.setValue(round(self.job.holes_completed_in_job / program.hole_count * 100) if program else 0)
        if program_modified:
            self.program_label.setText("程序已修改 · 孔位图显示上次校验版本，请重新校验")
        else:
            self.program_label.setText(
                f"当前模拟作业  |  完成 {self.job.holes_completed_in_job}/{program.hole_count} 孔"
                if program else "当前模拟作业  |  未加载"
            )
        minutes, seconds = divmod(int(self.job.elapsed_s), 60)
        self.elapsed.setText(f"已加工：{minutes:02d}:{seconds:02d}")
        self.message.setText(status.fault or "模拟模式 · 未连接硬件")
        self.speed_bars[2][0].setValue(30 if status.mode == MachineMode.EDM_Z else 0)
        self.speed_bars[2][1].setText("30%" if status.mode == MachineMode.EDM_Z else "0%")
