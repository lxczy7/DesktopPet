import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from PySide6.QtCore import QSettings, QStandardPaths

# 哨兵：用于区分"键不存在"与"键的值恰好是 None"
_MISSING = object()


class SettingsManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        if getattr(sys, "frozen", False):
            # PyInstaller 打包模式：用户设置写到 %APPDATA%/DesktopPet/
            # （exe 解包的临时目录重启即丢，不能用作持久化位置）
            appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
            self._settings_file = Path(appdata) / "DesktopPet" / "settings.json"
        else:
            self._settings_file = Path(__file__).parent / "settings.json"
        self._qt_settings = QSettings("DesktopPet", "DesktopPet")
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """加载配置文件；跨版本时用新默认重置（外观/结构重构后旧值不再适用）"""
        default_file = Path(__file__).parent / "settings.json"
        with open(default_file, "r", encoding="utf-8") as f:
            defaults = json.load(f)
        default_ver = defaults.get("_config_version", 1)

        if self._settings_file.exists():
            with open(self._settings_file, "r", encoding="utf-8") as f:
                user_data = json.load(f)
            user_ver = user_data.get("_config_version", 1)
            if user_ver != default_ver:
                # 版本不匹配：重置为新默认，并清掉注册表里的旧值防止回写覆盖
                print(f"配置版本升级 v{user_ver} -> v{default_ver}，重置为默认配置")
                self._data = defaults
                try:
                    self._qt_settings.clear()
                except Exception:
                    pass
                self.save()
            else:
                # 同版本：保留用户值，补全新增键
                self._data = self._merge_defaults(defaults, user_data)
        else:
            self._data = defaults
            self.save()

        # 从 QSettings 覆盖（用户运行时修改的配置）
        for key in self._data.keys():
            if key.startswith("_"):
                continue
            value = self._qt_settings.value(key)
            if value is not None:
                self._set_nested(self._data, key.split("."), value)

    @staticmethod
    def _merge_defaults(defaults: Dict, user: Dict) -> Dict:
        """以用户值为准，递归补全默认里存在而用户缺失的键"""
        merged = dict(user)
        for k, v in defaults.items():
            if k not in merged:
                merged[k] = v
            elif isinstance(v, dict) and isinstance(merged[k], dict):
                merged[k] = SettingsManager._merge_defaults(v, merged[k])
        return merged

    def save(self) -> None:
        """保存配置到 JSON 文件"""
        self._settings_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._settings_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的嵌套键"""
        keys = key.split(".")
        return self._get_nested(self._data, keys, default)

    def set(self, key: str, value: Any) -> None:
        """设置配置值"""
        keys = key.split(".")
        self._set_nested(self._data, keys, value)
        self._qt_settings.setValue(key, value)
        self.save()

    def has(self, key: str) -> bool:
        """判断配置键是否**真实存在于文件中**。

        与 ``get(key, default)`` 的区别：get 的 default 只在键不存在时生效，
        所以「键不存在」和「键的值是空串」在 get 看来是两回事，
        但业务代码里往往需要前者（才能正确走兜底路径）。
        """
        return self._get_nested(self._data, key.split("."), _MISSING) is not _MISSING

    def delete(self, key: str) -> None:
        """删除配置键（支持点号嵌套），并同步清掉 QSettings 里的旧值。

        ⚠️ 恢复现场时不要用 ``set(key, 默认值)`` —— 那会把键**永久固化**进
        settings.json，导致后续 ``get(key, default)`` 的兜底失效。
        原本就不存在的键，必须用 delete 移除。
        """
        keys = key.split(".")
        parent = self._get_nested(self._data, keys[:-1], _MISSING)
        if isinstance(parent, dict):
            parent.pop(keys[-1], None)
        try:
            self._qt_settings.remove(key)
        except Exception:
            pass
        self.save()

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取整个配置节"""
        return self._data.get(section, {})

    def update_section(self, section: str, values: Dict[str, Any]) -> None:
        """批量更新配置节"""
        if section not in self._data:
            self._data[section] = {}
        self._data[section].update(values)
        for k, v in values.items():
            self._qt_settings.setValue(f"{section}.{k}", v)
        self.save()

    def _get_nested(self, data: Dict, keys: list, default: Any) -> Any:
        for key in keys:
            if isinstance(data, dict) and key in data:
                data = data[key]
            else:
                return default
        return data

    def _set_nested(self, data: Dict, keys: list, value: Any) -> None:
        for key in keys[:-1]:
            data = data.setdefault(key, {})
        data[keys[-1]] = value


settings = SettingsManager()