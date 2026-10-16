# -*- coding: utf-8 -*-
"""趣味小互动

参考 openpets 的三个轻量官方插件：
- fortune-cookie（每日运势签）：一天固定一条，点几次都是同一条
- magic-8-ball（魔法八球）：心里想个问题，给一句俏皮回答
- mood-check-in（情绪打卡）：选个心情，宠物给对应回应并记下来

设计上刻意做"轻"：不新开窗口，只用宠物气泡 + 一个输入框，
让用户随时点一下就有反馈。
"""

import datetime
import random

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QInputDialog

# ---------------- 今日运势 ----------------
FORTUNES = [
    "今天适合把最难的那件事先干掉，后面会很轻松。",
    "会收到一条让你开心的消息，记得看手机。",
    "宜早睡。熬夜的账，身体都记着。",
    "有个卡了很久的问题，今天换个思路就能通。",
    "适合整理桌面和文件夹，清爽的环境带来清爽的思路。",
    "今天讲话自带说服力，适合谈事情。",
    "会遇到一个小惊喜，别急着赶路。",
    "宜喝热水，忌硬撑。",
    "灵感在路上了，随手记下来别让它跑掉。",
    "今天适合推进老项目，不适合开新坑。",
    "有人默默记着你的好，今天可能会表达出来。",
    "宜慢一点。快不等于对。",
    "今天的手气不错，可以试试运气。",
    "适合跟久没联系的朋友说句话。",
    "别跟自己较劲，今天放过自己一次。",
    "适合打扫心里的灰尘：删掉不看的文件、退掉没用的群。",
    "今天学的知识点，过两天正好用得上。",
    "宜出门走走，哪怕只是下楼买杯咖啡。",
    "今天适合把想法写下来，写着写着就清楚了。",
    "会遇到愿意帮你的人，开口就好。",
]

# ---------------- 魔法八球 ----------------
EIGHT_BALL = [
    "会的，而且比你想象的快。",
    "再等等，时机还没到。",
    "大概率可以，但别掉以轻心。",
    "不太行，换个方向试试。",
    "现在就去做，答案在路上。",
    "问这个问题的你，其实已经有答案了。",
    "有戏，但需要你先迈出第一步。",
    "这个嘛……再观察观察。",
    "可以，但记得给自己留退路。",
    "悬。不如先做点别的。",
    "是的，相信你的直觉。",
    "不太建议，风险比收益大。",
    "会顺利的，放轻松。",
    "别急，三天后你就不纠结了。",
    "值得一试，失败也就多学一课。",
    "看起来是，但细节要盯紧些。",
    "换个问法可能更容易得到答案。",
    "先把手头这点做完再说吧。",
    "嗯，我倾向于说「可以」。",
    "不一定，取决于你今天的状态。",
]

# ---------------- 情绪打卡 ----------------
MOOD_OPTIONS = ["很好 😄", "还行 🙂", "一般 😐", "有点累 😮‍💨", "不太好 😔"]

MOOD_RESPONSE = {
    "很好 😄": ("cheer", "太棒了！好心情要保持住哦～"),
    "还行 🙂": ("calm", "平平淡淡也挺好呀"),
    "一般 😐": ("think", "要不要起来走两步？换个气儿"),
    "有点累 😮‍💨": ("sleepy", "辛苦啦，记得早点休息"),
    "不太好 😔": ("tired", "抱一下。先深呼吸几次，我陪着你"),
}


class FunInteractions(QObject):
    """今日运势 / 魔法八球 / 情绪打卡"""

    def __init__(self, pet_window, parent=None):
        super().__init__(parent)
        self._pet = pet_window
        self._fortune_cache = None   # (日期字符串, 运势文案)

    # ---------------- 今日运势 ----------------

    def daily_fortune(self) -> str:
        """今日运势签：同一天内多次点击返回同一条（先抽签后固定）"""
        today = datetime.date.today().isoformat()
        if self._fortune_cache and self._fortune_cache[0] == today:
            text = self._fortune_cache[1]
        else:
            text = random.choice(FORTUNES)
            self._fortune_cache = (today, text)
        self._express("happy", f"🔮 今日运势\n{text}")
        self._notify("🔮 今日运势", text)
        return text

    # ---------------- 魔法八球 ----------------

    def magic_8_ball(self) -> str:
        """魔法八球：输入一个心里想着的问题，给一句回答"""
        question, ok = QInputDialog.getText(
            None, "🎱 魔法八球", "心里想一个问题，然后问我：")
        if not ok or not question.strip():
            return ""
        answer = random.choice(EIGHT_BALL)
        self._express("think", "嗯……让我想想 🤔")
        # 停一下再揭晓，比"秒答"更有仪式感
        QTimer.singleShot(900, lambda: self._express("cheer", f"🎱 {answer}"))
        self._notify("🎱 魔法八球", f"问：{question.strip()}\n答：{answer}")
        return answer

    # ---------------- 情绪打卡 ----------------

    def mood_checkin(self) -> str:
        """情绪打卡：选一个心情，宠物给对应回应，并记进配置备查"""
        choice, ok = QInputDialog.getItem(
            None, "💗 情绪打卡", "今天心情怎么样？", MOOD_OPTIONS, 1, False)
        if not ok or not choice:
            return ""
        mood, reply = MOOD_RESPONSE.get(choice, ("calm", "嗯，记下了"))
        self._express(mood, reply)
        self._notify("💗 情绪打卡", f"今天：{choice}\n{reply}")
        try:
            from config.settings_manager import settings
            settings.set("mood.last_date", datetime.date.today().isoformat())
            settings.set("mood.last_value", choice)
        except Exception:
            pass
        return choice

    # ---------------- 内部 ----------------

    def _express(self, mood: str, text: str = "") -> None:
        try:
            self._pet.express(mood, text)
        except Exception:
            try:
                self._pet.speak(text)
            except Exception:
                pass

    def _notify(self, title: str, text: str) -> None:
        try:
            self._pet.notify(title, text)
        except Exception:
            pass
