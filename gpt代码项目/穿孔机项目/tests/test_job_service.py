"""作业与设备状态测试：穿孔、退刀、暂停、反馈设置切换。"""

from dataclasses import replace
from pathlib import Path

import pytest

from edm_drill.domain import FeedbackMode, MachineConfig, MachineMode
from edm_drill.job_service import JobService
from edm_drill.simulator import SimulatedController


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "three_holes.ngc"


def _make_job() -> tuple[JobService, SimulatedController, list[str]]:
    config = MachineConfig()
    controller = SimulatedController(config)
    events: list[str] = []
    job = JobService(controller, config, events.append)
    job.load(EXAMPLE.read_text(encoding="utf-8"))
    controller.home_z()
    controller.home_xy()
    controller.set_surface_zero()
    return job, controller, events


def test_full_program_pauses_and_resumes_after_two_holes() -> None:
    job, controller, events = _make_job()
    job.start()
    for _ in range(400):
        job.tick(0.1)
        if job.paused:
            break
    assert job.paused
    assert controller.completed_holes == 2
    assert controller.status().mode == MachineMode.MANUAL_Z
    job.resume()
    for _ in range(200):
        job.tick(0.1)
        if not job.running and not job.waiting_hole:
            break
    assert controller.completed_holes == 3
    assert events[-1] == "作业完成"


def test_manual_jog_and_feedback_change_are_locked_during_edm() -> None:
    job, controller, _ = _make_job()
    job.start()
    job.tick(0.1)
    assert controller.status().mode == MachineMode.EDM_Z
    with pytest.raises(RuntimeError):
        controller.jog_z(1)
    new_config = replace(
        job.config,
        feedback=replace(job.config.feedback, mode=FeedbackMode.DUAL),
    )
    with pytest.raises(RuntimeError):
        job.update_config(new_config)
    job.stop()
    for _ in range(30):
        job.tick(0.1)
    assert controller.status().mode == MachineMode.MANUAL_Z


def test_emergency_stop_requires_reset_and_new_home() -> None:
    job, controller, _ = _make_job()
    job.start()
    job.tick(0.1)
    job.emergency_stop()
    assert controller.status().mode == MachineMode.FAULT
    assert not controller.status().pulse_enabled
    controller.reset_fault()
    assert not controller.status().homed
    with pytest.raises(RuntimeError, match="回零"):
        job.start()


def test_pre_work_rapid_z_move_requires_new_surface_confirmation() -> None:
    job, controller, _ = _make_job()
    controller.move_z_absolute(3.0)
    assert controller.status().z_mm == 3.0
    assert not controller.status().surface_set
    with pytest.raises(RuntimeError, match="工件表面"):
        job.start()
    with pytest.raises(RuntimeError, match="软限位"):
        controller.move_z_absolute(100.0)


def test_pause_request_finishes_current_hole_before_pausing() -> None:
    job, controller, _ = _make_job()
    job.start()
    job.tick(0.1)
    job.request_pause()
    assert job.running and job.waiting_hole
    for _ in range(100):
        job.tick(0.1)
        if job.paused:
            break
    assert job.paused
    assert controller.completed_holes == 1
    assert controller.status().mode == MachineMode.MANUAL_Z


def test_single_block_pauses_after_every_completed_hole() -> None:
    job, controller, _ = _make_job()
    job.single_block = True
    job.start()
    for _ in range(100):
        job.tick(0.1)
        if job.paused:
            break
    assert job.paused
    assert job.holes_completed_in_job == 1
    job.resume()
    for _ in range(100):
        job.tick(0.1)
        if job.paused:
            break
    assert job.holes_completed_in_job == 2


def test_controller_poll_exception_stops_job_once_and_requires_reset() -> None:
    class FailingController(SimulatedController):
        def __init__(self, config: MachineConfig):
            super().__init__(config)
            self.emergency_calls = 0

        def tick(self, elapsed_s: float) -> None:
            raise OSError("下位机通信中断")

        def emergency_stop(self) -> None:
            self.emergency_calls += 1
            super().emergency_stop()

    config = MachineConfig()
    controller = FailingController(config)
    controller.home_z()
    controller.home_xy()
    controller.set_surface_zero()
    job = JobService(controller, config, lambda _: None)
    job.load(EXAMPLE.read_text(encoding="utf-8"))
    job.start()

    with pytest.raises(RuntimeError, match="通信中断"):
        job.tick(0.1)
    assert not job.running and not job.waiting_xy and not job.waiting_hole
    assert job.last_status.mode == MachineMode.FAULT
    assert controller.emergency_calls == 1
    job.tick(0.1)
    assert controller.emergency_calls == 1
    with pytest.raises(RuntimeError, match="尚未复位"):
        job.start()

    job.reset_fault()
    assert controller.status().mode == MachineMode.MANUAL_Z
    assert not controller.status().homed


def test_xy_position_read_exception_emergency_stops_waiting_job() -> None:
    class PositionFailingController(SimulatedController):
        def __init__(self, config: MachineConfig):
            super().__init__(config)
            self.position_reads = 0

        @property
        def xy_in_position(self) -> bool:
            self.position_reads += 1
            if self.position_reads == 1:
                return False
            raise OSError("XY 到位信号丢失")

    config = MachineConfig()
    controller = PositionFailingController(config)
    controller.home_z()
    controller.home_xy()
    controller.set_surface_zero()
    job = JobService(controller, config, lambda _: None)
    job.load(EXAMPLE.read_text(encoding="utf-8"))
    job.start()
    job.tick(0.1)
    assert job.waiting_xy
    with pytest.raises(RuntimeError, match="到位信号丢失"):
        job.tick(0.1)
    assert not job.running and not job.waiting_xy
    assert controller.status().mode == MachineMode.FAULT
