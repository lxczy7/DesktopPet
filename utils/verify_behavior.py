"""新行为验证：宠物尺寸 / 视线朝向 / 拖拽下落弹跳
（对照 openpets 的 motion-engine 与 gaze 设计做的移植）
"""
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPoint

app = QApplication(sys.argv)

import core.pet_window as pw
from core.animation_engine import PetState

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)) if detail else ""))


# 用假光标替换真实 QCursor.pos()，让视线逻辑可控
class FakeCursor:
    _pos = QPoint(0, 0)

    @staticmethod
    def pos():
        return FakeCursor._pos


real_cursor = pw.QCursor
pw.QCursor = FakeCursor

win = pw.PetWindow()
win.show()
win._animation_engine.set_state(PetState.IDLE, force=True)

# ---------- 1. 宠物尺寸实时调整 ----------
print("== 1. 尺寸调整 ==")
win.apply_pet_size(120)
check("1a. 窗口尺寸变为 120", win.width() == 120 and win.height() == 120, f"{win.width()}x{win.height()}")
check("1b. _pet_size 同步", win._pet_size == 120)
center_before = win.geometry().center()
win.apply_pet_size(80)
check("1c. 改尺寸后中心不跳", abs(win.geometry().center().x() - center_before.x()) <= 2,
      f"dx={win.geometry().center().x() - center_before.x()}")
check("1d. 下限保护（传 5 -> 40）", (win.apply_pet_size(5), win.width() == 40)[1], f"{win.width()}")

# 恢复 90 便于后续测试
win.apply_pet_size(90)

# ---------- 2. 视线朝向（openpets gaze 移植）----------
print("== 2. 视线朝向 ==")
win._animation_engine.set_state(PetState.IDLE, force=True)
win.move(800, 600)
c = win.geometry().center()

FakeCursor._pos = QPoint(c.x() - 300, c.y())   # 鼠标在宠物左侧
win._gaze_last_flip = 0.0                      # 视为距上次翻转已过去很久（绕过冷却）
win._gaze_tick()
check("2a. 鼠标在左 -> 朝左（翻转）", win._gaze_flip is True, f"flip={win._gaze_flip}")

FakeCursor._pos = QPoint(c.x() + 300, c.y())   # 鼠标在右侧
win._gaze_last_flip = 0.0                      # 同样绕过冷却，单独验证方向判定
win._gaze_tick()
check("2b. 鼠标在右 -> 恢复正常朝向", win._gaze_flip is False, f"flip={win._gaze_flip}")

FakeCursor._pos = QPoint(c.x() + 10, c.y())    # 死区内，保持不变
before = win._gaze_flip
win._gaze_tick()
check("2c. 死区内不抖动", win._gaze_flip == before, f"flip={win._gaze_flip}")

# 翻转冷却：刚翻过就反向移动鼠标，不应立刻横跳（防"抽搐"）
win._gaze_flip = False
win._gaze_last_flip = time.monotonic()         # 模拟"刚刚翻过"
FakeCursor._pos = QPoint(c.x() - 300, c.y())
win._gaze_tick()
check("2c2. 翻转冷却期内不立即反向横跳", win._gaze_flip is False, f"flip={win._gaze_flip}")
win._gaze_last_flip = 0.0                      # 冷却结束后可以正常翻
win._gaze_tick()
check("2c3. 冷却结束后可正常翻转", win._gaze_flip is True, f"flip={win._gaze_flip}")

# 走动状态下不应翻转
win._gaze_flip = True
win._animation_engine.set_state(PetState.WALK_LEFT, force=True)
win._gaze_tick()
check("2d. 行走时恢复朝向", win._gaze_flip is False, f"flip={win._gaze_flip}")

# 拖拽中不干涉
win._animation_engine.set_state(PetState.IDLE, force=True)
win._gaze_flip = True
win._is_dragging = True
FakeCursor._pos = QPoint(c.x() + 300, c.y())
win._gaze_tick()
check("2e. 拖拽中不变朝向", win._gaze_flip is True)

