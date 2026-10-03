"""各功能共用的数据结构；不依赖 PyQt 或通信实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math


def _require_finite_number(value: object, name: str) -> None:
    """拒绝配置中的非数字、布尔值、NaN 和无穷大。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}必须为有限数")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{name}必须为有限数")


class FeedbackMode(str, Enum):
    ENCODER = "encoder"
    SCALE = "scale"
    DUAL = "dual"


class MachineMode(str, Enum):
    IDLE = "idle"
    MANUAL_Z = "manual_z"
    ARMED = "armed"
    EDM_Z = "edm_z"
    RETRACT = "retract"
    FAULT = "fault"


@dataclass(frozen=True)
class FeedbackConfig:
    """位置反馈配置。分辨率是每个有效计数代表的毫米数。"""

    mode: FeedbackMode = FeedbackMode.SCALE
    scale_mm_per_count: float = 0.005  # 5 µm，后续可按实测修改
    encoder_counts_per_rev: int | None = None
    screw_pitch_mm: float | None = None
    scale_direction: int = 1
    encoder_direction: int = 1
    max_disagreement_mm: float = 0.10

    def validate(self, *, require_hardware: bool = False) -> None:
        for name, value in (
            ("光栅尺分辨率", self.scale_mm_per_count),
            ("双反馈允许偏差", self.max_disagreement_mm),
        ):
            _require_finite_number(value, name)
        if self.screw_pitch_mm is not None:
            _require_finite_number(self.screw_pitch_mm, "丝杠导程")
        if self.scale_mm_per_count <= 0:
            raise ValueError("光栅尺分辨率必须大于 0")
        if self.max_disagreement_mm <= 0:
            raise ValueError("双反馈允许偏差必须大于 0")
        if any(type(direction) is not int or direction not in (-1, 1)
               for direction in (self.scale_direction, self.encoder_direction)):
            raise ValueError("传感器方向只能为 +1 或 -1")
        if self.encoder_counts_per_rev is not None:
            if type(self.encoder_counts_per_rev) is not int or self.encoder_counts_per_rev <= 0:
                raise ValueError("编码器每转计数必须为正整数")
        if self.screw_pitch_mm is not None and self.screw_pitch_mm <= 0:
            raise ValueError("丝杠导程必须大于 0")
        if require_hardware and self.mode in (FeedbackMode.ENCODER, FeedbackMode.DUAL):
            if not self.encoder_counts_per_rev or not self.screw_pitch_mm:
                raise ValueError("编码器或双闭环模式需要编码器每转计数和丝杠导程")


@dataclass(frozen=True)
class MachineConfig:
    feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
    x_min_mm: float = 0.0
    x_max_mm: float = 200.0
    y_min_mm: float = 0.0
    y_max_mm: float = 200.0
    z_min_mm: float = -50.0
    z_max_mm: float = 20.0
    manual_speed_mm_s: float = 5.0
    edm_feed_mm_s: float = 0.5  # 仅供仿真；实机由间隙控制决定
    max_hole_depth_mm: float = 30.0

    def validate(self, *, require_hardware: bool = False) -> None:
        self.feedback.validate(require_hardware=require_hardware)
        for name, value in (
            ("X 下限", self.x_min_mm), ("X 上限", self.x_max_mm),
            ("Y 下限", self.y_min_mm), ("Y 上限", self.y_max_mm),
            ("Z 下限", self.z_min_mm), ("Z 上限", self.z_max_mm),
            ("手动速度", self.manual_speed_mm_s), ("仿真进给速度", self.edm_feed_mm_s),
            ("最大穿孔深度", self.max_hole_depth_mm),
        ):
            _require_finite_number(value, name)
        if not (self.x_min_mm < self.x_max_mm and self.y_min_mm < self.y_max_mm):
            raise ValueError("XY 行程上下限无效")
        if not self.z_min_mm < 0 < self.z_max_mm:
            raise ValueError("Z 行程必须跨越工件表面 Z0")
        if self.manual_speed_mm_s <= 0 or self.edm_feed_mm_s <= 0:
            raise ValueError("运动速度必须大于 0")
        if not 0 < self.max_hole_depth_mm <= -self.z_min_mm:
            raise ValueError("最大穿孔深度超出 Z 行程")


@dataclass(frozen=True)
class Recipe:
    """工艺配方占位数据；放电参数须在下位机协议确定后增加。"""

    recipe_id: int
    name: str
    electrode_diameter_mm: float


DEFAULT_RECIPES = {
    1: Recipe(1, "演示配方 1", 0.5),
    2: Recipe(2, "演示配方 2", 1.0),
}


@dataclass(frozen=True)
class MachineStatus:
    mode: MachineMode = MachineMode.IDLE
    x_mm: float = 0.0
    y_mm: float = 0.0
    z_mm: float = 0.0
    xy_homed: bool = False
    xy_stationary: bool = True
    homed: bool = False
    surface_set: bool = False
    pulse_enabled: bool = False
    flush_enabled: bool = False
    rotation_enabled: bool = False
    g54_offset_x_mm: float = 0.0
    g54_offset_y_mm: float = 0.0
    encoder_ok: bool = True
    scale_ok: bool = True
    encoder_mm: float = 0.0
    scale_mm: float = 0.0
    fault: str = ""
    active_recipe: int | None = None
