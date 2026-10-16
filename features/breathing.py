# -*- coding: utf-8 -*-
"""4-7-8 呼吸放松引导

参考 openpets 官方插件 anxiety-aid-tools 的"呼吸练习"：
- 4 秒吸气 → 7 秒屏息 → 8 秒呼气，为一轮；默认做 5 轮
- 宠物用气泡当节奏提示器（每秒刷新剩余秒数），并保持安静的坐姿陪着
- 引导语走宠物气泡 + 托盘通知，不弹窗打断手头的事

4-7-8 是常见的助眠/减压呼吸法，节奏慢、易上手，适合写代码/备课间隙用。
"""

from PySide6.QtCore import QObject, QTimer, Signal

import random

# (阶段标识, 持续秒数, 中文引导语, 提示符号)
PHASES = [
    ("inhale", 4, "吸气", "🌬️"),
    ("hold",   7, "屏住", "⏸️"),
    ("exhale", 8, "呼气", "😮‍💨"),
]

DEFAULT_ROUNDS = 5

START_PHRASES = [
    "找个舒服的姿势，跟着我慢慢呼吸～",
    "放松肩膀，我们来练几轮呼吸",
    "坐正一点，深呼吸预备～",
]

FINISH_PHRASES = [
    "呼吸做完啦，感觉轻松些了吗？",
    "很棒，身体放松下来了吧～",
    "一轮呼吸结束，脑子清爽一点了吗？",
]


class BreathingService(QObject):
    """4-7-8 呼吸引导：按阶段推进，用气泡播报节奏"""

    phase_changed = Signal(str, int)   # (阶段标识, 剩余秒数)
    finished = Signal()
    stopped = Signal()

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet = pet_window
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self._phase_index = 0
        self._remaining = 0
        self._round_index = 1
        self._rounds = DEFAULT_ROUNDS
        self._running = False

    # ---------------- 对外接口 ----------------

    def is_running(self) -> bool:
        return self._running

    def current_phase(self) -> str:
        return PHASES[self._phase_index][0] if self._running else ""

    def status_text(self) -> str:
        if not self._running:
            return "当前没有进行中的呼吸练习"
        _, _, label, _ = PHASES[self._phase_index]
        return f"第 {self._round_index}/{self._rounds} 轮 · {label} 还剩 {self._remaining} 秒"

    def start(self, rounds: int = DEFAULT_ROUNDS) -> None:
        self._rounds = max(1, int(rounds))
        self._round_index = 1
        self._phase_index = 0
        self._remaining = PHASES[0][1]
        self._running = True
        self._timer.start()

        try:
            # 呼吸练习期间让宠物安静坐下不游走（calm 不锁行为，靠 focused 锁）
            self._pet.express("focused")
        except Exception:
            pass
        self._notify("🫁 呼吸放松",
                     f"{self._rounds} 轮 4-7-8 呼吸：吸气 4 秒 → 屏息 7 秒 → 呼气 8 秒")
        self._say(random.choice(START_PHRASES))
        self._announce()
        self.phase_changed.emit(PHASES[0][0], self._remaining)

    def stop(self, silent: bool = False) -> None:
        was_running = self._running
        self._timer.stop()
        self._running = False
        self._phase_index = 0
        self._remaining = 0
        try:
            self._pet.release_mood()
        except Exception:
            pass
        if was_running and not silent:
            self._say("呼吸练习先到这儿～")
        self.stopped.emit()

    # ---------------- 内部 ----------------

    def _say(self, text: str) -> None:
        try:
            self._pet.speak(text)
        except Exception:
            pass

    def _notify(self, title: str, text: str) -> None:
        try:
            self._pet.notify(title, text)
        except Exception:
            pass

    def _announce(self) -> None:
        """每秒刷新气泡：阶段名 + 剩余秒数"""
        key, total, label, icon = PHASES[self._phase_index]
        try:
            self._pet.speak(
                f"{icon} {label}… {self._remaining}\n"
                f"（第 {self._round_index}/{self._rounds} 轮）",
                duration=1400)
        except Exception:
            pass

    def _tick(self) -> None:
        if not self._running:
            return
        self._remaining -= 1
        if self._remaining <= 0:
            self._phase_index += 1
            if self._phase_index >= len(PHASES):
                self._phase_index = 0
                self._round_index += 1
                if self._round_index > self._rounds:
                    self._finish()
                    return
            self._remaining = PHASES[self._phase_index][1]
            self.phase_changed.emit(PHASES[self._phase_index][0], self._remaining)
        self._announce()

    def _finish(self) -> None:
        self._timer.stop()
        self._running = False
        self._phase_index = 0
        self._remaining = 0
        try:
            self._pet.express("happy", random.choice(FINISH_PHRASES))
            self._pet.release_mood()
        except Exception:
            pass
        self._notify("🫁 呼吸放松", "一轮呼吸练习完成，感觉如何？")
        self.finished.emit()
