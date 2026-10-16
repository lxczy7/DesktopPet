# -*- coding: utf-8 -*-
"""宠物动作节奏验证：静止状态「常驻帧 + 偶发小动作」+ 行为切换频率

背景：早期 IDLE/SIT/LIE 的帧是首尾相接循环播放的（每 0.9~2.6 秒一轮），
表现成"宠物一直重复同一个抽搐动作"，用户反馈非常不自然。
本套件锁定修复后的节奏契约，防止以后调参又调回抽搐。
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from core.animation_engine import (  # noqa: E402
    AnimationEngine, PetState, RESTING_STATES, FROZEN_STATES,
    GESTURE_GAP_SECONDS, FRAME_DURATIONS,
)
from core.pet_window import PetWindow  # noqa: E402
from config.settings_manager import settings  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(detail)) if detail else ""))


eng = AnimationEngine()
print("== 1. 静止状态：常驻帧 + 偶发小动作 ==")

# ---------- R1 IDLE 进入后停在第 0 帧，不自动播放 ----------
eng.set_state(PetState.IDLE, force=True)
check("R1. IDLE 进入后停在常驻帧(0)且帧定时器不转",
      eng._current_frame_index == 0 and not eng._timer.isActive(),
      f"index={eng._current_frame_index} timer={eng._timer.isActive()}")

# ---------- R2 已排好小动作 ----------
check("R2. IDLE 已排好下一次小动作",
      eng._gesture_timer.isActive(), f"active={eng._gesture_timer.isActive()}")

# ---------- R3 小动作间隔落在配置区间 ----------
lo, hi = GESTURE_GAP_SECONDS[PetState.IDLE]
rt = eng._gesture_timer.remainingTime()
check("R3. IDLE 小动作间隔落在 8~18 秒（松弛感，不是抽搐）",
      lo * 1000 - 200 <= rt <= hi * 1000 + 200, f"remaining={rt}ms 期望[{lo*1000},{hi*1000}]")

# ---------- R4 空闲空转不会推进帧（核心防抽搐）----------
for _ in range(40):
    eng._next_frame()
check("R4. 空闲时反复调用 _next_frame 也不推进帧（不再抽搐）",
      eng._current_frame_index == 0 and not eng._timer.isActive(),
      f"index={eng._current_frame_index}")

# ---------- R5 插播小动作 -> 演完自动回常驻帧 ----------
eng._play_gesture()
during = (eng._current_frame_index, eng._timer.isActive())
eng._next_frame()
after = (eng._current_frame_index, eng._timer.isActive(), eng._gesture_timer.isActive())
check("R5. 插播小动作播完自动回常驻帧并停住",
      during == (1, True) and after == (0, False, True),
      f"插播中={during} 演完={after}")

# ---------- R6 SIT / LIE 同样节奏 ----------
for st in (PetState.SIT, PetState.LIE):
    eng.set_state(st, force=True)
    enter = (eng._current_frame_index, eng._timer.isActive())
    eng._play_gesture()
    busy = eng._timer.isActive()
    eng._next_frame()
    back = (eng._current_frame_index, eng._timer.isActive())
    check(f"R6.{st.value} 常驻->插播->回位",
          enter == (0, False) and busy and back == (0, False),
          f"enter={enter} busy={busy} back={back}")

# ---------- R7 循环类状态不受影响 ----------
eng.set_state(PetState.WALK_LEFT, force=True)
seq = []
for _ in range(9):
    seq.append(eng._current_frame_index)
    eng._next_frame()
check("R7. 走路帧仍正常首尾相接循环",
      seq == [0, 1, 2, 3, 0, 1, 2, 3, 0], f"seq={seq}")

eng.set_state(PetState.INTERACT, force=True)
seq2 = []
for _ in range(4):
    seq2.append(eng._current_frame_index)
    eng._next_frame()
check("R8. 互动帧仍正常循环（不被常驻逻辑影响）",
      seq2 == [0, 1, 2, 0], f"seq={seq2}")

# ---------- R9 DRAG 冻结在常驻帧 ----------
eng.set_state(PetState.DRAG, force=True)
seq3 = []
for _ in range(5):
    seq3.append(eng._current_frame_index)
    eng._next_frame()
check("R9. 拖拽帧冻结在第 0 帧（不再站直/歪头狂闪）",
      seq3 == [0, 0, 0, 0, 0] and not eng._timer.isActive(), f"seq={seq3}")

# ---------- R10 换状态会取消旧的小动作排程 ----------
eng.set_state(PetState.IDLE, force=True)
was = eng._gesture_timer.isActive()
eng.set_state(PetState.WALK_RIGHT)
check("R10. 切换状态时取消上一个小动作排程",
      was and not eng._gesture_timer.isActive(),
      f"切换前={was} 切换后={eng._gesture_timer.isActive()}")

# ---------- R11 duration=0 常驻语义仍成立 ----------
eng.set_state(PetState.SIT, duration=0, force=True)
check("R11. set_state(duration=0) 停掉残留状态计时器（常驻）",
      not eng._state_timer.isActive(),
      f"state_timer={eng._state_timer.isActive()}")

# ---------- R12 FRAME_DURATIONS 契约 ----------
ok_dur = all(
    FRAME_DURATIONS[s][0] == 0 for s in RESTING_STATES if s in FRAME_DURATIONS
)
check("R12. 静止类状态第 0 帧时长标为 0（常驻占位）", ok_dur,
      str({s.value: FRAME_DURATIONS.get(s) for s in RESTING_STATES}))

check("R13. FROZEN_STATES 覆盖 DRAG", PetState.DRAG in FROZEN_STATES,
      str([s.value for s in FROZEN_STATES]))

print()
print("== 2. 行为时钟：切换频率 ==")

win = PetWindow()

# ---------- R14 行为间隔按状态匹配 ----------
win._animation_engine.set_state(PetState.LIE, force=True)
win._schedule_next_behavior()
rt = win._behavior_timer.remainingTime()
lo = int(settings.get("pet.lie_duration_min", 9000))
hi = int(settings.get("pet.lie_duration_max", 18000))
check("R14. 躺姿行为间隔落在 lie 区间（久躺不发神经）",
      lo - 200 <= rt <= hi + 200, f"remaining={rt}ms 期望[{lo},{hi}]")

win._animation_engine.set_state(PetState.SIT, force=True)
win._schedule_next_behavior()
rt2 = win._behavior_timer.remainingTime()
lo2 = int(settings.get("pet.sit_duration_min", 6000))
hi2 = int(settings.get("pet.sit_duration_max", 12000))
check("R15. 坐姿行为间隔落在 sit 区间",
      lo2 - 200 <= rt2 <= hi2 + 200, f"remaining={rt2}ms 期望[{lo2},{hi2}]")

win._animation_engine.set_state(PetState.IDLE, force=True)
win._schedule_next_behavior()
rt3 = win._behavior_timer.remainingTime()
lo3 = int(settings.get("pet.idle_interval_min", 6000))
hi3 = int(settings.get("pet.idle_interval_max", 14000))
check("R16. 待机行为间隔落在 idle 区间（≥6 秒，不再 1~3 秒一跳）",
      lo3 - 200 <= rt3 <= hi3 + 200, f"remaining={rt3}ms 期望[{lo3},{hi3}]")

check("R17. 待机最短停留不低于 5 秒（防多动症回归）", lo3 >= 5000, f"idle_min={lo3}")
check("R17b. 坐姿最短停留不低于 5 秒", lo2 >= 5000, f"sit_min={lo2}")
check("R17c. 躺姿最短停留不低于 8 秒", lo >= 8000, f"lie_min={lo}")

# ---------- R18 走路超时不死锁 ----------
calls = []
orig_decide = win._decide_next_behavior
win._decide_next_behavior = lambda: calls.append(1)
try:
    win._is_moving = True
    win._animation_engine.set_state(PetState.WALK_LEFT, duration=80, force=True)
    win._animation_engine._on_state_duration_end()      # 模拟走路超时
    ok_dead = (not win._is_moving) and len(calls) == 1 and \
              win._animation_engine.get_state() == PetState.IDLE
finally:
    win._decide_next_behavior = orig_decide
check("R18. 走路超时后清理移动标志并重排行为（修掉行为系统死锁）",
      ok_dead, f"is_moving={win._is_moving} 决策次数={len(calls)}")

# ---------- R19 state_finished 信号 ----------
fired = []
win._animation_engine.state_finished.connect(lambda: fired.append(1))
win._animation_engine.set_state(PetState.INTERACT, duration=60, force=True)
win._animation_engine._on_state_duration_end()
check("R19. 动作自然结束会发出 state_finished 信号",
      len(fired) == 1, f"发出次数={len(fired)}")

# ---------- R20 拖动中不抢控制权 ----------
win._mood_lock = True
before_state = win._animation_engine.get_state()
win._animation_engine.state_finished.emit()
check("R20. 情绪锁定期间 state_finished 不会抢走状态",
      win._animation_engine.get_state() == before_state,
      f"{before_state.value} -> {win._animation_engine.get_state().value}")
win._mood_lock = False

print()
total = len(RESULTS)
passed = sum(1 for _, ok in RESULTS if ok)
print(f"===== {passed}/{total} 通过 =====")
sys.exit(0 if passed == total else 1)
