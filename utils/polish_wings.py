# -*- coding: utf-8 -*-
"""翅根精修（在 remove_wings.py 结果之上再清一遍）。

remove_wings.py 用"身体凸包"判定，能删掉翅膀主体，
但紧贴身体轮廓外侧的翅根（落在凸包内/保护圈内）会残留一小片。

本脚本用"环绕度"判定解决：
  · 取低饱和浅色像素（白/暖白/灰）做连通域
  · 看该连通域的**外圈一环**里有多少是身体像素
      - 眼睛反光、脸上高光、腮红：外圈几乎全是身体 → 环绕度高 → 保留
      - 翅根残留：外圈大半是透明背景 → 环绕度低 → 删除
  · 删除时跳过紧贴身体的 2px，保护轮廓柔边

用法：
  python utils/polish_wings.py            # 预览（输出到 _wingpolish/）
  python utils/polish_wings.py --write    # 写回
"""
import sys
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.remove_wings import (  # noqa: E402
    dilate, largest_component, hue_of,
    BODY_ALPHA_MIN, BODY_SAT_MIN, BODY_HUE,
)

BASE = Path(__file__).parent.parent
D = BASE / "resources" / "frames" / "orig"
PREVIEW = BASE / "resources" / "frames" / "_wingpolish"
BAK = D / "_prepolish_backup"

WRITE = "--write" in sys.argv

CAND_ALPHA_MIN = 18
CAND_SAT_MAX = 100        # 翅根暖白也在内
MIN_AREA = 40             # 小于此面积不判（避免动到发丝级细节）
SURROUND_MIN = 0.85       # 外圈中不透明像素占比 >= 此值 视为"身体内部"→ 保留
GUARD = 2                 # 紧贴身体的保护带（px）
RING_OUT = 3              # 环绕度采样外圈半径（px）

# 定向修补：躺姿帧的翅尖紧贴身体左下、与身体边缘的抗锯齿像素连通，
# 环绕度判定会把它当作身体轮廓保留下来，这里按区域兜底清掉。
# 帧名 -> [(x0, y0, x1, y1, sat_max), ...]
TOUCHUP = {
    "lie_00": [(40, 175, 105, 244, 70)],
    "lie_01": [(40, 175, 105, 244, 70)],
}


def touchup_mask(arr: np.ndarray, name: str) -> np.ndarray:
    """按帧/区域定向清理贴边翅尖"""
    alpha = arr[..., 3]
    rgb = arr[..., :3].astype(np.int16)
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    hue = hue_of(arr[..., :3].astype(np.uint8))
    kill = np.zeros(alpha.shape, bool)
    for (x0, y0, x1, y1, sat_max) in TOUCHUP.get(name, []):
        sub = np.s_[y0:y1, x0:x1]
        is_green = (hue[sub] > 80) & (hue[sub] < 200)
        kill[sub] = (alpha[sub] > CAND_ALPHA_MIN) & (sat[sub] <= sat_max) & (~is_green)
    return kill


def components(mask: np.ndarray):
    """返回 [(label_id, pixel_indices_list)]，4 连通 BFS"""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    out = []
    ys, xs = np.nonzero(mask)
    cur = 0
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if lab[y0, x0]:
            continue
        cur += 1
        px = []
        stack = [(y0, x0)]
        lab[y0, x0] = cur
        while stack:
            cy, cx = stack.pop()
            px.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and lab[ny, nx] == 0:
                    lab[ny, nx] = cur
                    stack.append((ny, nx))
        out.append((cur, px))
    return out, lab


def build_polish_mask(arr: np.ndarray) -> np.ndarray:
    alpha = arr[..., 3]
    rgb = arr[..., :3].astype(np.int16)
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    hue = hue_of(arr[..., :3].astype(np.uint8))

    body = largest_component(
        (alpha > BODY_ALPHA_MIN) & (sat >= BODY_SAT_MIN)
        & (hue >= BODY_HUE[0]) & (hue <= BODY_HUE[1]))
    if not body.any():
        return np.zeros(alpha.shape, bool)
    guard = dilate(body, GUARD)
    is_green = (hue > 80) & (hue < 200)

    cand = (alpha > CAND_ALPHA_MIN) & (sat <= CAND_SAT_MAX) & (~is_green) & (~guard)
    if not cand.any():
        return np.zeros(alpha.shape, bool)

    comps, _ = components(cand)
    kill = np.zeros(alpha.shape, bool)

    for cid, px in comps:
        if len(px) < MIN_AREA:
            continue
        ys = np.fromiter((p[0] for p in px), dtype=np.int32, count=len(px))
        xs = np.fromiter((p[1] for p in px), dtype=np.int32, count=len(px))
        y0, y1 = max(0, ys.min() - 2), min(alpha.shape[0], ys.max() + 3)
        x0, x1 = max(0, xs.min() - 2), min(alpha.shape[1], xs.max() + 3)
        sub = np.zeros(alpha.shape, bool)
        sub[ys, xs] = True
        # 外圈取 2~3px 处：若只取紧邻的 1px，取到的是连通域自身的抗锯齿过渡像素
        ring = dilate(sub, RING_OUT) & (~dilate(sub, 1))
        n_ring = int(ring.sum())
        if n_ring == 0:
            continue
        # 环绕度 = 外圈中"不透明像素"的占比。
        #   用"是否透明"而不是"是否严格身体色"：眼睛周围是浅色高光/过渡像素，
        #   并非高饱和黄，若按身体色算会把眼白误判成外部物体。
        #   五官/高光四周都是实心图像 → 环绕度 ≈ 1；翅根贴边、外侧是桌面 → 明显偏低。
        n_solid = int((ring & (alpha > CAND_ALPHA_MIN)).sum())
        if n_solid / n_ring >= SURROUND_MIN:
            continue          # 被实心图像包围 → 是五官/高光，保留
        sel = sub & (~guard)  # 只删保护带之外的部分
        kill |= sel
        print(f"    连通域 #{cid}: {len(px)}px, 环绕度={n_solid/n_ring:.2f} -> 删除 {int(sel.sum())}px")
    return kill


def main() -> None:
    files = [f for f in sorted(D.glob("*.png")) if not f.name.startswith("_")]
    total = 0
    for f in files:
        img = Image.open(f).convert("RGBA")
        arr = np.array(img)
        kill = build_polish_mask(arr) | touchup_mask(arr, f.stem)
        n = int(kill.sum())
        if n:
            out = arr.copy()
            out[..., 3] = np.where(kill, 0, arr[..., 3])
            out[..., 3] = np.where(out[..., 3] < 12, 0, out[..., 3])
            print(f"{f.name}: 删除 {n}px")
            if WRITE:
                BAK.mkdir(exist_ok=True)
                if not (BAK / f.name).exists():
                    shutil.copy2(f, BAK / f.name)
                Image.fromarray(out, "RGBA").save(f)
            else:
                PREVIEW.mkdir(exist_ok=True)
                big = Image.new("RGBA", (img.size[0] * 2 + 12, img.size[1]), (250, 250, 250, 255))
                big.paste(img, (0, 0), img)
                new = Image.fromarray(out, "RGBA")
                big.paste(new, (img.size[0] + 12, 0), new)
                big.save(PREVIEW / f"{f.stem}_polish.png")
            total += n
        else:
            print(f"{f.name}: 无需处理")
    print(f"\n合计 {total}px | {'已写入' if WRITE else '预览目录: ' + str(PREVIEW)}")


if __name__ == "__main__":
    main()
