"""验证打包资源进入首页，并且孔位状态随作业和编辑器同步。"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from edm_drill import app as app_module  # noqa: E402
from edm_drill.domain import MachineConfig  # noqa: E402
from edm_drill.domain import MachineMode, MachineStatus  # noqa: E402
from edm_drill.event_log import EventLog  # noqa: E402
from edm_drill.job_service import JobService  # noqa: E402
from edm_drill.settings_store import SettingsStore  # noqa: E402
from edm_drill.simulator import SimulatedController  # noqa: E402
from edm_drill.ui.main_window import MainWindow  # noqa: E402


def test_first_page_shows_bundled_holes_and_current_progress(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    example = Path(app_module.__file__).resolve().parent / "examples" / "twelve_holes.ngc"
    assert example.is_file()
    config = MachineConfig()
    controller = SimulatedController(config)
    events = EventLog()
    job = JobService(controller, config, events.add)
    window = MainWindow(job, SettingsStore(tmp_path / "settings.json"), events, example)
    window.show()
    application.processEvents()
    try:
        assert (window.width(), window.height()) == (1280, 800)
        assert window.pages.currentIndex() == 0
        assert len(window.overview.hole_map.holes) == 12
        assert (window.overview.hole_map.holes[0].x_mm, window.overview.hole_map.holes[0].y_mm) == (20, 15)
        assert "12" in window.overview.map_summary.text()
        assert window.overview.hole_map.isVisible()
        assert [button.text() for button in window.nav_buttons] == [
            "加工总览", "机床手动", "找中 / 补偿", "程序库", "工艺 / 诊断",
        ]
        window.show_page(1)
        assert window.pages.currentWidget() is window.manual
        window.show_page(2)
        assert window.pages.currentWidget() is window.alignment
        window.show_page(0)

        controller.home_z()
        controller.home_xy()
        controller.set_surface_zero()
        window.program.start()
        window.refresh()
        assert window.overview.hole_map.current_number == 1
        assert "H001" in window.overview.current_hole_label.text()

        job.request_pause()
        job.tick(100)
        job.tick(100)
        window.refresh()
        assert job.paused
        assert window.overview.hole_map.completed_count == 1
        assert window.program.editor.isReadOnly()
        assert not window.program.validate_button.isEnabled()

        job.stop()
        window.program.editor.insertPlainText("\n")
        window.refresh()
        assert not window.start_button.isEnabled()
        assert "上次校验版本" in window.overview.program_label.text()

        window.overview.refresh(MachineStatus(mode=MachineMode.FAULT, x_mm=float("nan"), y_mm=float("nan")))
        assert "X —" in window.overview.coords.text()
        assert "Y —" in window.overview.coords.text()
    finally:
        window.timer.stop()
        window.close()
