# -*- coding: utf-8 -*-
"""删除宠物两侧翅膀。

原理（不依赖连通域，因为翅膀与身体在抠图后已粘连）：
  1. 提取"身体掩膜" body：黄色/橙色系（色相 15~80，饱和度高）像素的最大连通域
     —— 白色翅膀、绿色叶子因色相/饱和度不同天然被排除
  2. 逐行求 body 的最左/最右边界 (xl, xr)
  3. 翅膀候选 = 不透明 且 浅色(低饱和+高明度) 且 落在该行 body 边界之外
     —— 举起的黄色手臂(高饱和)、绿叶(绿色)、橙脚(高饱和) 均不会被误删
  4. 候选膨胀 1px 后 alpha 置 0，并清理孤立残点

用法：
  python utils/remove_wings.py            # 预览：输出对比图到 _wingprobe/
  python utils/remove_wings.py --write    # 写回 resources/frames/orig/*.png
"""
import sys
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path(__file__).parent.parent
D = BASE / "resources" / "frames" / "orig"
PREVIEW = BASE / "resources" / "frames" / "_wingprobe"
BAK = D / "_wingfix_backup"

WRITE = "--write" in sys.argv

# ---- 阈值 ----
ALPHA_MIN = 18          # 翅膀候选 alpha 下限（翅膀是半透明的，门槛要低）
BODY_ALPHA_MIN = 25     # 提取身体掩膜用的 alpha 下限
BODY_SAT_MIN = 55       # 身体掩膜饱和度下限（黄/橙）
BODY_HUE = (15.0, 80.0)  # 身体色相区间（黄橙），绿色/白色落在此区间外
WING_SAT_MAX = 110      # 翅膀饱和度上限（白/灰/浅灰蓝；绿叶 hue 豁免、黄手 ~120、橙脚 ~165）
EDGE_MARGIN = 3         # 凸包收缩量（px）：多覆盖贴边的翅根残留
RESIDUE_ALPHA = 32      # 身体外低于此 alpha 的像素视为残影，一并清除


def hue_of(rgb: np.ndarray) -> np.ndarray:
    r = rgb[..., 0].astype(np.float32)
    g = rgb[..., 1].astype(np.float32)
    b = rgb[..., 2].astype(np.float32)
    mx = np.max(rgb, axis=2).astype(np.float32)
    mn = np.min(rgb, axis=2).astype(np.float32)
    d = mx - mn
    d_safe = np.where(d == 0, 1.0, d)
    h = np.zeros_like(r)
    # max = r
    m_r = (mx == r) & (d > 0)
    h[m_r] = (60 * ((g - b) / d_safe) % 360)[m_r]
    # max = g
    m_g = (mx == g) & (d > 0)
    h[m_g] = (60 * ((b - r) / d_safe) + 120)[m_g]
    # max = b
    m_b = (mx == b) & (d > 0)
    h[m_b] = (60 * ((r - g) / d_safe) + 240)[m_b]
    return h


def largest_component(mask: np.ndarray) -> np.ndarray:
    """mask 的最大 4 连通域（BFS 实现，不依赖 scipy）"""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    best_id, best_size = 0, 0
    cur = 0
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if lab[y0, x0]:
            continue
        cur += 1
        size = 0
        stack = [(y0, x0)]
        lab[y0, x0] = cur
        while stack:
            cy, cx = stack.pop()
            size += 1
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and lab[ny, nx] == 0:
                    lab[ny, nx] = cur
                    stack.append((ny, nx))
        if size > best_size:
            best_id, best_size = cur, size
    return lab == best_id


