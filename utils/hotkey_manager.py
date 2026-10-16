"""
全局热键管理器 v2
- 按键按规范值匹配：功能键归一到 'ctrl'/'alt'/'shift'（兼容左右键），
  字符键按 vk 虚拟键码匹配（不依赖 char，兼容注入输入与各种键盘布局）
"""
from pynput import keyboard
from typing import Dict, Callable, Set
import threading
import time

# 功能键归一化别名：左右修饰键视为同一个
_SPECIAL_ALIAS = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt",
    "shift_l": "shift", "shift_r": "shift",
    "cmd_l": "cmd", "cmd_r": "cmd", "cmd": "cmd",
}


def _norm_key(key) -> tuple:
    """pynput key -> 可哈希规范值"""
    if isinstance(key, keyboard.Key):
        return ("k", _SPECIAL_ALIAS.get(key.name, key.name))
    if isinstance(key, keyboard.KeyCode):
        return ("vk", key.vk)
    return ("raw", str(key))


def _char_vk(ch: str) -> int:
    """字符 -> Windows 虚拟键码（VkKeyScanW 失败时回退 ASCII 大写码）"""
    import ctypes
    user32 = ctypes.windll.user32
    r = user32.VkKeyScanW(ch)
    vk = r & 0xFF
    if vk in (0, 0xFF):
        return ord(ch.upper())
    return vk


def _norm_str_key(part: str) -> tuple:
    """热键字符串片段 -> 规范值"""
    part = part.strip().lower()
    if part in _SPECIAL_ALIAS:
        return ("k", _SPECIAL_ALIAS[part])
    if len(part) == 1:
        # 字符键：按 vk 匹配（from_char.vk 在某些环境下为 None，不可依赖）
        return ("vk", _char_vk(part))
    try:
        k = getattr(keyboard.Key, part)
        return ("k", _SPECIAL_ALIAS.get(k.name, k.name))
    except AttributeError:
        return ("raw", part)


class HotkeyManager:
    def __init__(self):
        self._hotkeys: Dict[frozenset, Callable] = {}
        self._pressed_keys: Set[tuple] = set()
        self._listener: keyboard.Listener = None
        self._running = False

    def _parse_hotkey(self, hotkey_str: str) -> Set[tuple]:
        keys = set()
        for part in hotkey_str.lower().split("+"):
            keys.add(_norm_str_key(part))
        return keys

    def register(self, hotkey_str: str, callback: Callable) -> bool:
        try:
            key_set = self._parse_hotkey(hotkey_str)
            if not key_set:
                return False
            self._hotkeys[frozenset(key_set)] = callback
            return True
        except Exception as e:
            print(f"注册热键失败 {hotkey_str}: {e}")
            return False

    def unregister(self, hotkey_str: str) -> bool:
        key_set = self._parse_hotkey(hotkey_str)
        return self._hotkeys.pop(frozenset(key_set), None) is not None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        self._listener.start()

    def stop(self) -> None:
        self._running = False
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _on_press(self, key) -> None:
        self._pressed_keys.add(_norm_key(key))
        self._check_hotkeys()

    def _on_release(self, key) -> None:
        self._pressed_keys.discard(_norm_key(key))

    def _check_hotkeys(self) -> None:
        for key_set, callback in self._hotkeys.items():
            if key_set.issubset(self._pressed_keys):
                threading.Thread(target=callback, daemon=True).start()
                time.sleep(0.1)
                break

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


_global_hotkey_manager = None


def get_hotkey_manager() -> HotkeyManager:
    global _global_hotkey_manager
    if _global_hotkey_manager is None:
        _global_hotkey_manager = HotkeyManager()
    return _global_hotkey_manager
