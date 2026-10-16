"""
动画引擎 v2：状态机 + 分类帧
状态: IDLE(站立待机) / WALK_LEFT / WALK_RIGHT / SIT(坐) / LIE(躺) / INTERACT(互动) / DRAG(拖拽中)
素材目录: resources/frames/orig/<state_prefix>_XX.png
  idle_*.png -> IDLE      walk_*.png -> WALK_LEFT    walkr_*.png -> WALK_RIGHT
  sit_*.png  -> SIT       lie_*.png  -> LIE          interact_*.png -> INTERACT
兼容回退: orig 目录为空时回退旧管线(nobg/selected 均分)
"""
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QPixmap, QImage
from PIL import Image
import random

from config.constants import FRAMES_DIR, ANIMATION_CONFIG
from config.settings_manager import settings


class PetState(Enum):
    IDLE = "idle"
    WALK_LEFT = "walk_left"
    WALK_RIGHT = "walk_right"
    SIT = "sit"
    LIE = "lie"
    INTERACT = "interact"
    DRAG = "drag"


# 状态 -> 素材文件名前缀（按前缀 glob 加载）
STATE_PREFIX = {
    PetState.IDLE: ["idle"],
    PetState.WALK_LEFT: ["walk"],
    PetState.WALK_RIGHT: ["walkr"],
    PetState.SIT: ["sit"],
    PetState.LIE: ["lie"],
    PetState.INTERACT: ["interact"],
    PetState.DRAG: ["drag"],  # 无专属素材时回退 idle
}

# 每帧停留时长（ms），与帧序列一一对应；长度不足时最后一个值兜底
# 设计原则：睁眼/静态帧久留，过渡帧快闪，避免"疯狂眨眼"式机械循环。
# 注意：RESTING_STATES 的 index 0 是「常驻姿态」，不参与自动播放，填 0 占位；
#      index 1 起才是「小动作」帧的停留时长（见下方 RESTING_STATES 说明）。
FRAME_DURATIONS = {
    PetState.IDLE: [0, 1100],               # 0=站直(常驻)  1=歪头(小动作)
    PetState.WALK_LEFT: [100, 100, 100, 130],
    PetState.WALK_RIGHT: [100, 100, 100, 130],
    PetState.SIT: [0, 1800],                # 0=坐正(常驻)  1=犯困(小动作)
    PetState.LIE: [0, 2600],                # 0=侧躺(常驻)  1=打哈欠(小动作)
    PetState.INTERACT: [220, 220, 500],
    PetState.DRAG: [0],
}

# ---------------- 静止类状态：常驻帧 + 偶发小动作 ----------------
# IDLE / SIT / LIE 的素材本质是「同一姿势的变体」（站直↔歪头、坐正↔犯困、
# 侧躺↔打哈欠）。若按普通状态做首尾相接循环，就变成「每 1 秒抽搐一下」的
# 机械感，实测非常不自然。
# 正确节奏：长期保持常驻帧（第 0 帧）不动，每隔一段随机时间才**插播一次**
# 小动作，播完立刻回到常驻帧停住 —— 这才像有生命的小动物。
RESTING_STATES = frozenset({PetState.IDLE, PetState.SIT, PetState.LIE})

# 小动作插播间隔（秒，(min, max)）。
# 必须远大于动作自身停留时长，才有"偶尔自己动一下"的松弛感；
# 间隔越短越像抽搐，别低于 6 秒。
GESTURE_GAP_SECONDS = {
    PetState.IDLE: (8, 18),
    PetState.SIT: (10, 22),
    PetState.LIE: (14, 30),
}

# 冻结状态：只显示第 0 帧，绝不自动推进（拖拽姿态由外部接管）
FROZEN_STATES = frozenset({PetState.DRAG})

# 待机睁眼帧白名单：只用站姿睁眼/微歪头帧。
# idle_02-05（闭眼/笑脸帧）弃用——用户明确不需要平时自动眨眼，
# 互动时眼睛的变化由 INTERACT 帧（笑眼+张嘴）承担。
IDLE_KEEP = {"idle_00.png", "idle_01.png"}


