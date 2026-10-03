"""用模拟 LinuxCNC Python API 验证接口顺序；不需要安装机床软件。"""

from pathlib import Path
import math
import re

import pytest

from edm_drill.domain import MachineConfig, MachineMode
from edm_drill.job_service import JobService
from edm_drill.linuxcnc_adapter import LinuxCncController
from edm_drill.simulator import SimulatedController


class FakeStat:
    task_state = 4
    task_mode = 3
    homed = (1, 1)
    linear_units = 1.0
    g5x_index = 1
    rotation_xy = 0.0
    g5x_offset = (10.0, 20.0, 0.0)
    g92_offset = (0.0, 0.0, 0.0)
    tool_offset = (0.0, 0.0, 0.0)
    actual_position = (10.0, 20.0, 0.0)
    interp_state = 1
    motion_mode = 2
    inpos = True

    def poll(self):
        return None


class FakeCommand:
    def __init__(self, stat: FakeStat):
        self.stat = stat
        self.mdi_lines: list[str] = []
        self.mode_requests: list[int] = []
        self.home_requests: list[int] = []
        self.teleop_requests: list[int] = []
        self.jog_requests: list[tuple[int, bool, int, float, float]] = []
        self.aborted = False
        self.states: list[int] = []

    def mode(self, mode):
        self.mode_requested = mode
        self.mode_requests.append(mode)
        self.stat.task_mode = mode

    def wait_complete(self, timeout):
        return 1

    def mdi(self, command):
        self.mdi_lines.append(command)
        if command.startswith("G10 L20 P1"):
            # G10 L20 改 G54 读数，不移动机床；未指定的轴应保留原偏置。
            offsets = list(self.stat.g5x_offset)
            for axis, value in re.findall(r"\b([XY])(-?\d+(?:\.\d+)?)", command):
                index = 0 if axis == "X" else 1
                offsets[index] = self.stat.actual_position[index] - float(value)
            self.stat.g5x_offset = tuple(offsets)

    def home(self, joint):
        self.home_requests.append(joint)
        if joint == -1:
            self.stat.homed = (1, 1)

    def teleop_enable(self, enabled):
        self.teleop_requests.append(enabled)
        if enabled:
            self.stat.motion_mode = FakeLinuxCnc.TRAJ_MODE_TELEOP

    def jog(self, command, joint_mode, axis, velocity=None, distance=None):
        self.jog_requests.append((command, joint_mode, axis, velocity, distance))

    def abort(self):
        self.aborted = True

    def state(self, new_state):
        self.states.append(new_state)


class FakeErrors:
    def poll(self):
        return None


class FakeLinuxCnc:
    STATE_ON = 4
    STATE_ESTOP = 1
    MODE_MDI = 3
    MODE_MANUAL = 1
    TRAJ_MODE_TELEOP = 2
    JOG_INCREMENT = 7
    JOG_STOP = 8
    INTERP_IDLE = 1
    RCS_DONE = 1
    NML_ERROR = 10
    OPERATOR_ERROR = 11

    def __init__(self):
        self.fake_stat = FakeStat()
        self.fake_command = FakeCommand(self.fake_stat)

    def stat(self):
        return self.fake_stat

    def command(self):
        return self.fake_command

    def error_channel(self):
        return FakeErrors()


def _adapter() -> tuple[LinuxCncController, FakeLinuxCnc]:
    config = MachineConfig()
    z = SimulatedController(config)
    z.home_z()
    z.set_surface_zero()
    fake = FakeLinuxCnc()
    adapter = LinuxCncController(z, config, linuxcnc_module=fake, allow_simulated_z=True)
    return adapter, fake


