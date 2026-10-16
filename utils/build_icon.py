# -*- coding: utf-8 -*-
"""从宠物形象帧生成应用图标 resources/icons/pet.ico（多分辨率）。

用法：
  python utils/build_icon.py [源帧名，默认 idle_00]
"""
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).parent.parent
FRAMES = BASE / "resources" / "frames" / "orig"
ICON_DIR = BASE / "resources" / "icons"
SIZES = [16, 24, 32, 48, 64, 128, 256]
# 主体在画布中的占比（留一点呼吸空间，避免贴边）
PADDING_RATIO = 0.06


def build(src_name: str = "idle_00") -> Path:
    src_path = FRAMES / f"{src_name}.png"
    if not src_path.exists():
        raise FileNotFoundError(src_path)
    img = Image.open(src_path).convert("RGBA")

    # 裁到主体包围盒
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)

    # 方形画布 + 居中 + 留边，并统一放大到 256（ICO 最大尺寸，各档由此下采样）
    side = int(max(img.size) * (1 + PADDING_RATIO * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    canvas = canvas.resize((256, 256), Image.Resampling.LANCZOS)

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    out = ICON_DIR / "pet.ico"
    canvas.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"图标已生成: {out}  源={src_name}  画布={side}x{side}  尺寸={SIZES}")
    return out


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "idle_00"
    build(name)
