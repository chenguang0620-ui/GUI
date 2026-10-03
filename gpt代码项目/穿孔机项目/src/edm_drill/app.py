"""PyQt 应用入口。默认只连接离线模拟器。"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from .event_log import EventLog
from .job_service import JobService
from .settings_store import SettingsStore
from .simulator import SimulatedController
from .ui.main_window import MainWindow


def main() -> int:
    application = QApplication(sys.argv)
    package_root = Path(__file__).resolve().parent
    project_root = package_root.parents[1]
    # 源码运行时将设置留在项目中；安装到机床电脑后写入用户数据目录。
    default_data_dir = (
        project_root / "data" if (project_root / "pyproject.toml").is_file()
        else Path.home() / ".local" / "share" / "edm-drill"
    )
    data_dir = Path(os.environ.get("EDM_DRILL_DATA", default_data_dir))
    store = SettingsStore(data_dir / "settings.json")
    try:
        config = store.load()
    except Exception as exc:
        QMessageBox.critical(None, "设置文件错误", f"无法加载设备设置：{exc}")
        return 1
    events = EventLog()
    events.add("已启动离线仿真控制器")
    controller = SimulatedController(config)
    job = JobService(controller, config, events.add)
    example = package_root / "examples" / "twelve_holes.ngc"
    if not example.is_file():
        QMessageBox.critical(None, "程序文件缺失", f"找不到默认十二孔程序：{example}")
        return 1
    window = MainWindow(job, store, events, example)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
