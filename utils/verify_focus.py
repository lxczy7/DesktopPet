# -*- coding: utf-8 -*-
"""专注 / 呼吸 / 趣味互动 验证

背景：宣哥要求参考 openpets 开源桌宠的官方插件区，加入
1) 番茄钟专注（focus-buddy）
2) 4-7-8 呼吸放松引导（anxiety-aid-tools）
3) 趣味小互动：今日运势 / 魔法八球 / 情绪打卡
4) 状态驱动情绪：宠物能表达开心/疲惫/专注等，而不只是待机走路

本脚本锁死这些能力，全部离屏运行、不依赖真实网络与人工点击。
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from PySide6.QtCore import QPoint  # noqa: E402
from core.pet_window import PetWindow, MOOD_PRESETS  # noqa: E402
from core.animation_engine import PetState  # noqa: E402
from features.pomodoro import PomodoroService  # noqa: E402
from features.breathing import BreathingService, PHASES  # noqa: E402
from features.fun_interactions import (  # noqa: E402
    FunInteractions, FORTUNES, EIGHT_BALL, MOOD_RESPONSE)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# ============ 准备：宠物窗口（离屏）============
pet = PetWindow()

# ---------- F1 新信号 ----------
try:
    sigs = ["pomodoro_requested", "breathing_requested", "fun_requested"]
    ok1 = all(hasattr(pet, s) for s in sigs)
    detail1 = ""
except Exception as e:
    ok1, detail1 = False, str(e)
check("F1. PetWindow 提供 pomodoro/breathing/fun 三个信号", ok1, detail1)

# ---------- F2 右键菜单结构 ----------
top = [a.text() for a in pet._context_menu.actions()]
menus = {a.menu().title(): [x.text() for x in a.menu().actions()]
         for a in pet._context_menu.actions() if a.menu()}
focus_items = menus.get("🎯 专注", [])
breath_items = menus.get("🫁 呼吸放松", [])
fun_items = menus.get("🎲 趣味", [])
check("F2. 右键菜单含「专注/呼吸/趣味」三个子菜单",
      "🎯 专注" in menus and "🫁 呼吸放松" in menus and "🎲 趣味" in menus,
      str(list(menus.keys())))
check("F2b. 专注菜单有 25/45/60 三档 + 暂停/休息/结束",
      any("25" in t for t in focus_items) and any("45" in t for t in focus_items)
      and any("60" in t for t in focus_items)
      and any("暂停" in t for t in focus_items)
      and any("结束" in t for t in focus_items),
      str(focus_items))
check("F2c. 呼吸菜单有 5 轮 / 10 轮 / 结束引导",
      any("5 轮" in t for t in breath_items) and any("10 轮" in t for t in breath_items)
      and any("结束" in t for t in breath_items),
      str(breath_items))
check("F2d. 趣味菜单有三项互动",
      len(fun_items) == 3 and any("运势" in t for t in fun_items)
      and any("八球" in t for t in fun_items) and any("情绪" in t for t in fun_items),
      str(fun_items))

# ---------- F3 托盘菜单也挂上了入口 ----------
tray_texts = [a.text() for a in pet._tray_icon.contextMenu().actions()]
check("F3. 托盘菜单含专注 / 呼吸 / 运势入口",
      any("专注" in t for t in tray_texts) and any("呼吸" in t for t in tray_texts)
      and any("运势" in t for t in tray_texts),
      str(tray_texts))

# ================= 情绪表达 =================

# ---------- F4 express 映射到动画状态 ----------
pet.express("cheer", "")
check("F4. express('cheer') 切到 interact 帧且不锁行为",
      pet._animation_engine.get_state() == PetState.INTERACT and not pet.is_mood_locked(),
      pet._animation_engine.get_state().value)

pet.express("tired", "")
check("F4b. express('tired') 切到 lie 帧（躺下歇会儿）",
      pet._animation_engine.get_state() == PetState.LIE,
      pet._animation_engine.get_state().value)

# ---------- F5 focused 锁定行为调度 ----------
pet.express("focused")
locked_ok = pet.is_mood_locked() and pet._animation_engine.get_state() == PetState.SIT
# 锁定期间，随机行为调度不应改变状态
pet._is_dragging = False
pet._falling = False
pet._decide_next_behavior()
check("F5. express('focused') 锁定行为，随机调度不改变专注坐姿",
      locked_ok and pet._animation_engine.get_state() == PetState.SIT
      and not pet._is_moving,
      f"lock={pet.is_mood_locked()} state={pet._animation_engine.get_state().value}")

# ---------- F6 release_mood 解锁 ----------
pet.release_mood()
check("F6. release_mood 解除锁定并恢复行为调度",
      not pet.is_mood_locked(), f"lock={pet.is_mood_locked()}")

# ---------- F7 动画引擎：duration=0 常驻不被残留计时器抢走 ----------
pet._animation_engine.set_state(PetState.INTERACT)          # 起一个带时长的状态
pet._animation_engine.set_state(PetState.SIT, duration=0, force=True)
check("F7. set_state(duration=0) 停掉残留状态计时器（常驻语义）",
      not pet._animation_engine._state_timer.isActive(),
      f"state_timer.active={pet._animation_engine._state_timer.isActive()}")

# ================= 番茄钟 =================

pom = PomodoroService(pet)
finished_events = []
pom.phase_finished.connect(lambda ph: finished_events.append(ph))
stopped_events = []
pom.stopped.connect(lambda: stopped_events.append(True))

# ---------- F8 开始专注 ----------
pom.start_focus(25)
check("F8. start_focus(25) 进入 focus 且剩余 25 分钟、宠物被锁定陪坐",
      pom.is_running() and pom.current_phase() == "focus" and pom._remaining == 1500
      and pet.is_mood_locked()
      and pet._animation_engine.get_state() == PetState.SIT,
      f"phase={pom.current_phase()} remain={pom._remaining} lock={pet.is_mood_locked()}")

# ---------- F9 倒计时推进 ----------
before = pom._remaining
pom._tick()
check("F9. 每秒 tick 递减剩余时间", pom._remaining == before - 1,
      f"{before} -> {pom._remaining}")

# ---------- F10 暂停期间不倒计时 ----------
pom.toggle_pause()
frozen = pom._remaining
pom._tick()
check("F10. 暂停后 tick 不减少（倒计时冻结）",
      pom.is_paused() and pom._remaining == frozen,
      f"paused={pom.is_paused()} remain={pom._remaining}")
pom.toggle_pause()
check("F10b. 再次 toggle 恢复计时", not pom.is_paused(), f"paused={pom.is_paused()}")

# ---------- F11 专注走完 -> 自动进入休息 ----------
pom._remaining = 1
pom._tick()
check("F11. 专注走完自动进入 break 阶段并记录番茄数",
      pom.current_phase() == "break" and pom._remaining == 300
      and pom.finished_count() == 1 and finished_events == ["focus"],
      f"phase={pom.current_phase()} remain={pom._remaining} done={pom.finished_count()}")
check("F11b. 进入休息时解除宠物行为锁（可以自由活动）",
      not pet.is_mood_locked(), f"lock={pet.is_mood_locked()}")

# ---------- F12 休息走完 -> 会话结束 ----------
pom._remaining = 1
pom._tick()
check("F12. 休息走完自动结束会话并解锁宠物",
      not pom.is_running() and pom.current_phase() == ""
      and finished_events == ["focus", "break"] and stopped_events,
      f"finished={finished_events} stopped={len(stopped_events)}")

# ---------- F13 跳过 / 中途结束 ----------
pom.start_focus(45)
pom.skip_to_break()
ok13 = pom.current_phase() == "break"
pom.stop()
check("F13. skip_to_break 直接跳到休息；stop 结束会话",
      ok13 and not pom.is_running() and not pet.is_mood_locked(),
      f"skip_ok={ok13} running={pom.is_running()} lock={pet.is_mood_locked()}")

# ---------- F14 status_text ----------
pom.start_focus(25)
s14 = pom.status_text()
pom.stop(silent=True)
check("F14. status_text 输出阶段/剩余/番茄数",
      "专注" in s14 and "25:00" in s14 and "个番茄" in s14, s14)

# ================= 呼吸引导 =================

br = BreathingService(pet)
br_phases = []
br.finished.connect(lambda: br_phases.append("finished"))
br.phase_changed.connect(lambda ph, s: br_phases.append(ph))

# ---------- F15 启动 ----------
br.start(2)
check("F15. start(2) 从「吸气 4 秒」开始且宠物进入专注陪伴",
      br.is_running() and br.current_phase() == "inhale" and br._remaining == 4
      and pet.is_mood_locked(),
      f"phase={br.current_phase()} remain={br._remaining} lock={pet.is_mood_locked()}")

# ---------- F16 阶段推进顺序 ----------
for _ in range(4):       # 吸气 4s 走完 -> 屏息
    br._tick()
after_inhale = (br.current_phase(), br._remaining)
for _ in range(7):       # 屏息 7s 走完 -> 呼气
    br._tick()
after_hold = (br.current_phase(), br._remaining)
check("F16. 阶段按 吸气4s → 屏息7s → 呼气8s 推进",
      after_inhale == ("hold", 7) and after_hold == ("exhale", 8),
      f"吸气后={after_inhale} 屏息后={after_hold}")

# ---------- F17 一轮结束进入下一轮 ----------
for _ in range(8):       # 呼气 8s 走完 -> 第 2 轮吸气
    br._tick()
check("F17. 一轮结束回到吸气并进入第 2 轮",
      br.current_phase() == "inhale" and br._round_index == 2 and br._remaining == 4,
      f"round={br._round_index} phase={br.current_phase()} remain={br._remaining}")

# ---------- F18 跑完全部轮数 -> finished + 解锁 ----------
for _ in range(4 + 7 + 8):
    br._tick()
check("F18. 轮数跑完触发 finished、解锁宠物并复位",
      not br.is_running() and "finished" in br_phases and not pet.is_mood_locked(),
      f"events={br_phases} running={br.is_running()} lock={pet.is_mood_locked()}")

# ---------- F19 中途结束 ----------
br.start(5)
br.stop()
check("F19. stop 中途结束呼吸练习并解锁",
      not br.is_running() and not pet.is_mood_locked(),
      f"running={br.is_running()} lock={pet.is_mood_locked()}")

# ---------- F20 status_text ----------
br.start(5)
s20 = br.status_text()
br.stop(silent=True)
check("F20. 呼吸 status_text 含轮次与阶段",
      "1/5" in s20 and "吸气" in s20, s20)

# ================= 趣味互动 =================

fun = FunInteractions(pet)

# ---------- F21 今日运势同一天固定 ----------
t1 = fun.daily_fortune()
t2 = fun.daily_fortune()
check("F21. 今日运势同一天多次点击返回同一条",
      bool(t1) and t1 == t2 and t1 in FORTUNES, t1)

# ---------- F22 跨天重新抽签 ----------
fun._fortune_cache = ("2000-01-01", "旧签")
t3 = fun.daily_fortune()
check("F22. 换一天会重新抽签", t3 != "旧签" and t3 in FORTUNES, t3)

# ---------- F23 魔法八球 ----------
with patch("features.fun_interactions.QInputDialog.getText",
           return_value=("今天会顺利吗", True)):
    ans = fun.magic_8_ball()
check("F23. 魔法八球返回预设回答之一",
      ans in EIGHT_BALL, ans)

# ---------- F24 取消输入不应给答案 ----------
with patch("features.fun_interactions.QInputDialog.getText",
           return_value=("", False)):
    ans_cancel = fun.magic_8_ball()
check("F24. 取消输入时不返回回答（不打扰）", ans_cancel == "", repr(ans_cancel))

# ---------- F25 情绪打卡 ----------
# 「不太好」映射到 tired -> lie 帧（躺下），区分度最强
with patch("features.fun_interactions.QInputDialog.getItem",
           return_value=("不太好 😔", True)):
    picked = fun.mood_checkin()
check("F25. 情绪打卡选中「不太好」后切到 lie 帧陪着你",
      picked == "不太好 😔"
      and pet._animation_engine.get_state() == PetState.LIE,
      f"picked={picked} state={pet._animation_engine.get_state().value}")

# ---------- F26 情绪映射表完整性 ----------
check("F26. 情绪打卡 5 个选项都有对应情绪映射",
      all(m in MOOD_RESPONSE for m in
          ["很好 😄", "还行 🙂", "一般 😐", "有点累 😮‍💨", "不太好 😔"])
      and all(MOOD_RESPONSE[m][0] in MOOD_PRESETS for m in MOOD_RESPONSE),
      str({k: v[0] for k, v in MOOD_RESPONSE.items()}))

# ---------- F27 气泡停留时长可配 ----------
pet._bubble.show_text("倒计时 25:00", QPoint(100, 100), duration=5000)
ok27 = pet._bubble._hide_timer.isActive() and pet._bubble._hide_timer.interval() == 5000
pet._bubble.show_text("常驻", QPoint(100, 100), duration=0)
ok27b = not pet._bubble._hide_timer.isActive()
check("F27. 气泡支持自定义停留时长（duration<=0 表示常驻）",
      ok27 and ok27b, f"5秒={ok27} 常驻={ok27b}")

# ================= 主程序接线 =================

try:
    import main as main_mod
    from types import SimpleNamespace

    calls = {}

    class _FakePet:
        def notify(self, t, m):
            calls["notify"] = (t, m)

        def speak(self, t, **kw):
            calls["speak"] = t

        def express(self, mood, text="", **kw):
            calls["express"] = mood

        def release_mood(self):
            calls["release"] = True

    fs = SimpleNamespace(
        _pet_window=_FakePet(),
        _pomodoro=PomodoroService(_FakePet()),
        _breathing=BreathingService(_FakePet()),
        _fun=FunInteractions(_FakePet()),
    )
    err = ""
    with patch("PySide6.QtWidgets.QMessageBox.warning") as mw:
        try:
            main_mod.DesktopPetApp._handle_pomodoro(fs, "status", 0)
            main_mod.DesktopPetApp._handle_breathing(fs, "start", 5)
            main_mod.DesktopPetApp._handle_fun(fs, "fortune")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        if mw.called:
            err = err or f"弹出了错误框: {mw.call_args}"
    check("F28. 主程序三个 handler 均不抛异常",
          not err and "notify" in calls, err or str(list(calls.keys())))
except Exception as e:
    check("F28. 主程序三个 handler 均不抛异常", False, f"{type(e).__name__}: {e}")

# ---------- 收尾 ----------
try:
    pet.close()
except Exception:
    pass

fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
sys.exit(1 if fails else 0)
