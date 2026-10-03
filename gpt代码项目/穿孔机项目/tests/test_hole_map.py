"""孔位提取、紧凑尺寸渲染以及地图交互。"""

import os
from pathlib import Path
from math import hypot as real_hypot

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import edm_drill.ui.hole_map as hole_map_module
from edm_drill.gcode import Program, Step, parse_program
from edm_drill.ui.hole_map import HoleMap, holes_from_program


@pytest.fixture(scope="module")
def app() -> QApplication:
    """真实运行 Qt 绘图和鼠标事件，不只测试数据结构。"""
    application = QApplication.instance() or QApplication([])
    yield application


def _demo_program():
    source = (Path(__file__).resolve().parents[1] / "examples" / "twelve_holes.ngc").read_text()
    return parse_program(source)


def test_twelve_holes_follow_gcode_order() -> None:
    holes = holes_from_program(_demo_program())
    assert len(holes) == 12
    assert (holes[0].x_mm, holes[0].y_mm) == (20, 15)
    assert (holes[7].x_mm, holes[7].y_mm) == (80, 30)
    assert (holes[-1].x_mm, holes[-1].y_mm) == (80, 45)


def test_compact_map_keeps_all_twelve_holes_visible_and_clickable(app: QApplication) -> None:
    widget = HoleMap()
    widget.resize(320, 210)
    widget.set_program(_demo_program())
    widget.show()
    app.processEvents()

    points = [widget._point(hole) for hole in widget.holes]
    assert all(25 <= point.x() <= widget.width() - 25 for point in points)
    assert all(55 <= point.y() <= widget.height() - 40 for point in points)

    received = []
    widget.selected.connect(received.append)
    point = points[7]
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(round(point.x()), round(point.y())))
    assert received == [8]
    assert widget.selected_number == 8


def test_status_colors_are_drawn_for_current_completed_and_pending(app: QApplication) -> None:
    widget = HoleMap()
    widget.resize(540, 400)
    widget.set_program(_demo_program())
    widget.set_progress(3, 4)
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    widget.render(image)

    def colors_near(number: int) -> set[str]:
        point = widget._point(widget.holes[number - 1])
        x, y = round(point.x()), round(point.y())
        return {image.pixelColor(i, j).name() for i in range(x - 6, x + 7) for j in range(y - 6, y + 7)}

    assert QColor("#43daa1").name() in colors_near(1)
    assert QColor("#ffd12b").name() in colors_near(4)
    assert QColor("#a9bec9").name() in colors_near(5)
    assert image.pixelColor(0, 0) == QColor("#10171c")


def test_zoom_stays_on_cursor_and_drag_keeps_selection(app: QApplication) -> None:
    widget = HoleMap()
    widget.resize(360, 240)
    widget.set_program(_demo_program())
    widget.show()
    app.processEvents()
    anchor = widget._point(widget.holes[5])
    widget._zoom_at(anchor, 2.0)
    moved = widget._point(widget.holes[5])
    assert abs(moved.x() - anchor.x()) < 0.001
    assert abs(moved.y() - anchor.y()) < 0.001

    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(round(moved.x()), round(moved.y())))
    assert widget.selected_number == 6
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=QPoint(25, 205))
    QTest.mouseMove(widget, QPoint(40, 195))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=QPoint(40, 195))
    assert widget.pan != QPointF(0, 0)
    widget.reset_view()
    assert widget.pan == QPointF(0, 0)
    assert widget.selected_number == 6


def test_replacing_program_clears_old_progress_and_selection(app: QApplication) -> None:
    widget = HoleMap()
    widget.set_program(_demo_program())
    widget.set_progress(3, 4)
    widget.selected_number = 2
    widget.set_program(parse_program("%\nG21\nG90\nG54\nG0 X5 Y7\nM200 P1 D8\nM2\n%"))
    assert len(widget.holes) == 1
    assert widget.completed_count == 0
    assert widget.current_number is None
    assert widget.selected_number is None
    widget.set_progress(99, 10)
    assert widget.completed_count == 1
    assert widget.current_number is None
    point = widget._point(widget.holes[0])
    assert point == QPointF(widget.width() / 2, (widget.height() + 58 - 45) / 2)


def test_clicking_duplicate_coordinates_cycles_hole_numbers(app: QApplication) -> None:
    widget = HoleMap()
    widget.resize(320, 210)
    program = parse_program("%\nG21\nG90\nG54\nG0 X5 Y7\nM200 P1 D8\nM200 P1 D8\nM2\n%")
    widget.set_program(program)
    widget.show()
    app.processEvents()
    point = widget._point(widget.holes[0])
    at = QPoint(round(point.x()), round(point.y()))
    received = []
    widget.selected.connect(received.append)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=at)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=at)
    assert received == [1, 2]


def test_many_holes_skip_pairwise_label_checks(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    steps = []
    for number in range(200):
        steps.append(Step("move_xy", number * 2 + 1, x_mm=float(number), y_mm=5.0))
        steps.append(Step("hole", number * 2 + 2, recipe_id=1, depth_mm=8.0))
    widget = HoleMap()
    widget.resize(540, 300)
    widget.set_program(Program(tuple(steps), "test"))
    calls = 0

    def counted_hypot(x: float, y: float) -> float:
        nonlocal calls
        calls += 1
        return real_hypot(x, y)

    monkeypatch.setattr(hole_map_module, "hypot", counted_hypot)
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    widget.render(image)
    assert calls <= len(widget.holes) * 2  # 路径箭头是线性处理，无孔号两两扫描
