# -*- coding: utf-8 -*-
"""翅膀修复：把 idle_00 的左翅（alpha 合成）移植到缺失翅膀的 interact 帧"""
from pathlib import Path
import shutil

from PIL import Image

D = Path("resources/frames/orig")
BAK = D / "_wingfix_backup"
BAK.mkdir(exist_ok=True)

src = Image.open(D / "idle_00.png").convert("RGBA")
W, H = src.size
# 左翅 ROI：画面左侧 x 4%-40%, y 28%-72%
x0, x1 = int(W * 0.04), int(W * 0.40)
y0, y1 = int(H * 0.28), int(H * 0.72)

wing = src.crop((x0, y0, x1, y1))
# 只保留翅膀实体：alpha>60 且颜色明显偏白/浅（与黄身体区分）
import numpy as np
wa = np.array(wing)
r, g, b = wa[..., 0].astype(int), wa[..., 1].astype(int), wa[..., 2].astype(int)
bright = (r + g + b) / 3.0
is_wing = (wa[..., 3] > 60) & ((r > 180) & (g > 170) & (b > 150))
wa[..., 3] = np.where(is_wing, wa[..., 3], 0)
wing_layer = Image.fromarray(wa, "RGBA")

print(f"翅膀实体像素: {int(is_wing.sum())} / {wa.shape[0]*wa.shape[1]}")

for name in ["interact_00", "interact_01"]:
    tgt_path = D / f"{name}.png"
    if not (BAK / tgt_path.name).exists():
        shutil.copy2(tgt_path, BAK / tgt_path.name)
    tgt = Image.open(tgt_path).convert("RGBA")
    tgt.alpha_composite(wing_layer, (x0, y0))
    tgt.save(tgt_path)
    print(f"已修复 {name}.png")

# 同时检查 sit/lie/walk 是否也需要（已知翅膀正常，跳过）
print("done")