def test_xy_mdi_waits_for_real_position_before_drilling() -> None:
    adapter, fake = _adapter()
    source = (Path(__file__).resolve().parents[1] / "examples" / "three_holes.ngc").read_text()
    job = JobService(adapter, MachineConfig(), lambda _: None)
    job.load(source)
    job.start()
    job.tick(0.1)
    assert job.waiting_xy
    assert adapter.status().mode == MachineMode.MANUAL_Z
    assert fake.fake_command.mdi_lines == ["G21 G90 G54 G0 X10.000 Y20.000"]
    assert " Z" not in fake.fake_command.mdi_lines[0]
    job.tick(0.1)
    assert not job.waiting_hole
    fake.fake_stat.actual_position = (20.0, 40.0, 0.0)  # 减去 G54 后为 X10 Y20
    job.tick(0.1)
    assert not job.waiting_xy
    assert job.waiting_hole
    assert adapter.status().mode == MachineMode.EDM_Z


def test_linuxcnc_rejects_unhomed_xy_and_wrong_coordinate_mode() -> None:
    adapter, fake = _adapter()
    fake.fake_stat.homed = (1, 0)
    with pytest.raises(RuntimeError, match="回零"):
        adapter.move_xy(10, 20)
    fake.fake_stat.homed = (1, 1)
    fake.fake_stat.g5x_index = 2
    with pytest.raises(RuntimeError, match="G54"):
        adapter.move_xy(10, 20)


def test_real_linuxcnc_rejects_simulated_z_by_default() -> None:
    config = MachineConfig()
    with pytest.raises(ValueError, match="仿真 Z"):
        LinuxCncController(SimulatedController(config), config, linuxcnc_module=FakeLinuxCnc())


def test_unexpected_xy_motion_during_edm_stops_z() -> None:
    adapter, fake = _adapter()
    adapter.arm_hole(1, 1.0)
    adapter.start_hole()
    fake.fake_stat.inpos = False
    adapter.tick(0.1)
    status = adapter.status()
    assert status.mode == MachineMode.FAULT
    assert not status.pulse_enabled
    assert "XY 状态异常" in status.fault
    assert fake.fake_command.aborted


def test_linuxcnc_poll_failure_aborts_xy_and_emergency_stops_z() -> None:
    adapter, fake = _adapter()
    adapter.move_xy(10, 20)
    assert not fake.fake_command.aborted

    def communication_failure():
        raise OSError("状态通道断开")

    fake.fake_stat.poll = communication_failure
    status = adapter.status()
    assert status.mode == MachineMode.FAULT
    assert "状态通信失败" in status.fault
    assert fake.fake_command.aborted
    assert adapter.z.status().mode == MachineMode.FAULT
    assert not status.pulse_enabled
    assert math.isnan(status.x_mm) and math.isnan(status.y_mm)


def test_unexpected_xy_motion_during_retract_aborts_xy() -> None:
    adapter, fake = _adapter()
    adapter.arm_hole(1, 0.001)
    adapter.start_hole()
    fake.fake_stat.inpos = False
    adapter.tick(0.1)
    assert fake.fake_command.aborted
    assert adapter.status().mode == MachineMode.FAULT


def test_pause_while_xy_moves_waits_for_arrival_without_starting_hole() -> None:
    adapter, fake = _adapter()
    source = (Path(__file__).resolve().parents[1] / "examples" / "three_holes.ngc").read_text()
    job = JobService(adapter, MachineConfig(), lambda _: None)
    job.load(source)
    job.start()
    job.tick(0.1)
    assert job.waiting_xy
    job.request_pause()
    fake.fake_stat.actual_position = (20.0, 40.0, 0.0)
    job.tick(0.1)
    assert job.paused
    assert not job.waiting_hole
    assert adapter.status().mode == MachineMode.MANUAL_Z


def test_z_can_home_before_xy_and_xy_home_does_not_target_stm_z() -> None:
    config = MachineConfig()
    z = SimulatedController(config)
    fake = FakeLinuxCnc()
    fake.fake_stat.homed = (0, 0)
    adapter = LinuxCncController(z, config, linuxcnc_module=fake, allow_simulated_z=True)

    adapter.home_z()
    assert adapter.z.status().homed
    assert fake.fake_command.home_requests == []

    adapter.home_xy()
    assert fake.fake_command.mode_requests == [fake.MODE_MANUAL]
    assert fake.fake_command.home_requests == [-1]
    assert fake.fake_stat.homed == (1, 1)


