"""生成噜噜新形象的交付总览图（6 组代表姿态 + 实际桌宠尺寸对照）。

用法: python utils/make_lulu_sheet.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).parent.parent
FRAMES = BASE / "resources" / "frames" / "orig"
OUT = BASE / "generated-images" / "噜噜新形象_2026-10-16.png"

ROWS = ["idle_00", "walk_00", "sit_00", "lie_00", "interact_00", "interact_02"]
LABELS = ["待机", "行走", "坐下", "躺平", "欢呼", "开心"]

SCALE = 1.6          # 姿态放大倍数
PAD_X = 56
TOP = 96
BOTTOM = 76
BG = (250, 249, 246)


def font(size):
    for p in (r"C:/Windows/Fonts/msyh.ttc", r"C:/Windows/Fonts/simhei.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def main():
    ims = []
    for n in ROWS:
        p = FRAMES / f"{n}.png"
        if not p.exists():
            print(f"缺少 {n}")
            return
        im = Image.open(p).convert("RGBA")
        ims.append(im.resize((int(im.width * SCALE), int(im.height * SCALE)), Image.LANCZOS))

    cell_w = max(i.width for i in ims) + PAD_X
    cell_h = max(i.height for i in ims)
    W = cell_w * len(ims)
    H = TOP + cell_h + BOTTOM

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    f_title = font(40)
    f_sub = font(22)
    f_label = font(26)

    d.text((PAD_X, 24), "噜噜 · 桌宠新形象", font=f_title, fill=(58, 52, 44))
    d.text((PAD_X + 4, 74), "13 个姿态帧全部替换完成 · 头顶橘子 / 橙短裤 / 蓝眼睛",
           font=f_sub, fill=(140, 132, 120))

    # 细微底纹线
    d.line([(0, TOP - 6), (W, TOP - 6)], fill=(232, 228, 220), width=2)

    for i, im in enumerate(ims):
        x0 = i * cell_w + (cell_w - im.width) // 2
        y0 = TOP + (cell_h - im.height)  # 底部对齐
        canvas.paste(im, (x0, y0), im)
        lab = LABELS[i]
        tw = d.textlength(lab, font=f_label)
        d.text((i * cell_w + (cell_w - tw) / 2, TOP + cell_h + 14), lab,
               font=f_label, fill=(96, 88, 76))

    # 实际尺寸对照（放在标题区右侧，避免与姿态列冲突）
    real = Image.open(FRAMES / "idle_00.png").convert("RGBA")
    bbox = real.getchannel("A").getbbox()
    real = real.crop(bbox).resize((90, 90), Image.Resampling.LANCZOS)
    rx = W - 180
    ry = 6
    d.text((rx - 118, ry + 30), "实际 90px", font=f_sub, fill=(150, 142, 130))
    tile = Image.new("RGBA", (104, 104), (240, 238, 233, 255))
    tile.paste(real, (7, 7), real)
    canvas.paste(tile, (rx, ry), tile)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print(f"已生成 {OUT}  {canvas.size}")


if __name__ == "__main__":
    main()
