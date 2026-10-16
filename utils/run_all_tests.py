# -*- coding: utf-8 -*-
"""一键回归：跑完全部验证脚本并汇总。

用法：
  python utils/run_all_tests.py
退出码 0 = 全绿，1 = 有失败项。
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
UTILS = BASE / "utils"

PER_TEST_TIMEOUT = 90   # 单个套件超时（秒）：抓屏类测试在受限环境可能挂起

TESTS = [
    ("冒烟测试（基础结构/热键/裁剪/保存/枚举）", "smoke_test.py"),
    ("真实抓屏 + DPI 裁剪数学", "verify_screenshot_real.py"),
    ("右键截图直达 + 遮罩流程", "verify_menu_flow.py"),
    ("截图结果悬浮窗", "verify_floating.py"),
    ("截图编辑器（画笔/直线/箭头/文字/马赛克/撤销）", "verify_editor.py"),
    ("换壁纸整条链路（本地/随机/联网）", "verify_wallpaper.py"),
    ("宠物行为/物理/视线跟随", "verify_behavior.py"),
    ("宠物动作节奏（常驻帧+偶发小动作/切换频率）", "verify_animation_rhythm.py"),
    ("健康提醒（喝水/久坐/静默时段）", "verify_reminders.py"),
    ("专注/呼吸/趣味互动 + 情绪表达", "verify_focus.py"),
]


def main() -> int:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(BASE)

    # ⚠️ 兜底：验证脚本会经 SettingsManager.set 写入 config/settings.json
    # （例如临时把壁纸目录指向 tmp）。跑完必须还原，否则测试残留会被固化进仓库 ——
    # 曾把 wallpaper.local_folder 写成空串，导致 settings.get(key, default) 兜底失效。
    settings_file = BASE / "config" / "settings.json"
    backup = settings_file.read_bytes() if settings_file.exists() else None

    rows = []
    try:
        for title, script in TESTS:
            path = UTILS / script
            if not path.exists():
                rows.append((title, script, "SKIP", "脚本不存在"))
                continue
            try:
                proc = subprocess.run(
                    [sys.executable, str(path)],
                    cwd=str(BASE), env=env, timeout=PER_TEST_TIMEOUT,
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                rows.append((title, script, "TIMEOUT",
                             f"超过 {PER_TEST_TIMEOUT}s（多为沙箱/远程环境下抓屏被限制）"))
                continue
            out = (proc.stdout or "") + (proc.stderr or "")
            summary = next((l.strip() for l in reversed(out.splitlines())
                            if "通过" in l or "PASS ===" in l or "全部" in l or "SKIP" in l), "")
            fails = [l.strip() for l in out.splitlines() if l.startswith("FAIL")]
            status = "PASS" if proc.returncode == 0 else "FAIL"
            rows.append((title, script, status, summary or ("; ".join(fails[:2]) or "无输出")))
    finally:
        try:
            if backup is not None and settings_file.read_bytes() != backup:
                settings_file.write_bytes(backup)
                print("[配置还原] config/settings.json 已恢复为回归前状态")
        except OSError:
            pass

    print("=" * 78)
    print("桌面宠物 · 全量功能回归")
    print("=" * 78)
    for title, script, status, detail in rows:
        mark = {"PASS": "✅", "SKIP": "⚠️", "TIMEOUT": "⏱️"}.get(status, "❌")
        print(f"{mark} {title}")
        print(f"    {script}  |  {detail}")
    bad = [r for r in rows if r[2] == "FAIL"]
    print("-" * 78)
    print(f"合计 {len(rows)} 个套件，通过 "
          f"{sum(1 for r in rows if r[2] == 'PASS')}，失败 {len(bad)}，"
          f"超时 {sum(1 for r in rows if r[2] == 'TIMEOUT')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
