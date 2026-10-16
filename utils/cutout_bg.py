"""
白底抠图工具：把 AI 生成的纯白背景角色图转成透明 PNG。

思路（比全局阈值稳）：
1. 背景候选 = "接近纯白" ∪ "低饱和 & 高亮的淡色"（后者用于吃掉 AI 画的接触阴影）；
2. 只保留**与图像四边连通**的那部分候选作为真背景——角色内部的眼白/高光被包围，不受影响；
3. 背景 alpha 归零；角色边缘用"距纯白的暗度"做**软 alpha**，得到平滑抗锯齿边；
4. 剔除孤立小连通域（生成噪声）；
5. 轻微羽化，避免硬边。

用法:
    python utils/cutout_bg.py <输入目录> [输出目录]
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

WHITE_MIN = 238          # 三通道均 >= 此值 -> 背景候选
SHADOW_SAT_MAX = 0.20    # 低饱和
SHADOW_VAL_MIN = 0.80    # 高亮
# 二者同时满足 -> 疑似接触阴影（仍须与画面边缘连通才作数，
# 因此角色内部的浅色高光不会被误删）

SOFT_LOW = 3             # 暗度 <= 此值 -> 全透明
SOFT_HIGH = 26           # 暗度 >= 此值 -> 全不透明

MIN_AREA_RATIO = 0.02    # 连通域面积小于主域的此比例则丢弃


def _connected_to_border(cand: np.ndarray) -> np.ndarray:
    """从图像四边出发，泛洪标记 cand 中与边缘连通的区域"""
    h, w = cand.shape
    seeds = []
    for x in range(w):
        if cand[0, x]:
            seeds.append((x, 0))
        if cand[h - 1, x]:
            seeds.append((x, h - 1))
    for y in range(h):
        if cand[y, 0]:
            seeds.append((0, y))
        if cand[y, w - 1]:
            seeds.append((w - 1, y))

    mask = np.zeros((h + 2, w + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    work = cand.astype(np.uint8).copy()
    for sx, sy in seeds:
        if work[sy, sx] == 1:
            cv2.floodFill(work, mask, (sx, sy), 2, flags=flags)
    return (mask[1:-1, 1:-1] == 255)


def _keep_large_components(solid: np.ndarray) -> np.ndarray:
    """只保留面积较大的连通域，滤掉生成噪声"""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(solid.astype(np.uint8), 8)
    if n <= 1:
        return solid
    areas = stats[1:, cv2.CC_STAT_AREA]
    biggest = areas.max()
    keep = np.zeros_like(solid, bool)
    for i, area in enumerate(areas, start=1):
        if area >= biggest * MIN_AREA_RATIO:
            keep |= labels == i
    return keep


def cutout(img: Image.Image) -> Image.Image:
    """白底图 -> 透明背景 RGBA"""
    rgb_u8 = np.array(img.convert("RGB"))
    rgb = rgb_u8.astype(np.int16)

    # --- 1. 背景候选 ---
    near_white = (rgb >= WHITE_MIN).all(axis=2)
    hsv = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2HSV).astype(np.float32)
    sat = hsv[..., 1] / 255.0
    val = hsv[..., 2] / 255.0
    shadow = (sat <= SHADOW_SAT_MAX) & (val >= SHADOW_VAL_MIN)
    bg = _connected_to_border(near_white | shadow)

    # --- 2. 软 alpha ---
    darkness = 255 - rgb.min(axis=2)
    alpha = np.clip((darkness - SOFT_LOW) / (SOFT_HIGH - SOFT_LOW), 0.0, 1.0)
    alpha[bg] = 0.0

    # --- 3. 滤噪 ---
    solid = _keep_large_components(alpha > 0.35)
    alpha[~solid & (alpha <= 0.35)] = 0.0

    # --- 4. 轻度羽化，柔化边缘 ---
    a_img = (alpha * 255).astype(np.uint8)
    a_img = cv2.GaussianBlur(a_img, (3, 3), 0.6)

    out = np.dstack([rgb_u8, a_img])
    return Image.fromarray(out, "RGBA")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    src_dir = Path(sys.argv[1])
    dst_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else src_dir / "cutout"
    dst_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src_dir.glob("*.png") if p.parent == src_dir and not p.name.startswith("_"))
    if not files:
        print(f"{src_dir} 下没有 png")
        return
    for f in files:
        out = cutout(Image.open(f))
        arr = np.array(out)
        ys, xs = np.where(arr[..., 3] > 8)
        (dst_dir / f.name).save(out)
        print(f"OK {f.name}  bbox x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}]"
              f"  占比 {(arr[..., 3] > 8).mean() * 100:.1f}%")


if __name__ == "__main__":
    main()
