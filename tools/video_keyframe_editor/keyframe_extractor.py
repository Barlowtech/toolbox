"""
Keyframe extraction from video files.

Uses PySceneDetect for content-aware scene detection when available,
falls back to interval-based extraction.
"""

import os
import subprocess
import sys
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger("keyframe_extractor")


def _ensure_cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "opencv-python",
             "--break-system-packages", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import cv2
        return cv2


def _ensure_scenedetect():
    try:
        import scenedetect
        return scenedetect
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "scenedetect[opencv]",
             "--break-system-packages", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import scenedetect
        return scenedetect


@dataclass
class Keyframe:
    index: int
    timestamp: float  # seconds
    frame_number: int
    path: str  # path to saved image


def extract_by_interval(video_path: str, output_dir: str,
                         interval_sec: float = 2.0,
                         max_keyframes: int = 50) -> list[Keyframe]:
    """Extract frames at fixed time intervals."""
    cv2 = _ensure_cv2()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    interval_frames = int(interval_sec * fps)

    os.makedirs(output_dir, exist_ok=True)
    keyframes = []
    frame_num = 0

    while frame_num < total_frames and len(keyframes) < max_keyframes:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            break

        timestamp = frame_num / fps
        filename = f"keyframe_{len(keyframes):04d}_{timestamp:.2f}s.png"
        filepath = os.path.join(output_dir, filename)
        cv2.imwrite(filepath, frame)

        keyframes.append(Keyframe(
            index=len(keyframes),
            timestamp=timestamp,
            frame_number=frame_num,
            path=filepath,
        ))

        frame_num += interval_frames

    cap.release()
    logger.info(f"Extracted {len(keyframes)} keyframes by interval ({interval_sec}s) from {video_path}")
    return keyframes


def extract_by_scene_detect(video_path: str, output_dir: str,
                              threshold: float = 27.0,
                              min_scene_len: float = 1.0,
                              max_keyframes: int = 50) -> list[Keyframe]:
    """Extract keyframes at scene boundaries using PySceneDetect."""
    cv2 = _ensure_cv2()
    sd = _ensure_scenedetect()
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len * video.frame_rate))
    )
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    if not scene_list:
        logger.warning("No scenes detected, falling back to interval extraction")
        return extract_by_interval(video_path, output_dir, max_keyframes=max_keyframes)

    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    keyframes = []

    # Always include the first frame
    scene_frames = [0]
    for start, end in scene_list:
        frame_num = start.get_frames()
        if frame_num not in scene_frames:
            scene_frames.append(frame_num)

    # Cap at max
    scene_frames = scene_frames[:max_keyframes]

    for i, frame_num in enumerate(scene_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()
        if not ret:
            continue

        timestamp = frame_num / fps
        filename = f"keyframe_{i:04d}_{timestamp:.2f}s.png"
        filepath = os.path.join(output_dir, filename)
        cv2.imwrite(filepath, frame)

        keyframes.append(Keyframe(
            index=i,
            timestamp=timestamp,
            frame_number=frame_num,
            path=filepath,
        ))

    cap.release()
    logger.info(f"Extracted {len(keyframes)} keyframes by scene detection from {video_path}")
    return keyframes


def extract_keyframes(video_path: str, output_dir: str,
                       method: str = "scene_detect",
                       interval_sec: float = 2.0,
                       threshold: float = 27.0,
                       min_scene_len: float = 1.0,
                       max_keyframes: int = 50) -> list[Keyframe]:
    """Main entry point. Extracts keyframes using the specified method."""
    if method == "scene_detect":
        try:
            return extract_by_scene_detect(
                video_path, output_dir,
                threshold=threshold,
                min_scene_len=min_scene_len,
                max_keyframes=max_keyframes,
            )
        except Exception as e:
            logger.warning(f"Scene detection failed ({e}), falling back to interval")
            return extract_by_interval(video_path, output_dir,
                                        interval_sec=interval_sec,
                                        max_keyframes=max_keyframes)
    else:
        return extract_by_interval(video_path, output_dir,
                                    interval_sec=interval_sec,
                                    max_keyframes=max_keyframes)


def get_video_info(video_path: str) -> dict:
    """Get basic video metadata."""
    cv2 = _ensure_cv2()
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    info = {
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "fps": cap.get(cv2.CAP_PROP_FPS),
        "total_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "duration": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / (cap.get(cv2.CAP_PROP_FPS) or 30),
    }
    cap.release()
    return info
