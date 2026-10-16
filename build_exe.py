"""PyInstaller 一键打包：产出单文件 dist/DesktopPet.exe

用法：
    .venv/Scripts/python.exe build_exe.py

产物：
    dist/DesktopPet.exe   （单文件，约 50-60MB，可直接微信分发）

说明：
    - --onefile 单文件便于分享；如需更快启动可改 --onedir
    - resources/（动画帧+图标）与 config/（默认设置）随包分发
    - 打包后用户设置写入 %APPDATA%/DesktopPet/settings.json
    - 开机自启注册表项指向 exe 本身
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent

ONEFILE = "--onefile" in sys.argv


def main():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",                 # 无控制台窗口
        "--name", "DesktopPet",
        "--icon", str(BASE / "resources" / "icons" / "pet.ico"),
        # 只打包运行必需资源：动画帧 orig + 图标 + 默认配置
        # （raw/_tmp_gen/nobg/selected 是素材中间产物，共 20+MB，不进包）
        "--add-data", "resources/frames/orig;resources/frames/orig",
        "--add-data", "resources/icons;resources/icons",
        "--add-data", "config;config",
        "--exclude-module", "tkinter",
        "--exclude-module", "pynput",          # 旧热键方案，已不用
        "--exclude-module", "torch",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL.ImageQt",
    ]
    if ONEFILE:
        cmd.append("--onefile")
    cmd.append("main.py")

    print("打包命令:", " ".join(cmd))
    r = subprocess.run(cmd, cwd=BASE)
    if r.returncode != 0:
        print("打包失败")
        sys.exit(r.returncode)

    if ONEFILE:
        exe = BASE / "dist" / "DesktopPet.exe"
    else:
        exe = BASE / "dist" / "DesktopPet" / "DesktopPet.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"\n打包完成: {exe}  ({size_mb:.1f} MB)")
    else:
        print("\n警告: 未找到预期产物", exe)


if __name__ == "__main__":
    main()
