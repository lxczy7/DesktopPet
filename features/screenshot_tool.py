"""
截图工具 v3（freeze-first 架构）

相对 v2 的关键修复：
  1. 先抓屏冻结、再显示遮罩：遮罩显示期间不再抓屏，
     彻底规避"遮罩在线时 BitBlt 失败"的路径（v2 的坑）
  2. DPI 修正：Qt 逻辑坐标 × devicePixelRatio = 物理抓屏坐标，
     修掉 v2 在 125%/150% 缩放下选区与实际裁剪区域错位的问题
  3. 全程 try/except + 友好错误提示，异常绝不冒泡杀进程
  4. mss.MSS 新 API（with_cursor 控制是否包含光标）
  5. 尊重 screenshot.show_editor 设置：关闭编辑器时直接保存+复制

功能：
  - 区域截图：冻结鼠标所在屏幕 → 全屏遮罩拖拽选区 → 从冻结图裁剪
  - 全屏截图：冻结鼠标所在屏幕 → 直接进编辑器
  - 窗口截图：枚举顶层窗口 → 选择后抓取
  - 编辑器：画笔 / 矩形 / 箭头 / 文字 / 马赛克 / 撤销 / 保存并复制
"""
import os
from datetime import datetime
from pathlib import Path

import mss
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, QSize, QPoint, Signal
from PySide6.QtGui import (
    QGuiApplication, QColor, QCursor, QFont, QImage, QPainter, QPen, QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QGraphicsLineItem,
    QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem,
    QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)


# ----------------------------------------------------------------------
# 全屏截图遮罩：冻结画面为底，压暗显示，选区内恢复原图亮度
# ----------------------------------------------------------------------
class ScreenshotOverlay(QWidget):
    """全屏截图遮罩（freeze-first：背景为冻结抓图，非实时桌面）"""

    selection_done = Signal(QRectF)  # 逻辑坐标（相对本屏幕左上角）
    closed = Signal()               # 遮罩完全关闭（无论完成或取消）

    def __init__(self, screen, frozen_pixmap: QPixmap, dpr: float):
        """
        screen:         QScreen，遮罩覆盖的屏幕
        frozen_pixmap:  该屏幕的冻结抓图（物理分辨率）
        dpr:            screen.devicePixelRatio()
        """
        super().__init__()
        self._screen = screen
        self._frozen = frozen_pixmap
        self._dpr = dpr if dpr and dpr > 0 else 1.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(screen.geometry())

        self._start = QPointF()
        self._end = QPointF()
        self._selecting = False
        self._hint_visible = True  # 未开始拖选时显示操作提示

    # ---------------- 事件 ----------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.activateWindow()
        self.raise_()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position()
            self._end = self._start
            self._selecting = True
            self._hint_visible = False  # 开始拖选后隐藏提示
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            self._end = event.position()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            rect = QRectF(self._start, self._end).normalized()
            valid = rect.width() >= 10 and rect.height() >= 10
            # 必须先关闭遮罩再触发后续（emit 是同步的，会一路执行到
            # 编辑器 exec() 模态循环；若顺序反了遮罩将盖住编辑器）
            self.close()
            if valid:
                self.selection_done.emit(rect)

    # ---------------- 绘制 ----------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 1. 冻结画面铺满整屏（逻辑尺寸 <- 物理图缩放）
        p.drawPixmap(self.rect(), self._frozen, self._frozen.rect())
        # 2. 整体压暗
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))

        # 3. 选区内恢复原图亮度 + 白框 + 尺寸提示
        if self._selecting:
            rect = QRectF(self._start, self._end).normalized()
            if rect.width() > 0 and rect.height() > 0:
                dpr = self._dpr
                src = QRectF(rect.x() * dpr, rect.y() * dpr,
                             rect.width() * dpr, rect.height() * dpr)
                p.drawPixmap(rect, self._frozen, src)
                p.setPen(QPen(QColor(255, 255, 255), 2))
                p.drawRect(rect)
                p.setPen(QPen(QColor(255, 255, 255)))
                p.setFont(QFont("Microsoft YaHei", 10))
                p.drawText(rect.bottomRight() + QPointF(8, 18),
                           f"{int(rect.width())} x {int(rect.height())}")

        # 4. 拖选前的操作提示（半透明药丸，顶部居中）
        elif self._hint_visible:
            hint = "🖱️ 拖动鼠标选择截图区域，松开完成  ·  按 Esc 取消"
            p.setFont(QFont("Microsoft YaHei", 12))
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(hint)
            cx = self.width() / 2
            cy = 64
            pill = QRectF(cx - tw / 2 - 20, cy - 24, tw + 40, 40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 20, 20, 200))
            p.drawRoundedRect(pill, 20, 20)
            p.setPen(QPen(QColor(255, 255, 255)))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, hint)


# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 截图编辑器 v3：画笔 / 直线 / 矩形 / 椭圆 / 箭头 / 文字 / 马赛克
#   v2 的三个致命问题：
#     1. event.pos() 在 PySide6 6.x 已移除 → 所有鼠标绘制抛异常
#        （线条/马赛克/文字全都用不了），统一改用 event.position()
#     2. "画笔"分支从未实现（press 置空 pending_item，move 不处理）
#     3. 标注被"烧"回底图后仍留在场景里，导致撤销错乱
#   v3 策略：标注恒为场景 item，保存时才合成；撤销用"底图 + 标注列表"快照
# ----------------------------------------------------------------------
from PySide6.QtGui import QBrush, QPainterPath
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QFrame, QGraphicsEllipseItem, QGraphicsItem,
    QGraphicsPathItem,
)
import math


class _CanvasView(QGraphicsView):
    """画布视图：鼠标事件转交编辑器；滚轮以光标为锚点缩放"""

    def __init__(self, scene: QGraphicsScene, editor: "EditorDialog"):
        super().__init__(scene)
        self._editor = editor
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QBrush(QColor(42, 44, 48)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def mousePressEvent(self, e) -> None:
        if not self._editor.canvas_press(e):
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if not self._editor.canvas_move(e):
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if not self._editor.canvas_release(e):
            super().mouseReleaseEvent(e)

    def wheelEvent(self, e) -> None:
        self._editor.canvas_wheel(e)


class EditorDialog(QDialog):
    """截图编辑器：标注 + 撤销 + 缩放 + 保存/复制"""

    TOOLS = [
        ("freehand", "✏️ 画笔"),
        ("line", "╱ 直线"),
        ("rect", "▭ 矩形"),
        ("ellipse", "◯ 椭圆"),
        ("arrow", "➤ 箭头"),
        ("text", "T 文字"),
        ("mosaic", "▦ 马赛克"),
    ]
    PALETTE = ["#e62828", "#ff9500", "#ffd60a", "#30d158", "#0a84ff", "#111111", "#ffffff"]
    BASE_WIDTHS = [2, 4, 7]
    MAX_HISTORY = 40

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("截图编辑器")

        img = pixmap.toImage()
        if img.format() != QImage.Format.Format_ARGB32:
            img = img.convertToFormat(QImage.Format.Format_ARGB32)
        self._base: QImage = img
        self._image: QImage = img.copy()     # 最终结果（保存/accept 后供调用方读取）

        self._scene = QGraphicsScene(self)
        self._pixitem = QGraphicsPixmapItem()
        self._pixitem.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._pixitem)
        self._view = _CanvasView(self._scene, self)

        self._annotations: list = []   # 场景中的标注项
        self._history: list = []       # 撤销快照 [(QImage, [items])]
        self._tool = None
        self._color = QColor(self.PALETTE[0])
        self._width_level = 1

        self._drawing = False
        self._start = QPointF()
        self._cur_item = None
        self._free_path = None
        self._last_mosaic = None
        self._zoom_fit = True

        self._set_base(img)
        self._build_ui()
        self._apply_tool("freehand")   # 默认画笔

    # ================= 初始化 =================

    def _set_base(self, img: QImage) -> None:
        self._base = img
        self._pixitem.setPixmap(QPixmap.fromImage(img))
        self._scene.setSceneRect(QRectF(img.rect()))

    def _build_ui(self) -> None:
        bar = QWidget(self)
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)

        # ---- 工具（互斥）----
        self._tool_btns = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, label in self.TOOLS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._apply_tool(k))
            self._group.addButton(btn)
            hl.addWidget(btn)
            self._tool_btns[key] = btn

        # ---- 颜色 ----
        hl.addSpacing(10)
        for c in self.PALETTE:
            cb = QPushButton()
            cb.setFixedSize(20, 20)
            cb.setToolTip(c)
            cb.setCursor(Qt.CursorShape.PointingHandCursor)
            cb.setStyleSheet(
                f"background:{c}; border:1px solid #999; border-radius:10px;")
            cb.clicked.connect(lambda _=False, col=c: self._set_color(col))
            hl.addWidget(cb)
        more = QPushButton("…")
        more.setFixedWidth(26)
        more.setToolTip("自定义颜色")
        more.clicked.connect(self._pick_color)
        hl.addWidget(more)

        # ---- 粗细 ----
        hl.addSpacing(10)
        self._width_btns = []
        for i, name in enumerate(("细", "中", "粗")):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setFixedWidth(34)
            b.clicked.connect(lambda _=False, idx=i: self._set_width(idx))
            hl.addWidget(b)
            self._width_btns.append(b)
        self._width_btns[1].setChecked(True)

        hl.addStretch(1)
        for txt, fn in (("适应窗口", self._fit), ("1:1", self._zoom_100),
                        ("撤销", self._undo)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            hl.addWidget(b)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        hl.addWidget(cancel_btn)
        save_btn = QPushButton("保存并复制")
        save_btn.setStyleSheet(
            "background:#1fcd88; color:white; font-weight:bold; padding:4px 14px;")
        save_btn.clicked.connect(self._on_save)
        hl.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._view, 1)
        layout.addWidget(bar)

        # 窗口尺寸：图片适配，且不小于可用屏 70% 的下限（避免小截图窗口太小）
        avail = QGuiApplication.primaryScreen().availableGeometry()
        w = min(max(self._base.width() + 40, 760), int(avail.width() * 0.92))
        h = min(max(self._base.height() + 120, 600), int(avail.height() * 0.92))
        self.resize(w, h)

    # ================= 工具/样式 =================

    def _apply_tool(self, key: str) -> None:
        self._tool = key
        btn = self._tool_btns.get(key)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        cursor = {
            "text": Qt.CursorShape.IBeamCursor,
            "mosaic": Qt.CursorShape.PointingHandCursor,
        }.get(key, Qt.CursorShape.CrossCursor)
        self._view.setCursor(cursor)

    def _set_color(self, color: str) -> None:
        self._color = QColor(color)

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(self._color, self, "选择颜色")
        if c.isValid():
            self._color = c

    def _set_width(self, idx: int) -> None:
        self._width_level = max(0, min(idx, len(self.BASE_WIDTHS) - 1))
        for i, b in enumerate(self._width_btns):
            b.setChecked(i == self._width_level)

    # ================= 缩放 =================

    def _view_scale(self) -> float:
        return max(0.05, abs(self._view.transform().m11()))

    def _pen_width(self) -> float:
        """笔宽按当前缩放反向补偿：视觉粗细恒定"""
        return max(1.2, self.BASE_WIDTHS[self._width_level] / self._view_scale())

    def _fit(self) -> None:
        self._view.fitInView(QRectF(self._base.rect()),
                             Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom_fit = True

    def _zoom_100(self) -> None:
        self._view.resetTransform()
        self._zoom_fit = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._zoom_fit:
            self._fit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._zoom_fit:
            self._fit()

    def canvas_wheel(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            return
        f = 1.18 if delta > 0 else 1 / 1.18
        self._view.scale(f, f)
        self._zoom_fit = False

    # ================= 撤销 =================

    def _push_state(self) -> None:
        self._history.append((self._base.copy(), list(self._annotations)))
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    def _undo(self) -> None:
        if not self._history:
            return
        img, items = self._history.pop()
        for it in self._annotations:
            self._scene.removeItem(it)
        self._annotations = []
        self._set_base(img)
        for it in items:
            self._scene.addItem(it)
            self._annotations.append(it)
        self._cur_item = None
        self._free_path = None
        self._drawing = False

    # ================= 画布事件 =================

    def _scene_pos(self, event) -> QPointF:
        return self._view.mapToScene(event.position().toPoint())

    def canvas_press(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton or not self._tool:
            return False
        pos = self._scene_pos(event)

        if self._tool == "text":
            text, ok = QInputDialog.getText(self, "插入文字", "请输入要标注的文字：")
            if not ok or not text.strip():
                return True
            self._push_state()
            self._add_text_item(text.strip(), pos)
            return True

        self._push_state()

        if self._tool == "mosaic":
            self._last_mosaic = pos
            self._apply_mosaic(pos)
            self._drawing = True
            return True

        pen = QPen(self._color, self._pen_width(), Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        self._start = pos
        self._drawing = True
        item = None
        if self._tool == "freehand":
            self._free_path = QPainterPath(pos)
            item = QGraphicsPathItem(self._free_path)
            item.setPen(pen)
        elif self._tool == "line":
            item = QGraphicsLineItem(pos.x(), pos.y(), pos.x(), pos.y())
            item.setPen(pen)
        elif self._tool == "rect":
            item = QGraphicsRectItem(QRectF(pos, pos))
            item.setPen(pen)
        elif self._tool == "ellipse":
            item = QGraphicsEllipseItem(QRectF(pos, pos))
            item.setPen(pen)
        elif self._tool == "arrow":
            item = QGraphicsPathItem()
            item.setPen(pen)
            item.setBrush(QBrush(self._color))

        if item is None:
            return True
        item.setZValue(10)
        self._scene.addItem(item)
        self._annotations.append(item)
        self._cur_item = item
        return True

    def canvas_move(self, event) -> bool:
        if not self._drawing or not self._tool:
            return False
        pos = self._scene_pos(event)

        if self._tool == "mosaic":
            if (self._last_mosaic is None
                    or (pos - self._last_mosaic).manhattanLength() > self._mosaic_radius() * 0.5):
                self._last_mosaic = pos
                self._apply_mosaic(pos)
            return True

        item = self._cur_item
        if item is None:
            return False
        if self._tool == "freehand":
            self._free_path.lineTo(pos)
            item.setPath(self._free_path)
        elif self._tool == "line":
            item.setLine(self._start.x(), self._start.y(), pos.x(), pos.y())
        elif self._tool in ("rect", "ellipse"):
            item.setRect(QRectF(self._start, pos).normalized())
        elif self._tool == "arrow":
            item.setPath(self._arrow_path(self._start, pos))
        return True

    def canvas_release(self, event) -> bool:
        if not self._drawing:
            return False
        self._drawing = False
        item, self._cur_item = self._cur_item, None
        self._free_path = None
        self._last_mosaic = None
        if item is not None and self._is_degenerate(item):
            # 单击未拖动 → 丢弃空标注，同时撤回这次快照
            self._scene.removeItem(item)
            if item in self._annotations:
                self._annotations.remove(item)
            if self._history:
                self._history.pop()
        return True

    @staticmethod
    def _is_degenerate(item) -> bool:
        if isinstance(item, QGraphicsPathItem):
            r = item.path().boundingRect()
            return r.width() < 3 and r.height() < 3
        if isinstance(item, (QGraphicsRectItem, QGraphicsEllipseItem)):
            r = item.rect()
            return r.width() < 3 or r.height() < 3
        if isinstance(item, QGraphicsLineItem):
            ln = item.line()
            return abs(ln.x2() - ln.x1()) < 3 and abs(ln.y2() - ln.y1()) < 3
        return False

    # ================= 标注构造 =================

    def _arrow_path(self, a: QPointF, b: QPointF) -> QPainterPath:
        path = QPainterPath(a)
        path.lineTo(b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = max(8.0, self._pen_width() * 3.5)
        spread = math.pi / 7
        left = QPointF(b.x() - size * math.cos(ang - spread),
                       b.y() - size * math.sin(ang - spread))
        right = QPointF(b.x() - size * math.cos(ang + spread),
                        b.y() - size * math.sin(ang + spread))
        head = QPainterPath(b)
        head.lineTo(left)
        head.lineTo(right)
        head.closeSubpath()
        path.addPath(head)
        return path

    def _add_text_item(self, text: str, pos: QPointF):
        item = QGraphicsTextItem(text)
        item.setDefaultTextColor(self._color)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(max(13, int(26 / self._view_scale())))
        font.setBold(True)
        item.setFont(font)
        item.setPos(pos)
        item.setZValue(10)
        self._scene.addItem(item)
        self._annotations.append(item)
        return item

    # ================= 马赛克 =================

    def _mosaic_radius(self) -> int:
        """马赛克半径随缩放自适应，保证视觉块大小稳定"""
        return max(10, int(22 / self._view_scale()))

    def _apply_mosaic(self, pos: QPointF) -> None:
        rad = self._mosaic_radius()
        w, h = self._base.width(), self._base.height()
        if w < rad * 2 or h < rad * 2:
            return
        x = max(0, min(int(pos.x()) - rad, w - rad * 2))
        y = max(0, min(int(pos.y()) - rad, h - rad * 2))
        src = self._base.copy(x, y, rad * 2, rad * 2)
        block = max(3, rad // 3)
        small = src.scaled(max(1, rad * 2 // block), max(1, rad * 2 // block),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        big = small.scaled(rad * 2, rad * 2, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.FastTransformation)
        painter = QPainter(self._base)
        painter.drawImage(x, y, big)
        painter.end()
        self._pixitem.setPixmap(QPixmap.fromImage(self._base))

    # ================= 结果 =================

    def render_result(self) -> QImage:
        """把底图 + 所有标注合成为最终图（用于保存/回传给悬浮窗）"""
        img = QImage(self._base.size(), QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self._scene.render(painter, QRectF(img.rect()), QRectF(self._base.rect()))
        painter.end()
        return img

    def _on_save(self) -> None:
        self._image = self.render_result()
        filepath = ScreenshotTool.save_pixmap(self._image)
        if filepath is None:
            QMessageBox.warning(self, "保存失败", "无法保存截图，请检查保存目录设置")
            return
        ScreenshotTool.maybe_copy_to_clipboard(self._image)
        self.accept()

# ----------------------------------------------------------------------
# 截图结果悬浮窗：图片停在桌面上，配工具条（保存/编辑/复制/关闭）
# ----------------------------------------------------------------------
class FloatingShotResult(QWidget):
    """截图结果悬浮展示窗：先看结果，再决定保存/编辑/复制"""

    closed = Signal()

    def __init__(self, pixmap: QPixmap, on_saved=None, parent=None):
        super().__init__(parent)
        self._image = pixmap.toImage()
        self._on_saved = on_saved
        self._drag_pos = None
        self._saved_path = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("""
            FloatingShotResult { background: rgba(30,30,30,230); border-radius: 10px; }
            QLabel#shot-status { color: #aef; font-size: 11px; }
            QPushButton { background: #3a3a3a; color: #eee; border: none;
                          border-radius: 5px; padding: 5px 12px; font-size: 12px; }
            QPushButton:hover { background: #4a4a4a; }
            QPushButton#primary { background: #1fcd88; color: white; font-weight: bold; }
            QPushButton#primary:hover { background: #29e099; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        # ---- 工具条 ----
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._save_btn = QPushButton("💾 保存")
        self._save_btn.setObjectName("primary")
        self._save_btn.clicked.connect(self._on_save_click)
        self._edit_btn = QPushButton("✏️ 编辑")
        self._edit_btn.clicked.connect(self._on_edit_click)
        self._copy_btn = QPushButton("📋 复制")
        self._copy_btn.clicked.connect(self._on_copy_click)
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedWidth(32)
        self._close_btn.clicked.connect(self.close)
        for b in (self._save_btn, self._edit_btn, self._copy_btn, self._close_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        self._status = QLabel("截图完成！可保存 / 编辑 / 复制，Esc 关闭")
        self._status.setObjectName("shot-status")
        bar.addWidget(self._status)
        layout.addLayout(bar)

        # ---- 图片区 ----
        self._img_label = QLabel()
        self._img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scaled = pixmap.scaled(
            QGuiApplication.primaryScreen().availableSize() * 0.7,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._img_label.setPixmap(scaled)
        layout.addWidget(self._img_label, 1)

        # 窗口尺寸 = 工具条 + 图片
        self.resize(scaled.width() + 24, scaled.height() + 70)
        self._move_to_default()

    def _move_to_default(self) -> None:
        avail = QGuiApplication.primaryScreen().availableGeometry()
        self.move(avail.center().x() - self.width() // 2,
                  avail.center().y() - self.height() // 2)

    # ---- 拖动（按工具条区域拖动整窗）----
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 50:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)

    # ---- 工具条动作 ----
    def _on_save_click(self) -> None:
        path = ScreenshotTool.save_pixmap(self._image)
        if path is None:
            self._status.setText("❌ 保存失败，请检查保存目录设置")
            return
        self._saved_path = path
        self._status.setText(f"✅ 已保存到：{path}")
        ScreenshotTool.maybe_copy_to_clipboard(self._image)
        if self._on_saved:
            try:
                self._on_saved(path)
            except Exception:
                pass

    def _on_edit_click(self) -> None:
        dlg = EditorDialog(QPixmap.fromImage(self._image), self)
        if dlg.exec():
            self._image = dlg._image.copy()
            pm = QPixmap.fromImage(self._image)
            self._img_label.setPixmap(pm.scaled(
                self._img_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            self._status.setText("已编辑，记得保存哦～")

    def _on_copy_click(self) -> None:
        ScreenshotTool.maybe_copy_to_clipboard(self._image)
        QApplication.clipboard().setPixmap(QPixmap.fromImage(self._image))
        self._status.setText("📋 已复制到剪贴板")


# ----------------------------------------------------------------------
# 截图工具入口
# ----------------------------------------------------------------------
class ScreenshotTool(QWidget):
    """截图工具入口：区域 / 全屏 / 窗口（freeze-first）"""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle("DesktopPetScreenshot")
        self.hide()  # 工具本体不显示，仅作为逻辑载体
        self._overlay = None      # 防 GC
        self._frozen = None       # 当前冻结图（物理分辨率）
        self._frozen_dpr = 1.0
        self._floating = None     # 悬浮结果窗引用（防 GC）
        self.on_finished = None   # 截图流程结束回调（恢复宠物等），成功/失败/取消都会触发
        self.on_shot_saved = None  # 悬浮窗保存成功回调（通知保存路径）

    # ---------------- 对外接口 ----------------

    def capture_region(self) -> None:
        """区域截图：冻结 → 遮罩 → 选区裁剪"""
        screen = self._target_screen()
        pixmap, dpr = self._freeze_screen(screen)
        if pixmap is None:
            self._notify_finished()  # 抓屏失败也要让调用方恢复状态
            return
        self._frozen = pixmap
        self._frozen_dpr = dpr
        overlay = ScreenshotOverlay(screen, pixmap, dpr)
        overlay.selection_done.connect(self._on_region_selected)
        overlay.closed.connect(self._on_overlay_closed)
        overlay.show()
        self._overlay = overlay  # 保持引用防止被 GC

    def capture_fullscreen(self) -> None:
        """全屏截图：冻结当前屏幕直接进编辑器"""
        screen = self._target_screen()
        pixmap, dpr = self._freeze_screen(screen)
        if pixmap is None:
            self._notify_finished()
            return
        self._finish(pixmap)

    def capture_window(self) -> None:
        """窗口截图：枚举顶层窗口选择后抓取"""
        windows = self._enum_windows()
        if not windows:
            QMessageBox.information(self, "窗口截图", "未找到可截取的窗口")
            self._notify_finished()
            return
        titles = [w[1] for w in windows]
        title, ok = QInputDialog.getItem(self, "窗口截图", "请选择要截取的窗口:",
                                         titles, 0, False)
        if not ok:
            self._notify_finished()
            return
        idx = titles.index(title)
        hwnd, _, rect = windows[idx]
        try:
            shot = self._grab_rect(rect)
            pixmap = self._to_pixmap(shot)
        except Exception as e:
            QMessageBox.warning(self, "截图失败", f"窗口捕获失败：{e}")
            self._notify_finished()
            return
        self._finish(pixmap)

    # ---------------- 内部实现 ----------------

    def _on_region_selected(self, rect: QRectF) -> None:
        """选区完成（逻辑坐标）→ 从冻结图物理裁剪"""
        frozen = self._frozen
        if frozen is None:
            return
        dpr = self._frozen_dpr
        x = int(round(rect.x() * dpr))
        y = int(round(rect.y() * dpr))
        w = int(round(rect.width() * dpr))
        h = int(round(rect.height() * dpr))
        # 边界钳制，防止越界
        x = max(0, min(x, frozen.width() - 1))
        y = max(0, min(y, frozen.height() - 1))
        w = max(1, min(w, frozen.width() - x))
        h = max(1, min(h, frozen.height() - y))
        cropped = frozen.copy(x, y, w, h)
        self._frozen = None
        self._overlay = None
        self._finish(cropped)

    def _on_overlay_closed(self) -> None:
        """遮罩已关闭（完成或取消）：清理引用并通知调用方。
        注意：不能在这里清 self._frozen——close() 由 mouseReleaseEvent
        先于 selection_done.emit 同步触发，清了冻结图会导致裁剪拿不到图。
        取消路径残留的 frozen 由下次 capture_region 覆盖。"""
        self._overlay = None
        self._notify_finished()

    def _notify_finished(self) -> None:
        """触发完成回调（每次 tool 实例只触发一次）"""
        if getattr(self, "_finished_notified", False):
            return
        self._finished_notified = True
        cb = self.on_finished
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    @staticmethod
    def _target_screen():
        """鼠标当前所在屏幕（多屏时截鼠标屏）"""
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos)
        return screen if screen is not None else QGuiApplication.primaryScreen()

    def _freeze_screen(self, screen):
        """抓屏冻结指定屏幕，返回 (QPixmap, dpr)；失败返回 (None, dpr)"""
        dpr = screen.devicePixelRatio() or 1.0
        geo = screen.geometry()
        monitor = {
            "left": int(round(geo.x() * dpr)),
            "top": int(round(geo.y() * dpr)),
            "width": int(round(geo.width() * dpr)),
            "height": int(round(geo.height() * dpr)),
        }
        try:
            with mss.MSS(with_cursor=self._include_cursor()) as sct:
                shot = sct.grab(monitor)
            return self._to_pixmap(shot), dpr
        except Exception as e:
            QMessageBox.warning(
                None, "截图失败",
                f"屏幕捕获失败：{e}\n\n"
                "可能原因：\n"
                "• 正处于远程桌面 / 虚拟机环境\n"
                "• 显卡驱动异常\n"
                "• 系统安全策略限制了屏幕捕获")
            return None, dpr

    @staticmethod
    def _include_cursor() -> bool:
        from config.settings_manager import settings
        return bool(settings.get("screenshot.include_cursor", False))

    def _finish(self, pixmap: QPixmap) -> None:
        """按设置决定悬浮展示还是直接保存"""
        from config.settings_manager import settings
        if settings.get("screenshot.show_editor", True):
            # 悬浮结果窗：图片停桌面上，用户选保存/编辑/复制
            floating = FloatingShotResult(pixmap, on_saved=getattr(self, "on_shot_saved", None))
            floating.show()
            self._floating = floating  # 防 GC
        else:
            if ScreenshotTool.save_pixmap(pixmap) is None:
                QMessageBox.warning(None, "保存失败", "无法保存截图，请检查保存目录设置")
                return
            ScreenshotTool.maybe_copy_to_clipboard(pixmap)
        self._notify_finished()  # 同步流程（全屏/窗口）：结束后恢复宠物

    @staticmethod
    def _grab_rect(rect) -> "mss.base.ScreenShot":
        with mss.MSS(with_cursor=ScreenshotTool._include_cursor()) as sct:
            return sct.grab({"left": int(rect[0]), "top": int(rect[1]),
                             "width": int(rect[2]), "height": int(rect[3])})

    @staticmethod
    def _to_pixmap(shot) -> QPixmap:
        # mss 10.x: shot.raw 为 BGRA bytes
        raw = getattr(shot, "raw", None) or shot.bgra_bits
        # PySide6/Qt6 无 Format_BGRA8888，用 numpy 交换 R/B 通道转 RGBA
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        arr = arr[..., [2, 1, 0, 3]]  # BGRA -> RGBA
        img = QImage(arr.tobytes(), shot.width, shot.height,
                     QImage.Format.Format_RGBA8888).copy()  # copy 脱离缓冲区
        return QPixmap.fromImage(img)

    @staticmethod
    def save_pixmap(image):
        """保存截图到配置目录，返回路径；失败返回 None（兼容 QPixmap/QImage）"""
        from config.constants import SCREENSHOT_SAVE_DIR
        from config.settings_manager import settings
        if isinstance(image, QPixmap):
            image = image.toImage()
        save_dir = Path(settings.get("screenshot.save_folder", str(SCREENSHOT_SAVE_DIR)))
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = save_dir / filename
            if not image.save(str(filepath), "PNG"):
                return None
            return filepath
        except Exception:
            return None

    @staticmethod
    def maybe_copy_to_clipboard(image) -> None:
        """复制到剪贴板（尊重设置，兼容 QPixmap/QImage）"""
        from config.settings_manager import settings
        if isinstance(image, QPixmap):
            image = image.toImage()
        if settings.get("screenshot.auto_copy_to_clipboard", True):
            QApplication.clipboard().setPixmap(QPixmap.fromImage(image))

    @staticmethod
    def _enum_windows():
        """枚举可见顶层窗口 [(hwnd, title, (l,t,w,h)), ...]（物理坐标）"""
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        my_pid = os.getpid()
        results = []

        def is_cloaked(hwnd) -> bool:
            """UWP 被虚拟化隐藏的窗口（DWM 标记）"""
            try:
                dwm = ctypes.windll.dwmapi
                cloaked = ctypes.c_int(0)
                # DWMWA_CLOAKED = 14
                if dwm.DwmGetWindowAttribute(
                        wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), 4) == 0:
                    return cloaked.value != 0
            except Exception:
                pass
            return False

        def cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == my_pid:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w > 50 and h > 50 and not user32.IsIconic(hwnd) and not is_cloaked(hwnd):
                results.append((hwnd, title.value, (rect.left, rect.top, w, h)))
            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(cb), 0)
        # 过滤掉桌面宠物自身窗口（按标题兜底）
        results = [r for r in results if "DesktopPetScreenshot" not in r[1]]
        return results
