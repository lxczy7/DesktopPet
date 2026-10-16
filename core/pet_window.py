"""
桌面宠物主窗口 v2
- 无边框 / 透明背景 / 置顶 / 托盘常驻
- 行为系统：地面慢速游走 + 待机 / 坐 / 躺 / 互动，不再乱窜
- 气泡交互：点击弹气泡、定时主动打招呼
"""
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QRect, QPropertyAnimation,
    QEasingCurve, Signal, QSize, QPointF
)
from PySide6.QtWidgets import (
    QWidget, QMenu, QApplication, QSystemTrayIcon, QStyle, QLabel
)
from PySide6.QtGui import (
    QPixmap, QPainter, QCursor, QAction, QIcon, QGuiApplication,
    QColor, QFont, QPen, QBrush, QScreen, QFontMetrics, QPolygonF
)
import random
import math
import time
from typing import Optional

from core.animation_engine import AnimationEngine, PetState
from config.settings_manager import settings
from config.constants import ICONS_DIR

# 情绪 -> (动画状态, 持续毫秒, 是否锁定行为调度)
#
# 设计说明（借鉴 openpets 的 state-driven reaction：thinking / success /
# error 等由状态驱动表情）：这里不新增素材帧，而是把抽象情绪映射到已有的
# 6 类动作帧上，用「选哪一帧 + 演多久 + 配什么台词」来表达情绪。
#   - focused 时长 0 表示常驻，直到 release_mood()（番茄钟专注陪伴用）
MOOD_PRESETS = {
    "happy":   (PetState.INTERACT, 1600, False),   # 蹦跳欢呼
    "cheer":   (PetState.INTERACT, 2400, False),   # 更长的欢呼
    "tired":   (PetState.LIE,      4000, False),   # 躺下歇会儿
    "sleepy":  (PetState.SIT,      5000, False),   # 坐着犯困
    "think":   (PetState.SIT,      3000, False),   # 坐着沉思
    "calm":    (PetState.IDLE,     2500, False),   # 安静站着
    "care":    (PetState.IDLE,     3000, False),   # 关心地看着你
    "focused": (PetState.SIT,         0, True),    # 专注陪伴，锁定行为
}
MOOD_DEFAULT = "calm"

# 气泡语料
CLICK_PHRASES = [
    "你好呀~", "今天也要元气满满！", "摸到我啦 ☁️", "嘿嘿，好开心~",
    "要加油哦！", "陪我玩会儿嘛~", "咕噜咕噜~", "怎么啦？",
]
GREET_PHRASES = [
    "今天天气不错呀", "该喝水啦~", "久坐会累，起来动动！",
    "工作辛苦啦，休息一下", "想你呀 ~", "今天也要加油鸭",
    "记得保护眼睛哦", "休息会儿，发发呆也很棒",
]
DOUBLE_CLICK_PHRASES = [
    "哇！跳一个~", "嘿嘿，被你发现了", "开心得要飞起来啦",
    "双击收到！元气 +1", "蹦蹦跳跳真可爱", "再点我就转圈啦",
]


