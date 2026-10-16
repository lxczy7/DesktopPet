"""
把 selected/nobg 帧按原始视频的时间顺序重命名。
背景：video_extractor.select_best_frames 按拉普拉斯方差（清晰度）排序拷贝，
导致帧序不是时间序，动画播放会抖动。本脚本通过内容哈希把帧映射回
raw/<视频>/frame_XXXX.png 的原始序号，再按 (视频, 序号) 重排。
"""
import hashlib
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.constants import FRAMES_DIR

RAW_DIR = FRAMES_DIR / "raw"
NOBG_DIR = FRAMES_DIR / "nobg"
SELECTED_DIR = FRAMES_DIR / "selected"


def md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # 1. raw 帧: md5 -> (视频目录序, 帧序号)
    raw_map = {}
    video_dirs = sorted([d for d in RAW_DIR.iterdir() if d.is_dir()])
    for v_idx, vdir in enumerate(video_dirs):
        for f in sorted(vdir.glob("*.png")):
            try:
                idx = int(f.stem.split("_")[1])
            except (IndexError, ValueError):
                continue
            raw_map[md5(f)] = (v_idx, idx, f.name)
    print(f"raw 帧映射: {len(raw_map)} 条, 视频数: {len(video_dirs)}")

    # 2. nobg 帧按原始时间序排序
    nobg_files = sorted(NOBG_DIR.glob("*.png"))
    entries = []
    unmatched = 0
    for f in nobg_files:
        # nobg 文件名与 selected 一致（rembg folder 模式保留主名）
        sel = SELECTED_DIR / f.name
        if not sel.exists():
            # 兼容 rembg 的 -no-bg 后缀命名
            sel = SELECTED_DIR / (f.stem.replace("-no-bg", "") + ".png")
        key = None
        if sel.exists():
            key = raw_map.get(md5(sel))
        if key is None:
            # 直接尝试匹配 nobg 自身内容（selected 与 nobg 像素不同，仅作兜底）
            unmatched += 1
            entries.append(((9999, 0), f))
            continue
        entries.append(((key[0], key[1]), f))
    entries.sort(key=lambda e: e[0])

    # 3. 先改临时名再改正式名，避免覆盖
    tmp_names = []
    for i, (_, f) in enumerate(entries):
        tmp = NOBG_DIR / f"__tmp_{i:04d}.png"
        f.rename(tmp)
        tmp_names.append(tmp)
    for i, tmp in enumerate(tmp_names):
        tmp.rename(NOBG_DIR / f"anim_{i:04d}.png")

    print(f"重命名完成: {len(entries)} 帧 (未匹配 {unmatched} 帧排在末尾)")
    print("时序样例:", [e[1].name for e in entries[:5]])


if __name__ == "__main__":
    main()
