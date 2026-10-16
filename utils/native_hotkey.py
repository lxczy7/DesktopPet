"""
原生全局热键（Windows RegisterHotKey）
比 pynput 底层 hook 更可靠：
  - 系统级注册，不受其他应用键盘 hook 干扰
  - WM_HOTKEY 消息驱动，无重复触发
  - 支持注册失败检测（热键被占用时返回 False）
"""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MOD_MAP = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "cmd": MOD_WIN,
}


def _char_vk(ch: str) -> int:
    user32 = ctypes.windll.user32
    r = user32.VkKeyScanW(ch)
    vk = r & 0xFF
    return ord(ch.upper()) if vk in (0, 0xFF) else vk


def _parse(hotkey_str: str):
    """'ctrl+alt+a' -> (mods, vk)"""
    mods = 0
    vk = None
    for part in hotkey_str.lower().split("+"):
        part = part.strip()
        if part in _MOD_MAP:
            mods |= _MOD_MAP[part]
        elif len(part) == 1:
            vk = _char_vk(part)
        else:
            # f1..f12 等命名键
            named = {"f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
                     "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
                     "f11": 0x7A, "f12": 0x7B,
                     "space": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09,
                     "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27}
            if part in named:
                vk = named[part]
    if vk is None:
        raise ValueError(f"无法解析热键: {hotkey_str}")
    return mods, vk


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_size_t),
        ("time", ctypes.c_uint),
        ("pt", wintypes.POINT),
    ]


class NativeHotkeyManager(QAbstractNativeEventFilter):
    """注册/接收系统级全局热键"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hotkeys = {}   # id -> (hotkey_str, callback)
        self._hwnd = None
        self._next_id = 1

    def attach(self, widget) -> None:
        """绑定到 Qt 窗口（取其原生 HWND）并安装事件过滤器"""
        self._hwnd = int(widget.winId())
        print(f"[native hotkey] attach hwnd={self._hwnd}")
        app = QApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self)

    def register(self, hotkey_str: str, callback) -> bool:
        try:
            mods, vk = _parse(hotkey_str)
        except ValueError as e:
            print(f"热键解析失败: {e}")
            return False
        if self._hwnd is None:
            print("热键管理器未 attach 到窗口")
            return False
        hk_id = self._next_id
        user32 = ctypes.windll.user32
        # MOD_NOREPEAT 防止长按重复触发
        ok = user32.RegisterHotKey(self._hwnd, hk_id, mods | MOD_NOREPEAT, vk)
        if not ok:
            err = ctypes.get_last_error()
            print(f"注册热键失败 {hotkey_str}: 可能被其他程序占用 (err={err})")
            return False
        self._next_id += 1  # 仅注册成功才消耗 id
        self._hotkeys[hk_id] = (hotkey_str, callback)
        print(f"热键注册成功: {hotkey_str}")
        return True

    def unregister_all(self) -> None:
        if self._hwnd is None:
            self._hotkeys.clear()
            return
        user32 = ctypes.windll.user32
        for hk_id in list(self._hotkeys):
            user32.UnregisterHotKey(self._hwnd, hk_id)
        self._hotkeys.clear()

    def nativeEventFilter(self, eventType, message):
        # eventType 在 PySide6 中是 QByteArray，需转成字符串比较
        try:
            et = bytes(eventType).decode("ascii", "ignore")
        except Exception:
            et = str(eventType)
        if "windows_generic_MSG" not in et and "windows_dispatcher_MSG" not in et:
            return False, 0
        try:
            msg = MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                entry = self._hotkeys.get(int(msg.wParam))
                if entry:
                    hotkey_str, callback = entry
                    try:
                        callback()
                    except Exception as e:
                        print(f"热键回调执行失败 {hotkey_str}: {e}")
                return True, 0
        except Exception as e:
            print(f"nativeEventFilter 解析失败: {e}")
        return False, 0