def dilate(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    out = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.zeros_like(mask)
            ys = slice(max(0, dy), mask.shape[0] + min(0, dy))
            yd = slice(max(0, -dy), mask.shape[0] + min(0, -dy))
            xs = slice(max(0, dx), mask.shape[1] + min(0, dx))
            xd = slice(max(0, -dx), mask.shape[1] + min(0, -dx))
            shifted[yd, xd] = mask[ys, xs]
            out |= shifted
    return out


def row_bounds(body: np.ndarray):
    """逐行求身体左右边界 xl/xr；无身体的行沿用最近有效行的边界。

    这样身体上方（叶子区）/下方（脚区）的行也有边界参考，
    翅膀延伸到身体轮廓之外的尖端同样能被判定删除。
    """
    h, w = body.shape
    col = np.arange(w)[None, :].repeat(h, axis=0)
    valid = body.any(axis=1)
    xl_src = np.where(body, col, w + 1).min(axis=1)
    xr_src = np.where(body, col, -1).max(axis=1)
    src = np.where(valid, np.arange(h), -1)
    last = -1
    for y in range(h):
        if src[y] >= 0:
            last = src[y]
        else:
            src[y] = last
    last = -1
    for y in range(h - 1, -1, -1):
        if src[y] >= 0:
            last = src[y]
        else:
            src[y] = last
    src = np.clip(src, 0, h - 1)
    return xl_src[src], xr_src[src]


def convex_body_mask(body: np.ndarray):
    """用身体轮廓点的凸包近似"身体区域"。

    相比逐行/逐列外接矩形，凸包能正确处理"身体左下角外侧的翅尖"
    这类落在矩形内、但在身体实体之外的像素；同时眼睛/腮红等内部
    空洞位于凸包内，天然被保护（不会像距离法那样把五官挖掉）。
    """
    from PIL import Image as _Image, ImageDraw
    h, w = body.shape
    ys = np.where(body.any(axis=1))[0]
    if len(ys) == 0:
        return None
    col = np.arange(w)[None, :].repeat(h, axis=0)
    xl = np.where(body, col, w + 1).min(axis=1)
    xr = np.where(body, col, -1).max(axis=1)
    pts = [(int(xl[y]), int(y)) for y in ys] + [(int(xr[y]), int(y)) for y in ys]
    hull = cv2_hull(pts)
    m = _Image.new("1", (w, h), 0)
    ImageDraw.Draw(m).polygon(hull, fill=1)
    return np.array(m, bool)


def cv2_hull(points):
    """Andrew monotone chain 凸包（返回顶点列表，逆时针）"""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def build_wing_mask(arr: np.ndarray) -> np.ndarray:
    """返回需要删除的翅膀像素掩膜"""
    alpha = arr[..., 3]
    rgb = arr[..., :3].astype(np.int16)

    sat = rgb.max(axis=2) - rgb.min(axis=2)
    hue = hue_of(arr[..., :3].astype(np.uint8))

    # 1) 身体掩膜：黄/橙色像素的最大连通域（翅膀白、叶子绿，天然落选）
    body_core = (alpha > BODY_ALPHA_MIN) & (sat >= BODY_SAT_MIN) \
        & (hue >= BODY_HUE[0]) & (hue <= BODY_HUE[1])
    body = largest_component(body_core)
    if not body.any():
        return np.zeros_like(alpha > 0)

    # 2) 身体区域 = 轮廓点凸包（外接矩形会漏掉矩形角落里的翅尖）
    inside = convex_body_mask(body)
    if inside is None:
        return np.zeros_like(alpha > 0)
    # 凸包基于"高饱黄橙"像素，比真实轮廓天然内缩 2~3px（轮廓过渡带）；
    # 再收缩 EDGE_MARGIN，把贴着身体边缘的翅根一并对齐处理
    inside = ~dilate(~inside, EDGE_MARGIN)

    # 3) 翅膀 = 凸包之外 且 白/暖白/灰（低饱和），绿色叶子豁免
    #    黄手(~120)、橙脚(~165) 饱和度高，不会被误删
    is_green = (hue > 80) & (hue < 200)
    wing = (alpha > 0) & (~inside) & (~is_green) \
        & (((alpha > ALPHA_MIN) & (sat <= WING_SAT_MAX)) | (alpha <= RESIDUE_ALPHA))
    return dilate(wing, 1) & (alpha > 0)


def process(path: Path, write: bool) -> int:
    img = Image.open(path).convert("RGBA")
    arr = np.array(img)
    wing = build_wing_mask(arr)
    out = arr.copy()
    out[..., 3] = np.where(wing, 0, arr[..., 3])

    # 清掉 alpha 极低但仍带颜色的杂点（避免边缘泛白圈）
    out[..., 3] = np.where(out[..., 3] < 12, 0, out[..., 3])

    if write:
        BAK.mkdir(exist_ok=True)
        if not (BAK / path.name).exists():
            shutil.copy2(path, BAK / path.name)
        Image.fromarray(out, "RGBA").save(path)
    else:
        PREVIEW.mkdir(exist_ok=True)
        base = Image.new("RGBA", (img.size[0] * 2 + 12, img.size[1]), (250, 250, 250, 255))
        base.paste(img, (0, 0), img)
        new = Image.fromarray(out, "RGBA")
        base.paste(new, (img.size[0] + 12, 0), new)
        base.save(PREVIEW / f"{path.stem}_nowing.png")
    return int(wing.sum())


def main() -> None:
    total = 0
    files = [f for f in sorted(D.glob("*.png")) if not f.name.startswith("_")]
    for f in files:
        n = process(f, WRITE)
        total += n
        print(f"{'写入' if WRITE else '预览'} {f.name}: 删除 {n} px")
    print(f"\n合计 {total} px，{len(files)} 个文件")
    if not WRITE:
        print(f"对比图目录: {PREVIEW}")


if __name__ == "__main__":
    main()