def test_xy_home_rejects_extra_linuxcnc_joint() -> None:
    adapter, fake = _adapter()
    fake.fake_stat.homed = (1, 1, 0)
    with pytest.raises(RuntimeError, match="仅配置 X/Y 两关节"):
        adapter.home_xy()
    assert fake.fake_command.home_requests == []


def test_manual_xy_move_does_not_require_surface_zero() -> None:
    adapter, fake = _adapter()
    adapter.z.home_z()  # Z 已回零，但工件表面 Z0 尚未设定。
    with pytest.raises(RuntimeError, match="Z0"):
        adapter.move_xy(5.0, 6.0)

    adapter.manual_move_xy(5.0, 6.0)
    assert fake.fake_command.mode_requests == [fake.MODE_MDI]
    assert fake.fake_command.mdi_lines == ["G21 G90 G54 G0 X5.000 Y6.000"]
    assert not adapter.xy_in_position


def test_xy_increment_jog_uses_cartesian_axis_speed_and_signed_direction() -> None:
    adapter, fake = _adapter()
    fake.fake_stat.actual_position = (10.0, 30.0, 0.0)  # G54: X0 Y10。

    adapter.jog_xy(1.25, 0.0)
    assert fake.fake_command.mode_requests == [fake.MODE_MANUAL]
    assert fake.fake_command.teleop_requests == [1]
    assert fake.fake_command.jog_requests == [
        (fake.JOG_INCREMENT, False, 0, adapter.config.manual_speed_mm_s, 1.25)
    ]
    assert not adapter.xy_in_position

    fake.fake_stat.actual_position = (11.25, 30.0, 0.0)
    assert adapter.status().xy_stationary
    assert adapter.xy_in_position
    adapter.jog_xy(0.0, -0.5)
    assert fake.fake_command.jog_requests[-1] == (
        fake.JOG_INCREMENT, False, 1, -adapter.config.manual_speed_mm_s, 0.5
    )


def test_manual_stop_sends_jog_stop_before_xy_abort() -> None:
    adapter, fake = _adapter()
    adapter.jog_xy(0.5, 0.0)
    adapter.stop()
    assert fake.fake_command.jog_requests[-1][:3] == (fake.JOG_STOP, False, 0)
    assert fake.fake_command.aborted
    assert adapter.xy_in_position


def test_g54_single_axis_touch_off_changes_reading_without_machine_motion() -> None:
    adapter, fake = _adapter()
    fake.fake_stat.actual_position = (80.0, 55.0, 0.0)
    original_machine_position = fake.fake_stat.actual_position
    original_y_offset = fake.fake_stat.g5x_offset[1]

    adapter.set_work_coordinates(x_mm=1.25)

    assert fake.fake_command.mode_requests == [fake.MODE_MDI]
    assert fake.fake_command.mdi_lines == ["G10 L20 P1 X1.250"]
    assert fake.fake_stat.actual_position == original_machine_position
    assert fake.fake_stat.g5x_offset[0] == pytest.approx(78.75)
    assert fake.fake_stat.g5x_offset[1] == original_y_offset
    assert adapter.status().x_mm == pytest.approx(1.25)
    assert adapter.status().y_mm == pytest.approx(35.0)


def test_g54_touch_off_rejects_xy_motion() -> None:
    adapter, fake = _adapter()
    adapter.manual_move_xy(5.0, 6.0)
    with pytest.raises(RuntimeError, match="未停稳"):
        adapter.set_work_coordinates(y_mm=0.0)
    assert fake.fake_command.mdi_lines == ["G21 G90 G54 G0 X5.000 Y6.000"]


def test_fault_reset_allows_rehoming_after_xy_home_state_is_lost() -> None:
    adapter, fake = _adapter()
    adapter.z.emergency_stop()
    fake.fake_stat.homed = (0, 0)
    adapter.reset_fault()
    assert adapter.z.status().mode == MachineMode.MANUAL_Z
    assert not adapter.status().xy_homed
    adapter.home_z()
    adapter.home_xy()
    assert adapter.status().xy_homed
