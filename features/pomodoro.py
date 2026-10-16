# -*- coding: utf-8 -*-
"""番茄钟专注服务

参考 openpets 官方插件 focus-buddy 的设计：
- 专注 / 休息两段式状态机，专注结束自动进入休息
- 宠物全程陪着（专注时坐下不动，休息时恢复自由活动）
- 用宠物气泡当倒计时面板（每秒刷新，不再固定 2.5 秒淡出）

与其他模块的关系：
- 只管"计时 + 播报"，不直接碰窗口；通过 pet_window 的
  speak / notify / express / release_mood 接口表达。
- 专注期间调用 express("focused") 锁定随机行为，避免宠物走神跑掉。
"""

import random

from PySide6.QtCore import QObject, QTimer, Signal

# 专注时长选项（分钟）——与 openpets focus-buddy 的 25/45/60 对齐
FOCUS_CHOICES = (25, 45, 60)
DEFAULT_FOCUS_MINUTES = 25
DEFAULT_BREAK_MINUTES = 5

START_PHRASES = [
    "好，开始专心做事吧，我陪着你～",
    "专注模式启动！加油鸭",
    "这段时间交给我看着，你专心就好",
    "开工啦，别分心哦",
]

BREAK_START_PHRASES = [
    "休息时间到，起来动一动～",
    "歇会儿吧，看看远处放松眼睛",
    "伸个懒腰，喝口水~",
    "休息一下，我陪你发发呆",
]

FOCUS_DONE_PHRASES = [
    "一轮专注完成，太厉害啦！",
    "又搞定一个番茄，休息下吧～",
    "专注结束，辛苦咯！",
]

BREAK_DONE_PHRASES = [
    "休息好了，要不要再来一轮？",
    "精神恢复啦，继续加油！",
]


class PomodoroService(QObject):
    """番茄钟：专注 N 分钟 → 休息 M 分钟"""

    phase_changed = Signal(str, int)   # (phase, 剩余秒数)
    phase_finished = Signal(str)       # 刚结束的阶段 "focus" / "break"
    stopped = Signal()

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet = pet_window
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._phase = None            # None / "focus" / "break"
        self._remaining = 0           # 剩余秒数
        self._paused = False
        self._finished_focus = 0      # 本次会话完成的番茄数
        self._focus_minutes = DEFAULT_FOCUS_MINUTES
        self._break_minutes = DEFAULT_BREAK_MINUTES

    # ---------------- 对外接口 ----------------

    def is_running(self) -> bool:
        return bool(self._phase) and self._remaining > 0

    def is_paused(self) -> bool:
        return self._paused

    def current_phase(self) -> str:
        return self._phase or ""

    def finished_count(self) -> int:
        return self._finished_focus

    def start_focus(self, minutes: int = None) -> None:
        self._focus_minutes = int(minutes or DEFAULT_FOCUS_MINUTES)
        self._enter_phase("focus", self._focus_minutes)

    def start_break(self, minutes: int = None) -> None:
        self._break_minutes = int(minutes or DEFAULT_BREAK_MINUTES)
        self._enter_phase("break", self._break_minutes)

    def toggle_pause(self) -> bool:
        """暂停 / 继续；返回暂停后的状态（True=已暂停）"""
        if not self._phase:
            self._say("现在没有进行中的专注哦")
            return False
        self._paused = not self._paused
        self._refresh_bubble()
        return self._paused

    def skip_to_break(self) -> None:
        """跳过剩余专注时间，直接进入休息"""
        if self._phase == "focus":
            self._say("好，直接去休息～")
            self._complete_phase()
        elif self._phase == "break":
            self._say("休息结束，回来继续吧")
            self._complete_phase()
        else:
            self._say("现在没有进行中的专注哦")

    def stop(self, silent: bool = False) -> None:
        """结束整个专注会话"""
        had_phase = bool(self._phase)
        self._timer.stop()
        self._phase = None
        self._remaining = 0
        self._paused = False
        try:
            self._pet.release_mood()
        except Exception:
            pass
        if had_phase and not silent:
            self._say("专注结束，辛苦啦～")
        self.stopped.emit()

    def status_text(self) -> str:
        if not self._phase:
            return "当前没有进行中的专注"
        mm, ss = divmod(self._remaining, 60)
        label = "专注" if self._phase == "focus" else "休息"
        state = "已暂停" if self._paused else "进行中"
        return f"{label}{state}，剩余 {mm:02d}:{ss:02d}（已完成 {self._finished_focus} 个番茄）"

    # ---------------- 内部 ----------------

    def _say(self, text: str) -> None:
        try:
            self._pet.speak(text)
        except Exception:
            pass

    def _enter_phase(self, phase: str, minutes: int) -> None:
        self._phase = phase
        self._remaining = max(1, int(minutes)) * 60
        self._paused = False
        self._timer.start()

        if phase == "focus":
            try:
                self._pet.express("focused")   # 锁定行为：坐下陪着你
            except Exception:
                pass
            self._notify("🎯 专注开始", f"接下来 {minutes} 分钟专心做事，我陪着你～")
            self._say(random.choice(START_PHRASES))
        else:
            try:
                self._pet.release_mood()       # 休息时恢复自由活动
                self._pet.express("calm")
            except Exception:
                pass
            self._notify("☕ 休息时间", f"休息 {minutes} 分钟，起来动一动吧")
            self._say(random.choice(BREAK_START_PHRASES))

        self._refresh_bubble()
        self.phase_changed.emit(phase, self._remaining)

    def _notify(self, title: str, text: str) -> None:
        try:
            self._pet.notify(title, text)
        except Exception:
            pass

    def _refresh_bubble(self) -> None:
        """把剩余时间画进宠物气泡；每秒刷新，duration 略大于 1 秒防闪烁"""
        mm, ss = divmod(max(0, self._remaining), 60)
        icon = "🎯" if self._phase == "focus" else "☕"
        label = "专注中" if self._phase == "focus" else "休息中"
        suffix = "（已暂停）" if self._paused else ""
        try:
            self._pet.speak(f"{icon} {label} {mm:02d}:{ss:02d}{suffix}", duration=1400)
        except Exception:
            pass

    def _tick(self) -> None:
        if self._paused or self._remaining <= 0:
            return
        self._remaining -= 1
        self._refresh_bubble()
        self.phase_changed.emit(self._phase, self._remaining)
        if self._remaining <= 0:
            self._complete_phase()

    def _complete_phase(self) -> None:
        done = self._phase
        self._timer.stop()
        if done == "focus":
            self._finished_focus += 1
            try:
                self._pet.express("cheer", random.choice(FOCUS_DONE_PHRASES))
            except Exception:
                pass
            self._notify("🎉 专注完成",
                         f"已完成 {self._finished_focus} 个番茄，休息一下吧")
            self.phase_finished.emit("focus")
            # 专注结束自动接一段休息，符合番茄工作法的节奏
            self.start_break()
        elif done == "break":
            try:
                self._pet.express("happy", random.choice(BREAK_DONE_PHRASES))
                self._pet.release_mood()
            except Exception:
                pass
            self._notify("☕ 休息结束",
                         f"今天已完成 {self._finished_focus} 个番茄，要继续就再点一次～")
            self.phase_finished.emit("break")
            self._phase = None
            self._remaining = 0
            self.stopped.emit()
        else:
            self._phase = None
            self._remaining = 0
