# -*- coding: utf-8 -*-
"""编辑器 v3 验证：三类历史致命 bug + 全工具可用性

覆盖：
  E1  显示后图片适应窗口（不再是"图很小"）
  E2  滚轮缩放生效、可退出 fit
  E3  画笔：拖动生成多点路径（v2 完全未实现）
  E4  直线：端点与拖动一致
  E5  矩形 / 椭圆：尺寸与拖动一致
  E6  箭头：带实心箭头（boundingRect 大于线段）
  E7  文字：写入场景文本项
  E8  马赛克：拖动改变底图像素
  E9  撤销：逐级回退标注 / 马赛克
  E10 单击未拖动不留空标注
  E11 渲染结果包含标注（与底图不同）
  E12 保存并复制：产出文件 + 回传 _image
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from features.screenshot_tool import EditorDialog  # noqa: E402
import features.screenshot_tool as st  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# ---------- 造测试图（709x485 彩色棋盘，利于检测马赛克变化） ----------
pm = QPixmap(709, 485)
p = QPainter(pm)
for x in range(0, 709, 37):
    for y in range(0, 485, 31):
        p.fillRect(x, y, 37, 31, QColor((x * 7) % 256, (y * 11) % 256, (x + y) % 256))
p.end()

dlg = EditorDialog(pm)
dlg.show()
app.processEvents()
view = dlg._view


def fire(kind, x, y, buttons=Qt.MouseButton.LeftButton, button=Qt.MouseButton.LeftButton):
    """向 view 派发真实鼠标事件（坐标 = view 视口坐标）"""
    ev = QMouseEvent(
        kind, QPointF(x, y), QPointF(x, y),
        button, buttons, Qt.KeyboardModifier.NoModifier)
    if kind == QMouseEvent.Type.MouseButtonPress:
        view.mousePressEvent(ev)
    elif kind == QMouseEvent.Type.MouseMove:
        view.mouseMoveEvent(ev)
    else:
        view.mouseReleaseEvent(ev)


def drag(x1, y1, x2, y2, steps=6):
    fire(QMouseEvent.Type.MouseButtonPress, x1, y1)
    for i in range(1, steps + 1):
        fire(QMouseEvent.Type.MouseMove,
             x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps,
             buttons=Qt.MouseButton.LeftButton)
    fire(QMouseEvent.Type.MouseButtonRelease, x2, y2, buttons=Qt.MouseButton.NoButton)


# ---------- E1 / E2 视图 ----------
vw = view.viewport().width()
vh = view.viewport().height()
scale = view.transform().m11()
img_w, img_h = 709 * scale, 485 * scale
rw, rh = img_w / vw if vw else 0, img_h / vh if vh else 0
fits = img_w <= vw * 1.03 and img_h <= vh * 1.03
check("E1. 显示后图片适应窗口（完整可见且填满至少一维）",
      fits and max(rw, rh) > 0.8,
      f"图 {img_w:.0f}x{img_h:.0f} / view {vw}x{vh} (占宽{rw*100:.0f}% 占高{rh*100:.0f}%)")
check("E2. 初始处于 fit 模式", dlg._zoom_fit is True)


class _Wheel:
    def __init__(self, dy):
        self._dy = dy

    def angleDelta(self):
        return QPointF(0, self._dy)


b = view.transform().m11()
dlg.canvas_wheel(_Wheel(120))
up = view.transform().m11()
check("E2b. 滚轮放大生效", up > b * 1.1, f"{b:.3f} -> {up:.3f}")
check("E2c. 放大后退出 fit", dlg._zoom_fit is False)
dlg.canvas_wheel(_Wheel(-120))
check("E2d. 滚轮缩小生效", view.transform().m11() < up * 0.95)

# 统一回到 1:1，便于坐标断言
dlg._zoom_100()
app.processEvents()

# ---------- E3 画笔 ----------
dlg._apply_tool("freehand")
n0 = len(dlg._annotations)
drag(100, 100, 300, 220)
painter_item = dlg._annotations[-1] if len(dlg._annotations) > n0 else None
ok = painter_item is not None and len(painter_item.path().toFillPolygon()) > 2
npts = len(painter_item.path().toFillPolygon()) if painter_item else 0
check("E3. 画笔拖动生成多点路径", ok, f"路径点数={npts}")

# ---------- E4 直线 ----------
dlg._apply_tool("line")
s_pt = view.mapToScene(QPoint(120, 300))
e_pt = view.mapToScene(QPoint(320, 400))
drag(120, 300, 320, 400)
ln = dlg._annotations[-1].line()
check("E4. 直线端点与拖动一致",
      abs(ln.x1() - s_pt.x()) < 3 and abs(ln.y1() - s_pt.y()) < 3
      and abs(ln.x2() - e_pt.x()) < 3 and abs(ln.y2() - e_pt.y()) < 3,
      f"({ln.x1():.0f},{ln.y1():.0f})->({ln.x2():.0f},{ln.y2():.0f})")

# ---------- E5 矩形 / 椭圆 ----------
dlg._apply_tool("rect")
drag(380, 80, 520, 180)
r = dlg._annotations[-1].rect()
check("E5a. 矩形尺寸与拖动一致",
      abs(r.width() - 140) < 4 and abs(r.height() - 100) < 4 and r.width() > 0 and r.height() > 0,
      f"{r.width():.0f}x{r.height():.0f}")

dlg._apply_tool("ellipse")
drag(380, 220, 520, 320)
e = dlg._annotations[-1].rect()
check("E5b. 椭圆尺寸与拖动一致",
      abs(e.width() - 140) < 4 and abs(e.height() - 100) < 4,
      f"{e.width():.0f}x{e.height():.0f}")

# ---------- E6 箭头 ----------
dlg._apply_tool("arrow")
drag(140, 380, 340, 380)
ai = dlg._annotations[-1]
abr = ai.path().boundingRect()
check("E6. 箭头为实心箭头（高度超出线宽）", abr.height() > 6,
      f"箭头包围盒 {abr.width():.0f}x{abr.height():.0f}")

# ---------- E7 文字 ----------
_seen = {}
dlg._apply_tool("text")
_orig_get_text = st.QInputDialog.getText
st.QInputDialog.getText = staticmethod(lambda *a, **k: (_seen.setdefault("t", "标注文字"), True))
try:
    fire(QMouseEvent.Type.MouseButtonPress, 430, 420)
    fire(QMouseEvent.Type.MouseButtonRelease, 430, 420, buttons=Qt.MouseButton.NoButton)
finally:
    st.QInputDialog.getText = _orig_get_text
text_items = [i for i in dlg._annotations if i.__class__.__name__ == "QGraphicsTextItem"]
check("E7. 文字标注写入场景", len(text_items) == 1
      and text_items[0].toPlainText() == "标注文字",
      f"文本={text_items[0].toPlainText() if text_items else '无'}")

# ---------- E8 马赛克 ----------
dg_before = dlg._base.copy()
dlg._apply_tool("mosaic")
drag(560, 120, 640, 200, steps=4)


def diff_px(a: QImage, b: QImage) -> int:
    return sum(1 for y in range(0, a.height(), 3) for x in range(0, a.width(), 3)
               if a.pixel(x, y) != b.pixel(x, y))


d_mos = diff_px(dg_before, dlg._base)
check("E8. 马赛克拖动改变底图像素", d_mos > 50, f"变化采样点={d_mos}")

# ---------- E9 撤销 ----------
before_undo = diff_px(dg_before, dlg._base)
dlg._undo()
after_undo = diff_px(dg_before, dlg._base)
check("E9a. 撤销马赛克恢复底图", after_undo < before_undo * 0.3,
      f"{before_undo} -> {after_undo}")

n_before = len(dlg._annotations)
dlg._undo()
check("E9b. 撤销移除最近标注", len(dlg._annotations) < n_before,
      f"{n_before} -> {len(dlg._annotations)}")

# ---------- E10 单击不留空标注 ----------
dlg._apply_tool("rect")
n_x = len(dlg._annotations)
fire(QMouseEvent.Type.MouseButtonPress, 200, 200)
fire(QMouseEvent.Type.MouseButtonRelease, 200, 200, buttons=Qt.MouseButton.NoButton)
check("E10. 单击未拖动不留空标注", len(dlg._annotations) == n_x,
      f"{n_x} -> {len(dlg._annotations)}")

# ---------- E11 渲染包含标注 ----------
out = dlg.render_result()
same = diff_px(dlg._base, out)
check("E11. 渲染结果包含标注", out.width() == 709 and same > 50,
      f"与底图差异采样点={same}")

# ---------- E12 保存 ----------
tmpdir = Path(tempfile.mkdtemp(prefix="dpet_editor_"))
saved = {}


def _fake_save(image):
    fp = tmpdir / "out.png"
    image.save(str(fp), "PNG")
    saved["path"] = fp
    return fp


_orig_save = st.ScreenshotTool.save_pixmap
_orig_copy = st.ScreenshotTool.maybe_copy_to_clipboard
st.ScreenshotTool.save_pixmap = staticmethod(_fake_save)
st.ScreenshotTool.maybe_copy_to_clipboard = staticmethod(lambda img: None)
try:
    dlg._on_save()
finally:
    st.ScreenshotTool.save_pixmap = _orig_save
    st.ScreenshotTool.maybe_copy_to_clipboard = _orig_copy

ok = saved.get("path") and Path(saved["path"]).exists() and Path(saved["path"]).stat().st_size > 0
check("E12. 保存并复制产出文件", bool(ok),
      f"{saved.get('path')} ({Path(saved['path']).stat().st_size if ok else 0} B)")

dlg.close()
fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
sys.exit(1 if fails else 0)
