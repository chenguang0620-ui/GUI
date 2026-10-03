"""铜管外径补偿、单边基准和对边找中计算。"""

import math

import pytest

from edm_drill.alignment import (
    AlignmentError,
    AlignmentSession,
    Axis,
    ReferenceMode,
    TouchEdge,
)


def _four_edges() -> AlignmentSession:
    session = AlignmentSession(tube_outer_diameter_mm=2.0)
    # 所有读数都是碰边时铜管中心的机床坐标；非目标轴取不同值，
    # 确认单轴计算不会误用另一个坐标分量。
    session.record_touch(TouchEdge.X_MINUS, x_mm=8.0, y_mm=101.0)
    session.record_touch(TouchEdge.X_PLUS, x_mm=22.0, y_mm=102.0)
    session.record_touch(TouchEdge.Y_MINUS, x_mm=103.0, y_mm=-6.0)
    session.record_touch(TouchEdge.Y_PLUS, x_mm=104.0, y_mm=6.0)
    return session


def test_every_touch_uses_tube_radius_in_correct_direction() -> None:
    session = _four_edges()
    assert session.edge_coordinate(TouchEdge.X_MINUS) == pytest.approx(9.0)
    assert session.edge_coordinate(TouchEdge.X_PLUS) == pytest.approx(21.0)
    assert session.edge_coordinate(TouchEdge.Y_MINUS) == pytest.approx(-5.0)
    assert session.edge_coordinate(TouchEdge.Y_PLUS) == pytest.approx(5.0)


def test_single_edge_reference_and_signed_extra_compensation() -> None:
    session = _four_edges()
    result = session.calculate(
        x_reference=ReferenceMode.MINUS,
        y_reference=ReferenceMode.PLUS,
        x_compensation_mm=-0.25,
        y_compensation_mm=1.5,
    )
    assert result.x_mm == pytest.approx(8.75)
    assert result.y_mm == pytest.approx(6.5)
    assert result.x_reference is ReferenceMode.MINUS
    assert result.y_reference is ReferenceMode.PLUS
    assert result.x_compensation_mm == pytest.approx(-0.25)
    assert result.y_compensation_mm == pytest.approx(1.5)


def test_opposite_edges_find_center_then_apply_independent_xy_compensation() -> None:
    session = _four_edges()
    result = session.calculate(
        x_reference=ReferenceMode.CENTER,
        y_reference=ReferenceMode.CENTER,
        x_compensation_mm=0.25,
        y_compensation_mm=-1.5,
    )
    assert result.x_mm == pytest.approx(15.25)
    assert result.y_mm == pytest.approx(-1.5)


def test_each_axis_can_be_calculated_before_the_other_axis_is_touched() -> None:
    session = AlignmentSession(1.0)
    session.record_touch("X-", x_mm=12.0, y_mm=99.0)
    assert session.calculate_axis("X", "minus", -0.1) == pytest.approx(12.4)
    with pytest.raises(AlignmentError, match="X\\+ 触碰"):
        session.calculate_axis(Axis.X, ReferenceMode.CENTER)
    with pytest.raises(AlignmentError, match="Y- 触碰"):
        session.calculate_axis(Axis.Y, ReferenceMode.MINUS)


def test_duplicate_touch_requires_explicit_clear_before_remeasurement() -> None:
    session = AlignmentSession(2.0)
    session.record_touch(TouchEdge.X_MINUS, x_mm=8.0, y_mm=0.0)
    with pytest.raises(AlignmentError, match="已记录"):
        session.record_touch(TouchEdge.X_MINUS, x_mm=9.0, y_mm=0.0)
    assert session.edge_coordinate(TouchEdge.X_MINUS) == pytest.approx(9.0)
    session.clear_touch(TouchEdge.X_MINUS)
    session.record_touch(TouchEdge.X_MINUS, x_mm=9.0, y_mm=0.0)
    assert session.edge_coordinate(TouchEdge.X_MINUS) == pytest.approx(10.0)
    session.clear_all()
    with pytest.raises(AlignmentError, match="缺少 X- 触碰"):
        session.edge_coordinate(TouchEdge.X_MINUS)


def test_touch_dictionary_is_not_mutable_from_outside() -> None:
    session = _four_edges()
    copied = session.touches
    copied.clear()
    assert len(session.touches) == 4


def test_reversed_or_zero_workpiece_width_is_rejected_for_center_mode() -> None:
    session = AlignmentSession(2.0)
    session.record_touch(TouchEdge.X_MINUS, x_mm=10.0, y_mm=0.0)
    session.record_touch(TouchEdge.X_PLUS, x_mm=11.0, y_mm=0.0)
    with pytest.raises(AlignmentError, match="有效宽度"):
        session.calculate_axis(Axis.X, ReferenceMode.CENTER)
    # 单边基准仍可独立求值。
    assert session.calculate_axis(Axis.X, ReferenceMode.MINUS) == pytest.approx(11.0)


@pytest.mark.parametrize("diameter", [0, -1, True, "2", math.nan, math.inf, -math.inf, 10**400])
def test_invalid_tube_diameter_is_rejected(diameter: object) -> None:
    with pytest.raises(AlignmentError, match="铜管外径"):
        AlignmentSession(diameter)  # type: ignore[arg-type]


@pytest.mark.parametrize("coordinate", [True, "1", math.nan, math.inf, -math.inf, 10**400])
def test_nonfinite_or_nonnumeric_touch_coordinate_is_rejected(coordinate: object) -> None:
    session = AlignmentSession(1.0)
    with pytest.raises(AlignmentError, match="触碰 X 坐标"):
        session.record_touch(TouchEdge.X_MINUS, x_mm=coordinate, y_mm=0.0)  # type: ignore[arg-type]
    with pytest.raises(AlignmentError, match="触碰 Y 坐标"):
        session.record_touch(TouchEdge.X_MINUS, x_mm=0.0, y_mm=coordinate)  # type: ignore[arg-type]
    assert not session.touches


@pytest.mark.parametrize("compensation", [True, "1", math.nan, math.inf, -math.inf, 10**400])
def test_nonfinite_or_nonnumeric_compensation_is_rejected(compensation: object) -> None:
    session = _four_edges()
    with pytest.raises(AlignmentError, match="附加补偿"):
        session.calculate_axis(Axis.X, ReferenceMode.CENTER, compensation)  # type: ignore[arg-type]
    with pytest.raises(AlignmentError, match="附加补偿"):
        session.calculate(
            x_reference=ReferenceMode.CENTER,
            y_reference=ReferenceMode.CENTER,
            y_compensation_mm=compensation,  # type: ignore[arg-type]
        )


def test_invalid_edge_axis_or_reference_is_rejected() -> None:
    session = _four_edges()
    with pytest.raises(AlignmentError, match="触碰边缘无效"):
        session.record_touch("Z-", x_mm=0.0, y_mm=0.0)
    with pytest.raises(AlignmentError, match="坐标轴无效"):
        session.calculate_axis("Z", ReferenceMode.MINUS)
    with pytest.raises(AlignmentError, match="找中方式无效"):
        session.calculate_axis(Axis.X, "left")


def test_calculated_coordinate_cannot_overflow_to_infinity() -> None:
    session = AlignmentSession(2.0)
    session.record_touch(TouchEdge.X_MINUS, x_mm=1e308, y_mm=0.0)
    with pytest.raises(AlignmentError, match="找中坐标"):
        session.calculate_axis(Axis.X, ReferenceMode.MINUS, 1e308)
