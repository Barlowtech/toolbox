"""
Workflow builder — parameterizes ComfyUI API-format JSON templates.

Loads template files, replaces __PLACEHOLDER__ values with actual parameters,
and returns ready-to-submit workflow dicts.
"""

import copy
import json
import os
import random
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"

DEFAULT_WAN_NEGATIVE = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
    "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
    "画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
    "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"
)

DEFAULT_QWEN_NEGATIVE = (
    "ugly, blurry, distorted, artifacts, bad, wrong, low quality, "
    "anime, digital art, semirealistic, cartoon, manga, drawing, fake, unreal"
)


def _load_template(name: str) -> dict:
    """Load a workflow template JSON file."""
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    with open(path) as f:
        return json.load(f)


def _replace_placeholders(workflow: dict, replacements: dict) -> dict:
    """Recursively replace __PLACEHOLDER__ strings in workflow dict."""
    result = copy.deepcopy(workflow)

    def _replace(obj):
        if isinstance(obj, dict):
            return {k: _replace(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_replace(v) for v in obj]
        elif isinstance(obj, str) and obj.startswith("__") and obj.endswith("__"):
            key = obj
            if key in replacements:
                return replacements[key]
            return obj  # leave unreplaced if no value provided
        return obj

    return _replace(result)


def build_flf2v_workflow(
    first_frame_filename: str,
    last_frame_filename: str,
    positive_prompt: str,
    negative_prompt: str = None,
    width: int = 640,
    height: int = 640,
    length: int = 81,
    total_steps: int = 20,
    high_noise_steps: int = 10,
    fps: int = 16,
    seed: int = None,
) -> dict:
    """Build a WAN 2.2 First-Last-Frame-to-Video workflow.

    Args:
        first_frame_filename: ComfyCloud filename for the first frame
        last_frame_filename: ComfyCloud filename for the last frame
        positive_prompt: Describes the desired motion/content
        negative_prompt: What to avoid (defaults to standard WAN negative)
        width: Output width (must be divisible by 8)
        height: Output height (must be divisible by 8)
        length: Number of frames. (length-1) must be divisible by 4.
        total_steps: Total sampling steps (split between high/low noise)
        high_noise_steps: Steps for the high-noise expert
        fps: Output video FPS
        seed: Random seed (random if None)
    """
    # Validate frame count
    if (length - 1) % 4 != 0:
        # Snap to nearest valid value
        length = ((length - 1) // 4) * 4 + 1

    if seed is None:
        seed = random.randint(0, 2**53)

    template = _load_template("wan_flf2v.json")

    replacements = {
        "__FIRST_FRAME__": first_frame_filename,
        "__LAST_FRAME__": last_frame_filename,
        "__POSITIVE_PROMPT__": positive_prompt,
        "__NEGATIVE_PROMPT__": negative_prompt or DEFAULT_WAN_NEGATIVE,
        "__WIDTH__": width,
        "__HEIGHT__": height,
        "__LENGTH__": length,
        "__TOTAL_STEPS__": total_steps,
        "__HIGH_NOISE_STEPS__": high_noise_steps,
        "__FPS__": fps,
        "__SEED__": seed,
    }

    return _replace_placeholders(template, replacements)


def build_qwen_edit_workflow(
    input_image_filename: str,
    edit_prompt: str,
    negative_prompt: str = None,
    steps: int = 8,
    seed: int = None,
    lora1_strength: float = 1.0,
    lora2_name: str = "Flat Chest (Qwen).safetensors",
    lora2_strength: float = 0.0,
    lora3_name: str = "[QWEN] Send Nudes Pro - Beta v1.safetensors",
    lora3_strength: float = 0.0,
    lora4_name: str = "Flat Chest (Qwen).safetensors",
    lora4_strength: float = 0.0,
) -> dict:
    """Build a Qwen image editing workflow.

    Args:
        input_image_filename: ComfyCloud filename for the source image
        edit_prompt: Natural language edit instruction
        negative_prompt: What to avoid
        steps: Sampling steps (default 8 for speed)
        seed: Random seed (random if None)
        lora1_strength: Strength for jib_qwen_fix LoRA (1.0 recommended)
        lora2-4_name/strength: Additional LoRA slots (set strength to 0 to disable)
    """
    if seed is None:
        seed = random.randint(0, 2**53)

    template = _load_template("qwen_edit.json")

    replacements = {
        "__INPUT_IMAGE__": input_image_filename,
        "__EDIT_PROMPT__": edit_prompt,
        "__NEGATIVE_PROMPT__": negative_prompt or DEFAULT_QWEN_NEGATIVE,
        "__STEPS__": steps,
        "__SEED__": seed,
        "__LORA1_STRENGTH__": lora1_strength,
        "__LORA2_NAME__": lora2_name,
        "__LORA2_STRENGTH__": lora2_strength,
        "__LORA3_NAME__": lora3_name,
        "__LORA3_STRENGTH__": lora3_strength,
        "__LORA4_NAME__": lora4_name,
        "__LORA4_STRENGTH__": lora4_strength,
    }

    return _replace_placeholders(template, replacements)


def snap_frame_count(target_frames: int) -> int:
    """Snap to nearest valid WAN frame count where (n-1) is divisible by 4."""
    if target_frames < 5:
        return 5
    return ((target_frames - 1) // 4) * 4 + 1


def calculate_frame_count(time_gap_seconds: float, fps: int = 16,
                           min_frames: int = 33, max_frames: int = 121) -> int:
    """Calculate appropriate frame count for a time gap."""
    target = int(time_gap_seconds * fps)
    target = max(min_frames, min(target, max_frames))
    return snap_frame_count(target)
