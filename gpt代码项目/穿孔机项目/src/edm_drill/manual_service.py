"""全机床手动控制：把页面命令与作业状态、轴运动及辅助输出联锁。"""

from __future__ import annotations

import math

from .domain import MachineMode, MachineStatus
from .job_service import JobService


class ManualService:
    """只执行离散点动/目标移动；持续按住运动需另做失焦停止联锁。"""

    def __init__(self, job: JobService):
        self.job = job
        self.controller = job.controller

    @property
    def job_active(self) -> bool:
        return self.job.running or self.job.waiting_xy or self.job.waiting_hole or self.job.paused

    def _ready(self, *, allow_fault_off: bool = False) -> MachineStatus:
        if self.job_active:
            raise RuntimeError("作业运行或暂停中，禁止手动控制；请先停止作业")
        status = self.controller.status()
        if allow_fault_off and status.mode == MachineMode.FAULT:
            return status
        if status.mode != MachineMode.MANUAL_Z:
            raise RuntimeError("控制器未处于手动模式")
        return status

    def _axes_ready(self, *, xy: bool) -> MachineStatus:
        status = self._ready()
        if not status.homed or (xy and not status.xy_homed):
            raise RuntimeError("请先完成 Z 与 XY 回零")
        if status.pulse_enabled:
            raise RuntimeError("轴移动前请关闭手动放电")
        if not status.xy_stationary or not self.controller.xy_in_position:
            raise RuntimeError("XY 尚未停稳")
        return status

    @staticmethod
    def _finite(value: float, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name}必须为有限数")

    def home_xy(self) -> None:
        status = self._ready()
        if not status.homed or status.pulse_enabled:
            raise RuntimeError("XY 回零前请先回零 Z 并关闭放电")
        self.controller.home_xy()
        self.job.log("手动请求 XY 回零")

    def home_z(self) -> None:
        status = self._ready()
        if status.pulse_enabled:
            raise RuntimeError("Z 回零前请关闭放电")
        self.controller.home_z()
        self.job.log("手动请求 Z 回零")

    def set_surface_zero(self) -> None:
        status = self._ready()
        if not status.homed or status.pulse_enabled:
            raise RuntimeError("确认 Z0 前请回零 Z 并关闭放电")
        self.controller.set_surface_zero()
        self.job.log("已确认工件表面 Z0")

    def reset_fault(self) -> None:
        if self.job_active:
            raise RuntimeError("停止作业后才能复位故障")
        self.job.reset_fault()

    def stop_motion(self) -> None:
        """中止手动轴运动并关闭手动输出；自动作业使用作业停止按钮。"""
        if self.job_active:
            raise RuntimeError("自动作业运行中，请使用停止作业")
        errors: list[str] = []
        try:
            self.controller.stop()
        except Exception as exc:
            errors.append(f"轴停止失败：{exc}")
            try:
                self.controller.emergency_stop()
            except Exception as emergency_exc:
                errors.append(f"急停请求失败：{emergency_exc}")
        # 不依赖下位机 stop() 的辅助输出实现细节，逐项请求关闭。
        for name in ("pulse", "rotation", "flush"):
            if not self.supports_manual_output(name):
                continue
            try:
                getattr(self.controller, f"set_{name}")(False)
            except Exception as exc:
                errors.append(f"{name} 关闭失败：{exc}")
        if errors:
            raise RuntimeError("；".join(errors))
        self.job.log("已请求停止手动运动和输出")

    def jog_xy(self, dx_mm: float, dy_mm: float) -> None:
        self._finite(dx_mm, "X 点动量")
        self._finite(dy_mm, "Y 点动量")
        if (dx_mm == 0) == (dy_mm == 0):
            raise ValueError("每次只允许一条轴点动")
        if max(abs(dx_mm), abs(dy_mm)) > 10:
            raise ValueError("单次 XY 点动不超过 10 mm")
        self._axes_ready(xy=True)
        self.controller.jog_xy(dx_mm, dy_mm)
        self.job.log(f"手动 XY 点动：X{dx_mm:+.3f} Y{dy_mm:+.3f}")

    def move_xy(self, x_mm: float, y_mm: float) -> None:
        self._finite(x_mm, "X 目标")
        self._finite(y_mm, "Y 目标")
        status = self._axes_ready(xy=True)
        if status.z_mm < 0:
            raise RuntimeError("XY 快移前请先将 Z 抬至 0 mm 或以上；接触高度仅用小步距点动")
        self.controller.manual_move_xy(x_mm, y_mm)
        self.job.log(f"手动 XY 目标：X{x_mm:.3f} Y{y_mm:.3f}")

    def jog_z(self, delta_mm: float) -> None:
        self._finite(delta_mm, "Z 点动量")
        if delta_mm == 0 or abs(delta_mm) > 10:
            raise ValueError("单次 Z 点动须在 0～10 mm 内")
        self._axes_ready(xy=False)
        self.controller.jog_z(delta_mm)
        self.job.log(f"手动 Z 点动：{delta_mm:+.3f} mm")

    def move_z(self, target_mm: float) -> None:
        self._finite(target_mm, "Z 目标")
        self._axes_ready(xy=False)
        self.controller.move_z_absolute(target_mm)
        self.job.log(f"手动 Z 目标：{target_mm:.3f} mm")

    def supports_manual_output(self, name: str) -> bool:
        check = getattr(self.controller, "supports_manual_output", None)
        return bool(check(name)) if callable(check) else False

    def _set_output(self, name: str, enabled: bool) -> None:
        if name not in ("flush", "rotation", "pulse"):
            raise ValueError("未知手动输出")
        if not self.supports_manual_output(name):
            raise RuntimeError(f"{name} 输出未接入")
        status = self._ready(allow_fault_off=not enabled)
        if enabled and (not status.xy_stationary or not self.controller.xy_in_position):
            raise RuntimeError("XY 尚未停稳，禁止开启手动输出")
        if enabled and name == "pulse":
            if not status.homed or not status.surface_set or not status.flush_enabled:
                raise RuntimeError("手动放电前请确认 Z0 并开启冲液")
        getattr(self.controller, f"set_{name}")(bool(enabled))
        names = {"flush": "冲液", "rotation": "电极旋转", "pulse": "放电"}
        self.job.log(f"手动{names[name]}已{'开启' if enabled else '关闭'}")

    def set_flush(self, enabled: bool) -> None:
        self._set_output("flush", enabled)

    def set_rotation(self, enabled: bool) -> None:
        self._set_output("rotation", enabled)

    def set_pulse(self, enabled: bool) -> None:
        self._set_output("pulse", enabled)
