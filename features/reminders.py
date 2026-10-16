"""轻量提醒服务

参考 openpets 官方插件的设计思路（water-reminder / day-routine）：
- 插件是"宠物能做的事"，用宠物气泡 + 托盘通知自然呈现，不弹窗打断
- 定时器只做调度，具体文案与节奏走配置，用户可调

提供的提醒：
1. 喝水提醒（间隔可配）
2. 久坐提醒（间隔可配，适合长时间在电脑前的老师/研究者）
3. 安静时段（如 22:00-08:00 不打扰）
"""

import datetime
import random

from PySide6.QtCore import QObject, QTimer

from config.settings_manager import settings

DRINK_PHRASES = [
    "该喝水啦，咕咚咕咚~ 💧",
    "嗓子干不干？喝口水吧",
    "水杯见底啦，去接一杯嘛",
    "喝水时间到，我陪你一起~",
    "别忘补水哦，皮肤会感谢你的",
]

SIT_PHRASES = [
    "坐太久啦，起来动一动吧",
    "脖子酸不酸？站起来伸个懒腰~",
    "久坐伤身，走两步嘛",
    "休息 5 分钟，看看远处放松眼睛",
    "该活动一下啦，我陪你走两步",
]

DRINK_TITLE = "💧 喝水提醒"
SIT_TITLE = "🧘 久坐提醒"


class ReminderService(QObject):
    """喝水 / 久坐 定时提醒（随宠物气泡一起出现）"""

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet = pet_window
        self._drink_timer = QTimer(self)
        self._drink_timer.timeout.connect(lambda: self._fire(DRINK_PHRASES, DRINK_TITLE))
        self._sit_timer = QTimer(self)
        self._sit_timer.timeout.connect(lambda: self._fire(SIT_PHRASES, SIT_TITLE))

    # ---------------- 对外接口 ----------------

    def start(self) -> None:
        self.reload()

    def stop(self) -> None:
        self._drink_timer.stop()
        self._sit_timer.stop()

    def reload(self) -> None:
        """按当前配置重启定时器（设置里改完立即生效）"""
        self.stop()
        if not settings.get("reminders.enabled", True):
            return

        drink_min = max(5, int(settings.get("reminders.drink_minutes", 45)))
        sit_min = max(5, int(settings.get("reminders.sit_minutes", 60)))
        # 非单次定时器：首轮等到一个完整周期后才提醒，之后循环
        self._drink_timer.start(drink_min * 60 * 1000)
        self._sit_timer.start(sit_min * 60 * 1000)

    # ---------------- 内部 ----------------

    def _in_quiet_hours(self) -> bool:
        start = int(settings.get("reminders.quiet_start_hour", 22))
        end = int(settings.get("reminders.quiet_end_hour", 8))
        if start == end:
            return False
        hour = datetime.datetime.now().hour
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end   # 跨零点（如 22 -> 8）

    def _fire(self, phrases: list, title: str) -> None:
        """触发一次提醒：安静时段自动跳过（不重置周期，等下一轮）"""
        if self._in_quiet_hours():
            return
        phrase = random.choice(phrases)
        try:
            self._pet.speak(phrase)
        except Exception:
            pass
        try:
            self._pet.notify(title, phrase)
        except Exception:
            pass
