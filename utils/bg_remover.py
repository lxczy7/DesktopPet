import os
from pathlib import Path
from typing import List, Optional
from rembg import remove, new_session
from PIL import Image
import numpy as np
from config.constants import FRAMES_DIR, ANIMATION_CONFIG


class BackgroundRemover:
    def __init__(self, model_name: str = "u2net"):
        """
        :param model_name: rembg 模型名称
            - 'u2net': 通用模型，较大但精度高 (176MB)
            - 'u2netp': 轻量版，速度快 (4.7MB)
            - 'u2net_human_seg': 人像专用
            - 'u2net_cloth_seg': 衣物分割
            - 'isnet-general-use': 新一代通用模型
        """
        print(f"加载模型: {model_name}...")
        self.session = new_session(model_name)
        self.target_size = ANIMATION_CONFIG["target_size"]
        print("模型加载完成")

    def remove_background(
        self,
        input_path: Path,
        output_path: Path,
        alpha_matting: bool = True,
        alpha_matting_foreground_threshold: int = 240,
        alpha_matting_background_threshold: int = 10,
        alpha_matting_erode_size: int = 10,
    ) -> bool:
        """
        单张图片去背景
        """
        try:
            with open(input_path, "rb") as f:
                input_data = f.read()

            output_data = remove(
                input_data,
                session=self.session,
                alpha_matting=alpha_matting,
                alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
                alpha_matting_background_threshold=alpha_matting_background_threshold,
                alpha_matting_erode_size=alpha_matting_erode_size,
            )

            # 后处理：确保尺寸统一、优化透明边缘
            img = Image.open(io.BytesIO(output_data)).convert("RGBA")
            img = self._post_process(img)
            img.save(output_path, "PNG")
            return True
        except Exception as e:
            print(f"去背景失败 {input_path.name}: {e}")
            return False

    def _post_process(self, img: Image.Image) -> Image.Image:
        """后处理：缩放、边缘平滑、去噪"""
        # 缩放到目标尺寸（保持比例，居中填充透明背景）
        img.thumbnail(self.target_size, Image.Resampling.LANCZOS)

        # 创建目标尺寸的透明画布
        canvas = Image.new("RGBA", self.target_size, (0, 0, 0, 0))
        x = (self.target_size[0] - img.width) // 2
        y = (self.target_size[1] - img.height) // 2
        canvas.paste(img, (x, y), img)

        # 边缘轻微羽化（可选）
        # from PIL import ImageFilter
        # canvas = canvas.filter(ImageFilter.GaussianBlur(radius=0.5))

        return canvas

    def batch_remove(
        self,
        input_dir: Path,
        output_dir: Path,
        pattern: str = "*.png",
        max_workers: int = 1,  # rembg 不适合多线程，显存易溢出
    ) -> List[Path]:
        """
        批量去背景
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        input_files = sorted(input_dir.glob(pattern))
        success_paths = []

        print(f"开始批量去背景: {len(input_files)} 张图片 -> {output_dir}")
        for i, input_file in enumerate(input_files):
            output_file = output_dir / f"{input_file.stem}_nobg.png"
            print(f"  [{i+1}/{len(input_files)}] {input_file.name} -> {output_file.name}")
            if self.remove_background(input_file, output_file):
                success_paths.append(output_file)

        print(f"完成: 成功 {len(success_paths)}/{len(input_files)}")
        return success_paths


import io


def main():
    # 使用轻量模型 u2netp 先测试，效果不好再换 u2net
    remover = BackgroundRemover(model_name="u2netp")

    input_dir = FRAMES_DIR / "selected"
    output_dir = FRAMES_DIR / "nobg"

    if not input_dir.exists():
        print(f"输入目录不存在: {input_dir}")
        print("请先运行 video_extractor.py 提取帧")
        return

    remover.batch_remove(input_dir, output_dir)


if __name__ == "__main__":
    main()