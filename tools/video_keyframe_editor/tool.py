"""
Video Keyframe Editor — Toolbox orchestrator.

This tool exposes multiple actions via the params["action"] field,
allowing the custom UI to drive a multi-step pipeline:

  1. extract_keyframes  — Pull keyframes from a video
  2. edit_keyframes     — Send selected keyframes to ComfyCloud Qwen edit
  3. generate_segments  — Send edited frame pairs to WAN 2.2 FLF2V
  4. stitch_video       — Concatenate generated segments into final output
  5. get_status         — Check status of running jobs
"""

import asyncio
import json
import os
import sys
import logging
from pathlib import Path

# Add tool directory to path for local imports
TOOL_DIR = Path(__file__).parent
sys.path.insert(0, str(TOOL_DIR))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("video_keyframe_editor")


def run(params: dict, context: dict) -> dict:
    """Main entry point. Dispatches to action handlers."""
    action = params.get("action", "")
    secrets = context.get("secrets", {})

    if action == "extract_keyframes":
        return _action_extract(params, context)
    elif action == "edit_keyframes":
        return asyncio.get_event_loop().run_until_complete(
            _action_edit(params, context, secrets)
        )
    elif action == "generate_segments":
        return asyncio.get_event_loop().run_until_complete(
            _action_generate(params, context, secrets)
        )
    elif action == "stitch_video":
        return _action_stitch(params, context)
    elif action == "get_video_info":
        return _action_video_info(params)
    elif action == "check_requirements":
        return _action_check_requirements()
    else:
        return {
            "message": f"Unknown action: '{action}'",
            "data": {
                "available_actions": [
                    "check_requirements",
                    "get_video_info",
                    "extract_keyframes",
                    "edit_keyframes",
                    "generate_segments",
                    "stitch_video",
                ]
            }
        }


# ---------------------------------------------------------------------------
# Action: Check Requirements
# ---------------------------------------------------------------------------

def _action_check_requirements() -> dict:
    """Verify that all dependencies are available or installable."""
    status = {}

    # OpenCV
    try:
        import cv2
        status["opencv"] = {"installed": True, "version": cv2.__version__}
    except ImportError:
        status["opencv"] = {"installed": False, "install": "pip install opencv-python"}

    # aiohttp
    try:
        import aiohttp
        status["aiohttp"] = {"installed": True, "version": aiohttp.__version__}
    except ImportError:
        status["aiohttp"] = {"installed": False, "install": "pip install aiohttp"}

    # scenedetect
    try:
        import scenedetect
        status["scenedetect"] = {"installed": True, "version": getattr(scenedetect, "__version__", "?")}
    except ImportError:
        status["scenedetect"] = {"installed": False, "install": "pip install scenedetect[opencv]"}

    # FFmpeg
    from video_stitcher import find_ffmpeg
    try:
        ffmpeg_path = find_ffmpeg()
        status["ffmpeg"] = {"installed": True, "path": ffmpeg_path}
    except RuntimeError:
        status["ffmpeg"] = {"installed": False, "install": "brew install ffmpeg"}

    all_ok = all(v["installed"] for v in status.values())

    return {
        "message": "All requirements met" if all_ok else "Some requirements missing",
        "data": {"requirements": status, "all_ok": all_ok},
    }


# ---------------------------------------------------------------------------
# Action: Get Video Info
# ---------------------------------------------------------------------------

def _action_video_info(params: dict) -> dict:
    video_path = params.get("video_path", "")
    if not video_path or not os.path.isfile(video_path):
        return {"message": f"Video not found: {video_path}"}

    from keyframe_extractor import get_video_info
    info = get_video_info(video_path)
    return {
        "message": f"{info['width']}x{info['height']} @ {info['fps']:.1f}fps, {info['duration']:.1f}s",
        "data": info,
    }


# ---------------------------------------------------------------------------
# Action: Extract Keyframes
# ---------------------------------------------------------------------------

