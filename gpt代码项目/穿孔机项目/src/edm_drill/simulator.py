"""离线下位机模拟器。用于界面和流程测试，不代表放电物理过程。"""

from __future__ import annotations

from dataclasses import replace
import math

from .domain import FeedbackMode, MachineConfig, MachineMode, MachineStatus


class SimulatedController:
    def __init__(self, config: MachineConfig):
        config.validate()
        self.config = config
        self._status = MachineStatus(mode=MachineMode.MANUAL_Z)
        self._target_depth_mm = 0.0
        self._completed_holes = 0

    @property
    def completed_holes(self) -> int:
        return self._completed_holes

    @property
    def xy_in_position(self) -> bool:
        # 仿真 XY 运动立即完成；实机适配器需读取 LinuxCNC 的到位信号。
        return True

    def status(self) -> MachineStatus:
        resolution = self.config.feedback.scale_mm_per_count
        measured_scale = round(self._status.z_mm / resolution) * resolution
        return replace(self._status, scale_mm=measured_scale, encoder_mm=self._status.z_mm)

    def apply_config(self, config: MachineConfig) -> None:
        config.validate()
        self._require(MachineMode.MANUAL_Z)
        self.config = config
        # 模式切换后重新确认工件表面，避免沿用旧坐标。
        self._status = replace(self._status, surface_set=False)

    def home_z(self) -> None:
        self._require(MachineMode.MANUAL_Z)
        if self._status.pulse_enabled:
            raise RuntimeError("放电开启时不能回零 Z")
        self._status = replace(self._status, z_mm=0.0, homed=True, surface_set=False)

    def home_xy(self) -> None:
        """模拟 XY 双轴回零，保留当前 G54 偏置。"""
        self._require(MachineMode.MANUAL_Z)
        if self._status.pulse_enabled:
            raise RuntimeError("放电开启时不能回零 XY")
        self._status = replace(
            self._status, xy_homed=True,
            x_mm=0.0 - self._status.g54_offset_x_mm,
            y_mm=0.0 - self._status.g54_offset_y_mm,
        )

    def set_surface_zero(self) -> None:
        self._require(MachineMode.MANUAL_Z)
        if self._status.pulse_enabled:
            raise RuntimeError("放电开启时不能设置 Z0")
        if not self._status.homed:
            raise RuntimeError("请先回零")
        self._status = replace(self._status, z_mm=0.0, surface_set=True)

    def jog_z(self, delta_mm: float) -> None:
        self.move_z_absolute(self._status.z_mm + delta_mm)

    def move_z_absolute(self, target_mm: float) -> None:
        """仿真快移立即到位；实机由下位机执行限速和加减速。"""
        self._require(MachineMode.MANUAL_Z)
        if self._status.pulse_enabled:
            raise RuntimeError("放电开启时不能手动移动 Z")
        if not self._status.homed:
            raise RuntimeError("请先回零")
        if not self.config.z_min_mm <= target_mm <= self.config.z_max_mm:
            raise RuntimeError("Z 轴运动超出软限位")
        self._status = replace(self._status, z_mm=target_mm, surface_set=False)

    def move_xy(self, x_mm: float, y_mm: float) -> None:
        self._require(MachineMode.MANUAL_Z)
        if self._status.pulse_enabled:
            raise RuntimeError("放电开启时不能移动 XY")
        if not self._status.xy_homed or not self._status.homed or not self._status.surface_set:
            raise RuntimeError("加工 XY 前请回零并确认工件表面 Z0")
        self._set_xy(x_mm, y_mm)

    def _set_xy(self, x_mm: float, y_mm: float) -> None:
        if not math.isfinite(x_mm) or not math.isfinite(y_mm):
            raise RuntimeError("XY 目标必须为有限数")
        if not self.config.x_min_mm <= x_mm <= self.config.x_max_mm:
            raise RuntimeError("X 超出软限位")
        if not self.config.y_min_mm <= y_mm <= self.config.y_max_mm:
            raise RuntimeError("Y 超出软限位")
        self._status = replace(self._status, x_mm=x_mm, y_mm=y_mm)

    def manual_move_xy(self, x_mm: float, y_mm: float) -> None:
        """手动 XY 不依赖工件 Z0，供找边前定位。"""
        self._require(MachineMode.MANUAL_Z)
        if not self._status.xy_homed or not self._status.homed or self._status.pulse_enabled:
            raise RuntimeError("手动 XY 前请回零并关闭放电")
        if self._status.z_mm < 0:
            raise RuntimeError("XY 快移前请抬起 Z；接触高度仅允许小步距点动")
        self._set_xy(x_mm, y_mm)

    def jog_xy(self, dx_mm: float, dy_mm: float) -> None:
        if not math.isfinite(dx_mm) or not math.isfinite(dy_mm):
            raise RuntimeError("XY 点动量必须为有限数")
        if (dx_mm == 0) == (dy_mm == 0):
            raise RuntimeError("每次只允许单轴点动")
        self._require(MachineMode.MANUAL_Z)
        if not self._status.xy_homed or not self._status.homed or self._status.pulse_enabled:
            raise RuntimeError("手动 XY 前请回零并关闭放电")
        self._set_xy(self._status.x_mm + dx_mm, self._status.y_mm + dy_mm)

    def set_work_coordinates(self, x_mm: float | None = None, y_mm: float | None = None) -> None:
        """模拟 G10 L20 P1：保持机床位置，修改当前铜管中心的 G54 读数。"""
        self._require(MachineMode.MANUAL_Z)
        if not self._status.xy_homed or not self._status.homed or self._status.pulse_enabled:
            raise RuntimeError("写入 G54 前请回零并关闭放电")
        if x_mm is None and y_mm is None:
            raise ValueError("至少指定一条 G54 轴")
        values = (x_mm, y_mm)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("G54 坐标必须为有限数")
        state = self._status
        self._status = replace(
            state,
            x_mm=state.x_mm if x_mm is None else x_mm,
            y_mm=state.y_mm if y_mm is None else y_mm,
            g54_offset_x_mm=(state.g54_offset_x_mm if x_mm is None
                             else state.g54_offset_x_mm + state.x_mm - x_mm),
            g54_offset_y_mm=(state.g54_offset_y_mm if y_mm is None
                             else state.g54_offset_y_mm + state.y_mm - y_mm),
        )

    def supports_manual_output(self, name: str) -> bool:
        return name in ("flush", "rotation", "pulse")

    def set_flush(self, enabled: bool) -> None:
        if enabled:
            self._require(MachineMode.MANUAL_Z)
        self._status = replace(
            self._status, flush_enabled=bool(enabled),
            pulse_enabled=self._status.pulse_enabled if enabled else False,
        )

    def set_rotation(self, enabled: bool) -> None:
        if enabled:
            self._require(MachineMode.MANUAL_Z)
        self._status = replace(self._status, rotation_enabled=bool(enabled))

    def set_pulse(self, enabled: bool) -> None:
        if enabled:
            self._require(MachineMode.MANUAL_Z)
            if not self._status.homed or not self._status.surface_set or not self._status.flush_enabled:
                raise RuntimeError("手动放电前请确认 Z0 并开启冲液")
        self._status = replace(self._status, pulse_enabled=bool(enabled))

    def arm_hole(self, recipe_id: int, depth_mm: float) -> None:
        self._require(MachineMode.MANUAL_Z)
        if not self._status.homed or not self._status.surface_set:
            raise RuntimeError("穿孔前请回零并确认工件表面 Z0")
        feedback_mode = self.config.feedback.mode
        encoder_required = feedback_mode in (FeedbackMode.ENCODER, FeedbackMode.DUAL)
        scale_required = feedback_mode in (FeedbackMode.SCALE, FeedbackMode.DUAL)
        if (encoder_required and not self._status.encoder_ok) or (scale_required and not self._status.scale_ok):
            raise RuntimeError("位置传感器故障")
        if not 0 < depth_mm <= self.config.max_hole_depth_mm:
            raise RuntimeError("穿孔深度无效")
        if -depth_mm < self.config.z_min_mm:
            raise RuntimeError("穿孔目标超过 Z 软限位")
        self._target_depth_mm = depth_mm
        self._status = replace(self._status, mode=MachineMode.ARMED, active_recipe=recipe_id)

    def start_hole(self) -> None:
        self._require(MachineMode.ARMED)
        self._status = replace(self._status, mode=MachineMode.EDM_Z, pulse_enabled=True)

    def stop(self) -> None:
        if self._status.mode in (MachineMode.EDM_Z, MachineMode.ARMED):
            self._status = replace(
                self._status, mode=MachineMode.RETRACT, pulse_enabled=False,
                flush_enabled=False, rotation_enabled=False,
            )
        else:
            self._status = replace(
                self._status, pulse_enabled=False, flush_enabled=False, rotation_enabled=False,
            )

    def emergency_stop(self) -> None:
        self._status = replace(
            self._status, mode=MachineMode.FAULT, pulse_enabled=False,
            flush_enabled=False, rotation_enabled=False,
            active_recipe=None, fault="急停触发（仿真）",
        )

    def reset_fault(self) -> None:
        self._require(MachineMode.FAULT)
        self._status = replace(
            self._status, mode=MachineMode.MANUAL_Z, fault="", homed=False, xy_homed=False,
            surface_set=False, active_recipe=None,
        )

    def tick(self, elapsed_s: float) -> None:
        if elapsed_s <= 0:
            return
        state = self._status
        if state.mode == MachineMode.EDM_Z:
            next_z = max(-self._target_depth_mm, state.z_mm - self.config.edm_feed_mm_s * elapsed_s)
            if next_z <= -self._target_depth_mm:
                self._status = replace(state, z_mm=next_z, mode=MachineMode.RETRACT, pulse_enabled=False)
            else:
                self._status = replace(state, z_mm=next_z)
        elif state.mode == MachineMode.RETRACT:
            next_z = min(0.0, state.z_mm + self.config.manual_speed_mm_s * elapsed_s)
            if next_z >= 0:
                self._status = replace(state, z_mm=0.0, mode=MachineMode.MANUAL_Z, active_recipe=None)
                self._completed_holes += 1
            else:
                self._status = replace(state, z_mm=next_z)

    def _require(self, mode: MachineMode) -> None:
        if self._status.mode != mode:
            raise RuntimeError(f"当前模式 {self._status.mode.value} 不允许此操作")
