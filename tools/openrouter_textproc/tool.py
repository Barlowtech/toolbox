"""
OpenRouter Text Processor — Toolbox tool backend.

Two-panel text processor: source text + instruction prompt, sent to any
OpenRouter model. Supports single-shot and conversation modes.

Actions:
    list_models   — fetch available models from OpenRouter (cached 24h)
    process       — single-shot: source_text + instruction → result
    conversation  — multi-turn: maintains message history across turns
    save          — write result text to output_dir as timestamped .md
"""

import json
import os
import time
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

MODELS_CACHE_FILE = os.path.join(os.path.dirname(__file__), "models_cache.json")
CACHE_TTL = 86400  # 24 hours

DEFAULT_SYSTEM_PROMPT = (
    "You are a versatile text processing assistant. The user will provide "
    "source text along with instructions for how to transform, analyze, edit, "
    "or respond to that text. Follow the instructions precisely. When editing "
    "text, preserve the original voice and style unless explicitly told to "
    "change it. Return only the processed result unless the instruction asks "
    "for commentary or explanation."
)

MAX_CONVERSATION_TURNS = 20  # keep last N assistant turns to bound history size


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_request(url: str, api_key: str, method: str = "GET",
                 payload: dict = None, timeout: int = 180) -> dict:
    """Make an HTTP request to OpenRouter and return parsed JSON."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload else None
    req = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode()
        try:
            err_json = json.loads(body)
            msg = err_json.get("error", {}).get("message", body[:300])
        except Exception:
            msg = body[:300]
        raise RuntimeError(f"OpenRouter API error ({e.code}): {msg}")
    except URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")


def _build_user_message(source_text: str, instruction: str) -> str:
    """Structure source text + instruction into a clear user message."""
    if source_text and instruction:
        return f"## Instruction\n\n{instruction}\n\n## Source Text\n\n{source_text}"
    elif source_text:
        return source_text
    elif instruction:
        return instruction
    return ""


def _call_openrouter(messages: list, params: dict, context: dict) -> dict:
    """Send a chat completion request to OpenRouter."""
    api_key = context["secrets"].get("OPENROUTER_KEY")
    if not api_key:
        raise ValueError(
            "OPENROUTER_KEY not set. Add it via the Secrets panel on the dashboard."
        )

    model = params.get("model") or "anthropic/claude-sonnet-4"
    temperature = float(params.get("temperature", 0.7))
    max_tokens = int(params.get("max_tokens", 4096))

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    return _api_request(
        "https://openrouter.ai/api/v1/chat/completions",
        api_key,
        method="POST",
        payload=payload,
        timeout=180,
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def list_models(context: dict) -> dict:
    """Fetch models from OpenRouter, cache for 24h."""
    # Check cache
    if os.path.exists(MODELS_CACHE_FILE):
        cache_age = time.time() - os.path.getmtime(MODELS_CACHE_FILE)
        if cache_age < CACHE_TTL:
            try:
                with open(MODELS_CACHE_FILE) as f:
                    cached = json.load(f)
                return {"message": f"Models loaded (cached). {len(cached)} available.", "data": cached}
            except Exception:
                pass  # bad cache, re-fetch

    api_key = context["secrets"].get("OPENROUTER_KEY")
    if not api_key:
        return {"message": "Error: OPENROUTER_KEY not set. Add it via the Secrets panel."}

    try:
        resp = _api_request(
            "https://openrouter.ai/api/v1/models",
            api_key,
            timeout=30,
        )
    except Exception as e:
        return {"message": f"Error fetching models: {e}"}

    raw_models = resp.get("data", [])
    models = []
    for m in raw_models:
        # Skip image/moderation-only models
        arch = m.get("architecture", {})
        modality_out = arch.get("modality", "text->text")
        if "text" not in modality_out.split("->")[-1]:
            continue

        models.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "context_length": m.get("context_length", 0),
            "pricing_prompt": m.get("pricing", {}).get("prompt", "0"),
            "pricing_completion": m.get("pricing", {}).get("completion", "0"),
        })

    models.sort(key=lambda x: x["name"].lower())

    # Write cache
    try:
        with open(MODELS_CACHE_FILE, "w") as f:
            json.dump(models, f)
    except Exception:
        pass  # non-critical

    return {"message": f"Loaded {len(models)} models.", "data": models}


def process_text(params: dict, context: dict) -> dict:
    """Single-shot: source_text + instruction → processed result."""
    source_text = params.get("source_text", "")
    instruction = params.get("instruction", "")

    if not source_text and not instruction:
        return {"message": "Error: Provide source text, an instruction, or both."}

    system_prompt = params.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
    user_content = _build_user_message(source_text, instruction)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        resp = _call_openrouter(messages, params, context)
    except Exception as e:
        return {"message": f"Error: {e}"}

    choice = resp.get("choices", [{}])[0]
    result_text = choice.get("message", {}).get("content", "")
    usage = resp.get("usage", {})
    model_used = resp.get("model", params.get("model", "unknown"))

    return {
        "message": "Processing complete.",
        "data": {
            "result_text": result_text,
            "model_used": model_used,
            "usage": usage,
            "finish_reason": choice.get("finish_reason", ""),
        },
    }


def conversation_turn(params: dict, context: dict) -> dict:
    """Multi-turn conversation with maintained history."""
    raw_history = params.get("conversation_history", "[]")
    try:
        history = json.loads(raw_history) if isinstance(raw_history, str) else raw_history
    except json.JSONDecodeError:
        history = []

    source_text = params.get("source_text", "")
    instruction = params.get("instruction", "")

    if not instruction:
        return {"message": "Error: Provide an instruction for this turn."}

    # First turn — inject system prompt + combined source/instruction
    if not history:
        system_prompt = params.get("system_prompt") or DEFAULT_SYSTEM_PROMPT
        history.append({"role": "system", "content": system_prompt})
        user_content = _build_user_message(source_text, instruction)
    else:
        # Subsequent turns — instruction only (source text already in context)
        user_content = instruction

    history.append({"role": "user", "content": user_content})

    # Trim history if too long (keep system + last N*2 messages)
    assistant_count = sum(1 for m in history if m["role"] == "assistant")
    if assistant_count > MAX_CONVERSATION_TURNS:
        system_msgs = [m for m in history if m["role"] == "system"]
        other_msgs = [m for m in history if m["role"] != "system"]
        # Keep last MAX_CONVERSATION_TURNS * 2 non-system messages
        keep = MAX_CONVERSATION_TURNS * 2
        history = system_msgs + other_msgs[-keep:]

    try:
        resp = _call_openrouter(history, params, context)
    except Exception as e:
        # Remove the user message we just appended since the call failed
        if history and history[-1]["role"] == "user":
            history.pop()
        return {
            "message": f"Error: {e}",
            "data": {"conversation_history": json.dumps(history)},
        }

    choice = resp.get("choices", [{}])[0]
    assistant_msg = choice.get("message", {}).get("content", "")
    usage = resp.get("usage", {})

    history.append({"role": "assistant", "content": assistant_msg})

    turn_count = sum(1 for m in history if m["role"] == "assistant")

    return {
        "message": "Response received.",
        "data": {
            "result_text": assistant_msg,
            "conversation_history": json.dumps(history),
            "usage": usage,
            "turn_count": turn_count,
            "finish_reason": choice.get("finish_reason", ""),
        },
    }


def save_output(params: dict, context: dict) -> dict:
    """Save result text to a timestamped markdown file."""
    result_text = params.get("result_text", "")
    if not result_text:
        return {"message": "Error: No result text to save."}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_short = (params.get("model") or "unknown").split("/")[-1]
    filename = f"textproc_{model_short}_{timestamp}.md"
    filepath = os.path.join(context["output_dir"], filename)

    os.makedirs(context["output_dir"], exist_ok=True)

    with open(filepath, "w") as f:
        f.write("# OpenRouter Text Processor Output\n\n")
        f.write(f"**Model:** {params.get('model', 'unknown')}\n")
        f.write(f"**Timestamp:** {timestamp}\n")
        f.write(f"**Instruction:** {params.get('instruction', '(none)')}\n\n")
        f.write("---\n\n")
        f.write(result_text)

    file_url = f"{context['outputs_base_url']}/{filename}"
    return {
        "message": f"Saved to {filename}",
        "files": [{"name": filename, "url": file_url}],
    }


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

def run(params: dict, context: dict) -> dict:
    """Entry point — dispatch by action param."""
    try:
        action = params.get("action", "process")

        if action == "list_models":
            return list_models(context)
        elif action == "process":
            return process_text(params, context)
        elif action == "conversation":
            return conversation_turn(params, context)
        elif action == "save":
            return save_output(params, context)
        else:
            return {"message": f"Unknown action: {action}"}
    except Exception as e:
        return {"message": f"Unexpected error: {e}"}