def _action_extract(params: dict, context: dict) -> dict:
    video_path = params.get("video_path", "")
    method = params.get("method", "scene_detect")
    interval = float(params.get("interval_sec", 2.0) or 2.0)
    threshold = float(params.get("threshold", 27.0) or 27.0)
    max_kf = int(params.get("max_keyframes", 30) or 30)

    if not video_path or not os.path.isfile(video_path):
        return {"message": f"Video not found: {video_path}"}

    output_dir = os.path.join(context["output_dir"], "keyframes")
    os.makedirs(output_dir, exist_ok=True)

    from keyframe_extractor import extract_keyframes
    keyframes = extract_keyframes(
        video_path, output_dir,
        method=method,
        interval_sec=interval,
        threshold=threshold,
        max_keyframes=max_kf,
    )

    base_url = context["outputs_base_url"]
    kf_data = []
    for kf in keyframes:
        rel_path = os.path.relpath(kf.path, context["output_dir"])
        kf_data.append({
            "index": kf.index,
            "timestamp": round(kf.timestamp, 2),
            "frame_number": kf.frame_number,
            "path": kf.path,
            "url": f"{base_url}/{rel_path}",
        })

    return {
        "message": f"Extracted {len(keyframes)} keyframes",
        "data": {
            "keyframes": kf_data,
            "output_dir": output_dir,
        },
    }


# ---------------------------------------------------------------------------
# Action: Edit Keyframes (Qwen on ComfyCloud)
# ---------------------------------------------------------------------------

async def _action_edit(params: dict, context: dict, secrets: dict) -> dict:
    api_key = secrets.get("COMFYCLOUD_API_KEY", "")
    if not api_key:
        return {"message": "Error: COMFYCLOUD_API_KEY not set. Add it in the Secrets panel."}

    base_url = secrets.get("COMFYCLOUD_BASE_URL", "https://api.comfy.org")
    edit_prompt = params.get("edit_prompt", "")
    keyframe_paths = params.get("keyframe_paths", [])
    steps = int(params.get("steps", 8) or 8)
    lora1_strength = float(params.get("lora1_strength", 1.0) or 1.0)
    lora2_name = params.get("lora2_name", "Flat Chest (Qwen).safetensors")
    lora2_strength = float(params.get("lora2_strength", 0.0) or 0.0)
    lora3_name = params.get("lora3_name", "[QWEN] Send Nudes Pro - Beta v1.safetensors")
    lora3_strength = float(params.get("lora3_strength", 0.0) or 0.0)
    lora4_name = params.get("lora4_name", "Flat Chest (Qwen).safetensors")
    lora4_strength = float(params.get("lora4_strength", 0.0) or 0.0)

    if not edit_prompt:
        return {"message": "Error: No edit prompt provided."}
    if not keyframe_paths:
        return {"message": "Error: No keyframes selected for editing."}

    # Ensure aiohttp is available
    try:
        import aiohttp
    except ImportError:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "aiohttp",
             "--break-system-packages", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    from comfycloud_client import ComfyCloudClient
    from workflow_builder import build_qwen_edit_workflow

    output_dir = os.path.join(context["output_dir"], "edited_frames")
    os.makedirs(output_dir, exist_ok=True)

    client = ComfyCloudClient(api_key, base_url)
    results = []
    log_lines = []

    try:
        for i, kf_path in enumerate(keyframe_paths):
            log_lines.append(f"  [{i+1}/{len(keyframe_paths)}] Uploading {os.path.basename(kf_path)}…")
            uploaded_name = await client.upload_image(kf_path)

            log_lines.append(f"  [{i+1}/{len(keyframe_paths)}] Submitting Qwen edit…")
            workflow = build_qwen_edit_workflow(
                input_image_filename=uploaded_name,
                edit_prompt=edit_prompt,
                steps=steps,
                lora1_strength=lora1_strength,
                lora2_name=lora2_name,
                lora2_strength=lora2_strength,
                lora3_name=lora3_name,
                lora3_strength=lora3_strength,
                lora4_name=lora4_name,
                lora4_strength=lora4_strength,
            )

            output_files = await client.run_workflow(workflow, output_dir)

            if output_files:
                results.append({
                    "original": kf_path,
                    "edited": output_files[0],
                    "all_outputs": output_files,
                })
                log_lines.append(f"  [{i+1}/{len(keyframe_paths)}] ✓ Edited -> {os.path.basename(output_files[0])}")
            else:
                log_lines.append(f"  [{i+1}/{len(keyframe_paths)}] ✗ No output received")
    finally:
        await client.close()

    base_url_out = context["outputs_base_url"]
    for r in results:
        rel = os.path.relpath(r["edited"], context["output_dir"])
        r["url"] = f"{base_url_out}/{rel}"

    return {
        "message": f"Edited {len(results)}/{len(keyframe_paths)} keyframes",
        "log": log_lines,
        "data": {"edited_frames": results},
    }