class AnimationEngine(QObject):
    """动画引擎：管理宠物动画状态机与帧播放"""

    frame_changed = Signal(QPixmap)   # 当前帧变化
    state_changed = Signal(str)       # 状态变化
    state_finished = Signal()         # 带时长的状态自然结束（走路走完 / 互动播完）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = PetState.IDLE
        self._frames: Dict[PetState, List[QPixmap]] = {}
        self._current_frame_index = 0
        self._fps = settings.get("pet.animation_fps", ANIMATION_CONFIG["fps"])
        self._frame_interval = int(1000 / self._fps)

        # 帧播放定时器
        self._timer = QTimer(self)
        self._timer.setInterval(self._frame_interval)
        self._timer.timeout.connect(self._next_frame)

        # 状态持续时间控制
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.timeout.connect(self._on_state_duration_end)

        # 静止状态下的「小动作」插播（歪头 / 犯困 / 打哈欠）
        self._gesture_playing = False
        self._gesture_timer = QTimer(self)
        self._gesture_timer.setSingleShot(True)
        self._gesture_timer.timeout.connect(self._play_gesture)

        self._load_frames()

    # ---------------- 素材加载 ----------------

    def _load_frames(self) -> None:
        orig_dir = FRAMES_DIR / "orig"
        if orig_dir.exists() and any(orig_dir.glob("*.png")):
            self._load_state_frames(orig_dir)
        else:
            self._load_legacy_frames()

        # 兜底：任何状态没帧时用 idle，再没有用占位图
        idle_frames = self._frames.get(PetState.IDLE, [])
        for state in PetState:
            if not self._frames.get(state):
                self._frames[state] = idle_frames or [self._create_placeholder()]
        if not idle_frames:
            self._frames[PetState.IDLE] = [self._create_placeholder()]

        summary = {s.value: len(f) for s, f in self._frames.items()}
        print(f"动画帧加载完成: {summary}")

    def _load_state_frames(self, orig_dir: Path) -> None:
        for state, prefixes in STATE_PREFIX.items():
            frames: List[QPixmap] = []
            for prefix in prefixes:
                files = sorted(orig_dir.glob(f"{prefix}_*.png"))
                if state == PetState.IDLE:
                    # 待机只用睁眼帧白名单，过滤掉眨眼/笑脸帧
                    files = [f for f in files if f.name in IDLE_KEEP] or files[:1]
                if not files:
                    continue
                frames = [px for px in (self._load_pixmap(f) for f in files) if px]
                if frames:
                    print(f"  加载 {state.value}: {len(frames)} 帧 ({prefix}_*)")
                    break
            self._frames[state] = frames

    def _load_legacy_frames(self) -> None:
        """旧管线回退：nobg/selected 均分给 4 个状态"""
        all_frames: List[QPixmap] = []
        for name in ("nobg", "selected"):
            d = FRAMES_DIR / name
            if d.exists():
                all_frames.extend(
                    px for px in (self._load_pixmap(f) for f in sorted(d.glob("*.png"))) if px
                )
        if not all_frames:
            return
        per_state = max(1, len(all_frames) // 4)
        states = [PetState.IDLE, PetState.WALK_LEFT, PetState.WALK_RIGHT, PetState.INTERACT]
        for i, state in enumerate(states):
            seg = all_frames[i * per_state:(i + 1) * per_state if i < 3 else len(all_frames)]
            self._frames[state] = seg or all_frames[:1]
        print(f"  旧管线回退: 共 {len(all_frames)} 帧均分")

    def _load_pixmap(self, path: Path) -> Optional[QPixmap]:
        try:
            img = Image.open(path).convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            return QPixmap.fromImage(qimg.copy())  # copy 脱离缓冲区
        except Exception as e:
            print(f"加载图片失败 {path}: {e}")
            return None

    def _create_placeholder(self) -> QPixmap:
        from PySide6.QtGui import QPainter, QColor, QBrush
        size = settings.get("pet.size", 180)
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setBrush(QBrush(QColor(255, 200, 60, 220)))
        painter.setPen(QColor(255, 255, 255))
        painter.drawEllipse(10, 10, size - 20, size - 20)
        painter.drawText(pixmap.rect(), 0x0004 | 0x0080, "宠物")
        painter.end()
        return pixmap

    # ---------------- 状态与播放 ----------------

    def set_state(self, state: PetState, duration: Optional[int] = None, force: bool = False) -> None:
        """切换动画状态；force=True 时同状态也重新触发"""
        if state == self._state and not force:
            return
        self._state = state
        self._current_frame_index = 0
        self._gesture_playing = False
        self._gesture_timer.stop()          # 换状态即取消上一个小动作排程
        self.state_changed.emit(state.value)

        if duration is None:
            duration = self._default_duration(state)
        if duration and duration > 0:
            self._state_timer.start(duration)
        else:
            # duration=0 表示"常驻此状态，由外部结束"（如 DRAG、专注陪伴）。
            # 必须停掉残留计时器，否则上一状态的到期事件会把状态抢回 IDLE。
            self._state_timer.stop()

        self._emit_current_frame()

        if state in RESTING_STATES:
            # 静止类：常驻第 0 帧，只排一个"过会儿动一下"，不逐帧自播放
            self._timer.stop()
            self._schedule_gesture()
        elif state in FROZEN_STATES:
            # 冻结类：连小动作都不播，纯静态
            self._timer.stop()
        else:
            # 循环类（走路/互动）：按当前帧的延时启动下一次
            self._timer.start(self._frame_duration())

    def _schedule_gesture(self) -> None:
        """为静止类状态安排下一次小动作插播"""
        lo, hi = GESTURE_GAP_SECONDS.get(self._state, (8, 18))
        self._gesture_timer.start(random.randint(int(lo * 1000), int(hi * 1000)))

    def _play_gesture(self) -> None:
        """插播一次小动作（歪头 / 犯困 / 打哈欠），播完由 _next_frame 回常驻帧"""
        if self._state not in RESTING_STATES:
            return
        frames = self._frames.get(self._state, [])
        if len(frames) <= 1:                # 只有一帧，没得演，继续等下一轮
            self._schedule_gesture()
            return
        self._gesture_playing = True
        self._current_frame_index = 1       # 从第 2 帧开始演小动作
        self._emit_current_frame()
        self._timer.start(self._frame_duration())

    def _frame_duration(self) -> int:
        """当前帧应停留的毫秒数"""
        durs = FRAME_DURATIONS.get(self._state, [])
        if not durs:
            return self._frame_interval
        idx = min(self._current_frame_index, len(durs) - 1)
        return durs[idx]

    def _default_duration(self, state: PetState) -> int:
        # IDLE / SIT / LIE 一律返回 0（常驻），切换时机交给 pet_window 的
        # 行为时钟统一安排 —— 否则"状态计时器"和"行为计时器"两套时钟会互相
        # 抢跑，导致 1~3 秒就换一次姿势。0 = 常驻，由外部结束。
        if state in RESTING_STATES:
            return 0
        if state in (PetState.WALK_LEFT, PetState.WALK_RIGHT):
            return random.randint(
                settings.get("pet.walk_duration_min", 2000),
                settings.get("pet.walk_duration_max", 5000),
            )
        if state == PetState.INTERACT:
            return random.randint(800, 1500)
        return 0  # DRAG 常驻，由外部结束

    def _next_frame(self) -> None:
        frames = self._frames.get(self._state, [])
        if not frames:
            return

        if self._state in FROZEN_STATES:
            return

        if self._state in RESTING_STATES:
            # 静止类：只在"小动作插播"期间推进帧，演完立刻回常驻帧并停住
            if not self._gesture_playing:
                return
            nxt = self._current_frame_index + 1
            if nxt >= len(frames):
                self._gesture_playing = False
                self._current_frame_index = 0
                self._emit_current_frame()
                self._timer.stop()
                self._schedule_gesture()    # 排下一次小动作
                return
            self._current_frame_index = nxt
            self._emit_current_frame()
            self._timer.start(self._frame_duration())
            return

        # 循环类（走路/互动）：首尾相接
        self._current_frame_index = (self._current_frame_index + 1) % len(frames)
        self._emit_current_frame()
        # 按下一帧延时重启（单次触发）
        self._timer.start(self._frame_duration())

    def _emit_current_frame(self) -> None:
        frames = self._frames.get(self._state, [])
        if frames:
            self.frame_changed.emit(frames[self._current_frame_index])

    def _on_state_duration_end(self) -> None:
        """带时长的状态自然结束：先回到待机，再通知外部安排下一个行为。

        RESTING_STATES 是常驻状态（duration=0），不会走到这里。
        这里主要服务 WALK（走到一半超时）与 INTERACT（互动播完）。
        必须 emit state_finished，否则外部若在等"动作结束"来驱动下一个行为，
        就会一直等下去（实测会死锁：走路超时后 _is_moving 没清、宠物卡住不动）。
        """
        if self._state == PetState.DRAG:
            return
        if self._state != PetState.IDLE:
            self.set_state(PetState.IDLE)
        self.state_finished.emit()

    def trigger_interaction(self, kind: str = "click") -> None:
        """交互触发：播放互动动画后自动回待机"""
        self.set_state(PetState.INTERACT, duration=1200, force=True)

    def get_current_frame(self) -> Optional[QPixmap]:
        frames = self._frames.get(self._state, [])
        return frames[self._current_frame_index] if frames else None

    def get_state(self) -> PetState:
        return self._state

    def start(self) -> None:
        self.set_state(PetState.IDLE, force=True)

    def stop(self) -> None:
        self._timer.stop()
        self._state_timer.stop()
        self._gesture_timer.stop()

    def set_fps(self, fps: int) -> None:
        self._fps = fps
        self._frame_interval = int(1000 / fps)
        self._timer.setInterval(self._frame_interval)
