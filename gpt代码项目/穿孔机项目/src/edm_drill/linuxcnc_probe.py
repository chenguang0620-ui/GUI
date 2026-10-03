"""只读检查 LinuxCNC Python 接口是否可用，不发送任何运动命令。"""

from __future__ import annotations

import importlib


def main() -> int:
    try:
        api = importlib.import_module("linuxcnc")
        status = api.stat()
        status.poll()
    except Exception as exc:
        print(f"LinuxCNC 接口不可用：{exc}")
        return 1
    print(f"机床状态：{status.task_state}（STATE_ON={api.STATE_ON}）")
    print(f"XY 关节回零：{tuple(status.homed[:2])}")
    print(f"机床线性单位/毫米：{status.linear_units}")
    print(f"工作坐标系编号：{status.g5x_index}（G54=1）")
    print(f"解释器状态：{status.interp_state}（INTERP_IDLE={api.INTERP_IDLE}）")
    print(f"XY 到位：{bool(status.inpos)}")
    print(f"XY 机床坐标：{tuple(status.actual_position[:2])}")
    print(f"G54 XY 偏置：{tuple(status.g5x_offset[:2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
