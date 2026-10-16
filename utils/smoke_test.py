"""无头功能测试 v2（合成抓图，不依赖真实屏幕捕获）

覆盖：
  1. 动画引擎帧加载
  2. 热键解析（ctrl+alt+a -> mods/vk）
  3. freeze-first 区域截图流程：合成抓图 + DPI 裁剪数学 + 边界钳制
  4. 遮罩渲染（widget.grab，不需要真实截屏）
  5. 编辑器保存 + 剪贴板
  6. show_editor=False 时的直接保存路径
  7. 窗口枚举（EnumWindows，不需要 BitBlt）
  8. 气泡
  9. 设置对话框：实例化 + get_settings + accept 保存链路
 10. 其他功能模块导入

注意：本机 agent 会话环境限制了 GDI 屏幕捕获（BitBlt 失败），
真实抓屏链路需由使用者在本机直接运行应用验收。
"""
import sys
import os
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QColor, QImage
from PySide6.QtCore import QRectF, QPointF

app = QApplication(sys.argv)

PASS = []


def ok(name):
    PASS.append(name)
    print(f"  [OK] {name}")


print("== 1. 动画引擎 ==")
from core.animation_engine import AnimationEngine, PetState, FRAME_DURATIONS
eng = AnimationEngine()
for s in PetState:
    print(f"  {s.value}: {len(eng._frames.get(s, []))} 帧")
# 待机只用睁眼帧白名单（idle_00/01），不再自动眨眼
assert len(eng._frames[PetState.IDLE]) >= 2
assert len(eng._frames[PetState.IDLE]) <= 2
assert len(eng._frames[PetState.WALK_LEFT]) >= 4
assert len(eng._frames[PetState.SIT]) >= 2
assert len(eng._frames[PetState.LIE]) >= 2
assert len(eng._frames[PetState.INTERACT]) >= 3
ok("动画引擎 6 状态帧加载")

print("== 2. 热键解析 ==")
from utils.native_hotkey import _parse, NativeHotkeyManager
mods, vk = _parse("ctrl+alt+a")
assert mods == (0x0001 | 0x0002) and vk == 0x41, (hex(mods), hex(vk))
mods2, vk2 = _parse("ctrl+alt+f5")
assert mods2 == 0x0003 and vk2 == 0x74
mgr = NativeHotkeyManager()
mgr.unregister_all()  # 未 attach 时不应报错
ok("热键解析 ctrl+alt+a / ctrl+alt+f5 + 未 attach 注销安全")

print("== 3. freeze-first 区域截图流程（合成抓图） ==")
from features.screenshot_tool import ScreenshotTool, ScreenshotOverlay, EditorDialog


def make_synthetic(w=2000, h=1500):
    """合成图：底色(100,150,200)，物理坐标 (500..600, 300..400) 放白色方块"""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(100, 150, 200))
    p = img
    for y in range(300, 400):
        for x in range(500, 600):
            p.setPixel(x, y, qrgb_white())
    return QPixmap.fromImage(img)


def qrgb_white():
    from PySide6.QtGui import qRgb
    return qRgb(255, 255, 255)


tool = ScreenshotTool()
DPR = 1.25
frozen = make_synthetic()
tool._frozen = frozen
tool._frozen_dpr = DPR

# 3a. 正常选区：逻辑 (400,240,160,128) -> 物理 (500,300,200,160)，应包含白块
captured = {}
tool._finish = lambda pm: captured.update(pix=pm)  # 拦掉编辑器/保存
tool._on_region_selected(QRectF(400, 240, 160, 128))
crop = captured["pix"]
assert crop.width() == 200 and crop.height() == 160, (crop.width(), crop.height())
img = crop.toImage()
c = img.pixelColor(50, 50)   # 物理 (550, 350) 在白块内
assert (c.red(), c.green(), c.blue()) == (255, 255, 255), (c.red(), c.green(), c.blue())
c2 = img.pixelColor(50, 50)   # 物理 (550, 350) 在白块内（上一断言已覆盖）
c3 = img.pixelColor(195, 155)  # 物理 (695, 455) 白块外，应为底色
assert (c3.red(), c3.green(), c3.blue()) == (100, 150, 200), (c3.red(), c3.green(), c3.blue())
ok("DPI 裁剪数学：逻辑选区 x1.25 = 物理裁剪，内容正确")

# 3b. 边界钳制：选区超出冻结图范围（注意：冻结图一次性，需重新挂载）
tool._frozen = frozen
tool._frozen_dpr = DPR
tool._on_region_selected(QRectF(1900, 1400, 400, 300))  # 远超 2000x1500
crop2 = captured["pix"]
assert 0 < crop2.width() <= 200 and 0 < crop2.height() <= 150, (crop2.width(), crop2.height())
ok(f"边界钳制：越界选区裁到 {crop2.width()}x{crop2.height()}")

