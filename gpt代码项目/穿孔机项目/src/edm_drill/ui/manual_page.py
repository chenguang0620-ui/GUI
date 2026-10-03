"""机床手动页：集中操作各轴和辅助输出；找中与补偿使用独立页面。"""

from __future__ import annotations

from collections.abc import Callable
import math
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..domain import MachineMode, MachineStatus

if TYPE_CHECKING:
    from ..manual_service import ManualService


def _millimetres(value: float) -> str:
    """通信故障时不把未知坐标显示为有效数值。"""
    return f"{value:+.3f} mm" if math.isfinite(value) else "—"


def _position_box() -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(3)
    box.setRange(-10000.0, 10000.0)
    box.setSingleStep(1.0)
    box.setSuffix(" mm")
    return box


class ManualPage(QWidget):
    """只收集手动指令；运动和联锁校验由 ManualService 决定。"""

    def __init__(self, manual: ManualService, action: Callable[[Callable[[], None]], None]):
        super().__init__()
        self.manual = manual
        self.action = action
        self._last_status: MachineStatus | None = None
        self._xy_target_initialized = False
        self._z_target_initialized = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("机床手动控制")
        title.setObjectName("panelTitle")
        self.stop_manual_button = QPushButton("停止手动运动 / 输出")
        self.stop_manual_button.setStyleSheet(
            "QPushButton { background:#59402b; border:1px solid #c18943; color:#ffe3bb; }"
            "QPushButton:hover { background:#705032; }"
            "QPushButton:disabled { background:#202b31; border-color:#42545e; color:#75848d; }"
        )
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.stop_manual_button)
        layout.addLayout(title_row)
        self.stop_manual_button.clicked.connect(lambda: self.action(self.manual.stop_motion))
        self.guidance = QLabel(
            "请先回零；接触工件边缘时仅用小步距点动并现场监护。XY 目标快移前请抬起 Z，核对坐标和现场安全高度。"
        )
        self.guidance.setWordWrap(True)
        layout.addWidget(self.guidance)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(8)
        right = QVBoxLayout()
        right.setSpacing(8)
        columns.addLayout(left, 3)
        columns.addLayout(right, 2)
        layout.addLayout(columns, 1)

        left.addWidget(self._make_xy_panel())
        left.addWidget(self._make_z_panel())
        left.addStretch()
        right.addWidget(self._make_status_panel())
        right.addWidget(self._make_outputs_panel())
        right.addStretch()

    def _make_xy_panel(self) -> QGroupBox:
        group = QGroupBox("X / Y 轴")
        layout = QVBoxLayout(group)
        header = QHBoxLayout()
        self.xy_position = QLabel("X —    Y —")
        self.xy_position.setObjectName("panelTitle")
        self.xy_homing = QLabel("XY 待回零")
        self.home_xy_button = QPushButton("XY 回零")
        header.addWidget(self.xy_position, 1)
        header.addWidget(self.xy_homing)
        header.addWidget(self.home_xy_button)
        layout.addLayout(header)

        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("点动步距"))
        self.xy_step = QDoubleSpinBox()
        self.xy_step.setDecimals(3)
        self.xy_step.setRange(0.001, 10.0)
        self.xy_step.setSingleStep(0.05)
        self.xy_step.setValue(0.05)
        self.xy_step.setSuffix(" mm")
        step_row.addWidget(self.xy_step)
        step_row.addStretch()
        layout.addLayout(step_row)

        jog = QGridLayout()
        self.y_plus_button = QPushButton("Y +")
        self.y_minus_button = QPushButton("Y −")
        self.x_plus_button = QPushButton("X +")
        self.x_minus_button = QPushButton("X −")
        centre = QLabel("定长点动")
        centre.setAlignment(Qt.AlignmentFlag.AlignCenter)
        jog.addWidget(self.y_plus_button, 0, 1)
        jog.addWidget(self.x_minus_button, 1, 0)
        jog.addWidget(centre, 1, 1)
        jog.addWidget(self.x_plus_button, 1, 2)
        jog.addWidget(self.y_minus_button, 2, 1)
        for column in range(3):
            jog.setColumnStretch(column, 1)
        layout.addLayout(jog)

        target_row = QHBoxLayout()
        self.x_target = _position_box()
        self.y_target = _position_box()
        self.xy_current_button = QPushButton("取当前位置")
        self.xy_move_button = QPushButton("XY 快移到目标")
        target_row.addWidget(QLabel("目标 X"))
        target_row.addWidget(self.x_target, 1)
        target_row.addWidget(QLabel("Y"))
        target_row.addWidget(self.y_target, 1)
        target_row.addWidget(self.xy_current_button)
        target_row.addWidget(self.xy_move_button)
        layout.addLayout(target_row)

        self.home_xy_button.clicked.connect(lambda: self.action(self.manual.home_xy))
        self.x_plus_button.clicked.connect(lambda: self._jog_xy(1, 0))
        self.x_minus_button.clicked.connect(lambda: self._jog_xy(-1, 0))
        self.y_plus_button.clicked.connect(lambda: self._jog_xy(0, 1))
        self.y_minus_button.clicked.connect(lambda: self._jog_xy(0, -1))
        self.xy_current_button.clicked.connect(self._sync_xy_target)
        self.xy_move_button.clicked.connect(
            lambda: self.action(lambda: self.manual.move_xy(self.x_target.value(), self.y_target.value()))
        )
        return group

    def _make_z_panel(self) -> QGroupBox:
        group = QGroupBox("Z 轴")
        layout = QVBoxLayout(group)
        header = QHBoxLayout()
        self.z_position = QLabel("Z —")
        self.z_position.setObjectName("panelTitle")
        self.z_homing = QLabel("Z 待回零")
        self.home_z_button = QPushButton("Z 回零")
        header.addWidget(self.z_position, 1)
        header.addWidget(self.z_homing)
        header.addWidget(self.home_z_button)
        layout.addLayout(header)

        jog = QHBoxLayout()
        self.z_minus_button = QPushButton("Z − 点动")
        self.z_plus_button = QPushButton("Z + 点动")
        jog.addWidget(QLabel("点动步距与 XY 相同"))
        jog.addStretch()
        jog.addWidget(self.z_minus_button)
        jog.addWidget(self.z_plus_button)
        layout.addLayout(jog)

        target = QHBoxLayout()
        self.z_target = _position_box()
        self.z_current_button = QPushButton("取当前位置")
        self.z_move_button = QPushButton("Z 快移到目标")
        target.addWidget(QLabel("目标 Z"))
        target.addWidget(self.z_target, 1)
        target.addWidget(self.z_current_button)
        target.addWidget(self.z_move_button)
        layout.addLayout(target)

        surface = QHBoxLayout()
        self.surface_status = QLabel("工件表面 Z0：未确认")
        self.surface_zero_button = QPushButton("确认当前位置为工件表面 Z0")
        surface.addWidget(self.surface_status, 1)
        surface.addWidget(self.surface_zero_button)
        layout.addLayout(surface)

        self.home_z_button.clicked.connect(lambda: self.action(self.manual.home_z))
        self.z_minus_button.clicked.connect(lambda: self._jog_z(-1))
        self.z_plus_button.clicked.connect(lambda: self._jog_z(1))
        self.z_current_button.clicked.connect(self._sync_z_target)
        self.z_move_button.clicked.connect(
            lambda: self.action(lambda: self.manual.move_z(self.z_target.value()))
        )
        self.surface_zero_button.clicked.connect(lambda: self.action(self.manual.set_surface_zero))
        return group

    def _make_status_panel(self) -> QGroupBox:
        group = QGroupBox("手动状态")
        layout = QVBoxLayout(group)
        self.mode_status = QLabel("控制器状态：待机")
        self.operation_status = QLabel("等待状态更新")
        self.operation_status.setWordWrap(True)
        self.fault_status = QLabel("")
        self.fault_status.setWordWrap(True)
        self.reset_button = QPushButton("复位故障")
        layout.addWidget(self.mode_status)
        layout.addWidget(self.operation_status)
        layout.addWidget(self.fault_status)
        layout.addWidget(self.reset_button)
        self.reset_button.clicked.connect(lambda: self.action(self.manual.reset_fault))
        return group

    def _make_outputs_panel(self) -> QGroupBox:
        group = QGroupBox("辅助设备手动开关")
        layout = QVBoxLayout(group)
        self.output_controls: dict[str, tuple[QLabel, QPushButton, QPushButton]] = {}
        for name, label in (
            ("flush", "冲液 / 水泵"),
            ("rotation", "电极旋转"),
            ("pulse", "放电脉冲"),
        ):
            row = QHBoxLayout()
            title = QLabel(label)
            state = QLabel("未接入")
            on = QPushButton("开")
            off = QPushButton("关")
            row.addWidget(title, 1)
            row.addWidget(state)
            row.addWidget(on)
            row.addWidget(off)
            layout.addLayout(row)
            self.output_controls[name] = (state, on, off)
            operation = getattr(self.manual, f"set_{name}")
            on.clicked.connect(lambda _=False, command=operation: self.action(lambda: command(True)))
            off.clicked.connect(lambda _=False, command=operation: self.action(lambda: command(False)))
        note = QLabel("加工中手动开关锁定；状态以控制器回传为准。")
        note.setObjectName("subtle")
        note.setWordWrap(True)
        layout.addWidget(note)
        return group

    def _jog_xy(self, x_sign: int, y_sign: int) -> None:
        step = self.xy_step.value()
        self.action(lambda: self.manual.jog_xy(x_sign * step, y_sign * step))

    def _jog_z(self, sign: int) -> None:
        self.action(lambda: self.manual.jog_z(sign * self.xy_step.value()))

    def _sync_xy_target(self) -> None:
        status = self._last_status
        if status is not None and math.isfinite(status.x_mm) and math.isfinite(status.y_mm):
            self.x_target.setValue(status.x_mm)
            self.y_target.setValue(status.y_mm)
            self._xy_target_initialized = True

    def _sync_z_target(self) -> None:
        status = self._last_status
        if status is not None and math.isfinite(status.z_mm):
            self.z_target.setValue(status.z_mm)
            self._z_target_initialized = True

    def refresh(self, status: MachineStatus, *, job_active: bool) -> None:
        """界面门控便于操作；ManualService 仍负责最终安全校验。"""
        self._last_status = status
        manual_mode = status.mode == MachineMode.MANUAL_Z and not job_active
        xy_homed = bool(getattr(status, "xy_homed", False))
        z_ready = manual_mode and status.homed and status.xy_stationary
        xy_ready = z_ready and xy_homed
        if xy_ready and not self._xy_target_initialized:
            self._sync_xy_target()
        if z_ready and not self._z_target_initialized:
            self._sync_z_target()

        self.xy_position.setText(f"X {_millimetres(status.x_mm)}    Y {_millimetres(status.y_mm)}")
        self.z_position.setText(f"Z {_millimetres(status.z_mm)}")
        self.xy_homing.setText("XY 已回零" if xy_homed else "XY 待回零")
        self.z_homing.setText("Z 已回零" if status.homed else "Z 待回零")
        self.surface_status.setText("工件表面 Z0：已确认" if status.surface_set else "工件表面 Z0：未确认")

        self.home_z_button.setEnabled(manual_mode and status.xy_stationary)
        self.stop_manual_button.setEnabled(not job_active and status.mode != MachineMode.FAULT)
        self.home_xy_button.setEnabled(z_ready)
        self.surface_zero_button.setEnabled(z_ready)
        for button in (
            self.x_plus_button, self.x_minus_button, self.y_plus_button,
            self.y_minus_button, self.xy_current_button, self.xy_move_button,
        ):
            button.setEnabled(xy_ready)
        for button in (
            self.z_plus_button, self.z_minus_button, self.z_current_button, self.z_move_button,
        ):
            button.setEnabled(z_ready)
        self.reset_button.setEnabled(status.mode == MachineMode.FAULT and not job_active)

        if status.mode == MachineMode.FAULT:
            self.mode_status.setText("控制器状态：故障")
            self.operation_status.setText("手动操作已锁定，请排查故障并复位。")
            self.fault_status.setText(status.fault)
        elif job_active:
            self.mode_status.setText("控制器状态：作业中 / 已暂停")
            self.operation_status.setText("作业结束或停止后可进行手动操作。")
            self.fault_status.clear()
        elif status.mode != MachineMode.MANUAL_Z:
            self.mode_status.setText(f"控制器状态：{status.mode.value}")
            self.operation_status.setText("控制器尚未返回手动模式，请等待当前动作结束。")
            self.fault_status.clear()
        else:
            self.mode_status.setText("控制器状态：手动")
            if not status.xy_stationary:
                self.operation_status.setText("XY 正在运动；可按“停止手动运动 / 输出”中止。")
            elif not status.homed:
                self.operation_status.setText("请先执行 Z 回零。")
            elif not xy_homed:
                self.operation_status.setText("Z 已回零；请执行 XY 回零。")
            else:
                self.operation_status.setText("各轴已回零，可点动或输入目标坐标快移。")
            self.fault_status.clear()

        output_states = {
            "flush": bool(getattr(status, "flush_enabled", False)),
            "rotation": bool(getattr(status, "rotation_enabled", False)),
            "pulse": status.pulse_enabled,
        }
        for name, enabled in output_states.items():
            state, on, off = self.output_controls[name]
            supported = bool(self.manual.supports_manual_output(name))
            state.setText(("开启" if enabled else "关闭") if supported else "未接入")
            on.setEnabled(
                manual_mode and status.xy_stationary and supported and not enabled
                and (name != "pulse" or (status.surface_set and status.flush_enabled))
            )
            # 故障时仍允许把已开启的输出请求关闭。
            off.setEnabled(
                not job_active and supported and enabled
                and status.mode in (MachineMode.MANUAL_Z, MachineMode.FAULT)
            )
