# Contributing to Toolbox

This guide is for **Claude Code / Cowork sessions** and human developers building new tools for Toolbox.

## Architecture at a Glance

Toolbox is a local browser-based dashboard that auto-discovers Python tools and serves them at `http://localhost:8400`.

```
toolbox/
├── server.py              # FastAPI server — tool discovery, secrets API, execution
├── static/index.html      # Dashboard frontend (cyberpunk theme, vanilla JS)
├── secrets.json           # API keys (gitignored, shared via Dropbox)
├── requirements.txt       # Python deps (fastapi, uvicorn)
├── launch.command         # macOS double-click launcher
├── outputs/               # Tool run outputs (gitignored)
└── tools/
    ├── _TEMPLATE/         # Copy this to create a new tool
    ├── my_tool/
    │   ├── manifest.json  # Tool metadata + form fields
    │   ├── tool.py        # Python logic (run function)
    │   └── ui.html        # (optional) Custom interface
    └── ...
```

## How to Create a New Tool

### 1. Copy the template

```bash
cp -r tools/_TEMPLATE tools/my_new_tool
```

### 2. Edit `manifest.json`

```json
{
  "name": "My New Tool",
  "description": "One-sentence summary.",
  "category": "api",
  "icon": "api",
  "version": "1.0",
  "params": [
    {
      "name": "input_text",
      "type": "text",
      "label": "Input",
      "required": true,
      "placeholder": "Enter something…"
    }
  ]
}
```

**Param types:** `text`, `string`, `number`, `url`, `textarea`, `select`, `boolean`, `file`

**Icon/category values:** `general`, `media`, `api`, `data`, `file`, `text`, `image`, `audio`, `dev`, `ai`

### 3. Implement `tool.py`

```python
def run(params: dict, context: dict) -> dict:
    # Your logic here
    user_input = params.get("input_text", "")
    api_key = context["secrets"].get("OPENROUTER_API_KEY", "")

    return {
        "message": "Human-readable result summary",
        "log": ["Optional", "log", "lines"],
        "data": {"any": "structured data"},
        "files": [
            {"name": "output.txt", "url": f"{context['outputs_base_url']}/output.txt"}
        ]
    }
```

**The `context` dict contains:**

| Key | Description |
|-----|-------------|
| `run_id` | Unique ID for this execution |
| `tool_id` | Your tool's folder name |
| `output_dir` | Absolute path to write output files |
| `outputs_base_url` | URL path to serve those files |
| `base_dir` | Toolbox root directory |
| `timestamp` | ISO timestamp of run start |
| `secrets` | Dict of all stored API keys |

### 4. (Optional) Add a custom `ui.html`

For tools that need a richer interface than the auto-generated form, add `ui.html` to your tool folder. It gets loaded in an iframe with access to:

```javascript
// Wait for injection
window.addEventListener('message', (e) => {
  if (e.data.type === 'toolbox-ready') {
    // Toolbox API is now available
    const result = await Toolbox.run({ param1: "value" });
  }
});

// API reference:
Toolbox.run(params)        // Call your tool's Python backend
Toolbox.toolId             // Your tool's ID string
Toolbox.manifest           // Your manifest.json data
Toolbox.assetsUrl          // Base URL for your tool's static files
Toolbox.outputsUrl(runId)  // Base URL for run output files
```

### 5. Restart the server

The server re-discovers tools on every API call, so new tools appear automatically. If you changed Python dependencies, restart.

## Using Secrets / API Keys

Tools access shared API keys via `context["secrets"]`. Keys are stored in `secrets.json` (gitignored) and managed through the dashboard's SECRETS button.

Common pattern:

```python
def run(params, context):
    api_key = context["secrets"].get("OPENROUTER_API_KEY")
    if not api_key:
        return {"message": "Error: OPENROUTER_API_KEY not set. Add it in the Secrets panel."}
    # Use the key...
```

## Folder Naming Rules

- Folder names starting with `_` are **ignored** by the tool scanner (e.g., `_TEMPLATE`, `_archive`)
- Use `snake_case` for folder names
- The folder name becomes the tool's `id`

## Multi-Computer Sync

Toolbox lives in Dropbox, so it syncs automatically between machines. Key points:

- `secrets.json` is gitignored but syncs via Dropbox (both machines get the same API keys)
- `outputs/` is gitignored and local to each machine
- Tools, manifests, and custom UIs all sync via Dropbox
- Both machines need Python 3 + `pip install fastapi uvicorn`

## Dependencies

If your tool needs additional Python packages:

1. Import them in your `tool.py`
2. Add them to `requirements.txt` (or document in your manifest description)
3. The `launch.command` script handles initial install

For tool-specific deps that aren't needed globally, you can install them in your tool's `run()`:

```python
import subprocess
try:
    import cv2
except ImportError:
    subprocess.check_call(["pip3", "install", "opencv-python", "--break-system-packages"])
    import cv2
```

## For Claude Code / Cowork Sessions

When asked to build a new Toolbox tool:

1. Read this file first
2. Read `tools/_TEMPLATE/tool.py` for the full contract documentation
3. Create the tool folder in `tools/` (not in `_inbox/`)
4. Test by running `python3 -c "from tools.my_tool.tool import run; print(run({}, {'run_id':'test','output_dir':'/tmp','secrets':{}}))"` from the toolbox root
5. If the tool uses API keys, tell the user which secrets to add via the dashboard

## Running the Server

```bash
# From the toolbox directory:
python3 server.py

# Or double-click launch.command on macOS
```

Server runs at `http://localhost:8400`.
