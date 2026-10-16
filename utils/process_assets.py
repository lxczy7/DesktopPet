"""
桌宠素材后处理：
1. 清理 AI 水印残留（右下角半透明区域）
2. 按 alpha 包围盒裁切主体
3. 统一缩放（高度 TARGET_H）并加均匀透明边距
4. 由左行走帧镜像生成右行走帧
输出: resources/frames/orig/<state>_XX.png
"""
import sys
from pathlib import Path
from PIL import Image
import numpy as np

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

ORIG_DIR = BASE_DIR / "resources" / "frames" / "orig"
TARGET_H = 220          # 素材统一高度（桌宠显示约 180px，留缩放余量）
PAD = 12                # 主体四周透明边距
WATERMARK_ZONE = 0.22   # 右下角清理区域比例


def clean_watermark(img: Image.Image) -> Image.Image:
    """右下角水印残留区域直接清成全透明"""
    arr = np.array(img)
    h, w = arr.shape[:2]
    x0, y0 = int(w * (1 - WATERMARK_ZONE)), int(h * (1 - WATERMARK_ZONE))
    arr[y0:, x0:, 3] = 0
    return Image.fromarray(arr, "RGBA")


def crop_and_scale(img: Image.Image) -> Image.Image:
    arr = np.array(img)
    alpha = arr[..., 3]
    ys, xs = np.where(alpha > 8)
    if len(xs) == 0:
        raise ValueError("全透明图")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    img = img.crop((x0, y0, x1 + 1, y1 + 1))
    # 等比缩放到目标高度
    scale = TARGET_H / img.height
    new_w = max(1, round(img.width * scale))
    img = img.resize((new_w, TARGET_H), Image.Resampling.LANCZOS)
    # 加透明边
    canvas = Image.new("RGBA", (new_w + PAD * 2, TARGET_H + PAD * 2), (0, 0, 0, 0))
    canvas.paste(img, (PAD, PAD), img)
    return canvas


def main():
    ORIG_DIR.mkdir(parents=True, exist_ok=True)
    src_dir = ORIG_DIR  # rembg 抠图输出目录（idle_a.png 等中间名）

    mapping = {
        # idle 序列: 睁眼 -> 歪头 -> 半眨 -> 全眨 -> 半眨(拷) -> 歪头(拷)
        "idle_a": "idle_00",        # 定妆睁眼
        "tilt_a": "idle_01",        # 歪头睁眼
        "blink_half": "idle_02",    # 半眨眼
        "blink_full": "idle_03",    # 全眨眼(笑眼)
        # walk 序列: 左脚前 -> 离地 -> 右脚前 -> 落地缓冲
        "walk_a": "walk_00",
        "walk_c": "walk_01",
        "walk_b": "walk_02",
        "walk_d": "walk_03",
        # sit 序列: 坐正 -> 歪头犯困
        "sit_a": "sit_00",
        "sit_b": "sit_01",
        # lie 序列: 躺平 -> 打哈欠
        "lie_a": "lie_00",
        "lie_b": "lie_01",
        # interact 序列: 跳起 -> 落地 -> 眯眼笑
        "interact_a": "interact_00",
        "interact_b": "interact_01",
        "idle_b": "interact_02",
    }
    src_dir = BASE_DIR / "resources" / "frames" / "orig"

    for src_name, dst_name in mapping.items():
        src = src_dir / f"{src_name}.png"
        if not src.exists():
            print(f"缺少 {src_name}")
            continue
        img = Image.open(src).convert("RGBA")
        img = clean_watermark(img)
        img = crop_and_scale(img)
        img.save(src_dir / f"{dst_name}.png")
        print(f"OK {src_name} -> {dst_name}.png ({img.size[0]}x{img.size[1]})")

    # 拷贝复用帧：闭眼序列回程 + 走路反方向镜像
    import shutil
    for dst, src in [("idle_04", "idle_02"), ("idle_05", "idle_01")]:
        s = src_dir / f"{src}.png"
        if s.exists():
            shutil.copy2(s, src_dir / f"{dst}.png")
    for i in range(4):
        s = src_dir / f"walk_{i:02d}.png"
        if s.exists():
            mirror = Image.open(s).transpose(Image.FLIP_LEFT_RIGHT)
            mirror.save(src_dir / f"walkr_{i:02d}.png")

    # 清理中间文件（抠图原始输出）
    for tmp_name in mapping.keys():
        p = src_dir / f"{tmp_name}.png"
        if p.exists():
            p.unlink()

    print("\n最终素材清单:")
    for f in sorted(src_dir.glob("*.png")):
        print(" ", f.name)


if __name__ == "__main__":
    main()