class SpeechBubble(QWidget):
    """宠物头顶气泡：圆角对话框 + 小尾巴，2.5 秒后淡出"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._text = ""
        self._font = QFont("Microsoft YaHei", 10)
        # 气泡宽度跟随宠物尺寸（小宠物不配大气泡），下限 140 保证文字可读
        self._max_w = max(140, int(settings.get("pet.size", 180)) * 1.4)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(400)
        self._fade.finished.connect(self.hide)
        # 停留时长可配：番茄钟/呼吸引导需要把气泡当"倒计时面板"用，
        # 每阶段刷新一次，不能固定 2.5 秒就淡出
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._start_fade)

    def show_text(self, text: str, anchor: QPoint, duration: int = 2500) -> None:
        """在 anchor 上方显示气泡。

        duration: 停留毫秒数；重复调用会重置计时（可当常驻面板用）。
                  传 0 或负数表示一直显示，直到再次调用或手动 hide。
        """
        self._text = text
        # 气泡宽度跟随宠物尺寸（用户改过大小后这里要重算）
        self._max_w = max(140, int(settings.get("pet.size", 180)) * 1.4)
        fm = QFontMetrics(self._font)
        # 计算换行后的尺寸
        lines, cur = [], ""
        for ch in text:
            cur += ch
            if fm.horizontalAdvance(cur) > self._max_w - 24:
                lines.append(cur)
                cur = ""
        if cur:
            lines.append(cur)
        line_h = fm.height() + 2
        w = min(self._max_w, max(fm.horizontalAdvance(l) for l in lines) + 24)
        h = line_h * len(lines) + 16 + 8  # 8 = 尾巴高度
        self.setFixedSize(int(w), int(h))
        # 水平居中对齐宠物：偏移量取宠物尺寸的一半（原来硬编码 90，
        # 宠物不是 180px 时气泡会明显偏左/偏右）
        center_offset = int(settings.get("pet.size", 180)) // 2
        self.move(anchor.x() + center_offset - w // 2, anchor.y() - h - 6)
        self._fade.stop()
        self.setWindowOpacity(1.0)
        self.show()
        self.update()
        if duration and duration > 0:
            self._hide_timer.start(int(duration))
        else:
            self._hide_timer.stop()

    def _start_fade(self) -> None:
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def paintEvent(self, event) -> None:
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 气泡主体（留出尾巴位置）
        body = self.rect().adjusted(0, 0, 0, -8)
        p.setBrush(QBrush(QColor(255, 255, 255, 235)))
        p.setPen(QPen(QColor(120, 120, 120, 120), 1))
        p.drawRoundedRect(body, 10, 10)
        # 小三角尾巴（底部中间偏左）
        cx = 26
        p.setBrush(QBrush(QColor(255, 255, 255, 235)))
        p.setPen(Qt.PenStyle.NoPen)
        tail = QPolygonF([
            QPointF(cx - 7, body.bottom()),
            QPointF(cx + 7, body.bottom()),
            QPointF(cx, self.rect().bottom()),
        ])
        p.drawPolygon(tail)
        # 文字
        p.setPen(QColor(60, 60, 60))
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        y = 8 + fm.ascent()
        for line in self._wrap_lines():
            p.drawText(12, y, line)
            y += fm.height() + 2

    def _wrap_lines(self):
        fm = QFontMetrics(self._font)
        lines, cur = [], ""
        for ch in self._text:
            cur += ch
            if fm.horizontalAdvance(cur) > self._max_w - 24:
                lines.append(cur)
                cur = ""
        if cur:
            lines.append(cur)
        return lines


class PetWindow(QWidget):
    """桌面宠物主窗口"""

    screenshot_requested = Signal(str)
    wallpaper_change_requested = Signal(str)
    clipboard_history_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()
    # 专注 / 呼吸 / 趣味（借鉴 openpets 官方插件区）
    pomodoro_requested = Signal(str, int)    # (action, minutes)
    breathing_requested = Signal(str, int)   # (action, rounds)
    fun_requested = Signal(str)              # fortune / 8ball / mood

    # 行为权重
    BEHAVIOR_WEIGHTS = [
        (PetState.IDLE, 50),
        (PetState.SIT, 16),
        (PetState.LIE, 16),
        ("walk", 18),
    ]

    # 视线翻转冷却（秒）：鼠标在判定阈值附近来回时，避免宠物高频左右横跳
    GAZE_FLIP_COOLDOWN = 1.5

    def __init__(self):
        super().__init__()

        # ---- 窗口属性 ----
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # 点击穿透（默认关闭）
        self._click_through = settings.get("general.click_through", False)
        self._update_click_through()

        # ---- 核心组件 ----
        self._animation_engine = AnimationEngine(self)
        self._animation_engine.frame_changed.connect(self._on_frame_changed)
        self._animation_engine.state_changed.connect(self._on_state_changed)
        self._animation_engine.state_finished.connect(self._on_state_finished)

        self._current_pixmap: QPixmap = QPixmap()

        # 宠物尺寸（默认 180，原 140 偏小）
        self._pet_size = int(settings.get("pet.size", 180))
        self.setFixedSize(self._pet_size, self._pet_size)

        # ---- 移动相关 ----
        self._velocity = QPoint(0, 0)
        self._target_pos = QPoint(0, 0)
        self._is_moving = False
        self._is_dragging = False
        self._capture_was_visible = False  # 截图期间临时隐藏的状态记录
        self._drag_start_pos = QPoint()
        self._window_start_pos = QPoint()
        self._drag_moved = False
        self._bob_offset = 0.0     # 行走身体起伏偏移
        self._bob_phase = 0.0
        self._current_screen: QScreen = QGuiApplication.primaryScreen()
        self._screen_geometry: QRect = QRect()

        # ---- 物理下落（拖拽松手后自由落体 + 落地弹跳，借鉴 openpets 运动引擎）----
        self._vy = 0.0
        self._falling = False

        # ---- 视线跟随（待机时面向鼠标，借鉴 openpets gaze 模块）----
        self._gaze_flip = False        # 是否水平翻转（朝鼠标方向）
        self._gaze_last_flip = 0.0     # 上次翻转时刻（单调时钟），用于冷却防抖
        self._gaze_bounce_count = 0    # 落地弹跳计数

        # ---- 定时器 ----
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(50)  # 20 FPS 移动更新
        self._move_timer.timeout.connect(self._update_position)

        self._behavior_timer = QTimer(self)
        self._behavior_timer.setSingleShot(True)
        self._behavior_timer.timeout.connect(self._decide_next_behavior)

        # ---- 右键菜单 / 托盘 / 气泡 ----
        self._setup_context_menu()
        self._setup_tray_icon()
        self._bubble = SpeechBubble()

        # ---- 情绪表达（状态驱动 reaction）----
        self._mood_lock = False          # 锁定期间随机行为不抢占状态
        self._mood_timer = QTimer(self)
        self._mood_timer.setSingleShot(True)
        self._mood_timer.timeout.connect(self.release_mood)

        # ---- 多显示器 ----
        self._multi_monitor = settings.get("general.multi_monitor", True)
        _app = QGuiApplication.instance()
        if _app is not None:
            _app.screenAdded.connect(self._on_screen_changed)
            _app.screenRemoved.connect(self._on_screen_changed)

        # ---- 主动打招呼定时器 ----
        self._greet_timer = QTimer(self)
        self._greet_timer.timeout.connect(self._auto_greet)
        self._schedule_next_greet()

        # ---- 物理下落定时器（拖拽松手后触发，约 60FPS）----
        self._physics_timer = QTimer(self)
        self._physics_timer.setInterval(16)
        self._physics_timer.timeout.connect(self._physics_tick)

        # ---- 视线跟随定时器（待在原地时朝鼠标方向看）----
        self._gaze_timer = QTimer(self)
        self._gaze_timer.setInterval(120)
        self._gaze_timer.timeout.connect(self._gaze_tick)
        if settings.get("pet.gaze_follow", True):
            self._gaze_timer.start()

        # 初始位置：主屏幕地面区域
        self._move_to_random_position()

        # 启动
        self._animation_engine.start()
        self._move_timer.start()
        self._decide_next_behavior()

    # ================= 视觉 =================

    def _update_click_through(self) -> None:
        if self._click_through:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowTransparentForInput)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowTransparentForInput)
        self.show()

    def _on_frame_changed(self, pixmap: QPixmap) -> None:
        self._current_pixmap = pixmap
        self.update()

    def _on_state_changed(self, state: str) -> None:
        pass

    def _on_state_finished(self) -> None:
        """一个带时长的动作自然结束（走路超时 / 互动播完）→ 重排下一个行为。

        这是修复"行为系统死锁"的关键：走路超时后引擎会把状态切回 IDLE，
        但 _is_moving 仍是 True，而 _update_position 对 IDLE 直接 return，
        结果既走不动、也等不到下一次决策，宠物会永久卡在原地不动。
        """
        if self._mood_lock or self._is_dragging or self._falling:
            return
        self._is_moving = False
        self._decide_next_behavior()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self._current_pixmap.isNull():
            scaled = self._current_pixmap.scaled(
                QSize(self.width(), self.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2 + int(self._bob_offset)
            if self._gaze_flip:
                # 朝鼠标方向：水平镜像绘制（保持位置不变）
                painter.save()
                painter.translate(x + scaled.width(), y)
                painter.scale(-1, 1)
                painter.drawPixmap(0, 0, scaled)
                painter.restore()
            else:
                painter.drawPixmap(x, y, scaled)

    # ================= 菜单与托盘 =================

    def _setup_context_menu(self) -> None:
        self._context_menu = QMenu(self)
        self._context_menu.setStyleSheet("""
            QMenu { background: #2d2d2d; border: 1px solid #444; border-radius: 8px;
                    padding: 6px; color: #eee; font-size: 13px; }
            QMenu::item { padding: 8px 24px; border-radius: 4px; }
            QMenu::item:selected { background: #3d3d3d; }
            QMenu::separator { height: 1px; background: #444; margin: 4px 8px; }
        """)

        # 截图三个功能全部一级直达：点击即进入对应截图操作，无需快捷键
        self._context_menu.addAction("📸 截图", lambda: self.screenshot_requested.emit("region"))
        self._context_menu.addAction("🖵 全屏截图", lambda: self.screenshot_requested.emit("full"))
        self._context_menu.addAction("🪟 窗口截图", lambda: self.screenshot_requested.emit("window"))

        wallpaper_menu = self._context_menu.addMenu("🖼️ 换壁纸")
        wallpaper_menu.addAction("下一张", lambda: self.wallpaper_change_requested.emit("next"))
        wallpaper_menu.addAction("随机一张", lambda: self.wallpaper_change_requested.emit("random"))
        wallpaper_menu.addAction("🌐 联网随机壁纸", lambda: self.wallpaper_change_requested.emit("online"))
        wallpaper_menu.addSeparator()
        wallpaper_menu.addAction("打开壁纸文件夹", lambda: self.wallpaper_change_requested.emit("open_folder"))
        wallpaper_menu.addAction("壁纸设置...", lambda: self.wallpaper_change_requested.emit("settings"))

        self._context_menu.addSeparator()

        # ---- 专注 / 呼吸 / 趣味（借鉴 openpets 的官方插件区）----
        focus_menu = self._context_menu.addMenu("🎯 专注")
        for minutes in (25, 45, 60):
            focus_menu.addAction(
                f"开始专注（{minutes} 分钟）",
                lambda checked=False, m=minutes: self.pomodoro_requested.emit("start", m))
        focus_menu.addSeparator()
        focus_menu.addAction("暂停 / 继续", lambda: self.pomodoro_requested.emit("pause", 0))
        focus_menu.addAction("直接休息（5 分钟）", lambda: self.pomodoro_requested.emit("break", 5))
        focus_menu.addAction("查看进度", lambda: self.pomodoro_requested.emit("status", 0))
        focus_menu.addAction("结束专注", lambda: self.pomodoro_requested.emit("stop", 0))

        breath_menu = self._context_menu.addMenu("🫁 呼吸放松")
        breath_menu.addAction("4-7-8 呼吸（5 轮）",
                              lambda: self.breathing_requested.emit("start", 5))
        breath_menu.addAction("4-7-8 呼吸（10 轮）",
                              lambda: self.breathing_requested.emit("start", 10))
        breath_menu.addSeparator()
        breath_menu.addAction("结束引导", lambda: self.breathing_requested.emit("stop", 0))

        fun_menu = self._context_menu.addMenu("🎲 趣味")
        fun_menu.addAction("今日运势", lambda: self.fun_requested.emit("fortune"))
        fun_menu.addAction("魔法八球", lambda: self.fun_requested.emit("8ball"))
        fun_menu.addAction("情绪打卡", lambda: self.fun_requested.emit("mood"))

        self._context_menu.addSeparator()
        self._context_menu.addAction("📋 剪贴板历史", self.clipboard_history_requested.emit)
        self._context_menu.addAction("⚙️ 设置", self.settings_requested.emit)
        self._context_menu.addSeparator()
        self._context_menu.addAction("🚪 退出", self.quit_requested.emit)

    def _setup_tray_icon(self) -> None:
        self._tray_icon = QSystemTrayIcon(self)
        icon_path = ICONS_DIR / "pet.ico"
        if icon_path.exists():
            self._tray_icon.setIcon(QIcon(str(icon_path)))
        else:
            self._tray_icon.setIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self._tray_icon.setToolTip("桌面宠物")

        tray_menu = QMenu()
        tray_menu.addAction("显示/隐藏宠物", self.toggle_visibility)
        tray_menu.addSeparator()
        tray_menu.addAction("跟它打个招呼", self._say_hello)
        tray_menu.addAction("让它躺一会儿", lambda: self._animation_engine.set_state(PetState.LIE, duration=8000, force=True))
        tray_menu.addSeparator()
        tray_menu.addAction("📸 截图", lambda: self.screenshot_requested.emit("region"))
        tray_menu.addAction("全屏截图", lambda: self.screenshot_requested.emit("full"))
        tray_menu.addAction("窗口截图", lambda: self.screenshot_requested.emit("window"))
        tray_menu.addSeparator()
        tray_menu.addAction("换壁纸（下一张）", lambda: self.wallpaper_change_requested.emit("next"))
        tray_menu.addAction("🌐 联网随机壁纸", lambda: self.wallpaper_change_requested.emit("online"))
        tray_menu.addSeparator()
        tray_menu.addAction("🎯 开始专注（25 分钟）",
                            lambda: self.pomodoro_requested.emit("start", 25))
        tray_menu.addAction("🫁 4-7-8 呼吸（5 轮）",
                            lambda: self.breathing_requested.emit("start", 5))
        tray_menu.addAction("🔮 今日运势", lambda: self.fun_requested.emit("fortune"))
        tray_menu.addSeparator()
        tray_menu.addAction("设置", self.settings_requested.emit)
        tray_menu.addAction("退出", self.quit_requested.emit)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)

    def notify(self, title: str, text: str) -> None:
        """托盘气泡通知（热键顺延等场景）"""
        try:
            self._tray_icon.showMessage(title, text, msecs=5000)
        except Exception:
            pass
        if settings.get("general.show_tray_icon", True):
            self._tray_icon.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_visibility()

    def toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
            self._move_timer.stop()
        else:
            self.show()
            self._move_timer.start()
            self._decide_next_behavior()

    # ================= 截图协作 =================

    def hide_for_capture(self) -> None:
        """截图期间临时隐藏宠物（避免宠物入镜/遮挡），记录原可见状态"""
        self._capture_was_visible = self.isVisible()
        if self._capture_was_visible:
            self.hide()
            self._move_timer.stop()

    def restore_after_capture(self) -> None:
        """截图结束后恢复宠物显示并继续行为循环"""
        if getattr(self, "_capture_was_visible", False):
            self._capture_was_visible = False
            self.show()
            self._move_timer.start()
            self._decide_next_behavior()

    def speak(self, text: str, duration: int = 2500) -> None:
        """让宠物说一句话（气泡）。

        duration 可加长 —— 番茄钟/呼吸引导会把气泡当倒计时面板反复刷新。
        """
        self._bubble.show_text(text, self.pos(), duration)

    # ================= 情绪表达（状态驱动 reaction） =================

    def express(self, mood: str, text: str = "", duration: Optional[int] = None) -> None:
        """按情绪切换表现：选帧 + 演出时长 + 台词，可选锁定随机行为。

        mood 取值见 MOOD_PRESETS：happy / cheer / tired / sleepy /
        think / calm / care / focused。duration 可覆盖预设毫秒数。
        """
        state, dur, lock = MOOD_PRESETS.get(mood, MOOD_PRESETS[MOOD_DEFAULT])
        if duration is not None:
            dur = max(0, int(duration))
        if text:
            self._bubble.show_text(text, self.pos())
        self._mood_lock = bool(lock)
        self._is_moving = False
        self._behavior_timer.stop()
        self._animation_engine.set_state(state, duration=dur, force=True)
        if lock or dur <= 0:
            self._mood_timer.stop()          # 常驻，等 release_mood 收场
        else:
            self._mood_timer.start(dur + 150)

    def release_mood(self) -> None:
        """解除情绪锁定，把控制权交还给随机行为调度"""
        self._mood_timer.stop()
        self._mood_lock = False
        self._decide_next_behavior()

    def is_mood_locked(self) -> bool:
        return self._mood_lock

    # ================= 交互 =================

    def _say_hello(self) -> None:
        self._bubble.show_text(random.choice(GREET_PHRASES + CLICK_PHRASES), self.pos())

    def _schedule_next_greet(self) -> None:
        if not settings.get("greet.enabled", True):
            return
        lo = int(settings.get("greet.interval_min_minutes", 90)) * 1000
        hi = int(settings.get("greet.interval_max_minutes", 180)) * 1000
        self._greet_timer.start(random.randint(lo, hi))

    def _auto_greet(self) -> None:
        if self.isVisible():
            self._bubble.show_text(random.choice(GREET_PHRASES), self.pos())
            self._animation_engine.trigger_interaction("greet")
        self._schedule_next_greet()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.globalPosition().toPoint()
            self._window_start_pos = self.pos()
            self._is_dragging = True
            self._drag_moved = False
            self._animation_engine.set_state(PetState.DRAG, duration=0, force=True)
        elif event.button() == Qt.MouseButton.RightButton:
            self._context_menu.exec(QCursor.pos())

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            if delta.manhattanLength() > 6:
                self._drag_moved = True
            new_pos = self._constrain_to_screens(self._window_start_pos + delta)
            self.move(new_pos)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            if not self._drag_moved:
                # 单击 = 互动 + 气泡
                self._animation_engine.trigger_interaction("click")
                self._bubble.show_text(random.choice(CLICK_PHRASES), self.pos())
                self._decide_next_behavior()
            else:
                # 拖拽结束：自由落体到地面 + 落地弹跳（"扔出去"的手感）
                self._start_fall()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # 双击 = 原地起跳（openpets 的 jumping / success 反应思路）
            self._start_jump()
            self._bubble.show_text(random.choice(DOUBLE_CLICK_PHRASES), self.pos())

    def enterEvent(self, event) -> None:
        self._animation_engine.trigger_interaction("hover")

    # ================= 尺寸 / 物理 / 视线 =================

    def apply_pet_size(self, size: int) -> None:
        """运行时调整显示尺寸（设置面板拖动滑块即时预览），保持中心不跳"""
        size = max(40, min(int(size), 400))
        if size == self._pet_size:
            return
        center = self.geometry().center()
        self._pet_size = size
        self.setFixedSize(size, size)
        self.move(center.x() - size // 2, center.y() - size // 2)
        self.update()

    def _start_fall(self) -> None:
        """松手瞬间：进入自由落体，落地后弹跳几次再恢复待机"""
        if self._falling:
            return
        self._falling = True
        self._vy = 0.0
        self._gaze_bounce_count = 0
        self._is_moving = False
        self._animation_engine.set_state(PetState.DRAG, duration=0, force=True)
        self._physics_timer.start()

    def _start_jump(self) -> None:
        """原地起跳（双击触发）：给一个向上初速度，复用下落物理引擎"""
        if self._falling:
            return
        self._falling = True
        self._is_moving = False
        self._vy = -17.0                 # 向上初速度（屏幕坐标 y 向下为正）
        self._gaze_bounce_count = 2      # 落地后最多再弹 2 下
        self._animation_engine.set_state(PetState.INTERACT, duration=0, force=True)
        self._physics_timer.start()

    def _physics_tick(self) -> None:
        """自由落体 + 弹跳衰减（借鉴 openpets motion engine 的重力模型）"""
        if self._is_dragging:
            return
        self._update_current_screen()
        geo = self._current_screen.availableGeometry()
        floor = geo.bottom() - self.height()

        self._vy = min(self._vy + 2.4, 46.0)   # 重力加速度（上限防穿地）
        new_y = self.pos().y() + self._vy
        if new_y >= floor:
            new_y = floor
            if abs(self._vy) > 6.0 and self._gaze_bounce_count < 4:
                self._vy = -self._vy * 0.42     # 弹跳并衰减
                self._gaze_bounce_count += 1
            else:
                # 落地停稳 → 精确贴地后回待机
                self._vy = 0.0
                self._falling = False
                self._physics_timer.stop()
                self._bob_offset = 0.0
                x = max(geo.left(), min(self.pos().x(), geo.right() - self.width()))
                self.move(int(x), int(floor))
                self._animation_engine.set_state(PetState.IDLE, force=True)
                self._decide_next_behavior()
                return

        x = max(geo.left(), min(self.pos().x(), geo.right() - self.width()))
        self.move(int(x), int(new_y))

    def _gaze_tick(self) -> None:
        """待在原地时朝鼠标方向看（只做水平镜像，身体不动）"""
        if not self.isVisible() or self._is_dragging or self._falling:
            return
        state = self._animation_engine.get_state()
        if state not in (PetState.IDLE, PetState.SIT, PetState.LIE):
            if self._gaze_flip:          # 走动/互动时恢复正常朝向
                self._gaze_flip = False
                self.update()
            return

        cursor = QCursor.pos()
        center = self.geometry().center()
        # 鼠标在左 / 右超过阈值才转向，留中间死区防抖动
        if cursor.x() < center.x() - 60:
            want = True
        elif cursor.x() > center.x() + 60:
            want = False
        else:
            return
        if want == self._gaze_flip:
            return
        # 翻转冷却：鼠标在死区边界附近来回时，避免高频左右横跳（看着像抽搐）
        now = time.monotonic()
        if now - self._gaze_last_flip < self.GAZE_FLIP_COOLDOWN:
            return
        self._gaze_flip = want
        self._gaze_last_flip = now
        self.update()

    # ================= 行为系统 =================

    def _ground_rect(self) -> QRect:
        """地面区域：可用屏幕底部 30%"""
        geo = self._current_screen.availableGeometry()
        h = int(geo.height() * 0.30)
        return QRect(geo.left(), geo.bottom() - h, geo.width(), h)

    def _constrain_to_screens(self, pos: QPoint) -> QPoint:
        screens = QGuiApplication.screens() if self._multi_monitor else [self._current_screen]
        for screen in screens:
            if screen.availableGeometry().contains(pos):
                return pos
        primary_geo = QGuiApplication.primaryScreen().availableGeometry()
        x = max(primary_geo.left(), min(pos.x(), primary_geo.right() - self.width()))
        y = max(primary_geo.top(), min(pos.y(), primary_geo.bottom() - self.height()))
        return QPoint(x, y)

    def _update_position(self) -> None:
        if self._is_dragging or self._falling:
            return  # 拖拽中 / 自由落体中：位置由鼠标或物理引擎接管
        state = self._animation_engine.get_state()
        if state in (PetState.SIT, PetState.LIE, PetState.IDLE):
            self._bob_offset = 0.0
            return  # 非行走状态不移动

        current = self.pos()
        dx = self._target_pos.x() - current.x()
        dy = self._target_pos.y() - current.y()
        dist = math.hypot(dx, dy)

        if dist < 4:
            self._is_moving = False
            self._bob_offset = 0.0
            self._animation_engine.set_state(PetState.IDLE)
            self._decide_next_behavior()
            return

        # 慢速行走（默认 2.0px/50ms ≈ 40px/s）
        speed = float(settings.get("pet.walk_speed", 2.0))
        step_x = dx / dist * speed
        step_y = dy / dist * speed
        new_pos = QPoint(int(current.x() + step_x), int(current.y() + step_y))

        # 根据方向切换行走动画
        want = PetState.WALK_RIGHT if step_x > 0 else PetState.WALK_LEFT
        if self._animation_engine.get_state() != want:
            self._animation_engine.set_state(want)

        self.move(self._constrain_to_screens(new_pos))
        # 行走身体上下起伏（迈步感）
        self._bob_phase += 0.8
        self._bob_offset = math.sin(self._bob_phase) * 3.0
        self.update()
        # 气泡跟随
        if self._bubble.isVisible():
            self._bubble.move(self._bubble.pos() + QPoint(int(step_x), int(step_y)))

    def _decide_next_behavior(self) -> None:
        # 情绪表达锁定期间（如专注陪伴、呼吸引导）不随机游走，
        # 但也别抢拖拽/自由落体中的控制权，落地后自然回到锁定姿势
        if self._mood_lock:
            if self._is_dragging or self._falling:
                return
            self._is_moving = False
            self._behavior_timer.stop()
            self._animation_engine.set_state(PetState.SIT, duration=0, force=False)
            return
        self._update_current_screen()
        geo = self._ground_rect()
        margin = int(settings.get("pet.bounds_margin", 50))

        # 加权随机选择行为
        roll = random.uniform(0, 100)
        acc, choice = 0.0, PetState.IDLE
        for item, w in self.BEHAVIOR_WEIGHTS:
            acc += w
            if roll <= acc:
                choice = item
                break

        if choice == "walk":
            self._behavior_timer.stop()     # 走路期间由"到达目标点"驱动，不用行为时钟
            # 在地面区域内随机选目标点
            x = random.randint(geo.left() + margin, max(geo.left() + margin + 1, geo.right() - margin - self.width()))
            y = random.randint(geo.top() + margin, max(geo.top() + margin + 1, geo.bottom() - margin - self.height()))
            self._target_pos = QPoint(x, y)
            self._is_moving = True
            direction = PetState.WALK_RIGHT if x > self.pos().x() else PetState.WALK_LEFT
            self._animation_engine.set_state(direction)
        else:
            self._is_moving = False
            self._animation_engine.set_state(choice)
            self._schedule_next_behavior()

    def _schedule_next_behavior(self) -> None:
        """安排下一次行为决策 —— 宠物自主行为的唯一切换时钟。

        停留时长按当前姿势匹配：坐着/躺着留更长的"发呆"时间。
        早期实现固定 1~3 秒换一次（还叠加了状态计时器抢跑），
        观感像多动症，用户反馈"动作切换过于频繁"，现已放慢到 6~20 秒量级，
        让它看起来有自己的节奏而不是被程序赶着走。
        """
        state = self._animation_engine.get_state()
        if state == PetState.LIE:
            lo = int(settings.get("pet.lie_duration_min", 9000))
            hi = int(settings.get("pet.lie_duration_max", 18000))
        elif state == PetState.SIT:
            lo = int(settings.get("pet.sit_duration_min", 6000))
            hi = int(settings.get("pet.sit_duration_max", 12000))
        else:
            lo = int(settings.get("pet.idle_interval_min", 6000))
            hi = int(settings.get("pet.idle_interval_max", 14000))
        if hi < lo:
            lo, hi = hi, lo
        self._behavior_timer.start(random.randint(lo, hi))

    def _update_current_screen(self) -> None:
        pos = self.pos() + QPoint(self.width() // 2, self.height() // 2)
        for screen in QGuiApplication.screens():
            if screen.geometry().contains(pos):
                self._current_screen = screen
                self._screen_geometry = screen.availableGeometry()
                return
        self._current_screen = QGuiApplication.primaryScreen()
        self._screen_geometry = self._current_screen.availableGeometry()

    def _move_to_random_position(self) -> None:
        self._update_current_screen()
        geo = self._ground_rect()
        margin = int(settings.get("pet.bounds_margin", 50))
        x = random.randint(geo.left() + margin, max(geo.left() + margin + 1, geo.right() - margin - self.width()))
        y = random.randint(geo.top() + margin, max(geo.top() + margin + 1, geo.bottom() - margin - self.height()))
        self.move(x, y)

    def _on_screen_changed(self) -> None:
        self._update_current_screen()
        if not any(s.geometry().contains(self.pos()) for s in QGuiApplication.screens()):
            self._move_to_random_position()

    # ================= 其他 =================

    def set_click_through(self, enabled: bool) -> None:
        self._click_through = enabled
        self._update_click_through()
        settings.set("general.click_through", enabled)

    def closeEvent(self, event) -> None:
        self._animation_engine.stop()
        self._move_timer.stop()
        self._behavior_timer.stop()
        self._greet_timer.stop()
        self._physics_timer.stop()
        self._gaze_timer.stop()
        self._mood_timer.stop()
        self._tray_icon.hide()
        super().closeEvent(event)
