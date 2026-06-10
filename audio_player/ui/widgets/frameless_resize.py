from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QMouseEvent, QCursor

EDGE_MARGIN = 6


class FramelessResizeMixin:
    """Mixin for frameless QDialog/QWidget — edge resize via windowHandle().startSystemResize()."""

    def _on_edge(self, pos: QPoint) -> bool:
        return self._edge_at(pos) is not None

    def _edge_at(self, pos: QPoint):
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        edge = None
        if y <= EDGE_MARGIN:
            edge = Qt.Edge.TopEdge
        elif y >= h - EDGE_MARGIN:
            edge = Qt.Edge.BottomEdge
        if x <= EDGE_MARGIN:
            edge = edge | Qt.Edge.LeftEdge if edge else Qt.Edge.LeftEdge
        elif x >= w - EDGE_MARGIN:
            edge = edge | Qt.Edge.RightEdge if edge else Qt.Edge.RightEdge
        return edge

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton and self._on_edge(e.pos()):
            wh = self.windowHandle()
            if wh:
                wh.startSystemResize(self._edge_at(e.pos()))
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        edge = self._edge_at(e.pos())
        if edge in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif edge in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edge in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edge in (Qt.Edge.TopEdge | Qt.Edge.RightEdge, Qt.Edge.BottomEdge | Qt.Edge.LeftEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)
