"""找中页显示实际边缘和 G54 修改预览，并要求明确确认。"""

from __future__ import annotations

from dataclasses import replace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from edm_drill.alignment import AlignmentSession, Axis, ReferenceMode, TouchEdge  # noqa: E402
from edm_drill.domain import MachineMode, MachineStatus  # noqa: E402
from edm_drill.ui.alignment_page import AlignmentPage  # noqa: E402


class _FakeController:
    def __init__(self) -> None:
        self.current = MachineStatus(mode=MachineMode.MANUAL_Z, x_mm=10, y_mm=15)

    def status(self) -> MachineStatus:
        return self.current


class _FakeService:
    def __init__(self) -> None:
        self.session = AlignmentSession(2.0)
        self.controller = _FakeController()
        self.job = object()
        self.applied: list[tuple[Axis, ReferenceMode, float]] = []

    def set_tube_diameter(self, mm: float) -> None:
        self.session = AlignmentSession(mm)

    def capture(self, edge: TouchEdge) -> None:
        status = self.controller.status()
        self.session.record_touch(edge, x_mm=status.x_mm, y_mm=status.y_mm)

    def clear_touch(self, edge: TouchEdge) -> None:
        self.session.clear_touch(edge)

    def clear_all(self) -> None:
        self.session.clear_all()

    def preview_axis(
        self, axis: Axis, reference: ReferenceMode, compensation_mm: float
    ) -> float:
        return self.session.calculate_axis(axis, reference, compensation_mm)

    def apply_axis(
        self, axis: Axis, reference: ReferenceMode, compensation_mm: float
    ) -> float:
        origin = self.preview_axis(axis, reference, compensation_mm)
        current = self.controller.current
        if axis is Axis.X:
            self.controller.current = replace(current, x_mm=current.x_mm - origin)
        else:
            self.controller.current = replace(current, y_mm=current.y_mm - origin)
        self.applied.append((axis, reference, compensation_mm))
        self.session.clear_all()
        return origin


def test_page_shows_radius_adjusted_edges_and_center_preview() -> None:
    app = QApplication.instance() or QApplication([])
    service = _FakeService()
    page = AlignmentPage(service, lambda call: call())
    page.refresh(service.controller.status(), job_active=False)
    try:
        page.capture_buttons[TouchEdge.X_MINUS].click()
        service.controller.current = replace(service.controller.current, x_mm=30)
        page.capture_buttons[TouchEdge.X_PLUS].click()
        page.references[Axis.X].setCurrentIndex(
            page.references[Axis.X].findData(ReferenceMode.CENTER)
        )
        page.compensations[Axis.X].setValue(0.5)
        page.refresh(service.controller.status(), job_active=False)

        assert "实际 X- 边缘 +11.000 mm" in page.touch_labels[TouchEdge.X_MINUS].text()
        assert "实际 X+ 边缘 +29.000 mm" in page.touch_labels[TouchEdge.X_PLUS].text()
        assert "+20.500 mm" in page.preview_labels[Axis.X].text()
        assert "应用后：+9.500 mm" in page.preview_labels[Axis.X].text()
        assert page.apply_buttons[Axis.X].isEnabled()
        assert not page.apply_buttons[Axis.Y].isEnabled()
        app.processEvents()
    finally:
        page.close()


def test_page_confirms_persisted_single_axis_g54_and_clears_touches(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    service = _FakeService()
    page = AlignmentPage(service, lambda call: call())
    page.refresh(service.controller.status(), job_active=False)
    messages: list[str] = []

    def confirm(*args, **kwargs):
        messages.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    try:
        page.capture_buttons[TouchEdge.X_MINUS].click()
        page.refresh(service.controller.status(), job_active=False)
        page.apply_buttons[Axis.X].click()
        page.refresh(service.controller.status(), job_active=False)

        assert service.applied == [(Axis.X, ReferenceMode.MINUS, 0.0)]
        assert service.controller.status().x_mm == -1.0
        assert service.controller.status().y_mm == 15.0
        assert not service.session.touches
        assert "当前 G54 读数：+10.000 mm" in messages[0]
        assert "应用后当前 G54 读数：-1.000 mm" in messages[0]
        assert "持久保存 G54" in messages[0]
        assert not page.apply_buttons[Axis.X].isEnabled()
        app.processEvents()
    finally:
        page.close()


def test_page_blocks_capture_and_apply_during_job() -> None:
    app = QApplication.instance() or QApplication([])
    service = _FakeService()
    page = AlignmentPage(service, lambda call: call())
    try:
        page.refresh(service.controller.status(), job_active=True)
        assert not page.capture_buttons[TouchEdge.X_MINUS].isEnabled()
        assert not page.diameter_button.isEnabled()
        assert not page.apply_buttons[Axis.X].isEnabled()
        app.processEvents()
    finally:
        page.close()
