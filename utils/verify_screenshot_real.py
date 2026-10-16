# -*- coding: utf-8 -*-
"""截图链路真实环境验证（不 mock 抓屏）"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QGuiApplication

app = QApplication(sys.argv)

from features.screenshot_tool import ScreenshotTool, ScreenshotOverlay

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


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

# ---- 1. 冻结真实屏幕 ----
screen = tool._target_screen()
pixmap, dpr = tool._freeze_screen(screen)
check("1. 真实抓屏冻结", pixmap is not None and pixmap.width() > 0,
      f"pixmap={pixmap.width()}x{pixmap.height()} dpr={dpr} screen={screen.geometry().getRect()}")

# ---- 2. 遮罩创建与显示 ----
overlay = ScreenshotOverlay(screen, pixmap, dpr)
overlay.show()
app.processEvents()
check("2. 遮罩窗口可见", overlay.isVisible(),
      f"geo={overlay.geometry().getRect()}")

# ---- 3. 区域裁剪数学（真实数据）----
tool._frozen = pixmap
tool._frozen_dpr = dpr
captured = {}
tool._finish = lambda pm: captured.__setitem__("pix", pm)

# 逻辑选区 (200,150,600,400) → 物理（按实际 devicePixelRatio，兼容 100%/125%/150% 缩放）
tool._on_region_selected(QRectF(200, 150, 600, 400))
c = captured.get("pix")
_x, _y = int(round(200 * dpr)), int(round(150 * dpr))
exp_w = max(1, min(int(round(600 * dpr)), pixmap.width() - _x))
exp_h = max(1, min(int(round(400 * dpr)), pixmap.height() - _y))
check("3. 逻辑选区→物理裁剪尺寸",
      c is not None and abs(c.width() - exp_w) <= 1 and abs(c.height() - exp_h) <= 1,
      f"got={c.width()}x{c.height()} expect={exp_w}x{exp_h} (dpr={dpr})")

# 像素一致性：与直接 copy 对比（同样取整规则）
expect = pixmap.copy(_x, _y, exp_w, exp_h)
if c and expect:
    img1, img2 = c.toImage(), expect.toImage()
    diff = sum(1 for i in range(0, min(exp_w, 750), 37) for j in range(0, min(exp_h, 500), 29)
               if img1.pixel(i, j) != img2.pixel(i, j))
    check("4. 裁剪像素与直接copy一致", diff == 0, f"采样差异点={diff}")

# 边界钳制
tool._frozen = pixmap
tool._on_region_selected(QRectF(pixmap.width() / dpr - 100, pixmap.height() / dpr - 100, 500, 500))
c2 = captured.get("pix")
check("5. 越界选区钳制不崩", c2 is not None and c2.width() > 0 and c2.height() > 0,
      f"clamped={c2.width()}x{c2.height()}")

# ---- 6. 全屏截图链路 ----
captured.clear()
full_pix, full_dpr = tool._freeze_screen(screen)
tool._finish(full_pix)
check("6. 全屏冻结尺寸", full_pix.width() == pixmap.width() and full_pix.height() == pixmap.height(),
      f"{full_pix.width()}x{full_pix.height()}")

# ---- 7. 窗口截图枚举 ----
wins = tool._enum_windows()
check("7. 窗口枚举", len(wins) > 0, f"找到 {len(wins)} 个窗口")
if wins:
    hwnd, title, rect = wins[0]
    try:
        shot = tool._grab_rect(rect)
        pm = tool._to_pixmap(shot)
        check("8. 窗口抓取转QPixmap", pm.width() > 0 and pm.height() > 0,
              f"{title[:30]} -> {pm.width()}x{pm.height()}")
    except Exception as e:
        check("8. 窗口抓取转QPixmap", False, str(e))

# ---- 9. 保存链路 ----
out = BASE_DIR / "resources" / "test_crop.png"
if c:
    okk = c.save(str(out), "PNG")
    check("9. 裁剪图保存PNG", okk and out.exists() and out.stat().st_size > 1000,
          f"{out.stat().st_size if out.exists() else 0} bytes")

overlay.close()
app.processEvents()

fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
sys.exit(1 if fails else 0)
