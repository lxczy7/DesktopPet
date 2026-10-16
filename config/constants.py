import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent.parent

# 资源目录
RESOURCES_DIR = BASE_DIR / "resources"
FRAMES_DIR = RESOURCES_DIR / "frames"
ICONS_DIR = RESOURCES_DIR / "icons"

# 配置目录
CONFIG_DIR = BASE_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# 默认壁纸目录
DEFAULT_WALLPAPER_DIR = Path.home() / "Pictures" / "壁纸"
HAOWALLPAPER_CACHE_DIR = DEFAULT_WALLPAPER_DIR / "haowallpaper"
SCREENSHOT_SAVE_DIR = DEFAULT_WALLPAPER_DIR / "screenshots"

# 视频源文件（仅原型素材抽帧用）
# 把原型视频放进 <项目根>/assets/videos 即可复用 utils/video_extractor.py；
# 目录不存在时自动跳过，不影响主程序运行。
VIDEO_SOURCE_DIR = BASE_DIR / "assets" / "videos"
VIDEO_FILES = sorted(VIDEO_SOURCE_DIR.glob("*.mp4")) if VIDEO_SOURCE_DIR.is_dir() else []

# 动画配置
ANIMATION_CONFIG = {
    "target_size": (140, 140),  # 统一缩放尺寸
    "fps": 12,  # 动画播放帧率
    "idle_frame_range": (8, 12),  # 待机动画帧数范围
    "walk_frame_range": (6, 8),   # 行走动画帧数范围
    "interact_frame_range": (4, 6), # 互动动画帧数范围
}

# 宠物行为配置
PET_CONFIG = {
    "walk_speed": 3,  # 像素/帧
    "idle_duration_range": (3000, 8000),  # 待机时长(ms)
    "walk_duration_range": (2000, 5000),  # 行走时长(ms)
    "bounds_margin": 50,  # 边界缓冲区
    "direction_change_prob": 0.02,  # 每帧随机改变方向概率
}

# 网络配置
HAOWALLPAPER_BASE_URL = "https://haowallpaper.com"
REQUEST_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# 联网随机壁纸 - 必应每日壁纸（主源：国内直连、免 Key、可拿 4K UHD）
# 接口返回最近 8 天的 JSON 元数据，图片地址由 urlbase + '_UHD.jpg' 拼出
BING_ARCHIVE_URL = "https://www.bing.com/HPImageArchive.aspx"
BING_HOST = "https://www.bing.com"
BING_MARKET = "zh-CN"          # 中文区（带中文版权描述，可读性好）
BING_MAX_DAYS = 8              # 接口最多回溯 8 天
BING_UHD_SUFFIX = "_UHD.jpg"   # 4K 尺寸后缀（3840x2160）

# 热键默认配置
DEFAULT_HOTKEYS = {
    "toggle_pet": "ctrl+alt+p",
    "screenshot_region": "ctrl+alt+a",
    "screenshot_full": "ctrl+alt+s",
    "next_wallpaper": "ctrl+alt+w",
}