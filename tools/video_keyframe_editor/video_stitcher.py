"""
Video stitcher — concatenate video segments using FFmpeg.
"""

import os
import subprocess
import shutil
import logging
import tempfile

logger = logging.getLogger("video_stitcher")


def find_ffmpeg() -> str:
    """Locate ffmpeg binary. Returns path or raises RuntimeError."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    # Common macOS locations
    for p in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
        if os.path.isfile(p):
            return p
    raise RuntimeError(
        "FFmpeg not found. Install it with: brew install ffmpeg (macOS) "
        "or download from https://ffmpeg.org"
    )


def stitch_segments(segment_paths: list[str], output_path: str,
                     crossfade: float = 0.0) -> str:
    """Concatenate video segments into a single output file.

    Args:
        segment_paths: Ordered list of video file paths
        output_path: Where to save the final video
        crossfade: Crossfade duration in seconds (0 = hard cut)

    Returns:
        Path to the output file
    """
    ffmpeg = find_ffmpeg()

    if not segment_paths:
        raise ValueError("No segments to stitch")

    if len(segment_paths) == 1:
        # Just copy the single segment
        shutil.copy2(segment_paths[0], output_path)
        return output_path

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if crossfade > 0:
        return _stitch_with_crossfade(ffmpeg, segment_paths, output_path, crossfade)
    else:
        return _stitch_concat(ffmpeg, segment_paths, output_path)


def _stitch_concat(ffmpeg: str, segments: list[str], output_path: str) -> str:
    """Stitch using FFmpeg concat demuxer (fast, no re-encode if codecs match)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for seg in segments:
            # FFmpeg concat demuxer needs absolute paths with proper escaping
            abs_path = os.path.abspath(seg).replace("'", "'\\''")
            f.write(f"file '{abs_path}'\n")
        concat_file = f.name

    try:
        cmd = [
            ffmpeg, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            # Fallback: re-encode if concat copy fails (codec mismatch)
            logger.warning("Concat copy failed, re-encoding...")
            cmd = [
                ffmpeg, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg concat failed: {result.stderr[-500:]}")
    finally:
        os.unlink(concat_file)

    logger.info(f"Stitched {len(segments)} segments -> {output_path}")
    return output_path


def _stitch_with_crossfade(ffmpeg: str, segments: list[str],
                            output_path: str, crossfade: float) -> str:
    """Stitch with crossfade transitions using FFmpeg xfade filter."""
    if len(segments) == 2:
        cmd = [
            ffmpeg, "-y",
            "-i", segments[0],
            "-i", segments[1],
            "-filter_complex",
            f"xfade=transition=fade:duration={crossfade}:offset=0",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
    else:
        # For 3+ segments, chain xfade filters
        inputs = []
        for seg in segments:
            inputs.extend(["-i", seg])

        # Build filter chain
        filter_parts = []
        prev = "[0:v]"
        for i in range(1, len(segments)):
            next_label = f"[v{i}]" if i < len(segments) - 1 else ""
            out = next_label if next_label else ""
            filter_parts.append(
                f"{prev}[{i}:v]xfade=transition=fade:duration={crossfade}:offset=0{out}"
            )
            prev = next_label

        filter_str = ";".join(filter_parts)
        cmd = [
            ffmpeg, "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning(f"Crossfade stitch failed, falling back to hard cuts: {result.stderr[-200:]}")
        return _stitch_concat(ffmpeg, segments, output_path)

    logger.info(f"Stitched {len(segments)} segments with {crossfade}s crossfade -> {output_path}")
    return output_path
