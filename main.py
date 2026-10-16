import sys
import os
from pathlib import Path

# 添加项目根目录到路径
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))


def _enable_dpi_awareness() -> None:
    """显式开启 Per-Monitor V2 DPI 感知。

    必须在创建任何窗口/调用 Qt 之前执行。
    作用：125%/150% 等缩放设置下，Qt 逻辑坐标与物理抓屏坐标
    的换算（devicePixelRatio）才可靠，截屏选区不会错位。
    """
    try:
        import ctypes
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR
        except Exception:
            pass


_enable_dpi_awareness()

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QTimer, QSettings, QThread, Signal
from PySide6.QtGui import QIcon

from core.pet_window import PetWindow
from config.settings_manager import settings
from config.constants import ICONS_DIR


class _OnlineWallpaperWorker(QThread):
    """后台线程：联网抓一张随机壁纸 → 保存到壁纸库 → 设为屏幕壁纸。

    为什么要开线程：Bing 的 UHD 原图有 3~4 MB，叠加站点请求往返，
    在网络差的机器上可能耗时十几秒。放主线程会直接冻住宠物和菜单。
    """

    succeeded = Signal(object)  # WallpaperInfo
    failed = Signal(str)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager

    def run(self) -> None:
        try:
            info = self._manager.apply_online_wallpaper()
            if info is None:
                self.failed.emit("没抓到可用的壁纸（网络不通或壁纸站点异常）")
            else:
                self.succeeded.emit(info)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class DesktopPetApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setApplicationName("DesktopPet")
        self.setApplicationDisplayName("桌面宠物")
        self.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，托盘常驻

        # 设置应用图标
        icon_path = ICONS_DIR / "pet.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # 单实例检查
        self._check_single_instance()

        # 创建主窗口
        self._pet_window = PetWindow()
        self._connect_signals()

        # 显示宠物
        self._pet_window.show()

        # 注册全局热键（延迟执行，避免阻塞启动）
        QTimer.singleShot(1000, self._register_hotkeys)

        # 退出前注销热键
        self.aboutToQuit.connect(self._cleanup_hotkeys)
        self.aboutToQuit.connect(self._cleanup_services)

        # 开机自启检查
        QTimer.singleShot(2000, self._ensure_autostart)

        # 提醒服务（喝水 / 久坐，借鉴 openpets 的 water-reminder、day-routine 插件）
        try:
            from features.reminders import ReminderService
            self._reminders = ReminderService(self._pet_window, self)
            self._reminders.start()
        except Exception as e:
            print(f"提醒服务启动失败: {e}")

        # 专注 / 呼吸 / 趣味（借鉴 openpets 的 focus-buddy、
        # anxiety-aid-tools、fortune-cookie / magic-8-ball / mood-check-in）
        self._pomodoro = None
        self._breathing = None
        self._fun = None
        try:
            from features.pomodoro import PomodoroService
            from features.breathing import BreathingService
            from features.fun_interactions import FunInteractions
            self._pomodoro = PomodoroService(self._pet_window, self)
            self._breathing = BreathingService(self._pet_window, self)
            self._fun = FunInteractions(self._pet_window, self)
        except Exception as e:
            print(f"专注/呼吸/趣味服务启动失败: {e}")

    def _cleanup_hotkeys(self) -> None:
        mgr = getattr(self, "_hotkey_manager", None)
        if mgr is not None:
            try:
                mgr.unregister_all()
            except Exception:
                pass

    def _check_single_instance(self) -> None:
        """单实例运行检查（简单版本）"""
        import socket
        try:
            # 尝试绑定本地端口作为锁
            self._lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._lock_socket.bind(("127.0.0.1", 19847))
            self._lock_socket.listen(1)
        except OSError:
            # 已经有实例运行
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "桌面宠物", "程序已在运行中！")
            sys.exit(1)

    def _connect_signals(self) -> None:
        """连接宠物窗口信号到处理函数"""
        w = self._pet_window
        w.screenshot_requested.connect(self._handle_screenshot)
        w.wallpaper_change_requested.connect(self._handle_wallpaper_change)
        w.clipboard_history_requested.connect(self._handle_clipboard_history)
        w.settings_requested.connect(self._handle_settings)
        w.quit_requested.connect(self.quit)
        w.pomodoro_requested.connect(self._handle_pomodoro)
        w.breathing_requested.connect(self._handle_breathing)
        w.fun_requested.connect(self._handle_fun)

    def _handle_screenshot(self, mode: str) -> None:
        """处理截图请求（右键菜单/热键共用，异常不外抛防止杀进程）"""
        try:
            from features.screenshot_tool import ScreenshotTool
            # 截图期间隐藏宠物：既避免宠物入镜，也让用户专注选区
            self._pet_window.hide_for_capture()
            tool = ScreenshotTool(self._pet_window)
            # 截图流程结束（成功/失败/取消）→ 恢复宠物；
            # 全屏/窗口模式编辑器已关闭，补一句完成反馈；
            # 区域模式编辑器紧接着弹出，保持安静不打扰
            def _on_done():
                self._pet_window.restore_after_capture()
                if mode != "region":
                    QTimer.singleShot(300, lambda: self._pet_window.speak("截图好啦！"))
            tool.on_finished = _on_done
            # 悬浮窗保存成功 → 托盘通知 + 宠物亲口告知保存位置
            def _on_saved(path):
                self._pet_window.notify("📸 截图已保存", f"保存位置：{path}")
                self._pet_window.speak(f"保存好啦：{path.name}")
            tool.on_shot_saved = _on_saved
            if mode == "region":
                tool.capture_region()
            elif mode == "full":
                tool.capture_fullscreen()
            elif mode == "window":
                tool.capture_window()
        except Exception as e:
            # 异常也要恢复宠物，否则宠物"消失"
            try:
                self._pet_window.restore_after_capture()
            except Exception:
                pass
            QMessageBox.warning(None, "截图失败", f"截图功能出错：{e}")

    def _handle_wallpaper_change(self, action: str) -> None:
        """处理换壁纸请求"""
        try:
            from features.wallpaper_manager import get_wallpaper_manager
            # 先在主线程取单例：管理器内部持有 QTimer，
            # 若首次实例化发生在子线程会触发 "Timers can only be used
            # with threads started with QThread" 报错。
            manager = get_wallpaper_manager()

            if action == "online":
                self._apply_online_wallpaper(manager)
                return

            if action in ("next", "random"):
                info = manager.random_wallpaper() if action == "random" else manager.next_wallpaper()
                if info is None:
                    self._pet_window.notify(
                        "🖼️ 没有可用壁纸",
                        f"本地壁纸库为空且联网获取失败。\n请把图片放到：{manager._local_folder}")
                    return
                if manager.set_current_wallpaper(info):
                    self._pet_window.notify("🖼️ 壁纸已切换", f"当前：{info.title}")
                    self._pet_window.speak(f"壁纸换成「{info.title}」啦~")
                else:
                    self._pet_window.notify(
                        "🖼️ 切换失败",
                        "系统拒绝了壁纸设置请求。\n"
                        "（常见原因：图片文件损坏 / 被其他程序锁定）")
            elif action == "open_folder":
                manager.open_wallpaper_folder()
            elif action == "settings":
                self._handle_settings()
        except Exception as e:
            QMessageBox.warning(None, "换壁纸失败", f"换壁纸功能出错：{e}")

    def _apply_online_wallpaper(self, manager) -> None:
        """联网随机壁纸：后台抓取 → 存入壁纸库 → 立即设为屏幕壁纸。

        全程异步，先给「正在找」的即时反馈，避免用户以为点了没反应。
        """
        running = getattr(self, "_wp_worker", None)
        try:
            if running is not None and running.isRunning():
                self._pet_window.speak("还在下载呢，稍等一下下~")
                return
        except RuntimeError:
            # 上一个 worker 已被 Qt 回收，忽略
            self._wp_worker = None

        pet = self._pet_window
        pet.notify("🌐 正在联网找壁纸", "正在随机挑选并下载高清壁纸，请稍候…")
        pet.speak("我去网上淘张壁纸~")

        worker = _OnlineWallpaperWorker(manager)
        self._wp_worker = worker

        def _on_ok(info) -> None:
            try:
                pet.notify("🖼️ 新壁纸已就位", f"{info.title}\n已保存到：{info.local_path}")
                pet.speak(f"换上了「{info.title}」~")
            except Exception:
                pass

        def _on_fail(msg: str) -> None:
            try:
                pet.notify("🖼️ 联网换壁纸失败",
                           f"{msg}\n可以先试试「下一张」用本地壁纸。")
            except Exception:
                pass

        def _on_done() -> None:
            self._wp_worker = None

        worker.succeeded.connect(_on_ok)
        worker.failed.connect(_on_fail)
        worker.finished.connect(_on_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    # ---------------- 专注 / 呼吸 / 趣味 ----------------

    def _handle_pomodoro(self, action: str, minutes: int) -> None:
        """番茄钟：菜单动作 -> 服务方法"""
        svc = getattr(self, "_pomodoro", None)
        if svc is None:
            return
        pet = self._pet_window
        try:
            if action == "start":
                svc.start_focus(minutes)
            elif action == "break":
                svc.start_break(minutes)
            elif action == "pause":
                if not svc.is_running():
                    pet.notify("🎯 番茄钟", svc.status_text())
                    return
                paused = svc.toggle_pause()
                pet.notify("🎯 番茄钟",
                           "已暂停，随时可以继续" if paused else "继续专注，加油！")
            elif action == "status":
                pet.notify("🎯 番茄钟", svc.status_text())
            elif action == "stop":
                svc.stop()
        except Exception as e:
            QMessageBox.warning(None, "番茄钟", f"出错：{e}")

    def _handle_breathing(self, action: str, rounds: int) -> None:
        """4-7-8 呼吸引导"""
        svc = getattr(self, "_breathing", None)
        if svc is None:
            return
        try:
            if action == "start":
                if svc.is_running():
                    self._pet_window.notify("🫁 呼吸放松",
                                            "已经在引导中啦，跟着节奏呼吸～")
                    return
                svc.start(rounds)
            elif action == "stop":
                svc.stop()
        except Exception as e:
            QMessageBox.warning(None, "呼吸放松", f"出错：{e}")

    def _handle_fun(self, kind: str) -> None:
        """趣味互动：今日运势 / 魔法八球 / 情绪打卡"""
        svc = getattr(self, "_fun", None)
        if svc is None:
            return
        try:
            if kind == "fortune":
                svc.daily_fortune()
            elif kind == "8ball":
                svc.magic_8_ball()
            elif kind == "mood":
                svc.mood_checkin()
        except Exception as e:
            QMessageBox.warning(None, "趣味互动", f"出错：{e}")

    def _cleanup_services(self) -> None:
        """退出前停掉定时服务，避免残留定时器"""
        for name in ("_pomodoro", "_breathing"):
            svc = getattr(self, name, None)
            if svc is not None:
                try:
                    svc.stop(silent=True)
                except Exception:
                    pass

    def _handle_clipboard_history(self) -> None:
        """显示剪贴板历史"""
        try:
            from features.clipboard_history import ClipboardHistoryDialog
            dialog = ClipboardHistoryDialog(self._pet_window)
            dialog.exec()
        except Exception as e:
            QMessageBox.warning(None, "剪贴板历史", f"打开失败：{e}")

    def _handle_settings(self) -> None:
        """打开设置对话框（对话框自行负责保存）"""
        try:
            from features.settings_dialog import SettingsDialog
            dialog = SettingsDialog(self._pet_window)
            dialog.exec()
            # 提醒相关配置可能被改动 → 立即按新配置重启定时器
            reminders = getattr(self, "_reminders", None)
            if reminders is not None:
                reminders.reload()
        except Exception as e:
            QMessageBox.warning(None, "设置", f"打开设置失败：{e}")

    def _register_hotkeys(self) -> None:
        """注册全局热键（Windows 原生 RegisterHotKey，系统级可靠）

        每个热键带候选列表：默认组合被其他软件占用时自动顺延，
        保证在不同用户的机器上开箱可用（商用分发场景关键）。
        """
        try:
            from utils.native_hotkey import NativeHotkeyManager
            self._hotkey_manager = NativeHotkeyManager(self)
            self._hotkey_manager.attach(self._pet_window)
            hk = settings.get_section("hotkeys")

            candidates = {
                "toggle_pet": (
                    self._pet_window.toggle_visibility,
                    [hk.get("toggle_pet", "ctrl+alt+p"), "ctrl+alt+o", "ctrl+alt+h"],
                ),
                "screenshot_region": (
                    lambda: self._handle_screenshot("region"),
                    [hk.get("screenshot_region", "ctrl+alt+a"), "ctrl+alt+q"],
                ),
                "screenshot_full": (
                    lambda: self._handle_screenshot("full"),
                    [hk.get("screenshot_full", "ctrl+alt+s"), "ctrl+alt+j"],
                ),
                "next_wallpaper": (
                    lambda: self._handle_wallpaper_change("next"),
                    [hk.get("next_wallpaper", "ctrl+alt+w"), "ctrl+alt+k"],
                ),
            }

            for key, (callback, options) in candidates.items():
                chosen = None
                for opt in options:
                    if self._hotkey_manager.register(opt, callback):
                        chosen = opt
                        break
                if chosen is None:
                    print(f"热键 {key}: 所有候选组合均被占用")
                    continue
                if chosen != options[0]:
                    # 顺延成功：写回设置并通知用户
                    settings.set(f"hotkeys.{key}", chosen)
                    print(f"热键 {key} 顺延为 {chosen}")
                    self._pet_window.notify(
                        "桌面宠物 - 热键调整",
                        f"{options[0].upper()} 被其他软件占用，"
                        f"{key} 已自动切换为 {chosen.upper()}\n"
                        f"（可在右键菜单 → 设置中修改）")
        except Exception as e:
            print(f"热键注册失败: {e}")

    def _ensure_autostart(self) -> None:
        """确保开机自启设置"""
        if settings.get("general.auto_start", True):
            self._set_autostart(True)

    def _set_autostart(self, enable: bool) -> None:
        """设置开机自启（Windows 注册表）"""
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            app_name = "DesktopPet"
            if getattr(sys, "frozen", False):
                # PyInstaller 打包后：直接运行 exe（窗口程序，无控制台）
                exe_path = f'"{Path(sys.executable)}"'
            else:
                # 开发模式：优先用 pythonw.exe，避免开机自启时闪控制台窗口
                pythonw = Path(sys.executable).parent / "pythonw.exe"
                runner = pythonw if pythonw.exists() else Path(sys.executable)
                exe_path = f'"{runner}" "{BASE_DIR / "main.py"}"'

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
            settings.set("general.auto_start", enable)
        except Exception as e:
            print(f"设置开机自启失败: {e}")


def main():
    # 高 DPI 支持（Qt6 已默认开启，AA_EnableHighDpiScaling 等属性已废弃）
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = DesktopPetApp(sys.argv)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())