"""作业调度：校验后逐步解释 G 代码，不把扩展指令直接发送给驱动器。"""

from __future__ import annotations

from collections.abc import Callable
import math

from .controller import Controller
from .domain import DEFAULT_RECIPES, MachineConfig, MachineMode, MachineStatus, Recipe
from .gcode import Program, parse_program, validate_program


class JobService:
    def __init__(
        self,
        controller: Controller,
        config: MachineConfig,
        log: Callable[[str], None],
        recipes: dict[int, Recipe] | None = None,
    ):
        self.controller = controller
        self.config = config
        self.log = log
        self.recipes = recipes if recipes is not None else DEFAULT_RECIPES
        self.program: Program | None = None
        self.step_index = 0
        self.running = False
        self.paused = False
        self.waiting_hole = False
        self.waiting_xy = False
        self.pause_requested = False
        self.single_block = False
        self.elapsed_s = 0.0
        self.current_hole_target_mm: float | None = None
        self.current_hole_number: int | None = None
        self.holes_completed_in_job = 0
        self._hole_count_before = 0
        self.last_status = MachineStatus()
        self._controller_exception: str | None = None

    def load(self, source: str) -> Program:
        if self.running or self.waiting_hole or self.waiting_xy or self.paused:
            raise RuntimeError("运行中不能更换程序")
        program = parse_program(source)
        validate_program(program, self.config, self.recipes)
        self.program = program
        self.step_index = 0
        self.paused = False
        self.pause_requested = False
        self.current_hole_target_mm = None
        self.current_hole_number = None
        self.waiting_xy = False
        self.holes_completed_in_job = 0
        self.log(f"已校验程序：{program.hole_count} 个孔")
        return program

    def update_config(self, config: MachineConfig) -> None:
        if self.running or self.waiting_hole or self.waiting_xy or self.paused:
            raise RuntimeError("运行中不能修改设备设置")
        status = self.controller.status()
        if (status.mode != MachineMode.MANUAL_Z or not status.xy_stationary
                or status.pulse_enabled or status.flush_enabled or status.rotation_enabled):
            raise RuntimeError("修改设置前请停止手动运动和辅助输出")
        if self.program is not None:
            validate_program(self.program, config, self.recipes)
        self.controller.apply_config(config)
        self.config = config
        self.log("设备设置已应用；请重新确认工件表面 Z0")

    def start(self) -> None:
        if self._controller_exception:
            raise RuntimeError("控制器故障尚未复位")
        if self.program is None:
            raise RuntimeError("请先校验并加载 G 代码")
        if self.running or self.waiting_hole or self.waiting_xy or self.paused:
            raise RuntimeError("程序正在运行")
        status = self.controller.status()
        if status.mode != MachineMode.MANUAL_Z or not status.xy_homed or not status.homed or not status.surface_set:
            raise RuntimeError("请先完成 XY/Z 回零并确认工件表面 Z0")
        if not status.xy_stationary:
            raise RuntimeError("XY 尚未停稳")
        if status.pulse_enabled or status.flush_enabled or status.rotation_enabled:
            raise RuntimeError("启动自动作业前请关闭手动辅助输出")
        self.step_index = 0
        self.running = True
        self.paused = False
        self.pause_requested = False
        self.elapsed_s = 0.0
        self.current_hole_target_mm = None
        self.current_hole_number = None
        self.holes_completed_in_job = 0
        self.waiting_xy = False
        self.log("作业开始")

    def request_pause(self) -> None:
        """当前孔完成退刀后暂停；没有孔在运行时立即暂停。"""
        if not self.running:
            raise RuntimeError("作业未运行")
        if self.waiting_hole or self.waiting_xy:
            self.pause_requested = True
            self.log("已请求暂停；将在当前动作安全结束后暂停")
        else:
            self.running = False
            self.paused = True
            self.log("作业已暂停")

    def resume(self) -> None:
        if not self.paused:
            raise RuntimeError("程序没有处于暂停状态")
        if self.controller.status().mode != MachineMode.MANUAL_Z:
            raise RuntimeError("控制器尚未回到手动模式")
        self.paused = False
        self.running = True
        self.pause_requested = False
        self.log("作业继续")

    def stop(self) -> None:
        self.running = False
        self.paused = False
        self.waiting_hole = False
        self.waiting_xy = False
        self.pause_requested = False
        self.current_hole_target_mm = None
        self.current_hole_number = None
        self.controller.stop()
        self.log("作业已请求停止")

    def emergency_stop(self) -> None:
        self.running = False
        self.paused = False
        self.waiting_hole = False
        self.waiting_xy = False
        self.pause_requested = False
        self.current_hole_target_mm = None
        self.current_hole_number = None
        self.controller.emergency_stop()
        self.log("急停触发")

    def reset_fault(self) -> None:
        """控制器复位成功后，解除一次通信异常造成的作业锁定。"""
        self.controller.reset_fault()
        try:
            status = self.controller.status()
        except Exception as exc:
            self._controller_failed(exc)
        self._controller_exception = None
        self.last_status = status
        self.log("故障已复位；请重新回零并确认工件表面 Z0")

    def _controller_failed(self, exc: Exception) -> None:
        """轮询异常时只处理一次，避免界面定时器反复发送急停。"""
        message = f"控制器通信或状态更新失败：{exc}"
        self.running = False
        self.paused = False
        self.waiting_hole = False
        self.waiting_xy = False
        self.pause_requested = False
        self.current_hole_target_mm = None
        self.current_hole_number = None
        try:
            self.controller.emergency_stop()
        except Exception as stop_exc:
            message += f"；急停请求失败：{stop_exc}"
        self._controller_exception = message
        self.last_status = MachineStatus(
            mode=MachineMode.FAULT, x_mm=math.nan, y_mm=math.nan, z_mm=math.nan,
            fault=message,
        )
        self.log(f"作业中止：{message}")
        raise RuntimeError(message) from exc

    def tick(self, elapsed_s: float) -> None:
        if self._controller_exception:
            return
        if self.running:
            self.elapsed_s += max(0.0, elapsed_s)
        try:
            self.controller.tick(elapsed_s)
            status = self.controller.status()
        except Exception as exc:
            self._controller_failed(exc)
        self.last_status = status
        if status.mode == MachineMode.FAULT:
            if self.running or self.waiting_hole or self.waiting_xy:
                self.log(f"作业因故障中止：{status.fault}")
            self.running = False
            self.waiting_hole = False
            self.waiting_xy = False
            self.paused = False
            self.current_hole_target_mm = None
            self.current_hole_number = None
            return
        if self.waiting_xy:
            try:
                xy_in_position = self.controller.xy_in_position
            except Exception as exc:
                self._controller_failed(exc)
            if not xy_in_position:
                return
            self.waiting_xy = False
            self.log("XY 已到位")
            if self.pause_requested:
                self.pause_requested = False
                self.running = False
                self.paused = True
                self.log("XY 定位完成，作业暂停")
                return
        if self.waiting_hole:
            try:
                completed_holes = self.controller.completed_holes
            except Exception as exc:
                self._controller_failed(exc)
            if completed_holes == self._hole_count_before:
                return
            if status.mode != MachineMode.MANUAL_Z:
                return
            self.waiting_hole = False
            self.current_hole_target_mm = None
            self.current_hole_number = None
            self.holes_completed_in_job += 1
            self.log("单孔完成并已退刀")
            if self.pause_requested or self.single_block:
                self.pause_requested = False
                self.running = False
                self.paused = True
                self.log("单孔结束，作业暂停")
                return
        if not self.running or self.program is None:
            return
        # 一次 tick 最多走到下一次穿孔或暂停，防止 UI 事件循环被大程序占满。
        for _ in range(100):
            if self.step_index >= len(self.program.steps):
                self.running = False
                return
            step = self.program.steps[self.step_index]
            self.step_index += 1
            try:
                if step.kind == "move_xy":
                    assert step.x_mm is not None and step.y_mm is not None
                    self.controller.move_xy(step.x_mm, step.y_mm)
                    self.log(f"第 {step.line} 行：定位 X{step.x_mm:g} Y{step.y_mm:g}")
                    if not self.controller.xy_in_position:
                        self.waiting_xy = True
                        return
                elif step.kind == "hole":
                    assert step.recipe_id is not None and step.depth_mm is not None
                    self._hole_count_before = self.controller.completed_holes
                    self.controller.arm_hole(step.recipe_id, step.depth_mm)
                    self.controller.start_hole()
                    self.current_hole_target_mm = step.depth_mm
                    self.current_hole_number = self.holes_completed_in_job + 1
                    self.waiting_hole = True
                    self.log(f"第 {step.line} 行：穿孔 P{step.recipe_id} D{step.depth_mm:g}")
                    return
                elif step.kind == "pause":
                    self.running = False
                    self.paused = True
                    self.current_hole_target_mm = None
                    self.current_hole_number = None
                    self.log(f"第 {step.line} 行：M0 暂停")
                    return
                elif step.kind == "end":
                    self.running = False
                    self.current_hole_target_mm = None
                    self.current_hole_number = None
                    self.log("作业完成")
                    return
            except Exception as exc:
                self.running = False
                self.waiting_hole = False
                self.waiting_xy = False
                self.current_hole_target_mm = None
                self.current_hole_number = None
                try:
                    self.controller.stop()
                except Exception as stop_exc:
                    self._controller_failed(stop_exc)
                self.log(f"第 {step.line} 行执行失败：{exc}")
                raise
