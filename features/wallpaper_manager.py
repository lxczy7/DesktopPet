# -*- coding: utf-8 -*-
"""
壁纸管理器 v3

v1 → v2 修复（历史）：
  1. 模块缺少 settings / constants import（实例化即 NameError）
  2. 依赖不存在的 APScheduler.Scheduler（ImportError）
  3. QCoreApplication.executeOnce 不存在
  4. 切换策略本末倒置：先爬网（慢/脆）后才看本地

v2 → v3 新增（联网随机壁纸）：
  1. 「下一张 / 随机一张」语义分离：
     - next  = 按文件名顺序轮换到下一张（可预期）
     - random = 整库随机（可能重复，但更"惊喜"）
  2. 新增「联网随机壁纸」：从壁纸网站随机挑一张 → 下载到**壁纸保存路径**
     （用户可见的本地库）→ 同时设为屏幕壁纸。
     主源 = 必应每日壁纸（免 Key、国内直连、可拿 4K UHD）；
     备源 = haowallpaper。
  3. 下载到本地库的文件带可读中文名（标题_日期_短哈希），不会再是一串
     随机 hash，用户打开壁纸文件夹能直接认出内容。

策略总览：
  - 本地优先：本地库有多张时立即轮换
  - 网络兜底：本地库为空才联网（Bing 优先，haowallpaper 兜底）
  - 显式联网：菜单「联网随机壁纸」→ 抓取 → 入库 → 立即生效
  - QTimer 定时自动更换（主线程，无需调度器线程）
"""
import os
import re
import json
import time
import hashlib
import random
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests
from PySide6.QtCore import QTimer

from config.constants import (
    DEFAULT_WALLPAPER_DIR,
    HAOWALLPAPER_CACHE_DIR,
    REQUEST_TIMEOUT,
    USER_AGENT,
    HAOWALLPAPER_BASE_URL,
    BING_ARCHIVE_URL,
    BING_HOST,
    BING_MARKET,
    BING_MAX_DAYS,
    BING_UHD_SUFFIX,
)
from config.settings_manager import settings
import config.constants as constants


