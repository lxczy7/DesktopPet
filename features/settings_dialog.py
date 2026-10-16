"""
设置对话框
功能：
1. 热键配置
2. 宠物行为设置
3. 壁纸设置
4. 截图设置
5. 开机自启开关
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLineEdit, QPushButton, QCheckBox, QLabel, QComboBox,
    QDialogButtonBox, QMessageBox, QSlider, QSpinBox
)
from PySide6.QtCore import Qt, QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator

from config.constants import DEFAULT_WALLPAPER_DIR
from config.settings_manager import settings


class SettingsDialog(QDialog):
    """设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("桌面宠物 - 设置")
        self.resize(500, 600)
        self.setModal(False)

        # 主布局
        layout = QVBoxLayout(self)

        # --- 宠物行为组 ---
        pet_group = QGroupBox("宠物行为")
        pet_layout = QFormLayout()

        # 宠物大小（实时预览）
        self._size_slider = QSlider(Qt.Horizontal)
        self._size_slider.setRange(60, 220)
        self._size_slider.setSingleStep(10)
        self._size_slider.setPageStep(10)
        self._size_slider.setValue(int(settings.get("pet.size", 90)))
        self._size_value_lbl = QLabel(f"{self._size_slider.value()} px")
        self._size_value_lbl.setMinimumWidth(56)
        size_row = QHBoxLayout()
        size_row.addWidget(self._size_slider)
        size_row.addWidget(self._size_value_lbl)
        self._size_slider.valueChanged.connect(self._on_size_changed)
        pet_layout.addRow("宠物大小", size_row)

        # 点击穿透
        self._click_through_cb = QCheckBox("点击穿透（不挡住下层窗口）")
        self._click_through_cb.setChecked(
            settings.get("general.click_through", False)
        )
        pet_layout.addRow("", self._click_through_cb)

        # 游走速度
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(1, 10)
        self._speed_slider.setValue(settings.get("pet.walk_speed", 3))
        self._speed_value_lbl = QLabel(f"速度: {self._speed_slider.value()}")
        self._speed_slider.valueChanged.connect(
            lambda v: self._speed_value_lbl.setText(f"速度: {v}")
        )
        pet_layout.addRow("游走速度", self._speed_slider)

        # 待机间隔（单位：秒；内部存储为毫秒，见 get_settings）
        self._idle_min_sb = QSpinBox()
        self._idle_min_sb.setRange(1, 120)
        self._idle_min_sb.setSuffix(" 秒")
        self._idle_min_sb.setValue(max(1, settings.get("pet.idle_interval_min", 3000) // 1000))
        pet_layout.addRow("最小待机间隔", self._idle_min_sb)

        self._idle_max_sb = QSpinBox()
        self._idle_max_sb.setRange(1, 120)
        self._idle_max_sb.setSuffix(" 秒")
        self._idle_max_sb.setValue(max(1, settings.get("pet.idle_interval_max", 8000) // 1000))
        pet_layout.addRow("最大待机间隔", self._idle_max_sb)

        # 动画帧率
        self._fps_sb = QSpinBox()
        self._fps_sb.setRange(8, 30)
        self._fps_sb.setValue(settings.get("pet.animation_fps", 12))
        pet_layout.addRow("动画帧率", self._fps_sb)

        pet_group.setLayout(pet_layout)
        layout.addWidget(pet_group)

        # --- 壁纸组 ---
        wallpaper_group = QGroupBox("壁纸设置")
        wp_layout = QFormLayout()

        self._auto_change_cb = QCheckBox("自动换壁纸")
        self._auto_change_cb.setChecked(
            settings.get("wallpaper.auto_change", True)
        )
        wp_layout.addRow("", self._auto_change_cb)

        self._interval_sb = QSpinBox()
        self._interval_sb.setRange(1, 168)  # 1小时到1周
        self._interval_sb.setValue(
            settings.get("wallpaper.change_interval_hours", 24)
        )
        wp_layout.addRow("换壁纸间隔(小时)", self._interval_sb)

        self._local_folder_btn = QPushButton("打开壁纸文件夹")
        self._local_folder_btn.clicked.connect(self._open_local_folder)
        wp_layout.addRow("", self._local_folder_btn)

        wallpaper_group.setLayout(wp_layout)
        layout.addWidget(wallpaper_group)

        # --- 热键组 ---
        hotkey_group = QGroupBox("全局热键")
        hk_layout = QFormLayout()

        # 热键输入框
        self._toggle_hk_edit = QLineEdit()
        self._toggle_hk_edit.setPlaceholderText("Ctrl+Alt+P (例如)")
        self._toggle_hk_edit.setText(
            settings.get("hotkeys.toggle_pet", "ctrl+alt+p")
        )
        # 添加验证：仅接受有效的热键字符
        validator = QRegularExpressionValidator(
            QRegularExpression(r"^[a-zA-Z0-9\+\s]+$")
        )
        self._toggle_hk_edit.setValidator(validator)
        hk_layout.addRow("切换宠物", self._toggle_hk_edit)

        self._screenshot_region_hk_edit = QLineEdit()
        self._screenshot_region_hk_edit.setPlaceholderText("Ctrl+Alt+A")
        self._screenshot_region_hk_edit.setText(
            settings.get("hotkeys.screenshot_region", "ctrl+alt+a")
        )
        hk_layout.addRow("区域截图", self._screenshot_region_hk_edit)

        self._screenshot_full_hk_edit = QLineEdit()
        self._screenshot_full_hk_edit.setPlaceholderText("Ctrl+Alt+S")
        self._screenshot_full_hk_edit.setText(
            settings.get("hotkeys.screenshot_full", "ctrl+alt+s")
        )
        hk_layout.addRow("全屏截图", self._screenshot_full_hk_edit)

        self._next_wallpaper_hk_edit = QLineEdit()
        self._next_wallpaper_hk_edit.setPlaceholderText("Ctrl+Alt+W")
        self._next_wallpaper_hk_edit.setText(
            settings.get("hotkeys.next_wallpaper", "ctrl+alt+w")
        )
        hk_layout.addRow("下一张壁纸", self._next_wallpaper_hk_edit)

        # 重置热键按钮
        self._reset_hk_btn = QPushButton("重置为默认值")
        self._reset_hk_btn.clicked.connect(self._reset_hotkeys)
        hk_layout.addRow("", self._reset_hk_btn)

        # 热键生效提示
        hk_hint = QLabel("提示：热键修改后需重启程序生效；若提示被占用，请换一组组合键。")
        hk_hint.setWordWrap(True)
        hk_hint.setStyleSheet("color: #888; font-size: 11px;")
        hk_layout.addRow("", hk_hint)

        hotkey_group.setLayout(hk_layout)
        layout.addWidget(hotkey_group)

        # --- 健康提醒组（借鉴 openpets 的 water-reminder / day-routine 插件）---
        remind_group = QGroupBox("健康提醒")
        remind_layout = QFormLayout()

        self._remind_enabled_cb = QCheckBox("开启定时提醒（宠物会来提醒你）")
        self._remind_enabled_cb.setChecked(settings.get("reminders.enabled", True))
        remind_layout.addRow("", self._remind_enabled_cb)

        self._drink_sb = QSpinBox()
        self._drink_sb.setRange(5, 240)
        self._drink_sb.setSuffix(" 分钟")
        self._drink_sb.setValue(int(settings.get("reminders.drink_minutes", 45)))
        remind_layout.addRow("喝水提醒间隔", self._drink_sb)

        self._sit_sb = QSpinBox()
        self._sit_sb.setRange(5, 240)
        self._sit_sb.setSuffix(" 分钟")
        self._sit_sb.setValue(int(settings.get("reminders.sit_minutes", 60)))
        remind_layout.addRow("久坐提醒间隔", self._sit_sb)

        quiet_row = QHBoxLayout()
        self._quiet_start_sb = QSpinBox()
        self._quiet_start_sb.setRange(0, 23)
        self._quiet_start_sb.setSuffix(" 点")
        self._quiet_start_sb.setValue(int(settings.get("reminders.quiet_start_hour", 22)))
        self._quiet_end_sb = QSpinBox()
        self._quiet_end_sb.setRange(0, 23)
        self._quiet_end_sb.setSuffix(" 点")
        self._quiet_end_sb.setValue(int(settings.get("reminders.quiet_end_hour", 8)))
        quiet_row.addWidget(self._quiet_start_sb)
        quiet_row.addWidget(QLabel("至"))
        quiet_row.addWidget(self._quiet_end_sb)
        remind_layout.addRow("免打扰时段", quiet_row)

        remind_hint = QLabel("提示：提醒会以宠物气泡 + 托盘通知的方式出现，不会弹窗打断。")
        remind_hint.setWordWrap(True)
        remind_hint.setStyleSheet("color: #888; font-size: 11px;")
        remind_layout.addRow("", remind_hint)

        remind_group.setLayout(remind_layout)
        layout.addWidget(remind_group)

        # --- 便利功能组 ---
        convenience_group = QGroupBox("便利功能")
        conv_layout = QFormLayout()

        self._auto_start_cb = QCheckBox("开机自启")
        self._auto_start_cb.setChecked(
            settings.get("general.auto_start", True)
        )
        conv_layout.addRow("", self._auto_start_cb)

        self._show_tray_cb = QCheckBox("显示系统托盘图标")
        self._show_tray_cb.setChecked(
            settings.get("general.show_tray_icon", True)
        )
        conv_layout.addRow("", self._show_tray_cb)

        self._screenshot_auto_copy_cb = QCheckBox("截图后自动复制到剪贴板")
        self._screenshot_auto_copy_cb.setChecked(
            settings.get("screenshot.auto_copy_to_clipboard", True)
        )
        conv_layout.addRow("", self._screenshot_auto_copy_cb)

        convenience_group.setLayout(conv_layout)
        layout.addWidget(convenience_group)

        # --- 对话框按钮 ---
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # 连接信号
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        self._auto_change_cb.toggled.connect(self._on_auto_change_toggled)
        self._auto_start_cb.toggled.connect(self._on_auto_start_toggled)

    def accept(self) -> None:
        """点击"确定"：保存所有设置后再关闭"""
        for key, value in self.get_settings().items():
            try:
                settings.set(key, value)
            except Exception as e:
                print(f"保存设置失败 {key}={value}: {e}")
        # 热键变化需要重启注册，给个明确反馈
        QMessageBox.information(self, "已保存", "设置已保存。\n热键修改需重启程序后生效。")
        super().accept()

    def _open_local_folder(self) -> None:
        """打开本地壁纸文件夹"""
        import subprocess
        import os
        folder = settings.get("wallpaper.local_folder", str(DEFAULT_WALLPAPER_DIR))
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif os.name == "posix":
                subprocess.run(["open", folder] if __import__("os").uname().sysname == "Darwin" else ["xdg-open", folder])
        except Exception as e:
            QMessageBox.warning(self, "打开失败", f"无法打开文件夹: {folder}\n{e}")

    def _reset_hotkeys(self) -> None:
        """重置热键为默认值"""
        defaults = {
            "hotkeys.toggle_pet": "ctrl+alt+p",
            "hotkeys.screenshot_region": "ctrl+alt+a",
            "hotkeys.screenshot_full": "ctrl+alt+s",
            "hotkeys.next_wallpaper": "ctrl+alt+w",
        }
        for key, value in defaults.items():
            settings.set(key, value)
            # 更新输入框
            if "toggle" in key:
                self._toggle_hk_edit.setText(value)
            elif "screenshot_region" in key:
                self._screenshot_region_hk_edit.setText(value)
            elif "screenshot_full" in key:
                self._screenshot_full_hk_edit.setText(value)
            elif "next_wallpaper" in key:
                self._next_wallpaper_hk_edit.setText(value)
        QMessageBox.information(self, "成功", "热键已重置为默认值")

    def _on_speed_changed(self, value: int) -> None:
        """速度滑块变化"""
        settings.set("pet.walk_speed", value)

    def _on_size_changed(self, value: int) -> None:
        """宠物大小变化：保存并让宠物实时变大小（所见即所得）"""
        self._size_value_lbl.setText(f"{value} px")
        settings.set("pet.size", value)
        parent = self.parent()
        apply_size = getattr(parent, "apply_pet_size", None)
        if callable(apply_size):
            apply_size(value)

    def _on_auto_change_toggled(self, checked: bool) -> None:
        """自动换壁纸开关"""
        settings.set("wallpaper.auto_change", checked)

    def _on_auto_start_toggled(self, checked: bool) -> None:
        """开机自启开关"""
        settings.set("general.auto_start", checked)
        # 实际注册/注销需要在 main.py 中处理，这里只保存配置
        # 可以通过父窗口通知
        if hasattr(self.parent(), "set_autostart"):
            self.parent().set_autostart(checked)

    def get_settings(self) -> dict:
        """获取所有设置"""
        return {
            "general.click_through": self._click_through_cb.isChecked(),
            "pet.size": self._size_slider.value(),
            "pet.walk_speed": self._speed_slider.value(),
            "pet.idle_interval_min": self._idle_min_sb.value() * 1000,
            "pet.idle_interval_max": max(self._idle_min_sb.value(), self._idle_max_sb.value()) * 1000,
            "pet.animation_fps": self._fps_sb.value(),
            "wallpaper.auto_change": self._auto_change_cb.isChecked(),
            "wallpaper.change_interval_hours": self._interval_sb.value(),
            "hotkeys.toggle_pet": self._toggle_hk_edit.text() or "ctrl+alt+p",
            "hotkeys.screenshot_region": self._screenshot_region_hk_edit.text() or "ctrl+alt+a",
            "hotkeys.screenshot_full": self._screenshot_full_hk_edit.text() or "ctrl+alt+s",
            "hotkeys.next_wallpaper": self._next_wallpaper_hk_edit.text() or "ctrl+alt+w",
            "general.auto_start": self._auto_start_cb.isChecked(),
            "general.show_tray_icon": self._show_tray_cb.isChecked(),
            "screenshot.auto_copy_to_clipboard": self._screenshot_auto_copy_cb.isChecked(),
            "reminders.enabled": self._remind_enabled_cb.isChecked(),
            "reminders.drink_minutes": self._drink_sb.value(),
            "reminders.sit_minutes": self._sit_sb.value(),
            "reminders.quiet_start_hour": self._quiet_start_sb.value(),
            "reminders.quiet_end_hour": self._quiet_end_sb.value(),
        }


# 用于测试
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    dialog = SettingsDialog()
    if dialog.exec() == QDialog.Accepted:
        settings_dict = dialog.get_settings()
        print("保存的设置:")
        for k, v in settings_dict.items():
            print(f"  {k}: {v}")