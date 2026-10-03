"""手动轴运动和辅助输出在回零、放电及自动作业之间的联锁。"""

from pathlib import Path

import pytest

from edm_drill.domain import MachineConfig, MachineMode
from edm_drill.job_service import JobService
from edm_drill.manual_service import ManualService
from edm_drill.simulator import SimulatedController


def _manual() -> tuple[ManualService, SimulatedController]:
    config = MachineConfig()
    controller = SimulatedController(config)
    return ManualService(JobService(controller, config, lambda _: None)), controller


def test_xy_can_be_manually_positioned_before_surface_zero() -> None:
    manual, controller = _manual()
    with pytest.raises(RuntimeError, match="Z"):
        manual.home_xy()
    manual.home_z()
    manual.home_xy()
    manual.jog_xy(0.05, 0)
    manual.move_xy(20, 15)
    assert (controller.status().x_mm, controller.status().y_mm) == (20, 15)
    assert not controller.status().surface_set
    manual.jog_z(-0.05)
    assert controller.status().z_mm == pytest.approx(-0.05)
    with pytest.raises(RuntimeError, match="抬至"):
        manual.move_xy(21, 15)
    manual.jog_xy(0.05, 0)
    assert controller.status().x_mm == pytest.approx(20.05)


def test_manual_pulse_requires_flush_and_z0_and_stop_closes_outputs() -> None:
    manual, controller = _manual()
    manual.home_z()
    manual.home_xy()
    with pytest.raises(RuntimeError, match="Z0"):
        manual.set_pulse(True)
    manual.set_surface_zero()
    with pytest.raises(RuntimeError, match="冲液"):
        manual.set_pulse(True)
    manual.set_flush(True)
    manual.set_rotation(True)
    manual.set_pulse(True)
    assert controller.status().pulse_enabled
    with pytest.raises(RuntimeError, match="关闭手动放电"):
        manual.jog_xy(0.05, 0)
    manual.stop_motion()
    status = controller.status()
    assert not status.pulse_enabled and not status.flush_enabled and not status.rotation_enabled


def test_automatic_job_locks_manual_commands() -> None:
    manual, controller = _manual()
    manual.home_z()
    manual.home_xy()
    manual.set_surface_zero()
    program = Path(__file__).resolve().parents[1] / "examples" / "three_holes.ngc"
    manual.job.load(program.read_text(encoding="utf-8"))
    manual.job.start()
    with pytest.raises(RuntimeError, match="作业运行"):
        manual.jog_xy(0.05, 0)
    with pytest.raises(RuntimeError, match="作业运行"):
        manual.set_flush(True)
    manual.job.emergency_stop()
    assert controller.status().mode == MachineMode.FAULT
    assert not controller.status().pulse_enabled
