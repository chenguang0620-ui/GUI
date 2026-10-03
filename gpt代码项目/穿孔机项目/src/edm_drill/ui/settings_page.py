"""设备设置页：每个参数明确单位，保存前由领域模型校验。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..domain import FeedbackConfig, FeedbackMode, MachineConfig, MachineMode
from ..job_service import JobService
from ..settings_store import SettingsStore


def _float_box(value: float, low: float, high: float, decimals: int = 3) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(low, high)
    box.setValue(value)
    return box


class SettingsPage(QWidget):
    def __init__(
        self,
        job: JobService,
        store: SettingsStore,
        action: Callable[[Callable[[], None]], None],
    ):
        super().__init__()
        self.job = job
        self.store = store
        self.action = action
        config = job.config
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Z 轴反馈由 STM32F407 执行。以下参数保存后须重新确认工件表面 Z0。"))

        feedback_group = QGroupBox("Z 轴位置反馈")
        feedback_form = QFormLayout(feedback_group)
        self.mode = QComboBox()
        for title, mode in (
            ("光栅尺", FeedbackMode.SCALE),
            ("编码器", FeedbackMode.ENCODER),
            ("光栅尺 + 编码器双闭环", FeedbackMode.DUAL),
        ):
            self.mode.addItem(title, mode)
        self.mode.setCurrentIndex(self.mode.findData(config.feedback.mode))
        self.scale_resolution_um = _float_box(config.feedback.scale_mm_per_count * 1000, 0.001, 1000, 3)
        self.scale_resolution_um.setSuffix(" µm/计数")
        self.encoder_counts = QSpinBox()
        self.encoder_counts.setRange(0, 10_000_000)
        self.encoder_counts.setSpecialValueText("未配置")
        self.encoder_counts.setValue(config.feedback.encoder_counts_per_rev or 0)
        self.screw_pitch = _float_box(config.feedback.screw_pitch_mm or 0, 0, 1000)
        self.screw_pitch.setSpecialValueText("未配置")
        self.screw_pitch.setSuffix(" mm/转")
        self.disagreement = _float_box(config.feedback.max_disagreement_mm, 0.001, 10)
        self.disagreement.setSuffix(" mm")
        self.encoder_direction = QComboBox()
        self.scale_direction = QComboBox()
        for combo, value in ((self.encoder_direction, config.feedback.encoder_direction),
                             (self.scale_direction, config.feedback.scale_direction)):
            combo.addItem("正向", 1)
            combo.addItem("反向", -1)
            combo.setCurrentIndex(combo.findData(value))
        for title, field in (
            ("反馈模式", self.mode), ("光栅尺分辨率", self.scale_resolution_um),
            ("编码器每转有效计数", self.encoder_counts), ("丝杠导程", self.screw_pitch),
            ("编码器方向", self.encoder_direction), ("光栅尺方向", self.scale_direction),
            ("双反馈允许偏差", self.disagreement),
        ):
            feedback_form.addRow(title, field)
        layout.addWidget(feedback_group)

        limits_group = QGroupBox("行程与速度")
        limits_form = QFormLayout(limits_group)
        self.x_max = _float_box(config.x_max_mm, 1, 10000)
        self.y_max = _float_box(config.y_max_mm, 1, 10000)
        self.z_min = _float_box(config.z_min_mm, -10000, -0.001)
        self.z_max = _float_box(config.z_max_mm, 0.001, 10000)
        self.max_depth = _float_box(config.max_hole_depth_mm, 0.001, 10000)
        self.manual_speed = _float_box(config.manual_speed_mm_s, 0.001, 1000)
        self.sim_feed = _float_box(config.edm_feed_mm_s, 0.001, 1000)
        for title, field in (
            ("X 最大值 (mm)", self.x_max), ("Y 最大值 (mm)", self.y_max),
            ("Z 最小值 (mm)", self.z_min), ("Z 最大值 (mm)", self.z_max),
            ("单孔最大深度 (mm)", self.max_depth),
            ("手动速度 (mm/s)", self.manual_speed),
            ("仿真进给速度 (mm/s)", self.sim_feed),
        ):
            limits_form.addRow(title, field)
        layout.addWidget(limits_group)

        row = QHBoxLayout()
        self.apply_button = QPushButton("应用并保存")
        row.addWidget(self.apply_button)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        self.apply_button.clicked.connect(lambda: self.action(self.apply))

    def apply(self) -> None:
        current = self.job.config
        feedback = FeedbackConfig(
            mode=self.mode.currentData(),
            scale_mm_per_count=self.scale_resolution_um.value() / 1000,
            encoder_counts_per_rev=self.encoder_counts.value() or None,
            screw_pitch_mm=self.screw_pitch.value() or None,
            encoder_direction=self.encoder_direction.currentData(),
            scale_direction=self.scale_direction.currentData(),
            max_disagreement_mm=self.disagreement.value(),
        )
        new_config = replace(
            current, feedback=feedback, x_max_mm=self.x_max.value(),
            y_max_mm=self.y_max.value(), z_min_mm=self.z_min.value(),
            z_max_mm=self.z_max.value(), max_hole_depth_mm=self.max_depth.value(),
            manual_speed_mm_s=self.manual_speed.value(), edm_feed_mm_s=self.sim_feed.value(),
        )
        new_config.validate()
        self.job.update_config(new_config)
        self.store.save(new_config)

    def refresh(self) -> None:
        status = self.job.last_status
        self.apply_button.setEnabled(
            status.mode == MachineMode.MANUAL_Z and status.xy_stationary
            and not status.pulse_enabled and not status.flush_enabled and not status.rotation_enabled
            and not self.job.running and not self.job.waiting_xy and not self.job.waiting_hole and not self.job.paused
        )
