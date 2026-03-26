"""
Video Frame Extractor — pull frames from any video at configurable intervals.

Uses OpenCV (cv2) for video decoding. Will auto-install opencv-python if missing.

Features:
  - Extract every Nth frame
  - Optional start/end time window
  - JPG/PNG/BMP output
  - Optional resize (maintains aspect ratio)
  - Max frame safety limit
  - Saves to timestamped output folder
"""

import os
import subprocess
import sys
import time
from pathlib import Path


def _ensure_cv2():
    """Install opencv-python if not already available."""
    try:
        import cv2
        return cv2
    except ImportError:
        print("[toolbox] Installing opencv-python…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "opencv-python", "--break-system-packages", "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import cv2
        return cv2


def _parse_time(value: str) -> float | None:
    """Parse a time string into seconds. Accepts HH:MM:SS, MM:SS, or raw seconds."""
    if not value or not value.strip():
        return None
    value = value.strip()

    # Raw number (seconds)
    try:
        return float(value)
    except ValueError:
        pass

    # HH:MM:SS or MM:SS
    parts = value.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
    except (ValueError, TypeError):
        pass

    return None


def run(params: dict, context: dict) -> dict:
    cv2 = _ensure_cv2()

    video_path = params.get("video_path", "").strip()
    every_n = max(1, int(params.get("every_n", 10) or 10))
    fmt = params.get("format", "jpg").lower()
    quality = int(params.get("quality", 95) or 95)
    start_time = _parse_time(params.get("start_time", ""))
    end_time = _parse_time(params.get("end_time", ""))
    max_frames = int(params.get("max_frames", 0) or 0)
    resize_width = int(params.get("resize_width", 0) or 0)

    # --- Validate ---
    if not video_path:
        return {"message": "Error: No video path provided."}

    if not os.path.isfile(video_path):
        return {"message": f"Error: File not found — {video_path}"}

    # --- Open video ---
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"message": f"Error: Could not open video — {video_path}"}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = total_frames / fps if fps > 0 else 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    video_name = Path(video_path).stem

    # Calculate start/end frame numbers
    start_frame = int(start_time * fps) if start_time is not None else 0
    end_frame = int(end_time * fps) if end_time is not None else total_frames

    start_frame = max(0, min(start_frame, total_frames))
    end_frame = max(start_frame, min(end_frame, total_frames))

    # --- Output directory ---
    output_dir = context["output_dir"]

    # --- Extension and encode params ---
    ext = fmt if fmt in ("jpg", "png", "bmp") else "jpg"
    encode_params = []
    if ext == "jpg":
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    elif ext == "png":
        encode_params = [cv2.IMWRITE_PNG_COMPRESSION, 3]

    # --- Extract ---
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    extracted = 0
    frame_idx = start_frame
    log_lines = [
        f"  Video:      {video_name} ({width}x{height})",
        f"  Duration:   {duration:.1f}s @ {fps:.1f} fps ({total_frames} frames)",
        f"  Range:      frame {start_frame} → {end_frame}",
        f"  Sampling:   every {every_n} frame{'s' if every_n > 1 else ''}",
        f"  Format:     {ext.upper()}" + (f" (quality {quality})" if ext == "jpg" else ""),
        f"  Resize:     {'original' if resize_width == 0 else f'{resize_width}px wide'}",
        f"  Output:     {output_dir}",
        "",
    ]

    t0 = time.time()

    while frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret:
            break

        if (frame_idx - start_frame) % every_n == 0:
            # Optional resize
            if resize_width > 0 and frame.shape[1] != resize_width:
                scale = resize_width / frame.shape[1]
                new_h = int(frame.shape[0] * scale)
                frame = cv2.resize(frame, (resize_width, new_h), interpolation=cv2.INTER_AREA)

            # Timestamp for filename
            timestamp_sec = frame_idx / fps
            minutes = int(timestamp_sec // 60)
            seconds = timestamp_sec % 60

            filename = f"{video_name}_f{frame_idx:06d}_{minutes:02d}m{seconds:05.2f}s.{ext}"
            filepath = os.path.join(output_dir, filename)
            cv2.imwrite(filepath, frame, encode_params)

            extracted += 1

            # Progress logging every 50 frames
            if extracted % 50 == 0:
                pct = ((frame_idx - start_frame) / max(1, end_frame - start_frame)) * 100
                log_lines.append(f"  … extracted {extracted} frames ({pct:.0f}%)")

            if max_frames > 0 and extracted >= max_frames:
                log_lines.append(f"  ⚠ Hit max frame limit ({max_frames})")
                break

        frame_idx += 1

    cap.release()
    elapsed = time.time() - t0

    log_lines.append("")
    log_lines.append(f"  ✓ Extracted {extracted} frames in {elapsed:.1f}s")

    # Build file links for first few frames (preview)
    output_files = []
    base_url = context["outputs_base_url"]
    saved_files = sorted(os.listdir(output_dir))[:10]
    for f in saved_files:
        output_files.append({"name": f, "url": f"{base_url}/{f}"})
    if len(os.listdir(output_dir)) > 10:
        output_files.append({"name": f"… and {len(os.listdir(output_dir)) - 10} more", "url": "#"})

    return {
        "message": f"Extracted {extracted} frames from {video_name} ({elapsed:.1f}s)",
        "log": log_lines,
        "data": {
            "frames_extracted": extracted,
            "elapsed_seconds": round(elapsed, 2),
            "output_dir": output_dir,
            "video": {
                "name": video_name,
                "resolution": f"{width}x{height}",
                "fps": round(fps, 2),
                "duration_seconds": round(duration, 2),
                "total_frames": total_frames,
            },
        },
        "files": output_files,
    }
