import cv2
import os
from pathlib import Path
from typing import List, Tuple, Optional
import numpy as np
from config.constants import VIDEO_FILES, FRAMES_DIR, ANIMATION_CONFIG


class VideoFrameExtractor:
    def __init__(self, output_dir: Path = FRAMES_DIR):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.target_size = ANIMATION_CONFIG["target_size"]

    def extract_keyframes(
        self,
        video_path: Path,
        interval: int = 15,
        max_frames: int = 200,
        roi: Optional[Tuple[int, int, int, int]] = None
    ) -> List[Path]:
        """
        从视频中提取关键帧
        :param video_path: 视频文件路径
        :param interval: 每隔多少帧提取一帧
        :param max_frames: 最大提取帧数
        :param roi: 感兴趣区域 (x, y, w, h)，None 则全图
        :return: 提取的帧文件路径列表
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"无法打开视频: {video_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        print(f"视频: {video_path.name}, 总帧数: {total_frames}, FPS: {fps:.1f}")

        saved_paths = []
        frame_idx = 0
        saved_count = 0

        video_name = video_path.stem
        video_out_dir = self.output_dir / "raw" / video_name
        video_out_dir.mkdir(parents=True, exist_ok=True)

        while saved_count < max_frames:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % interval == 0:
                if roi:
                    x, y, w, h = roi
                    frame = frame[y:y+h, x:x+w]

                # 缩放到目标尺寸
                frame = cv2.resize(frame, self.target_size, interpolation=cv2.INTER_AREA)

                out_path = video_out_dir / f"frame_{saved_count:04d}.png"
                # 中文路径下 cv2.imwrite 会静默失败，改用 imencode + write_bytes
                ok, buf = cv2.imencode(".png", frame)
                if ok:
                    out_path.write_bytes(buf.tobytes())
                saved_paths.append(out_path)
                saved_count += 1
                print(f"  提取帧 {saved_count}/{max_frames}: {out_path.name}")

            frame_idx += 1

        cap.release()
        print(f"完成: {video_path.name} -> {saved_count} 帧")
        return saved_paths

    def extract_all_videos(
        self,
        interval: int = 15,
        max_frames_per_video: int = 100
    ) -> List[Path]:
        """批量提取所有视频的关键帧"""
        all_frames = []
        for video_path in VIDEO_FILES:
            if video_path.exists():
                frames = self.extract_keyframes(
                    video_path,
                    interval=interval,
                    max_frames=max_frames_per_video
                )
                all_frames.extend(frames)
            else:
                print(f"视频不存在，跳过: {video_path}")
        return all_frames

    @staticmethod
    def select_best_frames(
        frame_paths: List[Path],
        target_count: int = 50,
        method: str = "variance"
    ) -> List[Path]:
        """
        从大量帧中筛选最佳帧（去重、质量评分）
        :param method: 'variance' (拉普拉斯方差评清晰度) 或 'histogram' (直方图差异去重)
        """
        if len(frame_paths) <= target_count:
            return frame_paths

        scored_frames = []
        for path in frame_paths:
            # 中文路径下 cv2.imread 会失败，改用 imdecode
            data = np.fromfile(str(path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            if method == "variance":
                # 拉普拉斯方差：值越大越清晰
                score = cv2.Laplacian(gray, cv2.CV_64F).var()
            else:
                score = 1.0
            scored_frames.append((score, path))

        # 按清晰度降序排序
        scored_frames.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored_frames[:target_count]]


def main():
    extractor = VideoFrameExtractor()
    print("开始提取视频关键帧...")
    frames = extractor.extract_all_videos(interval=12, max_frames_per_video=120)
    print(f"共提取 {len(frames)} 帧")

    # 筛选最佳帧
    best = extractor.select_best_frames(frames, target_count=80)
    print(f"筛选后保留 {len(best)} 帧")

    # 复制到统一目录供后续抠图使用
    select_dir = FRAMES_DIR / "selected"
    select_dir.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(best):
        dst = select_dir / f"frame_{i:04d}.png"
        import shutil
        shutil.copy2(src, dst)
    print(f"已复制到: {select_dir}")


if __name__ == "__main__":
    main()