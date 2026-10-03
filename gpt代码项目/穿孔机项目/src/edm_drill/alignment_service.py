"""人工碰边找中流程：记录 G54 触碰读数、预览零点并按轴写入 G54。"""

from __future__ import annotations

import math

from .alignment import AlignmentSession, Axis, ReferenceMode, TouchEdge, TouchPoint
from .domain import MachineMode, MachineStatus
from .job_service import JobService


class AlignmentService:
    """触碰记录只在同一个 G54 基准中有效；改写 G54 后立即清空。"""

    def __init__(self, job: JobService, tube_outer_diameter_mm: float = 0.5):
        self.job = job
        self.controller = job.controller
        self.session = AlignmentSession(tube_outer_diameter_mm)
        self._g54_baseline: tuple[float, float] | None = None

    def _check_g54_basis(self, status: MachineStatus) -> None:
        offsets = (status.g54_offset_x_mm, status.g54_offset_y_mm)
        if not all(math.isfinite(value) for value in offsets):
            raise RuntimeError("G54 偏置读数无效，不能找中")
        if self._g54_baseline is not None and any(
            abs(now - before) > 0.0001 for now, before in zip(offsets, self._g54_baseline)
        ):
            self.session.clear_all()
            self._g54_baseline = None
            raise RuntimeError("G54 偏置已改变；旧触碰记录已清空，请重新找中")

    def _ready(self) -> MachineStatus:
        if self.job.running or self.job.waiting_xy or self.job.waiting_hole or self.job.paused:
            raise RuntimeError("作业运行或暂停时不能找中；请先停止作业")
        status = self.controller.status()
        if status.mode != MachineMode.MANUAL_Z or not status.homed or not status.xy_homed:
            raise RuntimeError("找中前请完成 XY/Z 回零并进入手动模式")
        if status.pulse_enabled:
            raise RuntimeError("找中前请关闭放电")
        if not status.xy_stationary or not self.controller.xy_in_position:
            raise RuntimeError("XY 尚未停稳，不能记录触碰或写入 G54")
        self._check_g54_basis(status)
        return status

    def set_tube_diameter(self, mm: float) -> None:
        if self.job.running or self.job.waiting_xy or self.job.waiting_hole or self.job.paused:
            raise RuntimeError("作业运行或暂停时不能改找中参数")
        if mm == self.session.tube_outer_diameter_mm:
            return
        self.session = AlignmentSession(mm)
        self._g54_baseline = None
        self.job.log(f"找中铜管外径设为 {mm:.4f} mm；旧触碰记录已清空")

    def capture(self, edge: TouchEdge) -> TouchPoint:
        edge = TouchEdge(edge)
        status = self._ready()
        touch = self.session.record_touch(edge, x_mm=status.x_mm, y_mm=status.y_mm)
        if self._g54_baseline is None:
            self._g54_baseline = (status.g54_offset_x_mm, status.g54_offset_y_mm)
        self.job.log(f"人工记录 {edge.value} 碰边：X{touch.x_mm:.3f} Y{touch.y_mm:.3f}")
        return touch

    def clear_touch(self, edge: TouchEdge) -> None:
        edge = TouchEdge(edge)
        self.session.clear_touch(edge)
        if not self.session.touches:
            self._g54_baseline = None
        self.job.log(f"已清除 {edge.value} 碰边记录")

    def clear_all(self) -> None:
        self.session.clear_all()
        self._g54_baseline = None
        self.job.log("已清除全部找中触碰记录")

    def preview_axis(self, axis: Axis, reference: ReferenceMode, compensation_mm: float = 0.0) -> float:
        return self.session.calculate_axis(axis, reference, compensation_mm)

    def apply_axis(self, axis: Axis, reference: ReferenceMode, compensation_mm: float = 0.0) -> float:
        """使旧 G54 下的目标零点变成新 G54 零点；写入不移动轴。"""
        axis = Axis(axis)
        status = self._ready()
        origin = self.preview_axis(axis, reference, compensation_mm)
        current = status.x_mm if axis is Axis.X else status.y_mm
        new_readout = current - origin
        if not math.isfinite(new_readout):
            raise ValueError("G54 新读数无效")
        # 指令可能已到达 LinuxCNC 但确认失联，此时旧触碰数据不能再沿用。
        try:
            if axis is Axis.X:
                self.controller.set_work_coordinates(x_mm=new_readout)
            else:
                self.controller.set_work_coordinates(y_mm=new_readout)
        finally:
            self.session.clear_all()
            self._g54_baseline = None
        updated = self.controller.status()
        actual = updated.x_mm if axis is Axis.X else updated.y_mm
        if updated.mode == MachineMode.FAULT or not math.isfinite(actual) or abs(actual - new_readout) > 0.02:
            raise RuntimeError("G54 已请求写入，但回读未确认；请检查机床坐标后重新找中")
        self.job.log(
            f"{axis.value} 轴 G54 已写入：旧零点 {origin:+.3f} mm，"
            f"当前铜管中心新读数 {actual:+.3f} mm"
        )
        return origin
