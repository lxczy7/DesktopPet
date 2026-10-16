# -*- coding: utf-8 -*-
"""换壁纸链路验证（不修改真实壁纸：SystemParametersInfoW 全部 mock）

背景：宣哥反馈右键"换壁纸 → 下一张"报
      AttributeError: type object 'WallpaperManager' has no attribute 'get_instance'
本脚本锁死该回归点，并覆盖整条链路。
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PIL import Image  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from features.wallpaper_manager import (  # noqa: E402
    WallpaperManager, WallpaperInfo, get_wallpaper_manager)
from config.settings_manager import settings  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


tmp = Path(tempfile.mkdtemp(prefix="dpet_wp_"))
(tmp / "screenshots").mkdir(parents=True, exist_ok=True)
# 造 3 张壁纸 + 1 张"截图"（截图必须被排除）
for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
    Image.new("RGB", (64, 48), color).save(tmp / f"wall_{i}.jpg")
Image.new("RGB", (32, 32), (0, 0, 0)).save(tmp / "screenshots" / "shot_1.png")

old_local = settings.get("wallpaper.local_folder", "")
old_cache = settings.get("wallpaper.cache_folder", "")
settings.set("wallpaper.local_folder", str(tmp))
settings.set("wallpaper.cache_folder", str(tmp / "cache"))

try:
    # ---------- W1/W2 单例入口（用户报错点） ----------
    m1 = get_wallpaper_manager()
    m2 = WallpaperManager()
    check("W1. get_wallpaper_manager 返回单例", m1 is m2)

    try:
        m3 = WallpaperManager.get_instance()
        ok_alias, err = m3 is m1, ""
    except AttributeError as e:
        ok_alias, err = False, str(e)
    check("W2. WallpaperManager.get_instance() 兼容别名可用（回归点）", ok_alias, err)

    # ---------- W3 主程序调用路径不再抛错 ----------
    import main as main_mod
    from types import SimpleNamespace

    captured = {}

    class _FakePet:
        def notify(self, t, m):
            captured["notify"] = (t, m)

        def speak(self, t):
            captured["speak"] = t

    # 不走 QApplication.__init__，直接以轻量 self 调用绑定方法
    fake_self = SimpleNamespace(_pet_window=_FakePet(), _reminders=None)
    err = ""
    with patch.object(WallpaperManager, "set_current_wallpaper", return_value=True), \
         patch("PySide6.QtWidgets.QMessageBox.warning") as mw:
        try:
            main_mod.DesktopPetApp._handle_wallpaper_change(fake_self, "next")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        if mw.called:
            err = err or f"弹出了错误框: {mw.call_args}"
    check("W3. 主程序『换壁纸→下一张』不抛异常", not err and "notify" in captured,
          err or str(captured.get("notify")))

    # ---------- W4 本地列表排除截图子目录 ----------
    mgr = get_wallpaper_manager()
    files = mgr._list_local_files()
    names = sorted(f.name for f in files)
    check("W4. 本地壁纸只扫顶层，排除 screenshots 子目录",
          len(files) == 3 and "shot_1.png" not in names, f"{names}")

    # ---------- W5 next_wallpaper 轮换 ----------
    info = mgr.next_wallpaper()
    check("W5a. next_wallpaper 返回本地壁纸",
          info is not None and info.local_path is not None and info.local_path.exists(),
          info.title if info else "None")
    first = info.local_path
    second = mgr.next_wallpaper()
    check("W5b. 下一次不重复上一张（图>1 时）",
          second is not None and second.local_path != first,
          f"{first.name} -> {second.local_path.name}")

    # ---------- W6 设置壁纸调用系统 API（mock，不真改壁纸） ----------
    class _FakeUser32:
        def __init__(self):
            self.calls = []

        def SystemParametersInfoW(self, *args):
            self.calls.append(args)
            return 1

    fake = _FakeUser32()
    with patch("ctypes.windll.user32", fake):
        ok = mgr.set_current_wallpaper(info)
    check("W6. set_current_wallpaper 调用 SystemParametersInfoW(SPI_SETDESKWALLPAPER=20)",
          ok and fake.calls and fake.calls[0][0] == 20,
          f"调用={fake.calls[0] if fake.calls else '无'}")

    # ---------- W7 空目录 + 联网失败 -> None（不崩） ----------
    empty = Path(tempfile.mkdtemp(prefix="dpet_wp_empty_"))
    old_local2 = settings.get("wallpaper.local_folder")
    settings.set("wallpaper.local_folder", str(empty))
    mgr2 = WallpaperManager()
    mgr2._local_folder = empty
    mgr2._cache_folder = empty / "cache"
    with patch.object(WallpaperManager, "_online_fallback", return_value=None):
        none_info = mgr2.next_wallpaper()
    settings.set("wallpaper.local_folder", old_local2)
    check("W7. 本地空 + 联网失败安全返回 None", none_info is None, str(none_info))

    # ---------- W8 webp 自动转 PNG ----------
    webp = tmp / "pic.webp"
    Image.new("RGB", (64, 48), (120, 200, 90)).save(webp, "WEBP")
    w_info = mgr._local_info(webp)
    fake2 = _FakeUser32()
    with patch("ctypes.windll.user32", fake2):
        ok8 = mgr.set_current_wallpaper(w_info)
    target = fake2.calls[0][2] if fake2.calls else ""
    check("W8. webp 壁纸自动转 PNG 后设置", ok8 and target.lower().endswith(".png"),
          f"目标={target}")

    # ---------- W9 打开文件夹不抛异常 ----------
    err9 = ""
    with patch("os.startfile", create=True) as sf:
        try:
            mgr.open_wallpaper_folder()
        except Exception as e:
            err9 = str(e)
    check("W9. 打开壁纸文件夹不抛异常", not err9 and sf.called, err9 or "os.startfile 已调用")

    # ================= 联网随机壁纸（v3 新增） =================
    # 全部走 mock：不真连网、不真改壁纸，可在无网环境稳定回归
    import io

    class _FakeResp:
        def __init__(self, payload=None, content=b"", status=200):
            self._payload = payload
            self.content = content
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    BING_JSON = {"images": [
        {"urlbase": "/th?id=OHR.AlphaTest_ZH-CN111",
         "copyright": "测试山，某地，某国 (© Someone/Getty Images)"},
        {"urlbase": "/th?id=OHR.BetaTest_ZH-CN222",
         "copyright": "测试湖 (© Xxx)"},
    ]}

    _buf = io.BytesIO()
    # 用噪声图：纯色 JPEG 会被压到 4KB 以下，过不了下载体积校验
    import numpy as _np
    _noise = _np.random.default_rng(7).integers(0, 256, (360, 640, 3), dtype=_np.uint8)
    Image.fromarray(_noise, "RGB").save(_buf, "JPEG", quality=92)
    IMG_BYTES = _buf.getvalue()
    assert len(IMG_BYTES) > 4096, "测试图片字节需 >4096（下载体积校验阈值）"

    def _fake_get(url, *a, **kw):
        if "HPImageArchive" in url:
            return _FakeResp(payload=BING_JSON)
        return _FakeResp(content=IMG_BYTES)

    lib = tmp / "lib3"
    mgr3 = WallpaperManager()
    mgr3._local_folder = lib
    mgr3._cache_folder = tmp / "cache3"

    # ---------- W10 必应每日壁纸解析 ----------
    mgr3._downloaded_hashes.clear()
    with patch("features.wallpaper_manager.requests.get", side_effect=_fake_get):
        bing = mgr3.fetch_bing_wallpapers(days=3)
    check("W10. 必应每日壁纸解析（UHD 4K / source=bing / 标题取自版权串）",
          len(bing) == 2 and all(b.url.endswith("_UHD.jpg") for b in bing)
          and all(b.source == "bing" for b in bing) and "测试山" in bing[0].title,
          f"{len(bing)} 条 | {bing[0].title if bing else 'None'}")

    # ---------- W11 主源优先 ----------
    mgr3._downloaded_hashes.clear()
    with patch("features.wallpaper_manager.requests.get", side_effect=_fake_get):
        pick = mgr3.fetch_online_random()
    check("W11. fetch_online_random 优先选必应源（免 Key、国内直连）",
          pick is not None and pick.source == "bing",
          f"source={pick.source if pick else 'None'}")

    # ---------- W12 下载落到「壁纸保存路径」+ 文件名可读 ----------
    mgr3._downloaded_hashes.clear()
    cand = WallpaperInfo(
        url="https://www.bing.com/th?id=OHR.AlphaTest_ZH-CN111_UHD.jpg",
        title="测试山，某地，某国", resolution="3840x2160",
        source="bing", md5="deadbeefcafe1234")
    with patch("features.wallpaper_manager.requests.get", side_effect=_fake_get):
        ok12 = mgr3.download_to_library(cand)
    saved = cand.local_path
    check("W12. download_to_library 落盘到壁纸库（local_folder，非隐藏缓存）",
          ok12 and saved is not None and saved.exists()
          and saved.parent.resolve() == lib.resolve(),
          f"{saved.name if saved else 'None'}")
    check("W12b. 入库文件名带可读中文标题，不再是纯哈希",
          saved is not None and "测试山" in saved.name and "deadbe" in saved.name,
          saved.name if saved else "")

    # ---------- W13 一键流程：抓取 → 入库 → 设为屏幕壁纸 ----------
    mgr3._downloaded_hashes.clear()
    fake13 = _FakeUser32()
    with patch("features.wallpaper_manager.requests.get", side_effect=_fake_get), \
         patch("ctypes.windll.user32", fake13):
        applied = mgr3.apply_online_wallpaper()
    check("W13. apply_online_wallpaper 全链路（抓取→入库→SystemParametersInfoW）",
          applied is not None and applied.local_path is not None
          and applied.local_path.exists() and bool(fake13.calls)
          and fake13.calls[0][0] == 20,
          f"{applied.local_path.name if applied and applied.local_path else 'None'}")

    # ---------- W14 断网降级 ----------
    mgr3._downloaded_hashes.clear()

    def _boom(*a, **kw):
        raise ConnectionError("network unreachable")

    with patch("features.wallpaper_manager.requests.get", side_effect=_boom):
        dead = mgr3.fetch_online_random()
    check("W14. 断网时 fetch_online_random 安全返回 None（不抛异常）",
          dead is None, str(dead))

    # ---------- W15 下一张=顺序轮换 / 随机=真随机 ----------
    seq = tmp / "seq"
    seq.mkdir(parents=True, exist_ok=True)
    for nm in ("a.jpg", "b.jpg", "c.jpg"):
        Image.new("RGB", (16, 16), (10, 10, 10)).save(seq / nm)
    mgr4 = WallpaperManager()
    mgr4._local_folder = seq
    mgr4._cache_folder = seq / "cache"
    mgr4._current_wallpaper = None
    order = [Path(mgr4.next_wallpaper().local_path).name for _ in range(3)]
    check("W15. 『下一张』按文件名顺序轮换 a→b→c（语义可预期）",
          order == ["a.jpg", "b.jpg", "c.jpg"], str(order))

    mgr4._current_wallpaper = None
    picks = {Path(mgr4.random_wallpaper().local_path).name for _ in range(80)}
    check("W15b. 『随机一张』能覆盖整个本地库",
          picks == {"a.jpg", "b.jpg", "c.jpg"}, str(sorted(picks)))

    # ---------- W16 文件名清洗 ----------
    n1 = WallpaperManager._safe_name("斯奈费尔斯山，里奇韦附近，美国 (© X/Y)")
    n2 = WallpaperManager._safe_name('a/b:c*d?e"f<g>h|i')
    n3 = WallpaperManager._safe_name("   ")
    check("W16. 文件名清洗：取首分句 + 剔除 Windows 非法字符 + 空值兜底",
          n1 == "斯奈费尔斯山" and n2 == "abcdefghi" and n3 == "wallpaper",
          f"{n1!r} / {n2!r} / {n3!r}")

    # ---------- W17 主程序 online 分支：必须走后台线程，不阻塞 UI ----------
    captured2 = {}

    class _FakePet2:
        def notify(self, t, m):
            captured2["notify"] = (t, m)

        def speak(self, t):
            captured2["speak"] = t

    fake_self2 = SimpleNamespace(_pet_window=_FakePet2(), _reminders=None)
    # SimpleNamespace 不会从 DesktopPetApp 继承方法，需手动挂上被调用的实例方法，
    # 否则 self._apply_online_wallpaper 会 AttributeError → 落到 QMessageBox 模态框卡死
    fake_self2._apply_online_wallpaper = (
        lambda mgr: main_mod.DesktopPetApp._apply_online_wallpaper(fake_self2, mgr))
    fake_self2._handle_settings = lambda: None
    err17 = ""
    with patch.object(WallpaperManager, "apply_online_wallpaper", return_value=None), \
         patch("PySide6.QtWidgets.QMessageBox.warning") as mw17:
        try:
            main_mod.DesktopPetApp._handle_wallpaper_change(fake_self2, "online")
        except Exception as e:
            err17 = f"{type(e).__name__}: {e}"
        if mw17.called:
            err17 = err17 or f"弹出了错误框: {mw17.call_args}"
        running = getattr(fake_self2, "_wp_worker", None)
        check("W17. 主程序『联网随机壁纸』起后台线程且不抛异常",
              not err17 and running is not None and "notify" in captured2,
              err17 or f"worker={type(running).__name__ if running else 'None'}")
        if running is not None:
            running.wait(15000)  # 等线程收尾，避免退出时残留

finally:
    settings.set("wallpaper.local_folder", old_local)
    settings.set("wallpaper.cache_folder", old_cache)

fails = [r for r in results if not r[1]]
print(f"\n===== {len(results) - len(fails)}/{len(results)} 通过 =====")
sys.exit(1 if fails else 0)
