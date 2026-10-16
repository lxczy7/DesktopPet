# -*- coding: utf-8 -*-
"""生成 README 首页展示图（docs/images/lulu_showcase.png）。

把 resources/frames/orig 里的姿态帧横排到一张浅暖色渐变底上，供 README
首屏展示。素材帧为 RGBA 透明底，直接带 alpha 粘贴；所有帧按**统一内容高度**
缩放（与 build_lulu_frames.py 的口径一致，不逐帧撑满）。

用法：
  .venv/Scripts/python.exe utils/make_readme_banner.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent.parent
FRAMES = BASE / "resources" / "frames" / "orig"
OUT = BASE / "docs" / "images" / "lulu_showcase.png"

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"

# (帧文件, 标签) —— 挑 6 个最有代表性的姿态
SHOWCASE = [
    ("idle_00.png", "待机"),
    ("walk_00.png", "行走"),
    ("sit_00.png", "坐下"),
    ("lie_00.png", "躺平"),
    ("interact_00.png", "欢呼"),
    ("interact_02.png", "开心"),
]

W, H = 1400, 420
PAD_X = 50
TARGET_H = 210          # 统一内容高度
BASELINE = 318          # 姿态底部对齐线
LABEL_GAP = 22          # 标签距底线的距离
BG_TOP = (255, 252, 245)
BG_BOTTOM = (255, 236, 210)
LABEL_COLOR = (146, 106, 58)


def main() -> None:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # 竖向柔和渐变
    for y in range(H):
        t = y / (H - 1)
        draw.line(
            [(0, y), (W, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)),
        )

    font = ImageFont.truetype(FONT_PATH, 24)
    cell_w = (W - 2 * PAD_X) / len(SHOWCASE)

    for i, (fname, label) in enumerate(SHOWCASE):
        path = FRAMES / fname
        if not path.exists():
            print("跳过（缺失）:", path)
            continue
        frame = Image.open(path).convert("RGBA")
        scale = TARGET_H / frame.height
        frame = frame.resize(
            (max(1, round(frame.width * scale)), TARGET_H),
            Image.Resampling.LANCZOS,
        )

        cx = PAD_X + cell_w * (i + 0.5)
        img.paste(frame, (round(cx - frame.width / 2), BASELINE - frame.height), frame)

        tw = draw.textlength(label, font=font)
        draw.text((cx - tw / 2, BASELINE + LABEL_GAP), label, font=font, fill=LABEL_COLOR)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"saved: {OUT}\n       {img.size[0]}x{img.size[1]}  "
          f"{OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
