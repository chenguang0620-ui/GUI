"""独立找中页：人工确认碰边、铜管半径换算及单轴 G54 原点设置。

此页只收集操作意图和显示预览；坐标计算、状态检查及 G54 写入
由 AlignmentService 执行。这里没有自动探针或 G41/G42 路径刀补。
"""

from __future__ import annotations

from collections.abc import Callable
import math
from typing import Protocol

from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..alignment import AlignmentSession, Axis, ReferenceMode, TouchEdge
from ..domain import MachineMode, MachineStatus


class _AlignmentService(Protocol):
    """页面所需的服务接口，避免在控件中实现机床控制逻辑。"""

    session: AlignmentSession
    controller: object
    job: object

    def set_tube_diameter(self, mm: float) -> None: ...

    def capture(self, edge: TouchEdge) -> object: ...

    def clear_touch(self, edge: TouchEdge) -> None: ...

    def clear_all(self) -> None: ...

    def preview_axis(
        self, axis: Axis, reference: ReferenceMode, compensation_mm: float
    ) -> float: ...

    def apply_axis(
        self, axis: Axis, reference: ReferenceMode, compensation_mm: float
    ) -> float: ...


def _measurement(value: float) -> str:
    """失联或无效坐标不应被显示成看似有效的零值。"""

    return f"{value:+.3f} mm" if math.isfinite(value) else "—"


