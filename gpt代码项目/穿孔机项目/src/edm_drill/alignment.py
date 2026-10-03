"""铜管碰边找中的纯计算逻辑，不读取或改变 G54 工作坐标系。

触碰值是铜管中心的当前 G54 工作坐标。同一次找中的全部触碰必须
使用同一个 G54 基准；写入新的 G54 后应清空触碰记录，重新测量。
X-/Y- 是工件负方向外侧边缘，
因此该边缘坐标等于触碰坐标加铜管半径；X+/Y+ 则减去半径。
附加补偿是有符号的目标坐标修正值，在半径补偿及找中后相加。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import TypeVar


class AlignmentError(ValueError):
    """找中输入、触碰记录或几何关系无效。"""


class Axis(str, Enum):
    X = "X"
    Y = "Y"


class TouchEdge(str, Enum):
    X_MINUS = "X-"
    X_PLUS = "X+"
    Y_MINUS = "Y-"
    Y_PLUS = "Y+"


class ReferenceMode(str, Enum):
    """单边选边缘作为基准；CENTER 使用该轴的两个相对边缘。"""

    MINUS = "minus"
    PLUS = "plus"
    CENTER = "center"


@dataclass(frozen=True)
class TouchPoint:
    """碰边瞬间铜管中心的 G54 工作坐标，单位 mm。"""

    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class AlignmentResult:
    """已加铜管半径及附加补偿的 XY 目标 G54 工作坐标。"""

    x_mm: float
    y_mm: float
    x_reference: ReferenceMode
    y_reference: ReferenceMode
    x_compensation_mm: float
    y_compensation_mm: float


_EnumT = TypeVar("_EnumT", bound=Enum)


def _enum(value: _EnumT | str, enum_type: type[_EnumT], name: str) -> _EnumT:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise AlignmentError(f"{name}无效：{value!r}") from exc


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AlignmentError(f"{name}必须为有限数")
    try:
        number = float(value)
    except OverflowError as exc:
        raise AlignmentError(f"{name}必须为有限数") from exc
    if not math.isfinite(number):
        raise AlignmentError(f"{name}必须为有限数")
    return number


class AlignmentSession:
    """保存同一 G54 基准下的触碰记录；G54 改变后须 ``clear_all``。"""

    def __init__(self, tube_outer_diameter_mm: float) -> None:
        diameter = _finite(tube_outer_diameter_mm, "铜管外径")
        if diameter <= 0:
            raise AlignmentError("铜管外径必须大于 0")
        self._tube_outer_diameter_mm = diameter
        self._touches: dict[TouchEdge, TouchPoint] = {}

    @property
    def tube_outer_diameter_mm(self) -> float:
        return self._tube_outer_diameter_mm

    @property
    def touches(self) -> dict[TouchEdge, TouchPoint]:
        """返回记录副本，避免调用方绕过重复碰边检查。"""

        return self._touches.copy()

    def record_touch(
        self, edge: TouchEdge | str, *, x_mm: float, y_mm: float
    ) -> TouchPoint:
        """记录碰边时铜管中心的 G54 工作坐标；重复记录须先清除。"""

        selected_edge = _enum(edge, TouchEdge, "触碰边缘")
        x = _finite(x_mm, "触碰 X 坐标")
        y = _finite(y_mm, "触碰 Y 坐标")
        if selected_edge in self._touches:
            raise AlignmentError(f"{selected_edge.value} 已记录；请先清除后重测")
        point = TouchPoint(x, y)
        self._touches[selected_edge] = point
        return point

    def clear_touch(self, edge: TouchEdge | str) -> None:
        """清除指定边缘，供重新测量；尚无记录时也可调用。"""

        self._touches.pop(_enum(edge, TouchEdge, "触碰边缘"), None)

    def clear_all(self) -> None:
        self._touches.clear()

    def edge_coordinate(self, edge: TouchEdge | str) -> float:
        """把触碰时的铜管中心坐标换算成工件实际边缘坐标。"""

        selected_edge = _enum(edge, TouchEdge, "触碰边缘")
        point = self._touches.get(selected_edge)
        if point is None:
            raise AlignmentError(f"缺少 {selected_edge.value} 触碰记录")
        measured = point.x_mm if selected_edge in (TouchEdge.X_MINUS, TouchEdge.X_PLUS) else point.y_mm
        radius = self._tube_outer_diameter_mm / 2
        correction = radius if selected_edge in (TouchEdge.X_MINUS, TouchEdge.Y_MINUS) else -radius
        return _finite(measured + correction, f"{selected_edge.value} 边缘坐标")

    def calculate_axis(
        self,
        axis: Axis | str,
        reference: ReferenceMode | str,
        compensation_mm: float = 0.0,
    ) -> float:
        """计算单轴基准位置；可独立于另一轴使用。

        MINUS/PLUS 使用各自的实际工件边缘，CENTER 使用对边中点。
        ``compensation_mm`` 可正可负，最后叠加到计算出的坐标。
        """

        selected_axis = _enum(axis, Axis, "坐标轴")
        selected_reference = _enum(reference, ReferenceMode, "找中方式")
        compensation = _finite(compensation_mm, f"{selected_axis.value} 附加补偿")
        minus = TouchEdge(f"{selected_axis.value}-")
        plus = TouchEdge(f"{selected_axis.value}+")
        if selected_reference is ReferenceMode.MINUS:
            base = self.edge_coordinate(minus)
        elif selected_reference is ReferenceMode.PLUS:
            base = self.edge_coordinate(plus)
        else:
            lower = self.edge_coordinate(minus)
            upper = self.edge_coordinate(plus)
            if upper <= lower:
                raise AlignmentError(f"{selected_axis.value} 对边顺序错误或有效宽度不大于 0")
            # 分别除以 2，避免两个很大的有限坐标相加时溢出。
            base = lower / 2 + upper / 2
        return _finite(base + compensation, f"{selected_axis.value} 找中坐标")

    def calculate(
        self,
        *,
        x_reference: ReferenceMode | str,
        y_reference: ReferenceMode | str,
        x_compensation_mm: float = 0.0,
        y_compensation_mm: float = 0.0,
    ) -> AlignmentResult:
        """计算 XY 目标 G54 工作坐标；不执行移动、回零或 G54 写入。"""

        x_mode = _enum(x_reference, ReferenceMode, "X 找中方式")
        y_mode = _enum(y_reference, ReferenceMode, "Y 找中方式")
        x_compensation = _finite(x_compensation_mm, "X 附加补偿")
        y_compensation = _finite(y_compensation_mm, "Y 附加补偿")
        x = self.calculate_axis(Axis.X, x_mode, x_compensation)
        y = self.calculate_axis(Axis.Y, y_mode, y_compensation)
        return AlignmentResult(x, y, x_mode, y_mode, x_compensation, y_compensation)
