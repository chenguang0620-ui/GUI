"""LinuxCNC XY 接口：通过同机 Python API 执行 MDI；Z/放电由 STM 控制器负责。

此文件只在安装 LinuxCNC 的机床电脑上导入原生 ``linuxcnc`` 模块。
不要把 LinuxCNC 的 Z 轴脉冲和 STM32 的 Z 轴脉冲并联到同一驱动器。
"""

from __future__ import annotations

from dataclasses import replace
import importlib
import math
import time
from types import ModuleType

from .controller import ZController
from .domain import MachineConfig, MachineMode, MachineStatus
from .simulator import SimulatedController


class LinuxCncController:
    """把 LinuxCNC 的 XY 运动与独立的 Z/EDM 控制器组成统一接口。

    ``move_xy`` 只发起运动；``xy_in_position`` 使用 LinuxCNC 的
    ``inpos``、解释器状态与实际位置共同确认到位。作业调度在到位前等待。
    ``z_controller`` 必须具有真实的 Z 轴与穿孔实现；仿真 Z 只供台架测试。
    """

    def __init__(
        self,
        z_controller: ZController,
        config: MachineConfig,
        *,
        linuxcnc_module: ModuleType | None = None,
        xy_joint_indices: tuple[int, int] = (0, 1),
        xy_timeout_s: float = 30.0,
        arrival_tolerance_mm: float = 0.02,
        allow_simulated_z: bool = False,
    ):
        config.validate(require_hardware=True)
        if isinstance(z_controller, SimulatedController) and not allow_simulated_z:
            raise ValueError("实机 LinuxCNC 不能搭配仿真 Z 控制器")
        if len(xy_joint_indices) != 2 or min(xy_joint_indices) < 0:
            raise ValueError("XY 关节索引无效")
        if (not math.isfinite(xy_timeout_s) or not math.isfinite(arrival_tolerance_mm)
                or xy_timeout_s <= 0 or arrival_tolerance_mm <= 0):
            raise ValueError("到位超时和公差必须大于 0")
        if linuxcnc_module is None:
            try:
                linuxcnc_module = importlib.import_module("linuxcnc")
            except ImportError as exc:
                raise RuntimeError("未找到 LinuxCNC Python 模块；请在机床电脑的 LinuxCNC 环境运行") from exc
        self.api = linuxcnc_module
        self.command = self.api.command()
        self.stat = self.api.stat()
        self.errors = self.api.error_channel()
        self.z = z_controller
        self.config = config
        self.xy_joint_indices = xy_joint_indices
        self.xy_timeout_s = xy_timeout_s
        self.arrival_tolerance_mm = arrival_tolerance_mm
        self._xy_target: tuple[float, float] | None = None
        self._xy_manual_jog_axis: int | None = None
        self._xy_deadline: float | None = None
        self._fault_message = ""
        self._fault_latched = False

    @property
    def completed_holes(self) -> int:
        return self.z.completed_holes

    def _poll(self) -> bool:
        try:
            self.stat.poll()
            return True
        except Exception as exc:
            self._fault_stop(f"LinuxCNC 状态通信失败：{exc}")
            return False

    def _fault_stop(self, message: str) -> None:
        """LinuxCNC 异常时同时撤销 XY 指令并要求 Z/放电急停。"""
        if self._fault_latched:
            return
        self._fault_latched = True
        self._fault_message = message
        self._xy_target = None
        self._xy_deadline = None
        if self._xy_manual_jog_axis is not None:
            try:
                self.command.jog(self.api.JOG_STOP, False, self._xy_manual_jog_axis)
            except Exception as exc:
                self._fault_message += f"；XY 点动停止命令失败：{exc}"
            self._xy_manual_jog_axis = None
        try:
            self.command.abort()
        except Exception as exc:
            self._fault_message += f"；XY 中止命令失败：{exc}"
        try:
            self.z.emergency_stop()
        except Exception as exc:
            self._fault_message += f"；Z 急停命令失败：{exc}"

    def _fault_status(self) -> MachineStatus:
        # 故障处理可能改变 Z 状态，必须重新读取，避免界面显示旧的放电开状态。
        # XY 状态不可用时使用 NaN，由界面显示“—”，不能误报为 G54 零点。
        return replace(
            self.z.status(), x_mm=math.nan, y_mm=math.nan,
            xy_homed=False, xy_stationary=False,
            g54_offset_x_mm=math.nan, g54_offset_y_mm=math.nan,
            mode=MachineMode.FAULT, fault=self._fault_message,
        )

    def _poll_error_channel(self) -> None:
        try:
            error = self.errors.poll()
        except Exception as exc:
            self._fault_stop(f"LinuxCNC 错误通道通信失败：{exc}")
            return
        if error and error[0] in (
            getattr(self.api, "NML_ERROR", None),
            getattr(self.api, "OPERATOR_ERROR", None),
        ):
            self._fault_stop(f"LinuxCNC：{error[1]}")

    def _work_xy(self) -> tuple[float, float]:
        """仅在无 XY 旋转/额外偏置时将机床坐标换算成 G54 工作坐标。"""
        actual = self.stat.actual_position
        g5x = self.stat.g5x_offset
        g92 = self.stat.g92_offset
        tool = self.stat.tool_offset
        return (
            float(actual[0] - g5x[0] - g92[0] - tool[0]),
            float(actual[1] - g5x[1] - g92[1] - tool[1]),
        )

    def status(self) -> MachineStatus:
        if not self._poll():
            return self._fault_status()
        self._poll_error_channel()
        if self._fault_message:
            return self._fault_status()
        # 手动 XY 没有 JobService.waiting_xy；状态刷新也必须确认到位并清理目标。
        if self._xy_target is not None:
            _ = self.xy_in_position
            if self._fault_message:
                return self._fault_status()
        try:
            x, y = self._work_xy()
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            self._fault_stop(f"LinuxCNC 坐标状态无效：{exc}")
            return self._fault_status()
        if self.stat.task_state != self.api.STATE_ON:
            self._fault_stop("LinuxCNC 未上电或急停未释放")
            return self._fault_status()
        xy_homed = (
            max(self.xy_joint_indices) < len(self.stat.homed)
            and all(self.stat.homed[index] for index in self.xy_joint_indices)
        )
        return replace(
            self.z.status(), x_mm=x, y_mm=y, xy_homed=xy_homed,
            xy_stationary=(self._xy_target is None and bool(self.stat.inpos)
                           and self.stat.interp_state == self.api.INTERP_IDLE),
            g54_offset_x_mm=float(self.stat.g5x_offset[0]),
            g54_offset_y_mm=float(self.stat.g5x_offset[1]),
        )

    def _require_xy_ready(self) -> None:
        if not self._poll():
            raise RuntimeError(self._fault_message)
        self._poll_error_channel()
        if self._fault_message:
            raise RuntimeError(self._fault_message)
        if self.stat.task_state != self.api.STATE_ON:
            raise RuntimeError("LinuxCNC 未上电或急停未释放")
        if max(self.xy_joint_indices) >= len(self.stat.homed):
            raise RuntimeError("LinuxCNC XY 关节索引与机床配置不匹配")
        if any(not self.stat.homed[index] for index in self.xy_joint_indices):
            raise RuntimeError("LinuxCNC X/Y 轴尚未回零")
        if not math.isclose(float(self.stat.linear_units), 1.0, abs_tol=0.00001):
            raise RuntimeError("当前 LinuxCNC 机床单位不是毫米；请先使用毫米机床配置")
        if self.stat.g5x_index != 1:
            raise RuntimeError("请先在 LinuxCNC 选择 G54 工作坐标系")
        if abs(float(self.stat.rotation_xy)) > 0.00001:
            raise RuntimeError("LinuxCNC 存在 XY 坐标旋转；此接口仅支持零旋转")
        if any(abs(float(values[index])) > 0.00001 for values in
               (self.stat.g92_offset, self.stat.tool_offset) for index in (0, 1)):
            raise RuntimeError("LinuxCNC 存在 G92 或刀具 XY 偏置；请先清除")

    def _require_stationary_xy(self) -> None:
        self._require_xy_ready()
        if not self.xy_in_position or self.stat.interp_state != self.api.INTERP_IDLE or not self.stat.inpos:
            raise RuntimeError("LinuxCNC XY 未停稳，禁止 Z 运动或放电")

    @property
    def xy_in_position(self) -> bool:
        if self._xy_target is None:
            return True
        if not self._poll():
            return False
        self._poll_error_channel()
        if self._fault_message:
            return False
        try:
            x, y = self._work_xy()
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            self._fault_stop(f"LinuxCNC 坐标状态无效：{exc}")
            return False
        target_x, target_y = self._xy_target
        arrived = (
            self.stat.interp_state == self.api.INTERP_IDLE
            and bool(self.stat.inpos)
            and abs(x - target_x) <= self.arrival_tolerance_mm
            and abs(y - target_y) <= self.arrival_tolerance_mm
        )
        if arrived:
            self._xy_target = None
            self._xy_deadline = None
            self._xy_manual_jog_axis = None
        return arrived

    def move_xy(self, x_mm: float, y_mm: float) -> None:
        self._send_xy(x_mm, y_mm, require_surface=True)

    def manual_move_xy(self, x_mm: float, y_mm: float) -> None:
        """手动目标快移不依赖 Z0，但仍要求 Z 已回零且放电关闭。"""
        self._send_xy(x_mm, y_mm, require_surface=False, require_z_clearance=True)

    def _send_xy(
        self, x_mm: float, y_mm: float, *, require_surface: bool,
        require_z_clearance: bool = False,
    ) -> None:
        self._require_xy_ready()
        if not math.isfinite(x_mm) or not math.isfinite(y_mm):
            raise RuntimeError("XY 目标必须为有限数")
        z_status = self.z.status()
        if z_status.mode != MachineMode.MANUAL_Z or not z_status.homed or z_status.pulse_enabled:
            raise RuntimeError("Z 轴未回零、放电未关闭或不在手动模式")
        if require_surface and not z_status.surface_set:
            raise RuntimeError("加工 XY 前请确认工件 Z0")
        if require_z_clearance and z_status.z_mm < 0:
            raise RuntimeError("XY 快移前请抬起 Z；接触高度仅允许小步距点动")
        if not self.xy_in_position:
            raise RuntimeError("上一条 XY 运动尚未完成")
        if not self.config.x_min_mm <= x_mm <= self.config.x_max_mm:
            raise RuntimeError("X 超出软件行程")
        if not self.config.y_min_mm <= y_mm <= self.config.y_max_mm:
            raise RuntimeError("Y 超出软件行程")
        self._require_stationary_xy()
        try:
            self.command.mode(self.api.MODE_MDI)
            if self.command.wait_complete(2.0) != self.api.RCS_DONE:
                raise RuntimeError("LinuxCNC 切换 MDI 模式失败")
            # 只发送 XY；Z 由 STM32 独占。显式声明单位、坐标和距离模式。
            self.command.mdi(f"G21 G90 G54 G0 X{x_mm:.3f} Y{y_mm:.3f}")
        except Exception as exc:
            self._fault_stop(f"LinuxCNC XY 指令失败：{exc}")
            raise RuntimeError(self._fault_message) from exc
        self._xy_target = (x_mm, y_mm)
        self._xy_manual_jog_axis = None
        self._xy_deadline = time.monotonic() + self.xy_timeout_s

    def home_xy(self) -> None:
        """仅支持 LinuxCNC 配置恰好两条 XY 关节时整组回零。"""
        if not self._poll():
            raise RuntimeError(self._fault_message)
        self._poll_error_channel()
        if self._fault_message or self.stat.task_state != self.api.STATE_ON:
            raise RuntimeError(self._fault_message or "LinuxCNC 未上电")
        if len(self.stat.homed) != 2 or self.xy_joint_indices != (0, 1):
            raise RuntimeError("XY 回零仅支持仅配置 X/Y 两关节的 LinuxCNC")
        z_status = self.z.status()
        if z_status.mode != MachineMode.MANUAL_Z or not z_status.homed or z_status.pulse_enabled:
            raise RuntimeError("请先回零 Z 并关闭放电")
        if self._xy_target is not None or not self.stat.inpos or self.stat.interp_state != self.api.INTERP_IDLE:
            raise RuntimeError("XY 运动中不能重新回零")
        try:
            self.command.mode(self.api.MODE_MANUAL)
            if self.command.wait_complete(2.0) != self.api.RCS_DONE:
                raise RuntimeError("LinuxCNC 切换手动模式失败")
            # 本机配置只有 XY 两关节时，home(-1) 不会操作 STM 独占的 Z。
            self.command.home(-1)
        except Exception as exc:
            self._fault_stop(f"LinuxCNC XY 回零命令失败：{exc}")
            raise RuntimeError(self._fault_message) from exc

    def jog_xy(self, dx_mm: float, dy_mm: float) -> None:
        """LinuxCNC 离散增量点动；轴坐标模式 X=0、Y=1。"""
        if not math.isfinite(dx_mm) or not math.isfinite(dy_mm) or (dx_mm == 0) == (dy_mm == 0):
            raise ValueError("每次仅允许一条 XY 轴有限增量点动")
        self._require_stationary_xy()
        z_status = self.z.status()
        if z_status.mode != MachineMode.MANUAL_Z or not z_status.homed or z_status.pulse_enabled:
            raise RuntimeError("Z 未回零、放电未关闭或不在手动模式")
        x, y = self._work_xy()
        target_x, target_y = x + dx_mm, y + dy_mm
        if not self.config.x_min_mm <= target_x <= self.config.x_max_mm:
            raise RuntimeError("X 点动目标超出软件行程")
        if not self.config.y_min_mm <= target_y <= self.config.y_max_mm:
            raise RuntimeError("Y 点动目标超出软件行程")
        axis, delta = (0, dx_mm) if dx_mm else (1, dy_mm)
        try:
            self.command.mode(self.api.MODE_MANUAL)
            if self.command.wait_complete(2.0) != self.api.RCS_DONE:
                raise RuntimeError("LinuxCNC 切换手动模式失败")
            self.command.teleop_enable(1)
            if self.command.wait_complete(2.0) != self.api.RCS_DONE:
                raise RuntimeError("LinuxCNC 切换轴坐标点动失败")
            if not self._poll():
                raise RuntimeError(self._fault_message)
            if self.stat.motion_mode != self.api.TRAJ_MODE_TELEOP:
                raise RuntimeError("LinuxCNC 未进入轴坐标点动模式")
            velocity = math.copysign(self.config.manual_speed_mm_s, delta)
            self.command.jog(self.api.JOG_INCREMENT, False, axis, velocity, abs(delta))
        except Exception as exc:
            self._fault_stop(f"LinuxCNC XY 点动失败：{exc}")
            raise RuntimeError(self._fault_message) from exc
        self._xy_target = (target_x, target_y)
        self._xy_manual_jog_axis = axis
        self._xy_deadline = time.monotonic() + self.xy_timeout_s

    def set_work_coordinates(self, x_mm: float | None = None, y_mm: float | None = None) -> None:
        """G10 L20 P1 将当前铜管中心的 G54 读数改为指定轴坐标。"""
        if x_mm is None and y_mm is None:
            raise ValueError("至少指定一条 G54 轴")
        if any(value is not None and not math.isfinite(value) for value in (x_mm, y_mm)):
            raise ValueError("G54 坐标必须为有限数")
        self._require_stationary_xy()
        z_status = self.z.status()
        if z_status.mode != MachineMode.MANUAL_Z or not z_status.homed or z_status.pulse_enabled:
            raise RuntimeError("写入 G54 前须 Z 回零、停止并关闭放电")
        words = "".join(
            f" {axis}{value:.3f}" for axis, value in (("X", x_mm), ("Y", y_mm)) if value is not None
        )
        try:
            self.command.mode(self.api.MODE_MDI)
            if self.command.wait_complete(2.0) != self.api.RCS_DONE:
                raise RuntimeError("LinuxCNC 切换 MDI 模式失败")
            self.command.mdi(f"G10 L20 P1{words}")
            if self.command.wait_complete(2.0) != self.api.RCS_DONE or not self._poll():
                raise RuntimeError("LinuxCNC G54 写入未确认")
            actual_x, actual_y = self._work_xy()
            if ((x_mm is not None and abs(actual_x - x_mm) > self.arrival_tolerance_mm)
                    or (y_mm is not None and abs(actual_y - y_mm) > self.arrival_tolerance_mm)):
                raise RuntimeError("LinuxCNC G54 写入后坐标未达到预期")
        except Exception as exc:
            self._fault_stop(f"LinuxCNC G54 写入失败：{exc}")
            raise RuntimeError(self._fault_message) from exc

    def supports_manual_output(self, name: str) -> bool:
        check = getattr(self.z, "supports_manual_output", None)
        return bool(check(name)) if callable(check) else False

    def _set_manual_output(self, name: str, enabled: bool) -> None:
        if not self.supports_manual_output(name):
            raise RuntimeError(f"{name} 输出未接入 STM 控制器")
        if enabled:
            if not self._poll() or self.stat.task_state != self.api.STATE_ON:
                raise RuntimeError(self._fault_message or "LinuxCNC 未上电")
            if self._xy_target is not None or not self.stat.inpos or self.stat.interp_state != self.api.INTERP_IDLE:
                raise RuntimeError("XY 运动中不能开启手动输出")
            if self.z.status().mode != MachineMode.MANUAL_Z:
                raise RuntimeError("Z 不在手动模式")
        getattr(self.z, f"set_{name}")(enabled)

    def set_flush(self, enabled: bool) -> None:
        self._set_manual_output("flush", enabled)

    def set_rotation(self, enabled: bool) -> None:
        self._set_manual_output("rotation", enabled)

    def set_pulse(self, enabled: bool) -> None:
        self._set_manual_output("pulse", enabled)

    def tick(self, elapsed_s: float) -> None:
        self._poll_error_channel()
        if self._fault_latched:
            return
        z_mode = self.z.status().mode
        if z_mode in (MachineMode.EDM_Z, MachineMode.RETRACT) or self._xy_target is not None:
            if not self._poll():
                return
            if self.stat.task_state != self.api.STATE_ON:
                self._fault_stop("LinuxCNC 未上电或急停未释放")
                return
        if z_mode in (MachineMode.EDM_Z, MachineMode.RETRACT):
            if (not self.stat.inpos or self.stat.interp_state != self.api.INTERP_IDLE
                    or self._xy_target is not None):
                self._fault_stop("放电或退刀期间 LinuxCNC XY 状态异常")
                return
        self.z.tick(elapsed_s)
        z_status = self.z.status()
        if z_status.mode == MachineMode.FAULT:
            self._fault_stop(f"Z 控制器故障：{z_status.fault}")
            return
        if self._xy_deadline is not None and time.monotonic() > self._xy_deadline:
            if not self.xy_in_position:
                self._fault_stop("LinuxCNC XY 到位超时")

    def apply_config(self, config: MachineConfig) -> None:
        config.validate(require_hardware=True)
        if self._xy_target is not None:
            raise RuntimeError("XY 运动中不能改设置")
        self.z.apply_config(config)
        self.config = config

    def home_z(self) -> None:
        # 允许先回零 STM Z，再在手动页请求 LinuxCNC XY 回零。
        if not self._poll():
            raise RuntimeError(self._fault_message)
        self._poll_error_channel()
        if self._fault_message or self.stat.task_state != self.api.STATE_ON:
            raise RuntimeError(self._fault_message or "LinuxCNC 未上电")
        if self._xy_target is not None or not self.stat.inpos or self.stat.interp_state != self.api.INTERP_IDLE:
            raise RuntimeError("XY 未停稳，禁止 Z 回零")
        self.z.home_z()

    def set_surface_zero(self) -> None:
        self._require_stationary_xy()
        self.z.set_surface_zero()

    def jog_z(self, delta_mm: float) -> None:
        self._require_stationary_xy()
        self.z.jog_z(delta_mm)

    def move_z_absolute(self, target_mm: float) -> None:
        self._require_stationary_xy()
        self.z.move_z_absolute(target_mm)

    def arm_hole(self, recipe_id: int, depth_mm: float) -> None:
        self._require_stationary_xy()
        self.z.arm_hole(recipe_id, depth_mm)

    def start_hole(self) -> None:
        self._require_stationary_xy()
        self.z.start_hole()

    def stop(self) -> None:
        jog_error: Exception | None = None
        try:
            if self._xy_manual_jog_axis is not None:
                try:
                    self.command.jog(self.api.JOG_STOP, False, self._xy_manual_jog_axis)
                except Exception as exc:
                    jog_error = exc
            self.command.abort()
        finally:
            self._xy_target = None
            self._xy_manual_jog_axis = None
            self._xy_deadline = None
            self.z.stop()
        if jog_error is not None:
            raise RuntimeError(f"LinuxCNC 点动停止命令失败：{jog_error}") from jog_error

    def emergency_stop(self) -> None:
        try:
            self.command.state(self.api.STATE_ESTOP)
        finally:
            self._xy_target = None
            self._xy_manual_jog_axis = None
            self._xy_deadline = None
            self._fault_message = "软件急停已请求；硬件急停仍须独立接线"
            self.z.emergency_stop()

    def reset_fault(self) -> None:
        # 故障后 LinuxCNC 可能丢失 XY 回零状态；复位不能以已回零为前提。
        # 电源和运动状态须先恢复安全，之后由操作者重新回零。
        if not self._poll():
            raise RuntimeError(self._fault_message)
        if self.stat.task_state != self.api.STATE_ON:
            raise RuntimeError("LinuxCNC 尚未重新上电，不能复位故障")
        if not self.stat.inpos or self.stat.interp_state != self.api.INTERP_IDLE:
            raise RuntimeError("LinuxCNC XY 未停稳，不能复位故障")
        if self.z.status().mode == MachineMode.FAULT:
            self.z.reset_fault()
        self._fault_message = ""
        self._fault_latched = False