class WallpaperInfo:
    """壁纸信息"""

    def __init__(
        self,
        url: str,
        title: str = "",
        resolution: str = "",
        source: str = "haowallpaper",
        md5: str = "",
    ):
        self.url = url
        self.title = title or os.path.basename(url).split("?")[0].split(".")[0].replace("-", " ").title()
        self.resolution = resolution
        self.source = source
        self.md5 = md5
        self.download_path: Optional[Path] = None
        self.local_path: Optional[Path] = None

    @property
    def is_downloaded(self) -> bool:
        return self.local_path is not None and self.local_path.exists()

    @property
    def md5_hash(self) -> str:
        if not self.local_path:
            return ""
        with open(self.local_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()


class WallpaperManager:
    """壁纸管理单例类"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @classmethod
    def get_instance(cls) -> "WallpaperManager":
        """单例访问别名（兼容旧调用点，避免 AttributeError）"""
        return cls()

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 配置（显式读取 settings，缺失时用 constants 默认值）
        self._local_folder = Path(
            settings.get("wallpaper.local_folder", str(DEFAULT_WALLPAPER_DIR))
        )
        self._cache_folder = Path(
            settings.get("wallpaper.cache_folder", str(HAOWALLPAPER_CACHE_DIR))
        )
        self._change_interval = settings.get("wallpaper.change_interval_hours", 24)
        self._preferred_resolution = settings.get("wallpaper.preferred_resolution", "1920x1080")
        self._auto_change = settings.get("wallpaper.auto_change", True)

        # 状态
        self._current_wallpaper: Optional[WallpaperInfo] = None
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_auto_change)
        self._downloaded_hashes: set = set()

        # 初始化文件夹 + 哈希库
        self._ensure_folders()
        self._load_downloaded_hashes()

        # 启动自动更换定时器（主线程 QTimer，间隔小时）
        if self._auto_change and self._change_interval > 0:
            self._timer.start(int(self._change_interval * 3600 * 1000))

    # ---------------- 基础设施 ----------------

    def _ensure_folders(self) -> None:
        try:
            self._local_folder.mkdir(parents=True, exist_ok=True)
            self._cache_folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"壁纸文件夹创建失败: {e}")

    def _load_downloaded_hashes(self) -> None:
        hash_file = self._cache_folder / ".downloaded_hashes.json"
        if hash_file.exists():
            try:
                with open(hash_file, "r", encoding="utf-8") as f:
                    self._downloaded_hashes = set(json.load(f))
            except Exception:
                self._downloaded_hashes = set()

    def _save_downloaded_hashes(self) -> None:
        try:
            with open(self._cache_folder / ".downloaded_hashes.json", "w", encoding="utf-8") as f:
                json.dump(list(self._downloaded_hashes), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _parse_resolution(self, resolution_str: str) -> tuple:
        if not resolution_str:
            return (0, 0)
        match = re.match(r"(\d+)\s*[×x]\s*(\d+)", resolution_str)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return (0, 0)

    @staticmethod
    def _safe_name(text: str, limit: int = 14) -> str:
        """把壁纸标题清洗成安全的文件名片段。

        中文版权串往往是「地点，方位，国家」的长句，取第一个分句就够辨识了；
        再剔除 Windows 非法字符 \\ / : * ? " < > | 与空白，超长时截断。
        注意分隔符只取中文顿逗句号 —— 问号叹号在英文标题里常是正文的一部分
        （如 "Hello? World"），不当分隔符处理。
        """
        t = re.split(r"[，,。;；、]", text or "")[0]
        t = re.sub(r'[\\/:*?"<>|\r\n\t（）()《》【】\[\]\s·—–\-]+', "", t)
        t = t.strip(". ")
        return t[:limit] or "wallpaper"

    def _meets_resolution(self, resolution_str: str) -> bool:
        """无分辨率信息时放行（宽松策略，避免过滤太狠无图可用）"""
        if not self._preferred_resolution:
            return True
        res_w, res_h = self._parse_resolution(resolution_str)
        pref_w, pref_h = self._parse_resolution(self._preferred_resolution)
        if res_w == 0 or res_h == 0 or pref_w == 0 or pref_h == 0:
            return True
        ratio_match = abs(res_w / res_h - pref_w / pref_h) < 0.15
        size_match = abs(res_w - pref_w) / pref_w < 0.4 and abs(res_h - pref_h) / pref_h < 0.4
        return ratio_match and size_match

    def _list_local_files(self) -> List[Path]:
        """本地壁纸：只扫壁纸根目录顶层，避免把 screenshots/ 子目录里的截图也当壁纸"""
        files: List[Path] = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"):
            try:
                files.extend(self._local_folder.glob(ext))
            except Exception:
                continue
        return [f for f in files if f.is_file()]

    # ---------------- 网络抓取 ----------------

    def fetch_bing_wallpapers(self, days: int = BING_MAX_DAYS) -> List[WallpaperInfo]:
        """必应每日壁纸：拉最近 N 天的元数据，返回可下载的 4K UHD 条目。

        优点：无需 API Key、国内可直连、接口是稳定的 JSON（不用解析 HTML）、
              每张都是 3840x2160 的 UHD 原图，质量有保证。
        接口 idx=0 是今天，最大可回溯 8 天（再往后会重复最后一张，故截断）。
        """
        results: List[WallpaperInfo] = []
        try:
            day_count = max(1, min(int(days), BING_MAX_DAYS))
            resp = requests.get(
                BING_ARCHIVE_URL,
                params={"format": "js", "idx": 0, "n": day_count, "mkt": BING_MARKET},
                headers={"User-Agent": USER_AGENT},
                timeout=min(REQUEST_TIMEOUT, 10),
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            print(f"必应壁纸抓取失败: {e}")
            return results

        for img in payload.get("images", []) or []:
            try:
                urlbase = (img.get("urlbase") or "").strip()
                if not urlbase:
                    continue
                url = f"{BING_HOST}{urlbase}{BING_UHD_SUFFIX}"
                md5 = hashlib.md5(url.encode("utf-8")).hexdigest()
                if md5 in self._downloaded_hashes:
                    continue  # 已经下过，跳过，避免重复占空间

                # 版权串形如「斯奈费尔斯山，…，美国 (© xxx/Getty Images)」
                # 取括号前的主体作为可读标题
                raw_title = (img.get("copyright") or "").strip()
                title = re.split(r"[（(]", raw_title)[0].strip() or "必应每日壁纸"

                results.append(WallpaperInfo(
                    url=url, title=title, resolution="3840x2160",
                    source="bing", md5=md5))
            except Exception:
                continue
        return results

    def fetch_online_random(self) -> Optional[WallpaperInfo]:
        """联网随机挑一张壁纸（只返回候选，不下载）。

        优先级：必应每日壁纸 → haowallpaper 兜底。
        两个源都拿不到（断网/被墙/改版）时返回 None，由调用方决定提示语。
        """
        # ---- 主源：必应每日（干净 JSON，失败概率最低）----
        try:
            bing = self.fetch_bing_wallpapers()
            if bing:
                return random.choice(bing)
        except Exception as e:
            print(f"必应主源异常: {e}")

        # ---- 备源：haowallpaper（HTML 解析，站点改版会失效）----
        try:
            fallback = self.fetch_from_haowallpaper(max_pages=2)
            fallback = [c for c in fallback if c.md5 not in self._downloaded_hashes]
            if fallback:
                return random.choice(fallback)
        except Exception as e:
            print(f"备源异常: {e}")
        return None

    def download_to_library(self, info: WallpaperInfo) -> bool:
        """下载壁纸到「壁纸保存路径」（local_folder，用户可见的本地库）。

        与 download_wallpaper 的区别：后者落在隐藏的 cache 目录，仅作轮换缓存；
        这里落的是**用户自己的壁纸库**，文件名可读（标题_日期_短哈希.ext），
        方便用户打开文件夹直接辨认、保留或删除。
        """
        try:
            dest = self._local_folder
            dest.mkdir(parents=True, exist_ok=True)

            m = re.search(r"\.(jpg|jpeg|png|webp|bmp)(?:[?#]|$)", info.url, re.I)
            ext = m.group(1).lower() if m else "jpg"
            stamp = time.strftime("%Y%m%d")
            fname = f"{self._safe_name(info.title)}_{stamp}_{info.md5[:6]}.{ext}"
            save_path = dest / fname

            if not (save_path.exists() and save_path.stat().st_size > 0):
                resp = requests.get(
                    info.url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=min(REQUEST_TIMEOUT, 30),
                )
                resp.raise_for_status()
                content = resp.content or b""
                if len(content) < 4096:
                    raise ValueError(f"下载内容仅 {len(content)} 字节，疑似失败")
                with open(save_path, "wb") as f:
                    f.write(content)

            info.local_path = save_path
            self._downloaded_hashes.add(info.md5)
            self._save_downloaded_hashes()
            self._current_wallpaper = info
            print(f"壁纸已存入本地库: {save_path}")
            return True
        except Exception as e:
            print(f"壁纸入库失败 {info.url} -> {e}")
            return False

    def apply_online_wallpaper(self) -> Optional[WallpaperInfo]:
        """联网随机壁纸一键流程：抓取 → 保存到壁纸库 → 设为屏幕壁纸。

        这是给菜单「🌐 联网随机壁纸」用的入口。整段会发起网络请求，
        务必放在后台线程调用，否则会阻塞 UI。
        返回成功应用的 WallpaperInfo；任一步失败返回 None。
        """
        info = self.fetch_online_random()
        if info is None:
            print("联网随机壁纸：未能获取候选（断网或站点异常）")
            return None
        if not self.download_to_library(info):
            return None
        if not self.set_current_wallpaper(info):
            # 下载成功但设置失败：文件已入库，下次「下一张」仍可用
            print("联网随机壁纸：已下载但设置屏幕壁纸失败")
            return None
        return info

    def _online_fallback(self) -> Optional[WallpaperInfo]:
        """本地库为空时的联网兜底（不写入用户壁纸库，只落缓存后轮换）。

        与 apply_online_wallpaper 的区别：这是"默默兜底"路径，不应该
        往用户壁纸目录里塞文件；先下到 cache，再回退到已缓存内容。
        """
        info = self.fetch_online_random()
        if info and self.download_wallpaper(info):
            return info
        cached = self._list_cached_files()
        if cached:
            fallback = self._local_info(random.choice(cached))
            self._current_wallpaper = fallback
            return fallback
        return None

    def fetch_from_haowallpaper(self, max_pages: int = 2) -> List[WallpaperInfo]:
        results = []
        for page in range(1, max_pages + 1):
            try:
                url = f"{HAOWALLPAPER_BASE_URL}/page/{page}" if page > 1 else HAOWALLPAPER_BASE_URL
                headers = {"User-Agent": USER_AGENT}
                resp = requests.get(url, timeout=min(REQUEST_TIMEOUT, 10), headers=headers)
                resp.raise_for_status()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "lxml")

                articles = soup.find_all("article") or soup.find_all("div", class_="post") or soup.find_all("a", href=True)
                for article in articles:
                    try:
                        img_tag = article.find("img")
                        if not img_tag:
                            continue
                        img_url = img_tag.get("src") or img_tag.get("data-src") or ""
                        if not img_url or not img_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                            continue
                        if img_url.startswith("//"):
                            img_url = "https:" + img_url
                        elif img_url.startswith("/"):
                            img_url = f"{HAOWALLPAPER_BASE_URL}{img_url}"

                        title = ""
                        h_tag = article.find(["h1", "h2", "h3", "h4"]) or article.find("a")
                        if h_tag:
                            title = h_tag.get_text(strip=True) or ""

                        res_tag = article.find(class_="resolution") or article.find("span", string=re.compile(r"\d+x\d+"))
                        resolution = res_tag.get_text(strip=True) if res_tag else ""

                        if not self._meets_resolution(resolution):
                            continue

                        md5 = hashlib.md5(img_url.encode("utf-8")).hexdigest()
                        if md5 in self._downloaded_hashes:
                            continue

                        results.append(WallpaperInfo(
                            url=img_url, title=title or "壁纸",
                            resolution=resolution or "Unknown",
                            source="haowallpaper", md5=md5))
                        if len(results) >= 20:
                            break
                    except Exception:
                        continue
            except Exception as e:
                print(f"抓取壁纸第 {page} 页出错: {e}")
        return results

    def download_wallpaper(self, info: WallpaperInfo) -> bool:
        try:
            headers = {"User-Agent": USER_AGENT}
            resp = requests.get(info.url, timeout=min(REQUEST_TIMEOUT, 15), headers=headers)
            resp.raise_for_status()
            self._ensure_folders()
            ext = info.url.split(".")[-1].split("?")[0] or "jpg"
            filename = f"{info.md5}.{ext}"
            save_path = self._cache_folder / filename
            if not (save_path.exists() and save_path.stat().st_size > 0):
                with open(save_path, "wb") as f:
                    f.write(resp.content)
            info.local_path = save_path
            self._downloaded_hashes.add(info.md5)
            self._save_downloaded_hashes()
            self._current_wallpaper = info
            print(f"下载壁纸成功: {info.title} -> {save_path}")
            return True
        except Exception as e:
            print(f"下载壁纸失败: {info.url} -> {e}")
            return False

    # ---------------- 切换（本地优先） ----------------

    def _local_info(self, path: Path) -> WallpaperInfo:
        info = WallpaperInfo(
            url=f"file://{path}", title=path.stem,
            resolution="", source="local",
            md5=hashlib.md5(path.read_bytes()).hexdigest())
        info.local_path = path
        return info

    def next_wallpaper(self) -> Optional[WallpaperInfo]:
        """下一张：按文件名顺序轮换到下一张（行为可预期）。

        语义分离说明：早期版本 next / random 都走随机，用户点「下一张」
        时完全猜不到会跳到哪张。现在改成顺序轮换 —— 打开壁纸文件夹按
        名称排序，就能预判下一张是哪张图。
        """
        local_files = sorted(self._list_local_files())
        if local_files:
            current = self._current_wallpaper.local_path if self._current_wallpaper else None
            if current in local_files:
                idx = (local_files.index(current) + 1) % len(local_files)
            else:
                idx = 0
            info = self._local_info(local_files[idx])
            self._current_wallpaper = info
            return info

        # 本地库为空 → 联网兜底（不往用户壁纸库塞文件）
        return self._online_fallback()

    def _list_cached_files(self) -> List[Path]:
        files: List[Path] = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"):
            try:
                files.extend(self._cache_folder.rglob(ext))
            except Exception:
                continue
        return files

    def random_wallpaper(self) -> Optional[WallpaperInfo]:
        """随机一张：从整个本地库随机挑（不保证与当前不同，但更"惊喜"）。"""
        local_files = self._list_local_files()
        if local_files:
            current = self._current_wallpaper.local_path if self._current_wallpaper else None
            pool = [f for f in local_files if f != current] or local_files
            info = self._local_info(random.choice(pool))
            self._current_wallpaper = info
            return info
        return self._online_fallback()

    def set_current_wallpaper(self, info: WallpaperInfo) -> bool:
        try:
            local_path = info.local_path
            if not local_path or not local_path.exists():
                if not self.download_wallpaper(info):
                    return False
                local_path = info.local_path
            if not local_path or not local_path.exists():
                return False

            # Windows 壁纸只认 bmp/jpg/png：webp 等先转成 PNG
            target = local_path
            if local_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp"):
                try:
                    from PIL import Image
                    self._cache_folder.mkdir(parents=True, exist_ok=True)
                    converted = self._cache_folder / f"{local_path.stem}_conv.png"
                    Image.open(local_path).convert("RGB").save(converted, "PNG")
                    target = converted
                except Exception as e:
                    print(f"壁纸格式转换失败: {e}")
                    return False

            import ctypes
            SPI_SETDESKWALLPAPER = 20
            SPIF_UPDATEINIFILE = 0x01
            SPIF_SENDWININICHANGE = 0x02
            ok = ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, str(target.resolve()),
                SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE)
            if not ok:
                print(f"SystemParametersInfoW 失败 err={ctypes.get_last_error()}")
                return False
            self._current_wallpaper = info
            print(f"壁纸已设置: {target}")
            return True
        except Exception as e:
            print(f"设置壁纸失败: {e}")
            return False

    # ---------------- 自动更换 ----------------

    def _on_auto_change(self) -> None:
        self._do_auto_change()

    def _do_auto_change(self) -> Optional[WallpaperInfo]:
        info = self.next_wallpaper()
        if info:
            self.set_current_wallpaper(info)
        return info

    def open_wallpaper_folder(self) -> None:
        import subprocess
        folder = str(self._local_folder)
        if os.name == "nt":
            os.startfile(folder)
        else:
            subprocess.run(["open", folder] if os.uname().sysname == "Darwin" else ["xdg-open", folder])

    def list_local_wallpapers(self) -> List[Dict[str, Any]]:
        wallpapers = []
        for f in self._list_local_files():
            try:
                stat = f.stat()
                wallpapers.append({
                    "path": str(f), "name": f.name, "size": stat.st_size,
                    "md5": hashlib.md5(f.read_bytes()).hexdigest(),
                    "modified": time.strftime("%Y-%m-%d", stat.st_mtime)})
            except Exception:
                continue
        return wallpapers

    def local_count(self) -> int:
        return len(self._list_local_files())


def get_wallpaper_manager() -> WallpaperManager:
    """获取壁纸管理器单例"""
    return WallpaperManager()


if __name__ == "__main__":
    gm = get_wallpaper_manager()
    print(f"本地壁纸数量: {gm.local_count()}")
    info = gm.next_wallpaper()
    if info:
        print(f"下一张: {info.title} -> {info.local_path}")
        print(f"设置结果: {gm.set_current_wallpaper(info)}")
    else:
        print("无可用壁纸（本地空且网络兜底失败）")
