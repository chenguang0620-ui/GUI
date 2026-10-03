"""孔位图：按 G 代码孔序绘制路径，并提供点选、缩放和平移。"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..gcode import Program


@dataclass(frozen=True)
class Hole:
    number: int
    x_mm: float
    y_mm: float
    depth_mm: float
    recipe_id: int


def holes_from_program(program: Program | None) -> list[Hole]:
    """孔号按 M200 执行顺序产生，坐标继承前一条 G0 XY。"""
    if program is None:
        return []
    holes: list[Hole] = []
    x = y = 0.0
    for step in program.steps:
        if step.kind == "move_xy":
            assert step.x_mm is not None and step.y_mm is not None
            x, y = step.x_mm, step.y_mm
        elif step.kind == "hole":
            assert step.depth_mm is not None and step.recipe_id is not None
            holes.append(Hole(len(holes) + 1, x, y, step.depth_mm, step.recipe_id))
    return holes


class HoleMap(QWidget):
    """只展示孔位，不直接下发运动命令；``selected`` 只用于查看孔信息。"""

    selected = pyqtSignal(int)

    _BACKGROUND = QColor("#10171c")
    _PENDING = QColor("#a9bec9")
    _COMPLETE = QColor("#43daa1")
    _CURRENT = QColor("#ffd12b")
    _SELECTED = QColor("#64caff")

    def __init__(self):
        super().__init__()
        self.holes: list[Hole] = []
        self._program: Program | None = None
        self.selected_number: int | None = None
        self.current_number: int | None = None
        self.completed_count = 0
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.drag_start: QPointF | None = None
        self._center_x = 0.0
        self._center_y = 0.0
        self._span_x = 0.0
        self._span_y = 0.0
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.setToolTip("点击孔位查看坐标；滚轮缩放，拖动平移")

    def set_program(self, program: Program | None) -> None:
        """仅在孔序变化时复位视图，避免每次状态刷新打断用户操作。"""
        if program is self._program:
            return
        self._program = program
        new_holes = holes_from_program(program)
        if new_holes != self.holes:
            self.holes = new_holes
            self.completed_count = 0
            self.current_number = None
            self.selected_number = None
            if new_holes:
                xs = [hole.x_mm for hole in new_holes]
                ys = [hole.y_mm for hole in new_holes]
                self._center_x = (min(xs) + max(xs)) / 2
                self._center_y = (min(ys) + max(ys)) / 2
                self._span_x = max(xs) - min(xs)
                self._span_y = max(ys) - min(ys)
            else:
                self._center_x = self._center_y = self._span_x = self._span_y = 0.0
            self.reset_view()

    def set_progress(self, completed_count: int, current_number: int | None = None) -> None:
        """更新加工状态；无效孔号不会在图上产生虚假的当前孔。"""
        completed = min(max(int(completed_count), 0), len(self.holes))
        current = current_number if current_number is not None and completed < current_number <= len(self.holes) else None
        if (completed, current) != (self.completed_count, self.current_number):
            self.completed_count = completed
            self.current_number = current
            self.update()

    def reset_view(self) -> None:
        """恢复完整孔位视野，同时保留用户点选的孔。"""
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.drag_start = None
        self.update()

    def _fit_scale(self) -> float:
        # 为标题、图例和孔号留边；单行、单列孔位也能正确居中。
        side = min(54.0, max(34.0, self.width() * 0.10))
        usable_width = max(self.width() - side * 2, 1.0)
        usable_height = max(self.height() - 58.0 - 45.0, 1.0)
        scales = []
        if self._span_x > 0:
            scales.append(usable_width / self._span_x)
        if self._span_y > 0:
            scales.append(usable_height / self._span_y)
        return min(scales) if scales else 1.0

    def _point(self, hole: Hole) -> QPointF:
        scale = self._fit_scale() * self.zoom
        # 机床 Y 正方向朝上，屏幕 Y 正方向朝下。
        return QPointF(
            self.width() / 2 + (hole.x_mm - self._center_x) * scale + self.pan.x(),
            (self.height() + 58.0 - 45.0) / 2 - (hole.y_mm - self._center_y) * scale + self.pan.y(),
        )

    def _draw_header(self, painter: QPainter) -> None:
        painter.setFont(QFont("", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor("#dce8ed"))
        painter.drawText(QRectF(12, 4, self.width() - 24, 22), f"孔位 {len(self.holes)}  ·  按加工顺序连线")

        # 窄窗口将图例放到第二行，避免遮住孔号或首行孔位。
        legend_y = 37 if self.width() < 480 else 17
        legend_x = 13 if self.width() < 480 else self.width() - 235
        painter.setFont(QFont("", 8))
        for label, color, advance in (
            ("当前", self._CURRENT, 66),
            ("完成", self._COMPLETE, 66),
            ("待加工", self._PENDING, 82),
        ):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(legend_x + 4, legend_y), 4, 4)
            painter.setPen(QColor("#aebec7"))
            painter.drawText(QRectF(legend_x + 12, legend_y - 10, advance - 14, 21), label)
            legend_x += advance

    def _draw_route(self, painter: QPainter, points: list[QPointF]) -> None:
        for index, (start, end) in enumerate(zip(points, points[1:]), start=1):
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length = hypot(dx, dy)
            if length < 2:
                continue
            target_number = index + 1
            if target_number <= self.completed_count:
                color, style = QColor("#4caa86"), Qt.PenStyle.SolidLine
            elif target_number == self.current_number:
                color, style = self._CURRENT, Qt.PenStyle.SolidLine
            else:
                color, style = QColor("#69808e"), Qt.PenStyle.DashLine
            painter.setPen(QPen(color, 1.7, style))
            painter.drawLine(start, end)
            if length < 27:
                continue
            # 中途的箭头给出实际加工方向，折返路径更容易辨认。
            t = 0.58
            tip = QPointF(start.x() + dx * t, start.y() + dy * t)
            ux, uy = dx / length, dy / length
            back = QPointF(tip.x() - ux * 7, tip.y() - uy * 7)
            painter.setPen(QPen(color, 1.7))
            painter.drawLine(tip, QPointF(back.x() - uy * 3, back.y() + ux * 3))
            painter.drawLine(tip, QPointF(back.x() + uy * 3, back.y() - ux * 3))

    def _draw_hole(self, painter: QPainter, hole: Hole, point: QPointF, show_label: bool) -> None:
        current = hole.number == self.current_number
        complete = hole.number <= self.completed_count
        selected = hole.number == self.selected_number
        color = self._CURRENT if current else self._COMPLETE if complete else self._PENDING

        if current:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#ffd12b"), 2))
            painter.drawEllipse(point, 15, 15)
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._SELECTED, 2))
            painter.drawEllipse(point, 19 if current else 15, 19 if current else 15)

        painter.setPen(QPen(QColor("#e9f1f4"), 1.2))
        painter.setBrush(color)
        painter.drawEllipse(point, 9 if current else 8, 9 if current else 8)
        if complete and not current:
            # 对已完成孔再加勾，颜色之外也可区分状态。
            painter.setPen(QPen(QColor("#143e32"), 2))
            painter.drawLine(QPointF(point.x() - 4, point.y()), QPointF(point.x() - 1, point.y() + 3))
            painter.drawLine(QPointF(point.x() - 1, point.y() + 3), QPointF(point.x() + 5, point.y() - 4))

        if show_label:
            label_rect = QRectF(point.x() - 28, point.y() + 11, 56, 21)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._BACKGROUND)
            painter.drawRoundedRect(label_rect, 3, 3)
            painter.setFont(QFont("", 9, QFont.Weight.DemiBold if current or selected else QFont.Weight.Normal))
            painter.setPen(self._SELECTED if selected else color if current or complete else QColor("#e6eef2"))
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                f"H{hole.number:03d}",
            )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._BACKGROUND)
        if not self.holes:
            painter.setPen(QColor("#c5d1d7"))
            painter.setFont(QFont("", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "请在程序库校验 G 代码以生成孔位图")
            return
        self._draw_header(painter)
        points = [self._point(hole) for hole in self.holes]
        self._draw_route(painter, points)

        # 点位太密时只标当前和选中孔；其余孔仍可点选并在悬停时看坐标。
        labels_fit = False
        if len(points) <= 48:
            labels_fit = all(
                hypot(a.x() - b.x(), a.y() - b.y()) >= 37
                for index, a in enumerate(points) for b in points[index + 1:]
            )
        # 同坐标重复穿孔时，始终让当前孔的标记处于最上层。
        current_item = None
        for hole, point in zip(self.holes, points):
            if hole.number == self.current_number:
                current_item = (hole, point)
                continue
            self._draw_hole(
                painter, hole, point,
                labels_fit or hole.number in (self.current_number, self.selected_number),
            )
        if current_item is not None:
            hole, point = current_item
            self._draw_hole(painter, hole, point, True)

    def _zoom_at(self, anchor: QPointF, factor: float) -> None:
        """以鼠标位置为缩放锚点，使选中的孔不会突然跳走。"""
        old_zoom = self.zoom
        self.zoom = min(8.0, max(0.5, old_zoom * factor))
        if self.zoom == old_zoom:
            return
        ratio = self.zoom / old_zoom
        center = QPointF(self.width() / 2, (self.height() + 58.0 - 45.0) / 2)
        offset = anchor - center - self.pan
        self.pan = QPointF(
            anchor.x() - center.x() - offset.x() * ratio,
            anchor.y() - center.y() - offset.y() * ratio,
        )
        self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        delta = event.angleDelta().y()
        if self.holes and delta:
            self._zoom_at(event.position(), 1.15 if delta > 0 else 1 / 1.15)
            event.accept()

    def _nearest_hole(self, pos: QPointF) -> Hole | None:
        candidates = []
        for hole in self.holes:
            point = self._point(hole)
            distance_sq = (point.x() - pos.x()) ** 2 + (point.y() - pos.y()) ** 2
            if distance_sq <= 21 ** 2:
                candidates.append((distance_sq, hole))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1].number))
        # 重合孔位可重复点击，依次查看不同的 M200 指令。
        closest_distance = candidates[0][0]
        stacked = [hole for distance, hole in candidates if abs(distance - closest_distance) < 1]
        if len(stacked) > 1 and self.selected_number in [hole.number for hole in stacked]:
            current_index = next(i for i, hole in enumerate(stacked) if hole.number == self.selected_number)
            return stacked[(current_index + 1) % len(stacked)]
        return candidates[0][1]

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hole = self._nearest_hole(event.position())
        if hole is not None:
            self.selected_number = hole.number
            self.selected.emit(hole.number)
            self.update()
            return
        self.drag_start = event.position()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        pos = event.position()
        if self.drag_start is not None:
            self.pan += pos - self.drag_start
            self.drag_start = pos
            self.update()
            return
        hole = self._nearest_hole(pos)
        self.setCursor(Qt.CursorShape.PointingHandCursor if hole else Qt.CursorShape.ArrowCursor)
        if hole:
            self.setToolTip(
                f"H{hole.number:03d}  X {hole.x_mm:+.3f}  Y {hole.y_mm:+.3f}  "
                f"P{hole.recipe_id}  D{hole.depth_mm:.3f}"
            )
        else:
            self.setToolTip("点击孔位查看坐标；滚轮缩放，拖动平移")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