win._is_dragging = False
win._gaze_flip = False

# ---------- 3. 拖拽下落 + 弹跳（openpets gravity 移植）----------
print("== 3. 下落弹跳 ==")
win._animation_engine.set_state(PetState.IDLE, force=True)
win._update_current_screen()
geo = win._current_screen.availableGeometry()
floor = geo.bottom() - win.height()

win.move(900, geo.top() + 120)      # 从高处松手
win._start_fall()
check("3a. 进入下落状态", win._falling is True)
check("3b. 下落时不接受行走指令", win._animation_engine.get_state() == PetState.DRAG)

y0 = win.pos().y()
win._physics_tick()
check("3c. 首帧向下加速", win.pos().y() > y0, f"{y0} -> {win.pos().y()}")

# 模拟循环直到停稳（加最大步数保护）
bounce_seen = 0
prev_vy = win._vy
steps = 0
while win._falling and steps < 2000:
    win._physics_tick()
    if win._vy < 0 and prev_vy > 0:      # 速度由正转负 = 发生一次弹跳
        bounce_seen += 1
    prev_vy = win._vy
    steps += 1

check("3d. 落地停稳（不再下落）", not win._falling, f"steps={steps}")
check("3e. 精确停在地面线", abs(win.pos().y() - floor) <= 2, f"y={win.pos().y()} floor={floor}")
check("3f. 至少弹跳 1 次", bounce_seen >= 1, f"bounces={bounce_seen}")
# 落地后 _decide_next_behavior() 会按权重随机挑下一个行为
# （IDLE 45% / SIT 15% / LIE 15% / walk 25%），因此只要是合法的"非落体"状态即算通过
_after = win._animation_engine.get_state()
check("3g. 停稳后回到行为循环（非 DRAG/INTERACT 悬挂态）",
      _after not in (PetState.DRAG, PetState.INTERACT), _after.value)

# ---------- 4. 下落中 _update_position 不抢位置 ----------
print("== 4. 单写者不冲突 ==")
win.move(900, geo.top() + 100)
win._start_fall()
y_before = win.pos().y()
win._update_position()                 # 模拟移动定时器同时触发
check("4a. 下落中行走逻辑被屏蔽", win.pos().y() == y_before, f"y={win.pos().y()}")
win._falling = False
win._physics_timer.stop()

# ---------- 5. 双击原地起跳 ----------
print("== 5. 原地起跳 ==")
win._animation_engine.set_state(PetState.IDLE, force=True)
win._update_current_screen()
win.move(700, geo.bottom() - 320)          # 悬在半空起跳
y_start = win.pos().y()
win._start_jump()
check("5a. 进入跳跃状态", win._falling is True)
check("5b. 初速度向上（负）", win._vy < 0, f"vy={win._vy}")

peak = y_start
steps = 0
while win._falling and steps < 2000:
    win._physics_tick()
    peak = min(peak, win.pos().y())
    steps += 1
check("5c. 确实跳起来了（最高点高于起点）", peak < y_start - 15, f"起点={y_start} 最高={peak}")
check("5d. 落回地面线", abs(win.pos().y() - floor) <= 2, f"y={win.pos().y()} floor={floor}")
check("5e. 跳跃结束回待机", not win._falling)

# ---------- 6. 配置键存在 ----------
print("== 6. 配置 ==")
from config.settings_manager import settings
check("6a. gaze_follow 配置存在", settings.get("pet.gaze_follow") is True)

# 收尾
win._gaze_timer.stop()
win._physics_timer.stop()
win._move_timer.stop()
win._behavior_timer.stop()
win._greet_timer.stop()
win.hide()

passed = sum(1 for _, ok in RESULTS if ok)
print(f"\n===== {passed}/{len(RESULTS)} PASS =====")
if passed != len(RESULTS):
    for n, ok in RESULTS:
        if not ok:
            print("  FAILED:", n)
    sys.exit(1)
sys.exit(0)
