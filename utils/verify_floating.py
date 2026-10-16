# -*- coding: utf-8 -*-
"""悬浮结果窗验证：截图后图片停桌面 + 工具条全功能"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRectF, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QKeyEvent, QGuiApplication
from unittest.mock import patch
import tempfile

app = QApplication(sys.argv)

from features.screenshot_tool import ScreenshotTool, FloatingShotResult
from config.settings_manager import settings

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# 造一张测试图（渐变+方块，模拟截图）
from PySide6.QtGui import QPixmap, QColor, QPainter
pm = QPixmap(800, 500)
p = QPainter(pm)
for x in range(0, 800, 100):
    for y in range(0, 500, 100):
        p.fillRect(x, y, 100, 100, QColor((x * 7) % 256, (y * 5) % 256, 128))
p.end()

# ============ E1: _finish 弹悬浮窗 ============
print("--- E1：截图完成 → 悬浮窗 ---")
tool = ScreenshotTool()
events = []
tool.on_finished = lambda: events.append("f")
tool._finish(pm)
check("E1. 悬浮窗弹出且 on_finished 触发",
      tool._floating is not None and tool._floating.isVisible() and events == ["f"])
floating = tool._floating
check("E2. 悬浮窗有四个工具按钮 + 状态标签",
      floating._save_btn.text() == "💾 保存" and floating._edit_btn.text() == "✏️ 编辑"
      and floating._copy_btn.text() == "📋 复制" and floating._status.text() != "")

# ============ E3: 保存（patch 掉真实写盘目标） ============
print("--- E3：保存 ---")
saved_cb = []
fake_path = Path(tempfile.gettempdir()) / "fake_shot.png"
floating._on_saved = lambda path: saved_cb.append(path)
with patch.object(ScreenshotTool, "save_pixmap", staticmethod(lambda im: fake_path)), \
     patch.object(ScreenshotTool, "maybe_copy_to_clipboard"):
    floating._on_save_click()
check("E3. 保存 → 回调带路径 + 状态栏显示位置",
      saved_cb == [fake_path] and str(fake_path) in floating._status.text(),
      f"status={floating._status.text()}")

# ============ E4: 保存失败路径 ============
print("--- E4：保存失败 ---")
floating._saved_path = None
with patch.object(ScreenshotTool, "save_pixmap", staticmethod(lambda im: None)):
    floating._on_save_click()
check("E4. 保存失败有提示不崩", "失败" in floating._status.text())

# ============ E5: 复制 ============
print("--- E5：复制 ---")
cb = QApplication.clipboard()
floating._on_copy_click()
check("E5. 复制到剪贴板", not cb.pixmap().isNull()
      and cb.pixmap().width() == 800 and cb.pixmap().height() == 500)

# ============ E6: 编辑（EditorDialog 模态，patch exec） ============
print("--- E6：编辑入口 ---")
edited = {}
class FakeDlg:
    def __init__(self, pix, parent=None):
        self._image = pix.toImage()
    def exec(self):
        # 模拟用户在编辑器里画了一笔（改一个像素）
        self._image.setPixelColor(5, 5, QColor(255, 0, 0))
        return 1
with patch("features.screenshot_tool.EditorDialog", FakeDlg):
    floating._on_edit_click()
check("E6. 编辑后同步回悬浮窗", floating._image.pixelColor(5, 5) == QColor(255, 0, 0))

# ============ E7: Esc 关闭 ============
print("--- E7：Esc 关闭 ---")
closed = []
floating.closed.connect(lambda: closed.append(1))
esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
app.sendEvent(floating, esc)
app.processEvents()
check("E7. Esc 关闭 + closed 信号", not floating.isVisible() and closed == [1])

# ============ E8: show_editor=False 直接保存路径 ============
print("--- E8：关闭悬浮窗时直接保存 ---")
tool2 = ScreenshotTool()
events2 = []
tool2.on_finished = lambda: events2.append("f")
old = settings.get("screenshot.show_editor", True)
settings.set("screenshot.show_editor", False)
with patch.object(ScreenshotTool, "save_pixmap", staticmethod(lambda im: fake_path)), \
     patch.object(ScreenshotTool, "maybe_copy_to_clipboard") as mc:
    tool2._finish(pm)
settings.set("screenshot.show_editor", old)
check("E8. 无悬浮窗时直接保存+复制+恢复", mc.called and events2 == ["f"]
      and tool2._floating is None)

fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
for f in fails:
    print("  FAILED:", f[0], f[2])
sys.exit(1 if fails else 0)