# ---------------------------------------------------------------------------
# Action: Generate Video Segments (WAN 2.2 FLF2V)
# ---------------------------------------------------------------------------

async def _action_generate(params: dict, context: dict, secrets: dict) -> dict:
    api_key = secrets.get("COMFYCLOUD_API_KEY", "")
    if not api_key:
        return {"message": "Error: COMFYCLOUD_API_KEY not set. Add it in the Secrets panel."}

    base_url = secrets.get("COMFYCLOUD_BASE_URL", "https://api.comfy.org")
    frame_pairs = params.get("frame_pairs", [])
    motion_prompt = params.get("motion_prompt", "")
    width = int(params.get("width", 640) or 640)
    height = int(params.get("height", 640) or 640)
    length = int(params.get("length", 81) or 81)
    total_steps = int(params.get("total_steps", 20) or 20)
    high_noise_steps = int(params.get("high_noise_steps", 10) or 10)
    fps = int(params.get("fps", 16) or 16)

    if not frame_pairs:
        return {"message": "Error: No frame pairs provided."}

    try:
        import aiohttp
    except ImportError:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "aiohttp",
             "--break-system-packages", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    from comfycloud_client import ComfyCloudClient
    from workflow_builder import build_flf2v_workflow

    output_dir = os.path.join(context["output_dir"], "segments")
    os.makedirs(output_dir, exist_ok=True)

    client = ComfyCloudClient(api_key, base_url)
    segments = []
    log_lines = []

    try:
        for i, pair in enumerate(frame_pairs):
            first_path = pair["first"]
            last_path = pair["last"]

            log_lines.append(f"  [{i+1}/{len(frame_pairs)}] Uploading frame pair…")
            first_name = await client.upload_image(first_path)
            last_name = await client.upload_image(last_path)

            prompt = motion_prompt or "Smooth natural motion transitioning between the two frames."

            log_lines.append(f"  [{i+1}/{len(frame_pairs)}] Submitting WAN 2.2 FLF2V…")
            workflow = build_flf2v_workflow(
                first_frame_filename=first_name,
                last_frame_filename=last_name,
                positive_prompt=prompt,
                width=width,
                height=height,
                length=length,
                total_steps=total_steps,
                high_noise_steps=high_noise_steps,
                fps=fps,
            )

            output_files = await client.run_workflow(workflow, output_dir, timeout=900)

            if output_files:
                segments.append({
                    "index": i,
                    "first": first_path,
                    "last": last_path,
                    "video": output_files[0],
                    "all_outputs": output_files,
                })
                log_lines.append(f"  [{i+1}/{len(frame_pairs)}] ✓ Generated -> {os.path.basename(output_files[0])}")
            else:
                log_lines.append(f"  [{i+1}/{len(frame_pairs)}] ✗ No output received")
    finally:
        await client.close()

    return {
        "message": f"Generated {len(segments)}/{len(frame_pairs)} video segments",
        "log": log_lines,
        "data": {"segments": segments},
    }


# ---------------------------------------------------------------------------
# Action: Stitch Video
# ---------------------------------------------------------------------------

def _action_stitch(params: dict, context: dict) -> dict:
    segment_paths = params.get("segment_paths", [])
    crossfade = float(params.get("crossfade", 0.0) or 0.0)

    if not segment_paths:
        return {"message": "Error: No segments to stitch."}

    from video_stitcher import stitch_segments

    output_path = os.path.join(context["output_dir"], "final_output.mp4")
    result_path = stitch_segments(segment_paths, output_path, crossfade=crossfade)

    rel = os.path.relpath(result_path, context["output_dir"])
    return {
        "message": f"Stitched {len(segment_paths)} segments into final video",
        "data": {"output_path": result_path},
        "files": [{"name": "final_output.mp4", "url": f"{context['outputs_base_url']}/{rel}"}],
    }
