# -*- coding: utf-8 -*-
"""端到端验证：模拟宣哥"右键点截图"完整操作路径（真实抓屏）"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRectF, QTimer, QPointF, Qt, QPoint
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtCore import QEvent

app = QApplication(sys.argv)

from features.screenshot_tool import ScreenshotTool, ScreenshotOverlay

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# ============ 场景 A：完整区域截图（模拟鼠标按下-移动-松开） ============
print("--- 场景 A：右键点'截图' → 拖选 → 编辑器 ---")
def _capture_available(timeout: float = 8.0) -> bool:
    """探测本环境能否抓屏：受限环境（沙箱/远程桌面）下 mss 会挂起，
    用独立线程 + 超时避免整个测试卡死。"""
    import threading
    import mss
    res = {}

    def _run():
        try:
            with mss.MSS() as sct:
                sct.grab({"left": 0, "top": 0, "width": 64, "height": 64})
            res["ok"] = True
        except Exception:
            res["ok"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout)
    return bool(res.get("ok"))


if not _capture_available():
    print("SKIP: 当前环境屏幕捕获无响应（沙箱 / 远程桌面 / 安全策略限制），跳过本套件")
    print("===== SKIP：本环境无法抓屏，已跳过 =====")
    sys.exit(0)


tool = ScreenshotTool()

events = []
tool.on_finished = lambda: events.append("finished")

captured = {}
tool._finish = lambda pm: captured.__setitem__("pix", pm)

screen = tool._target_screen()
tool.capture_region()
overlay = tool._overlay
check("A1. 遮罩已弹出", overlay is not None and overlay.isVisible())

# 记录冻结图与 dpr，用于推算裁剪期望值（兼容 100%/125% 缩放）
_dpr = overlay._dpr
_fz = overlay._frozen
_fw, _fh = _fz.width(), _fz.height()

# 模拟鼠标按下（屏幕中心偏左上）
app.processEvents()
press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(300, 200),
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
app.sendEvent(overlay, press)
move = QMouseEvent(QEvent.Type.MouseMove, QPointF(900, 650),
                    Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
app.sendEvent(overlay, move)
app.processEvents()
check("A2. 拖选进行中（提示已隐藏）", overlay._selecting and not overlay._hint_visible)

release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(900, 650),
                      Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
app.sendEvent(overlay, release)
app.processEvents()

c = captured.get("pix")
_sx, _sy = int(round(300 * _dpr)), int(round(200 * _dpr))
_exp_w = max(1, min(int(round(600 * _dpr)), _fw - _sx))
_exp_h = max(1, min(int(round(450 * _dpr)), _fh - _sy))
check(f"A3. 裁剪结果尺寸（逻辑600x450 × dpr{_dpr}，含越界钳制）",
      c is not None and abs(c.width() - _exp_w) <= 1 and abs(c.height() - _exp_h) <= 1,
      f"got={c.width()}x{c.height()} expect={_exp_w}x{_exp_h}")
check("A4. 遮罩先于编辑器关闭（防盖编辑器 bug）",
      not overlay.isVisible(), "overlay visible after release")
check("A5. on_finished 已触发且只触发一次", events == ["finished"], str(events))

# ============ 场景 B：Esc 取消 ============
print("--- 场景 B：Esc 取消 ---")
tool2 = ScreenshotTool()
events2 = []
tool2.on_finished = lambda: events2.append("f")
tool2._finish = lambda pm: captured.__setitem__("pix", pm)
tool2.capture_region()
ov2 = tool2._overlay
check("B1. 遮罩弹出", ov2.isVisible())
from PySide6.QtGui import QKeyEvent
esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
app.sendEvent(ov2, esc)
app.processEvents()
check("B2. Esc 后遮罩关闭 + on_finished 触发",
      not ov2.isVisible() and events2 == ["f"])

# ============ 场景 C：全屏截图 ============
print("--- 场景 C：全屏截图 ---")
from unittest.mock import patch
from config.settings_manager import settings

tool3 = ScreenshotTool()
events3 = []
tool3.on_finished = lambda: events3.append("f")
old_show = settings.get("screenshot.show_editor", True)
settings.set("screenshot.show_editor", False)
with patch.object(ScreenshotTool, "save_pixmap", staticmethod(lambda im: Path("x.png"))), \
     patch.object(ScreenshotTool, "maybe_copy_to_clipboard"):
    tool3.capture_fullscreen()
settings.set("screenshot.show_editor", old_show)
check("C1. 全屏裁剪 + on_finished 触发一次", events3 == ["f"], f"events={events3}")

# ============ 场景 D：提示文字绘制不崩 ============
print("--- 场景 D：遮罩提示渲染 ---")
tool4 = ScreenshotTool()
tool4.capture_region()
ov4 = tool4._overlay
try:
    ov4.grab()  # 强制重绘含提示文字
    check("D1. 含提示文字的遮罩可渲染", True)
except Exception as e:
    check("D1. 含提示文字的遮罩可渲染", False, str(e))
ov4.close()
app.processEvents()

fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
for f in fails:
    print("  FAILED:", f[0], f[2])
sys.exit(1 if fails else 0)