# 3c. _freeze_screen 的显示器矩形计算（不真抓，只验证几何）
screen = QApplication.primaryScreen()
geo = screen.geometry()
dpr_real = screen.devicePixelRatio() or 1.0
mon_expected = {
    "left": int(round(geo.x() * dpr_real)), "top": int(round(geo.y() * dpr_real)),
    "width": int(round(geo.width() * dpr_real)), "height": int(round(geo.height() * dpr_real)),
}
with patch.object(ScreenshotTool, "_to_pixmap", staticmethod(lambda shot: make_synthetic(800, 600))), \
     patch("mss.MSS") as MockMSS:
    inst = MockMSS.return_value.__enter__.return_value
    inst.grab.return_value = object()
    pm, dpr = tool._freeze_screen(screen)
    assert pm is not None
    called_mon = inst.grab.call_args[0][0]
    assert called_mon == mon_expected, (called_mon, mon_expected)
ok(f"冻结矩形计算：逻辑 {geo.width()}x{geo.height()} x{dpr_real} -> 物理 {mon_expected['width']}x{mon_expected['height']}")

# 3d. 抓屏失败时的友好降级（不抛异常、返回 None）
with patch("mss.MSS", side_effect=Exception("BitBlt boom")):
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mw:
        pm2, _ = tool._freeze_screen(screen)
        assert pm2 is None
        assert mw.called
ok("抓屏失败 -> 返回 None + 弹出友好提示（不崩溃）")

print("== 4. 遮罩渲染 ==")
overlay = ScreenshotOverlay(screen, frozen, DPR)
overlay.show()
rendered = overlay.grab()
assert not rendered.isNull() and rendered.width() > 0
overlay.close()
ok(f"遮罩渲染 OK ({rendered.width()}x{rendered.height()})")

print("== 5. 编辑器保存 + 剪贴板 ==")
from config.constants import SCREENSHOT_SAVE_DIR
dlg = EditorDialog(make_synthetic(600, 400))
with patch.object(ScreenshotTool, "maybe_copy_to_clipboard") as mc:
    dlg._on_save()
    assert mc.called
files = sorted(SCREENSHOT_SAVE_DIR.glob("screenshot_*.png"))
assert files, "截图未保存"
ok(f"编辑器保存 OK: {files[-1].name} ({files[-1].stat().st_size} bytes)")

print("== 6. show_editor=False 直接保存路径 ==")
from config.settings_manager import settings
tool2 = ScreenshotTool()  # 新实例，避免 3a 替换过的 _finish 实例属性
old_show = settings.get("screenshot.show_editor", True)
settings.set("screenshot.show_editor", False)
with patch.object(ScreenshotTool, "save_pixmap", staticmethod(lambda im: Path("x.png"))), \
     patch.object(ScreenshotTool, "maybe_copy_to_clipboard") as mc2:
    tool2._finish(make_synthetic(300, 200))
    assert mc2.called
settings.set("screenshot.show_editor", old_show)
ok("关闭编辑器时直接保存+复制")

print("== 7. 窗口枚举 ==")
wins = tool._enum_windows()
print(f"  枚举到 {len(wins)} 个窗口: {[w[1][:20] for w in wins[:5]]}")
assert len(wins) > 0
ok("窗口枚举")

print("== 8. 气泡 ==")
from core.pet_window import SpeechBubble, CLICK_PHRASES, GREET_PHRASES
bubble = SpeechBubble()
bubble.show_text("测试气泡文字", QPointF(500, 500))
assert bubble.isVisible()
bubble.close()
ok(f"气泡 OK, 点击语料 {len(CLICK_PHRASES)} 条, 问候语料 {len(GREET_PHRASES)} 条")

print("== 9. 设置对话框 ==")
from features.settings_dialog import SettingsDialog
sdlg = SettingsDialog()
s = sdlg.get_settings()
for k in ["hotkeys.toggle_pet", "hotkeys.screenshot_region", "pet.walk_speed",
          "general.auto_start", "screenshot.auto_copy_to_clipboard"]:
    assert k in s, k
with patch("PySide6.QtWidgets.QMessageBox.information"):
    sdlg.accept()  # 走保存链路（值来自 settings 本身，写回无害）
assert settings.get("hotkeys.screenshot_region") == "ctrl+alt+a"
sdlg.close()
ok("设置对话框：get_settings + accept 保存链路")

print("== 10. 其他功能模块导入 ==")
from features.clipboard_history import ClipboardHistoryDialog
from features.wallpaper_manager import WallpaperManager
from utils.native_hotkey import NativeHotkeyManager as _NHM
ok("clipboard/wallpaper/native_hotkey 全部导入 OK")

print(f"\n=== 全部 {len(PASS)} 项测试通过 ===")
