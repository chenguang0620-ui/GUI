"""用仿真控制器验证人工找中、G54 写入及操作互锁。"""

from dataclasses import replace
from pathlib import Path

import pytest

from edm_drill.alignment import AlignmentError, Axis, ReferenceMode, TouchEdge
from edm_drill.alignment_service import AlignmentService
from edm_drill.domain import MachineConfig, MachineStatus
from edm_drill.job_service import JobService
from edm_drill.simulator import SimulatedController


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "three_holes.ngc"


def _setup(
    controller_type: type[SimulatedController] = SimulatedController,
) -> tuple[AlignmentService, JobService, SimulatedController, list[str]]:
    config = MachineConfig()
    controller = controller_type(config)
    controller.home_xy()
    controller.home_z()
    events: list[str] = []
    job = JobService(controller, config, events.append)
    service = AlignmentService(job, tube_outer_diameter_mm=2.0)
    return service, job, controller, events


def _capture_at(
    service: AlignmentService,
    controller: SimulatedController,
    edge: TouchEdge,
    x_mm: float,
    y_mm: float,
) -> None:
    controller.manual_move_xy(x_mm, y_mm)
    service.capture(edge)


def test_manual_four_edge_capture_finds_centers_with_signed_compensation() -> None:
    service, _, controller, events = _setup()
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    _capture_at(service, controller, TouchEdge.X_PLUS, 22.0, 30.0)
    _capture_at(service, controller, TouchEdge.Y_MINUS, 22.0, 28.0)
    _capture_at(service, controller, TouchEdge.Y_PLUS, 22.0, 42.0)

    assert len(service.session.touches) == 4
    assert service.preview_axis(Axis.X, ReferenceMode.CENTER, 0.25) == pytest.approx(15.25)
    assert service.preview_axis(Axis.Y, ReferenceMode.CENTER, -0.5) == pytest.approx(34.5)
    assert sum("人工记录" in event for event in events) == 4


def test_single_edge_uses_copper_tube_radius_before_extra_compensation() -> None:
    service, _, controller, _ = _setup()
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    _capture_at(service, controller, TouchEdge.Y_PLUS, 8.0, 42.0)

    # 外径 2 mm：负侧加半径，正侧减半径。
    assert service.preview_axis(Axis.X, ReferenceMode.MINUS) == pytest.approx(9.0)
    assert service.preview_axis(Axis.Y, ReferenceMode.PLUS) == pytest.approx(41.0)
    assert service.preview_axis(Axis.X, ReferenceMode.MINUS, -0.25) == pytest.approx(8.75)
    assert service.preview_axis(Axis.Y, ReferenceMode.PLUS, 0.5) == pytest.approx(41.5)


def test_applying_one_g54_axis_preserves_other_and_clears_old_touches() -> None:
    service, _, controller, _ = _setup()
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    _capture_at(service, controller, TouchEdge.X_PLUS, 22.0, 30.0)
    _capture_at(service, controller, TouchEdge.Y_MINUS, 22.0, 28.0)
    _capture_at(service, controller, TouchEdge.Y_PLUS, 22.0, 42.0)
    before = controller.status()

    old_g54_origin = service.apply_axis(Axis.X, ReferenceMode.CENTER, 0.5)
    after = controller.status()
    assert old_g54_origin == pytest.approx(15.5)
    assert before.x_mm == pytest.approx(22.0)
    assert after.x_mm == pytest.approx(6.5)
    assert after.y_mm == pytest.approx(before.y_mm)
    assert after.g54_offset_x_mm == pytest.approx(15.5)
    assert after.g54_offset_y_mm == pytest.approx(before.g54_offset_y_mm)
    assert not service.session.touches

    # G54 已改变，旧 Y 触碰不能再使用；先在新的基准下重新测量。
    with pytest.raises(AlignmentError, match="缺少 Y- 触碰"):
        service.preview_axis(Axis.Y, ReferenceMode.CENTER)
    service.capture(TouchEdge.Y_PLUS)
    y_origin = service.apply_axis(Axis.Y, ReferenceMode.PLUS, -0.5)
    final = controller.status()
    assert y_origin == pytest.approx(40.5)
    assert final.y_mm == pytest.approx(1.5)
    assert final.x_mm == pytest.approx(after.x_mm)
    assert final.g54_offset_x_mm == pytest.approx(after.g54_offset_x_mm)
    assert final.g54_offset_y_mm == pytest.approx(40.5)
    assert not service.session.touches


def test_capture_and_apply_are_rejected_while_job_is_running() -> None:
    service, job, controller, _ = _setup()
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    controller.set_surface_zero()
    job.load(EXAMPLE.read_text(encoding="utf-8"))
    job.start()

    with pytest.raises(RuntimeError, match="作业运行"):
        service.capture(TouchEdge.X_PLUS)
    with pytest.raises(RuntimeError, match="作业运行"):
        service.apply_axis(Axis.X, ReferenceMode.MINUS)
    assert len(service.session.touches) == 1


class _MovingSimulatedController(SimulatedController):
    """沿用仿真设备状态与 G54 逻辑，仅延迟 XY 到位。"""

    moving = False

    @property
    def xy_in_position(self) -> bool:
        return not self.moving

    def status(self) -> MachineStatus:
        return replace(super().status(), xy_stationary=not self.moving)


def test_capture_and_apply_are_rejected_while_xy_is_moving() -> None:
    service, _, controller, _ = _setup(_MovingSimulatedController)
    assert isinstance(controller, _MovingSimulatedController)
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    controller.moving = True

    with pytest.raises(RuntimeError, match="XY 尚未停稳"):
        service.capture(TouchEdge.X_PLUS)
    with pytest.raises(RuntimeError, match="XY 尚未停稳"):
        service.apply_axis(Axis.X, ReferenceMode.MINUS)
    assert controller.status().g54_offset_x_mm == pytest.approx(0.0)


def test_capture_and_apply_are_rejected_during_edm_hole() -> None:
    service, _, controller, _ = _setup()
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    controller.set_surface_zero()
    controller.arm_hole(recipe_id=1, depth_mm=1.0)
    controller.start_hole()

    with pytest.raises(RuntimeError, match="手动模式"):
        service.capture(TouchEdge.X_PLUS)
    with pytest.raises(RuntimeError, match="手动模式"):
        service.apply_axis(Axis.X, ReferenceMode.MINUS)
    assert controller.status().g54_offset_x_mm == pytest.approx(0.0)


def test_manual_pulse_also_blocks_alignment_operations() -> None:
    service, _, controller, _ = _setup()
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    controller.set_surface_zero()
    controller.set_flush(True)
    controller.set_pulse(True)

    with pytest.raises(RuntimeError, match="关闭放电"):
        service.capture(TouchEdge.X_PLUS)
    with pytest.raises(RuntimeError, match="关闭放电"):
        service.apply_axis(Axis.X, ReferenceMode.MINUS)


def test_external_g54_change_invalidates_captured_edges() -> None:
    service, _, controller, _ = _setup()
    _capture_at(service, controller, TouchEdge.X_MINUS, 8.0, 30.0)
    controller.set_work_coordinates(x_mm=0.0)
    with pytest.raises(RuntimeError, match="G54 偏置已改变"):
        service.apply_axis(Axis.X, ReferenceMode.MINUS)
    assert not service.session.touches