class AlignmentPage(QWidget):
    """手动碰边找中；X、Y 可分别选负边、正边或双边中心。"""

    def __init__(
        self,
        service: _AlignmentService,
        action: Callable[[Callable[[], None]], None],
    ) -> None:
        super().__init__()
        self.service = service
        self.action = action
        self._last_status = MachineStatus()
        self._job_active = False
        self.capture_buttons: dict[TouchEdge, QPushButton] = {}
        self.clear_buttons: dict[TouchEdge, QPushButton] = {}
        self.touch_labels: dict[TouchEdge, QLabel] = {}
        self.references: dict[Axis, QComboBox] = {}
        self.compensations: dict[Axis, QDoubleSpinBox] = {}
        self.preview_labels: dict[Axis, QLabel] = {}
        self.apply_buttons: dict[Axis, QPushButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        heading = QLabel("找中与 G54 补偿")
        heading.setObjectName("panelTitle")
        layout.addWidget(heading)
        instruction = QLabel(
            "先在手动页移动铜管并轻触工件边缘，操作者确认触碰后再点“记录当前坐标”。"
            "本页没有自动探针或自动碰边检测。"
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        layout.addLayout(columns)
        measurement_column = QVBoxLayout()
        calculation_column = QVBoxLayout()
        columns.addLayout(measurement_column, 11)
        columns.addLayout(calculation_column, 9)

        tube_group = QGroupBox("铜管尺寸")
        tube_form = QFormLayout(tube_group)
        self.diameter = QDoubleSpinBox()
        self.diameter.setDecimals(4)
        self.diameter.setRange(0.001, 100.0)
        self.diameter.setSingleStep(0.05)
        self.diameter.setSuffix(" mm")
        self.diameter.setValue(service.session.tube_outer_diameter_mm)
        self.diameter_button = QPushButton("更新外径")
        diameter_row = QHBoxLayout()
        diameter_row.addWidget(self.diameter, 1)
        diameter_row.addWidget(self.diameter_button)
        tube_form.addRow("铜管外径", diameter_row)
        self.active_diameter = QLabel()
        self.active_diameter.setWordWrap(True)
        tube_form.addRow("当前换算", self.active_diameter)
        measurement_column.addWidget(tube_group)

        touch_group = QGroupBox("人工碰边记录 · 当前 G54 工作坐标")
        touch_layout = QVBoxLayout(touch_group)
        self.current_position = QLabel("当前：X —  Y —")
        touch_layout.addWidget(self.current_position)
        self.current_offset = QLabel("G54 偏置：X —  Y —")
        self.current_offset.setObjectName("subtle")
        touch_layout.addWidget(self.current_offset)
        for edge in TouchEdge:
            row = QHBoxLayout()
            name = QLabel(edge.value)
            name.setMinimumWidth(30)
            row.addWidget(name)
            measured = QLabel("尚未记录")
            measured.setWordWrap(True)
            row.addWidget(measured, 1)
            capture = QPushButton("记录当前坐标")
            clear = QPushButton("清除 / 重测")
            row.addWidget(capture)
            row.addWidget(clear)
            touch_layout.addLayout(row)
            self.touch_labels[edge] = measured
            self.capture_buttons[edge] = capture
            self.clear_buttons[edge] = clear
            capture.clicked.connect(lambda _, selected=edge: self._capture(selected))
            clear.clicked.connect(lambda _, selected=edge: self._clear_touch(selected))
        self.clear_all_button = QPushButton("清除全部触碰记录")
        touch_layout.addWidget(self.clear_all_button)
        measurement_column.addWidget(touch_group)

        geometry_note = QLabel(
            "实际工件边缘 = 触碰时铜管中心坐标 ± 铜管半径："
            "X−/Y− 加半径，X+/Y+ 减半径；双边中心取两个实际边缘的中点。"
        )
        geometry_note.setWordWrap(True)
        geometry_note.setObjectName("subtle")
        measurement_column.addWidget(geometry_note)
        measurement_column.addStretch()

        for axis in Axis:
            group = QGroupBox(f"{axis.value} 轴 G54 找中")
            group_layout = QVBoxLayout(group)
            form = QFormLayout()
            reference = QComboBox()
            for title, mode in (
                ("负边作为零点", ReferenceMode.MINUS),
                ("正边作为零点", ReferenceMode.PLUS),
                ("双边中心作为零点", ReferenceMode.CENTER),
            ):
                reference.addItem(title, mode)
            compensation = QDoubleSpinBox()
            compensation.setDecimals(3)
            compensation.setRange(-10000.0, 10000.0)
            compensation.setSingleStep(0.01)
            compensation.setSuffix(" mm")
            compensation.setToolTip("有符号的零点修正量，正值向该轴正方向移动零点")
            form.addRow("基准", reference)
            form.addRow("附加补偿", compensation)
            group_layout.addLayout(form)
            preview = QLabel("请先记录所选边缘")
            preview.setWordWrap(True)
            group_layout.addWidget(preview)
            apply_button = QPushButton(f"预览确认并应用 {axis.value} 轴 G54")
            group_layout.addWidget(apply_button)
            calculation_column.addWidget(group)
            self.references[axis] = reference
            self.compensations[axis] = compensation
            self.preview_labels[axis] = preview
            self.apply_buttons[axis] = apply_button
            reference.currentIndexChanged.connect(self._refresh_from_current_state)
            compensation.valueChanged.connect(self._refresh_from_current_state)
            apply_button.clicked.connect(
                lambda _, selected=axis: self.action(lambda: self._confirm_apply(selected))
            )
        calculation_column.addStretch()

        note = QLabel(
            "这里设置的是 G54 找正偏置，不是 G41/G42 加工路径刀补。"
            "应用单轴时不会移动机床，但会改变该轴工作坐标；"
            "LinuxCNC 会持续保存 G54。应用后全部触碰记录自动清空，须重新测量。"
        )
        note.setWordWrap(True)
        note.setObjectName("subtle")
        layout.addWidget(note)
        layout.addStretch()

        self.diameter_button.clicked.connect(self._set_diameter)
        self.diameter.valueChanged.connect(self._refresh_from_current_state)
        self.clear_all_button.clicked.connect(lambda: self.action(self.service.clear_all))
        self._refresh_from_current_state()

    def _set_diameter(self) -> None:
        self.action(lambda: self.service.set_tube_diameter(self.diameter.value()))

    def _capture(self, edge: TouchEdge) -> None:
        self.action(lambda: self.service.capture(edge))

    def _clear_touch(self, edge: TouchEdge) -> None:
        self.action(lambda: self.service.clear_touch(edge))

    def _refresh_from_current_state(self) -> None:
        self.refresh(self._last_status, job_active=self._job_active)

    def refresh(self, status: MachineStatus, *, job_active: bool) -> None:
        """显示实时坐标、碰边换算与单轴应用后的当前 G54 读数。"""

        self._last_status = status
        self._job_active = job_active
        session = self.service.session
        touches = session.touches
        diameter_dirty = abs(self.diameter.value() - session.tube_outer_diameter_mm) > 0.00005
        can_set = status.mode == MachineMode.MANUAL_Z and not job_active
        self.current_position.setText(
            f"当前：X {_measurement(status.x_mm)}  Y {_measurement(status.y_mm)}"
        )
        self.current_offset.setText(
            f"当前 G54 偏置：X {_measurement(status.g54_offset_x_mm)}"
            f"  Y {_measurement(status.g54_offset_y_mm)}"
        )
        self.active_diameter.setText(
            f"已使用外径 {session.tube_outer_diameter_mm:.4f} mm，"
            f"半径 {session.tube_outer_diameter_mm / 2:.4f} mm"
            + (" · 输入已修改，请先更新外径" if diameter_dirty else "")
        )
        self.diameter.setEnabled(can_set)
        self.diameter_button.setEnabled(can_set and diameter_dirty)

        for edge in TouchEdge:
            point = touches.get(edge)
            if point is None:
                self.touch_labels[edge].setText("尚未记录")
            else:
                location = session.edge_coordinate(edge)
                self.touch_labels[edge].setText(
                    f"触碰 X {_measurement(point.x_mm)}  Y {_measurement(point.y_mm)}"
                    f"\n实际 {edge.value} 边缘 {_measurement(location)}"
                )
            self.capture_buttons[edge].setEnabled(can_set and not diameter_dirty and point is None)
            self.clear_buttons[edge].setEnabled(point is not None)
        self.clear_all_button.setEnabled(bool(touches))

        for axis in Axis:
            reference = self.references[axis].currentData()
            compensation = self.compensations[axis].value()
            current = status.x_mm if axis is Axis.X else status.y_mm
            try:
                origin = self.service.preview_axis(axis, reference, compensation)
                if not math.isfinite(origin) or not math.isfinite(current - origin):
                    raise ValueError("坐标无效，请检查机床状态")
            except (ValueError, RuntimeError) as exc:
                self.preview_labels[axis].setText(f"预览：{exc}")
                ready = False
            else:
                self.preview_labels[axis].setText(
                    f"零点位置（旧 G54）：{_measurement(origin)}\n"
                    f"当前读数：{_measurement(current)}  →  应用后：{_measurement(current - origin)}"
                )
                ready = True
            self.apply_buttons[axis].setEnabled(can_set and not diameter_dirty and ready)

    def _confirm_apply(self, axis: Axis) -> None:
        """应用前再次显示实际读数变化；确认后的状态由服务再次检查。"""

        reference = self.references[axis].currentData()
        compensation = self.compensations[axis].value()
        old_status = self.service.controller.status()
        old_coordinate = old_status.x_mm if axis is Axis.X else old_status.y_mm
        origin = self.service.preview_axis(axis, reference, compensation)
        new_coordinate = old_coordinate - origin
        if not all(math.isfinite(value) for value in (old_coordinate, origin, new_coordinate)):
            raise ValueError("当前坐标无效，不能设置 G54")
        answer = QMessageBox.question(
            self,
            f"确认应用 {axis.value} 轴 G54",
            f"{axis.value} 轴零点位置（旧 G54）：{_measurement(origin)}\n"
            f"当前 G54 读数：{_measurement(old_coordinate)}\n"
            f"应用后当前 G54 读数：{_measurement(new_coordinate)}\n\n"
            "机床不会因此移动。LinuxCNC 会持久保存 G54；"
            "应用后触碰记录将清空。确认设置？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def apply_confirmed() -> None:
            # 确认框打开期间控制器仍可能被其他入口改变；避免按过时的读数写 G54。
            latest_status = self.service.controller.status()
            latest_coordinate = latest_status.x_mm if axis is Axis.X else latest_status.y_mm
            latest_origin = self.service.preview_axis(axis, reference, compensation)
            if (not math.isfinite(latest_coordinate)
                    or abs(latest_coordinate - old_coordinate) > 0.001
                    or abs(latest_origin - origin) > 0.001):
                raise RuntimeError("坐标或找中记录已变化，请重新预览并确认")
            self.service.apply_axis(axis, reference, compensation)

        apply_confirmed()
