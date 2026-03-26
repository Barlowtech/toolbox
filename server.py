"""
Toolbox — Local Tool Dashboard Server

A lightweight FastAPI server that auto-discovers Python tools from the /tools
directory and serves a browser-based dashboard for running them.

Each tool is a folder containing:
  - manifest.json  (name, description, category, icon, params)
  - tool.py        (must define a `run(params, context)` function — sync or async)
  - ui.html        (OPTIONAL — custom interface loaded instead of auto-generated form)

If a tool folder contains ui.html, that file is served as the tool's interface.
The custom UI has access to a Toolbox JS API for calling the backend.
If no ui.html exists, a form is auto-generated from manifest.json params.

Usage:
  python server.py
  Then open http://localhost:8400 in your browser.
"""

import asyncio
import importlib.util
import json
import os
import sys
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.resolve()
TOOLS_DIR = BASE_DIR / "tools"
OUTPUTS_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"

SECRETS_FILE = BASE_DIR / "secrets.json"

OUTPUTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Secrets Management
# ---------------------------------------------------------------------------

def load_secrets() -> dict:
    """Load secrets from secrets.json. Returns empty dict if missing."""
    if not SECRETS_FILE.exists():
        return {}
    try:
        with open(SECRETS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_secrets(secrets: dict):
    """Write secrets dict to secrets.json."""
    with open(SECRETS_FILE, "w") as f:
        json.dump(secrets, f, indent=2)


# ---------------------------------------------------------------------------
# Tool Discovery
# ---------------------------------------------------------------------------

def discover_tools() -> dict:
    """Scan /tools for valid tool folders (manifest.json + tool.py)."""
    tools = {}
    if not TOOLS_DIR.exists():
        return tools

    for folder in sorted(TOOLS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        manifest_path = folder / "manifest.json"
        tool_path = folder / "tool.py"
        if not manifest_path.exists() or not tool_path.exists():
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            manifest["id"] = folder.name
            manifest["path"] = str(folder)
            manifest["has_custom_ui"] = (folder / "ui.html").exists()
            tools[folder.name] = manifest
        except Exception as e:
            print(f"[warn] Skipping {folder.name}: {e}")
    return tools


def load_tool_module(tool_id: str):
    """Dynamically import a tool's tool.py module."""
    tool_path = TOOLS_DIR / tool_id / "tool.py"
    if not tool_path.exists():
        raise FileNotFoundError(f"Tool '{tool_id}' not found")

    spec = importlib.util.spec_from_file_location(f"tools.{tool_id}", tool_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Toolbox", version="1.0.0")

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
# Serve output files so tools can link to results
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/tools")
async def list_tools():
    """Return all discovered tools and their manifests."""
    tools = discover_tools()
    return {"tools": list(tools.values())}


@app.get("/api/tools/{tool_id}")
async def get_tool(tool_id: str):
    """Return a single tool's manifest."""
    tools = discover_tools()
    if tool_id not in tools:
        raise HTTPException(404, f"Tool '{tool_id}' not found")
    return tools[tool_id]


@app.get("/api/tools/{tool_id}/ui")
async def get_tool_ui(tool_id: str):
    """Serve a tool's custom ui.html if it exists."""
    ui_path = TOOLS_DIR / tool_id / "ui.html"
    if not ui_path.exists():
        raise HTTPException(404, f"No custom UI for tool '{tool_id}'")
    return FileResponse(ui_path, media_type="text/html")


@app.get("/api/tools/{tool_id}/assets/{file_path:path}")
async def get_tool_asset(tool_id: str, file_path: str):
    """Serve static assets from a tool's folder (images, css, js, etc.)."""
    asset_path = (TOOLS_DIR / tool_id / file_path).resolve()
    # Security: ensure the resolved path is inside the tool's folder
    tool_folder = (TOOLS_DIR / tool_id).resolve()
    if not str(asset_path).startswith(str(tool_folder)):
        raise HTTPException(403, "Access denied")
    if not asset_path.exists():
        raise HTTPException(404, "Asset not found")
    return FileResponse(asset_path)


# ---------------------------------------------------------------------------
# Secrets API
# ---------------------------------------------------------------------------

@app.get("/api/secrets")
async def list_secrets():
    """Return all secret keys (names only, no values)."""
    secrets = load_secrets()
    return {
        "keys": [
            {"key": k, "preview": v[:4] + "…" if len(v) > 4 else "***"}
            for k, v in secrets.items()
        ]
    }


@app.post("/api/secrets")
async def set_secret(payload: dict = {}):
    """Set or update a secret. Body: {"key": "NAME", "value": "sk-..."}"""
    key = payload.get("key", "").strip()
    value = payload.get("value", "")
    if not key:
        raise HTTPException(400, "Secret key is required")
    secrets = load_secrets()
    secrets[key] = value
    save_secrets(secrets)
    return {"status": "ok", "key": key}


@app.delete("/api/secrets/{key}")
async def delete_secret(key: str):
    """Delete a secret by key."""
    secrets = load_secrets()
    if key not in secrets:
        raise HTTPException(404, f"Secret '{key}' not found")
    del secrets[key]
    save_secrets(secrets)
    return {"status": "ok", "key": key}


# ---------------------------------------------------------------------------
# Tool Execution
# ---------------------------------------------------------------------------

@app.post("/api/tools/{tool_id}/run")
async def run_tool(tool_id: str, payload: dict = {}):
    """Execute a tool with the given parameters."""
    tools = discover_tools()
    if tool_id not in tools:
        raise HTTPException(404, f"Tool '{tool_id}' not found")

    # Build context that every tool receives
    run_id = str(uuid.uuid4())[:8]
    run_output_dir = OUTPUTS_DIR / f"{tool_id}_{run_id}"
    run_output_dir.mkdir(exist_ok=True)

    context = {
        "run_id": run_id,
        "tool_id": tool_id,
        "output_dir": str(run_output_dir),
        "outputs_base_url": f"/outputs/{tool_id}_{run_id}",
        "base_dir": str(BASE_DIR),
        "timestamp": datetime.now().isoformat(),
        "secrets": load_secrets(),
    }

    try:
        module = load_tool_module(tool_id)
        if not hasattr(module, "run"):
            raise AttributeError(f"Tool '{tool_id}' has no run() function")

        result = module.run(payload.get("params", {}), context)
        # Support both sync and async run functions
        if asyncio.iscoroutine(result):
            result = await result

        return {
            "status": "success",
            "run_id": run_id,
            "result": result,
        }

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "run_id": run_id,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
        )


@app.websocket("/ws/tools/{tool_id}/run")
async def run_tool_ws(websocket: WebSocket, tool_id: str):
    """WebSocket endpoint for tools that stream output."""
    await websocket.accept()

    tools = discover_tools()
    if tool_id not in tools:
        await websocket.send_json({"type": "error", "message": f"Tool '{tool_id}' not found"})
        await websocket.close()
        return

    run_id = str(uuid.uuid4())[:8]
    run_output_dir = OUTPUTS_DIR / f"{tool_id}_{run_id}"
    run_output_dir.mkdir(exist_ok=True)

    context = {
        "run_id": run_id,
        "tool_id": tool_id,
        "output_dir": str(run_output_dir),
        "outputs_base_url": f"/outputs/{tool_id}_{run_id}",
        "base_dir": str(BASE_DIR),
        "timestamp": datetime.now().isoformat(),
        "secrets": load_secrets(),
        "send_progress": lambda msg: asyncio.ensure_future(
            websocket.send_json({"type": "progress", "message": msg})
        ),
    }

    try:
        data = await websocket.receive_json()
        params = data.get("params", {})

        module = load_tool_module(tool_id)
        result = module.run(params, context)
        if asyncio.iscoroutine(result):
            result = await result

        await websocket.send_json({"type": "complete", "run_id": run_id, "result": result})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        traceback.print_exc()
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n  ╔═══════════════════════════════════════╗")
    print("  ║         TOOLBOX — Local Dashboard      ║")
    print("  ║     http://localhost:8400               ║")
    print("  ╚═══════════════════════════════════════╝\n")
    uvicorn.run(app, host="127.0.0.1", port=8400, log_level="info")
