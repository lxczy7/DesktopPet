"""
从噜噜（Lulu）AI 生成稿构建桌宠标准帧。

关键：所有帧用**同一个缩放系数**（由定妆稿的角色高度决定），而不是逐帧缩放到同一高度。
否则坐姿/躺姿会被放大，动画播放时角色忽大忽小。

对齐：统一帧高 = 最高内容 + 2*PAD，内容底部对齐（下留 PAD），水平居中。
这样在 pet_window 的居中显示逻辑下，各帧的角色"脚底"始终落在同一水平线。

用法:
    python utils/build_lulu_frames.py            # 预览（输出到 _preview，不动 orig）
    python utils/build_lulu_frames.py --write    # 真正替换 resources/frames/orig
"""
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from utils.cutout_bg import cutout   # noqa: E402

RAW = BASE_DIR / "generated-images" / "lulu_raw"
ORIG = BASE_DIR / "resources" / "frames" / "orig"
BACKUP = BASE_DIR / "resources" / "frames" / "orig_backup_lemon"
PREVIEW = BASE_DIR / "generated-images" / "lulu_frames_preview"

TARGET_H = 220   # 定妆稿缩放后的内容高度
PAD = 12         # 四周透明边距
ALPHA_MIN = 8

PICKS = {
    "idle_a": RAW / "Same_exact_3D_cartoon_characte_2026-10-16T03-34-40.png",
    "tilt_a": RAW / "b8" / "Same_exact_3D_cartoon_characte_2026-10-16T03-38-42.png",
    "walk_a": RAW / "p_walk03" / "Same_exact_3D_cartoon_characte_2026-10-16T03-37-04.png",
    "walk_c": RAW / "p_walk03" / "Same_exact_3D_cartoon_characte_2026-10-16T03-37-05.png",
    "walk_b": RAW / "p_walk03" / "Same_exact_3D_cartoon_characte_2026-10-16T03-37-06.png",
    "walk_d": RAW / "p_walk03" / "Same_exact_3D_cartoon_characte_2026-10-16T03-37-07.png",
    "sit_a": RAW / "b3" / "Same_exact_3D_cartoon_characte_2026-10-16T03-37-55.png",
    "sit_b": RAW / "sit01" / "Same_exact_3D_cartoon_characte_2026-10-16T03-39-17.png",
    "lie_a": RAW / "b3" / "Same_exact_3D_cartoon_characte_2026-10-16T03-37-58.png",
    "lie_b": RAW / "b3" / "Same_exact_3D_cartoon_characte_2026-10-16T03-37-57.png",
    "interact_a": RAW / "int00" / "Same_exact_3D_cartoon_characte_2026-10-16T03-39-34.png",
    "interact_b": RAW / "b8" / "Same_exact_3D_cartoon_characte_2026-10-16T03-38-41.png",
    "idle_b": RAW / "int02" / "Same_exact_3D_cartoon_characte_2026-10-16T03-39-53.png",
}

MAPPING = {
    "idle_a": "idle_00",
    "tilt_a": "idle_01",
    # walk: 左脚前 -> 腾空 -> 右脚前 -> 落地缓冲
    "walk_a": "walk_00",
    "walk_c": "walk_01",
    "walk_b": "walk_02",
    "walk_d": "walk_03",
    "sit_a": "sit_00",
    "sit_b": "sit_01",
    "lie_a": "lie_00",
    "lie_b": "lie_01",
    "interact_a": "interact_00",
    "interact_b": "interact_01",
    "idle_b": "interact_02",
}


def _content(img: Image.Image):
    """裁到不透明内容边界，返回 (裁好的图, 宽, 高)"""
    a = np.array(img)
    ys, xs = np.where(a[..., 3] > ALPHA_MIN)
    if len(xs) == 0:
        raise ValueError("全透明")
    img = img.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    return img, img.width, img.height


def main():
    write = "--write" in sys.argv
    print("=" * 64)
    print("构建噜噜桌宠帧" + ("（写入 orig）" if write else "（预览模式）"))
    print("=" * 64)

    # ---- 1. 抠图 + 裁切（不缩放），拿原始尺度 ----
    cut = {}
    for mid, src in PICKS.items():
        if not src.exists():
            print(f"❌ 缺少源图 {mid}: {src}")
            return
        img, w, h = _content(cutout(Image.open(src)))
        cut[mid] = (img, w, h)

    # ---- 2. 统一缩放系数：以定妆稿高度为准 ----
    base_w, base_h = cut["idle_a"][1], cut["idle_a"][2]
    scale = TARGET_H / base_h
    print(f"\n定妆稿内容 {base_w}x{base_h} -> 统一缩放系数 {scale:.4f}")

    scaled = {}
    for mid, (img, w, h) in cut.items():
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        scaled[mid] = img.resize((nw, nh), Image.Resampling.LANCZOS)

    # ---- 3. 统一帧高，内容底部对齐 ----
    frame_h = max(im.height for im in scaled.values()) + PAD * 2
    print(f"统一帧高 {frame_h}（内容最高 {frame_h - PAD * 2}）\n")

    out_dir = PREVIEW
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []
    for mid, dst_name in MAPPING.items():
        im = scaled[mid]
        fw = im.width + PAD * 2
        canvas = Image.new("RGBA", (fw, frame_h), (0, 0, 0, 0))
        canvas.paste(im, (PAD, frame_h - PAD - im.height), im)
        canvas.save(out_dir / f"{dst_name}.png")
        made.append(f"{dst_name}.png")
        print(f"  {mid:12s} -> {dst_name}.png  内容 {im.width}x{im.height}  帧 {fw}x{frame_h}")

    for i in range(4):
        s = out_dir / f"walk_{i:02d}.png"
        if s.exists():
            Image.open(s).transpose(Image.FLIP_LEFT_RIGHT).save(out_dir / f"walkr_{i:02d}.png")
            made.append(f"walkr_{i:02d}.png")

    # ---- 4. contact sheet ----
    names = ["idle_00", "idle_01", "walk_00", "walk_01", "walk_02", "walk_03",
             "sit_00", "sit_01", "lie_00", "lie_01", "interact_00", "interact_01", "interact_02"]
    ims = [Image.open(out_dir / f"{n}.png").convert("RGBA") for n in names if (out_dir / f"{n}.png").exists()]
    if ims:
        H = max(i.height for i in ims)
        W = sum(i.width for i in ims) + 8 * len(ims)
        sheet = Image.new("RGBA", (W, H), (248, 248, 248, 255))
        x = 0
        for i in ims:
            sheet.paste(i, (x, H - i.height), i)
            x += i.width + 8
        sheet.convert("RGB").save(out_dir / "_contact_sheet.png")
        print(f"\ncontact sheet -> {out_dir / '_contact_sheet.png'}")

    if not write:
        print(f"\n预览 {len(made)} 个文件 -> {out_dir}")
        print("确认无误后加 --write 正式替换 orig")
        return

    if not BACKUP.exists():
        shutil.copytree(ORIG, BACKUP)
        print(f"\n已备份旧素材 -> {BACKUP}")
    keep = set(made)
    for f in ORIG.glob("*.png"):
        if f.name not in keep:
            f.unlink()
            print(f"  清理旧帧 {f.name}")
    for f in out_dir.glob("*.png"):
        if not f.name.startswith("_"):
            shutil.copy2(f, ORIG / f.name)
    print(f"\n✅ 已写入 {len(list(ORIG.glob('*.png')))} 个帧 -> {ORIG}")


if __name__ == "__main__":
    main()
